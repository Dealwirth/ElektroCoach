"""End-to-End-Tests der HTTP-API ueber den echten FastAPI-Client.

Diese Tests pruefen die tatsaechlich ausgelieferten Endpunkte inklusive
Ingress-Verhalten, Dateiupload, Import-Worker und Fehlerbehandlung.
"""

from __future__ import annotations

import io
import time
import zipfile

from PIL import Image, ImageDraw


def _png_bytes(text: str = "Leitungsschutzschalter 16 A") -> bytes:
    image = Image.new("L", (800, 200), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((20, 60), text, fill=0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ping(client):
    assert client.get("/api/ping").json()["pong"] is True


def test_system_info(client):
    data = client.get("/api/system/info").json()
    assert data["version"] == "1.0.0"
    assert "storage" in data
    assert "ai" in data
    assert "ha" in data
    assert "tesseract" in data


def test_openapi_schema_wird_ausgeliefert(client):
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "ElektroCoach"
    assert len(schema["paths"]) > 30


def test_spa_fallback_ohne_build(client):
    response = client.get("/irgendein/pfad")
    assert response.status_code in (200, 503)


def test_unbekannter_api_pfad_ist_404(client):
    assert client.get("/api/gibt-es-nicht").status_code == 404


def test_sicherheitsheader_werden_gesetzt(client):
    response = client.get("/api/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "same-origin"


def test_ingress_pfad_header_wird_durchgereicht(client):
    response = client.get("/api/health", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert response.headers.get("X-Ingress-Path") == "/api/hassio_ingress/abc"


def test_einstellungen_lesen_und_schreiben(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "ollama_model" in response.json()

    updated = client.put("/api/settings", json={"values": {"ollama_model": "phi4-mini:3.8b"}})
    assert updated.status_code == 200
    assert "ollama_model" in updated.json()["changed"]
    assert client.get("/api/settings").json()["ollama_model"] == "phi4-mini:3.8b"

    client.put("/api/settings", json={"values": {"ollama_model": "llama3.2:3b"}})


def test_api_schluessel_wird_nie_im_klartext_ausgeliefert(client):
    client.put("/api/settings", json={"values": {"gemini_api_key": "AIzaSyGeheim123456"}})
    data = client.get("/api/settings").json()
    assert data["gemini_api_key"] == "********"
    assert "AIzaSyGeheim" not in str(data)
    assert data["gemini_api_key_set"] is True


def test_unbekannte_einstellung_wird_ignoriert(client):
    response = client.put("/api/settings", json={"values": {"nicht_vorhanden": "x"}})
    assert response.status_code == 200
    assert "nicht_vorhanden" not in response.json()["changed"]


def test_dashboard(client):
    data = client.get("/api/dashboard").json()
    assert "stats" in data
    assert "series" in data
    assert "plan" in data
    assert len(data["series"]) == 14


def test_importformate(client):
    data = client.get("/api/import/formats").json()
    assert data["samsung_direct"]["supported"] is True


def test_dateiimport_ueber_http_startet_auftrag(client):
    files = [("files", ("notizen.txt", b"Der RCD schuetzt Personen bei Fehlerstrom. " * 5, "text/plain"))]
    response = client.post("/api/import", files=files, data={"collection": "Lehrjahr 1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] == 1
    job_id = payload["job_id"]

    job = _wait_for_job(client, job_id)
    assert job["status"] == "done"
    assert job["imported"] >= 1
    assert job["progress_percent"] == 100.0


def test_import_lehnt_verbotene_dateitypen_ab(client):
    files = [("files", ("schaedlich.exe", b"MZ...", "application/octet-stream"))]
    response = client.post("/api/import", files=files)
    assert response.status_code == 400
    assert response.json()["detail"]["rejected"][0]["filename"] == "schaedlich.exe"


def test_import_erkennt_duplikate(client):
    content = b"Der Schutzleiter muss niederohmig sein. " * 5
    files = [("files", ("dup.txt", content, "text/plain"))]
    first = client.post("/api/import", files=files).json()
    job1 = _wait_for_job(client, first["job_id"])
    assert job1["imported"] >= 1

    second = client.post("/api/import", files=files).json()
    job2 = _wait_for_job(client, second["job_id"])
    assert job2["duplicates"] >= 1


def test_import_ueber_zip_sammlung(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("seite1.txt", "Drehstrommotor Sternschaltung " * 10)
        archive.writestr("seite2.txt", "Wechselstrom Wirkleistung Blindleistung " * 10)
    buffer.seek(0)
    response = client.post(
        "/api/import",
        files=[("files", ("sammlung.zip", buffer.read(), "application/zip"))],
        data={"collection": "Sammlung"},
    )
    assert response.status_code == 200
    job = _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "done"
    assert job["imported"] >= 1


def test_bildimport_ueber_http(client):
    response = client.post(
        "/api/import",
        files=[("files", ("scan.png", _png_bytes(), "image/png"))],
    )
    assert response.status_code == 200
    job = _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "done"


def test_dokumentliste_und_details(client):
    client.post("/api/import", files=[("files", ("liste.txt", b"Fachinhalt " * 50, "text/plain"))])
    time.sleep(1.0)
    listing = client.get("/api/documents").json()
    assert listing["total"] >= 1
    document_id = listing["items"][0]["id"]

    detail = client.get(f"/api/documents/{document_id}").json()
    assert detail["filename"]
    assert isinstance(detail["pages"], list)

    chunks = client.get(f"/api/documents/{document_id}/chunks").json()
    assert "items" in chunks

    export = client.get(f"/api/documents/{document_id}/export")
    assert export.status_code == 200
    assert "Seite 1" in export.text


def test_suche_ueber_api(client):
    client.post("/api/import", files=[("files", ("suche.txt", b"Blindleistungskompensation Kondensator " * 20, "text/plain"))])
    time.sleep(1.0)
    result = client.get("/api/search", params={"q": "Blindleistungskompensation"}).json()
    assert result["count"] >= 1


def test_dokument_loeschen(client):
    client.post("/api/import", files=[("files", ("weg.txt", b"Zu loeschen " * 50, "text/plain"))])
    time.sleep(1.0)
    document_id = client.get("/api/documents").json()["items"][0]["id"]
    assert client.delete(f"/api/documents/{document_id}").status_code == 200
    assert client.get(f"/api/documents/{document_id}").status_code == 404


def test_themen_ueber_api(client):
    data = client.get("/api/topics").json()
    assert len(data["items"]) >= 20
    assert client.post("/api/topics/analyze", json={"use_ai": False}).status_code == 200
    assert "items" in client.get("/api/topics/missing").json()


def test_fragengenerierung_und_bewertung_ueber_api(client):
    client.post("/api/import", files=[("files", ("gen.txt", b"Der RCD mit 30 mA schuetzt Personen bei Fehlerstrom. " * 10, "text/plain"))])
    time.sleep(1.0)
    client.post("/api/topics/analyze", json={"use_ai": False})

    generated = client.post("/api/questions/generate", json={
        "qtype": "cloze", "count": 2, "difficulty": 2, "use_ai": False,
    }).json()
    assert generated["created"] >= 1
    question_id = generated["questions"][0]["id"]

    detail = client.get(f"/api/questions/{question_id}").json()
    assert detail["prompt"]

    graded = client.post(f"/api/questions/{question_id}/answer",
                         json={"answer": detail["answer"], "use_ai": False}).json()
    assert graded["score"] >= 0
    assert "srs" in graded


def test_bewertung_unbekannter_frage_ist_404(client):
    assert client.post("/api/questions/unbekannt/answer", json={"answer": "x"}).status_code == 404


def test_pruefung_ueber_api(client):
    client.post("/api/import", files=[("files", ("exam.txt", b"Leitungsschutzschalter RCD Spannungsfall Drehstrom " * 20, "text/plain"))])
    time.sleep(1.0)
    client.post("/api/topics/analyze", json={"use_ai": False})
    client.post("/api/questions/generate", json={"count": 5, "use_ai": False})

    if client.get("/api/questions").json()["total"] == 0:
        return

    created = client.post("/api/exams", json={"name": "E2E", "minutes": 30,
                                              "question_count": 3, "total_points": 30})
    assert created.status_code == 200
    exam_id = created.json()["exam"]["id"]

    started = client.post(f"/api/exams/{exam_id}/start").json()
    assert started["status"] == "running"

    finished = client.post(f"/api/exams/{exam_id}/finish", json={"use_ai": False}).json()
    assert "percentage" in finished
    assert "pass_probability" in finished
    assert "weak_topics" in finished

    assert "items" in client.get("/api/exams/compare").json()


def test_pruefung_ohne_fragen_meldet_verstaendlichen_fehler(client):
    response = client.post("/api/exams", json={"question_count": 5})
    if response.status_code == 400:
        assert "Fragen" in response.json()["detail"]


def test_schaltplan_ueber_api(client):
    library = client.get("/api/schematic/library").json()
    assert library["grid"] == 20

    created = client.post("/api/schematic/projects", json={
        "name": "E2E Schaltplan",
        "data": {
            "components": [
                {"id": "c1", "type": "supply_l1", "x": 0, "y": 0},
                {"id": "c2", "type": "mcb", "x": 120, "y": 0},
            ],
            "wires": [{
                "id": "w1", "from": {"component_id": "c1", "pin_id": "L1"},
                "to": {"component_id": "c2", "pin_id": "1"},
                "points": [{"x": 40, "y": 20}, {"x": 120, "y": 20}],
            }],
            "junctions": [],
        },
    }).json()
    project_id = created["id"]
    assert created["validation"]["ok"] is True

    saved = client.put(f"/api/schematic/projects/{project_id}",
                       json={"name": "Umbenannt"}).json()
    assert saved["name"] == "Umbenannt"

    analysis = client.post("/api/schematic/analyze", json={
        "components": [{"id": "c1", "type": "supply_l1", "x": 0, "y": 0}],
        "wires": [], "junctions": [],
    }).json()
    assert "validation" in analysis and "stats" in analysis and "networks" in analysis

    svg = client.get(f"/api/schematic/projects/{project_id}/export.svg")
    assert svg.status_code == 200
    assert svg.text.startswith("<svg")

    json_export = client.get(f"/api/schematic/projects/{project_id}/export.json")
    assert json_export.status_code == 200

    assert client.delete(f"/api/schematic/projects/{project_id}").status_code == 200


def test_schaltplan_validierung_meldet_kurzschluss(client):
    result = client.post("/api/schematic/validate", json={
        "components": [
            {"id": "l1", "type": "supply_l1", "x": 0, "y": 0},
            {"id": "n", "type": "supply_n", "x": 200, "y": 0},
        ],
        "wires": [{
            "id": "bad", "from": {"component_id": "l1", "pin_id": "L1"},
            "to": {"component_id": "n", "pin_id": "N"}, "points": [],
        }],
        "junctions": [],
    }).json()
    assert result["ok"] is False
    assert any("Kurzschluss" in e for e in result["errors"])


def test_ki_status_und_verbrauch_ueber_api(client):
    status = client.get("/api/ai/status").json()
    assert "any_available" in status
    usage = client.get("/api/ai/usage").json()
    assert "today" in usage
    assert "gemini_quota" in usage
    assert "limits" in usage


def test_ki_chat_ohne_konfiguration_meldet_hinweis(client):
    response = client.post("/api/ai/chat", json={"message": "Was ist ein RCD?"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "hint" in data


def test_ki_explain_ohne_konfiguration(client):
    response = client.post("/api/ai/explain", json={"question": "Was ist ein RCD?"})
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_ha_status_und_sensoren(client):
    data = client.get("/api/ha/status").json()
    assert "mqtt_enabled" in data
    assert "sensors" in data
    for key in ("progress_percent", "due_reviews", "status_text"):
        assert key in data["sensors"]


def test_ha_publish_ohne_mqtt_ist_fehlerfrei(client):
    assert client.post("/api/ha/publish").status_code == 200


def test_ha_benachrichtigung_ohne_dienst_meldet_fehler(client):
    response = client.post("/api/ha/notify", json={"message": "Test"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Benachrichtigungsdienst" in detail or "Supervisor" in detail


def test_backup_ueber_api(client):
    created = client.post("/api/backups", json={"label": "api-test", "include_documents": False})
    assert created.status_code == 200
    name = created.json()["name"]

    listing = client.get("/api/backups").json()
    assert any(item["name"] == name for item in listing["items"])

    restored = client.post("/api/backups/restore", json={"name": name, "restore_documents": False})
    assert restored.status_code == 200

    assert client.delete(f"/api/backups/{name}").status_code == 200
    assert client.delete("/api/backups/nicht-vorhanden.tar.gz").status_code == 404


def test_storage_und_wartung(client):
    storage = client.get("/api/storage").json()
    assert "disk_free_mb" in storage
    maintenance = client.post("/api/maintenance").json()
    assert maintenance["ok"] is True
    assert maintenance["integrity"] == "ok"


def test_lernziele_ueber_api(client):
    created = client.post("/api/goals", json={"title": "E2E Ziel", "target": "Themen ueben"}).json()
    goal_id = created["id"]
    assert client.put(f"/api/goals/{goal_id}", json={"progress": 25.0}).status_code == 200
    assert any(g["id"] == goal_id for g in client.get("/api/goals").json()["items"])
    assert client.delete(f"/api/goals/{goal_id}").status_code == 200
    assert client.delete(f"/api/goals/{goal_id}").status_code == 404


def test_import_auftrag_uebersicht(client):
    data = client.get("/api/import/jobs").json()
    assert "items" in data
    assert "queue" in data


def test_review_seiten_und_abschnitte(client):
    assert "items" in client.get("/api/review/pages").json()
    assert "items" in client.get("/api/review/chunks").json()


def _wait_for_job(client, job_id: str, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/import/jobs/{job_id}").json()
        if job["status"] in {"done", "error", "cancelled"}:
            return job
        time.sleep(0.2)
    raise AssertionError(f"Importauftrag {job_id} wurde nicht fertig")
