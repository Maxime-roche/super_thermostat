"""Moteur « temporel » de la zone — portage du plugin thermostat de Jeedom.

Module en Python pur (aucun import Home Assistant) : il peut être testé seul.

Principe (identique à Jeedom) :
    puissance % = dir * (consigne - T_int) * coeff_int
                + dir * (consigne - T_ext) * coeff_ext
                + offset
bornée entre 0 et 100, recalculée à chaque cycle, avec auto-apprentissage des
coefficients à partir de la montée en température observée entre deux cycles.

Écarts volontaires par rapport au PHP d'origine (tous marqués « ÉCART ») :
  * l'estimation instantanée d'un coefficient est bornée (x3 / ÷3) pour qu'une
    mesure aberrante (sonde qui bouge de 0,1 °C) ne fausse pas l'apprentissage ;
  * l'offset « cycle précédent chaud » ne peut jamais devenir négatif.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

HEAT = "heat"
COOL = "cool"
STOP = "stop"

MAX_LEARN_COUNT = 50  # « 50 = apprentissage terminé » dans Jeedom
LEARN_MAX_RATIO = 3.0  # ÉCART : garde-fou sur une mesure d'apprentissage
MANUAL_CONFIDENCE = 10  # compteur appliqué quand l'utilisateur fixe un coeff à la main


@dataclass
class ZoneParams:
    """Réglages (modifiables à chaud)."""

    cycle_min: float = 60.0
    min_power: float = 5.0  # minCycleDuration (%)
    limit_cycles: bool = False  # « limiter les cycles marche/arrêt » (stove_boiler)
    autolearn: bool = True
    offset_heat: float = 0.0
    offset_cool: float = 0.0
    heat_allowed: bool = True
    cool_allowed: bool = True
    threshold_hot: float = 100.0  # threshold_heathot
    offset_next_full: float = 0.0  # offset_nextFullCyle (0 = désactivé)
    dir_delta_heat: float = 0.0  # direction::delta::heat
    dir_delta_cool: float = 0.0  # direction::delta::cool
    fail_offset_heat: float = 1.0  # offsetHeatFaillure
    fail_offset_cool: float = 1.0  # offsetColdFaillure
    delta_order: float = 0.0  # « Delta consigne »
    forced_direction: int = 0  # +1 chauffe / -1 froid imposés par la zone (0 = déduit de la température)


@dataclass
class ZoneState:
    """État persistant (coefficients appris + mémoire du cycle précédent)."""

    coeff_in_heat: float = 10.0
    coeff_out_heat: float = 2.0
    coeff_in_cool: float = 10.0
    coeff_out_cool: float = 2.0
    n_in_heat: int = 1
    n_out_heat: int = 1
    n_in_cool: int = 1
    n_out_cool: int = 1
    last_order: float = 0.0
    last_temp_in: float = 0.0
    last_temp_out: float = 0.0
    last_power: float = 0.0
    last_state: str = STOP
    nb_failures: int = 0
    end_date: float = 0.0  # timestamp avant lequel on n'apprend pas

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ZoneState":
        state = cls()
        if not data:
            return state
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in names:
                setattr(state, key, type(getattr(state, key))(value))
        return state

    @property
    def actuator_failure(self) -> bool:
        return self.nb_failures >= 2

    def interrupt(self) -> None:
        """Appelé quand la zone s'arrête (Off, fenêtre, panne sonde).

        On oublie le cycle précédent pour ne pas apprendre sur un cycle
        interrompu.
        """
        self.last_state = STOP
        self.last_power = 0.0

    def reset_learning(self) -> None:
        fresh = ZoneState()
        for name in (
            "coeff_in_heat", "coeff_out_heat", "coeff_in_cool", "coeff_out_cool",
            "n_in_heat", "n_out_heat", "n_in_cool", "n_out_cool",
            "nb_failures", "end_date",
        ):
            setattr(self, name, getattr(fresh, name))
        self.interrupt()


@dataclass
class CycleResult:
    power: int = 0  # 0..100, déjà arrondi
    state: str = STOP  # HEAT / COOL / STOP
    direction: int = 0
    learned: list[str] = field(default_factory=list)


def calc_temporal(
    p: ZoneParams,
    s: ZoneState,
    consigne: float,
    temp_in: float,
    temp_out: float | None,
    allow_overfull: bool = False,
) -> tuple[float, int]:
    """Équivalent de calculTemporalData() : renvoie (puissance, direction)."""
    if temp_out is None:
        temp_out = consigne

    diff_in = consigne - temp_in
    diff_out = consigne - temp_out

    if p.forced_direction:
        # zone à deux consignes : le sens est déjà choisi (saison / température)
        direction = 1 if p.forced_direction > 0 else -1
    else:
        direction = 1 if consigne > temp_in else -1
        if direction < 0 and (
            (temp_in < consigne + 0.5 and s.last_state == HEAT)
            or (consigne - temp_out) > p.dir_delta_heat
        ):
            direction = 1
        if direction > 0 and (
            (temp_in > consigne - 0.5 and s.last_state == COOL)
            or (consigne - temp_out) < p.dir_delta_cool
        ):
            direction = -1

    if temp_in >= consigne + 1.5 and direction == 1:
        return 0.0, direction
    if temp_in <= consigne - 1.5 and direction == -1:
        return 0.0, direction

    if direction > 0:
        coeff_out, coeff_in, offset = s.coeff_out_heat, s.coeff_in_heat, p.offset_heat
    else:
        coeff_out, coeff_in, offset = s.coeff_out_cool, s.coeff_in_cool, p.offset_cool

    power = direction * diff_in * coeff_in + direction * diff_out * coeff_out + offset

    if (
        not allow_overfull
        and p.offset_next_full > 0
        and s.last_power >= p.threshold_hot
    ):
        if s.last_power >= 100:
            power -= p.offset_next_full
        else:
            # ÉCART : jamais négatif (dans le PHP, on pouvait ajouter de la puissance)
            power -= max(0.0, p.offset_next_full - (100 - s.last_power))

    if power > 100 and not allow_overfull:
        power = 100.0
    if power < 0:
        power = 0.0
    return power, direction


def _avg(old: float, new: float, n: int) -> float:
    return (old * n + new) / (n + 1)


def _learn_indoor(s: ZoneState, kind: str, estimate: float) -> None:
    old = getattr(s, f"coeff_in_{kind}")
    n = getattr(s, f"n_in_{kind}")
    if old > 0:  # ÉCART : estimation bornée
        estimate = min(max(estimate, old / LEARN_MAX_RATIO), old * LEARN_MAX_RATIO)
    value = _avg(old, estimate, n)
    setattr(s, f"n_in_{kind}", min(n + 1, MAX_LEARN_COUNT))
    setattr(s, f"coeff_in_{kind}", round(max(value, 0.0), 2))


def _learn_outdoor(s: ZoneState, kind: str, ratio: float) -> None:
    coeff_in = getattr(s, f"coeff_in_{kind}")
    old = getattr(s, f"coeff_out_{kind}")
    n = getattr(s, f"n_out_{kind}")
    ratio = max(-LEARN_MAX_RATIO, min(LEARN_MAX_RATIO, ratio))  # ÉCART : borné
    estimate = coeff_in * ratio + old
    value = _avg(old, estimate, n)
    setattr(s, f"n_out_{kind}", min(n + 1, MAX_LEARN_COUNT))
    setattr(s, f"coeff_out_{kind}", round(max(value, 0.0), 2))


def learn(
    s: ZoneState, temp_in: float, temp_out: float | None
) -> list[str]:
    """Auto-apprentissage, à appeler AVANT de recalculer le cycle."""
    learned: list[str] = []
    if s.last_state == HEAT:
        if temp_in > s.last_temp_in and s.last_order > s.last_temp_in:
            est = s.coeff_in_heat * (
                (s.last_order - s.last_temp_in) / (temp_in - s.last_temp_in)
            )
            _learn_indoor(s, "heat", est)
            learned.append("coeff_in_heat")
        elif temp_out is not None and temp_out < s.last_order:
            ratio = (s.last_order - temp_in) / (s.last_order - temp_out)
            _learn_outdoor(s, "heat", ratio)
            learned.append("coeff_out_heat")
    elif s.last_state == COOL:
        if temp_in < s.last_temp_in and s.last_order < s.last_temp_in:
            est = s.coeff_in_cool * (
                (s.last_temp_in - s.last_order) / (s.last_temp_in - temp_in)
            )
            _learn_indoor(s, "cool", est)
            learned.append("coeff_in_cool")
        elif temp_out is not None and temp_out > s.last_order:
            ratio = (s.last_order - temp_in) / (s.last_order - temp_out)
            _learn_outdoor(s, "cool", ratio)
            learned.append("coeff_out_cool")
    return learned


def run_cycle(
    p: ZoneParams,
    s: ZoneState,
    now: float,
    consigne: float,
    temp_in: float,
    temp_out: float | None,
) -> CycleResult:
    """Un cycle complet (équivalent de thermostat::temporal)."""
    result = CycleResult()

    # --- défaillance du chauffage / de la clim (2 cycles de suite) ---
    fail_heat = (
        temp_in < s.last_order - p.fail_offset_heat
        and temp_in < s.last_temp_in
        and s.last_state == HEAT
        and s.n_in_heat > 25
    )
    fail_cool = (
        temp_in > s.last_order + p.fail_offset_cool
        and temp_in > s.last_temp_in
        and s.last_state == COOL
        and s.n_in_cool > 25
    )
    if fail_heat or fail_cool:
        s.nb_failures += 1
    else:
        s.nb_failures = 0

    # --- auto-apprentissage ---
    if (
        s.nb_failures < 3
        and p.autolearn
        and now > s.end_date
        and 0 < s.last_power < 100
    ):
        result.learned = learn(s, temp_in, temp_out)

    # --- calcul, avec lissage « delta consigne » ---
    delta = p.delta_order
    if delta > 0:
        delta = delta / 2
    power, direction = calc_temporal(p, s, consigne - delta, temp_in, temp_out)
    if power > 0 and delta > 0:
        power, direction = calc_temporal(p, s, consigne + delta, temp_in, temp_out)
    result.direction = direction

    # --- mémoire du cycle ---
    s.last_power = power
    s.last_order = consigne
    s.last_temp_in = temp_in
    s.last_temp_out = temp_out if temp_out is not None else s.last_temp_out
    s.end_date = now + math.ceil(p.cycle_min * 0.9) * 60

    # --- puissance trop faible : on n'allume pas ---
    too_short = (not p.limit_cycles and power < p.min_power) or (
        (s.last_state == HEAT and power < 1)
        or (s.last_state != HEAT and power < p.min_power)
    )
    if too_short:
        s.last_state = STOP
        return result

    # --- changement de sens ---
    if s.last_state == HEAT and direction < 0:
        s.last_state = STOP
    elif s.last_state == COOL and direction > 0:
        s.last_state = STOP

    if direction > 0:
        if p.heat_allowed:
            s.last_state = HEAT
            result.state, result.power = HEAT, int(round(power))
        else:
            s.last_state = STOP
    else:
        if p.cool_allowed:
            s.last_state = COOL
            result.state, result.power = COOL, int(round(power))
        else:
            s.last_state = STOP
    return result


def resolve_sense(
    hvac_mode: str,
    summer: bool | None,
    temp_in: float,
    target_heat: float,
    target_cool: float,
    previous: str | None,
) -> str | None:
    """Sens actif d'une zone : HEAT, COOL ou None (rien à faire).

    * mode chauffe / froid : forcé ;
    * mode auto avec entité « saison » : été -> froid, hiver -> chauffe ;
    * mode auto sans saison : chauffe sous la consigne de chauffe, froid au-dessus de
      la consigne de froid, et entre les deux (zone morte) on garde le sens précédent.
    """
    if hvac_mode == "heat":
        return HEAT
    if hvac_mode == "cool":
        return COOL
    if summer is True:
        return COOL
    if summer is False:
        return HEAT
    if temp_in > target_cool:
        return COOL
    if temp_in < target_heat:
        return HEAT
    return previous
