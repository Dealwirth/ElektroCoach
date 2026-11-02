# AGENTS.md — Repository-Wissen für ElektroCoach

Diese Datei ist die dauerhafte Wissensablage für die Arbeit an diesem
Repository. Sie wird bei jeder Sitzung mitgeladen.

## Projekt in einem Satz

ElektroCoach ist ein Home-Assistant-Add-on (Repository mit zwei Add-ons) für
die Ausbildung zum Elektroniker für Energie- und Gebäudetechnik: FastAPI-Backend,
SQLite/FTS5-Datenbank, statische Vanilla-JS-Oberfläche, KI-Dispatcher für
lokales Ollama und Google Gemini (Free Tier).

## Verzeichnisstruktur

```
elektrocoach-repository/
├── repository.yaml          # Add-on-Store-Metadaten
├── README.md                # Projektübersicht
├── docs/                    # ausführliche Anleitungen (deutsch)
├── elektrocoach/            # Haupt-Add-on
│   ├── config.yaml          # Add-on-Optionen + schema (muss synchron bleiben)
│   ├── Dockerfile           # ARG BUILD_FROM ist Pflicht
│   ├── build.yaml           # Basis-Images je Architektur (aarch64, amd64)
│   ├── run.sh               # Einstiegspunkt, startet uvicorn
│   ├── DOCS.md              # Add-on-Hilfe in Home Assistant
│   ├── apparmor.txt         # Sicherheitsprofil
│   ├── icon.png, logo.png
│   └── elektrocoach/        # Python-Paket
│       ├── backend/         # FastAPI, Router, Config, Security, WebSocket
│       ├── database/        # SQLite, Migrationen, Repository
│       ├── ai/              # Dispatcher, Ollama- und Gemini-Client
│       ├── documents/       # Import, OCR, Extraktion, Taxonomie
│       ├── learning/        # Aufgaben, Bewertung, SRS, Prüfungen, Rechnen
│       ├── drawing/         # Schaltplanmodell, Symbole, Export
│       ├── backup/          # Sicherung und Wiederherstellung
│       ├── jobs/            # Hintergrund-Worker
│       ├── monitoring/      # Diagnose, Health, Reparatur
│       ├── integrations/    # Home-Assistant-Anbindung
│       ├── frontend/        # index.html + assets (Vanilla JS, kein Build)
│       └── tests/           # pytest
└── ollama/                  # zweites Add-on: lokaler Ollama-Server
```

## Entwicklungsbefehle

Virtuelle Umgebung: `/workspace/project/.venv/bin/python`

```bash
cd elektrocoach-repository/elektrocoach

# Tests (139 Tests, ca. 4 s)
/workspace/project/.venv/bin/python -m pytest elektrocoach/tests -q

# Nur ein Modul
/workspace/project/.venv/bin/python -m pytest elektrocoach/tests/test_backup.py -q

# Image für lokale Tests bauen (amd64). BUILD_FROM ist Pflicht, weil das
# Dockerfile `FROM ${BUILD_FROM}` verwendet und build.yaml nur vom Supervisor
# gelesen wird.
sudo -n docker build \
  --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 \
  -t elektrocoach:test -f Dockerfile .

# Container starten (Ingress-Port 8099 auf 18099)
mkdir -p /tmp/ecrun/data /tmp/ecrun/share
# options.json nach /tmp/ecrun/data/options.json schreiben
sudo -n docker run -d --name ec-test -p 18099:8099 \
  -v /tmp/ecrun/data:/data -v /tmp/ecrun/share:/share elektrocoach:test
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18099/healthz
```

## Wichtige Konventionen

- **Sprache**: Alle benutzersichtbaren Texte, Meldungen, Protokolle und
  Dokumentation sind auf Deutsch. Code-Bezeichner und Kommentare ebenfalls
  deutsch/englisch gemischt wie im Bestand; neue Kommentare auf Deutsch.
- **Keine vorgetäuschten Funktionen**: Jede Option in `config.yaml` muss
  tatsächlich gelesen und angewendet werden. Kein UI-Element ohne Funktion.
- **Keine kostenpflichtigen Dienste**: Nur Ollama (lokal) und Gemini Free Tier.
  Bei erschöpftem Kontingent wird pausiert, nie auf einen bezahlten Tarif
  gewechselt.
- **Ingress**: Das Frontend muss unter einem dynamischen Pfad funktionieren.
  `index.html` setzt ein `<base>`-Tag; API-Aufrufe sind relativ. WebSockets
  nutzen den Ingress-Pfad mit.
- **Optionen**: `config.yaml` (`options` + `schema`) ist die Quelle der
  Wahrheit. Neue Optionen dort ergänzen und in `backend/config.py` auswerten.
- **Migrationen**: Datenbankschema nur über `database/migrations.py` ändern,
  versioniert und rückwärtskompatibel.
- **Tests**: Keine Mocks für Kernlogik. Reale Codepfade testen (echte SQLite-DB,
  temporäre Verzeichnisse).

## Erkenntnisse und Fallstricke

- **Backup-Register liegt NICHT in der Datenbank.** Die Liste der Sicherungen
  steht als `index.json` im Backup-Ordner (Standard
  `/share/elektrocoach/backups`). Grund: Eine Wiederherstellung ersetzt die
  Datenbank. Läge das Register darin, wäre nach dem Zurückspielen die gesamte
  Sicherungshistorie gelöscht und die automatische Sicherung vor der
  Wiederherstellung unsichtbar — der Nutzer könnte eine Wiederherstellung nicht
  mehr rückgängig machen. Die Tabelle `backups` in der Datenbank ist nur eine
  Spiegelung für Abfragen.
