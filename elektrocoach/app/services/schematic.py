"""Schaltplan-Editor: Backend fuer Projekte, Bauteile und Leitungen.

Das Modell ist ein echtes Netzwerkmodell, keine Zeichenflaeche:

  components[]  id, type, x, y, rotation, label, props
  wires[]       id, from {component_id, pin_id}, to {component_id, pin_id},
                points[] (Zwischenpunkte in Rasterkoordinaten), color, width
  junctions[]   id, x, y  (echte Verbindungspunkte)
  crossings[]   implizit: zwei Leitungen ohne Junction an der Kreuzung sind
                KEINE Verbindung. Genau das unterscheidet Kreuzung und
                Verbindung eindeutig.

Anschlusspunkte (Pins) werden aus der Symbolbibliothek abgeleitet und in
Rasterkoordinaten berechnet. Dadurch rasten Leitungen immer exakt ein und
bleiben beim Verschieben von Bauteilen erhalten (Leitungen werden relativ zu
den Bauteilen neu berechnet).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from .. import db

log = logging.getLogger(__name__)

GRID = 20


# ---------------------------------------------------------------------------
# Symbolbibliothek nach IEC-Konventionen (Auswahl fuer die Ausbildung)
# ---------------------------------------------------------------------------
def _pin(pid: str, x: float, y: float, name: str = "") -> dict[str, Any]:
    return {"id": pid, "x": x, "y": y, "name": name or pid}


SYMBOL_LIBRARY: list[dict[str, Any]] = [
    {
        "type": "switch", "category": "Schalter", "name": "Schalter (Ausschalter)",
        "width": 80, "height": 40,
        "pins": [_pin("1", 0, 20, "L"), _pin("2", 80, 20, "L'")],
    },
    {
        "type": "pushbutton_no", "category": "Taster", "name": "Taster (Schliesser)",
        "width": 80, "height": 40,
        "pins": [_pin("1", 0, 20), _pin("2", 80, 20)],
    },
    {
        "type": "pushbutton_nc", "category": "Taster", "name": "Taster (Oeffner)",
        "width": 80, "height": 40,
        "pins": [_pin("1", 0, 20), _pin("2", 80, 20)],
    },
    {
        "type": "changeover", "category": "Schalter", "name": "Umschalter (Wechsler)",
        "width": 80, "height": 60,
        "pins": [_pin("1", 0, 30, "COM"), _pin("2", 80, 0, "NO"), _pin("3", 80, 60, "NC")],
    },
    {
        "type": "relay", "category": "Relais", "name": "Relais",
        "width": 100, "height": 60,
        "pins": [_pin("A1", 0, 20, "A1"), _pin("A2", 0, 40, "A2"),
                 _pin("11", 100, 20, "11"), _pin("14", 100, 40, "14")],
    },
    {
        "type": "contactor", "category": "Schuetz", "name": "Schuetz",
        "width": 120, "height": 80,
        "pins": [_pin("A1", 0, 20, "A1"), _pin("A2", 0, 60, "A2"),
                 _pin("1", 120, 10, "1/L1"), _pin("2", 120, 30, "2/T1"),
                 _pin("3", 120, 50, "3/L2"), _pin("4", 120, 70, "4/T2")],
    },
    {
        "type": "fuse", "category": "Sicherungen", "name": "Schmelzsicherung",
        "width": 80, "height": 30,
        "pins": [_pin("1", 0, 15), _pin("2", 80, 15)],
    },
    {
        "type": "mcb", "category": "Schutz", "name": "Leitungsschutzschalter (LS)",
        "width": 80, "height": 60,
        "pins": [_pin("1", 0, 15), _pin("2", 80, 15)],
    },
    {
        "type": "rcd", "category": "Schutz", "name": "FI/RCD Schutzschalter",
        "width": 100, "height": 100,
        "pins": [_pin("L1", 0, 20, "1"), _pin("L2", 0, 40, "3"), _pin("L3", 0, 60, "5"),
                 _pin("N", 0, 80, "N"), _pin("L1'", 100, 20, "2"),
                 _pin("L2'", 100, 40, "4"), _pin("L3'", 100, 60, "6"), _pin("N'", 100, 80, "N'")],
    },
    {
        "type": "motor", "category": "Motoren", "name": "Motor",
        "width": 80, "height": 80,
        "pins": [_pin("U1", 0, 20, "U1"), _pin("V1", 0, 40, "V1"), _pin("W1", 0, 60, "W1")],
    },
    {
        "type": "lamp", "category": "Verbraucher", "name": "Leuchte",
        "width": 60, "height": 60,
        "pins": [_pin("1", 0, 30, "L"), _pin("2", 60, 30, "N")],
    },
    {
        "type": "socket", "category": "Verbraucher", "name": "Steckdose",
        "width": 60, "height": 60,
        "pins": [_pin("L", 0, 15, "L"), _pin("N", 0, 30, "N"), _pin("PE", 0, 45, "PE")],
    },
    {
        "type": "terminal", "category": "Klemmen", "name": "Klemme",
        "width": 40, "height": 40,
        "pins": [_pin("1", 0, 20), _pin("2", 40, 20)],
    },
    {
        "type": "supply_l1", "category": "Versorgung", "name": "Versorgung L1 (Phase)",
        "width": 40, "height": 40,
        "pins": [_pin("L1", 40, 20, "L1")],
    },
    {
        "type": "supply_n", "category": "Versorgung", "name": "Versorgung N (Neutralleiter)",
        "width": 40, "height": 40,
        "pins": [_pin("N", 40, 20, "N")],
    },
    {
        "type": "supply_pe", "category": "Versorgung", "name": "Versorgung PE (Schutzleiter)",
        "width": 40, "height": 40,
        "pins": [_pin("PE", 40, 20, "PE")],
    },
    {
        "type": "junction", "category": "Verbindungen", "name": "Verbindungspunkt",
        "width": 20, "height": 20,
        "pins": [],
    },
    {
        "type": "heater", "category": "Verbraucher", "name": "Heizkoerper / Heizung",
        "width": 80, "height": 40,
        "pins": [_pin("1", 0, 20, "L"), _pin("2", 80, 20, "N")],
    },
    {
        "type": "temperature_sensor", "category": "Sensorik", "name": "Temperatursensor",
        "width": 80, "height": 40,
        "pins": [_pin("1", 0, 20), _pin("2", 80, 20)],
    },
    {
        "type": "pv_module", "category": "Photovoltaik", "name": "PV-Modul",
        "width": 100, "height": 60,
        "pins": [_pin("+", 0, 20, "+"), _pin("-", 0, 40, "-")],
    },
    {
        "type": "inverter", "category": "Photovoltaik", "name": "Wechselrichter",
        "width": 100, "height": 80,
        "pins": [_pin("DC+", 0, 20, "DC+"), _pin("DC-", 0, 40, "DC-"),
                 _pin("L", 100, 20, "L"), _pin("N", 100, 40, "N"), _pin("PE", 100, 60, "PE")],
    },
    {
        "type": "contactor_coil", "category": "Schuetz", "name": "Schuetzspule",
        "width": 60, "height": 60,
        "pins": [_pin("A1", 0, 20, "A1"), _pin("A2", 60, 20, "A2")],
    },
    {
        "type": "pushbutton_emergency", "category": "Sicherheit", "name": "Not-Aus-Taster",
        "width": 80, "height": 60,
        "pins": [_pin("1", 0, 30), _pin("2", 80, 30)],
    },
    {
        "type": "text", "category": "Beschriftung", "name": "Textfeld",
        "width": 120, "height": 40, "pins": [],
    },
]

_SYMBOLS_BY_TYPE = {item["type"]: item for item in SYMBOL_LIBRARY}


def library() -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {}
    for symbol in SYMBOL_LIBRARY:
        categories.setdefault(symbol["category"], []).append(symbol)
    return {"grid": GRID, "categories": categories, "symbols": SYMBOL_LIBRARY}


def get_symbol(symbol_type: str) -> dict[str, Any] | None:
    return _SYMBOLS_BY_TYPE.get(symbol_type)


def snap(value: float, grid: int = GRID) -> float:
    return round(value / grid) * grid


def _as_point(value: Any) -> dict[str, float] | None:
    """Akzeptiert {"x": .., "y": ..} oder [x, y] und liefert immer {"x", "y"}."""
    if isinstance(value, dict):
        try:
            return {"x": float(value.get("x", 0)), "y": float(value.get("y", 0))}
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return {"x": float(value[0]), "y": float(value[1])}
        except (TypeError, ValueError):
            return None
    return None


def normalise_points(points: Any) -> list[dict[str, float]]:
    if not isinstance(points, (list, tuple)):
        return []
    result = []
    for point in points:
        normalised = _as_point(point)
        if normalised is not None:
            result.append(normalised)
    return result


def rotate_point(x: float, y: float, rotation: int, width: float, height: float) -> tuple[float, float]:
    """Dreht einen lokalen Punkt um 0/90/180/270 Grad innerhalb der Bauteilbox."""
    rotation = int(rotation or 0) % 360
    if rotation == 90:
        return (width - y, x)
    if rotation == 180:
        return (width - x, height - y)
    if rotation == 270:
        return (y, height - x)
    return (x, y)


def pin_position(component: dict[str, Any], pin_id: str) -> dict[str, float] | None:
    symbol = get_symbol(str(component.get("type", "")))
    if not symbol:
        return None
    pin = next((p for p in symbol["pins"] if p["id"] == pin_id), None)
    if not pin:
        return None
    width = float(symbol.get("width", GRID))
    height = float(symbol.get("height", GRID))
    lx, ly = rotate_point(float(pin["x"]), float(pin["y"]),
                          int(component.get("rotation", 0) or 0), width, height)
    return {
        "x": snap(float(component.get("x", 0)) + lx),
        "y": snap(float(component.get("y", 0)) + ly),
    }


def component_pins(component: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = get_symbol(str(component.get("type", "")))
    if not symbol:
        return []
    out = []
    for pin in symbol["pins"]:
        position = pin_position(component, pin["id"])
        if position:
            out.append({**pin, **position, "component_id": component.get("id")})
    return out


def all_pins(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    for component in components:
        pins.extend(component_pins(component))
    return pins


# ---------------------------------------------------------------------------
# Validierung und Netzanalyse
# ---------------------------------------------------------------------------
def validate_design(data: dict[str, Any]) -> dict[str, Any]:
    """Prueft Bauteile, Leitungen und Anschluesse eines Entwurfs.

    Liefert Fehler, Warnungen und eine Liste freier Anschluesse. Die Leitungen
    werden gegen die tatsaechliche Pin-Geometrie geprueft, nicht gegen die
    gespeicherten Koordinaten - so werden auch verschobene Bauteile erkannt.
    """
    components = [c for c in (data.get("components") or []) if isinstance(c, dict)]
    wires = [w for w in (data.get("wires") or []) if isinstance(w, dict)]
    junctions = [j for j in (data.get("junctions") or []) if isinstance(j, dict)]
    errors: list[str] = []
    warnings: list[str] = []

    by_id = {str(c.get("id")): c for c in components if c.get("id")}
    for component in components:
        if not component.get("id"):
            errors.append("Bauteil ohne ID gefunden.")
        if not get_symbol(str(component.get("type", ""))):
            errors.append(f"Unbekannter Bauteiltyp: {component.get('type')}")

    pin_index = {(str(p["component_id"]), p["id"]): p for p in all_pins(components)}
    used_pins: set[tuple[str, str]] = set()

    for wire in wires:
        start = wire.get("from") or {}
        end = wire.get("to") or {}
        for endpoint in (start, end):
            key = (str(endpoint.get("component_id")), str(endpoint.get("pin_id")))
            if key not in pin_index:
                errors.append(
                    f"Leitung {wire.get('id')} haengt an einem nicht vorhandenen "
                    f"Anschluss: {key[0]}.{key[1]}"
                )
            else:
                used_pins.add(key)
        if start == end:
            warnings.append(f"Leitung {wire.get('id')} verbindet einen Anschluss mit sich selbst.")

    # Kurzschlusspruefung: Phase direkt auf Neutralleiter/Schutzleiter ohne Verbraucher.
    for wire in wires:
        start = wire.get("from") or {}
        end = wire.get("to") or {}
        names = []
        for endpoint in (start, end):
            component = by_id.get(str(endpoint.get("component_id")))
            symbol = get_symbol(str((component or {}).get("type", "")))
            pin = pin_index.get((str(endpoint.get("component_id")), str(endpoint.get("pin_id"))))
            names.append(((symbol or {}).get("type", ""), (pin or {}).get("name", "")))
        types = {n[0] for n in names}
        pins = {n[1] for n in names}
        if {"supply_l1", "supply_n"} <= types:
            errors.append("Kurzschluss: Phase (L1) direkt mit Neutralleiter (N) verbunden.")
        if {"supply_l1", "supply_pe"} <= types:
            errors.append("Kurzschluss: Phase (L1) direkt mit Schutzleiter (PE) verbunden.")
        if {"supply_l1"} & types and pins & {"N", "PE"} and types & {"socket", "motor", "lamp"}:
            warnings.append("Anschluss pruefen: L1 direkt auf N/PE eines Verbrauchers.")

    free_pins = [p for key, p in pin_index.items() if key not in used_pins]
    for junction in junctions:
        if not any(
            abs(p["x"] - float(junction.get("x", 0))) < GRID / 2
            and abs(p["y"] - float(junction.get("y", 0))) < GRID / 2
            for p in pin_index.values()
        ):
            warnings.append("Verbindungspunkt liegt auf keinem Anschluss oder Leitungsende.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "free_pins": [
            {"component_id": p["component_id"], "pin_id": p["id"],
             "x": p["x"], "y": p["y"], "name": p.get("name", "")}
            for p in free_pins
        ],
        "component_count": len(components),
        "wire_count": len(wires),
        "junction_count": len(junctions),
    }


def connected_groups(data: dict[str, Any]) -> list[list[str]]:
    """Ermittelt zusammenhaengende Netzgruppen (Union-Find ueber Anschluesse)."""
    components = data.get("components") or []
    wires = data.get("wires") or []
    pins = {(str(p["component_id"]), p["id"]): p for p in all_pins(components)}
    parent: dict[tuple[str, str], tuple[str, str]] = {key: key for key in pins}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for wire in wires:
        start = wire.get("from") or {}
        end = wire.get("to") or {}
        a = (str(start.get("component_id")), str(start.get("pin_id")))
        b = (str(end.get("component_id")), str(end.get("pin_id")))
        if a in parent and b in parent:
            union(a, b)

    groups: dict[tuple[str, str], list[str]] = {}
    for key in pins:
        groups.setdefault(find(key), []).append(f"{key[0]}.{key[1]}")
    return sorted(groups.values(), key=len, reverse=True)


def wire_length(points: list[dict[str, float]]) -> float:
    pts = normalise_points(points)
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.hypot(float(b["x"]) - float(a["x"]), float(b["y"]) - float(a["y"]))
    return round(total, 2)


def design_stats(data: dict[str, Any]) -> dict[str, Any]:
    components = data.get("components") or []
    wires = data.get("wires") or []
    by_type: dict[str, int] = {}
    for component in components:
        key = str(component.get("type", "unbekannt"))
        by_type[key] = by_type.get(key, 0) + 1
    total_length = sum(
        wire_length(w.get("points") or []) for w in wires
    )
    return {
        "components": len(components),
        "wires": len(wires),
        "by_type": by_type,
        "wire_length_px": round(total_length, 2),
        "wire_length_m": round(total_length / 1000, 3),
    }


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------
def create_project(name: str, description: str = "", data: dict[str, Any] | None = None) -> dict[str, Any]:
    project_id = db.new_id()
    payload = data or {"components": [], "wires": [], "junctions": []}
    db.insert(
        "INSERT INTO schematic_projects(id, name, description, grid, data_json, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (project_id, name[:200], description[:1000], GRID,
         db.json_dumps_safe(payload), db.now(), db.now()),
    )
    return get_project(project_id)  # type: ignore[return-value]


def list_projects() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, name, description, grid, thumbnail, created_at, updated_at "
        "FROM schematic_projects ORDER BY updated_at DESC"
    )
    out = []
    for row in rows:
        item = dict(row)
        data_row = db.query_one(
            "SELECT data_json FROM schematic_projects WHERE id = ?", (row["id"],)
        )
        try:
            data = json.loads(data_row["data_json"]) if data_row else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        item["stats"] = design_stats(data)
        out.append(item)
    return out


def get_project(project_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM schematic_projects WHERE id = ?", (project_id,))
    if not row:
        return None
    item = dict(row)
    try:
        item["data"] = json.loads(item.pop("data_json"))
    except (json.JSONDecodeError, TypeError):
        item["data"] = {"components": [], "wires": [], "junctions": []}
    item["data"]["grid"] = item.get("grid", GRID)
    item["validation"] = validate_design(item["data"])
    item["stats"] = design_stats(item["data"])
    return item


def save_project(project_id: str, name: str | None = None,
                 description: str | None = None,
                 data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = db.query_one("SELECT id FROM schematic_projects WHERE id = ?", (project_id,))
    if not row:
        return None
    updates: dict[str, Any] = {"updated_at": db.now()}
    if name is not None:
        updates["name"] = name[:200]
    if description is not None:
        updates["description"] = description[:1000]
    if data is not None:
        # Bauteile auf das Raster einrasten, bevor gespeichert wird.
        for component in data.get("components") or []:
            if not isinstance(component, dict):
                continue
            component["x"] = snap(float(component.get("x", 0) or 0))
            component["y"] = snap(float(component.get("y", 0) or 0))
        for junction in data.get("junctions") or []:
            if not isinstance(junction, dict):
                continue
            junction["x"] = snap(float(junction.get("x", 0) or 0))
            junction["y"] = snap(float(junction.get("y", 0) or 0))
        # Leitungs-Zwischenpunkte vereinheitlichen und einrasten.
        for wire in data.get("wires") or []:
            if not isinstance(wire, dict):
                continue
            wire["points"] = [
                {"x": snap(p["x"]), "y": snap(p["y"])}
                for p in normalise_points(wire.get("points"))
            ]
        updates["data_json"] = db.json_dumps_safe(data)
    columns = ", ".join(f"{k} = ?" for k in updates)
    db.execute(
        f"UPDATE schematic_projects SET {columns} WHERE id = ?",  # noqa: S608
        list(updates.values()) + [project_id],
    )
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    row = db.query_one("SELECT id FROM schematic_projects WHERE id = ?", (project_id,))
    if not row:
        return False
    db.execute("DELETE FROM schematic_projects WHERE id = ?", (project_id,))
    return True


def duplicate_project(project_id: str) -> dict[str, Any] | None:
    project = get_project(project_id)
    if not project:
        return None
    return create_project(f"{project['name']} (Kopie)", project.get("description", ""), project["data"])


def project_svg(project_id: str) -> str | None:
    """Erzeugt ein SVG fuer den Export (serverseitig, ohne Browser)."""
    project = get_project(project_id)
    if not project:
        return None
    data = project["data"]
    components = data.get("components") or []
    wires = data.get("wires") or []

    xs: list[float] = [0.0, 800.0]
    ys: list[float] = [0.0, 600.0]
    for component in components:
        symbol = get_symbol(str(component.get("type", "")))
        width = float((symbol or {}).get("width", 80))
        height = float((symbol or {}).get("height", 40))
        xs.extend([float(component.get("x", 0)), float(component.get("x", 0)) + width])
        ys.extend([float(component.get("y", 0)), float(component.get("y", 0)) + height])
    for wire in wires:
        for point in normalise_points(wire.get("points")):
            xs.append(point["x"])
            ys.append(point["y"])

    margin = 60
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    width = max_x - min_x
    height = max_y - min_y

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.0f} {min_y:.0f} '
        f'{width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}">',
        '<rect x="{}" y="{}" width="{}" height="{}" fill="#ffffff"/>'.format(
            min_x, min_y, width, height),
        '<g stroke="#94a3b8" stroke-width="1" opacity="0.35">',
    ]
    grid = GRID * 4
    start_x = int(min_x // grid) * grid
    while start_x < max_x:
        parts.append(f'<line x1="{start_x}" y1="{min_y:.0f}" x2="{start_x}" y2="{max_y:.0f}"/>')
        start_x += grid
    start_y = int(min_y // grid) * grid
    while start_y < max_y:
        parts.append(f'<line x1="{min_x:.0f}" y1="{start_y}" x2="{max_x:.0f}" y2="{start_y}"/>')
        start_y += grid
    parts.append("</g>")

    for wire in wires:
        points = normalise_points(wire.get("points"))
        if len(points) < 2:
            continue
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{p['x']:.0f} {p['y']:.0f}"
            for i, p in enumerate(points)
        )
        color = wire.get("color") or "#1e293b"
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    for component in components:
        symbol = get_symbol(str(component.get("type", "")))
        if not symbol:
            continue
        x = float(component.get("x", 0))
        y = float(component.get("y", 0))
        width_c = float(symbol.get("width", 80))
        height_c = float(symbol.get("height", 40))
        rotation = int(component.get("rotation", 0) or 0)
        label = str(component.get("label") or symbol["name"])
        parts.append(
            f'<g transform="rotate({rotation} {x + width_c / 2:.0f} {y + height_c / 2:.0f})">'
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{width_c:.0f}" height="{height_c:.0f}" '
            'rx="4" fill="#f8fafc" stroke="#334155" stroke-width="2"/>'
            f'<text x="{x + width_c / 2:.0f}" y="{y + height_c / 2 + 5:.0f}" '
            'font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#0f172a" '
            f'text-anchor="middle">{_escape(label)}</text></g>'
        )
        for pin in component_pins(component):
            parts.append(
                f'<circle cx="{pin["x"]:.0f}" cy="{pin["y"]:.0f}" r="4" '
                'fill="#ffffff" stroke="#1e293b" stroke-width="2"/>'
            )

    for junction in data.get("junctions") or []:
        parts.append(
            f'<circle cx="{float(junction.get("x", 0)):.0f}" '
            f'cy="{float(junction.get("y", 0)):.0f}" r="6" fill="#1e293b"/>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )
