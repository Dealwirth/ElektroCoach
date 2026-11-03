# Backup und Wiederherstellung

Die Lernplattform sichert ihre Daten selbst und nutzt zusätzlich die
Home-Assistant-Sicherung.

## Was gesichert wird

Ein Backup enthält die komplette Datenbank mit:

* importierten Dokumenten und Seitenzuordnungen,
* erkannten Texten,
* Themen und Wissensbereichen,
* Lernfragen und Antworten,
* Lernfortschritt, Fehlern und Stärken,
* Lernplänen,
* Prüfungsergebnissen,
* Schaltplanprojekten,
* Einstellungen.

Nicht enthalten sind die großen Originaldateien, weil sie sich erneut
importieren lassen. Dadurch bleibt jedes Backup klein und schnell.

## Backup im Reiter System anlegen

1. ElektroCoach → **System**.
2. Abschnitt **Backup**.
3. **Backup erstellen** klicken.
4. Der Name wird automatisch mit Datum und Uhrzeit gebildet, zum Beispiel
   `elektrocoach-20261103-061202-1234`.

Die Datei liegt im Add-on-Datenverzeichnis unter `backups/` und ist über den
Reiter **System** auflistbar. Sie ist zusätzlich über die Dateifreigabe
erreichbar, wenn `share` eingebunden ist.

## Automatische Sicherung

Home Assistant sichert Add-on-Daten mit, wenn eine Sicherung erstellt wird:

1. **Einstellungen → System → Sicherungen → Sicherung erstellen**.
2. **ElektroCoach** auswählen.
3. Speichern.

Richte unter **Einstellungen → System → Sicherungen** einen Zeitplan ein, damit
regelmäßig automatisch gesichert wird.

## Wiederherstellung

### Aus einem internen Backup

1. ElektroCoach → **System → Backup**.
2. Bei der gewünschten Datei **Wiederherstellen** klicken.
3. Bestätigen. Die Anwendung liest die Datenbank neu ein.

Wichtig: Vor der Wiederherstellung wird automatisch ein Sicherheitsbackup
angelegt. Es kann also nichts verloren gehen.

### Aus einer Home-Assistant-Sicherung

1. **Einstellungen → System → Sicherungen**.
2. Die gewünschte Sicherung wählen und **Wiederherstellen**.
3. **ElektroCoach** auswählen und bestätigen.
4. Nach der Wiederherstellung das Add-on starten.

## Schutz vor Datenverlust

* Die Datenbank läuft im **WAL-Modus**. Ein Stromausfall mitten im Schreiben
  beschädigt die Daten nicht.
* Alle Schreibvorgänge sind transaktional. Entweder wird ein Vorgang ganz oder
  gar nicht gespeichert.
* Der Import arbeitet in Schritten und merkt sich den Fortschritt. Nach einem
  Neustart kann er fortgesetzt werden.
* Vor jeder Wiederherstellung entsteht ein Sicherheitsbackup.

## Speicherplatz

Unter **System** steht der freie Speicher. Regeln:

* Der Import pausiert, wenn der freie Platz unter 512 MB fällt. So kann die
  Karte nicht volllaufen.
* Bei dauerhaft knappem Platz alte Backups löschen oder auf SSD umsteigen
  (siehe [SSD_MIGRATION.md](SSD_MIGRATION.md)).
* Backups lassen sich einzeln über den Reiter **System** löschen.

## Empfohlener Ablauf

1. Nach jedem großen Import ein Backup anlegen.
2. Zusätzlich wöchentlich eine Home-Assistant-Sicherung mit ElektroCoach.
3. Die Sicherungen an einem zweiten Ort ablegen, etwa auf einem NAS oder PC.
4. Vor jedem Add-on-Update ein Backup anlegen.
