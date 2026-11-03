"""Tests der KI-Anbindung, der Ausweichlogik und des Verhaltens ohne KI.

Die Tests laufen ohne echte API-Aufrufe: sie pruefen die Ausweichkette, die
Kontingentverwaltung und die Fehlerbehandlung mit einem Mock-Transport.
"""

from __future__ import annotations

import asyncio

import pytest

from app import db
from app.config import settings
from app.services import ai_router, ai_usage, gemini, ollama


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_ai_state():
    settings.set_runtime("ai_mode", "auto")
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("gemini_api_key", "")
    gemini._degraded.clear()
    db.execute("DELETE FROM ai_usage")
    yield
    settings.set_runtime("ai_mode", "auto")
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("gemini_api_key", "")
    gemini._degraded.clear()


def test_ollama_health_ohne_aktivierung():
    result = _run(ollama.health())
    assert result["available"] is False
    assert result["reason"] == "deaktiviert"


def test_ollama_empfohlene_modelle_fuer_raspberry_pi():
    names = {m["name"] for m in ollama.RECOMMENDED_MODELS}
    assert "llama3.2:3b" in names
    assert "phi4-mini:3.8b" in names
    for model in ollama.RECOMMENDED_MODELS:
        # Alle empfohlenen Modelle muessen in 8 GB RAM passen.
        assert model["size_gb"] <= 4.0


def test_gemini_ohne_schluessel_meldet_fehler():
    result = _run(gemini.generate("Test"))
    assert result["ok"] is False
    assert "API-Schluessel" in result["error"]


def test_gemini_health_ohne_schluessel():
    result = _run(gemini.health())
    assert result["available"] is False


def test_gemini_kontingent_erschoepft_blockiert_anfragen():
    settings.set_runtime("gemini_api_key", "test-key")
    # Kontingent kuenstlich aufbrauchen.
    for _ in range(ai_usage.DAILY_LIMITS["gemini"]):
        ai_usage.record("gemini", "gemini-2.5-flash", "chat", True)
    assert ai_usage.can_use("gemini") is False
    result = _run(gemini.generate("Test"))
    assert result["ok"] is False
    assert result.get("quota_exhausted") is True


def test_gemini_429_wird_als_kontingent_gewertet(monkeypatch):
    settings.set_runtime("gemini_api_key", "test-key")

    class FakeResponse:
        status_code = 429
        text = "RESOURCE_EXHAUSTED"

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)
    result = _run(gemini.generate("Test", retries=0))
    assert result["ok"] is False
    assert result.get("quota_exhausted") is True


async def _no_sleep(_seconds):
    return None


def test_gemini_erfolgreiche_antwort_wird_gelesen(monkeypatch):
    settings.set_runtime("gemini_api_key", "test-key")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Der RCD schuetzt."}]}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    result = _run(gemini.generate("Test"))
    assert result["ok"] is True
    assert result["text"] == "Der RCD schuetzt."


def test_gemini_blockierte_antwort_wird_erkannt(monkeypatch):
    settings.set_runtime("gemini_api_key", "test-key")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    result = _run(gemini.generate("Test"))
    assert result["ok"] is False
    assert "blockiert" in result["error"]


def test_router_ohne_ki_meldet_klaren_fehler():
    result = _run(ai_router.complete("Frage"))
    assert result["ok"] is False
    assert "Keine KI erreichbar" in result["error"] or "deaktiviert" in result["error"]


