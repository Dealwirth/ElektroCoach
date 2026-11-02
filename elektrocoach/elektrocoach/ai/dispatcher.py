"""Intelligent AI dispatcher.

For every request the dispatcher decides:

1. **Which provider** is suitable (local Ollama first, Gemini only when the
   task genuinely needs it).
2. **Whether the local model suffices** — cheap tasks stay on the Pi.
3. **Which data is sent** — callers pass already-reduced excerpts, and the
   dispatcher never appends the whole knowledge base.
4. **Whether the free Gemini budget is still available** — when it is used up
   the request is paused, never silently moved to a paid path.
5. **How much it cost** — every attempt is recorded with token counts.

Every decision is logged and exposed to the UI through :meth:`last_decisions`
so the user can see what ran where.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..backend.util import sha256_bytes
from ..database.repository import Repository
from .base import (
    AIError,
    AIQuotaExceeded,
    AIResult,
    AIUnavailable,
    AIResponseInvalid,
    estimate_tokens,
)
from .gemini_client import GeminiClient
from .ollama_client import OllamaClient

logger = logging.getLogger("elektrocoach.ai.dispatcher")

# Tasks a 1.5B local model can do reliably and cheaply.
LOCAL_FIRST_TASKS = {
    "classify",
    "keywords",
    "summarize",
    "structure",
    "flashcards",
    "simple_exercise",
    "document_preprocess",
    "extract",
    "translate_short",
}

# Tasks that need real reasoning, vision or high-quality German.
CLOUD_FIRST_TASKS = {
    "hard_qa",
    "complex_explanation",
    "grading_freetext",
    "quality_check",
    "plausibility",
    "handwriting",
    "vision",
    "exam_analysis",
    "document_structuring",
}

# Tasks that cannot be served by the small local chat model at all.
VISION_TASKS = {"handwriting", "vision"}

KNOWN_TASKS = LOCAL_FIRST_TASKS | CLOUD_FIRST_TASKS


@dataclass
class Decision:
    task_type: str
    chosen: str | None
    order: list[str]
    reasons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    tokens_estimated: int = 0
    cached: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "chosen": self.chosen,
            "order": self.order,
            "reasons": self.reasons,
            "tokens_estimated": self.tokens_estimated,
            "cached": self.cached,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)),
        }


class AIDispatcher:
    def __init__(self, repo: Repository, ollama: OllamaClient, gemini: GeminiClient, *,
                 gemini_daily_budget: int = 200) -> None:
        self.repo = repo
        self.ollama = ollama
        self.gemini = gemini
        self.gemini_daily_budget = gemini_daily_budget
        self._decisions: deque[Decision] = deque(maxlen=100)
        self._lock = asyncio.Lock()

    # -- transparency ---------------------------------------------------------

    def last_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [d.as_dict() for d in list(self._decisions)[-limit:]][::-1]

    def _record(self, decision: Decision) -> None:
        self._decisions.append(decision)

    # -- provider viability ---------------------------------------------------

    async def _gemini_available(self) -> tuple[bool, str]:
        if not self.gemini.configured:
            if not self.gemini.enabled:
                return False, "Gemini ist in den Einstellungen deaktiviert."
            return False, "Es ist kein Gemini-API-Schlüssel hinterlegt."
        if self.gemini_daily_budget > 0:
            used = self.repo.ai_budget_today("gemini")["requests_used"]
            if used >= self.gemini_daily_budget:
                return False, (
                    f"Das lokale Tageslimit für Gemini ist erreicht "
                    f"({used}/{self.gemini_daily_budget} Anfragen). "
                    "Die Aufgabe wird nicht kostenpflichtig ausgeführt."
                )
        return True, "Gemini ist konfiguriert und das Tageskontingent ist verfügbar."

    async def _ollama_available(self) -> tuple[bool, str]:
        if not self.ollama.enabled:
            return False, "Ollama ist in den Einstellungen deaktiviert."
        if not await self.ollama.is_available():
            return False, f"Ollama ist unter {self.ollama.base_url} nicht erreichbar."
        if not await self.ollama.has_model():
            return False, f"Das Modell „{self.ollama.model}“ ist nicht installiert."
        return True, f"Ollama läuft und das Modell „{self.ollama.model}“ ist installiert."

    async def decide(self, task_type: str, *, images: bool = False,
                     prompt_chars: int = 0, prefer: str = "auto") -> Decision:
        """Compute the provider order and the reasons, without running anything."""

        if prefer == "ollama":
            order = ["ollama", "gemini"]
        elif prefer == "gemini":
            order = ["gemini", "ollama"]
        elif task_type in VISION_TASKS or images:
            order = ["gemini"]
        elif task_type in CLOUD_FIRST_TASKS:
            order = ["gemini", "ollama"]
        else:
            order = ["ollama", "gemini"]

        reasons: list[str] = [
            f"Aufgabentyp „{task_type}“ → Reihenfolge: {', '.join(order)}."
        ]
        if images:
            reasons.append(
                "Die Aufgabe enthält Bilder; das kleine lokale Textmodell kann "
                "Bilder nicht auswerten, daher ist Gemini erforderlich."
            )
        if task_type in LOCAL_FIRST_TASKS and order[0] == "ollama":
            reasons.append(
                "Diese Aufgabe ist einfach genug für das lokale Modell; das spart "
                "Gemini-Kontingent und überträgt keine Daten nach außen."
            )
        if task_type in CLOUD_FIRST_TASKS and order[0] == "gemini":
            reasons.append(
                "Diese Aufgabe verlangt fachliche Tiefe bzw. Bildverständnis und "
                "wird deshalb bevorzugt von Gemini bearbeitet."
            )

        estimated = estimate_tokens("x" * prompt_chars) if prompt_chars else 0

        decision = Decision(task_type=task_type, chosen=None, order=order,
                            reasons=reasons, tokens_estimated=estimated)
        return decision

    # -- execution ------------------------------------------------------------

    async def run(self, task_type: str, prompt: str, *, system: str | None = None,
                  json_mode: bool = False, images: list[dict[str, str]] | None = None,
                  prefer: str = "auto", temperature: float = 0.2,
                  max_tokens: int | None = None, use_cache: bool = True,
                  cache_key: str | None = None) -> AIResult:
        """Run a task, choosing the provider automatically."""

        decision = await self.decide(
            task_type, images=bool(images), prompt_chars=len(prompt), prefer=prefer
        )

        if use_cache:
            key = cache_key or self._cache_key(task_type, prompt, system, images, prefer)
            cached = self.repo.cache_get(key)
            if cached is not None:
                decision.chosen = cached.get("provider", "cache")
                decision.cached = True
                decision.reasons.append("Ergebnis aus dem Zwischenspeicher verwendet.")
                self._record(decision)
                return AIResult(
                    text=cached.get("text", ""),
                    provider=cached.get("provider", "cache"),
                    model=cached.get("model"),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                    cached=True,
                    structured=cached.get("structured"),
                )
        else:
            key = None

        errors: list[str] = []
        for provider in decision.order:
            try:
                if provider == "gemini":
                    available, reason = await self._gemini_available()
                    if not available:
                        errors.append(f"Gemini: {reason}")
                        decision.reasons.append(f"Gemini übersprungen: {reason}")
                        continue
                    if images:
                        decision.reasons.append(
                            "Es werden nur die für die Aufgabe nötigen Bild- und "
                            "Textausschnitte an Google Gemini übertragen."
                        )
                    result = await self._run_gemini(
                        prompt, system=system, json_mode=json_mode,
                        images=images, temperature=temperature,
                        max_tokens=max_tokens, task_type=task_type,
                    )
                else:
                    available, reason = await self._ollama_available()
                    if not available:
                        errors.append(f"Ollama: {reason}")
                        decision.reasons.append(f"Ollama übersprungen: {reason}")
                        continue
                    result = await self._run_ollama(
                        prompt, system=system, json_mode=json_mode,
                        temperature=temperature, max_tokens=max_tokens,
                        task_type=task_type,
                    )
            except AIQuotaExceeded as exc:
                errors.append(f"{provider}: {exc}")
                decision.reasons.append(f"{provider} Kontingent erschöpft: {exc}")
                self._record_usage_failure(provider, task_type, str(exc))
                continue
            except AIUnavailable as exc:
                errors.append(f"{provider}: {exc}")
                decision.reasons.append(f"{provider} nicht verfügbar: {exc}")
                self._record_usage_failure(provider, task_type, str(exc))
                continue
            except AIResponseInvalid:
                raise
            except AIError as exc:
                errors.append(f"{provider}: {exc}")
                self._record_usage_failure(provider, task_type, str(exc))
                if not exc.retryable:
                    # A non-retryable provider error (bad key, bad model) is
                    # reported immediately; trying the other provider would only
                    # hide the real problem.
                    decision.chosen = provider
                    decision.reasons.append(f"{provider} nicht nutzbar: {exc}")
                    self._record(decision)
                    raise
                decision.reasons.append(f"{provider} Fehler: {exc}")
                continue

            decision.chosen = provider
            self._record(decision)
            if key:
                self._store_cache(key, provider, result)
            return result

        decision.chosen = None
        self._record(decision)
        raise AIUnavailable(
            "Keine KI konnte die Aufgabe bearbeiten. " + " ".join(errors),
            guidance=(
                "Öffnen Sie in ElektroCoach den Bereich „Systemstatus“ und prüfen "
                "Sie die Zeilen „Ollama“ und „Gemini“. Für Ollama: ElektroCoach-"
                "Ollama-App starten. Für Gemini: API-Schlüssel in den Einstellungen "
                "prüfen."
            ),
        )

    async def _run_ollama(self, prompt: str, *, system: str | None, json_mode: bool,
                          temperature: float, max_tokens: int | None,
                          task_type: str) -> AIResult:
        started = time.monotonic()
        try:
            result = await self.ollama.generate(
                prompt, system=system, json_mode=json_mode,
                temperature=temperature, max_tokens=max_tokens, task_type=task_type,
            )
        except AIError as exc:
            self.repo.record_ai_usage(
                provider="ollama", model=self.ollama.model, task_type=task_type,
                prompt_tokens=estimate_tokens(prompt), completion_tokens=0,
                success=False, error=str(exc)[:300],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise
        self.repo.record_ai_usage(
            provider="ollama", model=result.model, task_type=task_type,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            success=True, latency_ms=result.latency_ms,
        )
        return result

    async def _run_gemini(self, prompt: str, *, system: str | None, json_mode: bool,
                          images: list[dict[str, str]] | None, temperature: float,
                          max_tokens: int | None, task_type: str) -> AIResult:
        started = time.monotonic()
        try:
            result = await self.gemini.generate(
                prompt, system=system, json_mode=json_mode, images=images,
                temperature=temperature, max_tokens=max_tokens, task_type=task_type,
            )
        except AIError as exc:
            self.repo.record_ai_usage(
                provider="gemini", model=self.gemini.model, task_type=task_type,
                prompt_tokens=estimate_tokens(prompt), completion_tokens=0,
                success=False, error=str(exc)[:300],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            if isinstance(exc, AIQuotaExceeded):
                self.repo.add_event(
                    level="warning", category="ai",
                    message="Gemini-Kontingent erschöpft; Aufgabe pausiert.",
                    details={"task_type": task_type, "guidance": exc.guidance},
                )
            raise
        self.repo.record_ai_usage(
            provider="gemini", model=result.model, task_type=task_type,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            success=True, latency_ms=result.latency_ms,
        )
        return result

    def _record_usage_failure(self, provider: str, task_type: str, error: str) -> None:
        try:
            self.repo.record_ai_usage(
                provider=provider, model=None, task_type=task_type,
                prompt_tokens=0, completion_tokens=0, success=False, error=error[:300],
            )
        except Exception as exc:  # noqa: BLE001 - usage logging must not break the task
            logger.debug("failed to record usage: %s", exc)

    # -- caching --------------------------------------------------------------

    @staticmethod
    def _cache_key(task_type: str, prompt: str, system: str | None,
                   images: list[dict[str, str]] | None, prefer: str) -> str:
        digest = hashlib.sha256()
        digest.update(task_type.encode("utf-8"))
        digest.update(b"\x00")
        digest.update((system or "").encode("utf-8"))
        digest.update(b"\x00")
        digest.update(prompt.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(prefer.encode("utf-8"))
        for image in images or []:
            digest.update(sha256_bytes(image.get("data_base64", "").encode("utf-8")).encode())
        return digest.hexdigest()

    def _store_cache(self, key: str, provider: str, result: AIResult) -> None:
        try:
            self.repo.cache_put(
                cache_key=key, provider=provider, model=result.model,
                task_type=result.raw.get("task_type"),
                response={
                    "text": result.text,
                    "provider": provider,
                    "model": result.model,
                    "structured": result.structured,
                },
            )
        except Exception as exc:  # noqa: BLE001 - caching is best effort
            logger.debug("cache store failed: %s", exc)

    # -- helpers --------------------------------------------------------------

    async def ask_json(self, task_type: str, prompt: str, *, system: str | None = None,
                       images: list[dict[str, str]] | None = None, prefer: str = "auto",
                       max_tokens: int | None = None,
                       use_cache: bool = True) -> tuple[Any, AIResult]:
        """Run a task and parse the answer as JSON."""

        result = await self.run(
            task_type, prompt, system=system, json_mode=True, images=images,
            prefer=prefer, max_tokens=max_tokens, use_cache=use_cache,
        )
        try:
            payload = result.json()
        except AIResponseInvalid as exc:
            # One retry with a stricter instruction; small local models often
            # need it.
            retry_prompt = (
                prompt
                + "\n\nAntworte ausschließlich mit gültigem JSON, ohne Erklärtext."
            )
            result = await self.run(
                task_type, retry_prompt, system=system, json_mode=True, images=images,
                prefer=prefer, max_tokens=max_tokens, use_cache=False,
            )
            try:
                payload = result.json()
            except AIResponseInvalid:
                raise exc
        result.structured = payload
        return payload, result

    async def status(self) -> dict[str, Any]:
        ollama_status = await self.ollama.status()
        gemini_used = self.repo.ai_budget_today("gemini")["requests_used"]
        gemini_status = await self.gemini.status(requests_used_today=gemini_used)
        return {
            "ollama": ollama_status,
            "gemini": gemini_status,
            "usage": self.repo.ai_usage_summary(7),
            "cache": self.repo.cache_stats(),
            "decisions": self.last_decisions(10),
        }
