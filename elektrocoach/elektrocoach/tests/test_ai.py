"""Tests for the AI layer using a stub HTTP transport (no network access).

The clients talk to Ollama and Gemini through ``httpx``. By injecting a
``MockTransport`` we exercise the real request building, response parsing,
budget accounting and error handling instead of mocking the client methods.
"""

from __future__ import annotations

import json

import httpx
import pytest

from elektrocoach.ai.gemini_client import API_BASE
from elektrocoach.ai.base import (
    AIError, AIQuotaExceeded, AIUnavailable, AIResponseInvalid, estimate_tokens,
    extract_json_block, parse_json_response, reduce_text,
)


def make_transport(handler):
    """Build an httpx transport from a handler function."""

    return httpx.MockTransport(handler)


# -- pure helpers ------------------------------------------------------------

def test_estimate_tokens_is_proportional():
    short = estimate_tokens("kurz")
    long = estimate_tokens("wort " * 500)
    assert short < long
    assert long > 100


def test_reduce_text_truncates_and_marks():
    text = "A" * 5000
    reduced = reduce_text(text, max_chars=500)
    assert len(reduced) <= 520
    assert reduced != text


def test_reduce_text_keeps_short_text_unchanged():
    text = "Kurzer Text zum Testen."
    assert reduce_text(text, max_chars=500) == text


def test_extract_json_block_handles_fenced_output():
    payload = 'Hier das Ergebnis:\n```json\n{"a": 1}\n```\nEnde'
    assert json.loads(extract_json_block(payload)) == {"a": 1}


def test_parse_json_response_rejects_garbage():
    with pytest.raises(AIResponseInvalid):
        parse_json_response("das ist kein json")


def test_parse_json_response_accepts_plain_object():
    assert parse_json_response('{"x": true}') == {"x": True}


# -- Ollama ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ollama_generate_parses_response(repo):
    from elektrocoach.ai.ollama_client import OllamaClient

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={
                "message": {"role": "assistant", "content": "Die Spannung ist 230 V."},
                "prompt_eval_count": 12,
                "eval_count": 8,
                "model": "qwen2.5:1.5b",
            })
        return httpx.Response(404, json={"error": "not found"})

    client = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    client._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(handler))
    result = await client.generate("Was ist die Netzspannung?", system="Sei knapp.")
    assert "230 V" in result.text
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 8
    assert result.provider == "ollama"
    # Only one model may be requested at a time; the payload must say so.
    assert captured["body"]["model"] == "qwen2.5:1.5b"
    assert captured["body"]["stream"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_unavailable_raises_aiunavailable(repo):
    from elektrocoach.ai.ollama_client import OllamaClient

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    client._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(handler))
    with pytest.raises(AIUnavailable):
        await client.generate("Frage")
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_status_reports_missing_model(repo):
    from elektrocoach.ai.ollama_client import OllamaClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404, json={})

    client = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    client._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(handler))
    status = await client.status()
    assert status["available"] is True
    assert status["version"] == "0.5.0"
    assert status["model_installed"] is False
    await client.aclose()


# -- Gemini ------------------------------------------------------------------

def gemini_handler_factory(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-2.0-flash",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.0-flash-lite",
                 "supportedGenerationMethods": ["generateContent"]},
            ]})
        if "generateContent" in request.url.path:
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "Antwort von Gemini"}]}}],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10},
            })
        return httpx.Response(404, json={})
    return handler


