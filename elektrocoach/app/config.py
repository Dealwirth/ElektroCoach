"""Konfiguration: Home-Assistant-Optionen, Umgebungsvariablen und Laufzeit-Einstellungen."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import threading
from typing import Any

log = logging.getLogger(__name__)

DATA_DIR = pathlib.Path(os.environ.get("ELEKTROCOACH_DATA", "/data"))
OPTIONS_FILE = DATA_DIR / "options.json"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_URL = "http://supervisor"

DEFAULTS: dict[str, Any] = {
    "gemini_api_key": "",
    "gemini_text_model": "gemini-2.5-flash",
    "gemini_vision_model": "gemini-2.5-flash",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2:3b",
    "ollama_enabled": False,
    "ocr_languages": "deu+eng",
    "ai_mode": "auto",
    "ha_notify_service": "",
    "mqtt_enabled": False,
    "mqtt_host": "core-mosquitto",
    "mqtt_port": 1883,
    "mqtt_username": "",
    "mqtt_password": "",
    "mqtt_discovery_prefix": "homeassistant",
    "daily_study_minutes": 45,
    "sensor_update_interval": 300,
    "log_level": "info",
    # Lernsystem
    "exam_pass_percent": 50,
    "question_default_count": 5,
    "question_default_difficulty": 3,
    "question_max_count": 20,
    "mark_unverified": True,
    "auto_analyze_after_import": True,
    # Import und Texterkennung
    "ocr_dpi": 150,
    "use_ai_for_ocr": False,
    "gemini_allow_images": False,
    "allow_external_ai": True,
    "keep_page_images": True,
    "import_max_parallel": 1,
    "import_memory_guard_mb": 400,
    # Schutz vor entpackten Riesenarchiven (ZIP-Bomben).
    "import_max_zip_depth": 3,
    "import_max_zip_entries": 5000,
    "import_max_zip_member_mb": 128,
    "import_max_unpacked_mb": 4096,
    "dedupe_threshold": 0.92,
    # KI
    "ai_timeout_seconds": 60,
    "ai_max_retries": 1,
    "gemini_daily_limit": 450,
    # Sicherheit
    "require_auth": False,
    "auth_password": "",
    "audit_log_enabled": True,
    "allow_external_ai_strict": False,
}

SECRET_KEYS = {"gemini_api_key", "mqtt_password", "auth_password"}

ENV_OVERRIDES = {
    "gemini_api_key": "ELEKTROCOACH_GEMINI_API_KEY",
    "ollama_url": "ELEKTROCOACH_OLLAMA_URL",
    "ollama_model": "ELEKTROCOACH_OLLAMA_MODEL",
    "data_dir": "ELEKTROCOACH_DATA",
}


class Settings:
    """Zentrale, threadsichere Konfiguration.

    Reihenfolge der Aufloesung (spaeter gewinnt):
      1. Standardwerte
      2. /data/options.json  (vom Supervisor geschrieben)
      3. Umgebungsvariablen  (z. B. ELEKTROCOACH_GEMINI_API_KEY)
      4. Laufzeit-Aenderungen aus der Weboberflaeche (in der Datenbank)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, Any] = dict(DEFAULTS)
        self._runtime: dict[str, Any] = {}
        self.reload()

    # -- Laden ---------------------------------------------------------------
    def reload(self) -> None:
        values = dict(DEFAULTS)
        if OPTIONS_FILE.exists():
            try:
                loaded = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    values.update({k: v for k, v in loaded.items() if v is not None})
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("options.json konnte nicht gelesen werden: %s", exc)
        for key, env in ENV_OVERRIDES.items():
            if key == "data_dir":
                continue
            val = os.environ.get(env)
            if val:
                values[key] = val
        with self._lock:
            self._values = values
            self._values.update(self._runtime)

    def set_runtime(self, key: str, value: Any) -> None:
        with self._lock:
            self._runtime[key] = value
            self._values[key] = value

    def clear_runtime(self, key: str) -> None:
        with self._lock:
            self._runtime.pop(key, None)
        self.reload()

    # -- Zugriff -------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            value = self._values.get(key, DEFAULTS.get(key, default))
        return default if value is None else value

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def as_dict(self, redact: bool = True) -> dict[str, Any]:
        with self._lock:
            data = dict(self._values)
        if redact:
            for key in SECRET_KEYS:
                if data.get(key):
                    data[key] = "********"
                else:
                    data[key] = ""
            data["gemini_api_key_set"] = bool(self.get("gemini_api_key"))
            data["mqtt_password_set"] = bool(self.get("mqtt_password"))
        return data

    @property
    def data_dir(self) -> pathlib.Path:
        return DATA_DIR

    @property
    def db_path(self) -> pathlib.Path:
        return DATA_DIR / "elektrocoach.db"


settings = Settings()
