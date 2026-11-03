# Aufzeichnungen importieren (Samsung Notes)

Die Plattform verarbeitet die Aufzeichnungen aus drei Lehrjahren: Handschrift,
digitale Texte, Formeln, Tabellen, Bilder und Schaltpläne. Der Import läuft im
Hintergrund und ist unterbrechbar.

## Unterstützte Formate

| Format | Verarbeitung |
| --- | --- |
| PDF (auch gescannt) | Jede Seite wird gerendert, Textebene gelesen, sonst OCR |
| Bilder (PNG, JPG, WEBP, TIFF, BMP, HEIC) | Direkte OCR |
| Samsung Notes Export `.sdoc`, `.snote`, `.sdocx` | Container wird geöffnet, Texte und eingebettete Bilder ausgelesen |
| ZIP-Sammlung | Alle enthaltenen Dateien werden wie einzeln behandelt |

Samsung Notes kann **nicht** direkt aus der App heraus gelesen werden. Der
offizielle Weg ist der Export. Die zwei Wege sind unten beschrieben.

## Weg A (empfohlen): Export als PDF

1. Samsung Notes auf dem Tablet oder Handy öffnen.
2. Notiz oder Ordner auswählen.
3. **Teilen / Menü → Als Datei speichern → PDF**.
4. Alle PDFs auf einen Computer oder auf das Gerät kopieren.
5. In ElektroCoach auf **Import** gehen, die Dateien auswählen, einen
   Sammlungsnamen eintragen (zum Beispiel `Lehrjahr 1`), **Import starten**.

Tipp: Für große Mengen zuerst alle PDFs in einen Ordner legen und den ganzen
Ordner auf einmal auswählen.

## Weg B: Sammlungs-Export

Samsung Notes speichert Sammlungen als `.sdoc` oder `.snote`. Diese Container
haben kein öffentlich dokumentiertes Format. ElektroCoach öffnet sie dennoch
und liest alles Verwertbare heraus:

1. Sammlung in Samsung Notes teilen und als Datei speichern.
2. Die `.sdoc`- oder `.snote`-Datei in ElektroCoach unter **Import** hochladen.
3. Der Importer holt Texte aus enthaltenen JSON-, XML- und HTML-Dateien und
   schickt eingebettete Bilder durch die OCR.
4. Was nicht sicher erkannt wird, wird als **zu prüfen** gekennzeichnet.

## Empfehlung für 200–300 Seiten

1. Alles zuerst als PDF exportieren (Weg A). Das ist die zuverlässigste Quelle.
2. In Blöcken importieren, etwa ein Lehrjahr pro Sammlung. Ein Block von
   50 bis 100 Seiten ist auf dem Pi 4 in wenigen Minuten durch.
3. Nach jedem Block **Themen analysieren** (Reiter **Lernen**) laufen lassen.
4. Den Fortschritt unter **Import** beobachten. Der Import läuft im Hintergrund
   weiter, auch wenn die Seite geschlossen wird.

## Was mit den Inhalten passiert

* Jede Seite wird als eigener Datensatz mit Seitenzahl und Zuordnung gespeichert.
  Die ursprüngliche Reihenfolge bleibt erhalten.
* Erkannter Text ist über die **Bibliothek** und die Suche (FTS5) auffindbar.
* Erkannte Inhalte werden in Abschnitte geteilt und Themen zugeordnet.
* Lernfragen verweisen auf die Quellseiten, damit jede Antwort nachvollziehbar ist.
* Die Originaldatei bleibt gespeichert, das Seitenbild ist in der Bibliothek sichtbar.
* **Zu prüfen** erscheint, wenn die OCR unsicher ist (Standard: Erkennungsgüte
  unter 70 % oder zu wenig Text). Solche Seiten lassen sich manuell korrigieren:
  Bibliothek → Seite öffnen → Text bearbeiten → speichern.

## Duplikate

Beim Import wird der Inhalt verglichen. Wird eine Seite zweimal gefunden,
wird sie als Dublette erkannt und nicht erneut aufgenommen. Die Meldung nennt
die betroffene Datei.

## Fehlerhafte Dateien

Nicht lesbare Dateien werden namentlich gemeldet und übersprungen. Der Import
läuft mit den übrigen Dateien weiter. Typische Ursachen sind passwortgeschützte
PDFs und beschädigte Dateien.

## OCR verbessern

* **OCR-Sprache**: `deu+eng` ist voreingestellt, `equ` (Formelzeichen) ist
  zusätzlich installiert.
* **OCR-Auflösung**: Standard 150 dpi. Bei kleinen Handschriften 200 bis
  300 dpi einstellen (Reiter **Einstellungen**). Höher bedeutet langsamer und
  mehr Speicherverbrauch.
* **KI für OCR** (optional): Schaltet Gemini-Vision für schwierige Handschrift
  und Schaltplanbilder zu. Nur sinnvoll mit API-Schlüssel, verbraucht
  Tageskontingent und sendet Seitenbilder an Google. Standardmäßig aus.
* Manuelle Korrektur bleibt immer möglich und hat Vorrang.

## Rechen- und Formelinhalte

Formeln werden als Text erkannt. Rechenaufgaben erzeugt die KI daraus, sofern
Ollama oder Gemini aktiv ist. Ohne KI entstehen Lückentext- und
Verständnisfragen aus den eigenen Unterlagen.
