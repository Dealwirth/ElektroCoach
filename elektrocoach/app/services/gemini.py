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
import time
from typing import Any

import httpx

from ..config import settings
from . import ai_usage

log = logging.getLogger(__name__)

PROVIDER = "gemini"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Modelle, die kurz zuvor mit 404 (abgestellt) oder 503 (ueberlastet)
# geantwortet haben, werden voruebergehend nach hinten sortiert. So kostet ein
# ueberlastetes Modell nicht bei jeder Anfrage erneut Wartezeit.
_DEGRADED_TTL = 120.0
_degraded: dict[str, float] = {}


def _mark_degraded(name: str) -> None:
    _degraded[name] = time.monotonic() + _DEGRADED_TTL


def _is_degraded(name: str) -> bool:
    until = _degraded.get(name)
    if until is None:
        return False
    if until < time.monotonic():
        _degraded.pop(name, None)
        return False
    return True


# Bevorzugte Modelle im kostenlosen Kontingent (Reihenfolge = Fallback).
# Die Liste ist nur eine Vorauswahl: Zur Laufzeit wird sie gegen die
# tatsaechlich verfuegbaren Modelle geprueft. Google stellt Modelle regelmaessig
# ab ("no longer available to new users"), deshalb wird das aktive Modell
# automatisch neu bestimmt, wenn eine Anfrage mit HTTP 404 scheitert.
FREE_TIER_PREFERENCE = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
]

# Modelle, die fuer Text- und Bildaufgaben nicht geeignet sind. Pro-Modelle
# sind im kostenlosen Kontingent nicht nutzbar und werden deshalb uebersprungen.
_MODEL_EXCLUDE = ("image", "tts", "live", "transcribe", "embedding", "aqa", "audio", "pro", "nano-banana")

_model_cache: dict[str, Any] = {"at": 0.0, "models": []}
_MODEL_CACHE_TTL = 6 * 3600.0


def _model_rank(name: str) -> tuple[int, int]:
    """Sortierschluessel: hohe Version und 'flash' vor 'lite' bevorzugen."""
    import re

    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    major = int(match.group(1)) if match else 0
    minor = int(match.group(2)) if match and match.group(2) else 0
    lite_penalty = -1 if "lite" in name else 0
    return (major * 100 + minor + lite_penalty, -len(name))


def _usable_models(names: list[str]) -> list[str]:
    return [n for n in names if not any(x in n for x in _MODEL_EXCLUDE)]


async def _fetch_models() -> list[str]:
    info = await list_models()
    return info.get("models", []) if info.get("available") else []


async def available_models(refresh: bool = False) -> list[str]:
    """Verfuegbare Modelle, kurzzeitig zwischengespeichert."""
    now = asyncio.get_event_loop().time()
    if not refresh and _model_cache["models"] and now - _model_cache["at"] < _MODEL_CACHE_TTL:
        return _model_cache["models"]
    models = await _fetch_models()
    if models:
        _model_cache["models"] = models
        _model_cache["at"] = now
    return models or _model_cache["models"]


async def model_candidates(preferred: str | None = None, images: bool = False,
                           refresh: bool = False) -> list[str]:
    """Kandidaten in sinnvoller Reihenfolge.

    Das konfigurierte Modell steht zuerst. Danach folgen die bevorzugten
    Modelle und die von der Schnittstelle gemeldeten Modelle. Die Liste wird
    zur Laufzeit durchprobiert, weil Google Modelle abstellt, sie aber
    teilweise weiterhin auflistet.
    """
    preferred = preferred or (vision_model() if images else text_model())
    listed = await available_models(refresh=refresh)
    ordered: list[str] = [preferred, *FREE_TIER_PREFERENCE]
    ordered.extend(sorted(_usable_models(listed), key=_model_rank, reverse=True))
    seen: set[str] = set()
    result: list[str] = []
    for name in ordered:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    # Zuletzt als ueberlastet oder abgestellt gemeldete Modelle nach hinten.
    fresh = [n for n in result if not _is_degraded(n)]
    degraded = [n for n in result if _is_degraded(n)]
    return fresh + degraded


def pick_model(configured: str, models: list[str]) -> str:
    """Waehlt aus einer Modellliste das beste nutzbare Modell."""
    usable = _usable_models(models)
    if configured in models:
        return configured
    for candidate in FREE_TIER_PREFERENCE:
        if candidate in usable:
            return candidate
    if usable:
        return sorted(usable, key=_model_rank, reverse=True)[0]
    return configured


async def resolve_model(configured: str | None = None, refresh: bool = False) -> str:
    """Bestimmt ein tatsaechlich nutzbares Modell (nur anhand der Liste)."""
    configured = configured or text_model()
    models = await available_models(refresh=refresh)
    if not models:
        return configured
    return pick_model(configured, models)


