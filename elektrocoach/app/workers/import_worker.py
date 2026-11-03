"""Hintergrund-Import: ressourcenschonend, unterbrechbar, mit Fortschritt.

Design:
  * Genau ein Import-Worker-Thread gleichzeitig (der Pi 4 hat 4 Kerne).
  * Verarbeitung streng sequenziell je Datei, mit kurzer Pause dazwischen,
    damit Home Assistant und der Rest des Systems Luft behalten.
  * Speicherbremse: vor jeder Datei wird der freie Speicher geprueft. Ist zu
    wenig frei, pausiert der Import, statt das System in einen OOM zu treiben.
  * Abbruch ueber cancel_requested, mitten im Dateibatch moeglich.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from .. import db
from ..config import settings
from ..security import is_allowed_upload, safe_filename, sha256_file
from ..services import library

log = logging.getLogger(__name__)

_queue: "queue.Queue[tuple[str, list[str]]]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()

# Untergrenze freier Speicher (Bytes), ab der der Import pausiert.
MIN_FREE_BYTES = 512 * 1024 * 1024
# Zusaetzliche Reserve Arbeitsspeicher (MB), ab der der Import pausiert.
MEMORY_GUARD_MB = 400
# Pause zwischen Dateien (Sekunden), damit das System atmen kann.
INTER_FILE_DELAY = 0.25
# Maximale Groesse einer Einzeldatei (Bytes).
MAX_FILE_BYTES = 512 * 1024 * 1024


def free_bytes() -> int:
    try:
        return shutil.disk_usage(str(settings.data_dir)).free
    except OSError:
        return 0


def start_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run, name="import-worker", daemon=True)
        _worker.start()
        log.info("Import-Worker gestartet.")


def resume_interrupted_jobs() -> int:
    """Setzt Auftraege fort, die ein Neustart unterbrochen hat.

    Ein Abbruch mitten im Import (Neustart, Stromausfall) laesst einen Auftrag
    sonst dauerhaft auf "running" stehen. Beim Start werden solche Auftraege
    erneut eingereiht. Bereits importierte Dateien werden ueber die
    SHA-256-Pruefung als Duplikate erkannt und uebersprungen, die Verarbeitung
    ist dadurch wiederholbar.
    """
    try:
        rows = db.query(
            "SELECT id, status FROM import_jobs WHERE status IN ('running', 'queued')"
        )
    except Exception:  # noqa: BLE001 - darf den Start nicht verhindern
        log.exception("Unterbrochene Importauftraege konnten nicht gelesen werden.")
        return 0
    resumed = 0
    for row in rows:
        job_id = row["id"]
        data = job(job_id) or {}
        try:
            stats = json.loads(data.get("stats_json") or "{}")
        except json.JSONDecodeError:
            stats = {}
        if not stats.get("files"):
            _set_job(job_id, status="error",
                     message="Import wurde durch einen Neustart unterbrochen")
            continue
        _set_job(job_id, status="queued", cancel_requested=0,
                 message="Nach Neustart fortgesetzt")
        if _dispatch(job_id):
            resumed += 1
    if resumed:
        log.info("%s unterbrochene Importauftraege werden fortgesetzt.", resumed)
    return resumed


def _dispatch(job_id: str) -> bool:
    """Reiht einen Auftrag ein. Ohne laufenden Worker wird dieser gestartet."""
    start_worker()
    _queue.put((job_id, []))
    return True


def enqueue_job(job_id: str, paths: list[str]) -> None:
    _queue.put((job_id, paths))


def _run() -> None:
    """Endlosschleife des Import-Workers.

    Die Schleife darf nie sterben: faellt die Fehlerbehandlung selbst aus
    (z. B. bei einem Datenbankproblem), wird der Auftrag trotzdem abgeschlossen
    und der naechste Auftrag angenommen. Sonst waeren nach einem einzigen
    Fehler dauerhaft keine Importe mehr moeglich.
    """
    while True:
        job_id, paths = _queue.get()
        try:
            _process_job(job_id, paths)
        except Exception:  # noqa: BLE001
            log.exception("Import-Job %s fehlgeschlagen", job_id)
            try:
                _set_job(job_id, status="error", message="Unerwarteter Fehler im Import")
            except Exception:  # noqa: BLE001
                log.exception("Fehlerstatus fuer Job %s konnte nicht gespeichert werden", job_id)
        finally:
            try:
                _queue.task_done()
            except Exception:  # noqa: BLE001
                log.exception("task_done fuer Job %s fehlgeschlagen", job_id)


def _set_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = db.now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    db.execute(f"UPDATE import_jobs SET {columns} WHERE id = ?", values)  # noqa: S608


def job(job_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM import_jobs WHERE id = ?", (job_id,))
    return dict(row) if row else None


def latest_job() -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT 1")
    return dict(row) if row else None


def request_cancel(job_id: str) -> bool:
    job_data = job(job_id)
    if not job_data or job_data["status"] in {"done", "error", "cancelled"}:
        return False
    _set_job(job_id, cancel_requested=1, message="Abbruch angefordert")
    return True


def _cancelled(job_id: str) -> bool:
    row = db.query_one("SELECT cancel_requested FROM import_jobs WHERE id = ?", (job_id,))
    return bool(row and row["cancel_requested"])


def create_job(files: list[tuple[str, str]], collection: str | None = None) -> str:
    """files: Liste (temporaerer Pfad, Originalname)."""
    job_id = db.new_id()
    db.insert(
        "INSERT INTO import_jobs(id, status, total_files, current_item, message, stats_json, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (job_id, "queued", len(files), "", "Wartet auf Verarbeitung",
         db.json_dumps_safe({"collection": collection, "files": files}), db.now(), db.now()),
    )
    return job_id


def _unpack_archives(files: list[tuple[str, str]], job_id: str) -> list[tuple[str, str]]:
    """Entpackt ZIPs (z. B. Samsung-Sammlungen), auch verschachtelt.

    Schutzmechanismen:
      * maximale Schachtelungstiefe (Standard 3)
      * Obergrenze fuer die Gesamtzahl entpackter Dateien je Job
      * Obergrenze fuer die entpackte Gesamtgroesse (ZIP-Bombe)
    """
    max_depth = max(1, settings.get_int("import_max_zip_depth", 3))
    max_entries = max(100, settings.get_int("import_max_zip_entries", 5000))
    max_unpacked = settings.get_int("import_max_unpacked_mb", 4096) * 1024 * 1024
    max_member = settings.get_int("import_max_zip_member_mb", 128) * 1024 * 1024

    workdir = settings.data_dir / "import_tmp" / job_id
    expanded: list[tuple[str, str]] = []
    state = {"entries": 0, "bytes": 0}

    def unpack_one(path_str: str, name: str, depth: int) -> None:
        path = Path(path_str)
        if path.suffix.lower() != ".zip" or not zipfile.is_zipfile(path):
            expanded.append((path_str, name))
            return
        added = 0
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir() or state["entries"] >= max_entries:
                        continue
                    if info.file_size > max_member:
                        log.warning("Ueberspringe zu grosse Datei im Archiv: %s", info.filename)
                        continue
                    if state["bytes"] + info.file_size > max_unpacked:
                        log.warning("Archiv %s ueberschreitet das Groessenlimit.", name)
                        break
                    inner_name = safe_filename(info.filename)
                    if not is_allowed_upload(inner_name):
                        continue
                    target = workdir / f"d{depth}_{state['entries']:05d}_{inner_name}"
                    with archive.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1 << 20)
                    state["entries"] += 1
                    state["bytes"] += info.file_size
                    added += 1
                    if depth < max_depth and inner_name.lower().endswith(".zip"):
                        unpack_one(str(target), inner_name, depth + 1)
                    else:
                        expanded.append((str(target), inner_name))
        except Exception as exc:  # noqa: BLE001
            log.warning("ZIP %s konnte nicht entpackt werden: %s", name, exc)
            expanded.append((path_str, name))
            return
        if added == 0:
            # Leeres oder unbrauchbares Archiv: nicht stillschweigend verwerfen.
            log.warning("Archiv %s enthaelt keine verwertbaren Dateien.", name)
            expanded.append((path_str, name))

    for path_str, name in files:
        unpack_one(path_str, name, depth=0)
    return expanded


def _process_job(job_id: str, paths: list[str]) -> None:
    row = db.query_one("SELECT stats_json, total_files FROM import_jobs WHERE id = ?", (job_id,))
    stats = {}
    if row:
        try:
            stats = json.loads(row["stats_json"] or "{}")
        except json.JSONDecodeError:
            stats = {}
    raw_files: list[tuple[str, str]] = [tuple(pair) for pair in stats.get("files", [])]  # type: ignore[misc]
    collection = stats.get("collection")

    _set_job(job_id, status="running", message="Import gestartet")

    files = _unpack_archives(raw_files, job_id)
    _set_job(job_id, total_files=len(files))

    processed = 0
    failed = 0
    skipped = 0
    results: list[dict[str, Any]] = []

    for index, (path_str, name) in enumerate(files, start=1):
        if _cancelled(job_id):
            _set_job(job_id, status="cancelled", message="Import abgebrochen",
                     processed_files=processed, failed_files=failed)
            _cleanup(raw_files, job_id)
            return

        _set_job(job_id, current_item=name,
                 message=f"Verarbeite {index} von {len(files)}: {name}")

        path = Path(path_str)
        if not path.exists():
            failed += 1
            results.append({"filename": name, "status": "error", "error": "Datei fehlt"})
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            failed += 1
            results.append({"filename": name, "status": "error",
                            "error": "Datei groesser als 512 MB"})
            continue
        if not is_allowed_upload(name):
            failed += 1
            results.append({"filename": name, "status": "error",
                            "error": "Dateityp nicht unterstuetzt"})
            continue

        _wait_for_space(job_id)

        try:
            digest = sha256_file(path)
        except OSError as exc:
            failed += 1
            results.append({"filename": name, "status": "error", "error": str(exc)})
            continue

        duplicate = library.find_duplicate(digest)
        if duplicate:
            skipped += 1
            results.append({"filename": name, "status": "duplicate",
                            "duplicate_of": duplicate["filename"],
                            "document_id": duplicate["id"]})
            _set_job(job_id, processed_files=processed + skipped,
                     failed_files=failed, message=f"Duplikat uebersprungen: {name}")
            continue

        try:
            outcome = library.store_document(path, name, collection=collection,
                                             source="import", sha256=digest)
        except Exception as exc:  # noqa: BLE001
            log.exception("Import von %s fehlgeschlagen", name)
            failed += 1
            results.append({"filename": name, "status": "error", "error": str(exc)[:300]})
            continue

        if outcome.get("status") == "error":
            failed += 1
            results.append({"filename": name, "status": "error",
                            "error": outcome.get("error") or "Verarbeitung fehlgeschlagen",
                            "document_id": outcome.get("id")})
        else:
            processed += 1
            results.append({"filename": name, **outcome})
        _set_job(job_id, processed_files=processed + skipped, failed_files=failed)
        time.sleep(INTER_FILE_DELAY)

    if processed and settings.get_bool("auto_analyze_after_import", True):
        try:
            _set_job(job_id, message="Themen werden zugeordnet …")
            from ..services import learning

            report = learning.analyze_topics(use_ai=False)
            log.info("Themenanalyse nach Import: %s Abschnitte zugeordnet", report.get("assigned_chunks"))
        except Exception:  # noqa: BLE001 - Analysefehler darf den Import nicht verwerfen
            log.exception("Themenanalyse nach dem Import fehlgeschlagen")

    _cleanup(raw_files, job_id)
    _set_job(
        job_id,
        status="done",
        processed_files=processed + skipped,
        failed_files=failed,
        current_item="",
        message=f"Fertig: {processed} importiert, {skipped} Duplikate, {failed} Fehler",
        stats_json=db.json_dumps_safe({
            "collection": collection, "files": [], "results": results[-200:],
            "imported": processed, "duplicates": skipped, "failed": failed,
        }),
    )
    db.insert(
        "INSERT INTO activity_log(id, kind, detail, created_at) VALUES(?,?,?,?)",
        (db.new_id(), "import_done",
         f"{processed} importiert, {skipped} Duplikate, {failed} Fehler", db.now()),
    )


def _memory_guard_mb() -> int:
    return max(100, settings.get_int("import_memory_guard_mb", MEMORY_GUARD_MB))


def _wait_for_space(job_id: str) -> None:
    """Pausiert den Import, wenn Speicherplatz oder Arbeitsspeicher knapp werden."""
    waited = 0
    guard = _memory_guard_mb()
    while True:
        low_disk = free_bytes() < MIN_FREE_BYTES
        available = available_memory_mb()
        low_memory = available is not None and available < guard
        if not low_disk and not low_memory:
            return
        if _cancelled(job_id):
            return
        if low_memory and not low_disk:
            _set_job(job_id, message="Arbeitsspeicher knapp - Import pausiert")
        else:
            _set_job(job_id, message="Speicher knapp - Import pausiert, bitte Platz schaffen")
        time.sleep(5)
        waited += 5
        if waited >= 600:
            log.warning("Import pausiert seit 10 Minuten wegen Speichermangels.")


def _cleanup(raw_files: list[tuple[str, str]], job_id: str) -> None:
    for path_str, _name in raw_files:
        try:
            Path(path_str).unlink(missing_ok=True)
        except OSError:
            pass
    tmp = settings.data_dir / "import_tmp" / job_id
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)


def queue_length() -> int:
    return _queue.qsize()


def worker_alive() -> bool:
    return bool(_worker and _worker.is_alive())


def available_memory_mb() -> int | None:
    """Freier Arbeitsspeicher aus /proc/meminfo (Linux)."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def process_load() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None
