"""Lernsystem: Themenkatalog, Wissensaufbau, Fragengenerierung, Bewertung,
Lernplan, Spaced Repetition und Pruefungssimulation.

Alle KI-Aufrufe laufen ueber ai_router. Ist keine KI erreichbar, greifen die
deterministischen Verfahren aus offline.py. Ergebnisse, die nicht sicher sind,
werden mit needs_review = 1 gekennzeichnet.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from .. import db
from ..config import settings
from . import ai_router, offline, srs

log = logging.getLogger(__name__)

QTYPES = {
    "multiple_choice", "open", "calculation", "cloze", "true_false", "practical",
}

SYSTEM_TUTOR = (
    "Du bist Fachdozent fuer Elektrotechnik, Schwerpunkt Energie- und "
    "Gebaeudetechnik, und bereitest auf die Abschlusspruefung vor. "
    "Antworte auf Deutsch, fachlich korrekt, nachvollziehbar und ohne Floskeln. "
    "Rechne in SI-Einheiten und gib bei Rechenaufgaben immer den vollstaendigen "
    "Loesungsweg mit Formel, Einsetzen und Ergebnis an. "
    "Wenn eine Angabe fehlt oder unsicher ist, sage das ausdruecklich."
)


# ---------------------------------------------------------------------------
# Themenkatalog
# ---------------------------------------------------------------------------
def ensure_default_topics() -> int:
    """Legt den fachlichen Themenkatalog an, falls er noch leer ist."""
    existing = db.query_one("SELECT COUNT(*) AS n FROM topics")
    if existing and existing["n"] > 0:
        return 0
    created = 0
    for order, (slug, terms) in enumerate(sorted(offline.DOMAIN_TERMS.items())):
        name = _topic_name(slug)
        db.insert(
            "INSERT OR IGNORE INTO topics(id, slug, name, description, coverage, source, "
            "ordering, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (db.new_id(), slug, name, "Stichworte: " + ", ".join(terms[:6]), 0.0,
             "catalog", order, db.now(), db.now()),
        )
        created += 1
    return created


_TOPIC_LABELS = {
    "schutzkleinspannung": "Schutzkleinspannung (SELV/PELV)",
    "netzsysteme": "Netzsysteme (TN/TT/IT)",
    "schutzleiter": "Schutzleiter, Erdung und Potentialausgleich",
    "rcd": "Fehlerstrom-Schutzeinrichtungen (RCD/FI)",
    "leitungsschutzschalter": "Leitungsschutz und Schutzeinrichtungen",
    "leitungsberechnung": "Leitungsdimensionierung und Spannungsfall",
    "drehstrom": "Drehstromtechnik und Drehstrommotor",
    "wechselstrom": "Wechselstromtechnik und Leistungen",
    "gleichstrom": "Gleichstromtechnik und Grundgesetze",
    "schuetzschaltung": "Schuetz- und Steuerschaltungen",
    "steuerungstechnik": "Steuerungstechnik und SPS",
    "beleuchtung": "Beleuchtungstechnik",
    "installation": "Elektroinstallation und Verteilungen",
    "hausanschluss": "Hausanschluss und Hauptverteilung",
    "blitzschutz": "Blitzschutz und Ueberspannungsschutz",
    "photovoltaik": "Photovoltaik und Eigenverbrauch",
    "elektromobilitaet": "Elektromobilitaet und Ladeinfrastruktur",
    "waermepumpe": "Waermepumpen und Heizungstechnik",
    "gebaeudeautomation": "Gebaeudeautomation und Bussysteme",
    "sicherheit": "Arbeitssicherheit und Unfallverhuetung",
    "messtechnik": "Messtechnik und Messverfahren",
    "normen": "Normen und Vorschriften (DIN VDE)",
    "werkstoffe": "Werkstoffe und Leitungsarten",
    "motoren": "Elektrische Maschinen und Antriebe",
    "transformatoren": "Transformatoren",
    "sicherungen": "Sicherungen und Schutzcharakteristiken",
    "kompensation": "Blindleistungskompensation",
    "energiemanagement": "Energiemanagement und Effizienz",
}


def _topic_name(slug: str) -> str:
    return _TOPIC_LABELS.get(slug, slug.replace("-", " ").title())


def list_topics() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT t.*, "
        "  (SELECT COUNT(*) FROM topic_chunks tc WHERE tc.topic_id = t.id) AS chunk_count, "
        "  (SELECT COUNT(*) FROM questions q WHERE q.topic_id = t.id) AS question_count "
        "FROM topics t ORDER BY t.ordering, t.name"
    )
    out = []
    for row in rows:
        item = dict(row)
        item["mastery"] = _topic_mastery(row["id"], row["chunk_count"], row["question_count"])
        out.append(item)
    return out


def _topic_mastery(topic_id: str, chunk_count: int, question_count: int) -> dict[str, Any]:
    row = db.query_one(
        "SELECT SUM(a.score) AS got, SUM(a.max_points) AS total, COUNT(*) AS n "
        "FROM attempts a JOIN questions q ON q.id = a.question_id WHERE q.topic_id = ?",
        (topic_id,),
    )
    total = float(row["total"] or 0) if row else 0.0
    got = float(row["got"] or 0) if row else 0.0
    accuracy = (got / total) if total > 0 else 0.0
    coverage = min(1.0, chunk_count / 12.0)
    return srs.mastery_level(accuracy, coverage, question_count)


def analyze_topics(use_ai: bool = True) -> dict[str, Any]:
    """Ordnet Abschnitte den Themen zu und aktualisiert die Abdeckung."""
    ensure_default_topics()
    topics = {row["slug"]: row["id"] for row in db.query("SELECT id, slug FROM topics")}
    chunks = db.query(
        "SELECT id, text, heading FROM chunks ORDER BY created_at DESC LIMIT 4000"
    )
    assignments: dict[str, list[tuple[str, float]]] = {tid: [] for tid in topics.values()}

    for chunk in chunks:
        haystack = f"{chunk['heading'] or ''}\n{chunk['text']}"
        detected = offline.detect_topics(haystack)
        for item in detected:
            topic_id = topics.get(str(item["slug"]))
            if topic_id:
                weight = float(item["hits"])
                assignments[topic_id].append((chunk["id"], weight))

    db.execute("DELETE FROM topic_chunks")
    rows: list[tuple] = []
    for topic_id, pairs in assignments.items():
        for chunk_id, weight in pairs[:400]:
            rows.append((topic_id, chunk_id, weight))
    if rows:
        db.executemany(
            "INSERT OR IGNORE INTO topic_chunks(topic_id, chunk_id, weight) VALUES(?,?,?)",
            rows,
        )

    coverage_report: list[dict[str, Any]] = []
    for row in db.query("SELECT id, slug, name FROM topics"):
        count = db.query_one(
            "SELECT COUNT(*) AS n FROM topic_chunks WHERE topic_id = ?", (row["id"],)
        )
        n = int(count["n"]) if count else 0
        coverage = min(1.0, n / 12.0)
        db.execute(
            "UPDATE topics SET coverage = ?, updated_at = ? WHERE id = ?",
            (coverage, db.now(), row["id"]),
        )
        coverage_report.append({
            "slug": row["slug"], "name": row["name"], "chunks": n,
            "coverage": round(coverage, 3),
            "gap": n == 0,
        })

    gaps = [item for item in coverage_report if item["gap"]]
    return {
        "assigned_chunks": len(rows),
        "topics": len(coverage_report),
        "gaps": gaps,
        "covered": [item for item in coverage_report if not item["gap"]],
        "ai_used": False,
        "method": "keyword-matching (deterministisch)",
    }


def missing_topics() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT t.id, t.slug, t.name, "
        "(SELECT COUNT(*) FROM topic_chunks tc WHERE tc.topic_id = t.id) AS chunks "
        "FROM topics t ORDER BY chunks ASC, t.ordering"
    )
    return [
        {"id": r["id"], "slug": r["slug"], "name": r["name"], "chunks": r["chunks"]}
        for r in rows if r["chunks"] < 3
    ]


# ---------------------------------------------------------------------------
# Fragengenerierung
# ---------------------------------------------------------------------------
def _context_for_topic(topic_id: str, max_chunks: int = 6, max_chars: int = 5000) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT c.id, c.text, c.heading, c.page_number, c.document_id, d.filename "
        "FROM topic_chunks tc JOIN chunks c ON c.id = tc.chunk_id "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE tc.topic_id = ? ORDER BY tc.weight DESC LIMIT ?",
        (topic_id, max_chunks),
    )
    out: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        if total + len(row["text"]) > max_chars:
            break
        out.append(dict(row))
        total += len(row["text"])
    return out


async def generate_questions(
    topic_id: str | None,
    qtype: str = "multiple_choice",
    count: int = 5,
    difficulty: int = 2,
    use_ai: bool = True,
) -> dict[str, Any]:
    ensure_default_topics()
    if qtype not in QTYPES:
        qtype = "multiple_choice"
    count = max(1, min(settings.get_int("question_max_count", 20), count))
    difficulty = max(1, min(5, difficulty))

    if not topic_id:
        row = db.query_one(
            "SELECT id FROM topics WHERE id IN (SELECT topic_id FROM topic_chunks) "
            "ORDER BY RANDOM() LIMIT 1"
        )
        topic_id = row["id"] if row else None

    topic_name = "Allgemeine Elektrotechnik"
    if topic_id:
        row = db.query_one("SELECT name FROM topics WHERE id = ?", (topic_id,))
        topic_name = row["name"] if row else topic_name

    context = _context_for_topic(topic_id) if topic_id else []
    source_ids = [c["id"] for c in context]

    created: list[dict[str, Any]] = []
    ai_used = False
    if use_ai:
        ai_questions = await _ai_generate(topic_name, qtype, count, difficulty, context)
        if ai_questions:
            ai_used = True
            for item in ai_questions:
                created.append(_store_question(item, topic_id, source_ids, "ai"))

    if len(created) < count and context:
        needed = count - len(created)
        for item in _offline_generate(topic_name, qtype, needed, difficulty, context):
            created.append(_store_question(item, topic_id, source_ids, "offline"))

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "qtype": qtype,
        "created": len(created),
        "questions": created,
        "ai_used": ai_used,
        "note": None if ai_used else (
            "Offline erzeugte Fragen sind als pruefbeduerftig markiert. "
            "Bitte Inhalt und Loesung kontrollieren."
        ),
    }


async def _ai_generate(
    topic_name: str, qtype: str, count: int, difficulty: int,
    context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not context:
        return []
    material = "\n\n".join(
        f"[{c['filename']} S.{c['page_number']}]\n{c['text'][:900]}" for c in context
    )
    type_hint = {
        "multiple_choice": "Multiple-Choice mit genau 4 Antwortoptionen (A-D), eine davon richtig",
        "open": "offene Frage mit Musterantwort",
        "calculation": "Rechenaufgabe mit gegeben/gesucht/Formel/Loesungsweg/Ergebnis",
        "cloze": "Lueckentext",
        "true_false": "Aussage mit richtig/falsch",
        "practical": "praxisbezogene Aufgabe aus dem Berufsalltag",
    }.get(qtype, "Frage")

    prompt = (
        f"Erstelle {count} Aufgaben zum Thema \"{topic_name}\" "
        f"(Schwierigkeit {difficulty} von 5). Aufgabenart: {type_hint}.\n\n"
        "Nutze ausschliesslich das folgende Material aus den eigenen Aufzeichnungen "
        "als fachliche Grundlage. Wenn das Material nicht ausreicht, formuliere die "
        "Aufgabe trotzdem, setze aber \"unsicher\": true.\n\n"
        f"MATERIAL:\n{material}\n\n"
        "Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat die Felder:\n"
        '  "prompt" (Aufgabentext), "options" (Array mit 4 Strings bei multiple_choice, '
        'sonst []), "answer" (richtige Antwort, bei multiple_choice der Buchstabe A-D), '
        '"solution_steps" (Loesungsweg, bei Rechenaufgaben vollstaendig), '
        '"explanation" (kurze fachliche Erklaerung), "difficulty" (1-5), '
        '"points" (Punkte), "unsicher" (true/false).'
    )
    result = await ai_router.complete(
        prompt, system=SYSTEM_TUTOR, task="question_generation",
        json_mode=True, temperature=0.4, max_output_tokens=3000,
    )
    if not result.get("ok"):
        log.info("KI-Fragengenerierung nicht verfuegbar: %s", result.get("error"))
        return []
    parsed = ai_router.parse_json(result.get("text", ""))
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("prompt"):
            continue
        options = item.get("options") or []
        if not isinstance(options, list):
            options = []
        out.append({
            "prompt": str(item["prompt"])[:4000],
            "options": [str(o)[:500] for o in options][:6],
            "answer": str(item.get("answer", ""))[:2000],
            "solution_steps": str(item.get("solution_steps", ""))[:4000],
            "explanation": str(item.get("explanation", ""))[:4000],
            "difficulty": int(item.get("difficulty") or difficulty),
            "points": float(item.get("points") or 1),
            "needs_review": bool(item.get("unsicher")),
            "ai_source": result.get("provider", "ai"),
        })
    return out


def _offline_generate(
    topic_name: str, qtype: str, count: int, difficulty: int,
    context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministische Ersatzfragen ohne KI."""
    material = "\n\n".join(c["text"] for c in context)
    out: list[dict[str, Any]] = []
    if qtype in {"cloze", "open"}:
        for item in offline.cloze_questions(material, max_items=count):
            out.append({
                "prompt": item["prompt"], "options": [], "answer": item["answer"],
                "solution_steps": "", "explanation":
                    "Offline erzeugt aus dem eigenen Material. Bitte fachlich pruefen.",
                "difficulty": difficulty, "points": 1.0,
                "needs_review": True, "ai_source": "offline", "qtype": "cloze",
            })
    if len(out) < count:
        terms = [t for t in offline.keywords(material, limit=40) if len(t) > 5]
        for term in terms:
            if len(out) >= count:
                break
            sentence = _sentence_with(material, term)
            if not sentence:
                continue
            out.append({
                "prompt": (
                    f"Thema {topic_name}: Erklaeren Sie den Fachbegriff "
                    f"\"{term}\" im Kontext der Energie- und Gebaeudetechnik."
                ),
                "options": [],
                "answer": term,
                "solution_steps": "",
                "explanation": (
                    f"Fundstelle im eigenen Material: {sentence[:300]}\n\n"
                    "Offline erzeugte Frage. Musterantwort bitte ergaenzen."
                ),
                "difficulty": difficulty, "points": 2.0,
                "needs_review": True, "ai_source": "offline",
                "qtype": "open" if qtype in {"open", "calculation"} else "cloze",
            })
    return out[:count]


