"""Question generation.

Two independent sources:

1. **Deterministic generators** — these always work, even with no AI at all:
   * cloze questions built from definition sentences in the notes,
   * matching questions built from term/definition pairs,
   * calculation questions built from a curated formula library with randomised
     values (and a deterministically computed solution).

2. **AI generation** — uses the dispatcher (Ollama first). Generated questions
   are validated before they are stored: an empty prompt, a missing solution or
   an out-of-range correct index is rejected rather than stored.

Both paths record the knowledge items they were derived from so the UI can show
the source and page number.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from ..ai.base import AIError, reduce_text

logger = logging.getLogger("elektrocoach.learning.generator")

VALID_TYPES = {
    "multiple_choice", "freetext", "numeric", "matching", "cloze",
    "error_analysis", "circuit_analysis", "practical", "exam_question",
}

DIFFICULTY_LABELS = {1: "leicht", 2: "mittel", 3: "schwer"}

QUESTION_PROMPT = """Du erstellst Prüfungsaufgaben für die Abschlussprüfung zum \
Elektroniker für Energie- und Gebäudetechnik.

Fachgebiet: {subject}
Thema: {topic}

Auszüge aus den eigenen Notizen des Auszubildenden (nur diese Inhalte verwenden):
---
{context}
---

Erstelle genau {count} unterschiedliche Aufgaben der Typen: {types}.
Die Aufgaben müssen fachlich korrekt sein und dürfen nichts enthalten, was nicht \
aus den Auszügen hervorgeht oder gesichertes Grundlagenwissen ist.

Antworte ausschließlich mit einem JSON-Array. Jede Aufgabe hat diese Felder:
{{
  "type": "{first_type}",
  "difficulty": 2,
  "prompt": "vollständige Aufgabenstellung",
  "payload": {{}},
  "solution": {{}},
  "explanation": "Erklärung für die Lösung"
}}

Felder je Typ:
- "multiple_choice": payload {{"options": ["A", "B", "C", "D"]}}, solution {{"correct_index": 0, "max_points": 1}}
- "freetext": solution {{"model_answer": "...", "keywords": ["Begriff1", "Begriff2"], "max_points": 4}}
- "numeric": payload {{"unit": "V"}}, solution {{"expected": 230, "unit": "V", "tolerance_relative": 0.01, "max_points": 2, "steps": "Rechenweg"}}
- "matching": payload {{"left": ["a","b"], "right": ["1","2"]}}, solution {{"pairs": [[0,1],[1,0]], "max_points": 2}}
- "cloze": payload {{"text": "Text mit {{1}} Lücke"}}, solution {{"answers": [["Lösung"]], "max_points": 1}}
- "error_analysis" / "circuit_analysis" / "practical": solution {{"model_answer": "...", "keywords": ["..."], "max_points": 5}}

