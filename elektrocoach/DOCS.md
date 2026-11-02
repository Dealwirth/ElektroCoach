# ElektroCoach

Lernplattform für die Ausbildung zum **Elektroniker für Energie- und
Gebäudetechnik** – als Home-Assistant-Add-on.

Diese Seite ist die Kurzdokumentation, die Home Assistant direkt in der
Add-on-Ansicht anzeigt. Die ausführlichen Anleitungen stehen im Repository
unter [`docs/`](../docs/).

## Was das Add-on kann

| Bereich | Funktion |
|---|---|
| Wissensdatenbank | Volltextsuche über SQLite + FTS5, Quellen und Seitenzahlen bleiben erhalten |
| Dokumentenimport | PDF, Bilder und Scans; OCR mit Tesseract, Handschrift über Gemini |
| Lernsystem | Multiple-Choice, Rechen-, Zuordnungs-, Freitext- und Fehleranalyse-Aufgaben |
| Adaptives Lernen | SM-2-Wiederholungsplaner, individueller Lernplan |
| Prüfungssimulation | Zeitlimit, Punkteverteilung, Auswertung, Stärken/Schwächen-Analyse |
| Schaltplaneditor | Raster mit 20 px, IEC-Symbole, Verbindungsprüfung, SVG-/PDF-Export |
| KI-Dispatcher | Lokales Ollama und Google Gemini (Free Tier) mit Budgetüberwachung |
| Selbstdiagnose | Systemprüfung, sichere automatische Reparaturen, Fehlerberichte |
| Backup | Automatische und manuelle Sicherung mit Wiederherstellung |
| Home Assistant | Sensoren, Benachrichtigungen, Ingress-Panel |

## Installation

1. Öffnen Sie in Home Assistant **Einstellungen → Add-ons → Add-on-Store**.
2. Klicken Sie oben rechts auf die drei Punkte und dann auf **Repositories**.
3. Fügen Sie die URL dieses Repositories hinzu und bestätigen Sie mit **Hinzufügen**.
4. Aktualisieren Sie die Seite. Unter **ElektroCoach Add-ons** erscheint jetzt
   das Add-on **ElektroCoach**.
5. Öffnen Sie das Add-on und klicken Sie auf **Installieren**.
6. Wechseln Sie zum Reiter **Konfiguration**. Die Standardwerte funktionieren
   ohne Änderung. Details zu jeder Option stehen weiter unten.
7. Wechseln Sie zum Reiter **Info** und aktivieren Sie **Beim Start anzeigen**
   sowie **In Seitenleiste anzeigen**.
8. Klicken Sie auf **Starten**. Öffnen Sie anschließend **ElektroCoach** in der
   Seitenleiste und folgen Sie dem Einrichtungsassistenten.

Der Einrichtungsassistent prüft alle Voraussetzungen der Reihe nach und zeigt
für jeden Schritt einen echten Status. Er lässt sich erst abschließen, wenn
alle erforderlichen Prüfungen bestanden sind.

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `log_level` | `info` | Ausführlichkeit der Protokolle. Für Fehlersuche `debug`. |
| `ollama_url` | `http://a0d7b954-ollama:11434` | Adresse der Ollama-App. Bleibt unverändert, wenn die Ollama-App aus diesem Repository installiert wurde. |
| `ollama_model` | `qwen2.5:1.5b` | Lokales Modell. Kleinere Modelle sind auf dem Raspberry Pi 4 deutlich schneller. |
| `ollama_enabled` | `true` | Lokale KI verwenden. Ausschalten ist möglich; Gemini übernimmt dann mehr Aufgaben. |
| `ollama_unload_after_seconds` | `900` | Modell nach dieser Zeit ohne Anfrage aus dem Arbeitsspeicher entladen. |
| `gemini_enabled` | `false` | Google Gemini (Free Tier) verwenden. Erst einschalten, wenn ein API-Schlüssel vorliegt. |
| `gemini_api_key` | *(leer)* | Ihr persönlicher Gemini-Schlüssel. Er wird nur im Backend gespeichert und niemals an den Browser gesendet. |
| `gemini_model` | `gemini-2.0-flash` | Modellname. ElektroCoach prüft die Verfügbarkeit über die aktuelle API. |
| `gemini_daily_request_budget` | `200` | Harte Obergrenze für Gemini-Anfragen pro Tag. Bei Erreichen pausiert ElektroCoach die Aufgabe. |
| `ha_notifications_enabled` | `true` | Benachrichtigungen über Home Assistant senden. |
| `notify_service` | *(leer)* | Zieldienst, z. B. `notify.mobile_app_mein_handy`. Leer bedeutet: Standarddienst verwenden. |
| `auto_repair_enabled` | `true` | Sichere, risikoarme Fehlerbehebungen automatisch ausführen. |
| `storage_warning_percent` | `90` | Ab dieser Belegung erscheint eine Warnung. |
| `storage_critical_percent` | `95` | Ab dieser Belegung pausiert ElektroCoach Hintergrundaufgaben. |
| `backup_enabled` | `true` | Automatische Sicherungen erstellen. |
| `backup_interval_hours` | `24` | Abstand zwischen automatischen Sicherungen. |
| `backup_keep` | `7` | Anzahl der aufbewahrten Sicherungen. |
| `backup_dir` | `/share/elektrocoach/backups` | Zielordner. Liegt bewusst außerhalb von `/data`, damit die Sicherungen ein Deinstallieren überstehen. |
| `monitoring_interval_seconds` | `60` | Abstand der Systemprüfung. |
| `seed_demo_data` | `false` | Nur für Tests: Beispieldaten anlegen. Im Normalbetrieb ausgeschaltet lassen. |
| `ocr_language` | `deu+eng` | Sprachen für die Texterkennung. |

## Sicherung und Wiederherstellung

Sicherungen liegen standardmäßig unter `/share/elektrocoach/backups`. Über das
Samba-Add-on erreichen Sie diesen Ordner von einem Windows-PC und können die
Dateien zusätzlich auf einen externen Datenträger kopieren. Das ist wichtig,
weil Sicherungen auf derselben microSD-Karte nicht vor einem Defekt der Karte
schützen.

Die Liste der Sicherungen liegt als `index.json` im selben Ordner und nicht in
der Datenbank. So bleibt die Übersicht auch nach einer Wiederherstellung
vollständig, und die automatische Sicherung, die vor jeder Wiederherstellung
angelegt wird, bleibt sichtbar und kann zurückgespielt werden.

## Datenschutz

- Lokale Aufgaben bleiben vollständig auf dem Gerät (Ollama).
- Externe Anfragen gehen ausschließlich an Google Gemini, nur wenn Gemini
  aktiviert ist und nur mit den für die Aufgabe nötigen Textausschnitten.
- Die Oberfläche zeigt an, wenn Inhalte an Google Gemini übermittelt werden.
- Es gibt keine fest eingebauten Zugangsdaten und keine kostenpflichtigen
  Dienste. Bei erschöpftem Free-Tier-Kontingent pausiert ElektroCoach die
  Aufgabe, statt auf einen kostenpflichtigen Tarif zu wechseln.

## Speicherbedarf

Das Add-on benötigt auf der microSD-Karte:

- etwa 350 MB für das Image (inklusive Tesseract und den Sprachdaten),
- den Platz für Ihre importierten Dokumente und Seitenbilder,
- den Platz für die Sicherungen.

ElektroCoach prüft den freien Speicher vor jedem Import und vor jedem
Modell-Download. Bei kritischem Speicherstand pausiert es Hintergrundaufgaben
und meldet den Grund verständlich in der Oberfläche.
