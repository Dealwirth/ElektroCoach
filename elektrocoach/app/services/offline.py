"""Deterministische Ersatzverfahren ohne KI.

Diese Funktionen halten Bewertung, Fragengenerierung und Themenerkennung
funktionsfaehig, wenn weder Ollama noch Gemini erreichbar sind. Sie sind
bewusst konservativ: unsichere Ergebnisse werden als "needs_review"
gekennzeichnet statt als gesichert ausgegeben.
"""

from __future__ import annotations

import math
import re
import unicodedata

STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines",
    "und", "oder", "aber", "sowie", "mit", "ohne", "für", "fuer", "von", "vom",
    "zu", "zum", "zur", "im", "in", "am", "an", "auf", "aus", "bei", "ist",
    "sind", "wird", "werden", "kann", "können", "muss", "müssen", "soll",
    "sollen", "hat", "haben", "dass", "wenn", "dann", "als", "auch", "nicht",
    "nur", "noch", "über", "ueber", "unter", "nach", "vor", "durch", "sich",
    "dieser", "diese", "dieses", "man", "wird", "hier", "dort", "zwei", "drei",
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
}

# Fachliche Schluesselbegriffe der Elektrotechnik (Energie- und Gebaeudetechnik).
DOMAIN_TERMS = {
    "schutzkleinspannung": ["selv", "pelv", "schutzkleinspannung", "schutzmaßnahme"],
    "netzsysteme": ["tn-system", "tt-system", "it-system", "netzform", "sternpunkt"],
    "schutzleiter": ["schutzleiter", "pe-leiter", "potentialausgleich", "erdung"],
    "rcd": ["fi-schutzschalter", "rcd", "fehlerstrom", "bemessungsdifferenzstrom", "30 ma"],
    "leitungsschutzschalter": ["leitungsschutzschalter", "ls-schalter", "mcb", "b16", "c16"],
    "leitungsberechnung": ["spannungsfall", "querschnitt", "strombelastbarkeit", "verlegeart"],
    "drehstrom": ["drehstrom", "drehstrommotor", "sternschaltung", "dreieckschaltung", "außenleiter"],
    "wechselstrom": ["wechselstrom", "scheinleistung", "wirkleistung", "blindleistung", "cos φ"],
    "gleichstrom": ["gleichstrom", "ohmsches gesetz", "widerstand", "spannungsteiler"],
    "schuetzschaltung": ["schütz", "schuetz", "selbsthaltung", "wendeschütz", "hauptstromkreis"],
    "steuerungstechnik": ["steuerung", "sps", "speicherprogrammierbar", "ablaufsteuerung", "kontaktplan"],
    "beleuchtung": ["beleuchtung", "leuchtstofflampe", "led", "lichtstrom", "beleuchtungsstärke"],
    "installation": ["installation", "unterverteilung", "stromkreisverteiler", "zählerplatz"],
    "hausanschluss": ["hausanschluss", "hauptverteilung", "hak", "zähler", "trennvorrichtung"],
    "blitzschutz": ["blitzschutz", "überspannungsschutz", "blitzstrom", "ableiter"],
    "photovoltaik": ["photovoltaik", "pv-anlage", "wechselrichter", "solarzelle", "einspeisung"],
    "elektromobilitaet": ["wallbox", "ladeeinrichtung", "elektrofahrzeug", "ladeinfrastruktur"],
    "waermepumpe": ["wärmepumpe", "heizlast", "vorlauftemperatur", "jahresarbeitszahl"],
    "gebaeudeautomation": ["knx", "gebäudeautomation", "bussystem", "eib", "dali"],
    "sicherheit": ["arbeitssicherheit", "fünf sicherheitsregeln", "unfallverhütung", "dgUV"],
    "messtechnik": ["multimeter", "messgerät", "strommesszange", "isolationsmessung"],
    "normen": ["din vde", "vde 0100", "din 18015", "norm", "richtlinie"],
    "werkstoffe": ["kupfer", "aluminium", "leiterwerkstoff", "isolierstoff"],
    "motoren": ["asynchronmotor", "käfigläufer", "drehzahl", "schlupf", "frequenzumrichter"],
    "transformatoren": ["transformator", "trafo", "übersetzung", "wicklung"],
    "sicherungen": ["sicherung", "schmelzsicherung", "nh-sicherung", "charakteristik"],
    "kompensation": ["blindleistungskompensation", "kompensationsanlage", "kondensator"],
    "energiemanagement": ["energiemanagement", "lastmanagement", "energieeffizienz", "smart meter"],
}

FORMULA_PATTERN = re.compile(
    r"[A-Za-zÄÖÜäöü]{1,3}\s*=\s*[^,.;\n]{2,60}"
)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-ZäöüÄÖÜß][a-zA-ZäöüÄÖÜß0-9\-]{2,}", _normalise(text))]


def keywords(text: str, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for token in tokenize(text):
        if token in STOPWORDS or len(token) < 4:
            continue
        counts[token] = counts.get(token, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def detect_topics(text: str) -> list[dict[str, object]]:
    """Erkennt Fachthemen anhand von Schluesselbegriffen (ohne KI)."""
    haystack = _normalise(text)
    found: list[dict[str, object]] = []
    for slug, terms in DOMAIN_TERMS.items():
        hits = sum(haystack.count(_normalise(t)) for t in terms)
        if hits:
            found.append({"slug": slug, "name": slug.replace("-", " ").title(), "hits": hits})
    found.sort(key=lambda item: -int(item["hits"]))  # type: ignore[arg-type]
    return found[:8]


def extract_formulas(text: str) -> list[str]:
    return [m.strip() for m in FORMULA_PATTERN.findall(text or "")][:20]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?:;])\s+|\n{2,}", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 25]


