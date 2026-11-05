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

# ---------------------------------------------------------------------------
# Formeln lesbar machen
# ---------------------------------------------------------------------------
# Bildmodelle geben Formeln gern als LaTeX aus. Fuer die Anzeige wird das in
# uebliche Schreibweise uebersetzt: \frac{a}{b} -> a / b, \cdot -> ·, ^{2} -> ².

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "µ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_SYMBOLS = {
    "cdot": "·", "times": "×", "div": ":", "pm": "±", "mp": "∓",
    "approx": "≈", "neq": "≠", "leq": "≤", "geq": "≥", "le": "≤", "ge": "≥",
    "rightarrow": "→", "to": "→", "infty": "∞", "percent": "%",
    "degree": "°", "circ": "°", "square": "²", "squared": "²",
    "ldots": "…", "dots": "…", "quad": " ", "qquad": " ", "sqrt": "√",
}
_SUPERSCRIPTS = str.maketrans("0123456789+-()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾ⁿ")
_SUBSCRIPTS = str.maketrans("0123456789+-()", "₀₁₂₃₄₅₆₇₈₉₊₋₍₎")


def _read_group(text: str, start: int) -> tuple[str, int]:
    """Liest eine geschweifte Gruppe ab ``start`` (Zeichen dort muss ``{`` sein)."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return text[start + 1 :], len(text)


def _strip_latex(text: str, depth: int = 0) -> str:
    """Ersetzt LaTeX-Befehle durch lesbare Zeichen. Rekursiv wegen \\frac."""
    if depth > 8:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 < len(text) and not text[index + 1].isalpha():
                following = text[index + 1]
                if following in "()[]":
                    # Gruppierungsklammern: nur die Klammer entfernen.
                    pass
                elif following in ",;:! ":
                    # LaTeX-Leerraum (\\, \\; \\: \\! \\ ). Nie ein Komma.
                    out.append(" ")
                else:
                    out.append(following)
                index += 2
                continue
            name = ""
            cursor = index + 1
            while cursor < len(text) and text[cursor].isalpha():
                name += text[cursor]
                cursor += 1
            argument = ""
            if cursor < len(text) and text[cursor] == "{":
                argument, cursor = _read_group(text, cursor)
            if name in ("frac", "dfrac", "tfrac"):
                numerator = _strip_latex(argument, depth + 1)
                denominator = ""
                if cursor < len(text) and text[cursor] == "{":
                    denominator, cursor = _read_group(text, cursor)
                denominator = _strip_latex(denominator, depth + 1)
                out.append(f"{numerator.strip()} / {denominator.strip()}")
            elif name in ("text", "mathrm", "operatorname", "mathbf", "mathit"):
                out.append(_strip_latex(argument, depth + 1))
            elif name == "sqrt":
                inner = _strip_latex(argument, depth + 1) if argument else ""
                out.append(f"√({inner})" if inner else "√")
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name])
            elif name in _GREEK:
                out.append(_GREEK[name])
            elif name in ("left", "right", "displaystyle", "limits", "nolimits"):
                pass
            elif name == "" and argument == "":
                out.append("\\")
            else:
                out.append(argument or "")
            index = cursor
            continue
        out.append(char)
        index += 1
    return "".join(out)


_LATEX_MARKERS = ("\\", "\\(", "\\)", "\\[", "\\]")


def strip_latex(text: str) -> str:
    """Uebersetzt LaTeX-Reste in uebliche Schreibweise.

    Nur anwenden, wenn wirklich LaTeX vorkommt; sonst bleibt der Text gleich.
    """
    if not text or not any(marker in text for marker in _LATEX_MARKERS):
        return text
    result = _strip_latex(text)
    # Hoch- und Tiefstellungen in Sonderzeichen wandeln, sofern einfach.
    result = re.sub(r"\^\{([0-9+\-()]{1,3})\}", lambda m: m.group(1).translate(_SUPERSCRIPTS), result)
    result = re.sub(r"\^([0-9+\-()])", lambda m: m.group(1).translate(_SUPERSCRIPTS), result)
    result = re.sub(r"_\{([0-9+\-()]{1,3})\}", lambda m: m.group(1).translate(_SUBSCRIPTS), result)
    result = re.sub(r"_([0-9])", lambda m: m.group(1).translate(_SUBSCRIPTS), result)
    # Uebrig gebliebene Klammern um Formeln entfernen: "\( x \)" -> "x".
    result = result.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    result = result.replace("$", "")
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result


def _fix_decimal(match: re.Match[str]) -> str:
    """``1.5`` -> ``1,5``, aber ``1.000`` (Tausenderpunkt) bleibt."""
    before, after = match.group(1), match.group(2)
    if len(after) == 3 and before:
        # "1.000" oder "12.500": wahrscheinlich Tausenderpunkt.
        return f"{before}.{after}"
    return f"{before},{after}"


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
    """Zieht ein Wort auf einen Fachbegriff, wenn es nah genug dran ist.

    Woerter mit Ziffern oder Formelzeichen bleiben unangetastet: ``L1``,
    ``mm2`` oder ``U12`` sind keine Tippfehler.
    """
    lowered = word.lower()
    if lowered in _TERM_LOOKUP:
        return _TERM_LOOKUP[lowered]
    if any(char.isdigit() for char in word):
        return word
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


def _spacing(line: str) -> str:
    """Setzt Leerzeichen um Rechenoperatoren, ohne Zeichen zu veraendern.

    Bewusst zeilenweise: ``\\s`` wuerde sonst Zeilenumbrueche verschlucken und
    die Seitenstruktur zerstoeren.
    """
    line = re.sub(r"\s*=\s*", " = ", line)
    line = re.sub(r"\s*([·×])\s*", r" \1 ", line)
    # Strichrechnung nur mit Ziffernbezug; "FI-Schutzschalter" bleibt zusammen.
    line = re.sub(r"(?<=\d)\s*([+\-])\s*(?=[\dA-Za-zÄÖÜäöüß(])", r" \1 ", line)
    line = re.sub(r"(?<=[\dA-Za-zÄÖÜäöüß)])\s*([+\-])\s*(?=\d)", r" \1 ", line)
    line = re.sub(r"\s*/\s*", " / ", line)
    line = re.sub(r"[ \t]{2,}", " ", line)
    return line.strip()


def normalize_formulas(text: str) -> str:
    """Vereinheitlicht Formelzeichen und Rechenoperatoren (zeilenweise)."""
    lines = []
    for raw_line in text.split("\n"):
        line = strip_latex(raw_line)
        # Ausgeschriebene Formelzeichen in Zeichen wandeln.
        line = re.sub(r"\brho\b", "ρ", line)
        line = re.sub(r"\bOhm\b", "Ω", line)
        line = re.sub(r"\bomega\b", "Ω", line)
        # Spezifischer Widerstand: das Zeichen wird oft als "h" gelesen
        # (R = h * l / A). Nur in dieser Formelstellung ersetzen.
        line = re.sub(r"\bh\b(?=\s*[·×*]\s*[lL]\b)", "ρ", line)
        line = re.sub(r"\b[hg]\b(?=\s*[·×*]\s*[lL]\s*/)", "ρ", line)
        # Mal-Zeichen zwischen Zahlen.
        line = re.sub(r"(?<=\d)\s*[x×]\s*(?=\d)", " × ", line)
        # Dezimalkomma: "1.5" -> "1,5" (Tausenderpunkt bleibt).
        line = re.sub(r"(\d)\.(\d{1,4})\b", _fix_decimal, line)
        lines.append(_spacing(line))
    return "\n".join(lines)


def postprocess(text: str, level: str = "standard") -> str:
    """Wendet die Nachbearbeitung an.

    ``level``: ``"off"`` (nur Leerraum), ``"light"`` (Einheiten, Akronyme),
    ``"standard"`` (zusaetzlich Fachbegriffe) oder ``"formula"`` (zusaetzlich
    Formel-Normalisierung samt LaTeX-Uebersetzung).
    """
    if not text:
        return text
    if level == "off":
        return text
    # LaTeX-Reste immer uebersetzen: sie sind nie gewollter Inhalt, sondern
    # nur eine andere Schreibweise der Formel.
    text = strip_latex(text)
    result = fix_units(text)
    result = fix_acronyms(result)
    if level in ("standard", "formula"):
        result = correct_terms(result)
    if level == "formula":
        result = normalize_formulas(result)
    return result
