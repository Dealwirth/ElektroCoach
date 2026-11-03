"""Intelligente Weiterleitung zwischen Ollama (lokal) und Gemini (Cloud).

Grundregeln:
  * Bilder/Handschrift/Schaltplaene und schwierige Aufgaben -> Gemini.
  * Einfache Aufgaben (kurze Texte, Zusammenfassungen, Wiederholungsfragen)
    -> Ollama, weil lokal und kostenlos.
  * Modus "auto": bevorzugt die jeweils guenstigere Quelle, weicht bei
    Nichterreichbarkeit oder erschoepftem Kontingent auf die andere aus.
  * Ist keine KI erreichbar, bleiben Bewertung und Fragengenerierung durch
    deterministische Ersatzverfahren funktionsfaehig (siehe offline.py).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import settings
from . import gemini, ollama

log = logging.getLogger(__name__)

VISION_TASKS = {"ocr", "vision", "handwriting", "schematic", "page_analysis"}
COMPLEX_TASKS = {"exam", "complex_explanation", "topic_extraction", "question_generation"}


def mode() -> str:
    return str(settings.get("ai_mode", "auto"))


def _prefer_local(task: str, has_images: bool, prompt_len: int) -> bool:
    if has_images or task in VISION_TASKS:
        return False
    if task in COMPLEX_TASKS and prompt_len > 1200:
        return False
    return True


async def status() -> dict[str, Any]:
    local = await ollama.health()
    cloud = await gemini.health()
    return {
        "mode": mode(),
        "ollama": local,
        "gemini": cloud,
        "any_available": bool(local.get("available") or cloud.get("available")),
    }


async def complete(
    prompt: str,
    system: str | None = None,
    task: str = "chat",
    images: list[dict[str, str]] | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    max_output_tokens: int = 2048,
) -> dict[str, Any]:
    """Fuehrt eine KI-Anfrage mit Ausweichkette aus.

    Rueckgabe: {ok, text, provider, model, error, fallback_used}
    """
    current_mode = mode()
    if current_mode == "off":
        return {"ok": False, "error": "KI ist in den Einstellungen deaktiviert", "provider": "none"}

    # Datenschutz: externe Dienste nur, wenn ausdruecklich erlaubt.
    external_allowed = settings.get_bool("allow_external_ai", True) and not settings.get_bool(
        "allow_external_ai_strict", False
    )
    if images and not settings.get_bool("gemini_allow_images", False):
        # Bilder werden nur mit ausdruecklicher Freigabe uebertragen.
        images = None
        has_images = False
    else:
        has_images = bool(images)

    prompt_len = len(prompt or "")
    prefer_local = _prefer_local(task, has_images, prompt_len)

    order: list[str]
    if current_mode == "local_only":
        order = ["ollama"]
    elif current_mode == "cloud_only":
        order = ["gemini"] if external_allowed else []
    else:
        order = ["ollama", "gemini"] if prefer_local else ["gemini", "ollama"]
    if not external_allowed:
        order = [provider for provider in order if provider != "gemini"]
    # Nachbearbeitung: Cloud nur, wenn ausdruecklich freigegeben. Sonst bleibt
    # der lokale Weg (Ollama) die einzige Quelle.
    if task.startswith("ocr_refine") and not settings.get_bool("refine_use_cloud", False):
        order = [provider for provider in order if provider != "gemini"]

    errors: list[str] = []
    for provider in order:
        if provider == "ollama":
            if not ollama.is_enabled():
                errors.append("Ollama deaktiviert")
                continue
            result = await ollama.chat(
                prompt, system=system, images=_ollama_images(images),
                json_mode=json_mode, task=task, temperature=temperature,
            )
        else:
            if not gemini.is_configured():
                errors.append("Gemini nicht eingerichtet")
                continue
            result = await gemini.generate(
                prompt, system=system, images=images, json_mode=json_mode,
                task=task, temperature=temperature, max_output_tokens=max_output_tokens,
            )

        if result.get("ok"):
            result["fallback_used"] = bool(errors)
            result["attempt_errors"] = errors
            result["external"] = provider == "gemini"
            return result
        errors.append(f"{provider}: {result.get('error')}")
        if result.get("quota_exhausted"):
            log.info("Kontingent fuer %s erschoepft, weiche aus.", provider)

    if not order:
        errors.append("Externe KI ist deaktiviert")
    return {
        "ok": False,
        "provider": "none",
        "error": "; ".join(errors) or "Keine KI erreichbar",
        "fallback_used": True,
        "external": False,
    }


def _ollama_images(images: list[dict[str, str]] | None) -> list[str] | None:
    """Ollama erwartet reine Base64-Strings ohne Datenpraefix."""
    if not images:
        return None
    return [img["data"] for img in images]


def parse_json(text: str) -> Any | None:
    """Robustes JSON-Parsing fuer Modellantworten (entfernt Codebloecke)."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    for candidate in (cleaned, _slice_json(cleaned)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _slice_json(text: str) -> str | None:
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if 0 <= start < end:
            return text[start : end + 1]
    return None
