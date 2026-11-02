"""Typed data access.

Every SQL statement used by the application lives here. Keeping the queries in
one module makes them easy to audit for parameterisation and easy to change
without touching business logic.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Iterable, Sequence

from ..backend.util import sha256_bytes, utcnow_iso
from .db import Database

logger = logging.getLogger("elektrocoach.repository")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- settings -------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        if row is None:
            return default
        return _loads(row["value"], default)

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, _dumps(value), utcnow_iso()),
        )

    def all_settings(self) -> dict[str, Any]:
        return {
            row["key"]: _loads(row["value"], None)
            for row in self.db.query("SELECT key, value FROM app_settings")
        }

    # -- audit ----------------------------------------------------------------

    def audit(self, action: str, target: str | None = None, detail: Any = None,
              actor: str = "system") -> None:
        self.db.execute(
            "INSERT INTO audit_log(actor, action, target, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (actor, action, target, _dumps(detail) if detail is not None else None,
             utcnow_iso()),
        )

    # -- documents ------------------------------------------------------------

    def create_document(self, *, original_name: str, stored_name: str, mime: str,
                        size_bytes: int, sha256: str, status: str = "imported",
                        subject: str | None = None, source: str | None = None) -> int:
        now = utcnow_iso()
        return self.db.insert(
            "INSERT INTO documents(original_name, stored_name, mime, size_bytes, sha256, "
            "status, subject, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (original_name, stored_name, mime, size_bytes, sha256, status, subject,
             source, now, now),
        )

    def find_document_by_hash(self, sha256: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM documents WHERE sha256 = ?", (sha256,))
        return dict(row) if row else None

    def get_document(self, document_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        return dict(row) if row else None

    def list_documents(self, limit: int = 100, offset: int = 0,
                       status: str | None = None) -> list[dict]:
        if status:
            rows = self.db.query(
                "SELECT * FROM documents WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM documents ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(row) for row in rows]

    def count_documents(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM documents", default=0))

    def update_document(self, document_id: int, **fields: Any) -> None:
        allowed = {
            "status", "page_count", "subject", "source", "notes", "error",
            "mime", "size_bytes", "updated_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        updates.setdefault("updated_at", utcnow_iso())
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [document_id]
        self.db.execute(f"UPDATE documents SET {assignments} WHERE id = ?", params)

    def delete_document(self, document_id: int) -> None:
        self.db.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    # -- document pages -------------------------------------------------------

    def add_page(self, *, document_id: int, page_number: int, image_path: str | None,
                 text: str | None, ocr_engine: str | None,
                 ocr_confidence: float | None, needs_review: bool = False) -> int:
        return self.db.insert(
            "INSERT INTO document_pages(document_id, page_number, image_path, text, "
            "ocr_engine, ocr_confidence, needs_review, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, page_number, image_path, text, ocr_engine,
             ocr_confidence, 1 if needs_review else 0, utcnow_iso()),
        )

    def get_page(self, page_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM document_pages WHERE id = ?", (page_id,))
        return dict(row) if row else None

    def list_pages(self, document_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM document_pages WHERE document_id = ? ORDER BY page_number",
            (document_id,),
        )
        return [dict(row) for row in rows]

    def pages_needing_review(self, limit: int = 100) -> list[dict]:
        rows = self.db.query(
            "SELECT p.*, d.original_name FROM document_pages p "
            "JOIN documents d ON d.id = p.document_id "
            "WHERE p.needs_review = 1 ORDER BY p.id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def update_page(self, page_id: int, **fields: Any) -> None:
        allowed = {"text", "ocr_engine", "ocr_confidence", "needs_review", "image_path"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [page_id]
        self.db.execute(f"UPDATE document_pages SET {assignments} WHERE id = ?", params)

    # -- knowledge ------------------------------------------------------------

    def upsert_knowledge(self, *, title: str, content: str, subject: str | None = None,
                         topic: str | None = None, subtopic: str | None = None,
                         document_id: int | None = None, page_id: int | None = None,
                         source_label: str | None = None, page_number: int | None = None,
                         quality: float = 1.0, uncertainty: bool = False) -> tuple[int, bool]:
        """Insert knowledge, skipping exact duplicates.

        Returns ``(id, created)``. Duplicates are detected with a normalised
        content hash so re-importing a document does not inflate the database.
        """

        normalised = " ".join(content.split()).strip().lower()
        content_hash = sha256_bytes(normalised.encode("utf-8"))
        existing = self.db.query_one(
            "SELECT id FROM knowledge_items WHERE content_hash = ?", (content_hash,)
        )
        if existing:
            return int(existing["id"]), False
        now = utcnow_iso()
        new_id = self.db.insert(
            "INSERT INTO knowledge_items(document_id, page_id, title, content, subject, "
            "topic, subtopic, source_label, page_number, quality, uncertainty, "
            "content_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, page_id, title[:500], content, subject, topic, subtopic,
             source_label, page_number, float(quality), 1 if uncertainty else 0,
             content_hash, now, now),
        )
        return new_id, True

    def get_knowledge(self, item_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM knowledge_items WHERE id = ?", (item_id,))
        return dict(row) if row else None

    def update_knowledge(self, item_id: int, **fields: Any) -> None:
        allowed = {"title", "content", "subject", "topic", "subtopic", "quality",
                   "uncertainty", "source_label", "page_number"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [item_id]
        self.db.execute(f"UPDATE knowledge_items SET {assignments} WHERE id = ?", params)

    def delete_knowledge(self, item_id: int) -> None:
        self.db.execute("DELETE FROM knowledge_items WHERE id = ?", (item_id,))

    def list_knowledge(self, limit: int = 50, offset: int = 0,
                       subject: str | None = None, topic: str | None = None,
                       uncertainty_only: bool = False) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if topic:
            clauses.append("topic = ?")
            params.append(topic)
        if uncertainty_only:
            clauses.append("uncertainty = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self.db.query(
            f"SELECT * FROM knowledge_items {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        )
        return [dict(row) for row in rows]

    def count_knowledge(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM knowledge_items", default=0))

    def knowledge_topics(self) -> list[dict]:
        rows = self.db.query(
            "SELECT COALESCE(subject, 'Ohne Fachgebiet') AS subject, "
            "COALESCE(topic, 'Allgemein') AS topic, COUNT(*) AS count "
            "FROM knowledge_items GROUP BY subject, topic ORDER BY count DESC"
        )
        return [dict(row) for row in rows]

    @staticmethod
    def _fts_query(term: str) -> str:
        """Turn user input into a safe FTS5 MATCH expression.

        Each whitespace-separated token is quoted, which neutralises FTS5
        operators (``*``, ``:``, ``NEAR``, ``-``) that would otherwise change
        the query meaning or raise a syntax error.
        """

        tokens = [t for t in term.replace('"', " ").split() if t]
        if not tokens:
            return ""
        quoted = [f'"{t}"*' for t in tokens]
        return " AND ".join(quoted)

    def search_knowledge(self, term: str, limit: int = 25,
                         subject: str | None = None) -> list[dict]:
        if not term.strip():
            return []
        if self.db.fts5_available:
            match = self._fts_query(term)
            if match:
                params: list[Any] = [match]
                subject_clause = ""
                if subject:
                    subject_clause = "AND k.subject = ?"
                    params.append(subject)
                params.append(limit)
                try:
                    rows = self.db.query(
                        "SELECT k.*, bm25(knowledge_fts) AS rank FROM knowledge_fts "
                        "JOIN knowledge_items k ON k.id = knowledge_fts.rowid "
                        f"WHERE knowledge_fts MATCH ? {subject_clause} "
                        "ORDER BY rank LIMIT ?",
                        params,
                    )
                    if rows:
                        return [dict(row) for row in rows]
                except Exception as exc:  # noqa: BLE001 - FTS syntax must not 500
                    logger.warning("FTS search failed, falling back to LIKE: %s", exc)
        like = f"%{term.strip()}%"
        rows = self.db.query(
            "SELECT * FROM knowledge_items WHERE (title LIKE ? OR content LIKE ? "
            "OR topic LIKE ?) ORDER BY id DESC LIMIT ?",
            (like, like, like, limit),
        )
        return [dict(row) for row in rows]

    def knowledge_snippets(self, term: str, limit: int = 6, max_chars: int = 700) -> list[dict]:
        """Return reduced excerpts used to build Gemini prompts (token saving)."""

        results = self.search_knowledge(term, limit=limit)
        snippets: list[dict] = []
        for item in results:
            content = (item.get("content") or "").strip()
            if len(content) > max_chars:
                content = content[:max_chars].rsplit(" ", 1)[0] + " …"
            snippets.append({
                "id": item["id"],
                "title": item.get("title"),
                "subject": item.get("subject"),
                "topic": item.get("topic"),
                "source": item.get("source_label"),
                "page": item.get("page_number"),
                "excerpt": content,
            })
        return snippets

    # -- questions ------------------------------------------------------------

    def create_question(self, *, type: str, prompt: str, subject: str | None = None,
                        topic: str | None = None, difficulty: int = 2,
                        payload: Any = None, solution: Any = None,
                        explanation: str | None = None,
                        source_knowledge_ids: Sequence[int] | None = None,
                        created_by: str = "system") -> int:
        return self.db.insert(
            "INSERT INTO questions(subject, topic, type, difficulty, prompt, payload_json, "
            "solution_json, explanation, source_knowledge_ids, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (subject, topic, type, int(difficulty), prompt, _dumps(payload or {}),
             _dumps(solution or {}), explanation,
             _dumps(list(source_knowledge_ids or [])), created_by, utcnow_iso()),
        )

    def get_question(self, question_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM questions WHERE id = ?", (question_id,))
        if row is None:
            return None
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json", "{}"), {})
        item["solution"] = _loads(item.pop("solution_json", "{}"), {})
        item["source_knowledge_ids"] = _loads(item.pop("source_knowledge_ids", "[]"), [])
        return item

    def list_questions(self, *, subject: str | None = None, topic: str | None = None,
                       type: str | None = None, limit: int = 50, offset: int = 0,
                       order: str = "id DESC") -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if topic:
            clauses.append("topic = ?")
            params.append(topic)
        if type:
            clauses.append("type = ?")
            params.append(type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_order = order if order in {
            "id DESC", "id ASC", "difficulty DESC", "difficulty ASC",
            "times_served ASC", "times_correct ASC",
        } else "id DESC"
        params.extend([limit, offset])
        rows = self.db.query(
            f"SELECT * FROM questions {where} ORDER BY {safe_order} LIMIT ? OFFSET ?",
            params,
        )
        out: list[dict] = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json", "{}"), {})
            item["solution"] = _loads(item.pop("solution_json", "{}"), {})
            item["source_knowledge_ids"] = _loads(item.pop("source_knowledge_ids", "[]"), [])
            out.append(item)
        return out

    def count_questions(self, subject: str | None = None) -> int:
        if subject:
            return int(self.db.scalar(
                "SELECT COUNT(*) FROM questions WHERE subject = ?", (subject,), default=0))
        return int(self.db.scalar("SELECT COUNT(*) FROM questions", default=0))

    def sample_questions(self, *, subjects: Sequence[str] | None = None, types: Sequence[str] | None = None,
                         difficulties: Sequence[int] | None = None, limit: int = 10,
                         exclude_ids: Sequence[int] | None = None) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if subjects:
            clauses.append(f"subject IN ({','.join('?' for _ in subjects)})")
            params.extend(subjects)
        if types:
            clauses.append(f"type IN ({','.join('?' for _ in types)})")
            params.extend(types)
        if difficulties:
            clauses.append(f"difficulty IN ({','.join('?' for _ in difficulties)})")
            params.extend(difficulties)
        if exclude_ids:
            clauses.append(f"id NOT IN ({','.join('?' for _ in exclude_ids)})")
            params.extend(exclude_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.db.query(
            f"SELECT * FROM questions {where} ORDER BY (times_served * 1.0 + 1) "
            "ASC, RANDOM() LIMIT ?",
            params,
        )
        out: list[dict] = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json", "{}"), {})
            item["solution"] = _loads(item.pop("solution_json", "{}"), {})
            item["source_knowledge_ids"] = _loads(item.pop("source_knowledge_ids", "[]"), [])
            out.append(item)
        return out

    def mark_question_served(self, question_id: int, correct: bool) -> None:
        self.db.execute(
            "UPDATE questions SET times_served = times_served + 1, "
            "times_correct = times_correct + ? WHERE id = ?",
            (1 if correct else 0, question_id),
        )

    def delete_question(self, question_id: int) -> None:
        self.db.execute("DELETE FROM questions WHERE id = ?", (question_id,))

    def question_subjects(self) -> list[dict]:
        rows = self.db.query(
            "SELECT COALESCE(subject, 'Ohne Fachgebiet') AS subject, COUNT(*) AS count "
            "FROM questions GROUP BY subject ORDER BY count DESC"
        )
        return [dict(row) for row in rows]

    # -- attempts -------------------------------------------------------------

    def record_attempt(self, *, question_id: int | None, user_answer: str,
                       is_correct: bool, score: float, max_score: float,
                       feedback: str | None = None, grading_method: str | None = None,
                       duration_ms: int | None = None, exam_id: int | None = None) -> int:
        return self.db.insert(
            "INSERT INTO attempts(question_id, exam_id, user_answer, is_correct, score, "
            "max_score, feedback, grading_method, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (question_id, exam_id, user_answer, 1 if is_correct else 0, float(score),
             float(max_score), feedback, grading_method, duration_ms, utcnow_iso()),
        )

    def recent_attempts(self, limit: int = 20) -> list[dict]:
        rows = self.db.query(
            "SELECT a.*, q.prompt, q.subject, q.topic, q.type FROM attempts a "
            "LEFT JOIN questions q ON q.id = a.question_id "
            "ORDER BY a.id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def attempt_stats(self, days: int = 30) -> dict:
        row = self.db.query_one(
            "SELECT COUNT(*) AS total, COALESCE(SUM(is_correct), 0) AS correct, "
            "COALESCE(AVG(score * 1.0 / NULLIF(max_score, 0)), 0) AS avg_ratio "
            "FROM attempts WHERE created_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        if row is None:
            return {"total": 0, "correct": 0, "avg_ratio": 0.0}
        return {
            "total": int(row["total"] or 0),
            "correct": int(row["correct"] or 0),
            "avg_ratio": float(row["avg_ratio"] or 0.0),
        }

    def daily_activity(self, days: int = 14) -> list[dict]:
        rows = self.db.query(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS attempts, "
            "COALESCE(SUM(is_correct), 0) AS correct FROM attempts "
            "WHERE created_at >= datetime('now', ?) GROUP BY day ORDER BY day",
            (f"-{int(days)} days",),
        )
        return [dict(row) for row in rows]

    # -- exams ----------------------------------------------------------------

    def create_exam(self, *, title: str, config: Any, time_limit_seconds: int | None,
                    items: Sequence[dict]) -> int:
        exam_id = self.db.insert(
            "INSERT INTO exam_sessions(title, status, config_json, time_limit_seconds, "
            "created_at) VALUES (?, 'created', ?, ?, ?)",
            (title, _dumps(config), time_limit_seconds, utcnow_iso()),
        )
        for position, item in enumerate(items):
            self.db.execute(
                "INSERT INTO exam_items(exam_id, question_id, position, max_points) "
                "VALUES (?, ?, ?, ?)",
                (exam_id, item.get("question_id"), position, float(item.get("max_points", 1))),
            )
        return exam_id

    def get_exam(self, exam_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
        if row is None:
            return None
        exam = dict(row)
        exam["config"] = _loads(exam.pop("config_json", "{}"), {})
        exam["analysis"] = _loads(exam.pop("analysis_json", None), None)
        return exam

    def list_exams(self, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM exam_sessions ORDER BY id DESC LIMIT ?", (limit,)
        )
        out: list[dict] = []
        for row in rows:
            exam = dict(row)
            exam["config"] = _loads(exam.pop("config_json", "{}"), {})
            exam["analysis"] = _loads(exam.pop("analysis_json", None), None)
            out.append(exam)
        return out

    def exam_items(self, exam_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM exam_items WHERE exam_id = ? ORDER BY position", (exam_id,)
        )
        return [dict(row) for row in rows]

    def get_exam_item(self, item_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM exam_items WHERE id = ?", (item_id,))
        return dict(row) if row else None

    def update_exam_item(self, item_id: int, **fields: Any) -> None:
        allowed = {"answer", "points_awarded", "is_correct", "feedback", "answered_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [item_id]
        self.db.execute(f"UPDATE exam_items SET {assignments} WHERE id = ?", params)

    def update_exam(self, exam_id: int, **fields: Any) -> None:
        allowed = {"status", "started_at", "finished_at", "total_score", "max_score",
                   "analysis_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [exam_id]
        self.db.execute(f"UPDATE exam_sessions SET {assignments} WHERE id = ?", params)

    def delete_exam(self, exam_id: int) -> None:
        self.db.execute("DELETE FROM exam_sessions WHERE id = ?", (exam_id,))

    # -- spaced repetition ----------------------------------------------------

    def ensure_card(self, *, question_id: int, subject: str | None, topic: str | None,
                    due_at: str | None = None) -> int:
        existing = self.db.query_one(
            "SELECT id FROM srs_cards WHERE question_id = ?", (question_id,)
        )
        if existing:
            return int(existing["id"])
        return self.db.insert(
            "INSERT INTO srs_cards(question_id, subject, topic, due_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (question_id, subject, topic, due_at or utcnow_iso(), utcnow_iso()),
        )

    def get_card(self, card_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM srs_cards WHERE id = ?", (card_id,))
        return dict(row) if row else None

    def get_card_for_question(self, question_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM srs_cards WHERE question_id = ?", (question_id,))
        return dict(row) if row else None

    def update_card(self, card_id: int, **fields: Any) -> None:
        allowed = {"ease", "interval_days", "repetitions", "lapses", "due_at",
                   "last_reviewed_at", "state"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        params: list[Any] = list(updates.values()) + [card_id]
        self.db.execute(f"UPDATE srs_cards SET {assignments} WHERE id = ?", params)

    def log_review(self, *, card_id: int, question_id: int | None, grade: int,
                   ease_before: float, ease_after: float, interval_before: float,
                   interval_after: float) -> None:
        self.db.execute(
            "INSERT INTO review_log(card_id, question_id, grade, ease_before, ease_after, "
            "interval_before, interval_after, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (card_id, question_id, grade, ease_before, ease_after, interval_before,
             interval_after, utcnow_iso()),
        )

    def due_cards(self, limit: int = 20, subject: str | None = None) -> list[dict]:
        params: list[Any] = [utcnow_iso()]
        subject_clause = ""
        if subject:
            subject_clause = "AND c.subject = ?"
            params.append(subject)
        params.append(limit)
        rows = self.db.query(
            "SELECT c.*, q.prompt, q.type, q.difficulty FROM srs_cards c "
            "LEFT JOIN questions q ON q.id = c.question_id "
            f"WHERE c.due_at <= ? {subject_clause} ORDER BY c.due_at LIMIT ?",
            params,
        )
        return [dict(row) for row in rows]

    def count_due_cards(self) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM srs_cards WHERE due_at <= ?", (utcnow_iso(),), default=0))

    def review_forecast(self, days: int = 14) -> list[dict]:
        rows = self.db.query(
            "SELECT substr(due_at, 1, 10) AS day, COUNT(*) AS count FROM srs_cards "
            "WHERE due_at <= datetime('now', ?) GROUP BY day ORDER BY day",
            (f"+{int(days)} days",),
        )
        return [dict(row) for row in rows]

    # -- mastery --------------------------------------------------------------

    def update_mastery(self, *, subject: str, topic: str, correct: bool,
                       score_ratio: float) -> None:
        now = utcnow_iso()
        existing = self.db.query_one(
            "SELECT * FROM topic_mastery WHERE subject = ? AND topic = ?", (subject, topic)
        )
        if existing is None:
            mastery = score_ratio if correct else 0.0
            self.db.execute(
                "INSERT INTO topic_mastery(subject, topic, attempts, correct, mastery, "
                "last_attempt_at) VALUES (?, ?, 1, ?, ?, ?)",
                (subject, topic, 1 if correct else 0, mastery, now),
            )
            return
        attempts = int(existing["attempts"]) + 1
        correct_count = int(existing["correct"]) + (1 if correct else 0)
        # Exponential moving average so recent performance dominates.
        previous = float(existing["mastery"])
        mastery = previous * 0.7 + float(score_ratio) * 0.3
        self.db.execute(
            "UPDATE topic_mastery SET attempts = ?, correct = ?, mastery = ?, "
            "last_attempt_at = ? WHERE id = ?",
            (attempts, correct_count, mastery, now, int(existing["id"])),
        )

    def mastery_overview(self) -> list[dict]:
        rows = self.db.query(
            "SELECT subject, topic, attempts, correct, mastery, last_attempt_at "
            "FROM topic_mastery ORDER BY mastery ASC, attempts DESC"
        )
        return [dict(row) for row in rows]

    # -- study plan -----------------------------------------------------------

    def save_study_plan(self, *, plan: Any, horizon_days: int) -> int:
        self.db.execute("UPDATE study_plan SET active = 0 WHERE active = 1")
        return self.db.insert(
            "INSERT INTO study_plan(generated_at, horizon_days, plan_json, active) "
            "VALUES (?, ?, ?, 1)",
            (utcnow_iso(), int(horizon_days), _dumps(plan)),
        )

    def active_study_plan(self) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM study_plan WHERE active = 1 ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        plan = dict(row)
        plan["plan"] = _loads(plan.pop("plan_json", "{}"), {})
        return plan

    # -- drawings -------------------------------------------------------------

    def create_drawing(self, *, name: str, data: Any, thumbnail: str | None = None) -> int:
        now = utcnow_iso()
        return self.db.insert(
            "INSERT INTO drawings(name, data_json, thumbnail, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, _dumps(data), thumbnail, now, now),
        )

    def update_drawing(self, drawing_id: int, *, name: str | None, data: Any,
                       thumbnail: str | None = None) -> None:
        self.db.execute(
            "UPDATE drawings SET name = COALESCE(?, name), data_json = ?, thumbnail = ?, "
            "version = version + 1, updated_at = ? WHERE id = ?",
            (name, _dumps(data), thumbnail, utcnow_iso(), drawing_id),
        )

    def get_drawing(self, drawing_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM drawings WHERE id = ?", (drawing_id,))
        if row is None:
            return None
        item = dict(row)
        item["data"] = _loads(item.pop("data_json", "{}"), {})
        return item

    def list_drawings(self, limit: int = 100) -> list[dict]:
        rows = self.db.query(
            "SELECT id, name, thumbnail, version, created_at, updated_at FROM drawings "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    def delete_drawing(self, drawing_id: int) -> None:
        self.db.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))

    # -- jobs -----------------------------------------------------------------

    def enqueue_job(self, *, type: str, payload: Any, priority: int = 5,
                    max_attempts: int = 3) -> int:
        return self.db.insert(
            "INSERT INTO jobs(type, status, priority, payload_json, max_attempts, created_at) "
            "VALUES (?, 'queued', ?, ?, ?, ?)",
            (type, int(priority), _dumps(payload), int(max_attempts), utcnow_iso()),
        )

    def claim_job(self) -> dict | None:
        """Atomically claim the next queued job."""

        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' "
                "ORDER BY priority ASC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ?, attempts = attempts + 1 "
                "WHERE id = ?",
                (utcnow_iso(), row["id"]),
            )
        job = dict(row)
        job["payload"] = _loads(job.pop("payload_json", "{}"), {})
        job["status"] = "running"
        return job

    def finish_job(self, job_id: int, *, result: Any = None, error: str | None = None) -> None:
        status = "failed" if error else "done"
        self.db.execute(
            "UPDATE jobs SET status = ?, result_json = ?, error = ?, progress = 1.0, "
            "finished_at = ? WHERE id = ?",
            (status, _dumps(result) if result is not None else None, error,
             utcnow_iso(), job_id),
        )

    def update_job_progress(self, job_id: int, progress: float, message: str | None = None) -> None:
        self.db.execute(
            "UPDATE jobs SET progress = ?, message = ? WHERE id = ?",
            (float(progress), message, job_id),
        )

    def requeue_job(self, job_id: int) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL WHERE id = ?", (job_id,)
        )

    def get_job(self, job_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            return None
        job = dict(row)
        job["payload"] = _loads(job.pop("payload_json", "{}"), {})
        job["result"] = _loads(job.pop("result_json", None), None)
        return job

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        if status:
            rows = self.db.query(
                "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
        out: list[dict] = []
        for row in rows:
            job = dict(row)
            job["payload"] = _loads(job.pop("payload_json", "{}"), {})
            job["result"] = _loads(job.pop("result_json", None), None)
            out.append(job)
        return out

    def job_counts(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status")
        counts = {row["status"]: int(row["c"]) for row in rows}
        for key in ("queued", "running", "done", "failed", "cancelled"):
            counts.setdefault(key, 0)
        return counts

    def stale_running_jobs(self, older_than_seconds: int = 1800) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM jobs WHERE status = 'running' AND started_at IS NOT NULL "
            "AND started_at < datetime('now', ?)",
            (f"-{int(older_than_seconds)} seconds",),
        )
        return [dict(row) for row in rows]

    def cancel_job(self, job_id: int) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ? AND "
            "status IN ('queued', 'running')",
            (utcnow_iso(), job_id),
        )

    # -- events / repairs -----------------------------------------------------

    def add_event(self, *, level: str, category: str, message: str,
                  details: Any = None) -> int:
        return self.db.insert(
            "INSERT INTO system_events(level, category, message, details_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (level, category, message,
             _dumps(details) if details is not None else None, utcnow_iso()),
        )

    def list_events(self, *, level: str | None = None, unresolved_only: bool = False,
                    limit: int = 100) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if level:
            clauses.append("level = ?")
            params.append(level)
        if unresolved_only:
            clauses.append("resolved = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.db.query(
            f"SELECT * FROM system_events {where} ORDER BY id DESC LIMIT ?", params
        )
        out: list[dict] = []
        for row in rows:
            event = dict(row)
            event["details"] = _loads(event.pop("details_json", None), None)
            out.append(event)
        return out

    def resolve_event(self, event_id: int) -> None:
        self.db.execute("UPDATE system_events SET resolved = 1 WHERE id = ?", (event_id,))

    def event_counts(self) -> dict[str, int]:
        rows = self.db.query(
            "SELECT level, COUNT(*) AS c FROM system_events WHERE resolved = 0 GROUP BY level"
        )
        counts = {row["level"]: int(row["c"]) for row in rows}
        for key in ("info", "warning", "error", "critical"):
            counts.setdefault(key, 0)
        return counts

    def add_repair(self, *, event_id: int | None, action: str, status: str,
                   detail: str | None = None) -> int:
        return self.db.insert(
            "INSERT INTO repairs(event_id, action, status, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, action, status, detail, utcnow_iso()),
        )

    def list_repairs(self, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT * FROM repairs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    def last_repair(self) -> dict | None:
        row = self.db.query_one("SELECT * FROM repairs ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None

    # -- AI usage / budget / cache -------------------------------------------

    def record_ai_usage(self, *, provider: str, model: str | None, task_type: str | None,
                        prompt_tokens: int, completion_tokens: int, success: bool,
                        error: str | None = None, latency_ms: int | None = None) -> None:
        total = int(prompt_tokens) + int(completion_tokens)
        now = utcnow_iso()
        day = now[:10]
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO ai_usage(provider, model, task_type, prompt_tokens, "
                "completion_tokens, total_tokens, requests, success, error, latency_ms, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (provider, model, task_type, int(prompt_tokens), int(completion_tokens),
                 total, 1 if success else 0, error, latency_ms, now),
            )
            conn.execute(
                "INSERT INTO ai_budget(day, provider, requests_used, tokens_used) "
                "VALUES (?, ?, 1, ?) ON CONFLICT(day, provider) DO UPDATE SET "
                "requests_used = requests_used + 1, tokens_used = tokens_used + ?",
                (day, provider, total, total),
            )

    def ai_budget_today(self, provider: str) -> dict:
        day = utcnow_iso()[:10]
        row = self.db.query_one(
            "SELECT requests_used, tokens_used FROM ai_budget WHERE day = ? AND provider = ?",
            (day, provider),
        )
        if row is None:
            return {"requests_used": 0, "tokens_used": 0}
        return {"requests_used": int(row["requests_used"]),
                "tokens_used": int(row["tokens_used"])}

    def ai_usage_summary(self, days: int = 7) -> list[dict]:
        rows = self.db.query(
            "SELECT provider, COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens, "
            "COALESCE(AVG(latency_ms), 0) AS avg_latency, "
            "COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS failures "
            "FROM ai_usage WHERE created_at >= datetime('now', ?) GROUP BY provider",
            (f"-{int(days)} days",),
        )
        return [dict(row) for row in rows]

    def cache_get(self, cache_key: str) -> Any | None:
        row = self.db.query_one("SELECT * FROM ai_cache WHERE cache_key = ?", (cache_key,))
        if row is None:
            return None
        self.db.execute("UPDATE ai_cache SET hits = hits + 1 WHERE id = ?", (int(row["id"]),))
        return _loads(row["response_json"], None)

    def cache_put(self, *, cache_key: str, provider: str, model: str | None,
                  task_type: str | None, response: Any) -> None:
        self.db.execute(
            "INSERT INTO ai_cache(cache_key, provider, model, task_type, response_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
            "response_json = excluded.response_json, created_at = excluded.created_at",
            (cache_key, provider, model, task_type, _dumps(response), utcnow_iso()),
        )

    def cache_stats(self) -> dict:
        row = self.db.query_one(
            "SELECT COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS hits FROM ai_cache"
        )
        if row is None:
            return {"entries": 0, "hits": 0}
        return {"entries": int(row["entries"]), "hits": int(row["hits"])}

    def prune_ai_cache(self, keep: int = 5000) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM ai_cache WHERE id NOT IN "
                "(SELECT id FROM ai_cache ORDER BY id DESC LIMIT ?)", (int(keep),)
            )
            return cursor.rowcount or 0

    # -- backups --------------------------------------------------------------

    def add_backup(self, *, filename: str, path: str, size_bytes: int, sha256: str,
                   kind: str, status: str = "ok", integrity_ok: bool | None = None,
                   note: str | None = None) -> int:
        return self.db.insert(
            "INSERT INTO backups(filename, path, size_bytes, sha256, kind, status, "
            "integrity_ok, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (filename, path, int(size_bytes), sha256, kind, status,
             None if integrity_ok is None else (1 if integrity_ok else 0), note,
             utcnow_iso()),
        )

    def list_backups(self, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT * FROM backups ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    def replace_backups(self, records: list[dict]) -> None:
        """Rebuild the mirror table from the authoritative file-based index.

        The backup registry lives in ``index.json`` (see
        :mod:`elektrocoach.backup.service`) because a restore replaces this
        database. This table is a read-only mirror for the dashboard and the
        health checks, so it is rewritten wholesale instead of being patched.
        """

        with self.db.transaction():
            self.db.execute("DELETE FROM backups")
            for record in records:
                integrity = record.get("integrity_ok")
                self.db.execute(
                    "INSERT INTO backups(id, filename, path, size_bytes, sha256, kind, "
                    "status, integrity_ok, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(record.get("id") or 0),
                        str(record.get("filename") or ""),
                        str(record.get("path") or ""),
                        int(record.get("size_bytes") or 0),
                        record.get("sha256"),
                        str(record.get("kind") or "auto"),
                        str(record.get("status") or "ok"),
                        None if integrity is None else (1 if integrity else 0),
                        record.get("note"),
                        str(record.get("created_at") or utcnow_iso()),
                    ),
                )

    def last_successful_backup(self) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM backups WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None

    def delete_backup_record(self, backup_id: int) -> None:
        self.db.execute("DELETE FROM backups WHERE id = ?", (backup_id,))

    # -- notifications --------------------------------------------------------

    def queue_notification(self, *, title: str, message: str, level: str = "info",
                           channel: str = "homeassistant") -> int:
        return self.db.insert(
            "INSERT INTO notifications(title, message, level, channel, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (title, message, level, channel, utcnow_iso()),
        )

    def mark_notification(self, notification_id: int, *, status: str,
                          error: str | None = None) -> None:
        self.db.execute(
            "UPDATE notifications SET status = ?, error = ?, sent_at = ? WHERE id = ?",
            (status, error, utcnow_iso() if status == "sent" else None, notification_id),
        )

    def list_notifications(self, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    def pending_notifications(self, limit: int = 20) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM notifications WHERE status = 'pending' ORDER BY id LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # -- diagnostics / setup --------------------------------------------------

    def start_diagnostics(self) -> int:
        return self.db.insert(
            "INSERT INTO diagnostics_runs(started_at, status) VALUES (?, 'running')",
            (utcnow_iso(),),
        )

    def finish_diagnostics(self, run_id: int, *, report: Any, status: str) -> None:
        self.db.execute(
            "UPDATE diagnostics_runs SET finished_at = ?, status = ?, report_json = ? "
            "WHERE id = ?",
            (utcnow_iso(), status, _dumps(report), run_id),
        )

    def last_diagnostics(self) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM diagnostics_runs ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        run = dict(row)
        run["report"] = _loads(run.pop("report_json", None), None)
        return run

    def get_setup_state(self) -> dict:
        row = self.db.query_one("SELECT * FROM setup_state WHERE id = 1")
        if row is None:
            return {"current_step": 0, "steps": [], "completed": False}
        return {
            "current_step": int(row["current_step"]),
            "steps": _loads(row["steps_json"], []),
            "completed": bool(row["completed"]),
            "updated_at": row["updated_at"],
        }

    def save_setup_state(self, *, current_step: int, steps: Any, completed: bool) -> None:
        self.db.execute(
            "INSERT INTO setup_state(id, current_step, steps_json, completed, updated_at) "
            "VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "current_step = excluded.current_step, steps_json = excluded.steps_json, "
            "completed = excluded.completed, updated_at = excluded.updated_at",
            (int(current_step), _dumps(steps), 1 if completed else 0, utcnow_iso()),
        )

    # -- maintenance ----------------------------------------------------------

    def purge_old_logs(self, days: int = 60) -> dict[str, int]:
        """Delete old log rows. Tables use different timestamp columns."""

        cutoff = f"-{int(days)} days"
        # (table, timestamp column) – review_log uses reviewed_at, the others
        # use created_at. Getting this wrong would abort the whole maintenance
        # run, so the mapping is explicit and tested.
        targets = (
            ("system_events", "created_at"),
            ("ai_usage", "created_at"),
            ("notifications", "created_at"),
            ("review_log", "reviewed_at"),
        )
        removed: dict[str, int] = {}
        with self.db.transaction() as conn:
            for table, column in targets:
                try:
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE {column} < datetime('now', ?)",
                        (cutoff,),
                    )
                    removed[table] = cursor.rowcount or 0
                except sqlite3.OperationalError as exc:
                    # A missing table must not break maintenance; report zero.
                    logger.warning("purge skipped for %s: %s", table, exc)
                    removed[table] = 0
        return removed

    def vacuum(self) -> None:
        # VACUUM cannot run inside a transaction, so only the writer lock is taken.
        with self.db._write_lock:  # noqa: SLF001 - intentional, shared lock
            self.db.conn.execute("VACUUM")

    def export_all(self, tables: Iterable[str] | None = None) -> dict[str, list[dict]]:
        """Export table contents as JSON-serialisable dictionaries (for backup)."""

        default_tables = [
            "documents", "document_pages", "knowledge_items", "questions", "attempts",
            "exam_sessions", "exam_items", "srs_cards", "review_log", "topic_mastery",
            "study_plan", "drawings", "app_settings", "system_events", "repairs",
            "backups", "notifications", "audit_log",
        ]
        out: dict[str, list[dict]] = {}
        for table in (tables or default_tables):
            try:
                rows = self.db.query(f"SELECT * FROM {table}")
                out[table] = [dict(row) for row in rows]
            except Exception as exc:  # noqa: BLE001 - a missing table must not abort export
                logger.warning("export skipped table %s: %s", table, exc)
        return out
