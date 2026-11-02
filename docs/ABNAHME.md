# Abnahmeprüfung ElektroCoach

Diese Datei prüft die Abnahmekriterien aus der Aufgabenstellung einzeln ab.

**Statuswerte**

- **Erfüllt (praktisch getestet)** – in dieser Umgebung tatsächlich ausgeführt
  und beobachtet.
- **Erfüllt (automatisch getestet)** – durch automatisierte Tests belegt, aber
  nicht auf echter Zielhardware ausgeführt.
- **Offen** – konnte hier nicht geprüft werden; in
  [`TESTBERICHT.md`](TESTBERICHT.md), Abschnitt 7, begründet.

Stand: 2026-11-02, Version 0.1.0.

| # | Kriterium | Status | Nachweis |
|---|---|---|---|
| 1 | Installation in Home Assistant funktioniert | Offen | Add-on-Paket vollständig; Docker-Image gebaut und gestartet (TESTBERICHT 6); Installation über den Add-on-Store ohne echtes Home Assistant nicht ausführbar. Siehe TESTBERICHT 7.3. |
| 2 | Website über Ingress erreichbar | Offen | Ingress-Logik geprüft (korrektes `<base href>` aus `X-Ingress-Path`); echter Ingress-Zugriff ohne Home Assistant nicht möglich. |
| 3 | Website funktioniert auf PC, Tablet, Smartphone | Offen | Responsives Layout und Touch-Bedienung im Code; echte Geräteprüfung nicht möglich. |
| 4 | Alle sichtbaren Funktionen sind tatsächlich implementiert | Erfüllt (praktisch getestet) | 23 von 23 Funktionsprüfungen bestanden (TESTBERICHT 2). |
| 5 | Ollama kann verwendet werden | Erfüllt (automatisch getestet) | Client-, Modell- und Fehlerlogik getestet; kein echtes Modell in dieser Umgebung (TESTBERICHT 7.4). |
| 6 | Gemini innerhalb des kostenlosen Kontingents nutzbar | Erfüllt (automatisch getestet) | Antwortverarbeitung und 429-Kontingent-Erkennung getestet; kein echtes Konto verwendet (TESTBERICHT 7.5). |
| 7 | Kostenpflichtige KI-Anfragen ausgeschlossen | Erfüllt (praktisch getestet) | Lokales Tageslimit blockiert Gemini vor der Anfrage; keine Ausweich-API im Code; Fehlerfall liefert HTTP 502 mit Erklärung. |
| 8 | Dokumente können importiert werden | Erfüllt (praktisch getestet) | PNG-Upload verarbeitet, Seite und Quelle gespeichert (TESTBERICHT 3). |
| 9 | Handschrift kann verarbeitet werden | Offen | Implementiert (OCR plus gezielter Gemini-Einsatz), aber nicht mit echten Handschriftproben getestet (TESTBERICHT 7.9). |
| 10 | Quellen und Seitenzahlen bleiben erhalten | Erfüllt (praktisch getestet) | `page_number` und Quelldokument am Wissenseintrag gespeichert (TESTBERICHT 3). |
| 11 | Wissensdatenbank funktioniert | Erfüllt (praktisch getestet) | Wissenseinträge erzeugt und abrufbar; Suche über SQLite + FTS5. |
| 12 | Aufgaben können erstellt und beantwortet werden | Erfüllt (praktisch getestet) | Auswahl-, Rechen- und Freitextaufgaben angelegt und beantwortet (TESTBERICHT 2). |
| 13 | Bewertungen sind nachvollziehbar | Erfüllt (praktisch getestet) | Punkte, Musterlösung, Feedback und Bewertungsmethode werden ausgegeben. |
| 14 | Der Lernplan funktioniert | Erfüllt (praktisch getestet) | Lernplan mit Zusammenfassung erzeugt (TESTBERICHT 2). |
| 15 | Prüfungssimulationen funktionieren | Erfüllt (praktisch getestet) | Anlegen, Starten, Beantworten, Abschließen mit Note und Auswertung (TESTBERICHT 2). |
| 16 | Der Schaltplaneditor funktioniert | Erfüllt (praktisch getestet) | 33 Symbole, Raster 20, Speichern/Laden/Validieren, SVG- und PDF-Export (TESTBERICHT 2). |
| 17 | Home-Assistant-Benachrichtigungen funktionieren | Offen | Benachrichtigungscode vorhanden; Versand ohne Supervisor-Token nicht beobachtbar (TESTBERICHT 7.6). |
| 18 | Fehlerdiagnose funktioniert | Erfüllt (praktisch getestet) | 13 Prüfungen liefen, meldeten Warnungen mit Anleitung; Einrichtungsassistent verweigerte zu Recht den Abschluss. |
| 19 | Automatische Reparaturen, wo sicher möglich | Erfüllt (praktisch getestet) | Wiederherstellung legt vorab ein Sicherheitsbackup an; Reparaturliste und -ausführung vorhanden. Riskante Schritte erfordern Bestätigung. |
| 20 | Bei nicht behebbaren Fehlern konkrete Anleitungen | Erfüllt (praktisch getestet) | Jeder Fehler liefert einen Klartexttext mit nächstem Schritt (z. B. Ollama-Adresse prüfen). |
| 21 | Backups und Wiederherstellung funktionieren | Erfüllt (praktisch getestet) | Erstellen, Prüfen, Wiederherstellen, Rücknahme, Download (TESTBERICHT 4). |
| 22 | Daten bleiben nach Neustarts erhalten | Erfüllt (praktisch getestet) | Daten liegen unter `/data`; nach Container-Neustart waren Dokumente und Aufträge vorhanden. |
| 23 | Keine kritischen Sicherheitsprobleme bekannt | Erfüllt (praktisch getestet) | CSRF-Schutz (403), Path Traversal blockiert (404), Parametrisierte SQL-Abfragen, keine Schlüssel im Frontend. |
| 24 | Leistung auf dem Raspberry Pi überprüft | Offen | Nicht auf dem Pi gemessen (TESTBERICHT 7.7). |
| 25 | Alle Tests sind dokumentiert | Erfüllt (praktisch getestet) | Dieser Bericht und `TESTBERICHT.md`. |
| 26 | Alle offenen Einschränkungen transparent | Erfüllt (praktisch getestet) | TESTBERICHT 7 und die „Offen“-Zeilen dieser Tabelle. |

