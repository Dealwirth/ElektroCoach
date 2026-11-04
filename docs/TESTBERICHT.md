# Testbericht

Stand: 2026-11-03. Alle Angaben wurden in dieser Umgebung tatsächlich geprüft,
sofern nicht ausdrücklich anders vermerkt. Zusätzlich wurde das Add-on auf einem
echten Raspberry Pi 4 (8 GB, Home Assistant OS, aarch64) installiert und über
den echten Home-Assistant-Ingress geprüft (Abschnitt 12).

## Umgebung

| Punkt | Wert |
| --- | --- |
| Tests | 310 automatisierte Tests, 5 übersprungen |
| Laufzeit | Python 3.13.15, FastAPI 0.119.1, Uvicorn 0.39.0 |
| Bildverarbeitung | Pillow 11.3.0, pypdfium2 4.30.0 |
| OCR | Tesseract mit `deu`, `eng`, `equ` |
| Container | Docker-Image gebaut aus `elektrocoach/Dockerfile`, gestartet, getestet |
| Architektur der Testmaschine | x86_64 und **arm64 (echter Pi, siehe Abschnitt 12)** |

## 1. Automatisierte Tests

```
310 passed, 5 skipped
```

| Testdatei | Anzahl | Inhalt |
| --- | --- | --- |
| `test_api.py` | 39 | HTTP-Endpunkte, Antwortformate, Fehlerfälle |
| `test_schematic.py` | 30 | Symbole, Leitungen, Raster, Validierung, Export |
| `test_learning.py` | 27 | Themen, Fragen, Bewertung, Lernplan |
| `test_ha_and_resources.py` | 25 | Sensoren, Sensorwerte, Speichergrenzen |
| `test_ai.py` | 23 | Weiterleitung, Kontingent, Ausfälle |
| `test_database.py` | 24 | Schema, FTS5, Transaktionen, WAL |
| `test_offline.py` | 19 | Ersatzverfahren ohne KI |
| `test_robustness.py` | 19 | Fehlerfälle, kaputte Eingaben, Randwerte |
| `test_exam.py` | 15 | Prüfungsablauf, Punkte, Vergleich |
| `test_ocr.py` | 15 | Text-, PDF- und Bildverarbeitung, Auflösung |
| `test_ollama_addon.py` | 14 | Ollama-Add-on über den Supervisor (neu) |
| `test_settings_wiring.py` | 11 | Einstellungen wirken tatsächlich |
| `test_refine_api.py` | 10 | Endpunkte der KI-Nachbearbeitung (neu) |
| `test_refine.py` | 8 | Zweistufige Nachbearbeitung (neu) |
| `test_spa_base.py` | 7 | Auslieferung der Oberfläche, `<base>` für Ingress (neu) |
| `test_ai_choice_web_stylus.py` | 20 | KI pro Anfrage, strikte Wahl, Webquellen-Filter, Handschrift (neu) |

### Neu in 1.1.0 geprüft

