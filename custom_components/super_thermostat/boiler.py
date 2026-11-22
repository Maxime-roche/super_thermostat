"""Gestion chaudière : somme des puissances, circulateur, brûleur."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .boiler_logic import burner_target, circulator_target, total_demand, water_band
from .const import (
    B_CIRCULATING, B_DISABLED, B_HEATING, B_IDLE, B_SAFETY, B_WATER_FAILURE,
    CONF_BURNER, CONF_CIRCULATOR, CONF_FRACTION_ENTITY, CONF_MIN_OFF, CONF_MIN_ON, CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICE, CONF_POST_RUN,
    CONF_SAFETY_MAX, CONF_SOURCES, CONF_USE_FRACTION, CONF_WATER_MAX_AGE, CONF_WATER_TEMP,
    DEFAULT_BOILER_OPTIONS, DEFAULT_OFFSET, DEFAULT_T_MAX, DEFAULT_T_MIN, DOMAIN,
    STORAGE_VERSION, TYPE_FRACTION,
)
from .helpers import read_number
from .notify import FailureNotifier

_LOGGER = logging.getLogger(__name__)
TICK = timedelta(seconds=30)


class BoilerController:
    """Boucle de la chaudière."""

    model = "Chaudière"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**DEFAULT_BOILER_OPTIONS, **entry.data, **entry.options}
        self.values = {"t_min": DEFAULT_T_MIN, "t_max": DEFAULT_T_MAX, "offset": DEFAULT_OFFSET}
        self.enabled = True
        self.dry_run = False
        self.use_fraction = bool(self.cfg.get(CONF_USE_FRACTION, True))

        self.demand = 0.0
        self.fraction = 100.0
        self.low = DEFAULT_T_MIN
        self.high = DEFAULT_T_MIN + DEFAULT_OFFSET
        self.water: float | None = None
        self.status = B_IDLE
        self.source_values: dict[str, float | None] = {}
        self.burner_on = False
        self.circulator_on = False

        self._burner_cmd: bool | None = None
        self._burner_since = 0.0
        self._circ_cmd = False
        self._zero_since: float | None = None

        self._notifier = FailureNotifier(
            hass, entry.title, self.cfg.get(CONF_NOTIFY_SERVICE), self.cfg.get(CONF_NOTIFY_MESSAGE)
        )
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

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
            "values": self.values,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "use_fraction": self.use_fraction,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, 10)

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.values.update({k: float(v) for k, v in data.get("values", {}).items() if k in self.values})
            self.enabled = bool(data.get("enabled", True))
            self.dry_run = bool(data.get("dry_run", False))
            if "use_fraction" in data:
                self.use_fraction = bool(data["use_fraction"])

    # -------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        watched = [*self.cfg.get(CONF_SOURCES, []), self.cfg[CONF_WATER_TEMP]]
        if self.cfg.get(CONF_FRACTION_ENTITY):
            watched.append(self.cfg[CONF_FRACTION_ENTITY])
        self._unsubs.append(
            async_track_state_change_event(self.hass, watched, self._on_event)
        )
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, TICK))
        unsub = async_at_started(self.hass, self._started)
        if unsub:
            self._unsubs.append(unsub)

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        self._evaluate()

    @callback
    def _on_event(self, _event: Event) -> None:
        self._evaluate()

    @callback
    def _on_tick(self, _now: Any) -> None:
        self._evaluate()

    # ----------------------------------------------------------- actionneurs
    def _actual(self, entity_id: str) -> bool | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state == "on"

    @callback
    def _drive(self, entity_id: str, want: bool) -> None:
        """Envoie l'ordre seulement si l'état réel est différent (jamais en simulation)."""
        if self.dry_run:
            return
        actual = self._actual(entity_id)
        if actual is None or actual == want:
            return
        service = "turn_on" if want else "turn_off"
        self.hass.async_create_task(
            self.hass.services.async_call(
                "homeassistant", service, {"entity_id": entity_id}, blocking=False
            )
        )

    # ------------------------------------------------------------- évaluation
    @callback
    def _evaluate(self) -> None:
        now = time.time()
        burner_entity = self.cfg[CONF_BURNER]
        circ_entity = self.cfg[CONF_CIRCULATOR]

        if self._burner_cmd is None:  # premier passage : on reprend l'état réel
            self._burner_cmd = bool(self._actual(burner_entity))
            self._circ_cmd = bool(self._actual(circ_entity))
            self._burner_since = 0.0

        # Fraction chaudière : lecture de l'entité configurée ou détection automatique
        frac_ent = self.cfg.get(CONF_FRACTION_ENTITY)
        frac_val = read_number(self.hass, frac_ent) if frac_ent else None
        if frac_val is not None:
            self.fraction = max(0.0, min(100.0, frac_val))
        else:
            found = False
            for e in self.hass.config_entries.async_entries(DOMAIN):
                if e.data.get(CONF_TYPE) == TYPE_FRACTION:
                    ctrl = getattr(e, "runtime_data", None)
                    if ctrl is not None and hasattr(ctrl, "fraction"):
                        self.fraction = float(ctrl.fraction)
                        found = True
                        break
            if not found:
                self.fraction = 100.0

        self.source_values = {
            e: read_number(self.hass, e) for e in self.cfg.get(CONF_SOURCES, [])
        }
        demand = total_demand(self.source_values.values())
        self.water = read_number(
            self.hass, self.cfg[CONF_WATER_TEMP], float(self.cfg[CONF_WATER_MAX_AGE]),
            temperature=True,
        )
        t_min, t_max, offset = (self.values[k] for k in ("t_min", "t_max", "offset"))
        ref_percent = self.fraction if self.use_fraction else demand
        self.low, self.high = water_band(ref_percent, t_min, t_max, offset)
        safety = float(self.cfg[CONF_SAFETY_MAX])

        if not self.enabled:
            demand = 0.0
            want_circ, self._zero_since = False, None
            want_burner = False
        else:
            want_circ, self._zero_since = circulator_target(
                demand=demand, currently_on=self._circ_cmd, zero_since=self._zero_since,
                now=now, post_run_s=float(self.cfg[CONF_POST_RUN]) * 60,
            )
            want_burner = want_circ and burner_target(
                demand=demand, water=self.water, low=self.low, high=self.high,
                safety_max=safety, currently_on=self._burner_cmd, since=self._burner_since,
                now=now, min_on_s=float(self.cfg[CONF_MIN_ON]) * 60,
                min_off_s=float(self.cfg[CONF_MIN_OFF]) * 60,
            )

        if want_burner != self._burner_cmd:
            self._burner_since = now
        self._burner_cmd, self._circ_cmd = want_burner, want_circ
        self.demand = demand

        # allumage : circulateur d'abord ; arrêt : brûleur d'abord
        if want_burner:
            self._drive(circ_entity, want_circ)
            self._drive(burner_entity, want_burner)
        else:
            self._drive(burner_entity, want_burner)
            self._drive(circ_entity, want_circ)

        self.burner_on, self.circulator_on = want_burner, want_circ
        if not self.enabled:
            self.status = B_DISABLED
        elif demand > 0 and self.water is None:
            self.status = B_WATER_FAILURE
        elif demand > 0 and self.water is not None and self.water >= safety:
            self.status = B_SAFETY
        elif want_burner:
            self.status = B_HEATING
        elif want_circ:
            self.status = B_CIRCULATING
        else:
            self.status = B_IDLE
        self._notifier.update({
            "water": (self.status == B_WATER_FAILURE, "sonde d'eau de la chaudière absente ou périmée"),
            "safety": (self.status == B_SAFETY, "température d'eau de sécurité atteinte : brûleur coupé"),
        })
        self._notify()

    # ------------------------------------------------------------ commandes UI
    def get_value(self, key: str) -> float:
        return self.values[key]

    async def async_set_value(self, key: str, value: float) -> None:
        self.values[key] = float(value)
        self._save()
        self._evaluate()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._save()
        self._evaluate()

    async def async_set_dry_run(self, value: bool) -> None:
        self.dry_run = value
        self._save()
        self._evaluate()

    async def async_set_use_fraction(self, value: bool) -> None:
        self.use_fraction = value
        self._save()
        self._evaluate()
