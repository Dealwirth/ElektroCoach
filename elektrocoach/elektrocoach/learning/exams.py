"""Exam simulation.

An exam is created from a weighted blueprint of subjects and question types,
with a time limit and a realistic point distribution. Grading reuses the same
:class:`~elektrocoach.learning.grading.Grader` as practice mode, so the result
is consistent between the two.

The UI and the report state clearly that a simulation is **not** an official
exam paper.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..backend.util import utcnow_iso
from .grading import Grader

logger = logging.getLogger("elektrocoach.learning.exams")

DEFAULT_BLUEPRINT = [
    {"subject": "Elektrotechnische Grundlagen", "questions": 3, "points": 6},
    {"subject": "Schutzmaßnahmen", "questions": 2, "points": 5},
    {"subject": "Leitungsberechnung", "questions": 2, "points": 5},
    {"subject": "Installationsschaltungen", "questions": 2, "points": 4},
    {"subject": "Drehstrom", "questions": 1, "points": 3},
    {"subject": "Wechselstrom", "questions": 1, "points": 3},
    {"subject": "Steuerungs- und Regelungstechnik", "questions": 1, "points": 3},
    {"subject": "Photovoltaik", "questions": 1, "points": 3},
    {"subject": "Wärmepumpen", "questions": 1, "points": 2},
    {"subject": "Mess- und Prüftechnik", "questions": 1, "points": 2},
    {"subject": "VDE und Normen", "questions": 1, "points": 2},
    {"subject": "Netzwerktechnik", "questions": 1, "points": 2},
]

PASS_RATIO = 0.5
GOOD_RATIO = 0.81
SATISFACTORY_RATIO = 0.67

DISCLAIMER = (
    "Hinweis: Diese Prüfungssimulation wurde automatisch aus Ihren eigenen "
    "Aufgaben zusammengestellt. Sie entspricht nicht einer offiziellen "
    "Prüfungsaufgabe der IHK und ersetzt keine offizielle Prüfung."
)


class ExamService:
    def __init__(self, repo, dispatcher=None) -> None:
        self.repo = repo
        self.grader = Grader(dispatcher)

    # -- creation -------------------------------------------------------------

    def create_exam(self, *, title: str | None = None,
                    blueprint: list[dict] | None = None,
                    time_limit_minutes: int = 90,
                    subjects: list[str] | None = None,
                    total_questions: int | None = None) -> dict[str, Any]:
        blueprint = blueprint or DEFAULT_BLUEPRINT
        if subjects:
            blueprint = [b for b in blueprint if b["subject"] in subjects] or blueprint

        selected: list[dict] = []
        used_ids: list[int] = []
        for block in blueprint:
            count = int(block.get("questions") or 1)
            points_each = float(block.get("points") or 2) / max(1, count)
            questions = self.repo.sample_questions(
                subjects=[block["subject"]], limit=count, exclude_ids=used_ids
            )
            if not questions and block["subject"]:
                # Fall back to any question if the subject has none yet.
                questions = self.repo.sample_questions(limit=count, exclude_ids=used_ids)
            for question in questions:
                used_ids.append(int(question["id"]))
                selected.append({
                    "question_id": question["id"],
                    "max_points": points_each,
                    "subject": question.get("subject"),
                    "type": question.get("type"),
                })

        if total_questions:
            selected = selected[:total_questions]

        if not selected:
            raise ValueError(
                "Es sind noch keine Aufgaben vorhanden. Erstellen Sie zuerst im "
                "Bereich „Aufgaben“ Aufgaben, zum Beispiel Rechenaufgaben."
            )

        exam_title = title or f"Prüfungssimulation {utcnow_iso()[:16].replace('T', ' ')}"
        max_score = sum(item["max_points"] for item in selected)
        config = {
            "blueprint": blueprint,
            "subjects": sorted({item["subject"] for item in selected if item["subject"]}),
            "disclaimer": DISCLAIMER,
            "pass_ratio": PASS_RATIO,
        }
        exam_id = self.repo.create_exam(
            title=exam_title, config=config,
            time_limit_seconds=int(time_limit_minutes) * 60, items=selected,
        )
        self.repo.update_exam(exam_id, max_score=max_score, status="created")
        self.repo.audit("exam.create", target=str(exam_id),
                        detail={"questions": len(selected), "max_score": max_score})
        return self.get_exam(exam_id)

    # -- retrieval ------------------------------------------------------------

    def get_exam(self, exam_id: int, *, include_solutions: bool = False) -> dict:
        exam = self.repo.get_exam(exam_id)
        if exam is None:
            raise ValueError(f"Die Prüfung {exam_id} existiert nicht.")
        items = self.repo.exam_items(exam_id)
        enriched: list[dict] = []
        for item in items:
            question = (self.repo.get_question(int(item["question_id"]))
                        if item.get("question_id") else None)
            entry = {
                "item_id": item["id"],
                "position": item["position"],
                "max_points": item["max_points"],
                "answer": item.get("answer"),
                "points_awarded": item.get("points_awarded"),
                "is_correct": item.get("is_correct"),
                "feedback": item.get("feedback"),
                "answered_at": item.get("answered_at"),
                "question": _exam_question(question, include_solutions),
            }
            enriched.append(entry)
        exam["items"] = enriched
        exam["remaining_seconds"] = self._remaining_seconds(exam)
        exam["disclaimer"] = DISCLAIMER
        return exam

    def list_exams(self) -> list[dict]:
        return self.repo.list_exams()

    def start_exam(self, exam_id: int) -> dict:
        exam = self.repo.get_exam(exam_id)
        if exam is None:
            raise ValueError(f"Die Prüfung {exam_id} existiert nicht.")
        if exam["status"] == "created":
            self.repo.update_exam(exam_id, status="running", started_at=utcnow_iso())
        return self.get_exam(exam_id)

    # -- answering ------------------------------------------------------------

    def submit_item(self, item_id: int, answer: str, *, use_ai: bool = True) -> dict:
        item = self.repo.get_exam_item(item_id)
        if item is None:
            raise ValueError(f"Die Prüfungsaufgabe {item_id} existiert nicht.")
        exam = self.repo.get_exam(int(item["exam_id"]))
        if exam is None:
            raise ValueError("Die zugehörige Prüfung existiert nicht.")
        if exam["status"] == "finished":
            raise ValueError("Diese Prüfung ist bereits abgeschlossen.")

        # Enforce the time limit on the server. The browser also hides the form,
        # but a client must never be able to answer after the deadline.
        remaining = self._remaining_seconds(exam)
        if remaining is not None and exam["status"] == "running" and remaining <= 0:
            self.repo.update_exam(int(exam["id"]), status="finished",
                                  finished_at=utcnow_iso())
            raise ValueError(
                "Die Prüfungszeit ist abgelaufen. Die Prüfung wurde automatisch "
                "abgeschlossen; bitte rufen Sie die Auswertung auf."
            )

        question = self.repo.get_question(int(item["question_id"]))
        if question is None:
            raise ValueError("Die zugrunde liegende Aufgabe existiert nicht mehr.")

        result = self.grader.grade(question, answer, use_ai=use_ai)
        ratio = result.ratio
        max_points = float(item["max_points"])
        awarded = round(ratio * max_points, 3)

        self.repo.update_exam_item(
            item_id, answer=str(answer or "")[:4000], points_awarded=awarded,
            is_correct=1 if result.is_correct else 0, feedback=result.feedback,
            answered_at=utcnow_iso(),
        )
        self.repo.record_attempt(
            question_id=int(item["question_id"]), user_answer=str(answer or "")[:4000],
            is_correct=result.is_correct, score=awarded, max_score=max_points,
            feedback=result.feedback, grading_method=result.method,
            exam_id=int(item["exam_id"]),
        )
        return {
            "item_id": item_id,
            "grading": result.as_dict(),
            "points_awarded": awarded,
            "max_points": max_points,
            "solution": question.get("solution"),
            "explanation": question.get("explanation"),
        }

    # -- finishing ------------------------------------------------------------

    def finish_exam(self, exam_id: int) -> dict:
        exam = self.repo.get_exam(exam_id)
        if exam is None:
            raise ValueError(f"Die Prüfung {exam_id} existiert nicht.")
        items = self.repo.exam_items(exam_id)
        total = sum(float(item["points_awarded"] or 0) for item in items)
        max_score = sum(float(item["max_points"]) for item in items)
        analysis = self._analyse(exam, items, total, max_score)
        self.repo.update_exam(
            exam_id, status="finished", finished_at=utcnow_iso(),
            total_score=round(total, 3), max_score=round(max_score, 3),
            analysis_json=json.dumps(analysis, ensure_ascii=False),
        )
        self.repo.audit("exam.finish", target=str(exam_id),
                        detail={"score": round(total, 3), "max": round(max_score, 3)})
        return self.get_exam(exam_id, include_solutions=True)

    def _analyse(self, exam: dict, items: list[dict], total: float,
                 max_score: float) -> dict:
        ratio = (total / max_score) if max_score else 0.0
        grade = _grade_from_ratio(ratio)

        by_subject: dict[str, dict[str, float]] = {}
        by_type: dict[str, dict[str, float]] = {}
        unanswered = 0
        for item in items:
            question = (self.repo.get_question(int(item["question_id"]))
                        if item.get("question_id") else None)
            subject = (question or {}).get("subject") or "Ohne Fachgebiet"
            qtype = (question or {}).get("type") or "unbekannt"
            awarded = float(item["points_awarded"] or 0)
            possible = float(item["max_points"])
            if item.get("answer") in (None, ""):
                unanswered += 1
            for bucket, key in ((by_subject, subject), (by_type, qtype)):
                entry = bucket.setdefault(key, {"awarded": 0.0, "possible": 0.0})
                entry["awarded"] += awarded
                entry["possible"] += possible

        def summarise(bucket: dict[str, dict[str, float]]) -> list[dict]:
            out = []
            for key, values in bucket.items():
                possible = values["possible"] or 1.0
                out.append({
                    "name": key,
                    "awarded": round(values["awarded"], 2),
                    "possible": round(values["possible"], 2),
                    "ratio": round(values["awarded"] / possible, 3),
                })
            return sorted(out, key=lambda x: x["ratio"])

        subjects = summarise(by_subject)
        types = summarise(by_type)
        strengths = [s for s in subjects if s["ratio"] >= 0.8]
        weaknesses = [s for s in subjects if s["ratio"] < 0.6]

        recommendations: list[str] = []
        for weak in weaknesses[:4]:
            recommendations.append(
                f"Wiederholen Sie das Fachgebiet „{weak['name']}“ "
                f"(erreicht {weak['ratio'] * 100:.0f} % der Punkte). "
                "Legen Sie im Lernplan gezielte Übungen für dieses Thema an."
            )
        if unanswered:
            recommendations.append(
                f"{unanswered} Aufgabe(n) wurden nicht beantwortet. Achten Sie in "
                "der echten Prüfung darauf, jede Aufgabe zumindest teilweise zu "
                "bearbeiten."
            )
        if not weaknesses and subjects:
            recommendations.append(
                "Alle bearbeiteten Fachgebiete liegen über 60 %. Steigern Sie den "
                "Schwierigkeitsgrad, um das Niveau zu halten."
            )

        return {
            "score": round(total, 3),
            "max_score": round(max_score, 3),
            "ratio": round(ratio, 4),
            "percent": round(ratio * 100, 1),
            "grade": grade,
            "passed": ratio >= PASS_RATIO,
            "unanswered": unanswered,
            "by_subject": subjects,
            "by_type": types,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recommendations,
            "disclaimer": DISCLAIMER,
            "generated_at": utcnow_iso(),
        }

    def _remaining_seconds(self, exam: dict) -> int | None:
        if exam.get("time_limit_seconds") is None:
            return None
        if exam["status"] == "finished":
            return 0
        if exam["status"] != "running" or not exam.get("started_at"):
            return int(exam["time_limit_seconds"])
        from ..backend.util import parse_iso

        started = parse_iso(exam["started_at"])
        if started is None:
            return int(exam["time_limit_seconds"])
        from ..backend.util import utcnow

        elapsed = (utcnow() - started).total_seconds()
        return max(0, int(exam["time_limit_seconds"] - elapsed))


def _exam_question(question: dict | None, include_solutions: bool) -> dict | None:
    if question is None:
        return None
    payload = question.get("payload") or {}
    public_payload = {k: v for k, v in payload.items()
                      if k not in {"correct", "correct_index", "answers", "solution"}}
    entry = {
        "id": question["id"],
        "type": question["type"],
        "subject": question.get("subject"),
        "topic": question.get("topic"),
        "difficulty": question.get("difficulty"),
        "prompt": question.get("prompt"),
        "payload": public_payload,
    }
    if include_solutions:
        entry["solution"] = question.get("solution")
        entry["explanation"] = question.get("explanation")
    return entry


def _grade_from_ratio(ratio: float) -> str:
    if ratio >= GOOD_RATIO:
        return "sehr gut bis gut"
    if ratio >= SATISFACTORY_RATIO:
        return "befriedigend"
    if ratio >= PASS_RATIO:
        return "ausreichend"
    return "nicht bestanden"
