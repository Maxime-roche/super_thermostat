"""Petits utilitaires de lecture d'états."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import PRESET_ALIASES, STANDARD_PRESETS


def read_number(
    hass: HomeAssistant,
    entity_id: str | None,
    max_age_min: float | None = None,
    *,
    temperature: bool = False,
) -> float | None:
    """Lit un état numérique ; None si absent, indisponible ou périmé."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    domain = entity_id.split(".", 1)[0]
    if domain == "weather":  # l'état est la condition météo, pas la température
        raw: Any = state.attributes.get("temperature")
    elif domain == "climate":
        raw = state.attributes.get("current_temperature")
    else:
        raw = state.state
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    unit = state.attributes.get("unit_of_measurement") or state.attributes.get("temperature_unit")
    if temperature and unit == UnitOfTemperature.FAHRENHEIT:
        value = (value - 32) * 5 / 9
    if max_age_min:
        last = max(state.last_updated, getattr(state, "last_reported", state.last_updated))
        if (dt_util.utcnow() - last).total_seconds() > max_age_min * 60:
            return None
    return value


def slugify_name(name: str) -> str:
    """Nom → identifiant ASCII stable (« Soirée » → « soiree »)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_") or "preset"


def parse_preset_names(text: str | None) -> dict[str, str]:
    """« Jour, Nuit, Parti » → {"home": "home", "sleep": "sleep", "away": "away"}.

    Les noms standards de Home Assistant (home, comfort, eco, sleep, away, boost, activity)
    et leurs équivalents français (Jour, Nuit, Parti…) donnent les icônes de la tuile ;
    tout autre nom reste tel quel (sans icône).
    """
    names: dict[str, str] = {}
    for raw in (text or "").split(","):
        name = raw.strip()
        if not name:
            continue
        slug = slugify_name(name)
        if slug in STANDARD_PRESETS:
            names.setdefault(slug, slug)
        elif slug in PRESET_ALIASES:
            names.setdefault(PRESET_ALIASES[slug], PRESET_ALIASES[slug])
        else:
            names.setdefault(slug, name)
    return names
