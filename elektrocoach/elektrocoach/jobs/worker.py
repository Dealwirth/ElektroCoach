"""Background job worker.

Design constraints on a Raspberry Pi 4:

* **One worker, one job at a time.** Two concurrent imports would double memory
  use and slow the whole system down.
* The worker is a plain thread, so a long import never blocks the web server.
* Jobs are claimed atomically from the database, so a restart cannot lose a
  queued job and cannot run the same job twice.
* Every job reports progress, and a failure is stored with a readable message.
* The worker can be restarted safely at runtime (used by the self-repair).
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..backend.util import utcnow_iso

logger = logging.getLogger("elektrocoach.jobs")

IDLE_SLEEP_SECONDS = 2.0
MAX_JOBS_PER_CYCLE = 50


@dataclass
class JobContext:
    job_id: int
    type: str
    payload: dict[str, Any]
    worker: "JobWorker"

    def progress(self, value: float, message: str | None = None) -> None:
        self.worker.repo.update_job_progress(self.job_id, value, message)

    def log(self, message: str) -> None:
        logger.info("job %s (%s): %s", self.job_id, self.type, message)


Handler = Callable[[JobContext], dict[str, Any] | None]


class JobWorker:
    def __init__(self, repo, *, enabled: bool = True) -> None:
        self.repo = repo
        self.enabled = enabled
        self._handlers: dict[str, Handler] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._current_job_id: int | None = None
        self._last_error: str | None = None
        self._started_at: float | None = None

    # -- registration ---------------------------------------------------------

    def register(self, job_type: str, handler: Handler) -> None:
        self._handlers[job_type] = handler

    def known_types(self) -> list[str]:
        return sorted(self._handlers)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            logger.info("job worker disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="elektrocoach-worker",
                                        daemon=True)
        self._thread.start()
        self._started_at = time.time()
        logger.info("job worker started")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("job worker stopped")

    def restart(self) -> bool:
        """Restart the worker thread. Returns True if a restart was performed."""

        if not self.enabled:
            return False
        alive = self.is_alive()
        self.stop(timeout=5.0)
        self._thread = None
        self.start()
        return not alive or True

    def is_alive(self) -> bool:
        if not self.enabled:
            return True  # "alive" means "not broken" when disabled
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "alive": self.is_alive(),
            "current_job_id": self._current_job_id,
            "last_error": self._last_error,
            "started_at": self._started_at,
            "handlers": self.known_types(),
        }

    # -- main loop ------------------------------------------------------------

    def _run(self) -> None:
        processed = 0
        while not self._stop.is_set():
            try:
                job = self.repo.claim_job()
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self._last_error = str(exc)
                logger.exception("could not claim a job")
                self._stop.wait(IDLE_SLEEP_SECONDS * 2)
                continue

            if job is None:
                self._current_job_id = None
                processed = 0
                self._stop.wait(IDLE_SLEEP_SECONDS)
                continue

            self._execute(job)
            processed += 1
            if processed >= MAX_JOBS_PER_CYCLE:
                # Yield briefly so monitoring and the web server stay responsive.
                processed = 0
                self._stop.wait(IDLE_SLEEP_SECONDS)

    def _execute(self, job: dict) -> None:
        job_id = int(job["id"])
        job_type = str(job["type"])
        self._current_job_id = job_id
        handler = self._handlers.get(job_type)
        if handler is None:
            self.repo.finish_job(
                job_id,
                error=(f"Für den Aufgabentyp „{job_type}“ ist kein Bearbeiter "
                       "registriert."),
            )
            self.repo.add_event(
                level="error", category="jobs",
                message=f"Unbekannter Aufgabentyp „{job_type}“ (Aufgabe {job_id}).",
                details={"job_id": job_id},
            )
            self._current_job_id = None
            return

        context = JobContext(job_id=job_id, type=job_type,
                             payload=job.get("payload") or {}, worker=self)
        logger.info("running job %s of type %s", job_id, job_type)
        started = time.monotonic()
        try:
            result = handler(context) or {}
            duration = time.monotonic() - started
            self.repo.finish_job(job_id, result=result)
            logger.info("job %s finished in %.1fs", job_id, duration)
            self._last_error = None
        except Exception as exc:  # noqa: BLE001 - every job failure is contained
            duration = time.monotonic() - started
            self._last_error = str(exc)
            detail = traceback.format_exc(limit=6)
            logger.error("job %s failed after %.1fs: %s", job_id, duration, exc)
            self.repo.finish_job(job_id, error=f"{exc}")
            self.repo.add_event(
                level="error", category="jobs",
                message=(f"Die Hintergrundaufgabe {job_id} ({job_type}) ist "
                         f"fehlgeschlagen: {exc}"),
                details={"job_id": job_id, "type": job_type,
                         "traceback": detail[-2000:]},
            )
        finally:
            self._current_job_id = None
