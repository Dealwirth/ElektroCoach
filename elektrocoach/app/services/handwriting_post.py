"""Nachverarbeitung erkannter Handschrift.

Die Erkennung liefert gelegentlich fachlich falsche Zeichen (etwa ``0`` statt
``O``, ``l`` statt ``1``, fehlende Einheiten). Dieses Modul korrigiert nur
eindeutige Faelle und laesst alles andere unangetastet - es wird nie Inhalt
erfunden.

Zwei Bausteine:
  * Ein Fachlexikon Elektrotechnik: gebraeuchliche Woerter werden mit einer
    Toleranz auf die erkannten Woerter abgebildet (Tippfehler-Korrektur).
  * Regeln fuer Formeln und Einheiten: ``230 v`` -> ``230 V``, ``16a`` ->
    ``16 A``, ``rcd`` -> ``RCD``, Dezimalkomma-Vereinheitlichung.
"""

from __future__ import annotations

import re

# Gebraeuchliche Begriffe der Elektrotechnik (Energie- und Gebaeudetechnik).
# Dient nur als Korrekturvorschlag; erkannte Woerter werden nicht ersetzt,
# wenn sie schon im Lexikon stehen oder zu weit abweichen.
TERMS: tuple[str, ...] = (
    "Spannung", "Strom", "Widerstand", "Leistung", "Leitung", "Leiter",
    "Leitungsschutzschalter", "Schutzschalter", "Fehlerstromschutzschalter",
    "Fehlerstrom-Schutzschalter", "RCD", "FI-Schutzschalter", "Sicherung",
    "Schmelzsicherung", "Sicherungsautomat", "Motorschutzschalter",
    "Schuetz", "Schütz", "Relais", "Schalter", "Taster", "Wechselschalter",
    "Kreuzschalter", "Serienschalter", "Dimmer", "Transformator", "Trafo",
    "Drehstrom", "Wechselstrom", "Gleichstrom", "Drehstrommotor",
    "Asynchronmotor", "Synchronmotor", "Kondensator", "Spule", "Diode",
    "Transistor", "Gleichrichter", "Netzteil", "Phase", "Außenleiter",
    "Neutralleiter", "Schutzleiter", "Erdung", "Potentialausgleich",
    "Querschnitt", "Aderleitung", "Kabel", "Leitungsquerschnitt",
    "Spannungsfall", "Spannungsabfall", "Stromstärke", "Kurzschluss",
    "Überlast", "Überlastung", "Bemessungsstrom", "Bemessungsspannung",
    "Bemessungsleistung", "Wirkleistung", "Blindleistung", "Scheinleistung",
    "Wirkungsgrad", "Frequenz", "Phasenverschiebung", "Leistungsfaktor",
    "Ohmsches", "Ohmsche", "Gesetz", "Reihenschaltung", "Parallelschaltung",
    "Sternschaltung", "Dreieckschaltung", "Sternpunkt", "Schaltplan",
    "Stromlaufplan", "Schaltzeichen", "Klemme", "Klemmenbezeichnung",
    "Stromkreis", "Steckdose", "Schutzkontaktsteckdose", "Verteiler",
    "Unterverteilung", "Zählerschrank", "Sicherungskasten", "Leuchte",
    "Lampe", "Glühlampe", "LED", "Leuchtstofflampe", "Vorschaltgerät",
    "Bewegungsmelder", "Dämmerungsschalter", "Zeitschaltuhr", "Thermostat",
    "Wärmepumpe", "Heizung", "Solar", "Photovoltaik", "Wechselrichter",
    "Batterie", "Akku", "Ladegerät", "Speicher", "Zähler", "Stromzähler",
    "Messgerät", "Multimeter", "Spannungsprüfer", "Wattmeter", "Amperemeter",
    "Voltmeter", "Messung", "Prüfung", "Messung", "Norm", "VDE", "DIN",
    "Schutzmaßnahme", "Schutzklasse", "Isolation", "Isolationsmessung",
    "Schutzisolierung", "Schutzkleinspannung", "Fehlerstrom", "Ableitstrom",
    "Berührungsspannung", "Berührungsstrom", "Abschaltung", "Absicherung",
    "Nennspannung", "Nennstrom", "Nennleistung", "Anschluss", "Anschlussklemme",
    "Außenleiter", "Mantelleitung", "Installationsrohr", "Dose", "Abzweigdose",
    "Verbindung", "Lötverbindung", "Klemmverbindung", "Schraubverbindung",
    "Widerstandsmessung", "Durchgangsprüfung", "Spannungsmessung",
    "Strommessung", "Leistungsmessung", "Frequenzmessung",
)

