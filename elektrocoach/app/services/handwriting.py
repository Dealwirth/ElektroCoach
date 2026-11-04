"""Digitalisierung handschriftlicher Antworten (Stift- und Touch-Eingabe).

Der Lernende kann Pruefungs- und Uebungsaufgaben mit Stift, Finger oder Maus
beantworten. Das Bild der Handschrift wird hier in Text umgewandelt, damit die
bestehende Bewertung (Punkte, Teilpunkte, Rechenweg) darauf arbeiten kann.

Zwei Wege:

  * ``gemini``: Bildanalyse. Erkennt auch unordentliche Handschrift, Formeln
    und Schaltplaene. Nur bei ausdruecklicher Freigabe von Bildern.
  * ``offline``: meldet, dass keine Handschrifterkennung moeglich ist. Der
    Lernende bekommt dann den Hinweis, den Text zu tippen. Es wird nichts
    geraten.

Ein optionaler OCR-Text aus dem Browser (Handschrift-API) wird, wenn vorhanden,
bevorzugt verwendet. Das spart eine Cloud-Anfrage.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from ..config import settings
from . import ai_router, gemini

log = logging.getLogger(__name__)

# Mehr als dieses Mass wird nicht uebertragen (Speicher und Datenmenge).
MAX_IMAGE_BYTES = 4 * 1024 * 1024

SYSTEM_HANDWRITING = (
    "Du liest die handschriftliche Antwort eines Auszubildenden der "
    "Elektrotechnik (Energie- und Gebaeudetechnik) von einem Bild. "
    "Regeln: "
    "1) Gib nur wieder, was wirklich dasteht. Erfinde nichts. "
    "2) Formeln, Einheiten, Klemmen- und Betriebsmittelbezeichnungen "
    "uebernimm fachlich korrekt (z. B. I, U, R, P, cos phi, mm2, L1, PE, RCD). "
    "3) Zahlen und Rechenwege vollstaendig wiedergeben. "
    "4) Ist eine Stelle nicht lesbar, schreibe [unleserlich] dafuer. "
    "Antworte ausschliesslich mit einem JSON-Objekt: "
    '{"text": "<erkannter Text>", "confidence": <0.0-1.0>, '
    '"unleserlich": <true|false>, "hinweis": "<kurze Anmerkung>"}'
)


def _parse(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            confidence = data.get("confidence")
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None
            return {
                "text": data["text"].strip(),
                "confidence": confidence,
                "unleserlich": bool(data.get("unleserlich", False)),
                "hinweis": str(data.get("hinweis") or "")[:300],
            }
    return None


def _decode_image(data_url: str) -> dict[str, str] | None:
    """Wandelt eine Data-URL (data:image/png;base64,...) in Nutzdaten um."""
    if not data_url:
        return None
    match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)", data_url, re.DOTALL)
    if not match:
        return None
    mime, payload = match.group(1), match.group(2).strip()
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception:  # noqa: BLE001
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    return {"mime": mime, "data": base64.b64encode(raw).decode("ascii")}


def available() -> bool:
    """Ist eine Handschrifterkennung moeglich?"""
    return gemini.is_configured() and settings.get_bool("gemini_allow_images", False)


async def transcribe(
    image_data_url: str,
    *,
    hint: str = "",
    browser_text: str = "",
) -> dict[str, Any]:
    """Erkennt Text aus einem Handschriftbild.

    ``browser_text`` ist ein optionaler Text aus der Handschrift-Erkennung des
    Browsers. Er wird bevorzugt, weil er ohne Cloud auskommt.
    """
    if browser_text and browser_text.strip():
        return {
            "ok": True,
            "text": browser_text.strip(),
            "confidence": 0.7,
            "method": "browser",
            "unleserlich": False,
            "hinweis": "Im Browser erkannt.",
        }

    if not available():
        # Zwei verschiedene Ursachen, zwei verschiedene Hinweise. Sonst sucht
        # der Nutzer an der falschen Stelle.
        if not gemini.is_configured():
            error = "Handschrifterkennung braucht einen Gemini-Schluessel."
            hint = (
                "Es ist kein Gemini-Schluessel hinterlegt. Entweder den Schluessel "
                "unter Einstellungen -> KI-Dienste eintragen oder die Antwort tippen."
            )
        else:
            error = "Bilder sind fuer die Cloud nicht freigegeben."
            hint = (
                "Unter Einstellungen -> KI-Dienste die Option 'Bilder an die Cloud "
                "senden' einschalten oder die Antwort tippen."
            )
        return {"ok": False, "error": error, "method": "offline", "hint": hint}

    image = _decode_image(image_data_url)
    if not image:
        return {
            "ok": False,
            "error": "Bild konnte nicht gelesen werden.",
            "method": "offline",
        }

    prompt = "Lies die handschriftliche Antwort aus dem Bild."
    if hint:
        prompt += f"\n\nAufgabenstellung zur Hilfe:\n{hint[:1500]}"

    result = await gemini.generate(
        prompt,
        system=SYSTEM_HANDWRITING,
        images=[image],
        json_mode=True,
        task="handwriting",
        temperature=0.1,
        max_output_tokens=1500,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error"),
            "method": "gemini",
            "hint": "Die Handschrift konnte nicht erkannt werden. Bitte erneut versuchen oder tippen.",
        }

    parsed = _parse(str(result.get("text") or ""))
    if not parsed or not parsed["text"]:
        return {"ok": False, "error": "Keine verwertbare Handschrift erkannt.", "method": "gemini"}

    parsed.update({"ok": True, "method": "gemini", "model": result.get("model")})
    return parsed
