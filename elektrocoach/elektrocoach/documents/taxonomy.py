"""Subject/topic taxonomy for the German "Elektroniker für Energie- und
Gebäudetechnik" curriculum.

The taxonomy is used to sort imported notes and to tag generated questions.
Classification is deterministic (keyword scoring) so it works with no AI at all;
the AI layer can refine it afterwards but is never required.
"""

from __future__ import annotations

import re
import unicodedata

SUBJECTS: dict[str, list[str]] = {
    "Elektrotechnische Grundlagen": [
        "ohmsches gesetz", "ohmsche", "spannung", "strom", "widerstand", "leistung",
        "elektrische ladung", "kirchhoff", "reihenschaltung", "parallelschaltung",
        "spannungsteiler", "stromteiler", "arbeit", "energie", "wirkungsgrad",
        "elektrisches feld", "kondensator", "kapazität", "magnetismus", "induktion",
        "spule", "induktivität",
    ],
    "Wechselstrom": [
        "wechselstrom", "wechselspannung", "frequenz", "phasenverschiebung",
        "blindwiderstand", "impedanz", "scheinleistung", "blindleistung",
        "wirkleistung", "cos phi", "leistungsfaktor", "effektivwert", "sinus",
    ],
    "Drehstrom": [
        "drehstrom", "drehstromnetz", "außenleiter", "neutralleiter", "sternschaltung",
        "dreieckschaltung", "phasenleiter", "verkettete spannung", "400 v", "230 v",
        "schieflast", "drehfeld",
    ],
    "Schutzmaßnahmen": [
        "schutzmaßnahme", "schutzerdung", "schutzleiter", "fehlerstrom",
        "fi-schalter", "rcd", "fehlerstromschutzschalter", "schutzisolierung",
        "schutzkleinspannung", "potentialausgleich", "körperstrom", "berührungsspannung",
        "abschaltbedingung", "vde 0100", "schutzklasse", "isolation",
    ],
    "Leitungsberechnung": [
        "leitungsberechnung", "leitungswiderstand", "spannungsfall", "querschnitt",
        "strombelastbarkeit", "verlegeart", "häufung", "länge der leitung",
        "spezifischer widerstand", "kappa", "stromdichte", "absicherung",
    ],
    "Installationsschaltungen": [
        "installationsschaltung", "ausschaltung", "wechselschaltung",
        "kreuzschaltung", "serienschaltung", "stromstoßschaltung",
        "tasterschaltung", "schaltplan", "installationsplan", "verteiler",
        "sicherung", "leitungsschutzschalter", "ls-schalter", "klemmleiste",
    ],
    "Motoren und Antriebe": [
        "motor", "drehstrommotor", "asynchronmotor", "synchronmotor",
        "käfigläufer", "schleifringläufer", "stern-dreieck", "sanftanlauf",
        "frequenzumrichter", "schütz", "motorschutz", "bemessungsstrom",
        "drehzahl", "schlupf", "anlaufstrom",
    ],
    "Steuerungs- und Regelungstechnik": [
        "steuerung", "regelung", "sps", "speicherprogrammierbar", "schützschaltung",
        "selbsthaltung", "verriegelung", "folgeschaltung", "signalfluss",
        "regelkreis", "sollwert", "istwert", "regler", "sensor", "aktor",
    ],
    "KNX und Gebäudeautomation": [
        "knx", "eib", "gebäudeautomation", "bussystem", "busleitung", "tastsensor",
        "aktorkanal", "linienkoppler", "bereichslinie", "physikalische adresse",
        "gruppenadresse", "ets",
    ],
    "Beleuchtung": [
        "beleuchtung", "leuchte", "lichtstrom", "lumen", "beleuchtungsstärke",
        "lux", "lichtausbeute", "leuchtstofflampe", "led", "vorschaltgerät",
        "farbtemperatur", "farbwiedergabe", "schattenwurf",
    ],
    "Kommunikationstechnik": [
        "kommunikationstechnik", "telefonanlage", "netzwerktechnik", "lan",
        "cat", "patchfeld", "routing", "ip-adresse", "dhcp", "schirmung",
        "twisted pair", "glasfaser", "ethernet", "vlan",
    ],
    "Netzwerktechnik": [
        "netzwerk", "switch", "router", "subnetz", "subnetzmaske", "dns",
        "gateway", "wlan", "access point", "poe", "kabeltester",
    ],
    "Photovoltaik": [
        "photovoltaik", "solar", "solarzelle", "wechselrichter", "pv-anlage",
        "einspeisung", "eigenverbrauch", "strings", "verschattung", "leistungsoptimierer",
        "batteriespeicher", "überschusseinspeisung",
    ],
    "Wärmepumpen": [
        "wärmepumpe", "heizstab", "cop", "jahresarbeitszahl", "sole", "luft-wasser",
        "heizkreis", "vorlauf", "rücklauf", "kältemittel", "verdichter",
    ],
    "Mess- und Prüftechnik": [
        "messgerät", "multimeter", "prüfgerät", "isolationsmessung", "r-iso",
        "durchgangsprüfung", "schleifenimpedanz", "messung", "oszi", "zangenamperemeter",
        "prüfprotokoll", "dgUV", "wiederholungsprüfung",
    ],
    "VDE und Normen": [
        "vde", "din", "norm", "vde 0100", "vde 0105", "vde 0298", "vde 0113",
        "betriebsmittel", "richtlinie", "dgUV v3", "tabelle", "normen",
    ],
    "Sicherheit und Arbeitsschutz": [
        "arbeitsschutz", "unfallverhütung", "fünf sicherheitsregeln",
        "freischalten", "erden und kurzschließen", "gefährdungsbeurteilung",
        "erste hilfe", "schutzausrüstung", "psa",
    ],
}

# Longest keywords first so that "vde 0100" wins over "vde".
_ALL_KEYWORDS: list[tuple[str, str]] = sorted(
    ((kw, subject) for subject, kws in SUBJECTS.items() for kw in kws),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def normalize(text: str) -> str:
    lowered = (text or "").lower()
    lowered = unicodedata.normalize("NFKD", lowered)
    lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    lowered = lowered.replace("ß", "ss")
    return re.sub(r"\s+", " ", lowered)


def classify(text: str) -> tuple[str | None, str | None, float]:
    """Return ``(subject, topic, confidence)`` for a text block.

    The topic is the keyword that scored highest. Confidence is a simple ratio
    that reflects how clearly one subject dominates.
    """

    haystack = normalize(text)
    if not haystack.strip():
        return None, None, 0.0
    scores: dict[str, int] = {}
    best_keyword: dict[str, str] = {}
    for keyword, subject in _ALL_KEYWORDS:
        if keyword in haystack:
            scores[subject] = scores.get(subject, 0) + 1
            best_keyword.setdefault(subject, keyword)
    if not scores:
        return None, None, 0.0
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    subject, top = ranked[0]
    total = sum(scores.values())
    confidence = round(top / total, 2) if total else 0.0
    topic = best_keyword.get(subject)
    return subject, topic, confidence


def subject_list() -> list[str]:
    return sorted(SUBJECTS.keys())
