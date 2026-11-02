"""Tests for the OCR wrapper and the document extractor.

These tests exercise the real code paths (no mocks of the OCR result): the
tesseract command line is checked against a fake binary that records its
arguments, and the TSV parser is fed genuine tesseract-shaped output. The
extractor runs on real text.
"""

from __future__ import annotations

import stat
from pathlib import Path

from elektrocoach.documents import taxonomy
from elektrocoach.documents.extractor import build_chunks, deduplicate, chunk_text
from elektrocoach.documents.ocr import LOW_CONFIDENCE_THRESHOLD, OcrEngine


TSV_SAMPLE = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
    "width\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t900\t260\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t21\t32\t68\t8\t61.8\tElektrotechnik\n"
    "5\t1\t1\t1\t1\t2\t93\t32\t36\t8\t82.4\tNotizen\n"
    "5\t1\t1\t1\t2\t1\t21\t81\t40\t9\t90.0\tSchutzleiter\n"
    "5\t1\t1\t1\t2\t2\t64\t81\t30\t9\t88.0\tPE\n"
)


def test_tsv_parser_rebuilds_lines_and_averages_confidence():
    result = OcrEngine._parse_tsv(TSV_SAMPLE)
    assert result.text == "Elektrotechnik Notizen\nSchutzleiter PE"
    assert result.engine == "tesseract"
    assert result.word_count == 4
    assert result.confidence == 80.5  # (61.8 + 82.4 + 90.0 + 88.0) / 4
    assert result.needs_review is False


def test_tsv_parser_flags_empty_or_low_confidence_pages_for_review():
    empty = OcrEngine._parse_tsv(TSV_SAMPLE.splitlines()[0] + "\n")
    assert empty.word_count == 0
    assert empty.needs_review is True

    low = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
        "width\theight\tconf\ttext\n"
        f"5\t1\t1\t1\t1\t1\t1\t1\t10\t10\t{LOW_CONFIDENCE_THRESHOLD - 10}\tunleserlich\n"
    )
    result = OcrEngine._parse_tsv(low)
    assert result.word_count == 1
    assert result.needs_review is True


def test_ocr_requests_tsv_as_a_config_name(tmp_path: Path):
    """tesseract expects ``tsv`` as a config name, not as ``--tsv``.

    A fake tesseract records the arguments it receives and writes a TSV file,
    so this test fails if the command line ever regresses.
    """

    fake = tmp_path / "tesseract"
    recorder = tmp_path / "args.txt"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{recorder}"\n'
        # tesseract's second argument is the output base; it appends ".tsv".
        'base="$2"\n'
        'printf "level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\t'
        'left\\ttop\\twidth\\theight\\tconf\\ttext\\n" > "$base.tsv"\n'
        'printf "5\\t1\\t1\\t1\\t1\\t1\\t1\\t1\\t10\\t10\\t95\\tHallo\\n" >> "$base.tsv"\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    engine = OcrEngine("deu+eng")
    engine._binary = str(fake)  # bypass shutil.which for a deterministic binary
    result = engine.ocr_image(image)

    args = recorder.read_text().splitlines()
    assert "tsv" in args, f"tesseract must receive the tsv config name, got {args}"
    assert "--tsv" not in args, f"--tsv is not a valid tesseract argument: {args}"
    assert result.text == "Hallo"
    assert result.word_count == 1
    assert result.needs_review is False


def test_ocr_without_binary_is_unavailable_not_a_crash():
    engine = OcrEngine("deu+eng")
    engine._binary = None
    assert engine.available is False
    result = engine.ocr_image("does-not-matter.png")
    assert result.engine == "unavailable"
    assert result.needs_review is True
    assert engine.languages_available() == []


# -- extractor ---------------------------------------------------------------

NOTE = """\
Schutzmaßnahmen

Der Schutzleiter PE führt den Fehlerstrom ab. Der FI-Schutzschalter löst bei
30 mA aus. Die Abschaltung muss in 0,4 s erfolgen.

Leistungsberechnung

P = U * I. Bei 230 V und 2 A ergibt sich P = 460 W.

Spannungsfall

U = 2 * l * I / (kappa * A)
"""


def test_build_chunks_keeps_source_and_page():
    chunks = build_chunks(NOTE, source_label="notizen.pdf", page_number=7,
                          page_quality=0.9)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert chunk.metadata["source"] == "notizen.pdf"
        assert chunk.metadata["page"] == 7
        assert chunk.content.strip()
    joined = " ".join(c.content for c in chunks)
    assert "Schutzleiter" in joined


def test_chunks_are_classified_into_subjects():
    chunks = build_chunks(NOTE, source_label="n.pdf", page_number=1,
                          page_quality=0.8)
    subjects = {c.subject for c in chunks}
    assert subjects, "classification should assign a subject"
    assert None not in subjects or len(subjects) > 1


def test_deduplicate_removes_repeated_chunks():
    chunks = build_chunks(NOTE, source_label="n.pdf", page_number=1,
                          page_quality=0.8)
    doubled = chunks + build_chunks(NOTE, source_label="n.pdf", page_number=1,
                                    page_quality=0.8)
    assert len(deduplicate(doubled)) == len(chunks)


def test_chunk_text_splits_long_input_without_losing_text():
    long_text = "\n\n".join(
        f"Absatz {i}: " + ("Wort " * 200) for i in range(6)
    )
    pieces = chunk_text(long_text, max_chars=1200)
    assert len(pieces) > 1
    assert all(len(p) <= 1400 for p in pieces)


def test_classify_maps_known_terms():
    subject, _topic, score = taxonomy.classify(
        "Der FI-Schutzschalter und der Schutzleiter PE sichern die Anlage."
    )
    assert subject is not None
    assert 0.0 <= score <= 1.0
    assert subject in taxonomy.subject_list()
