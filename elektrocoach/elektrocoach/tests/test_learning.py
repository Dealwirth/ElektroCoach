"""Tests for the learning system: deterministic maths, grading, SRS, exams.

The calculation and grading tests use the real code paths. Grading with AI is
covered with a stubbed dispatcher, so a wrong answer from a model can never turn
a failing test green.
"""

from __future__ import annotations

import pytest


# -- deterministic calculation ----------------------------------------------

def test_safe_eval_basic_arithmetic():
    from elektrocoach.learning.calc import safe_eval

    assert safe_eval("2 + 3 * 4") == 14
    assert safe_eval("(2 + 3) * 4") == 20
    assert safe_eval("2 ** 3") == 8


def test_safe_eval_with_variables_and_functions():
    from elektrocoach.learning.calc import safe_eval

    assert safe_eval("u / i", {"u": 230.0, "i": 2.0}) == 115.0
    assert safe_eval("sqrt(16)") == 4.0
    assert round(safe_eval("pi", {}), 4) == 3.1416


def test_safe_eval_rejects_code_execution():
    from elektrocoach.learning.calc import CalculationError, safe_eval

    for expression in ("__import__('os').system('id')",
                       "open('/etc/passwd').read()",
                       "[x for x in range(3)]",
                       "lambda: 1"):
        with pytest.raises(CalculationError):
            safe_eval(expression)


def test_safe_eval_rejects_unknown_name():
    from elektrocoach.learning.calc import CalculationError, safe_eval

    with pytest.raises(CalculationError):
        safe_eval("unbekannt * 2")


def test_parse_value_understands_german_decimal_comma():
    from elektrocoach.learning.calc import parse_value

    parsed = parse_value("230,5 V")
    assert parsed.value == pytest.approx(230.5)
    assert parsed.unit == "V"


def test_parse_value_understands_german_thousands_separator():
    """``1.500 W`` is 1500 W in German notation, not 1.5 W."""

    from elektrocoach.learning.calc import parse_value

    assert parse_value("1.500 W").value == pytest.approx(1500.0)
    assert parse_value("1.500,5 W").value == pytest.approx(1500.5)
    assert parse_value("2.000.000 W").value == pytest.approx(2_000_000.0)
    # An English-format number still works.
    assert parse_value("1.5 A").value == pytest.approx(1.5)


def test_safe_eval_handles_thousands_separator_in_expressions():
    from elektrocoach.learning.calc import safe_eval

    assert safe_eval("1.500 * 2") == 3000.0
    assert safe_eval("12,5 * 4") == 50.0


def test_check_numeric_accepts_equivalent_answers():
    from elektrocoach.learning.calc import check_numeric

    assert check_numeric("230 V", 230.0, unit="V")[0] is True
    assert check_numeric("230,0V", 230.0, unit="V")[0] is True
    # Compatible unit, converted before comparison: 0.5 kV == 500 V.
    assert check_numeric("0,5 kV", 500.0, unit="V")[0] is True
    # Within absolute tolerance counts as correct.
    assert check_numeric("230.2", 230.0, tolerance_absolute=0.5)[0] is True
    # Outside tolerance does not.
    assert check_numeric("235", 230.0, tolerance_absolute=0.5)[0] is False
    # A wrong unit must be rejected even when the number matches.
    assert check_numeric("230 A", 230.0, unit="V")[0] is False


# -- grading -----------------------------------------------------------------

def make_question(**overrides):
    question = {
        "id": 1,
        "type": "multiple_choice",
        "prompt": "Welche Spannung hat das europäische Niederspannungsnetz?",
        "subject": "Elektrotechnische Grundlagen",
        "topic": "Wechselstrom",
        "payload": {"options": ["230 V", "400 V", "110 V", "24 V"]},
        "solution": {"correct_indices": [0],
                     "answer": "230 V",
                     "explanation": "Außenleiter gegen Neutralleiter.",
                     "max_points": 2.0},
        "explanation": "Außenleiter gegen Neutralleiter.",
    }
    question.update(overrides)
    return question


def test_grade_multiple_choice_correct_and_wrong(repo):
    from elektrocoach.learning.grading import Grader

    grader = Grader(dispatcher=None)
    # Indices are 0-based: option 0 is "230 V" and is the correct answer.
    correct = grader.grade(make_question(), "0", use_ai=False)
    assert correct.is_correct is True
    assert correct.score == 2.0

    wrong = grader.grade(make_question(), "1", use_ai=False)
    assert wrong.is_correct is False
    assert wrong.score == 0.0


