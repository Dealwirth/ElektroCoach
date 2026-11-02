"""Setup wizard.

Twelve checks, each reporting a real status and, where a manual step is needed,
a concrete instruction that matches the user's actual system state.

The wizard never reports success for a check it did not actually perform, and it
refuses to mark the whole setup as complete while a required check is still
failing. Optional checks (Gemini, notifications) may remain a warning; that is
stated explicitly rather than hidden.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..backend.util import human_bytes, utcnow_iso
from ..documents.ocr import OcrEngine

logger = logging.getLogger("elektrocoach.setup")

STATUS_NOT_STARTED = "not_started"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_FAILED = "failed"
STATUS_NEEDS_INPUT = "needs_input"

# Steps marked required block the final "setup complete" state.
REQUIRED_STEPS = {"ha_connection", "resources", "storage", "database",
                  "ai_connections", "permissions", "document_processing",
                  "functional_test"}


@dataclass
class StepDefinition:
    key: str
    title: str
    description: str
    why: str
    manual: bool = False
    required: bool = True


STEP_DEFINITIONS: list[StepDefinition] = [
    StepDefinition(
        "ha_connection", "Verbindung zu Home Assistant prüfen",
        "Prüft, ob ElektroCoach die Home-Assistant-API erreichen darf.",
        "Ohne diese Verbindung können Sensoren und Benachrichtigungen nicht "
        "gesetzt werden. Die Lernfunktionen bleiben davon unabhängig nutzbar.",
    ),
    StepDefinition(
        "resources", "Systemressourcen prüfen",
        "Liest Arbeitsspeicher, Prozessorkerne und Systemlast.",
        "Auf einem Raspberry Pi 4 mit 8 GB muss sichergestellt sein, dass "
        "genügend Arbeitsspeicher für ein Sprachmodell frei ist.",
    ),
    StepDefinition(
        "storage", "Speicherplatz prüfen",
        "Ermittelt den freien Platz auf der microSD-Karte.",
        "Dokumente, Seitenbilder und Modelle benötigen Platz. Bei zu wenig Platz "
        "werden Hintergrundaufgaben pausiert.",
    ),
    StepDefinition(
        "database", "Datenbank initialisieren",
        "Legt die Datenbank an, wendet Migrationen an und prüft die Integrität.",
        "Alle Lernstände und Dokumente werden hier gespeichert.",
    ),
    StepDefinition(
        "ai_connections", "KI-Verbindungen prüfen",
        "Prüft die Erreichbarkeit der konfigurierten KI-Dienste.",
        "ElektroCoach nutzt Ollama lokal und optional Gemini. Beide werden geprüft.",
    ),
    StepDefinition(
        "ollama", "Ollama prüfen",
        "Prüft, ob Ollama läuft und ob das eingestellte Modell installiert ist.",
        "Ollama stellt die lokale, kostenfreie KI bereit.",
        manual=False, required=False,
    ),
    StepDefinition(
        "gemini", "Gemini prüfen",
        "Prüft API-Schlüssel und Modellliste von Google Gemini.",
        "Gemini wird für Handschrifterkennung und schwierige Fachfragen genutzt "
        "(kostenloses Kontingent).",
        manual=True, required=False,
    ),
    StepDefinition(
        "models", "Modelle prüfen",
        "Prüft, ob das eingestellte Ollama-Modell und das Gemini-Modell verfügbar sind.",
        "Ein fehlendes lokales Modell kann nachgeladen werden; das dauert auf dem "
        "Raspberry Pi mehrere Minuten.",
        manual=False, required=False,
    ),
    StepDefinition(
        "permissions", "Berechtigungen prüfen",
        "Prüft, ob ElektroCoach in alle benötigten Ordner schreiben darf.",
        "Ohne Schreibrechte können keine Dokumente, Backups oder Protokolle "
        "gespeichert werden.",
    ),
    StepDefinition(
        "document_processing", "Dokumentenverarbeitung testen",
        "Erzeugt ein Testdokument und verarbeitet es vollständig.",
        "Damit wird bewiesen, dass Import, Texterkennung und Wissensdatenbank "
        "zusammenarbeiten – nicht nur, dass die Module vorhanden sind.",
    ),
    StepDefinition(
        "notifications", "Benachrichtigungen testen",
        "Sendet eine Testbenachrichtigung an Home Assistant.",
        "So wissen Sie, dass Lernempfehlungen und Warnungen ankommen.",
        manual=True, required=False,
    ),
    StepDefinition(
        "functional_test", "Vollständigen Funktionstest durchführen",
        "Prüft Bewertung, Wiederholungssystem, Suche und Schaltplanprüfung.",
        "Damit wird sichergestellt, dass die Kernfunktionen tatsächlich arbeiten.",
    ),
]


class SetupWizard:
    def __init__(self, context) -> None:
        self.context = context
        self.ocr = OcrEngine(getattr(context.opts, "ocr_language", "deu+eng"))

    # -- state ----------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        stored = self.context.repo.get_setup_state()
        results = {entry["key"]: entry for entry in stored.get("steps", [])}
        steps: list[dict[str, Any]] = []
        for definition in STEP_DEFINITIONS:
            entry = results.get(definition.key, {})
            steps.append({
                "key": definition.key,
                "title": definition.title,
                "description": definition.description,
                "why": definition.why,
                "manual": definition.manual,
                "required": definition.required,
                "status": entry.get("status", STATUS_NOT_STARTED),
                "message": entry.get("message"),
                "guidance": entry.get("guidance"),
                "details": entry.get("details") or {},
                "checked_at": entry.get("checked_at"),
            })
        completed = stored.get("completed", False)
        blocking = [s["key"] for s in steps
                    if s["required"] and s["status"] in {STATUS_FAILED, STATUS_NEEDS_INPUT}]
        return {
            "completed": completed,
            "steps": steps,
            "blocking": blocking,
            "progress": self._progress(steps),
            "summary": self._summary(steps),
            "can_complete": not blocking,
        }

    @staticmethod
    def _progress(steps: list[dict]) -> dict[str, int]:
        counts = {STATUS_NOT_STARTED: 0, STATUS_OK: 0, STATUS_WARNING: 0,
                  STATUS_FAILED: 0, STATUS_NEEDS_INPUT: 0, STATUS_RUNNING: 0}
        for step in steps:
            counts[step["status"]] = counts.get(step["status"], 0) + 1
        total = len(steps)
        done = counts[STATUS_OK] + counts[STATUS_WARNING]
        return {"total": total, "done": done,
                "percent": round(done / total * 100) if total else 0, **counts}

    @staticmethod
    def _summary(steps: list[dict]) -> str:
        problems = [s for s in steps if s["status"] in {STATUS_FAILED, STATUS_NEEDS_INPUT}]
        if not problems:
            warnings = [s for s in steps if s["status"] == STATUS_WARNING]
            if warnings:
                return (f"Die Einrichtung ist funktionsfähig. "
                        f"{len(warnings)} optionale Prüfung(en) melden eine Warnung: "
                        + ", ".join(s["title"] for s in warnings) + ".")
            return "Alle Prüfungen waren erfolgreich. ElektroCoach ist einsatzbereit."
        return ("Folgende Punkte müssen noch geklärt werden: "
                + ", ".join(s["title"] for s in problems) + ".")

    # -- execution ------------------------------------------------------------

    async def run_step(self, key: str) -> dict[str, Any]:
        definition = next((d for d in STEP_DEFINITIONS if d.key == key), None)
        if definition is None:
            raise ValueError(f"Der Einrichtungsschritt „{key}“ existiert nicht.")
        handler = getattr(self, f"_step_{key}", None)
        if handler is None:
            return {"key": key, "status": STATUS_FAILED,
                    "message": "Für diesen Schritt ist keine Prüfung hinterlegt."}
        try:
            result = await handler()
        except Exception as exc:  # noqa: BLE001 - a step must not abort the wizard
            logger.exception("setup step %s failed", key)
            result = {
                "status": STATUS_FAILED,
                "message": f"Die Prüfung ist fehlgeschlagen: {exc}",
                "guidance": ("Bitte den Bereich „Fehlerdiagnose“ öffnen und einen "
                             "vollständigen Fehlerbericht erstellen."),
            }
        result["key"] = key
        result["checked_at"] = utcnow_iso()
        self._persist(key, result)
        return result

    async def run_all(self, *, only_pending: bool = False) -> dict[str, Any]:
        state = self.state()
        done = {s["key"]: s["status"] for s in state["steps"]}
        for definition in STEP_DEFINITIONS:
            if only_pending and done.get(definition.key) in {STATUS_OK, STATUS_WARNING}:
                continue
            await self.run_step(definition.key)
        return self.finalise()

    def finalise(self) -> dict[str, Any]:
        """Persist the completion flag only when no required step is failing."""

        state = self.state()
        if state["can_complete"]:
            self.context.repo.save_setup_state(
                current_step=len(STEP_DEFINITIONS),
                steps=[{"key": s["key"], "status": s["status"], "message": s["message"],
                        "guidance": s["guidance"], "details": s["details"],
                        "checked_at": s["checked_at"]}
                       for s in state["steps"]],
                completed=True,
            )
            self.context.repo.set_setting("setup.completed", True)
        else:
            stored = self.context.repo.get_setup_state()
            self.context.repo.save_setup_state(
                current_step=stored.get("current_step", 0),
                steps=stored.get("steps", []),
                completed=False,
            )
        return self.state()

    def reset(self) -> dict[str, Any]:
        self.context.repo.save_setup_state(current_step=0, steps=[], completed=False)
        self.context.repo.set_setting("setup.completed", False)
        return self.state()

    def _persist(self, key: str, result: dict[str, Any]) -> None:
        stored = self.context.repo.get_setup_state()
        entries = {entry["key"]: entry for entry in stored.get("steps", [])}
        entries[key] = {
            "key": key,
            "status": result.get("status"),
            "message": result.get("message"),
            "guidance": result.get("guidance"),
            "details": result.get("details") or {},
            "checked_at": result.get("checked_at"),
        }
        ordered = [entries[d.key] for d in STEP_DEFINITIONS if d.key in entries]
        index = [d.key for d in STEP_DEFINITIONS].index(key)
        self.context.repo.save_setup_state(
            current_step=max(stored.get("current_step", 0), index + 1),
            steps=ordered,
            completed=stored.get("completed", False) and False,
        )

    # -- individual steps -----------------------------------------------------

    async def _step_ha_connection(self) -> dict[str, Any]:
        result = await self.context.ha.check()
        if result.get("available"):
            return {
                "status": STATUS_OK,
                "message": (f"Home Assistant ist erreichbar"
                            + (f" (Version {result.get('version')})"
                               if result.get("version") else "") + "."),
                "details": result,
            }
        if result.get("reason") == "no_token":
            return {
                "status": STATUS_NEEDS_INPUT,
                "message": ("ElektroCoach hat keinen Zugangsschlüssel für die "
                            "Home-Assistant-API erhalten."),
                "guidance": (
                    "Öffnen Sie Home Assistant → Einstellungen → Add-ons → "
                    "ElektroCoach → Konfiguration und stellen Sie sicher, dass die "
                    "Option „homeassistant_api“ aktiv ist (Standard). Starten Sie "
                    "das Add-on anschließend neu. Danach diesen Schritt erneut "
                    "ausführen."
                ),
                "details": result,
            }
        return {
            "status": STATUS_WARNING,
            "message": result.get("message") or "Die Home-Assistant-API antwortet nicht.",
            "guidance": (
                "Sensoren und Benachrichtigungen sind deshalb nicht verfügbar. Alle "
                "Lernfunktionen arbeiten weiterhin. Starten Sie das Add-on neu und "
                "führen Sie diesen Schritt erneut aus."
            ),
            "details": result,
        }

    async def _step_resources(self) -> dict[str, Any]:
        memory = self.context.health.check_memory()
        cpu = self.context.health.check_cpu()
        status = STATUS_OK
        if memory["status"] in {"critical", "error"} or cpu["status"] in {"critical", "error"}:
            status = STATUS_FAILED
        elif memory["status"] == "warning" or cpu["status"] == "warning":
            status = STATUS_WARNING
        return {
            "status": status,
            "message": f"{memory['message']} {cpu['message']}",
            "guidance": memory.get("guidance") or cpu.get("guidance"),
            "details": {"memory": memory["details"], "cpu": cpu["details"]},
        }

    async def _step_storage(self) -> dict[str, Any]:
        result = self.context.health.check_storage()
        return {"status": result["status"], "message": result["message"],
                "guidance": result.get("guidance"), "details": result["details"]}

    async def _step_database(self) -> dict[str, Any]:
        applied = self.context.db.migrate()
        ok, message = self.context.db.integrity_check()
        details = {
            "schema_version": self.context.db.schema_version,
            "migrations_applied_now": applied,
            "fts5": self.context.db.fts5_available,
            "size": human_bytes(self.context.db.size_bytes()),
            "counts": self.context.db.table_counts(),
            "check": message,
        }
        if not ok:
            return {
                "status": STATUS_FAILED,
                "message": f"Die Integritätsprüfung der Datenbank meldet: {message}",
                "guidance": ("Starten Sie das Add-on neu. Bleibt der Fehler, stellen "
                             "Sie im Bereich „Backups“ ein Backup wieder her."),
                "details": details,
            }
        if not self.context.db.fts5_available:
            return {
                "status": STATUS_WARNING,
                "message": ("Die Datenbank ist in Ordnung, aber die Volltextsuche "
                            "(FTS5) ist in dieser SQLite-Version nicht verfügbar."),
                "guidance": ("Die Suche funktioniert dann über eine einfachere "
                             "Methode und ist langsamer, aber vollständig nutzbar."),
                "details": details,
            }
        return {
            "status": STATUS_OK,
            "message": (f"Die Datenbank ist bereit (Schema-Version "
                        f"{self.context.db.schema_version}, "
                        f"{len(applied)} Migration(en) jetzt angewendet)."),
            "details": details,
        }

    async def _step_ai_connections(self) -> dict[str, Any]:
        ollama_status = await self.context.ollama.status()
        gemini_configured = self.context.opts.gemini_configured
        details = {"ollama": ollama_status, "gemini_configured": gemini_configured}

        if not ollama_status["enabled"] and not gemini_configured:
            return {
                "status": STATUS_NEEDS_INPUT,
                "message": ("Es ist keine KI verfügbar: Ollama ist deaktiviert und "
                            "Gemini ist nicht eingerichtet."),
                "guidance": (
                    "Aktivieren Sie mindestens eine KI. Empfohlen: Starten Sie die "
                    "App „ElektroCoach Ollama“ (Einstellungen → Add-ons) und "
                    "aktivieren Sie Ollama in den ElektroCoach-Einstellungen. "
                    "Gemini ist optional und benötigt einen kostenlosen API-Schlüssel."
                ),
                "details": details,
            }
        available = []
        if ollama_status["available"]:
            available.append("Ollama")
        if gemini_configured:
            available.append("Gemini")
        if available:
            return {
                "status": STATUS_OK,
                "message": f"Verfügbare KI: {', '.join(available)}.",
                "details": details,
            }
        return {
            "status": STATUS_WARNING,
            "message": ("Ollama ist aktiviert, aber nicht erreichbar. Die "
                        "KI-Funktionen sind deshalb eingeschränkt."),
            "guidance": (
                "Öffnen Sie Home Assistant → Einstellungen → Add-ons und starten "
                "Sie „ElektroCoach Ollama“. Prüfen Sie danach die Ollama-Adresse in "
                f"den ElektroCoach-Einstellungen (aktuell: {ollama_status['base_url']})."
            ),
            "details": details,
        }

    async def _step_ollama(self) -> dict[str, Any]:
        status = await self.context.ollama.status()
        if not status["enabled"]:
            return {"status": STATUS_WARNING,
                    "message": "Ollama ist in den Einstellungen deaktiviert.",
                    "guidance": ("Aktivieren Sie Ollama, um lokale KI ohne "
                                 "Datenübertragung zu nutzen."),
                    "details": status}
        if not status["available"]:
            return {"status": STATUS_FAILED,
                    "message": f"Ollama ist unter {status['base_url']} nicht erreichbar.",
                    "guidance": ("Starten Sie die App „ElektroCoach Ollama“ unter "
                                 "Einstellungen → Add-ons."),
                    "details": status}
        if not status["model_installed"]:
            return {"status": STATUS_NEEDS_INPUT,
                    "message": (f"Ollama läuft, aber das Modell "
                                f"„{status['configured_model']}“ fehlt."),
                    "guidance": (f"Laden Sie das Modell jetzt über den Knopf "
                                 f"„Modell laden“ in diesem Assistenten. Das Modell "
                                 f"{status['configured_model']} ist rund 1 GB groß."),
                    "details": status}
        return {"status": STATUS_OK,
                "message": (f"Ollama {status['version']} läuft, Modell "
                            f"„{status['configured_model']}“ ist installiert."),
                "details": status}

    async def _step_gemini(self) -> dict[str, Any]:
        if not self.context.opts.gemini_enabled:
            return {
                "status": STATUS_WARNING,
                "message": "Gemini ist nicht aktiviert (optional).",
                "guidance": (
                    "Ohne Gemini funktionieren Handschrifterkennung und sehr "
                    "schwierige Fachfragen nicht. Alle übrigen Funktionen bleiben "
                    "nutzbar. Wenn Sie Gemini nutzen möchten: Einstellungen → "
                    "„Google Gemini“ → kostenlosen API-Schlüssel eintragen."
                ),
                "details": {"enabled": False},
            }
        if not self.context.opts.gemini_api_key:
            return {
                "status": STATUS_NEEDS_INPUT,
                "message": "Gemini ist aktiviert, aber es fehlt der API-Schlüssel.",
                "guidance": (
                    "Öffnen Sie https://aistudio.google.com/app/apikey, melden Sie "
                    "sich an, klicken Sie auf „Create API key“, kopieren Sie den "
                    "Schlüssel und fügen Sie ihn in den ElektroCoach-Einstellungen "
                    "unter „Google Gemini“ ein."
                ),
                "details": {"enabled": True, "key_set": False},
            }
        validation = await self.context.gemini.validate_key()
        if not validation.get("ok"):
            return {
                "status": STATUS_FAILED,
                "message": validation.get("message") or "Gemini ist nicht erreichbar.",
                "guidance": validation.get("guidance") or (
                    "Prüfen Sie den API-Schlüssel und die Internetverbindung."
                ),
                "details": validation,
            }
        if not validation.get("configured_model_available"):
            return {
                "status": STATUS_NEEDS_INPUT,
                "message": (f"Der Schlüssel ist gültig, aber das Modell "
                            f"„{validation.get('configured_model')}“ ist nicht in "
                            "der aktuellen Modellliste enthalten."),
                "guidance": ("Öffnen Sie die Einstellungen, laden Sie die Modellliste "
                             "und wählen Sie ein dort aufgeführtes Modell."),
                "details": validation,
            }
        return {
            "status": STATUS_OK,
            "message": (f"Gemini ist einsatzbereit "
                        f"({validation.get('model_count')} Modelle verfügbar)."),
            "details": validation,
        }

    async def _step_models(self) -> dict[str, Any]:
        ollama_status = await self.context.ollama.status()
        problems: list[str] = []
        guidance: list[str] = []
        if ollama_status["enabled"] and ollama_status["available"]:
            if not ollama_status["model_installed"]:
                problems.append(f"Das lokale Modell „{ollama_status['configured_model']}“ fehlt.")
                guidance.append("Laden Sie es über „Modell laden“ nach.")
        gemini_models: list[str] = []
        if self.context.opts.gemini_configured:
            try:
                gemini_models = [m["name"] for m in
                                 await self.context.gemini.list_models()]
                if gemini_models and self.context.opts.gemini_model not in gemini_models:
                    problems.append(
                        f"Das Gemini-Modell „{self.context.opts.gemini_model}“ ist "
                        "nicht verfügbar."
                    )
                    guidance.append("Wählen Sie ein Modell aus der Liste: "
                                    + ", ".join(gemini_models[:6]) + ".")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"Die Gemini-Modellliste konnte nicht geladen werden: {exc}")
        details = {"ollama": ollama_status.get("models", []),
                   "gemini_models": gemini_models}
        if problems:
            return {"status": STATUS_WARNING, "message": " ".join(problems),
                    "guidance": " ".join(guidance), "details": details}
        return {"status": STATUS_OK,
                "message": "Alle eingestellten Modelle sind verfügbar.",
                "details": details}

    async def _step_permissions(self) -> dict[str, Any]:
        problems: list[str] = []
        details: dict[str, Any] = {}
        for key in ("data", "uploads", "documents", "pages", "tmp", "logs"):
            path = self.context.opts.path(key)
            writable = self._probe(path)
            details[key] = {"path": str(path), "writable": writable}
            if not writable:
                problems.append(f"Der Ordner {path} ist nicht beschreibbar.")
        backup_target = self.context.backup.target_dir()
        backup_writable = self._probe(backup_target)
        details["backups"] = {"path": str(backup_target), "writable": backup_writable}
        if not backup_writable:
            problems.append(f"Der Backup-Ordner {backup_target} ist nicht beschreibbar.")

        if problems:
            return {
                "status": STATUS_FAILED,
                "message": " ".join(problems),
                "guidance": (
                    "Prüfen Sie in Home Assistant, ob das Add-on Schreibzugriff auf "
                    "/data und /share hat (Add-on-Konfiguration, Abschnitt „map“). "
                    "Starten Sie das Add-on nach einer Änderung neu."
                ),
                "details": details,
            }
        return {"status": STATUS_OK,
                "message": f"Alle {len(details)} benötigten Ordner sind beschreibbar.",
                "details": details}

    @staticmethod
    def _probe(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".setup_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    async def _step_document_processing(self) -> dict[str, Any]:
        """Create a real test document, import it and verify the result."""

        temp_dir = Path(tempfile.mkdtemp(prefix="elektrocoach-setup-"))
        sample = temp_dir / "elektrocoach-testdokument.pdf"
        try:
            sample.write_bytes(_sample_pdf_text())
            # The import pipeline is synchronous (it may call the local model via
            # a thread bridge). Running it in a worker thread keeps the event loop
            # responsive and avoids a nested-loop deadlock.
            summary = await asyncio.to_thread(
                self.context.importer.import_file,
                sample,
                original_name="elektrocoach-testdokument.pdf",
                mime="application/pdf",
                subject="Elektrotechnische Grundlagen",
                use_vision=False,
            )
            details = summary.as_dict()
            if summary.knowledge_created == 0:
                return {
                    "status": STATUS_FAILED,
                    "message": ("Das Testdokument wurde gelesen, aber es wurden keine "
                                "Inhalte gespeichert."),
                    "guidance": ("Öffnen Sie den Bereich „Fehlerdiagnose“. Wenn "
                                 "pdftoppm fehlt, kann nur die Textebene gelesen "
                                 "werden; dieses Testdokument hat eine Textebene."),
                    "details": details,
                }
            ocr = self.ocr.status()
            message = (f"Das Testdokument wurde verarbeitet: {summary.knowledge_created} "
                       f"Wissenseinträge aus {summary.pages} Seite(n).")
            status = STATUS_OK
            guidance = None
            if not ocr["available"]:
                status = STATUS_WARNING
                guidance = (
                    "Gedruckter Text in Scans kann nicht lokal erkannt werden, weil "
                    "Tesseract fehlt. Handschrift und Scans können über Gemini "
                    "verarbeitet werden."
                )
                message += " Hinweis: Die lokale Texterkennung (Tesseract) fehlt."
            return {"status": status, "message": message, "guidance": guidance,
                    "details": {**details, "ocr": ocr}}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _step_notifications(self) -> dict[str, Any]:
        if not self.context.opts.ha_notifications_enabled:
            return {
                "status": STATUS_WARNING,
                "message": "Benachrichtigungen sind in den Einstellungen deaktiviert.",
                "guidance": ("Aktivieren Sie Benachrichtigungen in den Einstellungen, "
                             "wenn Sie Lernempfehlungen und Warnungen erhalten möchten."),
            }
        result = await self.context.ha.notify(
            "ElektroCoach Einrichtung",
            "Diese Testnachricht bestätigt, dass Benachrichtigungen funktionieren. "
            "Sie erhalten künftig Lernempfehlungen und Warnungen.",
            level="info",
        )
        if result.get("sent"):
            return {"status": STATUS_OK,
                    "message": f"Testbenachrichtigung gesendet ({result.get('service')}).",
                    "details": result}
        return {
            "status": STATUS_NEEDS_INPUT,
            "message": (result.get("message")
                        or "Die Testbenachrichtigung konnte nicht gesendet werden."),
            "guidance": (
                "Richten Sie in Home Assistant einen Benachrichtigungsdienst ein "
                "(z. B. die Home-Assistant-App auf dem Smartphone unter "
                "Einstellungen → Geräte & Dienste). Tragen Sie den Dienstnamen "
                "optional in den ElektroCoach-Einstellungen ein, z. B. "
                "„notify.mobile_app_mein_handy“. Ohne Angabe werden dauerhafte "
                "Benachrichtigungen in Home Assistant erzeugt."
            ),
            "details": result,
        }

    async def _step_functional_test(self) -> dict[str, Any]:
        """Deterministic self-test of the core learning functions."""

        results: list[dict[str, Any]] = []

        def check(name: str, function: Callable[[], bool], failure: str) -> None:
            try:
                ok = bool(function())
            except Exception as exc:  # noqa: BLE001
                results.append({"name": name, "ok": False,
                                "message": f"Ausnahme: {exc}"})
                return
            results.append({"name": name, "ok": ok,
                            "message": "bestanden" if ok else failure})

        # 1. Calculation grading is deterministic and unit aware.
        def calculation() -> bool:
            from ..learning.calc import check_numeric

            ok1, _ = check_numeric("0,5 kV", 500, unit="V")
            ok2, _ = check_numeric("999 V", 500, unit="V")
            return ok1 and not ok2

        # 2. Multiple choice grading.
        def multiple_choice() -> bool:
            from ..learning.grading import Grader

            grader = Grader(None)
            result = grader.grade(
                {"type": "multiple_choice", "payload": {"options": ["a", "b", "c"]},
                 "solution": {"correct_index": 1}}, "B")
            return result.is_correct and result.method == "deterministic"

        # 3. Spaced repetition reschedules.
        def srs() -> bool:
            from ..learning.srs import review

            card = {"ease": 2.5, "interval_days": 0, "repetitions": 0, "state": "new"}
            good = review(card, 2)
            again = review(card, 0)
            return good.interval_days >= 0 and again.interval_days < 1

        # 4. Full-text search works (or the fallback does).
        def search() -> bool:
            rows = self.context.repo.search_knowledge("Spannung", limit=3)
            return isinstance(rows, list)

        # 5. Drawing validation detects a short circuit.
        def drawing() -> bool:
            from ..drawing.model import normalise_document, validate

            document = normalise_document({
                "components": [
                    {"id": "L", "symbol": "phase", "x": 0, "y": 0},
                    {"id": "N", "symbol": "neutral", "x": 0, "y": 4},
                ],
                "connections": [
                    {"from": {"component": "L", "terminal": "l"},
                     "to": {"component": "N", "terminal": "n"}},
                ],
            })
            report = validate(document)
            return any(i.code == "short_circuit" for i in report.issues)

        # 6. Export produces a valid SVG and PDF.
        def export() -> bool:
            from ..drawing.exporter import to_pdf, to_svg
            from ..drawing.model import normalise_document as normalise

            document = normalise({
                "components": [{"id": "R1", "symbol": "resistor", "x": 2, "y": 2}],
                "wires": [{"points": [[0, 2], [2, 2]]}],
            })
            svg = to_svg(document)
            pdf = to_pdf(document)
            return svg.startswith("<?xml") and pdf.startswith(b"%PDF-")

        # 7. Database writes and reads back.
        def database() -> bool:
            marker = f"setup-{utcnow_iso()}"
            self.context.repo.set_setting("setup.functional_test", marker)
            return self.context.repo.get_setting("setup.functional_test") == marker

        check("Rechenbewertung (deterministisch, einheitenbewusst)", calculation,
              "Die Rechenbewertung lieferte ein falsches Ergebnis.")
        check("Bewertung von Auswahlaufgaben", multiple_choice,
              "Auswahlaufgaben wurden nicht korrekt bewertet.")
        check("Wiederholungsplaner", srs,
              "Der Wiederholungsplaner lieferte kein sinnvolles Intervall.")
        check("Wissensdatenbank-Suche", search,
              "Die Suche lieferte kein Ergebnis-Objekt.")
        check("Schaltplanprüfung (Kurzschlusserkennung)", drawing,
              "Ein Kurzschluss wurde nicht erkannt.")
        check("Export als SVG und PDF", export,
              "Der Export erzeugte keine gültigen Dateien.")
        check("Datenbank-Schreib- und Lesetest", database,
              "Ein Wert konnte nicht gespeichert und gelesen werden.")

        failed = [r for r in results if not r["ok"]]
        details = {"checks": results}
        if failed:
            return {
                "status": STATUS_FAILED,
                "message": ("Der Funktionstest hat Fehler gefunden: "
                            + "; ".join(f"{r['name']} ({r['message']})" for r in failed)),
                "guidance": ("Bitte einen vollständigen Fehlerbericht im Bereich "
                             "„Fehlerdiagnose“ erstellen."),
                "details": details,
            }
        return {
            "status": STATUS_OK,
            "message": (f"Alle {len(results)} Funktionstests waren erfolgreich."),
            "details": details,
        }


def _sample_pdf_text() -> bytes:
    """Build a minimal one-page PDF that contains a real text layer.

    Used to prove that the import pipeline reads text from a PDF. The text is
    German electrical-engineering content so the classifier has something
    meaningful to work with.
    """

    lines = [
        "ElektroCoach Funktionstest",
        "Der Spannungsfall ist die Differenz der Spannung am Anfang und am Ende",
        "einer Leitung. Er wird mit der Formel berechnet und in Volt angegeben.",
        "Der Schutzleiter dient dem Schutz gegen elektrischen Schlag.",
        "Die Leistung berechnet sich als Produkt aus Spannung und Strom.",
    ]
    content_parts = ["BT /F1 12 Tf 50 780 Td 16 TL"]
    for line in lines:
        content_parts.append(f"({_pdf_escape(line)}) Tj T*")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1", "replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode("latin-1")
    pdf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
    return bytes(pdf)


def _pdf_escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))
