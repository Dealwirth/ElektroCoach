# Handschrifterkennung (TrOCR)

ElektroCoach liest Handschrift mit einem lokalen neuronalen Netz (TrOCR) statt
mit Tesseract. Tesseract ist auf Druckschrift ausgelegt und liefert bei
deutscher Handschrift unbrauchbare Ergebnisse.

## Warum TrOCR

Gemessen an 40 echten handschriftlichen Zeilen aus dem Datensatz
`fhswf/german_handwriting` (Zeichenfehlerrate, CER – kleiner ist besser):

| Engine | mittlere CER | Median |
| --- | --- | --- |
| Tesseract `deu` | 52,1 % | 50,6 % |
| TrOCR (dieses Add-on) | 0,5 % | 0,0 % |

Robustheit über 120 echte Zeilen mit künstlich erschwerten Bedingungen:

| Bedingung | mittlere CER | p90 |
| --- | --- | --- |
| sauber | 1,53 % | 3,77 % |
| Schattenverlauf | 1,67 % | 4,46 % |
| 3° Schräglage | 2,23 % | 4,43 % |
| leichte Unschärfe | 1,38 % | 4,37 % |

## Modell

* `EpsilonGreedy/TrOCR_small_german_handwritten` (Lizenz afl-3.0),
  Basismodell `microsoft/trocr-small-handwritten`.
* Export nach ONNX, dynamisch auf int8 quantisiert: Encoder 23 MB, Decoder
  40 MB, zusammen rund 63 MB. Das Modell liegt im Image unter
  `/app/models/trocr-de` und wird **nicht** zur Laufzeit heruntergeladen.
* Läuft ausschließlich lokal und offline. Keine Cloud, kein API-Schlüssel.

Das größere Modell `fhswf/TrOCR_german_handwritten` wurde geprüft und
verworfen: 614 MB int8, rund 10-mal langsamer und mit 8,7 % CER schlechter
als das kleine Modell.

## Ablauf

1. **Vorverarbeitung:** Graustufen, Kontrastspreizung, Rauschunterdrückung.
2. **Zeilensegmentierung:** Horizontale Projektion der dunklen Bildpunkte,
   rein mit Pillow/NumPy (kein OpenCV – hält das Alpine-Image klein).
3. **Erkennung je Zeile:** Encoder + autoregressiver Decoder (ONNX Runtime).
   Das Bild wird seitenverhältnis-treu auf 384 × 384 gestaucht – so wurde das
   Modell trainiert. Auffüllen mit Weiß verschlechtert das Ergebnis drastisch
   (76 % CER statt 0,4 %).
4. **Nachbearbeitung:** Einheiten (`30ma` → `30 mA`), Akronyme (`rcd` → `RCD`),
   Fachbegriffe (Levenshtein-Abgleich) und Formeln.

## Einstellungen

| Option | Werte | Wirkung |
| --- | --- | --- |
| `ocr_engine` | `auto`, `trocr`, `tesseract` | `auto` nutzt TrOCR, wenn das Modell vorhanden ist, sonst Tesseract |
| `ocr_postprocess` | `off`, `light`, `standard`, `formula` | Umfang der Nachbearbeitung |
| `ocr_dpi` | 150–600 | Auflösung der Seitenbilder; 150 genügt dem Modell |
| `ocr_trocr_max_tokens` | 16–256 | Maximale Länge je Zeile |

## Laufzeit und Speicher

Die Erkennung läuft auf der CPU und braucht weder GPU noch Netz. Auf vier
Kernen (x86_64) dauert eine Zeile rund 400 ms, auf einem Raspberry Pi 4
mehrere Sekunden. Der Import läuft im Hintergrund-Worker; die Oberfläche
bleibt bedienbar. Ein eigenes Geschwindigkeitsprofil mit KV-Cache wurde
verworfen, weil es die Ergebnisse verfälschte.

## Grenzen

* Das Modell ist auf **Text** trainiert. Reine Formeln und Rechenzeichen
  (`×`, `=`, `√`) erkennt es weniger zuverlässig als Fließtext. Solche Seiten
  werden gekennzeichnet; die Korrektur-Ansicht in der Bibliothek erlaubt das
  Nachbessern.
* Sehr krakelige oder stark durchgestrichene Handschrift bleibt schwierig.
* Unsichere Ergebnisse (Konfidenz unter 70 %) werden zur Prüfung markiert.

## Fehlersuche

Der Endpunkt `GET /api/system/info` liefert unter `handwriting`:

```json
{
  "available": true,
  "dir": "/app/models/trocr-de",
  "missing": [],
  "dependencies": {"numpy": true, "onnxruntime": true, "tokenizers": true, "pillow": true},
  "engine": "auto",
  "postprocess": "standard"
}
```

Fehlt das Modell oder eine Abhängigkeit, steht dort `available: false` mit
Begründung. Der Pfad lässt sich mit `ELEKTROCOACH_TROCR_DIR` überschreiben.
