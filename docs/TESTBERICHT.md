# Testbericht ElektroCoach

Dieser Bericht dokumentiert **ausschließlich tatsächlich durchgeführte** Tests
und deren reale Ergebnisse. Es werden keine Ergebnisse erfunden.

- **Stand:** 2026-11-02
- **Version:** 0.1.0
- **Testumgebung:** Linux-Container (amd64), Python 3.13, SQLite, Tesseract mit
  Sprachpaketen `deu` und `eng`. Die Anwendung lief in einem Container, der aus
  demselben `Dockerfile` gebaut wurde wie das Home-Assistant-Add-on
  (`ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20`).

> **Wichtig:** Auf einem echten **Raspberry Pi 4 mit Home Assistant OS** konnte
> in dieser Entwicklungsumgebung **nicht** getestet werden. Die entsprechenden
> Punkte sind unten in Abschnitt 6 als „nicht praktisch getestet“ aufgeführt.

## 1. Automatisierte Tests

| Testart | Werkzeug | Ergebnis |
|---|---|---|
| Unit- und Integrationstests | pytest | **139 bestanden, 0 fehlgeschlagen** |
| Statische Typprüfung | (nur teilweise, siehe Abschnitt 6) | offen |

Ausführung:

```bash
cd elektrocoach/elektrocoach
python -m pytest tests -q
```

Die Testsuite deckt ab: Datenbank und Migrationen, KI-Client und -Dispatcher,
Dokumentenimport, Bewertung (alle Aufgabentypen), Prüfungen, Schaltplanmodell
und -export, Backup/Wiederherstellung sowie die HTTP-API.

## 2. Praktische Funktionstests (laufende Anwendung)

Die Anwendung wurde gestartet und über die echte HTTP-Schnittstelle geprüft
(Sitzung, CSRF-Token, echte Anfragen). Ergebnis: **23 von 23 Prüfungen
bestanden.**

| Bereich | Prüfung | Ergebnis |
|---|---|---|
| Auswahlaufgabe | Natürlicher Schlüssel `correct_index` wird bewertet | OK |
| Auswahlaufgabe | Richtige Antwort → richtig, volle Punktzahl 2,0 | OK |
| Auswahlaufgabe | Falsche Antwort → falsch, Musterlösung genannt | OK |
| Wiederholung | Intervall nach richtiger Antwort gesetzt (4 Tage) | OK |
| Rechenaufgabe | Exaktes Ergebnis innerhalb der Toleranz → richtig | OK |
| Rechenaufgabe | Falsches Ergebnis → falsch | OK |
| Freitextaufgabe | Bewertung mit Punkten (4,0) und Methode | OK |
| Eingabeprüfung | Auswahlaufgabe ohne gültige Lösung → HTTP 400 | OK |
| Lernplan | Erzeugung mit Zusammenfassung und Kennzahlen | OK |
| Prüfung | Anlegen, Starten, Beantworten, Abschließen | OK |
| Prüfung | Punkteverteilung, Note, Auswertung, Disclaimer | OK |
| Editor | Symbolbibliothek: 33 Symbole, 7 Kategorien | OK |
| Editor | Raster ist 20 Pixel | OK |
| Editor | Speichern, Laden, Validieren | OK |
| Editor | SVG- und PDF-Export (gültiges PDF) | OK |
| Editor | Kurzschluss L–N wird als Fehler erkannt | OK |
| Editor | Körperschluss L–PE wird als Fehler erkannt | OK |
| Editor | Korrekte Schaltung wird ohne Beanstandung akzeptiert | OK |
| Editor | Unbekannter Anschluss wird als Fehler erkannt | OK |
| Editor | Offener Anschluss wird gemeldet | OK |
| Editor | Alle 17 Frontend-Module syntaktisch fehlerfrei | OK |
| Home Assistant | 12 Sensoren definiert | OK |
| Home Assistant | Ohne Token sauber als „nicht verfügbar“ gemeldet | OK |

