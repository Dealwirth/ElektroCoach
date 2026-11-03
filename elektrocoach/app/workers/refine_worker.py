"""Hintergrund-Worker fuer die KI-Nachbearbeitung erkannter Texte.

Gleiche Grundsaetze wie beim Import-Worker:
  * genau ein Thread, streng sequenziell,
  * Speicher- und Platzbremse,
  * jederzeit abbrechbar,
  * Fortschritt je Seite in der Datenbank.

Der Worker ist bewusst vom Import getrennt: der Import kann bereits fertig
sein, waehrend die Nachbearbeitung (KI) noch laeuft oder erneut angestossen
wird. So bleibt ein grosser Import auch dann nutzbar, wenn keine KI erreichbar
ist.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from .. import db
from ..config import settings
from ..services import refine
from . import import_worker

log = logging.getLogger(__name__)

_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()

# Pause zwischen Seiten, damit der Pi 4 und Home Assistant Luft behalten.
PAGE_DELAY = 0.3
# Obergrenze je Auftrag, damit ein versehentlich grosser Lauf nicht endlos ist.
MAX_PAGES_PER_JOB = 2000


def start_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run, name="refine-worker", daemon=True)
        _worker.start()
        log.info("Nachbearbeitungs-Worker gestartet.")


def create_job(document_id: str | None, scope: str) -> str:
    job_id = db.new_id()
    db.insert(
        "INSERT INTO refine_jobs(id, document_id, scope, status, total_pages, processed_pages, "
        "message, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (job_id, document_id, scope, "queued", 0, 0, "Wartet auf Verarbeitung",
         db.now(), db.now()),
    )
    return job_id


def enqueue(job_id: str) -> None:
    start_worker()
    _queue.put(job_id)


def _set_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = db.now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    db.execute(f"UPDATE refine_jobs SET {columns} WHERE id = ?", values)  # noqa: S608


def job(job_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM refine_jobs WHERE id = ?", (job_id,))
    return dict(row) if row else None


def latest_job() -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM refine_jobs ORDER BY created_at DESC LIMIT 1")
    return dict(row) if row else None


def request_cancel(job_id: str) -> bool:
    data = job(job_id)
    if not data or data["status"] in {"done", "error", "cancelled"}:
        return False
    _set_job(job_id, cancel_requested=1, message="Abbruch angefordert")
    return True


def _cancelled(job_id: str) -> bool:
    row = db.query_one("SELECT cancel_requested FROM refine_jobs WHERE id = ?", (job_id,))
    return bool(row and row["cancel_requested"])


def _run() -> None:
    while True:
        job_id = _queue.get()
        try:
            _process_job(job_id)
        except Exception:  # noqa: BLE001 - die Schleife darf nie sterben
            log.exception("Nachbearbeitungs-Auftrag %s fehlgeschlagen", job_id)
            try:
                _set_job(job_id, status="error", message="Unerwarteter Fehler")
            except Exception:  # noqa: BLE001
                log.exception("Fehlerstatus fuer %s konnte nicht gespeichert werden", job_id)
        finally:
            try:
                _queue.task_done()
            except Exception:  # noqa: BLE001
                pass


def _wait_for_space(job_id: str) -> None:
    """Pausiert, wenn Arbeitsspeicher oder Platte knapp werden."""
    guard = max(100, settings.get_int("import_memory_guard_mb", 400))
    waited = 0
    while True:
        available = import_worker.available_memory_mb()
        low_memory = available is not None and available < guard
        low_disk = import_worker.free_bytes() < 256 * 1024 * 1024
        if not low_memory and not low_disk:
            return
        if _cancelled(job_id):
            return
        _set_job(job_id, message="Speicher knapp - Nachbearbeitung pausiert")
        time.sleep(5)
        waited += 5
        if waited >= 600:
            log.warning("Nachbearbeitung pausiert seit 10 Minuten.")


def _process_job(job_id: str) -> None:
    data = job(job_id)
    if not data:
        return
    document_id = data.get("document_id")
    scope = data.get("scope") or ("document" if document_id else "review")
    if scope == "document":
        pages = refine.pending_pages(document_id=document_id, limit=MAX_PAGES_PER_JOB)
    else:
        pages = refine.pending_pages(limit=MAX_PAGES_PER_JOB)

    _set_job(job_id, status="running", total_pages=len(pages),
             message=f"{len(pages)} Seiten werden nachbearbeitet")

    if not pages:
        _set_job(job_id, status="done", message="Keine Seiten nachzubearbeiten")
        return

    processed = 0
    improved = 0
    failed = 0
    for index, page in enumerate(pages, start=1):
        if _cancelled(job_id):
            _set_job(job_id, status="cancelled", processed_pages=processed,
                     message="Nachbearbeitung abgebrochen")
            return
        _wait_for_space(job_id)
        _set_job(job_id, current_page=page.get("page_number", 0),
                 message=f"Seite {index} von {len(pages)}")
        result = _run_refine(page)
        if result.get("ok"):
            refine.apply_result(result)
            processed += 1
            if result.get("text") != result.get("original"):
                improved += 1
        else:
            failed += 1
        _set_job(job_id, processed_pages=processed)
        time.sleep(PAGE_DELAY)

    db.insert(
        "INSERT INTO activity_log(id, kind, detail, created_at) VALUES(?,?,?,?)",
        (db.new_id(), "refine_done",
         f"{processed} Seiten nachbearbeitet, {improved} verbessert, {failed} Fehler",
         db.now()),
    )
    _set_job(job_id, status="done", processed_pages=processed,
             message=f"Fertig: {processed} Seiten bearbeitet, {improved} verbessert")


def _run_refine(page: dict[str, Any]) -> dict[str, Any]:
    """Fuehrt die Nachbearbeitung asynchron aus (eigener Event-Loop)."""
    import asyncio

    try:
        return asyncio.run(refine.refine_page(page))
    except Exception as exc:  # noqa: BLE001
        log.warning("Nachbearbeitung der Seite %s fehlgeschlagen: %s", page.get("id"), exc)
        return {"ok": False, "error": str(exc)[:200], "page_id": page.get("id")}


def queue_length() -> int:
    return _queue.qsize()


def worker_alive() -> bool:
    return bool(_worker and _worker.is_alive())
