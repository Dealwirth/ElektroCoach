"""Regressionstests fuer Fehler, die im Belastungstest gefunden wurden.

Jeder Test beschreibt einen konkreten Fehlerfall, der vorher falsch behandelt
wurde. Die Tests laufen gegen die echte Verarbeitung (keine Mocks).
"""

from __future__ import annotations

import io
import threading
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import db
from app.services import library, ocr, samsung_notes
from app.services.library import store_document
from app.workers import import_worker


def _png_with_text(text: str) -> bytes:
    image = Image.new("L", (900, 200), color=255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 20), text, fill=0, font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Beschaedigte und leere Dateien
# ---------------------------------------------------------------------------
def test_empty_pdf_is_marked_as_error(tmp_path: Path) -> None:
    """Eine 0-Byte-PDF darf nicht als "fertig" mit 0 Seiten erscheinen."""
    path = tmp_path / "leer.pdf"
    path.write_bytes(b"")
    outcome = store_document(path, "leer.pdf")
    assert outcome["status"] == "error"
    assert outcome["error"]
    assert outcome["pages"] >= 1


def test_corrupt_pdf_is_marked_as_error(tmp_path: Path) -> None:
    """Eine abgeschnittene PDF muss als Fehler sichtbar werden."""
    path = tmp_path / "kaputt.pdf"
    path.write_bytes(b"%PDF-1.4\nDies ist kein gueltiges PDF\x00\xff")
    outcome = store_document(path, "kaputt.pdf")
    assert outcome["status"] == "error"
    assert "beschaedigt" in (outcome["error"] or "") or "leer" in (outcome["error"] or "")


def test_empty_text_file_is_marked_as_error(tmp_path: Path) -> None:
    path = tmp_path / "leer.txt"
    path.write_text("", encoding="utf-8")
    outcome = store_document(path, "leer.txt")
    assert outcome["status"] == "error"
    assert outcome["error"]


def test_error_document_stores_reason_in_database(tmp_path: Path) -> None:
    """Der Fehlergrund muss in der Datenbank stehen, nicht nur in der Antwort."""
    path = tmp_path / "kaputt2.pdf"
    path.write_bytes(b"%PDF-1.4\nnur Schrott")
    outcome = store_document(path, "kaputt2.pdf")
    row = library.get_document(outcome["id"])
    assert row is not None
    assert row["status"] == "error"
    assert row["error"]


# ---------------------------------------------------------------------------
# Duplikaterkennung
# ---------------------------------------------------------------------------
def test_empty_files_are_not_treated_as_duplicates(tmp_path: Path) -> None:
    """Zwei leere Dateien sind kein Duplikat, sondern zwei eigene Fehler."""
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    outcome_a = store_document(first, "a.txt")
    assert outcome_a["status"] == "error"
    duplicate = library.find_duplicate(_sha(second))
    assert duplicate is None
    outcome_b = store_document(second, "b.txt")
    assert outcome_b["status"] == "error"
    assert outcome_b["id"] != outcome_a["id"]


def _sha(path: Path) -> str:
    from app.security import sha256_file

    return sha256_file(path)


def test_real_duplicate_is_still_detected(tmp_path: Path) -> None:
    payload = b"Der RCD schuetzt Personen bei Fehlerstrom.\n" * 5
    first = tmp_path / "original.txt"
    second = tmp_path / "kopie.txt"
    first.write_bytes(payload)
    second.write_bytes(payload)
    outcome = store_document(first, "original.txt")
    assert outcome["status"] in {"ready", "needs_review"}
    duplicate = library.find_duplicate(_sha(second))
    assert duplicate is not None
    assert duplicate["id"] == outcome["id"]


# ---------------------------------------------------------------------------
# Scan-PDFs ohne Textebene
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not ocr.tesseract_available(), reason="Tesseract fehlt")
def test_scanned_pdf_without_text_layer_gets_ocr_pages(tmp_path: Path) -> None:
    """Ein PDF ohne Textebene (reiner Scan) muss OCR-Seiten bekommen.

    Vorher wurde ein solches Dokument mit 0 Seiten und Status "ready" abgelegt.
    """
    image = Image.open(io.BytesIO(_png_with_text("Leitungsschutzschalter 16 A")))
    path = tmp_path / "scan.pdf"
    image.convert("RGB").save(path, "PDF", resolution=150.0)

    outcome = store_document(path, "scan.pdf")
    assert outcome["pages"] >= 1
    assert outcome["status"] in {"ready", "needs_review"}
    document = library.get_document(outcome["id"])
    assert document is not None
    assert document["page_count"] >= 1
    pages = library.get_pages(outcome["id"])
    assert pages
    assert "Leitungsschutzschalter" in pages[0]["text"]


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------
def test_empty_zip_is_reported_not_swallowed(tmp_path: Path) -> None:
    """Ein leeres ZIP darf nicht spurlos verschwinden."""
    path = tmp_path / "leer.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    expanded = import_worker._unpack_archives([(str(path), "leer.zip")], "testjob")
    assert expanded
    assert expanded[0][1] == "leer.zip"


