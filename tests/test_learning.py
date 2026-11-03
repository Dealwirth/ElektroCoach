"""Tests fuer Themenkatalog, Fragengenerierung, Bewertung, Lernplan und SM-2."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app import db
from app.services import learning, srs
from app.services.library import delete_document, store_document


@pytest.fixture
def material():
    """Legt echten Lerninhalt an, damit die Themenzuordnung greift."""
    text = (
        "Der Fehlerstrom-Schutzschalter (RCD) mit 30 mA Bemessungsdifferenzstrom\n"
        "schuetzt Personen bei indirektem Beruehren.\n\n"
        "Der Leitungsschutzschalter schuetzt die Leitung vor Ueberlast und Kurzschluss.\n"
        "Der Nennstrom wird nach der Verlegeart und der Strombelastbarkeit gewaehlt.\n\n"
        "Der Spannungsfall wird mit U = (2 * l * I * cos phi) / (kappa * A) berechnet.\n"
        "Der Querschnitt muss so gewaehlt werden, dass der Spannungsfall unter 3 % bleibt.\n\n"
        "Der Schutzleiter muss niederohmig mit dem Potentialausgleich verbunden sein.\n"
        "Die Erdung erfolgt ueber den Fundamenterder und den Hauptpotentialausgleich."
    )
    tmp = Path(db.settings.data_dir) / "testmaterial"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "lehrjahr1.txt"
    path.write_text(text, encoding="utf-8")
    document = store_document(path, "lehrjahr1.txt", collection="Lehrjahr 1")
    yield document
    delete_document(document["id"])


def test_standardthemenkatalog_wird_angelegt():
    learning.ensure_default_topics()
    topics = learning.list_topics()
    assert len(topics) >= 20
    slugs = {t["slug"] for t in topics}
    assert {"rcd", "leitungsschutzschalter", "leitungsberechnung", "drehstrom"} <= slugs


def test_themenkatalog_wird_nicht_doppelt_angelegt():
    learning.ensure_default_topics()
    first = len(learning.list_topics())
    assert learning.ensure_default_topics() == 0
    assert len(learning.list_topics()) == first


def test_themenanalyse_ordnet_material_zu(material):
    report = learning.analyze_topics()
    assert report["assigned_chunks"] > 0
    assert report["ai_used"] is False

    topics = {t["slug"]: t for t in learning.list_topics()}
    assert topics["rcd"]["chunk_count"] > 0
    assert topics["leitungsberechnung"]["chunk_count"] > 0
    assert topics["schutzleiter"]["chunk_count"] > 0


def test_fehlende_themen_werden_gemeldet(material):
    learning.analyze_topics()
    missing = learning.missing_topics()
    assert missing
    assert all(item["chunks"] < 3 for item in missing)


def test_fragengenerierung_ohne_ki_erzeugt_pruefbeduerftige_fragen(material):
    learning.analyze_topics()
    result = _run(learning.generate_questions(
        topic_id=None, qtype="cloze", count=3, difficulty=2, use_ai=False,
    ))
    assert result["created"] >= 1
    assert result["ai_used"] is False
    assert result["note"]
    for question in result["questions"]:
        assert question["id"]
        assert question["needs_review"] in (0, 1)


def test_fragengenerierung_respektiert_obergrenze(material):
    learning.analyze_topics()
    result = _run(learning.generate_questions(
        topic_id=None, qtype="open", count=2, difficulty=3, use_ai=False,
    ))
    assert result["created"] <= 2


def test_multiple_choice_bewertung_richtig_falsch(material):
    learning.analyze_topics()
    question_id = _make_question(
        prompt="Welcher Schutzschalter schuetzt Personen bei Fehlerstrom?",
        qtype="multiple_choice", answer="B",
        options=["A: Leitungsschutzschalter", "B: RCD", "C: Sicherung", "D: Schalter"],
    )
    correct = _run(learning.grade_answer(question_id, "B", use_ai=False))
    assert correct["correct"] is True
    assert correct["score"] == correct["max_points"]

    wrong = _run(learning.grade_answer(question_id, "A", use_ai=False))
    assert wrong["correct"] is False
    assert wrong["score"] == 0.0
    assert wrong["reference_answer"] == "B"


def test_rechenaufgabe_mit_zahlenvergleich(material):
    question_id = _make_question(
        prompt="Berechnen Sie den Spannungsfall in Volt.",
        qtype="calculation", answer="6.9",
        solution_steps="U = (2 * l * I) / (kappa * A) = (2 * 20 * 16) / (56 * 1.5) = 7.6 V",
    )
    result = _run(learning.grade_answer(question_id, "6,9 V", use_ai=False))
    assert result["correct"] is True
    assert result["solution_steps"]


def test_rechenaufgabe_falsche_zahl_zeigt_abweichung(material):
    question_id = _make_question(
        prompt="Berechnen Sie den Strom.", qtype="calculation", answer="16",
    )
    result = _run(learning.grade_answer(question_id, "10", use_ai=False))
    assert result["correct"] is False
    assert "Ergebnis weicht ab" in result["feedback"]


def test_offene_frage_teilpunkte_und_quellen(material):
    learning.analyze_topics()
    question_id = _make_question(
        prompt="Erklaeren Sie die Aufgabe des Schutzleiters.",
        qtype="open",
        answer="Der Schutzleiter fuehrt Fehlerstroeme ab und loest die Schutzeinrichtung aus.",
        source_chunk_ids=[c["id"] for c in db.query("SELECT id FROM chunks LIMIT 2")],
    )
    result = _run(learning.grade_answer(question_id, "Der Schutzleiter fuehrt Fehlerstroeme ab", use_ai=False))
    assert 0 < result["score"] <= result["max_points"]
    assert result["sources"]


def test_bewertung_ohne_ki_ist_als_orientierung_gekennzeichnet(material):
    question_id = _make_question(
        prompt="Erklaeren Sie den RCD.", qtype="open",
        answer="Der RCD vergleicht den Strom im Aussenleiter und Neutralleiter.",
    )
    result = _run(learning.grade_answer(question_id, "Der RCD vergleicht Stroeme", use_ai=False))
    assert result["ai_used"] is False
    assert "Orientierung" in result["feedback"]


def test_bewertung_unbekannter_frage_wirft_fehler():
    with pytest.raises(ValueError):
        _run(learning.grade_answer("gibt-es-nicht", "antwort"))


def test_sm2_richtige_antworten_verlaengern_intervall():
    state = srs.SrsState()
    state, due1 = srs.review(state, 5)
    assert state.repetitions == 1
    assert state.interval_days == 1.0
    state, due2 = srs.review(state, 5)
    assert state.repetitions == 2
    assert state.interval_days == 6.0
    state, due3 = srs.review(state, 5)
    assert state.interval_days > 6.0
    assert due3 > due2 > due1


def test_sm2_falsche_antwort_setzt_zurueck():
    state = srs.SrsState(ease=2.5, interval_days=30, repetitions=5, state="review")
    new_state, due = srs.review(state, 1)
    assert new_state.repetitions == 0
    assert new_state.lapses == 1
    assert new_state.state == "relearning"
    assert new_state.interval_days <= 0.5


def test_sm2_ease_wird_begrenzt():
    state = srs.SrsState()
    for _ in range(20):
        state, _ = srs.review(state, 0)
    assert state.ease >= srs.MIN_EASE


def test_quality_from_score_grenzwerte():
    assert srs.quality_from_score(1.0, 1.0) == 5
    assert srs.quality_from_score(0.9, 1.0) == 4
    assert srs.quality_from_score(0.75, 1.0) == 3
    assert srs.quality_from_score(0.5, 1.0) == 2
    assert srs.quality_from_score(0.3, 1.0) == 1
    assert srs.quality_from_score(0.0, 1.0) == 0
    assert srs.quality_from_score(1.0, 0.0) == 0


def test_srs_zustand_wird_gespeichert(material):
    question_id = _make_question(prompt="Frage", qtype="open", answer="Antwort")
    _run(learning.grade_answer(question_id, "Antwort", use_ai=False))
    row = db.query_one("SELECT * FROM srs WHERE question_id = ?", (question_id,))
    assert row is not None
    assert row["due_at"] is not None
    assert row["repetitions"] >= 1


def test_faellige_wiederholungen_werden_gefunden(material):
    question_id = _make_question(prompt="Faellig", qtype="open", answer="Antwort")
    db.execute("UPDATE srs SET due_at = ? WHERE question_id = ?",
               ("2000-01-01T00:00:00", question_id))
    due = learning.due_questions(limit=100)
    assert any(item["id"] == question_id for item in due)
    assert learning.due_count() >= 1


def test_lernplan_verteilt_zeitbudget(material):
    for _ in range(8):
        question_id = _make_question(prompt="Planfrage", qtype="open", answer="x")
        db.execute("UPDATE srs SET due_at = ? WHERE question_id = ?",
                   ("2000-01-01T00:00:00", question_id))
    plan = learning.study_plan(minutes=10)
    assert plan["minutes_available"] == 10
    assert plan["due_total"] >= 8
    assert plan["schedule"]["review_count"] >= 1
    assert plan["schedule"]["planned_minutes"] <= 10


def test_lernplan_mit_sehr_wenig_zeit():
    schedule = srs.plan_daily_schedule([], 1)
    assert schedule["review_count"] == 0
    assert schedule["planned_minutes"] == 0


def test_lernziele_anlegen_aendern_loeschen():
    goal = learning.create_goal("Pruefung bestehen", target="Alle Themen ueben")
    assert goal["id"]
    assert learning.update_goal(goal["id"], progress=50.0, status="open") is True
    goals = [g for g in learning.list_goals() if g["id"] == goal["id"]]
    assert goals and goals[0]["progress"] == 50.0
    assert learning.delete_goal(goal["id"]) is True
    assert learning.delete_goal(goal["id"]) is False


def test_lernziel_mit_unbekanntem_feld_wird_ignoriert():
    goal = learning.create_goal("Test")
    assert learning.update_goal(goal["id"], unsinniges_feld="x") is False
    learning.delete_goal(goal["id"])


def test_mastery_level_skala():
    assert srs.mastery_level(1.0, 1.0, 10)["level"] == "sicher"
    assert srs.mastery_level(0.0, 0.0, 0)["level"] == "offen"
    assert 0 <= srs.mastery_level(0.7, 0.7, 5)["score"] <= 100


def test_dashboard_kennzahlen(material):
    stats = learning.dashboard_stats()
    for key in ("documents", "pages", "chunks", "questions", "accuracy",
                "due_reviews", "streak_days", "topics"):
        assert key in stats
    assert stats["documents"] >= 1
    assert stats["topics"] >= 20


def test_zeitreihe_hat_feste_laenge():
    series = learning.study_time_series(7)
    assert len(series) == 7
    assert all("day" in item and "minutes" in item for item in series)


def test_lernserie_ohne_aktivitaet_ist_null():
    assert isinstance(learning.study_streak(), int)
    assert learning.study_streak() >= 0


def test_aktivitaetsprotokoll():
    learning.log_activity("test", "Eintrag")
    activity = learning.recent_activity(5)
    assert any(item["kind"] == "test" for item in activity)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _make_question(
    prompt: str, qtype: str = "open", answer: str = "",
    options: list[str] | None = None, source_chunk_ids: list[str] | None = None,
    solution_steps: str = "", points: float = 2.0,
) -> str:
    question_id = db.new_id()
    db.insert(
        "INSERT INTO questions(id, topic_id, qtype, difficulty, prompt, options_json, answer, "
        "solution_steps, explanation, points, source_chunk_ids, ai_source, verified, "
        "needs_review, tags, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (question_id, None, qtype, 2, prompt, db.json_dumps_safe(options or []), answer,
         solution_steps, "Erklaerung", points, db.json_dumps_safe(source_chunk_ids or []),
         "manual", 1, 0, "", db.now(), db.now()),
    )
    db.insert(
        "INSERT INTO srs(question_id, ease, interval_days, repetitions, lapses, state, "
        "due_at, last_reviewed_at) VALUES(?,?,?,?,?,?,?,?)",
        (question_id, 2.5, 0.0, 0, 0, "new", db.now(), None),
    )
    return question_id
