# AGENTS.md

Repository-Wissen für die Arbeit an ElektroCoach. Kurz und praktisch halten.

## Projekt

Home-Assistant-Add-on zur Prüfungsvorbereitung Elektroniker für Energie- und
Gebäudetechnik. Offline zuerst (Ollama), optional Gemini (kostenloses
Kontingent). Ziel: Raspberry Pi 4, 8 GB, Home Assistant OS, aarch64.

* Add-on-Quelle: `elektrocoach/` (nicht `app/` auf oberster Ebene)
* Backend: FastAPI, SQLite (WAL + FTS5), Import-Worker als eigener Prozess
* Frontend: React + TypeScript + Tailwind (Vite), Build-Stufe im Dockerfile
* Tests: `pytest` (`.venv/bin/python -m pytest`), conftest legt ein
  temporäres Datenverzeichnis an

## Wichtige Befehle

```bash
# Tests
.venv/bin/python -m pytest

# Import-/Syntaxprüfung des Backends
(cd elektrocoach && ../.venv/bin/python -c "from app.main import app; print('ok')")

# config.yaml prüfen
.venv/bin/python -c "import yaml; yaml.safe_load(open('elektrocoach/config.yaml'))"
```

## Add-on auf dem Pi (b274c19d_elektrocoach)

* Zugriff über den Supervisor-Proxy per WebSocket (`supervisor/api`).
* Nach einem Push auf `main`: Store neu laden, dann
  `POST /store/addons/b274c19d_elektrocoach/update`.
* Der Store cached die Version. Wenn `version_latest` veraltet ist, hilft ein
  erneutes Hinzufügen des Repositories (`POST /store/repositories`) – das löst
  einen frischen Git-Fetch aus.
* Während ein Build läuft, meldet ein zweiter Update-Versuch
  `Another job is running for job group app_...`. Das ist kein Fehler, sondern
  ein laufender Build.
* Der Build dauert auf dem Pi mehrere Minuten (Frontend-Build + pip).

## Fallstricke (bereits einmal getreten)

1. **`SUPERVISOR_TOKEN` leer trotz `homeassistant_api: true`.**
   Die HA-Basis nutzt s6-overlay. Ein Startskript mit `#!/usr/bin/env bash`
   erbt die Container-Umgebungsvariablen **nicht**. Immer
   `#!/command/with-contenv bash` in `run.sh` verwenden. Prüfen über
   `supervisor_token` in `/api/health`.
2. **Versionsanzeige.** Eine zentrale Konstante `app.__version__` verwenden,
   nicht mehrere Literale. `ELEKTROCOACH_BUILD` und `supervisor_token` in
   `/api/health` zeigen, ob eine Installation wirklich aktuell ist.
