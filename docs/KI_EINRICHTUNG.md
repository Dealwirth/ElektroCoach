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

### Automatische Einrichtung (empfohlen)

ElektroCoach kann das Ollama-Add-on selbst installieren, starten und die
richtige Adresse eintragen. Das spart die manuellen Schritte oben.

1. ElektroCoach → **Einstellungen → KI-Dienste**.
2. Im Bereich **Ollama automatisch einrichten** auf
   **Ollama installieren & starten** klicken.
3. Warten, bis die Meldung erscheint, dass das Add-on läuft. Die Adresse wird
   dabei automatisch in **Ollama-URL** übernommen.
4. Im Feld **Modell herunterladen** ein Modell eintragen (z. B.
   `llama3.2:3b`) und **Herunterladen** klicken.

Voraussetzungen und Grenzen:

* Die automatische Einrichtung braucht den Supervisor, also Home Assistant OS
  oder Supervised. Auf einer reinen Docker-Installation ohne Supervisor ist die
  Schaltfläche deaktiviert; dann die manuelle Einrichtung oben verwenden.
* Es wird ausschließlich das kostenlose Community-Add-on **Ollama**
  installiert. Es entstehen keine Kosten und keine Abrechnung.
* Der erste Modell-Download ist mehrere hundert MB groß und dauert auf dem Pi
  einige Minuten. Der Fortschritt ist im Add-on-Log sichtbar.

### Wenn "Ollama nicht installiert" erscheint, obwohl es läuft

Die Erkennung liest die Add-on-Liste am Supervisor. Meldet die Oberfläche
„nicht installiert", zuerst die Diagnose aufrufen:

```
GET /api/system/supervisor
```

Die Antwort zeigt in einem Aufruf, ob der Token gültig ist, welche Rechte das
Add-on hat und was der Supervisor zu den einzelnen Routen antwortet. Häufige
Ursachen:

* `hassio_api` oder `hassio_role: manager` fehlen in `config.yaml`. Dann lehnt
  der Supervisor `/addons` mit 403 ab. (Seit Version 1.0.7 sind beide gesetzt.)
* Die Antwort des Supervisors wurde nicht ausgepackt. Der Supervisor liefert
  `{"result": "ok", "data": {...}}`; wer die Schlüssel oben liest, sieht eine
  leere Liste. (Seit Version 1.0.10 behoben.)

### Wenn Ollama "500 Internal Server Error" meldet

Der Ollama-Server startet, antwortet aber auf jede Anfrage mit HTTP 500. Im
Add-on-Log steht dann:

```
llama_init_from_model: quantized V cache requires flash_attn to be enabled
```

Ursache: Im Ollama-Add-on ist `OLLAMA_KV_CACHE_TYPE` auf `q8_0` gesetzt, aber
`OLLAMA_FLASH_ATTENTION` ist `0`. Der quantisierte KV-Cache funktioniert nur mit
aktivierter Flash-Attention. Lösung: In der Add-on-Konfiguration
`OLLAMA_FLASH_ATTENTION` auf `1` setzen, das Add-on neu starten und die Anfrage
wiederholen. Der verkleinerte KV-Cache spart Speicher auf dem Pi 4 und ist
sinnvoll, sobald Flash-Attention aktiv ist.

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

## KI-Nachbearbeitung erkannter Texte

Nach dem Import kann ElektroCoach unsicher erkannte Seiten mit der KI
nachbearbeiten. Die Nachbearbeitung korrigiert OCR-Fehler, Formeln und
Einheiten und verknüpft die Quellen neu.

* **Einstellungen → Import**: **Nach dem Import automatisch nachbearbeiten**
  startet die Nachbearbeitung direkt nach einem Import.
* **Import-Seite**: Der Bereich **KI-Nachbearbeitung erkannter Texte** startet
  und überwacht die Nachbearbeitung manuell. Der Fortschritt ist sichtbar, ein
  Abbruch ist jederzeit möglich.
