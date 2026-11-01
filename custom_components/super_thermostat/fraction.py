"""Fraction chaudière : part de la chaleur confiée à la chaudière (le reste à la clim).

Remplace le template « Fraction Chaudière Extérieure » :
  0 % au-dessus de seuil_haut, 100 % sous seuil_bas, linéaire entre les deux,
  d'après une température de référence = valeur d'une entité OU moyenne de
  la veille de cette entité (lue dans l'historique, donc stable toute la journée).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FALLBACK_TEMP, CONF_FRACTION_MODE, CONF_FRACTION_SOURCE, DEFAULT_FRACTION_OPTIONS,
    CONF_MIN_FRACTION, CONF_SEUIL_BAS, CONF_SEUIL_HAUT, DOMAIN, MODE_YESTERDAY, STORAGE_VERSION,
)
from .fraction_logic import fraction_from_temp, time_weighted_mean
from .helpers import read_number

_LOGGER = logging.getLogger(__name__)


class FractionController:
    model = "Répartition chaudière / clim"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**DEFAULT_FRACTION_OPTIONS, **entry.data, **entry.options}
        self.values = {
            "seuil_haut": float(self.cfg[CONF_SEUIL_HAUT]),
            "seuil_bas": float(self.cfg[CONF_SEUIL_BAS]),
        }
        self.ref_temp: float | None = None
        self.ref_source = "fallback"
        self.ref_date: str | None = None
        self._cached_temp: float | None = None
        self._cached_date: str | None = None
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def min_fraction(self) -> float:
        return float(self.cfg[CONF_MIN_FRACTION])

    @property
    def raw_fraction(self) -> float:
        temp = self.ref_temp if self.ref_temp is not None else float(self.cfg[CONF_FALLBACK_TEMP])
        return fraction_from_temp(temp, self.values["seuil_haut"], self.values["seuil_bas"])

    @property
    def fraction(self) -> float:
        """Sous la fraction minimale, les radiateurs sont trop peu ouverts : la chaudière n'est pas utilisée."""
        raw = self.raw_fraction
        return 0.0 if raw < self.min_fraction else raw

    # -------------------------------------------------------------- listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        @callback
        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ---------------------------------------------------------------- storage
    def _data(self) -> dict[str, Any]:
        return {
            "ref_temp": self.ref_temp if self.ref_source == "history" else self._cached_temp,
            "ref_date": self.ref_date if self.ref_source == "history" else self._cached_date,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, 10)

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self._cached_temp = data.get("ref_temp")
            self._cached_date = data.get("ref_date")

    # -------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        source = self.cfg[CONF_FRACTION_SOURCE]
        if self.cfg[CONF_FRACTION_MODE] == MODE_YESTERDAY:
            self._unsubs.append(
                async_track_time_change(self.hass, self._daily, hour=0, minute=5, second=0)
            )
        else:
            self._unsubs.append(async_track_state_change_event(self.hass, [source], self._on_source))
        unsub = async_at_started(self.hass, self._started)
        if unsub:
            self._unsubs.append(unsub)

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _on_source(self, _event: Event) -> None:
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _daily(self, _now: Any) -> None:
        self.hass.async_create_task(self.async_refresh())

    # ---------------------------------------------------------------- calculs
    async def _yesterday_mean(self) -> float | None:
        """Moyenne pondérée par le temps de l'entité sur la journée d'hier."""
        entity = self.cfg[CONF_FRACTION_SOURCE]
        end = dt_util.start_of_local_day()
        start = end - timedelta(days=1)
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import get_significant_states

            fetch = partial(
                get_significant_states, self.hass, start, end,
                entity_ids=[entity], include_start_time_state=True,
                significant_changes_only=False, minimal_response=False, no_attributes=True,
            )
            states = await get_instance(self.hass).async_add_executor_job(fetch)
        except Exception:  # noqa: BLE001 — recorder absent / API différente : on retombe sur le cache
            _LOGGER.exception("%s : lecture de l'historique impossible", self.entry.title)
            return None
        points: list[tuple[float, float]] = []
        for state in states.get(entity, []):
            try:
                points.append((state.last_changed.timestamp(), float(state.state)))
            except (ValueError, TypeError, AttributeError):
                continue
        return time_weighted_mean(points, start.timestamp(), end.timestamp())

    async def async_refresh(self) -> None:
        source = self.cfg[CONF_FRACTION_SOURCE]
        today = dt_util.now().date().isoformat()
        if self.cfg[CONF_FRACTION_MODE] == MODE_YESTERDAY:
            temp = await self._yesterday_mean()
            if temp is not None:
                self.ref_temp, self.ref_source, self.ref_date = round(temp, 1), "history", today
                self._cached_temp, self._cached_date = self.ref_temp, today
            elif self._cached_temp is not None:
                self.ref_temp, self.ref_source, self.ref_date = self._cached_temp, "cache", self._cached_date
            else:
                self.ref_temp, self.ref_source, self.ref_date = None, "fallback", None
        else:
            temp = read_number(self.hass, source, temperature=True)
            self.ref_temp = temp
            self.ref_source = "entity" if temp is not None else "fallback"
            self.ref_date = today if temp is not None else None
        self._save()
        self._notify()