def cloze_questions(text: str, max_items: int = 5) -> list[dict[str, object]]:
    """Erzeugt Lueckentext-Fragen aus Fachbegriffen. Immer als unsicher markiert."""
    key_terms = [k for k in keywords(text, limit=25) if len(k) > 5]
    sentences = split_sentences(text)
    out: list[dict[str, object]] = []
    used: set[str] = set()
    for sentence in sentences:
        if len(out) >= max_items:
            break
        for term in key_terms:
            if term in used:
                continue
            if re.search(rf"\b{re.escape(term)}\b", _normalise(sentence)):
                blanked = re.sub(rf"(?i)\b{re.escape(term)}\b", "_____", sentence)
                out.append({
                    "prompt": f"Ergänzen Sie die Lücke: {blanked}",
                    "answer": term,
                    "qtype": "cloze",
                    "difficulty": 2,
                    "needs_review": True,
                    "ai_source": "offline",
                })
                used.add(term)
                break
    return out


def _tokens_set(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOPWORDS}


def grade_open_answer(user_answer: str, reference: str) -> dict[str, object]:
    """Bewertet eine offene Antwort ueber Schluesselwortabgleich."""
    user_tokens = _tokens_set(user_answer)
    ref_tokens = _tokens_set(reference)
    if not ref_tokens:
        return {"score": 0.0, "matched": [], "missing": [], "needs_review": True}
    matched = sorted(user_tokens & ref_tokens)
    missing = sorted(ref_tokens - user_tokens)
    ratio = len(matched) / len(ref_tokens)
    score = round(min(1.0, ratio * 1.15), 3)
    return {
        "score": score,
        "matched": matched[:25],
        "missing": missing[:25],
        "needs_review": score < 0.6,
    }


def grade_numeric(user_answer: str, reference: str, tolerance: float = 0.02) -> dict[str, object]:
    """Vergleicht einen Zahlenwert mit Toleranz und Einheiten-Toleranz."""

    def parse_number(value: str) -> float | None:
        if value is None:
            return None
        cleaned = _normalise(str(value)).replace(" ", "")
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", cleaned)
        return float(match.group()) if match else None

    target = parse_number(reference)
    given = parse_number(user_answer)
    if target is None or given is None:
        return {"score": 0.0, "correct": False, "needs_review": True}
    if target == 0:
        ok = abs(given) < 1e-9
    else:
        ok = abs(given - target) / abs(target) <= tolerance
    return {
        "score": 1.0 if ok else 0.0,
        "correct": ok,
        "target": target,
        "given": given,
        "tolerance": tolerance,
        "needs_review": False,
    }


def grade_multiple_choice(user_answer: str, correct: str, points: float = 1.0) -> dict[str, object]:
    normalise = lambda s: re.sub(r"[^a-z0-9]", "", _normalise(str(s)))  # noqa: E731
    ok = normalise(user_answer) == normalise(correct)
    return {"score": points if ok else 0.0, "correct": ok, "needs_review": False}


def estimate_difficulty(text: str) -> int:
    """Grobe Schwierigkeit aus Satzlaenge, Formeln und Fachbegriffen."""
    words = tokenize(text)
    if not words:
        return 1
    avg_len = sum(len(w) for w in words) / len(words)
    formulas = len(extract_formulas(text))
    topics = len(detect_topics(text))
    score = 1 + int(avg_len > 7) + int(formulas > 0) + int(topics > 2) + int(len(words) > 120)
    return max(1, min(5, score))


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[dict[str, object]]:
    """Zerlegt Text in ueberlappende Abschnitte, moeglichst an Absatzgrenzen."""
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[dict[str, object]] = []
    buffer = ""
    heading: str | None = None
    for para in paragraphs:
        candidate_heading = para.split("\n", 1)[0].strip("# ").strip()
        words = candidate_heading.split()
        # Als Ueberschrift gilt nur eine kurze Zeile ohne Satzendezeichen.
        if (
            len(candidate_heading) <= 70
            and len(words) <= 8
            and not candidate_heading.endswith((".", "!", "?", ",", ";"))
        ):
            heading = candidate_heading
        if len(buffer) + len(para) + 2 <= max_chars:
            buffer = f"{buffer}\n\n{para}".strip()
            continue
        if buffer:
            chunks.append({"text": buffer, "heading": heading})
        if len(para) <= max_chars:
            buffer = para
        else:
            for i in range(0, len(para), max_chars - overlap):
                piece = para[i : i + max_chars]
                chunks.append({"text": piece, "heading": heading})
            buffer = ""
    if buffer:
        chunks.append({"text": buffer, "heading": heading})

    out: list[dict[str, object]] = []
    for idx, chunk in enumerate(chunks):
        out.append({
            "text": chunk["text"],
            "heading": chunk.get("heading"),
            "ordinal": idx,
            "tokens": max(1, len(tokenize(str(chunk["text"])))),
        })
    return out


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[k] * b[k] for k in common)
    denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    if not denom:
        return 0.0
    return max(0.0, min(1.0, num / denom))


def term_frequencies(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in tokenize(text):
        if token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0.0) + 1.0
    return counts