Verwende "difficulty" 1 bis 3. Antworte nur mit dem JSON-Array."""


@dataclass
class GeneratedQuestion:
    type: str
    prompt: str
    payload: dict[str, Any]
    solution: dict[str, Any]
    explanation: str | None = None
    subject: str | None = None
    topic: str | None = None
    difficulty: int = 2
    source_knowledge_ids: list[int] | None = None
    created_by: str = "system"


# Formula library for deterministic calculation questions. Each entry produces
# a question with randomised but physically sensible values.
FORMULAS: list[dict[str, Any]] = [
    {
        "subject": "Elektrotechnische Grundlagen",
        "topic": "Ohmsches Gesetz",
        "prompt": "Ein Widerstand von {R} Ω liegt an einer Spannung von {U} V. "
                  "Berechnen Sie den Strom.",
        "variables": {"R": ("choice", [22, 47, 100, 220, 470, 1000]),
                      "U": ("choice", [12, 24, 48, 230])},
        "expression": "U / R",
        "unit": "A",
        "steps": "I = U / R",
        "max_points": 2,
    },
    {
        "subject": "Elektrotechnische Grundlagen",
        "topic": "Elektrische Leistung",
        "prompt": "Ein Verbraucher nimmt bei {U} V einen Strom von {I} A auf. "
                  "Berechnen Sie die aufgenommene Leistung.",
        "variables": {"U": ("choice", [230, 400, 24, 12]),
                      "I": ("choice", [0.5, 1.0, 2.5, 4.0, 6.0])},
        "expression": "U * I",
        "unit": "W",
        "steps": "P = U · I",
        "max_points": 2,
    },
    {
        "subject": "Leitungsberechnung",
        "topic": "Spannungsfall",
        "prompt": "Eine Leitung aus Kupfer (κ = 56 m/(Ω·mm²)) mit einem Querschnitt "
                  "von {A} mm² und einer Länge von {L} m führt einen Strom von {I} A. "
                  "Berechnen Sie den Spannungsfall (Hin- und Rückleiter).",
        "variables": {"A": ("choice", [1.5, 2.5, 4.0, 6.0]),
                      "L": ("choice", [10, 15, 20, 25, 30]),
                      "I": ("choice", [10, 13, 16, 20, 25])},
        "expression": "2 * L * I / (56 * A)",
        "unit": "V",
        "steps": "ΔU = (2 · L · I) / (κ · A)",
        "max_points": 3,
    },
    {
        "subject": "Drehstrom",
        "topic": "Leistung im Drehstromnetz",
        "prompt": "Ein Drehstromverbraucher nimmt bei einer Außenleiterspannung von "
                  "{U} V einen Außenleiterstrom von {I} A auf. Der Leistungsfaktor "
                  "beträgt cos φ = {cos}. Berechnen Sie die Wirkleistung.",
        "variables": {"U": ("choice", [400]),
                      "I": ("choice", [5, 8, 10, 16, 20]),
                      "cos": ("choice", [0.8, 0.85, 0.9, 0.95])},
        "expression": "1.7320508 * U * I * cos",
        "unit": "W",
        "steps": "P = √3 · U · I · cos φ",
        "max_points": 3,
    },
    {
        "subject": "Wechselstrom",
        "topic": "Scheinleistung",
        "prompt": "Ein Wechselstromverbraucher nimmt bei {U} V einen Strom von "
                  "{I} A auf. Berechnen Sie die Scheinleistung.",
        "variables": {"U": ("choice", [230]), "I": ("choice", [2, 4, 6, 8, 10])},
        "expression": "U * I",
        "unit": "VA",
        "steps": "S = U · I",
        "max_points": 2,
    },
    {
        "subject": "Elektrotechnische Grundlagen",
        "topic": "Arbeit und Energie",
        "prompt": "Ein Gerät mit einer Leistung von {P} W läuft {t} Stunden. "
                  "Berechnen Sie die elektrische Arbeit in kWh.",
        "variables": {"P": ("choice", [500, 1000, 1500, 2000, 2500]),
                      "t": ("choice", [2, 3, 4, 5, 8])},
        "expression": "P * t / 1000",
        "unit": "kWh",
        "steps": "W = P · t",
        "max_points": 2,
    },
    {
        "subject": "Photovoltaik",
        "topic": "Ertrag einer PV-Anlage",
        "prompt": "Eine PV-Anlage mit {P} kWp hat einen spezifischen Jahresertrag "
                  "von {y} kWh/kWp. Berechnen Sie den Jahresertrag in kWh.",
        "variables": {"P": ("choice", [5, 8, 10, 12]),
                      "y": ("choice", [900, 950, 1000, 1050])},
        "expression": "P * y",
        "unit": "kWh",
        "steps": "E = P · spezifischer Ertrag",
        "max_points": 2,
    },
    {
        "subject": "Wärmepumpen",
        "topic": "Jahresarbeitszahl",
        "prompt": "Eine Wärmepumpe gibt {Q} kWh Wärme ab und nimmt dafür {E} kWh "
                  "elektrische Energie auf. Berechnen Sie die Jahresarbeitszahl.",
        "variables": {"Q": ("choice", [8000, 12000, 16000]),
                      "E": ("choice", [2000, 3000, 4000])},
        "expression": "Q / E",
        "unit": None,
        "steps": "JAZ = Q / E",
        "max_points": 2,
    },
]

_DEFINITION_RE = re.compile(
    r"^([A-ZÄÖÜ][\wÄÖÜäöüß\-\s]{3,60}?)\s+(?:ist|sind|bedeutet|bezeichnet)\s+(.{20,300})$",
    re.MULTILINE,
)


class QuestionGenerator:
    def __init__(self, repo, dispatcher=None) -> None:
        self.repo = repo
        self.dispatcher = dispatcher

    # -- deterministic: calculation -------------------------------------------

    def calculation_questions(self, *, subject: str | None = None,
                              count: int = 3, seed: int | None = None) -> list[int]:
        rng = random.Random(seed)
        pool = [f for f in FORMULAS if not subject or f["subject"] == subject]
        if not pool:
            pool = FORMULAS
        created: list[int] = []
        for _ in range(max(1, count)):
            formula = rng.choice(pool)
            created.append(self._store_calculation(formula, rng))
        return created

    def _store_calculation(self, formula: dict, rng: random.Random) -> int:
        values: dict[str, float] = {}
        for name, spec in formula["variables"].items():
            kind, options = spec
            if kind == "choice":
                values[name] = float(rng.choice(options))
            elif kind == "range":
                low, high, step = options
                values[name] = float(rng.randrange(int(low), int(high) + 1, int(step)))
            else:
                values[name] = float(options)

        from .calc import safe_eval

        expected = safe_eval(formula["expression"], values)
        prompt = formula["prompt"].format(**{
            key: _format_number(value) for key, value in values.items()
        })
        solution = {
            "expected": round(expected, 6),
            "unit": formula["unit"],
            "expression": formula["expression"],
            "variables": values,
            "steps": formula["steps"] + " → " + _format_number(round(expected, 6))
                     + (f" {formula['unit']}" if formula["unit"] else ""),
            "tolerance_relative": 0.01,
            "max_points": formula["max_points"],
        }
        return self.repo.create_question(
            type="numeric", prompt=prompt, subject=formula["subject"],
            topic=formula["topic"], difficulty=2,
            payload={"unit": formula["unit"], "values": values},
            solution=solution,
            explanation=f"Verwendete Formel: {formula['steps']}",
            created_by="deterministic",
        )

    # -- deterministic: cloze from definitions --------------------------------

    def cloze_questions(self, *, subject: str | None = None, count: int = 3,
                        knowledge_ids: list[int] | None = None) -> list[int]:
        items = self._knowledge_pool(subject, knowledge_ids, limit=60)
        created: list[int] = []
        for item in items:
            if len(created) >= count:
                break
            for term, definition in _DEFINITION_RE.findall(item["content"])[:1]:
                if len(definition.strip()) < 25:
                    continue
                gap_index = definition.find(term)
                if gap_index == -1:
                    # Use the first meaningful noun as the gap.
                    words = [w for w in re.findall(r"[A-ZÄÖÜ][\wÄÖÜäöüß\-]{4,}", definition)]
                    if not words:
                        continue
                    term = words[0]
                    gap_index = definition.find(term)
                    if gap_index == -1:
                        continue
                masked = definition[:gap_index] + "____" + definition[gap_index + len(term):]
                question_id = self.repo.create_question(
                    type="cloze",
                    prompt=f"Ergänzen Sie den fehlenden Fachbegriff:\n\n{masked}",
                    subject=item.get("subject") or subject,
                    topic=item.get("topic"),
                    difficulty=1,
                    payload={"text": masked},
                    solution={"answers": [[term]], "max_points": 1,
                              "model_answer": definition},
                    explanation=f"Aus: {item.get('source_label') or 'Notizen'}, "
                                f"Seite {item.get('page_number') or '?'}",
                    source_knowledge_ids=[item["id"]],
                    created_by="deterministic",
                )
                created.append(question_id)
                break
        return created

    # -- deterministic: matching ----------------------------------------------

    def matching_questions(self, *, subject: str | None = None, count: int = 2,
                           knowledge_ids: list[int] | None = None) -> list[int]:
        items = self._knowledge_pool(subject, knowledge_ids, limit=80)
        pairs: list[tuple[str, str]] = []
        for item in items:
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not title or len(content) < 30:
                continue
            summary = content.split(".")[0][:140].strip()
            if len(summary) < 20:
                continue
            pairs.append((title[:60], summary))
            if len(pairs) >= 8:
                break

        created: list[int] = []
        rng = random.Random()
        for _ in range(max(1, count)):
            if len(pairs) < 4:
                break
            chosen = rng.sample(pairs, 4)
            left = [p[0] for p in chosen]
            right = [p[1] for p in chosen]
            shuffled = list(range(4))
            rng.shuffle(shuffled)
            solution_pairs = [[i, shuffled[i]] for i in range(4)]
            question_id = self.repo.create_question(
                type="matching",
                prompt="Ordnen Sie die Fachbegriffe den passenden Erläuterungen zu.",
                subject=subject,
                topic="Zuordnung",
                difficulty=2,
                payload={"left": left, "right": [right[i] for i in shuffled]},
                solution={"pairs": solution_pairs, "max_points": 4},
                explanation="Ordnen Sie jeden Begriff der inhaltlich passenden "
                            "Erläuterung zu.",
                created_by="deterministic",
            )
            created.append(question_id)
        return created

    # -- AI generation --------------------------------------------------------

    def ai_questions(self, *, subject: str, topic: str | None = None, count: int = 3,
                     types: list[str] | None = None,
                     knowledge_ids: list[int] | None = None) -> list[int]:
        if self.dispatcher is None:
            raise AIError(
                "Für die KI-Generierung ist der KI-Dispatcher nicht verfügbar.",
                guidance="Prüfen Sie den Systemstatus.",
            )
        types = [t for t in (types or ["multiple_choice", "freetext", "numeric"])
                 if t in VALID_TYPES] or ["multiple_choice"]
        excerpts = self._context_for(subject, topic, knowledge_ids)
        if not excerpts:
            logger.info("no knowledge available for %s / %s", subject, topic)
            return []

        prompt = QUESTION_PROMPT.format(
            subject=subject,
            topic=topic or "Allgemein",
            context=excerpts,
            count=max(1, min(6, count)),
            types=", ".join(types),
            first_type=types[0],
        )
        try:
            from ..backend.runtime import run_coroutine

            payload, result = run_coroutine(
                self.dispatcher.ask_json("simple_exercise", prompt,
                                         max_tokens=2200, use_cache=False)
            )
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIError(
                f"Die KI-Generierung ist fehlgeschlagen: {exc}",
                guidance="Prüfen Sie im Systemstatus, ob Ollama oder Gemini erreichbar ist.",
            ) from exc

        raw_items = payload if isinstance(payload, list) else payload.get("questions", [])
        source_ids = self._source_ids(subject, topic, knowledge_ids)
        created: list[int] = []
        rejected = 0
        for raw in raw_items:
            validated = self._validate_ai_question(raw, subject, topic, types)
            if validated is None:
                rejected += 1
                continue
            question_id = self.repo.create_question(
                type=validated.type, prompt=validated.prompt,
                subject=validated.subject, topic=validated.topic,
                difficulty=validated.difficulty, payload=validated.payload,
                solution=validated.solution, explanation=validated.explanation,
                source_knowledge_ids=validated.source_knowledge_ids,
                created_by=f"ai:{result.provider}",
            )
            created.append(question_id)
        if rejected:
            logger.info("rejected %s invalid AI questions", rejected)
        if created:
            self.repo.audit("questions.ai_generate", target=subject,
                            detail={"created": len(created), "rejected": rejected,
                                    "provider": result.provider})
        return created

    def _validate_ai_question(self, raw: Any, subject: str, topic: str | None,
                              allowed_types: list[str]) -> GeneratedQuestion | None:
        if not isinstance(raw, dict):
            return None
        qtype = str(raw.get("type") or "").strip()
        if qtype not in VALID_TYPES:
            return None
        prompt = str(raw.get("prompt") or "").strip()
        if len(prompt) < 15:
            return None
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        solution = raw.get("solution") if isinstance(raw.get("solution"), dict) else {}
        try:
            difficulty = int(raw.get("difficulty") or 2)
        except (TypeError, ValueError):
            difficulty = 2
        difficulty = max(1, min(3, difficulty))

        # Type specific validation: never store a question that cannot be graded.
        if qtype == "multiple_choice":
            options = payload.get("options")
            if not isinstance(options, list) or len(options) < 2:
                return None
            index = solution.get("correct_index")
            try:
                index = int(index)
            except (TypeError, ValueError):
                return None
            if not 0 <= index < len(options):
                return None
            payload["options"] = [str(o) for o in options]
            solution["correct_index"] = index
        elif qtype == "numeric":
            if solution.get("expected") is None and not solution.get("expression"):
                return None
            try:
                solution["expected"] = float(solution["expected"])
            except (TypeError, ValueError, KeyError):
                if not solution.get("expression"):
                    return None
        elif qtype == "matching":
            left = payload.get("left")
            right = payload.get("right")
            pairs = solution.get("pairs")
            if not isinstance(left, list) or not isinstance(right, list):
                return None
            if not isinstance(pairs, list) or not pairs:
                return None
            cleaned: list[list[int]] = []
            for pair in pairs:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    try:
                        a, b = int(pair[0]), int(pair[1])
                    except (TypeError, ValueError):
                        continue
                    if 0 <= a < len(left) and 0 <= b < len(right):
                        cleaned.append([a, b])
            if not cleaned:
                return None
            solution["pairs"] = cleaned
        elif qtype == "cloze":
            answers = solution.get("answers")
            if not isinstance(answers, list) or not answers:
                return None
            normalised_answers = []
            for entry in answers:
                if isinstance(entry, list):
                    normalised_answers.append([str(x) for x in entry if str(x).strip()])
                elif str(entry).strip():
                    normalised_answers.append([str(entry)])
                else:
                    return None
            solution["answers"] = normalised_answers
        else:  # open types
            keywords = solution.get("keywords")
            if not isinstance(keywords, list) or not keywords:
                solution["keywords"] = []
            if not solution.get("model_answer"):
                return None

        solution.setdefault("max_points", payload.get("max_points", 2))
        return GeneratedQuestion(
            type=qtype,
            prompt=prompt,
            payload=payload,
            solution=solution,
            explanation=str(raw.get("explanation") or "").strip() or None,
            subject=str(raw.get("subject") or subject),
            topic=str(raw.get("topic") or topic or "Allgemein"),
            difficulty=difficulty,
            source_knowledge_ids=self._source_ids(subject, topic, None),
        )

    # -- helpers --------------------------------------------------------------

    def _knowledge_pool(self, subject: str | None, knowledge_ids: list[int] | None,
                        limit: int = 50) -> list[dict]:
        if knowledge_ids:
            items = []
            for item_id in knowledge_ids:
                item = self.repo.get_knowledge(item_id)
                if item:
                    items.append(item)
            return items
        return self.repo.list_knowledge(limit=limit, subject=subject)

    def _source_ids(self, subject: str, topic: str | None,
                    knowledge_ids: list[int] | None) -> list[int]:
        if knowledge_ids:
            return list(knowledge_ids)
        items = self.repo.list_knowledge(limit=5, subject=subject, topic=topic)
        return [int(i["id"]) for i in items]

    def _context_for(self, subject: str, topic: str | None,
                     knowledge_ids: list[int] | None, max_chars: int = 4000) -> str:
        items = self._knowledge_pool(subject, knowledge_ids, limit=12)
        if topic:
            topic_items = [i for i in items if (i.get("topic") or "") == topic]
            items = topic_items or items
        parts: list[str] = []
        used = 0
        for item in items:
            excerpt = reduce_text(item.get("content") or "", 700)
            if not excerpt:
                continue
            block = (
                f"[{item.get('source_label') or 'Notiz'}, Seite "
                f"{item.get('page_number') or '?'}] {item.get('title')}: {excerpt}"
            )
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}".replace(".", ",")