| Prüfung | Ergebnis |
| --- | --- |
| Anbieterwahl `auto` / `ollama` / `gemini` je Anfrage | wirkt, Fallback-Kette bleibt erhalten |
| `ai_strict_provider = true` | kein Ausweichen, klare Fehlermeldung |
| Webquellen: nur verlässliche Adressen | fremde Adressen werden verworfen |
| Webquellen: Passgenauigkeit | unpassende Treffer werden verworfen |
| Webquellen: Quellenangabe | `[WEB-n]` und Link vorhanden |
| Handschrift ohne Bildfreigabe | klare Meldung, kein stiller Fehlschlag |
| Handschrift mit Gemini | Text kommt zurück, bleibt korrigierbar |
| KI-Modus in den Einstellungen | schreibt `local_only` / `cloud_only`, wirkt jetzt |

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
Zuerst wurde ein `<base>`-Tag zur Laufzeit per JavaScript gesetzt. Das reichte
jedoch nicht: der Browser liest `<base>` schon beim Vorabladen
(Preload-Scanner), deshalb lud Chromium auf verschachtelten Seiten
`assets/index-*.css` gegen den falschen Pfad und verwarf das Stylesheet
(„MIME type text/html"). Behoben in Version 1.0.5: Das Backend setzt den
Basispfad serverseitig in den Kopf der ausgelieferten Seite (aus dem Kopf
`X-Ingress-Path`). Zusätzlich wird ein Router-Basispfad genutzt. Geprüft mit
`test_spa_base.py` (7 Tests) und im Browser auf verschachtelten Seiten.

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

Add-on `b274c19d_elektrocoach`, Version **1.0.4**, Home Assistant OS auf
Raspberry Pi 4 (8 GB), aarch64, Python 3.14.10. Zugriff über den echten
Ingress-Pfad.

| Prüfung | Ergebnis |
| --- | --- |
| Add-on-Build (arm64) | Erfolgreich, Add-on startet |
| `/api/health` | `status ok`, `build 1.0.4`, Datenbank ok, Import-Worker aktiv |
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
| Add-on-Neustart über Supervisor | Erfolgreich, `state: started`, Version 1.0.4 |
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
| Version 1.0.4 auf dem Pi installiert | Erfolgreich; `/api/health` meldet `version 1.0.4`, `build 1.0.4`, `db ok`, `worker_alive true`, `supervisor_token true` |
| KI-Antwortzeit nach Modellwechsel-Fix | Erste Anfrage 33 s (einmaliger Wechsel von `gemini-flash-latest` auf `gemini-3.5-flash`), Folgeanfragen 12–13 s |
| Verhalten ohne KI (`ai_mode: off`) | Sofortige, verständliche Meldung in 0,4 s; kein Hängen; Hinweis, dass Wissenssuche und Lernfunktionen ohne KI verfügbar bleiben |

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
4. **Wartezeit bei überlastetem Gemini-Modell.** `gemini-flash-latest`
   antwortete zeitweise mit HTTP 503 („high demand"). Die Anfrage wurde zwar
   korrekt auf das nächste Modell umgeleitet, kostete aber bei jeder Anfrage
   erneut Wartezeit (bis zu 180 s Lesezeitlimit). Behoben in Version 1.0.4:
   - Ein Modell, das mit 404 oder 503 antwortet, wird 120 s lang als
     „degraded" nach hinten sortiert.
   - Reisst ein Modell das Lesezeitlimit, wird sofort das nächste Modell
     probiert, statt das Limit erneut abzuwarten.
   - Ein erfolgreich genutztes Ausweichmodell wird weiterhin gemerkt, sodass
     die nächste Anfrage direkt das funktionierende Modell nutzt.
   Geprüft mit zwei neuen Tests (`test_gemini_wechselt_bei_zeitueberschreitung`,
   `test_gemini_ueberlastetes_modell_wird_nach_hinten_sortiert`) und auf dem Pi.

## 13. Version 1.0.5: KI-Nachbearbeitung, Ollama-Add-on, Oberflächenprüfung

In dieser Umgebung tatsächlich durchgeführt (Docker-Container, echter Browser
mit Chromium über Playwright).

### 13.1 Neue Funktionen

| Funktion | Beschreibung |
| --- | --- |
| Ollama-Add-on-Verwaltung | Das Add-on kann sich das Ollama-Add-on über den Supervisor selbst installieren, starten und die Adresse eintragen (`/api/ai/ollama/addon`, `/ensure`, `/installed`, `/pull`) |
| KI-Nachbearbeitung erkannter Texte | Zweistufig: zuerst Ollama lokal, bei unsicheren Seiten optional Gemini (nur mit ausdrücklicher Freigabe). Hintergrund-Worker, abbrechbar, mit Speicher- und Platzbremse |
| Endpunkte der Nachbearbeitung | `/api/ai/refine`, `/refine/jobs`, `/refine/jobs/{id}`, `/refine/jobs/{id}/cancel`, `/refine/page` |
| Nachbearbeitung nach Import | Einstellung `refine_after_import`; startet nur, wenn wirklich eine KI erreichbar ist |
| Helles/dunkles Design | Folgt der Home-Assistant-Einstellung; Schaltplan-Leitungen und Symbole bleiben in beiden Betriebsarten sichtbar |

### 13.2 Echte Bedientests im Browser

| Prüfung | Ergebnis |
| --- | --- |
| Alle Seiten laden (`/`, `/import`, `/bibliothek`, `/lernen`, `/pruefungen`, `/schaltplan`, `/tutor`, `/einstellungen`, `/system`) | Alle 200, keine 404-Ressource, keine Konsolenfehler |
| Dunkle Betriebsart | Klasse `dark` aktiv, Farben passen sich an |
| Verschachtelte Seite (`/schaltplan/editor/<id>`) | Stylesheet lädt korrekt (Fehler aus Abschnitt 3 behoben) |
| Ollama-Bereich in den Einstellungen | Vorhanden und bedienbar |
| Nachbearbeitungsbereich auf der Import-Seite | Vorhanden |
| Bauteile über die Bibliothek einfügen | 2 Bauteile eingefügt, gespeichert und wieder geladen |
| Leitung zwischen zwei Anschlüssen ziehen | Leitung mit Verbindung `switch.1 → changeover.1` gespeichert |
| Leitung ziehen, während der Zeiger die Fläche verlässt | Leitung bleibt erhalten (Zeiger wird eingefangen) |
| Nachbearbeitung ohne erreichbare KI | Klare Meldung in der Oberfläche, kein Hängen |
| `/api/ai/refine` ohne KI | HTTP 400 mit verständlicher Meldung |
| Neustart des Containers | `/api/health` wieder `ok`, Datenbank und beide Worker aktiv |

### 13.3 Dabei gefundene und behobene Fehler

1. **Stylesheet fehlte auf verschachtelten Seiten** (siehe Abschnitt 3).
   Behoben durch serverseitiges `<base>`-Element.
2. **Leitung wurde beim Verlassen der Zeichenfläche vorzeitig beendet.**
   `onPointerLeave` beendete das Ziehen, obwohl der Zielanschluss noch folgen
   sollte. Behoben durch Einfangen des Zeigers (`setPointerCapture`) beim Start
   einer Leitung.
3. **Abschluss-Checkpoint der Datenbank konnte beim Herunterfahren fehlschlagen**
   („disk I/O error"), wenn die Datenbankdatei zuvor ersetzt wurde (etwa nach
   einer Wiederherstellung). Beim Herunterfahren wird der Fehler jetzt nur
   protokolliert (`db.checkpoint_quiet`), das Beenden läuft weiter.
4. **Nach einer Wiederherstellung schlugen alle Schreibzugriffe fehl.** Die
   Datenbankdatei wurde ersetzt, aber bestehende Verbindungen anderer Threads
   zeigten weiter auf die gelöschte Datei. Jeder Schreibzugriff (Import,
   Bewertung, Backup) endete mit „disk I/O error" — auch nach dem geforderten
   Neustart blieb die Anwendung bis zum manuellen Neustart des Add-ons
   schreibunfähig. Behoben in Version 1.0.5: Ein Verbindungsgenerationszähler
   (`db.invalidate_connections`) zwingt jeden Thread, seine Verbindung nach
   dem Ersetzen der Datei neu aufzubauen. Das Ersetzen läuft unter der
   Schreibsperre (`db.replace_database_file`). Geprüft mit dem Test
   `test_nach_wiederherstellung_sind_schreibzugriffe_moeglich` (schlägt ohne
   die Behebung fehl) und im Container (Import direkt nach einer
   Wiederherstellung).
5. **Wartezeit beim Einrichten des Ollama-Add-ons.** Das Warten auf die
   Erreichbarkeit ist jetzt auf 90 s begrenzt, damit die Oberfläche hinter dem
   Ingress nicht in eine Zeitüberschreitung läuft. Längere Starts werden über
   den Status erneut geprüft.

### 13.4 Gesamtprüfung im Container (Version 1.0.5)

| Schritt | Ergebnis |
| --- | --- |
| PNG-Import mit Fachtext | Erfolgreich, Hintergrundjob `done`, 1 Seite |
| Volltextsuche nach dem importierten Text | 1 Treffer mit Dokument- und Seitenbezug |
| Themenkatalog | 28 Themen vorhanden |
| Fragen erzeugen ohne KI | Antwort 200 mit verständlichem Hinweis, keine Fragen erfunden |
| Prüfungssimulation ohne Fragen | HTTP 400 mit klarer Begründung |
| Schaltplan anlegen, speichern, validieren | 2 Bauteile, 1 Leitung; freie Anschlüsse korrekt gemeldet |
| SVG-Export | Gültiges SVG |
| Backup anlegen und wiederherstellen | Beides erfolgreich, Sicherheitskopie angelegt |
| Import direkt nach der Wiederherstellung | Erfolgreich (vorher „disk I/O error") |
| `/api/health` nach allen Schritten | `status ok`, `db ok`, `worker_alive true` |

## 14. Version 1.1.0: Prüfung im laufenden Container (echt durchgeführt)

Geprüft an einem frisch gebauten Image (`elektrocoach:1.1.0`), gestartet mit
eigenem Datenverzeichnis. Alle folgenden Schritte liefen gegen den echten
HTTP-Dienst und die echte SQLite-Datenbank, nicht gegen Attrappen.

### 14.1 Import, OCR und Volltextsuche

| Schritt | Ergebnis |
| --- | --- |
| Bild-Import (PNG) über `/api/import` | Hintergrundjob `done`, 1 importiert, 0 Duplikate, 0 Fehler |
| OCR (deutsches Tesseract) | Text korrekt erkannt (`Leitungsschutzschalter`, `Bemessungsstrom In = 16 A`) |
| Mehrseitiges PDF importieren | 2 Seiten erkannt, Texte je Seite zugeordnet |
| Sammlungszuordnung beim Import | Sammlung „Lehrjahr 1" korrekt gespeichert |
| Volltextsuche (FTS5) | Treffer mit Dokument, Seite und Textausschnitt |
| Doppelte Datei erneut importieren | Als `duplicate` erkannt, Bestand unverändert |
| Importfortschritt über `/api/import/jobs/{id}` | Status, Zähler und Ergebnisliste vorhanden |

### 14.2 Lernsystem, Bewertung und Prüfung

| Schritt | Ergebnis |
| --- | --- |
| Themenkatalog | 28 Themen aus dem Katalog |
| Fragen ohne KI erzeugen | 5 Fragen mit Quellenverweis auf die eigene Seite |
| Antwort bewerten (offline) | Punkte, Teilpunkte, Feedback und Quellenzitat |
| Fällige Wiederholungen | Liste und Anzahl korrekt |
| Lernplan | Zeitbudget, Reihenfolge und Priorität berechnet |
| Fortschritt und Serie | Kennzahlen und Tagesreihe vorhanden |
| Prüfung anlegen, starten, antworten, abschließen | Voller Ablauf erfolgreich |
| Prüfungsvergleich | Durchschnitt, Bestwert, Trend vorhanden |

### 14.3 Schaltplan-Editor (Rechenkern)

| Schritt | Ergebnis |
| --- | --- |
| Symbolbibliothek | 24 Symbole in 15 Kategorien |
| Projekt anlegen, speichern, laden | Erfolgreich (Bauteile und Leitungen erhalten) |
| Unbekannter Bauteiltyp | Als Fehler gemeldet |
| Leitungen an echten Anschlüssen | Keine Fehler, keine freien Anschlüsse |
| Kurzschluss L1–N | Erkannt und gemeldet |
| Netzanalyse | Zusammenhängende Netze korrekt gruppiert |
| SVG- und JSON-Export | Gültiges SVG, JSON mit allen Bauteilen |

### 14.4 KI-Anbindung mit echtem HTTP-Durchstich

Für einen echten Durchstich wurde nur die Basisadresse von Gemini auf einen
lokalen Nachbau derselben Schnittstelle umgebogen. Alles andere (httpx,
JSON-Aufbau, Antwortauswertung, `ai_router`, Endpunkte) war der echte Code.

| Schritt | Ergebnis |
| --- | --- |
| Modellliste über die Schnittstelle | 2 Modelle erkannt |
| Anfrage an Gemini | Antwort gelesen, Modell vermerkt |
| Auswahl über `ai_router` | Anbieter `gemini`, kein Ausweichen |
| Handschrift über Gemini | Text zurückgegeben, Methode `gemini` |
| Kontingentzähler | Aufrufe je Anbieter gezählt |
| Endpunkt `/api/ai/chat` | HTTP 200, Anbieter `gemini` |
| Endpunkt `/api/ai/handwriting` | HTTP 200, Text, Konfidenz, Methode |

### 14.5 Home-Assistant-Anbindung und Neustart

| Schritt | Ergebnis |
| --- | --- |
| MQTT-Discovery | 10 Nachrichten, alle gültiges JSON, alle retained |
| Sensorzustände | Fortschritt, Lernzeit, Wiederholungen, Fragen, Trefferquote, Serie |
| Verfügbarkeitsthema | `online` (Klartext, wie von MQTT erwartet) |
| Aktualisierungsintervall | 300 s, Scheduler läuft |
| Container-Neustart | `/api/health` wieder `ok`, Datenbank ok, Worker aktiv |
| Daten nach Neustart | Dokumente, Seiten, Fragen, Prüfungen und Schaltpläne erhalten |
| Volltextsuche nach Neustart | Treffer weiterhin vorhanden |

### 14.6 Backup und Wiederherstellung (echt durchgeführt)

| Schritt | Ergebnis |
| --- | --- |
| Backup anlegen | Erfolgreich (`manuell`, Sicherungskopie geschrieben) |
| Dokument löschen | Erfolgreich, Bestand 0 |
| Wiederherstellung | Erfolgreich, Sicherheitskopie `vor-wiederherstellung-*.db` |
| Bestand nach Wiederherstellung | Dokument wieder vorhanden |

### 14.7 Dabei gefundener und behobener Fehler

1. **Leitungslänge wurde als 0 m gemeldet.** Im Schaltplan-Editor zeigte die
   Projektübersicht „0 m Leitungslänge", obwohl Leitungen vorhanden waren. Die
   Berechnung summierte nur die gespeicherten Zwischenpunkte. Eine gerade
   Leitung ohne Knick — der Normalfall — hat keine Zwischenpunkte und ergab
   deshalb die Länge 0. Behoben: Die Länge wird jetzt vom Startanschluss über
   die Zwischenpunkte zum Zielanschluss gemessen, aus derselben Pin-Geometrie
   wie beim Zeichnen und beim SVG-Export. Geprüft mit dem Regressionstest
   `test_leitung_ohne_zwischenpunkte_hat_trotzdem_laenge` (schlägt ohne die
   Behebung fehl) und im Container (160 px für eine 160-px-Strecke).
