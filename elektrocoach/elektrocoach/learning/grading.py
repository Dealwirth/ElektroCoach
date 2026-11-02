"""Answer grading.

Grading strategy per question type:

* ``multiple_choice``  – exact set comparison (deterministic).
* ``numeric``          – deterministic evaluation with unit conversion and
  tolerance (:mod:`elektrocoach.learning.calc`).
* ``matching``         – deterministic pair comparison, partial credit.
* ``cloze``            – deterministic gap comparison with a list of accepted
  spellings per gap, partial credit.
* ``freetext`` / ``error_analysis`` / ``circuit_analysis`` / ``practical``
  – rubric-based. Gemini is used when available; otherwise a transparent
  keyword-coverage score is used and the method is reported as
  ``keyword-fallback`` so the user knows the score is approximate.

Every result carries the method that produced it, so the UI can show whether a
score came from a deterministic calculation or from an AI assessment.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..ai.base import AIError, reduce_text
from .calc import CalculationError, check_numeric, parse_value

logger = logging.getLogger("elektrocoach.learning.grading")

DETERMINISTIC_TYPES = {"multiple_choice", "numeric", "matching", "cloze"}
AI_TYPES = {"freetext", "error_analysis", "circuit_analysis", "practical", "exam_question"}


@dataclass
class GradeResult:
    is_correct: bool
    score: float
    max_score: float
    feedback: str
    method: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return max(0.0, min(1.0, self.score / self.max_score))

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_correct": self.is_correct,
            "score": round(self.score, 3),
            "max_score": round(self.max_score, 3),
            "ratio": round(self.ratio, 3),
            "feedback": self.feedback,
            "method": self.method,
            "details": self.details,
        }


GRADING_PROMPT = """Du bewertest die Antwort eines Auszubildenden zum Elektroniker \
für Energie- und Gebäudetechnik.

Aufgabe:
{prompt}

Musterlösung:
{model_answer}

Bewertungsschema:
{rubric}

Antwort des Auszubildenden:
{answer}

Bewerte fachlich, nicht nach Wortlaut. Sinngemäß richtige Formulierungen sind \
richtig. Berücksichtige fachliche Korrektheit, Vollständigkeit und die \
verwendeten Fachbegriffe.

