"""Binaires : défaillance (zone), brûleur et circulateur (chaudière)."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_TYPE, TYPE_ZONE
from .entity import ControllerEntity


class ControllerBinary(ControllerEntity, BinarySensorEntity):
    def __init__(self, controller, key: str, fn: Callable[[], bool], device_class) -> None:
        super().__init__(controller, key)
        self._fn = fn
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool:
        return bool(self._fn())


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    if entry.data[CONF_TYPE] == TYPE_ZONE:
        async_add_entities([ControllerBinary(c, "problem", lambda: c.problem, BinarySensorDeviceClass.PROBLEM)])
    else:
        async_add_entities([
            ControllerBinary(c, "burner", lambda: c.burner_on, BinarySensorDeviceClass.RUNNING),
            ControllerBinary(c, "circulator", lambda: c.circulator_on, BinarySensorDeviceClass.RUNNING),
        ])
