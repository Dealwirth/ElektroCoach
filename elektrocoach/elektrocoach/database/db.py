"""SQLite access layer.

Design decisions:

* WAL mode: readers never block the single writer, which keeps the web UI
  responsive while a background job imports documents.
* One connection per thread (``threading.local``). FastAPI runs synchronous
  endpoints in a worker thread pool, so this gives us safe, cheap reuse.
* A single write lock serialises writes. SQLite has exactly one writer anyway,
  and an explicit lock turns "database is locked" errors into a short wait.
* All values are passed as SQL parameters. No query is ever built by string
  interpolation of user input.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .migrations import MIGRATIONS

logger = logging.getLogger("elektrocoach.database")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._fts5_available = False
        # Bumped whenever the database file is replaced (a restore). Each
        # thread compares this against the generation it opened its connection
        # with and reopens on mismatch.
        self._generation = 0

    # -- connection management ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=30.0,
            isolation_level=None,  # explicit transactions
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None or getattr(self._local, "generation", -1) != self._generation:
            if conn is not None:
                # This thread's connection points at a replaced file: close it
                # (only this thread may touch it) and open the new file.
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
                self._local.conn = None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            self._local.conn = conn
            self._local.generation = self._generation
        return conn

    def close_thread_connection(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None

    def invalidate_connections(self) -> None:
        """Mark every thread's connection as stale after the file is replaced.

        A restore swaps ``elektrocoach.sqlite3`` on disk. Any other thread (the
        background worker, FastAPI's thread pool) would otherwise keep its
        connection to the now-unlinked file and silently read and write the
        *old* database — the worker stopped processing queued jobs until the
        add-on was restarted. Closing from another thread is unsafe, so each
        thread closes its own connection on its next access instead.
        """

        with self._write_lock:
            self._generation += 1
        # The calling thread can close its own connection immediately.
        self.close_thread_connection()

    # -- migrations -----------------------------------------------------------

    def migrate(self) -> list[int]:
        """Apply pending migrations and return the versions that were applied."""

        applied: list[int] = []
        conn = self.conn
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, name, statements in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version in done:
                continue
            logger.info("applying migration %s (%s)", version, name)
            with self.transaction():
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    "VALUES (?, ?, datetime('now'))",
                    (version, name),
                )
            applied.append(version)
        self._fts5_available = self._check_fts5()
        return applied

    def _check_fts5(self) -> bool:
        try:
            self.conn.execute("SELECT count(*) FROM knowledge_fts").fetchone()
            return True
        except sqlite3.Error:
            logger.warning("FTS5 is not available in this SQLite build")
            return False

    @property
    def fts5_available(self) -> bool:
        return self._fts5_available

    @property
    def schema_version(self) -> int:
        try:
            row = self.conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            return int(row["v"] or 0)
        except sqlite3.Error:
            return 0

    # -- query helpers --------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._write_lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._write_lock:
            return self.conn.executemany(sql, seq)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._write_lock:
            cursor = self.conn.execute(sql, params)
            return int(cursor.lastrowid or 0)

    # -- maintenance ----------------------------------------------------------

    def integrity_check(self) -> tuple[bool, str]:
        try:
            row = self.conn.execute("PRAGMA integrity_check").fetchone()
            result = row[0] if row else "no result"
            return (str(result).lower() == "ok", str(result))
        except sqlite3.Error as exc:
            return False, str(exc)

    def quick_check(self) -> tuple[bool, str]:
        try:
            row = self.conn.execute("PRAGMA quick_check").fetchone()
            result = row[0] if row else "no result"
            return (str(result).lower() == "ok", str(result))
        except sqlite3.Error as exc:
            return False, str(exc)

    def optimize(self) -> None:
        with self._write_lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("PRAGMA optimize")

    def rebuild_fts(self) -> None:
        if not self._fts5_available:
            return
        with self._write_lock:
            self.conn.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")

    def backup_to(self, target: Path) -> None:
        """Consistent copy of the database using SQLite's online backup API."""

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(target))
        try:
            with self._write_lock:
                self.conn.backup(destination)
        finally:
            destination.close()

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def table_counts(self) -> dict[str, int]:
        tables = [
            "documents",
            "document_pages",
            "knowledge_items",
            "questions",
            "attempts",
            "exam_sessions",
            "srs_cards",
            "drawings",
            "jobs",
            "system_events",
        ]
        counts: dict[str, int] = {}
        for table in tables:
            try:
                counts[table] = int(
                    self.scalar(f"SELECT COUNT(*) FROM {table}", default=0)
                )
            except sqlite3.Error:
                counts[table] = -1
        return counts
