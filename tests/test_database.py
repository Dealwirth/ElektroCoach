"""Tests der Datenbank, FTS5-Suche, Duplikaterkennung und Sicherheitsfunktionen."""

from __future__ import annotations

import json

import pytest

from app import db
from app.config import settings
from app.security import decrypt, encrypt, is_allowed_upload, safe_filename, sha256_file, slugify
from app.services import library


def test_schema_tabellen_vorhanden():
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    for table in (
        "documents", "pages", "chunks", "chunks_fts", "topics", "topic_chunks",
        "questions", "attempts", "srs", "exams", "exam_questions", "learning_goals",
        "schematic_projects", "import_jobs", "ai_usage", "settings",
    ):
        assert table in names, f"Tabelle fehlt: {table}"


def test_fts5_verfuegbar():
    row = db.query_one("SELECT 1 AS x FROM pragma_compile_options WHERE compile_options LIKE '%FTS5%'")
    assert row is not None


def test_wal_modus_aktiv():
    row = db.query_one("PRAGMA journal_mode")
    assert row[0].lower() == "wal"


def test_foreign_keys_aktiv():
    row = db.query_one("PRAGMA foreign_keys")
    assert row[0] == 1


def test_suche_findet_abschnitt(sample_text):
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "notizen.txt"
        path.write_text(sample_text, encoding="utf-8")
        doc = library.store_document(path, "notizen.txt", collection="Testjahr")
        assert doc["status"] in {"ready", "needs_review"}

    hits = library.search("Leitungsschutzschalter")
    assert hits["count"] >= 1
    assert any("Leitungsschutzschalter" in h["text"] for h in hits["results"])

    library.delete_document(doc["id"])


def test_suche_mit_umlauten_und_diakritika(sample_text):
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "umlaut.txt"
        path.write_text("Der Spannungsfall über die Leitung ist zu groß.", encoding="utf-8")
        doc = library.store_document(path, "umlaut.txt")

    assert library.search("Spannungsfall")["count"] >= 1
    assert library.search("groß")["count"] >= 1
    library.delete_document(doc["id"])


def test_suche_mit_sonderzeichen_erzeugt_keinen_fehler():
    assert library.search("!!! ((( ))) ***")["count"] == 0
    assert library.search("")["count"] == 0


def test_duplikaterkennung_ueber_sha256(sample_text):
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.txt"
        path.write_text(sample_text, encoding="utf-8")
        digest = sha256_file(path)
        first = library.store_document(path, "a.txt", sha256=digest)
        assert library.find_duplicate(digest) is not None
        assert library.find_duplicate(digest)["id"] == first["id"]
        library.delete_document(first["id"])