def test_grade_multiple_choice_accepts_letter_answer(repo):
    from elektrocoach.learning.grading import Grader

    grader = Grader(dispatcher=None)
    result = grader.grade(make_question(), "A", use_ai=False)
    assert result.is_correct is True


def test_grade_numeric_is_checked_deterministically(repo):
    from elektrocoach.learning.grading import Grader

    question = make_question(
        type="numeric",
        payload={"unit": "A"},
        solution={"expected": 12.5, "unit": "A", "tolerance_relative": 0.01,
                  "steps": "I = P / U", "max_points": 4.0},
    )
    grader = Grader(dispatcher=None)
    good = grader.grade(question, "12,5 A", use_ai=False)
    assert good.is_correct is True
    assert good.score == 4.0
    assert "Rechenweg" in good.feedback

    # The same value with a wrong unit must not earn points.
    bad_unit = grader.grade(question, "12,5 V", use_ai=False)
    assert bad_unit.is_correct is False
    assert bad_unit.score == 0.0


def test_grade_numeric_supports_reference_expression(repo):
    from elektrocoach.learning.grading import Grader

    question = make_question(
        type="numeric",
        solution={"expression": "u / i", "variables": {"u": 230.0, "i": 2.0},
                  "unit": "Ω", "max_points": 3.0},
    )
    grader = Grader(dispatcher=None)
    result = grader.grade(question, "115 Ω", use_ai=False)
    assert result.is_correct is True
    assert result.score == 3.0


def test_grade_matching_gives_partial_credit(repo):
    from elektrocoach.learning.grading import Grader

    question = make_question(
        type="matching",
        solution={"pairs": [[0, 0], [1, 1], [2, 2]], "max_points": 3.0},
    )
    grader = Grader(dispatcher=None)
    full = grader.grade(question, "1-1, 2-2, 3-3", use_ai=False)
    assert full.is_correct is True
    assert full.score == 3.0

    partial = grader.grade(question, "1-1, 2-2", use_ai=False)
    assert 0 < partial.score < 3.0


def test_grade_cloze_partial_credit(repo):
    from elektrocoach.learning.grading import Grader

    question = make_question(
        type="cloze",
        solution={"answers": [["Spannung"], ["Strom"], ["Widerstand"], ["Leistung"]],
                  "max_points": 4.0},
    )
    grader = Grader(dispatcher=None)
    full = grader.grade(question, "Spannung; Strom; Widerstand; Leistung", use_ai=False)
    assert full.score == 4.0
    partial = grader.grade(question, "Spannung; Strom; falsch; falsch", use_ai=False)
    assert 0 < partial.score < 4.0
    assert "Lücke" in partial.feedback


def test_grade_open_uses_keywords_without_ai(repo):
    from elektrocoach.learning.grading import Grader

    question = make_question(
        type="open",
        payload={},
        solution={
            "keywords": [["schutzleiter", "pe"], ["fehlerstrom"],
                         ["berührungsspannung"]],
            "model_answer": "Der Schutzleiter führt den Fehlerstrom ab und begrenzt "
                            "so die Berührungsspannung.",
            "max_points": 5.0,
        },
    )
    grader = Grader(dispatcher=None)
    good = grader.grade(
        question,
        "Der Schutzleiter leitet den Fehlerstrom ab und senkt die Berührungsspannung.",
        use_ai=False,
    )
    assert good.score > 0
    poor = grader.grade(question, "Keine Ahnung.", use_ai=False)
    assert poor.score < good.score


def test_grade_never_accepts_empty_answer(repo):
    from elektrocoach.learning.grading import Grader

    grader = Grader(dispatcher=None)
    result = grader.grade(make_question(), "", use_ai=False)
    assert result.is_correct is False
    assert result.score == 0.0


def test_grade_open_with_ai_falls_back_when_ai_fails(repo):
    """A failing AI must not break grading; the keyword path still applies."""

    from elektrocoach.learning.grading import Grader

    class BrokenDispatcher:
        async def ask_json(self, *args, **kwargs):
            raise RuntimeError("KI nicht erreichbar")

    question = make_question(
        type="open",
        payload={},
        solution={"keywords": [["schutzleiter"], ["fehlerstrom"]],
                  "model_answer": "Schutzleiter führt Fehlerstrom ab.",
                  "max_points": 4.0},
    )
    grader = Grader(dispatcher=BrokenDispatcher())
    result = grader.grade(question, "Der Schutzleiter führt den Fehlerstrom ab.",
                          use_ai=True)
    # The deterministic keyword grading produced a usable result.
    assert result.score > 0
    assert result.is_correct is True


