"""Pruefungssimulation auf Abschlusspruefungsniveau.

Bestandteile:
  * Zeitlimit, gemischte Aufgabenarten, Punkteverteilung.
  * Auswertung nach Abschluss mit Teilpunkten.
  * Bestehenswahrscheinlichkeit als unverbindliche Orientierung.
  * Vergleich mehrerer Simulationen.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
from typing import Any

from .. import db
from ..config import settings
from . import learning

log = logging.getLogger(__name__)

# Typische Gewichtung der Abschlusspruefung Elektroniker EGT (Anteile an der Gesamtpunktzahl).
DEFAULT_BLUEPRINT = [
    {"qtype": "multiple_choice", "share": 0.30, "difficulty": 2},
    {"qtype": "calculation", "share": 0.30, "difficulty": 3},
    {"qtype": "open", "share": 0.25, "difficulty": 3},
    {"qtype": "practical", "share": 0.15, "difficulty": 4},
]

PRESETS = {
    "kurz": {"name": "Kurztest", "minutes": 45, "questions": 15, "points": 50},
    "standard": {"name": "Abschlusspruefung (Standard)", "minutes": 90, "questions": 25, "points": 100},
    "voll": {"name": "Grosser Pruefungsdurchlauf", "minutes": 180, "questions": 40, "points": 100},
}


def create_exam(
    name: str | None = None, minutes: int = 90, question_count: int = 25,
    total_points: float = 100.0, preset: str | None = None,
    topic_ids: list[str] | None = None,
) -> dict[str, Any]:
    if preset and preset in PRESETS:
        cfg = PRESETS[preset]
        name = name or cfg["name"]
        minutes = cfg["minutes"]
        question_count = cfg["questions"]
        total_points = cfg["points"]

    name = name or "Pruefungssimulation"
    selected = _select_questions(question_count, topic_ids)
    if not selected:
        return {
            "ok": False,
            "error": (
                "Es sind noch keine Fragen vorhanden. Bitte zuerst Lernmaterial "
                "importieren und Fragen erzeugen."
            ),
        }

    exam_id = db.new_id()
    config = {
        "blueprint": DEFAULT_BLUEPRINT,
        "topic_ids": topic_ids or [],
        "requested_questions": question_count,
    }
    db.insert(
        "INSERT INTO exams(id, name, duration_minutes, total_points, status, config_json, "
        "created_at) VALUES(?,?,?,?,?,?,?)",
        (exam_id, name, minutes, total_points, "created", db.json_dumps_safe(config), db.now()),
    )

    total_weight = sum(max(0.5, float(q["difficulty"])) for q in selected)
    rows = []
    for order, question in enumerate(selected):
        weight = max(0.5, float(question["difficulty"]))
        points = round(total_points * weight / total_weight, 2)
        rows.append((db.new_id(), exam_id, question["id"], order, points))
    db.executemany(
        "INSERT INTO exam_questions(id, exam_id, question_id, ordinal, points) VALUES(?,?,?,?,?)",
        rows,
    )

    return {"ok": True, "exam": get_exam(exam_id)}


def _select_questions(count: int, topic_ids: list[str] | None) -> list[dict[str, Any]]:
    """Waehlt Fragen ausgewogen ueber Themen und Aufgabenarten aus."""
    params: list[Any] = []
    clause = ""
    if topic_ids:
        placeholders = ",".join("?" for _ in topic_ids)
        clause = f"WHERE q.topic_id IN ({placeholders})"
        params.extend(topic_ids)

    pool = db.query(
        f"SELECT q.id, q.qtype, q.difficulty, q.topic_id FROM questions q {clause}",  # noqa: S608
        params,
    )
    if not pool:
        return []

    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in pool:
        by_type.setdefault(row["qtype"], []).append(dict(row))

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in DEFAULT_BLUEPRINT:
        target = max(1, int(round(count * block["share"])))
        candidates = by_type.get(block["qtype"], [])
        random.shuffle(candidates)
        for candidate in candidates:
            if len(selected) >= count:
                break
            if target <= 0:
                break
            if candidate["id"] in seen:
                continue
            selected.append(candidate)
            seen.add(candidate["id"])
            target -= 1

    if len(selected) < count:
        rest = [dict(r) for r in pool if r["id"] not in seen]
        random.shuffle(rest)
        selected.extend(rest[: count - len(selected)])
    return selected[:count]


def get_exam(exam_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM exams WHERE id = ?", (exam_id,))
    if not row:
        return None
    exam = dict(row)
    items = db.query(
        "SELECT eq.id AS exam_question_id, eq.ordinal, eq.points, eq.answer, eq.score, "
        "eq.feedback, q.id AS question_id, q.qtype, q.difficulty, q.prompt, q.options_json, "
        "q.points AS base_points, t.name AS topic_name "
        "FROM exam_questions eq JOIN questions q ON q.id = eq.question_id "
        "LEFT JOIN topics t ON t.id = q.topic_id "
        "WHERE eq.exam_id = ? ORDER BY eq.ordinal",
        (exam_id,),
    )
    exam["questions"] = []
    for item in items:
        entry = dict(item)
        entry["options"] = learning._load_json(entry.pop("options_json", "[]"), [])
        exam["questions"].append(entry)
    exam["elapsed_seconds"] = _elapsed(exam)
    return exam


def _elapsed(exam: dict[str, Any]) -> int | None:
    if not exam.get("started_at"):
        return None
    start = _parse(exam["started_at"])
    end = _parse(exam["finished_at"]) if exam.get("finished_at") else dt.datetime.now()
    if not start or not end:
        return None
    return int((end - start).total_seconds())


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def start_exam(exam_id: str) -> dict[str, Any] | None:
    exam = get_exam(exam_id)
    if not exam:
        return None
    if exam["status"] == "created":
        db.execute(
            "UPDATE exams SET status = 'running', started_at = ? WHERE id = ?",
            (db.now(), exam_id),
        )
    session_id = db.new_id()
    db.insert(
        "INSERT INTO study_sessions(id, kind, started_at, planned_minutes, meta_json) "
        "VALUES(?,?,?,?,?)",
        (session_id, "exam", db.now(), exam["duration_minutes"],
         db.json_dumps_safe({"exam_id": exam_id})),
    )
    result = get_exam(exam_id)
    if result:
        result["session_id"] = session_id
    return result


async def finish_exam(exam_id: str, session_id: str | None = None,
                      use_ai: bool = True) -> dict[str, Any]:
    exam = get_exam(exam_id)
    if not exam:
        raise ValueError("Pruefung nicht gefunden")

    total = 0.0
    achieved = 0.0
    results: list[dict[str, Any]] = []
    for item in exam["questions"]:
        points = float(item["points"] or 0)
        total += points
        answer = item.get("answer") or ""
        if not answer.strip():
            score = 0.0
            feedback = "Nicht beantwortet."
        else:
            outcome = await learning.grade_answer(
                item["question_id"], answer, exam_id=exam_id, use_ai=use_ai
            )
            score = float(outcome["score"])
            feedback = outcome["feedback"]
        # Punkte der Pruefung auf die erreichte Punktzahl skalieren.
        base = float(item["base_points"] or 1) or 1.0
        scaled = round(score / base * points, 3)
        achieved += scaled
        db.execute(
            "UPDATE exam_questions SET score = ?, feedback = ? WHERE id = ?",
            (scaled, feedback[:3000], item["exam_question_id"]),
        )
        results.append({
            "question_id": item["question_id"],
            "qtype": item["qtype"],
            "topic": item["topic_name"],
            "points": points,
            "achieved": scaled,
            "feedback": feedback,
        })

    percentage = round(100 * achieved / total, 1) if total else 0.0
    passed = percentage >= settings.get_int("exam_pass_percent", 50)
    probability = estimate_pass_probability(percentage, exam)

    db.execute(
        "UPDATE exams SET status = 'finished', finished_at = ?, score = ?, passed = ?, "
        "pass_probability = ? WHERE id = ?",
        (db.now(), percentage, 1 if passed else 0, probability, exam_id),
    )
    if session_id:
        db.execute(
            "UPDATE study_sessions SET ended_at = ?, score = ?, max_score = ? WHERE id = ?",
            (db.now(), achieved, total, session_id),
        )
    learning.log_activity("exam_finished", f"{exam['name']}: {percentage} %")

    return {
        "exam_id": exam_id,
        "name": exam["name"],
        "achieved": round(achieved, 2),
        "total": round(total, 2),
        "percentage": percentage,
        "passed": passed,
        "pass_probability": probability,
        "results": results,
        "weak_topics": _weak_topics_from_results(results),
    }


def estimate_pass_probability(percentage: float, exam: dict[str, Any]) -> float:
    """Unverbindliche Orientierung, keine Vorhersage.

    Basis: erreichte Prozentzahl, Anteil unbeantworteter Fragen und die
    Zeitnutzung. Bewusst als Bandbreite formuliert (siehe docs/).
    """
    base = percentage
    if exam.get("duration_minutes") and exam.get("elapsed_seconds") is not None:
        used_ratio = min(1.0, exam["elapsed_seconds"] / (exam["duration_minutes"] * 60))
        if used_ratio > 0.95:
            base -= 3
    probability = max(2.0, min(97.0, base - 8 + percentage * 0.1))
    return round(probability, 1)


def _weak_topics_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, float]] = {}
    for item in results:
        key = item.get("topic") or "Ohne Thema"
        bucket = agg.setdefault(key, {"got": 0.0, "total": 0.0})
        bucket["got"] += float(item["achieved"])
        bucket["total"] += float(item["points"])
    out = []
    for topic, bucket in agg.items():
        ratio = bucket["got"] / bucket["total"] if bucket["total"] else 0.0
        if ratio < 0.6:
            out.append({
                "topic": topic,
                "accuracy": round(ratio, 3),
                "points": round(bucket["total"], 1),
            })
    out.sort(key=lambda item: item["accuracy"])
    return out


def list_exams(limit: int = 30) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT e.*, "
        "(SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS question_count "
        "FROM exams e ORDER BY e.created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def compare_exams() -> dict[str, Any]:
    rows = db.query(
        "SELECT id, name, score, passed, finished_at, total_points, duration_minutes "
        "FROM exams WHERE status = 'finished' ORDER BY finished_at"
    )
    items = [dict(r) for r in rows]
    if not items:
        return {"items": [], "trend": None, "average": None, "best": None}
    scores = [float(r["score"] or 0) for r in items]
    trend = None
    if len(scores) >= 2:
        trend = round(scores[-1] - scores[0], 1)
    return {
        "items": items,
        "average": round(sum(scores) / len(scores), 1),
        "best": max(scores),
        "worst": min(scores),
        "trend": trend,
        "pass_rate": round(
            100 * sum(1 for r in items if r["passed"]) / len(items), 1
        ),
    }


def save_answer(exam_id: str, question_id: str, answer: str) -> bool:
    row = db.query_one(
        "SELECT id FROM exam_questions WHERE exam_id = ? AND question_id = ?",
        (exam_id, question_id),
    )
    if not row:
        return False
    db.execute("UPDATE exam_questions SET answer = ? WHERE id = ?", (answer[:8000], row["id"]))
    return True
