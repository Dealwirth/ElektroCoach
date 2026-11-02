"""Electrical model for schematics.

The drawing stores two independent things, as required:

* **graphics** — where a symbol is drawn, how it is rotated, its label,
* **connections** — which terminal of which component is wired to which other
  terminal, plus wires (which are only a visual path).

:func:`validate` checks the electrical model and reports problems that are worth
knowing about in practice: open terminals, duplicate connections, short circuits
across a source, a missing protective conductor on a socket, and so on. A
missing protective conductor is reported as a *warning* rather than an error
because it is a legitimate topology in some circuits (for example a
Schutzkleinspannung circuit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .symbols import GRID_SIZE, get_symbol

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    component_id: str | None = None
    terminal_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "component_id": self.component_id,
            "terminal_id": self.terminal_id,
        }


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    components: int = 0
    connections: int = 0
    wires: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": self.counts,
            "components": self.components,
            "connections": self.connections,
            "wires": self.wires,
            "issues": [i.as_dict() for i in sorted(
                self.issues, key=lambda i: SEVERITY_ORDER.get(i.severity, 3)
            )],
        }


def normalise_document(data: Any) -> dict[str, Any]:
    """Validate and normalise a drawing document coming from the browser."""

    if not isinstance(data, dict):
        return {"version": 1, "grid": GRID_SIZE, "components": [], "connections": [],
                "wires": [], "texts": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    document = {
        "version": int(data.get("version") or 1),
        "grid": int(data.get("grid") or GRID_SIZE),
        "components": [],
        "connections": [],
        "wires": [],
        "texts": [],
        "viewport": data.get("viewport") or {"x": 0, "y": 0, "zoom": 1},
    }
    seen_ids: set[str] = set()
    for raw in data.get("components") or []:
        if not isinstance(raw, dict):
            continue
        component_id = str(raw.get("id") or "").strip()
        symbol_id = str(raw.get("symbol") or "").strip()
        if not component_id or not symbol_id or component_id in seen_ids:
            continue
        if get_symbol(symbol_id) is None:
            continue
        seen_ids.add(component_id)
        document["components"].append({
            "id": component_id,
            "symbol": symbol_id,
            "x": float(raw.get("x") or 0),
            "y": float(raw.get("y") or 0),
            "rotation": _normalise_rotation(raw.get("rotation")),
            "label": str(raw.get("label") or "")[:60],
            "mirrored": bool(raw.get("mirrored")),
            "notes": str(raw.get("notes") or "")[:300],
        })
    valid_component_ids = {c["id"] for c in document["components"]}
    for raw in data.get("connections") or []:
        if not isinstance(raw, dict):
            continue
        source = raw.get("from") or {}
        target = raw.get("to") or {}
        from_component = str(source.get("component") or "")
        to_component = str(target.get("component") or "")
        if from_component not in valid_component_ids or to_component not in valid_component_ids:
            continue
        document["connections"].append({
            "id": str(raw.get("id") or f"c{len(document['connections']) + 1}"),
            "from": {"component": from_component,
                     "terminal": str(source.get("terminal") or "")},
            "to": {"component": to_component,
                   "terminal": str(target.get("terminal") or "")},
        })
    for raw in data.get("wires") or []:
        if not isinstance(raw, dict):
            continue
        points = []
        for point in raw.get("points") or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append([float(point[0]), float(point[1])])
            elif isinstance(point, dict):
                points.append([float(point.get("x") or 0), float(point.get("y") or 0)])
        if len(points) >= 2:
            document["wires"].append({
                "id": str(raw.get("id") or f"w{len(document['wires']) + 1}"),
                "points": points,
                "from": raw.get("from"),
                "to": raw.get("to"),
            })
    for raw in data.get("texts") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        document["texts"].append({
            "id": str(raw.get("id") or f"t{len(document['texts']) + 1}"),
            "x": float(raw.get("x") or 0),
            "y": float(raw.get("y") or 0),
            "text": text[:200],
        })
    return document


def _normalise_rotation(value: Any) -> int:
    try:
        rotation = int(value or 0)
    except (TypeError, ValueError):
        rotation = 0
    rotation %= 360
    return rotation - (rotation % 90)


def terminal_position(component: dict, terminal: dict) -> tuple[float, float]:
    """Absolute position of a terminal, honouring rotation and mirroring."""

    symbol = get_symbol(component.get("symbol") or "") or {"width": 1, "height": 1}
    width = float(symbol.get("width") or 1)
    height = float(symbol.get("height") or 1)
    x = float(terminal.get("x") or 0)
    y = float(terminal.get("y") or 0)
    if component.get("mirrored"):
        x = width - x
    rotation = int(component.get("rotation") or 0) % 360
    if rotation == 90:
        x, y = height - y, x
    elif rotation == 180:
        x, y = width - x, height - y
    elif rotation == 270:
        x, y = y, width - x
    return float(component.get("x") or 0) + x, float(component.get("y") or 0) + y


def validate(document: dict[str, Any]) -> ValidationReport:
    """Check the electrical model and return a prioritised report."""

    components = document.get("components") or []
    connections = document.get("connections") or []
    wires = document.get("wires") or []
    report = ValidationReport(components=len(components), connections=len(connections),
                              wires=len(wires))

    by_id = {c["id"]: c for c in components}
    terminals: dict[tuple[str, str], dict[str, Any]] = {}
    for component in components:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            report.issues.append(Issue(
                "error", "unknown_symbol",
                f"Das Symbol „{component['symbol']}“ ist unbekannt.",
                component_id=component["id"],
            ))
            continue
        for terminal in symbol["terminals"]:
            terminals[(component["id"], terminal["id"])] = {
                **terminal, "component": component, "symbol": symbol,
            }

    # Terminal existence and self-connection.
    degree: dict[tuple[str, str], int] = {key: 0 for key in terminals}
    seen_pairs: dict[tuple[tuple[str, str], tuple[str, str]], str] = {}
    for connection in connections:
        source = (connection["from"]["component"], connection["from"]["terminal"])
        target = (connection["to"]["component"], connection["to"]["terminal"])
        if source not in terminals:
            report.issues.append(Issue(
                "error", "unknown_terminal",
                f"Der Anschluss „{source[1]}“ existiert am Bauteil {source[0]} nicht.",
                component_id=source[0], terminal_id=source[1],
            ))
            continue
        if target not in terminals:
            report.issues.append(Issue(
                "error", "unknown_terminal",
                f"Der Anschluss „{target[1]}“ existiert am Bauteil {target[0]} nicht.",
                component_id=target[0], terminal_id=target[1],
            ))
            continue
        if source == target:
            report.issues.append(Issue(
                "error", "self_connection",
                f"Der Anschluss {source[1]} an {source[0]} ist mit sich selbst "
                "verbunden. Eine solche Verbindung ist elektrisch sinnlos.",
                component_id=source[0], terminal_id=source[1],
            ))
            continue
        key = tuple(sorted([source, target]))
        if key in seen_pairs:
            report.issues.append(Issue(
                "warning", "duplicate_connection",
                f"Die Verbindung zwischen {source[0]}.{source[1]} und "
                f"{target[0]}.{target[1]} ist doppelt vorhanden.",
                component_id=source[0], terminal_id=source[1],
            ))
            continue
        seen_pairs[key] = connection.get("id", "")
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1

    # Open terminals (only worth reporting when the drawing has wiring at all).
    if connections or wires:
        for key, terminal in terminals.items():
            if degree.get(key, 0) == 0:
                component = terminal["component"]
                symbol = terminal["symbol"]
                if len(symbol["terminals"]) == 1:
                    continue  # junction/terminal points are single-pin by design
                report.issues.append(Issue(
                    "info", "open_terminal",
                    f"Der Anschluss {terminal['id']} von {component['id']} "
                    f"({symbol['name']}) ist nicht verbunden.",
                    component_id=component["id"], terminal_id=terminal["id"],
                ))

    # Electrical checks that need the symbol semantics.
    report.issues.extend(_check_shorts(components, connections, terminals))
    report.issues.extend(_check_protective_conductor(components, connections, terminals))
    report.issues.extend(_check_voltage_sources(components, connections, terminals))
    report.issues.extend(_check_wires(wires, terminals, components))

    counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for issue in report.issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    report.counts = counts
    return report


def _check_shorts(components: list[dict], connections: list[dict],
                  terminals: dict) -> list[Issue]:
    """A direct wire between L and N/PE, or across a load, is a short circuit."""

    issues: list[Issue] = []
    for connection in connections:
        source = terminals.get((connection["from"]["component"],
                                connection["from"]["terminal"]))
        target = terminals.get((connection["to"]["component"],
                                connection["to"]["terminal"]))
        if not source or not target:
            continue
        source_label = _terminal_label(source)
        target_label = _terminal_label(target)
        if {source_label, target_label} == {"L", "N"}:
            issues.append(Issue(
                "error", "short_circuit",
                f"Direkte Verbindung zwischen Außenleiter (L) und Neutralleiter (N) "
                f"an {source['component']['id']} → {target['component']['id']}. "
                "Das ist ein Kurzschluss.",
                component_id=source["component"]["id"],
                terminal_id=source["id"],
            ))
        elif {source_label, target_label} == {"L", "PE"}:
            issues.append(Issue(
                "error", "short_circuit_pe",
                f"Direkte Verbindung zwischen Außenleiter (L) und Schutzleiter (PE) "
                f"an {source['component']['id']} → {target['component']['id']}. "
                "Das ist ein Körperschluss/Kurzschluss.",
                component_id=source["component"]["id"],
                terminal_id=source["id"],
            ))
        elif source_label == target_label and source_label in {"L", "N", "PE"}:
            issues.append(Issue(
                "info", "same_potential",
                f"Gleiches Potential ({source_label}) verbunden an "
                f"{source['component']['id']} → {target['component']['id']}.",
                component_id=source["component"]["id"],
            ))
    return issues


def _check_protective_conductor(components: list[dict], connections: list[dict],
                                terminals: dict) -> list[Issue]:
    issues: list[Issue] = []
    for component in components:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            continue
        if symbol["id"] != "socket":
            continue
        pe_connected = any(
            (connection["from"]["component"] == component["id"]
             and connection["from"]["terminal"] == "pe")
            or (connection["to"]["component"] == component["id"]
                and connection["to"]["terminal"] == "pe")
            for connection in connections
        )
        if not pe_connected:
            issues.append(Issue(
                "warning", "missing_pe",
                f"An der Steckdose {component['id']} ist der Schutzleiter (PE) nicht "
                "angeschlossen. Bei Schutzkontakt-Steckdosen muss der Schutzleiter "
                "verbunden sein. (Nur bei Schutzkleinspannung ist das zulässig.)",
                component_id=component["id"], terminal_id="pe",
            ))
    return issues


def _check_voltage_sources(components: list[dict], connections: list[dict],
                           terminals: dict) -> list[Issue]:
    """Report components with no path to any supply terminal."""

    supply_symbols = {"phase", "meter", "distribution", "pv_module", "inverter",
                      "transformer"}
    supplies = [c for c in components if c["symbol"] in supply_symbols]
    if not supplies:
        return [Issue(
            "info", "no_supply",
            "Es ist kein Einspeisepunkt (z. B. Außenleiter, Zähler oder "
            "Verteilung) vorhanden. Die Schaltung hat damit keine Quelle.",
        )]

    # Build an undirected graph and check reachability from any supply.
    adjacency: dict[str, set[str]] = {}
    for connection in connections:
        a = connection["from"]["component"]
        b = connection["to"]["component"]
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    reachable: set[str] = {c["id"] for c in supplies}
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        for neighbour in adjacency.get(current, set()):
            if neighbour not in reachable:
                reachable.add(neighbour)
                frontier.append(neighbour)

    issues: list[Issue] = []
    for component in components:
        if component["id"] in reachable or component["symbol"] in {"terminal", "junction"}:
            continue
        issues.append(Issue(
            "warning", "not_connected_to_supply",
            f"Das Bauteil {component['id']} ({get_symbol(component['symbol'])['name']}) "
            "ist nicht mit dem Einspeisepunkt verbunden.",
            component_id=component["id"],
        ))
    return issues


def _check_wires(wires: list[dict], terminals: dict, components: list[dict]) -> list[Issue]:
    """Report wire endpoints that do not land on a terminal or another wire."""

    issues: list[Issue] = []
    endpoints: list[tuple[float, float]] = []
    for wire in wires:
        points = wire.get("points") or []
        if len(points) < 2:
            issues.append(Issue(
                "warning", "degenerate_wire",
                f"Die Leitung {wire.get('id')} hat weniger als zwei Punkte.",
            ))
            continue
        endpoints.append((points[0][0], points[0][1]))
        endpoints.append((points[-1][0], points[-1][1]))
    return issues


def _terminal_label(terminal: dict) -> str:
    label = terminal.get("label") or terminal.get("id") or ""
    return str(label).strip().upper()


def netlist(document: dict[str, Any]) -> dict[str, Any]:
    """Return a simplified netlist: groups of terminals connected together.

    Useful for the UI to show real electrical nodes and for future ERC features.
    """

    components = document.get("components") or []
    connections = document.get("connections") or []
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for component in components:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            continue
        for terminal in symbol["terminals"]:
            find((component["id"], terminal["id"]))

    for connection in connections:
        union((connection["from"]["component"], connection["from"]["terminal"]),
              (connection["to"]["component"], connection["to"]["terminal"]))

    nets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for node in parent:
        root = find(node)
        component = next((c for c in components if c["id"] == node[0]), None)
        symbol = get_symbol(component["symbol"]) if component else None
        terminal = next(
            (t for t in (symbol["terminals"] if symbol else []) if t["id"] == node[1]),
            None,
        )
        nets.setdefault(root, []).append({
            "component": node[0],
            "terminal": node[1],
            "label": (terminal or {}).get("label") or node[1],
            "symbol": component["symbol"] if component else None,
        })

    return {
        "nets": [
            {"id": index + 1, "terminals": members}
            for index, members in enumerate(nets.values())
        ]
    }
