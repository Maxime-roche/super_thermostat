"""Logique de la clim (chauffe et froid) — Python pur, testable sans Home Assistant.

Reprend l'automatisation « Clim bas - hiver » :
  * consigne = round(T_pièce_Daikin + décalage), décalage linéaire de
    offset_low (à 0 %) à offset_high (à 100 %) — par défaut -1 -> +3 en chauffe,
    +1 -> -3 en froid (symétrique, à ajuster) ;
  * allumage seulement si > start_delay depuis le dernier réglage ;
  * réajustement de la consigne au plus tous les adjust_interval ;
  * extinction quand il n'y a plus de demande.
Ajouts : coupure quand la fraction chaudière atteint le seuil réglable, et
durée mini d'allumage (protection du compresseur).
"""
from __future__ import annotations

BLOCK_FRACTION = "fraction_cutoff"
HEAT = "heat"
COOL = "cool"


def ac_setpoint(demand: float, t_room: float, offset_low: float, offset_high: float) -> int:
    offset = offset_low + (offset_high - offset_low) * (demand / 100)
    return int(round(t_room + offset))


def ac_block_reason(fraction: float | None, cutoff: float) -> str | None:
    """La clim ne chauffe plus quand la fraction chaudière atteint le seuil."""
    if fraction is not None and fraction >= cutoff:
        return BLOCK_FRACTION
    return None


def ac_resolve(
    *,
    heat_demand: float,
    cool_demand: float,
    fraction_blocked: bool,
    season_set: bool,
    summer: bool,
    has_cool_sources: bool,
) -> tuple[str | None, bool, bool]:
    """Sens à appliquer : (actif, extinction forcée, ne rien toucher)."""
    if season_set and summer:
        if not has_cool_sources:
            return None, False, True  # l'été est géré ailleurs : on ne touche à rien
        return (COOL if cool_demand > 0 else None), False, False
    if heat_demand > 0 and not fraction_blocked:
        return HEAT, False, False
    if cool_demand > 0 and has_cool_sources and not season_set:
        return COOL, False, False  # sans entité saison, le sens suit la demande
    return None, fraction_blocked, False


def ac_decide(
    *,
    active: str | None,
    force_off: bool,
    mode: str | None,
    now: float,
    last_change: float,
    on_since: float,
    start_delay_s: float,
    adjust_s: float,
    min_on_s: float,
    setpoint: int,
    current_target: float | None,
) -> list[str]:
    """Actions à faire : "mode_on", "setpoint", "off" (dans cet ordre)."""
    if mode is None:
        return []
    if active:
        if mode != active:
            return ["mode_on", "setpoint"] if now - last_change > start_delay_s else []
        if now - last_change > adjust_s and (
            current_target is None or abs(current_target - setpoint) >= 0.25
        ):
            return ["setpoint"]
        return []
    if mode != "off" and (force_off or now - on_since >= min_on_s):
        return ["off"]
    return []