* Standardmäßig läuft die Nachbearbeitung **nur lokal** über Ollama. Erst mit
  **Nachbearbeitung darf Gemini nutzen** (`refine_use_cloud`) geht sie an die
  Cloud.
* Ist keine KI erreichbar, bleibt der Originaltext unverändert erhalten und die
  Seite weiterhin als „zu prüfen" markiert. Es gehen keine Inhalte verloren.

## KI pro Anfrage wählen

Der Modus oben gilt als Grundeinstellung. Zusätzlich lässt sich **für jede
einzelne Anfrage** wählen, welcher Dienst antwortet. Der Umschalter sitzt im
Tutor und in jeder Übungsaufgabe:

```
[ Auto ] [ Ollama ] [ Gemini ]            [ Web ]
```

| Knopf | Wirkung |
| --- | --- |
| Auto | Grundeinstellung: lokal zuerst, Cloud nur bei Bedarf |
| Ollama | Nur das lokale Modell, auch wenn Gemini verfügbar wäre |
| Gemini | Nur die Cloud, auch wenn Ollama verfügbar wäre |
| Web | Erlaubt dem lokalen Modell, im Internet nachzuschlagen |

Die Wahl wird im Browser gespeichert und gilt weiter, bis du sie änderst.

**Strikt oder ausweichend:** Standardmäßig weicht ElektroCoach aus, wenn der
gewählte Dienst nicht antwortet (z. B. Ollama aus, dann Gemini). Soll die Wahl
stattdessen strikt gelten, in den Einstellungen unter **KI-Dienste** die
Option *„Gewählten Dienst strikt verwenden"* aktivieren. Dann erscheint bei
Ausfall eine klare Meldung statt einer stillen Ausweichung.

## Internet für das lokale Modell

Das lokale Modell kann im Internet nachschlagen, wenn es etwas nicht sicher
weiß. Das ist **ausgeschaltet, bis du es einschaltest**, und auch dann nur
unter Bedingungen:

| Regel | Bedeutung |
| --- | --- |
| Nur bei Bedarf | Im Modus „Auto“ wird nur bei aktuellen Angaben gesucht: Normen (DIN/VDE), Förderungen, Preise, Vorschriften. Mit „Web“ am Umschalter wird immer gesucht. |
| Nur verlässliche Adressen | Wikipedia, VDE, DIN, BDEW, BAFA, DGUV, Bundesregierung. Andere Adressen nur, wenn *„Auch nicht amtliche Adressen zulassen"* aktiv ist. |
| Nur passende Daten | Jeder Treffer wird gegen deine Frage geprüft. Passt er nicht, wird er verworfen – das Modell sieht ihn dann nicht. |
| Immer mit Quelle | Jede übernommene Aussage wird im Text mit `[WEB-1]` belegt. Unter der Antwort stehen die Quellen mit Link. |

Einstellungen dazu: **KI-Dienste → Internet für das lokale Modell**.

## Antworten mit dem Stift

Offene und Rechenaufgaben lassen sich handschriftlich beantworten – mit Stift,
Finger oder Maus. Der Umschalter über dem Antwortfeld heißt *„Mit Stift
schreiben"*.

Ablauf:

1. Schreibe auf die Fläche.
2. *„Handschrift in Text umwandeln"* drücken.
3. Der erkannte Text erscheint im Antwortfeld. **Prüfe und korrigiere ihn**,
   bevor du bewertest.

Die Erkennung läuft in dieser Reihenfolge:

| Stufe | Wann | Voraussetzung |
| --- | --- | --- |
| Browser | Immer zuerst | Browser mit Handwriting-API (z. B. Chrome) und Stifteingabe |
| Gemini-Bildanalyse | Wenn der Browser nichts erkennt | Gemini-Schlüssel und *„Bilder an die Cloud senden"* aktiv |
| Keine | Wenn beides fehlt | Die App sagt es klar; bitte tippen |

Unsicher erkannte Stellen werden im Text nicht erfunden. Ist das Ergebnis
unbrauchbar, bleibt das Feld leer und eine Meldung erscheint.

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