# Haeufige Einheiten in der Schreibweise, die erkannt werden soll.
UNIT_CANON: dict[str, str] = {
    "v": "V", "mv": "mV", "kv": "kV",
    "a": "A", "ma": "mA", "ka": "kA",
    "w": "W", "kw": "kW", "mw": "mW", "mwatt": "mW",
    "ohm": "Ω", "ω": "Ω", "kohm": "kΩ", "kω": "kΩ", "mohm": "MΩ", "mω": "MΩ",
    "hz": "Hz", "khz": "kHz", "mhz": "MHz",
    "f": "F", "uf": "µF", "µf": "µF", "nf": "nF", "pf": "pF", "mf": "mF",
    "h": "H", "mh": "mH", "µh": "µH",
    "wh": "Wh", "kwh": "kWh", "mwh": "MWh",
    "va": "VA", "kva": "kVA",
    "mm2": "mm²", "mm²": "mm²", "mmq": "mm²",
    "mm": "mm", "cm": "cm", "m": "m", "km": "km",
    "°c": "°C", "c": "°C",
    "s": "s", "ms": "ms", "min": "min",
    "nm": "Nm", "rpm": "min⁻¹", "u/min": "min⁻¹",
    "db": "dB", "pa": "Pa", "bar": "bar",
}

# Abkuerzungen, die in Grossbuchstaben erscheinen muessen.
ACRONYMS: dict[str, str] = {
    "rcd": "RCD", "fi": "FI", "ls": "LS", "lsa": "LSS", "lss": "LSS",
    "vde": "VDE", "din": "DIN", "en": "EN", "iec": "IEC",
    "pe": "PE", "n": "N", "l1": "L1", "l2": "L2", "l3": "L3",
    "led": "LED", "uv": "UV", "hv": "HV", "nv": "NV",
    "dc": "DC", "ac": "AC", "pv": "PV", "ev": "EV",
    "tn": "TN", "tt": "TT", "it": "IT",
    "pue": "PUE", "ems": "EMS", "rcds": "RCD",
}

_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]*")
_TERM_LOOKUP = {term.lower(): term for term in TERMS}


def _levenshtein(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        best = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            if value < best:
                best = value
        if best > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _correct_word(word: str) -> str:
    """Zieht ein Wort auf einen Fachbegriff, wenn es nah genug dran ist."""
    lowered = word.lower()
    if lowered in _TERM_LOOKUP:
        return _TERM_LOOKUP[lowered]
    if len(lowered) < 5:
        return word
    limit = 1 if len(lowered) < 8 else 2
    best_term: str | None = None
    best_distance = limit + 1
    for term_lower, term in _TERM_LOOKUP.items():
        if abs(len(term_lower) - len(lowered)) > limit:
            continue
        distance = _levenshtein(lowered, term_lower, limit)
        if distance < best_distance:
            best_distance = distance
            best_term = term
    return best_term or word


def correct_terms(text: str) -> str:
    return _WORD_RE.sub(lambda m: _correct_word(m.group(0)), text)


def _fix_unit(match: re.Match[str]) -> str:
    number, unit = match.group(1), match.group(2)
    canonical = UNIT_CANON.get(unit.lower(), unit)
    return f"{number} {canonical}"


# Zahl direkt vor einer Einheit: "230v", "16 a", "1,5mm2".
_NUM_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)?)\s*("
    + "|".join(sorted((re.escape(u) for u in UNIT_CANON), key=len, reverse=True))
    + r")(?![A-Za-z0-9])"
)


def fix_units(text: str) -> str:
    return _NUM_UNIT_RE.sub(_fix_unit, text)


def _fix_acronym(match: re.Match[str]) -> str:
    word = match.group(0)
    return ACRONYMS.get(word.lower(), word)


_ACRONYM_RE = re.compile(r"\b[A-Za-z]{1,4}\b")


def fix_acronyms(text: str) -> str:
    return _ACRONYM_RE.sub(_fix_acronym, text)


def normalize_formulas(text: str) -> str:
    """Vereinheitlicht Formelzeichen und Rechenoperatoren."""
    # Mal-Zeichen
    text = re.sub(r"(?<=\d)\s*[x×]\s*(?=\d)", " × ", text)
    # Dezimalkomma: "1.5" -> "1,5" (deutsche Schreibweise), aber nicht bei Tausenderpunkt
    text = re.sub(r"(?<=\d)\.(?=\d{1,3}\b)", ",", text)
    # Doppelte Operatoren zusammenziehen
    text = re.sub(r"\s*([=+\-*/×:])\s*", r" \1 ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def postprocess(text: str, level: str = "standard") -> str:
    """Wendet die Nachbearbeitung an.

    ``level``: ``"off"`` (nur Leerraum), ``"light"`` (Einheiten, Akronyme),
    ``"standard"`` (zusaetzlich Fachbegriffe) oder ``"formula"`` (zusaetzlich
    Formel-Normalisierung).
    """
    if not text:
        return text
    if level == "off":
        return text
    result = fix_units(text)
    result = fix_acronyms(result)
    if level in ("standard", "formula"):
        result = correct_terms(result)
    if level == "formula":
        result = normalize_formulas(result)
    return result