def test_nested_zip_is_unpacked(tmp_path: Path) -> None:
    """Verschachtelte Archive werden rekursiv entpackt."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("tief.png", _png_with_text("Drehstrom"))
    outer = tmp_path / "aussen.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("innen.zip", inner.getvalue())
    expanded = import_worker._unpack_archives([(str(outer), "aussen.zip")], "nestedjob")
    names = [name for _path, name in expanded]
    assert "tief.png" in names


def test_zip_with_forbidden_content_is_reported(tmp_path: Path) -> None:
    """Archive mit ausschliesslich verbotenen Inhalten werden gemeldet."""
    path = tmp_path / "boese.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("script.sh", "#!/bin/sh\necho boese\n")
    expanded = import_worker._unpack_archives([(str(path), "boese.zip")], "badjob")
    assert expanded
    assert expanded[0][1] == "boese.zip"


def test_zip_bomb_size_limit_is_enforced(tmp_path: Path) -> None:
    """Das entpackte Gesamtvolumen wird begrenzt (Schutz vor ZIP-Bomben)."""
    from app.config import settings

    settings.set_runtime("import_max_unpacked_mb", 1)
    try:
        path = tmp_path / "bombe.zip"
        payload = b"0" * (2 * 1024 * 1024)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(4):
                z.writestr(f"teil_{i}.txt", payload)
        expanded = import_worker._unpack_archives([(str(path), "bombe.zip")], "bombjob")
        # Es darf nur so viel entpackt werden, wie das Limit erlaubt.
        unpacked = sum(Path(p).stat().st_size for p, _n in expanded if Path(p).exists())
        assert unpacked <= 2 * 1024 * 1024
    finally:
        settings.set_runtime("import_max_unpacked_mb", 4096)


# ---------------------------------------------------------------------------
# Unterbrochene Auftraege
# ---------------------------------------------------------------------------
def test_interrupted_job_without_files_is_closed(tmp_path: Path) -> None:
    """Ein Auftrag ohne Dateiliste kann nicht fortgesetzt werden -> Fehler."""
    job_id = db.new_id()
    db.insert(
        "INSERT INTO import_jobs(id, status, total_files, current_item, message, stats_json, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (job_id, "running", 3, "datei.pdf", "laeuft", db.json_dumps_safe({}), db.now(), db.now()),
    )
    _resume_without_worker()
    job = import_worker.job(job_id)
    assert job is not None
    assert job["status"] == "error"


def test_interrupted_job_with_files_is_requeued(tmp_path: Path) -> None:
    """Ein Auftrag mit Dateiliste wird nach dem Neustart fortgesetzt."""
    source = tmp_path / "weiter.txt"
    source.write_text("Inhalt fuer den fortgesetzten Import", encoding="utf-8")
    job_id = db.new_id()
    db.insert(
        "INSERT INTO import_jobs(id, status, total_files, current_item, message, stats_json, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (job_id, "running", 1, "weiter.txt", "laeuft",
         db.json_dumps_safe({"files": [[str(source), "weiter.txt"]], "collection": None}),
         db.now(), db.now()),
    )
    _resume_without_worker()
    job = import_worker.job(job_id)
    assert job is not None
    assert job["status"] == "queued"


def _resume_without_worker() -> None:
    """Fuehrt resume_interrupted_jobs aus, ohne einen echten Worker zu starten."""
    import queue as _queue

    original = import_worker._queue
    import_worker._queue = _queue.Queue()
    try:
        import_worker.resume_interrupted_jobs()
    finally:
        import_worker._queue = original


def test_worker_survives_failing_error_handler(monkeypatch) -> None:
    """Der Worker darf nicht sterben, wenn die Fehlerbehandlung selbst ausfaellt.

    Vorher beendete eine Ausnahme in _set_job den Worker dauerhaft, danach
    waren keine Importe mehr moeglich. Jetzt muss der zweite Auftrag noch
    verarbeitet werden.
    """
    calls = {"process": 0}

    def fake_process(job_id, paths):
        calls["process"] += 1
        raise RuntimeError("kaputte Datenbank")

    def fake_set_job(job_id, **fields):
        if fields.get("status") == "error":
            raise RuntimeError("auch das Speichern schlaegt fehl")

    monkeypatch.setattr(import_worker, "_process_job", fake_process)
    monkeypatch.setattr(import_worker, "_set_job", fake_set_job)

    import queue as _queue

    test_queue = _queue.Queue()
    test_queue.put(("job-1", []))
    test_queue.put(("job-2", []))
    monkeypatch.setattr(import_worker, "_queue", test_queue)

    thread = threading.Thread(target=import_worker._run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while calls["process"] < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert calls["process"] == 2, "Worker hat nach dem Fehler nicht weitergemacht"
    assert thread.is_alive(), "Worker-Thread ist gestorben"


# ---------------------------------------------------------------------------
# Schema-Migration
# ---------------------------------------------------------------------------
def test_schema_migration_removes_global_unique_on_sha256(tmp_path: Path) -> None:
    """Eine Datenbank im alten Schema (sha256 UNIQUE) wird fehlerfrei migriert.

    Vorher konnte eine zweite leere Datei nicht gespeichert werden.
    """
    import sqlite3

    db_file = tmp_path / "alt.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, stored_path TEXT NOT NULL,
            mime TEXT, sha256 TEXT UNIQUE, size_bytes INTEGER NOT NULL DEFAULT 0,
            page_count INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'upload',
            collection TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
            meta_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        INSERT INTO documents VALUES('a','alt.txt','/tmp/x','text/plain','hash1',10,1,
            'upload',NULL,'ready',NULL,'{}','2026-01-01','2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    db._migrate_documents_sha256(conn)
    conn.commit()

    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()["sql"]
    assert not db._has_column_unique(ddl, "sha256")
    # Altdaten bleiben erhalten.
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 1
    # Ein zweiter Eintrag mit demselben Hash ist jetzt erlaubt.
    conn.execute(
        "INSERT INTO documents(id, filename, stored_path, sha256, size_bytes, page_count, "
        "status, meta_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("b", "zweite.txt", "/tmp/y", "hash1", 0, 0, "error", "{}", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 2
    conn.close()


def test_partial_unique_index_still_blocks_real_duplicates(tmp_path: Path) -> None:
    """Der Teilindex verhindert weiterhin echte Duplikate mit Inhalt."""
    import sqlite3

    from app.config import settings

    conn = sqlite3.connect(settings.db_path)
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256_content
            ON documents(sha256) WHERE page_count > 0 AND status != 'error';
        """
    )
    params = ("insert into documents(id, filename, stored_path, sha256, size_bytes, "
              "page_count, status, meta_json, created_at, updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)")
    conn.execute(params, ("x1", "a.txt", "/tmp/a", "gleich", 5, 1, "ready", "{}", "1", "1"))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(params, ("x2", "b.txt", "/tmp/b", "gleich", 5, 1, "ready", "{}", "1", "1"))
    conn.close()


