"""Samsung-Notes-Import.

Samsung Notes kennt zwei Wege, Aufzeichnungen herauszugeben:

  1. Export als PDF (empfohlen, in Samsung Notes: Menue > Als Datei
     speichern > PDF). Diese Dateien verarbeitet der PDF-Pfad in ocr.py
     vollstaendig, inklusive Handschrift-OCR gescannter Seiten.

  2. Sammlungs-Export als .sdoc/.snote. Das sind ZIP-Container. Der Inhalt
     ist nicht oeffentlich dokumentiert, deshalb arbeitet dieser Importer
     best-effort: er oeffnet den Container, liest enthaltene JSON-, XML-,
     HTML- und Textdateien aus und schickt alle eingebetteten Bilder durch
     die OCR. Was nicht sicher erkannt wird, wird als "needs_review"
     gekennzeichnet, damit keine falschen Inhalte in die Wissensbasis
     gelangen.

Der Importer ist damit robust gegen Formatvarianten und liefert auch bei
unbekanntem Innenleben verwertbare Ergebnisse.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from .ocr import (
    IMAGE_SUFFIXES,
    PageResult,
    DocumentResult,
    _clean_text,
    ocr_image_bytes,
)

log = logging.getLogger(__name__)

SAMSUNG_SUFFIXES = {".sdoc", ".snote", ".sdocx"}
ARCHIVE_SUFFIXES = {".zip"}
TEXT_INNER_SUFFIXES = {".txt", ".md", ".json", ".xml", ".html", ".htm", ".csv"}
MAX_INNER_IMAGES = 400


def is_samsung_file(path: Path) -> bool:
    return path.suffix.lower() in SAMSUNG_SUFFIXES


def _text_from_json(payload: Any, depth: int = 0) -> list[str]:
    """Zieht alle lesbaren Textfelder aus einer JSON-Struktur."""
    if depth > 8:
        return []
    out: list[str] = []
    if isinstance(payload, str):
        cleaned = _clean_text(payload)
        if len(cleaned) > 2:
            out.append(cleaned)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (str, int, float)) and str(key).lower() in {
                "text", "content", "body", "title", "value", "note", "stroke",
            }:
                cleaned = _clean_text(str(value))
                if len(cleaned) > 2:
                    out.append(cleaned)
            else:
                out.extend(_text_from_json(value, depth + 1))
    elif isinstance(payload, list):
        for item in payload:
            out.extend(_text_from_json(item, depth + 1))
    return out


def _process_inner_text(name: str, data: bytes) -> list[str]:
    suffix = Path(name).suffix.lower()
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return []
    if suffix == ".json":
        try:
            return _text_from_json(json.loads(text))
        except json.JSONDecodeError:
            return [_clean_text(text)]
    if suffix in {".html", ".htm", ".xml"}:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "lxml")
            return [_clean_text(soup.get_text("\n"))]
        except Exception:
            return [_clean_text(re.sub(r"<[^>]+>", " ", text))]
    return [_clean_text(text)]


def process_container(path: Path) -> DocumentResult:
    """Verarbeitet .sdoc/.snote/.zip-Container."""
    result = DocumentResult(kind="samsung_notes")
    if not zipfile.is_zipfile(path):
        result.meta["error"] = "Kein lesbarer Samsung-Notes-Container (kein ZIP)"
        result.needs_review = True
        result.pages.append(PageResult(page_number=1, needs_review=True,
                                       meta={"error": result.meta["error"]}))
        return result

    collected_text: list[str] = []
    image_entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith("__MACOSX/"):
                continue
            suffix = Path(name).suffix.lower()
            try:
                data = archive.read(info)
            except Exception as exc:  # noqa: BLE001
                log.warning("Eintrag %s nicht lesbar: %s", name, exc)
                continue
            if suffix in IMAGE_SUFFIXES:
                image_entries.append((name, data))
            elif suffix in TEXT_INNER_SUFFIXES:
                collected_text.extend(_process_inner_text(name, data))

    page_number = 0
    for name, data in sorted(image_entries)[:MAX_INNER_IMAGES]:
        page_number += 1
        ocr = ocr_image_bytes(data)
        page = PageResult(
            page_number=page_number,
            text=ocr["text"] if ocr["ok"] else "",
            confidence=ocr["confidence"],
            image_bytes=data,
            image_mime=f"image/{Path(name).suffix.lstrip('.').lower() or 'png'}",
            meta={"source_entry": name, "ocr": "tesseract"},
        )
        if not ocr["ok"] or not page.text.strip() or (page.confidence or 0) < 70:
            page.needs_review = True
        result.pages.append(page)

    if collected_text:
        combined = "\n\n".join(t for t in collected_text if t.strip())
        if combined.strip():
            page_number += 1
            result.pages.append(
                PageResult(page_number=page_number, text=combined,
                           meta={"source": "embedded_text"})
            )

    result.meta["images"] = len(image_entries)
    result.meta["text_parts"] = len(collected_text)
    if not result.pages:
        result.meta["error"] = "Container enthielt keine verwertbaren Inhalte"
        result.pages.append(PageResult(page_number=1, needs_review=True))
    result.needs_review = any(p.needs_review for p in result.pages)
    return result


def describe_import_formats() -> dict[str, Any]:
    return {
        "samsung_direct": {
            "supported": True,
            "suffixes": sorted(SAMSUNG_SUFFIXES | ARCHIVE_SUFFIXES),
            "quality": "best-effort",
            "note": (
                "Samsung-Notes-Container (.sdoc/.snote) und ZIP-Sammlungen werden "
                "geoeffnet, eingebettete Texte und Bilder werden ausgelesen und per "
                "OCR erkannt. Nicht sicher erkannte Seiten werden zur Pruefung markiert."
            ),
        },
        "recommended": {
            "format": "PDF",
            "note": (
                "Der zuverlaessigste Weg: in Samsung Notes die Notiz oder Sammlung "
                "als PDF exportieren. PDFs mit eingebettetem Text werden direkt "
                "gelesen, handschriftliche Scans automatisch per OCR."
            ),
        },
        "also_supported": ["PDF", "PNG/JPG/WEBP/TIFF", "TXT", "MD", "HTML", "CSV", "ZIP"],
    }
