"""Super Thermostat — zones (% de chauffe) + gestion chaudière."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .boiler import BoilerController
from .ac import ACController
from .const import CONF_TYPE, TYPE_AC, TYPE_BOILER, TYPE_FRACTION, TYPE_ZONE, TYPE_ZONE_HYBRID
from .migration import migrate_valve_options
from .fraction import FractionController
from .zone import ZoneController
from .zone_hybrid import ZoneHybridController

type SuperThermostatConfigEntry = ConfigEntry[ZoneController | ZoneHybridController | BoilerController | FractionController | ACController]

PLATFORMS = {
    TYPE_ZONE: [
        Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR,
        Platform.NUMBER, Platform.BUTTON,
    ],
    TYPE_ZONE_HYBRID: [
        Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR,
        Platform.NUMBER, Platform.BUTTON,
    ],
    TYPE_BOILER: [
        Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH,
    ],
    TYPE_FRACTION: [Platform.SENSOR],
    TYPE_AC: [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH],
}


async def async_setup_entry(hass: HomeAssistant, entry: SuperThermostatConfigEntry) -> bool:
    kind = entry.data[CONF_TYPE]
    if kind in (TYPE_ZONE, TYPE_ZONE_HYBRID):
        # anciennes vannes -> champ libre « demande suivie » (une fois, avant d'écouter les changements)
        migrated = migrate_valve_options(dict(entry.data), dict(entry.options))
        if migrated is not None:
            hass.config_entries.async_update_entry(entry, options=migrated)
    controller_class = {
        TYPE_ZONE: ZoneController, TYPE_ZONE_HYBRID: ZoneHybridController,
        TYPE_BOILER: BoilerController,
        TYPE_FRACTION: FractionController, TYPE_AC: ACController,
    }[kind]
    controller = controller_class(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS[kind])
    await controller.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SuperThermostatConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS[entry.data[CONF_TYPE]]
    )
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _reload_on_update(hass: HomeAssistant, entry: SuperThermostatConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
