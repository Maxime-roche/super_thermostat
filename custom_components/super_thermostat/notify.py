"""Notifications de défaillance (service de notification + message), sans doublons."""
from __future__ import annotations

import logging
import time
from string import Template

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GRACE_SECONDS = 300  # une défaillance doit durer 5 min avant d'être notifiée (évite les faux positifs au démarrage)


async def async_send(hass: HomeAssistant, service: str, title: str, message: str) -> None:
    """Appelle un service de notification (« notify.mobile_app_x » ou simplement « mobile_app_x »)."""
    domain, _, name = service.partition(".") if "." in service else ("notify", "", service)
    if not hass.services.has_service(domain, name):
        _LOGGER.warning("Service de notification introuvable : %s.%s", domain, name)
        return
    await hass.services.async_call(domain, name, {"title": title, "message": message}, blocking=False)


class FailureNotifier:
    """Envoie un message à chaque nouvelle défaillance (une fois, après un court délai de confirmation)."""

    def __init__(self, hass: HomeAssistant, title: str, service: str | None, message: str | None) -> None:
        self.hass = hass
        self.title = title
        self.service = service or ""
        self.message = message or "$nom : $cause"
        self._since: dict[str, float] = {}
        self._sent: set[str] = set()

    def render(self, cause: str) -> str:
        return Template(self.message).safe_substitute(nom=self.title, cause=cause)

    def update(self, failures: dict[str, tuple[bool, str]]) -> None:
        """failures : {clé: (active ?, cause en français)}."""
        now = time.time()
        for key, (active, cause) in failures.items():
            if not active:
                self._since.pop(key, None)
                self._sent.discard(key)
                continue
            self._since.setdefault(key, now)
            if self.service and key not in self._sent and now - self._since[key] >= GRACE_SECONDS:
                self._sent.add(key)
                self.hass.async_create_task(async_send(self.hass, self.service, self.title, self.render(cause)))