# ---------------------------------------------------------------------------
# Samsung Notes
# ---------------------------------------------------------------------------
def test_samsung_container_pages_keep_original_order(tmp_path: Path) -> None:
    path = tmp_path / "notiz.sdoc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("note.json", '{"title":"Test","pages":2}')
        for i in range(2):
            z.writestr(f"images/page{i}.png", _png_with_text(f"Seite {i} Inhalt"))
    result = samsung_notes.process_container(path)
    assert len(result.pages) >= 2
    numbers = [p.page_number for p in result.pages]
    assert numbers == sorted(numbers)


def test_samsung_container_without_images_reports_problem(tmp_path: Path) -> None:
    """Ein Container ohne Bilder und ohne Text gilt als problematisch."""
    path = tmp_path / "leer.sdoc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("meta.json", "{}")
    result = samsung_notes.process_container(path)
    assert result.needs_review or result.meta.get("error")


def test_samsung_container_keeps_embedded_text_without_images(tmp_path: Path) -> None:
    """Enthaelt der Container nur Text, wird dieser als Seite uebernommen."""
    path = tmp_path / "text.sdoc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("note.json", '{"title":"Drehstrom","text":"Leistung P = U mal I"}')
    result = samsung_notes.process_container(path)
    assert result.pages
    combined = " ".join(p.text for p in result.pages)
    assert "Drehstrom" in combined
