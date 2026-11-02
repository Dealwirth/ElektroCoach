"""AI subsystem: local Ollama, Google Gemini (free tier) and the dispatcher."""

from .base import (
    AIError,
    AIQuotaExceeded,
    AIResponseInvalid,
    AIResult,
    AIUnavailable,
    estimate_tokens,
    reduce_text,
)
from .dispatcher import AIDispatcher
from .gemini_client import GeminiClient, encode_image_for_gemini
from .ollama_client import OllamaClient

__all__ = [
    "AIError",
    "AIQuotaExceeded",
    "AIResponseInvalid",
    "AIResult",
    "AIUnavailable",
    "AIDispatcher",
    "GeminiClient",
    "OllamaClient",
    "encode_image_for_gemini",
    "estimate_tokens",
    "reduce_text",
]
