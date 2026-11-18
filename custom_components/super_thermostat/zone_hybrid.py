"""Zone combinée chaudière (base lente) + climatisation (appoint rapide).

Cette zone spéciale hérite de ZoneController sans modifier les zones simples :
  * Chaudière : base lente asservie à la météo extérieure (fraction / loi d'eau),
    conditionnée à la demande réelle (arrêt dès consigne atteinte),
    avec recalibrage quotidien doux de son gain sur 1 à 2 semaines.
  * Climatisation : boucle rapide (cycle court de 10 à 15 min),
    apprenant uniquement sa propre réactivité intérieure (sans terme météo).
  * Publication séparée : publie power_boiler pour la chaudière et power_ac pour la clim.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_FAILSAFE_POWER, CONF_FRACTION_ENTITY, CONF_OUTDOOR_ENTITY,
    Z_COOLING, Z_HEATING, Z_IDLE, Z_OFF, Z_SENSOR_FAILURE, Z_SUSPENDED,
)
from .engine import COOL, HEAT, resolve_sense
from .helpers import read_number
from .zone import ZoneController

_LOGGER = logging.getLogger(__name__)

DEFAULT_COEFF_AC = 15.0       # gain réactif clim initial (%/°C)
DEFAULT_GAIN_BOILER = 5.0     # gain base chaudière initial (%/°C)
MAX_AC_LEARN_COUNT = 50
MIN_DAILY_SAMPLES = 12        # au moins ~2h de demande active pour recalibrer la journée


class ZoneHybridController(ZoneController):
    """Zone combinant une base lente (chaudière) et un appoint rapide (climatisation)."""

    model = "Zone Chaudière + Clim"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self.coeff_ac: float = DEFAULT_COEFF_AC
        self.n_ac: int = 1
        self.offset_ac: float = 0.0
        self.gain_boiler: float = DEFAULT_GAIN_BOILER
        self.n_boiler_days: int = 0
        self.power_ac: int = 0
        self._daily_errors: list[float] = []
        self._last_ac_temp_in: float | None = None
        self._last_ac_order: float | None = None
        self._last_ac_power: int = 0

    # ---------------------------------------------------------------- storage
    def _data(self) -> dict[str, Any]:
        data = super()._data()
        data.update({
            "coeff_ac": self.coeff_ac,
            "n_ac": self.n_ac,
            "offset_ac": self.offset_ac,
            "gain_boiler": self.gain_boiler,
            "n_boiler_days": self.n_boiler_days,
            "daily_errors": self._daily_errors,
            "last_ac_temp_in": self._last_ac_temp_in,
            "last_ac_order": self._last_ac_order,
            "last_ac_power": self._last_ac_power,
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
        self._daily_errors = list(data.get("daily_errors") or [])
        self._last_ac_temp_in = data.get("last_ac_temp_in")
        self._last_ac_order = data.get("last_ac_order")
        self._last_ac_power = int(data.get("last_ac_power", 0))

    # -------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        await super().async_start()
        # Recalibrage quotidien doux à 00:10
        self._unsubs.append(
            async_track_time_change(self.hass, self._daily_recalibration, hour=0, minute=10, second=0)
        )

    # --------------------------------------------------- recalibrage quotidien
    @callback
    def _daily_recalibration(self, _now: Any = None) -> None:
        """Recalibre doucement le gain de base chaudière sur l'écart moyen journalier."""
        if len(self._daily_errors) >= MIN_DAILY_SAMPLES:
            mean_err = sum(self._daily_errors) / len(self._daily_errors)
            # si mean_err > 0.15 : la température était en moyenne sous la consigne -> base un peu faible
            if mean_err > 0.15:
                adj = min(0.5, 0.2 * mean_err)
                self.gain_boiler = round(min(30.0, self.gain_boiler + adj), 2)
                self.n_boiler_days += 1
                _LOGGER.info(
                    "%s : recalibrage chaudière +%.2f (gain: %.2f, écart moyen: +%.2f °C)",
                    self.entry.title, adj, self.gain_boiler, mean_err,
                )
            # si mean_err < -0.15 : dépassement moyen de consigne -> base trop forte
            elif mean_err < -0.15:
                adj = min(0.5, 0.2 * abs(mean_err))
                self.gain_boiler = round(max(0.5, self.gain_boiler - adj), 2)
                self.n_boiler_days += 1
                _LOGGER.info(
                    "%s : recalibrage chaudière -%.2f (gain: %.2f, écart moyen: %.2f °C)",
                    self.entry.title, adj, self.gain_boiler, mean_err,
                )
        self._daily_errors.clear()
        self._save()
        self._notify()

    # ----------------------------------------------------------------- cycles
    async def async_run_cycle(self) -> None:
        """Cycle d'évaluation à boucle rapide."""
        self._schedule_next()

        if self.hvac_mode == "off":
            self.state.interrupt()
            self.sense = None
            self.sensor_failure = False
            self.power_boiler = 0
            self.power_ac = 0
            self._last_ac_power = 0
            self._apply(Z_OFF)
            return

        if self.suspended:
            self.state.interrupt()
            self.sensor_failure = False
            self.power_boiler = 0
            self.power_ac = 0
            self._last_ac_power = 0
            self._apply(Z_SUSPENDED)
            return

        temp_in = self._fresh_temperature()
        if temp_in is None:
            self.state.interrupt()
            self.sensor_failure = True
            _LOGGER.warning("%s : sonde intérieure absente ou périmée", self.entry.title)
            failsafe = int(self.cfg[CONF_FAILSAFE_POWER])
            heating = self.hvac_mode in ("heat", "heat_cool")
            self.power_boiler = failsafe if heating else 0
            self.power_ac = 0
            self._last_ac_power = 0
            self._apply(Z_SENSOR_FAILURE, heat=self.power_boiler)
            return

        self.sensor_failure = False
        temp_out = read_number(self.hass, self.cfg.get(CONF_OUTDOOR_ENTITY), temperature=True)
        fraction = self.fraction

        # Détermination du sens actif
        self.sense = resolve_sense(
            self.hvac_mode, self._summer(), temp_in, self.target_heat, self.target_cool, self.sense
        )
        if self.sense is None:
            self.state.interrupt()
            self.power_boiler = 0
            self.power_ac = 0
            self._last_ac_power = 0
            self._apply(Z_IDLE)
            return

        min_p = float(self.params.min_power)

        if self.sense == HEAT:
            consigne = self.target_heat
            diff_in = consigne - temp_in

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
                    self.coeff_ac = round(
                        (self.coeff_ac * self.n_ac + estimate) / (self.n_ac + 1), 2
                    )
                    self.n_ac = min(self.n_ac + 1, MAX_AC_LEARN_COUNT)
                    _LOGGER.debug(
                        "%s : apprentissage réactivité clim -> %.2f (mesure: %d)",
                        self.entry.title, self.coeff_ac, self.n_ac,
                    )

            # --- A. Chaudière (base lente) ---
            # Condition : sans demande de chauffage (diff_in <= 0), pas de chaudière
            if diff_in > 0:
                delta_loss = max(0.0, consigne - (temp_out if temp_out is not None else temp_in))
                raw_boiler = self.gain_boiler * delta_loss * (fraction / 100.0)
                raw_boiler = max(0.0, min(100.0, raw_boiler))
                p_boiler = raw_boiler if raw_boiler >= min_p else 0.0
                self._daily_errors.append(diff_in)
            else:
                p_boiler = 0.0

            # --- B. Climatisation (appoint rapide) ---
            # Corrige directement l'écart résiduel intérieur sans terme météo
            if diff_in > 0:
                raw_ac = self.coeff_ac * diff_in + self.offset_ac
                raw_ac = max(0.0, min(100.0, raw_ac))
                p_ac = raw_ac if raw_ac >= min_p else 0.0
            else:
                p_ac = 0.0

            self.power_boiler = int(round(p_boiler))
            self.power_ac = int(round(p_ac))
            self.power_heat = max(self.power_boiler, self.power_ac)
            self.power_cool = 0

            self._last_ac_temp_in = temp_in
            self._last_ac_order = consigne
            self._last_ac_power = self.power_ac

            status = Z_HEATING if self.power_heat > 0 else Z_IDLE
            self._apply(status, heat=self.power_heat, cool=0)

        elif self.sense == COOL:
            consigne = self.target_cool
            diff_in = temp_in - consigne
            if diff_in > 0:
                raw_cool = self.coeff_ac * diff_in
                p_cool = max(0.0, min(100.0, raw_cool)) if raw_cool >= min_p else 0.0
            else:
                p_cool = 0.0

            self.power_boiler = 0
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
        self._daily_errors.clear()
        self._last_ac_temp_in = None
        self._last_ac_order = None
        self._last_ac_power = 0
        self._save()
        self._notify()
        await self.async_run_cycle()
