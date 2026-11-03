"""API-Tests der neuen Endpunkte: Ollama-Add-on und KI-Nachbearbeitung."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import db
from app.config import settings


class _OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._send(200, b'{"models": [{"name": "llama3.2:3b"}]}')
        else:
            self._send(404, b'{"error": "not found"}')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path.startswith("/api/chat"):
            content = (
                '{"text": "Korrigierter Text", "confidence": 0.9, '
                '"notes": "", "uncertain": false}'
            )
            payload = ('{"message": {"role": "assistant", "content": ' +
                       __import__("json").dumps(content) + '}}').encode()
            self._send(200, payload)
        elif self.path.startswith("/api/pull"):
            self._send(200, b'{"status": "success"}')
        else:
            self._send(404, b'{"error": "not found"}')


@pytest.fixture
def ollama_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    settings.set_runtime("ollama_url", f"http://{host}:{port}")
    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("ai_mode", "local_only")
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("ai_mode", "auto")


def _make_page(text: str = "ocr fehler text") -> str:
    doc_id = db.new_id()
    page_id = db.new_id()
    db.insert(
        "INSERT INTO documents(id, filename, stored_path, mime, sha256, size_bytes, "
        "source, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (doc_id, "api.pdf", "/tmp/api.pdf", "application/pdf", db.new_id(), 5,
         "test", "needs_review", db.now(), db.now()),
    )
    db.insert(
        "INSERT INTO pages(id, document_id, page_number, text, needs_review, meta_json, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (page_id, doc_id, 1, text, 1, "{}", db.now()),
    )
    return page_id


def test_ollama_addon_status_endpoint(client):
    data = client.get("/api/ai/ollama/addon").json()
    assert "supervisor" in data
    assert "installed" in data


def test_ollama_installed_endpoint(client, ollama_server):
    data = client.get("/api/ai/ollama/installed").json()
    assert data["ok"] is True
    assert "llama3.2:3b" in data["models"]


def test_ollama_pull_endpoint(client, ollama_server):
    response = client.post("/api/ai/ollama/pull", json={"model": "llama3.2:3b"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_ollama_pull_leerer_name_wird_abgelehnt(client):
    assert client.post("/api/ai/ollama/pull", json={"model": ""}).status_code == 422


def test_ollama_addon_ensure_ohne_supervisor(client, monkeypatch):
    from app.services import ollama_addon

    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "")
    response = client.post("/api/ai/ollama/addon/ensure")
    assert response.status_code == 400


def test_refine_page_endpoint(client, ollama_server):
    page_id = _make_page()
    response = client.post("/api/ai/refine/page", json={"page_id": page_id})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["text"] == "Korrigierter Text"
    page = db.query_one("SELECT text, needs_review FROM pages WHERE id = ?", (page_id,))
    assert page["text"] == "Korrigierter Text"


def test_refine_page_unbekannt_ist_404(client, ollama_server):
    assert client.post("/api/ai/refine/page", json={"page_id": "gibtsnicht"}).status_code == 404


def test_refine_start_ohne_ki_wird_abgelehnt(client):
    settings.set_runtime("ollama_enabled", False)
    settings.set_runtime("gemini_api_key", "")
    settings.set_runtime("ai_mode", "off")
    response = client.post("/api/ai/refine", json={"scope": "review"})
    assert response.status_code == 400
    settings.set_runtime("ai_mode", "auto")


def test_refine_job_lifecycle(client, ollama_server):
    _make_page("noch ein ocr text")
    response = client.post("/api/ai/refine", json={"scope": "review"})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    # Der Worker laeuft im Hintergrund; wir warten kurz auf den Abschluss.
    import time

    for _ in range(40):
        data = client.get(f"/api/ai/refine/jobs/{job_id}").json()
        if data["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.2)
    assert data["status"] == "done"
    assert data["progress_percent"] >= 0


def test_refine_jobs_liste(client):
    data = client.get("/api/ai/refine/jobs").json()
    assert "items" in data
    assert "queue" in data
