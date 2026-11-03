# Umstieg von microSD auf SSD

Der Pi 4 läuft mit SSD deutlich schneller und langlebiger. Für den Dauerbetrieb
mit Import und OCR ist eine SSD klar zu empfehlen.

Die Anwendung muss dabei nicht angepasst werden. Sie speichert alles in `/data`
und erkennt den Speicherort zur Laufzeit.

## Variante A (empfohlen): Home-Assistant-Sicherung einspielen

1. Auf der microSD-Installation eine vollständige Sicherung erstellen:
   **Einstellungen → System → Sicherungen → Sicherung erstellen**, alle Inhalte
   auswählen.
2. Die Sicherungsdatei herunterladen und auf einen PC kopieren.
3. SSD an den Pi anschließen, Home Assistant OS neu installieren (siehe
   offizielle Anleitung für „Install Home Assistant OS" mit SSD-Boot).
4. Nach dem ersten Start die Sicherung über
   **Einstellungen → System → Sicherungen → Sicherung hochladen**
   einspielen.
5. ElektroCoach startet mit allen Daten.

## Variante B: Nur ElektroCoach-Daten umziehen

Wenn nur die Lernplattform umziehen soll:

1. In ElektroCoach unter **System** ein Backup erstellen.
2. Die Datei aus `/data/backups/` herunterladen.
3. Nach dem SSD-Umzug das Add-on installieren und das Backup über
   **System → Backup → Wiederherstellen** einspielen.

## Variante C: Datenordner auf SSD auslagern (ohne Neuinstallation)

Home Assistant OS erlaubt das Verschieben des Datenordners auf einen
angeschlossenen Datenträger:

1. **Einstellungen → System → Speicher**.
2. **Datenverschiebung** wählen und den Datenträger auswählen.
3. Warten, bis der Vorgang abgeschlossen ist. Home Assistant startet neu.
4. Prüfen, dass ElektroCoach läuft und die Dokumente sichtbar sind.

## Was die Anwendung unterstützt

* **Kein fester Pfad.** Der Speicherort kommt aus der Umgebung
  (`ELEKTROCOACH_DATA`, im Add-on `/data`). Ein Umzug ist transparent.
* **Automatische Verzeichnisse.** Benötigte Unterordner werden beim Start
  angelegt, falls sie fehlen.
* **WAL-Datenbank.** Sicher bei unerwartetem Stromausfall.
* **Speicherüberwachung.** Die Oberfläche zeigt freien Platz, der Import
  pausiert bei zu wenig Platz.

## Nach dem Umzug prüfen

1. Reiter **System**: freier Speicher wird angezeigt, Datenbank ist „ok".
2. Reiter **Bibliothek**: alle Dokumente vorhanden.
3. Reiter **Lernen**: Fortschritt und fällige Wiederholungen stimmen.
4. Ein neues Backup anlegen und wiederherstellen, um den Ablauf zu testen.

## Hinweise

* Nur SSDs mit USB-3-Gehäuse und UASP-Unterstützung verwenden.
* Ausreichend dimensionieren: 128 GB oder mehr, da Importe und Seitenbilder
  Platz brauchen.
* Vor jedem Umzug ein Backup anlegen. Der Umzug selbst ist unkritisch, aber
  ein Backup kostet nur wenige Sekunden.
