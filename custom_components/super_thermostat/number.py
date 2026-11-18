"""Nombres réglables : coefficients, offsets, presets, seuils d'eau."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_TYPE, COOL_OFF, PRESET_LABELS, TYPE_BOILER, TYPE_ZONE, TYPE_ZONE_HYBRID
from .entity import ControllerEntity

COEFF_UNIT = "%/°C"


@dataclass(frozen=True)
class Spec:
    key: str
    min: float
    max: float
    step: float
    unit: str | None = None
    device_class: NumberDeviceClass | None = None


def _zone_specs(c) -> list[Spec]:
    specs: list[Spec] = []
    if c.has_heat:
        specs += [
            Spec("coeff_in_heat", 0, 300, 0.01, COEFF_UNIT),
            Spec("coeff_out_heat", 0, 300, 0.01, COEFF_UNIT),
            Spec("offset_heat", -50, 50, 1, PERCENTAGE),
        ]
    if c.has_cool:
        specs += [
            Spec("coeff_in_cool", 0, 300, 0.01, COEFF_UNIT),
            Spec("coeff_out_cool", 0, 300, 0.01, COEFF_UNIT),
            Spec("offset_cool", -50, 50, 1, PERCENTAGE),
        ]
    specs.append(Spec("delta_order", 0, 5, 0.1, UnitOfTemperature.CELSIUS))
    return specs


def _zone_hybrid_specs(c) -> list[Spec]:
    return [
        Spec("gain_boiler", 0.5, 30, 0.1, COEFF_UNIT),
        Spec("coeff_in_ac", 1, 100, 0.1, COEFF_UNIT),
        Spec("offset_ac", -50, 50, 1, PERCENTAGE),
    ]


def _preset_specs(c) -> list[tuple[Spec, str]]:
    """Deux consignes par préréglage (le nom vient de la configuration, donc pas de traduction)."""
    out: list[tuple[Spec, str]] = []
    for slug, shown in c.preset_names.items():
        name = PRESET_LABELS.get(slug, shown)
        if c.has_heat:
            out.append((Spec(f"preset_{slug}_heat", 5, 30, 0.5, UnitOfTemperature.CELSIUS,
                             NumberDeviceClass.TEMPERATURE), f"{name} : consigne chauffe"))
        if c.has_cool:
            out.append((Spec(f"preset_{slug}_cool", 16, COOL_OFF, 0.5, UnitOfTemperature.CELSIUS,
                             NumberDeviceClass.TEMPERATURE), f"{name} : consigne froid (35 = clim coupée)"))
    return out


BOILER_SPECS = [
    Spec("t_min", 10, 60, 1, UnitOfTemperature.CELSIUS, NumberDeviceClass.TEMPERATURE),
    Spec("t_max", 40, 95, 1, UnitOfTemperature.CELSIUS, NumberDeviceClass.TEMPERATURE),
    Spec("offset", 1, 30, 0.5, UnitOfTemperature.CELSIUS),
]

AC_SPECS = [
    Spec("offset_low", -10, 10, 0.5, UnitOfTemperature.CELSIUS),
    Spec("offset_high", -10, 10, 0.5, UnitOfTemperature.CELSIUS),
    Spec("cool_offset_low", -10, 10, 0.5, UnitOfTemperature.CELSIUS),
    Spec("cool_offset_high", -10, 10, 0.5, UnitOfTemperature.CELSIUS),
    Spec("fraction_cutoff", 0, 100, 1, PERCENTAGE),
]


class ControllerNumber(ControllerEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, controller, spec: Spec, name: str | None = None) -> None:
        super().__init__(controller, spec.key)
        if name is not None:
            self._attr_translation_key = None
            self._attr_name = name
        self._attr_native_min_value = spec.min
        self._attr_native_max_value = spec.max
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class

    @property
    def native_value(self) -> float:
        return self._ctrl.get_value(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        count = getattr(self._ctrl, "learn_count", lambda _k: None)(self._key)
        return {"learn_count": count} if count is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self._ctrl.async_set_value(self._key, value)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    kind = entry.data[CONF_TYPE]
    specs = (
        _zone_specs(c) if kind == TYPE_ZONE
        else _zone_hybrid_specs(c) if kind == TYPE_ZONE_HYBRID
        else BOILER_SPECS if kind == TYPE_BOILER
        else AC_SPECS
    )
    entities = [ControllerNumber(c, s) for s in specs]
    if kind in (TYPE_ZONE, TYPE_ZONE_HYBRID):
        entities += [ControllerNumber(c, s, name) for s, name in _preset_specs(c)]
    async_add_entities(entities)
