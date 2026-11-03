"""Verschluesselte Ablage von Zugangsdaten und Eingabevalidierung."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import pathlib
import re
import stat
from typing import Any

log = logging.getLogger(__name__)

_KEY_NAME = "secret.key"

try:  # pragma: no cover - abhaengig von der Umgebung
    from cryptography.fernet import Fernet, InvalidToken

    _HAVE_CRYPTO = True
except Exception:  # pragma: no cover
    _HAVE_CRYPTO = False
    InvalidToken = Exception  # type: ignore[assignment,misc]


def _key_path(data_dir: pathlib.Path) -> pathlib.Path:
    return data_dir / _KEY_NAME


def _load_or_create_key(data_dir: pathlib.Path) -> bytes | None:
    if not _HAVE_CRYPTO:
        return None
    path = _key_path(data_dir)
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def encrypt(data_dir: pathlib.Path, value: str) -> str:
    """Verschluesselt einen Wert. Ohne cryptography: Klartext mit Praefix."""
    key = _load_or_create_key(data_dir)
    if key is None:
        return "plain:" + base64.b64encode(value.encode("utf-8")).decode("ascii")
    return "enc:" + Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(data_dir: pathlib.Path, value: str) -> str:
    if not value:
        return ""
    if value.startswith("plain:"):
        try:
            return base64.b64decode(value[6:]).decode("utf-8")
        except Exception:
            return ""
    if value.startswith("enc:"):
        key = _load_or_create_key(data_dir)
        if key is None:
            log.error("Verschluesselter Wert vorhanden, aber cryptography fehlt.")
            return ""
        try:
            return Fernet(key).decrypt(value[4:].encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            log.error("Gespeicherter Wert konnte nicht entschluesselt werden.")
            return ""
    return value


# --------------------------------------------------------------------------
# Eingabevalidierung
# --------------------------------------------------------------------------
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "thema") -> str:
    slug = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return slug[:80] or fallback


def safe_filename(name: str, fallback: str = "datei") -> str:
    """Bereinigt einen Dateinamen: keine Pfadanteile, keine Steuerzeichen."""
    name = os.path.basename(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.strip().strip(".")
    name = re.sub(r"[^A-Za-z0-9._\- ()\[\]]+", "_", name)
    name = name[:120]
    return name or fallback


ALLOWED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
    ".txt", ".md", ".html", ".htm", ".json", ".sdoc", ".snote", ".zip", ".csv",
}


def is_allowed_upload(filename: str) -> bool:
    return pathlib.Path(safe_filename(filename)).suffix.lower() in ALLOWED_SUFFIXES


def sha256_file(path: pathlib.Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def redact(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


def mask_dict(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    out = dict(data)
    for key in keys:
        if out.get(key):
            out[key] = "********"
    return out
