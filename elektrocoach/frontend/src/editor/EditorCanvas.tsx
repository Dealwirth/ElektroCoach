/**
 * Zeichenflaeche des Schaltplan-Editors.
 *
 * Maus, Touch und Stift werden ueber Pointer-Events einheitlich behandelt.
 * Raster: 20 px, alle Positionen werden gerastet.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Component, SymbolDef } from "../types";
import { SymbolShape } from "./SymbolShape";
import {
  GRID,
  componentPins,
  pinPosition,
  snap,
  wirePath,
  type EditorState,
  type Selection,
} from "./useEditor";

interface CanvasProps {
  state: EditorState;
  symbols: Record<string, SymbolDef>;
  selection: Selection[];
  tool: "select" | "wire" | "junction" | "pan";
  zoom: number;
  pan: { x: number; y: number };
  onSelect: (selection: Selection[], additive: boolean) => void;
  onMoveComponents: (updates: Array<{ id: string; patch: Partial<Component> }>) => void;
  onAddWire: (
    from: { component_id: string; pin_id: string },
    to: { component_id: string; pin_id: string },
    points: Array<{ x: number; y: number }>,
  ) => void;
  onUpdateWirePoints: (wireId: string, points: Array<{ x: number; y: number }>) => void;
  onAddJunction: (x: number, y: number) => void;
  onPan: (pan: { x: number; y: number }) => void;
  onZoom: (zoom: number) => void;
  onDoubleClickComponent: (id: string) => void;
  showGrid: boolean;
}

interface DragState {
  kind: "move" | "wire" | "pan" | "marquee" | "wire-point";
  startX: number;
  startY: number;
  originals?: Record<string, { x: number; y: number }>;
  fromPin?: { component_id: string; pin_id: string };
  preview?: { x: number; y: number };
  panStart?: { x: number; y: number };
  wireId?: string;
  pointIndex?: number;
}

export default function EditorCanvas(props: CanvasProps) {
  const {
    state, symbols, selection, tool, zoom, pan,
    onSelect, onMoveComponents, onAddWire, onUpdateWirePoints, onAddJunction,
    onPan, onZoom, onDoubleClickComponent, showGrid,
  } = props;

  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<DragState | null>(null);
  const [marquee, setMarquee] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [preview, setPreview] = useState<{ x: number; y: number } | null>(null);
  const [hoverPin, setHoverPin] = useState<{ component_id: string; pin_id: string } | null>(null);

  const componentMap = useMemo(() => {
    const map: Record<string, Component> = {};
    state.components.forEach((component) => {
      map[component.id] = component;
    });
    return map;
  }, [state.components]);

  const selectedComponentIds = useMemo(
    () => new Set(selection.filter((item) => item.kind === "component").map((item) => item.id)),
    [selection],
  );
  const selectedWireIds = useMemo(
    () => new Set(selection.filter((item) => item.kind === "wire").map((item) => item.id)),
    [selection],
  );

  const toWorld = useCallback(
    (event: { clientX: number; clientY: number }) => {
      const svg = svgRef.current;
      if (!svg) return { x: 0, y: 0 };
      const rect = svg.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left - pan.x) / zoom,
        y: (event.clientY - rect.top - pan.y) / zoom,
      };
    },
    [pan.x, pan.y, zoom],
  );

  const pinAt = useCallback(
    (world: { x: number; y: number }) => {
      let best: { component_id: string; pin_id: string; distance: number } | null = null;
      state.components.forEach((component) => {
        componentPins(component, symbols).forEach((pin) => {
          const distance = Math.hypot(pin.x - world.x, pin.y - world.y);
          if (distance <= 12 && (!best || distance < best.distance)) {
            best = { component_id: component.id, pin_id: pin.id, distance };
          }
        });
      });
      return best as { component_id: string; pin_id: string; distance: number } | null;
    },
    [state.components, symbols],
  );

  const componentAt = useCallback(
    (world: { x: number; y: number }) => {
      for (let index = state.components.length - 1; index >= 0; index -= 1) {
        const component = state.components[index];
        const symbol = symbols[component.type];
        if (!symbol) continue;
        if (
          world.x >= component.x - 4 &&
          world.x <= component.x + symbol.width + 4 &&
          world.y >= component.y - 4 &&
          world.y <= component.y + symbol.height + 4
        ) {
          return component;
        }
      }
      return null;
    },
    [state.components, symbols],
  );

  const wireAt = useCallback(
    (world: { x: number; y: number }) => {
      for (const wire of state.wires) {
        const path = wirePath(wire, componentMap, symbols);
        for (let index = 0; index < path.length - 1; index += 1) {
          if (distanceToSegment(world, path[index], path[index + 1]) <= 7) return wire;
        }
      }
      return null;
    },
    [componentMap, state.wires, symbols],
  );

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.button === 1 || (event.button === 0 && tool === "pan") || event.shiftKey === false && event.button === 2) {
      drag.current = { kind: "pan", startX: event.clientX, startY: event.clientY, panStart: { ...pan } };
      (event.target as Element).setPointerCapture?.(event.pointerId);
      return;
    }

    const world = toWorld(event);
    const pin = pinAt(world);
    const component = componentAt(world);
    const wire = wireAt(world);
    const additive = event.shiftKey || event.ctrlKey || event.metaKey;

    if (tool === "wire" || pin) {
      if (pin) {
        drag.current = {
          kind: "wire",
          startX: event.clientX,
          startY: event.clientY,
          fromPin: { component_id: pin.component_id, pin_id: pin.pin_id },
        };
        // Zeiger einfangen: sonst beendet ein Verlassen der Zeichenfläche die
        // Leitung vorzeitig (onPointerLeave), obwohl der Anschluss noch folgt.
        (event.target as Element).setPointerCapture?.(event.pointerId);
        const anchor = pinPosition(componentMap[pin.component_id], pin.pin_id, symbols);
        setPreview(anchor ?? world);
        return;
      }
    }

    if (tool === "junction") {
      onAddJunction(world.x, world.y);
      return;
    }

    if (component) {
      const ids = additive
        ? [...new Set([...selectedComponentIds, component.id])]
        : selectedComponentIds.has(component.id)
          ? [...selectedComponentIds]
          : [component.id];
      if (!additive) {
        onSelect(ids.map((id) => ({ kind: "component" as const, id })), false);
      } else {
        onSelect([...selection, { kind: "component" as const, id: component.id }], true);
      }
      const originals: Record<string, { x: number; y: number }> = {};
      ids.forEach((id) => {
        const item = componentMap[id];
        if (item) originals[id] = { x: item.x, y: item.y };
      });
      drag.current = { kind: "move", startX: world.x, startY: world.y, originals };
      return;
    }

    if (wire) {
      // Griff an einem Zwischenpunkt ziehen -> Leitungsführung ändern.
      const path = wirePath(wire, componentMap, symbols);
      const inner = path.slice(1, -1);
      let hitIndex = -1;
      inner.forEach((point, index) => {
        if (Math.hypot(point.x - world.x, point.y - world.y) <= 8) hitIndex = index;
      });
      if (hitIndex >= 0) {
        onSelect([{ kind: "wire", id: wire.id }], false);
        drag.current = {
          kind: "wire-point",
          startX: world.x,
          startY: world.y,
          wireId: wire.id,
          pointIndex: hitIndex,
        };
        return;
      }
      if (!additive) onSelect([{ kind: "wire", id: wire.id }], false);
      else onSelect([...selection, { kind: "wire", id: wire.id }], true);
      return;
    }

    if (!additive) onSelect([], false);
    drag.current = { kind: "marquee", startX: world.x, startY: world.y };
    setMarquee({ x1: world.x, y1: world.y, x2: world.x, y2: world.y });
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const world = toWorld(event);
    const active = drag.current;

    if (!active) {
      const pin = pinAt(world);
      setHoverPin(pin ? { component_id: pin.component_id, pin_id: pin.pin_id } : null);
      return;
    }

    if (active.kind === "pan" && active.panStart) {
      onPan({
        x: active.panStart.x + (event.clientX - active.startX),
        y: active.panStart.y + (event.clientY - active.startY),
      });
      return;
    }

    if (active.kind === "move" && active.originals) {
      const dx = snap(world.x - active.startX);
      const dy = snap(world.y - active.startY);
      onMoveComponents(
        Object.entries(active.originals).map(([id, original]) => ({
          id,
          patch: { x: snap(original.x + dx), y: snap(original.y + dy) },
        })),
      );
      return;
    }

    if (active.kind === "wire") {
      const pin = pinAt(world);
      setPreview(pin ? pinPosition(componentMap[pin.component_id], pin.pin_id, symbols) ?? world : { x: snap(world.x), y: snap(world.y) });
      setHoverPin(pin ? { component_id: pin.component_id, pin_id: pin.pin_id } : null);
      return;
    }

    if (active.kind === "marquee") {
      setMarquee({ x1: active.startX, y1: active.startY, x2: world.x, y2: world.y });
      return;
    }

    if (active.kind === "wire-point" && active.wireId !== undefined && active.pointIndex !== undefined) {
      const wire = state.wires.find((item) => item.id === active.wireId);
      if (!wire) return;
      const points = [...(wire.points ?? [])];
      points[active.pointIndex] = { x: snap(world.x), y: snap(world.y) };
      onUpdateWirePoints(active.wireId, points);
    }
  };

  const onPointerUp = (event: React.PointerEvent<SVGSVGElement>) => {
    const active = drag.current;
    drag.current = null;
    const world = toWorld(event);

    if (!active) return;

    if (active.kind === "wire" && active.fromPin) {
      const pin = pinAt(world);
      if (pin && !(pin.component_id === active.fromPin.component_id && pin.pin_id === active.fromPin.pin_id)) {
        const from = pinPosition(componentMap[active.fromPin.component_id], active.fromPin.pin_id, symbols);
        const to = pinPosition(componentMap[pin.component_id], pin.pin_id, symbols);
        const points = orthogonalPoints(from, to);
        onAddWire(active.fromPin, { component_id: pin.component_id, pin_id: pin.pin_id }, points);
      }
      setPreview(null);
      setHoverPin(null);
      return;
    }

    if (active.kind === "marquee" && marquee) {
      const minX = Math.min(marquee.x1, marquee.x2);
      const maxX = Math.max(marquee.x1, marquee.x2);
      const minY = Math.min(marquee.y1, marquee.y2);
      const maxY = Math.max(marquee.y1, marquee.y2);
      if (Math.abs(maxX - minX) > 4 || Math.abs(maxY - minY) > 4) {
        const hits: Selection[] = [];
        state.components.forEach((component) => {
          const symbol = symbols[component.type];
          if (!symbol) return;
          if (
            component.x >= minX &&
            component.x + symbol.width <= maxX &&
            component.y >= minY &&
            component.y + symbol.height <= maxY
          ) {
            hits.push({ kind: "component", id: component.id });
          }
        });
        onSelect(hits, event.shiftKey);
      }
      setMarquee(null);
    }
  };

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    if (!event.ctrlKey && !event.metaKey && Math.abs(event.deltaY) < 40) return;
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.1 : 0.9;
    onZoom(Math.max(0.3, Math.min(3, zoom * factor)));
  };

  useEffect(() => {
    const element = svgRef.current;
    if (!element) return;
    const prevent = (event: Event) => event.preventDefault();
    element.addEventListener("touchmove", prevent, { passive: false });
    return () => element.removeEventListener("touchmove", prevent);
  }, []);

  const wirePreview = preview && drag.current?.fromPin
    ? {
        from: pinPosition(componentMap[drag.current.fromPin.component_id], drag.current.fromPin.pin_id, symbols),
        to: preview,
      }
    : null;

  return (
    <svg
      ref={svgRef}
      className="h-full w-full touch-none select-none"
      style={{ background: "var(--canvas-bg)" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      onWheel={onWheel}
      onContextMenu={(event) => event.preventDefault()}
      role="application"
      aria-label="Schaltplan-Zeichenfläche"
    >
      <defs>
        <pattern id="grid-minor" width={GRID} height={GRID} patternUnits="userSpaceOnUse">
          <path
            d={`M ${GRID} 0 L 0 0 0 ${GRID}`}
            fill="none"
            stroke="var(--canvas-grid-minor)"
            strokeWidth="1"
          />
        </pattern>
        <pattern id="grid-major" width={GRID * 5} height={GRID * 5} patternUnits="userSpaceOnUse">
          <rect width={GRID * 5} height={GRID * 5} fill="url(#grid-minor)" />
          <path
            d={`M ${GRID * 5} 0 L 0 0 0 ${GRID * 5}`}
            fill="none"
            stroke="var(--canvas-grid-major)"
            strokeWidth="1"
          />
        </pattern>
      </defs>

      <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
        <rect
          x={-4000}
          y={-4000}
          width={12000}
          height={12000}
          fill={showGrid ? "url(#grid-major)" : "var(--canvas-bg)"}
        />

        {/* Leitungen */}
        {state.wires.map((wire) => {
          const path = wirePath(wire, componentMap, symbols);
          if (path.length < 2) return null;
          const selected = selectedWireIds.has(wire.id);
          const d = path.map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`).join(" ");
          // Die Standardfarbe Schwarz wird in der dunklen Betriebsart durch
          // eine helle Farbe ersetzt, sonst wären Leitungen unsichtbar.
          const baseColor =
            wire.color && wire.color !== "#1e293b" ? wire.color : "var(--canvas-wire)";
          return (
            <g key={wire.id}>
              <path
                d={d}
                fill="none"
                stroke={selected ? "#1b6ff5" : baseColor}
                strokeWidth={selected ? 4 : 2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d={d} fill="none" stroke="transparent" strokeWidth="14" data-wire={wire.id} />
              {wire.points?.map((point, index) => (
                <circle
                  key={index}
                  cx={point.x}
                  cy={point.y}
                  r={selected ? 4.5 : 3}
                  fill="var(--canvas-bg)"
                  stroke={selected ? "#1b6ff5" : "var(--canvas-label)"}
                  strokeWidth="1.5"
                />
              ))}
            </g>
          );
        })}

        {/* Bauteile */}
        {state.components.map((component) => {
          const symbol = symbols[component.type];
          if (!symbol) return null;
          return (
            <g
              key={component.id}
              data-component={component.id}
              onDoubleClick={(event) => {
                event.stopPropagation();
                onDoubleClickComponent(component.id);
              }}
            >
              <SymbolShape
                component={component}
                symbol={symbol}
                selected={selectedComponentIds.has(component.id)}
                interactive={tool === "select"}
              />
            </g>
          );
        })}

        {/* Verbindungspunkte */}
        {state.junctions.map((junction) => (
          <circle key={junction.id} cx={junction.x} cy={junction.y} r="6" fill="var(--canvas-ink)" />
        ))}

        {/* Pin-Hervorhebung */}
        {hoverPin && componentMap[hoverPin.component_id] && (
          (() => {
            const position = pinPosition(
              componentMap[hoverPin.component_id],
              hoverPin.pin_id,
              symbols,
            );
            return position ? (
              <circle
                cx={position.x}
                cy={position.y}
                r="8"
                fill="none"
                stroke="#1b6ff5"
                strokeWidth="2.5"
              />
            ) : null;
          })()
        )}

        {/* Leitungsvorschau */}
        {wirePreview && wirePreview.from && wirePreview.to && (
          <line
            x1={wirePreview.from.x}
            y1={wirePreview.from.y}
            x2={wirePreview.to.x}
            y2={wirePreview.to.y}
            stroke="#1b6ff5"
            strokeWidth="2.5"
            strokeDasharray="6 5"
          />
        )}

        {/* Auswahlrechteck */}
        {marquee && (
          <rect
            x={Math.min(marquee.x1, marquee.x2)}
            y={Math.min(marquee.y1, marquee.y2)}
            width={Math.abs(marquee.x2 - marquee.x1)}
            height={Math.abs(marquee.y2 - marquee.y1)}
            fill="rgba(27,111,245,0.10)"
            stroke="#1b6ff5"
            strokeWidth="1.5"
            strokeDasharray="4 3"
          />
        )}
      </g>
    </svg>
  );
}

/** Erzeugt einen rechtwinkligen Zwischenweg zwischen zwei Punkten. */
export function orthogonalPoints(
  from: { x: number; y: number } | null,
  to: { x: number; y: number } | null,
): Array<{ x: number; y: number }> {
  if (!from || !to) return [];
  if (from.x === to.x || from.y === to.y) return [];
  const midX = snap((from.x + to.x) / 2);
  return [
    { x: midX, y: from.y },
    { x: midX, y: to.y },
  ];
}

function distanceToSegment(
  point: { x: number; y: number },
  a: { x: number; y: number },
  b: { x: number; y: number },
): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  let t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}