## 3. Dokumentenimport und OCR (praktisch getestet)

Es wurde ein echtes Bild mit deutschem Fachtext hochgeladen und verarbeitet.

- OCR-Engine: **Tesseract**, Sprachen `deu` und `eng`
- Erkennungsgüte: **91,1 %** (`ocr_confidence`)
- Erkannter Text (Auszug): „Schutzleiter und Fehlerstrom … Der FI-Schutzschalter
  loest bei 30 mA Fehlerstrom innerhalb 0,3 Sekunden aus.“
- Quelle und Seitenzahl wurden gespeichert (`page_number: 1`).
- Aus der Seite wurden **2 Wissenseinträge** erzeugt.
- Nicht lesbare Stellen werden als „zu prüfen“ markiert (`needs_review`).

## 4. Backup und Wiederherstellung (praktisch getestet)

| Prüfung | Ergebnis |
|---|---|
| Backup erstellen | HTTP 201, Datei mit SHA-256-Prüfsumme |
| Integrität prüfen | „Das Backup ist in Ordnung und kann wiederhergestellt werden.“ |
| Wiederherstellen ohne Bestätigung | HTTP 400, klare Erklärung |
| Wiederherstellen mit `?confirmed=true` | HTTP 200, Sicherheitsbackup angelegt |
| Rücknahme möglich | Vorher 1, nachher 2 Backups (Art „pre-restore“) |
| Backup herunterladen | HTTP 200, gültige ZIP-Datei |
| Unbekannte Backup-ID | HTTP 404, verständliche Meldung |

**Gefundener und behobener Fehler:** Nach einer Wiederherstellung verarbeitete
der Hintergrund-Worker keine neuen Aufgaben mehr, bis das Add-on neu gestartet
wurde. Ursache: Der Worker-Thread behielt seine SQLite-Verbindung zur bereits
ersetzten Datei. Behoben durch einen Generationszähler in `Database`
(`invalidate_connections`), der alle Threads zwingt, ihre Verbindung neu
aufzubauen. Nach dem Fix praktisch bestätigt: Ein neuer Auftrag wurde direkt
nach der Wiederherstellung verarbeitet, ohne Neustart.

## 5. Fehlerpfade (praktisch getestet)

| Simulierter Fehler | Beobachtetes Verhalten |
|---|---|
| Ollama nicht erreichbar | Klare Meldung mit Adresse; Anwendung läuft weiter |
| Gemini-Schlüssel ungültig | „Der Gemini-API-Schlüssel wurde von Google abgelehnt.“ |
| Keine KI verfügbar | HTTP 502 mit erklärender Ursache, kein Absturz |
| Ungültiger Upload | HTTP 422 mit verständlicher Meldung |
| Path Traversal (`../../etc/passwd`) | HTTP 404, kein Dateizugriff |
| Ändernde Anfrage ohne CSRF-Token | HTTP 403 |
| Zu kurze Pflichteingabe | HTTP 422 mit Feldhinweis |
| Einrichtungsassistent unvollständig | HTTP 409, Abschluss verweigert |

Der Einrichtungsassistent meldete in der Testumgebung korrekt **83 %** mit zwei
echten Blockern („Verbindung zu Home Assistant prüfen“, „KI-Verbindungen
prüfen“) und verweigerte den Abschluss. Er zeigt damit **keinen** fälschlichen
Erfolg an.

## 6. Container-Build und Betrieb (praktisch getestet)

Das Docker-Image wurde aus dem **echten** `Dockerfile` gebaut:

```bash
docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 \
  -t elektrocoach:amd64-verify elektrocoach
```

| Prüfung | Ergebnis |
|---|---|
| Image-Build (amd64) | Erfolgreich |
| Start im Container | „ElektroCoach 0.1.0 ready“, Uvicorn auf Port 8099 |
| Optionen aus `/data/options.json` | Gelesen und angewendet |
| Website ausgeliefert | Startseite und Assets mit HTTP 200 |
| OCR im ausgelieferten Image | Tesseract `deu`, 82,5 % Konfidenz, Text korrekt erkannt |
| Wissenseintrag aus Import | 1 Eintrag erzeugt |
| Auftragswarteschlange | Auftrag „done“, Dokument „processed“ |

