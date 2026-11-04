"""Migrations de configuration (Python pur, testable sans Home Assistant)."""
from __future__ import annotations

from typing import Any

from .const import (
    CONF_FRACTION_ENTITY, CONF_VALVE_CUSTOM, CONF_VALVE_KEEP_OPEN, CONF_VALVE_LEVEL,
    CONF_VALVE_MODE, CONF_VALVE_NEVER_CLOSE, CONF_VALVE_OPEN_MAX, CONF_VALVE_OPEN_MIN,
    CONF_VALVE_PROPORTIONAL, CONF_VALVE_SOURCE, CONF_VALVES,
)


def migrate_valve_options(data: dict[str, Any], options: dict[str, Any]) -> dict[str, Any] | None:
    """Anciennes vannes (mode proportionnel / fraction / personnalisé / demande) -> champ libre.

    Renvoie les nouvelles options, ou None s'il n'y a rien à migrer. Le comportement d'origine
    est conservé : « fraction » et « personnalisé » deviennent une entité suivie avec la plage 0-100 %
    (l'ouverture suit la valeur) et sans maintien de l'ouverture à 0.
    """
    cfg = {**data, **options}
    if not cfg.get(CONF_VALVES) or CONF_VALVE_SOURCE in cfg:
        return None
    mode = cfg.get(CONF_VALVE_MODE) or "fraction"  # sans mode enregistré, c'était le suivi de la fraction
    new = dict(options)
    new[CONF_VALVE_SOURCE] = ""
    new[CONF_VALVE_PROPORTIONAL] = True
    if mode in ("fraction", "custom"):
        source = cfg.get(CONF_FRACTION_ENTITY if mode == "fraction" else CONF_VALVE_CUSTOM) or ""
        new[CONF_VALVE_SOURCE] = source
        new[CONF_VALVE_OPEN_MIN], new[CONF_VALVE_OPEN_MAX] = 0, 100
        new[CONF_VALVE_KEEP_OPEN] = False
        new[CONF_VALVE_NEVER_CLOSE] = False
        if not source:  # pas d'entité : l'ancien mode ouvrait en grand
            new[CONF_VALVE_PROPORTIONAL] = False
            new[CONF_VALVE_LEVEL] = 100
    elif mode == "demand":
        new[CONF_VALVE_PROPORTIONAL] = False
        new[CONF_VALVE_LEVEL] = cfg.get(CONF_VALVE_LEVEL) or 100
        new[CONF_VALVE_KEEP_OPEN] = False
    return new
