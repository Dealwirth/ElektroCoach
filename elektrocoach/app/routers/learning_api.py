"""Lernsystem: Themen, Fragen, Bewertung, Lernplan und Wiederholungen."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import learning

log = logging.getLogger(__name__)

router = APIRouter(tags=["learning"])


class TopicAnalyzeRequest(BaseModel):
    use_ai: bool = True


@router.get("/topics")
async def list_topics() -> dict[str, Any]:
    learning.ensure_default_topics()
    return {"items": learning.list_topics()}


@router.post("/topics/analyze")
async def analyze_topics(payload: TopicAnalyzeRequest | None = None) -> dict[str, Any]:
    return learning.analyze_topics(use_ai=bool(payload.use_ai) if payload else True)


@router.get("/topics/missing")
async def missing_topics() -> dict[str, Any]:
    learning.ensure_default_topics()
    return {"items": learning.missing_topics()}


class GenerateRequest(BaseModel):
    topic_id: str | None = None
    qtype: str = "multiple_choice"
    count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=2, ge=1, le=5)
    use_ai: bool = True


@router.post("/questions/generate")
async def generate_questions(payload: GenerateRequest) -> dict[str, Any]:
    return await learning.generate_questions(
        topic_id=payload.topic_id, qtype=payload.qtype, count=payload.count,
        difficulty=payload.difficulty, use_ai=payload.use_ai,
    )


@router.get("/questions")
async def list_questions(
    topic_id: str | None = None, qtype: str | None = None,
    needs_review: bool | None = None, limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
    return learning.list_questions(topic_id=topic_id, qtype=qtype,
                                   needs_review=needs_review, limit=limit, offset=offset)


@router.get("/questions/{question_id}")
async def get_question(question_id: str) -> dict[str, Any]:
    question = learning.get_question(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Frage nicht gefunden")
    return question


@router.delete("/questions/{question_id}")
async def delete_question(question_id: str) -> dict[str, Any]:
    if not learning.delete_question(question_id):
        raise HTTPException(status_code=404, detail="Frage nicht gefunden")
    return {"ok": True}


class AnswerRequest(BaseModel):
    answer: str = ""
    duration_ms: int = 0
    session_id: str | None = None
    use_ai: bool = True
    # "auto" | "ollama" | "gemini" — gilt nur fuer diese Bewertung.
    provider: str | None = None


@router.post("/questions/{question_id}/answer")
async def answer_question(question_id: str, payload: AnswerRequest) -> dict[str, Any]:
    try:
        return await learning.grade_answer(
            question_id, payload.answer, duration_ms=payload.duration_ms,
            session_id=payload.session_id, use_ai=payload.use_ai,
            provider=payload.provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/review/due")
async def due_questions(limit: int = 50) -> dict[str, Any]:
    items = learning.due_questions(limit=max(1, min(200, limit)))
    return {"items": items, "count": learning.due_count()}


@router.get("/plan")
async def study_plan(minutes: int | None = None) -> dict[str, Any]:
    return learning.study_plan(minutes=minutes)


@router.get("/progress")
async def progress() -> dict[str, Any]:
    return {
        "stats": learning.dashboard_stats(),
        "series": learning.study_time_series(30),
        "weak_areas": learning.weak_areas(10),
        "topics": learning.list_topics(),
        "streak": learning.study_streak(),
    }


# ---------------------------------------------------------------------------
# Lernziele
# ---------------------------------------------------------------------------
class GoalRequest(BaseModel):
    title: str
    topic_id: str | None = None
    target: str = ""
    due_date: str | None = None


@router.get("/goals")
async def list_goals() -> dict[str, Any]:
    return {"items": learning.list_goals()}


@router.post("/goals")
async def create_goal(payload: GoalRequest) -> dict[str, Any]:
    return learning.create_goal(payload.title, payload.topic_id, payload.target, payload.due_date)


class GoalUpdate(BaseModel):
    title: str | None = None
    topic_id: str | None = None
    target: str | None = None
    due_date: str | None = None
    progress: float | None = Field(default=None, ge=0, le=100)
    status: str | None = None


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: str, payload: GoalUpdate) -> dict[str, Any]:
    if not learning.update_goal(goal_id, **payload.model_dump(exclude_none=True)):
        raise HTTPException(status_code=404, detail="Lernziel nicht gefunden oder unveraendert")
    return {"ok": True}


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str) -> dict[str, Any]:
    if not learning.delete_goal(goal_id):
        raise HTTPException(status_code=404, detail="Lernziel nicht gefunden")
    return {"ok": True}
