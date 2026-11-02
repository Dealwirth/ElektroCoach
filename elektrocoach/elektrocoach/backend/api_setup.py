"""Setup wizard endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..backend.setup_wizard import STEP_DEFINITIONS, SetupWizard

logger = logging.getLogger("elektrocoach.api.setup")

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _wizard(context: AppContext) -> SetupWizard:
    return SetupWizard(context)


@router.get("")
async def state(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    wizard = _wizard(context)
    data = wizard.state()
    data["definitions"] = [
        {"key": d.key, "title": d.title, "description": d.description,
         "why": d.why, "manual": d.manual, "required": d.required}
        for d in STEP_DEFINITIONS
    ]
    return data


@router.post("/steps/{key}")
async def run_step(key: str, context: AppContext = Depends(get_context)) -> dict[str, Any]:
    wizard = _wizard(context)
    try:
        result = await wizard.run_step(key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Einrichtungsschritt") from exc
    return {"step": result, "state": wizard.state()}


@router.post("/run")
async def run_all(context: AppContext = Depends(get_context),
                  only_pending: bool = True) -> dict[str, Any]:
    wizard = _wizard(context)
    try:
        state = await wizard.run_all(only_pending=only_pending)
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Einrichtungsassistent") from exc
    return state


@router.post("/complete")
async def complete(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    wizard = _wizard(context)
    state = wizard.state()
    if not state["can_complete"]:
        raise HTTPException(
            status_code=409,
            detail=("Die Einrichtung kann noch nicht abgeschlossen werden. "
                    "Folgende Punkte sind offen: " + ", ".join(state["blocking"])
                    + ". Führen Sie diese Schritte zuerst aus."),
        )
    return wizard.finalise()


@router.post("/reset")
async def reset(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return _wizard(context).reset()


@router.post("/models/pull")
async def pull_model(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Queue the download of the configured Ollama model."""

    model = context.opts.ollama_model
    job_id = context.repo.enqueue_job(
        type="download_model", payload={"model": model}, priority=2, max_attempts=1,
    )
    return {
        "job_id": job_id,
        "model": model,
        "message": (f"Das Modell „{model}“ wird geladen. Der Fortschritt erscheint "
                    "unter „Systemstatus → Aufgaben“. Auf einem Raspberry Pi 4 "
                    "dauert der Download mehrere Minuten."),
    }
