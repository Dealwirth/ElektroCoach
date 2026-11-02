"""Learning, question and exam endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..learning.generator import DIFFICULTY_LABELS, VALID_TYPES
from ..learning.grading import correct_indices
from ..learning.service import _public_question

logger = logging.getLogger("elektrocoach.api.learning")

router = APIRouter(prefix="/api", tags=["learning"])


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=20000)
    use_ai: bool = True
    duration_ms: int | None = Field(default=None, ge=0, le=24 * 3600 * 1000)


class GenerateRequest(BaseModel):
    subject: str | None = None
    topic: str | None = None
    count: int = Field(default=5, ge=1, le=30)
    use_ai: bool = True
    types: list[str] | None = None


class ManualQuestionRequest(BaseModel):
    type: str
    prompt: str = Field(min_length=5, max_length=8000)
    subject: str | None = None
    topic: str | None = None
    difficulty: int = Field(default=2, ge=1, le=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    solution: dict[str, Any] = Field(default_factory=dict)
    explanation: str | None = None


class ExamRequest(BaseModel):
    title: str | None = None
    time_limit_minutes: int = Field(default=90, ge=5, le=600)
    subjects: list[str] | None = None
    total_questions: int | None = Field(default=None, ge=1, le=200)
    blueprint: list[dict[str, Any]] | None = None


class ExamAnswerRequest(BaseModel):
    item_id: int
    answer: str = Field(default="", max_length=20000)
    use_ai: bool = True


class PlanRequest(BaseModel):
    horizon_days: int = Field(default=14, ge=1, le=90)
    exam_date: str | None = None


# -- dashboard ---------------------------------------------------------------

def _require_gradable_solution(payload: ManualQuestionRequest) -> None:
    """Reject a manually created question that could never be graded.

    Without this check a multiple-choice question saved with a wrong key (for
    example ``{"correct": [0]}`` instead of the canonical
    ``{"correct_indices": [0]}``) is stored happily and then fails every answer
    with an empty "Richtig gewesen wäre: ." message. Failing here, with an
    explanation, is far better than storing a broken question.
    """

    if payload.type == "multiple_choice":
        options = payload.payload.get("options") or []
        if not isinstance(options, list) or len(options) < 2:
            raise HTTPException(
                status_code=400,
                detail=("Für eine Auswahlaufgabe müssen mindestens zwei Antworten "
                        "im Feld „options“ stehen."),
            )
        correct = correct_indices(payload.solution)
        if not correct:
            raise HTTPException(
                status_code=400,
                detail=("Für eine Auswahlaufgabe fehlt die richtige Antwort. "
                        "Tragen Sie sie als „correct_index“ (z. B. 0 für die erste "
                        "Antwort) oder als Liste „correct_indices“ (z. B. [0]) ein."),
            )
        if any(index < 0 or index >= len(options) for index in correct):
            raise HTTPException(
                status_code=400,
                detail=(f"Die angegebene richtige Antwort liegt außerhalb der "
                        f"{len(options)} Antworten. Zulässig sind die Zahlen 0 bis "
                        f"{len(options) - 1}."),
            )
    elif payload.type == "numeric":
        solution = payload.solution
        if solution.get("expected") is None and not solution.get("expression"):
            raise HTTPException(
                status_code=400,
                detail=("Für eine Rechenaufgabe fehlt das Ergebnis. Tragen Sie es "
                        "als „expected“ (z. B. 7.62) oder als Formel „expression“ ein."),
            )


@router.get("/dashboard")
async def dashboard(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Everything the dashboard needs, in one request (fewer round trips)."""

    stats = context.learning.stats()
    events = context.repo.event_counts()
    due = context.repo.count_due_cards()
    activity = context.repo.daily_activity(14)
    return {
        "due_now": due,
        "attempts_7d": stats["attempts_7d"],
        "attempts_30d": stats["attempts_30d"],
        "activity": activity,
        "mastery": stats["mastery"][:8],
        "weak_topics": sorted(stats["mastery"], key=lambda m: float(m["mastery"]))[:5],
        "review_forecast": stats["review_forecast"],
        "counts": {
            "questions": context.repo.count_questions(),
            "knowledge": context.repo.count_knowledge(),
            "documents": context.repo.count_documents(),
            "drawings": len(context.repo.list_drawings(limit=500)),
            "exams": len(context.repo.list_exams(limit=500)),
            "due": due,
        },
        "jobs": context.repo.job_counts(),
        "events": events,
        "last_backup": context.repo.last_successful_backup(),
        "last_diagnostics": (context.repo.last_diagnostics() or {}).get("finished_at"),
        "last_repair": context.repo.last_repair(),
        "daily_goal_minutes": context.repo.get_setting("learning.daily_goal_minutes", 30),
        "exam_date": context.repo.get_setting("learning.exam_date", ""),
    }


