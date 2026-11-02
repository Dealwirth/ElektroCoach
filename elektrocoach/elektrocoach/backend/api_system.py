"""System endpoints: status, diagnostics, repair, jobs, events, settings."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..backend.logging_setup import recent_log_entries

logger = logging.getLogger("elektrocoach.api.system")

router = APIRouter(prefix="/api", tags=["system"])

# Settings the UI may change. Anything else is rejected, so the API cannot be
# used to write arbitrary keys into the settings table.
EDITABLE_SETTINGS = {
    "learning.daily_goal_minutes": int,
    "learning.exam_date": str,
    "ui.theme": str,
    "ui.grid_size": int,
    "notifications.daily_reminder": bool,
    "notifications.reminder_time": str,
    "ai.prefer": str,
    "documents.auto_generate_questions": bool,
}

# Runtime options that require a restart of the add-on to take effect. They are
# stored in the database and shown to the user; the add-on options themselves
# are changed in the Home Assistant add-on configuration page.
RUNTIME_HINTS = {
    "ollama_url": "Wird in der Add-on-Konfiguration geändert.",
    "ollama_model": "Kann hier geändert werden; wirkt sofort.",
    "gemini_model": "Kann hier geändert werden; wirkt sofort.",
    "gemini_api_key": "Wird sicher gespeichert und nie an den Browser gesendet.",
}


class RepairRequest(BaseModel):
    action: str
    confirmed: bool = False
    job_id: int | None = None
    event_id: int | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class RuntimeSettings(BaseModel):
    ollama_model: str | None = Field(default=None, max_length=120)
    gemini_model: str | None = Field(default=None, max_length=120)
    gemini_api_key: str | None = Field(default=None, max_length=200)
    gemini_enabled: bool | None = None
    notify_service: str | None = Field(default=None, max_length=120)
    notifications_enabled: bool | None = None
    auto_repair_enabled: bool | None = None


# -- status / diagnostics ----------------------------------------------------

@router.get("/system/status")
async def system_status(context: AppContext = Depends(get_context),
                        checks: bool = Query(default=True)) -> dict[str, Any]:
    if not checks:
        return {"summary": context.summary()}
    try:
        report = await context.health.full_report()
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Systemstatus") from exc
    report["summary"] = context.summary()
    report["worker"] = context.worker.status
    report["backup_target"] = context.backup.target_info()
    return report


@router.post("/diagnostics/run")
async def run_diagnostics(context: AppContext = Depends(get_context),
                          auto_repair: bool = Query(default=True)) -> dict[str, Any]:
    try:
        return await context.diagnostics.run(auto_repair=auto_repair)
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Diagnose") from exc


@router.get("/diagnostics/last")
async def last_diagnostics(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    run = context.repo.last_diagnostics()
    if run is None:
        return {"run": None,
                "message": "Es wurde noch keine Systemprüfung durchgeführt."}
    return {"run": run}


@router.get("/diagnostics/repairs")
async def repair_actions(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return {
        "actions": context.repair.list_actions(),
        "history": context.repo.list_repairs(limit=30),
        "auto_repair_enabled": context.opts.auto_repair_enabled,
    }


@router.post("/diagnostics/actions")
async def run_repair(payload: RepairRequest,
                     context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Run a repair action.

    Safe actions run directly. Destructive actions require ``confirmed=true``;
    without it the endpoint returns an explanation instead of acting.
    """

    if not context.repair.enabled and not context.repair.is_safe(payload.action):
        raise HTTPException(
            status_code=403,
            detail=("Die automatische Reparatur ist in den Einstellungen "
                    "deaktiviert. Aktivieren Sie sie dort, um Reparaturen "
                    "auszuführen."),
        )
    result = context.repair.run(payload.action, confirmed=payload.confirmed,
                                event_id=payload.event_id, job_id=payload.job_id)
    if result.status == "failed":
        raise HTTPException(status_code=500, detail=result.detail)
    return result.as_dict()


@router.get("/diagnostics/report")
async def error_report(context: AppContext = Depends(get_context),
                       event_id: int | None = None,
                       component: str | None = None) -> dict[str, Any]:
    """Full, step-by-step error report (requirement 4.2)."""

    try:
        return context.diagnostics.error_report(event_id=event_id, component=component)
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Fehlerbericht") from exc


