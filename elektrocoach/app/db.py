"""SQLite-Datenbank mit FTS5-Volltextsuche, Migrationen und Backup-Hilfen."""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

_local = threading.local()
_write_lock = threading.RLock()
_initialised = False
# Wird bei jeder Wiederherstellung erhoeht. Jeder Thread verwirft dann seine
# Verbindung, weil sie auf die ersetzte Datei zeigt.
_generation = 0
_generation_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Verbindungen
# ---------------------------------------------------------------------------
def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-16000")


def invalidate_connections() -> None:
    """Alle Threads zwingen, ihre Verbindung neu aufzubauen.

    Nötig nach dem Ersetzen der Datenbankdatei (Wiederherstellung). Eine alte
    Verbindung zeigt dann auf eine geloeschte Datei und jeder Zugriff scheitert
    mit "disk I/O error". Die eigenen Verbindungen werden sofort geschlossen;
    andere Threads bauen ihre Verbindung beim naechsten Zugriff neu auf.
    """
    global _generation
    with _generation_lock:
        _generation += 1
    close_thread_connection()


def replace_database_file(source: os.PathLike[str] | str) -> None:
    """Ersetzt die Datenbankdatei durch eine Kopie aus dem Backup.

    Laeuft unter der Schreibsperre, damit kein anderer Thread gleichzeitig
    schreibt. Anschliessend werden alle Verbindungen ungueltig gemacht.
    """
    import shutil

    with _write_lock:
        shutil.copy2(source, settings.db_path)
        for suffix in ("-wal", "-shm"):
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
    invalidate_connections()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "generation", -1) != _generation:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn = None
        _local.conn = None
    if conn is None:
        path = settings.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        _configure(conn)
        _local.conn = conn
        _local.generation = _generation
    return conn


@contextlib.contextmanager
def write() -> Iterator[sqlite3.Connection]:
    """Serialisierter Schreibzugriff (SQLite erlaubt nur einen Schreiber)."""
    conn = get_conn()
    with _write_lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextlib.contextmanager
def read() -> Iterator[sqlite3.Connection]:
    yield get_conn()


def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return list(get_conn().execute(sql, params).fetchall())


def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, params).fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> None:
    with write() as conn:
        conn.execute(sql, params)


def executemany(sql: str, seq: Sequence[Sequence[Any]]) -> None:
    with write() as conn:
        conn.executemany(sql, seq)


def insert(sql: str, params: Sequence[Any] = ()) -> int:
    with write() as conn:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid or 0)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_id() -> str:
    return uuid.uuid4().hex


def json_dumps_safe(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    is_secret  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT,
    sha256      TEXT,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    page_count  INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'upload',
    collection  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    meta_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);

-- Nur Dokumente mit echtem Inhalt sind "Duplikat-faehig". Leere oder
-- fehlerhafte Dateien (0 Seiten) teilen sich haeufig denselben Hash und
-- duerfen sich deshalb nicht gegenseitig blockieren.
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256_content
    ON documents(sha256) WHERE page_count > 0 AND status != 'error';

CREATE TABLE IF NOT EXISTS pages (
    id               TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number      INTEGER NOT NULL,
    image_path       TEXT,
    text             TEXT NOT NULL DEFAULT '',
    ocr_confidence   REAL,
    needs_review     INTEGER NOT NULL DEFAULT 0,
    width            INTEGER,
    height           INTEGER,
    meta_json        TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    UNIQUE(document_id, page_number)
);
CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id);

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id        TEXT REFERENCES pages(id) ON DELETE CASCADE,
    page_number    INTEGER,
    ordinal        INTEGER NOT NULL DEFAULT 0,
    heading        TEXT,
    text           TEXT NOT NULL,
    tokens         INTEGER NOT NULL DEFAULT 0,
    needs_review   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(page_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    heading,
    content='chunks',
    content_rowid='rowid',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, heading)
    VALUES (new.rowid, new.text, COALESCE(new.heading, ''));
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading)
    VALUES ('delete', old.rowid, old.text, COALESCE(old.heading, ''));
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading)
    VALUES ('delete', old.rowid, old.text, COALESCE(old.heading, ''));
    INSERT INTO chunks_fts(rowid, text, heading)
    VALUES (new.rowid, new.text, COALESCE(new.heading, ''));
END;

CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    parent_id   TEXT REFERENCES topics(id) ON DELETE SET NULL,
    coverage    REAL NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'auto',
    ordering    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_chunks (
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    weight   REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (topic_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS questions (
    id             TEXT PRIMARY KEY,
    topic_id       TEXT REFERENCES topics(id) ON DELETE SET NULL,
    qtype          TEXT NOT NULL DEFAULT 'multiple_choice',
    difficulty     INTEGER NOT NULL DEFAULT 2,
    prompt         TEXT NOT NULL,
    options_json   TEXT NOT NULL DEFAULT '[]',
    answer         TEXT NOT NULL DEFAULT '',
    solution_steps TEXT NOT NULL DEFAULT '',
    explanation    TEXT NOT NULL DEFAULT '',
    points         REAL NOT NULL DEFAULT 1,
    source_chunk_ids TEXT NOT NULL DEFAULT '[]',
    ai_source      TEXT NOT NULL DEFAULT 'manual',
    verified       INTEGER NOT NULL DEFAULT 0,
    needs_review   INTEGER NOT NULL DEFAULT 0,
    tags           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic_id);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(qtype);

CREATE TABLE IF NOT EXISTS attempts (
    id           TEXT PRIMARY KEY,
    question_id  TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    session_id   TEXT,
    exam_id      TEXT,
    user_answer  TEXT NOT NULL DEFAULT '',
    score        REAL NOT NULL DEFAULT 0,
    max_points   REAL NOT NULL DEFAULT 0,
    feedback     TEXT NOT NULL DEFAULT '',
    needs_review INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_attempts_created ON attempts(created_at);

CREATE TABLE IF NOT EXISTS srs (
    question_id      TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    ease             REAL NOT NULL DEFAULT 2.5,
    interval_days    REAL NOT NULL DEFAULT 0,
    repetitions      INTEGER NOT NULL DEFAULT 0,
    lapses           INTEGER NOT NULL DEFAULT 0,
    state            TEXT NOT NULL DEFAULT 'new',
    due_at           TEXT,
    last_reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_srs_due ON srs(due_at);

CREATE TABLE IF NOT EXISTS study_sessions (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL DEFAULT 'practice',
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    planned_minutes INTEGER NOT NULL DEFAULT 0,
    actual_seconds  INTEGER NOT NULL DEFAULT 0,
    score           REAL NOT NULL DEFAULT 0,
    max_score       REAL NOT NULL DEFAULT 0,
    meta_json       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON study_sessions(started_at);

CREATE TABLE IF NOT EXISTS exams (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 90,
    total_points     REAL NOT NULL DEFAULT 100,
    status           TEXT NOT NULL DEFAULT 'created',
    config_json      TEXT NOT NULL DEFAULT '{}',
    score            REAL,
    passed           INTEGER,
    pass_probability REAL,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);

CREATE TABLE IF NOT EXISTS exam_questions (
    id          TEXT PRIMARY KEY,
    exam_id     TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL DEFAULT 0,
    points      REAL NOT NULL DEFAULT 1,
    answer      TEXT,
    score       REAL,
    feedback    TEXT
);
CREATE INDEX IF NOT EXISTS idx_exam_questions_exam ON exam_questions(exam_id);

CREATE TABLE IF NOT EXISTS learning_goals (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    topic_id    TEXT REFERENCES topics(id) ON DELETE SET NULL,
    target      TEXT NOT NULL DEFAULT '',
    due_date    TEXT,
    progress    REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schematic_projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    grid        INTEGER NOT NULL DEFAULT 20,
    data_json   TEXT NOT NULL DEFAULT '{}',
    thumbnail   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'queued',
    total_files      INTEGER NOT NULL DEFAULT 0,
    processed_files  INTEGER NOT NULL DEFAULT 0,
    failed_files     INTEGER NOT NULL DEFAULT 0,
    current_item     TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    stats_json       TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refine_jobs (
    id               TEXT PRIMARY KEY,
    document_id      TEXT,
    scope            TEXT NOT NULL DEFAULT 'review',
    status           TEXT NOT NULL DEFAULT 'queued',
    total_pages      INTEGER NOT NULL DEFAULT 0,
    processed_pages  INTEGER NOT NULL DEFAULT 0,
    current_page     INTEGER NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refine_jobs_created ON refine_jobs(created_at);

CREATE TABLE IF NOT EXISTS ai_usage (
    id         TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL DEFAULT '',
    task       TEXT NOT NULL DEFAULT '',
    ok         INTEGER NOT NULL DEFAULT 1,
    error      TEXT,
    day        TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_day ON ai_usage(day, provider);

CREATE TABLE IF NOT EXISTS notifications_log (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'info',
    title      TEXT NOT NULL DEFAULT '',
    message    TEXT NOT NULL DEFAULT '',
    delivered  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);
"""


def init_db() -> None:
    global _initialised
    with _write_lock:
        if _initialised:
            return
        conn = get_conn()
        _migrate_documents_sha256(conn)
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        _initialised = True
        log.info("Datenbank bereit: %s", settings.db_path)


def _migrate_documents_sha256(conn: sqlite3.Connection) -> None:
    """Entfernt die alte UNIQUE-Bedingung auf documents.sha256.

    Schema-Version 1 legte sha256 als UNIQUE-Spalte an. Dadurch konnte eine
    zweite leere oder beschaedigte Datei nicht gespeichert werden (Absturz mit
    IntegrityError). Ab Version 2 gilt die Eindeutigkeit nur noch fuer
    Dokumente mit Inhalt (Teilindex).
    """
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        if table is None:
            return
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        if ddl is None or "sha256" not in (ddl["sql"] or ""):
            return
        # Alte UNIQUE-Bedingung nur an der Spaltendefinition erkennen. Der
        # Teilindex (Version 2) heisst anders und wird hier nicht beruehrt.
        if not _has_column_unique(ddl["sql"], "sha256"):
            return
        log.info("Migriere documents-Tabelle: sha256 ohne globale UNIQUE-Bedingung.")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            ALTER TABLE documents RENAME TO documents_old;
            CREATE TABLE documents (
                id          TEXT PRIMARY KEY,
                filename    TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime        TEXT,
                sha256      TEXT,
                size_bytes  INTEGER NOT NULL DEFAULT 0,
                page_count  INTEGER NOT NULL DEFAULT 0,
                source      TEXT NOT NULL DEFAULT 'upload',
                collection  TEXT,
                status      TEXT NOT NULL DEFAULT 'pending',
                error       TEXT,
                meta_json   TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            INSERT INTO documents SELECT * FROM documents_old;
            DROP TABLE documents_old;
            """
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
    except sqlite3.Error as exc:  # pragma: no cover - nur bei defekten Altbestaenden
        log.warning("Migration von documents.sha256 uebersprungen: %s", exc)


def _has_column_unique(ddl: str, column: str) -> bool:
    """Prueft, ob eine Spalte in der Tabellendefinition UNIQUE ist."""
    import re

    pattern = re.compile(
        r"\b" + re.escape(column) + r"\b\s+[^,)]*?\bUNIQUE\b", re.IGNORECASE
    )
    if pattern.search(ddl):
        return True
    # Tabellenweite Bedingung: UNIQUE (..., sha256, ...)
    return bool(
        re.search(r"\bUNIQUE\s*\([^)]*\b" + re.escape(column) + r"\b[^)]*\)", ddl, re.IGNORECASE)
    )


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str | None, is_secret: bool = False) -> None:
    with write() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, is_secret, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "is_secret=excluded.is_secret, updated_at=excluded.updated_at",
            (key, value, 1 if is_secret else 0, now()),
        )


def all_settings() -> dict[str, str]:
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}


# ---------------------------------------------------------------------------
# Volltextsuche
# ---------------------------------------------------------------------------
def fts_query(text: str) -> str:
    """Baut eine sichere FTS5-MATCH-Abfrage aus freiem Text."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in (text or "")).split() if len(t) > 1]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"*' for t in tokens[:12])


def search_chunks(text: str, limit: int = 20, document_id: str | None = None) -> list[sqlite3.Row]:
    match = fts_query(text)
    if not match:
        return []
    sql = (
        "SELECT c.*, d.filename, bm25(chunks_fts) AS rank "
        "FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE chunks_fts MATCH ?"
    )
    params: list[Any] = [match]
    if document_id:
        sql += " AND c.document_id = ?"
        params.append(document_id)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        return query(sql, params)
    except sqlite3.OperationalError as exc:
        log.warning("FTS-Abfrage fehlgeschlagen: %s", exc)
        return []


def search_questions(text: str, limit: int = 20) -> list[sqlite3.Row]:
    like = f"%{text}%"
    return query(
        "SELECT * FROM questions WHERE prompt LIKE ? OR tags LIKE ? "
        "ORDER BY updated_at DESC LIMIT ?",
        (like, like, limit),
    )


# ---------------------------------------------------------------------------
# Statistik / Wartung
# ---------------------------------------------------------------------------
def db_stats() -> dict[str, Any]:
    size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    wal = settings.db_path.with_suffix(".db-wal")
    wal_size = wal.stat().st_size if wal.exists() else 0
    counts = {}
    for table in ("documents", "pages", "chunks", "topics", "questions",
                  "attempts", "exams", "schematic_projects"):
        row = query_one(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 - feste Tabellenliste
        counts[table] = row["n"] if row else 0
    return {"size_bytes": size, "wal_bytes": wal_size, "counts": counts}


def integrity_check() -> str:
    row = query_one("PRAGMA integrity_check")
    return row[0] if row else "unknown"


def vacuum() -> None:
    with write() as conn:
        conn.execute("VACUUM")


def checkpoint() -> None:
    with write() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def checkpoint_quiet() -> None:
    """Checkpoint beim Beenden: Fehler duerfen das Herunterfahren nicht stoeren.

    Nach einer Wiederherstellung zeigt die vorhandene Verbindung auf eine
    ersetzte Datei. Ein Checkpoint schlaegt dann fehl ("disk I/O error"). Beim
    Herunterfahren ist das unerheblich, deshalb wird der Fehler nur protokolliert.
    """
    try:
        checkpoint()
    except Exception as exc:  # noqa: BLE001
        log.warning("Abschluss-Checkpoint der Datenbank uebersprungen: %s", exc)


def backup_to(target: os.PathLike[str] | str) -> str:
    """Konsistentes Online-Backup via SQLite-Backup-API."""
    target = str(target)
    dest = sqlite3.connect(target)
    try:
        with _write_lock:
            get_conn().backup(dest)
    finally:
        dest.close()
    return target


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
