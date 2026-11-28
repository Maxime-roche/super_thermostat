"""Binaires : défaillance (zone), brûleur et circulateur (chaudière)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_DEFROST_MAX_MINUTES, CONF_DEFROST_MAX_OUTDOOR, CONF_DEFROST_MAX_POWER, CONF_DEFROST_MIN_POWER,
    CONF_DEFROST_OUTDOOR_ENTITY, CONF_DEFROST_POWER_ENTITY, CONF_TYPE, CONF_VALVE_PENDING,
    CONF_VALVE_POSITIONS, TYPE_AC, TYPE_ZONE, TYPE_ZONE_HYBRID,
)
from .entity import ControllerEntity


class ControllerBinary(ControllerEntity, BinarySensorEntity):
    def __init__(
        self, controller, key: str, fn: Callable[[], bool], device_class,
        attrs_fn: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__(controller, key)
        self._fn = fn
        self._attrs_fn = attrs_fn
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool:
        return bool(self._fn())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._attrs_fn() if self._attrs_fn else None


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    if entry.data[CONF_TYPE] in (TYPE_ZONE, TYPE_ZONE_HYBRID):
        entities = [ControllerBinary(c, "problem", lambda: c.problem, BinarySensorDeviceClass.PROBLEM)]
        if c.cfg.get(CONF_VALVE_POSITIONS):
            entities.append(
                ControllerBinary(
                    c, "valve_problem", lambda: c.valve_alert, BinarySensorDeviceClass.PROBLEM,
                    attrs_fn=lambda: {
                        "valves_in_alert": [v for v, i in c.valve_report.items() if i["alert"]],
                        "positions": c.valve_report,
                    },
                )
            )
        if c.cfg.get(CONF_VALVE_PENDING):
            entities.append(
                ControllerBinary(
                    c, "valve_waiting", lambda: c.valve_waiting, None,
                    attrs_fn=lambda: {
                        "sync_state": c.valve_sync_state,
                        "boiler_request": c.power_boiler_request,
                        "pending": {
                            v: (c.hass.states.get(p).state if c.hass.states.get(p) else None)
                            for v, p in c.pending_pairs
                        },
                    },
                )
            )
        async_add_entities(entities)
    elif entry.data[CONF_TYPE] == TYPE_AC:
        entities = []
        if c.cfg.get(CONF_DEFROST_POWER_ENTITY) and c.cfg.get(CONF_DEFROST_OUTDOOR_ENTITY):
            entities.append(
                ControllerBinary(
                    c, "defrost", lambda: c.defrost, None,
                    attrs_fn=lambda: {
                        "power": c.defrost_power,
                        "outdoor_temperature": c.defrost_outdoor,
                        "min_power": c.cfg[CONF_DEFROST_MIN_POWER],
                        "max_power": c.cfg[CONF_DEFROST_MAX_POWER],
                        "armed": c._defrost_armed,
                        "max_outdoor_temperature": c.cfg[CONF_DEFROST_MAX_OUTDOOR],
                        "max_minutes": c.cfg[CONF_DEFROST_MAX_MINUTES],
                        "seconds_since_start": c.defrost_seconds,
                    },
                )
            )
        async_add_entities(entities)
    else:
        async_add_entities([
            ControllerBinary(c, "burner", lambda: c.burner_on, BinarySensorDeviceClass.RUNNING),
            ControllerBinary(c, "circulator", lambda: c.circulator_on, BinarySensorDeviceClass.RUNNING),
        ])