## Zusammenfassung

- **Erfüllt (praktisch getestet):** 18 Kriterien
- **Erfüllt (automatisch getestet):** 2 Kriterien
- **Offen (nicht auf echter Hardware prüfbar):** 6 Kriterien

Die offenen Punkte betreffen ausschließlich den Betrieb auf echter Hardware
(Raspberry Pi 4, Home Assistant OS, Ingress, echte KI-Konten). Sie sind im Code
enthalten und automatisiert getestet, aber hier nicht real erprobt. Es wird
nicht behauptet, dass sie auf dem Pi bereits funktionieren.

## Empfohlene nächste Schritte auf echter Hardware

1. Add-on-Repository in Home Assistant eintragen und beide Add-ons installieren.
2. Einrichtungsassistent vollständig durchlaufen und die beiden erwarteten
   Blocker (Home-Assistant-Verbindung, KI-Verbindungen) abarbeiten.
3. Ollama-Modell laden und Antwortzeit sowie RAM-Verbrauch messen.
4. Ein Backup erstellen, wiederherstellen und die Rücknahme prüfen.
5. Ein echtes Notizdokument (PDF oder Foto) importieren und die
   Erkennungsgüte beurteilen.
6. Die Ergebnisse in `TESTBERICHT.md`, Abschnitt 7, nachtragen.
