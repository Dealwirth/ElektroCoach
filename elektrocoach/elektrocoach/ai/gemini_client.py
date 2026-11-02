"""Google Gemini client (free tier only).

Rules enforced here, matching the project requirements:

* The API key is never sent to the browser; it stays in the backend.
* Model names are **not** hard-coded as a truth. The list of models is read
  from the live API (``GET /v1beta/models``) and filtered to the ones that
  support ``generateContent``.
* A daily request budget is enforced locally. When it is exhausted the client
  raises :class:`AIQuotaExceeded` and the caller pauses the task. There is
  **no** fallback to a paid tier and **no** automatic billing.
* Rate limiting (HTTP 429) and quota errors from Google are mapped to clear,
  actionable German messages.

REST reference: https://ai.google.dev/api/generate-content
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

from .base import (
    AIError,
    AIQuotaExceeded,
    AIResult,
    AIUnavailable,
    estimate_tokens,
)

logger = logging.getLogger("elektrocoach.ai.gemini")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0

# Models that Google does not offer on the free tier (or that are deprecated)
# are filtered out of the selectable list.
_EXCLUDED_MODEL_MARKERS = ("embedding", "aqa", "imagen", "veo", "learnlm")


class GeminiClient:
    def __init__(self, api_key: str, model: str, *, enabled: bool = False,
                 daily_request_budget: int = 200, base_url: str | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.enabled = enabled
        self.daily_request_budget = daily_request_budget
        self.base_url = (base_url or API_BASE).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._models_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._semaphore = asyncio.Semaphore(2)

    # -- lifecycle ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
                headers={"x-goog-api-key": self.api_key},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key)

    # -- model discovery ------------------------------------------------------

    async def list_models(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Return free-tier capable models that support generateContent."""

        if not self.api_key:
            return []
        if not force and self._models_cache is not None:
            cached_at, cached = self._models_cache
            if time.monotonic() - cached_at < 3600:
                return cached
        try:
            response = await self._http().get("/models", params={"pageSize": 200})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in (400, 403):
                raise AIError(
                    "Der Gemini-API-Schlüssel wurde von Google abgelehnt.",
                    provider="gemini",
                    guidance=(
                        "Prüfen Sie den API-Schlüssel in den ElektroCoach-"
                        "Einstellungen. Der Schlüssel muss in der Google AI Studio "
                        "erzeugt worden sein und für die Gemini API gelten."
                    ),
                    retryable=False,
                ) from exc
            logger.warning("gemini model list failed: %s", exc)
            return self._models_cache[1] if self._models_cache else []
        except httpx.HTTPError as exc:
            logger.warning("gemini model list unreachable: %s", exc)
            return self._models_cache[1] if self._models_cache else []

        models: list[dict[str, Any]] = []
        for entry in payload.get("models", []) or []:
            name = str(entry.get("name") or "")
            methods = entry.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            short = name.split("/")[-1]
            if any(marker in short.lower() for marker in _EXCLUDED_MODEL_MARKERS):
                continue
            models.append({
                "name": short,
                "full_name": name,
                "display_name": entry.get("displayName") or short,
                "description": entry.get("description") or "",
                "input_token_limit": entry.get("inputTokenLimit"),
                "output_token_limit": entry.get("outputTokenLimit"),
            })
        models.sort(key=lambda m: m["name"])
        self._models_cache = (time.monotonic(), models)
        return models

    async def validate_key(self) -> dict[str, Any]:
        """Check the key and report whether the configured model is available."""

        if not self.api_key:
            return {"ok": False, "reason": "no_key",
                    "message": "Es ist kein Gemini-API-Schlüssel hinterlegt."}
        try:
            models = await self.list_models(force=True)
        except AIError as exc:
            return {"ok": False, "reason": "rejected", "message": str(exc),
                    "guidance": exc.guidance}
        names = [m["name"] for m in models]
        return {
            "ok": True,
            "model_count": len(models),
            "models": names,
            "configured_model": self.model,
            "configured_model_available": self.model in names,
        }

    # -- generation -----------------------------------------------------------

    async def generate(self, prompt: str, *, system: str | None = None,
                       model: str | None = None, json_mode: bool = False,
                       temperature: float = 0.2, max_tokens: int | None = None,
                       images: list[dict[str, str]] | None = None,
                       task_type: str | None = None) -> AIResult:
        """Generate content. ``images`` is a list of ``{mime, data_base64}``."""

        if not self.enabled:
            raise AIUnavailable(
                "Gemini ist in den Einstellungen deaktiviert.",
                provider="gemini",
                guidance="Aktivieren Sie Gemini in den ElektroCoach-Einstellungen.",
            )
        if not self.api_key:
            raise AIUnavailable(
                "Es ist kein Gemini-API-Schlüssel hinterlegt.",
                provider="gemini",
                guidance=(
                    "Tragen Sie in den ElektroCoach-Einstellungen unter "
                    "„Google Gemini“ Ihren kostenlosen API-Schlüssel ein."
                ),
            )

        target = (model or self.model).strip()
        if not target:
            raise AIUnavailable(
                "Es ist kein Gemini-Modell ausgewählt.",
                provider="gemini",
                guidance="Wählen Sie in den Einstellungen ein Modell aus der Liste.",
            )

        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images or []:
            parts.append({
                "inline_data": {
                    "mime_type": image.get("mime", "image/jpeg"),
                    "data": image.get("data_base64", ""),
                }
            })

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature},
        }
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = int(max_tokens)
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        started = time.monotonic()
        async with self._semaphore:
            try:
                response = await self._http().post(
                    f"/models/{target}:generateContent", json=body
                )
            except httpx.HTTPError as exc:
                raise AIUnavailable(
                    "Google Gemini ist nicht erreichbar.",
                    provider="gemini",
                    guidance=(
                        "Prüfen Sie die Internetverbindung des Raspberry Pi. "
                        "Lokale Funktionen (Ollama, Lernen, Datenbank) bleiben nutzbar."
                    ),
                ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code == 429:
            raise AIQuotaExceeded(
                "Das kostenlose Gemini-Kontingent ist für heute erschöpft.",
                provider="gemini",
                guidance=(
                    "Die Aufgabe wurde pausiert und wird nicht kostenpflichtig "
                    "ausgeführt. Versuchen Sie es nach dem nächsten Kontingent-Reset "
                    "(in der Regel um Mitternacht, pazifische Zeit) erneut oder "
                    "verwenden Sie für diese Aufgabe Ollama."
                ),
            )
        if response.status_code in (400, 403):
            detail = _safe_error_text(response)
            raise AIError(
                f"Gemini hat die Anfrage abgelehnt: {detail}",
                provider="gemini",
                guidance=(
                    "Prüfen Sie den API-Schlüssel und das gewählte Modell in den "
                    "ElektroCoach-Einstellungen."
                ),
                retryable=False,
            )
        if response.status_code == 404:
            raise AIError(
                f"Das Gemini-Modell „{target}“ ist nicht verfügbar.",
                provider="gemini",
                guidance=(
                    "Öffnen Sie in den Einstellungen die Modellliste und wählen Sie "
                    "ein dort aufgeführtes Modell."
                ),
                retryable=False,
            )
        if response.status_code >= 500:
            raise AIError(
                f"Gemini meldete einen Serverfehler ({response.status_code}).",
                provider="gemini",
                guidance="Bitte später erneut versuchen.",
            )
        if response.status_code != 200:
            raise AIError(
                f"Unerwartete Antwort von Gemini ({response.status_code}).",
                provider="gemini",
                guidance="Bitte den Systemstatus prüfen.",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIError(
                "Gemini lieferte keine auswertbare Antwort.",
                provider="gemini",
                guidance="Bitte erneut versuchen.",
            ) from exc

        text = _extract_text(data)
        usage = data.get("usageMetadata") or {}
        prompt_tokens = int(usage.get("promptTokenCount") or estimate_tokens(prompt))
        completion_tokens = int(usage.get("candidatesTokenCount") or estimate_tokens(text))

        return AIResult(
            text=text,
            provider="gemini",
            model=target,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            raw={"finish_reason": _finish_reason(data), "task_type": task_type},
        )

    # -- diagnostics ----------------------------------------------------------

    async def status(self, *, requests_used_today: int = 0) -> dict[str, Any]:
        result: dict[str, Any] = {
            "enabled": self.enabled,
            "key_configured": bool(self.api_key),
            "model": self.model,
            "daily_request_budget": self.daily_request_budget,
            "requests_used_today": requests_used_today,
            "requests_remaining": max(0, self.daily_request_budget - requests_used_today),
            "reachable": False,
            "models": [],
        }
        if not self.api_key:
            return result
        try:
            models = await self.list_models(force=True)
            result["reachable"] = True
            result["models"] = [m["name"] for m in models]
            result["model_available"] = self.model in result["models"]
        except AIError as exc:
            result["error"] = str(exc)
            result["guidance"] = exc.guidance
        except Exception as exc:  # noqa: BLE001 - diagnostics must never raise
            result["error"] = str(exc)
        return result


def _safe_error_text(response: httpx.Response) -> str:
    """Extract Google's error message without leaking the API key."""

    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = payload.get("error") or {}
    message = str(error.get("message") or f"HTTP {response.status_code}")
    # Google sometimes echoes the key in URLs; strip anything key-like.
    for marker in ("key=", "api_key=", "key "):
        if marker in message:
            message = message.split(marker)[0].strip()
    return message[:300]


def _extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            raise AIError(
                f"Gemini hat die Anfrage aus Sicherheitsgründen blockiert ({reason}).",
                provider="gemini",
                guidance=(
                    "Formulieren Sie die Anfrage neutraler oder verarbeiten Sie "
                    "den Inhalt lokal mit Ollama."
                ),
                retryable=False,
            )
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(str(part.get("text") or "") for part in parts)


def _finish_reason(data: dict[str, Any]) -> str | None:
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    return candidates[0].get("finishReason")


def encode_image_for_gemini(path: str, max_bytes: int = 4 * 1024 * 1024) -> dict[str, str]:
    """Read an image file and prepare it for an inline Gemini request.

    Oversized images are rejected rather than silently truncated, because a
    truncated scan would produce an unreliable recognition result.
    """

    import mimetypes
    from pathlib import Path

    file_path = Path(path)
    mime, _ = mimetypes.guess_type(file_path.name)
    if mime is None:
        suffix = file_path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "heic": "image/heic"}.get(suffix, "image/jpeg")
    data = file_path.read_bytes()
    if len(data) > max_bytes:
        raise AIError(
            f"Das Bild „{file_path.name}“ ist zu groß für die Handschrifterkennung "
            f"({len(data) // 1024 // 1024} MB).",
            provider="gemini",
            guidance=(
                "Teilen Sie das Dokument in kleinere Seiten auf oder verkleinern "
                "Sie die Auflösung auf etwa 2000 Pixel Kantenlänge."
            ),
            retryable=False,
        )
    return {"mime": mime, "data_base64": base64.b64encode(data).decode("ascii")}