Damit ist belegt, dass das **tatsächlich ausgelieferte Artefakt** läuft und
Dokumente verarbeitet – nicht nur die Entwicklungsumgebung.

Ein **ARM64-Build** (`linux/arm64`) war nicht möglich: Die QEMU/binfmt-
Registrierung ist in dieser Umgebung gesperrt
(`/proc/sys/fs/binfmt_misc/register`: „Read-only file system“). Die
Build-Dateien für `aarch64` sind vorhanden, der Build selbst wurde nicht
ausgeführt.

## 7. Bewusst NICHT praktisch getestete Punkte

Diese Punkte konnten in dieser Umgebung **nicht** praktisch geprüft werden. Sie
sind im Code enthalten und automatisiert getestet, aber **nicht** auf echter
Zielhardware erprobt:

1. **Betrieb auf Raspberry Pi 4 / Home Assistant OS.** Kein Gerät verfügbar.
2. **ARM64-Build.** Der Cross-Build mit QEMU/binfmt ist in dieser Umgebung
   gesperrt (das Verzeichnis `/proc/sys/fs/binfmt_misc` ist schreibgeschützt).
   Die Build-Dateien (`build.yaml` mit `aarch64`-Basis-Images, `config.yaml` mit
   `arch: [aarch64, amd64]`) sind vorhanden, der Build selbst wurde **nicht**
   ausgeführt.
3. **Installation über den Home-Assistant-Add-on-Store und Zugriff über
   Ingress.** Ohne Home Assistant nicht möglich. Die Ingress-Pfadlogik
   (`<base href>` aus dem `X-Ingress-Path`-Kopf) wurde separat mit einem
   simulierten Kopf geprüft und lieferte den korrekten Basispfad.
4. **Ollama mit echtem Modell.** In dieser Umgebung lief kein Ollama-Server mit
   heruntergeladenem Modell. Die Verbindungs-, Modell- und Fehlerlogik ist
   automatisiert getestet (u. a. mit einem lokalen Testserver), aber nicht mit
   `qwen2.5:1.5b` auf echter Hardware.
5. **Google Gemini mit echtem Konto.** Es wurde kein kostenpflichtiger oder
   privater Zugang verwendet. Die Antwortverarbeitung, die 429-Kontingent-
   erkennung und das lokale Tageslimit sind automatisiert getestet, nicht aber
   mit einem echten Google-Konto.
6. **Home-Assistant-Sensoren und Benachrichtigungen.** Ohne Supervisor-Token
   meldet die Anwendung korrekt „nicht verfügbar“. Die tatsächliche Anlage der
   Sensoren in Home Assistant wurde nicht beobachtet.
7. **Leistungsmessung (RAM, CPU, Speicher, Antwortzeiten) auf dem Raspberry Pi.**
   Nicht gemessen.
8. **Neustart während einer laufenden Aufgabe auf echter Hardware.** Das
   Auftragssystem ist wiederaufnahmefähig gestaltet und automatisiert getestet,
   aber kein echter Neustart wurde auf dem Pi ausgelöst.
9. **Handschrifterkennung.** Nur gedruckter Text wurde praktisch geprüft. Die
   Handschriftverarbeitung ist implementiert, aber nicht mit echten
   Handschriftproben getestet.

## 7. Reproduzierbarkeit

Alle Befehle in diesem Bericht sind wiederholbar. Die Ergebnisse in den
Abschnitten 2 bis 5 wurden mit einem Container erzeugt, der über

```bash
docker build -t elektrocoach:test -f elektrocoach/Dockerfile elektrocoach
```

gebaut und anschließend mit gemountetem `/data`- und `/share`-Verzeichnis
gestartet wurde.
