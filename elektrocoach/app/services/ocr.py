"""OCR und Dokumentverarbeitung.

Pipeline je Datei:
  * PDF   -> eingebetteter Text (pypdf); leere/gescannte Seiten werden mit
             pypdfium2 gerendert und per OCR gelesen.
  * Bild  -> Handschrift-OCR (TrOCR, lokal) mit Rueckfall auf Tesseract;
             optional Gemini-Vision.
  * Text  -> direkt uebernommen.

Reihenfolge der Texterkennung (Einstellung ``ocr_engine``):
  * ``auto``    - TrOCR fuer Handschrift, Tesseract als Rueckfall/Ergaenzung.
  * ``trocr``   - nur TrOCR (Tesseract nur, wenn TrOCR nicht verfuegbar ist).
  * ``tesseract`` - nur Tesseract.

Ergebnis pro Seite: Text, Konfidenz, Kennzeichnung "needs_review".
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings
from . import handwriting, handwriting_post, handwriting_vision

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


def _engine_mode() -> str:
    mode = str(settings.get("ocr_engine", "auto")).lower()
    return mode if mode in {"auto", "trocr", "tesseract"} else "auto"


def _post_level() -> str:
    level = str(settings.get("ocr_postprocess", "standard")).lower()
    return level if level in {"off", "light", "standard", "formula"} else "standard"


def _postprocess(text: str) -> str:
    return handwriting_post.postprocess(text, _post_level())


def _vision_enabled() -> bool:
    return bool(handwriting_vision.is_enabled() and settings.get_bool("ollama_enabled", False))


def _run_vision(image: "Image.Image", draft: str) -> dict[str, Any] | None:
    """Ruft das lokale Bildmodell auf, auch aus einem reinen Worker-Thread.

    Der Import-Worker ist synchron. Liegt kein Ereignisschleifen-Kontext vor,
    wird fuer den Aufruf eine eigene Schleife angelegt.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(handwriting_vision.transcribe(image, draft))
    # Innerhalb einer laufenden Schleife (z. B. TestClient) in einem eigenen
    # Thread ausfuehren, damit die Schleife nicht blockiert wird.
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = asyncio.run(handwriting_vision.transcribe(image, draft))
        except Exception as exc:  # noqa: BLE001
            box["error"] = str(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "result" in box:
        return box["result"]
    return {"ok": False, "text": "", "error": box.get("error"), "model": None}


def _refine_model() -> str | None:
    """Textmodell fuer die Formelkorrektur (leer = Standard-Textmodell)."""
    name = str(settings.get("ollama_refine_model", "") or "").strip()
    return name or None


def _run_refine(text: str) -> dict[str, Any] | None:
    """Berichtigt Formelzeichen mit dem Textmodell, auch aus einem Thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(handwriting_vision.refine_formulas(text, model_name=_refine_model()))
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = asyncio.run(
                handwriting_vision.refine_formulas(text, model_name=_refine_model())
            )
        except Exception as exc:  # noqa: BLE001
            box["error"] = str(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "result" in box:
        return box["result"]
    return {"ok": False, "text": text, "error": box.get("error")}


def _vision_stage(image: "Image.Image", base: dict[str, Any]) -> dict[str, Any]:
    """Ersetzt das Ergebnis durch die Bildmodell-Lesung, wenn diese taugt.

    Das Bildmodell erkennt Rechenwege und Formeln deutlich besser als TrOCR.
    Es wird nur uebernommen, wenn es erkennbar Text liefert; sonst bleibt der
    bisherige Stand erhalten.
    """
    if not _vision_enabled():
        return base
    # Der TrOCR-Entwurf ist bei schwerer Handschrift oft unbrauchbar und zieht
    # das Bildmodell dann nach unten. Er wird daher nur auf Wunsch mitgegeben.
    draft = base.get("text", "") if settings.get_bool("ocr_vision_use_draft", False) else ""
    # Das Bildmodell braucht dieselbe zugeschnittene, gerade gestellte Seite wie
    # TrOCR. Auf dem rohen Screenshot (dunkler Rand, schraeg) liest es schlecht.
    page = image
    try:
        page = handwriting.preprocess(image)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vorbereitung fuer das Bildmodell fehlgeschlagen: %s", exc)
        page = image
    try:
        vision = _run_vision(page, draft)
    except Exception as exc:  # noqa: BLE001 - Vision ist eine Zugabe, kein Muss
        log.warning("Bildmodell-Aufruf fehlgeschlagen: %s", exc)
        return base
    if not vision or not vision.get("ok") or not str(vision.get("text", "")).strip():
        if vision and vision.get("error"):
            log.info("Bildmodell lieferte nichts: %s", vision.get("error"))
        return base
    text = _postprocess(_clean_text(str(vision["text"])))
    if len(text) < 3:
        return base

    # Dritte Stufe: Formelzeichen berichtigen. Nur wenn Zahlen unveraendert
    # bleiben; sonst bleibt die Bildmodell-Lesung stehen.
    refined_model = None
    if handwriting_vision.refine_enabled():
        try:
            refined = _run_refine(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Formelkorrektur fehlgeschlagen: %s", exc)
            refined = None
        if refined and refined.get("ok") and str(refined.get("text", "")).strip():
            candidate = _postprocess(_clean_text(str(refined["text"])))
            if len(candidate) >= 3:
                text = candidate
                refined_model = refined.get("model")

    return {
        "text": text,
        "confidence": base.get("confidence"),
        "engine": "vision",
        "error": None,
        "trocr_lines": base.get("trocr_lines"),
        "vision_model": vision.get("model"),
        "refine_model": refined_model,
        "draft_engine": base.get("engine"),
    }


def recognize_image(image: "Image.Image", data: bytes | None = None) -> dict[str, Any]:
    """Erkennt Text auf einem Seitenbild mit der besten verfuegbaren Engine.

    Rueckgabe: ``{text, confidence, engine, error, trocr_lines}``. Handschrift
    liest TrOCR; Tesseract bleibt Rueckfall und wird bei Bedarf kombiniert.
    Ist ein lokales Bildmodell eingerichtet, liest es die Seite danach noch
    einmal und korrigiert Formeln und Rechenwege.
    """
    mode = _engine_mode()
    trocr_ready = mode != "tesseract" and handwriting.available()

    trocr: dict[str, Any] | None = None
    if trocr_ready:
        trocr = handwriting.transcribe_image(image)

    # Reines TrOCR: Ergebnis uebernehmen, wenn brauchbarer Text entsteht.
    if trocr and trocr.get("ok") and trocr.get("text", "").strip():
        text = _postprocess(_clean_text(trocr["text"]))
        return _vision_stage(image, {
            "text": text,
            "confidence": trocr.get("confidence"),
            "engine": "trocr",
            "error": None,
            "trocr_lines": trocr.get("lines"),
        })

    if mode == "trocr" and trocr and not trocr.get("ok"):
        # Ausdruecklich nur TrOCR gewuenscht, aber nicht einsatzbereit.
        return {
            "text": "",
            "confidence": None,
            "engine": "trocr",
            "error": trocr.get("error"),
            "trocr_lines": 0,
        }

    # Tesseract (Rueckfall oder ausdruecklich gewaehlt).
    payload = data
    if payload is None:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        payload = buffer.getvalue()
    tesseract = ocr_image_bytes(payload)
    if tesseract.get("ok"):
        return _vision_stage(image, {
            "text": _postprocess(_clean_text(tesseract.get("text", ""))),
            "confidence": tesseract.get("confidence"),
            "engine": "tesseract",
            "error": None,
            "trocr_lines": None,
        })
    # Keine Texterkennung, aber ein Bildmodell kann trotzdem lesen.
    staged = _vision_stage(image, {
        "text": "",
        "confidence": None,
        "engine": "none",
        "error": tesseract.get("error") or (trocr or {}).get("error"),
        "trocr_lines": None,
    })
    if staged.get("engine") == "vision":
        return staged
    return {
        "text": "",
        "confidence": None,
        "engine": "tesseract",
        "error": staged.get("error"),
        "trocr_lines": None,
    }


def recognize_bytes(data: bytes) -> dict[str, Any]:
    """Wie :func:`recognize_image`, aber aus rohen Bilddaten."""
    if not _HAVE_TESSERACT:
        # Ohne Pillow/Tesseract bleibt nur TrOCR (oeffnet selbst).
        result = handwriting.transcribe_bytes(data)
        result.setdefault("engine", "trocr")
        result.setdefault("trocr_lines", result.get("lines"))
        return result
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "confidence": None, "engine": "none",
                "error": f"Bild nicht lesbar: {exc}", "trocr_lines": None}
    return recognize_image(image, data)


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


def _empty_document_result(path: Path, kind: str, message: str) -> DocumentResult:
    """Ergebnis fuer eine Datei, die technisch lesbar, aber inhaltlich leer ist."""
    result = DocumentResult(kind=kind)
    result.meta["error"] = message
    result.meta["empty"] = True
    page = PageResult(page_number=1, needs_review=True)
    page.meta["error"] = message
    result.pages.append(page)
    result.needs_review = True
    return result


def process_pdf(path: Path, max_pages: int = 400, render_for_ocr: bool = True) -> DocumentResult:
    result = DocumentResult(kind="pdf")
    texts = _pdf_text_pages(path)
    result.meta["embedded_text_pages"] = sum(1 for t in texts if len(t.strip()) > MIN_TEXT_CHARS)

    # Beschaedigte Dateien liefern keine Seiten. Das darf nicht als
    # "fertig, 0 Seiten" durchgehen, sondern muss als Fehler sichtbar werden.
    if not texts and path.stat().st_size == 0:
        return _empty_document_result(path, "pdf", "Datei ist leer (0 Byte)")

    if not texts and render_for_ocr:
        # Reines Scan-PDF: pypdf findet keinen Text. Alle Seiten rendern und
        # per OCR lesen, statt das Dokument mit 0 Seiten abzulegen.
        images = _render_pdf_pages(path, max_pages)
        if not images:
            return _empty_document_result(
                path, "pdf", "PDF ist beschaedigt oder hat keine lesbaren Seiten"
            )
        result.meta["scanned"] = True
        for index, image in enumerate(images, start=1):
            page = PageResult(page_number=index, image_bytes=image)
            ocr = recognize_bytes(image)
            if ocr["text"]:
                page.text = ocr["text"]
                page.confidence = ocr["confidence"]
                page.meta["ocr"] = ocr["engine"]
            else:
                page.meta["ocr_error"] = ocr.get("error")
            if page.confidence is not None and page.confidence < REVIEW_CONFIDENCE:
                page.needs_review = True
            if not page.text.strip():
                page.needs_review = True
            result.pages.append(page)
        result.needs_review = any(p.needs_review for p in result.pages)
        return result

    if not texts:
        return _empty_document_result(
            path, "pdf", "PDF ist beschaedigt oder hat keine lesbaren Seiten"
        )

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
            ocr = recognize_bytes(images[idx])
            page = result.pages[idx]
            page.image_bytes = images[idx]
            if ocr["text"]:
                page.text = ocr["text"]
                page.confidence = ocr["confidence"]
                page.meta["ocr"] = ocr["engine"]
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
    ocr = recognize_bytes(data)
    if ocr["text"]:
        page.text = ocr["text"]
        page.confidence = ocr["confidence"]
        page.meta["ocr"] = ocr["engine"]
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
    if not text.strip():
        return _empty_document_result(path, "text", "Textdatei ist leer")
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