Antworte ausschließlich mit JSON:
{{
  "points": 0.0,
  "max_points": {max_points},
  "is_correct": false,
  "feedback": "verständliche Begründung mit Hinweis auf fehlende Punkte",
  "missing": ["fehlender Aspekt 1"],
  "typical_errors": ["typischer Fehler 1"]
}}
"points" liegt zwischen 0 und {max_points}. "is_correct" ist true, wenn \
mindestens 60 Prozent der Punkte erreicht wurden."""


class Grader:
    def __init__(self, dispatcher=None) -> None:
        self.dispatcher = dispatcher

    def grade(self, question: dict, answer: str, *, use_ai: bool = True) -> GradeResult:
        qtype = (question.get("type") or "freetext").lower()
        payload = question.get("payload") or {}
        solution = question.get("solution") or {}
        max_points = float(solution.get("max_points") or payload.get("max_points") or 1.0)

        try:
            if qtype == "multiple_choice":
                return self._grade_multiple_choice(payload, solution, answer, max_points)
            if qtype == "numeric":
                return self._grade_numeric(payload, solution, answer, max_points)
            if qtype == "matching":
                return self._grade_matching(payload, solution, answer, max_points)
            if qtype == "cloze":
                return self._grade_cloze(payload, solution, answer, max_points)
        except CalculationError as exc:
            return GradeResult(
                is_correct=False, score=0.0, max_score=max_points,
                feedback=f"Die Antwort konnte nicht ausgewertet werden: {exc}",
                method="deterministic-error",
            )

        if qtype in AI_TYPES or qtype == "freetext":
            return self._grade_open(question, payload, solution, answer, max_points,
                                    use_ai=use_ai)

        # Unknown type: fall back to open grading rather than refusing.
        return self._grade_open(question, payload, solution, answer, max_points,
                                use_ai=use_ai)

    # -- deterministic graders ------------------------------------------------

    def _grade_multiple_choice(self, payload: dict, solution: dict, answer: str,
                               max_points: float) -> GradeResult:
        options = payload.get("options") or []
        correct = correct_indices(solution)
        correct_set = {int(i) for i in (correct or [])}
        if not correct_set:
            raise CalculationError(
                "Für diese Auswahlaufgabe ist keine gültige Lösung hinterlegt."
            )
        selected = _parse_index_selection(answer, len(options))
        if not selected:
            return GradeResult(False, 0.0, max_points,
                               "Es wurde keine gültige Antwort ausgewählt.",
                               "deterministic")
        if selected == correct_set:
            return GradeResult(
                True, max_points, max_points,
                "Die Antwort ist vollständig richtig.",
                "deterministic",
                {"selected": sorted(selected), "correct": sorted(correct_set)},
            )
        # Partial credit for multiple-answer questions.
        hits = len(selected & correct_set)
        misses = len(selected - correct_set)
        partial = max(0.0, (hits - misses) / max(1, len(correct_set))) * max_points
        correct_text = ", ".join(
            f"{chr(65 + i)}" for i in sorted(correct_set) if 0 <= i < 26
        )
        return GradeResult(
            partial >= max_points * 0.6, partial, max_points,
            f"Nicht vollständig richtig. Richtig gewesen wäre: {correct_text}.",
            "deterministic",
            {"selected": sorted(selected), "correct": sorted(correct_set)},
        )

    def _grade_numeric(self, payload: dict, solution: dict, answer: str,
                       max_points: float) -> GradeResult:
        expected = solution.get("expected")
        unit = solution.get("unit") or payload.get("unit")
        if expected is None and solution.get("expression"):
            # Deterministic evaluation of the reference expression.
            from .calc import safe_eval

            expected = safe_eval(solution["expression"], solution.get("variables") or {})
        if expected is None:
            raise CalculationError("Für diese Aufgabe ist keine Lösung hinterlegt.")
        tolerance_abs = solution.get("tolerance_absolute")
        tolerance_rel = float(solution.get("tolerance_relative") or 0.01)

        ok, message = check_numeric(
            answer, float(expected), unit=unit,
            tolerance_absolute=float(tolerance_abs) if tolerance_abs is not None else None,
            tolerance_relative=tolerance_rel,
        )
        steps = solution.get("steps") or payload.get("formula")
        feedback = message
        if steps:
            feedback += f"\nRechenweg: {steps}"
        return GradeResult(
            ok, max_points if ok else 0.0, max_points, feedback, "deterministic",
            {"expected": expected, "unit": unit,
             "tolerance_relative": tolerance_rel},
        )

    def _grade_matching(self, payload: dict, solution: dict, answer: str,
                        max_points: float) -> GradeResult:
        pairs = solution.get("pairs") or []
        if not pairs:
            raise CalculationError("Für diese Zuordnungsaufgabe fehlt die Lösung.")
        submitted = _parse_pair_selection(answer)
        expected = {(int(a), int(b)) for a, b in pairs}
        hits = len(submitted & expected)
        per_pair = max_points / max(1, len(expected))
        score = round(hits * per_pair, 3)
        ok = hits == len(expected)
        feedback = (
            f"{hits} von {len(expected)} Zuordnungen sind richtig."
            if not ok else "Alle Zuordnungen sind richtig."
        )
        return GradeResult(ok, score, max_points, feedback, "deterministic",
                           {"hits": hits, "expected": len(expected)})

    def _grade_cloze(self, payload: dict, solution: dict, answer: str,
                     max_points: float) -> GradeResult:
        answers = solution.get("answers") or []
        if not answers:
            raise CalculationError("Für diesen Lückentext fehlt die Lösung.")
        submitted = _split_cloze_answer(answer, len(answers))
        per_gap = max_points / max(1, len(answers))
        hits = 0
        missing: list[str] = []
        for index, accepted in enumerate(answers):
            given = submitted[index] if index < len(submitted) else ""
            alternatives = accepted if isinstance(accepted, list) else [accepted]
            if _matches_any(given, alternatives):
                hits += 1
            else:
                missing.append(f"Lücke {index + 1}: {alternatives[0]}")
        score = round(hits * per_gap, 3)
        ok = hits == len(answers)
        feedback = (
            f"{hits} von {len(answers)} Lücken sind richtig."
            if not ok else "Alle Lücken sind richtig."
        )
        if missing:
            feedback += " Korrekt wäre: " + "; ".join(missing) + "."
        return GradeResult(ok, score, max_points, feedback, "deterministic",
                           {"hits": hits, "total": len(answers)})

    # -- open-ended graders ---------------------------------------------------

    def _grade_open(self, question: dict, payload: dict, solution: dict, answer: str,
                    max_points: float, *, use_ai: bool) -> GradeResult:
        if not answer or not answer.strip():
            return GradeResult(False, 0.0, max_points,
                               "Es wurde keine Antwort abgegeben.", "empty")

        keywords = solution.get("keywords") or payload.get("keywords") or []
        model_answer = solution.get("model_answer") or solution.get("answer") or ""
        rubric = solution.get("rubric") or payload.get("rubric") or (
            "Fachliche Richtigkeit, Vollständigkeit und korrekte Fachbegriffe."
        )

        if use_ai and self.dispatcher is not None:
            ai_result = self._grade_with_ai(question, answer, model_answer, rubric,
                                            max_points)
            if ai_result is not None:
                return ai_result

        return self._grade_with_keywords(answer, keywords, max_points,
                                         model_answer=model_answer)

    def _grade_with_ai(self, question: dict, answer: str, model_answer: str,
                       rubric: str, max_points: float) -> GradeResult | None:
        prompt = GRADING_PROMPT.format(
            prompt=reduce_text(question.get("prompt") or "", 1500),
            model_answer=reduce_text(model_answer or "(keine hinterlegt)", 1500),
            rubric=reduce_text(rubric, 800),
            answer=reduce_text(answer, 2500),
            max_points=max_points,
        )
        try:
            from ..backend.runtime import run_coroutine

            payload, result = run_coroutine(
                self.dispatcher.ask_json("grading_freetext", prompt,
                                         max_tokens=800, use_cache=False)
            )
        except AIError as exc:
            logger.info("AI grading unavailable, using keyword fallback: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail
            logger.warning("AI grading failed: %s", exc)
            return None

        if not isinstance(payload, dict):
            return None
        try:
            points = float(payload.get("points") or 0.0)
        except (TypeError, ValueError):
            points = 0.0
        points = max(0.0, min(max_points, points))
        is_correct = bool(payload.get("is_correct")) or points >= max_points * 0.6
        feedback = str(payload.get("feedback") or "").strip()
        missing = [str(x) for x in (payload.get("missing") or []) if str(x).strip()]
        typical = [str(x) for x in (payload.get("typical_errors") or []) if str(x).strip()]
        if missing:
            feedback += "\nFehlende Punkte: " + "; ".join(missing) + "."
        if typical:
            feedback += "\nTypische Fehler: " + "; ".join(typical) + "."
        return GradeResult(
            is_correct, points, max_points, feedback,
            f"ai:{result.provider}",
            {"missing": missing, "typical_errors": typical,
             "tokens": result.total_tokens},
        )

    def _grade_with_keywords(self, answer: str, keywords: list, max_points: float,
                             *, model_answer: str = "") -> GradeResult:
        """Transparent fallback: score by how many required terms appear."""

        if not keywords:
            return GradeResult(
                False, 0.0, max_points,
                "Die Antwort konnte nicht automatisch bewertet werden, weil weder "
                "eine KI noch ein Bewertungsschema verfügbar ist. Bitte die Antwort "
                "selbst mit der Musterlösung vergleichen."
                + (f"\nMusterlösung: {reduce_text(model_answer, 600)}" if model_answer else ""),
                "unavailable",
            )
        normalised = _normalise(answer)
        found: list[str] = []
        missing: list[str] = []
        for keyword in keywords:
            alternatives = keyword if isinstance(keyword, list) else [keyword]
            if any(_normalise(str(a)) in normalised for a in alternatives):
                found.append(str(alternatives[0]))
            else:
                missing.append(str(alternatives[0]))
        ratio = len(found) / max(1, len(keywords))
        points = round(ratio * max_points, 3)
        ok = ratio >= 0.6
        feedback = (
            f"Erkannt: {len(found)} von {len(keywords)} erwarteten Fachbegriffen."
        )
        if missing:
            feedback += "\nFehlende Begriffe: " + ", ".join(missing) + "."
        feedback += (
            "\nHinweis: Diese Bewertung wurde ohne KI anhand der erwarteten "
            "Fachbegriffe erstellt und ist deshalb nur eine Näherung."
        )
        if model_answer:
            feedback += f"\nMusterlösung: {reduce_text(model_answer, 800)}"
        return GradeResult(ok, points, max_points, feedback, "keyword-fallback",
                           {"found": found, "missing": missing})


# -- parsing helpers ---------------------------------------------------------

_LETTER_RE = re.compile(r"\b([A-Ha-h])\b")


def correct_indices(solution: dict) -> list[int]:
    """Read the correct option indices from a stored solution.

    The canonical key is ``correct_indices``. Questions are also accepted with
    ``correct_index`` (the key the AI generator and the manual-question help
    text use) or ``correct`` (the natural short form), so a question created
    with any of them stays gradable instead of silently failing every answer.
    """

    for key in ("correct_indices", "correct", "correct_index"):
        value = solution.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [int(value)]
        if isinstance(value, (list, tuple)):
            indices: list[int] = []
            for entry in value:
                try:
                    indices.append(int(entry))
                except (TypeError, ValueError):
                    continue
            if indices:
                return indices
    return []


def _parse_index_selection(answer: str, option_count: int) -> set[int]:
    """Accept ``"B"``, ``"b"``, ``"1"``, ``"A,C"`` or a JSON list of indices."""

    if answer is None:
        return set()
    text = str(answer).strip()
    if not text:
        return set()
    if text.startswith("[") or text.startswith("{"):
        import json

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = data.get("selected") or data.get("indices") or []
            return {int(x) for x in data if str(x).strip().lstrip("-").isdigit()}
        except (ValueError, TypeError):
            pass
    selected: set[int] = set()
    letters = _LETTER_RE.findall(text)
    if letters and not re.search(r"\d", text):
        for letter in letters:
            index = ord(letter.upper()) - 65
            if 0 <= index < max(option_count, 8):
                selected.add(index)
        return selected
    for token in re.split(r"[,\s;/]+", text):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            # Indices are 0-based everywhere: the generator validates
            # ``0 <= correct_index < len(options)``, the frontend submits the
            # array position, and the setup wizard self-test answers "B" for
            # ``correct_index`` 1. Reading small numbers as 1-based would map a
            # wrong option onto the correct one, so only 0-based values inside
            # the option range are accepted.
            value = int(token)
            if 0 <= value < option_count:
                selected.add(value)
            continue
        if len(token) == 1 and token.isalpha():
            index = ord(token.upper()) - 65
            if 0 <= index < max(option_count, 8):
                selected.add(index)
    return selected


def _parse_pair_selection(answer: str) -> set[tuple[int, int]]:
    """Accept ``"A-2, B-1"``, ``"1:3;2:1"`` or a JSON list of pairs."""

    if not answer:
        return set()
    text = str(answer).strip()
    if text.startswith("["):
        import json

        try:
            data = json.loads(text)
            pairs = set()
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    pairs.add((int(item[0]), int(item[1])))
                elif isinstance(item, dict):
                    pairs.add((int(item.get("left")), int(item.get("right"))))
            return pairs
        except (ValueError, TypeError):
            return set()
    pairs: set[tuple[int, int]] = set()
    for token in re.split(r"[;,\n]+", text):
        token = token.strip()
        if not token:
            continue
        parts = re.split(r"\s*[-–:=>]+\s*", token)
        if len(parts) != 2:
            continue
        left, right = parts
        left_index = _to_index(left)
        right_index = _to_index(right)
        if left_index is not None and right_index is not None:
            pairs.add((left_index, right_index))
    return pairs


def _to_index(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token) - 1
    if len(token) == 1 and token.isalpha():
        return ord(token.upper()) - 65
    return None


def _split_cloze_answer(answer: str, expected_count: int) -> list[str]:
    if not answer:
        return []
    text = str(answer)
    if text.strip().startswith("["):
        import json

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x) for x in data]
        except (ValueError, TypeError):
            pass
    parts = [p.strip() for p in re.split(r"[;|\n]+", text) if p.strip()]
    if len(parts) < expected_count and "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts


def _normalise(text: str) -> str:
    lowered = str(text).lower().replace("ß", "ss")
    lowered = re.sub(r"[^\wäöü\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _matches_any(given: str, alternatives: list) -> bool:
    if not given:
        return False
    given_norm = _normalise(given)
    for alternative in alternatives:
        alt_norm = _normalise(str(alternative))
        if not alt_norm:
            continue
        if given_norm == alt_norm or alt_norm in given_norm:
            return True
        # Numeric tolerance inside cloze gaps (e.g. "12,5" vs "12.50").
        try:
            given_value = parse_value(given).si_value
            alt_value = parse_value(str(alternative)).si_value
            if abs(given_value - alt_value) <= max(abs(alt_value) * 0.01, 1e-9):
                return True
        except CalculationError:
            continue
    return False
