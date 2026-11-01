"""Bouton : remise à zéro de l'apprentissage d'une zone."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ControllerEntity


class ResetLearningButton(ControllerEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller) -> None:
        super().__init__(controller, "reset_learning")

    async def async_press(self) -> None:
        await self._ctrl.async_reset_learning()


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ResetLearningButton(entry.runtime_data)])
