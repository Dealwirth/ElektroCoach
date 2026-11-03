"""pytest-Konfiguration: isoliertes Datenverzeichnis, asyncio-Modus."""

import os
import pathlib
import sys
import tempfile

TMP_DIR = tempfile.mkdtemp(prefix="elektrocoach-tests-")
os.environ["ELEKTROCOACH_DATA"] = TMP_DIR
os.environ.pop("ELEKTROCOACH_GEMINI_API_KEY", None)
os.environ.pop("SUPERVISOR_TOKEN", None)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "elektrocoach"))

import pytest  # noqa: E402

from app import db  # noqa: E402
from app.services import learning  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def initialised_database():
    db.init_db()
    learning.ensure_default_topics()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_text() -> str:
    return (
        "Der Leitungsschutzschalter schuetzt die Leitung vor Ueberlast und Kurzschluss.\n\n"
        "Der Fehlerstrom-Schutzschalter (RCD) mit 30 mA Bemessungsdifferenzstrom schuetzt "
        "Personen bei indirektem Beruehren.\n\n"
        "Der Spannungsfall wird mit der Formel U = (2 * l * I * cos phi) / (kappa * A) "
        "berechnet. Fuer Drehstrom gilt die dreifache Laenge.\n\n"
        "Der Schutzleiter muss niederohmig mit dem Potentialausgleich verbunden sein."
    )
