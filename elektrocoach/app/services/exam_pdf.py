"""Pruefungsdokument als PDF.

Erzeugt aus einer Pruefungssimulation ein druckfertiges PDF im Aufbau einer
echten Abschlusspruefung:

* Deckblatt mit Bezeichnung, Dauer, Punkten und Hinweisen
* Aufgabenblaetter mit fortlaufender Nummer, Punkten und Schreibplatz
* optional ein Loesungsblatt mit Musterloesung und Rechenweg

Die Schrift ist DejaVu Sans (in Home Assistant OS vorhanden) und deckt
Sonderzeichen wie rho (ρ), Omega (Ω), ² und · ab.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from . import exam as exam_service

log = logging.getLogger(__name__)

FONT_NAME = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_MONO = "Courier"

_FONT_CANDIDATES = (
    ("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ("DejaVu", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"),
)

_TYPE_LABELS = {
    "multiple_choice": "Multiple Choice",
    "calculation": "Rechenaufgabe",
    "short_answer": "Kurzantwort",
    "open": "Offene Aufgabe",
    "practical": "Praktische Aufgabe",
}


_UNICODE_FONTS = False


def _register_fonts() -> tuple[str, str, str]:
    """Meldet eine Unicode-Schrift an, wenn sie vorhanden ist."""
    global _UNICODE_FONTS
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:  # pragma: no cover - reportlab fehlt
        return FONT_NAME, FONT_BOLD, FONT_MONO

    for name, regular, bold, mono in _FONT_CANDIDATES:
        if not (Path(regular).exists() and Path(bold).exists()):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, regular))
            pdfmetrics.registerFont(TTFont(f"{name}-Bold", bold))
            if Path(mono).exists():
                pdfmetrics.registerFont(TTFont(f"{name}-Mono", mono))
            _UNICODE_FONTS = True
            return name, f"{name}-Bold", f"{name}-Mono"
        except Exception as exc:  # noqa: BLE001
            log.warning("Schrift %s nicht nutzbar: %s", regular, exc)
    return FONT_NAME, FONT_BOLD, FONT_MONO


def _safe_text(value: Any) -> str:
    """Ersetzt Zeichen, die die Standardschrift nicht kennt."""
    text = str(value or "")
    if _UNICODE_FONTS:
        return text
    return (
        text.replace("\u03c1", "rho")
        .replace("\u03a9", "Ohm")
        .replace("\u00b2", "2")
        .replace("\u00b7", "*")
    )


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _group_questions(exam: dict[str, Any]) -> list[dict[str, Any]]:
    """Gruppiert die Aufgaben nach Thema (Handlungsbereich)."""
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for entry in exam.get("questions", []):
        topic = entry.get("topic_name") or "Allgemein"
        group = index.get(topic)
        if group is None:
            group = {"topic": topic, "questions": []}
            index[topic] = group
            groups.append(group)
        group["questions"].append(entry)
    return groups


def _load_solutions(exam: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Laedt Musterloesung und Loesungsweg je Aufgabe direkt aus der Datenbank.

    Diese Felder werden bewusst nicht in ``get_exam`` geladen, damit sie waehrend
    einer laufenden Pruefung nicht an die Oberflaeche gelangen.
    """
    from .. import db

    ids = [q.get("question_id") for q in exam.get("questions", []) if q.get("question_id")]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = db.query(
            f"SELECT id, answer, solution_steps FROM questions WHERE id IN ({placeholders})",  # noqa: S608
            ids,
        )
    except Exception:  # noqa: BLE001
        log.exception("Loesungen konnten nicht geladen werden")
        return {}
    return {row["id"]: dict(row) for row in rows}


