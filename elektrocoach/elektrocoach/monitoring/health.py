"""Health checks for the self-monitoring system.

Every check returns a uniform dictionary so the UI can render the system status
table directly. Checks are cheap: they read ``/proc`` files, run a SQLite
``quick_check`` and query the already-instantiated clients. Nothing here blocks
for long, and a failing check never raises — it reports the failure.

Statuses: ``ok``, ``warning``, ``error``, ``critical``, ``disabled``.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from ..backend.util import human_bytes, parse_iso, utcnow
from ..documents import pdf_tools
from ..documents.ocr import OcrEngine

logger = logging.getLogger("elektrocoach.monitoring.health")

STATUS_ORDER = {"critical": 0, "error": 1, "warning": 2, "ok": 3, "disabled": 4}


def _result(name: str, status: str, message: str, *, guidance: str | None = None,
            details: dict | None = None, duration_ms: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "guidance": guidance,
        "details": details or {},
        "duration_ms": duration_ms,
    }


def _timed(name: str, function: Callable[[], dict]) -> dict:
    started = time.monotonic()
    try:
        result = function()
    except Exception as exc:  # noqa: BLE001 - a check must never crash the report
        logger.warning("check %s failed: %s", name, exc)
        return _result(name, "error", f"Die Prüfung ist fehlgeschlagen: {exc}",
                       guidance="Bitte den Fehlerbericht im Bereich "
                                "„Fehlerdiagnose“ ansehen.")
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


class HealthService:
    def __init__(self, repo, opts, *, ollama=None, gemini=None, dispatcher=None,
                 app_version: str = "0.1.0") -> None:
        self.repo = repo
        self.opts = opts
        self.ollama = ollama
        self.gemini = gemini
        self.dispatcher = dispatcher
        self.app_version = app_version
        self.ocr = OcrEngine(getattr(opts, "ocr_language", "deu+eng"))

    # -- individual checks ----------------------------------------------------

    def check_backend(self) -> dict:
        return _result(
            "Backend", "ok",
            f"Das Backend läuft (Version {self.app_version}, PID {os.getpid()}).",
            details={"version": self.app_version, "pid": os.getpid()},
        )

    def check_frontend(self) -> dict:
        index = self.opts.path("frontend") / "index.html"
        assets = self.opts.path("frontend") / "assets"
        if not index.is_file():
            return _result(
                "Website", "error",
                "Die Startseite der Website wurde nicht gefunden.",
                guidance=(
                    "Die Installation ist unvollständig. Installieren Sie das "
                    "ElektroCoach-Add-on neu, damit die Dateien entpackt werden."
                ),
                details={"index": str(index)},
            )
        missing_assets = []
        for name in ("app.js", "styles.css"):
            if not (assets / name).is_file():
                missing_assets.append(name)
        if missing_assets:
            return _result(
                "Website", "warning",
                f"Einzelne Dateien der Website fehlen: {', '.join(missing_assets)}.",
                guidance="Add-on neu installieren.",
                details={"missing": missing_assets},
            )
        return _result("Website", "ok", "Alle Dateien der Website sind vorhanden.",
                       details={"index": str(index)})

    def check_database(self) -> dict:
        try:
            ok, message = self.repo.db.quick_check()
        except Exception as exc:  # noqa: BLE001
            return _result(
                "Datenbank", "critical",
                f"Die Datenbank ist nicht erreichbar: {exc}",
                guidance=(
                    "Starten Sie das Add-on neu. Bleibt der Fehler bestehen, "
                    "spielen Sie ein Backup ein (Bereich „Backups“)."
                ),
            )
        size = self.repo.db.size_bytes()
        counts = self.repo.db.table_counts()
        if not ok:
            return _result(
                "Datenbank", "critical",
                f"Die Integritätsprüfung der Datenbank meldet: {message}",
                guidance=(
                    "Öffnen Sie den Bereich „Backups“, prüfen Sie die Integrität "
                    "des letzten Backups und stellen Sie es wieder her."
                ),
                details={"check": message, "size": size},
            )
        return _result(
            "Datenbank", "ok",
            f"Die Datenbank ist in Ordnung ({human_bytes(size)}, "
            f"Schema-Version {self.repo.db.schema_version}).",
            details={"size_bytes": size, "counts": counts,
                     "schema_version": self.repo.db.schema_version},
        )

    def check_storage(self) -> dict:
        target = Path(self.opts.data_dir)
        try:
            usage = shutil.disk_usage(str(target if target.exists() else "/"))
        except OSError as exc:
            return _result("Speicher", "warning", f"Speicherplatz nicht lesbar: {exc}")
        percent = usage.used / usage.total * 100 if usage.total else 0
        details = {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round(percent, 1),
            "total_human": human_bytes(usage.total),
            "free_human": human_bytes(usage.free),
        }
        if percent >= self.opts.storage_critical_percent:
            return _result(
                "Speicher", "critical",
                f"Kritischer Speicherstand: {percent:.1f} % belegt, nur noch "
                f"{human_bytes(usage.free)} frei.",
                guidance=(
                    "Bitte sofort Speicher freigeben: alte Backups löschen, nicht "
                    "benötigte Dokumente entfernen oder eine SSD anschließen. "
                    "Hintergrundaufgaben werden automatisch pausiert."
                ),
                details=details,
            )
        if percent >= self.opts.storage_warning_percent:
            return _result(
                "Speicher", "warning",
                f"Der Speicher ist zu {percent:.1f} % belegt "
                f"({human_bytes(usage.free)} frei).",
                guidance=(
                    "Prüfen Sie im Bereich „Backups“, ob alte Sicherungen gelöscht "
                    "werden können. Neue Modell-Downloads sollten vermieden werden."
                ),
                details=details,
            )
        return _result(
            "Speicher", "ok",
            f"{human_bytes(usage.free)} von {human_bytes(usage.total)} frei "
            f"({percent:.1f} % belegt).",
            details=details,
        )

    def check_memory(self) -> dict:
        info = _read_meminfo()
        if not info:
            return _result("RAM", "warning", "Der Speicherverbrauch konnte nicht gelesen werden.")
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        used = max(0, total - available)
        percent = used / total * 100 if total else 0
        details = {
            "total_bytes": total * 1024,
            "available_bytes": available * 1024,
            "used_percent": round(percent, 1),
            "total_human": human_bytes(total * 1024),
            "available_human": human_bytes(available * 1024),
        }
        if percent >= 95:
            return _result(
                "RAM", "critical",
                f"Der Arbeitsspeicher ist fast voll ({percent:.0f} % belegt).",
                guidance=(
                    "Entladen Sie das Ollama-Modell (Bereich „KI-Assistent“) oder "
                    "starten Sie die Ollama-App neu. Auf einem Raspberry Pi 4 mit "
                    "8 GB sollte nur ein Modell gleichzeitig geladen sein."
                ),
                details=details,
            )
        if percent >= 85:
            return _result(
                "RAM", "warning",
                f"Der Arbeitsspeicher ist zu {percent:.0f} % belegt.",
                guidance="Prüfen Sie, ob ein Ollama-Modell entladen werden kann.",
                details=details,
            )
        return _result("RAM", "ok",
                       f"{human_bytes(available * 1024)} Arbeitsspeicher frei "
                       f"({percent:.0f} % belegt).", details=details)

    def check_cpu(self) -> dict:
        try:
            load1, load5, load15 = os.getloadavg()
        except OSError:
            return _result("CPU", "warning", "Die Systemlast konnte nicht gelesen werden.")
        cores = os.cpu_count() or 1
        ratio = load1 / cores
        details = {"load1": round(load1, 2), "load5": round(load5, 2),
                   "load15": round(load15, 2), "cores": cores,
                   "ratio": round(ratio, 2)}
        if ratio >= 2.0:
            return _result(
                "CPU", "warning",
                f"Die Systemlast ist hoch (Last {load1:.2f} bei {cores} Kernen).",
                guidance=(
                    "Warten Sie laufende KI-Aufgaben ab. Auf dem Raspberry Pi 4 "
                    "sollten nicht mehrere schwere Aufgaben gleichzeitig laufen."
                ),
                details=details,
            )
        return _result("CPU", "ok",
                       f"Systemlast {load1:.2f} bei {cores} Kernen.", details=details)

    async def check_ollama(self) -> dict:
        if self.ollama is None:
            return _result("Ollama", "disabled", "Ollama ist nicht eingebunden.")
        status = await self.ollama.status()
        if not status.get("enabled"):
            return _result(
                "Ollama", "disabled",
                "Ollama ist in den Einstellungen deaktiviert.",
                guidance="Aktivieren Sie Ollama in den Einstellungen, um lokale KI zu nutzen.",
                details=status,
            )
        if not status.get("available"):
            return _result(
                "Ollama", "error",
                f"Ollama ist unter {status.get('base_url')} nicht erreichbar.",
                guidance=(
                    "Öffnen Sie in Home Assistant „Einstellungen → Add-ons“ und "
                    "starten Sie „ElektroCoach Ollama“. Prüfen Sie danach die "
                    "Ollama-Adresse in den ElektroCoach-Einstellungen "
                    f"(aktuell: {status.get('base_url')})."
                ),
                details=status,
            )
        if not status.get("model_installed"):
            return _result(
                "Ollama", "warning",
                f"Ollama läuft, aber das Modell „{status.get('configured_model')}“ "
                "ist noch nicht installiert.",
                guidance=(
                    "Öffnen Sie den Einrichtungsassistenten und führen Sie den "
                    "Schritt „Modell laden“ aus, oder starten Sie die "
                    "ElektroCoach-Ollama-App neu – sie lädt das Modell beim Start."
                ),
                details=status,
            )
        loaded = status.get("loaded_model")
        return _result(
            "Ollama", "ok",
            f"Ollama {status.get('version')} ist erreichbar, Modell "
            f"„{status.get('configured_model')}“ ist installiert"
            + (f", geladen: {loaded}." if loaded else ", zurzeit nicht geladen."),
            details=status,
        )

    async def check_gemini(self) -> dict:
        if self.gemini is None:
            return _result("Gemini", "disabled", "Gemini ist nicht eingebunden.")
        used = self.repo.ai_budget_today("gemini")["requests_used"]
        status = await self.gemini.status(requests_used_today=used)
        if not status.get("enabled"):
            return _result(
                "Gemini", "disabled",
                "Gemini ist in den Einstellungen deaktiviert.",
                guidance=(
                    "Für Handschrifterkennung und schwierige Fachfragen ist Gemini "
                    "hilfreich. Aktivieren Sie es in den Einstellungen und tragen "
                    "Sie einen kostenlosen API-Schlüssel ein."
                ),
                details=status,
            )
        if not status.get("key_configured"):
            return _result(
                "Gemini", "warning",
                "Gemini ist aktiviert, aber es ist kein API-Schlüssel hinterlegt.",
                guidance=(
                    "Erstellen Sie in der Google AI Studio einen kostenlosen "
                    "API-Schlüssel und tragen Sie ihn in den ElektroCoach-"
                    "Einstellungen unter „Google Gemini“ ein."
                ),
                details=status,
            )
        if status.get("error"):
            return _result(
                "Gemini", "error",
                f"Gemini ist nicht erreichbar oder der Schlüssel wurde abgelehnt: "
                f"{status['error']}",
                guidance=status.get("guidance") or (
                    "Prüfen Sie den API-Schlüssel und die Internetverbindung."
                ),
                details=status,
            )
        remaining = status.get("requests_remaining")
        budget = status.get("daily_request_budget") or 0
        if budget and remaining is not None and remaining <= 0:
            return _result(
                "Gemini", "warning",
                f"Das lokale Tageslimit für Gemini ist erreicht "
                f"({used}/{budget} Anfragen). Aufgaben werden pausiert, nicht "
                "kostenpflichtig ausgeführt.",
                guidance=(
                    "Verwenden Sie für einfache Aufgaben Ollama oder versuchen Sie "
                    "es nach dem Kontingent-Reset erneut."
                ),
                details=status,
            )
        if not status.get("model_available", True):
            return _result(
                "Gemini", "warning",
                f"Das eingestellte Modell „{status.get('model')}“ ist nicht in der "
                "aktuellen Modellliste von Google enthalten.",
                guidance=(
                    "Öffnen Sie die Einstellungen und wählen Sie ein Modell aus der "
                    "dort angezeigten Liste. Die Liste wird live von Google geladen."
                ),
                details=status,
            )
        return _result(
            "Gemini", "ok",
            f"Gemini ist erreichbar (Modell „{status.get('model')}“, "
            f"{remaining} von {budget} Anfragen heute übrig).",
            details=status,
        )

    def check_jobs(self) -> dict:
        counts = self.repo.job_counts()
        stale = self.repo.stale_running_jobs(older_than_seconds=1800)
        details = {"counts": counts, "stale": len(stale)}
        if counts.get("failed"):
            return _result(
                "Aufgaben", "warning",
                f"{counts['failed']} Hintergrundaufgabe(n) sind fehlgeschlagen.",
                guidance=(
                    "Öffnen Sie den Bereich „Fehlerdiagnose“. Dort können "
                    "fehlgeschlagene Aufgaben nach Prüfung erneut ausgeführt werden."
                ),
                details=details,
            )
        if stale:
            return _result(
                "Aufgaben", "warning",
                f"{len(stale)} Aufgabe(n) laufen seit über 30 Minuten.",
                guidance=(
                    "Die automatische Reparatur kann hängende Aufgaben neu starten. "
                    "Prüfen Sie den Bereich „Fehlerdiagnose“."
                ),
                details=details,
            )
        return _result(
            "Aufgaben", "ok",
            f"{counts.get('running', 0)} laufend, {counts.get('queued', 0)} wartend, "
            f"{counts.get('done', 0)} abgeschlossen.",
            details=details,
        )

    def check_backups(self) -> dict:
        last = self.repo.last_successful_backup()
        if last is None:
            return _result(
                "Backups", "warning",
                "Es wurde noch kein Backup erstellt.",
                guidance=(
                    "Öffnen Sie den Bereich „Backups“ und erstellen Sie ein Backup. "
                    "Prüfen Sie dabei den angezeigten Zielordner."
                ),
            )
        created = parse_iso(last.get("created_at"))
        age_hours = (utcnow() - created).total_seconds() / 3600 if created else None
        details = {"last": last, "age_hours": round(age_hours, 1) if age_hours else None}
        if age_hours is not None and age_hours > self.opts.backup_interval_hours * 2:
            return _result(
                "Backups", "warning",
                f"Das letzte erfolgreiche Backup ist {age_hours:.0f} Stunden alt.",
                guidance=(
                    "Prüfen Sie, ob das automatische Backup aktiviert ist und ob "
                    "der Zielordner beschreibbar ist."
                ),
                details=details,
            )
        return _result(
            "Backups", "ok",
            f"Letztes Backup: {last['created_at']} "
            f"({human_bytes(last.get('size_bytes') or 0)}).",
            details=details,
        )

    def check_documents(self) -> dict:
        pages = self.repo.pages_needing_review(limit=500)
        documents = self.repo.count_documents()
        knowledge = self.repo.count_knowledge()
        details = {"documents": documents, "knowledge_items": knowledge,
                   "pages_needing_review": len(pages)}
        if pages:
            return _result(
                "Dokumente", "warning",
                f"{len(pages)} Seite(n) konnten nicht sicher erkannt werden und "
                "warten auf Ihre Prüfung.",
                guidance=(
                    "Öffnen Sie den Bereich „Dokumentenimport“, prüfen Sie die "
                    "markierten Seiten und korrigieren Sie den Text bei Bedarf. "
                    "Nicht erkannte Inhalte werden nicht erfunden."
                ),
                details=details,
            )
        return _result(
            "Dokumente", "ok",
            f"{documents} Dokument(e) und {knowledge} Wissenseinträge gespeichert.",
            details=details,
        )

    def check_ocr(self) -> dict:
        status = self.ocr.status()
        pdf_status = pdf_tools.tool_status()
        details = {"ocr": status, "pdf": pdf_status}
        if not status["available"]:
            return _result(
                "Texterkennung", "warning",
                "Tesseract ist nicht installiert. Gedruckter Text kann nicht lokal "
                "erkannt werden.",
                guidance=(
                    "Das offizielle ElektroCoach-Add-on enthält Tesseract. Wenn Sie "
                    "diese Meldung sehen, wurde das Add-on ohne die OCR-Pakete "
                    "gebaut. Handschrift kann weiterhin über Gemini erkannt werden."
                ),
                details=details,
            )
        if status.get("warning"):
            return _result("Texterkennung", "warning", status["warning"],
                           details=details)
        if not pdf_status.get("pdftoppm"):
            return _result(
                "Texterkennung", "warning",
                "pdftoppm fehlt. Gescannte PDF-Seiten können nicht in Bilder "
                "umgewandelt werden.",
                details=details,
            )
        return _result(
            "Texterkennung", "ok",
            f"Tesseract ist verfügbar (Sprachen: {', '.join(status['languages'])}).",
            details=details,
        )

    def check_ai_dispatcher(self) -> dict:
        if self.dispatcher is None:
            return _result("KI-Verwaltung", "disabled", "Der KI-Dispatcher ist nicht eingebunden.")
        usage = self.repo.ai_usage_summary(7)
        cache = self.repo.cache_stats()
        failures = sum(int(u.get("failures") or 0) for u in usage)
        details = {"usage": usage, "cache": cache,
                   "decisions": self.dispatcher.last_decisions(5)}
        if failures and failures > sum(int(u.get("requests") or 0) for u in usage) * 0.5:
            return _result(
                "KI-Verwaltung", "warning",
                f"{failures} KI-Anfragen sind in den letzten 7 Tagen fehlgeschlagen.",
                guidance="Prüfen Sie die Zeilen „Ollama“ und „Gemini“ in dieser Übersicht.",
                details=details,
            )
        return _result(
            "KI-Verwaltung", "ok",
            f"KI-Verwaltung aktiv. Zwischenspeicher: {cache['entries']} Einträge, "
            f"{cache['hits']} Treffer.",
            details=details,
        )

    # -- full report ----------------------------------------------------------

    async def full_report(self) -> dict[str, Any]:
        checks = [
            _timed("Backend", self.check_backend),
            _timed("Website", self.check_frontend),
            _timed("Datenbank", self.check_database),
            _timed("Speicher", self.check_storage),
            _timed("RAM", self.check_memory),
            _timed("CPU", self.check_cpu),
            await _timed_async("Ollama", self.check_ollama),
            await _timed_async("Gemini", self.check_gemini),
            _timed("Aufgaben", self.check_jobs),
            _timed("Backups", self.check_backups),
            _timed("Dokumente", self.check_documents),
            _timed("Texterkennung", self.check_ocr),
            _timed("KI-Verwaltung", self.check_ai_dispatcher),
        ]
        counts = {"ok": 0, "warning": 0, "error": 0, "critical": 0, "disabled": 0}
        for check in checks:
            counts[check["status"]] = counts.get(check["status"], 0) + 1
        overall = "ok"
        for status in ("critical", "error", "warning"):
            if counts.get(status):
                overall = status
                break
        events = self.repo.event_counts()
        return {
            "overall": overall,
            "counts": counts,
            "checks": checks,
            "events": events,
            "generated_at": utcnow().replace(microsecond=0).isoformat(),
            "version": self.app_version,
        }


async def _timed_async(name: str, coroutine_factory) -> dict:
    started = time.monotonic()
    try:
        result = await coroutine_factory()
    except Exception as exc:  # noqa: BLE001
        logger.warning("async check %s failed: %s", name, exc)
        return _result(name, "error", f"Die Prüfung ist fehlgeschlagen: {exc}")
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def _read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                parts = value.strip().split()
                if parts and parts[0].isdigit():
                    info[key.strip()] = int(parts[0])
    except OSError:
        return {}
    return info
