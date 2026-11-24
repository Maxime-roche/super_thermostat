"""Zone combinée chaudière (base lente) + climatisation (appoint rapide).

Deux régulations indépendantes, chacune avec ses réglages (onglets d'options dédiés) :
  * Chaudière : base lente asservie à la météo extérieure (gain x pertes x fraction),
    température lissée (moyenne glissante), hystérésis, temps minimaux allumée/éteinte,
    réévaluée à sa propre période. Apprentissage doux du gain à chaque fin de cycle.
  * Clim : boucle rapide, température peu ou pas lissée, hystérésis, temps minimaux,
    apprentissage de sa seule réactivité. Maintenue allumée tant que la fraction chaudière
    dépasse le seuil X (avec relâchement à X - 5 %).
Les temps minimaux l'emportent toujours sur l'hystérésis.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_CYCLE, CONF_FAILSAFE_POWER, CONF_HY_A_CYCLE, CONF_HY_A_FORCE_FRACTION,
    CONF_HY_A_FORCE_POWER, CONF_HY_A_HYST_OFF, CONF_HY_A_HYST_ON, CONF_HY_A_MIN_OFF,
    CONF_HY_A_MIN_ON, CONF_HY_A_MIN_POWER, CONF_HY_A_SMOOTH, CONF_HY_B_CYCLE,
    CONF_HY_B_AUTOLEARN, CONF_HY_B_HYST_OFF, CONF_HY_B_HYST_ON, CONF_HY_B_MIN_OFF, CONF_HY_B_MIN_ON,
    CONF_HY_B_SMOOTH, CONF_MIN_POWER, CONF_OUTDOOR_ENTITY, DEFAULT_HYBRID_OPTIONS,
    HY_FORCE_RELEASE_GAP, Z_COOLING, Z_HEATING, Z_IDLE, Z_OFF, Z_SENSOR_FAILURE, Z_SUSPENDED,
)
from .engine import COOL, HEAT, resolve_sense
from .helpers import read_number
from .zone import ZoneController

_LOGGER = logging.getLogger(__name__)

DEFAULT_COEFF_AC = 15.0       # gain réactif clim initial (%/°C)
DEFAULT_GAIN_BOILER = 5.0     # gain base chaudière initial (%/°C)
MAX_AC_LEARN_COUNT = 50


class ZoneHybridController(ZoneController):
    """Zone combinant une base lente (chaudière) et un appoint rapide (climatisation)."""

    model = "Zone Chaudière + Clim"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        for key, value in DEFAULT_HYBRID_OPTIONS.items():
            self.cfg.setdefault(key, value)
        # anciennes entrées : l'ancien « cycle » devient le cycle de la clim (pas de migration)
        raw = {**entry.data, **entry.options}
        ac_cycle = raw.get(CONF_HY_A_CYCLE, raw.get(CONF_CYCLE, DEFAULT_HYBRID_OPTIONS[CONF_HY_A_CYCLE]))
        self.cfg[CONF_HY_A_CYCLE] = ac_cycle
        self.params.cycle_min = float(ac_cycle)  # timer de base + fenêtre d'apprentissage clim

        self.coeff_ac: float = DEFAULT_COEFF_AC
        self.n_ac: int = 1
        self.offset_ac: float = 0.0
        self.gain_boiler: float = DEFAULT_GAIN_BOILER
        self.n_boiler_days: int = 0
        self._power_boiler_hybrid: int = 0
        self.power_ac: int = 0
        self._boiler_learned_today = False
        self._last_ac_temp_in: float | None = None
        self._last_ac_order: float | None = None
        self._last_ac_power: int = 0
        # régulation : état allumé/éteint de chaque boucle
        self._b_on = False
        self._b_since = 0.0
        self._b_last_eval = 0.0
        self._b_last_order: float | None = None
        self._a_on = False
        self._a_since = 0.0
        self.ac_forced = False
        self._buf_b: deque[tuple[float, float]] = deque()
        self._buf_a: deque[tuple[float, float]] = deque()

    def _f(self, key: str) -> float:
        return float(self.cfg[key])

    # ---- Override : power_boiler est géré en propre ici (pas fraction * power_heat) ----
    @property
    def power_boiler_request(self) -> int:  # type: ignore[override]
        return self._power_boiler_hybrid

    @power_boiler_request.setter
    def power_boiler_request(self, value: int) -> None:
        self._power_boiler_hybrid = int(value)

    # ---------------------------------------------------------------- storage
    def _data(self) -> dict[str, Any]:
        data = super()._data()
        data.update({
            "coeff_ac": self.coeff_ac,
            "n_ac": self.n_ac,
            "offset_ac": self.offset_ac,
            "gain_boiler": self.gain_boiler,
            "n_boiler_days": self.n_boiler_days,
            "last_ac_temp_in": self._last_ac_temp_in,
            "last_ac_order": self._last_ac_order,
            "last_ac_power": self._last_ac_power,
            "b_on": self._b_on, "b_since": self._b_since,
            "a_on": self._a_on, "a_since": self._a_since,
        })
        return data

    async def _load(self) -> None:
        await super()._load()
        data = await self._store.async_load()
        if not data:
            return
        self.coeff_ac = float(data.get("coeff_ac", self.coeff_ac))
        self.n_ac = int(data.get("n_ac", self.n_ac))
        self.offset_ac = float(data.get("offset_ac", self.offset_ac))
        self.gain_boiler = float(data.get("gain_boiler", self.gain_boiler))
        self.n_boiler_days = int(data.get("n_boiler_days", self.n_boiler_days))
        self._last_ac_temp_in = data.get("last_ac_temp_in")
        self._last_ac_order = data.get("last_ac_order")
        self._last_ac_power = int(data.get("last_ac_power", 0))
        self._b_on = bool(data.get("b_on", False))
        self._b_since = float(data.get("b_since", 0.0))
        self._a_on = bool(data.get("a_on", False))
        self._a_since = float(data.get("a_since", 0.0))

    # -------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        await super().async_start()
        self._unsubs.append(
            async_track_time_change(self.hass, self._daily_recalibration, hour=0, minute=10, second=0)
        )

    # ------------------------------------------------- compteur de jours d'apprentissage
    @callback
    def _daily_recalibration(self, _now: Any = None) -> None:
        """À 00:10 : compte un jour d'apprentissage si le gain chaudière a bougé dans la journée."""
        if self._boiler_learned_today:
            self.n_boiler_days += 1
            self._boiler_learned_today = False
            self._save()
            self._notify()

    # ------------------------------------------------------ outils régulation
    @staticmethod
    def _smooth(buf: deque, window_min: float, now: float, temp: float) -> float:
        """Moyenne glissante sur « window_min » minutes (0 = température instantanée)."""
        if window_min <= 0:
            buf.clear()
            return temp
        buf.append((now, temp))
        limit = now - window_min * 60
        while len(buf) > 1 and buf[0][0] < limit:
            buf.popleft()
        return sum(t for _, t in buf) / len(buf)

    @staticmethod
    def _want(on: bool, diff: float, h_on: float, h_off: float) -> bool:
        """Hystérésis : allume si diff >= h_on, éteint si diff <= -h_off (diff = consigne - T)."""
        if on:
            return diff > -h_off
        return diff >= max(h_on, 0.01)

    @staticmethod
    def _gate(on: bool, since: float, now: float, want: bool, min_on: float, min_off: float):
        """Temps minimaux : ils l'emportent sur l'hystérésis."""
        if want == on:
            return on, since
        if on and now - since < min_on * 60:
            return on, since
        if not on and now - since < min_off * 60:
            return on, since
        return want, now

    def _reset_regulation(self) -> None:
        self._b_on = self._a_on = self.ac_forced = False
        self._b_since = self._a_since = 0.0
        self._b_last_eval = 0.0
        self._b_last_order = None
        self._buf_b.clear()
        self._buf_a.clear()

    def _stop_all(self) -> None:
        self.power_boiler_request = 0
        self.power_ac = 0
        self._last_ac_power = 0
        self._reset_regulation()

    # ----------------------------------------------------------------- cycles
    async def async_run_cycle(self) -> None:
        """Cycle de la boucle rapide ; la chaudière se réévalue à sa propre période."""
        self._schedule_next()

        if self.hvac_mode == "off":
            self.state.interrupt()
            self.sense = None
            self.sensor_failure = False
            self._stop_all()
            self._apply(Z_OFF)
            return

        if self.suspended:
            self.state.interrupt()
            self.sensor_failure = False
            self._stop_all()
            self._apply(Z_SUSPENDED)
            return

        temp_in = self._fresh_temperature()
        if temp_in is None:
            self.state.interrupt()
            self.sensor_failure = True
            _LOGGER.warning("%s : sonde intérieure absente ou périmée", self.entry.title)
            failsafe = int(self.cfg[CONF_FAILSAFE_POWER])
            heating = self.hvac_mode in ("heat", "heat_cool")
            self._stop_all()
            self.power_boiler_request = failsafe if heating else 0
            self._apply(Z_SENSOR_FAILURE, heat=self.power_boiler_request)
            return

        self.sensor_failure = False
        temp_out = read_number(self.hass, self.cfg.get(CONF_OUTDOOR_ENTITY), temperature=True)
        fraction = self.fraction
        now = time.time()

        self.sense = resolve_sense(
            self.hvac_mode, self._summer(), temp_in, self.target_heat, self.target_cool, self.sense
        )
        if self.sense is None:
            self.state.interrupt()
            self._stop_all()
            self._apply(Z_IDLE)
            return

        if self.sense == HEAT:
            consigne = self.target_heat

            # --- Apprentissage continu de la clim (réactivité propre) ---
            if (
                self.params.autolearn
                and self._last_ac_temp_in is not None
                and self._last_ac_order == consigne
                and 0 < self._last_ac_power < 100
            ):
                delta_obs = temp_in - self._last_ac_temp_in
                if delta_obs > 0.05:
                    cycle_ratio = max(0.5, float(self.params.cycle_min) / 10.0)
                    estimate = (
                        self.coeff_ac
                        * (self._last_ac_order - self._last_ac_temp_in)
                        / (delta_obs * cycle_ratio)
                    )
                    estimate = min(max(estimate, self.coeff_ac / 2.0), self.coeff_ac * 2.0)
                    self.coeff_ac = round((self.coeff_ac * self.n_ac + estimate) / (self.n_ac + 1), 2)
                    self.n_ac = min(self.n_ac + 1, MAX_AC_LEARN_COUNT)

            t_b = self._smooth(self._buf_b, self._f(CONF_HY_B_SMOOTH), now, temp_in)
            t_a = self._smooth(self._buf_a, self._f(CONF_HY_A_SMOOTH), now, temp_in)

            # --- A. Chaudière (base lente) : réévaluée à sa propre période ---
            due = (
                self._b_last_eval == 0.0
                or self._b_last_order != consigne
                or now - self._b_last_eval >= self._f(CONF_HY_B_CYCLE) * 60 * 0.9
            )
            if due:
                diff_b = consigne - t_b
                # apprentissage doux à chaque fin de cycle (si l'auto-apprentissage est coché)
                if (
                    bool(self.cfg[CONF_HY_B_AUTOLEARN]) and self._b_on and self._b_last_eval != 0.0
                    and self._b_last_order == consigne and abs(diff_b) > 0.15
                ):
                    step = min(0.5, 0.2 * abs(diff_b)) * min(1.0, self._f(CONF_HY_B_CYCLE) / 1440.0)
                    self.gain_boiler = round(
                        min(30.0, self.gain_boiler + step) if diff_b > 0 else max(0.5, self.gain_boiler - step), 3
                    )
                    self._boiler_learned_today = True
                    _LOGGER.debug("%s : apprentissage chaudière -> gain %.3f (écart %+.2f °C)",
                                  self.entry.title, self.gain_boiler, diff_b)
                want = self._want(self._b_on, diff_b, self._f(CONF_HY_B_HYST_ON), self._f(CONF_HY_B_HYST_OFF))
                self._b_on, self._b_since = self._gate(
                    self._b_on, self._b_since, now, want,
                    self._f(CONF_HY_B_MIN_ON), self._f(CONF_HY_B_MIN_OFF),
                )
                p_boiler = 0.0
                if self._b_on:
                    delta_loss = max(0.0, consigne - (temp_out if temp_out is not None else temp_in))
                    raw = max(0.0, min(100.0, self.gain_boiler * delta_loss * (fraction / 100.0)))
                    p_boiler = raw if raw >= self._f(CONF_MIN_POWER) else 0.0
                self.power_boiler_request = int(round(p_boiler))
                self._b_last_eval = now
                self._b_last_order = consigne

            # --- B. Clim (appoint rapide) ---
            x = self._f(CONF_HY_A_FORCE_FRACTION)
            if x > 0:
                self.ac_forced = fraction >= (x - HY_FORCE_RELEASE_GAP if self.ac_forced else x)
            else:
                self.ac_forced = False
            diff_a = consigne - t_a
            h_off_a = self._f(CONF_HY_A_HYST_OFF)
            forced_on = self.ac_forced and diff_a > -h_off_a  # jamais de forçage en surchauffe
            if forced_on:
                if not self._a_on:
                    self._a_on, self._a_since = True, now
            else:
                want = self._want(self._a_on, diff_a, self._f(CONF_HY_A_HYST_ON), h_off_a)
                self._a_on, self._a_since = self._gate(
                    self._a_on, self._a_since, now, want,
                    self._f(CONF_HY_A_MIN_ON), self._f(CONF_HY_A_MIN_OFF),
                )
            p_ac = 0.0
            if self._a_on:
                raw = max(0.0, min(100.0, self.coeff_ac * diff_a + self.offset_ac))
                floor = max(self._f(CONF_HY_A_MIN_POWER), self._f(CONF_HY_A_FORCE_POWER) if forced_on else 0.0)
                p_ac = max(raw, floor)

            self.power_ac = int(round(p_ac))
            self.power_heat = max(self.power_boiler_request, self.power_ac)
            self.power_cool = 0

            self._last_ac_temp_in = temp_in
            self._last_ac_order = consigne
            self._last_ac_power = self.power_ac

            status = Z_HEATING if self.power_heat > 0 else Z_IDLE
            self._apply(status, heat=self.power_heat, cool=0)

        elif self.sense == COOL:
            self._reset_regulation()
            consigne = self.target_cool
            diff_in = temp_in - consigne
            min_p = self._f(CONF_MIN_POWER)
            if diff_in > 0:
                raw_cool = self.coeff_ac * diff_in
                p_cool = max(0.0, min(100.0, raw_cool)) if raw_cool >= min_p else 0.0
            else:
                p_cool = 0.0

            self.power_boiler_request = 0
            self.power_ac = 0
            self.power_heat = 0
            self.power_cool = int(round(p_cool))
            self._last_ac_power = 0

            status = Z_COOLING if self.power_cool > 0 else Z_IDLE
            self._apply(status, heat=0, cool=self.power_cool)

    # ------------------------------------------------------------ commandes UI
    def get_value(self, key: str) -> float:
        if key == "coeff_in_ac":
            return float(self.coeff_ac)
        if key == "gain_boiler":
            return float(self.gain_boiler)
        if key == "offset_ac":
            return float(self.offset_ac)
        return super().get_value(key)

    def learn_count(self, key: str) -> int | None:
        if key == "coeff_in_ac":
            return self.n_ac
        if key == "gain_boiler":
            return self.n_boiler_days
        return super().learn_count(key)

    async def async_set_value(self, key: str, value: float) -> None:
        if key == "coeff_in_ac":
            self.coeff_ac = float(value)
            self.n_ac = 10
        elif key == "gain_boiler":
            self.gain_boiler = float(value)
            self.n_boiler_days = 7
        elif key == "offset_ac":
            self.offset_ac = float(value)
        else:
            await super().async_set_value(key, value)
            return
        self._save()
        self._notify()
        await self.async_run_cycle()

    async def async_reset_learning(self) -> None:
        self.coeff_ac = DEFAULT_COEFF_AC
        self.n_ac = 1
        self.gain_boiler = DEFAULT_GAIN_BOILER
        self.n_boiler_days = 0
        self._boiler_learned_today = False
        self._last_ac_temp_in = None
        self._last_ac_order = None
        self._last_ac_power = 0
        self._save()
        self._notify()
        await self.async_run_cycle()