@pytest.mark.asyncio
async def test_gemini_generate_and_usage(repo):
    from elektrocoach.ai.gemini_client import GeminiClient

    calls: list[str] = []
    client = GeminiClient("test-key", "gemini-2.0-flash", enabled=True,
                          daily_request_budget=5)
    client._client = httpx.AsyncClient(
        base_url=API_BASE,
        transport=make_transport(gemini_handler_factory(calls)))
    result = await client.generate("Erkläre den Spannungsfall.")
    assert result.text == "Antwort von Gemini"
    assert result.total_tokens == 30
    assert result.provider == "gemini"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_never_called_when_disabled(repo):
    from elektrocoach.ai.gemini_client import GeminiClient

    calls: list[str] = []
    client = GeminiClient("test-key", "gemini-2.0-flash", enabled=False)
    client._client = httpx.AsyncClient(
        base_url=API_BASE,
        transport=make_transport(gemini_handler_factory(calls)))
    with pytest.raises(AIUnavailable):
        await client.generate("Frage")
    assert calls == [], "Gemini must not be called when disabled"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_429_maps_to_quota_exceeded(repo):
    """Google's 429 answer must become a pausable quota error, not a retry."""

    from elektrocoach.ai.gemini_client import GeminiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED",
            "message": "Quota exceeded for quota metric 'Generate requests'.",
        }})

    client = GeminiClient("test-key", "gemini-2.0-flash", enabled=True,
                          daily_request_budget=200)
    client._client = httpx.AsyncClient(base_url=API_BASE,
                                      transport=make_transport(handler))
    with pytest.raises(AIQuotaExceeded) as excinfo:
        await client.generate("Frage")
    message = str(excinfo.value).lower()
    assert "kostenlos" in message or "kontingent" in message
    await client.aclose()


@pytest.mark.asyncio
async def test_dispatcher_blocks_gemini_when_local_budget_used_up(repo):
    """The dispatcher must refuse to call Gemini once the local budget is spent.

    This is the guarantee that a free-tier limit can never turn into a paid
    request: the check happens before the HTTP call, and the call count proves it.
    """

    from elektrocoach.ai.dispatcher import AIDispatcher
    from elektrocoach.ai.gemini_client import GeminiClient
    from elektrocoach.ai.ollama_client import OllamaClient

    calls: list[str] = []
    gemini = GeminiClient("test-key", "gemini-2.0-flash", enabled=True,
                          daily_request_budget=2)
    gemini._client = httpx.AsyncClient(
        base_url=API_BASE, transport=make_transport(gemini_handler_factory(calls)))
    # Ollama is switched off, so Gemini is the only candidate provider.
    ollama = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=False)

    for _ in range(2):
        repo.record_ai_usage(provider="gemini", model="gemini-2.0-flash",
                             task_type="hard_qa", prompt_tokens=1,
                             completion_tokens=1, success=True)

    dispatcher = AIDispatcher(repo, ollama, gemini, gemini_daily_budget=2)
    with pytest.raises(AIUnavailable) as excinfo:
        await dispatcher.run("hard_qa", "Schwierige Frage", use_cache=False)
    assert calls == [], "no Gemini request may leave the device over budget"
    assert "Tageslimit" in str(excinfo.value) or "kostenpflichtig" in str(excinfo.value)
    decisions = dispatcher.last_decisions(5)
    assert any("Kontingent" in reason or "Tageslimit" in reason
               for decision in decisions for reason in decision.get("reasons", []))
    await gemini.aclose()


