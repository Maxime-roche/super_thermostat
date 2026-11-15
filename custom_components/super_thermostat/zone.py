"""Contrôleur d'une zone : calcule un pourcentage de chauffe OU de froid.

Une zone ne pilote AUCUN appareil. Elle a deux consignes (chauffe / froid) :
la plage entre les deux est une zone morte. Elle publie :
  * puissance chauffe (%), puissance chaudière (%), puissance froid (%)
  * un statut, des coefficients appris, une entité climate.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later, async_track_state_change_event, async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .const import (
    ALLOWED_ALL, ALLOWED_COOL, ALLOWED_HEAT, CONF_ALLOWED, CONF_AUTOLEARN, CONF_CYCLE,
    CONF_FAIL_OFFSET, CONF_FAILSAFE_POWER, CONF_NOTIFY_MESSAGE, CONF_NOTIFY_SERVICE,
    CONF_VALVE_RETRY, CONF_FRACTION_ENTITY, CONF_LIMIT_CYCLES, CONF_STOVE, CONF_STOVE_DELAY,
    CONF_STOVE_THRESHOLD,
    CONF_MAX_SENSOR_AGE, CONF_MIN_POWER, CONF_OFFSET_NEXT_FULL, CONF_OUTDOOR_ENTITY,
    CONF_TEMP_ENTITY, CONF_THRESHOLD_HOT, CONF_VALVE_ALERT_MINUTES, CONF_VALVE_KEEP_OPEN,
    CONF_VALVE_LEVEL, CONF_VALVE_MIN_STEP, CONF_VALVE_NEVER_CLOSE, CONF_VALVE_OPEN_MAX,
    CONF_VALVE_OPEN_MIN, CONF_VALVE_POSITIONS, CONF_VALVE_PROPORTIONAL, CONF_VALVE_SOURCE,
    CONF_VALVES, CONF_WINDOW_RESTART_DELAY, CONF_WINDOW_STOP_DELAY, CONF_WINDOWS,
    CONF_ZONE_SEASON, COOL_OFF, DEFAULT_TARGET_COOL, DEFAULT_TARGET_HEAT,
    DEFAULT_ZONE_OPTIONS, DOMAIN, FIXED_PRESETS, PRESET_ALIASES, PRESET_DEFAULTS,
    STORAGE_VERSION, VALVE_ALERT_GAP, Z_ACTUATOR_FAILURE, Z_COOLING, Z_HEATING, Z_IDLE,
    Z_OFF, Z_SENSOR_FAILURE, Z_STOVE, Z_SUSPENDED,
)
from .engine import (
    COOL, HEAT, MANUAL_CONFIDENCE, ZoneParams, ZoneState, resolve_sense, run_cycle,
)
from .helpers import parse_preset_names, read_number
from .notify import FailureNotifier

_LOGGER = logging.getLogger(__name__)

PARAM_KEYS = ("offset_heat", "offset_cool", "delta_order")


class ZoneController:
    """Boucle de régulation d'une zone."""

    model = "Zone"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**DEFAULT_ZONE_OPTIONS, **entry.data, **entry.options}
        self.allowed: str = self.cfg.get(CONF_ALLOWED, ALLOWED_HEAT)
        self.params = ZoneParams(
            cycle_min=float(self.cfg[CONF_CYCLE]),
            min_power=float(self.cfg[CONF_MIN_POWER]),
            limit_cycles=bool(self.cfg[CONF_LIMIT_CYCLES]),
            autolearn=bool(self.cfg[CONF_AUTOLEARN]),
            threshold_hot=float(self.cfg[CONF_THRESHOLD_HOT]),
            offset_next_full=float(self.cfg[CONF_OFFSET_NEXT_FULL]),
            fail_offset_heat=float(self.cfg[CONF_FAIL_OFFSET]),
            fail_offset_cool=float(self.cfg[CONF_FAIL_OFFSET]),
        )
        self.state = ZoneState()
        self.hvac_mode: str = self.default_hvac_mode
        self.target_heat: float = DEFAULT_TARGET_HEAT
        self.target_cool: float = DEFAULT_TARGET_COOL
        # préréglages : {identifiant: nom affiché} et leurs deux consignes
        self.preset_names: dict[str, str] = parse_preset_names(FIXED_PRESETS)
        self.presets: dict[str, dict[str, float]] = {
            slug: dict(zip(("heat", "cool"), PRESET_DEFAULTS.get(slug, (DEFAULT_TARGET_HEAT, DEFAULT_TARGET_COOL))))
            for slug in self.preset_names
        }
        self.preset: str | None = None  # identifiant du préréglage actif
        self.sense: str | None = None  # HEAT / COOL / None
        self.status: str = Z_OFF
        self.power_heat: int = 0
        self.power_cool: int = 0
        self.suspended = False
        self.sensor_failure = False
        self.valve_target: int | None = None
        self.valve_alert = False
        self.stove_low = False  # poêle allumé et température sous le seuil depuis assez longtemps
        self._stove_low_since: float | None = None
        self._temp_good: tuple[float, float] | None = None  # (dernière valeur valide, date de son dernier rapport)
        self._valve_orders: dict[str, tuple[int, float]] = {}  # dernier ordre envoyé à chaque vanne
        self._notifier = FailureNotifier(
            hass, entry.title, self.cfg.get(CONF_NOTIFY_SERVICE), self.cfg.get(CONF_NOTIFY_MESSAGE)
        )
        self.valve_report: dict[str, dict[str, Any]] = {}
        self._drift: dict[str, dict[str, Any]] = {}

        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsub_cycle: CALLBACK_TYPE | None = None
        self._unsub_stop: CALLBACK_TYPE | None = None
        self._unsub_restart: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ modes
    @property
    def hvac_modes(self) -> list[str]:
        if self.allowed == ALLOWED_ALL:
            return ["off", "heat", "cool", "heat_cool"]
        return ["off", self.allowed]

    @property
    def default_hvac_mode(self) -> str:
        return {ALLOWED_HEAT: "heat", ALLOWED_COOL: "cool"}.get(self.allowed, "heat_cool")

    @property
    def has_heat(self) -> bool:
        return self.allowed in (ALLOWED_HEAT, ALLOWED_ALL)

    @property
    def has_cool(self) -> bool:
        return self.allowed in (ALLOWED_COOL, ALLOWED_ALL)

    @property
    def problem(self) -> bool:
        return self.status in (Z_SENSOR_FAILURE, Z_ACTUATOR_FAILURE)

    @property
    def fraction(self) -> float:
        """Part de la chaleur confiée à la chaudière (100 % si non configurée/indisponible)."""
        value = read_number(self.hass, self.cfg.get(CONF_FRACTION_ENTITY))
        return 100.0 if value is None else max(0.0, min(100.0, value))

    @property
    def power_boiler(self) -> int:
        return int(round(self.power_heat * self.fraction / 100))

    @property
    def current_temperature(self) -> float | None:
        return read_number(self.hass, self.cfg.get(CONF_TEMP_ENTITY), temperature=True)

    def _fresh_temperature(self) -> float | None:
        """Température de la pièce, avec tolérance aux coupures brèves de la sonde.

        On retient la dernière valeur numérique et la date de son dernier rapport (le plus récent de
        last_updated / last_reported). Un état « indisponible » de quelques minutes ne déclenche pas
        de défaillance : celle-ci n'apparaît que si le dernier rapport valide a plus de « âge max de
        la sonde ». Elle disparaît dès qu'un nouveau rapport arrive.
        """
        entity = self.cfg.get(CONF_TEMP_ENTITY)
        value = read_number(self.hass, entity, temperature=True)
        state = self.hass.states.get(entity) if entity else None
        if value is not None and state is not None:
            reported = max(state.last_updated, getattr(state, "last_reported", state.last_updated))
            self._temp_good = (value, reported.timestamp())
        if self._temp_good is None:
            return None
        if time.time() - self._temp_good[1] > float(self.cfg[CONF_MAX_SENSOR_AGE]) * 60:
            return None
        return self._temp_good[0]

    @property
    def sensor_age_minutes(self) -> float | None:
        """Ancienneté du dernier rapport valide de la sonde (minutes)."""
        self._fresh_temperature()
        if self._temp_good is None:
            return None
        return round((time.time() - self._temp_good[1]) / 60, 1)

    @property
    def windows(self) -> list[str]:
        return list(self.cfg.get(CONF_WINDOWS) or [])

    @property
    def cooling_disabled(self) -> bool:
        return self.target_cool >= COOL_OFF

    def _summer(self) -> bool | None:
        """True = été (froid), False = hiver (chauffe), None = pas d'entité saison."""
        entity = self.cfg.get(CONF_ZONE_SEASON)
        if not entity:
            return None
        state = self.hass.states.get(entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state == "on"

    # -------------------------------------------------------------- listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        @callback
        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ---------------------------------------------------------------- storage
    def _data(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "hvac_mode": self.hvac_mode,
            "target_heat": self.target_heat,
            "target_cool": self.target_cool,
            "preset": self.preset,
            "presets": self.presets,
            "params": {k: getattr(self.params, k) for k in PARAM_KEYS},
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, 10)

    async def _load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self.state = ZoneState.from_dict(data.get("state"))
        if data.get("hvac_mode") in self.hvac_modes:
            self.hvac_mode = data["hvac_mode"]
        # v0.3 n'avait qu'une consigne : elle devient la consigne de chauffe
        self.target_heat = float(data.get("target_heat", data.get("target", self.target_heat)))
        self.target_cool = float(data.get("target_cool", self.target_cool))
        # anciens noms (Jour, Nuit, Parti) -> noms standards, en gardant les consignes réglées
        legacy = lambda slug: PRESET_ALIASES.get(slug, slug)  # noqa: E731
        if legacy(data.get("preset") or "") in self.presets:
            self.preset = legacy(data["preset"])
        for old_slug, values in (data.get("presets") or {}).items():
            slug = legacy(old_slug)
            if slug in self.presets and isinstance(values, dict):
                self.presets[slug].update({k: float(v) for k, v in values.items() if k in ("heat", "cool")})
        for key, value in (data.get("params") or {}).items():
            if key in PARAM_KEYS:
                setattr(self.params, key, float(value))

    # -------------------------------------------------------------- lifecycle
    async def async_load(self) -> None:
        await self._load()

    async def async_start(self) -> None:
        watched = self.windows
        if watched:
            self._unsubs.append(async_track_state_change_event(self.hass, watched, self._on_window_event))
        if self.cfg.get(CONF_FRACTION_ENTITY):
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.cfg[CONF_FRACTION_ENTITY]], self._on_fraction_event
                )
            )
        if self.cfg.get(CONF_VALVE_SOURCE):
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.cfg[CONF_VALVE_SOURCE]], self._on_fraction_event
                )
            )
        pairs = self.valve_pairs
        if pairs:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [e for pair in pairs for e in pair], self._on_valve_event
                )
            )
        if self.cfg.get(CONF_STOVE):
            self._unsubs.append(
                async_track_state_change_event(self.hass, [self.cfg[CONF_STOVE]], self._on_stove_event)
            )
        # une vérification par minute : sonde, poêle, vannes (ordres à renvoyer), position réelle, notifications
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        if self.cfg.get(CONF_ZONE_SEASON):
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.cfg[CONF_ZONE_SEASON]], self._on_season_event
                )
            )
        unsub = async_at_started(self.hass, self._started)
        if unsub:
            self._unsubs.append(unsub)

    @callback
    def _on_fraction_event(self, _event: Event) -> None:
        self._refresh_valves()
        self._notify()

    # ---- poêle à bois ----
    def _stove_on(self) -> bool:
        entity = self.cfg.get(CONF_STOVE)
        return bool(entity) and self.hass.states.is_state(entity, "on")

    @callback
    def _on_stove_event(self, _event: Event) -> None:
        self._check_stove()
        self._recalc_now()  # pause ou reprise de la zone, vannes

    @callback
    def _check_stove(self, _now: Any = None) -> None:
        """Poêle allumé : la zone est en pause. Sous le seuil depuis assez longtemps : on anticipe."""
        if not self.cfg.get(CONF_STOVE):
            return
        now = time.time()
        temp = self.current_temperature
        if self._stove_on() and temp is not None and temp < float(self.cfg.get(CONF_STOVE_THRESHOLD, 21)):
            if self._stove_low_since is None:
                self._stove_low_since = now
        else:
            self._stove_low_since = None
        delay = float(self.cfg.get(CONF_STOVE_DELAY, 10)) * 60
        low = self._stove_low_since is not None and now - self._stove_low_since >= delay
        if low != self.stove_low:
            self.stove_low = low
            self._drive_valves()  # on ouvre déjà les vannes (ou on les referme) sans relancer le thermostat
            self._notify()

    @callback
    def _check_sensor(self) -> None:
        """Défaillance de sonde : détectée et levée à la minute, sans attendre la fin du cycle."""
        if self.hvac_mode == "off" or self.suspended or self._stove_on():
            return
        if (self._fresh_temperature() is None) != self.sensor_failure:
            self._recalc_now()

    @callback
    def _tick(self, _now: Any = None) -> None:
        self._check_sensor()
        self._check_stove()
        self._check_valves()
        self._drive_valves()
        self._update_failures()

    # ---- notifications de défaillance ----
    @callback
    def _update_failures(self) -> None:
        valves = [v for v, item in self.valve_report.items() if item.get("alert")]
        self._notifier.update({
            "sensor": (self.sensor_failure, "sonde de température absente ou périmée"),
            "actuator": (self.state.actuator_failure, "le chauffage ne chauffe pas (la température s'éloigne de la consigne)"),
            "valve": (self.valve_alert, "vanne(s) qui ne suivent pas leur consigne : " + ", ".join(valves)),
        })

    @callback
    def _on_season_event(self, _event: Event) -> None:
        self._recalc_now()

    @callback
    def _on_valve_event(self, _event: Event) -> None:
        self._check_valves()

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        self._check_valves()
        self._evaluate_windows()
        self.hass.async_create_task(self.async_run_cycle())

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for name in ("_unsub_cycle", "_unsub_stop", "_unsub_restart"):
            unsub = getattr(self, name)
            if unsub:
                unsub()
                setattr(self, name, None)
        await self._store.async_save(self._data())

    # ----------------------------------------------------------------- cycles
    @callback
    def _schedule_next(self) -> None:
        if self._unsub_cycle:
            self._unsub_cycle()
        self._unsub_cycle = async_call_later(
            self.hass, self.params.cycle_min * 60, self._cycle_cb
        )

    async def _cycle_cb(self, _now: Any) -> None:
        await self.async_run_cycle()

    def _apply(self, status: str, heat: int = 0, cool: int = 0) -> None:
        self.status, self.power_heat, self.power_cool = status, heat, cool
        self._refresh_valves()
        self._update_failures()
        self._save()
        self._notify()

    # ---- vannes thermostatiques ----
    def _other_zones(self) -> list["ZoneController"]:
        zones: list[ZoneController] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            ctrl = getattr(entry, "runtime_data", None)
            if entry.entry_id != self.entry.entry_id and isinstance(ctrl, ZoneController):
                zones.append(ctrl)
        return zones

    def _other_zone_demand(self) -> bool:
        return any(zone.power_boiler > 0 for zone in self._other_zones())

    def _valve_target(self) -> int | None:
        """Ouverture voulue (0-100) ; None = ne rien envoyer (on garde l'ouverture actuelle).

        La demande est la valeur (0-100 %) de l'entité choisie — par défaut la puissance chaudière
        de la zone. Dès qu'elle est positive :
          * ouverture proportionnelle : 1 % -> ouverture min, 100 % -> ouverture max ;
          * sinon : ouverture fixe (100 % si le champ est vide).
        Quand elle tombe à 0 : ouverture minimale (« ne jamais fermer »), sinon on garde l'ouverture
        tant qu'aucune autre zone ne demande, sinon fermeture.
        """
        low = float(self.cfg.get(CONF_VALVE_OPEN_MIN, 15))
        if self._stove_on():
            # poêle allumé : vannes à 0 % sans aucune contrainte (ni « jamais fermer », ni « garder ouvert »),
            # sauf anticipation (température basse) : on les ouvre déjà, le thermostat reste en pause
            if not self.stove_low:
                return 0
            if not self.cfg.get(CONF_VALVE_PROPORTIONAL, True):
                level = self.cfg.get(CONF_VALVE_LEVEL)
                return int(round(100 if level in (None, "") else float(level)))
            return int(round(float(self.cfg.get(CONF_VALVE_OPEN_MAX, 70))))
        if self.hvac_mode == "off":
            demand: float | None = 0.0
        else:
            source = self.cfg.get(CONF_VALVE_SOURCE)
            demand = read_number(self.hass, source) if source else float(self.power_boiler)
        if demand is None:
            return None  # source indisponible : on ne touche à rien
        if demand > 0:
            if not self.cfg.get(CONF_VALVE_PROPORTIONAL, True):
                level = self.cfg.get(CONF_VALVE_LEVEL)
                return int(round(100 if level in (None, "") else float(level)))
            high = float(self.cfg.get(CONF_VALVE_OPEN_MAX, 70))
            level = min(max(demand, 1.0), 100.0)
            return int(round(low + (high - low) * (level - 1) / 99))
        if self.cfg.get(CONF_VALVE_NEVER_CLOSE, False):
            return int(round(low))
        if self.cfg.get(CONF_VALVE_KEEP_OPEN, True) and not self._other_zone_demand():
            return None
        return 0

    # ---- suivi de la position réelle des vannes ----
    @property
    def valve_pairs(self) -> list[tuple[str, str]]:
        """(vanne, position réelle) appariées dans l'ordre des deux listes."""
        valves = list(self.cfg.get(CONF_VALVES) or [])
        positions = list(self.cfg.get(CONF_VALVE_POSITIONS) or [])
        return list(zip(valves, positions))

    @callback
    def _check_valves(self, _now: Any = None) -> None:
        """Compare la consigne envoyée à chaque vanne et sa position réelle.

        Une vanne « ne suit pas » quand l'écart dépasse 10 % pendant plus de X minutes (réglable,
        0 = désactivé). Le délai repart de zéro à chaque nouvel ordre, et rien n'est évalué en
        froid / en été (une vanne en mode été ne suit plus sa consigne).
        """
        pairs = self.valve_pairs
        if not pairs:
            return
        now = time.time()
        limit = float(self.cfg.get(CONF_VALVE_ALERT_MINUTES, 30)) * 60
        skip = self.hvac_mode == "cool" or self.sense == COOL or self._summer() is True
        report: dict[str, dict[str, Any]] = {}
        for valve, position_entity in pairs:
            setpoint = read_number(self.hass, valve)
            position = read_number(self.hass, position_entity)
            record = self._drift.setdefault(valve, {"since": None, "setpoint": None})
            gap = None if setpoint is None or position is None else abs(position - setpoint)
            drifting = not skip and gap is not None and gap > VALVE_ALERT_GAP
            if not drifting:
                record["since"] = None
            elif record["since"] is None or record["setpoint"] != setpoint:
                record["since"] = now  # nouvel ordre : on laisse le temps à la vanne
            record["setpoint"] = setpoint
            minutes = 0 if record["since"] is None else (now - record["since"]) / 60
            report[valve] = {
                "position_entity": position_entity,
                "setpoint": setpoint,
                "position": position,
                "gap": None if gap is None else round(gap),
                "drift_minutes": int(minutes),
                "alert": bool(limit > 0 and record["since"] is not None and now - record["since"] >= limit),
            }
        alert = any(item["alert"] for item in report.values())
        stable = lambda r: {k: {f: v for f, v in item.items() if f != "drift_minutes"} for k, item in r.items()}  # noqa: E731
        changed = alert != self.valve_alert or stable(report) != stable(self.valve_report)
        if alert and not self.valve_alert:
            _LOGGER.warning(
                "%s : vanne(s) qui ne suivent pas leur consigne : %s",
                self.entry.title, [v for v, item in report.items() if item["alert"]],
            )
        self.valve_alert, self.valve_report = alert, report
        if changed:
            self._notify()

    @callback
    def _refresh_valves(self) -> None:
        """Recalcule les vannes de cette zone et des autres (leur décision dépend de la nôtre)."""
        self._drive_valves()
        for zone in self._other_zones():
            zone._drive_valves()

    @callback
    def _drive_valves(self) -> None:
        """Pilote les vannes, en hiver seulement.

        Rien n'est envoyé en froid ni en été, ni si l'écart avec l'ouverture actuelle est inférieur
        à l'écart minimal (sauf pour fermer complètement) : les vannes sur pile n'aiment pas les
        écritures inutiles.
        """
        valves = self.cfg.get(CONF_VALVES) or []
        if not valves or self.hvac_mode == "cool" or self.sense == COOL or self._summer() is True:
            self.valve_target = None
            return
        value = self._valve_target()
        self.valve_target = value
        if value is None:
            return
        step = float(self.cfg.get(CONF_VALVE_MIN_STEP, 5))
        retry = float(self.cfg.get(CONF_VALVE_RETRY, 30)) * 60
        now = time.time()
        for entity in valves:
            state = self.hass.states.get(entity)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            try:
                diff = abs(round(float(state.state)) - value)
                if diff == 0 or (diff < step and value != 0):
                    self._valve_orders.pop(entity, None)  # la vanne a suivi : rien à renvoyer
                    continue
            except ValueError:
                pass
            sent = self._valve_orders.get(entity)
            if sent and sent[0] == value and now - sent[1] < retry:
                continue  # ordre déjà envoyé : certaines vannes mettent ~30 min à répondre
            self._valve_orders[entity] = (value, now)
            domain = entity.split(".", 1)[0]  # number ou input_number
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain, "set_value", {"entity_id": entity, "value": value}, blocking=False
                )
            )

    async def async_run_cycle(self) -> None:
        """Un cycle de calcul. Reprogramme aussi le suivant."""
        self._schedule_next()

        if self.hvac_mode == "off":
            self.state.interrupt()
            self.sense = None
            self.sensor_failure = False
            self._apply(Z_OFF)
            return
        if self._stove_on():
            # poêle allumé : zone en pause (mode et préréglage conservés, rien n'est appris)
            self.state.interrupt()
            self.sense = None
            self.sensor_failure = False
            self._apply(Z_STOVE)
            return
        if self.suspended:
            self.state.interrupt()
            self.sensor_failure = False
            self._apply(Z_SUSPENDED)
            return

        temp_in = self._fresh_temperature()
        if temp_in is None:
            self.state.interrupt()
            self.sensor_failure = True
            _LOGGER.warning("%s : sonde intérieure absente ou périmée", self.entry.title)
            failsafe = int(self.cfg[CONF_FAILSAFE_POWER])
            heating = self.hvac_mode in ("heat", "heat_cool")
            self._apply(Z_SENSOR_FAILURE, heat=failsafe if heating else 0)
            return
        self.sensor_failure = False
        temp_out = read_number(self.hass, self.cfg.get(CONF_OUTDOOR_ENTITY), temperature=True)

        # sens actif + consigne correspondante (la plage entre les deux = zone morte)
        self.sense = resolve_sense(
            self.hvac_mode, self._summer(), temp_in, self.target_heat, self.target_cool, self.sense
        )
        if self.sense is None:
            self.state.interrupt()
            self._apply(Z_IDLE)
            return
        self.params.heat_allowed = self.sense == HEAT
        self.params.cool_allowed = self.sense == COOL
        self.params.direction = 1 if self.sense == HEAT else -1
        consigne = self.target_heat if self.sense == HEAT else self.target_cool

        result = run_cycle(self.params, self.state, time.time(), consigne, temp_in, temp_out)
        if result.learned:
            _LOGGER.debug("%s : apprentissage %s", self.entry.title, result.learned)

        if result.state == HEAT:
            status, heat, cool = Z_HEATING, result.power, 0
        elif result.state == COOL:
            status, heat, cool = Z_COOLING, 0, result.power
        else:
            status, heat, cool = Z_IDLE, 0, 0
        if self.state.actuator_failure:
            status = Z_ACTUATOR_FAILURE
        self._apply(status, heat, cool)

    @callback
    def _recalc_now(self) -> None:
        self.hass.async_create_task(self.async_run_cycle())

    # ----------------------------------------------------------------- fenêtres
    def _windows_open(self) -> bool:
        return any(self.hass.states.is_state(w, "on") for w in self.windows)

    @callback
    def _on_window_event(self, _event: Event) -> None:
        self._evaluate_windows()

    @callback
    def _cancel(self, name: str) -> None:
        unsub = getattr(self, name)
        if unsub:
            unsub()
            setattr(self, name, None)

    @callback
    def _evaluate_windows(self) -> None:
        if self._windows_open():
            self._cancel("_unsub_restart")
            if not self.suspended and self._unsub_stop is None and self.hvac_mode != "off":
                delay = float(self.cfg[CONF_WINDOW_STOP_DELAY]) * 60
                if delay <= 0:
                    self._suspend()
                else:
                    self._unsub_stop = async_call_later(self.hass, delay, self._stop_cb)
        else:
            self._cancel("_unsub_stop")
            if self.suspended and self._unsub_restart is None:
                delay = float(self.cfg[CONF_WINDOW_RESTART_DELAY]) * 60
                if delay <= 0:
                    self._resume()
                else:
                    self._unsub_restart = async_call_later(self.hass, delay, self._restart_cb)

    @callback
    def _stop_cb(self, _now: Any) -> None:
        self._unsub_stop = None
        if self._windows_open():
            self._suspend()

    @callback
    def _restart_cb(self, _now: Any) -> None:
        self._unsub_restart = None
        if not self._windows_open():
            self._resume()

    @callback
    def _suspend(self) -> None:
        self.suspended = True
        self.state.interrupt()
        self._apply(Z_SUSPENDED)

    @callback
    def _resume(self) -> None:
        self.suspended = False
        self._recalc_now()

    # ------------------------------------------------------------ commandes UI
    async def async_set_hvac_mode(self, mode: str) -> None:
        if mode not in self.hvac_modes:
            return
        self.hvac_mode = mode
        self._evaluate_windows()
        await self.async_run_cycle()

    async def async_set_targets(
        self, heat: float | None = None, cool: float | None = None, *, keep_preset: bool = False
    ) -> None:
        """Fixe la consigne de chauffe et/ou de froid (la chauffe ne dépasse jamais le froid)."""
        changed = False
        if heat is not None and float(heat) != self.target_heat:
            self.target_heat, changed = float(heat), True
            if self.target_heat > self.target_cool:
                self.target_cool = self.target_heat
        if cool is not None and float(cool) != self.target_cool:
            self.target_cool, changed = float(cool), True
            if self.target_cool < self.target_heat:
                self.target_heat = self.target_cool
        if not keep_preset:
            self.preset = None
        self._save()
        self._notify()
        if changed:
            await self.async_run_cycle()

    async def async_set_preset(self, preset: str | None) -> None:
        """Applique un préréglage (identifiant ou nom affiché) : ses deux consignes."""
        if preset in (None, "none"):
            self.preset = None
            self._save()
            self._notify()
            return
        # accepte l'identifiant, le nom affiché ou un alias (« Jour » -> home)
        slug = next(
            (s for s in (*parse_preset_names(preset), preset) if s in self.preset_names), None
        )
        if slug is None:
            return
        self.preset = slug
        values = self.presets[slug]
        await self.async_set_targets(values["heat"], values["cool"], keep_preset=True)
        self._save()
        self._notify()

    @staticmethod
    def _split_preset_key(key: str) -> tuple[str, str]:
        prefix, kind = key.rsplit("_", 1)
        return prefix.removeprefix("preset_"), kind

    def get_value(self, key: str) -> float:
        if key.startswith("coeff_"):
            return float(getattr(self.state, key))
        if key.startswith("preset_"):
            slug, kind = self._split_preset_key(key)
            return self.presets[slug][kind]
        return float(getattr(self.params, key))

    def learn_count(self, key: str) -> int | None:
        if key.startswith("coeff_"):
            return int(getattr(self.state, key.replace("coeff_", "n_", 1)))
        return None

    async def async_set_value(self, key: str, value: float) -> None:
        if key.startswith("coeff_"):
            setattr(self.state, key, float(value))
            setattr(self.state, key.replace("coeff_", "n_", 1), MANUAL_CONFIDENCE)
        elif key.startswith("preset_"):
            slug, kind = self._split_preset_key(key)
            self.presets[slug][kind] = float(value)
            if self.preset == slug:
                await self.async_set_targets(
                    self.presets[slug]["heat"], self.presets[slug]["cool"], keep_preset=True
                )
        else:
            setattr(self.params, key, float(value))
        self._save()
        self._notify()
        if not key.startswith("preset_"):
            await self.async_run_cycle()  # coefficient / offset / delta : effet immédiat

    async def async_reset_learning(self) -> None:
        self.state.reset_learning()
        self._save()
        self._notify()
        await self.async_run_cycle()
