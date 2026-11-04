"""Tests fuer KI-Auswahl pro Anfrage, Webzugriff und Handschrift."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from elektrocoach.app.services import ai_router, handwriting, websearch


# ---------------------------------------------------------------------------
# KI-Auswahl pro Anfrage
# ---------------------------------------------------------------------------
def test_normalise_provider_kennt_alle_schreibweisen():
    assert ai_router._normalise_provider(None) == "auto"
    assert ai_router._normalise_provider("") == "auto"
    assert ai_router._normalise_provider("OLLAMA") == "ollama"
    assert ai_router._normalise_provider("local") == "ollama"
    assert ai_router._normalise_provider("cloud") == "gemini"
    assert ai_router._normalise_provider("gemini") == "gemini"
    assert ai_router._normalise_provider("local_only") == "local_only"
    assert ai_router._normalise_provider("quatsch") == "auto"


def test_provider_order_auto_bevorzugt_lokal_bei_einfacher_aufgabe():
    assert ai_router._provider_order("auto", "auto", True, False) == ["ollama", "gemini"]


def test_provider_order_auto_bevorzugt_cloud_bei_schwerer_aufgabe():
    assert ai_router._provider_order("auto", "auto", False, False) == ["gemini", "ollama"]


def test_provider_order_wahl_weicht_aus():
    # Ohne strikte Einstellung darf die gewaehlte KI ausweichen.
    assert ai_router._provider_order("auto", "ollama", True, False) == ["ollama", "gemini"]
    assert ai_router._provider_order("auto", "gemini", True, False) == ["gemini", "ollama"]


def test_provider_order_strikt_bleibt_bei_einer_quelle():
    assert ai_router._provider_order("auto", "ollama", True, True) == ["ollama"]
    assert ai_router._provider_order("auto", "gemini", True, True) == ["gemini"]
    assert ai_router._provider_order("auto", "local_only", True, False) == ["ollama"]
    assert ai_router._provider_order("auto", "cloud_only", True, False) == ["gemini"]


def test_provider_order_modus_hat_vorrang():
    # Der globale Modus schlaegt die Auswahl pro Anfrage.
    assert ai_router._provider_order("local_only", "gemini", True, False) == ["ollama"]
    assert ai_router._provider_order("cloud_only", "ollama", True, False) == ["gemini"]


def test_complete_waehlt_ollama_und_meldet_provider(monkeypatch):
    async def fake_chat(*args, **kwargs):
        return {"ok": True, "text": "lokal", "provider": "ollama", "model": "llama3.2:3b"}

    monkeypatch.setattr(ai_router.ollama, "is_enabled", lambda: True)
    monkeypatch.setattr(ai_router.ollama, "chat", fake_chat)

    result = asyncio.run(ai_router.complete("Test", provider="ollama"))
    assert result["ok"] is True
    assert result["provider"] == "ollama"
    assert result["requested"] == "ollama"
    assert result["external"] is False


def test_complete_gemini_strikt_weicht_nicht_aus(monkeypatch):
    monkeypatch.setattr(ai_router, "mode", lambda: "auto")
    monkeypatch.setattr(ai_router.ollama, "is_enabled", lambda: True)
    monkeypatch.setattr(ai_router.gemini, "is_configured", lambda: True)

    calls: list[str] = []

    async def fake_gemini(*args, **kwargs):
        calls.append("gemini")
        return {"ok": False, "error": "503 ueberlastet", "provider": "gemini"}

    async def fake_chat(*args, **kwargs):
        calls.append("ollama")
        return {"ok": True, "text": "lokal", "provider": "ollama"}

    monkeypatch.setattr(ai_router.gemini, "generate", fake_gemini)
    monkeypatch.setattr(ai_router.ollama, "chat", fake_chat)

    result = asyncio.run(ai_router.complete("Test", provider="cloud_only"))
    assert result["ok"] is False
    assert calls == ["gemini"]


# ---------------------------------------------------------------------------
# Webzugriff
# ---------------------------------------------------------------------------
def test_needs_web_nur_bei_aktuellen_angaben():
    assert websearch.needs_web("Was ist ein RCD?", "auto") is False
    assert websearch.needs_web("Welche DIN VDE gilt aktuell?", "auto") is True
    assert websearch.needs_web("Was ist ein RCD?", "on") is True
    assert websearch.needs_web("Welche DIN VDE gilt aktuell?", "off") is False


def test_is_authoritative_erkennt_verlaessliche_adressen():
    assert websearch._is_authoritative("https://de.wikipedia.org/wiki/RCD") is True
    assert websearch._is_authoritative("https://www.vde.com/de/fnn") is True
    assert websearch._is_authoritative("https://bafa.de/foerderung") is True
    assert websearch._is_authoritative("https://random-blog.example.com/rcd") is False


def test_relevant_filtert_fremde_treffer():
    assert websearch._relevant("Drehstrommotor Bemessungsstrom", "Der Drehstrommotor hat einen Bemessungsstrom.") is True
    assert websearch._relevant("Drehstrommotor Bemessungsstrom", "Rezept fuer Kuchen mit Aepfeln.") is False


def test_build_context_nennt_die_quelle():
    context = websearch.build_context([
        {"title": "RCD", "url": "https://de.wikipedia.org/wiki/RCD", "text": "Fehlerstrom."}
    ])
    assert "[WEB-1]" in context
    assert "https://de.wikipedia.org/wiki/RCD" in context


def test_sources_listet_titel_und_adresse():
    out = websearch.sources([{"title": "RCD", "url": "https://x", "source": "wikipedia"}])
    assert out == [{"title": "RCD", "url": "https://x", "kind": "wikipedia"}]


def test_strip_html_entfernt_auszeichnung():
    assert websearch._strip_html("<p>Hallo <b>Welt</b></p>").strip() == "Hallo Welt"


def test_user_agent_has_contact_info() -> None:
    """Wikimedia lehnt Anfragen ohne Kontaktadresse mit HTTP 403 ab."""
    agent = websearch.USER_AGENT
    assert "http" in agent, "Kontaktadresse im User-Agent fehlt"
    assert "/" in agent.split("(")[0], "Versionskennung im User-Agent fehlt"


# ---------------------------------------------------------------------------
# Handschrift
# ---------------------------------------------------------------------------
def _png_data_url() -> str:
    raw = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
    return f"data:image/png;base64,{raw}"


def test_decode_image_liest_data_url():
    image = handwriting._decode_image(_png_data_url())
    assert image is not None
    assert image["mime"] == "image/png"


def test_decode_image_lehnt_fremdes_format_ab():
    assert handwriting._decode_image("nicht-base64") is None
    assert handwriting._decode_image("") is None


def test_parse_liest_json_auch_mit_text_drumherum():
    raw = 'Hier das Ergebnis:\n{"text": "I = 12,7 A", "confidence": 0.9, "unleserlich": false}'
    parsed = handwriting._parse(raw)
    assert parsed is not None
    assert parsed["text"] == "I = 12,7 A"
    assert parsed["confidence"] == 0.9


def test_transcribe_bevorzugt_browser_text():
    result = asyncio.run(handwriting.transcribe(_png_data_url(), browser_text="U = R * I"))
    assert result["ok"] is True
    assert result["method"] == "browser"
    assert result["text"] == "U = R * I"


def test_transcribe_ohne_freigabe_meldet_klar(monkeypatch):
    monkeypatch.setattr(handwriting, "available", lambda: False)
    result = asyncio.run(handwriting.transcribe(_png_data_url()))
    assert result["ok"] is False
    assert result["method"] == "offline"
    assert "hint" in result


def test_transcribe_ohne_schluessel_nennt_die_ursache(monkeypatch):
    """Ohne Schluessel muss der Hinweis den Schluessel nennen, nicht die Bilder."""
    monkeypatch.setattr(handwriting, "available", lambda: False)
    monkeypatch.setattr(handwriting.gemini, "is_configured", lambda: False)
    result = asyncio.run(handwriting.transcribe(_png_data_url()))
    assert result["ok"] is False
    assert "Gemini-Schluessel" in result["error"]
    assert "Bilder" not in result["hint"]


def test_transcribe_ohne_bildfreigabe_nennt_die_option(monkeypatch):
    monkeypatch.setattr(handwriting, "available", lambda: False)
    monkeypatch.setattr(handwriting.gemini, "is_configured", lambda: True)
    result = asyncio.run(handwriting.transcribe(_png_data_url()))
    assert result["ok"] is False
    assert "Bilder" in result["error"]
    assert "Bilder an die Cloud senden" in result["hint"]


def test_transcribe_nutzt_gemini(monkeypatch):
    monkeypatch.setattr(handwriting, "available", lambda: True)

    async def fake_generate(*args, **kwargs):
        return {
            "ok": True,
            "text": json.dumps({"text": "I = P / (√3 · U · cos φ)", "confidence": 0.85}),
            "model": "gemini-flash-latest",
        }

    monkeypatch.setattr(handwriting.gemini, "generate", fake_generate)
    result = asyncio.run(handwriting.transcribe(_png_data_url(), hint="Berechne den Strom."))
    assert result["ok"] is True
    assert result["method"] == "gemini"
    assert "√3" in result["text"]
