"""Export drawings to SVG and PDF.

Both exporters use the same primitives as the on-screen canvas
(:mod:`elektrocoach.drawing.symbols`), so an exported file shows exactly what the
editor shows. The SVG exporter is pure Python; the PDF exporter writes a small,
self-contained PDF that embeds the SVG-derived vector commands as a content
stream, which avoids adding a heavy PDF library to the image.
"""

from __future__ import annotations

import html
import zlib
from typing import Any

from .model import terminal_position
from .symbols import GRID_SIZE, get_symbol

DEFAULT_STROKE = "#1f2937"
DEFAULT_FILL = "#ffffff"
LABEL_COLOR = "#0f172a"
WIRE_COLOR = "#2563eb"
GRID_COLOR = "#e5e7eb"
PADDING = 40


def _bounds(document: dict[str, Any]) -> tuple[float, float, float, float]:
    min_x = min_y = 0.0
    max_x = max_y = 0.0
    for component in document.get("components") or []:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            continue
        width = symbol["width"] * GRID_SIZE
        height = symbol["height"] * GRID_SIZE
        x = component["x"] * GRID_SIZE
        y = component["y"] * GRID_SIZE
        if component.get("rotation") in (90, 270):
            width, height = height, width
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x + width)
        max_y = max(max_y, y + height)
    for wire in document.get("wires") or []:
        for point in wire.get("points") or []:
            px = point[0] * GRID_SIZE
            py = point[1] * GRID_SIZE
            min_x = min(min_x, px)
            min_y = min(min_y, py)
            max_x = max(max_x, px)
            max_y = max(max_y, py)
    for text in document.get("texts") or []:
        px = text["x"] * GRID_SIZE
        py = text["y"] * GRID_SIZE
        min_x = min(min_x, px)
        min_y = min(min_y, py)
        max_x = max(max_x, px + len(text["text"]) * 7)
        max_y = max(max_y, py + 16)
    return min_x, min_y, max_x, max_y


def _transform(component: dict) -> str:
    width = (get_symbol(component["symbol"]) or {}).get("width", 1) * GRID_SIZE
    height = (get_symbol(component["symbol"]) or {}).get("height", 1) * GRID_SIZE
    x = component["x"] * GRID_SIZE
    y = component["y"] * GRID_SIZE
    parts = [f"translate({x:.2f},{y:.2f})"]
    rotation = int(component.get("rotation") or 0) % 360
    if rotation:
        if rotation == 90:
            parts.append(f"rotate(90,{0:.2f},{0:.2f}) translate({-(height):.2f},0)")
        elif rotation == 180:
            parts.append(f"translate({width:.2f},{height:.2f}) rotate(180)")
        elif rotation == 270:
            parts.append(f"rotate(-90,{0:.2f},{0:.2f}) translate(0,{-(width):.2f})")
    if component.get("mirrored"):
        parts.append(f"translate({width:.2f},0) scale(-1,1)")
    return " ".join(parts)


