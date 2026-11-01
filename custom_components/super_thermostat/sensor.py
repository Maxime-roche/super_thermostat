"""Capteurs : puissances, statuts, seuils d'eau."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AC_STATUSES, BOILER_STATUSES, CONF_TYPE, TYPE_AC, TYPE_BOILER, TYPE_ZONE, ZONE_STATUSES,
)
from .entity import ControllerEntity


class ControllerSensor(ControllerEntity, SensorEntity):
    def __init__(
        self, controller, key: str, value_fn: Callable[[], Any], *,
        unit: str | None = None, device_class: SensorDeviceClass | None = None,
        options: list[str] | None = None, attrs_fn: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__(controller, key)
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        if options:
            self._attr_options = options
        elif unit:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        return self._value_fn()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._attrs_fn() if self._attrs_fn else None


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[ControllerSensor] = []
    if entry.data[CONF_TYPE] == TYPE_ZONE:
        if c.has_heat:
            entities.append(ControllerSensor(c, "power_heat", lambda: c.power_heat, unit=PERCENTAGE))
            entities.append(
                ControllerSensor(
                    c, "power_boiler", lambda: c.power_boiler, unit=PERCENTAGE,
                    attrs_fn=lambda: {"fraction": c.fraction},
                )
            )
        if c.has_cool:
            entities.append(ControllerSensor(c, "power_cool", lambda: c.power_cool, unit=PERCENTAGE))
        entities.append(
            ControllerSensor(
                c, "zone_status", lambda: c.status,
                device_class=SensorDeviceClass.ENUM, options=ZONE_STATUSES,
            )
        )
    elif entry.data[CONF_TYPE] == TYPE_AC:
        entities += [
            ControllerSensor(
                c, "demand", lambda: round(c.demand, 1), unit=PERCENTAGE,
                attrs_fn=lambda: {"sources": c.source_values, "cool_sources": c.cool_values, "fraction": c.fraction},
            ),
            ControllerSensor(
                c, "ac_setpoint", lambda: c.setpoint, unit=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
            ),
            ControllerSensor(
                c, "ac_status", lambda: c.status, device_class=SensorDeviceClass.ENUM,
                options=AC_STATUSES,
                attrs_fn=lambda: {"dry_run": c.dry_run, "pending_actions": c.pending, **c.diagnostic},
            ),
        ]
    elif entry.data[CONF_TYPE] != TYPE_BOILER:  # fraction chaudière
        entities += [
            ControllerSensor(
                c, "fraction", lambda: c.fraction, unit=PERCENTAGE,
                attrs_fn=lambda: {"raw_fraction": c.raw_fraction, "min_fraction": c.min_fraction},
            ),
            ControllerSensor(
                c, "reference_temperature",
                lambda: None if c.ref_temp is None else round(c.ref_temp, 1),
                unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
                attrs_fn=lambda: {"source": c.ref_source, "as_of": c.ref_date},
            ),
        ]
    else:
        entities += [
            ControllerSensor(
                c, "demand", lambda: round(c.demand, 1), unit=PERCENTAGE,
                attrs_fn=lambda: {"sources": c.source_values},
            ),
            ControllerSensor(
                c, "water_low", lambda: round(c.low, 1), unit=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
            ),
            ControllerSensor(
                c, "water_high", lambda: round(c.high, 1), unit=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
            ),
            ControllerSensor(
                c, "boiler_status", lambda: c.status,
                device_class=SensorDeviceClass.ENUM, options=BOILER_STATUSES,
                attrs_fn=lambda: {"dry_run": c.dry_run},
            ),
        ]
    async_add_entities(entities)