@pytest.mark.asyncio
async def test_gemini_rejects_invalid_key(repo):
    from elektrocoach.ai.gemini_client import GeminiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {
            "code": 400, "status": "INVALID_ARGUMENT",
            "message": "API key not valid. Please pass a valid API key.",
        }})

    client = GeminiClient("bad-key", "gemini-2.0-flash", enabled=True)
    client._client = httpx.AsyncClient(base_url=API_BASE,
                                      transport=make_transport(handler))
    with pytest.raises(AIError) as excinfo:
        await client.generate("Frage")
    # A rejected key must not be retried silently.
    assert excinfo.value.retryable is False
    assert "abgelehnt" in str(excinfo.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_list_models_is_live(repo):
    from elektrocoach.ai.gemini_client import GeminiClient

    calls: list[str] = []
    client = GeminiClient("test-key", "gemini-2.0-flash", enabled=True)
    client._client = httpx.AsyncClient(
        base_url=API_BASE,
        transport=make_transport(gemini_handler_factory(calls)))
    models = await client.list_models(force=True)
    names = [model["name"] for model in models]
    assert "gemini-2.0-flash" in names
    assert any("models" in call for call in calls)
    await client.aclose()


# -- dispatcher --------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatcher_prefers_local_for_simple_tasks(repo):
    from elektrocoach.ai.dispatcher import AIDispatcher
    from elektrocoach.ai.gemini_client import GeminiClient
    from elektrocoach.ai.ollama_client import OllamaClient

    ollama_calls: list[str] = []

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        ollama_calls.append(request.url.path)
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={
                "message": {"content": "lokal beantwortet"},
                "prompt_eval_count": 5, "eval_count": 5, "model": "qwen2.5:1.5b",
            })
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})
        return httpx.Response(200, json={})

    gemini_calls: list[str] = []
    ollama = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    ollama._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(ollama_handler))
    gemini = GeminiClient("key", "gemini-2.0-flash", enabled=True)
    gemini._client = httpx.AsyncClient(base_url=API_BASE,
                                      transport=make_transport(gemini_handler_factory(gemini_calls)))

    dispatcher = AIDispatcher(repo, ollama, gemini, gemini_daily_budget=5)
    result = await dispatcher.run("summarize", "Fasse das zusammen.")
    assert result.provider == "ollama"
    assert gemini_calls == [], "a simple task must not be sent to Gemini"
    decisions = dispatcher.last_decisions(5)
    assert decisions and decisions[0]["task_type"] == "summarize"
    assert decisions[0]["chosen"] == "ollama"
    await ollama.aclose()
    await gemini.aclose()


@pytest.mark.asyncio
async def test_dispatcher_falls_back_when_ollama_down(repo):
    from elektrocoach.ai.dispatcher import AIDispatcher
    from elektrocoach.ai.gemini_client import GeminiClient
    from elektrocoach.ai.ollama_client import OllamaClient

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    gemini_calls: list[str] = []
    ollama = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    ollama._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(ollama_handler))
    gemini = GeminiClient("key", "gemini-2.0-flash", enabled=True)
    gemini._client = httpx.AsyncClient(base_url=API_BASE,
                                      transport=make_transport(gemini_handler_factory(gemini_calls)))

    dispatcher = AIDispatcher(repo, ollama, gemini, gemini_daily_budget=5)
    result = await dispatcher.run("hard_qa", "Schwierige Frage")
    assert result.provider == "gemini"
    await ollama.aclose()
    await gemini.aclose()


@pytest.mark.asyncio
async def test_dispatcher_uses_cache_and_records_usage(repo):
    from elektrocoach.ai.dispatcher import AIDispatcher
    from elektrocoach.ai.gemini_client import GeminiClient
    from elektrocoach.ai.ollama_client import OllamaClient

    calls = {"count": 0}

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})
        calls["count"] += 1
        return httpx.Response(200, json={
            "message": {"content": "zwischengespeichert"},
            "prompt_eval_count": 4, "eval_count": 2, "model": "qwen2.5:1.5b",
        })

    ollama = OllamaClient("http://ollama.test:11434", "qwen2.5:1.5b", enabled=True)
    ollama._client = httpx.AsyncClient(base_url="http://ollama.test:11434",
                                      transport=make_transport(ollama_handler))
    gemini = GeminiClient("", "gemini-2.0-flash", enabled=False)

    dispatcher = AIDispatcher(repo, ollama, gemini, gemini_daily_budget=5)
    first = await dispatcher.run("summarize", "Derselbe Text")
    second = await dispatcher.run("summarize", "Derselbe Text")
    assert first.cached is False
    assert second.cached is True
    assert calls["count"] == 1, "the second identical call must come from the cache"
    usage = {row["provider"]: row for row in repo.ai_usage_summary(1)}
    assert usage["ollama"]["requests"] >= 1
    await ollama.aclose()
