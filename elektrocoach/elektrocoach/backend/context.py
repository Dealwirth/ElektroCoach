"""Application context: owns every long-lived service.

One instance is created at startup and stored on ``app.state``. Routers receive
it through a FastAPI dependency. This keeps the wiring in one place and makes the
services trivially replaceable in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Options, ensure_directories, load_options
from .logging_setup import configure_logging
from .runtime import set_main_loop
from .util import utcnow_iso

from ..ai.dispatcher import AIDispatcher
from ..ai.gemini_client import GeminiClient
from ..ai.ollama_client import OllamaClient
from ..backup.service import BackupService
from ..database.db import Database
from ..database.repository import Repository
from ..documents.importer import DocumentImporter
from ..documents.ocr import OcrEngine
from ..drawing.symbols import GRID_SIZE
from ..integrations.homeassistant import HomeAssistantClient
from ..jobs.handlers import JobHandlers
from ..jobs.worker import JobWorker
from ..learning.exams import ExamService
from ..learning.generator import QuestionGenerator
from ..learning.service import LearningService
from ..monitoring.diagnostics import DiagnosticsService
from ..monitoring.health import HealthService
from ..monitoring.repair import SelfRepair

APP_VERSION = "0.1.0"

logger = logging.getLogger("elektrocoach.context")


@dataclass
class AppContext:
    opts: Options
    db: Database
    repo: Repository
    ollama: OllamaClient
    gemini: GeminiClient
    dispatcher: AIDispatcher
    ha: HomeAssistantClient
    health: HealthService
    repair: SelfRepair
    diagnostics: DiagnosticsService
    learning: LearningService
    exams: ExamService
    generator: QuestionGenerator
    importer: DocumentImporter
    backup: BackupService
    worker: JobWorker
    handlers: JobHandlers
    version: str = APP_VERSION
    started_at: str = field(default_factory=utcnow_iso)

    @property
    def grid_size(self) -> int:
        return GRID_SIZE

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "started_at": self.started_at,
            "data_dir": str(self.opts.path("data")),
            "database": str(self.opts.path("database")),
            "schema_version": self.db.schema_version,
            "fts5": self.db.fts5_available,
            "worker": self.worker.status,
            "ollama_model": self.opts.ollama_model,
            "gemini_model": self.opts.gemini_model,
            "gemini_enabled": self.opts.gemini_configured,
            "ha_configured": self.ha.configured,
        }


def build_context(*, start_worker: bool = True) -> AppContext:
    """Create and wire every service. Used by the server and by the tests."""

    opts = load_options()
    ensure_directories(opts)
    configure_logging(opts.log_level, opts.path("logs"))
    logger.info("starting ElektroCoach %s (data dir %s)", APP_VERSION, opts.data_dir)

    db = Database(opts.path("database"))
    applied = db.migrate()
    if applied:
        logger.info("database migrations applied: %s", applied)
    repo = Repository(db)
    _seed_defaults(repo, opts)

    ollama = OllamaClient(
        opts.ollama_url, opts.ollama_model,
        enabled=opts.ollama_enabled,
        unload_after_seconds=opts.ollama_unload_after_seconds,
    )
    gemini = GeminiClient(
        opts.gemini_api_key, opts.gemini_model,
        enabled=opts.gemini_enabled,
        daily_request_budget=opts.gemini_daily_request_budget,
    )
    dispatcher = AIDispatcher(repo, ollama, gemini,
                              gemini_daily_budget=opts.gemini_daily_request_budget)
    ha = HomeAssistantClient(
        opts.supervisor_token,
        notifications_enabled=opts.ha_notifications_enabled,
        notify_service=opts.notify_service,
    )

    ocr = OcrEngine(opts.ocr_language)
    importer = DocumentImporter(repo, opts, dispatcher=dispatcher, ocr=ocr)
    generator = QuestionGenerator(repo, dispatcher=dispatcher)
    learning = LearningService(repo, dispatcher=dispatcher)
    exams = ExamService(repo, dispatcher=dispatcher)
    backup = BackupService(repo, opts, app_version=APP_VERSION)

    worker = JobWorker(repo, enabled=True)
    health = HealthService(repo, opts, ollama=ollama, gemini=gemini,
                           dispatcher=dispatcher, app_version=APP_VERSION)
    repair = SelfRepair(repo, opts, dispatcher=dispatcher, health=health,
                        worker=worker, enabled=opts.auto_repair_enabled)
    diagnostics = DiagnosticsService(repo, opts, health, repair,
                                     app_version=APP_VERSION)
    handlers = JobHandlers(repo, opts, importer=importer, generator=generator,
                           backup=backup, diagnostics=diagnostics,
                           dispatcher=dispatcher, learning=learning)
    handlers.register_all(worker)

    # Settings saved in the UI override the add-on options, so they must be
    # re-applied on every start.
    _apply_runtime_settings(repo, ollama, gemini, ha, repair)

    context = AppContext(
        opts=opts, db=db, repo=repo, ollama=ollama, gemini=gemini,
        dispatcher=dispatcher, ha=ha, health=health, repair=repair,
        diagnostics=diagnostics, learning=learning, exams=exams,
        generator=generator, importer=importer, backup=backup,
        worker=worker, handlers=handlers,
    )
    if start_worker:
        worker.start()
    return context


def _seed_defaults(repo: Repository, opts: Options) -> None:
    """Write the settings the UI edits, once, with their defaults."""

    defaults = {
        "learning.daily_goal_minutes": 30,
        "learning.exam_date": "",
        "ui.theme": "light",
        "ui.grid_size": GRID_SIZE,
        "notifications.daily_reminder": True,
        "notifications.reminder_time": "18:00",
        "ai.prefer": "auto",
        "documents.auto_generate_questions": True,
        "backup.enabled": opts.backup_enabled,
        "setup.completed": False,
        "runtime.ollama_model": opts.ollama_model,
        "runtime.gemini_model": opts.gemini_model,
        "runtime.gemini_enabled": opts.gemini_enabled,
        "runtime.notify_service": opts.notify_service,
        "runtime.notifications_enabled": opts.ha_notifications_enabled,
        "runtime.auto_repair_enabled": opts.auto_repair_enabled,
    }
    for key, value in defaults.items():
        if repo.get_setting(key, None) is None:
            repo.set_setting(key, value)


def _apply_runtime_settings(repo: Repository, ollama: OllamaClient,
                            gemini: GeminiClient, ha: HomeAssistantClient,
                            repair: SelfRepair) -> None:
    """Re-apply settings changed in the UI so they survive a restart.

    Without this a model name or API key saved through the settings page would be
    silently forgotten after the next restart.
    """

    model = repo.get_setting("runtime.ollama_model")
    if isinstance(model, str) and model.strip():
        ollama.model = model.strip()
    model = repo.get_setting("runtime.gemini_model")
    if isinstance(model, str) and model.strip():
        gemini.model = model.strip()
    api_key = repo.get_setting("runtime.gemini_api_key")
    if isinstance(api_key, str) and api_key.strip():
        gemini.api_key = api_key.strip()
    gemini_enabled = repo.get_setting("runtime.gemini_enabled")
    if gemini_enabled is not None:
        gemini.enabled = bool(gemini_enabled)
    notify_service = repo.get_setting("runtime.notify_service")
    if isinstance(notify_service, str) and notify_service.strip():
        ha.notify_service = notify_service.strip()
    notifications_enabled = repo.get_setting("runtime.notifications_enabled")
    if notifications_enabled is not None:
        ha.notifications_enabled = bool(notifications_enabled)
    auto_repair_enabled = repo.get_setting("runtime.auto_repair_enabled")
    if auto_repair_enabled is not None:
        repair.enabled = bool(auto_repair_enabled)


def attach_main_loop(loop) -> None:
    set_main_loop(loop)
