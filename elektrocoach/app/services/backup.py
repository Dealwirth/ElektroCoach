"""Backup, Wiederherstellung und Speicherueberwachung.

Backups nutzen die SQLite-Online-Backup-API. Damit ist die Sicherung auch
waehrend des Betriebs konsistent (kein kopieren einer halb geschriebenen
Datenbankdatei, kein Verlust durch WAL-Inhalte).
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

from .. import db
from ..config import settings
from ..security import safe_filename
from ..workers import import_worker

log = logging.getLogger(__name__)

MAX_BACKUPS = 5
AUTO_BACKUP_INTERVAL_SECONDS = 24 * 3600


def backups_dir() -> Path:
    path = settings.data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in sorted(backups_dir().glob("elektrocoach-*.tar.gz"), reverse=True):
        stat = item.stat()
        out.append({
            "name": item.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
        })
    return out


def create_backup(label: str = "manuell", include_documents: bool = True) -> dict[str, Any]:
    """Erstellt ein vollstaendiges Backup (Datenbank + optional Dokumente)."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = safe_filename(label, "backup")[:40]
    name = f"elektrocoach-{timestamp}-{safe_label}.tar.gz"
    target = backups_dir() / name
    tmp_db = backups_dir() / f".tmp-{timestamp}.db"

    db.checkpoint()
    db.backup_to(tmp_db)

    manifest = {
        "created_at": db.now(),
        "label": label,
        "app_version": "1.0.0",
        "db_stats": db.db_stats(),
        "include_documents": include_documents,
    }
    manifest_path = backups_dir() / f".manifest-{timestamp}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        with tarfile.open(target, "w:gz") as archive:
            archive.add(tmp_db, arcname="elektrocoach.db")
            archive.add(manifest_path, arcname="manifest.json")
            if include_documents:
                for folder in ("documents", "pages", "schematics"):
                    path = settings.data_dir / folder
                    if path.exists():
                        archive.add(path, arcname=folder)
    finally:
        tmp_db.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)

    _prune_backups()
    db.insert(
        "INSERT INTO activity_log(id, kind, detail, created_at) VALUES(?,?,?,?)",
        (db.new_id(), "backup", name, db.now()),
    )
    return {"ok": True, "name": name, "size_mb": round(target.stat().st_size / (1024 * 1024), 2)}


def _prune_backups() -> None:
    files = sorted(backups_dir().glob("elektrocoach-*.tar.gz"), reverse=True)
    for old in files[MAX_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


def delete_backup(name: str) -> bool:
    safe = safe_filename(name)
    path = backups_dir() / safe
    if not path.exists() or not path.name.startswith("elektrocoach-"):
        return False
    path.unlink()
    return True


def restore_backup(name: str, restore_documents: bool = True) -> dict[str, Any]:
    """Spielt ein Backup zurueck. Die App muss danach neu gestartet werden."""
    safe = safe_filename(name)
    path = backups_dir() / safe
    if not path.exists():
        return {"ok": False, "error": "Backup nicht gefunden"}

    workdir = settings.data_dir / f".restore-{int(time.time())}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(path, "r:gz") as archive:
            _safe_extract(archive, workdir)

        db_file = workdir / "elektrocoach.db"
        if not db_file.exists():
            return {"ok": False, "error": "Backup enthaelt keine Datenbank"}

        db.checkpoint()
        # Vorhandene Datenbank vor dem Ueberschreiben sichern.
        safety = backups_dir() / f"vor-wiederherstellung-{int(time.time())}.db"
        if settings.db_path.exists():
            shutil.copy2(settings.db_path, safety)

        db.close_thread_connection()
        shutil.copy2(db_file, settings.db_path)
        for suffix in ("-wal", "-shm"):
            side = Path(str(settings.db_path) + suffix)
            side.unlink(missing_ok=True)

        if restore_documents:
            for folder in ("documents", "pages", "schematics"):
                source = workdir / folder
                if source.exists():
                    target = settings.data_dir / folder
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(source, target)

        return {"ok": True, "restart_required": True,
                "safety_copy": safety.name}
    except Exception as exc:  # noqa: BLE001
        log.exception("Wiederherstellung fehlgeschlagen")
        return {"ok": False, "error": str(exc)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _safe_extract(archive: tarfile.TarFile, target: Path) -> None:
    """Verhindert Pfad-Ausbrueche (Zip-Slip) beim Entpacken."""
    target = target.resolve()
    for member in archive.getmembers():
        member_path = (target / member.name).resolve()
        if not str(member_path).startswith(str(target)):
            raise ValueError(f"Unsicherer Pfad im Backup: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"Verknuepfung im Backup nicht erlaubt: {member.name}")
    archive.extractall(target)


def storage_report() -> dict[str, Any]:
    total = used = free = 0
    try:
        usage = shutil.disk_usage(str(settings.data_dir))
        total, used, free = usage.total, usage.used, usage.free
    except OSError:
        pass

    def folder_size(name: str) -> int:
        path = settings.data_dir / name
        if not path.exists():
            return 0
        total_size = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except OSError:
                    pass
        return total_size

    db_stats = db.db_stats()
    return {
        "disk_total_mb": round(total / (1024 * 1024), 1),
        "disk_used_mb": round(used / (1024 * 1024), 1),
        "disk_free_mb": round(free / (1024 * 1024), 1),
        "disk_free_percent": round(100 * free / total, 1) if total else 0,
        "database_mb": round(db_stats["size_bytes"] / (1024 * 1024), 2),
        "wal_mb": round(db_stats["wal_bytes"] / (1024 * 1024), 2),
        "documents_mb": round(folder_size("documents") / (1024 * 1024), 2),
        "pages_mb": round(folder_size("pages") / (1024 * 1024), 2),
        "backups_mb": round(folder_size("backups") / (1024 * 1024), 2),
        "counts": db_stats["counts"],
        "memory_available_mb": import_worker.available_memory_mb(),
        "load_1min": import_worker.process_load(),
        "low_space_warning": free < 1024 * 1024 * 1024,
        "integrity": db.integrity_check(),
    }


def maybe_auto_backup() -> dict[str, Any] | None:
    last = db.get_setting("last_auto_backup")
    now_ts = time.time()
    if last:
        try:
            if now_ts - float(last) < AUTO_BACKUP_INTERVAL_SECONDS:
                return None
        except ValueError:
            pass
    result = create_backup("automatisch", include_documents=False)
    db.set_setting("last_auto_backup", str(now_ts))
    return result


def maintenance() -> dict[str, Any]:
    """Wartung: WAL sichern, Datenbank optimieren, Speicher pruefen."""
    db.checkpoint()
    before = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    db.vacuum()
    after = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    return {
        "ok": True,
        "size_before_mb": round(before / (1024 * 1024), 2),
        "size_after_mb": round(after / (1024 * 1024), 2),
        "integrity": db.integrity_check(),
    }
