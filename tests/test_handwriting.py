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
# Endpunkt
# ---------------------------------------------------------------------------
def test_system_info_enthaelt_handschrift_status(client):
    response = client.get("/api/system/info")
    assert response.status_code == 200
    body = response.json()
    assert "handwriting" in body
    assert "available" in body["handwriting"]
    assert "dependencies" in body["handwriting"]


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
