"""Diagnostics and user-facing troubleshooting reports.

Requirement 4.2: when ElektroCoach cannot fix a problem itself, it must produce a
complete report — description, time, affected component, suspected and confirmed
cause, repair attempts, log excerpts, the exact solution and the ordered steps —
written so a non-programmer can follow it. No bare "Connection failed.".

This module turns a failing health check into exactly that report.
"""

from __future__ import annotations

import logging
from typing import Any

from ..backend.logging_setup import recent_log_entries
from ..backend.util import utcnow_iso

logger = logging.getLogger("elektrocoach.monitoring.diagnostics")

# Ordered, concrete instructions per component. Placeholders are filled from the
# live check details so the text always matches the user's actual system state.
GUIDANCE: dict[str, dict[str, Any]] = {
    "Ollama": {
        "why": (
            "Ollama stellt die lokale KI bereit. Ohne Ollama funktionieren "
            "einfache Aufgaben (Klassifizierung, Lernkarten, Zusammenfassungen) "
            "nicht. Lernen, Datenbank und Schaltplaneditor funktionieren weiterhin."
        ),
        "steps": [
            "Öffnen Sie Home Assistant.",
            "Gehen Sie zu „Einstellungen“ → „Add-ons“.",
            "Suchen Sie in der Liste die App „ElektroCoach Ollama“.",
            "Klicken Sie auf die App und dann auf „Starten“, falls sie nicht läuft.",
            "Warten Sie, bis der Status „Wird ausgeführt“ anzeigt.",
            "Öffnen Sie den Reiter „Protokoll“ der Ollama-App und warten Sie auf "
            "eine Zeile mit „starting server on 0.0.0.0:11434“.",
            "Kehren Sie zu ElektroCoach zurück und öffnen Sie „Systemstatus“.",
            "Klicken Sie bei der Zeile „Ollama“ auf „Erneut prüfen“.",
        ],
        "success": (
            "Die Zeile „Ollama“ zeigt grün „Ollama … ist erreichbar, Modell … ist "
            "installiert“."
        ),
        "if_error": (
            "Erscheint die Meldung weiterhin, prüfen Sie in den ElektroCoach-"
            "Einstellungen die Ollama-Adresse. Sie muss auf die ElektroCoach-"
            "Ollama-App zeigen. Der Standardwert ist "
            "„http://a0d7b954-ollama:11434“."
        ),
    },
    "Gemini": {
        "why": (
            "Gemini wird für Handschrifterkennung und schwierige Fachfragen "
            "verwendet. Es ist ausschließlich die kostenlose Nutzung vorgesehen."
        ),
        "steps": [
            "Öffnen Sie ElektroCoach und gehen Sie zu „Einstellungen“.",
            "Suchen Sie den Abschnitt „Google Gemini“.",
            "Öffnen Sie in einem Browser die Seite https://aistudio.google.com/app/apikey.",
            "Melden Sie sich mit Ihrem Google-Konto an.",
            "Klicken Sie auf „Create API key“ und kopieren Sie den Schlüssel.",
            "Fügen Sie den Schlüssel in das Feld „Gemini-API-Schlüssel“ ein.",
            "Setzen Sie den Schalter „Gemini verwenden“ auf aktiv.",
            "Öffnen Sie die Modellliste und wählen Sie ein dort angezeigtes Modell "
            "(z. B. ein Modell mit „flash“ im Namen).",
            "Klicken Sie auf „Speichern“.",
            "Öffnen Sie „Systemstatus“ und klicken Sie bei „Gemini“ auf „Erneut prüfen“.",
        ],
        "success": "Die Zeile „Gemini“ zeigt grün „Gemini ist erreichbar …“.",
        "if_error": (
            "Erscheint „Der Gemini-API-Schlüssel wurde abgelehnt“, wurde der "
            "Schlüssel falsch kopiert oder ist gesperrt. Erstellen Sie in der "
            "Google AI Studio einen neuen Schlüssel und tragen Sie ihn erneut ein."
        ),
    },
    "Datenbank": {
        "why": "Alle Lernstände, Dokumente und Einstellungen liegen in der Datenbank.",
        "steps": [
            "Öffnen Sie den Bereich „Backups“.",
            "Prüfen Sie, ob ein Backup mit dem Status „in Ordnung“ vorhanden ist.",
            "Klicken Sie bei diesem Backup auf „Integrität prüfen“.",
            "Klicken Sie anschließend auf „Wiederherstellen“ und bestätigen Sie "
            "die Rückfrage.",
            "Warten Sie, bis die Meldung „Wiederherstellung abgeschlossen“ erscheint.",
            "Öffnen Sie „Systemstatus“ und klicken Sie auf „Erneut prüfen“.",
        ],
        "success": "Die Zeile „Datenbank“ zeigt grün „Die Datenbank ist in Ordnung …“.",
        "if_error": (
            "Ist kein Backup vorhanden, starten Sie das ElektroCoach-Add-on neu "
            "(Einstellungen → Add-ons → ElektroCoach → Neu starten). Tritt der "
            "Fehler danach erneut auf, wenden Sie sich mit dem vollständigen "
            "Fehlerbericht an den Support."
        ),
    },
    "Speicher": {
        "why": (
            "Die microSD-Karte ist begrenzt. Ist sie voll, können keine Dokumente "
            "mehr gespeichert und keine Modelle geladen werden."
        ),
        "steps": [
            "Öffnen Sie den Bereich „Backups“.",
            "Löschen Sie Sicherungen, die Sie nicht mehr benötigen, mit „Löschen“.",
            "Öffnen Sie den Bereich „Dokumentenimport“ und entfernen Sie "
            "Dokumente, die Sie nicht mehr brauchen.",
            "Öffnen Sie den Bereich „Fehlerdiagnose“ und klicken Sie auf "
            "„Temporäre Dateien entfernen“.",
            "Öffnen Sie den Bereich „Fehlerdiagnose“ und klicken Sie auf "
            "„Datenbank verdichten“.",
            "Prüfen Sie in „Systemstatus“ den freien Speicher erneut.",
        ],
        "success": "Die Zeile „Speicher“ zeigt grün, dass genügend Platz frei ist.",
        "if_error": (
            "Reicht der Platz weiterhin nicht, schließen Sie eine SSD an und "
            "verschieben Sie die Daten. ElektroCoach ist darauf vorbereitet."
        ),
    },
    "RAM": {
        "why": "Der Raspberry Pi 4 hat 8 GB Arbeitsspeicher; das Modell belegt davon einen Teil.",
        "steps": [
            "Öffnen Sie den Bereich „KI-Assistent“.",
            "Klicken Sie auf „Modell entladen“.",
            "Warten Sie 10 Sekunden.",
            "Öffnen Sie „Systemstatus“ und prüfen Sie die Zeile „RAM“ erneut.",
            "Läuft weiterhin eine schwere KI-Aufgabe, warten Sie deren Ende ab.",
        ],
        "success": "Die Zeile „RAM“ zeigt grün mit ausreichend freiem Speicher.",
        "if_error": (
            "Bleibt der Speicher voll, starten Sie die Ollama-App neu "
            "(Einstellungen → Add-ons → ElektroCoach Ollama → Neu starten)."
        ),
    },
    "Aufgaben": {
        "why": "Hintergrundaufgaben übernehmen den Dokumentenimport und die Aufgabenerzeugung.",
        "steps": [
            "Öffnen Sie den Bereich „Fehlerdiagnose“.",
            "Suchen Sie die fehlgeschlagene Aufgabe in der Liste.",
            "Lesen Sie die angezeigte Fehlermeldung.",
            "Klicken Sie auf „Erneut versuchen“.",
            "Prüfen Sie in „Systemstatus“, ob die Zeile „Aufgaben“ grün wird.",
        ],
        "success": "Es sind keine fehlgeschlagenen Aufgaben mehr vorhanden.",
        "if_error": (
            "Schlägt die Aufgabe erneut fehl, ist die Ursache häufig die "
            "zugrunde liegende Datei. Importieren Sie das Dokument erneut, "
            "möglichst als PDF."
        ),
    },
    "Backups": {
        "why": "Backups schützen Ihre Lernstände und Dokumente.",
        "steps": [
            "Öffnen Sie den Bereich „Backups“.",
            "Prüfen Sie die angezeigte Zeile „Zielordner“.",
            "Ist der Zielordner nicht beschreibbar, wird automatisch der interne "
            "Ordner /data/backups verwendet.",
            "Klicken Sie auf „Backup jetzt erstellen“.",
            "Warten Sie, bis das Backup mit Status „in Ordnung“ erscheint.",
        ],
        "success": "Unter „Letztes Backup“ steht ein aktuelles Datum.",
        "if_error": (
            "Wird das Backup nicht erstellt, prüfen Sie in „Systemstatus“ die "
            "Zeile „Speicher“. Ist die Karte voll, geben Sie zuerst Speicher frei."
        ),
    },
    "Texterkennung": {
        "why": "Die lokale Texterkennung wandelt gedruckten Text aus Scans in Text um.",
        "steps": [
            "Öffnen Sie in Home Assistant „Einstellungen“ → „Add-ons“ → "
            "„ElektroCoach“.",
            "Klicken Sie auf „Neu starten“.",
            "Warten Sie, bis das Add-on wieder läuft.",
            "Öffnen Sie „Systemstatus“ und klicken Sie auf „Erneut prüfen“.",
        ],
        "success": "Die Zeile „Texterkennung“ zeigt grün mit den Sprachen deu und eng.",
        "if_error": (
            "Bleibt die Meldung bestehen, ist das Add-on ohne OCR-Pakete gebaut "
            "worden. Handschrift und schwierige Scans können weiterhin über "
            "Gemini verarbeitet werden."
        ),
    },
    "Website": {
        "why": "Die Website ist die Bedienoberfläche von ElektroCoach.",
        "steps": [
            "Öffnen Sie in Home Assistant „Einstellungen“ → „Add-ons“ → "
            "„ElektroCoach“.",
            "Klicken Sie auf „Neu starten“.",
            "Öffnen Sie ElektroCoach erneut über die Seitenleiste.",
            "Laden Sie die Seite mit gedrückter Umschalttaste neu, um den "
            "Browser-Cache zu leeren.",
        ],
        "success": "Die ElektroCoach-Oberfläche erscheint vollständig.",
        "if_error": (
            "Erscheint die Seite weiterhin unvollständig, deinstallieren Sie das "
            "Add-on und installieren Sie es erneut. Ihre Daten bleiben unter "
            "/data erhalten, solange das Add-on nicht mit „Daten löschen“ "
            "entfernt wird."
        ),
    },
}

