"""Logging configuration.

A single rotating file handler keeps the logs on the SD card small, and a
console handler feeds the Home Assistant add-on log. Log records are also
mirrored into an in-memory ring buffer so the diagnostics page can show the
most recent entries without reading the file.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections import deque
from pathlib import Path
from threading import Lock

LEVEL_MAP = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

_RING: deque[dict[str, str]] = deque(maxlen=500)
_RING_LOCK = Lock()


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": self.formatter.formatTime(record) if self.formatter else "",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            with _RING_LOCK:
                _RING.append(entry)
        except Exception:  # pragma: no cover - logging must never raise
            pass


def recent_log_entries(limit: int = 200) -> list[dict[str, str]]:
    with _RING_LOCK:
        entries = list(_RING)
    return entries[-limit:]


def configure_logging(level: str, log_dir: Path) -> logging.Logger:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    resolved = LEVEL_MAP.get(level, logging.INFO)
    root.setLevel(resolved)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "elektrocoach.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # A read-only data directory must not stop the application.
        pass

    ring = RingBufferHandler()
    ring.setFormatter(fmt)
    root.addHandler(ring)

    # uvicorn's access log is noisy and duplicates the monitoring data.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return logging.getLogger("elektrocoach")