def test_nahe_duplikate_werden_erkannt():
    from pathlib import Path
    import tempfile

    text = (
        "Der Leitungsschutzschalter schuetzt die elektrische Leitung vor Ueberlast "
        "und Kurzschluss und wird nach dem Nennstrom ausgewaehlt."
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.txt"
        path.write_text(text, encoding="utf-8")
        doc = library.store_document(path, "x.txt")

    hits = library.near_duplicate_chunks(text, threshold=0.8)
    assert hits
    assert hits[0]["similarity"] >= 0.8
    library.delete_document(doc["id"])


def test_chunk_anzahl_passt_zur_seitenzahl():
    from pathlib import Path
    import tempfile

    long_text = "\n\n".join(
        ["Absatz mit Fachinhalt zum Thema Elektrotechnik und Installation " + str(i)
         for i in range(60)]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "lang.txt"
        path.write_text(long_text, encoding="utf-8")
        doc = library.store_document(path, "lang.txt")

    chunks = library.get_chunks(doc["id"])
    assert len(chunks) >= 2
    assert chunks[0]["page_number"] == 1
    library.delete_document(doc["id"])


def test_dokument_loeschen_entfernt_seiten_und_abschnitte():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "del.txt"
        path.write_text("Inhalt zum Loeschen. " * 20, encoding="utf-8")
        doc = library.store_document(path, "del.txt")

    doc_id = doc["id"]
    assert library.get_document(doc_id) is not None
    assert library.delete_document(doc_id) is True
    assert library.get_document(doc_id) is None
    assert library.get_pages(doc_id) == []
    assert library.get_chunks(doc_id) == []


def test_seitentext_korrigieren_entfernt_pruefmarkierung():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ocr.txt"
        # Sehr kurzer Text -> als pruefbeduerftig markiert.
        path.write_text("x", encoding="utf-8")
        doc = library.store_document(path, "ocr.txt")

    pages = library.get_pages(doc["id"])
    assert pages
    page_id = pages[0]["id"]
    assert library.update_page_text(page_id, "Der RCD schuetzt Personen bei Fehlerstrom mit 30 mA.", True)
    updated = library.get_pages(doc["id"])
    assert updated[0]["needs_review"] == 0
    assert "RCD" in updated[0]["text"]
    # Neue Abschnitte wurden erzeugt und sind durchsuchbar.
    assert library.search("Fehlerstrom")["count"] >= 1
    library.delete_document(doc["id"])


# ---------------------------------------------------------------------------
# Sicherheit
# ---------------------------------------------------------------------------
def test_safe_filename_entfernt_pfadanteile():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("/tmp/../secret.txt") == "secret.txt"
    assert safe_filename("C:\\Windows\\system32\\evil.exe") == "evil.exe"
    assert "/" not in safe_filename("a/b/c.pdf")
    assert safe_filename("") == "datei"


def test_safe_filename_entfernt_steuerzeichen():
    result = safe_filename("test\x00\x01\x1f.pdf")
    assert "\x00" not in result
    assert result.endswith(".pdf")


def test_is_allowed_upload():
    assert is_allowed_upload("notizen.pdf") is True
    assert is_allowed_upload("scan.PNG") is True
    assert is_allowed_upload("sammlung.sdoc") is True
    assert is_allowed_upload("boese.exe") is False
    assert is_allowed_upload("script.sh") is False


def test_slugify():
    assert slugify("Leitungsberechnung und Spannungsfall") == "leitungsberechnung-und-spannungsfall"
    assert slugify("") == "thema"
    assert slugify("Ümläute & Sonderzeichen!!!") == "ml-ute-sonderzeichen"


def test_verschluesselung_rundlauf():
    secret = "AIzaSyTestKey1234567890"
    token = encrypt(settings.data_dir, secret)
    assert token != secret
    assert token.startswith(("enc:", "plain:"))
    assert decrypt(settings.data_dir, token) == secret


def test_verschluesselung_leerer_wert():
    assert decrypt(settings.data_dir, "") == ""


def test_einstellungen_werden_gespeichert():
    db.set_setting("test_key", "test_value")
    assert db.get_setting("test_key") == "test_value"
    db.set_setting("test_key", "neu")
    assert db.get_setting("test_key") == "neu"


def test_backup_und_wiederherstellung():
    from app.services import backup

    db.set_setting("backup_probe", "vor-backup")
    result = backup.create_backup("test", include_documents=False)
    assert result["ok"] is True
    name = result["name"]
    assert any(item["name"] == name for item in backup.list_backups())

    db.set_setting("backup_probe", "nach-backup")
    assert db.get_setting("backup_probe") == "nach-backup"

    restore = backup.restore_backup(name, restore_documents=False)
    assert restore["ok"] is True
    assert db.get_setting("backup_probe") == "vor-backup"
    assert backup.delete_backup(name) is True


def test_backup_pfad_ausbruch_wird_verhindert():
    from app.services import backup

    assert backup.delete_backup("../../etc/passwd") is False
    assert backup.delete_backup("nicht-vorhanden.tar.gz") is False


def test_nach_wiederherstellung_sind_schreibzugriffe_moeglich():
    """Regression: nach dem Ersetzen der Datenbankdatei muss Schreiben gehen.

    Beim Ersetzen der Datei werden auch die WAL-Dateien entfernt. Eine
    Verbindung, die vorher bestand, zeigt danach ins Leere; Schreibzugriffe
    scheiterten mit "disk I/O error". Der Verbindungsgenerationszaehler zwingt
    jeden Thread, die Verbindung neu aufzubauen.
    """
    import threading

    from app.services import backup

    db.set_setting("restore_probe", "vor")
    result = backup.create_backup("restore-test", include_documents=False)
    assert result["ok"] is True
    name = result["name"]
    db.set_setting("restore_probe", "nach")

    ready = threading.Event()
    proceed = threading.Event()
    outcome: dict[str, object] = {}

    def worker() -> None:
        before = db.get_conn()
        outcome["before"] = id(before)
        ready.set()
        proceed.wait(timeout=10)
        try:
            after = db.get_conn()
            outcome["after"] = id(after)
            db.set_setting("restore_thread", "ok")
            outcome["value"] = db.get_setting("restore_thread")
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = repr(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(timeout=10)

    restore = backup.restore_backup(name, restore_documents=False)
    assert restore["ok"] is True

    proceed.set()
    thread.join(timeout=10)

    assert "error" not in outcome, outcome.get("error")
    assert outcome.get("value") == "ok"
    # Die Verbindung des Threads wurde tatsaechlich ersetzt.
    assert outcome["before"] != outcome["after"]

    # Auch ein direkter Schreibvorgang aus dem Hauptthread muss gehen.
    db.execute(
        "INSERT INTO learning_goals(id, title, target, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("restore-goal", "Probe", "", db.now(), db.now()),
    )
    assert db.query_one("SELECT title FROM learning_goals WHERE id = ?", ("restore-goal",))["title"] == "Probe"

    backup.delete_backup(name)


def test_storage_report_enthaelt_kennzahlen():
    from app.services import backup

    report = backup.storage_report()
    for key in ("disk_total_mb", "disk_free_mb", "database_mb", "integrity", "counts"):
        assert key in report
    assert report["integrity"] == "ok"


def test_json_dumps_safe_mit_nicht_serialisierbarem_wert():
    class Eigenartig:
        pass

    result = db.json_dumps_safe({"objekt": Eigenartig()})
    assert json.loads(result)["objekt"].startswith("<")
