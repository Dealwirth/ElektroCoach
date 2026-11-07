"""Tests der Einstellungs-Verkabelung.

Diese Tests pruefen, dass die Einstellungen aus der Oberflaeche tatsaechlich
im Verhalten der Dienste ankommen - nicht nur gespeichert werden. Jeder Test
setzt einen Wert, ruft die betroffene Funktion auf und prueft die Wirkung.
"""

from __future__ import annotations

import asyncio

import pytest

from app import db
from app.config import settings
from app.services import ai_usage, exam, gemini, learning, ocr, ollama
from app.workers import import_worker


@pytest.fixture(autouse=True)
def _restore_settings():
    """Stellt die Laufzeiteinstellungen nach jedem Test wieder her."""
    with settings._lock:
        runtime = dict(settings._runtime)
        values = dict(settings._values)
    yield
    with settings._lock:
        settings._runtime = runtime
        settings._values = values


def test_get_float_liest_und_begrenzt_werte():
    settings.set_runtime("dedupe_threshold", 0.75)
    assert settings.get_float("dedupe_threshold", 0.92) == pytest.approx(0.75)
    # Unbekannter Schluessel liefert den Standardwert.
    assert settings.get_float("gibt_es_nicht", 1.25) == pytest.approx(1.25)


def test_ocr_dpi_wird_begrenzt():
    settings.set_runtime("ocr_dpi", 50)
    assert ocr._render_scale() == pytest.approx(100 / 72)
    settings.set_runtime("ocr_dpi", 9999)
    assert ocr._render_scale() == pytest.approx(600 / 72)
    settings.set_runtime("ocr_dpi", 150)
    assert ocr._render_scale() == pytest.approx(150 / 72)


def test_ocr_engine_kommt_aus_den_einstellungen():
    settings.set_runtime("ocr_engine", "trocr")
    assert ocr._engine_mode() == "trocr"
    settings.set_runtime("ocr_engine", "tesseract")
    assert ocr._engine_mode() == "tesseract"
    # Unbekannte Werte fallen auf "auto" zurueck.
    settings.set_runtime("ocr_engine", "quatsch")
    assert ocr._engine_mode() == "auto"


def test_ocr_postprocess_stufe_kommt_aus_den_einstellungen():
    settings.set_runtime("ocr_postprocess", "off")
    assert ocr._postprocess("30ma") == "30ma"
    settings.set_runtime("ocr_postprocess", "light")
    assert ocr._postprocess("30ma") == "30 mA"
    settings.set_runtime("ocr_postprocess", "standard")
    assert ocr._postprocess("30ma") == "30 mA"
    # Unbekannte Werte fallen auf "standard" zurueck.
    settings.set_runtime("ocr_postprocess", "quatsch")
    assert ocr._post_level() == "standard"


def test_exam_bestehensgrenze_kommt_aus_den_einstellungen():
    settings.set_runtime("exam_pass_percent", 80)
    assert settings.get_int("exam_pass_percent", 50) == 80
    # 75 % liegt unter der gesetzten Grenze von 80 %.
    assert exam.estimate_pass_probability(75.0, {}) > 0
    settings.set_runtime("exam_pass_percent", 50)


def test_gemini_tageslimit_begrenzt_nutzung():
    settings.set_runtime("gemini_daily_limit", 0)
    assert ai_usage.can_use("gemini") is False
    settings.set_runtime("gemini_daily_limit", 450)
    assert ai_usage.can_use("gemini") is True


def test_ai_timeout_kommt_aus_den_einstellungen():
    settings.set_runtime("ai_timeout_seconds", 12)
    assert gemini._timeout().read == pytest.approx(12.0)
    settings.set_runtime("ai_timeout_seconds", 60)


def test_ollama_modell_wird_uebernommen():
    settings.set_runtime("ollama_model", "qwen2.5:3b")
    assert ollama.model() == "qwen2.5:3b"
    settings.set_runtime("ollama_model", "llama3.2:3b")


def test_mark_unverified_schaltet_kennzeichnung_ab():
    settings.set_runtime("mark_unverified", False)
    stored = learning._store_question(
        {"prompt": "Testfrage?", "answer": "Antwort", "needs_review": True},
        None, [], "offline",
    )
    assert not stored["needs_review"]
    db.execute("DELETE FROM questions WHERE id = ?", (stored["id"],))

    settings.set_runtime("mark_unverified", True)
    stored = learning._store_question(
        {"prompt": "Testfrage 2?", "answer": "Antwort", "needs_review": True},
        None, [], "offline",
    )
    assert stored["needs_review"]
    db.execute("DELETE FROM questions WHERE id = ?", (stored["id"],))


def test_speicherbremse_liest_einstellungen():
    settings.set_runtime("import_memory_guard_mb", 123)
    assert import_worker._memory_guard_mb() == 123
    settings.set_runtime("import_memory_guard_mb", 400)


def test_import_mindestspeicher_ist_gesetzt():
    assert import_worker.MIN_FREE_BYTES >= 100 * 1024 * 1024


def test_import_nachlauf_ist_abschaltbar():
    settings.set_runtime("auto_analyze_after_import", False)
    assert settings.get_bool("auto_analyze_after_import", True) is False
    settings.set_runtime("auto_analyze_after_import", True)
    assert settings.get_bool("auto_analyze_after_import", True) is True


def test_ki_faellt_ohne_zugangsdaten_sauber_aus():
    settings.set_runtime("gemini_api_key", "")
    settings.set_runtime("ollama_enabled", False)
    result = asyncio.run(gemini.generate("Test"))
    assert result["ok"] is False
    assert "Schluessel" in result["error"]
