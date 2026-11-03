"""Nachbearbeitung erkannter Texte mit KI (OCR-Verbesserung).

Die Texterkennung (Tesseract) liefert bei Handschrift und Formeln haeufig
fehlerhafte Zeichen. Diese Stufe verbessert den Text zweistufig:

  1. Lokales Modell (Ollama): korrigiert offensichtliche OCR-Fehler, ergaenzt
     Einheiten und Formeln. Kostenlos und offline.
  2. Cloud (Gemini Free Tier): nur bei unsicher erkannten Seiten und nur, wenn
     Bilder ausdruecklich freigegeben sind. Dann wird das Seitenbild mitgesandt
     (bessere Handschrifterkennung).

Ergebnis je Seite:
  * verbesserter Text,
  * Einschaetzung der Verlaesslichkeit (0..1),
  * Kennzeichnung "unsicher" -> bleibt zur Pruefung markiert.

Faellt jede KI aus, bleibt der urspruengliche Text unveraendert erhalten. Es
wird nie Text geloescht, wenn die KI nichts Brauchbares liefert.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

from .. import db
from ..config import settings
from . import ai_router

log = logging.getLogger(__name__)

# Unterhalb dieser Verlaesslichkeit bleibt die Seite zur Pruefung markiert.
CONFIDENCE_KEEP_REVIEW = 0.75
# Ab dieser Textlaenge wird der Text in Stuecke zerlegt (Kontextgrenze).
MAX_PROMPT_CHARS = 6000

SYSTEM_REFINE = (
    "Du bist Fachkraft fuer Elektrotechnik (Energie- und Gebaeudetechnik) und "
    "korrigierst per Texterkennung (OCR) erfasste Ausbildungsaufzeichnungen. "
    "Regeln: "
    "1) Erfinde keinen Inhalt und ergaenze keine Absaetze, die nicht im Text "
    "stehen. "
    "2) Korrigiere nur eindeutige OCR-Fehler, Trennzeichen, Gross- und "
    "Kleinschreibung sowie offensichtliche Worttrennungen. "
    "3) Fachbegriffe, Formeln, Einheiten und Normbezuege (z. B. DIN VDE 0100, "
    "RCD, Leitungsschutzschalter, Querschnitt in mm2) bleiben fachlich korrekt. "
    "4) Bleibt eine Stelle unklar, kennzeichne sie mit [unklar] statt zu raten. "
    "Antworte ausschliesslich mit einem JSON-Objekt in dieser Form: "
    '{"text": "<korrigierter Text>", "confidence": <0.0-1.0>, '
    '"notes": "<kurze Hinweise>", "uncertain": <true|false>}'
)

SYSTEM_VISION = (
    "Du liest handschriftliche oder gedruckte Aufzeichnungen aus der "
    "Elektrotechnik-Ausbildung. Gib den erkannten Text vollstaendig wieder. "
    "Formeln, Schaltzeichen-Bezeichnungen, Klemmenbezeichnungen, Tabellen und "
    "Einheiten uebernimm fachlich korrekt. Nutze den vorhandenen OCR-Text als "
    "Anhaltspunkt, korrigiere ihn anhand des Bildes. "
    "Antworte ausschliesslich mit einem JSON-Objekt: "
    '{"text": "<Text>", "confidence": <0.0-1.0>, "notes": "<Hinweise>", '
    '"uncertain": <true|false>}'
)


def _parse_response(raw: str) -> dict[str, Any] | None:
    """Liest das JSON-Objekt aus der KI-Antwort, auch bei Text drumherum."""
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
                "text": data["text"],
                "confidence": confidence,
                "notes": str(data.get("notes") or "")[:500],
                "uncertain": bool(data.get("uncertain", False)),
            }
    return None


def _split_text(text: str, limit: int = MAX_PROMPT_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    for index in range(0, len(text), limit):
        parts.append(text[index : index + limit])
    return parts


def _image_payload(page: dict[str, Any]) -> dict[str, str] | None:
    """Liest das Seitenbild als Base64, wenn vorhanden und erlaubt."""
    if not settings.get_bool("gemini_allow_images", False):
        return None
    path = page.get("image_path")
    if not path:
        return None
    file = Path(path)
    if not file.exists():
        return None
    try:
        data = file.read_bytes()
    except OSError:
        return None
    return {"mime": "image/png", "data": base64.b64encode(data).decode("ascii")}


async def refine_text(
    text: str,
    *,
    images: list[dict[str, str]] | None = None,
    task: str = "ocr_refine",
) -> dict[str, Any]:
    """Verbessert einen Textabschnitt. Rueckgabe: {ok, text, confidence, ...}."""
    prompt = (
        "Korrigiere den folgenden, per Texterkennung erfassten Text.\n\n"
        f"TEXT:\n{text}"
    )
    system = SYSTEM_VISION if images else SYSTEM_REFINE
    result = await ai_router.complete(
        prompt,
        system=system,
        task=task,
        images=images,
        json_mode=True,
        temperature=0.1,
        max_output_tokens=3072,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "provider": result.get("provider")}
    parsed = _parse_response(str(result.get("text") or ""))
    if not parsed or not parsed["text"].strip():
        return {
            "ok": False,
            "error": "Antwort war nicht verwertbar",
            "provider": result.get("provider"),
            "model": result.get("model"),
        }
    parsed.update({
        "ok": True,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "fallback_used": result.get("fallback_used", False),
    })
    return parsed


async def refine_page(page: dict[str, Any]) -> dict[str, Any]:
    """Verbessert eine Seite. Gibt das Ergebnis ohne Datenbankschreiben zurueck."""
    original = (page.get("text") or "").strip()
    if not original:
        return {"ok": False, "error": "Seite enthaelt keinen Text", "page_id": page.get("id")}

    images = _image_payload(page) if page.get("needs_review") else None
    parts = _split_text(original)
    pieces: list[str] = []
    confidences: list[float] = []
    notes: list[str] = []
    uncertain = False
    providers: set[str] = set()
    succeeded = 0

    for part in parts:
        result = await refine_text(part, images=images)
        if not result.get("ok"):
            # Bei Fehlern bleibt der Originaltext dieses Abschnitts erhalten.
            pieces.append(part)
            uncertain = True
            notes.append(str(result.get("error") or "KI nicht verfuegbar"))
            continue
        succeeded += 1
        pieces.append(result["text"].strip() or part)
        if result.get("confidence") is not None:
            confidences.append(float(result["confidence"]))
        if result.get("uncertain"):
            uncertain = True
        if result.get("notes"):
            notes.append(str(result["notes"]))
        if result.get("provider"):
            providers.add(str(result["provider"]))

    if succeeded == 0:
        # Keine einzige Anfrage war erfolgreich: klar als Fehler melden, damit
        # die Oberflaeche nicht faelschlich "verbessert" anzeigt.
        return {
            "ok": False,
            "page_id": page.get("id"),
            "error": "; ".join(dict.fromkeys(notes))[:300] or "KI nicht erreichbar",
        }

    refined = "\n\n".join(piece for piece in pieces if piece.strip())
    confidence = sum(confidences) / len(confidences) if confidences else None
    keep_review = uncertain or confidence is None or confidence < CONFIDENCE_KEEP_REVIEW

    return {
        "ok": True,
        "page_id": page.get("id"),
        "document_id": page.get("document_id"),
        "original": original,
        "text": refined,
        "confidence": confidence,
        "needs_review": keep_review,
        "notes": " | ".join(dict.fromkeys(notes))[:500],
        "providers": sorted(providers),
    }


def apply_result(result: dict[str, Any]) -> bool:
    """Schreibt das Ergebnis in die Datenbank und erneuert die Abschnitte."""
    from . import library

    page_id = result.get("page_id")
    if not page_id or not result.get("ok"):
        return False
    library.update_page_text(page_id, result["text"], clear_review=not result["needs_review"])
    meta_row = db.query_one("SELECT meta_json FROM pages WHERE id = ?", (page_id,))
    meta: dict[str, Any] = {}
    if meta_row and meta_row["meta_json"]:
        try:
            meta = json.loads(meta_row["meta_json"])
        except json.JSONDecodeError:
            meta = {}
    meta["refined"] = {
        "confidence": result.get("confidence"),
        "needs_review": result.get("needs_review"),
        "providers": result.get("providers", []),
        "notes": result.get("notes", ""),
    }
    db.execute(
        "UPDATE pages SET meta_json = ?, ocr_confidence = COALESCE(?, ocr_confidence) WHERE id = ?",
        (db.json_dumps_safe(meta), result.get("confidence"), page_id),
    )
    return True


def pending_pages(document_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """Seiten, die von einer Nachbearbeitung profitieren."""
    if document_id:
        rows = db.query(
            "SELECT id, document_id, page_number, text, image_path, needs_review "
            "FROM pages WHERE document_id = ? AND text != '' ORDER BY page_number LIMIT ?",
            (document_id, limit),
        )
    else:
        rows = db.query(
            "SELECT id, document_id, page_number, text, image_path, needs_review "
            "FROM pages WHERE needs_review = 1 AND text != '' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in rows]