# -- questions ---------------------------------------------------------------

@router.get("/questions")
async def list_questions(
    context: AppContext = Depends(get_context),
    subject: str | None = None,
    topic: str | None = None,
    type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_solutions: bool = False,
) -> dict[str, Any]:
    questions = context.repo.list_questions(subject=subject, topic=topic, type=type,
                                           limit=limit, offset=offset)
    if include_solutions:
        items = questions
    else:
        items = [_public_question(q) for q in questions]
    return {
        "items": items,
        "total": context.repo.count_questions(subject),
        "subjects": context.repo.question_subjects(),
    }


@router.get("/questions/{question_id}")
async def get_question(question_id: int, context: AppContext = Depends(get_context),
                       include_solutions: bool = False) -> dict[str, Any]:
    question = context.repo.get_question(question_id)
    if question is None:
        raise HTTPException(status_code=404,
                            detail=f"Die Aufgabe {question_id} existiert nicht.")
    return question if include_solutions else _public_question(question)


@router.post("/questions", status_code=status.HTTP_201_CREATED)
async def create_question(payload: ManualQuestionRequest,
                          context: AppContext = Depends(get_context)) -> dict[str, Any]:
    if payload.type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(f"Der Aufgabentyp „{payload.type}“ ist unbekannt. Erlaubt sind: "
                    f"{', '.join(sorted(VALID_TYPES))}."),
        )
    _require_gradable_solution(payload)
    try:
        question_id = context.repo.create_question(
            type=payload.type, prompt=payload.prompt, subject=payload.subject,
            topic=payload.topic, difficulty=payload.difficulty,
            payload=payload.payload, solution=payload.solution,
            explanation=payload.explanation, created_by="user",
        )
        context.learning.ensure_cards([question_id])
        context.repo.audit("question.create", target=str(question_id), actor="user")
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Aufgabe anlegen") from exc
    return context.repo.get_question(question_id)


@router.delete("/questions/{question_id}")
async def delete_question(question_id: int,
                          context: AppContext = Depends(get_context)) -> dict[str, Any]:
    question = context.repo.get_question(question_id)
    if question is None:
        raise HTTPException(status_code=404,
                            detail=f"Die Aufgabe {question_id} existiert nicht.")
    context.repo.delete_question(question_id)
    context.repo.audit("question.delete", target=str(question_id), actor="user")
    return {"deleted": question_id}