def _sentence_with(text: str, term: str) -> str | None:
    import re

    for sentence in offline.split_sentences(text):
        if re.search(rf"(?i)\b{re.escape(term)}\b", sentence):
            return sentence
    return None


def _store_question(
    item: dict[str, Any], topic_id: str | None, source_ids: list[str], source: str,
) -> dict[str, Any]:
    question_id = db.new_id()
    qtype = item.get("qtype") or ("multiple_choice" if item.get("options") else "open")
    needs_review = bool(item.get("needs_review"))
    if needs_review and not settings.get_bool("mark_unverified", True):
        needs_review = False
    db.insert(
        "INSERT INTO questions(id, topic_id, qtype, difficulty, prompt, options_json, answer, "
        "solution_steps, explanation, points, source_chunk_ids, ai_source, verified, "
        "needs_review, tags, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (question_id, topic_id, qtype, int(item.get("difficulty", 2)),
         item["prompt"], db.json_dumps_safe(item.get("options", [])),
         item.get("answer", ""), item.get("solution_steps", ""),
         item.get("explanation", ""), float(item.get("points", 1)),
         db.json_dumps_safe(source_ids), source, 0,
         1 if needs_review else 0, "", db.now(), db.now()),
    )
    srs_state = srs.SrsState()
    db.insert(
        "INSERT OR REPLACE INTO srs(question_id, ease, interval_days, repetitions, lapses, "
        "state, due_at, last_reviewed_at) VALUES(?,?,?,?,?,?,?,?)",
        (question_id, srs_state.ease, srs_state.interval_days, srs_state.repetitions,
         srs_state.lapses, srs_state.state, db.now(), None),
    )
    return get_question(question_id) or {"id": question_id}


