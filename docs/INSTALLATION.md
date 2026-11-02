# Installation und Inbetriebnahme

Diese Anleitung führt Schritt für Schritt durch die Installation von
ElektroCoach auf einem Raspberry Pi 4 mit Home Assistant OS.

Sie brauchen keine Programmierkenntnisse. Führen Sie die Schritte in der
angegebenen Reihenfolge aus.

## Voraussetzungen

- Raspberry Pi 4 mit 8 GB RAM
- Home Assistant OS, bereits eingerichtet und erreichbar
- microSD-Karte mit mindestens 10 GB freiem Speicher
- Internetzugang für die Installation und den Modell-Download
- Optional: ein Google-Konto für Gemini (kostenlose Nutzung)

## Schritt 1 – Add-on-Repository eintragen

**Warum:** Home Assistant muss wissen, woher es die ElektroCoach-Add-ons laden
soll.

1. Öffnen Sie Home Assistant.
2. Gehen Sie zu **Einstellungen → Add-ons → Add-on Store**.
3. Klicken Sie oben rechts auf die drei Punkte **⋮** und wählen Sie
   **Repositories**.
4. Tragen Sie im Feld **Add repository** diese Adresse ein:

   ```text
   https://github.com/Dealwirth/ElektroCoach
   ```

5. Klicken Sie auf **Hinzufügen** und schließen Sie das Fenster.

**Erfolgskontrolle:** Im Add-on Store erscheinen zwei neue Einträge:
**ElektroCoach** und **ElektroCoach Ollama**.

**Bei einem Fehler:** Erscheint kein Eintrag, prüfen Sie die Internetverbindung
und die Schreibweise der Adresse. Nach einem erneuten Laden der Seite
(**Browser aktualisieren**) erscheint die Liste meist korrekt.

## Schritt 2 – Speicher prüfen

**Warum:** Die Notizen umfassen 200–300 Seiten. Der Import und das KI-Modell
benötigen freien Speicher.

1. Gehen Sie zu **Einstellungen → System → Speicher**.
2. Prüfen Sie den **freien Speicher**.

**Erfolgskontrolle:** Mindestens 10 GB frei.

**Bei einem Fehler:** Ist weniger Speicher frei, löschen Sie alte
Home-Assistant-Backups unter **Einstellungen → System → Backups**. ElektroCoach
warnt zusätzlich selbst, wenn der Speicher knapp wird.

## Schritt 3 – Ollama-Add-on installieren

**Warum:** Ollama stellt die lokale KI bereit. Sie ist kostenlos und arbeitet
ohne Internet.

1. Gehen Sie zu **Einstellungen → Add-ons → Add-on Store**.
2. Öffnen Sie **ElektroCoach Ollama**.
3. Klicken Sie auf **Installieren** und warten Sie, bis die Installation
   abgeschlossen ist.
4. Klicken Sie auf **Starten**.
5. Aktivieren Sie **Beim Start automatisch starten** und **Wächter**.

**Erfolgskontrolle:** Der Status wechselt auf **Läuft**. Im Protokoll steht,
dass das Modell `qwen2.5:1.5b` geladen wird. Der erste Start dauert einige
Minuten, weil das Modell heruntergeladen wird.

**Bei einem Fehler:** Steht im Protokoll ein Downloadfehler, prüfen Sie die
Internetverbindung und starten Sie das Add-on neu. Der Download wird fortgesetzt.

## Schritt 4 – ElektroCoach-Add-on installieren

**Warum:** Dies ist die Hauptanwendung.

1. Gehen Sie zu **Einstellungen → Add-ons → Add-on Store**.
2. Öffnen Sie **ElektroCoach**.
3. Klicken Sie auf **Installieren** und warten Sie, bis die Installation
   abgeschlossen ist.
4. Wechseln Sie zum Reiter **Konfiguration** und prüfen Sie die wichtigsten
   Werte:

   | Option | Empfohlener Wert | Bedeutung |
   |---|---|---|
   | `ollama_url` | `http://a0d7b954-ollama:11434` | Adresse des Ollama-Add-ons |
   | `ollama_model` | `qwen2.5:1.5b` | Lokales Modell |
   | `gemini_enabled` | `false` | Erst nach Schlüsseleingabe aktivieren |
   | `gemini_api_key` | leer | Wird sicher gespeichert |
   | `backup_dir` | `/share/elektrocoach/backups` | Ziel der Sicherungen |

5. Klicken Sie auf **Speichern**, dann auf **Starten**.
6. Aktivieren Sie **Beim Start automatisch starten** und **Wächter**.

**Erfolgskontrolle:** Der Status ist **Läuft**. In der Seitenleiste erscheint
der Eintrag **ElektroCoach**.

**Bei einem Fehler:** Öffnen Sie den Reiter **Protokoll** und lesen Sie die
letzten Zeilen. Häufige Ursachen sind ein falscher `ollama_url` oder fehlender
Speicher.

## Schritt 5 – Einrichtungsassistent durchlaufen

**Warum:** Der Assistent prüft alle Voraussetzungen und zeigt genau, was noch
fehlt.

1. Öffnen Sie **ElektroCoach** in der Seitenleiste.
2. Wechseln Sie zum Bereich **Einrichtung**.
3. Klicken Sie auf **Alle Schritte prüfen**.
4. Arbeiten Sie die angezeigten Punkte ab. Jeder Schritt zeigt Status, Meldung
   und – falls nötig – eine konkrete Anleitung.