def invalidate_model_cache() -> None:
    _model_cache["models"] = []
    _model_cache["at"] = 0.0


_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)


def _timeout() -> httpx.Timeout:
    """Zeitlimit aus den Einstellungen. Schuetzt vor blockierten Anfragen."""
    total = max(5, settings.get_int("ai_timeout_seconds", 180))
    return httpx.Timeout(connect=min(10.0, total), read=float(total), write=60.0, pool=10.0)


_last_429: float = 0.0


def api_key() -> str:
    return str(settings.get("gemini_api_key", "") or "")


def text_model() -> str:
    return str(settings.get("gemini_text_model", "gemini-flash-latest"))


def vision_model() -> str:
    return str(settings.get("gemini_vision_model", "gemini-flash-latest"))


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
    models = info.get("models", [])
    # Konfigurierte Modelle koennen von Google abgestellt worden sein.
    resolved_text = pick_model(text_model(), models)
    resolved_vision = pick_model(vision_model(), models)
    return {
        "available": True,
        "quota": quota,
        "text_model": resolved_text,
        "vision_model": resolved_vision,
        "configured_text_model": text_model(),
        "configured_vision_model": vision_model(),
        "model_changed": resolved_text != text_model() or resolved_vision != vision_model(),
        "text_model_available": resolved_text in models,
        "vision_model_available": resolved_vision in models,
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

    if model:
        use_model = model
        candidates: list[str] = []
    else:
        # Kandidatenliste aufbauen. Das konfigurierte Modell steht zuerst.
        # Google stellt Modelle regelmaessig ab, deshalb wird bei einem
        # Fehler 404 automatisch das naechste Modell probiert.
        candidates = await model_candidates(
            vision_model() if images else text_model(), images=images
        )
        use_model = candidates.pop(0)
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
    attempts = 0
    max_attempts = retries + 1 + (0 if model else 4)
    while attempts < max_attempts:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=_timeout()) as client:
                resp = await client.post(_url(use_model), headers=_headers(), json=payload)
            if resp.status_code == 429:
                last_error = "429 Kontingent/Ratenlimit erreicht"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                if attempts <= retries:
                    await asyncio.sleep(2.0 * attempts)
                    continue
                return {
                    "ok": False,
                    "error": "Kostenloses Gemini-Kontingent voruebergehend erschoepft (429)",
                    "provider": PROVIDER,
                    "quota_exhausted": True,
                }
            if resp.status_code in (404, 503) and not model:
                # Modell abgestellt (404) oder ueberlastet (503). Das naechste
                # in Frage kommende Modell probieren. Manche Modelle werden
                # noch aufgelistet, sind aber nicht mehr nutzbar, und die
                # Auslastung ist pro Modell unterschiedlich.
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                _mark_degraded(use_model)
                if not candidates:
                    invalidate_model_cache()
                    candidates = await model_candidates(
                        vision_model() if images else text_model(), images=images, refresh=True
                    )
                if candidates:
                    use_model = candidates.pop(0)
                    log.warning("Gemini-Modell nicht nutzbar (%s), naechster Versuch: %s",
                                resp.status_code, use_model)
                    continue
                return {"ok": False, "error": last_error, "provider": PROVIDER, "model": use_model}
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                ai_usage.record(PROVIDER, use_model, task, False, last_error)
                if resp.status_code in (500, 502, 503, 504) and attempts <= retries:
                    await asyncio.sleep(1.5 * attempts)
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
            if not model:
                # Gewaehltes Modell merken, damit der naechste Aufruf direkt
                # das funktionierende Modell verwendet.
                settings.set_runtime(
                    "gemini_vision_model" if images else "gemini_text_model", use_model
                )
            return {"ok": True, "text": text, "provider": PROVIDER, "model": use_model}
        except Exception as exc:  # noqa: BLE001 - Netzfehler sind erwartbar
            last_error = str(exc)
            if isinstance(exc, httpx.TimeoutException) and not model and candidates:
                # Ein ueberlastetes Modell kann das Lesezeitlimit reissen. Dann
                # sofort das naechste Modell probieren, statt das Zeitlimit bei
                # jeder Anfrage erneut abzuwarten.
                ai_usage.record(PROVIDER, use_model, task, False, f"Zeitlimit: {exc}")
                _mark_degraded(use_model)
                use_model = candidates.pop(0)
                log.warning("Gemini-Modell ueberschritt das Zeitlimit, naechster Versuch: %s", use_model)
                continue
            if attempts <= retries:
                await asyncio.sleep(1.5 * attempts)
                continue
            break
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
