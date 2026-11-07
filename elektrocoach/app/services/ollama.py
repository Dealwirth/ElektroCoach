"""Ollama-Client fuer lokale, ressourcenschonende KI auf dem Raspberry Pi.

Unterstuetzte Modelle (auf einem Raspberry Pi 4 mit 8 GB RAM getestet bzw.
empfohlen, Q4-Quantisierung, CPU-Inferenz):
  - llama3.2:3b   ~2.0 GB   schnell, guter Allrounder
  - qwen2.5:3b    ~1.9 GB   gute deutsche Texte
  - phi4-mini     ~2.5 GB   bestes kleines Modell fuer Logik/Rechnen
  - gemma3:4b     ~3.3 GB   mehrsprachig (langsamer auf ARM)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings
from . import ai_usage

log = logging.getLogger(__name__)

PROVIDER = "ollama"
RECOMMENDED_MODELS = [
    {"name": "llama3.2:3b", "size_gb": 2.0, "note": "Schnell, guter Allrounder (empfohlen)"},
    {"name": "qwen2.5:3b", "size_gb": 1.9, "note": "Gute deutsche Texte"},
    {"name": "phi4-mini:3.8b", "size_gb": 2.5, "note": "Bestes kleines Modell fuer Rechnen/Logik"},
    {"name": "gemma3:4b", "size_gb": 3.3, "note": "Mehrsprachig, langsamer auf ARM"},
]

# Modelle, die Bilder lesen koennen. Fuer Handschrift und Formeln sind sie
# deutlich staerker als reine Textmodelle.
VISION_MODELS = [
    {"name": "qwen2.5vl:3b", "size_gb": 3.2,
     "note": "Beste lokale Handschrift-/Formelerkennung (empfohlen)"},
    {"name": "gemma3:4b", "size_gb": 3.3, "note": "Mehrsprachig, braucht laenger"},
    {"name": "minicpm-v:8b", "size_gb": 5.5, "note": "Sehr genau, gross und langsam"},
    {"name": "llava:7b", "size_gb": 4.7, "note": "Aelteres Vision-Modell"},
]
VISION_PREFIXES = (
    "qwen2.5vl", "qwen2-vl", "qwen3-vl", "llava", "bakllava", "gemma3",
    "minicpm-v", "moondream", "llama3.2-vision", "granite3.2-vision",
    "internvl", "mistral-small3", "phi4-multimodal", "granite-vision",
)


def is_vision_model(name: str) -> bool:
    """Erkennt anhand des Namens, ob ein Modell Bilder annimmt."""
    base = (name or "").split(":")[0].strip().lower()
    return any(base == prefix or base.startswith(prefix) or prefix in base for prefix in VISION_PREFIXES)


def vision_model() -> str:
    return str(settings.get("ollama_vision_model", "qwen2.5vl:3b")).strip() or "qwen2.5vl:3b"


_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=5.0)


def _timeout() -> httpx.Timeout:
    """Zeitlimit aus den Einstellungen."""
    total = max(5, settings.get_int("ai_timeout_seconds", 180))
    return httpx.Timeout(connect=min(5.0, total), read=float(total), write=30.0, pool=5.0)


def base_url() -> str:
    return str(settings.get("ollama_url", "http://localhost:11434")).rstrip("/")


def model() -> str:
    return str(settings.get("ollama_model", "llama3.2:1b"))


def is_enabled() -> bool:
    return settings.get_bool("ollama_enabled", False)


async def health() -> dict[str, Any]:
    """Prueft Erreichbarkeit und listet vorhandene Modelle."""
    if not is_enabled():
        return {"available": False, "reason": "deaktiviert", "models": []}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{base_url()}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        vision_models = [m for m in models if is_vision_model(m)]
        wanted_vision = vision_model()
        return {
            "available": True,
            "url": base_url(),
            "model": model(),
            "model_present": any(m == model() or m.startswith(model().split(":")[0]) for m in models),
            "models": models,
            "recommended": RECOMMENDED_MODELS,
            "vision_model": wanted_vision,
            "vision_present": any(
                m == wanted_vision or m.startswith(wanted_vision.split(":")[0]) for m in vision_models
            ),
            "vision_models": vision_models,
            "vision_recommended": VISION_MODELS,
        }
    except Exception as exc:  # noqa: BLE001 - jede Netzstoerung ist hier erwartbar
        return {"available": False, "reason": str(exc), "url": base_url(), "models": []}


async def chat(
    prompt: str,
    system: str | None = None,
    images: list[str] | None = None,
    json_mode: bool = False,
    task: str = "chat",
    temperature: float = 0.2,
    num_ctx: int = 4096,
    model_name: str | None = None,
    num_predict: int = 1024,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Fuehrt einen Chat-Aufruf aus. Gibt {ok, text, error, provider, model} zurueck.

    ``model_name`` uebersteuert das eingestellte Modell. Fuer Bilder ist das
    noetig, weil nur Vision-Modelle Bilder annehmen.
    ``timeout_seconds`` uebersteuert das Lesezeitlimit. Die Bilderkennung
    braucht auf einem Raspberry Pi deutlich laenger als ein Textaufruf.
    """
    if not is_enabled():
        return {"ok": False, "error": "Ollama ist deaktiviert", "provider": PROVIDER}

    selected = (model_name or model()).strip() or model()
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    user_msg: dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    payload: dict[str, Any] = {
        "model": selected,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": max(16, num_predict),
        },
    }
    if json_mode:
        payload["format"] = "json"

    try:
        timeout = _timeout()
        if timeout_seconds:
            timeout = httpx.Timeout(connect=5.0, read=float(timeout_seconds),
                                    write=30.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url()}/api/chat", json=payload)
            if resp.status_code >= 400:
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                ai_usage.record(PROVIDER, selected, task, False, err)
                return {"ok": False, "error": err, "provider": PROVIDER, "model": selected}
            data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        ai_usage.record(PROVIDER, selected, task, True)
        return {"ok": True, "text": text, "provider": PROVIDER, "model": selected}
    except Exception as exc:  # noqa: BLE001
        ai_usage.record(PROVIDER, selected, task, False, str(exc))
        return {"ok": False, "error": str(exc), "provider": PROVIDER, "model": selected}