3. **Ingress-Pfade.** Der Ingress-Pfad ist zur Build-Zeit unbekannt. Das
   `<base>`-Element muss **serverseitig** in den Kopf der ausgelieferten Seite
   (`app/main.py`, `_base_href` aus dem Kopf `X-Ingress-Path`). Ein zur Laufzeit
   per JavaScript gesetztes `<base>` kommt für den Preload-Scanner des Browsers
   zu spät: Chromium lädt `assets/...` auf verschachtelten Seiten gegen den
   falschen Pfad und verwirft das Stylesheet („MIME type text/html"). Das
   Skript in `index.html` ist nur ein Ersatz ohne Backend.
4. **`notify.*` braucht ein Ziel.** Ein konfiguriertes `notify.send_message`
   ohne Empfänger lehnt Home Assistant mit HTTP 400 ab. Standard ist
   `persistent_notification.create` (Feld leer lassen).
5. **Gemini-Modelle sind zeitweise überlastet.** `gemini-flash-latest`
   antwortet sporadisch mit HTTP 503 („high demand"). `gemini.py` sortiert ein
   solches Modell 120 s lang als `degraded` nach hinten und wechselt bei einer
   Zeitüberschreitung sofort auf das nächste Modell. Das erfolgreich genutzte
   Modell wird in den Einstellungen gemerkt. Ohne diesen Mechanismus kostet
   jede Anfrage erneut bis zu 180 s (Lesezeitlimit).
6. **`/store/reload` kann mit leerem Fehler scheitern.** Dann das Repository
   erneut hinzufügen (`POST /store/repositories`); die Meldung „already in the
   store" ist dabei zu erwarten und aktualisiert `version_latest` trotzdem.
   Ein Update-Aufruf während eines laufenden Builds meldet „Another job is
   running for job group app_…". Das ist kein Fehler.
7. **Datenbankverbindungen überleben kein Ersetzen der Datei.** Nach einer
   Wiederherstellung zeigt die Verbindung eines Threads auf die gelöschte
   Datei; jeder Schreibzugriff scheitert mit „disk I/O error". Beim Ersetzen
   immer `db.replace_database_file(...)` verwenden (erhöht den
   Verbindungsgenerationszähler). Beim Herunterfahren `db.checkpoint_quiet()`.
8. **Schaltplan-Leitungen und Zeiger.** Beim Ziehen einer Leitung den Zeiger
   einfangen (`setPointerCapture`). Sonst beendet `onPointerLeave` das Ziehen,
   bevor der Zielanschluss erreicht ist.
9. **Supervisor-Antworten sind Umschläge.** Der Supervisor liefert jede
   erfolgreiche Antwort als `{"result": "ok", "data": {...}}`, Fehler als
   `{"result": "error", "message": ...}`. Wer die Schlüssel auf der obersten
   Ebene liest (z. B. `data["addons"]`), bekommt immer eine leere Liste und
   meldet fälschlich „nicht installiert", obwohl das Add-on läuft. Antwort
   immer über `ollama_addon.unwrap()` bzw. `_request()` auspacken.
10. **Ollama-Add-on-Verwaltung braucht `hassio_api`.** Mit nur
   `homeassistant_api: true` verweigert der Supervisor den Zugriff auf
   `/addons` (403). In `config.yaml` `hassio_api: true` und
   `hassio_role: manager` setzen. Nach Änderung der Berechtigungen genügt ein
   Neustart des Add-ons, kein Neu-Build.
11. **Diagnose des Supervisor-Zugriffs.** `GET /api/system/supervisor` zeigt
   Token-Status, Rechte und die Ergebnisse der einzelnen Supervisor-Routen in
   einem Aufruf. Bei „Ollama nicht installiert" zuerst diesen Endpunkt prüfen.
12. **MQTT-Entity-Namen.** `name` im Discovery-Payload darf den Gerätenamen
    nicht erneut enthalten, sonst entsteht `sensor.elektrocoach_elektrocoach_…`.
    `name` = Sensorname, `object_id` = `unique_id` = Geräteslug + Sensorkey.
    Bereits registrierte Entitäten behalten ihre alte ID; einmalig über
    `config/entity_registry/update` umbenennen.
13. **`OLLAMA_FLASH_ATTENTION=1` bei quantisiertem KV-Cache.** Ist
    `OLLAMA_KV_CACHE_TYPE=q8_0` gesetzt und Flash-Attention aus, antwortet das
    Ollama-Add-on auf jede Anfrage mit HTTP 500.
14. **Handschrift nur mit TrOCR, nicht mit Tesseract.** Tesseract erreicht auf
    deutscher Handschrift rund 52 % Zeichenfehler, das mitgelieferte
    TrOCR-Modell (`models/trocr-de`, int8-ONNX) 0,5 %. Drei Fallstricke:
    * Das Bild **seitenverhältnis-treu** auf 384 × 384 stauchen. Mit weißem
      Rand auffüllen kostet 76 % statt 0,4 % CER.
    * Kein KV-Cache im Decoder. Er bringt 2,3× Tempo, liefert aber andere
      Tokens – Korrektheit geht vor.
    * `py3-numpy` und `py3-onnxruntime` kommen als Alpine-Pakete (keine
      musllinux-Wheels auf PyPI); `tokenizers` per `--no-deps` (nur das
      native musl-Wheel wird gebraucht).
    Status unter `handwriting` in `GET /api/system/info`.

## Git

* Nie direkt auf `main` pushen. Branch anlegen, PR öffnen, mergen.
* Merge über die asynchrone API (`PUT .../merge-async`) und den Status pollen.
* Commit-Meldungen und Kommentare auf Deutsch, sachlich.
