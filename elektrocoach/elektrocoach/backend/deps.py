"""Shared FastAPI dependencies and error translation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status

from .context import AppContext

logger = logging.getLogger("elektrocoach.api")


def get_context(request: Request) -> AppContext:
    context = getattr(request.app.state, "context", None)
    if context is None:  # pragma: no cover - only during a broken startup
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("ElektroCoach ist noch nicht vollständig gestartet. Bitte "
                    "warten Sie einen Moment und laden Sie die Seite neu."),
        )
    return context


def translate_error(exc: Exception, *, context: str | None = None) -> HTTPException:
    """Map an internal exception to a user-readable HTTP error.

    The message the user sees is plain German and actionable. Technical detail is
    written to the log, never returned to the browser.
    """

    from ..ai.base import AIError, AIQuotaExceeded, AIResponseInvalid, AIUnavailable

    where = f" ({context})" if context else ""
    if isinstance(exc, AIQuotaExceeded):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                             detail=str(exc))
    if isinstance(exc, AIUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=str(exc))
    if isinstance(exc, AIResponseInvalid):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                             detail=str(exc))
    if isinstance(exc, AIError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Diese Aktion ist nicht erlaubt. Prüfen Sie die Einstellungen "
                    "oder wenden Sie sich an den Support."),
        )
    logger.exception("unhandled error%s", where)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=("Es ist ein unerwarteter Fehler aufgetreten. Öffnen Sie den Bereich "
                "„Fehlerdiagnose“; dort steht eine genaue Anleitung, was zu tun ist."),
    )


def require_confirmation(confirmed: Any) -> None:
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Diese Aktion verändert Daten und benötigt Ihre ausdrückliche "
                    "Bestätigung (Feld „confirmed“)."),
        )