def test_gemini_wechselt_bei_abgestelltem_modell(monkeypatch):
    """Google stellt Modelle ab (HTTP 404). Die App muss selbst ein
    nutzbares Modell finden und dieses merken."""
    settings.set_runtime("gemini_api_key", "test-key")
    settings.set_runtime("gemini_text_model", "gemini-2.5-flash")
    settings.set_runtime("ai_max_retries", 0)
    seen: list[str] = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            name = url.split("/models/", 1)[1].split(":", 1)[0]
            seen.append(name)
            if name == "gemini-2.5-flash":
                return FakeResponse(404, {"error": {"code": 404, "message": "no longer available"}})
            return FakeResponse(
                200, {"candidates": [{"content": {"parts": [{"text": "Antwort"}]}}]}
            )

    async def fake_list():
        return {
            "available": True,
            "models": ["gemini-2.5-flash", "gemini-3.5-flash"],
            "free_tier_candidates": ["gemini-3.5-flash"],
        }

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gemini, "list_models", fake_list)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)
    gemini.invalidate_model_cache()

    result = _run(gemini.generate("Test"))
    assert result["ok"] is True
    assert result["model"] != "gemini-2.5-flash"
    assert "gemini-2.5-flash" in seen
    assert settings.get("gemini_text_model") == result["model"]


def test_gemini_wechselt_bei_ueberlastetem_modell(monkeypatch):
    """HTTP 503 (Modell ueberlastet) darf nicht zum Abbruch fuehren, solange
    ein anderes Modell antwortet."""
    settings.set_runtime("gemini_api_key", "test-key")
    settings.set_runtime("gemini_text_model", "gemini-flash-latest")
    settings.set_runtime("ai_max_retries", 0)

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            name = url.split("/models/", 1)[1].split(":", 1)[0]
            if name == "gemini-flash-latest":
                return FakeResponse(503, {"error": {"code": 503, "message": "high demand"}})
            return FakeResponse(
                200, {"candidates": [{"content": {"parts": [{"text": "Antwort"}]}}]}
            )

    async def fake_list():
        return {
            "available": True,
            "models": ["gemini-flash-latest", "gemini-3.5-flash"],
            "free_tier_candidates": ["gemini-3.5-flash"],
        }

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gemini, "list_models", fake_list)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)
    gemini.invalidate_model_cache()

    result = _run(gemini.generate("Test"))
    assert result["ok"] is True
    assert result["model"] == "gemini-3.5-flash"


def test_gemini_wechselt_bei_zeitueberschreitung(monkeypatch):
    """Reisst ein ueberlastetes Modell das Lesezeitlimit, wird sofort das
    naechste Modell probiert, ohne das Limit erneut abzuwarten."""
    settings.set_runtime("gemini_api_key", "test-key")
    settings.set_runtime("gemini_text_model", "gemini-flash-latest")
    settings.set_runtime("ai_max_retries", 0)

    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            name = url.split("/models/", 1)[1].split(":", 1)[0]
            calls.append(name)
            if name == "gemini-flash-latest":
                raise gemini.httpx.ReadTimeout("zu langsam")
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "Antwort"}]}}]})

    async def fake_list():
        return {"available": True, "models": ["gemini-flash-latest", "gemini-3.5-flash"]}

    monkeypatch.setattr(gemini.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gemini, "list_models", fake_list)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)
    gemini.invalidate_model_cache()

    result = _run(gemini.generate("Test"))
    assert result["ok"] is True
    assert result["model"] == "gemini-3.5-flash"
    # Genau ein Versuch pro Modell, kein wiederholtes Abwarten.
    assert calls == ["gemini-flash-latest", "gemini-3.5-flash"]


def test_gemini_ueberlastetes_modell_wird_nach_hinten_sortiert(monkeypatch):
    """Ein zuvor ueberlastetes Modell wird voruebergehend zuletzt probiert."""

    async def fake_list():
        return {"available": True, "models": ["gemini-flash-latest", "gemini-3.5-flash"]}

    monkeypatch.setattr(gemini, "list_models", fake_list)
    gemini.invalidate_model_cache()
    settings.set_runtime("gemini_text_model", "gemini-flash-latest")

    before = _run(gemini.model_candidates())
    assert before[0] == "gemini-flash-latest"

    gemini._mark_degraded("gemini-flash-latest")
    try:
        after = _run(gemini.model_candidates())
        assert after[0] != "gemini-flash-latest"
        assert "gemini-flash-latest" in after
    finally:
        gemini._degraded.clear()


