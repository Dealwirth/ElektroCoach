"""Home Assistant integration.

Uses the supervisor API that Home Assistant provides to add-ons:

* ``SUPERVISOR_TOKEN`` authenticates against ``http://supervisor/core/api``.
* ``POST /api/services/<domain>/<service>`` sends a notification.
* ``POST /api/states/<entity_id>`` publishes a sensor value.

Requirements respected here:

* **No unnecessary event-bus traffic.** Sensor states are only written when the
  value actually changed, and at most once per configured interval.
* **No hard dependency.** If the supervisor API is unreachable, every method
  degrades to a no-op and records why; the rest of the app keeps working.
* Notifications are queued in the database first, so nothing is lost when the
  API is briefly unavailable, and they can be retried.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("elektrocoach.integrations.homeassistant")

SUPERVISOR_BASE = "http://supervisor/core/api"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 15.0

# Minimum seconds between two state writes of the same entity.
MIN_STATE_INTERVAL = 30.0

SENSOR_DEFINITIONS = [
    ("sensor.elektrocoach_lernfortschritt", "Lernfortschritt", "%", "mdi:school-outline"),
    ("sensor.elektrocoach_faellige_wiederholungen", "Fällige Wiederholungen",
     "", "mdi:repeat"),
    ("sensor.elektrocoach_offene_aufgaben", "Offene Aufgaben", "", "mdi:clipboard-list"),
    ("sensor.elektrocoach_naechste_wiederholung", "Nächste Wiederholung",
     "", "mdi:calendar-clock"),
    ("sensor.elektrocoach_systemstatus", "Systemstatus", "", "mdi:heart-pulse"),
    ("sensor.elektrocoach_ki_verfuegbarkeit", "KI-Verfügbarkeit", "",
     "mdi:robot-outline"),
    ("sensor.elektrocoach_gemini_kontingent", "Gemini-Kontingent", "Anfragen",
     "mdi:counter"),
    ("sensor.elektrocoach_speicher_frei", "Freier Speicher", "GB", "mdi:harddisk"),
    ("sensor.elektrocoach_dokumente", "Dokumente", "", "mdi:file-document-multiple"),
    ("sensor.elektrocoach_wissenseintraege", "Wissenseinträge", "", "mdi:book-open-variant"),
    ("sensor.elektrocoach_fehler", "Ungelöste Fehler", "", "mdi:alert-circle-outline"),
    ("sensor.elektrocoach_letztes_backup", "Letztes Backup", "", "mdi:backup-restore"),
]

NOTIFICATION_LEVELS = {
    "info": "notify",
    "warning": "notify",
    "error": "notify",
    "critical": "persistent_notification",
}


class HomeAssistantClient:
    def __init__(self, token: str, *, base_url: str = SUPERVISOR_BASE,
                 notifications_enabled: bool = True,
                 notify_service: str = "") -> None:
        self.token = (token or "").strip()
        self.base_url = base_url.rstrip("/")
        self.notifications_enabled = notifications_enabled
        self.notify_service = notify_service.strip()
        self._client: httpx.AsyncClient | None = None
        self._last_state_write: dict[str, float] = {}
        self._last_values: dict[str, Any] = {}
        self._available: bool | None = None
        self._last_error: str | None = None

    # -- lifecycle ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    # -- connectivity ---------------------------------------------------------

    async def check(self) -> dict[str, Any]:
        if not self.token:
            self._available = False
            self._last_error = "Es ist kein SUPERVISOR_TOKEN vorhanden."
            return {"available": False, "reason": "no_token",
                    "message": self._last_error}
        try:
            response = await self._http().get("/", timeout=CONNECT_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            self._available = True
            self._last_error = None
            return {"available": True, "message": data.get("message", "API erreichbar"),
                    "location_name": data.get("location_name"),
                    "version": data.get("version")}
        except httpx.HTTPStatusError as exc:
            self._available = False
            self._last_error = f"Die Home-Assistant-API antwortete mit {exc.response.status_code}."
            return {"available": False, "reason": "http_error",
                    "message": self._last_error}
        except httpx.HTTPError as exc:
            self._available = False
            self._last_error = f"Die Home-Assistant-API ist nicht erreichbar: {exc}"
            return {"available": False, "reason": "unreachable",
                    "message": self._last_error}

    @property
    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "available": self._available,
            "last_error": self._last_error,
            "notifications_enabled": self.notifications_enabled,
            "notify_service": self.notify_service or "(Standarddienst)",
            "sensors_tracked": len(self._last_values),
        }

    # -- states ---------------------------------------------------------------

    async def set_state(self, entity_id: str, state: Any, *, attributes: dict | None = None,
                        force: bool = False) -> bool:
        if not self.token:
            return False
        value = state
        now = time.monotonic()
        previous = self._last_values.get(entity_id)
        if not force:
            if previous == value:
                return False
            last_write = self._last_state_write.get(entity_id, 0.0)
            if now - last_write < MIN_STATE_INTERVAL:
                return False
        payload = {
            "state": "" if value is None else str(value),
            "attributes": {
                "friendly_name": _friendly_name(entity_id),
                "icon": _icon(entity_id),
                **(attributes or {}),
            },
        }
        try:
            response = await self._http().post(f"/states/{entity_id}", json=payload)
            response.raise_for_status()
            self._last_state_write[entity_id] = now
            self._last_values[entity_id] = value
            return True
        except httpx.HTTPError as exc:
            self._last_error = f"Status {entity_id} konnte nicht gesetzt werden: {exc}"
            logger.debug("state write failed for %s: %s", entity_id, exc)
            return False

    async def publish_sensors(self, values: dict[str, Any]) -> dict[str, Any]:
        """Publish a batch of sensor values, skipping unchanged ones."""

        written: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []
        for entity_id, value in values.items():
            if entity_id in self._last_values and self._last_values[entity_id] == value:
                skipped.append(entity_id)
                continue
            ok = await self.set_state(entity_id, value)
            (written if ok else skipped).append(entity_id)
        return {"written": written, "skipped": skipped, "failed": failed}

    # -- notifications --------------------------------------------------------

    async def notify(self, title: str, message: str, *, level: str = "info") -> dict[str, Any]:
        if not self.notifications_enabled:
            return {"sent": False, "reason": "disabled"}
        if not self.token:
            return {"sent": False, "reason": "no_token",
                    "message": "Es ist kein SUPERVISOR_TOKEN vorhanden."}

        service = self.notify_service or "persistent_notification"
        if "/" in service:
            domain, _, name = service.partition("/")
        elif "." in service:
            domain, _, name = service.partition(".")
        else:
            domain, name = "persistent_notification", service or "create"

        payload: dict[str, Any] = {"title": title, "message": message}
        if domain == "persistent_notification":
            name = "create"
            payload["notification_id"] = f"elektrocoach_{abs(hash(title)) % 100000}"

        try:
            response = await self._http().post(f"/services/{domain}/{name}", json=payload)
            response.raise_for_status()
            return {"sent": True, "service": f"{domain}.{name}"}
        except httpx.HTTPError as exc:
            self._last_error = f"Benachrichtigung fehlgeschlagen: {exc}"
            logger.warning("notification failed: %s", exc)
            return {"sent": False, "reason": "http_error", "message": str(exc)}

    async def flush_pending(self, repo, limit: int = 10) -> dict[str, Any]:
        """Send queued notifications. Safe to call periodically."""

        pending = repo.pending_notifications(limit=limit)
        sent = 0
        failed = 0
        for record in pending:
            result = await self.notify(record["title"], record["message"],
                                       level=record["level"])
            if result.get("sent"):
                repo.mark_notification(int(record["id"]), status="sent")
                sent += 1
            elif result.get("reason") == "disabled":
                repo.mark_notification(int(record["id"]), status="skipped",
                                       error="Benachrichtigungen sind deaktiviert.")
                failed += 1
            else:
                repo.mark_notification(int(record["id"]), status="failed",
                                       error=result.get("message") or result.get("reason"))
                failed += 1
        return {"sent": sent, "failed": failed, "pending": len(pending)}

    # -- calibration ----------------------------------------------------------

    async def sync_clock(self) -> dict[str, Any]:
        try:
            response = await self._http().get("/", timeout=CONNECT_TIMEOUT)
            response.raise_for_status()
            return {"ok": True, "config": response.json()}
        except httpx.HTTPError as exc:
            return {"ok": False, "message": str(exc)}


def _friendly_name(entity_id: str) -> str:
    for known, name, _unit, _icon in SENSOR_DEFINITIONS:
        if known == entity_id:
            return f"ElektroCoach {name}"
    return entity_id.split(".")[-1].replace("_", " ").title()


def _icon(entity_id: str) -> str:
    for known, _name, _unit, icon in SENSOR_DEFINITIONS:
        if known == entity_id:
            return icon
    return "mdi:information-outline"
