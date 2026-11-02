"""Application entry point.

Responsibilities:

* build the service context once,
* register the API routers,
* serve the static frontend,
* run a small background scheduler (backups, diagnostics, notification flush,
  Home Assistant sensor publishing, automatic repair),
* shut everything down cleanly on SIGTERM (Home Assistant stops add-ons that
  way, and the database must be closed cleanly).

Ingress: Home Assistant proxies the add-on under a dynamic path and strips the
``X-Ingress-Path`` handling itself, so all API calls use relative URLs. The
frontend reads the path from ``<base>``; nothing here needs to know the path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import api_ai, api_backup, api_documents, api_drawing, api_learning
from . import api_session, api_setup, api_system, websocket
from .context import APP_VERSION, AppContext, build_context
from .security import SecurityMiddleware, SessionStore
from .util import utcnow_iso

logger = logging.getLogger("elektrocoach.main")


def _ingress_base(request: Request) -> str:
    """Return the path prefix the browser sees, ending with a slash.

    Home Assistant's Ingress proxy strips the prefix before forwarding and adds
    ``X-Ingress-Path``. Using that value keeps the ``<base>`` tag correct, so
    relative asset, API and WebSocket URLs all resolve under Ingress. When the
    header is absent (local access, tests) the app is served from the root.
    """

    for header in ("x-ingress-path", "x-forwarded-prefix"):
        value = request.headers.get(header)
        if value:
            path = value.strip()
            if not path.startswith("/"):
                path = "/" + path
            return path if path.endswith("/") else path + "/"
    return "/"


def create_app(context: AppContext | None = None) -> FastAPI:
    context = context or build_context()
    app = FastAPI(
        title="ElektroCoach",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.context = context
    app.state.sessions = SessionStore(context.opts.path("secret_key"))

    app.add_middleware(SecurityMiddleware)

    for module in (api_session, api_learning, api_documents, api_drawing,
                   api_ai, api_system, api_setup, api_backup):
        app.include_router(module.router)
    app.include_router(websocket.router)

    _register_error_handlers(app)
    _mount_frontend(app, context)
    _register_lifecycle(app, context)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail, "path": request.url.path})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request,
                               exc: RequestValidationError) -> JSONResponse:
        problems = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            problems.append(f"{location}: {error.get('msg')}")
        return JSONResponse(
            status_code=422,
            content={
                "detail": ("Die Eingabe war nicht vollständig oder hatte ein falsches "
                           "Format. " + "; ".join(problems)),
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": ("Es ist ein unerwarteter Fehler aufgetreten. Öffnen Sie "
                                "den Bereich „Fehlerdiagnose“ für eine genaue "
                                "Anleitung.")},
        )


def _mount_frontend(app: FastAPI, context: AppContext) -> None:
    frontend_dir: Path = context.opts.path("frontend")
    assets_dir = frontend_dir / "assets"

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    index_file = frontend_dir / "index.html"

    @app.get("/", include_in_schema=False)
    async def index(request: Request) -> Response:
        if not index_file.is_file():
            return JSONResponse(
                status_code=503,
                content={"detail": (
                    "Die Website wurde nicht gefunden. Installieren Sie das "
                    "ElektroCoach-Add-on neu, damit die Dateien entpackt werden."
                )},
            )
        # Render the template with the actual request path so the <base> tag
        # matches the Ingress prefix. Home Assistant strips the prefix before
        # forwarding, so we reconstruct it from the forwarded headers.
        try:
            template = index_file.read_text(encoding="utf-8")
        except OSError:
            return JSONResponse(status_code=500, content={
                "detail": "Die Startseite konnte nicht gelesen werden."})
        base = _ingress_base(request)
        return Response(
            content=template.replace("{{ ingress_base }}", base),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        icon = frontend_dir / "assets" / "icon.png"
        if icon.is_file():
            return FileResponse(icon, media_type="image/png")
        return Response(status_code=204)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, Any]:
        """Liveness probe used by the container health check."""

        return {
            "status": "ok",
            "version": context.version,
            "schema_version": context.db.schema_version,
            "worker_alive": context.worker.is_alive(),
            "uptime_started_at": context.started_at,
            "time": utcnow_iso(),
        }


def _register_lifecycle(app: FastAPI, context: AppContext) -> None:
    @app.on_event("startup")
    async def on_startup() -> None:
        from .runtime import set_main_loop

        set_main_loop(asyncio.get_running_loop())
        app.state.scheduler = asyncio.create_task(_scheduler(context))
        logger.info("ElektroCoach %s ready", APP_VERSION)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler
        context.worker.stop(timeout=5.0)
        await context.ollama.aclose()
        await context.gemini.aclose()
        await context.ha.aclose()
        context.db.optimize()
        logger.info("ElektroCoach shut down cleanly")


async def _scheduler(context: AppContext) -> None:
    """Periodic maintenance.

    Every task runs on its own interval and is fully guarded: one failing task
    never stops the loop, and nothing runs more often than necessary.
    """

    started = time.monotonic()
    last_backup = started
    last_diagnostics = started
    last_ha_publish = started
    last_repair = started
    last_notification_flush = started
    last_log_purge = started

    monitoring_interval = max(15, context.opts.monitoring_interval_seconds)
    backup_interval = max(3600, context.opts.backup_interval_hours * 3600)

    # Give the system a moment to settle before the first checks.
    await asyncio.sleep(8)

    while True:
        now = time.monotonic()
        try:
            if now - last_ha_publish >= monitoring_interval:
                last_ha_publish = now
                await _guarded(context, "Home-Assistant-Sensoren",
                               _publish_sensors(context))

            if now - last_notification_flush >= 60:
                last_notification_flush = now
                await _guarded(context, "Benachrichtigungen",
                               _flush_notifications(context))

            if now - last_repair >= monitoring_interval * 3:
                last_repair = now
                await _guarded(context, "automatische Reparatur",
                               _automatic_repair(context))

            if now - last_diagnostics >= max(300, monitoring_interval * 10):
                last_diagnostics = now
                await _guarded(context, "Systemprüfung",
                               _run_diagnostics(context))

            if context.opts.backup_enabled and now - last_backup >= backup_interval:
                last_backup = now
                await _guarded(context, "automatisches Backup", _run_backup(context))

            if now - last_log_purge >= 86400:
                last_log_purge = now
                await _guarded(context, "Protokollbereinigung",
                               _purge_logs(context))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must never die
            logger.exception("scheduler iteration failed")

        await asyncio.sleep(min(30, monitoring_interval))


async def _guarded(context: AppContext, name: str, coroutine) -> None:
    try:
        await coroutine
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled task %s failed: %s", name, exc)
        context.repo.add_event(level="warning", category="scheduler",
                               message=f"Geplante Aufgabe „{name}“ ist fehlgeschlagen: {exc}")


async def _publish_sensors(context: AppContext) -> None:
    from .api_system import _sensor_values

    if not context.ha.configured:
        return
    values = _sensor_values(context)
    result = await context.ha.publish_sensors(values)
    if result["written"]:
        logger.debug("published %s sensors", len(result["written"]))


async def _flush_notifications(context: AppContext) -> None:
    if not context.ha.configured or not context.opts.ha_notifications_enabled:
        return
    await context.ha.flush_pending(context.repo, limit=5)


async def _automatic_repair(context: AppContext) -> None:
    if not context.opts.auto_repair_enabled:
        return
    results = context.repair.automatic_cycle()
    for result in results:
        logger.info("automatic repair: %s", result)


async def _run_diagnostics(context: AppContext) -> None:
    report = await context.diagnostics.run(auto_repair=False)
    logger.info("scheduled diagnostics: %s", report.get("overall"))


async def _run_backup(context: AppContext) -> None:
    # Never start a backup while storage is critical: it would fill the card.
    storage = context.health.check_storage()
    if storage["status"] == "critical":
        context.repo.add_event(
            level="critical", category="backup",
            message=("Das automatische Backup wurde ausgesetzt, weil der "
                     "Speicherplatz kritisch knapp ist."),
        )
        return
    record = context.backup.create(kind="auto")
    logger.info("automatic backup created: %s (%s)", record["filename"],
                record["size_human"])
    if context.opts.ha_notifications_enabled:
        context.repo.queue_notification(
            title="ElektroCoach Backup",
            message=(f"Automatisches Backup erstellt: {record['filename']} "
                     f"({record['size_human']})."),
            level="info",
        )


async def _purge_logs(context: AppContext) -> None:
    removed = context.repo.purge_old_logs(days=60)
    logger.info("purged old log rows: %s", removed)


def main() -> int:
    context = build_context()
    app = create_app(context)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=context.opts.port,
        log_level=context.opts.log_level if context.opts.log_level in {
            "trace", "debug", "info", "warning", "error", "critical"
        } else "info",
        access_log=False,
        server_header=False,
        timeout_keep_alive=30,
        limit_concurrency=64,
    )
    server = uvicorn.Server(config)

    def handle_signal(signum: int, _frame: Any) -> None:
        logger.info("received signal %s, shutting down", signum)
        server.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, handle_signal)

    try:
        server.run()
    except Exception:  # noqa: BLE001
        logger.exception("the server stopped unexpectedly")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
