"""Common types for the AI layer.

The dispatcher and the feature modules talk to providers only through these
types. That keeps the provider-specific details (HTTP shapes, error codes,
token accounting) in one place per provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class AIError(RuntimeError):
    """Base class for AI failures that the user should see in plain language."""

    def __init__(self, message: str, *, provider: str | None = None,
                 guidance: str | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.provider = provider
        self.guidance = guidance
        self.retryable = retryable


class AIUnavailable(AIError):
    """No provider could serve the request (not reachable, not configured)."""


class AIQuotaExceeded(AIError):
    """The free-tier budget for a provider is used up for today."""

    def __init__(self, message: str, *, provider: str | None = None,
                 guidance: str | None = None) -> None:
        super().__init__(message, provider=provider, guidance=guidance, retryable=False)


class AIResponseInvalid(AIError):
    """The provider answered, but the answer could not be used."""


@dataclass
class AIResult:
    text: str
    provider: str
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
    structured: Any = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def json(self) -> Any:
        """Parse the response text as JSON, tolerating markdown code fences."""

        if self.structured is not None:
            return self.structured
        return parse_json_response(self.text)


def extract_json_block(text: str) -> str | None:
    """Find the first balanced JSON object or array in a text."""

    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return stripped[start:index + 1]
    return None


def parse_json_response(text: str) -> Any:
    block = extract_json_block(text)
    if block is None:
        raise AIResponseInvalid(
            "Die KI-Antwort enthielt kein verwertbares JSON.",
            guidance=(
                "Die Antwort konnte nicht ausgewertet werden. Bitte versuchen Sie "
                "es erneut; bleibt der Fehler bestehen, prüfen Sie das gewählte "
                "Modell in den Einstellungen."
            ),
        )
    try:
        return json.loads(block)
    except ValueError as exc:
        raise AIResponseInvalid(
            f"Die KI-Antwort war kein gültiges JSON: {exc}",
            guidance="Bitte die Aufgabe erneut starten.",
        ) from exc


def estimate_tokens(text: str) -> int:
    """Rough token estimate for German technical text.

    German compounds and technical terms tokenise slightly worse than English,
    so ~3.5 characters per token is a more honest estimate than 4.
    """

    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def reduce_text(text: str, max_chars: int) -> str:
    """Trim text to a character budget on a word boundary."""

    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip() + " …"
