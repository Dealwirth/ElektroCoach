"""Job handlers: the actual work behind each background task type."""

from __future__ import annotations

import logging
from typing import Any

from ..backend.util import utcnow_iso

logger = logging.getLogger("elektrocoach.jobs.handlers")


class JobHandlers:
    """Registers concrete handlers with the worker.

    Handlers receive a :class:`~elektrocoach.jobs.worker.JobContext` and return a
    JSON-serialisable result dict. Raising an exception marks the job as failed
    with the exception message, which is what the diagnostics UI shows.
    """

    def __init__(self, repo, opts, *, importer=None, generator=None, backup=None,
                 diagnostics=None, dispatcher=None, learning=None) -> None:
        self.repo = repo
        self.opts = opts
        self.importer = importer
        self.generator = generator
        self.backup = backup
        self.diagnostics = diagnostics
        self.dispatcher = dispatcher
        self.learning = learning

    def register_all(self, worker) -> None:
        worker.register("import_document", self.import_document)
        worker.register("reprocess_document", self.reprocess_document)
        worker.register("generate_questions", self.generate_questions)
        worker.register("create_backup", self.create_backup)
        worker.register("restore_backup", self.restore_backup)
        worker.register("run_diagnostics", self.run_diagnostics)
        worker.register("purge_logs", self.purge_logs)
        worker.register("prune_ai_cache", self.prune_ai_cache)
        worker.register("download_model", self.download_model)

    # -- document import ------------------------------------------------------

    def import_document(self, context) -> dict[str, Any]:
        if self.importer is None:
            raise RuntimeError("Der Dokumentenimport ist nicht verfügbar.")
        payload = context.payload
        document_id = payload.get("document_id")
        if document_id:
            context.log(f"reprocessing document {document_id}")
            summary = self.importer.reprocess(
                int(document_id),
                use_vision=bool(payload.get("use_vision", True)),
                progress=lambda value, message: context.progress(value, message),
            )
        else:
            path = payload.get("path")
            if not path:
                raise ValueError("Der Auftrag enthält keinen Dateipfad.")
            context.log(f"importing {path}")
            summary = self.importer.import_file(
                path,
                original_name=payload.get("original_name"),
                mime=payload.get("mime"),
                subject=payload.get("subject"),
                use_vision=bool(payload.get("use_vision", True)),
                progress=lambda value, message: context.progress(value, message),
            )
        result = summary.as_dict()
        # Newly imported material should become learnable material.
        if self.learning is not None and result.get("knowledge_created"):
            context.log("generating initial questions from the imported material")
            self.repo.enqueue_job(
                type="generate_questions",
                payload={"source": "import", "document_id": result["document_id"],
                         "count": 5},
                priority=6,
            )
        return result

    def reprocess_document(self, context) -> dict[str, Any]:
        payload = dict(context.payload)
        payload.setdefault("document_id", payload.get("document_id"))
        return self.import_document(context)

    # -- question generation --------------------------------------------------

    def generate_questions(self, context) -> dict[str, Any]:
        if self.generator is None:
            raise RuntimeError("Die Aufgabenerzeugung ist nicht verfügbar.")
        payload = context.payload
        subject = payload.get("subject")
        topic = payload.get("topic")
        count = int(payload.get("count") or 5)
        use_ai = bool(payload.get("use_ai", True))

        created: dict[str, list[int]] = {"calculation": [], "cloze": [], "matching": [],
                                        "ai": []}
        context.progress(0.1, "Rechenaufgaben werden erstellt …")
        created["calculation"] = self.generator.calculation_questions(
            subject=subject, count=max(1, count // 2)
        )
        context.progress(0.35, "Lückentexte werden erstellt …")
        created["cloze"] = self.generator.cloze_questions(subject=subject,
                                                          count=max(1, count // 3))
        context.progress(0.55, "Zuordnungsaufgaben werden erstellt …")
        created["matching"] = self.generator.matching_questions(subject=subject, count=1)

        if use_ai and subject:
            context.progress(0.7, "KI-Aufgaben werden erstellt …")
            try:
                created["ai"] = self.generator.ai_questions(
                    subject=subject, topic=topic, count=max(1, count // 2)
                )
            except Exception as exc:  # noqa: BLE001 - AI generation is optional
                context.log(f"AI generation skipped: {exc}")
                self.repo.add_event(
                    level="warning", category="learning",
                    message=("Die KI-Aufgabenerzeugung konnte nicht ausgeführt werden. "
                             f"Grund: {exc}"),
                    details={"subject": subject, "topic": topic},
                )

        all_ids = [qid for ids in created.values() for qid in ids]
        if self.learning is not None and all_ids:
            context.progress(0.9, "Aufgaben werden in den Lernplan aufgenommen …")
            self.learning.ensure_cards(all_ids)
        total = len(all_ids)
        if total == 0:
            raise RuntimeError(
                "Es konnten keine Aufgaben erstellt werden. Importieren Sie zuerst "
                "Dokumente im Bereich „Dokumentenimport“."
            )
        context.progress(1.0, f"{total} Aufgaben erstellt.")
        return {"created": created, "total": total}

    # -- backups --------------------------------------------------------------

    def create_backup(self, context) -> dict[str, Any]:
        if self.backup is None:
            raise RuntimeError("Die Backup-Funktion ist nicht verfügbar.")
        context.progress(0.2, "Backup wird erstellt …")
        record = self.backup.create(kind=context.payload.get("kind", "auto"),
                                    note=context.payload.get("note"))
        context.progress(1.0, "Backup abgeschlossen.")
        return record

    def restore_backup(self, context) -> dict[str, Any]:
        if self.backup is None:
            raise RuntimeError("Die Backup-Funktion ist nicht verfügbar.")
        backup_id = context.payload.get("backup_id")
        if backup_id is None:
            raise ValueError("Es wurde kein Backup ausgewählt.")
        context.progress(0.2, "Sicherheitsbackup wird angelegt …")
        result = self.backup.restore(int(backup_id))
        context.progress(1.0, "Wiederherstellung abgeschlossen.")
        return result

    # -- maintenance ----------------------------------------------------------

    def run_diagnostics(self, context) -> dict[str, Any]:
        if self.diagnostics is None:
            raise RuntimeError("Die Fehlerdiagnose ist nicht verfügbar.")
        from ..backend.runtime import run_coroutine

        context.progress(0.1, "Systemprüfung läuft …")
        report = run_coroutine(self.diagnostics.run(auto_repair=True), timeout=180)
        context.progress(1.0, "Systemprüfung abgeschlossen.")
        return {"overall": report.get("overall"), "counts": report.get("counts"),
                "auto_repairs": report.get("auto_repairs")}

    def purge_logs(self, context) -> dict[str, Any]:
        removed = self.repo.purge_old_logs(days=int(context.payload.get("days") or 60))
        return {"removed": removed}

    def prune_ai_cache(self, context) -> dict[str, Any]:
        keep = int(context.payload.get("keep") or 5000)
        removed = self.repo.prune_ai_cache(keep=keep)
        return {"removed": removed, "stats": self.repo.cache_stats()}

    def download_model(self, context) -> dict[str, Any]:
        """Pull an Ollama model, reporting progress into the job record."""

        if self.dispatcher is None:
            raise RuntimeError("Der KI-Dispatcher ist nicht verfügbar.")
        model = context.payload.get("model")
        if not model:
            raise ValueError("Es wurde kein Modell angegeben.")
        from ..backend.runtime import run_coroutine

        async def pull() -> dict[str, Any]:
            last: dict[str, Any] = {}
            async for event in self.dispatcher.ollama.pull_model(str(model)):
                if event.get("error"):
                    raise RuntimeError(f"Fehler beim Laden des Modells: {event['error']}")
                percent = float(event.get("percent") or 0.0)
                status = event.get("status") or "lädt"
                context.progress(percent / 100.0, f"{status} ({percent:.0f} %)")
                last = event
            return last

        run_coroutine(pull(), timeout=3600)
        return {"model": model, "installed": True}
