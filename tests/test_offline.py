"""Tests des deterministischen Ersatzverfahrens (ohne KI)."""

from __future__ import annotations

from app.services import offline


def test_tokenize_liefert_rohe_tokens_und_keywords_filtert_stopwoerter():
    tokens = offline.tokenize("Der Leitungsschutzschalter und die Leitung sind wichtig")
    assert "leitungsschutzschalter" in tokens
    keywords = offline.keywords("Der Leitungsschutzschalter und die Leitung sind wichtig")
    assert "leitungsschutzschalter" in keywords
    assert "und" not in keywords
    assert "der" not in keywords


def test_keywords_liefert_haeufigste_fachbegriffe():
    text = "Spannungsfall Spannungsfall Spannungsfall Querschnitt Querschnitt Kabel"
    result = offline.keywords(text, limit=2)
    assert result[0] == "spannungsfall"
    assert result[1] == "querschnitt"


def test_detect_topics_erkennt_fachthemen():
    text = (
        "Der RCD mit 30 mA Fehlerstrom schuetzt Personen. "
        "Der Leitungsschutzschalter B16 schuetzt die Leitung. "
        "Der Spannungsfall und der Querschnitt muessen berechnet werden."
    )
    topics = offline.detect_topics(text)
    slugs = {t["slug"] for t in topics}
    assert "rcd" in slugs
    assert "leitungsschutzschalter" in slugs
    assert "leitungsberechnung" in slugs


def test_detect_topics_bei_leerem_text():
    assert offline.detect_topics("") == []


def test_extract_formulas_findet_formeln():
    text = "U = 230 V und I = 16 A, daraus folgt P = U * I"
    formulas = offline.extract_formulas(text)
    assert any("U = 230 V" in f for f in formulas)
    assert any("P = U * I" in f for f in formulas)


def test_chunk_text_haelt_groesse_ein():
    text = "\n\n".join(["Absatz " + str(i) + " " + ("x" * 200) for i in range(30)])
    chunks = offline.chunk_text(text, max_chars=600, overlap=50)
    assert len(chunks) > 1
    assert all(len(str(c["text"])) <= 700 for c in chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_chunk_text_leerer_text():
    assert offline.chunk_text("") == []
    assert offline.chunk_text("   \n  ") == []


def test_chunk_text_sehr_langer_absatz_ohne_absatzgrenzen():
    text = "a" * 5000
    chunks = offline.chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) >= 5
    assert sum(len(str(c["text"])) for c in chunks) >= 5000


def test_grade_multiple_choice_erkennt_richtige_antwort():
    assert offline.grade_multiple_choice("B", "B")["correct"] is True
    assert offline.grade_multiple_choice("b", "B")["correct"] is True
    assert offline.grade_multiple_choice("A", "B")["correct"] is False
    assert offline.grade_multiple_choice("A", "B", points=3)["score"] == 0.0


def test_grade_numeric_mit_komma_und_toleranz():
    assert offline.grade_numeric("16,5 A", "16.5 A")["correct"] is True
    assert offline.grade_numeric("16 A", "16.5 A", tolerance=0.05)["correct"] is True
    assert offline.grade_numeric("10 A", "16.5 A", tolerance=0.02)["correct"] is False


def test_grade_numeric_ohne_zahl_ist_unsicher():
    result = offline.grade_numeric("weiss nicht", "16.5")
    assert result["needs_review"] is True
    assert result["score"] == 0.0


def test_grade_numeric_null_referenz():
    assert offline.grade_numeric("0", "0")["correct"] is True
    assert offline.grade_numeric("1", "0")["correct"] is False


def test_grade_open_answer_teilpunkte_und_luecken():
    reference = "Der RCD schuetzt Personen bei Fehlerstrom mit 30 mA"
    result = offline.grade_open_answer("Der RCD schuetzt Personen", reference)
    assert 0 < result["score"] < 1
    assert "rcd" in result["matched"]
    assert "fehlerstrom" in result["missing"]


def test_grade_open_answer_vollstaendig():
    reference = "Schutzleiter Erdung Potentialausgleich"
    result = offline.grade_open_answer(reference, reference)
    assert result["score"] == 1.0
    assert result["needs_review"] is False


def test_grade_open_answer_leere_referenz_ist_unsicher():
    result = offline.grade_open_answer("irgendwas", "")
    assert result["needs_review"] is True
    assert result["score"] == 0.0


def test_cloze_questions_erzeugt_unsichere_fragen():
    text = "Der Leitungsschutzschalter schuetzt die Leitung vor Ueberlast und Kurzschluss."
    questions = offline.cloze_questions(text, max_items=3)
    assert questions
    assert all(q["needs_review"] is True for q in questions)
    assert all("_____" in str(q["prompt"]) for q in questions)


def test_estimate_difficulty_steigt_mit_komplexitaet():
    einfach = "Kurz."
    schwer = (
        "Der Spannungsfall wird mit U = (2 * l * I) / (kappa * A) berechnet und muss "
        "den Querschnitt, die Verlegeart sowie die Strombelastbarkeit beruecksichtigen. "
        "Zusaetzlich sind die Normen nach DIN VDE 0100 und DIN 18015 zu beachten."
    )
    assert offline.estimate_difficulty(schwer) > offline.estimate_difficulty(einfach)


def test_cosine_similarity_identisch_und_verschieden():
    a = offline.term_frequencies("Spannungsfall Querschnitt Leitung")
    assert offline.cosine_similarity(a, a) == 1.0
    b = offline.term_frequencies("Voellig andere Woerter hier drin")
    assert offline.cosine_similarity(a, b) < 0.5
    assert offline.cosine_similarity({}, a) == 0.0


def test_split_sentences_ignoriert_kurze_fragmente():
    sentences = offline.split_sentences("Ja. Der Leitungsschutzschalter schuetzt die Leitung.")
    assert len(sentences) == 1
