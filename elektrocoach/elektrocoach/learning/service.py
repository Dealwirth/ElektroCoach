"""Learning service: answering, progress tracking and the study plan.

This is the layer the web API talks to for everything learning-related. It
combines grading, spaced repetition and mastery tracking so that a single
"answer" call updates all three consistently.
"""

from __future__ import annotations

import logging
from typing import Any

from ..backend.util import utcnow_iso
from .grading import Grader, GradeResult
from .srs import apply_attempt_grade, review

logger = logging.getLogger("elektrocoach.learning.service")

DEFAULT_HORIZON_DAYS = 14
NEW_QUESTIONS_PER_DAY = 8
MAX_REVIEWS_PER_DAY = 40


class LearningService:
    def __init__(self, repo, dispatcher=None) -> None:
        self.repo = repo
        self.grader = Grader(dispatcher)
        self.dispatcher = dispatcher

    # -- answering ------------------------------------------------------------

    def answer(self, question_id: int, answer: str, *, use_ai: bool = True,
               duration_ms: int | None = None, exam_id: int | None = None) -> dict[str, Any]:
        question = self.repo.get_question(question_id)
        if question is None:
            raise ValueError(f"Die Aufgabe {question_id} existiert nicht.")

        grade_result: GradeResult = self.grader.grade(question, answer, use_ai=use_ai)
        subject = question.get("subject") or "Ohne Fachgebiet"
        topic = question.get("topic") or "Allgemein"

        attempt_id = self.repo.record_attempt(
            question_id=question_id,
            user_answer=str(answer or "")[:4000],
            is_correct=grade_result.is_correct,
            score=grade_result.score,
            max_score=grade_result.max_score,
            feedback=grade_result.feedback,
            grading_method=grade_result.method,
            duration_ms=duration_ms,
            exam_id=exam_id,
        )
        self.repo.mark_question_served(question_id, grade_result.is_correct)
        self.repo.update_mastery(subject=subject, topic=topic,
                                 correct=grade_result.is_correct,
                                 score_ratio=grade_result.ratio)

        card_id = self.repo.ensure_card(question_id=question_id, subject=subject,
                                        topic=topic)
        card = self.repo.get_card(card_id)
        schedule = apply_attempt_grade(
            card or {}, correct=grade_result.is_correct,
            score_ratio=grade_result.ratio, duration_ms=duration_ms,
        )
        self.repo.update_card(
            card_id, ease=schedule.ease, interval_days=schedule.interval_days,
            repetitions=schedule.repetitions, lapses=schedule.lapses,
            due_at=schedule.due_at, last_reviewed_at=utcnow_iso(),
            state=schedule.state,
        )
        self.repo.log_review(
            card_id=card_id, question_id=question_id,
            grade=2 if grade_result.is_correct else 0,
            ease_before=float((card or {}).get("ease") or 2.5),
            ease_after=schedule.ease,
            interval_before=float((card or {}).get("interval_days") or 0.0),
            interval_after=schedule.interval_days,
        )

        sources = self._sources_for(question)

        return {
            "attempt_id": attempt_id,
            "question_id": question_id,
            "grading": grade_result.as_dict(),
            "schedule": {
                "due_at": schedule.due_at,
                "interval_days": schedule.interval_days,
                "state": schedule.state,
                "description": schedule.description,
            },
            "solution": question.get("solution"),
            "explanation": question.get("explanation"),
            "sources": sources,
            "mastery": self._topic_mastery(subject, topic),
        }

    def grade_only(self, question_id: int, answer: str, *, use_ai: bool = True) -> dict:
        """Grade without recording (used for exam items until submission)."""

        question = self.repo.get_question(question_id)
        if question is None:
            raise ValueError(f"Die Aufgabe {question_id} existiert nicht.")
        result = self.grader.grade(question, answer, use_ai=use_ai)
        return {
            "grading": result.as_dict(),
            "solution": question.get("solution"),
            "explanation": question.get("explanation"),
            "sources": self._sources_for(question),
        }

    # -- queues ---------------------------------------------------------------

    def due_queue(self, *, limit: int = 20, subject: str | None = None) -> list[dict]:
        cards = self.repo.due_cards(limit=limit, subject=subject)
        out: list[dict] = []
        for card in cards:
            question = self.repo.get_question(int(card["question_id"])) if card.get("question_id") else None
            if question is None:
                continue
            out.append({
                "card_id": card["id"],
                "due_at": card["due_at"],
                "state": card["state"],
                "interval_days": card["interval_days"],
                "question": _public_question(question),
            })
        return out

    def ensure_cards(self, question_ids: list[int]) -> int:
        created = 0
        for question_id in question_ids:
            question = self.repo.get_question(question_id)
            if question is None:
                continue
            before = self.repo.get_card_for_question(question_id)
            self.repo.ensure_card(
                question_id=question_id,
                subject=question.get("subject") or "Ohne Fachgebiet",
                topic=question.get("topic") or "Allgemein",
            )
            if before is None:
                created += 1
        return created

    # -- study plan -----------------------------------------------------------

    def build_study_plan(self, *, horizon_days: int = DEFAULT_HORIZON_DAYS,
                         exam_date: str | None = None) -> dict[str, Any]:
        """Create an adaptive plan from due cards, weak topics and new material."""

        due_cards = self.repo.due_cards(limit=500)
        due_by_topic: dict[tuple[str, str], int] = {}
        for card in due_cards:
            key = (card.get("subject") or "Ohne Fachgebiet",
                   card.get("topic") or "Allgemein")
            due_by_topic[key] = due_by_topic.get(key, 0) + 1

        mastery = self.repo.mastery_overview()
        weak = [m for m in mastery if float(m["mastery"]) < 0.7]
        strong = [m for m in mastery if float(m["mastery"]) >= 0.85]

        total_questions = self.repo.count_questions()
        knowledge_count = self.repo.count_knowledge()

        days: list[dict[str, Any]] = []
        remaining_due = dict(due_by_topic)
        new_budget = NEW_QUESTIONS_PER_DAY
        for offset in range(max(1, horizon_days)):
            day_topics: list[dict[str, Any]] = []
            reviews = 0
            for key in list(remaining_due.keys()):
                if reviews >= MAX_REVIEWS_PER_DAY:
                    break
                count = remaining_due[key]
                if count <= 0:
                    del remaining_due[key]
                    continue
                take = min(count, max(3, MAX_REVIEWS_PER_DAY // max(1, len(remaining_due))))
                day_topics.append({
                    "subject": key[0], "topic": key[1], "kind": "review",
                    "count": take,
                    "reason": "Fällige Wiederholung (Spaced Repetition).",
                })
                reviews += take
                remaining_due[key] = count - take
                if remaining_due[key] <= 0:
                    del remaining_due[key]

            # Fill the rest of the day with the weakest topics.
            slots = max(0, NEW_QUESTIONS_PER_DAY - reviews)
            if slots and weak:
                weak_sorted = sorted(weak, key=lambda m: float(m["mastery"]))
                per_topic = max(1, slots // min(len(weak_sorted), 3))
                for entry in weak_sorted[:3]:
                    if slots <= 0:
                        break
                    take = min(per_topic, slots)
                    day_topics.append({
                        "subject": entry["subject"], "topic": entry["topic"],
                        "kind": "practice", "count": take,
                        "reason": (
                            f"Schwachstelle: Trefferquote "
                            f"{float(entry['mastery']) * 100:.0f} %."
                        ),
                    })
                    slots -= take

            if not day_topics and new_budget > 0 and total_questions > 0:
                day_topics.append({
                    "subject": None, "topic": "Gemischte Wiederholung",
                    "kind": "mixed", "count": min(new_budget, 10),
                    "reason": "Keine fälligen Karten: gemischte Wiederholung zur Festigung.",
                })

            days.append({
                "day_index": offset,
                "items": day_topics,
                "planned_reviews": reviews,
                "planned_new": sum(i["count"] for i in day_topics if i["kind"] != "review"),
            })

        plan = {
            "generated_at": utcnow_iso(),
            "horizon_days": horizon_days,
            "exam_date": exam_date,
            "summary": {
                "due_now": self.repo.count_due_cards(),
                "weak_topics": len(weak),
                "strong_topics": len(strong),
                "tracked_topics": len(mastery),
                "questions_available": total_questions,
                "knowledge_items": knowledge_count,
            },
            "days": days,
            "weak_topics": [
                {
                    "subject": m["subject"], "topic": m["topic"],
                    "mastery": round(float(m["mastery"]), 3),
                    "attempts": int(m["attempts"]),
                }
                for m in sorted(weak, key=lambda m: float(m["mastery"]))[:10]
            ],
            "strong_topics": [
                {"subject": m["subject"], "topic": m["topic"],
                 "mastery": round(float(m["mastery"]), 3)}
                for m in strong[:10]
            ],
            "notes": _plan_notes(total_questions, knowledge_count, weak, due_cards,
                                 exam_date),
        }
        self.repo.save_study_plan(plan=plan, horizon_days=horizon_days)
        self.repo.audit("study_plan.generate", detail={"horizon_days": horizon_days})
        return plan

    def active_plan(self) -> dict | None:
        stored = self.repo.active_study_plan()
        if stored is None:
            return None
        plan = stored["plan"]
        plan["generated_at"] = stored["generated_at"]
        plan["horizon_days"] = stored["horizon_days"]
        return plan

    # -- statistics -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "due_now": self.repo.count_due_cards(),
            "attempts_7d": self.repo.attempt_stats(7),
            "attempts_30d": self.repo.attempt_stats(30),
            "daily_activity": self.repo.daily_activity(14),
            "review_forecast": self.repo.review_forecast(14),
            "mastery": self.repo.mastery_overview()[:20],
            "questions": {
                "total": self.repo.count_questions(),
                "by_subject": self.repo.question_subjects(),
            },
            "knowledge": {"total": self.repo.count_knowledge()},
        }

    def _topic_mastery(self, subject: str, topic: str) -> dict | None:
        row = self.repo.db.query_one(
            "SELECT * FROM topic_mastery WHERE subject = ? AND topic = ?",
            (subject, topic),
        )
        if row is None:
            return None
        return {"subject": row["subject"], "topic": row["topic"],
                "mastery": round(float(row["mastery"]), 3),
                "attempts": int(row["attempts"]), "correct": int(row["correct"])}

    def _sources_for(self, question: dict) -> list[dict]:
        ids = question.get("source_knowledge_ids") or []
        sources: list[dict] = []
        for item_id in ids[:5]:
            item = self.repo.get_knowledge(int(item_id))
            if item is None:
                continue
            sources.append({
                "id": item["id"],
                "title": item.get("title"),
                "source": item.get("source_label"),
                "page": item.get("page_number"),
                "subject": item.get("subject"),
                "topic": item.get("topic"),
                "uncertainty": bool(item.get("uncertainty")),
            })
        return sources


def _public_question(question: dict) -> dict:
    """Strip the solution before a question is sent to the browser."""

    payload = question.get("payload") or {}
    public_payload = {k: v for k, v in payload.items()
                      if k not in {"correct", "correct_index", "answers", "solution"}}
    return {
        "id": question["id"],
        "type": question["type"],
        "subject": question.get("subject"),
        "topic": question.get("topic"),
        "difficulty": question.get("difficulty"),
        "prompt": question.get("prompt"),
        "payload": public_payload,
    }


def _plan_notes(total_questions: int, knowledge_count: int, weak: list[dict],
                due_cards: list[dict], exam_date: str | None) -> list[str]:
    notes: list[str] = []
    if knowledge_count == 0:
        notes.append(
            "Es sind noch keine Notizen importiert. Importieren Sie zuerst Ihre "
            "Dokumente im Bereich „Dokumentenimport“, damit Aufgaben aus Ihren "
            "eigenen Unterlagen entstehen können."
        )
    if total_questions == 0:
        notes.append(
            "Es sind noch keine Aufgaben vorhanden. Erstellen Sie im Bereich "
            "„Aufgaben“ Aufgaben (Rechenaufgaben funktionieren auch ohne KI)."
        )
    if not weak and total_questions:
        notes.append(
            "Es liegen noch wenige Ergebnisse vor. Nach einigen beantworteten "
            "Aufgaben wird der Plan gezielt auf Ihre Schwachstellen ausgerichtet."
        )
    if not due_cards and total_questions:
        notes.append(
            "Zurzeit sind keine Karten fällig. Der Plan enthält deshalb gemischte "
            "Wiederholungen zur Festigung."
        )
    if exam_date:
        notes.append(f"Der eingetragene Prüfungstermin ist der {exam_date}.")
    else:
        notes.append(
            "Es ist kein Prüfungstermin hinterlegt. Tragen Sie ihn im Bereich "
            "„Einstellungen“ ein, damit der Plan auf den Termin zuläuft."
        )
    return notes
