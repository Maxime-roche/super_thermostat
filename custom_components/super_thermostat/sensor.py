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
    AC_STATUSES, BOILER_STATUSES, CONF_TYPE, CONF_VALVE_PROPORTIONAL, CONF_VALVE_SOURCE,
    CONF_VALVES, TYPE_AC, TYPE_BOILER, TYPE_ZONE, TYPE_ZONE_HYBRID, ZONE_STATUSES,
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
    kind = entry.data[CONF_TYPE]
    if kind in (TYPE_ZONE, TYPE_ZONE_HYBRID):
        if c.has_heat:
            entities.append(ControllerSensor(c, "power_heat", lambda: c.power_heat, unit=PERCENTAGE))
            entities.append(
                ControllerSensor(
                    c, "power_boiler", lambda: c.power_boiler, unit=PERCENTAGE,
                    attrs_fn=lambda: {"fraction": c.fraction},
                )
            )
        if kind == TYPE_ZONE_HYBRID:
            entities.append(ControllerSensor(c, "power_ac", lambda: c.power_ac, unit=PERCENTAGE))
        if c.has_cool:
            entities.append(ControllerSensor(c, "power_cool", lambda: c.power_cool, unit=PERCENTAGE))
        if c.cfg.get(CONF_VALVES):
            entities.append(
                ControllerSensor(
                    c, "valve_target", lambda: c.valve_target, unit=PERCENTAGE,
                    attrs_fn=lambda: {
                        "source": c.cfg.get(CONF_VALVE_SOURCE) or "zone_boiler_power",
                        "proportional": c.cfg.get(CONF_VALVE_PROPORTIONAL, True),
                        "other_zone_demand": c._other_zone_demand(),
                        "valves": {
                            e: (c.hass.states.get(e).state if c.hass.states.get(e) else None)
                            for e in c.cfg[CONF_VALVES]
                        },
                        "positions": c.valve_report,
                    },
                )
            )
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
                attrs_fn=lambda: {
                    "raw_fraction": c.raw_fraction_mean, "min_fraction": c.min_fraction,
                    "source": c.mean_source,
                },
            ),
            ControllerSensor(
                c, "fraction_current", lambda: c.fraction_current, unit=PERCENTAGE,
                attrs_fn=lambda: {
                    "raw_fraction": c.raw_fraction_current, "min_fraction": c.min_fraction,
                    "source": c.current_source,
                },
            ),
            ControllerSensor(
                c, "reference_temperature",
                lambda: None if c.ref_mean is None else round(c.ref_mean, 1),
                unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
                attrs_fn=lambda: {"source": c.mean_source, "as_of": c.mean_date},
            ),
            ControllerSensor(
                c, "current_temperature",
                lambda: None if c.ref_current is None else round(c.ref_current, 1),
                unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE,
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
