"""Configuration loading for ElektroCoach.

The Home Assistant supervisor writes the add-on options to ``/data/options.json``.
This module reads that file, validates every value and falls back to a safe
default when a value is missing or invalid. A broken options file must never
prevent the add-on from starting.

Environment variables prefixed with ``ELEKTROCOACH_`` override the file values,
which keeps local development and automated tests simple.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_OLLAMA_URL = "http://a0d7b954-ollama:11434"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

LOG_LEVELS = {"trace", "debug", "info", "notice", "warning", "error", "fatal"}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int, minimum: int | None = None,
            maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and result < minimum:
        return default
    if maximum is not None and result > maximum:
        return default
    return result


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


@dataclass
class Options:
    """Validated add-on options plus the derived filesystem paths."""

    log_level: str = "info"
    data_dir: str = "/data"
    share_dir: str = "/share"

    ollama_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = "qwen2.5:1.5b"
    ollama_enabled: bool = True
    ollama_unload_after_seconds: int = 900

    gemini_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_daily_request_budget: int = 200

    ha_notifications_enabled: bool = True
    notify_service: str = ""
    auto_repair_enabled: bool = True

    storage_warning_percent: int = 90
    storage_critical_percent: int = 95

    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_keep: int = 7
    backup_dir: str = "/share/elektrocoach/backups"

    monitoring_interval_seconds: int = 60
    seed_demo_data: bool = False
    ocr_language: str = "deu+eng"

    port: int = 8099
    root: str = "/app"
    supervisor_token: str = ""
    options_file: str = ""
    ingress_entry: str = ""

    paths: dict[str, Path] = field(default_factory=dict)

    def path(self, key: str) -> Path:
        return self.paths[key]

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_enabled and self.gemini_api_key.strip())


def _options_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("ELEKTROCOACH_OPTIONS_FILE")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/data/options.json"))
    candidates.append(Path.cwd() / "options.json")
    return candidates


def _read_options_file() -> dict[str, Any]:
    for candidate in _options_file_candidates():
        try:
            if candidate.is_file():
                with candidate.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            # A corrupt options file must not stop the add-on; fall through to
            # the next candidate / built-in defaults.
            continue
    return {}


def _env_override(name: str, current: Any) -> Any:
    env_key = f"ELEKTROCOACH_{name.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    return current


def load_options() -> Options:
    """Build an :class:`Options` instance from file, environment and defaults."""

    raw = _read_options_file()

    def get(name: str, default: Any) -> Any:
        value = raw.get(name, default)
        return _env_override(name, value)

    log_level = _as_str(get("log_level", "info"), "info").lower()
    if log_level not in LOG_LEVELS:
        log_level = "info"

    warning_percent = _as_int(get("storage_warning_percent", 90), 90, 50, 99)
    critical_percent = _as_int(get("storage_critical_percent", 95), 95, 51, 100)
    if critical_percent <= warning_percent:
        critical_percent = min(100, warning_percent + 1)

    opts = Options(
        log_level=log_level,
        data_dir=_as_str(get("data_dir", "/data"), "/data"),
        share_dir=_as_str(os.environ.get("ELEKTROCOACH_SHARE_DIR", "/share"), "/share"),
        ollama_url=_as_str(get("ollama_url", DEFAULT_OLLAMA_URL), DEFAULT_OLLAMA_URL).rstrip("/"),
        ollama_model=_as_str(get("ollama_model", "qwen2.5:1.5b"), "qwen2.5:1.5b"),
        ollama_enabled=_as_bool(get("ollama_enabled", True), True),
        ollama_unload_after_seconds=_as_int(get("ollama_unload_after_seconds", 900), 900, 0, 86400),
        gemini_enabled=_as_bool(get("gemini_enabled", False), False),
        gemini_api_key=_as_str(get("gemini_api_key", ""), "").strip(),
        gemini_model=_as_str(get("gemini_model", DEFAULT_GEMINI_MODEL), DEFAULT_GEMINI_MODEL),
        gemini_daily_request_budget=_as_int(get("gemini_daily_request_budget", 200), 200, 0, 100000),
        ha_notifications_enabled=_as_bool(get("ha_notifications_enabled", True), True),
        notify_service=_as_str(get("notify_service", ""), "").strip(),
        auto_repair_enabled=_as_bool(get("auto_repair_enabled", True), True),
        storage_warning_percent=warning_percent,
        storage_critical_percent=critical_percent,
        backup_enabled=_as_bool(get("backup_enabled", True), True),
        backup_interval_hours=_as_int(get("backup_interval_hours", 24), 24, 1, 720),
        backup_keep=_as_int(get("backup_keep", 7), 7, 1, 100),
        backup_dir=_as_str(get("backup_dir", "/share/elektrocoach/backups"),
                           "/share/elektrocoach/backups"),
        monitoring_interval_seconds=_as_int(get("monitoring_interval_seconds", 60), 60, 15, 3600),
        seed_demo_data=_as_bool(get("seed_demo_data", False), False),
        ocr_language=_as_str(get("ocr_language", "deu+eng"), "deu+eng"),
        port=_as_int(os.environ.get("ELEKTROCOACH_PORT", 8099), 8099, 1, 65535),
        root=_as_str(os.environ.get("ELEKTROCOACH_ROOT", "/app"), "/app"),
        supervisor_token=os.environ.get("SUPERVISOR_TOKEN", "").strip(),
        options_file=str(_options_file_candidates()[0]) if _options_file_candidates() else "",
        ingress_entry=os.environ.get("ELEKTROCOACH_INGRESS_ENTRY", "").strip(),
    )
    opts.paths = _build_paths(opts)
    return opts


def _build_paths(opts: Options) -> dict[str, Path]:
    data = Path(opts.data_dir)
    share = Path(opts.share_dir)
    paths = {
        "data": data,
        "database": data / "elektrocoach.sqlite3",
        "documents": data / "documents",
        "pages": data / "pages",
        "uploads": data / "uploads",
        "tmp": data / "tmp",
        "logs": data / "logs",
        "backups": Path(opts.backup_dir),
        "backups_fallback": data / "backups",
        "share": share,
        "secret_key": data / "secret.key",
        "frontend": Path(opts.root) / "elektrocoach" / "frontend",
        "migrations": Path(opts.root) / "elektrocoach" / "database" / "migrations",
    }
    return paths


def ensure_directories(opts: Options) -> None:
    """Create every directory the application writes to."""

    for key in ("data", "documents", "pages", "uploads", "tmp", "logs"):
        try:
            opts.path(key).mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
    # The backup directory may live on /share, which is only mounted in Home
    # Assistant. Fall back to the data directory when it is not writable.
    for key in ("backups", "backups_fallback"):
        try:
            opts.path(key).mkdir(parents=True, exist_ok=True)
            probe = opts.path(key) / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            break
        except OSError:
            continue
