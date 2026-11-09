"""Entité climate d'une zone : deux consignes (chauffe / froid), mode et préréglages."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE, ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW, PRESET_NONE,
    ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ALLOWED_ALL, CONF_TEMP_ENTITY, MAX_TEMP, MIN_TEMP, Z_COOLING, Z_HEATING, Z_OFF,
)
from .entity import ControllerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ZoneClimate(entry.runtime_data)])


class ZoneClimate(ControllerEntity, ClimateEntity):
    """Thermostat de zone : ne pilote rien, publie un pourcentage."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP  # une consigne de froid à 35 °C = clim coupée

    def __init__(self, controller) -> None:
        super().__init__(controller, "zone")
        self._attr_translation_key = None
        self._attr_hvac_modes = [HVACMode(m) for m in controller.hvac_modes]
        self._attr_preset_modes = [PRESET_NONE, *controller.preset_names.values()]
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if controller.allowed == ALLOWED_ALL:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._ctrl.cfg[CONF_TEMP_ENTITY]],
                lambda _event: self.async_write_ha_state(),
            )
        )

    @property
    def current_temperature(self) -> float | None:
        return self._ctrl.current_temperature

    @property
    def target_temperature(self) -> float | None:
        mode = self._ctrl.hvac_mode
        if mode == "heat_cool":
            return None  # en mode auto, l'interface affiche la plage basse / haute
        return self._ctrl.target_cool if mode == "cool" else self._ctrl.target_heat

    @property
    def target_temperature_low(self) -> float:
        return self._ctrl.target_heat

    @property
    def target_temperature_high(self) -> float:
        return self._ctrl.target_cool

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode(self._ctrl.hvac_mode)

    @property
    def hvac_action(self) -> HVACAction:
        status = self._ctrl.status
        if status == Z_OFF:
            return HVACAction.OFF
        if status == Z_HEATING:
            return HVACAction.HEATING
        if status == Z_COOLING:
            return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        slug = self._ctrl.preset
        return self._ctrl.preset_names.get(slug, PRESET_NONE) if slug else PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "status": self._ctrl.status,
            "sensor_entity": self._ctrl.cfg.get(CONF_TEMP_ENTITY),
            "sensor_age_minutes": self._ctrl.sensor_age_minutes,
            "sensor_failure": self._ctrl.sensor_failure,
            "active_sense": self._ctrl.sense,
            "target_heat": self._ctrl.target_heat,
            "target_cool": self._ctrl.target_cool,
            "cooling_disabled": self._ctrl.cooling_disabled,
            "power_heat": self._ctrl.power_heat,
            "power_cool": self._ctrl.power_cool,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._ctrl.async_set_hvac_mode(hvac_mode.value)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self._ctrl.async_set_hvac_mode(HVACMode(mode).value)
        low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:  # consigne unique : celle du sens du mode courant
            if self._ctrl.hvac_mode == "cool":
                high = temp
            else:
                low = temp
        if low is not None or high is not None:
            await self._ctrl.async_set_targets(
                None if low is None else float(low), None if high is None else float(high)
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._ctrl.async_set_preset(preset_mode)