def get_question(question_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT q.*, t.name AS topic_name FROM questions q "
        "LEFT JOIN topics t ON t.id = q.topic_id WHERE q.id = ?",
        (question_id,),
    )
    if not row:
        return None
    item = dict(row)
    item["options"] = _load_json(item.pop("options_json", "[]"), [])
    item["source_chunk_ids"] = _load_json(item.pop("source_chunk_ids", "[]"), [])
    item["sources"] = _sources_for(item["source_chunk_ids"])
    srs_row = db.query_one("SELECT * FROM srs WHERE question_id = ?", (question_id,))
    item["srs"] = dict(srs_row) if srs_row else None
    return item


def _load_json(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _sources_for(chunk_ids: list[str]) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []
    placeholders = ",".join("?" for _ in chunk_ids[:8])
    rows = db.query(
        f"SELECT c.id, c.page_number, c.heading, c.document_id, d.filename, "  # noqa: S608
        f"substr(c.text, 1, 300) AS excerpt FROM chunks c "
        f"JOIN documents d ON d.id = c.document_id WHERE c.id IN ({placeholders})",
        chunk_ids[:8],
    )
    return [dict(r) for r in rows]


def list_questions(
    topic_id: str | None = None, qtype: str | None = None,
    needs_review: bool | None = None, limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if topic_id:
        where.append("q.topic_id = ?")
        params.append(topic_id)
    if qtype:
        where.append("q.qtype = ?")
        params.append(qtype)
    if needs_review is not None:
        where.append("q.needs_review = ?")
        params.append(1 if needs_review else 0)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = db.query_one(f"SELECT COUNT(*) AS n FROM questions q {clause}", params)  # noqa: S608
    rows = db.query(
        f"SELECT q.*, t.name AS topic_name, s.due_at, s.state AS srs_state, "  # noqa: S608
        f"(SELECT COUNT(*) FROM attempts a WHERE a.question_id = q.id) AS attempt_count "
        f"FROM questions q LEFT JOIN topics t ON t.id = q.topic_id "
        f"LEFT JOIN srs s ON s.question_id = q.id {clause} "
        f"ORDER BY q.updated_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    items = []
    for row in rows:
        item = dict(row)
        item["options"] = _load_json(item.pop("options_json", "[]"), [])
        items.append(item)
    return {"total": total["n"] if total else 0, "items": items}


def delete_question(question_id: str) -> bool:
    row = db.query_one("SELECT id FROM questions WHERE id = ?", (question_id,))
    if not row:
        return False
    db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    return True


# ---------------------------------------------------------------------------
# Bewertung
# ---------------------------------------------------------------------------
async def grade_answer(
    question_id: str, user_answer: str, duration_ms: int = 0,
    session_id: str | None = None, exam_id: str | None = None, use_ai: bool = True,
    provider: str | None = None,
) -> dict[str, Any]:
    question = get_question(question_id)
    if not question:
        raise ValueError("Frage nicht gefunden")

    qtype = question["qtype"]
    max_points = float(question["points"] or 1)
    feedback = ""
    needs_review = False
    ai_used = False
    detail: dict[str, Any] = {}

    if qtype == "multiple_choice":
        outcome = offline.grade_multiple_choice(user_answer, question["answer"], max_points)
        score = outcome["score"]
        correct = outcome["correct"]
    elif qtype == "true_false":
        outcome = offline.grade_multiple_choice(user_answer, question["answer"], max_points)
        score = outcome["score"]
        correct = outcome["correct"]
    elif qtype == "calculation":
        numeric = offline.grade_numeric(user_answer, question["answer"])
        if numeric.get("needs_review"):
            grade, feedback, needs_review, ai_used = await _grade_text(
                question, user_answer, max_points, use_ai, provider
            )
            score, correct = grade, grade >= max_points * 0.5
        else:
            score = float(numeric["score"]) * max_points
            correct = bool(numeric["correct"])
            detail = numeric
            if not correct:
                feedback = (
                    f"Ergebnis weicht ab. Erwartet: {numeric.get('target')}, "
                    f"eingegeben: {numeric.get('given')}. "
                    f"Zulaessige Abweichung: {int(float(numeric.get('tolerance', 0.02)) * 100)} %."
                )
    elif qtype == "cloze":
        normalise = lambda s: " ".join(offline.tokenize(str(s)))  # noqa: E731
        given = normalise(user_answer)
        target = normalise(question["answer"])
        correct = bool(target) and (target in given or given in target)
        score = max_points if correct else 0.0
        if not correct:
            feedback = f"Erwartete Loesung: {question['answer']}"
    else:
        grade, feedback, needs_review, ai_used = await _grade_text(
            question, user_answer, max_points, use_ai, provider
        )
        score, correct = grade, grade >= max_points * 0.5

    if not feedback and question.get("explanation"):
        feedback = question["explanation"]

    attempt_id = db.new_id()
    db.insert(
        "INSERT INTO attempts(id, question_id, session_id, exam_id, user_answer, score, "
        "max_points, feedback, needs_review, duration_ms, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (attempt_id, question_id, session_id, exam_id, str(user_answer)[:8000], score,
         max_points, feedback[:4000], 1 if needs_review else 0, duration_ms, db.now()),
    )

    srs_state, due = _apply_srs(question_id, score, max_points)

    return {
        "attempt_id": attempt_id,
        "question_id": question_id,
        "score": round(score, 3),
        "max_points": max_points,
        "correct": correct,
        "partial": 0 < score < max_points,
        "feedback": feedback,
        "solution_steps": question.get("solution_steps", ""),
        "reference_answer": question.get("answer", ""),
        "needs_review": needs_review,
        "ai_used": ai_used,
        "detail": detail,
        "sources": question.get("sources", []),
        "srs": {**srs_state.as_dict(), "due_at": due.strftime("%Y-%m-%dT%H:%M:%S")},
    }


async def _grade_text(
    question: dict[str, Any], user_answer: str, max_points: float, use_ai: bool,
    provider: str | None = None,
) -> tuple[float, str, bool, bool]:
    """Bewertet offene oder Rechenaufgaben. KI wenn moeglich, sonst Schluesselwoerter."""
    if use_ai and user_answer.strip():
        prompt = (
            f"Aufgabe: {question['prompt']}\n\n"
            f"Musterloesung: {question.get('answer', '')}\n\n"
            f"Loesungsweg: {question.get('solution_steps', '')}\n\n"
            f"Antwort des Lernenden: {user_answer}\n\n"
            "Bewerte die Antwort. Antworte nur mit JSON:\n"
            '{"punkte": <0 bis '
            f"{max_points}"
            '>, "richtig": <true/false>, "teilpunkte": <true/false>, '
            '"feedback": "<kurze Begruendung, was fehlt und was richtig ist>", '
            '"loesungsweg": "<vollstaendiger Rechenweg, falls Rechenaufgabe, sonst leer>"}'
        )
        result = await ai_router.complete(
            prompt, system=SYSTEM_TUTOR, task="grading", json_mode=True,
            temperature=0.1, max_output_tokens=1200, provider=provider,
        )
        if result.get("ok"):
            parsed = ai_router.parse_json(result.get("text", ""))
            if isinstance(parsed, dict) and "punkte" in parsed:
                try:
                    points = max(0.0, min(float(parsed["punkte"]), max_points))
                except (TypeError, ValueError):
                    points = 0.0
                feedback = str(parsed.get("feedback", ""))[:3000]
                if parsed.get("loesungsweg") and not question.get("solution_steps"):
                    feedback += "\n\nLoesungsweg: " + str(parsed["loesungsweg"])[:3000]
                return points, feedback, False, True

    outcome = offline.grade_open_answer(user_answer, question.get("answer", ""))
    score = float(outcome["score"]) * max_points
    feedback = (
        f"Automatische Bewertung ohne KI (Schluesselwortvergleich). "
        f"Trefferquote {int(float(outcome['score']) * 100)} %."
    )
    if outcome["missing"]:
        feedback += " Fehlende Begriffe: " + ", ".join(str(m) for m in outcome["missing"][:12])
    feedback += "\nBitte fachlich pruefen - diese Bewertung ist eine Orientierung."
    return score, feedback, bool(outcome["needs_review"]), False


def _apply_srs(question_id: str, score: float, max_points: float) -> tuple[srs.SrsState, dt.datetime]:
    row = db.query_one("SELECT * FROM srs WHERE question_id = ?", (question_id,))
    state = srs.SrsState(
        ease=float(row["ease"]) if row else srs.DEFAULT_EASE,
        interval_days=float(row["interval_days"]) if row else 0.0,
        repetitions=int(row["repetitions"]) if row else 0,
        lapses=int(row["lapses"]) if row else 0,
        state=str(row["state"]) if row else "new",
    )
    quality = srs.quality_from_score(score, max_points)
    new_state, due = srs.review(state, quality)
    db.execute(
        "INSERT INTO srs(question_id, ease, interval_days, repetitions, lapses, state, "
        "due_at, last_reviewed_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(question_id) DO UPDATE SET ease=excluded.ease, "
        "interval_days=excluded.interval_days, repetitions=excluded.repetitions, "
        "lapses=excluded.lapses, state=excluded.state, due_at=excluded.due_at, "
        "last_reviewed_at=excluded.last_reviewed_at",
        (question_id, new_state.ease, new_state.interval_days, new_state.repetitions,
         new_state.lapses, new_state.state, due.strftime("%Y-%m-%dT%H:%M:%S"),
         db.now()),
    )
    return new_state, due


# ---------------------------------------------------------------------------
# Faellige Wiederholungen und Lernplan
# ---------------------------------------------------------------------------
def due_questions(limit: int = 50) -> list[dict[str, Any]]:
    now = db.now()
    rows = db.query(
        "SELECT q.id, q.prompt, q.qtype, q.difficulty, q.points, q.topic_id, t.name AS topic_name, "
        "s.due_at, s.interval_days, s.state, s.ease "
        "FROM srs s JOIN questions q ON q.id = s.question_id "
        "LEFT JOIN topics t ON t.id = q.topic_id "
        "WHERE s.due_at IS NOT NULL AND s.due_at <= ? ORDER BY s.due_at LIMIT ?",
        (now, limit),
    )
    return [dict(r) for r in rows]


def due_count() -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM srs WHERE due_at IS NOT NULL AND due_at <= ?", (db.now(),)
    )
    return int(row["n"]) if row else 0


def study_plan(minutes: int | None = None) -> dict[str, Any]:
    minutes = minutes or settings.get_int("daily_study_minutes", 45)
    due = due_questions(limit=200)
    now = dt.datetime.now()
    items = []
    for row in due:
        try:
            due_at = dt.datetime.strptime(row["due_at"], "%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            due_at = now
        overdue_days = (now - due_at).total_seconds() / 86400
        items.append({
            "question_id": row["id"],
            "topic": row["topic_name"],
            "qtype": row["qtype"],
            "difficulty": row["difficulty"],
            "interval_days": row["interval_days"],
            "overdue_days": round(max(0.0, overdue_days), 2),
            "priority": srs.due_score(float(row["interval_days"] or 0), overdue_days),
        })

    schedule = srs.plan_daily_schedule(items, minutes)

    weak_topics = db.query(
        "SELECT t.id, t.name, "
        "COALESCE(SUM(a.score) / NULLIF(SUM(a.max_points), 0), 0) AS accuracy, "
        "COUNT(a.id) AS attempts "
        "FROM topics t JOIN questions q ON q.topic_id = t.id "
        "JOIN attempts a ON a.question_id = q.id "
        "GROUP BY t.id HAVING attempts >= 3 ORDER BY accuracy ASC LIMIT 5"
    )
    goals = list_goals()
    return {
        "minutes_available": minutes,
        "due_total": len(due),
        "schedule": schedule,
        "weak_topics": [dict(r) for r in weak_topics],
        "goals": goals,
        "streak": study_streak(),
        "today_minutes": today_study_minutes(),
    }


def study_streak() -> int:
    rows = db.query(
        "SELECT DISTINCT substr(created_at, 1, 10) AS day FROM attempts ORDER BY day DESC LIMIT 400"
    )
    days = [r["day"] for r in rows]
    if not days:
        return 0
    streak = 0
    current = dt.date.today()
    day_set = set(days)
    while current.isoformat() in day_set:
        streak += 1
        current -= dt.timedelta(days=1)
    if streak == 0 and (dt.date.today() - dt.timedelta(days=1)).isoformat() in day_set:
        current = dt.date.today() - dt.timedelta(days=1)
        while current.isoformat() in day_set:
            streak += 1
            current -= dt.timedelta(days=1)
    return streak


def today_study_minutes() -> float:
    today = dt.date.today().isoformat()
    row = db.query_one(
        "SELECT COALESCE(SUM(actual_seconds), 0) AS s FROM study_sessions "
        "WHERE substr(started_at, 1, 10) = ?",
        (today,),
    )
    seconds = float(row["s"]) if row else 0.0
    attempts = db.query_one(
        "SELECT COUNT(*) AS n FROM attempts WHERE substr(created_at, 1, 10) = ?", (today,)
    )
    # Nicht erfasste Zeit konservativ aus der Anzahl beantworteter Fragen schaetzen.
    estimated = (int(attempts["n"]) if attempts else 0) * 45
    return round(max(seconds, estimated) / 60, 1)


def study_time_series(days: int = 14) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    today = dt.date.today()
    for offset in range(days - 1, -1, -1):
        day = (today - dt.timedelta(days=offset)).isoformat()
        row = db.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(score), 0) AS got, "
            "COALESCE(SUM(max_points), 0) AS total FROM attempts WHERE substr(created_at,1,10) = ?",
            (day,),
        )
        n = int(row["n"]) if row else 0
        total = float(row["total"] or 0) if row else 0.0
        got = float(row["got"] or 0) if row else 0.0
        out.append({
            "day": day,
            "questions": n,
            "accuracy": round(got / total, 3) if total else 0.0,
            "minutes": round(n * 45 / 60, 1),
        })
    return out


