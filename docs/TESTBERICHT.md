# Testbericht

Stand: 2026-11-03. Alle Angaben wurden in dieser Umgebung tatsächlich geprüft,
sofern nicht ausdrücklich anders vermerkt. Zusätzlich wurde das Add-on auf einem
echten Raspberry Pi 4 (8 GB, Home Assistant OS, aarch64) installiert und über
den echten Home-Assistant-Ingress geprüft (Abschnitt 12).

## Umgebung

| Punkt | Wert |
| --- | --- |
| Tests | 238 automatisierte Tests, 5 übersprungen |
| Laufzeit | Python 3.13.15, FastAPI 0.119.1, Uvicorn 0.39.0 |
| Bildverarbeitung | Pillow 11.3.0, pypdfium2 4.30.0 |
| OCR | Tesseract mit `deu`, `eng`, `equ` |
| Container | Docker-Image gebaut aus `elektrocoach/Dockerfile`, gestartet, getestet |
| Architektur der Testmaschine | x86_64 und **arm64 (echter Pi, siehe Abschnitt 12)** |

## 1. Automatisierte Tests

```
238 passed, 5 skipped
```

| Testdatei | Anzahl | Inhalt |
| --- | --- | --- |
| `test_api.py` | 39 | HTTP-Endpunkte, Antwortformate, Fehlerfälle |
| `test_learning.py` | 27 | Themen, Fragen, Bewertung, Lernplan |
| `test_schematic.py` | 27 | Symbole, Leitungen, Raster, Validierung, Export |
| `test_database.py` | 23 | Schema, FTS5, Transaktionen, WAL |
| `test_ha_and_resources.py` | 23 | Sensoren, Sensorwerte, Speichergrenzen |
| `test_offline.py` | 19 | Ersatzverfahren ohne KI |
| `test_ai.py` | 18 | Weiterleitung, Kontingent, Ausfälle |
| `test_exam.py` | 15 | Prüfungsablauf, Punkte, Vergleich |
| `test_ocr.py` | 15 | Text-, PDF- und Bildverarbeitung, Auflösung |
| `test_settings_wiring.py` | 11 | Einstellungen wirken tatsächlich (neu) |

## 2. Container-Build und -Start (echt durchgeführt)

* `docker build` erfolgreich, zwei Stufen: Oberfläche (Node 22) und Add-on
  (Home-Assistant-Basis mit Tesseract).
* Container startet, Datenbank und Import-Worker laufen an.
* Basis-Image ist für **amd64 und arm64** verfügbar (geprüft über das Manifest).
* Neu gebaute Oberfläche liegt korrekt unter `/app/app/static`.

## 3. Oberfläche hinter dem Ingress (echt durchgeführt)

Nachgebildeter Ingress-Proxy mit dem Pfad `/api/hassio_ingress/AbC123Token`:

| Prüfung | Ergebnis |
| --- | --- |
| Startseite über Ingress | 200, Oberfläche lädt |
| Tiefer Link `/pruefungen` über Ingress | 200, richtige Seite |
| Dateien (`assets/...`) über Ingress | 200, richtiger Typ |
| API über Ingress | 200 |
| Navigation | Alle Links tragen das Ingress-Präfix korrekt |
| Schaltplan-Editor über Ingress | Lädt, Symbole und Werkzeuge vorhanden |
| Export-Links (SVG/JSON) über Ingress | Korrekt aufgelöst |

Dabei wurde ein echter Fehler gefunden und behoben: Die Oberfläche verwendete
relative Dateipfade. Das funktionierte nur auf der Startseite. Auf
verschachtelten Seiten (etwa `/pruefungen/abc`) zeigten Dateipfade ins Leere.
Behoben durch einen `<base>`-Tag, der zur Laufzeit gesetzt wird, und durch
einen Router-Basispfad.

