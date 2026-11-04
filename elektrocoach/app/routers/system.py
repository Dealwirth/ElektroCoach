"""System-, Einstellungs-, Backup- und Dashboard-Endpunkte."""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import __version__, db
from ..config import SECRET_KEYS, settings
from ..security import decrypt, encrypt
from ..services import ai_router, backup, ha_integration, learning, schematic
from ..workers import import_worker

log = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

_START_TIME = time.time()


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "build": os.environ.get("ELEKTROCOACH_BUILD", "unbekannt"),
        "uptime_seconds": int(time.time() - _START_TIME),
        "db": db.integrity_check(),
        "worker_alive": import_worker.worker_alive(),
        "supervisor_token": bool(os.environ.get("SUPERVISOR_TOKEN")),
    }


@router.get("/system/info")
async def system_info() -> dict[str, Any]:
    ai = await ai_router.status()
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "uptime_seconds": int(time.time() - _START_TIME),
        "cpu_count": os.cpu_count(),
        "load_1min": import_worker.process_load(),
        "memory_available_mb": import_worker.available_memory_mb(),
        "import_queue": import_worker.queue_length(),
        "import_worker_alive": import_worker.worker_alive(),
        "storage": backup.storage_report(),
        "ai": ai,
        "ha": ha_integration.status(),
        "tesseract": _tesseract_info(),
        "handwriting": _handwriting_info(),
    }


def _tesseract_info() -> dict[str, Any]:
    from ..services import ocr

    return {
        "available": ocr.tesseract_available(),
        "languages": ocr.tesseract_languages(),
        "configured": settings.get("ocr_languages", "deu+eng"),
    }


def _handwriting_info() -> dict[str, Any]:
    from ..services import handwriting

    info = handwriting.status()
    info["engine"] = settings.get("ocr_engine", "auto")
    info["postprocess"] = settings.get("ocr_postprocess", "standard")
    return info


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    data = settings.as_dict(redact=True)
    stored = db.all_settings()
    for key in SECRET_KEYS:
        if stored.get(key):
            data[f"{key}_stored"] = True
    return data


@router.put("/settings")
async def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
    """Aendert Einstellungen. Geheimnisse werden verschluesselt gespeichert."""
    changed: list[str] = []
    for key, value in payload.values.items():
        if key not in settings.as_dict(redact=False):
            continue
        if key in SECRET_KEYS:
            if value in (None, "", "********"):
                continue
            db.set_setting(key, encrypt(settings.data_dir, str(value)), is_secret=True)
            settings.set_runtime(key, str(value))
        else:
            db.set_setting(key, str(value))
            settings.set_runtime(key, value)
        changed.append(key)

    if "sensor_update_interval" in changed or "mqtt_enabled" in changed:
        ha_integration.stop_scheduler()
        time.sleep(0.1)
        ha_integration.start_scheduler()

    return {"ok": True, "changed": changed, "settings": settings.as_dict(redact=True)}


@router.post("/settings/reload")
async def reload_settings() -> dict[str, Any]:
    settings.reload()
    return {"ok": True, "settings": settings.as_dict(redact=True)}


@router.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    stats = learning.dashboard_stats()
    return {
        "stats": stats,
        "series": learning.study_time_series(14),
        "weak_areas": learning.weak_areas(6),
        "due": learning.due_questions(10),
        "topics": learning.list_topics()[:12],
        "activity": learning.recent_activity(12),
        "plan": learning.study_plan(),
        "ai": await ai_router.status(),
    }


# ---------------------------------------------------------------------------
# Backup und Wartung
# ---------------------------------------------------------------------------
@router.get("/backups")
async def list_backups() -> dict[str, Any]:
    return {"items": backup.list_backups()}


class BackupRequest(BaseModel):
    label: str = "manuell"
    include_documents: bool = True


@router.post("/backups")
async def create_backup(payload: BackupRequest) -> dict[str, Any]:
    result = backup.create_backup(payload.label, payload.include_documents)
    return result


@router.delete("/backups/{name}")
async def delete_backup(name: str) -> dict[str, Any]:
    if not backup.delete_backup(name):
        raise HTTPException(status_code=404, detail="Backup nicht gefunden")
    return {"ok": True}


class RestoreRequest(BaseModel):
    name: str
    restore_documents: bool = True


@router.post("/backups/restore")
async def restore_backup(payload: RestoreRequest) -> dict[str, Any]:
    result = backup.restore_backup(payload.name, payload.restore_documents)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    return result


@router.get("/system/supervisor")
async def supervisor_diagnostics() -> dict[str, Any]:
    """Diagnose des Supervisor-Zugriffs (Rechte, Token, Add-on-Liste)."""
    from ..services import supervisor_diag

    return await supervisor_diag.diagnostics()


@router.get("/storage")
async def storage() -> dict[str, Any]:
    return backup.storage_report()


@router.post("/maintenance")
async def maintenance() -> dict[str, Any]:
    result = backup.maintenance()
    backup.maybe_auto_backup()
    return result


@router.get("/search")
async def search(q: str, limit: int = 25) -> dict[str, Any]:
    from ..services import library

    return library.search(q, limit=max(1, min(100, limit)))


@router.get("/schematics/library")
async def schematic_library() -> dict[str, Any]:
    return schematic.library()