DEFAULT_GUIDANCE = {
    "why": "Diese Komponente ist Teil der Selbstüberwachung von ElektroCoach.",
    "steps": [
        "Öffnen Sie den Bereich „Systemstatus“.",
        "Klicken Sie auf „Erneut prüfen“.",
        "Warten Sie, bis die Prüfung abgeschlossen ist.",
        "Prüfen Sie, ob die betroffene Zeile weiterhin rot oder gelb ist.",
    ],
    "success": "Die betroffene Zeile zeigt grün „in Ordnung“.",
    "if_error": (
        "Bleibt der Fehler bestehen, erstellen Sie über „Fehlerbericht erstellen“ "
        "einen vollständigen Bericht und senden Sie ihn an den Support."
    ),
}


class DiagnosticsService:
    def __init__(self, repo, opts, health, repair, *, app_version: str = "0.1.0") -> None:
        self.repo = repo
        self.opts = opts
        self.health = health
        self.repair = repair
        self.app_version = app_version

    async def run(self, *, auto_repair: bool = True) -> dict[str, Any]:
        run_id = self.repo.start_diagnostics()
        report = await self.health.full_report()

        repairs: list[dict[str, Any]] = []
        if auto_repair and report["overall"] in {"warning", "error", "critical"}:
            repairs = self.repair.automatic_cycle()
            if repairs:
                # Re-check after repairing so the report shows the real state.
                report = await self.health.full_report()
                report["repairs"] = repairs

        self._record_events(report)

        status = "ok" if report["overall"] == "ok" else "attention"
        self.repo.finish_diagnostics(run_id, report=report, status=status)
        report["run_id"] = run_id
        report["auto_repairs"] = repairs
        report["troubleshooting"] = self._troubleshooting(report)
        return report

    def _record_events(self, report: dict) -> None:
        """Persist problems as events, but do not duplicate an open event."""

        for check in report.get("checks", []):
            if check["status"] not in {"warning", "error", "critical"}:
                continue
            level = "critical" if check["status"] == "critical" else (
                "error" if check["status"] == "error" else "warning"
            )
            existing = self.repo.db.query_one(
                "SELECT id FROM system_events WHERE category = ? AND resolved = 0 "
                "AND message LIKE ? ORDER BY id DESC LIMIT 1",
                ("health", f"%{check['name']}%"),
            )
            if existing:
                continue
            self.repo.add_event(
                level=level, category="health",
                message=f"{check['name']}: {check['message']}",
                details={"check": check["name"], "status": check["status"],
                         "details": check.get("details", {})},
            )

    def _troubleshooting(self, report: dict) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for check in report.get("checks", []):
            if check["status"] in {"warning", "error", "critical"}:
                out.append(self.guidance_for(check["name"], check=check))
        return out

    def guidance_for(self, component: str, *, check: dict | None = None) -> dict[str, Any]:
        template = GUIDANCE.get(component, DEFAULT_GUIDANCE)
        return {
            "component": component,
            "problem": (check or {}).get("message"),
            "status": (check or {}).get("status"),
            "why": template["why"],
            "steps": list(template["steps"]),
            "success": template["success"],
            "if_error": template["if_error"],
            "what_happens_next": (
                "Nachdem Sie die Schritte ausgeführt haben, klicken Sie im Bereich "
                "„Systemstatus“ auf „Erneut prüfen“. ElektroCoach prüft dann "
                "automatisch, ob das Problem behoben ist, und meldet das Ergebnis."
            ),
        }

    # -- error report ---------------------------------------------------------

    def error_report(self, *, event_id: int | None = None,
                     component: str | None = None) -> dict[str, Any]:
        """Build the complete error report required by section 4.2."""

        event = None
        if event_id is not None:
            row = self.repo.db.query_one("SELECT * FROM system_events WHERE id = ?",
                                         (event_id,))
            event = dict(row) if row else None
        elif component:
            row = self.repo.db.query_one(
                "SELECT * FROM system_events WHERE resolved = 0 AND message LIKE ? "
                "ORDER BY id DESC LIMIT 1", (f"%{component}%",)
            )
            event = dict(row) if row else None
        else:
            row = self.repo.db.query_one(
                "SELECT * FROM system_events WHERE resolved = 0 "
                "ORDER BY CASE level WHEN 'critical' THEN 0 WHEN 'error' THEN 1 "
                "ELSE 2 END, id DESC LIMIT 1"
            )
            event = dict(row) if row else None

        component_name = component or self._component_from_event(event)
        last = self.repo.last_diagnostics() or {}
        report = last.get("report") or {}
        check = next(
            (c for c in report.get("checks", []) if c["name"] == component_name), None
        )

        guidance = self.guidance_for(component_name, check=check)
        repairs = [r for r in self.repo.list_repairs(limit=20)
                   if not event or r.get("event_id") == event["id"]] or \
                  self.repo.list_repairs(limit=5)

        suspected = self._suspected_cause(component_name, check)
        confirmed = check["message"] if check and check["status"] != "ok" else None

        return {
            "created_at": utcnow_iso(),
            "description": (event or {}).get("message")
                           or (check or {}).get("message")
                           or f"Für die Komponente „{component_name}“ liegt kein "
                              "konkreter Fehler vor.",
            "time": (event or {}).get("created_at") or (check or {}).get("checked_at"),
            "component": component_name,
            "level": (event or {}).get("level") or (check or {}).get("status") or "info",
            "suspected_cause": suspected,
            "confirmed_cause": confirmed,
            "repair_attempts": [
                {"action": r["action"], "status": r["status"], "detail": r["detail"],
                 "at": r["created_at"]}
                for r in repairs
            ],
            "log_excerpt": self._log_excerpt(component_name),
            "system_state": {
                "overall": report.get("overall"),
                "version": report.get("version") or self.app_version,
                "generated_at": report.get("generated_at"),
                "check": check,
            },
            "solution": guidance["why"],
            "steps": guidance["steps"],
            "success_criteria": guidance["success"],
            "if_error": guidance["if_error"],
            "what_happens_next": guidance["what_happens_next"],
            "responsible_action": self._responsible_action(component_name),
        }

    def _component_from_event(self, event: dict | None) -> str:
        if not event:
            return "System"
        details = event.get("details")
        if isinstance(details, dict) and details.get("check"):
            return str(details["check"])
        message = str(event.get("message") or "")
        for name in GUIDANCE:
            if name in message:
                return name
        return "System"

    def _suspected_cause(self, component: str, check: dict | None) -> str:
        status = (check or {}).get("status")
        mapping = {
            "Ollama": (
                "Die Ollama-App läuft nicht, ist noch nicht fertig gestartet, oder "
                "die in den Einstellungen hinterlegte Adresse passt nicht."
            ),
            "Gemini": (
                "Der API-Schlüssel fehlt, ist falsch kopiert, wurde gesperrt, oder "
                "der Raspberry Pi hat keine Internetverbindung."
            ),
            "Datenbank": (
                "Die Datenbankdatei wurde beim Herunterfahren unterbrochen, oder "
                "es ist nicht genügend Speicherplatz für das WAL-Protokoll frei."
            ),
            "Speicher": "Auf der microSD-Karte sind zu wenige freie Bytes vorhanden.",
            "RAM": "Ein Sprachmodell belegt dauerhaft Arbeitsspeicher.",
            "Aufgaben": (
                "Eine Hintergrundaufgabe ist an einer beschädigten Datei oder an "
                "einer nicht erreichbaren KI gescheitert."
            ),
            "Texterkennung": "Die OCR-Pakete sind im Add-on-Image nicht vorhanden.",
            "Backups": "Der Zielordner ist nicht beschreibbar oder das Intervall ist sehr groß.",
            "Website": "Die Add-on-Dateien sind unvollständig entpackt.",
        }
        if component in mapping:
            return mapping[component]
        return (f"Die Prüfung meldet den Status „{status}“. Die genaue Ursache "
                "lässt sich aus den Protokollzeilen ableiten.")

    def _log_excerpt(self, component: str, limit: int = 25) -> list[dict[str, str]]:
        entries = recent_log_entries(200)
        key = component.lower()
        relevant = [e for e in entries if key in e["message"].lower()
                    or key in e["logger"].lower()]
        return (relevant or entries)[-limit:]

    def _responsible_action(self, component: str) -> str:
        if component in {"Ollama", "Texterkennung", "Website", "Datenbank", "RAM"}:
            return (
                "ElektroCoach kann diese Reparatur teilweise selbst durchführen "
                "(Neustart des Workers, Neuaufbau des Index, Verdichten der "
                "Datenbank). Für einen Neustart der Ollama-App ist Ihre Handlung "
                "erforderlich, weil ElektroCoach keine anderen Add-ons steuern darf."
            )
        if component == "Gemini":
            return (
                "Hier ist Ihre Handlung erforderlich: Nur Sie können einen "
                "API-Schlüssel in der Google AI Studio erstellen. ElektroCoach "
                "trägt ihn danach sicher ein und prüft die Verbindung erneut."
            )
        return (
            "ElektroCoach führt die sicheren Schritte selbst aus und prüft danach "
            "automatisch, ob der Fehler behoben ist."
        )
