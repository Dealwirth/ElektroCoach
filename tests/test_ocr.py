"""Tests fuer OCR, PDF-Verarbeitung und Samsung-Notes-Import.

Die Tests erzeugen echte Bilder und PDFs und pruefen die erkannten Inhalte.
OCR-Tests laufen nur, wenn Tesseract installiert ist.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services import ocr, samsung_notes
from app.services.library import store_document

tesseract_required = pytest.mark.skipif(
    not ocr.tesseract_available(), reason="Tesseract ist nicht installiert"
)


def _render_text_image(text: str, width: int = 900, height: int = 260) -> bytes:
    """Erzeugt ein gut lesbares Bild mit Text fuer OCR-Tests."""
    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 20), text, fill=0, font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_pdf_with_text(path: Path, text: str) -> None:
    """Erzeugt ein minimales PDF mit eingebettetem Text (ohne Zusatzbibliothek)."""
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = f"BT /F1 18 Tf 50 700 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))


def test_tesseract_installation_wird_erkannt():
    assert isinstance(ocr.tesseract_available(), bool)


@tesseract_required
def test_ocr_liest_deutschen_text():
    data = _render_text_image("Leitungsschutzschalter 16 A")
    result = ocr.ocr_image_bytes(data, languages="deu")
    assert result["ok"] is True
    assert "Leitungsschutzschalter" in result["text"].replace("\n", " ")
    assert result["confidence"] is not None


@tesseract_required
def test_ocr_liefert_konfidenz():
    data = _render_text_image("RCD 30 mA Fehlerstrom")
    result = ocr.ocr_image_bytes(data, languages="deu")
    assert result["confidence"] is not None
    assert 0 <= result["confidence"] <= 100


@tesseract_required
def test_ocr_auf_leerem_bild_erkennt_keinen_text():
    image = Image.new("L", (600, 200), color=255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = ocr.ocr_image_bytes(buffer.getvalue())
    assert result["ok"] is True
    assert result["text"].strip() == ""


def test_ocr_mit_kaputten_daten_liefert_fehler():
    result = ocr.ocr_image_bytes(b"das ist kein bild")
    assert result["ok"] is False
    assert result["error"]


@tesseract_required
def test_bilddatei_verarbeiten_und_indizieren(tmp_path):
    data = _render_text_image("Spannungsfall berechnen")
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(data)

    document = store_document(image_path, "scan.png", collection="Lehrjahr 2")
    assert document["status"] in {"ready", "needs_review"}
    assert document["pages"] == 1

    from app.services import library

    pages = library.get_pages(document["id"])
    assert pages[0]["text"].strip()
    assert pages[0]["image_path"] is not None
    assert Path(pages[0]["image_path"]).exists()
    library.delete_document(document["id"])


def test_pdf_mit_eingebettetem_text_wird_ohne_ocr_gelesen(tmp_path):
    pdf_path = tmp_path / "notiz.pdf"
    _write_pdf_with_text(pdf_path, "Der Schutzleiter muss niederohmig sein.")

    result = ocr.process_pdf(pdf_path, render_for_ocr=False)
    assert result.kind == "pdf"
    assert len(result.pages) == 1
    assert "Schutzleiter" in result.pages[0].text


def test_pdf_als_dokument_speichern(tmp_path):
    pdf_path = tmp_path / "notiz2.pdf"
    _write_pdf_with_text(pdf_path, "Drehstrommotor Sternschaltung Dreieckschaltung")
    document = store_document(pdf_path, "notiz2.pdf")
    assert document["pages"] == 1

    from app.services import library

    assert library.search("Drehstrommotor")["count"] >= 1
    library.delete_document(document["id"])


def test_text_und_html_verarbeitung(tmp_path):
    text_path = tmp_path / "notizen.txt"
    text_path.write_text("Der Leitungsschutzschalter schuetzt die Leitung.", encoding="utf-8")
    text_result = ocr.process_text(text_path)
    assert "Leitungsschutzschalter" in text_result.pages[0].text

    html_path = tmp_path / "seite.html"
    html_path.write_text(
        "<html><head><style>b{}</style></head><body><h1>Schaltplan</h1>"
        "<p>Schuetz mit Selbsthaltung</p><script>var x=1;</script></body></html>",
        encoding="utf-8",
    )
    html_result = ocr.process_html(html_path)
    body = html_result.pages[0].text
    assert "Schaltplan" in body
    assert "Selbsthaltung" in body
    assert "var x" not in body


def test_unbekanntes_format_wird_als_pruefbeduerftig_markiert(tmp_path):
    path = tmp_path / "daten.bin"
    path.write_bytes(bytes(range(256)))
    result = ocr.process_container_choice(path)
    assert result.needs_review is True
    assert "error" in result.meta


# ---------------------------------------------------------------------------
# Samsung Notes
# ---------------------------------------------------------------------------
def test_samsung_container_mit_text_und_bild(tmp_path):
    archive_path = tmp_path / "notiz.sdoc"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("note.json", '{"title": "Lehrjahr 1", "text": "Ohmsches Gesetz"}')
        archive.writestr("page1.png", _render_text_image("U = R * I"))

    result = samsung_notes.process_container(archive_path)
    assert result.kind == "samsung_notes"
    assert result.pages
    combined = result.text
    assert "Ohmsches Gesetz" in combined or "Lehrjahr 1" in combined


def test_samsung_container_ohne_verwertbaren_inhalt(tmp_path):
    archive_path = tmp_path / "leer.snote"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("info.txt", " ")
    result = samsung_notes.process_container(archive_path)
    assert result.needs_review is True
    assert "error" in result.meta


def test_samsung_kein_zip(tmp_path):
    path = tmp_path / "kaputt.sdoc"
    path.write_bytes(b"das ist kein zip")
    result = samsung_notes.process_container(path)
    assert result.needs_review is True
    assert "error" in result.meta


def test_importformate_werden_beschrieben():
    info = samsung_notes.describe_import_formats()
    assert info["samsung_direct"]["supported"] is True
    assert ".sdoc" in info["samsung_direct"]["suffixes"]
    assert "PDF" in info["recommended"]["format"]


def test_zip_sammlung_mit_mehreren_bildern(tmp_path):
    archive_path = tmp_path / "sammlung.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(3):
            archive.writestr(f"seite{index}.png", _render_text_image(f"Seite Nummer {index + 1}"))
    document = store_document(archive_path, "sammlung.zip", collection="Sammlung")
    assert document["pages"] >= 1

    from app.services import library

    library.delete_document(document["id"])
