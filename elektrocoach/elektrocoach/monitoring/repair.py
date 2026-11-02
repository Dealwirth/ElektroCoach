"""Safe self-repair.

Every action here is deliberately narrow, reversible and idempotent. The
following actions are allowed because they cannot destroy data and cannot change
the system outside the add-on:

* ``restart_worker``          – restart the internal job worker thread,
* ``requeue_job``             – run a failed background task again,
* ``reset_stale_job``         – release a job stuck in "running",
* ``clear_ai_cache``          – rebuild the AI response cache,
* ``rebuild_fts``             – rebuild the full-text index from the content,
* ``vacuum_database``         – compact the database,
* ``retry_ai_connection``     – probe Ollama/Gemini again,
* ``prune_cache``             – remove old cache entries,
* ``purge_logs``              – remove old log/event rows,
* ``remove_temp_files``       – delete leftover import scratch files.

The following are **never** performed automatically and require explicit
confirmation through the API (``POST /api/diagnostics/actions`` with
``confirmed=true``), and are only offered as guidance otherwise:

* restoring a backup (overwrites the live database),
* deleting documents or knowledge items,
* deleting backup files,
* any change outside the add-on's own data directory.

No shell command is ever executed.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..backend.util import utcnow_iso

logger = logging.getLogger("elektrocoach.monitoring.repair")


@dataclass
class RepairAction:
    name: str
    description: str
    destructive: bool = False
    requires_confirmation: bool = False
    handler: Callable[..., dict] | None = None
    guidance: str | None = None


@dataclass
class RepairResult:
    action: str
    status: str  # "repaired" | "failed" | "skipped" | "needs_confirmation"
    detail: str
    verified: bool | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
            "verified": self.verified,
            "data": self.data,
        }


class SelfRepair:
    def __init__(self, repo, opts, *, dispatcher=None, health=None,
                 worker=None, enabled: bool = True) -> None:
        self.repo = repo
        self.opts = opts
        self.dispatcher = dispatcher
        self.health = health
        self.worker = worker
        self.enabled = enabled
        self._actions: dict[str, RepairAction] = {}
        self._register()

    # -- registry -------------------------------------------------------------

    def _register(self) -> None:
        self._actions = {
            "restart_worker": RepairAction(
                "restart_worker",
                "Startet den internen Aufgaben-Worker kontrolliert neu.",
                handler=self._restart_worker,
            ),
            "requeue_job": RepairAction(
                "requeue_job",
                "Stellt eine fehlgeschlagene Hintergrundaufgabe erneut in die Warteschlange.",
                handler=self._requeue_job,
            ),
            "reset_stale_job": RepairAction(
                "reset_stale_job",
                "Gibt eine seit über 30 Minuten laufende Aufgabe wieder frei.",
                handler=self._reset_stale_job,
            ),
            "clear_ai_cache": RepairAction(
                "clear_ai_cache",
                "Baut den KI-Zwischenspeicher kontrolliert neu auf.",
                handler=self._clear_ai_cache,
            ),
            "prune_cache": RepairAction(
                "prune_cache",
                "Entfernt alte Einträge aus dem KI-Zwischenspeicher.",
                handler=self._prune_cache,
            ),
            "rebuild_fts": RepairAction(
                "rebuild_fts",
                "Baut den Volltextindex aus den vorhandenen Wissenseinträgen neu auf.",
                handler=self._rebuild_fts,
            ),
            "vacuum_database": RepairAction(
                "vacuum_database",
                "Verdichtet die Datenbankdatei und gibt freien Platz zurück.",
                handler=self._vacuum,
            ),
            "retry_ai_connection": RepairAction(
                "retry_ai_connection",
                "Prüft die Verbindungen zu Ollama und Gemini erneut.",
                handler=self._retry_ai,
            ),
            "purge_logs": RepairAction(
                "purge_logs",
                "Löscht alte Protokoll- und Ereigniseinträge (älter als 60 Tage).",
                handler=self._purge_logs,
            ),
            "remove_temp_files": RepairAction(
                "remove_temp_files",
                "Löscht zurückgebliebene temporäre Importdateien.",
                handler=self._remove_temp,
            ),
            "restore_backup": RepairAction(
                "restore_backup",
                "Stellt ein Backup wieder her. Überschreibt die aktuelle Datenbank.",
                destructive=True, requires_confirmation=True,
                guidance=(
                    "Diese Aktion ersetzt die aktuelle Datenbank durch das gewählte "
                    "Backup. Sie erfordert Ihre ausdrückliche Bestätigung. Vorher "
                    "wird automatisch ein Sicherheitsbackup angelegt."
                ),
            ),
            "delete_document": RepairAction(
                "delete_document",
                "Löscht ein Dokument samt Seiten und Wissenseinträgen.",
                destructive=True, requires_confirmation=True,
                guidance=(
                    "Das Löschen von Dokumenten ist endgültig und erfordert Ihre "
                    "Bestätigung. Erstellen Sie vorher ein Backup."
                ),
            ),
        }

    def list_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": action.name,
                "description": action.description,
                "destructive": action.destructive,
                "requires_confirmation": action.requires_confirmation,
                "automatic": not action.requires_confirmation and self.enabled,
                "guidance": action.guidance,
            }
            for action in self._actions.values()
        ]

    def is_safe(self, name: str) -> bool:
        action = self._actions.get(name)
        return bool(action and not action.destructive and not action.requires_confirmation)

    # -- execution ------------------------------------------------------------

    def run(self, name: str, *, confirmed: bool = False, event_id: int | None = None,
            **kwargs: Any) -> RepairResult:
        action = self._actions.get(name)
        if action is None:
            return RepairResult(name, "failed", f"Unbekannte Reparaturaktion „{name}“.")
        if action.requires_confirmation and not confirmed:
            return RepairResult(
                name, "needs_confirmation",
                "Diese Aktion verändert Daten und benötigt Ihre ausdrückliche "
                "Bestätigung.",
                data={"guidance": action.guidance},
            )
        if action.handler is None:
            return RepairResult(
                name, "skipped",
                "Diese Aktion kann nicht automatisch ausgeführt werden.",
                data={"guidance": action.guidance},
            )
        if not self.enabled and not action.destructive:
            return RepairResult(
                name, "skipped",
                "Die automatische Reparatur ist in den Einstellungen deaktiviert.",
            )

        logger.info("running repair action %s", name)
        try:
            outcome = action.handler(confirmed=confirmed, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a failed repair is reported, not raised
            logger.exception("repair action %s failed", name)
            self.repo.add_repair(event_id=event_id, action=name, status="failed",
                                 detail=str(exc)[:500])
            self.repo.add_event(
                level="error", category="repair",
                message=f"Die automatische Reparatur „{name}“ ist fehlgeschlagen: {exc}",
                details={"action": name},
            )
            return RepairResult(name, "failed", f"Die Reparatur ist fehlgeschlagen: {exc}")

        detail = str(outcome.get("detail") or "Die Reparatur wurde ausgeführt.")
        verified = outcome.get("verified")
        self.repo.add_repair(event_id=event_id, action=name,
                             status="ok" if verified is not False else "unverified",
                             detail=detail[:500])
        self.repo.audit("repair.run", target=name,
                        detail={"verified": verified, "data": outcome.get("data", {})})
        if verified is not False:
            self.repo.add_event(
                level="info", category="repair",
                message=f"Automatische Reparatur „{name}“: {detail}",
                details={"action": name, "data": outcome.get("data", {})},
            )
        return RepairResult(name, "repaired", detail, verified=verified,
                            data=outcome.get("data", {}))

    # -- handlers -------------------------------------------------------------

    def _restart_worker(self, **_: Any) -> dict:
        if self.worker is None:
            return {"detail": "Es ist kein interner Worker aktiv.",
                    "verified": False}
        restarted = self.worker.restart()
        healthy = self.worker.is_alive()
        return {
            "detail": ("Der interne Worker wurde neu gestartet."
                       if restarted else "Der Worker läuft bereits."),
            "verified": healthy,
            "data": {"alive": healthy},
        }

    def _requeue_job(self, *, job_id: int | None = None, **_: Any) -> dict:
        if job_id is None:
            failed = self.repo.list_jobs(status="failed", limit=1)
            if not failed:
                return {"detail": "Es gibt keine fehlgeschlagene Aufgabe.", "verified": True}
            job_id = int(failed[0]["id"])
        job = self.repo.get_job(int(job_id))
        if job is None:
            return {"detail": f"Die Aufgabe {job_id} existiert nicht.", "verified": False}
        if int(job.get("attempts") or 0) >= int(job.get("max_attempts") or 3):
            return {
                "detail": (f"Die Aufgabe {job_id} hat bereits "
                           f"{job['attempts']} Versuche erreicht und wird nicht "
                           "automatisch erneut gestartet. Bitte die Ursache prüfen."),
                "verified": False,
                "data": {"job": job},
            }
        self.repo.requeue_job(int(job_id))
        return {"detail": f"Die Aufgabe {job_id} wurde erneut eingereiht.",
                "verified": True, "data": {"job_id": job_id}}

    def _reset_stale_job(self, **_: Any) -> dict:
        stale = self.repo.stale_running_jobs(older_than_seconds=1800)
        if not stale:
            return {"detail": "Es gibt keine hängende Aufgabe.", "verified": True}
        for job in stale:
            if int(job.get("attempts") or 0) >= int(job.get("max_attempts") or 3):
                self.repo.finish_job(int(job["id"]),
                                     error="Abgebrochen: Aufgabe lief zu lange.")
            else:
                self.repo.requeue_job(int(job["id"]))
        return {
            "detail": f"{len(stale)} hängende Aufgabe(n) wurden freigegeben.",
            "verified": True,
            "data": {"jobs": [job["id"] for job in stale]},
        }

    def _clear_ai_cache(self, **_: Any) -> dict:
        self.repo.db.execute("DELETE FROM ai_cache")
        stats = self.repo.cache_stats()
        return {
            "detail": "Der KI-Zwischenspeicher wurde geleert und wird neu aufgebaut.",
            "verified": stats["entries"] == 0,
            "data": stats,
        }

    def _prune_cache(self, *, keep: int = 2000, **_: Any) -> dict:
        removed = self.repo.prune_ai_cache(keep=keep)
        stats = self.repo.cache_stats()
        return {
            "detail": f"{removed} alte Cache-Einträge wurden entfernt.",
            "verified": True,
            "data": {"removed": removed, **stats},
        }

    def _rebuild_fts(self, **_: Any) -> dict:
        if not self.repo.db.fts5_available:
            return {"detail": "FTS5 ist in dieser SQLite-Version nicht verfügbar.",
                    "verified": False}
        self.repo.db.rebuild_fts()
        try:
            row = self.repo.db.query_one(
                "SELECT COUNT(*) AS c FROM knowledge_fts"
            )
            indexed = int(row["c"] if row else 0)
        except Exception as exc:  # noqa: BLE001
            return {"detail": f"Der Index konnte nicht geprüft werden: {exc}",
                    "verified": False}
        expected = self.repo.count_knowledge()
        return {
            "detail": f"Der Volltextindex wurde neu aufgebaut ({indexed} Einträge).",
            "verified": indexed == expected,
            "data": {"indexed": indexed, "expected": expected},
        }

    def _vacuum(self, **_: Any) -> dict:
        before = self.repo.db.size_bytes()
        self.repo.vacuum()
        after = self.repo.db.size_bytes()
        ok, message = self.repo.db.quick_check()
        return {
            "detail": f"Datenbank verdichtet ({before} → {after} Bytes).",
            "verified": ok,
            "data": {"before": before, "after": after, "check": message},
        }

    def _retry_ai(self, **_: Any) -> dict:
        import asyncio

        from ..backend.runtime import run_coroutine

        if self.dispatcher is None:
            return {"detail": "Der KI-Dispatcher ist nicht verfügbar.", "verified": False}

        async def probe() -> dict:
            ollama_ok = await self.dispatcher.ollama.is_available()
            model_ok = await self.dispatcher.ollama.has_model() if ollama_ok else False
            gemini_ok = False
            if self.dispatcher.gemini.configured:
                try:
                    validation = await self.dispatcher.gemini.validate_key()
                    gemini_ok = bool(validation.get("ok"))
                except Exception:  # noqa: BLE001
                    gemini_ok = False
            return {"ollama": ollama_ok, "ollama_model": model_ok, "gemini": gemini_ok}

        try:
            outcome = run_coroutine(probe(), timeout=30)
        except Exception as exc:  # noqa: BLE001
            return {"detail": f"Die Verbindungsprüfung ist fehlgeschlagen: {exc}",
                    "verified": False}
        if outcome["ollama"] and outcome["ollama_model"]:
            detail = "Ollama ist erreichbar und das Modell ist installiert."
            verified = True
        elif outcome["ollama"]:
            detail = "Ollama ist erreichbar, aber das Modell fehlt noch."
            verified = False
        else:
            detail = "Ollama ist weiterhin nicht erreichbar."
            verified = False
        if outcome["gemini"]:
            detail += " Gemini ist erreichbar."
        return {"detail": detail, "verified": verified, "data": outcome}

    def _purge_logs(self, *, days: int = 60, **_: Any) -> dict:
        removed = self.repo.purge_old_logs(days=days)
        total = sum(removed.values())
        return {
            "detail": f"{total} alte Protokolleinträge wurden entfernt.",
            "verified": True,
            "data": removed,
        }

    def _remove_temp(self, **_: Any) -> dict:
        removed = 0
        freed = 0
        tmp = self.opts.path("tmp")
        if tmp.is_dir():
            for entry in tmp.iterdir():
                try:
                    if entry.is_dir():
                        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        size = entry.stat().st_size
                        entry.unlink()
                    removed += 1
                    freed += size
                except OSError:
                    continue
        return {
            "detail": f"{removed} temporäre Datei(en) entfernt ({freed} Bytes).",
            "verified": True,
            "data": {"removed": removed, "freed_bytes": freed},
        }

    # -- automatic cycle ------------------------------------------------------

    def automatic_cycle(self) -> list[dict[str, Any]]:
        """Run the safe checks and repairs that are allowed without confirmation."""

        if not self.enabled:
            return []
        results: list[dict[str, Any]] = []

        stale = self.repo.stale_running_jobs(older_than_seconds=1800)
        if stale:
            results.append(self.run("reset_stale_job").as_dict())

        failed = self.repo.list_jobs(status="failed", limit=5)
        retryable = [j for j in failed
                     if int(j.get("attempts") or 0) < int(j.get("max_attempts") or 3)]
        if retryable:
            results.append(self.run("requeue_job", job_id=int(retryable[0]["id"])).as_dict())

        if self.worker is not None and not self.worker.is_alive():
            results.append(self.run("restart_worker").as_dict())

        try:
            cache = self.repo.cache_stats()
            if cache["entries"] > 20000:
                results.append(self.run("prune_cache", keep=10000).as_dict())
        except Exception as exc:  # noqa: BLE001
            logger.debug("cache maintenance skipped: %s", exc)

        tmp = self.opts.path("tmp")
        if tmp.is_dir():
            try:
                stale_files = [f for f in tmp.iterdir()
                               if f.stat().st_mtime < __import__("time").time() - 86400]
                if stale_files:
                    results.append(self.run("remove_temp_files").as_dict())
            except OSError:
                pass

        return results
