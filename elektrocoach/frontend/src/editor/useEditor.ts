/**
 * Editor-Kern: Zustand, Verlauf (Undo/Redo), Auswahl und Netzlogik.
 *
 * Der Editor arbeitet mit demselben Datenmodell wie das Backend. Pins werden
 * aus der Symbolbibliothek berechnet (nicht gespeichert). Dadurch bleiben
 * Leitungen beim Verschieben von Bauteilen erhalten.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import type { Component, DesignData, Junction, SymbolDef, Wire } from "../types";

export const GRID = 20;

export function snap(value: number, grid = GRID): number {
  return Math.round(value / grid) * grid;
}

export function rotatePoint(
  x: number,
  y: number,
  rotation: number,
  width: number,
  height: number,
): [number, number] {
  const normalised = ((rotation % 360) + 360) % 360;
  if (normalised === 90) return [width - y, x];
  if (normalised === 180) return [width - x, height - y];
  if (normalised === 270) return [y, height - x];
  return [x, y];
}

export function pinPosition(
  component: Component,
  pinId: string,
  symbols: Record<string, SymbolDef>,
): { x: number; y: number } | null {
  const symbol = symbols[component.type];
  if (!symbol) return null;
  const pin = symbol.pins.find((item) => item.id === pinId);
  if (!pin) return null;
  const [lx, ly] = rotatePoint(pin.x, pin.y, component.rotation, symbol.width, symbol.height);
  return { x: snap(component.x + lx), y: snap(component.y + ly) };
}

export function componentPins(
  component: Component,
  symbols: Record<string, SymbolDef>,
): Array<{ id: string; x: number; y: number; name: string }> {
  const symbol = symbols[component.type];
  if (!symbol) return [];
  return symbol.pins
    .map((pin) => {
      const position = pinPosition(component, pin.id, symbols);
      return position ? { id: pin.id, name: pin.name, ...position } : null;
    })
    .filter((value): value is { id: string; x: number; y: number; name: string } => value !== null);
}

/** Volle Leitungspunkte: berechnete Pin-Positionen plus Zwischenpunkte. */
export function wirePath(
  wire: Wire,
  components: Record<string, Component>,
  symbols: Record<string, SymbolDef>,
): Array<{ x: number; y: number }> {
  const fromComponent = components[wire.from.component_id];
  const toComponent = components[wire.to.component_id];
  if (!fromComponent || !toComponent) return wire.points ?? [];
  const start = pinPosition(fromComponent, wire.from.pin_id, symbols);
  const end = pinPosition(toComponent, wire.to.pin_id, symbols);
  if (!start || !end) return wire.points ?? [];
  return [start, ...(wire.points ?? []), end];
}

export interface EditorState {
  components: Component[];
  wires: Wire[];
  junctions: Junction[];
}

export type Selection = { kind: "component" | "wire" | "junction"; id: string };

