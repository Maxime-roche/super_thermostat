"""Configuration 100 % UI : ajout d'une zone ou de la chaudière + options."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    ALLOWED_ALL, ALLOWED_COOL, ALLOWED_HEAT, CONF_AC_FRACTION, CONF_AC_MIN_ON,
    CONF_ADJUST_INTERVAL, CONF_ALLOWED, CONF_ASSOCIATED_CLIMATE, CONF_AUTOLEARN, CONF_BURNER, CONF_CIRCULATOR,
    CONF_CLIMATE, CONF_COOL_SOURCES, CONF_CYCLE, CONF_FAILSAFE_POWER, CONF_FAIL_OFFSET,
    CONF_FALLBACK_TEMP, CONF_FRACTION_ENTITY, CONF_FRACTION_SOURCE, CONF_LIMIT_CYCLES,
    CONF_MAX_SENSOR_AGE, CONF_MIN_FRACTION, CONF_MIN_OFF, CONF_MIN_ON, CONF_MIN_POWER,
    CONF_MODE_DELAY, CONF_NAME, CONF_NOTIFY_MESSAGE, CONF_NOTIFY_SERVICE, CONF_OFFSET_NEXT_FULL,
    CONF_OUTDOOR_ENTITY, CONF_POST_RUN, CONF_SAFETY_MAX, CONF_SEUIL_BAS, CONF_SEUIL_HAUT,
    CONF_SOURCES, CONF_START_DELAY,
    CONF_SUMMER, CONF_TEMP_ENTITY, CONF_THRESHOLD_HOT, CONF_TYPE, CONF_VALVES,
    CONF_VALVE_ALERT_MINUTES, CONF_VALVE_KEEP_OPEN, CONF_VALVE_LEVEL, CONF_VALVE_MIN_STEP,
    CONF_VALVE_NEVER_CLOSE, CONF_VALVE_OPEN_MAX, CONF_VALVE_OPEN_MIN, CONF_VALVE_POSITIONS,
    CONF_VALVE_PROPORTIONAL, CONF_VALVE_RETRY, CONF_VALVE_SOURCE, CONF_WATER_MAX_AGE,
    CONF_WATER_TEMP, CONF_WINDOWS, CONF_WINDOW_RESTART_DELAY, CONF_WINDOW_STOP_DELAY,
    CONF_ZONE_SEASON, DEFAULT_AC_OPTIONS, DEFAULT_BOILER_OPTIONS, DEFAULT_FRACTION_OPTIONS,
    DEFAULT_ZONE_OPTIONS, DOMAIN, TYPE_AC, TYPE_BOILER, TYPE_FRACTION, TYPE_ZONE,
    TYPE_ZONE_HYBRID,
)


def _temp_sensor() -> sel.EntitySelector:
    """Toute entité numérique (sensor, input_number, number) ou météo / climate."""
    return sel.EntitySelector(
        sel.EntitySelectorConfig(domain=["sensor", "input_number", "number", "weather", "climate"])
    )


def _numeric_entity() -> sel.EntitySelector:
    return sel.EntitySelector(
        sel.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
    )


def _num(lo: float, hi: float, step: float = 1, unit: str | None = None) -> sel.NumberSelector:
    return sel.NumberSelector(
        sel.NumberSelectorConfig(
            min=lo, max=hi, step=step, unit_of_measurement=unit, mode=sel.NumberSelectorMode.BOX
        )
    )


def _relay() -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=["switch", "input_boolean"]))


def _sources() -> sel.EntitySelector:
    return sel.EntitySelector(
        sel.EntitySelectorConfig(domain=["sensor", "number", "input_number"], multiple=True)
    )


ALLOWED_SELECTOR = sel.SelectSelector(
    sel.SelectSelectorConfig(
        options=[ALLOWED_HEAT, ALLOWED_COOL, ALLOWED_ALL],
        translation_key="allowed_modes",
        mode=sel.SelectSelectorMode.DROPDOWN,
    )
)

# --- schémas des options ---
ZONE_SENSORS = vol.Schema(
    {
        vol.Required(CONF_TEMP_ENTITY): _temp_sensor(),
        vol.Optional(CONF_OUTDOOR_ENTITY): _temp_sensor(),
        vol.Optional(CONF_FRACTION_ENTITY): _numeric_entity(),
        vol.Optional(CONF_ZONE_SEASON): sel.EntitySelector(
            sel.EntitySelectorConfig(domain=["input_boolean", "switch", "binary_sensor"])
        ),
        vol.Optional(CONF_ASSOCIATED_CLIMATE): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="climate")
        ),
        vol.Required(CONF_ALLOWED): ALLOWED_SELECTOR,
        vol.Required(CONF_CYCLE): _num(5, 240, 1, "min"),
        vol.Required(CONF_MAX_SENSOR_AGE): _num(5, 1440, 1, "min"),
        vol.Required(CONF_FAILSAFE_POWER): _num(0, 100, 1, "%"),
    }
)
ZONE_VALVES = vol.Schema(
    {
        vol.Optional(CONF_VALVES): sel.EntitySelector(
            sel.EntitySelectorConfig(domain=["number", "input_number"], multiple=True)
        ),
        vol.Optional(CONF_VALVE_POSITIONS): sel.EntitySelector(
            sel.EntitySelectorConfig(domain=["sensor", "number", "input_number"], multiple=True)
        ),
        vol.Required(CONF_VALVE_ALERT_MINUTES): _num(0, 720, 5, "min"),
        vol.Optional(CONF_VALVE_SOURCE): _numeric_entity(),
        vol.Required(CONF_VALVE_PROPORTIONAL): sel.BooleanSelector(),
        vol.Required(CONF_VALVE_OPEN_MIN): _num(0, 100, 1, "%"),
        vol.Required(CONF_VALVE_OPEN_MAX): _num(0, 100, 1, "%"),
        vol.Optional(CONF_VALVE_LEVEL): _num(5, 100, 5, "%"),
        vol.Required(CONF_VALVE_MIN_STEP): _num(0, 50, 1, "%"),
        vol.Required(CONF_VALVE_RETRY): _num(5, 240, 5, "min"),
        vol.Required(CONF_VALVE_NEVER_CLOSE): sel.BooleanSelector(),
        vol.Required(CONF_VALVE_KEEP_OPEN): sel.BooleanSelector(),
    }
)
def _notify_schema(hass) -> vol.Schema:
    """Choix du service de notification parmi ceux qui existent (saisie libre possible) + message."""
    try:
        services = hass.services.async_services_for_domain("notify")
    except AttributeError:  # anciennes versions
        services = hass.services.async_services().get("notify", {})
    options = [{"value": f"notify.{name}", "label": name} for name in sorted(services)]
    return vol.Schema(
        {
            vol.Optional(CONF_NOTIFY_SERVICE): sel.SelectSelector(
                sel.SelectSelectorConfig(options=options, custom_value=True, mode=sel.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NOTIFY_MESSAGE): sel.TextSelector(sel.TextSelectorConfig(multiline=False)),
        }
    )


ZONE_REGULATION = vol.Schema(
    {
        vol.Required(CONF_MIN_POWER): _num(0, 50, 1, "%"),
        vol.Required(CONF_LIMIT_CYCLES): sel.BooleanSelector(),
        vol.Required(CONF_AUTOLEARN): sel.BooleanSelector(),
        vol.Required(CONF_THRESHOLD_HOT): _num(0, 100, 1, "%"),
        vol.Required(CONF_OFFSET_NEXT_FULL): _num(0, 100, 1, "%"),
        vol.Required(CONF_FAIL_OFFSET): _num(0, 10, 0.5, "°C"),
    }
)
ZONE_WINDOWS = vol.Schema(
    {
        vol.Optional(CONF_WINDOWS): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="binary_sensor", multiple=True)
        ),
        vol.Required(CONF_WINDOW_STOP_DELAY): _num(0, 60, 1, "min"),
        vol.Required(CONF_WINDOW_RESTART_DELAY): _num(0, 60, 1, "min"),
    }
)
BOILER_SENSORS = vol.Schema(
    {
        vol.Required(CONF_BURNER): _relay(),
        vol.Required(CONF_CIRCULATOR): _relay(),
        vol.Required(CONF_WATER_TEMP): _temp_sensor(),
        vol.Required(CONF_SOURCES): _sources(),
        vol.Optional(CONF_FRACTION_ENTITY): _numeric_entity(),
    }
)
BOILER_TUNING = vol.Schema(
    {
        vol.Required(CONF_POST_RUN): _num(0, 60, 1, "min"),
        vol.Required(CONF_MIN_ON): _num(0, 30, 1, "min"),
        vol.Required(CONF_MIN_OFF): _num(0, 30, 1, "min"),
        vol.Required(CONF_SAFETY_MAX): _num(40, 110, 1, "°C"),
        vol.Required(CONF_WATER_MAX_AGE): _num(1, 120, 1, "min"),
    }
)
# champs facultatifs → valeur « vide » quand l'utilisateur les efface
FRACTION_SOURCE = vol.Schema(
    {
        vol.Required(CONF_FRACTION_SOURCE): _temp_sensor(),
        vol.Required(CONF_FALLBACK_TEMP): _num(-30, 40, 0.5, "°C"),
        vol.Required(CONF_SEUIL_HAUT): _num(-30, 40, 0.5, "°C"),
        vol.Required(CONF_SEUIL_BAS): _num(-30, 40, 0.5, "°C"),
        vol.Required(CONF_MIN_FRACTION): _num(0, 50, 1, "%"),
    }
)
AC_ENTITIES = vol.Schema(
    {
        vol.Required(CONF_CLIMATE): sel.EntitySelector(sel.EntitySelectorConfig(domain="climate")),
        vol.Required(CONF_SOURCES): _sources(),
        vol.Optional(CONF_COOL_SOURCES): _sources(),
        vol.Optional(CONF_AC_FRACTION): _numeric_entity(),
        vol.Optional(CONF_SUMMER): sel.EntitySelector(
            sel.EntitySelectorConfig(domain=["input_boolean", "switch", "binary_sensor"])
        ),
    }
)
AC_TUNING = vol.Schema(
    {
        vol.Required(CONF_START_DELAY): _num(0, 120, 1, "min"),
        vol.Required(CONF_ADJUST_INTERVAL): _num(1, 120, 1, "min"),
        vol.Required(CONF_AC_MIN_ON): _num(0, 60, 1, "min"),
        vol.Required(CONF_MODE_DELAY): _num(0, 120, 1, "s"),
    }
)
CLEARABLE = {
    CONF_OUTDOOR_ENTITY: "", CONF_FRACTION_ENTITY: "", CONF_WINDOWS: [], CONF_VALVES: [], CONF_VALVE_SOURCE: "", CONF_VALVE_POSITIONS: [], CONF_VALVE_LEVEL: "",
    CONF_ASSOCIATED_CLIMATE: "",
    CONF_NOTIFY_SERVICE: "", CONF_NOTIFY_MESSAGE: "",
    CONF_AC_FRACTION: "", CONF_SUMMER: "", CONF_ZONE_SEASON: "", CONF_COOL_SOURCES: [],
}


class SuperThermostatConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["zone", "zone_hybrid", "boiler", "fraction", "ac"])

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_TYPE: TYPE_ZONE, **user_input},
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_TEMP_ENTITY): _temp_sensor(),
                vol.Optional(CONF_OUTDOOR_ENTITY): _temp_sensor(),
                vol.Required(CONF_ALLOWED, default=ALLOWED_HEAT): ALLOWED_SELECTOR,
                vol.Required(CONF_CYCLE, default=DEFAULT_ZONE_OPTIONS[CONF_CYCLE]): _num(5, 240, 1, "min"),
            }
        )
        return self.async_show_form(step_id="zone", data_schema=schema)

    async def async_step_zone_hybrid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_TYPE: TYPE_ZONE_HYBRID, **user_input},
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_TEMP_ENTITY): _temp_sensor(),
                vol.Optional(CONF_OUTDOOR_ENTITY): _temp_sensor(),
                vol.Optional(CONF_FRACTION_ENTITY): _numeric_entity(),
                vol.Optional(CONF_ASSOCIATED_CLIMATE): sel.EntitySelector(
                    sel.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_ALLOWED, default=ALLOWED_ALL): ALLOWED_SELECTOR,
                vol.Required(CONF_CYCLE, default=10): _num(5, 60, 1, "min"),
            }
        )
        return self.async_show_form(step_id="zone_hybrid", data_schema=schema)

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if any(e.data.get(CONF_TYPE) == TYPE_BOILER for e in self._async_current_entries()):
            return self.async_abort(reason="single_boiler")
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_TYPE: TYPE_BOILER, **user_input},
            )
        schema = vol.Schema({vol.Required(CONF_NAME, default="Chaudière"): str}).extend(
            BOILER_SENSORS.schema
        )
        return self.async_show_form(step_id="boiler", data_schema=schema)

    async def async_step_ac(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data={CONF_TYPE: TYPE_AC, **user_input}
            )
        schema = vol.Schema({vol.Required(CONF_NAME, default="Clim"): str}).extend(AC_ENTITIES.schema)
        return self.async_show_form(step_id="ac", data_schema=schema)

    async def async_step_fraction(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data={CONF_TYPE: TYPE_FRACTION, **user_input}
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Fraction chaudière"): str,
                vol.Required(CONF_FRACTION_SOURCE): _temp_sensor(),
                vol.Required(
                    CONF_FALLBACK_TEMP, default=DEFAULT_FRACTION_OPTIONS[CONF_FALLBACK_TEMP]
                ): _num(-30, 40, 0.5, "°C"),
                vol.Required(
                    CONF_SEUIL_HAUT, default=DEFAULT_FRACTION_OPTIONS[CONF_SEUIL_HAUT]
                ): _num(-30, 40, 0.5, "°C"),
                vol.Required(
                    CONF_SEUIL_BAS, default=DEFAULT_FRACTION_OPTIONS[CONF_SEUIL_BAS]
                ): _num(-30, 40, 0.5, "°C"),
                vol.Required(
                    CONF_MIN_FRACTION, default=DEFAULT_FRACTION_OPTIONS[CONF_MIN_FRACTION]
                ): _num(0, 50, 1, "%"),
            }
        )
        return self.async_show_form(step_id="fraction", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> "SuperThermostatOptionsFlow":
        return SuperThermostatOptionsFlow()


class SuperThermostatOptionsFlow(OptionsFlow):
    """Menu d'options : on modifie plusieurs rubriques puis on enregistre."""

    _opts: dict[str, Any] | None = None

    def _current(self) -> dict[str, Any]:
        defaults = {
            TYPE_ZONE: DEFAULT_ZONE_OPTIONS,
            TYPE_ZONE_HYBRID: DEFAULT_ZONE_OPTIONS,  # mêmes valeurs par défaut que zone simple
            TYPE_BOILER: DEFAULT_BOILER_OPTIONS,
            TYPE_FRACTION: DEFAULT_FRACTION_OPTIONS,
            TYPE_AC: DEFAULT_AC_OPTIONS,
        }[self.config_entry.data[CONF_TYPE]]
        return {**defaults, **self.config_entry.data, **(self._opts or {})}

    async def _form(self, step_id: str, schema: vol.Schema, user_input) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id=step_id,
                data_schema=self.add_suggested_values_to_schema(schema, self._current()),
            )
        opts = self._opts if self._opts is not None else dict(self.config_entry.options)
        for key in schema.schema:
            name = str(key)
            if name in CLEARABLE and name not in user_input:
                opts[name] = CLEARABLE[name]
        opts.update(user_input)
        self._opts = opts
        return await self.async_step_init()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._opts is None:
            self._opts = dict(self.config_entry.options)
        kind = self.config_entry.data[CONF_TYPE]
        if kind in (TYPE_ZONE, TYPE_ZONE_HYBRID):
            menu = ["zone_sensors", "valves", "regulation", "windows", "notifications", "save"]
        elif kind == TYPE_BOILER:
            menu = ["boiler_sensors", "tuning", "notifications", "save"]
        elif kind == TYPE_AC:
            menu = ["ac_entities", "ac_tuning", "save"]
        else:
            menu = ["fraction_source", "save"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_zone_sensors(self, user_input=None) -> ConfigFlowResult:
        return await self._form("zone_sensors", ZONE_SENSORS, user_input)

    async def async_step_valves(self, user_input=None) -> ConfigFlowResult:
        return await self._form("valves", ZONE_VALVES, user_input)

    async def async_step_notifications(self, user_input=None) -> ConfigFlowResult:
        return await self._form("notifications", _notify_schema(self.hass), user_input)

    async def async_step_regulation(self, user_input=None) -> ConfigFlowResult:
        return await self._form("regulation", ZONE_REGULATION, user_input)

    async def async_step_windows(self, user_input=None) -> ConfigFlowResult:
        return await self._form("windows", ZONE_WINDOWS, user_input)

    async def async_step_boiler_sensors(self, user_input=None) -> ConfigFlowResult:
        return await self._form("boiler_sensors", BOILER_SENSORS, user_input)

    async def async_step_tuning(self, user_input=None) -> ConfigFlowResult:
        return await self._form("tuning", BOILER_TUNING, user_input)

    async def async_step_fraction_source(self, user_input=None) -> ConfigFlowResult:
        return await self._form("fraction_source", FRACTION_SOURCE, user_input)

    async def async_step_ac_entities(self, user_input=None) -> ConfigFlowResult:
        return await self._form("ac_entities", AC_ENTITIES, user_input)

    async def async_step_ac_tuning(self, user_input=None) -> ConfigFlowResult:
        return await self._form("ac_tuning", AC_TUNING, user_input)

    async def async_step_save(self, user_input=None) -> ConfigFlowResult:
        return self.async_create_entry(data=self._opts or {})