Erwartete Status:

- **Erfolgreich:** Ressourcen, Speicher, Datenbank, Berechtigungen,
  Dokumentenverarbeitung, Funktionstest.
- **Benutzereingabe erforderlich:** Verbindung zu Home Assistant (wird im
  Add-on-Betrieb automatisch erfüllt) und KI-Verbindungen (erst nach Schritt 6).
- **Warnung:** Ollama, Gemini und Benachrichtigungen, solange sie nicht
  eingerichtet sind.

**Wichtig:** Der Assistent zeigt erst dann „abgeschlossen“, wenn keine
Pflichtprüfung mehr fehlschlägt. Ein grüner Abschluss bei offenen Pflichtpunkten
ist nicht möglich.

## Schritt 6 – Gemini einrichten (optional)

**Warum:** Gemini bearbeitet schwierige Aufgaben und erkennt Handschrift. Die
Nutzung im kostenlosen Kontingent ist möglich. Es entstehen keine Kosten.

1. Öffnen Sie <https://aistudio.google.com/app/apikey> und erstellen Sie einen
   **kostenlosen** API-Schlüssel.
2. Öffnen Sie in Home Assistant **ElektroCoach → Einstellungen**.
3. Tragen Sie den Schlüssel im Feld **Gemini-API-Schlüssel** ein.
4. Klicken Sie auf **Gemini-Verbindung testen**.

**Erfolgskontrolle:** Die Meldung „Verbindung erfolgreich“ erscheint, und das
Kontingent wird angezeigt.

**Bei einem Fehler:** Erscheint „Der Gemini-API-Schlüssel wurde von Google
abgelehnt“, prüfen Sie, ob Sie den Schlüssel vollständig kopiert haben.

**Hinweis:** ElektroCoach wechselt niemals automatisch auf einen
kostenpflichtigen Tarif. Ist das Tageskontingent aufgebraucht, pausiert die
Aufgabe und Sie werden informiert.

## Schritt 7 – Erste Notizen importieren

**Warum:** Die Wissensdatenbank und das Lernen bauen auf Ihren eigenen Notizen
auf.

1. Öffnen Sie **ElektroCoach → Dokumentenimport**.
2. Klicken Sie auf **Dateien auswählen** und wählen Sie PDF-Dateien oder Fotos
   Ihrer Notizen.
3. Starten Sie den Import und warten Sie, bis der Status **verarbeitet**
   erscheint.

**Erfolgskontrolle:** Unter **Wissensdatenbank** erscheinen Einträge mit Quelle
und Seitenzahl.

**Bei einem Fehler:** Markierte Stellen mit unsicherer Erkennung sind
gekennzeichnet. Prüfen Sie diese Stellen und bestätigen Sie sie bei Bedarf.

## Schritt 8 – Erste Lernaufgabe

1. Öffnen Sie **ElektroCoach → Lernen**.
2. Wählen Sie ein Fach und starten Sie eine Aufgabe.
3. Beantworten Sie die Aufgabe und lesen Sie die Bewertung mit Musterlösung.

## Updates

Ein Update verlieren keine Lernfortschritte und keine Dokumente. Alle Daten
liegen dauerhaft unter `/data`.

1. Gehen Sie zu **Einstellungen → Add-ons → ElektroCoach**.
2. Erscheint **Aktualisieren**, klicken Sie darauf.
3. Warten Sie, bis das Add-on neu startet.

**Vor einem Update empfohlen:** Erstellen Sie im Bereich **Backups** eine
Sicherung.

## Backup und Wiederherstellung

1. Öffnen Sie **ElektroCoach → Backups**.
2. Klicken Sie auf **Backup erstellen**.
3. Zum Wiederherstellen wählen Sie ein Backup und klicken auf
   **Wiederherstellen**. Bestätigen Sie die Sicherheitsabfrage.

**Wichtig:** Vor jeder Wiederherstellung legt ElektroCoach automatisch eine
Sicherung an. Sie können die Wiederherstellung damit rückgängig machen.

**Hinweis:** Bewahren Sie zusätzlich eine Kopie der Backups außerhalb der
microSD-Karte auf (z. B. auf einem PC). Der Zielordner ist `/share/elektrocoach/backups`.

## Deinstallation

1. Gehen Sie zu **Einstellungen → Add-ons → ElektroCoach**.
2. Klicken Sie auf **Deinstallieren**.

**Datenverhalten:** Ihre Daten unter `/data` werden bei der Deinstallation
entfernt. Erstellen Sie vorher ein Backup, wenn Sie die Daten behalten möchten.
Nach einer erneuten Installation können Sie das Backup wiederherstellen.

## Fehlerbehebung

| Symptom | Maßnahme |
|---|---|
| Ollama nicht erreichbar | Add-on **ElektroCoach Ollama** starten und `ollama_url` prüfen |
| Gemini abgelehnt | API-Schlüssel in den Einstellungen prüfen |
| Kontingent erschöpft | Aufgabe pausiert; nach Mitternacht (pazifische Zeit) erneut versuchen |
| Speicher knapp | Alte Backups löschen |
| Add-on startet nicht | Protokoll-Reiter öffnen und letzte Zeilen lesen |

Weitere Diagnosen finden Sie in **ElektroCoach → Fehlerdiagnose**. Dort erstellt
ElektroCoach auf Wunsch einen vollständigen Fehlerbericht mit konkreten
Schritten.