- **Dateinamen brauchen Mikrosekunden.** Mit Sekundenauflösung bekamen
  Sicherungen im selben Sekundenbruchteil denselben Namen und überschrieben
  einander. Außerdem wurde ein Name nach dem Löschen wieder frei und konnte
  erneut vergeben werden. Format:
  `elektrocoach-backup-<YYYYmmddTHHMMSSffffff>-<kind>.zip`.
- **Backup-IDs sind stabil.** `BackupService._normalize` vergibt IDs nie neu
  (die ID steckt im Dateinamen). Früher wurden IDs beim Sortieren neu
  durchnummeriert, wodurch eine neue Sicherung eine bestehende Datei
  überschreiben konnte.
- **Aufräumen darf die laufende Wiederherstellung nicht löschen.** `_prune`
  bekommt eine `protect`-Menge. Beim Anlegen der Sicherung vor einer
  Wiederherstellung wird die Quelldatei geschützt, sonst löscht das Aufräumen
  die Datei mitten im Vorgang (früher: roher `[Errno 2]`-Fehler für den Nutzer).
- **Nach einer Wiederherstellung müssen ALLE Threads ihre
  Datenbankverbindung verwerfen.** `Database` hält pro Thread eine eigene
  SQLite-Verbindung (`threading.local`). Eine Wiederherstellung ersetzt die
  Datei auf der Platte. Threads, die ihre Verbindung behalten, lesen und
  schreiben weiter die *alte*, bereits gelöschte Datei. Symptom: Der
  Hintergrund-Worker hat nach einer Wiederherstellung keine Jobs mehr
  verarbeitet, bis das Add-on neu gestartet wurde. Lösung:
  `Database.invalidate_connections()` erhöht einen Generationszähler; jede
  Verbindung wird beim nächsten Zugriff neu aufgebaut, wenn ihre Generation
  nicht mehr passt. Eine Verbindung darf nur der eigene Thread schließen,
  deshalb der Umweg über den Zähler statt eines direkten Schließens.
- **Frage-Bewertung akzeptiert mehrere Schlüssel.** `correct_indices` (kanonisch),
  `correct` und `correct_index` werden in `learning/grading.correct_indices`
  gelesen. Beim manuellen Anlegen einer Auswahlaufgabe prüft
  `api_learning._require_gradable_solution`, dass überhaupt eine gültige Lösung
  hinterlegt ist. Ohne diese Prüfung ließ sich eine Frage speichern, die nie
  richtig gewertet werden konnte und nur „Richtig gewesen wäre: .“ ausgab.
- **API-Feldnamen** (häufige Stolperfalle beim Testen mit curl):
  Antworten an `/api/questions/{id}/answer` erwarten `{"answer": "<text>"}`
  (String, z. B. `"0"` oder `"[0]"`), nicht `{"selected": [...]}`. Der
  Aufgabentyp heißt `freetext`, nicht `free_text`. Der Editor-Prefix ist
  `/api/drawing/...`. Die Wiederherstellung bestätigt man mit dem
  **Query-Parameter** `?confirmed=true`, nicht im Body. Die Lernplan-Route ist
  `/api/learning/plan`, die Listenantwort hat je Endpunkt andere Felder
  (`items`, `backups` bzw. `count`).
- **Ollama-Optionen** in `ollama/config.yaml` werden in `ollama/run.sh` über
  eine `read_opt`-Funktion gelesen. Das Basis-Image hat weder `python` noch
  `jq`, deshalb wird mit `sed` aus der einzeiligen `options.json` gelesen.
- **Add-on-Store-Metadaten**: `repository.yaml` braucht `name`, `url`,
  `maintainer`. Jedes Add-on braucht `config.yaml` mit `slug`, `version`,
  `arch`, `ingress`.

## Repository und Veröffentlichung

- **GitHub-Ziel**: `https://github.com/Dealwirth/ElektroCoach`
  (Standardbranch `main`). Das Repository hat nur einen Stub-Commit; die Arbeit
  liegt auf dem Branch `elektrocoach-addon` und wird über einen Pull Request
  eingebracht. **Nie direkt auf `main` pushen.**
- **Lokales Git**: Das Projektverzeichnis
  `elektrocoach-repository/` ist ein eigenes Git-Repository (Branch `main`
  bzw. `elektrocoach-addon`). Das übergeordnete `/workspace/project` hat ein
  eigenes, leeres Repository — nicht verwechseln.
- **Remote-URL** enthält das Token:
  `git remote set-url origin https://${GITHUB_TOKEN}@github.com/Dealwirth/ElektroCoach.git`
- Das Token des Agenten darf **keine** Repositories anlegen
  („Resource not accessible by integration“). Vorhandene Repositories mit
  Push-Recht funktionieren.

## Offene Punkte

- ARM64-Image wurde noch nicht auf echter Hardware (Raspberry Pi 4) gebaut und
  getestet. Der amd64-Build läuft lokal (Image gebaut, gestartet, OCR geprüft);
  ein Cross-Build für `linux/arm64` ist in dieser Umgebung nicht möglich, weil
  die QEMU/binfmt-Registrierung gesperrt ist
  (`/proc/sys/fs/binfmt_misc/register`: „Read-only file system“).
- Betrieb über den Home-Assistant-Add-on-Store, Ingress, echte HA-Sensoren und
  Benachrichtigungen sowie echte Ollama-/Gemini-Konten sind nicht praktisch
  getestet. Siehe `docs/TESTBERICHT.md`, Abschnitt 7.
