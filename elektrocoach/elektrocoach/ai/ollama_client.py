"""Ollama client (local, free, resource constrained).

Everything here is written for a Raspberry Pi 4 with 8 GB RAM:

* exactly one request at a time (an ``asyncio.Semaphore(1)``),
* a single chat model loaded at a time,
* optional automatic unload after a period of inactivity,
* clear, actionable errors instead of raw HTTP failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .base import AIError, AIResult, AIUnavailable, estimate_tokens

logger = logging.getLogger("elektrocoach.ai.ollama")

# Local inference on a Pi 4 is slow: allow generous read timeouts, but keep the
# connection attempt short so an offline Ollama is detected quickly.
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 600.0


@dataclass
class OllamaModel:
    name: str
    size: int = 0
    digest: str = ""
    modified_at: str = ""
    parameter_size: str = ""
    quantization: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "digest": self.digest,
            "modified_at": self.modified_at,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization,
        }


class OllamaClient:
    def __init__(self, base_url: str, model: str, *, enabled: bool = True,
                 unload_after_seconds: int = 900) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enabled = enabled
        self.unload_after_seconds = unload_after_seconds
        self._semaphore = asyncio.Semaphore(1)
        self._last_used: float = 0.0
        self._loaded_model: str | None = None
        self._unload_task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
            )
        return self._client

    async def aclose(self) -> None:
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # -- availability ---------------------------------------------------------

    async def version(self) -> str | None:
        if not self.enabled:
            return None
        try:
            response = await self._http().get("/api/version", timeout=CONNECT_TIMEOUT)
            response.raise_for_status()
            return str(response.json().get("version", ""))
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("ollama version check failed: %s", exc)
            return None

    async def is_available(self) -> bool:
        return await self.version() is not None

    async def list_models(self) -> list[OllamaModel]:
        if not self.enabled:
            return []
        try:
            response = await self._http().get("/api/tags", timeout=CONNECT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("ollama model list failed: %s", exc)
            return []
        models: list[OllamaModel] = []
        for entry in payload.get("models", []) or []:
            details = entry.get("details") or {}
            models.append(OllamaModel(
                name=str(entry.get("name") or entry.get("model") or ""),
                size=int(entry.get("size") or 0),
                digest=str(entry.get("digest") or ""),
                modified_at=str(entry.get("modified_at") or ""),
                parameter_size=str(details.get("parameter_size") or ""),
                quantization=str(details.get("quantization_level") or ""),
            ))
        return models

    async def has_model(self, name: str | None = None) -> bool:
        target = (name or self.model).strip()
        if not target:
            return False
        names = {model.name for model in await self.list_models()}
        if target in names:
            return True
        # Ollama reports names as "qwen2.5:1.5b"; accept a tagless request when
        # exactly one installed model matches the repository name.
        if ":" not in target:
            return any(n.split(":")[0] == target for n in names)
        return False

    async def running_models(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            response = await self._http().get("/api/ps", timeout=CONNECT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return list(payload.get("models", []) or [])

    async def pull_model(self, name: str) -> AsyncIterator[dict[str, Any]]:
        """Stream pull progress as dicts: ``{status, completed, total, percent}``."""

        if not self.enabled:
            raise AIUnavailable(
                "Ollama ist in den Einstellungen deaktiviert.",
                provider="ollama",
                guidance="Aktivieren Sie in den Einstellungen die Option „Ollama verwenden“.",
            )
        payload = {"name": name, "stream": True}
        try:
            async with self._http().stream(
                "POST", "/api/pull", json=payload, timeout=httpx.Timeout(1800.0, connect=CONNECT_TIMEOUT)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    total = int(event.get("total") or 0)
                    completed = int(event.get("completed") or 0)
                    percent = (completed / total * 100.0) if total else 0.0
                    yield {
                        "status": event.get("status", ""),
                        "completed": completed,
                        "total": total,
                        "percent": round(percent, 2),
                        "error": event.get("error"),
                    }
        except httpx.HTTPError as exc:
            raise AIUnavailable(
                f"Das Modell „{name}“ konnte nicht geladen werden: {exc}",
                provider="ollama",
                guidance=(
                    "Prüfen Sie, ob die ElektroCoach-Ollama-App läuft und ob "
                    "genügend Speicherplatz frei ist. Das Modell qwen2.5:1.5b "
                    "benötigt rund 1 GB."
                ),
            ) from exc

    async def unload(self, name: str | None = None) -> bool:
        """Ask Ollama to drop a model from RAM immediately."""

        target = (name or self.model).strip()
        if not target:
            return False
        try:
            response = await self._http().post(
                "/api/generate",
                json={"model": target, "keep_alive": 0, "prompt": ""},
                timeout=60.0,
            )
            response.raise_for_status()
            self._loaded_model = None
            logger.info("unloaded ollama model %s", target)
            return True
        except httpx.HTTPError as exc:
            logger.debug("unload failed for %s: %s", target, exc)
            return False

    # -- generation -----------------------------------------------------------

    async def generate(self, prompt: str, *, system: str | None = None,
                       model: str | None = None, json_mode: bool = False,
                       temperature: float = 0.2, max_tokens: int | None = None,
                       task_type: str | None = None) -> AIResult:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, model=model, json_mode=json_mode,
                               temperature=temperature, max_tokens=max_tokens,
                               task_type=task_type)

    async def chat(self, messages: list[dict[str, Any]], *, model: str | None = None,
                   json_mode: bool = False, temperature: float = 0.2,
                   max_tokens: int | None = None,
                   task_type: str | None = None) -> AIResult:
        if not self.enabled:
            raise AIUnavailable(
                "Ollama ist deaktiviert.",
                provider="ollama",
                guidance="Aktivieren Sie Ollama in den Einstellungen von ElektroCoach.",
            )
        target = (model or self.model).strip()
        if not target:
            raise AIUnavailable(
                "Es ist kein Ollama-Modell konfiguriert.",
                provider="ollama",
                guidance="Tragen Sie in den Einstellungen ein Modell ein, z. B. qwen2.5:1.5b.",
            )

        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        payload: dict[str, Any] = {
            "model": target,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if json_mode:
            payload["format"] = "json"
        if self.unload_after_seconds > 0:
            payload["keep_alive"] = self.unload_after_seconds

        started = time.monotonic()
        # Only one local inference at a time: the Pi has no spare CPU.
        async with self._semaphore:
            try:
                response = await self._http().post("/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:300] if exc.response is not None else ""
                if exc.response is not None and exc.response.status_code == 404:
                    raise AIUnavailable(
                        f"Das Ollama-Modell „{target}“ ist nicht installiert.",
                        provider="ollama",
                        guidance=(
                            f"Öffnen Sie die ElektroCoach-Ollama-App und laden Sie "
                            f"das Modell „{target}“ (Schritt „Modell laden“ im "
                            f"Einrichtungsassistenten)."
                        ),
                    ) from exc
                raise AIError(
                    f"Ollama meldete einen Fehler ({exc.response.status_code}): {body}",
                    provider="ollama",
                    guidance="Prüfen Sie das Ollama-Protokoll in der Ollama-App.",
                ) from exc
            except httpx.HTTPError as exc:
                raise AIUnavailable(
                    f"Ollama ist nicht erreichbar ({self.base_url}).",
                    provider="ollama",
                    guidance=(
                        "Öffnen Sie in Home Assistant die Add-ons, prüfen Sie, ob "
                        "„ElektroCoach Ollama“ läuft und ob die Adresse in den "
                        "ElektroCoach-Einstellungen korrekt ist."
                    ),
                ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        self._last_used = time.monotonic()
        self._loaded_model = target

        message = data.get("message") or {}
        text = str(message.get("content") or "")
        prompt_tokens = int(data.get("prompt_eval_count") or estimate_tokens(prompt))
        completion_tokens = int(data.get("eval_count") or estimate_tokens(text))

        if self.unload_after_seconds > 0:
            self._schedule_unload(target)

        return AIResult(
            text=text,
            provider="ollama",
            model=target,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            raw={"done_reason": data.get("done_reason"), "task_type": task_type},
        )

    # -- idle unload ----------------------------------------------------------

    def _schedule_unload(self, model: str) -> None:
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._unload_task = loop.create_task(self._unload_after_idle(model))

    async def _unload_after_idle(self, model: str) -> None:
        try:
            await asyncio.sleep(max(60, self.unload_after_seconds))
            if time.monotonic() - self._last_used < self.unload_after_seconds - 5:
                return
            await self.unload(model)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown
            raise
        except Exception as exc:  # noqa: BLE001 - a failed unload is not fatal
            logger.debug("idle unload failed: %s", exc)

    # -- diagnostics ----------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        version = await self.version()
        available = version is not None
        models = await self.list_models() if available else []
        running = await self.running_models() if available else []
        return {
            "enabled": self.enabled,
            "available": available,
            "version": version,
            "base_url": self.base_url,
            "configured_model": self.model,
            "model_installed": any(m.name == self.model for m in models),
            "models": [m.as_dict() for m in models],
            "running": [
                {"name": m.get("name"), "size": m.get("size")} for m in running
            ],
            "loaded_model": self._loaded_model,
            "idle_seconds": (
                round(time.monotonic() - self._last_used, 1) if self._last_used else None
            ),
        }
