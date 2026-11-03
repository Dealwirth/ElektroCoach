"""Tests der KI-Nachbearbeitung (refine) und der Ollama-Add-on-Verwaltung.

Es wird ein echter lokaler HTTP-Server gestartet, der die Ollama-Schnittstelle
nachbildet. Damit laufen die echten Code-Pfade (httpx, ai_router, refine) gegen
einen realen Server - es wird kein HTTP-Client ersetzt.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import db
from app.config import settings
from app.services import refine
from app.workers import refine_worker

REPLY_TEXT = "Der Leitungsschutzschalter schuetzt die Leitung."


class _Handler(BaseHTTPRequestHandler):
    """Minimaler Ollama-Nachbau: /api/tags und /api/chat."""

    def log_message(self, *args):  # noqa: D401 - ruhiger Testserver
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._send(200, {"models": [{"name": "llama3.2:3b"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path.startswith("/api/chat"):
            content = json.dumps({
                "text": REPLY_TEXT,
                "confidence": 0.93,
                "notes": "Einheiten korrigiert",
                "uncertain": False,
            })
            self._send(200, {"message": {"role": "assistant", "content": content}})
        elif self.path.startswith("/api/pull"):
            self._send(200, {"status": "success"})
        else:
            self._send(404, {"error": "not found"})


@pytest.fixture
def ollama_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    settings.set_runtime("ollama_url", f"http://{host}:{port}")
    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("ai_mode", "local_only")
    settings.set_runtime("refine_use_cloud", False)
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("ai_mode", "auto")


def _make_document(text: str = "Der Leitungsschutzschalter schutzt die Leitung.") -> tuple[str, str]:
    doc_id = db.new_id()
    page_id = db.new_id()
    db.insert(
        "INSERT INTO documents(id, filename, stored_path, mime, sha256, size_bytes, "
        "source, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (doc_id, "probe.pdf", "/tmp/probe.pdf", "application/pdf", db.new_id(), 10,
         "test", "needs_review", db.now(), db.now()),
    )
    db.insert(
        "INSERT INTO pages(id, document_id, page_number, text, needs_review, meta_json, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (page_id, doc_id, 1, text, 1, "{}", db.now()),
    )
    return doc_id, page_id


def _cleanup(doc_id: str) -> None:
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def test_refine_page_verbessert_text(ollama_server):
    doc_id, page_id = _make_document()
    try:
        row = db.query_one("SELECT * FROM pages WHERE id = ?", (page_id,))
        result = asyncio.run(refine.refine_page(dict(row)))
        assert result["ok"] is True
        assert result["text"] == REPLY_TEXT
        assert result["confidence"] == pytest.approx(0.93)
        assert result["needs_review"] is False
        assert "ollama" in result["providers"]
    finally:
        _cleanup(doc_id)


def test_refine_apply_schreibt_in_datenbank(ollama_server):
    doc_id, page_id = _make_document()
    try:
        row = db.query_one("SELECT * FROM pages WHERE id = ?", (page_id,))
        result = asyncio.run(refine.refine_page(dict(row)))
        assert refine.apply_result(result) is True
        page = db.query_one("SELECT text, needs_review, ocr_confidence FROM pages WHERE id = ?", (page_id,))
        assert page["text"] == REPLY_TEXT
        assert page["needs_review"] == 0
        chunks = db.query("SELECT text FROM chunks WHERE page_id = ?", (page_id,))
        assert chunks and REPLY_TEXT in chunks[0]["text"]
        meta = db.query_one("SELECT meta_json FROM pages WHERE id = ?", (page_id,))
        assert "refined" in json.loads(meta["meta_json"])
    finally:
        _cleanup(doc_id)


def test_refine_ohne_ki_behaelt_originaltext(monkeypatch):
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("gemini_api_key", "")
    settings.set_runtime("ai_mode", "off")
    doc_id, page_id = _make_document("Unveraenderter Originaltext.")
    try:
        row = db.query_one("SELECT * FROM pages WHERE id = ?", (page_id,))
        result = asyncio.run(refine.refine_page(dict(row)))
        assert result["ok"] is False
        # Der Originaltext darf nicht verloren gehen.
        page = db.query_one("SELECT text FROM pages WHERE id = ?", (page_id,))
        assert page["text"] == "Unveraenderter Originaltext."
    finally:
        _cleanup(doc_id)


def test_refine_leere_seite_wird_gemeldet(ollama_server):
    doc_id, page_id = _make_document("")
    try:
        row = db.query_one("SELECT * FROM pages WHERE id = ?", (page_id,))
        result = asyncio.run(refine.refine_page(dict(row)))
        assert result["ok"] is False
    finally:
        _cleanup(doc_id)


def test_parse_response_liest_json_aus_umgebung():
    raw = 'Hier das Ergebnis:\n```json\n{"text": "Hallo", "confidence": 0.5}\n```'
    parsed = refine._parse_response(raw)
    assert parsed is not None
    assert parsed["text"] == "Hallo"
    assert parsed["confidence"] == 0.5


def test_parse_response_lehnt_unbrauchbare_antwort_ab():
    assert refine._parse_response("") is None
    assert refine._parse_response("kein json hier") is None
    assert refine._parse_response('{"foo": 1}') is None


def test_pending_pages_findet_prueffall():
    doc_id, page_id = _make_document("Zu pruefender Text.")
    try:
        pages = refine.pending_pages(document_id=doc_id)
        assert any(p["id"] == page_id for p in pages)
    finally:
        _cleanup(doc_id)


def test_refine_worker_verarbeitet_auftrag(ollama_server):
    doc_id, page_id = _make_document("ocr fehler: leitungsschutzschalter")
    try:
        job_id = refine_worker.create_job(doc_id, "document")
        refine_worker._process_job(job_id)
        data = refine_worker.job(job_id)
        assert data["status"] == "done"
        assert data["processed_pages"] >= 1
        page = db.query_one("SELECT text FROM pages WHERE id = ?", (page_id,))
        assert page["text"] == REPLY_TEXT
    finally:
        _cleanup(doc_id)
