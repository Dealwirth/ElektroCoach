"""KI-Diagnose, Tutor-Chat und Home-Assistant-Endpunkte."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import (
    ai_router,
    ai_usage,
    gemini,
    ha_integration,
    learning,
    ollama,
    ollama_addon,
)
from ..workers import refine_worker

log = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


@router.get("/ai/status")
async def ai_status() -> dict[str, Any]:
    return await ai_router.status()


@router.get("/ai/usage")
async def usage() -> dict[str, Any]:
    return {
        "today": ai_usage.usage_today(),
        "gemini_quota": ai_usage.quota_state("gemini"),
        "ollama_quota": ai_usage.quota_state("ollama"),
        "recent_errors": ai_usage.recent_errors(10),
        "limits": ai_usage.DAILY_LIMITS,
    }


@router.get("/ai/ollama/models")
async def ollama_models() -> dict[str, Any]:
    return {
        "health": await ollama.health(),
        "recommended": ollama.RECOMMENDED_MODELS,
    }


@router.get("/ai/gemini/models")
async def gemini_models() -> dict[str, Any]:
    return await gemini.list_models()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    topic_id: str | None = None
    use_library: bool = True
    history: list[dict[str, str]] = Field(default_factory=list)


@router.post("/ai/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    """Fachlicher Tutor-Chat. Nutzt bevorzugt die eigenen Aufzeichnungen."""
    context_blocks: list[dict[str, Any]] = []
    if payload.use_library:
        from .. import db

        hits = db.search_chunks(payload.message, limit=5)
        for hit in hits:
            context_blocks.append({
                "filename": hit["filename"],
                "page": hit["page_number"],
                "text": hit["text"][:1200],
            })

    material = "\n\n".join(
        f"[{c['filename']} S.{c['page']}]\n{c['text']}" for c in context_blocks
    )
    prompt = payload.message
    if material:
        prompt = (
            "Beantworte die Frage fachlich korrekt. Nutze, wenn passend, das folgende "
            "Material aus den eigenen Aufzeichnungen und nenne die Fundstellen.\n\n"
            f"MATERIAL:\n{material}\n\nFRAGE:\n{payload.message}"
        )

    result = await ai_router.complete(
        prompt, system=learning.SYSTEM_TUTOR, task="chat",
        temperature=0.3, max_output_tokens=2048,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error"),
            "hint": (
                "Weder Ollama noch Gemini sind erreichbar. Die Wissenssuche und "
                "alle Lernfunktionen ohne KI bleiben verfuegbar."
            ),
            "sources": context_blocks,
        }
    return {
        "ok": True,
        "answer": result.get("text"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "fallback_used": result.get("fallback_used", False),
        "external": result.get("provider") == "gemini",
        "sources": context_blocks,
    }


class ExplainRequest(BaseModel):
    topic_id: str | None = None
    question: str = Field(min_length=3, max_length=4000)
    level: str = "pruefung"


@router.post("/ai/explain")
async def explain(payload: ExplainRequest) -> dict[str, Any]:
    level_hint = {
        "einfach": "Erklaere es einfach und anschaulich, ohne Fachjargon.",
        "pruefung": "Erklaere es auf Pruefungsniveau mit Fachbegriffen und Formeln.",
        "tief": "Erklaere es ausfuehrlich mit Hintergruenden, Normbezug und Rechenbeispiel.",
    }.get(payload.level, "Erklaere es auf Pruefungsniveau.")

    material = ""
    if payload.topic_id:
        from .. import db

        rows = db.query(
            "SELECT c.text, c.page_number, d.filename FROM topic_chunks tc "
            "JOIN chunks c ON c.id = tc.chunk_id JOIN documents d ON d.id = c.document_id "
            "WHERE tc.topic_id = ? ORDER BY tc.weight DESC LIMIT 4",
            (payload.topic_id,),
        )
        material = "\n\n".join(
            f"[{r['filename']} S.{r['page_number']}]\n{r['text'][:1000]}" for r in rows
        )

    prompt = f"{level_hint}\n\nThema/Frage: {payload.question}"
    if material:
        prompt += f"\n\nEigene Aufzeichnungen:\n{material}"

    result = await ai_router.complete(
        prompt, system=learning.SYSTEM_TUTOR, task="complex_explanation",
        temperature=0.3, max_output_tokens=2048,
    )
    return {
        "ok": bool(result.get("ok")),
        "answer": result.get("text"),
        "error": result.get("error"),
        "provider": result.get("provider"),
    }


# ---------------------------------------------------------------------------
# Home Assistant
# ---------------------------------------------------------------------------
@router.get("/ha/status")
async def ha_status() -> dict[str, Any]:
    return {
        **ha_integration.status(),
        "sensors": ha_integration.collect_state(),
    }


@router.post("/ha/publish")
async def ha_publish() -> dict[str, Any]:
    ha_integration.publish_discovery()
    state = ha_integration.publish_state()
    return {"ok": True, "state": state}


class NotifyRequest(BaseModel):
    title: str = "ElektroCoach"
    message: str
    service: str | None = None


@router.post("/ha/notify")
async def ha_notify(payload: NotifyRequest) -> dict[str, Any]:
    result = await ha_integration.notify(payload.title, payload.message, payload.service)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    return result


@router.post("/ha/notify/due")
async def ha_notify_due() -> dict[str, Any]:
    result = await ha_integration.notify_due_reviews()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    return result


# ---------------------------------------------------------------------------
# Ollama-Add-on (lokale, kostenlose KI)
# ---------------------------------------------------------------------------
@router.get("/ai/ollama/addon")
async def ollama_addon_status() -> dict[str, Any]:
    """Zustand des Ollama-Add-ons im Supervisor."""
    return await ollama_addon.status()


@router.post("/ai/ollama/addon/ensure")
async def ollama_addon_ensure() -> dict[str, Any]:
    """Installiert und startet das Ollama-Add-on und hinterlegt die Adresse."""
    result = await ollama_addon.ensure_running()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    return result


class PullRequest(BaseModel):
    model: str = Field(min_length=1, max_length=120)


@router.post("/ai/ollama/pull")
async def ollama_pull(payload: PullRequest) -> dict[str, Any]:
    """Laedt ein Modell in das Ollama-Add-on (kostenlos, lokal)."""
    result = await ollama_addon.pull_model(payload.model)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    return result


@router.get("/ai/ollama/installed")
async def ollama_installed() -> dict[str, Any]:
    return await ollama_addon.installed_models()


# ---------------------------------------------------------------------------
# KI-Nachbearbeitung erkannter Texte
# ---------------------------------------------------------------------------
class RefineRequest(BaseModel):
    document_id: str | None = None
    scope: str = "review"


@router.post("/ai/refine")
async def start_refine(payload: RefineRequest) -> dict[str, Any]:
    """Startet die KI-Nachbearbeitung (Ollama, bei Bedarf Gemini).

    scope "document": alle Seiten eines Dokuments.
    scope "review":   alle zur Pruefung markierten Seiten.
    """
    scope = payload.scope if payload.scope in {"document", "review"} else "review"
    if scope == "document" and not payload.document_id:
        raise HTTPException(status_code=400, detail="document_id fehlt")
    if scope == "review" and payload.document_id:
        scope = "document"
    status = await ai_router.status()
    if not status.get("any_available"):
        raise HTTPException(
            status_code=400,
            detail="Keine KI erreichbar. Bitte Ollama einrichten oder einen Gemini-Schluessel hinterlegen.",
        )
    job_id = refine_worker.create_job(payload.document_id, scope)
    refine_worker.enqueue(job_id)
    return {"ok": True, "job_id": job_id, "scope": scope}


@router.get("/ai/refine/jobs")
async def list_refine_jobs(limit: int = 10) -> dict[str, Any]:
    from .. import db

    rows = db.query(
        "SELECT id, document_id, scope, status, total_pages, processed_pages, current_page, "
        "message, created_at, updated_at FROM refine_jobs ORDER BY created_at DESC LIMIT ?",
        (max(1, min(50, limit)),),
    )
    return {"items": [dict(r) for r in rows], "queue": refine_worker.queue_length()}


@router.get("/ai/refine/jobs/{job_id}")
async def get_refine_job(job_id: str) -> dict[str, Any]:
    data = refine_worker.job(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    total = data.get("total_pages") or 0
    data["progress_percent"] = (
        round(100 * (data.get("processed_pages") or 0) / total, 1) if total else 0.0
    )
    return data


@router.post("/ai/refine/jobs/{job_id}/cancel")
async def cancel_refine_job(job_id: str) -> dict[str, Any]:
    if not refine_worker.request_cancel(job_id):
        raise HTTPException(status_code=400, detail="Auftrag kann nicht abgebrochen werden")
    return {"ok": True, "message": "Abbruch angefordert"}


class RefinePageRequest(BaseModel):
    page_id: str = Field(min_length=1, max_length=64)


@router.post("/ai/refine/page")
async def refine_single_page(payload: RefinePageRequest) -> dict[str, Any]:
    """Bearbeitet eine einzelne Seite sofort nach (fuer die Pruefansicht)."""
    from .. import db
    from ..services import refine

    row = db.query_one(
        "SELECT id, document_id, page_number, text, image_path, needs_review "
        "FROM pages WHERE id = ?",
        (payload.page_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Seite nicht gefunden")
    result = await refine.refine_page(dict(row))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Fehler"))
    refine.apply_result(result)
    return result
