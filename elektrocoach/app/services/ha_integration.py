"""Home-Assistant-Integration.

Sensoren werden ueber MQTT-Discovery bereitgestellt. Das ist der
ressourcenschonende Weg: Home Assistant abonniert die Topics, die App
veroeffentlicht nur in einem festen Intervall. Es findet KEIN dauerhaftes
Event-Feuern ueber den Home-Assistant-Event-Bus statt.

Sensoren:
  * sensor.elektrocoach_fortschritt          (Lernfortschritt in Prozent)
  * sensor.elektrocoach_lernzeit_heute       (Lernzeit heute in Minuten)
  * sensor.elektrocoach_offene_wiederholungen (faellige Wiederholungen)
  * sensor.elektrocoach_fragen_gesamt        (Fragen in der Wissensbasis)
  * sensor.elektrocoach_trefferquote         (Trefferquote in Prozent)
  * sensor.elektrocoach_lernserie            (Tage in Folge)
  * sensor.elektrocoach_pruefung_best        (bestes Pruefungsergebnis)
  * sensor.elektrocoach_speicher_frei        (freier Speicher in MB)
  * sensor.elektrocoach_status               (Textstatus)

Zusaetzlich: Benachrichtigungen ueber den Supervisor-Dienst notify.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx

from .. import db
from ..config import SUPERVISOR_TOKEN, SUPERVISOR_URL, settings
from ..security import decrypt
from . import learning

log = logging.getLogger(__name__)

DEVICE_ID = "elektrocoach"
DEVICE_NAME = "ElektroCoach"
DISCOVERY_NODE = "elektrocoach"

_client: Any = None
_client_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_last_publish: float = 0.0


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
def _mqtt_settings() -> dict[str, Any]:
    return {
        "enabled": settings.get_bool("mqtt_enabled", False),
        "host": str(settings.get("mqtt_host", "core-mosquitto")),
        "port": settings.get_int("mqtt_port", 1883),
        "username": str(settings.get("mqtt_username", "") or ""),
        "password": _mqtt_password(),
        "prefix": str(settings.get("mqtt_discovery_prefix", "homeassistant") or "homeassistant"),
    }


def _mqtt_password() -> str:
    stored = db.get_setting("mqtt_password")
    if stored:
        return decrypt(settings.data_dir, stored)
    return str(settings.get("mqtt_password", "") or "")


def _connect() -> Any:
    global _client
    cfg = _mqtt_settings()
    if not cfg["enabled"]:
        return None
    try:
        import paho.mqtt.client as mqtt
    except Exception as exc:  # noqa: BLE001
        log.warning("paho-mqtt nicht verfuegbar: %s", exc)
        return None

    with _client_lock:
        if _client is not None:
            return _client
        try:
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)
            except (AttributeError, TypeError):
                client = mqtt.Client(client_id=DEVICE_ID)
            if cfg["username"]:
                client.username_pw_set(cfg["username"], cfg["password"])
            client.connect(cfg["host"], cfg["port"], keepalive=60)
            client.loop_start()
            _client = client
            log.info("MQTT verbunden mit %s:%s", cfg["host"], cfg["port"])
        except Exception as exc:  # noqa: BLE001
            log.warning("MQTT-Verbindung fehlgeschlagen: %s", exc)
            _client = None
    return _client


def _publish(topic: str, payload: str, retain: bool = True) -> bool:
    client = _connect()
    if client is None:
        return False
    try:
        client.publish(topic, payload, qos=0, retain=retain)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("MQTT-Publish fehlgeschlagen: %s", exc)
        return False


SENSOR_DEFS = [
    {"key": "progress", "name": "Fortschritt", "unit": "%", "icon": "mdi:percent",
     "state_class": "measurement", "value": lambda s: round(s["progress_percent"], 1)},
    {"key": "study_minutes", "name": "Lernzeit heute", "unit": "min", "icon": "mdi:timer-outline",
     "state_class": "measurement", "value": lambda s: s["today_minutes"]},
    {"key": "due_reviews", "name": "Offene Wiederholungen", "unit": "Aufgaben",
     "icon": "mdi:repeat", "state_class": "measurement", "value": lambda s: s["due_reviews"]},
    {"key": "questions", "name": "Fragen gesamt", "unit": "Fragen", "icon": "mdi:help-circle-outline",
     "state_class": "measurement", "value": lambda s: s["questions"]},
    {"key": "accuracy", "name": "Trefferquote", "unit": "%", "icon": "mdi:target",
     "state_class": "measurement", "value": lambda s: round(s["accuracy"] * 100, 1)},
    {"key": "streak", "name": "Lernserie", "unit": "Tage", "icon": "mdi:fire",
     "state_class": "measurement", "value": lambda s: s["streak_days"]},
    {"key": "best_exam", "name": "Bestes Pruefungsergebnis", "unit": "%",
     "icon": "mdi:school-outline", "state_class": "measurement",
     "value": lambda s: s["best_exam_score"] if s["best_exam_score"] is not None else 0},
    {"key": "free_space", "name": "Freier Speicher", "unit": "MB",
     "icon": "mdi:harddisk", "state_class": "measurement",
     "value": lambda s: s["free_space_mb"]},
    {"key": "status", "name": "Status", "icon": "mdi:information-outline",
     "state_class": None, "value": lambda s: s["status_text"]},
]


def collect_state() -> dict[str, Any]:
    stats = learning.dashboard_stats()
    from ..workers import import_worker

    free_mb = 0
    try:
        free_mb = int(import_worker.free_bytes() / (1024 * 1024))
    except Exception:  # noqa: BLE001
        free_mb = 0

    total = max(1, stats["topics"])
    covered_row = db.query_one(
        "SELECT COUNT(*) AS n FROM topics WHERE coverage > 0.15"
    )
    covered = int(covered_row["n"]) if covered_row else 0
    accuracy_part = stats["accuracy"]
    coverage_part = covered / total
    practice_part = min(1.0, stats["attempts"] / 500.0)
    progress = round(100 * (0.45 * accuracy_part + 0.35 * coverage_part + 0.20 * practice_part), 1)

    if stats["due_reviews"] > 0:
        status = f"{stats['due_reviews']} Wiederholungen faellig"
    elif stats["questions"] == 0:
        status = "Keine Fragen vorhanden"
    else:
        status = "Alles wiederholt"

    return {
        "progress_percent": progress,
        "today_minutes": stats["today_minutes"],
        "due_reviews": stats["due_reviews"],
        "questions": stats["questions"],
        "accuracy": stats["accuracy"],
        "streak_days": stats["streak_days"],
        "best_exam_score": stats["best_exam_score"],
        "free_space_mb": free_mb,
        "status_text": status,
        "documents": stats["documents"],
        "needs_review_pages": stats["needs_review_pages"],
    }


def publish_discovery() -> bool:
    cfg = _mqtt_settings()
    if not cfg["enabled"]:
        return False
    ok = True
    for sensor in SENSOR_DEFS:
        topic = f"{cfg['prefix']}/sensor/{DEVICE_ID}/{sensor['key']}/config"
        payload: dict[str, Any] = {
            "name": f"ElektroCoach {sensor['name']}",
            "unique_id": f"{DEVICE_ID}_{sensor['key']}",
            "state_topic": f"{DEVICE_ID}/sensor/{sensor['key']}/state",
            "icon": sensor["icon"],
            "availability_topic": f"{DEVICE_ID}/status",
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": {
                "identifiers": [DEVICE_ID],
                "name": DEVICE_NAME,
                "manufacturer": "ElektroCoach",
                "model": "KI-Lernplattform",
                "sw_version": "1.0.0",
            },
        }
        if sensor.get("unit"):
            payload["unit_of_measurement"] = sensor["unit"]
        if sensor.get("state_class"):
            payload["state_class"] = sensor["state_class"]
        ok = _publish(topic, json.dumps(payload, ensure_ascii=False)) and ok
    _publish(f"{DEVICE_ID}/status", "online")
    return ok


def publish_state() -> dict[str, Any]:
    state = collect_state()
    for sensor in SENSOR_DEFS:
        try:
            value = sensor["value"](state)
        except Exception:  # noqa: BLE001
            value = "unbekannt"
        _publish(f"{DEVICE_ID}/sensor/{sensor['key']}/state", str(value))
    return state


def remove_discovery() -> None:
    cfg = _mqtt_settings()
    for sensor in SENSOR_DEFS:
        _publish(f"{cfg['prefix']}/sensor/{DEVICE_ID}/{sensor['key']}/config", "", retain=True)
    _publish(f"{DEVICE_ID}/status", "offline")


# ---------------------------------------------------------------------------
# Benachrichtigungen ueber den Supervisor
# ---------------------------------------------------------------------------
async def notify(title: str, message: str, service: str | None = None) -> dict[str, Any]:
    target = service or str(settings.get("ha_notify_service", "") or "")
    db.insert(
        "INSERT INTO notifications_log(id, kind, title, message, delivered, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (db.new_id(), "notify", title[:200], message[:2000], 0, db.now()),
    )
    if not target:
        return {"ok": False, "error": "Kein Benachrichtigungsdienst konfiguriert"}
    if not SUPERVISOR_TOKEN:
        return {"ok": False, "error": "Kein Supervisor-Token verfuegbar"}
    service = target.split(".", 1)[-1]
    url = f"{SUPERVISOR_URL}/core/api/services/notify/{service}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"title": title, "message": message},
            )
            if resp.status_code >= 400:
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        db.execute(
            "UPDATE notifications_log SET delivered = 1 WHERE title = ? AND message = ?",
            (title[:200], message[:2000]),
        )
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


async def notify_due_reviews() -> dict[str, Any]:
    state = collect_state()
    due = state["due_reviews"]
    if due <= 0:
        return {"ok": False, "error": "Keine faelligen Wiederholungen"}
    return await notify(
        "ElektroCoach: Wiederholungen faellig",
        f"{due} Wiederholungen warten auf dich. Jetzt eine kurze Lernrunde einlegen.",
    )


# ---------------------------------------------------------------------------
# Periodischer Veröffentlichungsdienst
# ---------------------------------------------------------------------------
def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ha-publisher", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def _loop() -> None:
    """Veroeffentlicht Sensorwerte in einem festen Intervall.

    Das Intervall ist bewusst gross (Standard 300 s), um den zentralen
    Home-Assistant-Event-Bus nicht zu belasten.
    """
    time.sleep(20)
    if _mqtt_settings()["enabled"]:
        try:
            publish_discovery()
        except Exception:  # noqa: BLE001
            log.exception("MQTT-Discovery fehlgeschlagen")
    while not _stop.is_set():
        try:
            publish_state()
        except Exception:  # noqa: BLE001
            log.exception("Sensorveroeffentlichung fehlgeschlagen")
        interval = max(30, settings.get_int("sensor_update_interval", 300))
        if _stop.wait(interval):
            break


def status() -> dict[str, Any]:
    cfg = _mqtt_settings()
    return {
        "mqtt_enabled": cfg["enabled"],
        "mqtt_host": cfg["host"],
        "mqtt_connected": _client is not None,
        "supervisor_token": bool(SUPERVISOR_TOKEN),
        "notify_service": settings.get("ha_notify_service", "") or None,
        "sensor_update_interval": settings.get_int("sensor_update_interval", 300),
        "scheduler_running": bool(_thread and _thread.is_alive()),
    }