# -- spaced repetition -------------------------------------------------------

def make_card(**overrides):
    card = {
        "id": 1, "question_id": 1, "ease": 2.5, "interval_days": 0.0,
        "repetitions": 0, "lapses": 0, "due_at": None, "state": "new",
    }
    card.update(overrides)
    return card


def test_srs_first_success_schedules_in_the_future():
    from elektrocoach.learning.srs import review

    result = review(make_card(), grade=2)
    assert result.interval_days >= 1
    assert result.repetitions == 1
    assert result.state == "learning"


def test_srs_easy_grade_skips_learning_steps():
    from elektrocoach.learning.srs import review

    result = review(make_card(), grade=3)
    assert result.interval_days == 4.0


def test_srs_intervals_grow_for_review_cards():
    from elektrocoach.learning.srs import review

    card = make_card(state="review", interval_days=10.0, repetitions=3, ease=2.5)
    intervals = []
    for _ in range(3):
        result = review(card, grade=3)
        intervals.append(result.interval_days)
        card.update({"ease": result.ease, "interval_days": result.interval_days,
                     "repetitions": result.repetitions, "lapses": result.lapses,
                     "state": result.state})
    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[0]


def test_srs_failure_resets_and_lowers_ease():
    from elektrocoach.learning.srs import review

    mature = make_card(ease=2.5, interval_days=30.0, repetitions=5, state="review")
    result = review(mature, grade=0)
    assert result.interval_days < 30.0
    assert result.lapses == 1
    assert result.ease < 2.5
    assert result.repetitions == 0


def test_srs_ease_never_below_floor():
    from elektrocoach.learning.srs import MIN_EASE, review

    card = make_card(ease=MIN_EASE, interval_days=10.0, repetitions=3,
                     state="review")
    result = review(card, grade=0)
    assert result.ease >= MIN_EASE


def test_srs_hard_grade_grows_slower_than_easy():
    from elektrocoach.learning.srs import review

    card = make_card(state="review", interval_days=10.0, repetitions=3, ease=2.5)
    hard = review(card, grade=1)
    easy = review(card, grade=3)
    assert hard.interval_days < easy.interval_days


def test_srs_interval_is_capped():
    from elektrocoach.learning.srs import review

    card = make_card(state="review", interval_days=300.0, repetitions=8, ease=3.2)
    result = review(card, grade=3)
    assert result.interval_days <= 365.0


def test_apply_attempt_grade_derives_grade_from_score():
    from elektrocoach.learning.srs import apply_attempt_grade

    card = make_card(state="review", interval_days=10.0, repetitions=3)
    failed = apply_attempt_grade(card, correct=False, score_ratio=0.1)
    easy = apply_attempt_grade(card, correct=True, score_ratio=1.0)
    assert failed.lapses == 1
    assert easy.interval_days > card["interval_days"]


def test_review_log_is_written(repo):
    question_id = repo.create_question(
        type="multiple_choice", prompt="Frage?", subject="Grundlagen",
        topic="Test", payload={"options": ["a", "b"]},
        solution={"correct_indices": [0], "max_points": 1.0},
    )
    card_id = repo.ensure_card(question_id=question_id, subject="Grundlagen",
                               topic="Test", due_at=None)
    repo.log_review(card_id=card_id, question_id=question_id, grade=3,
                    ease_before=2.5, ease_after=2.6, interval_before=0.0,
                    interval_after=1.0)
    rows = repo.db.query("SELECT * FROM review_log WHERE card_id = ?", (card_id,))
    assert len(rows) == 1
    assert rows[0]["grade"] == 3


# -- exam simulation ---------------------------------------------------------

def seed_questions(repo, count: int = 12, subject: str = "Elektrotechnische Grundlagen"):
    ids = []
    for index in range(count):
        ids.append(repo.create_question(
            type="multiple_choice", prompt=f"Frage {index}?",
            subject=subject, topic="Grundlagen",
            payload={"options": ["a", "b", "c", "d"]},
            solution={"correct_indices": [index % 4], "max_points": 2.0},
        ))
    return ids


