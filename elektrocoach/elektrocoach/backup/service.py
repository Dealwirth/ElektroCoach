"""Backup and restore.

A backup is a single ``.zip`` file containing:

* a consistent copy of the SQLite database (taken with SQLite's online backup
  API, so a running import cannot corrupt it),
* every imported document and stored page image,
* a ``manifest.json`` with versions, counts and checksums.

The target directory is ``/share/elektrocoach/backups`` when writable (that is
where the user can reach it from a Windows PC through the Samba add-on), and
falls back to ``/data/backups`` otherwise. Because /data is erased when the
add-on is uninstalled, the UI shows the active target directory prominently.

Restoring creates a safety backup of the current state first, then replaces the
database and documents, and re-runs an integrity check.

The registry of backups lives in ``index.json`` inside the backup directory, not
in the SQLite database. A restore replaces the database, so a registry stored
there would erase the history and — worse — hide the safety backup that was just
created, leaving the user unable to undo the restore. The database table is kept
as a mirror so the dashboard and health checks can query it cheaply, and it is
rebuilt from the index whenever the two disagree.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..backend.util import human_bytes, sha256_file, utcnow, utcnow_iso

logger = logging.getLogger("elektrocoach.backup")

MANIFEST_NAME = "manifest.json"
BACKUP_PREFIX = "elektrocoach-backup-"
INDEX_NAME = "index.json"


def _precise_now() -> str:
    """A microsecond-resolution UTC timestamp (``...T12:00:00.123456+00:00``).

    Second resolution is not enough for backups: the safety backup taken before
    a restore and the restore itself can fall into the same second, and records
    with identical timestamps cannot be ordered reliably.
    """

    return utcnow().isoformat(timespec="microseconds")


class BackupService:
    def __init__(self, repo, opts, *, app_version: str = "0.1.0") -> None:
        self.repo = repo
        self.opts = opts
        self.app_version = app_version

    # -- backup registry (file based, survives a restore) ---------------------

    def _index_path(self) -> Path:
        return self.target_dir() / INDEX_NAME

    def _load_index(self) -> list[dict[str, Any]]:
        """Return the registry, rebuilding it from disk only if it is unusable.

        The index is authoritative. Scanning the directory on every read would
        re-hash every archive (slow on a Raspberry Pi) and would race with a
        backup that is currently being written, so the scan is a recovery path
        used only when the index is missing or unreadable.
        """

        path = self._index_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    records = [r for r in data if isinstance(r, dict) and r.get("path")]
                    return self._normalize(records)
            except (OSError, ValueError) as exc:
                logger.warning("backup index unreadable, rebuilding: %s", exc)
        return self.resync()

    def resync(self) -> list[dict[str, Any]]:
        """Rebuild the registry from the backup files and persist it."""

        records = self._scan_target()
        self._save_index(records)
        return records

    @staticmethod
    def _normalize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Give every record a stable, unique id and sort by creation time.

        Ids are never reassigned: the id is part of the file name, so reusing an
        id would let a new backup overwrite an existing one.
        """

        used = {int(r["id"]) for r in records if r.get("id")}
        next_id = max(used, default=0) + 1
        for record in records:
            if not record.get("id"):
                record["id"] = next_id
                used.add(next_id)
                next_id += 1
        records.sort(key=lambda r: (str(r.get("created_at") or ""), int(r["id"])))
        return records

    def _scan_target(self) -> list[dict[str, Any]]:
        """Rebuild registry entries by inspecting the backup files on disk."""

        found: list[dict[str, Any]] = []
        target = self.target_dir()
        for file in sorted(target.glob(f"{BACKUP_PREFIX}*.zip")):
            created = None
            kind = "unknown"
            try:
                with zipfile.ZipFile(file) as archive:
                    if MANIFEST_NAME in archive.namelist():
                        manifest = json.loads(
                            archive.read(MANIFEST_NAME).decode("utf-8"))
                        created = manifest.get("created_at")
                        kind = manifest.get("kind") or kind
                if created is None:
                    created = utcnow_iso()
                found.append({
                    "filename": file.name,
                    "path": str(file),
                    "size_bytes": file.stat().st_size,
                    "sha256": sha256_file(file),
                    "kind": kind,
                    "status": "ok",
                    "integrity_ok": None,
                    "note": "Aus dem Backup-Ordner neu eingelesen.",
                    "created_at": created,
                })
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                logger.warning("could not read backup file %s: %s", file, exc)
        return self._normalize(found)

    def _save_index(self, records: list[dict[str, Any]]) -> None:
        path = self._index_path()
        payload = json.dumps(records, ensure_ascii=False, indent=2)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(path)  # atomic on the same filesystem
        self._mirror_to_db(records)

    def _mirror_to_db(self, records: list[dict[str, Any]]) -> None:
        """Keep the ``backups`` table in step with the index (best effort)."""

        replace = getattr(self.repo, "replace_backups", None)
        if replace is None:
            return
        try:
            replace(records)
        except Exception as exc:  # noqa: BLE001 - the mirror must never break a backup
            logger.warning("could not mirror backup index into the database: %s", exc)

    def _find(self, backup_id: int) -> dict[str, Any]:
        for record in self._load_index():
            if int(record.get("id") or 0) == int(backup_id):
                return record
        raise ValueError(f"Das Backup {backup_id} existiert nicht.")

    def _update(self, backup_id: int, **fields: Any) -> None:
        records = self._load_index()
        for record in records:
            if int(record.get("id") or 0) == int(backup_id):
                record.update(fields)
                break
        self._save_index(records)

    # -- target directory -----------------------------------------------------

    def target_dir(self) -> Path:
        for key in ("backups", "backups_fallback"):
            candidate = self.opts.path(key)
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return candidate
            except OSError:
                continue
        return self.opts.path("data")

    def target_info(self) -> dict[str, Any]:
        target = self.target_dir()
        primary = self.opts.path("backups")
        return {
            "path": str(target),
            "is_primary": target == primary,
            "primary_path": str(primary),
            "warning": None if target == primary else (
                f"Der bevorzugte Zielordner {primary} ist nicht beschreibbar. "
                f"Backups werden deshalb unter {target} gespeichert. Achten Sie "
                "darauf, diesen Ordner zusätzlich auf einen externen Datenträger "
                "zu kopieren, weil er beim Deinstallieren des Add-ons verloren geht."
            ),
        }

    # -- create ---------------------------------------------------------------

    def create(self, *, kind: str = "auto", note: str | None = None,
               protect: Iterable[str] = ()) -> dict[str, Any]:
        target = self.target_dir()
        # Microsecond resolution keeps names unique. A plain second stamp would
        # be reused once an older backup is pruned, so a new backup could take
        # the file name of a backup the user still has a copy of.
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = f"{BACKUP_PREFIX}{stamp}-{kind}.zip"
        path = self._unique_path(target, filename)

        # Read the registry *before* the archive exists. Reading it afterwards
        # would let the recovery scan pick up the new file, so it would be
        # registered twice with two different ids.
        records = self._load_index()
        backup_id = max((int(r.get("id") or 0) for r in records), default=0) + 1

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_copy = tmp / "elektrocoach.sqlite3"
            self.repo.db.backup_to(db_copy)

            manifest = {
                "app_version": self.app_version,
                "schema_version": self.repo.db.schema_version,
                "created_at": utcnow_iso(),
                "kind": kind,
                "note": note,
                "counts": self.repo.db.table_counts(),
                "contents": {"database": "elektrocoach.sqlite3",
                             "documents": "documents/", "pages": "pages/"},
                "database_size": db_copy.stat().st_size,
                "database_sha256": sha256_file(db_copy),
            }
            (tmp / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6) as archive:
                archive.write(db_copy, "elektrocoach.sqlite3")
                archive.write(tmp / MANIFEST_NAME, MANIFEST_NAME)
                self._add_tree(archive, self.opts.path("documents"), "documents")
                self._add_tree(archive, self.opts.path("pages"), "pages")

        size = path.stat().st_size
        digest = sha256_file(path)
        record = {
            "id": backup_id,
            "filename": path.name,
            "path": str(path),
            "size_bytes": size,
            "sha256": digest,
            "kind": kind,
            "status": "ok",
            "integrity_ok": None,
            "note": note,
            "created_at": _precise_now(),
        }
        records = [r for r in records if str(r.get("path")) != str(path)]
        records.append(record)
        self._save_index(records)
        self.repo.audit("backup.create", target=path.name,
                        detail={"size": size, "kind": kind})
        # Only the explicitly protected paths are spared. The new file is the
        # newest, so the keep budget already keeps it.
        self._prune(protect=set(protect))
        return {
            "id": backup_id,
            "filename": path.name,
            "path": str(path),
            "size_bytes": size,
            "size_human": human_bytes(size),
            "sha256": digest,
            "created_at": record["created_at"],
            "manifest": manifest,
        }

    @staticmethod
    def _unique_path(target: Path, filename: str) -> Path:
        """Return a path that does not exist yet.

        The timestamp has second resolution, so two backups created in the same
        second would otherwise share a name and the second would overwrite the
        first without any warning.
        """

        candidate = target / filename
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        for counter in range(2, 1000):
            candidate = target / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
        raise ValueError(
            f"Im Backup-Ordner {target} liegen zu viele Backups mit demselben "
            "Zeitstempel. Bitte räumen Sie den Ordner auf."
        )

    @staticmethod
    def _add_tree(archive: zipfile.ZipFile, source: Path, arc_prefix: str) -> None:
        if not source.is_dir():
            return
        for file in source.rglob("*"):
            if file.is_file():
                try:
                    archive.write(file, f"{arc_prefix}/{file.relative_to(source)}")
                except OSError as exc:
                    logger.warning("could not add %s to backup: %s", file, exc)

    def _prune(self, protect: set[str] | None = None) -> list[str]:
        """Delete the oldest backups beyond ``backup_keep``.

        ``protect`` holds paths that must survive, e.g. the backup that is
        currently being restored: deleting it mid-restore would abort the
        operation and could leave the user without the file they asked for.
        """

        keep = max(1, int(self.opts.backup_keep))
        protect = protect or set()
        backups = [r for r in self._load_index() if str(r.get("path")) not in protect]
        if len(backups) <= keep:
            return []
        removed: list[str] = []
        for record in backups[:-keep]:
            try:
                Path(record["path"]).unlink(missing_ok=True)
                removed.append(record["filename"])
            except OSError as exc:
                logger.warning("could not delete old backup %s: %s", record["path"], exc)
        if removed:
            self._save_index([r for r in backups if r["filename"] not in removed])
            self.repo.audit("backup.prune", detail={"removed": removed})
        return removed

    # -- verify ---------------------------------------------------------------

    def verify(self, backup_id: int) -> dict[str, Any]:
        record = self._record(backup_id)
        path = Path(record["path"])
        if not path.is_file():
            self._update(backup_id, integrity_ok=0, status="missing")
            return {"ok": False, "reason": "missing",
                    "message": f"Die Backup-Datei {path} wurde nicht gefunden."}

        problems: list[str] = []
        try:
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    problems.append(f"Beschädigter Eintrag: {bad}")
                names = set(archive.namelist())
                if "elektrocoach.sqlite3" not in names:
                    problems.append("Die Datenbank fehlt im Backup.")
                if MANIFEST_NAME not in names:
                    problems.append("Die Manifest-Datei fehlt im Backup.")
                if "elektrocoach.sqlite3" in names:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        extracted = Path(archive.extract("elektrocoach.sqlite3", tmpdir))
                        connection = sqlite3.connect(f"file:{extracted}?mode=ro",
                                                     uri=True)
                        try:
                            row = connection.execute("PRAGMA integrity_check").fetchone()
                            result = str(row[0]) if row else "kein Ergebnis"
                            if result.lower() != "ok":
                                problems.append(
                                    f"Die Datenbank im Backup meldet: {result}")
                        finally:
                            connection.close()
                if MANIFEST_NAME in names:
                    manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                    record_manifest = manifest.get("schema_version")
                    if record_manifest and int(record_manifest) > self.repo.db.schema_version:
                        problems.append(
                            f"Das Backup stammt von einer neueren Version "
                            f"(Schema {record_manifest}). Bitte zuerst das Add-on "
                            "aktualisieren."
                        )
        except zipfile.BadZipFile as exc:
            problems.append(f"Die Datei ist kein gültiges ZIP-Archiv: {exc}")
        except (OSError, ValueError) as exc:
            problems.append(f"Die Prüfung ist fehlgeschlagen: {exc}")

        ok = not problems
        self._update(backup_id, integrity_ok=1 if ok else 0,
                     status="ok" if ok else "corrupt")
        return {
            "ok": ok,
            "backup_id": backup_id,
            "filename": record["filename"],
            "problems": problems,
            "message": ("Das Backup ist in Ordnung und kann wiederhergestellt werden."
                        if ok else "Das Backup ist nicht verwendbar."),
        }

    # -- restore --------------------------------------------------------------

    def restore(self, backup_id: int, *, create_safety_backup: bool = True) -> dict[str, Any]:
        record = self._record(backup_id)
        path = Path(record["path"])
        if not path.is_file():
            raise FileNotFoundError(
                f"Die Backup-Datei {path} wurde nicht gefunden. Bitte prüfen Sie, "
                "ob der Ordner noch vorhanden ist."
            )

        verification = self.verify(backup_id)
        if not verification["ok"]:
            raise ValueError(
                "Das Backup ist beschädigt und wurde nicht wiederhergestellt. "
                "Gründe: " + "; ".join(verification["problems"])
            )

        safety = None
        if create_safety_backup:
            try:
                safety = self.create(kind="pre-restore",
                                     note=f"Sicherung vor Wiederherstellung von "
                                          f"{record['filename']}",
                                     protect={str(path)})
            except Exception as exc:  # noqa: BLE001
                logger.warning("safety backup failed: %s", exc)
                raise ValueError(
                    "Es konnte kein Sicherheitsbackup angelegt werden, deshalb "
                    f"wurde die Wiederherstellung abgebrochen: {exc}"
                ) from exc

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            if not path.is_file():
                # The file could have disappeared after the check above.
                raise ValueError(
                    f"Die Backup-Datei {path.name} ist nicht mehr vorhanden. "
                    "Wählen Sie in der Liste ein anderes Backup aus oder spielen "
                    "Sie die Datei erneut in den Backup-Ordner."
                )
            with zipfile.ZipFile(path) as archive:
                archive.extractall(tmp)

            restored_db = tmp / "elektrocoach.sqlite3"
            if not restored_db.is_file():
                raise ValueError("Im Backup fehlt die Datenbankdatei.")

            # Every thread must drop its connection: the file is replaced below.
            # Closing only this thread's connection would leave the worker and
            # the web threads reading the old, unlinked database.
            self.repo.db.invalidate_connections()
            live_db = self.opts.path("database")
            for suffix in ("", "-wal", "-shm"):
                Path(str(live_db) + suffix).unlink(missing_ok=True)
            shutil.copy2(restored_db, live_db)

            for name in ("documents", "pages"):
                source = tmp / name
                if source.is_dir():
                    destination = self.opts.path(name)
                    shutil.rmtree(destination, ignore_errors=True)
                    shutil.copytree(source, destination)

        ok, message = self.repo.db.quick_check()
        # The restored database has no knowledge of the backups made after the
        # backup was taken, so rebuild the mirror table from the file index.
        # Otherwise the safety backup would vanish from the UI and the user
        # could not undo the restore.
        self._mirror_to_db(self._load_index())
        self.repo.audit("backup.restore", target=record["filename"],
                        detail={"integrity": message, "safety_backup":
                                safety["filename"] if safety else None})
        if not ok:
            raise ValueError(
                f"Nach der Wiederherstellung meldet die Datenbank: {message}. "
                "Bitte starten Sie das Add-on neu."
            )
        return {
            "restored": record["filename"],
            "integrity": message,
            "safety_backup": safety,
            "restart_recommended": True,
            "message": (
                "Die Wiederherstellung war erfolgreich. Starten Sie das "
                "ElektroCoach-Add-on neu, damit alle Verbindungen frisch "
                "aufgebaut werden."
            ),
        }

    # -- delete ---------------------------------------------------------------

    def delete(self, backup_id: int) -> dict[str, Any]:
        record = self._record(backup_id)
        path = Path(record["path"])
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"Die Backup-Datei konnte nicht gelöscht werden: {exc}") from exc
        self._save_index([r for r in self._load_index()
                          if int(r.get("id") or 0) != int(backup_id)])
        self.repo.audit("backup.delete", target=record["filename"])
        return {"deleted": record["filename"]}

    # -- helpers --------------------------------------------------------------

    def _record(self, backup_id: int) -> dict:
        return self._find(backup_id)

    def status(self) -> dict[str, Any]:
        backups = self._load_index()
        # The dashboard and health checks read the mirror table, so refresh it.
        self._mirror_to_db(backups)
        target = self.target_info()
        total = sum(int(b.get("size_bytes") or 0) for b in backups)
        last = next((b for b in reversed(backups) if b.get("status") == "ok"), None)
        return {
            "target": target,
            "count": len(backups),
            "total_bytes": total,
            "total_human": human_bytes(total),
            "last": last,
            "enabled": self.opts.backup_enabled,
            "interval_hours": self.opts.backup_interval_hours,
            "keep": self.opts.backup_keep,
            "backups": [
                {**b, "size_human": human_bytes(b.get("size_bytes") or 0)}
                for b in backups
            ],
        }
