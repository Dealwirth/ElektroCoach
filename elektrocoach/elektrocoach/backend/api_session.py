"""Session, CSRF and app metadata endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .deps import get_context
from .security import SESSION_COOKIE, ensure_session, get_session

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session")
async def read_session(request: Request, response: Response) -> dict[str, Any]:
    """Return the current session, creating one on first visit.

    The response sets the signed session cookie and exposes the CSRF token that
    the frontend must send in the ``X-CSRF-Token`` header for every mutating
    request. The token is not a secret on its own; it is bound to the cookie.
    """

    context = get_context(request)
    session, is_new = ensure_session(request)
    if is_new:
        request.app.state.sessions  # ensure store exists
        store = request.app.state.sessions
        cookie_value = store.encode(session)
        secure = request.url.scheme == "https"
        response.set_cookie(
            SESSION_COOKIE, cookie_value, httponly=True, samesite="strict",
            secure=secure, path="/", max_age=12 * 3600,
        )
    ingress_path = request.headers.get("x-ingress-path", "")
    return {
        "csrf_token": session["csrf"],
        "user": session.get("user"),
        "ingress": bool(session.get("ingress")),
        "ingress_path": ingress_path,
        "new_session": is_new,
        "app": {
            "version": context.version,
            "started_at": context.started_at,
        },
    }


@router.get("/meta")
async def read_meta(request: Request) -> dict[str, Any]:
    """Static metadata the frontend needs on load (no secrets)."""

    context = get_context(request)
    return {
        "version": context.version,
        "schema_version": context.db.schema_version,
        "fts5": context.db.fts5_available,
        "grid_size": context.grid_size,
        "started_at": context.started_at,
        "features": {
            "ollama_enabled": context.opts.ollama_enabled,
            "gemini_configured": context.opts.gemini_configured,
            "auto_repair": context.opts.auto_repair_enabled,
            "notifications": context.opts.ha_notifications_enabled,
            "backup": context.opts.backup_enabled,
        },
    }
