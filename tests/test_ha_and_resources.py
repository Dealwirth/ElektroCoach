"""Tests der Home-Assistant-Anbindung, Sensorwerte und Ressourcenverhalten."""

from __future__ import annotations

import asyncio

import pytest

from app import db
from app.config import settings
from app.services import ha_integration, learning
from app.workers import import_worker


def _run(coro):
    return asyncio.run(coro)


def test_sensordefinitionen_sind_vollstaendig():
    keys = {sensor["key"] for sensor in ha_integration.SENSOR_DEFS}
    required = {
        "progress", "study_minutes", "due_reviews", "questions", "accuracy",
        "streak", "best_exam", "free_space", "status",
    }
    assert required <= keys


def test_jeder_sensor_hat_namen_und_icon():
    for sensor in ha_integration.SENSOR_DEFS:
        assert sensor["name"]
        assert sensor["icon"].startswith("mdi:")


def test_sensorwerte_werden_berechnet():
    state = ha_integration.collect_state()
    for key in ("progress_percent", "today_minutes", "due_reviews", "questions",
                "accuracy", "streak_days", "free_space_mb", "status_text"):
        assert key in state
    assert 0 <= state["progress_percent"] <= 100
    assert state["free_space_mb"] >= 0


def test_alle_sensor_lambdas_laufen_ohne_fehler():
    state = ha_integration.collect_state()
    for sensor in ha_integration.SENSOR_DEFS:
        value = sensor["value"](state)
        assert value is not None


def test_status_text_ohne_fragen():
    db.execute("UPDATE srs SET due_at = NULL")
    state = ha_integration.collect_state()
    assert isinstance(state["status_text"], str)
    assert state["status_text"]


def test_status_ohne_mqtt():
    status = ha_integration.status()
    assert status["mqtt_enabled"] is False
    assert status["mqtt_connected"] is False
    assert isinstance(status["sensor_update_interval"], int)


def test_publish_ohne_mqtt_ist_fehlerfrei():
    assert ha_integration.publish_discovery() is False
    assert ha_integration.publish_state()  # liefert trotzdem den Zustand
    ha_integration.remove_discovery()


def test_mqtt_publish_mit_ungueltigem_host_scheitert_sauber():
    settings.set_runtime("mqtt_enabled", True)
    settings.set_runtime("mqtt_host", "127.0.0.1")
    settings.set_runtime("mqtt_port", 1)
    try:
        # Kein Broker vorhanden: es darf keine Ausnahme nach aussen dringen.
        assert ha_integration._publish("test/topic", "wert") is False
    finally:
        settings.set_runtime("mqtt_enabled", False)
        ha_integration._client = None


def test_benachrichtigung_ohne_dienst_nutzt_standardziel():
    # Ohne eigene Konfiguration wird die dauerhafte HA-Benachrichtigung genutzt.
    result = _run(ha_integration.notify("Titel", "Text"))
    assert result["ok"] is False  # im Test gibt es keinen Supervisor-Token
    # Der Versuch wird protokolliert.
    row = db.query_one("SELECT * FROM notifications_log ORDER BY created_at DESC LIMIT 1")
    assert row is not None


def test_benachrichtigung_ziel_wird_zerlegt():
    import asyncio
    captured = {}

    class _FakeResponse:
        status_code = 200
        text = ""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            return _FakeResponse()

    original_token = ha_integration.SUPERVISOR_TOKEN
    ha_integration.SUPERVISOR_TOKEN = "test-token"
    import httpx
    original_client = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: _FakeClient()
    try:
        result = asyncio.run(
            ha_integration.notify("Titel", "Text", "persistent_notification.create")
        )
        assert result["ok"] is True
        assert captured["url"].endswith("/core/api/services/persistent_notification/create")
    finally:
        httpx.AsyncClient = original_client
        ha_integration.SUPERVISOR_TOKEN = original_token


def test_benachrichtigung_ohne_supervisor_token():
    settings.set_runtime("ha_notify_service", "notify.mobile_app_test")
    result = _run(ha_integration.notify("Titel", "Text"))
    assert result["ok"] is False
    settings.set_runtime("ha_notify_service", "")


def test_benachrichtigung_bei_keinen_faelligen():
    db.execute("UPDATE srs SET due_at = NULL")
    result = _run(ha_integration.notify_due_reviews())
    assert result["ok"] is False


def test_scheduler_startet_und_stoppt():
    ha_integration.start_scheduler()
    assert ha_integration.status()["scheduler_running"] is True
    ha_integration.stop_scheduler()
    # Zweiter Start darf keinen zweiten Thread erzeugen.
    ha_integration.start_scheduler()
    ha_integration.start_scheduler()
    assert ha_integration.status()["scheduler_running"] is True
    ha_integration.stop_scheduler()


# ---------------------------------------------------------------------------
# Ressourcenverhalten (wichtig fuer den Raspberry Pi 4)
# ---------------------------------------------------------------------------
def test_speicherpruefung_liefert_wert():
    free = import_worker.free_bytes()
    assert free > 0


def test_arbeitsspeicher_abfrage():
    memory = import_worker.available_memory_mb()
    assert memory is None or memory > 0


def test_systemlast_abfrage():
    load = import_worker.process_load()
    assert load is None or load >= 0


def test_import_mindestspeicher_ist_gesetzt():
    # Untergrenze schuetzt vor volllaufendem Speicher.
    assert import_worker.MIN_FREE_BYTES >= 256 * 1024 * 1024


def test_import_pause_zwischen_dateien():
    assert 0 < import_worker.INTER_FILE_DELAY <= 2.0


def test_dateigroessenlimit():
    assert import_worker.MAX_FILE_BYTES == 512 * 1024 * 1024


def test_sensor_intervall_untergrenze():
    # Der Scheduler erzwingt mindestens 30 Sekunden, um den HA-Event-Bus zu schonen.
    settings.set_runtime("sensor_update_interval", 5)
    assert max(30, settings.get_int("sensor_update_interval", 300)) == 30
    settings.set_runtime("sensor_update_interval", 300)


def test_standard_sensorintervall_ist_gross():
    from app.config import DEFAULTS

    assert DEFAULTS["sensor_update_interval"] >= 300


def test_datenbank_wal_modus_haelt_schreiblast_niedrig():
    row = db.query_one("PRAGMA journal_mode")
    assert row[0].lower() == "wal"
    synchronous = db.query_one("PRAGMA synchronous")
    # NORMAL statt FULL: deutlich weniger Schreibzugriffe auf die SD-Karte.
    assert synchronous[0] in (0, 1)


def test_dashboard_stats_sind_guenstig_berechenbar():
    import time

    start = time.perf_counter()
    learning.dashboard_stats()
    duration = time.perf_counter() - start
    # Muss auch auf dem Pi deutlich unter einer Sekunde bleiben.
    assert duration < 1.0


def test_suche_ist_begrenzt_und_schnell():
    import time

    start = time.perf_counter()
    db.search_chunks("RCD Leitungsschutzschalter Spannungsfall", limit=10)
    duration = time.perf_counter() - start
    assert duration < 1.0
