"""OCR und Dokumentverarbeitung.

Pipeline je Datei:
  * PDF   -> eingebetteter Text (pypdf); leere/gescannte Seiten werden mit
             pypdfium2 gerendert und per Tesseract OCR gelesen.
  * Bild  -> Tesseract OCR (deu+eng+equ), optional Gemini-Vision fuer
             Handschrift.
  * Text  -> direkt uebernommen.

Ergebnis pro Seite: Text, Konfidenz, Kennzeichnung "needs_review".
"""

from __future__ import annotations

import base64
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
HTML_SUFFIXES = {".html", ".htm"}

# Seiten mit weniger Zeichen gelten als "praktisch leer" und werden OCR-behandelt.
MIN_TEXT_CHARS = 40
# Unterhalb dieser Tesseract-Konfidenz wird die Seite zur Pruefung markiert.
REVIEW_CONFIDENCE = 70.0

try:
    import pytesseract
    from PIL import Image

    _HAVE_TESSERACT = True
except Exception:  # pragma: no cover
    _HAVE_TESSERACT = False
    Image = None  # type: ignore[assignment]


@dataclass
class PageResult:
    page_number: int
    text: str = ""
    confidence: float | None = None
    needs_review: bool = False
    image_bytes: bytes | None = None
    image_mime: str = "image/png"
    width: int | None = None
    height: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentResult:
    pages: list[PageResult] = field(default_factory=list)
    kind: str = "unknown"
    needs_review: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------
def tesseract_available() -> bool:
    if not _HAVE_TESSERACT:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def tesseract_languages() -> list[str]:
    if not _HAVE_TESSERACT:
        return []
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def _ocr_language() -> str:
    configured = str(settings.get("ocr_languages", "deu+eng"))
    available = tesseract_languages()
    if not available:
        return configured
    selected = [lang for lang in configured.split("+") if lang in available]
    if not selected:
        selected = [lang for lang in ("deu", "eng") if lang in available]
    return "+".join(selected) or "eng"


def ocr_image_bytes(data: bytes, languages: str | None = None) -> dict[str, Any]:
    """OCR eines Bildes. Rueckgabe: {text, confidence, ok, error}."""
    if not tesseract_available():
        return {"text": "", "confidence": None, "ok": False,
                "error": "Tesseract ist nicht installiert"}
    try:
        image = Image.open(io.BytesIO(data))
        image = _prepare_image(image)
        lang = languages or _ocr_language()
        try:
            text = pytesseract.image_to_string(image, lang=lang, config="--oem 1 --psm 6")
        except pytesseract.TesseractError:
            text = pytesseract.image_to_string(image, lang="eng", config="--oem 1 --psm 6")
        confidence = _mean_confidence(image, lang)
        return {"text": _clean_text(text), "confidence": confidence, "ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "confidence": None, "ok": False, "error": str(exc)}


def _prepare_image(image: "Image.Image") -> "Image.Image":
    """Skaliert grosse Scans herunter und verbessert den Kontrast."""
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    max_side = 2600
    if max(image.size) > max_side:
        ratio = max_side / max(image.size)
        image = image.resize((int(image.width * ratio), int(image.height * ratio)))
    return image


def _mean_confidence(image: "Image.Image", lang: str) -> float | None:
    try:
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    except Exception:
        return None
    values = []
    for raw in data.get("conf", []):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(value)
    return round(sum(values) / len(values), 2) if values else None


def _clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def image_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_text_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        log.warning("pypdf konnte %s nicht lesen: %s", path.name, exc)
        return []


def _render_scale() -> float:
    """Renderaufloesung aus den Einstellungen (DPI/72). Standard 150 DPI."""
    dpi = max(100, min(600, settings.get_int("ocr_dpi", 150)))
    return dpi / 72.0


def _render_pdf_pages(path: Path, max_pages: int, scale: float | None = None) -> list[bytes]:
    if scale is None:
        scale = _render_scale()
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        out: list[bytes] = []
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            buffer = io.BytesIO()
            pil.save(buffer, format="PNG", optimize=True)
            out.append(buffer.getvalue())
            page.close()
        pdf.close()
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("pypdfium2 konnte %s nicht rendern: %s", path.name, exc)
        return []


def process_pdf(path: Path, max_pages: int = 400, render_for_ocr: bool = True) -> DocumentResult:
    result = DocumentResult(kind="pdf")
    texts = _pdf_text_pages(path)
    result.meta["embedded_text_pages"] = sum(1 for t in texts if len(t.strip()) > MIN_TEXT_CHARS)

    need_ocr: list[int] = []
    for idx, text in enumerate(texts[:max_pages]):
        page = PageResult(page_number=idx + 1, text=_clean_text(text))
        if len(page.text) < MIN_TEXT_CHARS:
            need_ocr.append(idx)
        result.pages.append(page)

    if need_ocr and render_for_ocr:
        images = _render_pdf_pages(path, max_pages)
        for idx in need_ocr:
            if idx >= len(images):
                continue
            ocr = ocr_image_bytes(images[idx])
            page = result.pages[idx]
            page.image_bytes = images[idx]
            if ocr["ok"] and ocr["text"]:
                page.text = ocr["text"]
                page.confidence = ocr["confidence"]
                page.meta["ocr"] = "tesseract"
            else:
                page.meta["ocr_error"] = ocr.get("error")
                page.needs_review = True
            if page.confidence is not None and page.confidence < REVIEW_CONFIDENCE:
                page.needs_review = True

    for page in result.pages:
        if not page.text.strip():
            page.needs_review = True
    result.needs_review = any(p.needs_review for p in result.pages)
    return result


# ---------------------------------------------------------------------------
# Bilder und Text
# ---------------------------------------------------------------------------
def process_image(path: Path) -> DocumentResult:
    data = path.read_bytes()
    result = DocumentResult(kind="image")
    page = PageResult(page_number=1, image_bytes=data,
                      image_mime=f"image/{path.suffix.lstrip('.').lower()}")
    ocr = ocr_image_bytes(data)
    if ocr["ok"]:
        page.text = ocr["text"]
        page.confidence = ocr["confidence"]
        page.meta["ocr"] = "tesseract"
        if page.confidence is not None and page.confidence < REVIEW_CONFIDENCE:
            page.needs_review = True
    else:
        page.meta["ocr_error"] = ocr.get("error")
        page.needs_review = True
    if not page.text.strip():
        page.needs_review = True
    result.pages.append(page)
    result.needs_review = page.needs_review
    return result


def process_text(path: Path) -> DocumentResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    result = DocumentResult(kind="text")
    result.pages.append(PageResult(page_number=1, text=_clean_text(text)))
    return result


def process_container_choice(path: Path) -> DocumentResult:
    """Fallback fuer unbekannte Dateitypen: als Text oder OCR versuchen."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return process_image(path)
    try:
        head = path.read_bytes()[:512]
    except OSError:
        head = b""
    if head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff":
        return process_image(path)
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        if text.strip():
            result = DocumentResult(kind="text")
            result.pages.append(PageResult(page_number=1, text=_clean_text(text)))
            return result
    except (UnicodeDecodeError, OSError):
        pass
    result = DocumentResult(kind="unknown")
    result.meta["error"] = f"Unbekanntes Dateiformat: {suffix or 'ohne Endung'}"
    result.pages.append(PageResult(page_number=1, needs_review=True))
    result.needs_review = True
    return result


def process_html(path: Path) -> DocumentResult:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    result = DocumentResult(kind="html")
    result.pages.append(PageResult(page_number=1, text=_clean_text(text)))
    return result