@router.post("/questions/generate")
async def generate_questions(payload: GenerateRequest,
                             context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Queue generation as a background job and return the job id.

    Generation is queued rather than run inline because AI generation on a
    Raspberry Pi can take a while and must not block the web server.
    """

    types = payload.types or ["multiple_choice", "freetext", "numeric"]
    unknown = [t for t in types if t not in VALID_TYPES]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unbekannte Aufgabentypen: {', '.join(unknown)}")
    job_id = context.repo.enqueue_job(
        type="generate_questions",
        payload={"subject": payload.subject, "topic": payload.topic,
                 "count": payload.count, "use_ai": payload.use_ai,
                 "types": types},
        priority=4,
    )
    return {
        "job_id": job_id,
        "message": ("Die Aufgabenerzeugung wurde gestartet. Sie können den "
                    "Fortschritt im Bereich „Aufgaben“ verfolgen."),
    }


@router.get("/questions/generate/{job_id}")
async def generation_status(job_id: int,
                            context: AppContext = Depends(get_context)) -> dict[str, Any]:
    job = context.repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Auftrag {job_id} existiert nicht.")
    return job


# -- answering ---------------------------------------------------------------

@router.post("/questions/{question_id}/answer")
async def answer_question(question_id: int, payload: AnswerRequest,
                          context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return context.learning.answer(
            question_id, payload.answer, use_ai=payload.use_ai,
            duration_ms=payload.duration_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Antwort bewerten") from exc


@router.post("/questions/{question_id}/grade")
async def grade_question(question_id: int, payload: AnswerRequest,
                         context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Grade without recording (used for previews)."""

    try:
        return context.learning.grade_only(question_id, payload.answer,
                                          use_ai=payload.use_ai)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Antwort bewerten") from exc


@router.get("/learning/due")
async def due_queue(context: AppContext = Depends(get_context),
                    limit: int = Query(default=20, ge=1, le=100),
                    subject: str | None = None) -> dict[str, Any]:
    items = context.learning.due_queue(limit=limit, subject=subject)
    return {"items": items, "count": len(items),
            "total_due": context.repo.count_due_cards()}


@router.get("/learning/stats")
async def learning_stats(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return context.learning.stats()


@router.get("/learning/plan")
async def get_plan(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    plan = context.learning.active_plan()
    if plan is None:
        return {"plan": None,
                "message": ("Es wurde noch kein Lernplan erstellt. Klicken Sie auf "
                            "„Lernplan erstellen“.")}
    return {"plan": plan}


@router.post("/learning/plan")
async def create_plan(payload: PlanRequest,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    if payload.exam_date:
        context.repo.set_setting("learning.exam_date", payload.exam_date)
    try:
        plan = context.learning.build_study_plan(horizon_days=payload.horizon_days,
                                                 exam_date=payload.exam_date)
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Lernplan erstellen") from exc
    return {"plan": plan}


@router.get("/learning/mastery")
async def mastery(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    rows = context.repo.mastery_overview()
    return {
        "items": rows,
        "weak": [r for r in rows if float(r["mastery"]) < 0.7],
        "strong": [r for r in rows if float(r["mastery"]) >= 0.85],
    }


# -- exams -------------------------------------------------------------------

@router.get("/exams")
async def list_exams(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return {"items": context.exams.list_exams()}


@router.post("/exams", status_code=status.HTTP_201_CREATED)
async def create_exam(payload: ExamRequest,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        exam = context.exams.create_exam(
            title=payload.title, blueprint=payload.blueprint,
            time_limit_minutes=payload.time_limit_minutes,
            subjects=payload.subjects, total_questions=payload.total_questions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Prüfung erstellen") from exc
    return exam


@router.get("/exams/{exam_id}")
async def get_exam(exam_id: int, context: AppContext = Depends(get_context),
                   include_solutions: bool = False) -> dict[str, Any]:
    try:
        return context.exams.get_exam(exam_id, include_solutions=include_solutions)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/exams/{exam_id}/start")
async def start_exam(exam_id: int,
                     context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return context.exams.start_exam(exam_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/exams/answer")
async def answer_exam(payload: ExamAnswerRequest,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return context.exams.submit_item(payload.item_id, payload.answer,
                                         use_ai=payload.use_ai)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Prüfungsantwort bewerten") from exc


@router.post("/exams/{exam_id}/finish")
async def finish_exam(exam_id: int,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return context.exams.finish_exam(exam_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: int,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    exam = context.repo.get_exam(exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail=f"Die Prüfung {exam_id} existiert nicht.")
    context.repo.delete_exam(exam_id)
    context.repo.audit("exam.delete", target=str(exam_id), actor="user")
    return {"deleted": exam_id}


@router.get("/learning/taxonomy")
async def taxonomy(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    from ..documents.taxonomy import SUBJECTS

    return {
        "subjects": sorted(SUBJECTS.keys()),
        "question_types": sorted(VALID_TYPES),
        "difficulty_labels": DIFFICULTY_LABELS,
    }
