"""Tests der SPA-Auslieferung: <base>-Element fuer den Ingress.

Der Browser liest <base> schon beim Vorabladen. Deshalb muss der Basispfad
serverseitig im Kopf stehen, nicht erst per JavaScript gesetzt werden. Sonst
laedt Chromium auf verschachtelten Seiten (z. B. /schaltplan/editor/x) die
Dateien in ./assets gegen den falschen Pfad.
"""

from __future__ import annotations

import pathlib

import pytest

from app import main as main_module

INDEX_HTML = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <title>ElektroCoach</title>
    <!-- Ein Basiselement wird vom Backend eingesetzt. -->
    <script type="module" crossorigin src="./assets/index-abc.js"></script>
    <link rel="stylesheet" crossorigin href="./assets/index-abc.css" />
  </head>
  <body><div id="root"></div></body>
</html>
"""


def _head(html: str) -> str:
    return html.split("</head>", 1)[0]


def _base_href_of(html: str) -> str | None:
    import re

    match = re.search(r"<base\s+href=\"([^\"]*)\"\s*/?>", html, re.IGNORECASE)
    return match.group(1) if match else None


@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(main_module, "STATIC_DIR", pathlib.Path(tmp_path))
    return tmp_path


@pytest.fixture
def client():
    """Client ohne Lebenszyklus (kein Start/Stop der Anwendung).

    Die Auslieferung der Oberflaeche braucht keine Datenbank und keine Worker.
    Der Lebenszyklus wird bewusst nicht gestartet: andere Tests ersetzen die
    Datenbankdatei (Wiederherstellung), danach wuerde ein Abschluss-Checkpoint
    auf der alten Verbindung fehlschlagen.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_base_href_direkt(client, static_dir):
    response = client.get("/")
    assert response.status_code == 200
    assert _base_href_of(response.text) == "/"


def test_base_href_auf_verschachtelter_seite(client, static_dir):
    response = client.get("/schaltplan/editor/abc123")
    assert response.status_code == 200
    assert _base_href_of(response.text) == "/"
    assert "./assets/index-abc.css" in response.text


def test_base_href_hinter_ingress(client, static_dir):
    # Home Assistant entfernt das Ingress-Praefix aus dem Pfad und uebergibt es
    # im Kopf X-Ingress-Path.
    response = client.get(
        "/schaltplan/editor/abc",
        headers={"X-Ingress-Path": "/api/hassio_ingress/TOKEN"},
    )
    assert response.status_code == 200
    assert _base_href_of(response.text) == "/api/hassio_ingress/TOKEN/"


def test_base_href_landet_im_head_und_nicht_im_kommentar(client, static_dir):
    """Regression: ein <base> im HTML-Kommentar darf nicht ersetzt werden."""
    response = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/X"})
    head = _head(response.text)
    assert "<base href=\"/api/hassio_ingress/X/\" />" in head
    assert head.count("<base ") == 1


def test_base_href_ersetzt_vorhandenes_base(client, static_dir):
    (static_dir / "index.html").write_text(
        INDEX_HTML.replace("<meta charset=\"UTF-8\" />", '<base href="/falsch/" />'),
        encoding="utf-8",
    )
    response = client.get(
        "/einstellungen", headers={"X-Ingress-Path": "/api/hassio_ingress/NEU"}
    )
    assert response.status_code == 200
    assert _base_href_of(response.text) == "/api/hassio_ingress/NEU/"
    assert "/falsch/" not in response.text
    # Es darf nur ein <base>-Element geben.
    assert response.text.count("<base ") == 1


def test_asset_datei_wird_ausgeliefert(client, static_dir):
    (static_dir / "assets" / "index-abc.css").write_text("body{}", encoding="utf-8")
    response = client.get("/assets/index-abc.css")
    assert response.status_code == 200
    assert response.text == "body{}"


def test_ohne_build_meldet_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "STATIC_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 503
