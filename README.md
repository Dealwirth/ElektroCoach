# ElektroCoach

KI-Lernplattform für die Abschlussprüfung als **Elektroniker für Energie- und
Gebäudetechnik**. Läuft als Home-Assistant-Add-on auf einem Raspberry Pi 4
(8 GB) mit Home Assistant OS und ist über den Home-Assistant-Ingress im Browser
erreichbar.

Die Anwendung arbeitet **offline zuerst**: lokale KI über Ollama, optional
Google Gemini im kostenlosen Kontingent als Cloud-Fallback. Ohne KI läuft die
Plattform weiter — dann werden Aufgaben aus den eigenen Unterlagen erzeugt.

## Funktionsumfang

| Bereich | Funktion |
| --- | --- |
| Import | PDF, Bilder, Scans, Samsung-Notes-Exporte (`.sdoc`, `.snote`, `.pdf`), Sammlungsimport, OCR (Tesseract, `deu+eng+equ`), Handschrift, Formeln, Tabellen, Schaltplanbilder |
| Bibliothek | Dokumente, Seiten, Volltextsuche (SQLite FTS5), Seitenzuordnung, unsichere Erkennung gekennzeichnet, Dublettenerkennung |
| Wissensbasis | Themen automatisch gruppieren, fehlende Prüfungsthemen erkennen und ergänzen, Quellenverknüpfung |
| KI | Zwei Dienste: Ollama (lokal, kostenlos) und Gemini (Cloud, kostenloses Kontingent). **Pro Anfrage wählbar** (Auto/Ollama/Gemini). Lokales Modell darf auf Wunsch kontrolliert im Internet nachschlagen – nur verlässliche Quellen, immer mit Quellenangabe |
| Lernen | Multiple-Choice, offene Fragen, Rechenaufgaben mit Rechenweg, Verständnisfragen, Praxisaufgaben; automatische Bewertung mit Teilpunkten und Erklärungen; **Antworten auch handschriftlich mit Stift** |
| Lernplan | Spaced Repetition (SM-2), Stärken/Schwächen, individuelle Ziele, adaptive Schwierigkeit, fällige Wiederholungen |
| Prüfung | Simulation mit Zeitlimit, drei Presets, Punkteverteilung, Auswertung, Vergleich mehrerer Durchläufe |
| Schaltplan | Editor nach IEC-Konventionen: 20-px-Raster, 24 Symbole, Leitungen mit echten Anschlusspunkten, Undo/Redo, Kopieren, Rotation, SVG/JSON/PDF-Export |
| Home Assistant | MQTT-Discovery-Sensoren, Benachrichtigungen, Ingress-Oberfläche |
| System | Backup/Wiederherstellung, Speicherplatzüberwachung, Audit-Log, verschlüsselte Geheimnisse |

## Architektur

```
elektrocoach/
├── config.yaml            Home-Assistant-Add-on-Manifest (Ingress, Optionen, Schema)
├── Dockerfile             Multi-Stage: Node-Build der Oberfläche → HA-Basis-Image
├── run.sh                 Startskript (Uvicorn, Ingress-Port 8099)
├── app/
│   ├── main.py            FastAPI-App, Lifespan, SPA-Auslieferung
│   ├── config.py          Optionen: Defaults, /data/options.json, Laufzeit-Overrides
│   ├── db.py              SQLite (WAL, FTS5), Migrationen, Backups
│   ├── security.py        Verschlüsselung der Geheimnisse (Schlüssel in /data)
│   ├── routers/           HTTP-API (system, imports, learning_api, exams, schematics, ai_api)
│   ├── services/          OCR, Samsung Notes, KI-Router, Ollama, Gemini, Lernen, SRS, Prüfung, Schaltplan, HA, Backup
│   └── workers/           Import-Worker (unterbrechbar, ressourcenschonend)
└── frontend/              React + TypeScript + Tailwind (Vite), helle Oberfläche
```

Backend, Oberfläche, KI und Datenbank sind getrennt. Die Oberfläche ist eine
statische SPA; das Backend liefert sie aus und stellt die JSON-API bereit.
Alle Pfade sind relativ, damit die App hinter dem wechselnden Ingress-Pfad
funktioniert.

## Installation auf dem Raspberry Pi

Vollständige Anleitung: [docs/INSTALLATION.md](docs/INSTALLATION.md).

Kurzfassung:

1. Home Assistant → **Einstellungen → Add-ons → Add-on-Store**.
2. Oben rechts **⋮ → Repositories** → `https://github.com/Dealwirth/ElektroCoach` hinzufügen.
3. **ElektroCoach** installieren, starten, **In der Seitenleiste anzeigen** aktivieren.
4. Optional Gemini-Schlüssel und Ollama in den Add-on-Optionen hinterlegen.

## Dokumentation

| Thema | Datei |
| --- | --- |
| Installation und Einrichtung | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| Aufzeichnungen importieren (Samsung Notes) | [docs/IMPORT_SAMSUNG_NOTES.md](docs/IMPORT_SAMSUNG_NOTES.md) |
| Ollama und Gemini einrichten | [docs/KI_EINRICHTUNG.md](docs/KI_EINRICHTUNG.md) |
| Backup und Wiederherstellung | [docs/BACKUP_WIEDERHERSTELLUNG.md](docs/BACKUP_WIEDERHERSTELLUNG.md) |
| Testbericht | [docs/TESTBERICHT.md](docs/TESTBERICHT.md) |
| Bekannte Einschränkungen | [docs/EINSCHRAENKUNGEN.md](docs/EINSCHRAENKUNGEN.md) |
| SSD-Migration | [docs/SSD_MIGRATION.md](docs/SSD_MIGRATION.md) |
| Änderungen je Version | [CHANGELOG.md](CHANGELOG.md) |

## Entwicklung

```bash
# Backend-Abhängigkeiten
python3 -m venv .venv && .venv/bin/pip install -r elektrocoach/requirements.txt

# Tests
.venv/bin/python -m pytest

# Oberfläche bauen
cd elektrocoach/frontend && npm ci && npm run build

# Add-on-Image bauen (Ordner elektrocoach/ ist der Build-Kontext)
docker build -t elektrocoach:test elektrocoach
```

## Lizenz

MIT. Nutzung auf eigenes Risiko. Die Prüfungssimulation gibt eine unverbindliche
Orientierung und ersetzt keine offizielle Prüfungsordnung.