## 4. Import und OCR (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| PNG-Import | 1 Seite, Erkennungsgüte 88.9, Text korrekt |
| PDF-Import | 1 Seite, Erkennungsgüte 88.9, Text korrekt |
| Samsung-Notes-Export `.sdoc` (3 Bildseiten + Textseite) | 4 Seiten, alle Inhalte erkannt, Güte 91–92 |
| Rechenformel im Text | Erkannt: `U = (2*l*I*cos phi)/(kappa*A)` |
| Sammlungsname | Übernommen |
| Dublettenerkennung | Aktiv |
| Kennzeichnung unsicherer Seiten | Funktioniert (Schwelle 70 %) |

Die `.sdoc`-Datei war ein synthetischer Testbehälter mit realistischem Inhalt
(Bilder und JSON-Text). Ein echtes Samsung-Notes-Export konnte hier nicht
geprüft werden, weil kein Original vorliegt. Siehe Einschränkungen.

## 5. Lernsystem (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| Themenerkennung | 13 Abschnitte zugeordnet, 20 Lücken erkannt |
| Fragengenerierung ohne KI | 3 Fragen erzeugt, `ai_used: false` |
| Frage mit Quellenverweis | Quellseiten werden mitgeliefert |
| Antwort und Bewertung | Gespeichert, Fortschritt aktualisiert |
| Lernplan | Wiederholungen geplant (SM-2) |

## 6. Prüfungssimulation (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| Anlegen (Preset `kurz`) | 45 Minuten, 50 Punkte |
| Start | Status `running`, 3 Fragen |
| Antwort speichern | Erfolgreich |
| Abschluss | Bewertung, Bestehenswahrscheinlichkeit berechnet |
| Vergleich mehrerer Läufe | Mittelwert, Bestwert, Trend berechnet |

## 7. Schaltplan-Editor (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| Bibliothek | 15 Kategorien, 24 Symbole, Raster 20 px |
| Projekt anlegen | Erfolgreich |
| SVG-Export | Gültiges SVG mit Raster und Bauteilen |
| Validierung | Fehler erkannt: Leitung an nicht vorhandenem Anschluss; freie Anschlüsse gemeldet |
| Löschen | Erfolgreich |
| Bedienung im Browser | Editor lädt, Werkzeuge (Auswahl, Leitung, Punkt, Verschieben) vorhanden |

## 8. Home Assistant und Sensoren (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| Sensorwerte | Fortschritt, Lernzeit, fällige Wiederholungen, Fragen, Trefferquote, Serie, freier Speicher, Status |
| Aktualisierungsintervall | 300 Sekunden, konfigurierbar (30–3600) |
| Scheduler | Läuft, veröffentlicht nur im Intervall (kein Dauerfeuer auf dem Event-Bus) |
| MQTT | Konfiguration gelesen; ohne Broker nicht verbunden (erwartet) |

## 9. KI und Ausfallverhalten (echt durchgeführt)

| Situation | Ergebnis |
| --- | --- |
| Kein Schlüssel, Ollama aus | `any_available: false`, keine Abstürze |
| Anfrage im Ausfall | Klare Meldung, Hinweis, und passende Quellen aus eigenen Unterlagen |
| Fragengenerierung im Ausfall | Erfolgreich, Kennzeichnung `ai_used: false` |
| Kontingentgrenze | Getestet: Grenze 0 sperrt Anfragen |
| Zeitlimit | Aus Einstellungen übernommen |

Ein echter Gemini-Aufruf wurde **nicht** durchgeführt (kein Schlüssel in dieser
Umgebung). Die Anfrage- und Fehlerbehandlung ist über Tests mit
nachgebildeten Antworten abgedeckt.

## 10. Datenbank, Backup, Wiederherstellung (echt durchgeführt)

| Prüfung | Ergebnis |
| --- | --- |
| Backup anlegen | Erfolgreich, 0,27 MB |
| Backup auflisten | Erfolgreich |
| Wiederherstellung | Erfolgreich, Sicherheitskopie angelegt |
| Neustart des Containers | Daten bleiben erhalten (3 Dokumente) |
| Speicherplatzanzeige | Gesamt, belegt, frei, Prozent, Datenbankgröße |
| Import-Speicherbremse | Pausiert unter 512 MB freiem Platz |

