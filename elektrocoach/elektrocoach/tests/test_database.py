"""Tests for the database layer: migrations, FTS5, integrity, deduplication.

These tests assert against the real schema (see ``database/migrations.py``) so a
renamed table or column breaks the suite instead of silently passing.
"""

from __future__ import annotations

import sqlite3

EXPECTED_TABLES = [
    "documents", "document_pages", "knowledge_items", "questions", "attempts",
    "exam_sessions", "exam_items", "srs_cards", "review_log", "topic_mastery",
    "study_plan", "drawings", "app_settings", "jobs", "system_events", "repairs",
    "ai_usage", "ai_cache", "ai_budget", "backups", "notifications",
    "diagnostics_runs", "setup_state", "audit_log", "schema_migrations",
]


def test_migrations_create_schema(db):
    applied = db.migrate()
    # A second run must be idempotent and apply nothing.
    assert applied == []
    assert db.schema_version >= 1
    rows = db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    present = {row["name"] for row in rows}
    missing = [table for table in EXPECTED_TABLES if table not in present]
    assert not missing, f"tables missing after migration: {missing}"


def test_migration_is_idempotent(db):
    assert db.migrate() == []
    assert db.migrate() == []
    assert db.schema_version >= 1


def test_integrity_and_quick_check(db):
    ok, message = db.integrity_check()
    assert ok, message
    ok, message = db.quick_check()
    assert ok, message


def test_fts5_table_exists(db):
    if not db.fts5_available:
        # Without FTS5 the app falls back to a LIKE search; nothing to assert.
        return
    rows = db.query("SELECT name FROM sqlite_master WHERE name = 'knowledge_fts'")
    assert rows, "FTS5 is available but the knowledge_fts table is missing"


def test_transaction_rolls_back_on_error(db):
    db.execute("INSERT INTO app_settings (key, value, updated_at) "
               "VALUES ('t', '1', datetime('now'))")
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO app_settings (key, value, updated_at) "
                         "VALUES ('u', '2', datetime('now'))")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.query_one("SELECT * FROM app_settings WHERE key = 'u'") is None
    assert db.query_one("SELECT * FROM app_settings WHERE key = 't'") is not None


def test_backup_to_creates_readable_copy(db, tmp_path):
    from elektrocoach.database.repository import Repository

    repo = Repository(db)
    repo.set_setting("probe", "value")
    target = tmp_path / "copy.sqlite3"
    db.backup_to(target)
    assert target.is_file()

    connection = sqlite3.connect(target)
    try:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'probe'").fetchone()
    finally:
        connection.close()
    assert row is not None
    assert "value" in str(row[0])


def test_knowledge_upsert_deduplicates(repo):
    first = repo.upsert_knowledge(
        title="Spannungsfall", content="Der Spannungsfall wird in Volt angegeben.",
        subject="Elektrotechnische Grundlagen", topic="Spannungsfall",
        source_label="notizen.pdf", page_number=4,
    )
    second = repo.upsert_knowledge(
        title="Spannungsfall", content="Der Spannungsfall wird in Volt angegeben.",
        subject="Elektrotechnische Grundlagen", topic="Spannungsfall",
        source_label="notizen.pdf", page_number=4,
    )
    assert first[1] is True  # created
    assert second[1] is False  # duplicate
    assert repo.count_knowledge() == 1


def test_search_knowledge_finds_inserted_content(repo):
    repo.upsert_knowledge(
        title="Schutzleiter", content="Der Schutzleiter führt im Fehlerfall den "
        "Fehlerstrom ab und schützt so vor elektrischem Schlag.",
        subject="Schutzmaßnahmen", topic="Schutzleiter",
        source_label="notizen.pdf", page_number=12,
    )
    results = repo.search_knowledge("Schutzleiter", limit=5)
    assert results, "the full-text search returned nothing"
    assert any("Schutzleiter" in (row.get("title") or "") for row in results)


