"""Security helpers: sessions, CSRF protection and security headers.

Threat model and mitigations:

* **No secret reaches the browser.** The Gemini API key and the supervisor token
  live in the backend only. ``/api/settings`` never returns the raw key, only
  whether one is set.
* **Cross-site request forgery.** Home Assistant Ingress already authenticates
  the user, but a browser could still be tricked into sending a request from
  another origin. Every state-changing request must therefore carry a CSRF token
  that is bound to the session cookie (double-submit pattern, constant-time
  comparison). ``SameSite=Strict`` on the cookie is the second layer.
* **Path traversal.** Uploaded filenames are reduced to a safe basename before
  they are used; documents are addressed by numeric id, never by a client path.
* **SQL injection.** All SQL uses bound parameters (see the repository layer).
* **XSS.** The frontend renders text with ``textContent``/``createElement`` and
  never with ``innerHTML`` for user or AI content.
* **Error output.** Unexpected exceptions are logged with a traceback and
  returned to the client as a short, non-technical German message.

The session is a signed cookie. The signing key is generated once and stored in
the data directory with owner-only permissions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("elektrocoach.security")

SESSION_COOKIE = "elektrocoach_session"
CSRF_HEADER = "x-csrf-token"
SESSION_TTL_SECONDS = 12 * 3600
MAX_BODY_BYTES = 64 * 1024 * 1024  # uploads up to 64 MB

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # Ingress serves the app inside Home Assistant's own page frame, so inline
    # styles and the app's own script are allowed, but nothing external.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    ),
}


class SessionStore:
    """Signed-cookie sessions with a per-session CSRF token."""

    def __init__(self, key_path: Path) -> None:
        self.key_path = Path(key_path)
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        try:
            if self.key_path.is_file():
                data = self.key_path.read_bytes()
                if len(data) >= 32:
                    return data
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_bytes(48)
            self.key_path.write_bytes(key)
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return key
        except OSError as exc:
            # Without a writable data dir we still need a working key.
            logger.warning("could not persist session key (%s); using ephemeral key", exc)
            return secrets.token_bytes(48)

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def encode(self, data: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(
            json.dumps(data, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return f"{body}.{self._sign(body.encode('ascii'))}"

    def decode(self, token: str) -> dict[str, Any] | None:
        if not token or "." not in token:
            return None
        body, _, signature = token.rpartition(".")
        expected = self._sign(body.encode("ascii"))
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            padded = body + "=" * (-len(body) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        created = float(data.get("iat") or 0)
        if created and time.time() - created > SESSION_TTL_SECONDS:
            return None
        return data

    def new_session(self, *, user: str | None = None, ingress: bool = False) -> dict[str, Any]:
        return {
            "sid": secrets.token_urlsafe(16),
            "csrf": secrets.token_urlsafe(32),
            "iat": time.time(),
            "user": user or "Home-Assistant-Benutzer",
            "ingress": ingress,
        }


def get_session(request: Request) -> dict[str, Any] | None:
    store: SessionStore = request.app.state.sessions
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return store.decode(raw)


def ensure_session(request: Request) -> tuple[dict[str, Any], bool]:
    """Return ``(session, is_new)``."""

    existing = get_session(request)
    if existing is not None:
        return existing, False
    store: SessionStore = request.app.state.sessions
    ingress_user = request.headers.get("x-remote-user-id") or request.headers.get(
        "x-remote-user-display-name"
    )
    ingress = bool(request.headers.get("x-ingress-path")
                   or request.headers.get("x-remote-user-id"))
    return store.new_session(user=ingress_user, ingress=ingress), True


def verify_csrf(request: Request, session: dict[str, Any]) -> None:
    """Raise 403 when the CSRF token is missing or wrong."""

    provided = request.headers.get(CSRF_HEADER) or request.headers.get(
        CSRF_HEADER.title()
    )
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Der Sicherheitsschlüssel (CSRF-Token) fehlt. Laden Sie die "
                    "Seite neu und versuchen Sie es erneut."),
        )
    expected = str(session.get("csrf") or "")
    if not expected or not hmac.compare_digest(str(provided), expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Der Sicherheitsschlüssel (CSRF-Token) ist ungültig. Laden Sie "
                    "die Seite neu und versuchen Sie es erneut."),
        )


class SecurityMiddleware(BaseHTTPMiddleware):
    """Adds security headers and enforces CSRF on mutating API requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Body size guard before anything is read into memory.
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": (
                        f"Die Datei ist zu groß. Maximal erlaubt sind "
                        f"{MAX_BODY_BYTES // 1024 // 1024} MB pro Upload."
                    )},
                )

        path = request.url.path
        if request.method in MUTATING_METHODS and path.startswith("/api/"):
            session = get_session(request)
            if session is None:
                # Create one so the client can retry with a valid token rather
                # than being permanently locked out.
                return JSONResponse(
                    status_code=403,
                    content={"detail": (
                        "Ihre Sitzung ist abgelaufen. Bitte laden Sie die Seite neu."
                    )},
                )
            try:
                verify_csrf(request, session)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code,
                                    content={"detail": exc.detail})

        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unbekannt"


def parse_cookie_header(header: str) -> dict[str, str]:
    """Small helper used by the tests."""

    cookie = SimpleCookie()
    cookie.load(header or "")
    return {key: morsel.value for key, morsel in cookie.items()}
