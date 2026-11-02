"""Shared pytest fixtures.

Every test runs against a throw-away data directory and an in-memory-like SQLite
file, so tests never touch real user data and can run in parallel. The AI
services are replaced by deterministic stubs; no network access is needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the package importable when pytest is started from the repository root.
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    """A clean data directory plus the environment overrides for it."""

    target = tmp_path / "data"
    target.mkdir(parents=True, exist_ok=True)
    share = tmp_path / "share"
    share.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ELEKTROCOACH_DATA_DIR", str(target))
    monkeypatch.setenv("ELEKTROCOACH_SHARE_DIR", str(share))
    monkeypatch.setenv("ELEKTROCOACH_ROOT", str(PACKAGE_ROOT.parent))
    # Prevent a developer's real /data/options.json from leaking into the tests.
    monkeypatch.setenv("ELEKTROCOACH_OPTIONS_FILE", str(tmp_path / "no-options.json"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    return target


@pytest.fixture()
def options(data_dir: Path):
    from elektrocoach.backend.config import ensure_directories, load_options

    opts = load_options()
    ensure_directories(opts)
    return opts


@pytest.fixture()
def db(options):
    from elektrocoach.database.db import Database

    database = Database(options.path("database"))
    database.migrate()
    yield database
    database.close_thread_connection()


@pytest.fixture()
def repo(db):
    from elektrocoach.database.repository import Repository

    return Repository(db)


@pytest.fixture()
def context(options, monkeypatch):
    """A fully wired application context with the worker disabled."""

    from elektrocoach.backend import context as context_module

    monkeypatch.setattr(context_module, "load_options", lambda: options)
    ctx = context_module.build_context(start_worker=False)
    yield ctx
    ctx.worker.stop(timeout=1.0)


@pytest.fixture()
def client(context):
    from fastapi.testclient import TestClient

    from elektrocoach.backend.main import create_app

    app = create_app(context)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def csrf_client(client):
    """A client that already holds a session, with its CSRF token exposed."""

    response = client.get("/api/session")
    assert response.status_code == 200
    token = response.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": token})
    return client
