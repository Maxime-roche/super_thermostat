"""Logique de la chaudière — Python pur (testable sans Home Assistant)."""
from __future__ import annotations

from collections.abc import Iterable


def total_demand(values: Iterable[float | None]) -> float:
    """Somme des puissances, plafonnée à 100 (valeurs absentes = 0)."""
    total = sum(v for v in values if v is not None and v > 0)
    return max(0.0, min(100.0, total))


def water_band(
    fraction: float, t_min: float, t_max: float, offset: float
) -> tuple[float, float]:
    """Seuils bas/haut de la température d'eau selon la fraction chaudière (loi d'eau).

    0 %   -> bas = t_min,            haut = t_min + offset
    100 % -> bas = t_max - offset,   haut = t_max
    (interpolation linéaire entre les deux)
    """
    f = max(0.0, min(100.0, fraction))
    span = max(t_max - offset - t_min, 0.0)
    low = t_min + (f / 100.0) * span
    return low, low + offset


def burner_target(
    *,
    demand: float,
    water: float | None,
    low: float,
    high: float,
    safety_max: float,
    currently_on: bool,
    since: float,
    now: float,
    min_on_s: float,
    min_off_s: float,
) -> bool:
    """Le brûleur doit-il être allumé ?

    Arrêt immédiat (sans respecter les durées mini) si : pas de demande,
    sonde d'eau absente, ou température de sécurité atteinte.
    """
    if demand <= 0 or water is None or water >= safety_max:
        return False
    if water < low:
        want = True
    elif water > high:
        want = False
    else:
        want = currently_on  # dans la bande : on ne change rien
    if want != currently_on:
        held = now - since
        if currently_on and held < min_on_s:
            return True
        if not currently_on and held < min_off_s:
            return False
    return want


def circulator_target(
    *,
    demand: float,
    currently_on: bool,
    zero_since: float | None,
    now: float,
    post_run_s: float,
) -> tuple[bool, float | None]:
    """Circulateur : allumé dès que la demande est positive, post-circulation
    optionnelle. Renvoie (état voulu, nouvelle valeur de zero_since)."""
    if demand > 0:
        return True, None
    if not currently_on:
        return False, None
    if post_run_s <= 0:
        return False, None
    zero_since = now if zero_since is None else zero_since
    return (now - zero_since) < post_run_s, zero_since
