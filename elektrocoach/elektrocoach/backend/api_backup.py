"""Backup and restore endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..backend.util import human_bytes

logger = logging.getLogger("elektrocoach.api.backup")

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("")
async def list_backups(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return context.backup.status()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backup(context: AppContext = Depends(get_context),
                        note: str | None = Query(default=None, max_length=200)) -> dict[str, Any]:
    try:
        record = context.backup.create(kind="manual", note=note)
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Backup erstellen") from exc
    return {
        **record,
        "message": (f"Das Backup „{record['filename']}“ wurde erstellt "
                    f"({record['size_human']}) und liegt unter {record['path']}."),
    }


@router.post("/{backup_id}/verify")
async def verify_backup(backup_id: int,
                        context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return context.backup.verify(backup_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Backup prüfen") from exc


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: int,
                         context: AppContext = Depends(get_context),
                         confirmed: bool = Query(default=False)) -> dict[str, Any]:
    """Restore a backup. Destructive: requires ``confirmed=true``."""

    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail=("Das Wiederherstellen ersetzt die aktuelle Datenbank. "
                    "Bestätigen Sie mit „confirmed=true“. ElektroCoach legt vorher "
                    "automatisch ein Sicherheitsbackup an."),
        )
    try:
        result = context.backup.restore(backup_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Backup wiederherstellen") from exc
    return result


@router.delete("/{backup_id}")
async def delete_backup(backup_id: int,
                        context: AppContext = Depends(get_context),
                        confirmed: bool = Query(default=False)) -> dict[str, Any]:
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail="Das Löschen eines Backups ist endgültig. Bestätigen Sie mit „confirmed=true“.",
        )
    try:
        return context.backup.delete(backup_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{backup_id}/download")
async def download_backup(backup_id: int,
                          context: AppContext = Depends(get_context)):
    """Download a backup file (stays inside the configured backup directory)."""

    from pathlib import Path

    try:
        record = context.backup._record(backup_id)  # noqa: SLF001 - internal helper
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = Path(record["path"])
    allowed_root = context.backup.target_dir().resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Die Backup-Datei ist nicht lesbar.") from exc
    if allowed_root not in resolved.parents and resolved != allowed_root:
        logger.warning("blocked out-of-tree backup download: %s", path)
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")
    if not resolved.is_file():
        raise HTTPException(status_code=404,
                            detail="Die Backup-Datei wurde nicht gefunden.")
    return FileResponse(resolved, media_type="application/zip",
                        filename=record["filename"])


@router.get("/{backup_id}/contents")
async def backup_contents(backup_id: int,
                          context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """List what a backup contains without extracting it."""

    import json
    import zipfile
    from pathlib import Path

    try:
        record = context.backup._record(backup_id)  # noqa: SLF001
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = Path(record["path"])
    if not path.is_file():
        raise HTTPException(status_code=404,
                            detail="Die Backup-Datei wurde nicht gefunden.")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            manifest = None
            if "manifest.json" in names:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            documents = [n for n in names if n.startswith("documents/")]
            pages = [n for n in names if n.startswith("pages/")]
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Das Backup konnte nicht gelesen werden: {exc}",
        ) from exc
    return {
        "filename": record["filename"],
        "size_human": human_bytes(record.get("size_bytes") or 0),
        "manifest": manifest,
        "documents": len(documents),
        "pages": len(pages),
        "has_database": "elektrocoach.sqlite3" in names,
    }
