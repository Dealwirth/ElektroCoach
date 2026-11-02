"""IEC-style symbol library.

The library is the **single source of truth** for symbol geometry: the web
canvas, the SVG export and the PDF export all render the same primitive list.
That guarantees that what the user sees on screen is exactly what is exported.

Coordinates are in grid units (1 unit = ``GRID_SIZE`` pixels, default 20 px).
Terminals are placed on grid intersections so that snapping always lines up with
a wire endpoint.

Primitive kinds (kept intentionally small so every renderer can handle them):

* ``line``     – ``x1, y1, x2, y2``
* ``rect``     – ``x, y, w, h`` (``filled`` optional)
* ``circle``   – ``cx, cy, r`` (``filled`` optional)
* ``polyline`` – ``points: [[x, y], ...]`` (``filled`` optional)
* ``text``     – ``x, y, text`` (``anchor``: start|middle|end)

The shapes follow the usual IEC 60617 / VDE-style representation used in German
electrical drawings (for example a resistor as a rectangle, not a zig-zag).
"""

from __future__ import annotations

from typing import Any

GRID_SIZE = 20


def _line(x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _rect(x: float, y: float, w: float, h: float, filled: bool = False) -> dict[str, Any]:
    return {"type": "rect", "x": x, "y": y, "w": w, "h": h, "filled": filled}


def _circle(cx: float, cy: float, r: float, filled: bool = False) -> dict[str, Any]:
    return {"type": "circle", "cx": cx, "cy": cy, "r": r, "filled": filled}


def _poly(points: list[list[float]], filled: bool = False) -> dict[str, Any]:
    return {"type": "polyline", "points": points, "filled": filled}


def _text(x: float, y: float, text: str, *, anchor: str = "middle",
          size: float = 0.45) -> dict[str, Any]:
    return {"type": "text", "x": x, "y": y, "text": text, "anchor": anchor, "size": size}


def _terminal(tid: str, x: float, y: float, *, kind: str = "passive",
              label: str | None = None) -> dict[str, Any]:
    return {"id": tid, "x": x, "y": y, "kind": kind, "label": label or tid}


# -- library -----------------------------------------------------------------

def _build_library() -> dict[str, dict[str, Any]]:
    symbols: dict[str, dict[str, Any]] = {}

    def add(symbol_id: str, name: str, category: str, width: float, height: float,
            terminals: list[dict[str, Any]], shapes: list[dict[str, Any]],
            *, default_label: str = "", description: str = "",
            keywords: list[str] | None = None) -> None:
        symbols[symbol_id] = {
            "id": symbol_id,
            "name": name,
            "category": category,
            "width": width,
            "height": height,
            "terminals": terminals,
            "shapes": shapes,
            "default_label": default_label,
            "description": description,
            "keywords": keywords or [],
        }

    # --- Passive components -------------------------------------------------
    add("resistor", "Widerstand", "Passive Bauelemente", 3, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5)],
        [_line(0, 0.5, 0.5, 0.5), _rect(0.5, 0, 2, 1), _line(2.5, 0.5, 3, 0.5)],
        default_label="R", description="Widerstand nach IEC (Rechteck).",
        keywords=["widerstand", "resistor", "ohm"])
    add("resistor_var", "Widerstand einstellbar", "Passive Bauelemente", 3, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5), _terminal("3", 1.5, 1.6)],
        [_line(0, 0.5, 0.5, 0.5), _rect(0.5, 0, 2, 1), _line(2.5, 0.5, 3, 0.5),
         _line(1.5, 1.0, 2.2, 1.6), _line(1.5, 1.6, 2.2, 1.0)],
        default_label="R", description="Einstellbarer Widerstand (Potentiometer).",
        keywords=["potentiometer", "einstellbar"])
    add("capacitor", "Kondensator", "Passive Bauelemente", 3, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5)],
        [_line(0, 0.5, 1.3, 0.5), _line(1.3, 0, 1.3, 1), _line(1.7, 0, 1.7, 1),
         _line(1.7, 0.5, 3, 0.5)],
        default_label="C", description="Kondensator (nicht gepolt).",
        keywords=["kondensator", "capacitor"])
    add("capacitor_pol", "Kondensator gepolt", "Passive Bauelemente", 3, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5)],
        [_line(0, 0.5, 1.3, 0.5), _line(1.3, 0, 1.3, 1), _poly([[1.4, 0], [1.4, 1], [2.0, 0.5]], filled=True),
         _line(2.0, 0.5, 3, 0.5), _text(0.9, -0.35, "+")],
        default_label="C", description="Gepolter Kondensator (Elektrolytkondensator).",
        keywords=["elko", "gepolt"])
    add("inductor", "Spule / Induktivität", "Passive Bauelemente", 4, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 4, 0.5)],
        [_line(0, 0.5, 0.5, 0.5), _poly([[0.5, 0.5], [0.7, 0.1], [1.1, 0.9], [1.5, 0.1],
                                          [1.9, 0.9], [2.3, 0.1], [2.7, 0.9], [3.1, 0.5], [3.5, 0.5]]),
         _line(3.5, 0.5, 4, 0.5)],
        default_label="L", description="Spule / Induktivität.",
        keywords=["spule", "induktivitaet", "drossel"])

    # --- Semiconductors -----------------------------------------------------
    add("diode", "Diode", "Halbleiter", 3, 1,
        [_terminal("a", 0, 0.5, label="Anode"), _terminal("k", 3, 0.5, label="Kathode")],
        [_line(0, 0.5, 1.2, 0.5), _poly([[1.2, 0], [1.2, 1], [2.0, 0.5]], filled=True),
         _line(2.0, 0, 2.0, 1), _line(2.0, 0.5, 3, 0.5)],
        default_label="V", description="Diode; Durchlassrichtung von A nach K.",
        keywords=["diode", "gleichrichter"])
    add("led", "Leuchtdiode", "Halbleiter", 3, 1.4,
        [_terminal("a", 0, 0.5, label="Anode"), _terminal("k", 3, 0.5, label="Kathode")],
        [_line(0, 0.5, 1.2, 0.5), _poly([[1.2, 0], [1.2, 1], [2.0, 0.5]], filled=True),
         _line(2.0, 0, 2.0, 1), _line(2.0, 0.5, 3, 0.5),
         _line(1.5, 1.05, 2.4, 1.35), _poly([[2.1, 1.32], [2.4, 1.35], [2.3, 1.1]], filled=True)],
        default_label="V", description="Leuchtdiode (LED).",
        keywords=["led", "leuchtdiode"])
    add("transistor_npn", "Transistor NPN", "Halbleiter", 3, 3,
        [_terminal("b", 0, 1.5, label="Basis"), _terminal("c", 3, 0, label="Kollektor"),
         _terminal("e", 3, 3, label="Emitter")],
        [_circle(1.8, 1.5, 1.5), _line(0, 1.5, 1.5, 1.5), _line(1.5, 0.5, 1.5, 2.5),
         _line(1.5, 1.1, 3, 0), _line(1.5, 1.9, 3, 3),
         _poly([[2.6, 2.9], [3, 3], [2.9, 2.6]], filled=True)],
        default_label="V", description="Bipolartransistor NPN.",
        keywords=["transistor", "npn"])
    add("transistor_pnp", "Transistor PNP", "Halbleiter", 3, 3,
        [_terminal("b", 0, 1.5, label="Basis"), _terminal("c", 3, 3, label="Kollektor"),
         _terminal("e", 3, 0, label="Emitter")],
        [_circle(1.8, 1.5, 1.5), _line(0, 1.5, 1.5, 1.5), _line(1.5, 0.5, 1.5, 2.5),
         _line(1.5, 1.1, 3, 0), _line(1.5, 1.9, 3, 3),
         _poly([[2.6, 0.1], [3, 0], [2.9, 0.4]], filled=True)],
        default_label="V", description="Bipolartransistor PNP.",
        keywords=["transistor", "pnp"])

    # --- Switching devices --------------------------------------------------
    add("switch", "Schalter (Ausschalter)", "Schaltgeräte", 3, 2,
        [_terminal("1", 0, 0), _terminal("2", 3, 0)],
        [_circle(0.15, 0, 0.15), _circle(2.85, 0, 0.15), _line(0, 0, 1.2, 0),
         _line(1.2, 0, 2.7, -1.0), _line(2.7, -1.0, 2.85, -0.15)],
        default_label="Q", description="Ausschalter, einpolig.",
        keywords=["schalter", "ausschalter"])
    add("switch_no", "Schließer (Kontakt)", "Schaltgeräte", 3, 2,
        [_terminal("1", 0, 0), _terminal("2", 3, 0)],
        [_line(0, 0, 0.6, 0), _line(2.4, 0, 3, 0), _line(0.6, 0, 2.2, -1.0),
         _circle(0.6, 0, 0.12), _circle(2.4, 0, 0.12)],
        default_label="K", description="Schließerkontakt (NO).",
        keywords=["schliesser", "kontakt", "no"])
    add("switch_nc", "Öffner (Kontakt)", "Schaltgeräte", 3, 2,
        [_terminal("1", 0, 0), _terminal("2", 3, 0)],
        [_line(0, 0, 0.6, 0), _line(2.4, 0, 3, 0), _line(2.4, 0, 0.8, -1.0),
         _line(0.6, 0, 0.6, -0.6), _circle(0.6, 0, 0.12), _circle(2.4, 0, 0.12)],
        default_label="K", description="Öffnerkontakt (NC).",
        keywords=["oeffner", "kontakt", "nc"])
    add("push_button_no", "Taster (Schließer)", "Schaltgeräte", 3, 2,
        [_terminal("1", 0, 0), _terminal("2", 3, 0)],
        [_line(0, 0, 0.6, 0), _line(2.4, 0, 3, 0), _line(0.6, 0, 2.4, 0),
         _line(1.5, 0, 1.5, -0.9), _line(0.9, -0.9, 2.1, -0.9),
         _circle(0.6, 0, 0.12), _circle(2.4, 0, 0.12)],
        default_label="S", description="Taster mit Schließerkontakt.",
        keywords=["taster", "schliesser"])
    add("changeover", "Wechselschalter", "Schaltgeräte", 3, 3,
        [_terminal("1", 0, 1.5), _terminal("2", 3, 0), _terminal("3", 3, 3)],
        [_line(0, 1.5, 1.2, 1.5), _line(1.2, 1.5, 2.7, 0.2),
         _line(3, 0, 2.7, 0.2), _line(3, 3, 2.7, 3),
         _circle(1.2, 1.5, 0.14)],
        default_label="Q", description="Wechselschalter (Umschalter).",
        keywords=["wechselschalter", "umschalter"])
    add("fuse", "Sicherung", "Schutzgeräte", 3, 1,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5)],
        [_line(0, 0.5, 0.8, 0.5), _rect(0.8, 0.1, 1.4, 0.8), _line(0.8, 0.1, 2.2, 0.9),
         _line(2.2, 0.5, 3, 0.5)],
        default_label="F", description="Schmelzsicherung.",
        keywords=["sicherung", "schmelzsicherung"])
    add("breaker", "Leitungsschutzschalter", "Schutzgeräte", 3, 1.6,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5)],
        [_line(0, 0.5, 0.5, 0.5), _rect(0.5, 0.05, 2, 0.9), _line(0.5, 0.05, 2.5, 0.95),
         _line(2.5, 0.5, 3, 0.5), _rect(0.9, -0.5, 1.2, 0.4),
         _text(1.5, -0.2, "LS")],
        default_label="F", description="Leitungsschutzschalter (LS-Schalter).",
        keywords=["leitungsschutzschalter", "ls", "mcb"])
    add("rcd", "Fehlerstrom-Schutzeinrichtung (FI)", "Schutzgeräte", 4, 2,
        [_terminal("1", 0, 0.5, label="L1"), _terminal("2", 4, 0.5, label="L1'"),
         _terminal("3", 0, 1.5, label="N"), _terminal("4", 4, 1.5, label="N'")],
        [_rect(0, 0, 4, 2), _line(0.5, 0.5, 3.5, 0.5), _line(0.5, 1.5, 3.5, 1.5),
         _circle(2, 1.0, 0.5), _text(2, 1.15, "I∆", size=0.4),
         _text(2, 1.9, "FI", size=0.4)],
        default_label="FI", description="Fehlerstrom-Schutzeinrichtung (RCD/FI).",
        keywords=["fi", "rcd", "fehlerstromschutzschalter"])

    # --- Loads --------------------------------------------------------------
    add("lamp", "Leuchte", "Verbraucher", 3, 3,
        [_terminal("1", 0, 1.5), _terminal("2", 3, 1.5)],
        [_line(0, 1.5, 0.8, 1.5), _circle(1.5, 1.5, 0.7), _line(0.95, 0.95, 2.05, 2.05),
         _line(2.05, 0.95, 0.95, 2.05), _line(2.2, 1.5, 3, 1.5)],
        default_label="E", description="Leuchte / Lampe.",
        keywords=["leuchte", "lampe", "beleuchtung"])
    add("motor", "Motor", "Verbraucher", 3, 3,
        [_terminal("1", 0, 1.5), _terminal("2", 3, 1.5)],
        [_line(0, 1.5, 0.6, 1.5), _circle(1.5, 1.5, 0.9), _text(1.5, 1.65, "M", size=0.6),
         _line(2.4, 1.5, 3, 1.5)],
        default_label="M", description="Elektromotor.",
        keywords=["motor", "antrieb"])
    add("socket", "Steckdose", "Verbraucher", 3, 3,
        [_terminal("l", 0, 0.5, label="L"), _terminal("n", 0, 2.5, label="N"),
         _terminal("pe", 3, 1.5, label="PE")],
        [_poly([[0, 0.5], [1, 0.5], [1, 1.5], [2, 1.5], [2, 0.5], [3, 0.5]]),
         _line(0, 2.5, 1, 2.5), _line(1, 2.5, 1, 1.5),
         _line(3, 0.5, 3, 1.5), _line(1.5, 2.9, 1.5, 1.5)],
        default_label="X", description="Schutzkontakt-Steckdose.",
        keywords=["steckdose", "socket"])
    add("contactor_coil", "Schützspule", "Schaltgeräte", 3, 2,
        [_terminal("a1", 0, 1, label="A1"), _terminal("a2", 3, 1, label="A2")],
        [_line(0, 1, 0.6, 1), _rect(0.6, 0.2, 1.8, 1.6), _line(2.4, 1, 3, 1),
         _text(1.5, 1.15, "K", size=0.6)],
        default_label="K", description="Schütz- oder Relaisspule.",
        keywords=["schuetz", "relais", "spule"])

    # --- Supply and potentials ---------------------------------------------
    add("terminal", "Klemme", "Anschlüsse", 1, 1,
        [_terminal("1", 0.5, 0.5)],
        [_circle(0.5, 0.5, 0.22, filled=True)],
        default_label="X", description="Klemme / Verbindungspunkt.",
        keywords=["klemme", "verbindung"])
    add("junction", "Verbindungsknoten", "Anschlüsse", 1, 1,
        [_terminal("1", 0.5, 0.5)],
        [_circle(0.5, 0.5, 0.25, filled=True)],
        default_label="", description="Elektrischer Verbindungsknoten.",
        keywords=["knoten", "junction"])
    add("earth", "Schutzleiteranschluss", "Anschlüsse", 2, 2,
        [_terminal("pe", 1, 0, label="PE")],
        [_line(1, 0, 1, 0.8), _line(0.2, 0.8, 1.8, 0.8), _line(0.5, 1.2, 1.5, 1.2),
         _line(0.8, 1.6, 1.2, 1.6)],
        default_label="PE", description="Anschluss des Schutzleiters.",
        keywords=["schutzleiter", "pe", "erde"])
    add("neutral", "Neutralleiter", "Anschlüsse", 2, 2,
        [_terminal("n", 1, 0, label="N")],
        [_line(1, 0, 1, 1), _line(0.2, 1, 1.8, 1), _line(0.5, 1.4, 1.5, 1.4)],
        default_label="N", description="Neutralleiter (N).",
        keywords=["neutralleiter", "n"])
    add("phase", "Außenleiter", "Anschlüsse", 2, 2,
        [_terminal("l", 1, 0, label="L")],
        [_line(1, 0, 1, 1.2), _line(0.4, 1.2, 1.6, 1.2)],
        default_label="L", description="Außenleiter (L1/L2/L3).",
        keywords=["aussenleiter", "phase", "l1"])
    add("meter", "Zähler / Messgerät", "Anschlüsse", 3, 3,
        [_terminal("1", 0, 0.5), _terminal("2", 3, 0.5), _terminal("3", 0, 2.5),
         _terminal("4", 3, 2.5)],
        [_rect(0, 0, 3, 3), _text(1.5, 1.7, "kWh", size=0.6)],
        default_label="P", description="Elektrizitätszähler / Messgerät.",
        keywords=["zaehler", "messgeraet", "kwh"])

    # --- System components --------------------------------------------------
    add("distribution", "Verteilung", "Systeme", 6, 8,
        [_terminal("in_l", 0, 1, label="L"), _terminal("in_n", 0, 3, label="N"),
         _terminal("in_pe", 0, 5, label="PE"),
         _terminal("out1", 6, 1, label="L1"), _terminal("out2", 6, 3, label="L2"),
         _terminal("out3", 6, 5, label="L3")],
        [_rect(0, 0, 6, 8), _rect(0, 0, 6, 2),
         _text(3, 1.4, "Verteilung", size=0.6),
         _line(1.2, 1, 1.2, 5), _line(3, 1, 3, 5), _line(4.8, 1, 4.8, 5)],
        default_label="UV", description="Unterverteilung / Verteilerschrank.",
        keywords=["verteilung", "verteiler", "uv"])
    add("transformer", "Transformator", "Systeme", 5, 4,
        [_terminal("1", 0, 1, label="Primär 1"), _terminal("2", 0, 3, label="Primär 2"),
         _terminal("3", 5, 1, label="Sekundär 1"), _terminal("4", 5, 3, label="Sekundär 2")],
        [_circle(1.7, 2, 1.4), _circle(3.3, 2, 1.4),
         _line(0, 1, 0.4, 1), _line(0, 3, 0.4, 3),
         _line(4.6, 1, 5, 1), _line(4.6, 3, 5, 3),
         _line(1.7, 0.6, 1.7, 3.4), _line(3.3, 0.6, 3.3, 3.4)],
        default_label="T", description="Transformator.",
        keywords=["transformator", "trafo"])
    add("pv_module", "PV-Modul", "Systeme", 5, 4,
        [_terminal("p", 0, 2, label="+"), _terminal("n", 0, 3.4, label="-")],
        [_rect(0, 0, 5, 4), _line(0, 1.3, 5, 1.3), _line(0, 2.6, 5, 2.6),
         _line(1.6, 0, 1.6, 4), _line(3.3, 0, 3.3, 4)],
        default_label="PV", description="Photovoltaikmodul.",
        keywords=["photovoltaik", "pv", "solar"])
    add("inverter", "Wechselrichter", "Systeme", 4, 3,
        [_terminal("dcp", 0, 0.5, label="DC+"), _terminal("dcn", 0, 2.5, label="DC-"),
         _terminal("acl", 4, 0.5, label="AC L"), _terminal("acn", 4, 2.5, label="AC N")],
        [_rect(0, 0, 4, 3), _line(1, 0.5, 1, 2.5), _line(3, 0.5, 3, 2.5),
         _text(2, 1.75, "DC/AC", size=0.55)],
        default_label="WR", description="Wechselrichter (DC/AC).",
        keywords=["wechselrichter", "inverter"])
    add("heat_pump", "Wärmepumpe", "Systeme", 5, 4,
        [_terminal("l", 0, 1, label="L"), _terminal("n", 0, 3, label="N")],
        [_rect(0, 0, 5, 4), _circle(2.5, 2, 1.2), _line(2.5, 0.8, 2.5, 3.2),
         _text(2.5, 2.2, "WP", size=0.6)],
        default_label="WP", description="Wärmepumpe.",
        keywords=["waermepumpe", "wp"])
    add("contactor", "Schütz", "Systeme", 4, 3,
        [_terminal("a1", 0, 0.5, label="A1"), _terminal("a2", 0, 2.5, label="A2"),
         _terminal("13", 4, 0.5, label="13"), _terminal("14", 4, 2.5, label="14")],
        [_rect(0, 0, 4, 3), _text(1.4, 1.75, "K1", size=0.6),
         _line(3, 0.5, 3, 2.5)],
        default_label="K", description="Schütz mit Hilfskontakt.",
        keywords=["schuetz", "contactor"])

    return symbols


SYMBOL_LIBRARY: dict[str, dict[str, Any]] = _build_library()

CATEGORIES: list[str] = sorted({s["category"] for s in SYMBOL_LIBRARY.values()})


def get_symbol(symbol_id: str) -> dict[str, Any] | None:
    return SYMBOL_LIBRARY.get(symbol_id)


def library_as_list() -> list[dict[str, Any]]:
    return [SYMBOL_LIBRARY[key] for key in sorted(SYMBOL_LIBRARY)]


def search(query: str) -> list[dict[str, Any]]:
    term = (query or "").strip().lower()
    if not term:
        return library_as_list()
    out = []
    for symbol in SYMBOL_LIBRARY.values():
        haystack = " ".join([
            symbol["name"], symbol["category"], symbol["description"],
            " ".join(symbol["keywords"]), symbol["id"],
        ]).lower()
        if term in haystack:
            out.append(symbol)
    return out
