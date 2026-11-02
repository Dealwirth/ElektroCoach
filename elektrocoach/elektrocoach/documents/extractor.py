"""Turn page text into structured knowledge items.

Two stages:

1. **Splitting** — text is divided into sections at headings (numbering like
   ``1.2``, ``Aufgabe 3``, ``Kapitel``) and then into chunks of a bounded size
   with a small overlap so a sentence is never cut in the middle.
2. **Enrichment** — each chunk is classified with the deterministic keyword
   taxonomy. An AI pass is optional and only refines the result; the import
   works fully offline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .taxonomy import classify

logger = logging.getLogger("elektrocoach.documents.extractor")

MAX_CHUNK_CHARS = 1400
MIN_CHUNK_CHARS = 120
CHUNK_OVERLAP_CHARS = 120

# "1.2.3 Titel", "Aufgabe 4:", "Kapitel 7 - ...", "## Titel"
_HEADING_PATTERNS = [
    re.compile(r"^\s{0,3}(\d+(?:\.\d+){0,3})[.)]?\s+(\S.{2,80})$"),
    re.compile(r"^\s{0,3}((?:aufgabe|kapitel|abschnitt|thema|übung|beispiel|"
               r"merke|hinweis|lernziel)\s*\d*[.:)]?)\s*(.{0,80})$", re.IGNORECASE),
    re.compile(r"^\s{0,3}#{1,4}\s+(.{3,80})$"),
]

# Markers that indicate an unreadable or uncertain passage.
_UNCERTAIN_MARKERS = ("???", "[unleserlich]", "[unclear]", "�", "[?]")
_FORMULA_HINTS = ("=", "π", "cos", "sin", "√", "²", "³", "°", "Ω", "Δ", "%")
_TABLE_HINTS = ("|", "\t\t", "  +  ")


@dataclass
class Chunk:
    title: str
    content: str
    subject: str | None = None
    topic: str | None = None
    confidence: float = 0.0
    uncertainty: bool = False
    has_formula: bool = False
    has_table: bool = False
    heading_level: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def _looks_like_heading(line: str) -> tuple[bool, str, int]:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False, "", 0
    for index, pattern in enumerate(_HEADING_PATTERNS):
        match = pattern.match(line)
        if match:
            groups = [g for g in match.groups() if g]
            title = " ".join(str(g) for g in groups).strip(" .:-")
            if 2 <= len(title) <= 90:
                return True, title, 3 - index
    # A short line in title case followed by a blank line is treated as a heading.
    if len(stripped) <= 60 and stripped.endswith(":") and not stripped.endswith("::"):
        return True, stripped.rstrip(":"), 1
    return False, "", 0


def split_into_sections(text: str) -> list[tuple[str, str, int]]:
    """Return ``(title, body, heading_level)`` triples."""

    lines = (text or "").splitlines()
    sections: list[tuple[str, str, int]] = []
    current_title = ""
    current_level = 0
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body or current_title:
            sections.append((current_title, body, current_level))

    for line in lines:
        is_heading, title, level = _looks_like_heading(line)
        if is_heading:
            flush()
            buffer = []
            current_title = title
            current_level = level
        else:
            buffer.append(line)
    flush()
    return [s for s in sections if s[1].strip() or s[0].strip()]


def chunk_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS,
               overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Split a body into chunks on paragraph/sentence boundaries."""

    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return [clean] if clean else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            # A single long paragraph: split at sentence boundaries.
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars:
                    current = f"{current} {sentence}".strip()
                else:
                    if current:
                        chunks.append(current)
                    if len(sentence) > max_chars:
                        # Still too long: hard split.
                        for start in range(0, len(sentence), max_chars - overlap):
                            chunks.append(sentence[start:start + max_chars].strip())
                        current = ""
                    else:
                        current = sentence
            continue
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if overlap and current else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c.strip()) >= 20]


def _has_uncertain_marker(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _UNCERTAIN_MARKERS)


def _has_formula(text: str) -> bool:
    return any(hint in text for hint in _FORMULA_HINTS)


def _has_table(text: str) -> bool:
    return any(hint in text for hint in _TABLE_HINTS)


def build_chunks(text: str, *, source_label: str, page_number: int,
                 page_quality: float = 1.0,
                 page_uncertain: bool = False) -> list[Chunk]:
    """Create knowledge chunks from one page of extracted text."""

    chunks: list[Chunk] = []
    sections = split_into_sections(text)
    if not sections:
        return chunks

    for title, body, level in sections:
        combined = f"{title}\n{body}".strip()
        if len(combined) < MIN_CHUNK_CHARS and len(sections) > 1:
            # Very short fragments are still stored: they are often definitions.
            pass
        pieces = chunk_text(body) if body else [title]
        for index, piece in enumerate(pieces):
            heading = title if title else f"Seite {page_number}"
            if len(pieces) > 1:
                heading = f"{heading} ({index + 1}/{len(pieces)})"
            subject, topic, confidence = classify(f"{title} {piece}")
            uncertainty = page_uncertain or _has_uncertain_marker(piece)
            chunks.append(Chunk(
                title=heading[:200] or f"Seite {page_number}",
                content=piece.strip(),
                subject=subject,
                topic=topic,
                confidence=confidence,
                uncertainty=uncertainty,
                has_formula=_has_formula(piece),
                has_table=_has_table(piece),
                heading_level=level,
                metadata={
                    "source": source_label,
                    "page": page_number,
                    "quality": page_quality,
                    "length": len(piece),
                },
            ))
    return chunks


def deduplicate(chunks: list[Chunk]) -> list[Chunk]:
    """Drop near-duplicate chunks within one document."""

    seen: set[str] = set()
    out: list[Chunk] = []
    for chunk in chunks:
        key = re.sub(r"\W+", "", chunk.content.lower())[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


async def refine_with_ai(dispatcher, chunks: list[Chunk], *, max_chunks: int = 8) -> int:
    """Optionally improve subject/topic using the local model.

    Returns the number of chunks that were refined. Failures are swallowed: an
    import must never fail because the local model is unavailable.
    """

    refined = 0
    for chunk in chunks[:max_chunks]:
        if chunk.subject and chunk.confidence >= 0.5:
            continue
        prompt = (
            "Ordne den folgenden Auszug aus den Notizen eines angehenden "
            "Elektronikers für Energie- und Gebäudetechnik einem Fachgebiet zu.\n"
            'Antworte ausschließlich mit JSON: {"subject": "...", "topic": "..."}\n\n'
            f"Auszug:\n{chunk.content[:800]}"
        )
        try:
            payload, _ = await dispatcher.ask_json("classify", prompt, max_tokens=120)
        except Exception as exc:  # noqa: BLE001 - optional enrichment
            logger.debug("AI classification skipped: %s", exc)
            break
        if isinstance(payload, dict):
            subject = payload.get("subject")
            topic = payload.get("topic")
            if isinstance(subject, str) and subject.strip():
                chunk.subject = subject.strip()[:120]
                refined += 1
            if isinstance(topic, str) and topic.strip():
                chunk.topic = topic.strip()[:120]
    return refined
