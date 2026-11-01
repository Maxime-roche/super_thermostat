"""Gestion de la clim réversible (chauffe) pilotée par la puissance des zones."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .ac_logic import COOL, HEAT, ac_block_reason, ac_decide, ac_resolve, ac_setpoint
from .boiler_logic import total_demand
from .const import (
    A_COOLING, A_DISABLED, A_FRACTION_CUTOFF, A_HEATING, A_IDLE, A_SUMMER, CONF_ADJUST_INTERVAL,
    CONF_AC_FRACTION, CONF_AC_MIN_ON, CONF_CLIMATE, CONF_COOL_SOURCES, CONF_MODE_DELAY, CONF_SOURCES,
    CONF_START_DELAY, CONF_SUMMER, DEFAULT_AC_OPTIONS, DOMAIN, STORAGE_VERSION,
)
from .helpers import read_number

_LOGGER = logging.getLogger(__name__)
TICK = timedelta(seconds=30)
FALLBACK_ROOM_TEMP = 21.0


class ACController:
    model = "Clim"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**DEFAULT_AC_OPTIONS, **entry.data, **entry.options}
        self.values = {
            "offset_low": -1.0, "offset_high": 3.0,  # chauffe : -1 °C à 0 % -> +3 °C à 100 %
            "cool_offset_low": 1.0, "cool_offset_high": -3.0,  # froid (symétrique, à ajuster)
            "fraction_cutoff": 100.0,
        }
        self.enabled = True
        self.dry_run = False

        self.demand = 0.0
        self.setpoint: int | None = None
        self.fraction: float | None = None
        self.status = A_IDLE
        self.pending: list[str] = []
        self.reason = "starting"
        self.diagnostic: dict[str, Any] = {}
        self.source_values: dict[str, float | None] = {}
        self.cool_values: dict[str, float | None] = {}
        self.active: str | None = None

        self._last_change = 0.0
        self._on_since = 0.0
        self._busy = False
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

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
            "values": self.values, "enabled": self.enabled, "dry_run": self.dry_run,
            "last_change": self._last_change, "on_since": self._on_since,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, 10)

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.values.update({k: float(v) for k, v in data.get("values", {}).items() if k in self.values})
            self.enabled = bool(data.get("enabled", True))
            self.dry_run = bool(data.get("dry_run", False))
            self._last_change = float(data.get("last_change", 0.0))
            self._on_since = float(data.get("on_since", 0.0))

    # -------------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        watched = [*self.cfg.get(CONF_SOURCES, []), *(self.cfg.get(CONF_COOL_SOURCES) or []), self.cfg[CONF_CLIMATE]]
        for key in (CONF_AC_FRACTION, CONF_SUMMER):
            if self.cfg.get(key):
                watched.append(self.cfg[key])
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._on_event))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, TICK))
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
        self._evaluate()

    @callback
    def _on_event(self, _event: Event) -> None:
        self._evaluate()

    @callback
    def _on_tick(self, _now: Any) -> None:
        self._evaluate()

    # ------------------------------------------------------------- évaluation
    @callback
    def _evaluate(self) -> None:
        if self._busy:
            return
        now = time.time()
        self.source_values = {
            e: read_number(self.hass, e) for e in self.cfg.get(CONF_SOURCES, [])
        }
        cool_sources = list(self.cfg.get(CONF_COOL_SOURCES) or [])
        self.cool_values = {e: read_number(self.hass, e) for e in cool_sources}
        heat_demand = total_demand(self.source_values.values())
        cool_demand = total_demand(self.cool_values.values())
        self.fraction = (
            read_number(self.hass, self.cfg[CONF_AC_FRACTION]) if self.cfg.get(CONF_AC_FRACTION) else None
        )
        season_set = bool(self.cfg.get(CONF_SUMMER))
        summer = season_set and self.hass.states.is_state(self.cfg[CONF_SUMMER], "on")

        cstate = self.hass.states.get(self.cfg[CONF_CLIMATE])
        mode = None if cstate is None or cstate.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else cstate.state
        t_room = FALLBACK_ROOM_TEMP
        target: float | None = None
        if cstate is not None:
            try:
                t_room = float(cstate.attributes.get("current_temperature"))
            except (TypeError, ValueError):
                pass
            try:
                target = float(cstate.attributes.get("temperature"))
            except (TypeError, ValueError):
                target = None

        block = ac_block_reason(self.fraction, self.values["fraction_cutoff"])
        active, force_off, hands_off = ac_resolve(
            heat_demand=heat_demand, cool_demand=cool_demand, fraction_blocked=block is not None,
            season_set=season_set, summer=summer, has_cool_sources=bool(cool_sources),
        )
        self.active = active
        self.demand = cool_demand if active == COOL else heat_demand
        if active == COOL:
            self.setpoint = ac_setpoint(
                self.demand, t_room, self.values["cool_offset_low"], self.values["cool_offset_high"]
            )
        else:
            self.setpoint = ac_setpoint(
                self.demand, t_room, self.values["offset_low"], self.values["offset_high"]
            )

        if not self.enabled or hands_off:
            actions: list[str] = []
            self.status = A_DISABLED if not self.enabled else A_SUMMER
        else:
            actions = ac_decide(
                active=active, force_off=force_off, mode=mode, now=now,
                last_change=self._last_change, on_since=self._on_since,
                start_delay_s=float(self.cfg[CONF_START_DELAY]) * 60,
                adjust_s=float(self.cfg[CONF_ADJUST_INTERVAL]) * 60,
                min_on_s=float(self.cfg[CONF_AC_MIN_ON]) * 60,
                setpoint=self.setpoint, current_target=target,
            )
            if block and active != COOL:
                self.status = A_FRACTION_CUTOFF
            elif active == COOL and (mode == "cool" or "mode_on" in actions):
                self.status = A_COOLING
            elif active == HEAT and (mode == "heat" or "mode_on" in actions):
                self.status = A_HEATING
            else:
                self.status = A_IDLE
        self.pending = actions

        # --- pourquoi (ne pas) agir : visible dans les attributs du statut ---
        if not self.enabled:
            reason = "disabled"
        elif hands_off:
            reason = "summer_entity_on"
        elif mode is None:
            reason = "climate_unavailable"
        elif actions:
            reason = "dry_run_would_act" if self.dry_run else "acting"
        elif block and active != HEAT and active != COOL:
            reason = "fraction_cutoff"
        elif active is None:
            reason = "no_demand"
        elif mode != active:
            reason = "waiting_start_delay"
        else:
            reason = "regulating"
        self.diagnostic = {
            "reason": reason,
            "active_sense": active,
            "demand": round(self.demand, 1),
            "sources": self.source_values,
            "cool_sources": self.cool_values,
            "fraction": self.fraction,
            "fraction_cutoff": self.values["fraction_cutoff"],
            "summer_entity_on": summer,
            "climate_mode": mode,
            "climate_current_temperature": t_room,
            "climate_target": target,
            "setpoint_computed": self.setpoint,
            "seconds_since_last_change": round(now - self._last_change) if self._last_change else None,
        }
        if reason != self.reason:
            _LOGGER.info(
                "%s : %s (sens %s, demande %.0f %%, fraction %s, clim %s, consigne calculée %s)",
                self.entry.title, reason, active, self.demand, self.fraction, mode, self.setpoint,
            )
            self.reason = reason
        if actions and not self.dry_run:
            self._busy = True
            self.hass.async_create_task(self._run(actions, self.setpoint, active))
        self._notify()

    async def _call(self, service: str, data: dict[str, Any]) -> None:
        await self.hass.services.async_call(
            "climate", service, {"entity_id": self.cfg[CONF_CLIMATE], **data}, blocking=True
        )

    async def _run(self, actions: list[str], setpoint: int, active: str | None) -> None:
        try:
            for action in actions:
                if action == "mode_on":
                    await self._call("set_hvac_mode", {"hvac_mode": active})
                    if "setpoint" in actions and float(self.cfg[CONF_MODE_DELAY]) > 0:
                        await asyncio.sleep(float(self.cfg[CONF_MODE_DELAY]))
                elif action == "setpoint":
                    await self._call("set_temperature", {"temperature": setpoint})
                elif action == "off":
                    await self._call("set_hvac_mode", {"hvac_mode": "off"})
            self._last_change = time.time()
            if "mode_on" in actions:
                self._on_since = self._last_change
            self._save()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("%s : échec de la commande clim %s", self.entry.title, actions)
        finally:
            self._busy = False
            self.pending = []
            self._notify()

    # ------------------------------------------------------------ commandes UI
    def get_value(self, key: str) -> float:
        return self.values[key]

    async def async_set_value(self, key: str, value: float) -> None:
        self.values[key] = float(value)
        self._save()
        self._evaluate()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._save()
        self._evaluate()

    async def async_set_dry_run(self, value: bool) -> None:
        self.dry_run = value
        self._save()
        self._evaluate()