def test_exam_service_builds_and_scores_exam(repo):
    from elektrocoach.learning.exams import ExamService

    seed_questions(repo, 12)
    service = ExamService(repo)
    exam = service.create_exam(
        title="Prüfungssimulation",
        subjects=["Elektrotechnische Grundlagen"],
        time_limit_minutes=30,
    )
    assert exam["id"]
    items = repo.exam_items(exam["id"])
    assert len(items) >= 1
    assert exam["time_limit_seconds"] == 30 * 60
    assert exam["max_score"] > 0

    service.start_exam(exam["id"])
    # Answer everything correctly.
    for item in items:
        question = repo.get_question(int(item["question_id"]))
        correct = (question["solution"]["correct_indices"] or [0])[0]
        service.submit_item(int(item["id"]), str(correct), use_ai=False)
    result = service.finish_exam(exam["id"])
    assert result["status"] == "finished"
    assert result["total_score"] == result["max_score"]


def test_exam_analysis_reports_strengths_and_weaknesses(repo):
    from elektrocoach.learning.exams import ExamService

    seed_questions(repo, 8, subject="Schutzmaßnahmen")
    service = ExamService(repo)
    exam = service.create_exam(title="Analyse", subjects=["Schutzmaßnahmen"],
                               time_limit_minutes=20)
    service.start_exam(exam["id"])
    items = repo.exam_items(exam["id"])
    for index, item in enumerate(items):
        question = repo.get_question(int(item["question_id"]))
        correct = (question["solution"]["correct_indices"] or [0])[0]
        answer = str(correct) if index % 2 == 0 else "9"
        service.submit_item(int(item["id"]), answer, use_ai=False)
    result = service.finish_exam(exam["id"])
    analysis = result["analysis"]
    assert 0 < analysis["ratio"] < 1
    assert analysis["recommendations"]
    assert analysis["by_subject"]


def test_exam_result_is_labelled_as_simulation(repo):
    from elektrocoach.learning.exams import ExamService

    seed_questions(repo, 4, subject="S")
    service = ExamService(repo)
    exam = service.create_exam(title="Test", subjects=["S"], time_limit_minutes=10)
    assert exam["config"].get("disclaimer")
    assert "Simulation" in exam["config"]["disclaimer"] or "nicht" in exam["config"]["disclaimer"]
    result = service.finish_exam(exam["id"])
    assert result["analysis"]["disclaimer"]


def test_exam_time_limit_is_enforced_on_submit(repo):
    from elektrocoach.learning.exams import ExamService

    seed_questions(repo, 3, subject="S")
    service = ExamService(repo)
    exam = service.create_exam(title="Kurz", subjects=["S"], time_limit_minutes=10)
    service.start_exam(exam["id"])
    items = repo.exam_items(exam["id"])
    # Backdate the start so the limit has passed.
    repo.db.execute(
        "UPDATE exam_sessions SET started_at = datetime('now', '-40 minutes') "
        "WHERE id = ?", (exam["id"],))
    with pytest.raises(ValueError) as excinfo:
        service.submit_item(int(items[0]["id"]), "1", use_ai=False)
    assert "abgelaufen" in str(excinfo.value)
    # The exam is closed as a result.
    assert repo.get_exam(exam["id"])["status"] == "finished"


def test_exam_requires_existing_questions(repo):
    from elektrocoach.learning.exams import ExamService

    service = ExamService(repo)
    with pytest.raises(ValueError):
        service.create_exam(title="Leer", time_limit_minutes=10)


def test_multiple_choice_indices_are_not_shifted(repo):
    """A wrong option must not be graded correct through a 1-based shift.

    The frontend submits 0-based indices, so for a three-option question the
    answer "1" must select the second option. A previous implementation read
    small numbers as 1-based, which mapped "1" onto the correct first option.
    """

    from elektrocoach.learning.grading import Grader

    grader = Grader()
    question = {
        "type": "multiple_choice",
        "prompt": "Welche Aussage ist richtig?",
        "payload": {"options": ["richtig", "falsch", "auch falsch"]},
        "solution": {"correct_indices": [0], "max_points": 1},
    }
    assert grader.grade(question, "0", use_ai=False).is_correct is True
    assert grader.grade(question, "A", use_ai=False).is_correct is True
    assert grader.grade(question, "1", use_ai=False).is_correct is False
    assert grader.grade(question, "2", use_ai=False).is_correct is False
    # An out-of-range index is rejected instead of being shifted onto option 0.
    out_of_range = grader.grade(question, "3", use_ai=False)
    assert out_of_range.is_correct is False
    assert "keine gültige Antwort" in out_of_range.feedback
