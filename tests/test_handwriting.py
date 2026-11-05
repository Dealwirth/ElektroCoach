"""Tests fuer die lokale Handschrifterkennung (TrOCR).

Die Tests pruefen Segmentierung, Nachbearbeitung und die Auswahl der Engine.
Der Modell-Durchlauf wird nur ausgefuehrt, wenn die ONNX-Modelldateien
vorhanden sind (sonst uebersprungen).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.services import handwriting, handwriting_post, ocr

REPO_MODEL_DIR = Path(__file__).resolve().parents[1] / "elektrocoach" / "models" / "trocr-de"


@pytest.fixture(autouse=True)
def _restore_settings():
    with settings._lock:
        runtime = dict(settings._runtime)
        values = dict(settings._values)
    yield
    with settings._lock:
        settings._runtime = runtime
        settings._values = values


def _lines_image(count: int = 3) -> Image.Image:
    """Bild mit mehreren getrennten Textzeilen (schwarze Balken)."""
    image = Image.new("L", (800, 60 * count + 40), color=255)
    draw = ImageDraw.Draw(image)
    for index in range(count):
        top = 30 + index * 60
        draw.rectangle([40, top, 740, top + 28], fill=0)
    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Segmentierung
# ---------------------------------------------------------------------------
def test_segment_lines_findet_alle_zeilen():
    lines = handwriting.segment_lines(_lines_image(3))
    assert len(lines) == 3


def test_segment_lines_einzelne_zeile():
    lines = handwriting.segment_lines(_lines_image(1))
    assert len(lines) == 1


def test_segment_lines_leeres_bild_liefert_das_bild():
    blank = Image.new("RGB", (400, 300), color=255)
    lines = handwriting.segment_lines(blank)
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Nachbearbeitung
# ---------------------------------------------------------------------------
def test_einheiten_werden_vereinheitlicht():
    assert handwriting_post.fix_units("230v") == "230 V"
    assert handwriting_post.fix_units("30ma") == "30 mA"
    assert handwriting_post.fix_units("16 a") == "16 A"
    assert handwriting_post.fix_units("1,5mm2") == "1,5 mm²"


def test_akronyme_werden_grossgeschrieben():
    assert handwriting_post.fix_acronyms("der rcd und der vde") == "der RCD und der VDE"


def test_fachbegriffe_werden_korrigiert():
    # Ein Buchstabendreher wird auf den Fachbegriff gezogen.
    assert handwriting_post.correct_terms("Leitunsschutzschalter") == "Leitungsschutzschalter"
    # Kurze, unbekannte Woerter bleiben unangetastet.
    assert handwriting_post.correct_terms("und der mit") == "und der mit"


def test_formeln_werden_normalisiert():
    assert handwriting_post.normalize_formulas("1.5 A") == "1,5 A"
    assert "×" in handwriting_post.normalize_formulas("2x3")


def test_latex_brueche_werden_lesbar():
    result = handwriting_post.strip_latex(r"R = \frac{U}{I}")
    assert result == "R = U / I"


def test_latex_zeichen_werden_uebersetzt():
    result = handwriting_post.strip_latex(r"U = R \cdot I = 0.5 \Omega")
    assert "·" in result and "Ω" in result


def test_latex_hochzahl_und_einheit():
    result = handwriting_post.postprocess(r"A = \frac{0.0278 \cdot 2 \cdot m^2}{0.3 \cdot 2}", "formula")
    assert "mm" not in result or "mm²" in result
    assert "m²" in result
    assert "," in result  # Dezimalkomma statt Punkt


def test_postprocess_formula_ohne_latex_bleibt_stabil():
    assert handwriting_post.postprocess("Leitung 16 A", "formula") == "Leitung 16 A"


def test_tausenderpunkt_bleibt_erhalten():
    assert handwriting_post.normalize_formulas("1.000 V") == "1.000 V"


def test_postprocess_stufen():
    assert handwriting_post.postprocess("16a", "off") == "16a"
    assert handwriting_post.postprocess("16a", "light") == "16 A"
    assert handwriting_post.postprocess("", "standard") == ""


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def test_status_meldet_fehlende_modelle(tmp_path):
    status = handwriting.status() if not REPO_MODEL_DIR.is_dir() else None
    missing = handwriting.missing_files(tmp_path)
    assert set(missing) == set(handwriting.REQUIRED_FILES)
    if status is not None:
        assert status["available"] is False


def test_model_dir_respektiert_umgebungsvariable(monkeypatch):
    monkeypatch.setenv(handwriting.MODEL_ENV, "/tmp/eindeutig-trocr")
    assert str(handwriting.model_dir()) == "/tmp/eindeutig-trocr"


# ---------------------------------------------------------------------------
# Engine-Auswahl
# ---------------------------------------------------------------------------
def test_recognize_image_faellt_auf_tesseract_zurueck(monkeypatch):
    monkeypatch.setattr(handwriting, "available", lambda: False)
    monkeypatch.setattr(
        ocr, "ocr_image_bytes",
        lambda data: {"ok": True, "text": "rcd mit 30ma", "confidence": 71.0},
    )
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "tesseract"
    assert result["text"] == "RCD mit 30 mA"
    assert result["confidence"] == 71.0


def test_recognize_image_nutzt_trocr_wenn_verfuegbar(monkeypatch):
    monkeypatch.setattr(handwriting, "available", lambda: True)
    monkeypatch.setattr(
        handwriting, "transcribe_image",
        lambda image: {"ok": True, "text": "16a leitung", "lines": 1,
                       "confidence": 88.0, "error": None},
    )
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "trocr"
    assert result["text"] == "16 A Leitung"
    assert result["confidence"] == 88.0


def test_ocr_engine_tesseract_erzwingt_tesseract(monkeypatch):
    settings.set_runtime("ocr_engine", "tesseract")
    monkeypatch.setattr(handwriting, "available", lambda: True)
    called = {"trocr": False}

    def _fail(image):  # pragma: no cover - darf nicht aufgerufen werden
        called["trocr"] = True
        return {"ok": True, "text": "falsch", "lines": 1, "confidence": 99.0, "error": None}

    monkeypatch.setattr(handwriting, "transcribe_image", _fail)
    monkeypatch.setattr(
        ocr, "ocr_image_bytes",
        lambda data: {"ok": True, "text": "echt", "confidence": 50.0},
    )
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "tesseract"
    assert called["trocr"] is False


def test_ocr_engine_trocr_ohne_modell_meldet_fehler(monkeypatch):
    settings.set_runtime("ocr_engine", "trocr")
    monkeypatch.setattr(handwriting, "available", lambda: True)
    monkeypatch.setattr(
        handwriting, "transcribe_image",
        lambda image: {"ok": False, "text": "", "lines": 0, "confidence": None,
                       "error": "Modelldateien fehlen"},
    )
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "trocr"
    assert result["text"] == ""
    assert result["error"]


# ---------------------------------------------------------------------------
# Bildmodell (Vision) als zweite Stufe
# ---------------------------------------------------------------------------
def test_vision_stage_uebernimmt_bildmodell(monkeypatch):
    from app.services import handwriting_vision

    settings.set_runtime("ocr_engine", "auto")
    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("ocr_use_vision_model", True)
    monkeypatch.setattr(handwriting, "available", lambda: True)
    monkeypatch.setattr(
        handwriting, "transcribe_image",
        lambda image: {"ok": True, "text": "R = h l A", "lines": 1,
                       "confidence": 60.0, "error": None},
    )

    async def _fake_transcribe(image, draft=None, model_name=None):
        return {"ok": True, "text": r"R = \frac{0,4 \cdot 2}{0,1} = 375 \Omega",
                "model": "qwen2.5vl:3b", "error": None}

    monkeypatch.setattr(handwriting_vision, "transcribe", _fake_transcribe)
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "vision"
    assert "375" in result["text"]
    assert "Ω" in result["text"]
    assert "\\frac" not in result["text"]


def test_vision_stage_faellt_bei_fehler_zurueck(monkeypatch):
    from app.services import handwriting_vision

    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("ocr_use_vision_model", True)
    monkeypatch.setattr(handwriting, "available", lambda: True)
    monkeypatch.setattr(
        handwriting, "transcribe_image",
        lambda image: {"ok": True, "text": "16a leitung", "lines": 1,
                       "confidence": 80.0, "error": None},
    )

    async def _fail(image, draft=None, model_name=None):
        raise RuntimeError("Ollama nicht erreichbar")

    monkeypatch.setattr(handwriting_vision, "transcribe", _fail)
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "trocr"
    assert result["text"] == "16 A Leitung"


def test_vision_aus_laesst_trocr_ergebnis_unveraendert(monkeypatch):
    settings.set_runtime("ocr_use_vision_model", False)
    monkeypatch.setattr(handwriting, "available", lambda: True)
    monkeypatch.setattr(
        handwriting, "transcribe_image",
        lambda image: {"ok": True, "text": "16a", "lines": 1,
                       "confidence": 80.0, "error": None},
    )
    result = ocr.recognize_image(_lines_image(1))
    assert result["engine"] == "trocr"


# ---------------------------------------------------------------------------
# Endpunkt
# ---------------------------------------------------------------------------
def test_system_info_enthaelt_handschrift_status(client):
    response = client.get("/api/system/info")
    assert response.status_code == 200
    body = response.json()
    assert "handwriting" in body
    assert "available" in body["handwriting"]
    assert "dependencies" in body["handwriting"]
    assert "vision" in body["handwriting"]
    assert "model" in body["handwriting"]["vision"]


# ---------------------------------------------------------------------------
# Echter Modell-Durchlauf (nur mit Modelldateien)
# ---------------------------------------------------------------------------
model_required = pytest.mark.skipif(
    not REPO_MODEL_DIR.is_dir(), reason="TrOCR-Modell nicht vorhanden"
)


@model_required
def test_echtes_modell_liest_eine_zeile(monkeypatch):
    monkeypatch.setenv(handwriting.MODEL_ENV, str(REPO_MODEL_DIR))
    handwriting.reset()
    image = Image.new("RGB", (900, 200), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((30, 80), "Leitung 16 A", fill=0)
    result = handwriting.transcribe_image(image)
    assert result["ok"] is True
    assert result["lines"] >= 1
    assert result["confidence"] is not None


# ---------------------------------------------------------------------------
# Zeilenweises Lesen (Bildmodell)
# ---------------------------------------------------------------------------
def test_line_image_skaliert_kleine_zeile():
    from app.services import handwriting_vision

    line = Image.new("RGB", (400, 40), color=255)
    scaled = handwriting_vision._line_image(line)
    assert scaled.height == handwriting_vision.LINE_TARGET_HEIGHT
    assert scaled.width == 400 * handwriting_vision.LINE_TARGET_HEIGHT // 40


def test_line_image_laesst_grosse_zeile_unveraendert():
    from app.services import handwriting_vision

    line = Image.new("RGB", (500, 400), color=255)
    assert handwriting_vision._line_image(line).size == (500, 400)


def test_line_slices_teilt_ueberlange_zeile():
    from app.services import handwriting_vision

    line = Image.new("RGB", (handwriting_vision.LINE_MAX_WIDTH * 2, 256), color=255)
    parts = handwriting_vision._line_slices(line)
    assert len(parts) >= 2
    assert all(part.width <= handwriting_vision.LINE_MAX_WIDTH * 1.2 for part in parts)


def test_line_slices_laesst_kurze_zeile():
    from app.services import handwriting_vision

    line = Image.new("RGB", (600, 256), color=255)
    assert len(handwriting_vision._line_slices(line)) == 1


def test_merge_lines_entfernt_doppelte_naht():
    from app.services import handwriting_vision

    merged = handwriting_vision._merge_lines(["R = 1", "R = 1", "U = 2"])
    assert merged == "R = 1\nU = 2"
