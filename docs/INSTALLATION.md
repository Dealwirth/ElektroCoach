# Installation und Einrichtung

Diese Anleitung führt von der leeren Home-Assistant-Installation bis zur
fertigen Lernplattform. Alle Schritte laufen im Browser. Ein Windows-PC ist
nicht nötig.

## Voraussetzungen

* Raspberry Pi 4 mit 8 GB RAM, Home Assistant OS (64 Bit).
* MicroSD-Karte mit mindestens 64 GB, später SSD empfohlen
  (siehe [SSD_MIGRATION.md](SSD_MIGRATION.md)).
* Internetzugang nur für die Installation und optional für Gemini. Der Betrieb
  läuft auch offline.

## 1. Add-on-Repository hinzufügen

1. Home Assistant öffnen.
2. **Einstellungen → Add-ons → Add-on-Store**.
3. Oben rechts auf **⋮** (drei Punkte) klicken, dann **Repositories**.
4. Diese Adresse eintragen und **Hinzufügen** wählen:

   ```
   https://github.com/Dealwirth/ElektroCoach
   ```

5. Fenster schließen. Die Liste wird neu geladen.

## 2. Add-on installieren

1. Im Add-on-Store nach **ElektroCoach** suchen.
2. **Installieren** klicken. Der erste Build dauert auf dem Pi 4 etwa
   15 bis 30 Minuten, weil die Oberfläche kompiliert und die Python-Pakete
   gebaut werden. Das ist normal.
3. Nach dem Build **Starten** klicken.

## 3. Oberfläche öffnen

Nach dem Start erscheint der Reiter **ElektroCoach** in der Seitenleiste.
Ein Klick öffnet die Weboberfläche im Ingress.

Falls der Reiter fehlt:

1. **Einstellungen → Add-ons → ElektroCoach**.
2. Reiter **Info** öffnen.
3. **In der Seitenleiste anzeigen** aktivieren.

Die Oberfläche läuft auch direkt auf Port 8099. Für den Zugriff von einem
anderen Gerät im Netzwerk muss der Port in der Add-on-Konfiguration unter
**Netzwerk** freigegeben werden. Im Normalfall genügt der Ingress-Zugang.

## 4. Erste Einrichtung

1. Reiter **Einstellungen** öffnen.
2. Optional den **Gemini-API-Schlüssel** eintragen
   (siehe [KI_EINRICHTUNG.md](KI_EINRICHTUNG.md)).
3. Optional **Ollama** aktivieren und die Modell-Adresse eintragen.
4. **Speichern** klicken.

Ohne KI-Schlüssel ist die Plattform voll nutzbar. Fragen werden dann aus den
eigenen Unterlagen erzeugt und als "zu prüfen" gekennzeichnet.

## 5. Aufzeichnungen importieren

Weiter mit [IMPORT_SAMSUNG_NOTES.md](IMPORT_SAMSUNG_NOTES.md).

## 6. Home-Assistant-Sensoren (optional)

1. **Einstellungen → Add-ons → ElektroCoach → Konfiguration**.
2. **MQTT aktivieren** einschalten, Broker `core-mosquitto` beibehalten.
3. **Speichern** und das Add-on **Neu starten**.
4. Nach ein bis zwei Minuten erscheinen die Sensoren
   `sensor.elektrocoach_*` in Home Assistant.

Benachrichtigungen: Im Feld **Benachrichtigungsdienst** den eigenen Dienst
eintragen, zum Beispiel `notify.mobile_app_mein_handy`.

## Aktualisierung

1. **Einstellungen → Add-ons → ElektroCoach**.
2. **Aktualisieren** klicken, sobald eine neue Version erscheint.
3. Die Daten bleiben in `/data` erhalten und werden mitgesichert.

## Deinstallation

Das Add-on entfernen löscht auch die Daten in `/data`. Vorher ein Backup
anlegen (siehe [BACKUP_WIEDERHERSTELLUNG.md](BACKUP_WIEDERHERSTELLUNG.md)).

## Fehlerbehebung

| Symptom | Ursache | Lösung |
| --- | --- | --- |
| Build bricht ab | Kein Internet oder kein Speicherplatz | Internet prüfen, in Home Assistant unter **Einstellungen → System → Speicher** Platz schaffen |
| Reiter fehlt | Seitenleiste nicht aktiviert | **Info → In der Seitenleiste anzeigen** aktivieren |
| Seite bleibt weiß | Oberfläche wurde nicht gebaut | Add-on neu installieren, Log auf Fehler prüfen |
| Sensoren fehlen | MQTT nicht aktiviert | **MQTT aktivieren** setzen und neu starten |
| Import sehr langsam | Erste OCR-Aufwärmphase | Import im Hintergrund laufen lassen, Fortschritt unter **Import** beobachten |

Das Add-on-Protokoll ist unter **Einstellungen → Add-ons → ElektroCoach →
Protokoll** sichtbar.