## 11. Sicherheit (geprüft)

| Prüfung | Ergebnis |
| --- | --- |
| Schlüssel im Frontend | Nicht vorhanden; API gibt nur `********` zurück |
| Verschlüsselte Speicherung | Geheimnisse verschlüsselt in `/data` |
| Dateizugriff | Nur vorgesehene Dateiendungen |
| Uploads | Größenbegrenzung und Endungsprüfung |
| Externe Daten | Nur bei ausdrücklicher KI-Nutzung; Bilder standardmäßig aus |

## Offen / auf dem echten Pi zu prüfen

Diese Punkte wurden hier nicht oder nur teilweise geprüft:

1. **Laufzeit auf ARM64.** Inzwischen auf einem echten Raspberry Pi 4 über den
   echten Ingress geprüft (Abschnitt 12). Der ARM64-Build ist erfolgreich.
2. **Echtes Samsung-Notes-Export.** Nur mit synthetischem Behälter getestet.
3. **Gemini-Live-Aufruf.** Erledigt: echte Anfrage mit fachlich korrekter
   deutscher Antwort, Quellenverweis und Kennzeichnung `external: true`
   (siehe Abschnitt 12).
4. **Ollama-Live-Aufruf.** Ollama ist auf dem Pi noch nicht installiert.
5. **MQTT-Sensoren in Home Assistant.** Ohne Broker nicht sichtbar. Auf dem Pi
   ist derzeit kein MQTT-Broker installiert (nur `govee2mqtt`, im Fehlerzustand).

## 12. Echter Raspberry Pi 4 und echter Home-Assistant-Ingress

Add-on `b274c19d_elektrocoach`, Version **1.0.3**, Home Assistant OS auf
Raspberry Pi 4 (8 GB), aarch64, Python 3.14.10. Zugriff über den echten
Ingress-Pfad.

