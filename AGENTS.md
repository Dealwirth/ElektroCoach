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
   Frontend setzt zur Laufzeit ein `<base>`-Tag (siehe `index.html`).
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

## Git

* Nie direkt auf `main` pushen. Branch anlegen, PR öffnen, mergen.
* Merge über die asynchrone API (`PUT .../merge-async`) und den Status pollen.
* Commit-Meldungen und Kommentare auf Deutsch, sachlich.
