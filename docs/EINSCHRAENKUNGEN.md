# Bekannte Einschränkungen

Ehrliche Übersicht. Nichts hier wird beschönigt.

## 1. ARM64 auf dem Raspberry Pi noch nicht live geprüft

Das Add-on-Basis-Image ist offiziell für `aarch64` und `amd64` verfügbar
(über das Image-Manifest bestätigt). Alle Python-Abhängigkeiten haben
ARM64-Unterstützung. Gebaut und gestartet wurde in dieser Umgebung jedoch nur
die **x86_64**-Variante.

Was das bedeutet: Der erste Build auf dem Pi dauert länger (15–30 Minuten) und
muss dort einmal erfolgreich durchlaufen. Wenn dabei ein Paket nicht baut,
steht die genaue Ursache im Add-on-Protokoll.

Empfehlung: Vor dem ersten Start ausreichend freien Speicher schaffen
(mindestens 4 GB auf der Karte).

## 2. Samsung Notes: kein direkter Zugriff

Samsung Notes hat kein offenes Dateiformat und keine öffentliche API. Ein
direktes Auslesen der App-Daten ist technisch nicht möglich.

Umgesetzt ist daher:

* Export als PDF (zuverlässig, empfohlen),
* Export als `.sdoc`/`.snote` (best effort, Format nicht dokumentiert).

Der `.sdoc`-Importer wurde mit einem realistischen Testbehälter geprüft, nicht
mit einem echten Samsung-Export. Enthält ein echter Export stark abweichende
Strukturen, liest der Importer trotzdem alle Text- und Bilddateien aus, weil er
den Container generisch durchsucht. Sicherheitsnetz: Nicht sicher Erkanntes
wird als "zu prüfen" markiert.

## 3. Handschrifterkennung: Güte schwankt

Tesseract erkennt gedruckten Text sehr gut, Handschrift je nach Schriftbild
unterschiedlich. Bei unsauberer Handschrift sinkt die Erkennungsgüte.

Gegenmaßnahmen:

* OCR-Auflösung erhöhen (200–300 dpi).
* Unsichere Seiten werden gekennzeichnet und sind korrigierbar.
* Optional Gemini-Vision zuschalten (bessere Handschrift, verbraucht
  Kontingent und sendet Seitenbilder an Google).

Eine Garantie für 100 % korrekte Handschrift gibt es bei keinem Verfahren.

## 4. Formeln und Tabellen

Einfache Formeln wie `U = (2*l*I*cos phi)/(kappa*A)` werden als Text erkannt.
Sehr verschachtelte Formeln und komplexe Tabellenstrukturen können falsch
umgebrochen werden. Die Quellseite bleibt immer sichtbar, sodass sich jeder
Inhalt gegenprüfen lässt.

## 5. Kostenloses Kontingent kann sich ändern

Die Angaben zu Gemini beziehen sich auf den Stand der Google-Dokumentation
(November 2026): Flash-Modelle kostenlos, rund 1.500 Anfragen pro Tag,
Pro-Modelle kostenpflichtig. Google kann diese Grenzen ändern.

ElektroCoach richtet **keine** Abrechnung ein und ruft keine kostenpflichtigen
Modelle auf. Wird das Kontingent knapp, weicht die App auf Ollama oder die
Offline-Verfahren aus.

## 6. Lokale KI-Qualität auf dem Pi 4

Modelle mit 3 Milliarden Parametern (`llama3.2:3b`, `qwen2.5:3b`) laufen auf
dem Pi 4 flüssig, sind aber deutlich schwächer als Cloud-Modelle. Für einfache
Erklärungen und Wiederholungsfragen reicht das. Bei anspruchsvollen
Fachfragen ist Gemini klar besser.

Große Modelle (ab 7B) sind auf dem Pi 4 nicht sinnvoll: zu langsam, zu viel
Speicherverbrauch.

## 7. Prüfungssimulation ist eine Orientierung

Die errechnete Bestehenswahrscheinlichkeit ist eine unverbindliche Schätzung
auf Basis der eigenen Antworten. Sie ist kein Ersatz für die offizielle
Prüfungsordnung und keine Vorhersage.

## 8. Schaltplan-Editor: Umfang

Der Editor deckt die gängigen Symbole und Schaltungen der Ausbildung ab
(24 Symbole, 15 Kategorien). Er ist kein vollständiger Ersatz für
professionelle Elektrodokumentation (etwa EPLAN). Nicht enthalten sind unter
anderem: Normblattverwaltung, automatische Klemmenpläne, Artikelstammdaten,
Projektversionierung.

## 9. Import großer Mengen dauert

200–300 Seiten werden in Blöcken verarbeitet, nicht alle gleichzeitig. Das
schont den Speicher. Ein Block mit 50–100 Seiten ist auf dem Pi 4 in wenigen
Minuten durch. Parallelität ist auf 1 gesetzt.

## 10. Ohne KI weniger Aufgabentypen

Ohne Ollama und Gemini entstehen Lückentext- und Verständnisfragen aus den
eigenen Unterlagen. Komplexe Rechenaufgaben mit vollständigem Rechenweg und
frei formulierte Erklärungen benötigen eine der beiden KIs.

## 11. MQTT-Sensoren brauchen einen Broker

Die Home-Assistant-Sensoren laufen über MQTT-Discovery. Ohne MQTT-Broker
(Standard: `core-mosquitto`) erscheinen keine Sensoren. Die Oberfläche selbst
funktioniert unabhängig davon.

## 12. Ein Benutzer

Die Anwendung ist für eine einzelne Person ausgelegt (den Auszubildenden).
Optional lässt sich ein Passwortschutz aktivieren. Mehrere getrennte Konten
sind nicht vorgesehen.
