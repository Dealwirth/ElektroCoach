# Testbericht

Stand: 2026-11-03. Alle Angaben wurden in dieser Umgebung tatsächlich geprüft,
sofern nicht ausdrücklich anders vermerkt.

## Umgebung

| Punkt | Wert |
| --- | --- |
| Tests | 217 automatisierte Tests, alle erfolgreich |
| Laufzeit | Python 3.13.15, FastAPI 0.119.1, Uvicorn 0.39.0 |
| Bildverarbeitung | Pillow 11.3.0, pypdfium2 4.30.0 |
| OCR | Tesseract mit `deu`, `eng`, `equ` |
| Container | Docker-Image gebaut aus `elektrocoach/Dockerfile`, gestartet, getestet |
| Architektur der Testmaschine | x86_64 (siehe Einschränkungen für ARM64) |

## 1. Automatisierte Tests

```
217 passed in 11.84s
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

1. **Laufzeit auf ARM64.** Das Image ist für arm64 verfügbar, aber in dieser
   Umgebung wurde nur die x86_64-Variante gebaut und gestartet. Der erste
   Add-on-Build auf dem Pi muss noch erfolgen.
2. **Echtes Samsung-Notes-Export.** Nur mit synthetischem Behälter getestet.
3. **Gemini-Live-Aufruf.** Ohne Schlüssel nicht möglich.
4. **Ollama-Live-Aufruf.** Kein Ollama-Server in dieser Umgebung.
5. **MQTT-Sensoren in Home Assistant.** Ohne Broker nicht sichtbar.
6. **Echter Home-Assistant-Ingress.** Über nachgebildeten Proxy getestet.
