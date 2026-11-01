"""Calculs purs pour la fraction chaudière (testables sans Home Assistant)."""
from __future__ import annotations


def fraction_from_temp(temp: float, seuil_haut: float, seuil_bas: float) -> float:
    """100 % sous seuil_bas, 0 % au-dessus de seuil_haut, linéaire entre les deux.

    Reproduit le template « Fraction Chaudière Extérieure ».
    """
    span = seuil_haut - seuil_bas
    if span <= 0:
        ratio = 1.0 if temp < seuil_haut else 0.0
    else:
        ratio = (seuil_haut - temp) / span
    ratio = max(0.0, min(1.0, ratio))
    return round(ratio * 100, 1)


def time_weighted_mean(
    points: list[tuple[float, float]], start: float, end: float
) -> float | None:
    """Moyenne pondérée par le temps d'une série (timestamp, valeur).

    Chaque valeur est valable jusqu'au point suivant ; le premier point est
    ramené au début de la fenêtre, le dernier court jusqu'à la fin.
    """
    pts = sorted((max(ts, start), v) for ts, v in points if ts < end)
    if not pts or end <= start:
        return None
    total = 0.0
    for i, (ts, value) in enumerate(pts):
        nxt = pts[i + 1][0] if i + 1 < len(pts) else end
        total += value * max(0.0, nxt - ts)
    covered = end - pts[0][0]
    return total / covered if covered > 0 else None
