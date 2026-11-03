"""ElektroCoach - FastAPI-Anwendung.

Startet die Datenbank, den Import-Worker und die Home-Assistant-Anbindung und
stellt die Weboberflaeche sowie die API bereit. Die Oberflaeche arbeitet mit
relativen Pfaden, damit sie hinter dem Home-Assistant-Ingress ohne Anpassung
funktioniert.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routers import ai_api, exams, imports, learning_api, schematics, system
from .services import backup, ha_integration, learning
from .workers import import_worker

LOG_LEVELS = {
    "debug": logging.DEBUG, "info": logging.INFO,
    "warning": logging.WARNING, "error": logging.ERROR,
}


def configure_logging() -> None:
    level = LOG_LEVELS.get(str(settings.get("log_level", "info")).lower(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


log = logging.getLogger("elektrocoach")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for folder in ("documents", "pages", "backups", "schematics", "uploads"):
        (settings.data_dir / folder).mkdir(parents=True, exist_ok=True)

    db.init_db()
    _load_stored_settings()
    learning.ensure_default_topics()
    import_worker.start_worker()
    import_worker.resume_interrupted_jobs()
    ha_integration.start_scheduler()
    backup.maybe_auto_backup()
    log.info("ElektroCoach bereit. Datenverzeichnis: %s", settings.data_dir)
    try:
        yield
    finally:
        ha_integration.stop_scheduler()
        try:
            ha_integration.remove_discovery()
        except Exception:  # noqa: BLE001
            pass
        db.checkpoint()
        log.info("ElektroCoach beendet.")


def _load_stored_settings() -> None:
    """Laedt in der Datenbank gespeicherte Einstellungen (inkl. Geheimnisse)."""
    from .config import SECRET_KEYS
    from .security import decrypt

    stored = db.all_settings()
    for key, value in stored.items():
        if value is None:
            continue
        if key in SECRET_KEYS:
            settings.set_runtime(key, decrypt(settings.data_dir, value))
        else:
            settings.set_runtime(key, value)


app = FastAPI(
    title="ElektroCoach",
    version="1.0.0",
    description=(
        "KI-Lernplattform fuer die Abschlusspruefung Elektroniker fuer Energie- "
        "und Gebaeudetechnik mit OCR-Import, Lernsystem, Pruefungssimulation "
        "und Schaltplan-Editor."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

# Ingress kommt immer vom Supervisor. Fuer die lokale Entwicklung im Docker-
# Container sind zusaetzliche Quellen erlaubt, aber ohne Credentials-Transfer.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"

for module in (system, imports, learning_api, exams, schematics, ai_api):
    app.include_router(module.router, prefix=API_PREFIX)


@app.middleware("http")
async def ingress_headers(request: Request, call_next: Any) -> Response:
    """Reicht den Ingress-Pfad an die Antwort weiter und ergaenzt Sicherheitsheader."""
    response = await call_next(request)
    ingress_path = request.headers.get("X-Ingress-Path")
    if ingress_path:
        response.headers["X-Ingress-Path"] = ingress_path
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Interner Fehler",
            "hint": "Bitte das Add-on-Protokoll pruefen.",
        },
    )


@app.get("/api/ping")
async def ping() -> dict[str, Any]:
    return {"pong": True, "time": db.now(), "uptime": int(time.time())}


# ---------------------------------------------------------------------------
# Weboberflaeche
# ---------------------------------------------------------------------------
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


def _index_file() -> Path | None:
    index = STATIC_DIR / "index.html"
    return index if index.exists() else None


@app.get("/", include_in_schema=False)
async def index() -> Response:
    index_file = _index_file()
    if index_file:
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Weboberflaeche nicht gebaut",
            "hint": (
                "Das Frontend wurde nicht in das Image kopiert. Bitte das Image "
                "vollstaendig bauen (npm run build im Ordner frontend)."
            ),
        },
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> Response:
    """Liefert die SPA aus. Unbekannte Pfade ohne API-Praefix werden auf die
    Startseite geleitet, damit die Oberflaeche nach einem Neuladen funktioniert."""
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Nicht gefunden"})
    candidate = (STATIC_DIR / full_path).resolve()
    if str(candidate).startswith(str(STATIC_DIR.resolve())) and candidate.is_file():
        return FileResponse(candidate)
    index_file = _index_file()
    if index_file:
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Weboberflaeche nicht gebaut",
            "hint": (
                "Das Frontend wurde nicht in das Image kopiert. Bitte das Image "
                "vollstaendig bauen (npm run build im Ordner frontend)."
            ),
        },
    )