def build_exam_pdf(exam_id: str, *, include_solutions: bool = False) -> bytes | None:
    """Baut das Pruefungs-PDF. Gibt ``None`` zurueck, wenn die Pruefung fehlt."""
    exam = exam_service.get_exam(exam_id)
    if not exam:
        return None

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    font, font_bold, font_mono = _register_fonts()
    buffer = io.BytesIO()
    width, height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(_safe_text(exam.get("name") or "Pruefung"))
    pdf.setAuthor("ElektroCoach")

    margin = 20 * mm
    questions = exam.get("questions", [])
    total_points = float(exam.get("total_points") or 0)
    duration = int(exam.get("duration_minutes") or 0)

    def footer(page_label: str) -> None:
        pdf.setFont(font, 8)
        pdf.setFillGray(0.45)
        pdf.drawString(margin, 12 * mm, "ElektroCoach · Pruefungssimulation")
        pdf.drawRightString(width - margin, 12 * mm, page_label)
        pdf.setFillGray(0)

    def heading(text: str, size: int = 14) -> float:
        pdf.setFont(font_bold, size)
        pdf.drawString(margin, height - margin - size, _safe_text(text))
        pdf.setLineWidth(0.8)
        pdf.line(margin, height - margin - size - 4, width - margin, height - margin - size - 4)
        return height - margin - size - 16

    # ------------------------------------------------------------------
    # Deckblatt
    # ------------------------------------------------------------------
    pdf.setFont(font_bold, 22)
    pdf.drawString(margin, height - margin - 10, _safe_text(exam.get("name") or "Pruefung"))
    pdf.setFont(font, 11)
    pdf.setFillGray(0.3)
    pdf.drawString(margin, height - margin - 30, "Abschlusspruefung · Elektroniker fuer Energie- und Gebaeudetechnik")
    pdf.setFillGray(0)

    box_top = height - margin - 70
    rows = [
        ("Dauer", f"{duration} Minuten"),
        ("Aufgaben", str(len(questions))),
        ("Gesamtpunkte", _format_number(total_points)),
        ("Bestehensgrenze", "50 %"),
    ]
    pdf.setFont(font, 11)
    y = box_top
    for label, value in rows:
        pdf.setFont(font_bold, 11)
        pdf.drawString(margin, y, label)
        pdf.setFont(font, 11)
        pdf.drawString(margin + 45 * mm, y, value)
        y -= 8 * mm
    pdf.setLineWidth(0.5)
    pdf.setStrokeGray(0.7)
    pdf.rect(margin, y + 2 * mm, width - 2 * margin, box_top - y - 2 * mm)
    pdf.setStrokeGray(0)

    y -= 14 * mm
    pdf.setFont(font_bold, 12)
    pdf.drawString(margin, y, "Bearbeitungshinweise")
    y -= 7 * mm
    pdf.setFont(font, 10)
    hints = [
        "Alle Aufgaben sind zu bearbeiten. Trage die Loesungen in die vorgesehenen Felder ein.",
        "Erlaubte Hilfsmittel: Taschenrechner, Formelsammlung, Tabellenbuch, Schreibzeug.",
        "Rechenwege muessen nachvollziehbar sein. Ergebnisse ohne Einheit werden nicht gewertet.",
        "Bei Mehrfachauswahl ist genau eine Antwort richtig, sofern nicht anders angegeben.",
    ]
    for hint in hints:
        pdf.drawString(margin, y, _safe_text(f"- {hint}"))
        y -= 6 * mm

    y -= 12 * mm
    pdf.setFont(font_bold, 12)
    pdf.drawString(margin, y, "Angaben zur Person")
    y -= 4 * mm
    for label in ("Name:", "Datum:", "Pruefling-Nr.:"):
        y -= 10 * mm
        pdf.setFont(font, 10)
        pdf.drawString(margin, y + 3, _safe_text(label))
        pdf.setLineWidth(0.5)
        pdf.setStrokeGray(0.6)
        pdf.line(margin + 30 * mm, y, width - margin, y)
        pdf.setStrokeGray(0)
    pdf.setFont(font, 9)
    pdf.setFillGray(0.45)
    pdf.drawString(margin, 18 * mm, f"Erstellt am {exam.get('created_at', '')} · Gesamtpunkte {_format_number(total_points)}")
    pdf.setFillGray(0)
    pdf.showPage()

    # ------------------------------------------------------------------
    # Aufgaben
    # ------------------------------------------------------------------
    for group_index, group in enumerate(_group_questions(exam), start=1):
        y = heading(f"Aufgabe {group_index}: {group['topic']}", 14)
        pdf.setFont(font, 10)
        group_points = sum(float(q.get("points") or 0) for q in group["questions"])
        pdf.setFillGray(0.35)
        pdf.drawString(margin, y, _safe_text(f"{len(group['questions'])} Teilaufgaben · {_format_number(group_points)} Punkte"))
        pdf.setFillGray(0)
        y -= 10 * mm

        for part_index, question in enumerate(group["questions"], start=1):
            if y < margin + 40 * mm:
                footer(f"Aufgabe {group_index} · Seite {pdf.getPageNumber()}")
                pdf.showPage()
                y = height - margin

            points = _format_number(question.get("points"))
            pdf.setFont(font_bold, 11)
            pdf.drawString(margin, y, _safe_text(f"{group_index}.{part_index}"))
            type_label = _TYPE_LABELS.get(str(question.get("qtype") or ""), "")
            if type_label:
                pdf.setFont(font, 8.5)
                pdf.setFillGray(0.5)
                pdf.drawString(margin + 12 * mm, y, _safe_text(f"({type_label})"))
                pdf.setFillGray(0)
            pdf.setFont(font, 9)
            pdf.setFillGray(0.4)
            pdf.drawRightString(width - margin, y, _safe_text(f"{points} Punkte"))
            pdf.setFillGray(0)
            y -= 6 * mm

            prompt = _safe_text(question.get("prompt") or "")
            pdf.setFont(font, 10.5)
            for line in _wrap(prompt, font, 10.5, width - 2 * margin - 6 * mm):
                if y < margin + 25 * mm:
                    footer(f"Aufgabe {group_index} · Seite {pdf.getPageNumber()}")
                    pdf.showPage()
                    y = height - margin
                pdf.drawString(margin + 6 * mm, y, line)
                y -= 5.5 * mm

            options = question.get("options") or []
            if options:
                y -= 1 * mm
                pdf.setFont(font, 10)
                for option in options:
                    for line in _wrap(_safe_text(option), font, 10, width - 2 * margin - 12 * mm):
                        if y < margin + 25 * mm:
                            footer(f"Aufgabe {group_index} · Seite {pdf.getPageNumber()}")
                            pdf.showPage()
                            y = height - margin
                        pdf.drawString(margin + 10 * mm, y, line)
                        y -= 5 * mm
                y -= 1 * mm
            else:
                # Schreibplatz fuer freie Antworten.
                space = 22 * mm if question.get("qtype") == "calculation" else 16 * mm
                if y - space < margin + 20 * mm:
                    footer(f"Aufgabe {group_index} · Seite {pdf.getPageNumber()}")
                    pdf.showPage()
                    y = height - margin
                pdf.setLineWidth(0.4)
                pdf.setStrokeGray(0.75)
                lines = 4 if question.get("qtype") == "calculation" else 3
                for line_index in range(lines):
                    line_y = y - line_index * 6 * mm
                    pdf.line(margin + 6 * mm, line_y, width - margin, line_y)
                pdf.setStrokeGray(0)
                y -= lines * 6 * mm + 6 * mm

            y -= 2 * mm
        y -= 6 * mm

    # ------------------------------------------------------------------
    # Loesungsblatt
    # ------------------------------------------------------------------
    if include_solutions:
        solutions = _load_solutions(exam)
        footer(f"Aufgaben · Seite {pdf.getPageNumber()}")
        pdf.showPage()
        y = heading("Loesungen", 16)
        for group_index, group in enumerate(_group_questions(exam), start=1):
            pdf.setFont(font_bold, 12)
            pdf.drawString(margin, y, _safe_text(f"Aufgabe {group_index}: {group['topic']}"))
            y -= 7 * mm
            for part_index, question in enumerate(group["questions"], start=1):
                if y < margin + 35 * mm:
                    footer(f"Loesungen · Seite {pdf.getPageNumber()}")
                    pdf.showPage()
                    y = height - margin
                solution = solutions.get(question.get("question_id"), {})
                pdf.setFont(font_bold, 10)
                pdf.drawString(margin, y, _safe_text(f"{group_index}.{part_index}"))
                y -= 5 * mm
                answer = _safe_text(solution.get("answer") or "–")
                pdf.setFont(font_mono if FONT_MONO == "Courier" else font, 10)
                for line in _wrap(answer, font_mono, 10, width - 2 * margin - 6 * mm):
                    if y < margin + 20 * mm:
                        footer(f"Loesungen · Seite {pdf.getPageNumber()}")
                        pdf.showPage()
                        y = height - margin
                    pdf.drawString(margin + 6 * mm, y, line)
                    y -= 5 * mm
                steps = _safe_text(solution.get("solution_steps") or "")
                if steps:
                    pdf.setFont(font, 9)
                    pdf.setFillGray(0.35)
                    for line in _wrap(f"Loesungsweg: {steps}", font, 9, width - 2 * margin - 6 * mm):
                        if y < margin + 20 * mm:
                            footer(f"Loesungen · Seite {pdf.getPageNumber()}")
                            pdf.showPage()
                            y = height - margin
                        pdf.drawString(margin + 6 * mm, y, line)
                        y -= 4.5 * mm
                    pdf.setFillGray(0)
                y -= 4 * mm
            y -= 4 * mm

    footer(f"Seite {pdf.getPageNumber()}")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    """Bricht Text auf die verfuegbare Breite um."""
    from reportlab.pdfbase import pdfmetrics

    lines: list[str] = []
    for raw_line in (text or "").split("\n"):
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            try:
                width = pdfmetrics.stringWidth(candidate, font, size)
            except Exception:  # noqa: BLE001
                width = len(candidate) * size * 0.5
            if width <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def exam_filename(exam: dict[str, Any], *, solutions: bool = False) -> str:
    """Sicherer, reiner ASCII-Dateiname fuer den Download.

    Umlaute werden umgeschrieben: der ``Content-Disposition``-Kopf soll ohne
    Kodierung auskommen, damit auch aeltere Browser den Namen richtig zeigen.
    """
    name = str(exam.get("name") or "Pruefung")
    translit = (
        name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
        .replace("ß", "ss")
    )
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in translit).strip().replace(" ", "_")
    suffix = "_Loesungen" if solutions else ""
    return f"{safe or 'Pruefung'}{suffix}.pdf"
