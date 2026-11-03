"""Gemini-Client (Google AI Studio, kostenloses Kontingent).

Wichtige Eigenschaften:
  * Ausschliesslich kostenloses Kontingent: es wird nur der API-Schluessel aus
    Google AI Studio verwendet. Es wird KEINE Abrechnung aktiviert.
  * Der Schluessel bleibt serverseitig und wird nie an das Frontend gesendet.
  * Bei HTTP 429 (RESOURCE_EXHAUSTED) wird das Tageskontingent als erschoepft
    markiert und die Anfrage geordnet abgelehnt, damit die App auf Ollama
    ausweichen kann.
  * Das aktive Modell wird beim Start gegen die Model-Liste geprueft, damit
    umbenannte oder eingestellte Modelle automatisch erkannt werden.

REST-Schnittstelle: https://generativelanguage.googleapis.com/v1beta
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..config import settings
from . import ai_usage

log = logging.getLogger(__name__)

PROVIDER = "gemini"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Modelle, die im kostenlosen Kontingent nutzbar sind (Praefix-Reihenfolge =
# Fallback-Reihenfolge). Pro-Modelle sind seit April 2026 kostenpflichtig.
FREE_TIER_PREFERENCE = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
]

_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)


def _timeout() -> httpx.Timeout:
    """Zeitlimit aus den Einstellungen. Schuetzt vor blockierten Anfragen."""
    total = max(5, settings.get_int("ai_timeout_seconds", 60))
    return httpx.Timeout(connect=min(10.0, total), read=float(total), write=60.0, pool=10.0)


_last_429: float = 0.0


def api_key() -> str:
    return str(settings.get("gemini_api_key", "") or "")


def text_model() -> str:
    return str(settings.get("gemini_text_model", "gemini-2.5-flash"))


def vision_model() -> str:
    return str(settings.get("gemini_vision_model", "gemini-2.5-flash"))


def is_configured() -> bool:
    return bool(api_key())


def _url(model: str) -> str:
    return f"{API_BASE}/models/{model}:generateContent"


def _headers() -> dict[str, str]:
    return {
        "x-goog-api-key": api_key(),
        "Content-Type": "application/json",
    }


async def list_models() -> dict[str, Any]:
    """Listet verfuegbare Modelle (fuer die Einrichtung und Diagnose)."""
    if not is_configured():
        return {"available": False, "reason": "kein API-Schluessel gesetzt", "models": []}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(f"{API_BASE}/models", headers=_headers(), params={"pageSize": 100})
            resp.raise_for_status()
            data = resp.json()
        names = [
            m["name"].split("/", 1)[-1]
            for m in data.get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
        free = [m for m in FREE_TIER_PREFERENCE if m in names]
        return {"available": True, "models": names, "free_tier_candidates": free}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc), "models": []}


async def health() -> dict[str, Any]:
    if not is_configured():
        return {"available": False, "reason": "kein API-Schluessel gesetzt"}
    quota = ai_usage.quota_state(PROVIDER)
    info = await list_models()
    if not info.get("available"):
        return {"available": False, "reason": info.get("reason"), "quota": quota}
    return {
        "available": True,
        "quota": quota,
        "text_model": text_model(),
        "vision_model": vision_model(),
        "text_model_available": text_model() in info["models"],
        "vision_model_available": vision_model() in info["models"],
        "free_tier_candidates": info.get("free_tier_candidates", []),
    }


def _build_parts(prompt: str, images: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for img in images or []:
        parts.append({"inline_data": {"mime_type": img["mime"], "data": img["data"]}})
    return parts


async def generate(
    prompt: str,
    system: str | None = None,
    images: list[dict[str, str]] | None = None,
    json_mode: bool = False,
    task: str = "chat",
    model: str | None = None,
    temperature: float = 0.2,
    max_output_tokens: int = 2048,
    retries: int | None = None,
) -> dict[str, Any]:
    """Erzeugt eine Antwort. Rueckgabe: {ok, text, error, provider, model}."""
    if retries is None:
        retries = max(0, min(5, settings.get_int("ai_max_retries", 1)))
    if not is_configured():
        return {"ok": False, "error": "Kein Gemini-API-Schluessel gesetzt", "provider": PROVIDER}
    if not ai_usage.can_use(PROVIDER):
        return {
            "ok": False,
            "error": "Kostenloses Gemini-Tageskontingent erschoepft",
            "provider": PROVIDER,
            "quota_exhausted": True,
        }

    use_model = model or (vision_model() if images else text_model())
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": _build_parts(prompt, images)}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ],
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    last_error = "unbekannter Fehler"
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=_timeout()) as client:
                resp = await client.post(_url(use_model), headers=_headers(), json=payload)
            if resp.status_code == 429:
                last_error = "429 Kontingent/Ratenlimit erreicht"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                if attempt < retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return {
                    "ok": False,
                    "error": "Kostenloses Gemini-Kontingent voruebergehend erschoepft (429)",
                    "provider": PROVIDER,
                    "quota_exhausted": True,
                }
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                if resp.status_code in (500, 502, 503, 504) and attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return {"ok": False, "error": last_error, "provider": PROVIDER, "model": use_model}

            data = resp.json()
            text = _extract_text(data)
            if not text:
                reason = _blocked_reason(data)
                last_error = reason or "Leere Antwort vom Modell"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                return {"ok": False, "error": last_error, "provider": PROVIDER, "model": use_model}
            ai_usage.record(PROVIDER, use_model, task, True)
            return {"ok": True, "text": text, "provider": PROVIDER, "model": use_model}
        except Exception as exc:  # noqa: BLE001 - Netzfehler sind erwartbar
            last_error = str(exc)
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
    ai_usage.record(PROVIDER, use_model, task, False, last_error)
    return {"ok": False, "error": last_error, "provider": PROVIDER, "model": use_model}


def _extract_text(data: dict[str, Any]) -> str:
    out: list[str] = []
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []) or []:
            if "text" in part:
                out.append(part["text"])
    return "\n".join(out).strip()


def _blocked_reason(data: dict[str, Any]) -> str | None:
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        return f"Anfrage blockiert ({feedback['blockReason']})"
    for cand in data.get("candidates", []):
        if cand.get("finishReason") in {"SAFETY", "RECITATION", "BLOCKLIST"}:
            return f"Antwort blockiert ({cand['finishReason']})"
    return None
