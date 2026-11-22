"""Interrupteurs de la gestion chaudière : activation et simulation."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ControllerEntity


class BoilerSwitch(ControllerEntity, SwitchEntity):
    def __init__(self, controller, key: str, attr: str, setter: str) -> None:
        super().__init__(controller, key)
        self._attr = attr
        self._setter = setter

    @property
    def is_on(self) -> bool:
        return bool(getattr(self._ctrl, self._attr))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await getattr(self._ctrl, self._setter)(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await getattr(self._ctrl, self._setter)(False)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([
        BoilerSwitch(c, "enabled", "enabled", "async_set_enabled"),
        BoilerSwitch(c, "dry_run", "dry_run", "async_set_dry_run"),
        BoilerSwitch(c, "use_fraction", "use_fraction", "async_set_use_fraction"),
    ])