def test_gemini_modellwahl_ueberspringt_bildmodelle():
    """Bild- und Pro-Modelle sind keine gueltigen Text-Kandidaten."""
    models = [
        "gemini-2.5-pro",
        "gemini-3-pro-image",
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash-preview-tts",
    ]
    chosen = gemini.pick_model("abgestellt", models)
    assert chosen == "gemini-3.5-flash"


def test_router_im_modus_off():
    settings.set_runtime("ai_mode", "off")
    result = _run(ai_router.complete("Frage"))
    assert result["ok"] is False
    assert "deaktiviert" in result["error"]


def test_router_weicht_auf_gemini_aus_wenn_ollama_fehlt(monkeypatch):
    settings.set_runtime("ai_mode", "auto")
    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("gemini_api_key", "test-key")

    async def fake_ollama_chat(*args, **kwargs):
        return {"ok": False, "error": "Verbindung verweigert", "provider": "ollama"}

    async def fake_gemini_generate(*args, **kwargs):
        return {"ok": True, "text": "Antwort von Gemini", "provider": "gemini",
                "model": "gemini-2.5-flash"}

    monkeypatch.setattr(ai_router.ollama, "chat", fake_ollama_chat)
    monkeypatch.setattr(ai_router.gemini, "generate", fake_gemini_generate)

    result = _run(ai_router.complete("Einfache Frage", task="chat"))
    assert result["ok"] is True
    assert result["provider"] == "gemini"
    assert result["fallback_used"] is True


def test_router_weicht_auf_ollama_aus_wenn_gemini_kontingent_leer(monkeypatch):
    settings.set_runtime("ai_mode", "auto")
    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("gemini_api_key", "test-key")

    async def fake_ollama_chat(*args, **kwargs):
        return {"ok": True, "text": "Lokale Antwort", "provider": "ollama", "model": "llama3.2:3b"}

    async def fake_gemini_generate(*args, **kwargs):
        return {"ok": False, "error": "Kontingent erschoepft", "provider": "gemini",
                "quota_exhausted": True}

    monkeypatch.setattr(ai_router.ollama, "chat", fake_ollama_chat)
    monkeypatch.setattr(ai_router.gemini, "generate", fake_gemini_generate)

    # Vision-Aufgabe: Gemini zuerst, Ausweich auf Ollama.
    result = _run(ai_router.complete("Beschreibe den Schaltplan", task="vision"))
    assert result["ok"] is True
    assert result["provider"] == "ollama"
    assert result["fallback_used"] is True


def test_router_bevorzugt_lokal_fuer_einfache_aufgaben():
    assert ai_router._prefer_local("chat", False, 100) is True
    assert ai_router._prefer_local("chat", True, 100) is False
    assert ai_router._prefer_local("ocr", False, 100) is False
    assert ai_router._prefer_local("question_generation", False, 5000) is False


def test_router_json_parsing_robust():
    assert ai_router.parse_json('{"a": 1}') == {"a": 1}
    assert ai_router.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai_router.parse_json("Text davor [1, 2, 3] Text danach") == [1, 2, 3]
    assert ai_router.parse_json("kein json") is None
    assert ai_router.parse_json("") is None


def test_kontingentverwaltung_zaehlt_aufrufe():
    ai_usage.record("gemini", "m", "chat", True)
    ai_usage.record("gemini", "m", "chat", False, "Fehler")
    usage = ai_usage.usage_today()
    assert usage["gemini"]["calls"] == 2
    assert usage["gemini"]["ok"] == 1
    assert usage["total"] == 2


def test_kontingentstatus_berechnung():
    state = ai_usage.quota_state("gemini")
    assert state["limit"] == ai_usage.DAILY_LIMITS["gemini"]
    assert state["remaining"] == state["limit"] - state["used"]
    assert state["exhausted"] is False


def test_fehlerprotokoll():
    ai_usage.record("ollama", "m", "chat", False, "Timeout")
    errors = ai_usage.recent_errors(5)
    assert any("Timeout" in (e.get("error") or "") for e in errors)


def test_ki_status_ohne_konfiguration():
    status = _run(ai_router.status())
    assert status["any_available"] is False
    assert status["mode"] == "auto"
    assert "ollama" in status and "gemini" in status
