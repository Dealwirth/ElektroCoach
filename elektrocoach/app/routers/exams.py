"""Pruefungssimulation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..services import gemini
from ..services import exam as exam_service
from ..services import handwriting as handwriting_service

log = logging.getLogger(__name__)

router = APIRouter(tags=["exam"])


class ExamCreate(BaseModel):
    name: str | None = None
    minutes: int = Field(default=90, ge=5, le=300)
    question_count: int = Field(default=25, ge=1, le=100)
    total_points: float = Field(default=100.0, gt=0, le=1000)
    preset: str | None = None
    topic_ids: list[str] | None = None


@router.get("/exams/presets")
async def presets() -> dict[str, Any]:
    return {"presets": exam_service.PRESETS}


@router.get("/exams")
async def list_exams(limit: int = 30) -> dict[str, Any]:
    return {"items": exam_service.list_exams(limit=limit)}


@router.post("/exams")
async def create_exam(payload: ExamCreate) -> dict[str, Any]:
    result = exam_service.create_exam(
        name=payload.name, minutes=payload.minutes, question_count=payload.question_count,
        total_points=payload.total_points, preset=payload.preset, topic_ids=payload.topic_ids,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/exams/compare")
async def compare_exams() -> dict[str, Any]:
    return exam_service.compare_exams()


@router.get("/exams/{exam_id}")
async def get_exam(exam_id: str) -> dict[str, Any]:
    exam = exam_service.get_exam(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Pruefung nicht gefunden")
    return exam


@router.post("/exams/{exam_id}/start")
async def start_exam(exam_id: str) -> dict[str, Any]:
    exam = exam_service.start_exam(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Pruefung nicht gefunden")
    return exam


class ExamAnswer(BaseModel):
    question_id: str
    answer: str = ""


@router.put("/exams/{exam_id}/answer")
async def save_answer(exam_id: str, payload: ExamAnswer) -> dict[str, Any]:
    if not exam_service.save_answer(exam_id, payload.question_id, payload.answer):
        raise HTTPException(status_code=404, detail="Frage gehoert nicht zu dieser Pruefung")
    return {"ok": True}


class HandwritingRequest(BaseModel):
    """Handschriftliche Antwort, die in Text umgewandelt werden soll."""

    question_id: str
    image: str = Field(min_length=32, description="Data-URL des Handschriftbildes")
    browser_text: str = ""
    save: bool = True


@router.post("/exams/{exam_id}/handwriting")
async def handwriting(exam_id: str, payload: HandwritingRequest) -> dict[str, Any]:
    """Erkennt eine handschriftliche Antwort und speichert sie als Text.

    Das Bild wird nur verarbeitet, wenn die Bildfreigabe aktiv ist. Der
    erkannte Text wird, wenn gewuenscht, direkt als Antwort gespeichert.
    """
    exam = exam_service.get_exam(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Pruefung nicht gefunden")

    question = next(
        (q for q in exam.get("questions", []) if q["question_id"] == payload.question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Frage gehoert nicht zu dieser Pruefung")

    result = await handwriting_service.transcribe(
        payload.image,
        hint=str(question.get("prompt") or ""),
        browser_text=payload.browser_text,
    )
    if result.get("ok") and payload.save and result.get("text"):
        exam_service.save_answer(exam_id, payload.question_id, result["text"])
    result["saved"] = bool(result.get("ok") and payload.save)
    return result


@router.get("/handwriting/status")
async def handwriting_status() -> dict[str, Any]:
    return {
        "available": handwriting_service.available(),
        "images_allowed": settings.get_bool("gemini_allow_images", False),
        "gemini_configured": gemini.is_configured(),
    }


class FinishRequest(BaseModel):
    session_id: str | None = None
    use_ai: bool = True


@router.post("/exams/{exam_id}/finish")
async def finish_exam(exam_id: str, payload: FinishRequest) -> dict[str, Any]:
    try:
        return await exam_service.finish_exam(exam_id, payload.session_id, payload.use_ai)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: str) -> dict[str, Any]:
    from .. import db

    row = db.query_one("SELECT id FROM exams WHERE id = ?", (exam_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Pruefung nicht gefunden")
    db.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    return {"ok": True}
