"""Tests der Pruefungssimulation."""

from __future__ import annotations

import pytest

from app import db
from app.services import exam as exam_service


def _run(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.fixture
def question_pool():
    """Legt einen Fragenpool mit gemischten Aufgabenarten an."""
    ids: list[str] = []
    specs = [
        ("multiple_choice", "Welcher Schutzschalter schuetzt Personen?", "B", 2),
        ("multiple_choice", "Welche Norm gilt fuer Niederspannungsanlagen?", "A", 2),
        ("calculation", "Berechnen Sie den Spannungsfall.", "7.6", 3),
        ("calculation", "Berechnen Sie den Strom bei 3.5 kW.", "15.2", 3),
        ("open", "Erklaeren Sie die Aufgabe des Schutzleiters.", "Fehlerstrom ableiten", 3),
        ("open", "Beschreiben Sie die Sternschaltung.", "Aussenleiter Sternpunkt", 3),
        ("practical", "Planen Sie die Absicherung einer Wallbox.", "RCD Typ B 32 A", 4),
        ("cloze", "Der _____ schuetzt vor Fehlerstrom.", "rcd", 2),
    ]
    for qtype, prompt, answer, difficulty in specs:
        question_id = db.new_id()
        options = ["A: Antwort A", "B: Antwort B", "C: Antwort C", "D: Antwort D"] \
            if qtype == "multiple_choice" else []
        db.insert(
            "INSERT INTO questions(id, topic_id, qtype, difficulty, prompt, options_json, "
            "answer, solution_steps, explanation, points, source_chunk_ids, ai_source, "
            "verified, needs_review, tags, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (question_id, None, qtype, difficulty, prompt, db.json_dumps_safe(options),
             answer, "Schritt 1, Schritt 2", "Erklaerung", 2.0, "[]", "manual", 1, 0,
             "", db.now(), db.now()),
        )
        db.insert(
            "INSERT INTO srs(question_id, ease, interval_days, repetitions, lapses, state, "
            "due_at) VALUES(?,?,?,?,?,?,?)",
            (question_id, 2.5, 0.0, 0, 0, "new", db.now()),
        )
        ids.append(question_id)
    yield ids
    for question_id in ids:
        db.execute("DELETE FROM questions WHERE id = ?", (question_id,))


def test_presets_vorhanden():
    assert {"kurz", "standard", "voll"} <= set(exam_service.PRESETS)


def test_pruefung_ohne_fragen_wird_abgelehnt():
    db.execute("DELETE FROM exam_questions")
    result = exam_service.create_exam(question_count=5)
    if not db.query("SELECT id FROM questions LIMIT 1"):
        assert result["ok"] is False
        assert "keine Fragen" in result["error"].lower()


def test_pruefung_erstellen_mit_gemischten_aufgaben(question_pool):
    result = exam_service.create_exam(name="Testpruefung", minutes=45,
                                      question_count=6, total_points=60)
    assert result["ok"] is True
    exam = result["exam"]
    assert exam["duration_minutes"] == 45
    assert exam["status"] == "created"
    assert len(exam["questions"]) == 6

    types = {q["qtype"] for q in exam["questions"]}
    assert len(types) >= 2

    total = sum(q["points"] for q in exam["questions"])
    assert abs(total - 60) < 0.5


def test_preset_erzeugt_standardwerte(question_pool):
    result = exam_service.create_exam(preset="kurz")
    assert result["ok"] is True
    exam = result["exam"]
    assert exam["duration_minutes"] == exam_service.PRESETS["kurz"]["minutes"]


def test_punkteverteilung_gewichtet_nach_schwierigkeit(question_pool):
    result = exam_service.create_exam(question_count=8, total_points=100)
    questions = result["exam"]["questions"]
    hard = [q for q in questions if q["difficulty"] >= 4]
    easy = [q for q in questions if q["difficulty"] <= 2]
    if hard and easy:
        assert max(q["points"] for q in hard) > min(q["points"] for q in easy)


def test_pruefung_starten_setzt_status(question_pool):
    exam_id = exam_service.create_exam(question_count=4)["exam"]["id"]
    started = exam_service.start_exam(exam_id)
    assert started["status"] == "running"
    assert started["started_at"] is not None
    assert started["session_id"]


def test_antworten_speichern(question_pool):
    exam = exam_service.create_exam(question_count=3)["exam"]
    question = exam["questions"][0]
    assert exam_service.save_answer(exam["id"], question["question_id"], "Antwort A") is True
    assert exam_service.save_answer(exam["id"], "fremde-frage", "x") is False
    reloaded = exam_service.get_exam(exam["id"])
    assert reloaded["questions"][0]["answer"] == "Antwort A"


def test_pruefung_auswerten_mit_teilpunkten(question_pool):
    exam = exam_service.create_exam(question_count=5, total_points=50)["exam"]
    # Alle Fragen richtig beantworten.
    for question in exam["questions"]:
        detail = _question_detail(question["question_id"])
        answer = detail["answer"]
        if question["qtype"] == "open":
            answer = detail["answer"]
        exam_service.save_answer(exam["id"], question["question_id"], answer)

    result = _run(exam_service.finish_exam(exam["id"], use_ai=False))
    assert result["total"] > 0
    assert result["achieved"] > 0
    assert 0 <= result["percentage"] <= 100
    assert result["passed"] is True
    assert result["pass_probability"] > 0
    assert len(result["results"]) == len(exam["questions"])


def test_pruefung_ohne_antworten_ergibt_null(question_pool):
    exam = exam_service.create_exam(question_count=4)["exam"]
    result = _run(exam_service.finish_exam(exam["id"], use_ai=False))
    assert result["achieved"] == 0
    assert result["percentage"] == 0
    assert result["passed"] is False
    assert all("Nicht beantwortet" in r["feedback"] for r in result["results"])


def test_pruefung_auswerten_meldet_schwache_themen(question_pool):
    exam = exam_service.create_exam(question_count=5)["exam"]
    result = _run(exam_service.finish_exam(exam["id"], use_ai=False))
    assert isinstance(result["weak_topics"], list)


def test_bestehenswahrscheinlichkeit_grenzen():
    exam = {"duration_minutes": 90, "elapsed_seconds": 100}
    assert exam_service.estimate_pass_probability(100, exam) <= 97
    assert exam_service.estimate_pass_probability(0, exam) >= 2


def test_pruefungen_vergleichen(question_pool):
    for _ in range(2):
        exam = exam_service.create_exam(question_count=3)["exam"]
        _run(exam_service.finish_exam(exam["id"], use_ai=False))
    comparison = exam_service.compare_exams()
    assert comparison["items"]
    assert comparison["average"] is not None
    assert comparison["pass_rate"] is not None


def test_pruefung_loeschen(question_pool):
    exam_id = exam_service.create_exam(question_count=2)["exam"]["id"]
    assert exam_service.get_exam(exam_id) is not None
    db.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    assert exam_service.get_exam(exam_id) is None


def test_unbekannte_pruefung_liefert_none():
    assert exam_service.get_exam("gibt-es-nicht") is None
    assert exam_service.start_exam("gibt-es-nicht") is None


def test_auswerten_unbekannter_pruefung_wirft_fehler():
    with pytest.raises(ValueError):
        _run(exam_service.finish_exam("gibt-es-nicht"))


def _question_detail(question_id: str) -> dict:
    from app.services import learning

    return learning.get_question(question_id) or {"answer": ""}