| Prüfung | Ergebnis |
| --- | --- |
| Add-on-Build (arm64) | Erfolgreich, Add-on startet |
| `/api/health` | `status ok`, `build 1.0.2`, Datenbank ok, Import-Worker aktiv |
| `SUPERVISOR_TOKEN` | **Verfügbar** (`supervisor_token: true`) |
| Benachrichtigung (Standardziel) | Erfolgreich: `persistent_notification.create` |
| Benachrichtigung fälliger Wiederholungen | Erfolgreich |
| HA-Status | Token vorhanden, Scheduler läuft, Sensorwerte vorhanden |
| Sensordaten | Fortschritt 13 %, Lernzeit, 1 fällige Wiederholung, Fragen, Trefferquote, freier Speicher 29 GB |
| Oberfläche über Ingress | 200, `index.html` lädt, Basis-Pfad zur Laufzeit gesetzt |
| Oberflächendateien | `assets/index-*.js` 200 (155 kB) |
| API über Ingress | 200 |
| Schaltplan: Projekt speichern (Punkte als Arrays) | Erfolgreich, Punkte normalisiert (echter Bugfix geprüft) |
| Schaltplan-Bibliothek | 24 Symbole in 15 Kategorien |
| Schaltplan-Projekt: anlegen, speichern, laden | Erfolgreich; Leitungs-Punkte als Arrays werden zu `{x,y}` normalisiert |
| Schaltplan: SVG- und JSON-Export | Erfolgreich (gültiges SVG, JSON 1,4 kB) |
| Schaltplan: Analyse | Bauteile, Leitungen, freie Anschlüsse und Netzwerk berechnet |
| Schaltplan: gültige Schaltung (L1–Schalter–Lampe–N) | Keine Fehler, keine freien Anschlüsse |
| Schaltplan: fehlerhafte Schaltung | Erkannt: toter Anschluss und Kurzschluss L1–N |
| Import-Formate | Samsung-Notes-Container als „best effort“ gemeldet, PDF empfohlen |
| Volltextsuche | Treffer mit Dokument-, Seiten- und Textbezug |
| Fällige Wiederholungen | 2 Fragen fällig, Lernplan berechnet |
| Frage beantworten | Bewertung mit Teilpunkten, Feedback, Rechenweg, Quellen |
| Spaced Repetition | Frage nach Antwort neu geplant (fällig 2 → 1) |
| Prüfungssimulation | Anlegen, Starten, Antworten, Abschluss, Vergleich erfolgreich |
| Backup | Vorhanden (`automatisch`, 8,8 kB) |
| Backup anlegen | Erfolgreich (`livetest`) |
| Wiederherstellung | Erfolgreich, Sicherheitskopie `vor-wiederherstellung-*.db` angelegt |
| Daten nach Wiederherstellung | Dokumente 1, Fragen 3, Schaltpläne 2 — vollständig |
| Add-on-Neustart über Supervisor | Erfolgreich, `state: started`, Version 1.0.3 |
| Daten nach Neustart | Erhalten (Dokumente, Fragen, Schaltpläne) |
| `SUPERVISOR_TOKEN` nach Neustart | Weiterhin vorhanden; Scheduler läuft wieder |
| Ressourcen | 4 Kerne, Last 0,51, freier Speicher 28 GB (47,9 %) |
| KI-Status | Gemini verfügbar, Kontingent 3/450 genutzt; Ollama deaktiviert |
| KI-Live-Anfrage (Gemini) | Erfolgreich: fachlich korrekte Antwort, Quellenverweis `[lerntest.png S.1]`, `external: true` |
| Benachrichtigung sichtbar in HA | Bestätigt über `persistent_notification/get` |
| Import über Ingress (PNG) | Erfolgreich, Hintergrundjob `done`: 1 importiert, 0 Duplikate, 0 Fehler |
| OCR (deutsches Tesseract auf dem Pi) | Text korrekt erkannt, Überschrift aus Frage abgeleitet |
| Volltextsuche nach importiertem Text | Treffer mit Dokument- und Seitenbezug |
| Dokument löschen | Erfolgreich, Bestand wieder 1 Dokument |
| Benachrichtigung aus der Oberfläche | Testnachricht gesendet, in Home Assistant sichtbar (`persistent_notification/get`) |
| Alle Kernendpunkte über Ingress | 200 (`/api/topics`, `/api/review/due`, `/api/plan`, `/api/progress`, `/api/questions`, `/api/documents`, `/api/storage`, `/api/system/info`, `/api/goals`, `/api/schematics/library`, `/api/backups`, `/api/ha/status`, `/api/search`, `/api/ai/status`) |

### Gefundene und behobene Fehler auf dem echten System

1. **`SUPERVISOR_TOKEN` war immer leer** (Home Assistant konnte nicht
   benachrichtigt werden), obwohl `homeassistant_api: true` gesetzt war. Ursache:
   Die Home-Assistant-Basis nutzt s6-overlay; ein Startskript mit
   `#!/usr/bin/env bash` erbt die Container-Umgebungsvariablen nicht. Behoben
   durch `#!/command/with-contenv bash` in `run.sh`. Erst danach meldete
   `/api/health` `supervisor_token: true` und Benachrichtigungen funktionierten.
2. **Versionsanzeige zeigte fest `1.0.0`.** Jetzt eine zentrale Konstante
   `app.__version__`; zusätzlich `build` und `supervisor_token` in `/api/health`
   zur schnellen Prüfung einer Installation.
3. **`notify.send_message` ohne Empfänger** führte zu HTTP 400 mit
   unverständlicher Meldung. Die Fehlermeldung erklärt jetzt die Ursache und
   den Ausweg; Standardziel bleibt `persistent_notification.create`. Version
   1.0.3 ausgeliefert und auf dem Pi geprüft.
