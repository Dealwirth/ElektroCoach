"""AI assistant endpoints: ask, model management, status and usage."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..ai.base import AIError, reduce_text

logger = logging.getLogger("elektrocoach.api.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

MAX_CONTEXT_ITEMS = 8
MAX_CONTEXT_CHARS = 4000

ASK_SYSTEM_PROMPT = """Du bist ein fachlicher Assistent für einen Auszubildenden \
zum Elektroniker für Energie- und Gebäudetechnik. Antworte auf Deutsch, fachlich \
korrekt, strukturiert und mit den üblichen Fachbegriffen und Einheiten.

Wenn dir die bereitgestellten Auszüge aus den eigenen Notizen nicht ausreichen, \
sage das offen und kennzeichne allgemeines Fachwissen als solches. Erfinde keine \
Quellenangaben."""


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    use_notes: bool = True
    prefer: str = Field(default="auto", pattern="^(auto|ollama|gemini)$")


class PullModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=120)


@router.post("/ask")
async def ask(payload: AskRequest,
              context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Answer a technical question, using reduced note excerpts as context."""

    context_items: list[dict[str, Any]] = []
    context_text = ""
    if payload.use_notes:
        context_items = context.repo.knowledge_snippets(
            payload.question, limit=MAX_CONTEXT_ITEMS,
            max_chars=MAX_CONTEXT_CHARS // MAX_CONTEXT_ITEMS,
        )
        if context_items:
            blocks = []
            used = 0
            for item in context_items:
                block = (
                    f"[{item.get('source') or 'Notiz'}, Seite {item.get('page') or '?'}] "
                    f"{item.get('title')}: {item.get('excerpt')}"
                )
                if used + len(block) > MAX_CONTEXT_CHARS:
                    break
                blocks.append(block)
                used += len(block)
            context_text = "\n\n".join(blocks)

    prompt = _build_prompt(payload.question, context_text)
    try:
        result = await context.dispatcher.run(
            "hard_qa" if payload.prefer != "ollama" else "summarize",
            prompt, system=ASK_SYSTEM_PROMPT, prefer=payload.prefer,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="KI-Anfrage") from exc

    return {
        "answer": result.text,
        "provider": result.provider,
        "model": result.model,
        "cached": result.cached,
        "tokens": {"prompt": result.prompt_tokens,
                   "completion": result.completion_tokens,
                   "total": result.total_tokens},
        "latency_ms": result.latency_ms,
        "sources": [
            {"id": item["id"], "title": item.get("title"),
             "source": item.get("source"), "page": item.get("page"),
             "subject": item.get("subject")}
            for item in context_items
        ],
        "note": ("Für diese Anfrage wurden nur die aufgeführten Ausschnitte aus "
                 "Ihren Notizen verarbeitet, nicht die gesamte Wissensdatenbank."
                 if context_items else
                 "Es waren keine passenden Ausschnitte in Ihren Notizen vorhanden; "
                 "die Antwort beruht auf allgemeinem Fachwissen."),
    }


def _build_prompt(question: str, context_text: str) -> str:
    if not context_text:
        return (
            f"Frage des Auszubildenden:\n{question}\n\n"
            "In den importierten Notizen wurden keine passenden Ausschnitte "
            "gefunden. Beantworte die Frage mit allgemeinem Fachwissen und weise "
            "darauf hin, dass sie nicht aus den eigenen Unterlagen stammt."
        )
    return (
        "Auszüge aus den eigenen Notizen des Auszubildenden:\n"
        f"---\n{context_text}\n---\n\n"
        f"Frage:\n{question}\n\n"
        "Beantworte die Frage. Beziehe dich, wo möglich, auf die Auszüge und "
        "nenne Quelle und Seite. Kennzeichne Aussagen, die nicht aus den Auszügen "
        "stammen, ausdrücklich als allgemeines Fachwissen."
    )


@router.get("/status")
async def ai_status(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    try:
        return await context.dispatcher.status()
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="KI-Status") from exc


@router.get("/decisions")
async def ai_decisions(context: AppContext = Depends(get_context),
                       limit: int = 20) -> dict[str, Any]:
    """Show why each task went to which provider (transparency)."""

    return {
        "items": context.dispatcher.last_decisions(limit),
        "explanation": (
            "Jede Zeile zeigt, welche KI für eine Aufgabe gewählt wurde und "
            "warum. Einfache Aufgaben bleiben lokal (Ollama) und übertragen keine "
            "Daten nach außen."
        ),
    }


@router.get("/usage")
async def ai_usage(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    budget = context.repo.ai_budget_today("gemini")
    return {
        "summary_7d": context.repo.ai_usage_summary(7),
        "summary_30d": context.repo.ai_usage_summary(30),
        "gemini_today": {
            **budget,
            "budget": context.opts.gemini_daily_request_budget,
            "remaining": max(0, context.opts.gemini_daily_request_budget
                             - budget["requests_used"]),
        },
        "cache": context.repo.cache_stats(),
        "note": ("Kostenpflichtige Anfragen sind nicht möglich. Ist das kostenlose "
                 "Gemini-Kontingent erschöpft, wird die Aufgabe pausiert."),
    }


@router.get("/models")
async def list_models(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Available local and cloud models (live from the providers)."""

    ollama_models: list[dict[str, Any]] = []
    gemini_models: list[dict[str, Any]] = []
    ollama_error = None
    gemini_error = None

    try:
        ollama_models = [m.as_dict() for m in await context.ollama.list_models()]
    except Exception as exc:  # noqa: BLE001
        ollama_error = str(exc)

    if context.gemini.api_key:
        try:
            gemini_models = await context.gemini.list_models(force=True)
        except AIError as exc:
            gemini_error = str(exc)
        except Exception as exc:  # noqa: BLE001
            gemini_error = str(exc)

    return {
        "ollama": {"models": ollama_models, "error": ollama_error,
                   "configured": context.opts.ollama_model,
                   "url": context.opts.ollama_url},
        "gemini": {"models": gemini_models, "error": gemini_error,
                   "configured": context.opts.gemini_model,
                   "enabled": context.opts.gemini_configured},
    }


@router.post("/models/pull", status_code=status.HTTP_202_ACCEPTED)
async def pull_model(payload: PullModelRequest,
                     context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Queue a model download and report progress through the job record."""

    job_id = context.repo.enqueue_job(
        type="download_model", payload={"model": payload.model}, priority=7,
        max_attempts=1,
    )
    return {
        "job_id": job_id,
        "message": (f"Das Modell „{payload.model}“ wird im Hintergrund geladen. "
                    "Der Fortschritt erscheint im Bereich „Systemstatus“. Der "
                    "Download ist je nach Größe mehrere Minuten lang."),
    }


@router.post("/models/unload")
async def unload_model(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    ok = await context.ollama.unload()
    return {
        "unloaded": ok,
        "message": ("Das lokale Modell wurde entladen und der Arbeitsspeicher "
                    "freigegeben." if ok else
                    "Das Modell konnte nicht entladen werden. Prüfen Sie, ob Ollama "
                    "erreichbar ist."),
    }
