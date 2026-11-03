"""Tests der Ollama-Add-on-Verwaltung gegen einen echten lokalen HTTP-Server.

Der Supervisor und die Ollama-Schnittstelle werden durch zwei lokale
HTTP-Server nachgebildet. Dadurch laufen die echten Code-Pfade (httpx,
Supervisor-Aufrufe, Adressermittlung) ohne Ersatz des HTTP-Clients.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.config import settings
from app.services import ollama_addon


class _SupervisorHandler(BaseHTTPRequestHandler):
    """Minimaler Supervisor: Add-on-Liste, Info, Store, Start, Installation."""

    def log_message(self, *args):
        return

    def _send(self, code: int, payload: dict | None = None) -> None:
        # Der echte Supervisor verpackt Erfolgsantworten in
        # {"result": "ok", "data": ...}. Das bildet der Testserver nach.
        if code == 200 and payload is not None:
            payload = {"result": "ok", "data": payload}
        body = json.dumps(payload or {}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/addons":
            self._send(200, {"addons": [{
                "slug": "76e18fb5_ollama", "name": "Ollama", "state": "started",
                "hostname": "76e18fb5-ollama", "network": {"11434/tcp": None},
            }]})
        elif self.path == "/addons/76e18fb5_ollama/info":
            self._send(200, {
                "slug": "76e18fb5_ollama", "state": "started",
                "hostname": "76e18fb5-ollama", "network": {"11434/tcp": None},
            })
        elif self.path in ("/store/addons", "/store/apps"):
            self._send(200, {"addons": [{
                "slug": "76e18fb5_ollama", "name": "Ollama", "installed": False,
            }]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path.endswith("/start"):
            self._send(200, {"result": "ok"})
        elif "/install" in self.path:
            self._send(200, {"result": "ok"})
        else:
            self._send(404, {"error": "not found"})


class _OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
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
            self._send(200, {"models": [{"name": "llama3.2:3b"}, {"name": "phi4-mini:3.8b"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path.startswith("/api/pull"):
            self._send(200, {"status": "success"})
        else:
            self._send(404, {"error": "not found"})


def _serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


@pytest.fixture
def supervisor(monkeypatch):
    server, url = _serve(_SupervisorHandler)
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_URL", url)
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def ollama_server():
    server, url = _serve(_OllamaHandler)
    settings.set_runtime("ollama_url", url)
    yield url
    server.shutdown()
    server.server_close()


def test_available_ohne_token(monkeypatch):
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "")
    assert ollama_addon.available() is False
    result = asyncio.run(ollama_addon.status())
    assert result["supervisor"] is False
    assert result["installed"] is False


def test_url_from_addon_nutzt_hostname():
    addon = {"slug": "76e18fb5_ollama", "hostname": "76e18fb5-ollama", "network": {"11434/tcp": None}}
    assert ollama_addon.url_from_addon(addon) == "http://76e18fb5-ollama:11434"


def test_url_from_addon_ohne_hostname_faellt_auf_slug_zurueck():
    assert ollama_addon.url_from_addon({"slug": "abc_ollama"}) == "http://abc-ollama:11434"


def test_url_from_addon_ohne_angaben():
    assert ollama_addon.url_from_addon({}) is None


def test_unwrap_packt_supervisor_antwort_aus():
    # Der Supervisor liefert {"result": "ok", "data": {...}}.
    payload = {"result": "ok", "data": {"addons": [{"slug": "x"}]}}
    assert ollama_addon.unwrap(payload) == {"addons": [{"slug": "x"}]}


def test_unwrap_meldet_supervisor_fehler():
    with pytest.raises(ollama_addon.SupervisorError):
        ollama_addon.unwrap({"result": "error", "message": "Forbidden"})


def test_unwrap_laesst_klartext_durch():
    assert ollama_addon.unwrap({"models": []}) == {"models": []}


def test_find_installed_erkennt_ollama(supervisor):
    addon = asyncio.run(ollama_addon.find_installed())
    assert addon is not None
    assert addon["slug"] == "76e18fb5_ollama"


def test_all_addons_verarbeitet_reine_liste(monkeypatch):
    # Manche Supervisor-Versionen liefern eine Liste statt {"addons": [...]}.
    server, url = _serve(_SupervisorHandler)
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "t")
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_URL", url)

    async def fake_request(method, endpoint, **kwargs):
        if endpoint in ("/addons", "/apps"):
            return [{"slug": "76e18fb5_ollama", "name": "Ollama", "state": "started"}]
        raise ollama_addon.SupervisorError("unerwartet")

    monkeypatch.setattr(ollama_addon, "_request", fake_request)
    try:
        addon = asyncio.run(ollama_addon.find_installed())
        assert addon is not None
        assert addon["slug"] == "76e18fb5_ollama"
    finally:
        server.shutdown()
        server.server_close()


def test_status_meldet_fehler_wenn_supervisor_ablehnt(monkeypatch):
    # Ohne Supervisor-Zugriff liefert /addons einen Fehler. Statt eines
    # stillen "nicht installiert" muss die Ursache sichtbar sein.
    server, url = _serve(_SupervisorHandler)
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "t")
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_URL", url)

    async def fake_request(method, endpoint, **kwargs):
        raise ollama_addon.SupervisorError("HTTP 403: Forbidden")

    monkeypatch.setattr(ollama_addon, "_request", fake_request)
    try:
        result = asyncio.run(ollama_addon.status())
        assert result["installed"] is False
        assert "403" in result["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_status_meldet_installiert(supervisor):
    result = asyncio.run(ollama_addon.status())
    assert result["supervisor"] is True
    assert result["installed"] is True
    assert result["suggested_url"] == "http://76e18fb5-ollama:11434"


def test_find_in_store(supervisor):
    entry = asyncio.run(ollama_addon.find_in_store())
    assert entry is not None
    assert "ollama" in entry["slug"]


def test_installed_models_liest_tags(ollama_server):
    result = asyncio.run(ollama_addon.installed_models())
    assert result["ok"] is True
    assert "llama3.2:3b" in result["models"]


def test_installed_models_ohne_adresse():
    settings.set_runtime("ollama_url", "")
    result = asyncio.run(ollama_addon.installed_models())
    assert result["ok"] is False
    assert result["models"] == []


def test_pull_model_erfolgreich(ollama_server):
    result = asyncio.run(ollama_addon.pull_model("llama3.2:3b"))
    assert result["ok"] is True
    assert result["model"] == "llama3.2:3b"


def test_pull_model_ohne_adresse():
    settings.set_runtime("ollama_url", "")
    result = asyncio.run(ollama_addon.pull_model("llama3.2:3b"))
    assert result["ok"] is False


def test_pull_model_ohne_namen(ollama_server):
    result = asyncio.run(ollama_addon.pull_model(""))
    assert result["ok"] is False


def test_ensure_running_hinterlegt_adresse(supervisor):
    # Der Add-on-Hostname ist nicht aufloesbar; ensure_running darf deshalb
    # nicht dauerhaft blockieren und muss den Fehler transparent melden.
    result = asyncio.run(ollama_addon.ensure_running(wait_attempts=1, wait_delay=0.05))
    assert result["installed"] is True
    assert result["slug"] == "76e18fb5_ollama"
    assert result["url"] == "http://76e18fb5-ollama:11434"
    # Nicht erreichbar -> ok ist False, aber kein Absturz.
    assert result["ok"] is False


def test_ensure_running_ohne_supervisor(monkeypatch):
    monkeypatch.setattr(ollama_addon, "SUPERVISOR_TOKEN", "")
    result = asyncio.run(ollama_addon.ensure_running())
    assert result["ok"] is False
    assert "Supervisor" in result["error"]