def _shape_svg(shape: dict) -> str:
    kind = shape.get("type")
    if kind == "line":
        return (f'<line x1="{shape["x1"] * GRID_SIZE:.2f}" y1="{shape["y1"] * GRID_SIZE:.2f}" '
                f'x2="{shape["x2"] * GRID_SIZE:.2f}" y2="{shape["y2"] * GRID_SIZE:.2f}" '
                f'stroke="{DEFAULT_STROKE}" stroke-width="1.6" stroke-linecap="round"/>')
    if kind == "rect":
        fill = DEFAULT_FILL if not shape.get("filled") else DEFAULT_STROKE
        return (f'<rect x="{shape["x"] * GRID_SIZE:.2f}" y="{shape["y"] * GRID_SIZE:.2f}" '
                f'width="{shape["w"] * GRID_SIZE:.2f}" height="{shape["h"] * GRID_SIZE:.2f}" '
                f'fill="{fill}" stroke="{DEFAULT_STROKE}" stroke-width="1.6"/>')
    if kind == "circle":
        fill = DEFAULT_FILL if not shape.get("filled") else DEFAULT_STROKE
        return (f'<circle cx="{shape["cx"] * GRID_SIZE:.2f}" cy="{shape["cy"] * GRID_SIZE:.2f}" '
                f'r="{shape["r"] * GRID_SIZE:.2f}" fill="{fill}" '
                f'stroke="{DEFAULT_STROKE}" stroke-width="1.6"/>')
    if kind == "polyline":
        points = " ".join(f'{p[0] * GRID_SIZE:.2f},{p[1] * GRID_SIZE:.2f}'
                          for p in shape.get("points") or [])
        fill = DEFAULT_STROKE if shape.get("filled") else "none"
        return (f'<polyline points="{points}" fill="{fill}" stroke="{DEFAULT_STROKE}" '
                f'stroke-width="1.6" stroke-linejoin="round"/>')
    if kind == "text":
        size = float(shape.get("size") or 0.5) * GRID_SIZE
        anchor = shape.get("anchor", "middle")
        return (f'<text x="{shape["x"] * GRID_SIZE:.2f}" y="{shape["y"] * GRID_SIZE:.2f}" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{size:.2f}" '
                f'text-anchor="{anchor}" fill="{LABEL_COLOR}">'
                f'{html.escape(str(shape.get("text") or ""))}</text>')
    return ""


def to_svg(document: dict[str, Any], *, with_grid: bool = True,
           title: str = "Schaltplan") -> str:
    min_x, min_y, max_x, max_y = _bounds(document)
    width = (max_x - min_x) + PADDING * 2
    height = (max_y - min_y) + PADDING * 2
    offset_x = PADDING - min_x
    offset_y = PADDING - min_y

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        f'<title>{html.escape(title)}</title>',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>',
    ]

    if with_grid:
        grid = max(GRID_SIZE, int(document.get("grid") or GRID_SIZE))
        parts.append('<g id="grid">')
        start_x = -(min_x % grid)
        start_y = -(min_y % grid)
        x = start_x + offset_x
        while x < width:
            parts.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{height:.0f}" '
                         f'stroke="{GRID_COLOR}" stroke-width="0.5"/>')
            x += grid
        y = start_y + offset_y
        while y < height:
            parts.append(f'<line x1="0" y1="{y:.1f}" x2="{width:.0f}" y2="{y:.1f}" '
                         f'stroke="{GRID_COLOR}" stroke-width="0.5"/>')
            y += grid
        parts.append("</g>")

    parts.append(f'<g transform="translate({offset_x:.2f},{offset_y:.2f})">')

    # Wires first so symbols sit on top of them.
    parts.append(f'<g id="wires" stroke="{WIRE_COLOR}" stroke-width="2" fill="none">')
    for wire in document.get("wires") or []:
        points = wire.get("points") or []
        if len(points) < 2:
            continue
        path = " ".join(f'{p[0] * GRID_SIZE:.2f},{p[1] * GRID_SIZE:.2f}' for p in points)
        parts.append(f'<polyline points="{path}" stroke-linejoin="round"/>')
    parts.append("</g>")

    parts.append('<g id="components">')
    for component in document.get("components") or []:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            continue
        parts.append(f'<g data-id="{html.escape(component["id"])}" '
                     f'transform="{_transform(component)}">')
        for shape in symbol["shapes"]:
            parts.append(_shape_svg(shape))
        parts.append("</g>")
        label = component.get("label") or symbol.get("default_label") or ""
        if label:
            parts.append(
                f'<text x="{component["x"] * GRID_SIZE:.2f}" '
                f'y="{(component["y"] - 0.5) * GRID_SIZE:.2f}" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="12" '
                f'text-anchor="middle" fill="{LABEL_COLOR}">{html.escape(str(label))}</text>'
            )
    parts.append("</g>")

    parts.append(f'<g id="connections" stroke="{DEFAULT_STROKE}" stroke-width="1.2" '
                 'stroke-dasharray="4 2">')
    for connection in document.get("connections") or []:
        start = _terminal_absolute(document, connection["from"])
        end = _terminal_absolute(document, connection["to"])
        if start is None or end is None:
            continue
        parts.append(f'<line x1="{start[0] * GRID_SIZE:.2f}" y1="{start[1] * GRID_SIZE:.2f}" '
                     f'x2="{end[0] * GRID_SIZE:.2f}" y2="{end[1] * GRID_SIZE:.2f}"/>')
    parts.append("</g>")

    parts.append('<g id="texts" font-family="Helvetica,Arial,sans-serif" font-size="13" '
                 f'fill="{LABEL_COLOR}">')
    for text in document.get("texts") or []:
        parts.append(f'<text x="{text["x"] * GRID_SIZE:.2f}" y="{text["y"] * GRID_SIZE:.2f}">'
                     f'{html.escape(str(text["text"]))}</text>')
    parts.append("</g>")

    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def _terminal_absolute(document: dict, endpoint: dict) -> tuple[float, float] | None:
    component = next(
        (c for c in document.get("components") or [] if c["id"] == endpoint.get("component")),
        None,
    )
    if component is None:
        return None
    symbol = get_symbol(component["symbol"])
    if symbol is None:
        return None
    terminal = next(
        (t for t in symbol["terminals"] if t["id"] == endpoint.get("terminal")), None
    )
    if terminal is None:
        return None
    return terminal_position(component, terminal)