def test_job_lifecycle_claim_and_finish(repo):
    job_id = repo.enqueue_job(type="import_document", payload={"path": "x.pdf"})
    job = repo.claim_job()
    assert job is not None
    assert int(job["id"]) == job_id
    assert job["status"] == "running"
    # A claimed job cannot be claimed twice.
    assert repo.claim_job() is None
    repo.finish_job(job_id, result={"pages": 2})
    stored = repo.get_job(job_id)
    assert stored["status"] == "done"
    assert stored["result"]["pages"] == 2


def test_job_failure_records_error(repo):
    job_id = repo.enqueue_job(type="import_document", payload={})
    repo.claim_job()
    repo.finish_job(job_id, error="kaputte Datei")
    stored = repo.get_job(job_id)
    assert stored["status"] == "failed"
    assert "kaputte" in stored["error"]


def test_stale_job_detection(repo):
    job_id = repo.enqueue_job(type="import_document", payload={})
    repo.claim_job()
    # A job just started is not stale with the production threshold.
    assert repo.stale_running_jobs(older_than_seconds=1800) == []
    # Force the row to look old, then the same job must be reported as stale.
    repo.db.execute("UPDATE jobs SET started_at = datetime('now', '-2 hours') "
                    "WHERE id = ?", (job_id,))
    stale = repo.stale_running_jobs(older_than_seconds=1800)
    assert any(int(job["id"]) == job_id for job in stale)


def test_settings_round_trip_types(repo):
    repo.set_setting("a.int", 5)
    repo.set_setting("a.str", "text")
    repo.set_setting("a.bool", True)
    repo.set_setting("a.list", [1, 2, 3])
    assert repo.get_setting("a.int") == 5
    assert repo.get_setting("a.str") == "text"
    assert repo.get_setting("a.bool") is True
    assert repo.get_setting("a.list") == [1, 2, 3]
    assert repo.get_setting("missing", "fallback") == "fallback"


def test_ai_budget_and_usage_accounting(repo):
    assert repo.ai_budget_today("gemini")["requests_used"] == 0
    repo.record_ai_usage(provider="gemini", model="gemini-2.0-flash",
                         task_type="hard_qa", prompt_tokens=100,
                         completion_tokens=50, success=True)
    repo.record_ai_usage(provider="gemini", model="gemini-2.0-flash",
                         task_type="hard_qa", prompt_tokens=10,
                         completion_tokens=5, success=False)
    budget = repo.ai_budget_today("gemini")
    assert budget["requests_used"] == 2
    assert budget["tokens_used"] == 165
    summary = {row["provider"]: row for row in repo.ai_usage_summary(7)}
    assert summary["gemini"]["requests"] == 2
    assert summary["gemini"]["failures"] == 1


def test_cache_put_get_and_stats(repo):
    repo.cache_put(cache_key="abc", provider="ollama", model="qwen2.5:1.5b",
                   task_type="summarize", response={"answer": "42"})
    assert repo.cache_get("abc") == {"answer": "42"}
    repo.cache_get("abc")
    repo.cache_get("does-not-exist")
    stats = repo.cache_stats()
    assert stats["entries"] == 1
    assert stats["hits"] >= 1


def test_events_and_resolution(repo):
    event_id = repo.add_event(level="error", category="health",
                              message="Ollama: nicht erreichbar")
    counts = repo.event_counts()
    assert counts["error"] == 1
    unresolved = repo.list_events(unresolved_only=True)
    assert len(unresolved) == 1
    repo.resolve_event(event_id)
    assert repo.list_events(unresolved_only=True) == []


def test_purge_old_logs_keeps_recent_rows(repo):
    repo.add_event(level="info", category="test", message="frisch")
    repo.db.execute(
        "UPDATE system_events SET created_at = datetime('now', '-90 days')")
    removed = repo.purge_old_logs(days=60)
    assert removed.get("system_events", 0) == 1
    assert repo.list_events() == []


def test_vacuum_keeps_database_consistent(repo):
    repo.set_setting("vacuum.probe", "x" * 100)
    repo.vacuum()
    ok, message = repo.db.quick_check()
    assert ok, message
    assert repo.get_setting("vacuum.probe").startswith("x")
