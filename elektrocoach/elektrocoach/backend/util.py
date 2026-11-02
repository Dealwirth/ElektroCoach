"""Shared small helpers (time, hashing, safe filenames)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat()


def iso_in(seconds: float) -> str:
    return (utcnow() + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def iso_in_days(days: float) -> str:
    return iso_in(days * 86400)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(name: str, fallback: str = "datei") -> str:
    """Reduce an uploaded filename to a safe basename.

    Prevents path traversal (``../``), absolute paths and control characters.
    """

    base = str(name or "").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKD", base)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = _SAFE_CHARS.sub("_", base).strip("._-")
    if not base:
        base = fallback
    return base[:120]


def human_bytes(size: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