# ---------------------------------------------------------------------------
# Lernziele
# ---------------------------------------------------------------------------
def list_goals() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT g.*, t.name AS topic_name FROM learning_goals g "
        "LEFT JOIN topics t ON t.id = g.topic_id ORDER BY g.created_at DESC"
    )
    return [dict(r) for r in rows]


def create_goal(title: str, topic_id: str | None = None, target: str = "",
                due_date: str | None = None) -> dict[str, Any]:
    goal_id = db.new_id()
    db.insert(
        "INSERT INTO learning_goals(id, title, topic_id, target, due_date, progress, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (goal_id, title[:300], topic_id, target[:500], due_date, 0.0, "open", db.now(), db.now()),
    )
    return {"id": goal_id, "title": title, "topic_id": topic_id, "target": target,
            "due_date": due_date, "progress": 0.0, "status": "open"}


def update_goal(goal_id: str, **fields: Any) -> bool:
    allowed = {"title", "topic_id", "target", "due_date", "progress", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    updates["updated_at"] = db.now()
    columns = ", ".join(f"{k} = ?" for k in updates)
    db.execute(
        f"UPDATE learning_goals SET {columns} WHERE id = ?",  # noqa: S608
        list(updates.values()) + [goal_id],
    )
    return True


def delete_goal(goal_id: str) -> bool:
    row = db.query_one("SELECT id FROM learning_goals WHERE id = ?", (goal_id,))
    if not row:
        return False
    db.execute("DELETE FROM learning_goals WHERE id = ?", (goal_id,))
    return True


# ---------------------------------------------------------------------------
# Kennzahlen
# ---------------------------------------------------------------------------
def dashboard_stats() -> dict[str, Any]:
    doc = db.query_one("SELECT COUNT(*) AS n FROM documents")
    pages = db.query_one("SELECT COUNT(*) AS n FROM pages")
    chunks = db.query_one("SELECT COUNT(*) AS n FROM chunks")
    questions = db.query_one("SELECT COUNT(*) AS n FROM questions")
    attempts = db.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(score),0) AS got, COALESCE(SUM(max_points),0) AS total "
        "FROM attempts"
    )
    review = db.query_one("SELECT COUNT(*) AS n FROM questions WHERE needs_review = 1")
    review_pages = db.query_one("SELECT COUNT(*) AS n FROM pages WHERE needs_review = 1")
    exams = db.query_one("SELECT COUNT(*) AS n FROM exams WHERE status = 'finished'")
    best_exam = db.query_one(
        "SELECT MAX(score) AS best FROM exams WHERE status = 'finished'"
    )
    total = float(attempts["total"] or 0) if attempts else 0.0
    got = float(attempts["got"] or 0) if attempts else 0.0
    return {
        "documents": doc["n"] if doc else 0,
        "pages": pages["n"] if pages else 0,
        "chunks": chunks["n"] if chunks else 0,
        "questions": questions["n"] if questions else 0,
        "attempts": attempts["n"] if attempts else 0,
        "accuracy": round(got / total, 3) if total else 0.0,
        "needs_review_questions": review["n"] if review else 0,
        "needs_review_pages": review_pages["n"] if review_pages else 0,
        "exams_finished": exams["n"] if exams else 0,
        "best_exam_score": best_exam["best"] if best_exam else None,
        "due_reviews": due_count(),
        "streak_days": study_streak(),
        "today_minutes": today_study_minutes(),
        "daily_goal_minutes": settings.get_int("daily_study_minutes", 45),
        "topics": db.query_one("SELECT COUNT(*) AS n FROM topics")["n"],
    }


def weak_areas(limit: int = 8) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT t.id, t.name, "
        "COALESCE(SUM(a.score) / NULLIF(SUM(a.max_points), 0), 0) AS accuracy, "
        "COUNT(a.id) AS attempts "
        "FROM topics t JOIN questions q ON q.topic_id = t.id "
        "JOIN attempts a ON a.question_id = q.id "
        "GROUP BY t.id HAVING attempts >= 2 ORDER BY accuracy ASC, attempts DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def log_activity(kind: str, detail: str = "") -> None:
    db.insert(
        "INSERT INTO activity_log(id, kind, detail, created_at) VALUES(?,?,?,?)",
        (db.new_id(), kind, detail[:500], db.now()),
    )


def recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT kind, detail, created_at FROM activity_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]