export function useEditor(initial: DesignData, symbols: SymbolDef[]) {
  const symbolMap = useMemo(() => {
    const map: Record<string, SymbolDef> = {};
    symbols.forEach((symbol) => {
      map[symbol.type] = symbol;
    });
    return map;
  }, [symbols]);

  const [state, setStateRaw] = useState<EditorState>(() => ({
    components: (initial.components ?? []).map(normaliseComponent),
    wires: initial.wires ?? [],
    junctions: initial.junctions ?? [],
  }));
  const [selection, setSelection] = useState<Selection[]>([]);
  const [dirty, setDirty] = useState(false);

  const past = useRef<EditorState[]>([]);
  const future = useRef<EditorState[]>([]);
  const [historyTick, setHistoryTick] = useState(0);
  const clipboard = useRef<EditorState | null>(null);

  const commit = useCallback(
    (next: EditorState | ((current: EditorState) => EditorState)) => {
      setStateRaw((current) => {
        const resolved = typeof next === "function" ? (next as (c: EditorState) => EditorState)(current) : next;
        past.current = [...past.current.slice(-49), current];
        future.current = [];
        return resolved;
      });
      setDirty(true);
      setHistoryTick((value) => value + 1);
    },
    [],
  );

  const undo = useCallback(() => {
    setStateRaw((current) => {
      const previous = past.current.pop();
      if (!previous) return current;
      future.current = [current, ...future.current.slice(0, 49)];
      return previous;
    });
    setDirty(true);
    setHistoryTick((value) => value + 1);
  }, []);

  const redo = useCallback(() => {
    setStateRaw((current) => {
      const next = future.current.shift();
      if (!next) return current;
      past.current = [...past.current, current];
      return next;
    });
    setDirty(true);
    setHistoryTick((value) => value + 1);
  }, []);

  const canUndo = past.current.length > 0;
  const canRedo = future.current.length > 0;
  void historyTick;

  // -- Bauteile ------------------------------------------------------------
  const addComponent = useCallback(
    (type: string, x: number, y: number) => {
      const symbol = symbolMap[type];
      if (!symbol) return;
      const component: Component = {
        id: newId("c"),
        type,
        x: snap(x),
        y: snap(y),
        rotation: 0,
        label: nextLabel(type, state.components),
      };
      commit((current) => ({ ...current, components: [...current.components, component] }));
      setSelection([{ kind: "component", id: component.id }]);
    },
    [commit, state.components, symbolMap],
  );

  const updateComponents = useCallback(
    (updates: Array<{ id: string; patch: Partial<Component> }>) => {
      commit((current) => ({
        ...current,
        components: current.components.map((component) => {
          const update = updates.find((item) => item.id === component.id);
          return update ? { ...component, ...update.patch } : component;
        }),
      }));
    },
    [commit],
  );

  const removeSelection = useCallback(() => {
    if (selection.length === 0) return;
    const componentIds = new Set(selection.filter((s) => s.kind === "component").map((s) => s.id));
    const wireIds = new Set(selection.filter((s) => s.kind === "wire").map((s) => s.id));
    const junctionIds = new Set(selection.filter((s) => s.kind === "junction").map((s) => s.id));
    commit((current) => ({
      components: current.components.filter((component) => !componentIds.has(component.id)),
      junctions: current.junctions.filter((junction) => !junctionIds.has(junction.id)),
      wires: current.wires.filter(
        (wire) =>
          !wireIds.has(wire.id) &&
          !componentIds.has(wire.from.component_id) &&
          !componentIds.has(wire.to.component_id),
      ),
    }));
    setSelection([]);
  }, [commit, selection]);

  const rotateSelection = useCallback(
    (delta = 90) => {
      const ids = new Set(selection.filter((s) => s.kind === "component").map((s) => s.id));
      if (ids.size === 0) return;
      updateComponents(
        [...ids].map((id) => {
          const component = state.components.find((item) => item.id === id);
          return {
            id,
            patch: { rotation: (((component?.rotation ?? 0) + delta) % 360 + 360) % 360 },
          };
        }),
      );
    },
    [selection, state.components, updateComponents],
  );

  const copySelection = useCallback(() => {
    const componentIds = new Set(selection.filter((s) => s.kind === "component").map((s) => s.id));
    const wireIds = new Set(selection.filter((s) => s.kind === "wire").map((s) => s.id));
    clipboard.current = {
      components: state.components.filter((component) => componentIds.has(component.id)),
      junctions: state.junctions.filter((junction) =>
        selection.some((s) => s.kind === "junction" && s.id === junction.id),
      ),
      wires: state.wires.filter(
        (wire) =>
          wireIds.has(wire.id) ||
          (componentIds.has(wire.from.component_id) && componentIds.has(wire.to.component_id)),
      ),
    };
  }, [selection, state]);

  const paste = useCallback(() => {
    const data = clipboard.current;
    if (!data || data.components.length === 0) return;
    const idMap: Record<string, string> = {};
    const offset = GRID * 2;
    const components = data.components.map((component) => {
      const id = newId("c");
      idMap[component.id] = id;
      return { ...component, id, x: snap(component.x + offset), y: snap(component.y + offset) };
    });
    const wires = data.wires
      .filter((wire) => idMap[wire.from.component_id] && idMap[wire.to.component_id])
      .map((wire) => ({
        ...wire,
        id: newId("w"),
        from: { ...wire.from, component_id: idMap[wire.from.component_id] },
        to: { ...wire.to, component_id: idMap[wire.to.component_id] },
        points: (wire.points ?? []).map((point) => ({
          x: snap(point.x + offset),
          y: snap(point.y + offset),
        })),
      }));
    const junctions = data.junctions.map((junction) => ({
      id: newId("j"),
      x: snap(junction.x + offset),
      y: snap(junction.y + offset),
    }));
    commit((current) => ({
      components: [...current.components, ...components],
      wires: [...current.wires, ...wires],
      junctions: [...current.junctions, ...junctions],
    }));
    setSelection(components.map((component) => ({ kind: "component" as const, id: component.id })));
  }, [commit]);

  const duplicateSelection = useCallback(() => {
    copySelection();
    paste();
  }, [copySelection, paste]);

  // -- Leitungen -----------------------------------------------------------
  const addWire = useCallback(
    (
      from: { component_id: string; pin_id: string },
      to: { component_id: string; pin_id: string },
      points: Array<{ x: number; y: number }> = [],
    ) => {
      if (from.component_id === to.component_id && from.pin_id === to.pin_id) return null;
      const duplicate = state.wires.find(
        (wire) =>
          (wire.from.component_id === from.component_id &&
            wire.from.pin_id === from.pin_id &&
            wire.to.component_id === to.component_id &&
            wire.to.pin_id === to.pin_id) ||
          (wire.from.component_id === to.component_id &&
            wire.from.pin_id === to.pin_id &&
            wire.to.component_id === from.component_id &&
            wire.to.pin_id === from.pin_id),
      );
      if (duplicate) return duplicate.id;
      const wire: Wire = {
        id: newId("w"),
        from,
        to,
        points: points.map((point) => ({ x: snap(point.x), y: snap(point.y) })),
      };
      commit((current) => ({ ...current, wires: [...current.wires, wire] }));
      setSelection([{ kind: "wire", id: wire.id }]);
      return wire.id;
    },
    [commit, state.wires],
  );

  const updateWirePoints = useCallback(
    (wireId: string, points: Array<{ x: number; y: number }>) => {
      commit((current) => ({
        ...current,
        wires: current.wires.map((wire) =>
          wire.id === wireId
            ? { ...wire, points: points.map((point) => ({ x: snap(point.x), y: snap(point.y) })) }
            : wire,
        ),
      }));
    },
    [commit],
  );

  const addJunction = useCallback(
    (x: number, y: number) => {
      const point = { x: snap(x), y: snap(y) };
      const existing = state.junctions.find(
        (junction) => junction.x === point.x && junction.y === point.y,
      );
      if (existing) return existing.id;
      const junction: Junction = { id: newId("j"), ...point };
      commit((current) => ({ ...current, junctions: [...current.junctions, junction] }));
      return junction.id;
    },
    [commit, state.junctions],
  );

  const setDesign = useCallback(
    (data: DesignData) => {
      commit({
        components: (data.components ?? []).map(normaliseComponent),
        wires: data.wires ?? [],
        junctions: data.junctions ?? [],
      });
      setSelection([]);
    },
    [commit],
  );

  const resetDirty = useCallback(() => setDirty(false), []);

  const design: DesignData = useMemo(
    () => ({
      components: state.components,
      wires: state.wires,
      junctions: state.junctions,
      grid: GRID,
    }),
    [state],
  );

  return {
    state,
    design,
    symbols: symbolMap,
    selection,
    setSelection,
    dirty,
    resetDirty,
    canUndo,
    canRedo,
    undo,
    redo,
    addComponent,
    updateComponents,
    removeSelection,
    rotateSelection,
    copySelection,
    paste,
    duplicateSelection,
    addWire,
    updateWirePoints,
    addJunction,
    setDesign,
    commit,
  };
}

function normaliseComponent(component: Component): Component {
  return {
    ...component,
    x: snap(Number(component.x ?? 0)),
    y: snap(Number(component.y ?? 0)),
    rotation: Number(component.rotation ?? 0),
    label: component.label ?? "",
  };
}

const LABEL_PREFIX: Record<string, string> = {
  mcb: "F", fuse: "F", rcd: "FI", contactor: "K", relay: "K", motor: "M",
  lamp: "H", socket: "X", terminal: "X", switch: "S", pushbutton_no: "S",
  pushbutton_nc: "S", changeover: "S", heater: "E", temperature_sensor: "B",
};

export function nextLabel(type: string, components: Component[]): string {
  const prefix = LABEL_PREFIX[type];
  if (!prefix) return "";
  const used = components
    .map((component) => component.label)
    .filter((label) => label?.startsWith(prefix))
    .map((label) => Number(label.replace(/[^0-9]/g, "")))
    .filter((value) => !Number.isNaN(value));
  const next = used.length ? Math.max(...used) + 1 : 1;
  return `${prefix}${next}`;
}

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter.toString(36)}`;
}
