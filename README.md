# ElektroCoach

Lernplattform für die Ausbildung zum **Elektroniker für Energie- und
Gebäudetechnik**, lauffähig als Home-Assistant-Add-on auf einem Raspberry Pi 4
(8 GB RAM, Home Assistant OS, microSD).

ElektroCoach bündelt in einer Anwendung:

- Wissensdatenbank mit Volltextsuche (SQLite + FTS5)
- Dokumentenimport (PDF, Bilder, Scans) mit OCR und Quellen-/Seitenangabe
- Lernsystem mit Multiple-Choice-, Rechen-, Zuordnungs-, Freitext- und
  Fehleranalyse-Aufgaben
- Adaptives Lernen (SM-2 Wiederholungsplaner)
- Prüfungssimulation mit Zeitlimit und Auswertung
- Schaltplan-/Zeicheneditor
- KI-Dispatcher für lokales Ollama und Google Gemini (Free Tier)
- Systemstatus, Selbstdiagnose und sichere automatische Reparaturen
- Backup und Wiederherstellung
- Home-Assistant-Sensoren und Benachrichtigungen

## Wichtiger Hinweis zum Zustand des Projekts

Dieses Repository enthält eine **lauffähige, getestete Implementierung**.
Der Testnachweis, die tatsächlich durchgeführten Tests und die **noch offenen
Punkte** (insbesondere Messungen auf echter Raspberry-Pi-Hardware) sind in

- [`docs/TESTBERICHT.md`](docs/TESTBERICHT.md)
- [`docs/ABNAHME.md`](docs/ABNAHME.md)

dokumentiert. Punkte, die in dieser Entwicklungsumgebung nicht praktisch
getestet werden konnten, sind dort **ausdrücklich als „nicht praktisch
getestet"** gekennzeichnet. Es werden keine Ergebnisse erfunden.

## Installation in Home Assistant (Kurzfassung)

1. Home Assistant → **Einstellungen → Add-ons → Add-on Store**
2. Oben rechts **⋮ → Repositories** öffnen
3. Diese Repository-URL eintragen:
   `https://github.com/Dealwirth/ElektroCoach`
4. **ElektroCoach Ollama** installieren und starten (lädt das Modell im
   Hintergrund).
5. **ElektroCoach** installieren und starten.
6. **ElektroCoach** in der Seitenleiste öffnen und den Einrichtungsassistenten
   durchlaufen.

Die vollständige, jederzeit auf den aktuellen Systemzustand bezogene Anleitung
steht in [`docs/INSTALLATION.md`](docs/INSTALLATION.md).

## Verzeichnisse

```text
elektrocoach-repository/
├── repository.yaml            # Add-on-Store-Metadaten
├── elektrocoach/              # Haupt-App (Backend + Website + Datenbank)
├── ollama/                    # Ollama-App (lokale KI)
└── docs/                      # Handbücher, Test- und Abnahmeprotokolle
```

Die Sensoren für Home Assistant legt das Add-on selbst über die
Supervisor-API an (siehe `elektrocoach/elektrocoach/integrations/homeassistant.py`).
Eine zusätzliche HACS-Integration ist nicht nötig.

## Lizenz

MIT
