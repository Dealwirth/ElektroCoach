# ElektroCoach Ollama

Lokaler Ollama-Server für ElektroCoach. Stellt kleine Sprachmodelle auf dem
Raspberry Pi 4 bereit. Alles bleibt auf dem Gerät: keine Cloud, keine Kosten,
keine Anmeldung.

## Wozu diese App

ElektroCoach nutzt zwei KI-Wege. Die lokale Ollama-App übernimmt die einfachen,
häufigen Aufgaben, weil sie kostenlos und schnell genug ist:

- Klassifizierung und Schlagworterkennung
- kurze Zusammenfassungen
- Lernkarten und einfache Übungsaufgaben
- Vorverarbeitung importierter Dokumente
- Zusammenstellung relevanter Wissensausschnitte
- Vorbereitung der Anfragen an Google Gemini

Die anspruchsvollen Aufgaben (Handschrift, Bilder, Schaltpläne, schwierige
Freitextbewertung) übernimmt Google Gemini im kostenlosen Kontingent. Beide
Wege sind unabhängig: Fällt Ollama aus, arbeitet ElektroCoach weiter und meldet
den Zustand in der Systemübersicht.

## Installation

1. Öffnen Sie in Home Assistant **Einstellungen → Add-ons → Add-on-Store**.
2. Klicken Sie auf **ElektroCoach Add-ons** und dann auf **ElektroCoach Ollama**.
3. Klicken Sie auf **Installieren**. Der erste Start dauert einige Minuten,
   weil die Ollama-Anwendung einmalig heruntergeladen wird.
4. Wechseln Sie zum Reiter **Konfiguration** und prüfen Sie die Modellliste.
5. Klicken Sie auf **Starten**.
6. Prüfen Sie im Reiter **Protokoll**, ob eine Zeile wie
   `[ollama] ensuring model: qwen2.5:1.5b` erscheint. Der Modell-Download läuft
   im Hintergrund; der Server ist schon währenddessen erreichbar.

Ein Port-Mapping ist nicht nötig. ElektroCoach erreicht die App über das
interne Docker-Netz unter dem Namen `a0d7b954-ollama`.

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `models` | `["qwen2.5:1.5b"]` | Modelle, die beim Start vorhanden sein müssen. |
| `keep_alive` | `5m` | Wie lange ein Modell nach der letzten Anfrage im Arbeitsspeicher bleibt. `0` entlädt sofort, ein größerer Wert spart Ladezeit. |
| `num_parallel` | `1` | Gleichzeitige Anfragen. Auf dem Raspberry Pi 4 ist `1` die richtige Wahl. |
| `max_loaded_models` | `1` | Gleichzeitig geladene Modelle. `1` schützt den Arbeitsspeicher. |
| `context_length` | `2048` | Kontextlänge in Token. Größere Werte brauchen deutlich mehr RAM. |

Alle Optionen werden beim Start tatsächlich angewendet. Die Werte werden im
Protokoll ausgegeben, sodass Sie die Wirkung nachvollziehen können.

## Modellwahl auf dem Raspberry Pi 4

Das Gerät hat 8 GB Arbeitsspeicher, die es sich mit Home Assistant und allen
anderen Apps teilt. Für die lokale KI stehen davon realistisch etwa 2–3 GB zur
Verfügung. Daraus ergibt sich:

| Modell | Größe | Einschätzung |
|---|---|---|
| `qwen2.5:1.5b` | ca. 1 GB | Empfohlen. Gute deutsche Texte, vertretbare Geschwindigkeit. |
| `qwen2.5:3b` | ca. 2 GB | Möglich, aber langsamer. Nur verwenden, wenn genug RAM frei ist. |
| `llama3.2:1b` | ca. 1 GB | Alternative für kurze Aufgaben. |

Laden Sie nicht mehrere große Modelle gleichzeitig. Jedes zusätzliche Modell
belegt Speicher auf der microSD-Karte und im Arbeitsspeicher.

## Speicherplatz

Modelle liegen unter `/data/ollama/models` und bleiben über Neustarts erhalten.
Rechnen Sie mit 1–2 GB pro Modell. ElektroCoach prüft vor einem Modell-Download
den freien Speicher und meldet, wenn der Platz nicht reicht.

## Verhalten bei Neustart

Nach einem Neustart von Home Assistant startet die App automatisch. Bereits
heruntergeladene Modelle werden nicht erneut geladen; nur die im Feld `models`
eingetragenen Modelle werden geprüft und bei Bedarf ergänzt.

## Fehlerbehebung

**Die App startet nicht.**
Öffnen Sie den Reiter **Protokoll**. Erscheint
`unsupported architecture`, läuft die App auf einer nicht unterstützten
Plattform. Erscheint `FATAL: ollama binary not found after extraction`, ist der
Download unterbrochen worden. Starten Sie die App neu; sie lädt die Datei dann
erneut.

**ElektroCoach meldet „Ollama nicht erreichbar“.**
Prüfen Sie zuerst, ob diese App läuft (Reiter **Info**, Status **Gestartet**).
Prüfen Sie dann in der ElektroCoach-Konfiguration, ob `ollama_url` auf
`http://a0d7b954-ollama:11434` steht. Der Hostname `a0d7b954-ollama` ist fest
mit dieser App verknüpft.

**Der Raspberry Pi reagiert träge.**
Senken Sie `context_length` auf `1024` und stellen Sie sicher, dass
`max_loaded_models` auf `1` steht. Verwenden Sie ein kleineres Modell.
