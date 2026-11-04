# Änderungen

Kurze Übersicht der Versionen. Die Anwendung meldet ihre Version in
**Einstellungen → System** und in der Kopfzeile.

## 1.1.0

### KI pro Anfrage wählen
- Umschalter **Auto / Ollama / Gemini** im Tutor und in jeder Übungsaufgabe.
- Wahl wird im Browser gespeichert.
- Neue Einstellung *„Gewählten Dienst strikt verwenden"*: bei Ausfall keine
  stille Ausweichung, sondern eine klare Meldung.

### Kontrollierter Internetzugriff für das lokale Modell
- Nur bei Bedarf (Normen, Förderungen, Preise, Vorschriften).
- Nur verlässliche Quellen (Wikipedia, VDE, DIN, BDEW, BAFA, DGUV …).
- Treffer werden auf Passgenauigkeit geprüft, sonst verworfen.
- Jede übernommene Aussage wird mit `[WEB-n]` belegt und verlinkt.

### Antworten mit dem Stift
- Handschriftliche Antworten in Übungen und Prüfungen.
- Erkennung im Browser, sonst über die Gemini-Bildanalyse.
- Erkannter Text bleibt korrigierbar.

### Oberfläche
- Neue Signaturfarbe (Indigo) statt Standard-Blau.
- Kopfband mit Lernstandsanzeige auf der Übersicht.

### Behoben
- Der KI-Modus in den Einstellungen schrieb `local` / `cloud`, der Server
  erwartet `local_only` / `cloud_only`. Die Auswahl wirkte deshalb nicht.

## 1.0.11
- Dokumentation zu Supervisor-Fallstricken ergänzt.

## 1.0.10
- Supervisor-Antwort wird korrekt ausgewertet.

## 1.0.9
- Supervisor-Diagnose (Rechte, Token, Add-on-Liste).

## 1.0.0
- Erste vollständige Fassung: Import, Bibliothek, Wissensbasis, Lernen,
  Lernplan, Prüfungssimulation, Schaltplan-Editor, Home-Assistant-Anbindung,
  Backup und Wiederherstellung.
