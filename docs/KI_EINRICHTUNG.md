# Ollama und Gemini einrichten

ElektroCoach nutzt zwei KI-Systeme, die sich ergänzen. Beide sind optional.
Ohne sie bleibt die Plattform voll nutzbar.

* **Ollama (lokal)**: einfache Aufgaben, kostenlos, offline, schont die Cloud.
* **Gemini (Cloud)**: schwierige Handschrift, Bildanalyse, anspruchsvolle
  Fachfragen. Kostenloses Kontingent.

Der Modus **KI-Modus** in den Einstellungen steuert das Verhalten:

| Modus | Bedeutung |
| --- | --- |
| `auto` | Lokal zuerst, Cloud nur wenn nötig (Standard) |
| `local_only` | Nur Ollama, keine Daten verlassen das Haus |
| `cloud_only` | Nur Gemini |
| `off` | Keine KI, nur die Verfahren aus den eigenen Unterlagen |

## Teil 1: Ollama auf dem Raspberry Pi

Ollama läuft **nicht** im Add-on selbst, sondern als eigener Dienst. Auf Home
Assistant OS ist der einfachste Weg das Community-Add-on.

### Modelle für den Pi 4 mit 8 GB

Diese Modelle sind getestet und sinnvoll. Alle passen in den Arbeitsspeicher,
wenn nicht mehrere gleichzeitig laufen.

| Modell | Größe | Bewertung |
| --- | --- | --- |
| `llama3.2:3b` | ~2 GB | Standard. Guter Kompromiss aus Tempo und Qualität |
| `qwen2.5:3b` | ~2 GB | Gute deutsche Texte, oft etwas besser als llama3.2 |
| `phi4-mini` | ~2,5 GB | Gute Fachfragen, etwas langsamer |
| `gemma2:2b` | ~1,6 GB | Schnell, wenn Speicher knapp ist |
| `llama3.2:1b` | ~1,3 GB | Sehr schnell, nur für einfache Aufgaben |

Nicht empfohlen auf dem Pi 4: Modelle ab 7B. Sie sind zu langsam und
verdrängen andere Dienste aus dem Speicher.

### Installation

1. In Home Assistant **Einstellungen → Add-ons → Add-on-Store**.
2. Nach **Ollama** suchen und installieren.
3. Add-on starten. Im Reiter **Konfiguration** ein Modell eintragen, zum
   Beispiel `llama3.2:3b`.
4. Im Add-on-Log die Meldung abwarten, dass der Server bereit ist.

### Modelle vorladen

Nach dem ersten Start das Modell einmal laden, sonst dauert die erste Anfrage
sehr lange. Im Ollama-Add-on-Terminal:

```
ollama pull llama3.2:3b
ollama list
```

### Mit ElektroCoach verbinden

1. ElektroCoach → **Einstellungen**.
2. **Ollama aktivieren** einschalten.
3. **Ollama-URL**: `http://homeassistant.local:11434` oder
   `http://<IP-des-Pi>:11434`.
4. **Ollama-Modell**: `llama3.2:3b`.
5. **Speichern**. Der Status erscheint unter **System**.

## Teil 2: Google Gemini (kostenlos)

Gemini übernimmt schwierige Handschrift, Bildanalyse und komplexe Fragen.
Wichtig: Es wird **nur das kostenlose Kontingent** genutzt. Die App richtet
keine Abrechnung ein und ruft keine kostenpflichtigen Modelle auf.

### API-Schlüssel erzeugen

1. `https://aistudio.google.com/app/apikey` im Browser öffnen.
2. Mit dem Google-Konto anmelden.
3. **Create API key** wählen und den Schlüssel kopieren.

Der Schlüssel beginnt meist mit `AIza...`. Er ist kostenlos, solange das
kostenlose Kontingent reicht.

### In ElektroCoach eintragen

1. ElektroCoach → **Einstellungen**.
2. **Gemini-API-Schlüssel** einfügen.
3. **Gemini Textmodell**: `gemini-2.5-flash`.
4. **Gemini Bildmodell**: `gemini-2.5-flash`.
5. **Speichern**.

Der Schlüssel wird verschlüsselt in `/data` gespeichert und **nie** an das
Frontend oder an Dritte gesendet. In der Oberfläche erscheint er nur als
`********`.

### Kostenloses Kontingent und Grenzen

* Kostenlos verfügbar sind die Flash-Modelle. ElektroCoach prüft die Liste zur
  Laufzeit und bevorzugt `gemini-flash-latest`, danach `gemini-3.5-flash`,
  `gemini-3-flash-preview`, `gemini-2.5-flash`, `gemini-flash-lite-latest` und
  `gemini-2.5-flash-lite`. Pro-Modelle sind kostenpflichtig und werden nie
  verwendet.
* Google stellt Modelle regelmäßig ab oder benennt sie um. ElektroCoach prüft
  das gewählte Modell gegen die aktuelle Liste und wechselt bei HTTP 404
  (abgestellt) oder HTTP 503 (überlastet) automatisch auf das nächste Modell.
  Ein überlastetes Modell wird zwei Minuten lang zuletzt probiert, damit die
  Wartezeit nicht bei jeder Anfrage erneut entsteht.
* Übliche Grenze: **1.500 Anfragen pro Tag** für Flash-Modelle. Die Grenze kann
  sich ändern; sie steht in der Google-Dokumentation.
* ElektroCoach begrenzt sich zusätzlich selbst über **Gemini-Tageslimit**
  (Standard 450 Anfragen). Das lässt Sicherheitsabstand.
* Bei Überschreitung (HTTP 429) wartet die App kurz und weicht dann auf Ollama
  aus. Ist beides nicht möglich, arbeiten die Ersatzverfahren weiter.

### Datenschutz

* Standardmäßig werden **keine Seitenbilder** an Google gesendet.
* Bilder gehen nur raus, wenn **KI für OCR** aktiviert wird. Diese Option ist
  bewusst aus.
* Textanfragen senden nur den nötigen Ausschnitt, nicht das ganze Dokument.
* Unter **System → KI** ist jederzeit sichtbar, wann welche KI genutzt wurde.

## Ausfallverhalten

Die Plattform funktioniert in jedem Fall weiter:

| Situation | Verhalten |
| --- | --- |
| Ollama aus, Gemini aus | Fragen und Bewertung aus den eigenen Unterlagen, Ergebnisse als "zu prüfen" markiert |
| Ollama aus, Gemini an | Cloud übernimmt |
| Ollama an, Gemini aus | Lokal übernimmt |
| Gemini-Kontingent erschöpft | Automatisch lokal oder offline |
| Kein Internet | Rein lokal und offline |

## Prüfen, ob alles läuft

Reiter **System** öffnen. Dort stehen:

* Verfügbarkeit von Ollama und Gemini.
* Genutztes Tageskontingent.
* Die letzten Fehler mit Ursache.

## Empfehlung

Für den Alltag genügt `llama3.2:3b` in Modus `auto` plus ein Gemini-Schlüssel.
Damit läuft der normale Lernbetrieb lokal und kostenlos, und nur schwierige
Aufgaben gehen an die Cloud.