# -- PDF ---------------------------------------------------------------------

def to_pdf(document: dict[str, Any], *, title: str = "Schaltplan") -> bytes:
    """Create a single-page A4-landscape PDF from the drawing.

    A minimal PDF writer is used so that no additional dependency is required.
    The page content mirrors the SVG geometry (lines, rectangles, circles and
    text) with the same coordinates.
    """

    a4_width = 842.0  # A4 landscape, points
    a4_height = 595.0
    min_x, min_y, max_x, max_y = _bounds(document)
    content_width = max(1.0, (max_x - min_x) + PADDING * 2)
    content_height = max(1.0, (max_y - min_y) + PADDING * 2)
    scale = min(a4_width / content_width, a4_height / content_height, 1.0)

    commands: list[str] = []
    # White background.
    commands.append(f"1 1 1 rg 0 0 {a4_width:.2f} {a4_height:.2f} re f")

    def tx(x: float, y: float) -> tuple[float, float]:
        # PDF origin is bottom-left; flip the y axis.
        px = (x * GRID_SIZE - min_x + PADDING) * scale
        py = a4_height - (y * GRID_SIZE - min_y + PADDING) * scale
        return px, py

    def stroke_color(hex_color: str) -> str:
        r = int(hex_color[1:3], 16) / 255.0
        g = int(hex_color[3:5], 16) / 255.0
        b = int(hex_color[5:7], 16) / 255.0
        return f"{r:.3f} {g:.3f} {b:.3f}"

    commands.append(f"{stroke_color(WIRE_COLOR)} RG 1.4 w 1 J")
    for wire in document.get("wires") or []:
        points = wire.get("points") or []
        if len(points) < 2:
            continue
        start = tx(points[0][0], points[0][1])
        commands.append(f"{start[0]:.2f} {start[1]:.2f} m")
        for point in points[1:]:
            px, py = tx(point[0], point[1])
            commands.append(f"{px:.2f} {py:.2f} l")
        commands.append("S")

    commands.append(f"{stroke_color(DEFAULT_STROKE)} RG 1.1 w")
    for component in document.get("components") or []:
        symbol = get_symbol(component["symbol"])
        if symbol is None:
            continue
        for shape in symbol["shapes"]:
            commands.extend(_shape_pdf(shape, component, tx, stroke_color))

    # Dashed connection lines.
    commands.append(f"{stroke_color(DEFAULT_STROKE)} RG 0.8 w [3 2] 0 d")
    for connection in document.get("connections") or []:
        start = _terminal_absolute(document, connection["from"])
        end = _terminal_absolute(document, connection["to"])
        if start is None or end is None:
            continue
        x1, y1 = tx(*start)
        x2, y2 = tx(*end)
        commands.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
    commands.append("[] 0 d")

    # Free texts.
    for text in document.get("texts") or []:
        px, py = tx(text["x"], text["y"])
        commands.append("BT /F1 9 Tf "
                        f"{stroke_color(LABEL_COLOR)} rg {px:.2f} {py:.2f} Td "
                        f"({_pdf_escape(text['text'])}) Tj ET")

    stream = "\n".join(commands).encode("latin-1", "replace")
    compressed = zlib.compress(stream)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {a4_width:.2f} {a4_height:.2f}] "
        f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode("latin-1")
    )
    objects.append(
        f"<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n".encode("latin-1")
        + compressed + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode("latin-1")
    pdf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info << /Title "
            f"({_pdf_escape(title)}) /Producer (ElektroCoach) >> >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n").encode("latin-1")
    return bytes(pdf)


