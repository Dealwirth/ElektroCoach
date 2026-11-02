"""API and security tests through the real FastAPI application.

The app is started with ``TestClient`` and the real middleware stack, so these
tests exercise CSRF enforcement, security headers, input validation, path
traversal protection and the Ingress path handling end to end.
"""

from __future__ import annotations

import io
import json

import pytest


# -- session and meta --------------------------------------------------------

def test_healthz_is_public_and_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]


def test_session_creates_a_session_and_returns_csrf_token(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    payload = response.json()
    assert payload["csrf_token"]
    assert payload["user"]
    # The session cookie must be set and hardened.
    cookie_header = response.headers.get("set-cookie", "")
    assert "elektrocoach_session" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header.lower() or "samesite=strict" in cookie_header.lower()


def test_meta_reports_the_addon_version(client):
    response = client.get("/api/meta")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0"
    assert payload["schema_version"] >= 1
    assert payload["grid_size"] == 20
    assert "features" in payload


# -- CSRF protection ---------------------------------------------------------

def test_mutating_request_without_csrf_is_rejected(client):
    client.get("/api/session")  # obtain a session cookie
    response = client.post("/api/learning/plan", json={})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"] or "Sicherheitsschlüssel" in response.json()["detail"]


def test_mutating_request_with_wrong_csrf_is_rejected(client):
    client.get("/api/session")
    response = client.post("/api/learning/plan", json={},
                           headers={"X-CSRF-Token": "falsch"})
    assert response.status_code == 403


def test_mutating_request_without_session_is_rejected(client):
    # No prior GET /api/session, so no cookie exists at all.
    response = client.post("/api/learning/plan", json={},
                           headers={"X-CSRF-Token": "irgendwas"})
    assert response.status_code == 403


def test_read_request_does_not_need_csrf(client):
    client.get("/api/session")
    assert client.get("/api/dashboard").status_code == 200


def test_mutating_request_with_valid_csrf_succeeds(csrf_client):
    response = csrf_client.post("/api/learning/plan", json={})
    assert response.status_code in (200, 201)


# -- security headers --------------------------------------------------------

def test_security_headers_are_present(client):
    response = client.get("/api/session")
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
                   "Content-Security-Policy"):
        assert response.headers.get(header), f"missing security header {header}"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_oversized_upload_is_refused_before_reading(client):
    client.get("/api/session")
    token = client.get("/api/session").json()["csrf_token"]
    huge = b"x" * (65 * 1024 * 1024)
    response = client.post(
        "/api/documents/upload",
        files={"file": ("big.pdf", io.BytesIO(huge), "application/pdf")},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 413
    assert "zu groß" in response.json()["detail"]


# -- input validation --------------------------------------------------------

def test_upload_rejects_an_unsupported_file_type(csrf_client):
    response = csrf_client.post(
        "/api/documents/upload",
        files={"file": ("schaedlich.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")},
    )
    assert response.status_code == 400
    assert "Dateityp" in response.json()["detail"] or "nicht" in response.json()["detail"]


def test_upload_rejects_an_empty_file(csrf_client):
    response = csrf_client.post(
        "/api/documents/upload",
        files={"file": ("leer.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert response.status_code == 400


def test_drawing_validate_rejects_a_broken_body(csrf_client):
    response = csrf_client.post("/api/drawing/validate", json={"data": "kein objekt"})
    # Either a validation error or a well-formed empty report; never a 500.
    assert response.status_code in (200, 422)


def test_unknown_api_route_returns_a_clean_404(client):
    response = client.get("/api/gibtsnicht")
    assert response.status_code == 404
    assert "detail" in response.json()


# -- path traversal ----------------------------------------------------------

def test_page_image_endpoint_rejects_path_traversal(csrf_client):
    """The page image is addressed by numeric id, never by a client path."""

    response = csrf_client.get("/api/documents/pages/../../etc/passwd/image")
    # The router must not resolve this to a filesystem read.
    assert response.status_code in (400, 404, 422)


def test_document_download_uses_numeric_ids(client):
    response = client.get("/api/documents/..%2f..%2fetc%2fpasswd")
    assert response.status_code in (400, 404, 422)


# -- settings never leak secrets --------------------------------------------

def test_settings_never_return_a_gemini_key(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "settings" in payload
    assert "runtime" in payload
    # The raw secret is never part of the settings map; only a boolean flag
    # reports whether a key is configured.
    assert "runtime.gemini_api_key" not in payload["settings"]
    assert isinstance(payload["runtime"]["gemini_api_key_set"], bool)


def test_gemini_key_can_be_stored_but_is_never_returned(csrf_client):
    csrf_client.patch("/api/settings/runtime",
                      json={"gemini_api_key": "geheim-123", "gemini_enabled": True})
    response = csrf_client.get("/api/settings")
    assert "geheim-123" not in response.text
    assert response.json()["runtime"]["gemini_api_key_set"] is True
    # The stored secret must also be absent from the raw settings map.
    assert "runtime.gemini_api_key" not in response.json()["settings"]


# -- learning API ------------------------------------------------------------

def test_question_can_be_created_and_answered(csrf_client, context):
    created = csrf_client.post("/api/questions", json={
        "type": "multiple_choice",
        "prompt": "Wie hoch ist die Netzspannung?",
        "subject": "Elektrotechnische Grundlagen",
        "topic": "Wechselstrom",
        "payload": {"options": ["230 V", "400 V"]},
        "solution": {"correct_indices": [0], "max_points": 2.0},
    })
    assert created.status_code == 201
    question_id = created.json()["id"]

    # Indices are 0-based, so "0" selects the first option.
    graded = csrf_client.post(f"/api/questions/{question_id}/answer",
                              json={"answer": "0", "use_ai": False})
    assert graded.status_code == 200
    payload = graded.json()
    assert payload["grading"]["is_correct"] is True
    assert payload["grading"]["score"] == 2.0


def test_manual_question_with_natural_correct_key_is_gradable(csrf_client):
    """``correct`` and ``correct_index`` are accepted, not only ``correct_indices``."""

    created = csrf_client.post("/api/questions", json={
        "type": "multiple_choice",
        "prompt": "Welche Leitung hat den größeren Querschnitt?",
        "payload": {"options": ["1,5 mm²", "2,5 mm²"]},
        "solution": {"correct": [1], "max_points": 1.0},
    })
    assert created.status_code == 201
    question_id = created.json()["id"]
    graded = csrf_client.post(f"/api/questions/{question_id}/answer",
                              json={"answer": "1", "use_ai": False})
    assert graded.json()["grading"]["is_correct"] is True


def test_manual_multiple_choice_without_solution_is_rejected(csrf_client):
    """A question that could never be graded must not be stored."""

    response = csrf_client.post("/api/questions", json={
        "type": "multiple_choice",
        "prompt": "Frage ohne hinterlegte richtige Antwort",
        "payload": {"options": ["a", "b"]},
        "solution": {"max_points": 1.0},
    })
    assert response.status_code == 400
    assert "richtige Antwort" in response.json()["detail"]


def test_manual_multiple_choice_with_out_of_range_solution_is_rejected(csrf_client):
    response = csrf_client.post("/api/questions", json={
        "type": "multiple_choice",
        "prompt": "Frage mit unmöglicher richtiger Antwort",
        "payload": {"options": ["a", "b"]},
        "solution": {"correct_index": 5, "max_points": 1.0},
    })
    assert response.status_code == 400


def test_dashboard_reflects_real_counts(csrf_client, context):
    before = csrf_client.get("/api/dashboard").json()
    assert before["counts"]["questions"] == 0

    csrf_client.post("/api/questions", json={
        "type": "numeric", "prompt": "Berechne U.",
        "subject": "Elektrotechnische Grundlagen",
        "payload": {}, "solution": {"expected": 230, "unit": "V", "max_points": 1},
    })
    after = csrf_client.get("/api/dashboard").json()
    assert after["counts"]["questions"] == 1


def test_exam_endpoint_requires_questions(csrf_client, context):
    response = csrf_client.post("/api/exams", json={"time_limit_minutes": 10})
    assert response.status_code == 400
    assert "Aufgaben" in response.json()["detail"]


# -- knowledge base ----------------------------------------------------------

def test_knowledge_search_endpoint(client, context):
    context.repo.upsert_knowledge(
        title="Drehstrom", content="Drehstrom nutzt drei um 120 Grad versetzte "
        "Außenleiter.", subject="Drehstrom", topic="Grundlagen",
        source_label="notizen.pdf", page_number=3,
    )
    response = client.get("/api/knowledge/search", params={"q": "Drehstrom"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["items"][0]["source_label"] == "notizen.pdf"


def test_knowledge_update_is_validated(csrf_client, context):
    item_id, _ = context.repo.upsert_knowledge(
        title="Test", content="Inhalt", subject="S", topic="T",
        source_label="x.pdf", page_number=1,
    )
    response = csrf_client.patch(f"/api/knowledge/{item_id}",
                                 json={"content": "Neuer Inhalt"})
    assert response.status_code == 200
    assert context.repo.get_knowledge(item_id)["content"] == "Neuer Inhalt"


# -- drawing API -------------------------------------------------------------

def test_drawing_library_endpoint(client):
    response = client.get("/api/drawing/library")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) >= 25
    assert payload["categories"]


def test_drawing_save_load_and_validate(csrf_client):
    document = {
        "components": [{"id": "C1", "symbol": "resistor", "x": 2, "y": 2}],
        "connections": [],
    }
    created = csrf_client.post("/api/drawing/drawings",
                               json={"name": "Testplan", "data": document})
    assert created.status_code == 201
    drawing_id = created.json()["id"]

    loaded = csrf_client.get(f"/api/drawing/drawings/{drawing_id}")
    assert loaded.status_code == 200
    assert loaded.json()["name"] == "Testplan"
    assert loaded.json()["data"]["components"][0]["id"] == "C1"

    validated = csrf_client.post("/api/drawing/validate", json={"data": document})
    assert validated.status_code == 200
    assert "issues" in validated.json()


def test_drawing_export_svg_and_pdf(csrf_client):
    document = {"components": [{"id": "C1", "symbol": "lamp", "x": 2, "y": 2}],
                "connections": []}
    svg = csrf_client.post("/api/drawing/export/svg", json={"data": document})
    assert svg.status_code == 200
    assert svg.content.startswith(b"<?xml")
    assert svg.headers["content-type"].startswith("image/svg")

    pdf = csrf_client.post("/api/drawing/export/pdf", json={"data": document})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")


# -- backups -----------------------------------------------------------------

def test_backup_create_list_and_verify(csrf_client, context):
    created = csrf_client.post("/api/backups")
    assert created.status_code == 201
    backup_id = created.json()["id"]

    listed = csrf_client.get("/api/backups")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1

    verified = csrf_client.post(f"/api/backups/{backup_id}/verify")
    assert verified.status_code == 200
    assert verified.json()["ok"] is True


# -- system status -----------------------------------------------------------

def test_system_status_reports_every_check(client):
    response = client.get("/api/system/status")
    assert response.status_code == 200
    payload = response.json()
    names = {check["name"] for check in payload["checks"]}
    for expected in ("Backend", "Website", "Datenbank", "Speicher", "RAM", "CPU",
                     "Ollama", "Gemini", "Aufgaben", "Backups"):
        assert expected in names, f"health check {expected} missing"
    assert payload["overall"] in ("ok", "warning", "error", "critical")


def test_system_status_marks_ollama_down_without_ollama(client):
    payload = client.get("/api/system/status").json()
    ollama = next(c for c in payload["checks"] if c["name"] == "Ollama")
    # No Ollama in the test environment: it must be reported as a warning or
    # error with concrete guidance, never silently as "ok".
    assert ollama["status"] in ("warning", "error", "disabled")


# -- ingress path handling ---------------------------------------------------

def test_index_page_renders_without_ingress_header(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "ElektroCoach" in response.text
    # Without an ingress header the base path must be empty.
    assert "{{ ingress_base }}" not in response.text


def test_index_page_uses_the_ingress_prefix(client):
    response = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
    assert response.status_code == 200
    assert "/api/hassio_ingress/abc123" in response.text
    assert "{{ ingress_base }}" not in response.text


def test_api_works_while_the_ingress_header_is_present(client):
    """Ingress strips the prefix before forwarding; the app is served from root."""

    response = client.get("/api/session",
                          headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
    assert response.status_code == 200
    assert response.json()["csrf_token"]
    assert response.json()["ingress_path"] == "/api/hassio_ingress/abc123"


# -- error handling ----------------------------------------------------------

def test_unhandled_errors_are_reported_cleanly(context, monkeypatch):
    """An internal error returns a short German message, never a traceback."""

    from fastapi.testclient import TestClient

    from elektrocoach.backend.main import create_app

    def boom(*args, **kwargs):
        raise RuntimeError("interner Fehler mit Stacktrace")

    monkeypatch.setattr(context.repo, "list_questions", boom)
    app = create_app(context)
    # Let the server-side handler run instead of re-raising in the test client.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/questions")
    assert response.status_code == 500
    detail = response.json()["detail"]
    # The client must get a short German message, not a traceback.
    assert "Stacktrace" not in detail
    assert "Traceback" not in detail
    assert "Fehler" in detail or "Problem" in detail