@router.get("/diagnostics/guidance/{component}")
async def guidance(component: str,
                   context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return context.diagnostics.guidance_for(component)


# -- events and logs ---------------------------------------------------------

@router.get("/events")
async def list_events(context: AppContext = Depends(get_context),
                      level: str | None = None,
                      unresolved_only: bool = False,
                      limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {
        "items": context.repo.list_events(level=level, unresolved_only=unresolved_only,
                                         limit=limit),
        "counts": context.repo.event_counts(),
    }


@router.post("/events/{event_id}/resolve")
async def resolve_event(event_id: int,
                        context: AppContext = Depends(get_context)) -> dict[str, Any]:
    context.repo.resolve_event(event_id)
    return {"resolved": event_id}


@router.get("/logs")
async def logs(limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
    """Recent log lines from the in-memory ring buffer (no file access)."""

    return {"items": recent_log_entries(limit)}


# -- jobs --------------------------------------------------------------------

@router.get("/jobs")
async def list_jobs(context: AppContext = Depends(get_context),
                    status_filter: str | None = Query(default=None, alias="status"),
                    limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {
        "items": context.repo.list_jobs(status=status_filter, limit=limit),
        "counts": context.repo.job_counts(),
        "worker": context.worker.status,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, context: AppContext = Depends(get_context)) -> dict[str, Any]:
    job = context.repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Der Auftrag {job_id} existiert nicht.")
    return job


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, context: AppContext = Depends(get_context)) -> dict[str, Any]:
    job = context.repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Der Auftrag {job_id} existiert nicht.")
    result = context.repair.run("requeue_job", job_id=job_id)
    return result.as_dict()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, context: AppContext = Depends(get_context)) -> dict[str, Any]:
    job = context.repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Der Auftrag {job_id} existiert nicht.")
    context.repo.cancel_job(job_id)
    return {"cancelled": job_id}


# -- settings ----------------------------------------------------------------

@router.get("/settings")
async def get_settings(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Return the current settings. **Secrets are never included.**"""

    settings = context.repo.all_settings()
    # Never return a stored secret, even though it lives in the settings table.
    settings.pop("runtime.gemini_api_key", None)
    return {
        "settings": settings,
        "editable": sorted(EDITABLE_SETTINGS.keys()),
        "runtime": {
            "ollama_url": context.opts.ollama_url,
            "ollama_model": context.ollama.model,
            "ollama_enabled": context.ollama.enabled,
            "gemini_enabled": context.gemini.enabled,
            "gemini_model": context.gemini.model,
            "gemini_api_key_set": bool(context.gemini.api_key),
            "gemini_daily_request_budget": context.opts.gemini_daily_request_budget,
            "notify_service": context.ha.notify_service,
            "notifications_enabled": context.ha.notifications_enabled,
            "auto_repair_enabled": context.repair.enabled,
            "backup_enabled": context.opts.backup_enabled,
            "backup_interval_hours": context.opts.backup_interval_hours,
            "backup_keep": context.opts.backup_keep,
            "storage_warning_percent": context.opts.storage_warning_percent,
            "storage_critical_percent": context.opts.storage_critical_percent,
            "monitoring_interval_seconds": context.opts.monitoring_interval_seconds,
            "ocr_language": context.opts.ocr_language,
        },
        "hints": RUNTIME_HINTS,
        "addon_options_note": (
            "Einige Werte (z. B. die Ollama-Adresse und das Backup-Intervall) "
            "werden in der Add-on-Konfiguration von Home Assistant geändert: "
            "Einstellungen → Add-ons → ElektroCoach → Konfiguration."
        ),
    }


@router.patch("/settings")
async def update_settings(payload: SettingsUpdate,
                          context: AppContext = Depends(get_context)) -> dict[str, Any]:
    rejected = [key for key in payload.values if key not in EDITABLE_SETTINGS]
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=(f"Die folgenden Einstellungen können nicht geändert werden: "
                    f"{', '.join(rejected)}."),
        )
    applied: dict[str, Any] = {}
    for key, value in payload.values.items():
        expected = EDITABLE_SETTINGS[key]
        try:
            if expected is int:
                value = int(value)
            elif expected is bool:
                value = bool(value)
            else:
                value = str(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Der Wert für „{key}“ hat ein ungültiges Format.",
            ) from exc
        context.repo.set_setting(key, value)
        applied[key] = value
    context.repo.audit("settings.update", detail=applied, actor="user")
    return {"applied": applied, "message": "Die Einstellungen wurden gespeichert."}


@router.patch("/settings/runtime")
async def update_runtime_settings(payload: RuntimeSettings,
                                  context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Change model names and the API key without editing the add-on options.

    The API key is written to the settings table (never logged, never returned).
    Model changes take effect immediately because the clients read them per call.
    """

    applied: dict[str, Any] = {}
    if payload.ollama_model is not None:
        model = payload.ollama_model.strip()
        if not model:
            raise HTTPException(status_code=400, detail="Der Modellname darf nicht leer sein.")
        context.ollama.model = model
        context.repo.set_setting("runtime.ollama_model", model)
        applied["ollama_model"] = model
    if payload.gemini_model is not None:
        model = payload.gemini_model.strip()
        if not model:
            raise HTTPException(status_code=400, detail="Der Modellname darf nicht leer sein.")
        context.gemini.model = model
        context.repo.set_setting("runtime.gemini_model", model)
        applied["gemini_model"] = model
    if payload.gemini_api_key is not None:
        key = payload.gemini_api_key.strip()
        context.gemini.api_key = key
        context.gemini._models_cache = None
        context.repo.set_setting("runtime.gemini_api_key", key)
        applied["gemini_api_key"] = "gespeichert" if key else "geleert"
    if payload.gemini_enabled is not None:
        context.gemini.enabled = payload.gemini_enabled
        context.repo.set_setting("runtime.gemini_enabled", payload.gemini_enabled)
        applied["gemini_enabled"] = payload.gemini_enabled
    if payload.notify_service is not None:
        context.ha.notify_service = payload.notify_service.strip()
        applied["notify_service"] = context.ha.notify_service
    if payload.notifications_enabled is not None:
        context.ha.notifications_enabled = payload.notifications_enabled
        context.repo.set_setting("runtime.notifications_enabled",
                                 payload.notifications_enabled)
        applied["notifications_enabled"] = payload.notifications_enabled
    if payload.auto_repair_enabled is not None:
        context.repair.enabled = payload.auto_repair_enabled
        applied["auto_repair_enabled"] = payload.auto_repair_enabled

    if not applied:
        raise HTTPException(status_code=400, detail="Es wurden keine Werte übergeben.")
    context.repo.audit("settings.runtime", detail=applied, actor="user")
    return {"applied": applied, "message": "Die Einstellungen wurden übernommen."}


@router.post("/settings/gemini/test")
async def test_gemini(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Validate the Gemini key and refresh the model list."""

    if not context.gemini.api_key:
        return {"ok": False,
                "message": ("Es ist kein Gemini-API-Schlüssel hinterlegt. Tragen Sie "
                            "ihn in den Einstellungen ein.")}
    validation = await context.gemini.validate_key()
    if not validation.get("ok"):
        return {"ok": False, "message": validation.get("message"),
                "guidance": validation.get("guidance")}
    return {
        "ok": True,
        "model_count": validation.get("model_count"),
        "models": validation.get("models"),
        "configured_model": validation.get("configured_model"),
        "configured_model_available": validation.get("configured_model_available"),
        "message": (f"Der Schlüssel ist gültig. {validation.get('model_count')} "
                    "Modelle sind verfügbar."
                    + ("" if validation.get("configured_model_available") else
                       " Achtung: Das eingestellte Modell ist nicht in der Liste – "
                       "wählen Sie ein anderes Modell.")),
    }


@router.post("/settings/ollama/test")
async def test_ollama(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    status = await context.ollama.status()
    if not status["available"]:
        return {
            "ok": False,
            "message": f"Ollama ist unter {status['base_url']} nicht erreichbar.",
            "guidance": (
                "Starten Sie die App „ElektroCoach Ollama“ unter Einstellungen → "
                "Add-ons und prüfen Sie die Adresse."
            ),
            "details": status,
        }
    return {
        "ok": True,
        "message": (f"Ollama {status['version']} ist erreichbar. Modell "
                    f"„{status['configured_model']}“ "
                    + ("ist installiert." if status["model_installed"]
                       else "ist noch nicht installiert.")),
        "details": status,
    }


# -- Home Assistant ----------------------------------------------------------

@router.get("/homeassistant/status")
async def ha_status(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    result = await context.ha.check()
    return {
        **result,
        "client": context.ha.status,
        "sensors": [{"entity_id": e, "name": n, "unit": u, "icon": i}
                    for e, n, u, i in _sensor_definitions()],
        "notifications": {
            "enabled": context.opts.ha_notifications_enabled,
            "service": context.opts.notify_service or "persistent_notification.create",
        },
    }


@router.post("/homeassistant/publish")
async def ha_publish(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Publish the current sensor values to Home Assistant."""

    values = _sensor_values(context)
    result = await context.ha.publish_sensors(values)
    return {**result,
            "message": (f"{len(result['written'])} Sensor(en) aktualisiert, "
                        f"{len(result['skipped'])} unverändert.")}


@router.post("/homeassistant/notify-test")
async def ha_notify_test(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    result = await context.ha.notify(
        "ElektroCoach Testbenachrichtigung",
        "Wenn Sie diese Nachricht sehen, funktionieren die Benachrichtigungen. "
        "ElektroCoach sendet Benachrichtigungen nur, wenn sie in den Einstellungen "
        "aktiviert sind.",
        level="info",
    )
    if not result.get("sent"):
        return {
            "ok": False,
            "message": result.get("message") or "Die Benachrichtigung wurde nicht gesendet.",
            "guidance": (
                "Prüfen Sie, ob die Benachrichtigungen in den ElektroCoach-"
                "Einstellungen aktiviert sind und ob ein Benachrichtigungsdienst "
                "in Home Assistant eingerichtet ist (z. B. die Home-Assistant-App "
                "auf Ihrem Smartphone)."
            ),
        }
    return {"ok": True, "service": result.get("service"),
            "message": "Die Testbenachrichtigung wurde gesendet."}


@router.get("/notifications")
async def list_notifications(context: AppContext = Depends(get_context),
                             limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"items": context.repo.list_notifications(limit=limit)}


def _sensor_definitions():
    from ..integrations.homeassistant import SENSOR_DEFINITIONS

    return SENSOR_DEFINITIONS


def _sensor_values(context: AppContext) -> dict[str, Any]:
    """Build the sensor payload. Only values that exist are included."""

    stats = context.learning.stats()
    attempts_30 = stats["attempts_30d"]
    percent = round(attempts_30["avg_ratio"] * 100, 1) if attempts_30["total"] else 0.0
    counts = context.db.table_counts()
    last_backup = context.repo.last_successful_backup()
    events = context.repo.event_counts()
    storage = _free_gb(context)

    ai_available = []
    if context.opts.ollama_enabled:
        ai_available.append("ollama")
    if context.opts.gemini_configured:
        ai_available.append("gemini")

    return {
        "sensor.elektrocoach_lernfortschritt": percent,
        "sensor.elektrocoach_faellige_wiederholungen": context.repo.count_due_cards(),
        "sensor.elektrocoach_offene_aufgaben": context.repo.job_counts().get("queued", 0),
        "sensor.elektrocoach_naechste_wiederholung": _next_due(context),
        "sensor.elektrocoach_systemstatus": (context.repo.last_diagnostics() or {}).get(
            "status", "unbekannt"),
        "sensor.elektrocoach_ki_verfuegbarkeit": ", ".join(ai_available) or "keine",
        "sensor.elektrocoach_gemini_kontingent": context.repo.ai_budget_today(
            "gemini")["requests_used"],
        "sensor.elektrocoach_speicher_frei": storage,
        "sensor.elektrocoach_dokumente": counts.get("documents", 0),
        "sensor.elektrocoach_wissenseintraege": counts.get("knowledge_items", 0),
        "sensor.elektrocoach_fehler": (events.get("error", 0) + events.get("critical", 0)),
        "sensor.elektrocoach_letztes_backup": (last_backup or {}).get("created_at", "nie"),
    }


def _free_gb(context: AppContext) -> float:
    import shutil

    try:
        usage = shutil.disk_usage(context.opts.data_dir)
        return round(usage.free / 1024 / 1024 / 1024, 2)
    except OSError:
        return 0.0


def _next_due(context: AppContext) -> str:
    row = context.db.query_one(
        "SELECT due_at FROM srs_cards WHERE due_at > ? ORDER BY due_at LIMIT 1",
        (__import__("elektrocoach.backend.util", fromlist=["utcnow_iso"]).utcnow_iso(),),
    )
    return str(row["due_at"]) if row else "keine"