def _shape_pdf(shape: dict, component: dict, tx, stroke_color) -> list[str]:
    """Convert a symbol primitive to PDF operators inside the component transform."""

    rotation = int(component.get("rotation") or 0) % 360
    mirrored = bool(component.get("mirrored"))
    symbol = get_symbol(component["symbol"]) or {}
    width = float(symbol.get("width") or 1)
    height = float(symbol.get("height") or 1)

    def transform_point(x: float, y: float) -> tuple[float, float]:
        if mirrored:
            x = width - x
        if rotation == 90:
            x, y = height - y, x
        elif rotation == 180:
            x, y = width - x, height - y
        elif rotation == 270:
            x, y = y, width - x
        return component["x"] + x, component["y"] + y

    out: list[str] = []
    kind = shape.get("type")
    if kind == "line":
        x1, y1 = tx(*transform_point(shape["x1"], shape["y1"]))
        x2, y2 = tx(*transform_point(shape["x2"], shape["y2"]))
        out.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
    elif kind == "rect":
        x, y = transform_point(shape["x"], shape["y"])
        w = shape["w"] * GRID_SIZE * 0.5  # half-scale guard; recomputed below
        p1 = tx(x, y)
        p2 = tx(x + shape["w"], y + shape["h"])
        left, right = sorted([p1[0], p2[0]])
        bottom, top = sorted([p1[1], p2[1]])
        fill = "f" if shape.get("filled") else ""
        out.append(f"{left:.2f} {bottom:.2f} {right - left:.2f} {top - bottom:.2f} re "
                   f"{'B' if fill else 'S'}")
    elif kind == "circle":
        cx, cy = transform_point(shape["cx"], shape["cy"])
        px, py = tx(cx, cy)
        r = shape["r"] * GRID_SIZE * 0.5523
        out.append(f"{px:.2f} {py:.2f} {r:.2f} 0 360 arc "
                   f"{'B' if shape.get('filled') else 'S'}")
    elif kind == "polyline":
        points = [transform_point(p[0], p[1]) for p in shape.get("points") or []]
        if len(points) < 2:
            return out
        start = tx(*points[0])
        out.append(f"{start[0]:.2f} {start[1]:.2f} m")
        for point in points[1:]:
            px, py = tx(*point)
            out.append(f"{px:.2f} {py:.2f} l")
        out.append("B" if shape.get("filled") else "S")
    return out


def _pdf_escape(text: str) -> str:
    return (str(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
            .replace("ß", "ss").replace("∆", "dI").replace("Ω", "Ohm")
            .replace("²", "2").replace("³", "3").replace("·", "*"))
