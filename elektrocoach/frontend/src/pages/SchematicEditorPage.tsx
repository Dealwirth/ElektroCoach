/**
 * Schaltplan-Editor: Werkzeugleiste, Symbolbibliothek, Zeichenfläche,
 * Eigenschaften, Prüfung und Export.
 *
 * Tastatur: Entf (löschen), Strg+Z/Strg+Y (Undo/Redo), Strg+C/Strg+V,
 * Strg+D (duplizieren), R (drehen), Pfeiltasten (verschieben).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { Alert, Spinner } from "../components/ui";
import EditorCanvas from "../editor/EditorCanvas";
import { GRID, nextLabel, snap, useEditor } from "../editor/useEditor";
import type { SymbolDef, ValidationResult } from "../types";

type Tool = "select" | "wire" | "junction" | "pan";

export default function SchematicEditorPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [library, setLibrary] = useState<SymbolDef[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [tool, setTool] = useState<Tool>("select");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [showGrid, setShowGrid] = useState(true);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("");
  const [editingLabel, setEditingLabel] = useState<string | null>(null);
  const [initialData, setInitialData] = useState<import("../types").DesignData | null>(null);

  // Editor-Zustand erst nach dem Laden der Bibliothek aufbauen.
  const editor = useEditor(initialData ?? { components: [], wires: [], junctions: [] }, library ?? []);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    setLoading(true);
    Promise.all([api.schematicLibrary(), api.schematicProject(projectId)])
      .then(([lib, project]) => {
        if (!active) return;
        setLibrary(lib.symbols);
        setActiveCategory(lib.symbols[0]?.category ?? "");
        setProjectName(project.name);
        setDescription(project.description ?? "");
        setInitialData(project.data ?? { components: [], wires: [], junctions: [] });
        setValidation(project.validation ?? null);
      })
      .catch((err: unknown) => active && setError(err instanceof Error ? err.message : String(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId]);

  // Vorlagedaten in den Editor übernehmen, sobald beide geladen sind.
  useEffect(() => {
    if (initialData && library) {
      editor.setDesign(initialData);
      editor.resetDirty();
      setSavedAt(new Date().toISOString());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialData, library]);

  const categories = useMemo(() => {
    const map: Record<string, SymbolDef[]> = {};
    (library ?? []).forEach((symbol) => {
      map[symbol.category] = [...(map[symbol.category] ?? []), symbol];
    });
    return map;
  }, [library]);

  const save = useCallback(
    async (silent = false) => {
      if (!projectId) return;
      setSaving(true);
      if (!silent) setMessage(null);
      try {
        const result = await api.saveSchematic(projectId, {
          name: projectName,
          description,
          data: editor.design,
        });
        editor.resetDirty();
        setValidation(result.validation ?? null);
        setSavedAt(new Date().toISOString());
        if (!silent) setMessage({ tone: "success", text: "Projekt gespeichert." });
      } catch (err) {
        setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : String(err) });
      } finally {
        setSaving(false);
      }
    },
    [description, editor, projectId, projectName],
  );

  const validate = useCallback(async () => {
    try {
      const result = await api.validateSchematic(editor.design);
      setValidation(result);
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : String(err) });
    }
  }, [editor.design]);

  // Automatisches Speichern alle 20 Sekunden bei Änderungen.
  useEffect(() => {
    if (!editor.dirty) return;
    const timer = window.setTimeout(() => {
      void save(true);
    }, 20000);
    return () => window.clearTimeout(timer);
  }, [editor.dirty, editor.design, save]);

  // Tastatursteuerung
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      const meta = event.ctrlKey || event.metaKey;
      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) editor.redo();
        else editor.undo();
        return;
      }
      if (meta && event.key.toLowerCase() === "y") {
        event.preventDefault();
        editor.redo();
        return;
      }
      if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
        return;
      }
      if (meta && event.key.toLowerCase() === "c") {
        editor.copySelection();
        return;
      }
      if (meta && event.key.toLowerCase() === "v") {
        editor.paste();
        return;
      }
      if (meta && event.key.toLowerCase() === "d") {
        event.preventDefault();
        editor.duplicateSelection();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        editor.removeSelection();
        return;
      }
      if (event.key.toLowerCase() === "r") {
        editor.rotateSelection(90);
        return;
      }
      if (event.key === "Escape") {
        editor.setSelection([]);
        return;
      }
      if (event.key === "v") setTool("select");
      if (event.key === "w") setTool("wire");
      if (event.key === "j") setTool("junction");
      if (event.key === "h") setTool("pan");

      const step = event.shiftKey ? GRID * 5 : GRID;
      const componentIds = editor.selection
        .filter((item) => item.kind === "component")
        .map((item) => item.id);
      if (componentIds.length === 0) return;
      const deltas: Record<string, { dx: number; dy: number }> = {
        ArrowLeft: { dx: -step, dy: 0 },
        ArrowRight: { dx: step, dy: 0 },
        ArrowUp: { dx: 0, dy: -step },
        ArrowDown: { dx: 0, dy: step },
      };
      const delta = deltas[event.key];
      if (delta) {
        event.preventDefault();
        editor.updateComponents(
          componentIds.map((id) => {
            const component = editor.state.components.find((item) => item.id === id);
            return {
              id,
              patch: {
                x: snap((component?.x ?? 0) + delta.dx),
                y: snap((component?.y ?? 0) + delta.dy),
              },
            };
          }),
        );
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [editor, save]);

  const selectedComponent = useMemo(() => {
    const item = editor.selection.find((entry) => entry.kind === "component");
    return item ? editor.state.components.find((component) => component.id === item.id) ?? null : null;
  }, [editor.selection, editor.state.components]);

  const selectedWire = useMemo(() => {
    const item = editor.selection.find((entry) => entry.kind === "wire");
    return item ? editor.state.wires.find((wire) => wire.id === item.id) ?? null : null;
  }, [editor.selection, editor.state.wires]);

  if (loading) return <Spinner label="Projekt wird geladen …" />;
  if (error) {
    return (
      <Alert tone="danger" title="Projekt konnte nicht geladen werden">
        {error}
        <Link to="/schaltplan" className="btn-secondary btn-sm mt-3">
          Zur Projektliste
        </Link>
      </Alert>
    );
  }

  const canvasHeight = "calc(100vh - 96px)";

  return (
    <div className="flex h-screen flex-col bg-ink-50">
      {/* Kopfzeile */}
      <header className="flex flex-wrap items-center gap-2 border-b border-ink-200 bg-white px-3 py-2.5">
        <Link to="/schaltplan" className="btn-ghost btn-sm" aria-label="Zurück zur Projektliste">
          ← Zurück
        </Link>
        <input
          className="input w-48 py-1.5 text-sm sm:w-64"
          value={projectName}
          onChange={(event) => setProjectName(event.target.value)}
          aria-label="Projektname"
        />
        <span className="hidden text-xs text-ink-500 sm:inline">
          {editor.dirty ? "ungespeicherte Änderungen" : savedAt ? "gespeichert" : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button type="button" className="btn-ghost btn-sm" onClick={editor.undo} disabled={!editor.canUndo}>
            Rückgängig
          </button>
          <button type="button" className="btn-ghost btn-sm" onClick={editor.redo} disabled={!editor.canRedo}>
            Wiederholen
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={validate}>
            Prüfen
          </button>
          <button type="button" className="btn-primary btn-sm" onClick={() => save()} disabled={saving}>
            {saving ? "Speichern …" : "Speichern"}
          </button>
          <a className="btn-secondary btn-sm" href={api.schematicSvgUrl(projectId ?? "")} download>
            SVG
          </a>
          <a className="btn-secondary btn-sm" href={api.schematicJsonUrl(projectId ?? "")} download>
            JSON
          </a>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => {
              const win = window.open("", "_blank");
              if (!win) return;
              win.document.write(
                `<html><head><title>${projectName}</title></head><body style="margin:0">` +
                  `<img src="${api.schematicSvgUrl(projectId ?? "")}" style="max-width:100%"/>` +
                  `<script>window.onload=()=>window.print()<\/script></body></html>`,
              );
              win.document.close();
            }}
          >
            PDF
          </button>
        </div>
      </header>

      {message && (
        <div className="px-3 pt-3">
          <Alert tone={message.tone} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* Werkzeugleiste links */}
        <aside className="flex w-16 shrink-0 flex-col items-center gap-1.5 border-r border-ink-200 bg-white py-3 sm:w-56 sm:items-stretch sm:px-3">
          <div className="hidden gap-1 sm:grid sm:grid-cols-2">
            {(
              [
                ["select", "Auswahl", "M4 4l7 16 2-7 7-2z"],
                ["wire", "Leitung", "M4 12h16M4 12l4-4M4 12l4 4"],
                ["junction", "Punkt", "M12 5a7 7 0 100 14 7 7 0 000-14z"],
                ["pan", "Verschieben", "M12 3v18M3 12h18"],
              ] as Array<[Tool, string, string]>
            ).map(([id, label, path]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTool(id)}
                className={`flex flex-col items-center gap-1 rounded-xl px-2 py-2 text-xs font-medium ${
                  tool === id ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50"
                }`}
                title={label}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d={path} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {label}
              </button>
            ))}
          </div>
          {/* Werkzeuge für Smartphone */}
          <div className="flex flex-col gap-1.5 sm:hidden">
            {(
              [
                ["select", "M4 4l7 16 2-7 7-2z"],
                ["wire", "M4 12h16M4 12l4-4M4 12l4 4"],
                ["junction", "M12 5a7 7 0 100 14 7 7 0 000-14z"],
                ["pan", "M12 3v18M3 12h18"],
              ] as Array<[Tool, string]>
            ).map(([id, path]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTool(id)}
                className={`rounded-xl p-2.5 ${
                  tool === id ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50"
                }`}
                aria-label={id}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d={path} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ))}
          </div>

          <div className="hidden flex-1 flex-col gap-2 overflow-hidden sm:flex">
            <select
              className="input py-1.5 text-xs"
              value={activeCategory}
              onChange={(event) => setActiveCategory(event.target.value)}
            >
              {Object.keys(categories).map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
            <div className="flex-1 space-y-1 overflow-y-auto pr-1 scrollbar-thin">
              {(categories[activeCategory] ?? []).map((symbol) => (
                <button
                  key={symbol.type}
                  type="button"
                  draggable
                  onDragEnd={() => {
                    /* Ablegen auf der Fläche erfolgt per Klick in die Mitte */
                  }}
                  onClick={() => {
                    editor.addComponent(symbol.type, snap(-pan.x / zoom) + 200, snap(-pan.y / zoom) + 200);
                  }}
                  className="flex w-full items-center justify-between gap-2 rounded-lg border border-ink-100 px-2.5 py-2 text-left text-xs hover:border-brand-300 hover:bg-brand-50"
                >
                  <span className="truncate text-ink-700">{symbol.name}</span>
                  <span className="shrink-0 text-ink-400">{symbol.pins.length}</span>
                </button>
              ))}
            </div>
            <p className="text-[11px] leading-snug text-ink-400">
              Symbol anklicken, um es auf der Fläche einzufügen. Anschließend mit der Maus oder dem
              Finger an die richtige Stelle ziehen.
            </p>
          </div>
        </aside>

        {/* Zeichenfläche */}
        <div className="relative min-w-0 flex-1" style={{ height: canvasHeight }}>
          <EditorCanvas
            state={editor.state}
            symbols={editor.symbols}
            selection={editor.selection}
            tool={tool}
            zoom={zoom}
            pan={pan}
            showGrid={showGrid}
            onSelect={(selection, additive) =>
              editor.setSelection(additive ? [...editor.selection, ...selection] : selection)
            }
            onMoveComponents={editor.updateComponents}
            onAddWire={editor.addWire}
            onUpdateWirePoints={editor.updateWirePoints}
            onAddJunction={editor.addJunction}
            onPan={setPan}
            onZoom={setZoom}
            onDoubleClickComponent={(id) => setEditingLabel(id)}
          />

          {/* Ansichtsteuerung */}
          <div className="pointer-events-auto absolute bottom-3 left-3 flex items-center gap-1.5 rounded-xl border border-ink-200 bg-white/95 px-2 py-1.5 shadow-card">
            <button type="button" className="btn-ghost btn-sm" onClick={() => setZoom((value) => Math.max(0.3, value - 0.1))}>
              −
            </button>
            <span className="w-12 text-center text-xs text-ink-600">{Math.round(zoom * 100)} %</span>
            <button type="button" className="btn-ghost btn-sm" onClick={() => setZoom((value) => Math.min(3, value + 0.1))}>
              +
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => { setZoom(1); setPan({ x: 40, y: 40 }); }}>
              Zurücksetzen
            </button>
            <label className="flex items-center gap-1.5 text-xs text-ink-600">
              <input type="checkbox" checked={showGrid} onChange={(event) => setShowGrid(event.target.checked)} />
              Raster
            </label>
          </div>

          {tool === "wire" && (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-xl bg-brand-600 px-3 py-1.5 text-xs font-medium text-white shadow-lift">
              Leitung zeichnen: von Anschlusspunkt zu Anschlusspunkt ziehen
            </div>
          )}
        </div>

        {/* Eigenschaften rechts */}
        <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto border-l border-ink-200 bg-white p-4 scrollbar-thin lg:flex">
          <div>
            <p className="mb-2 text-sm font-semibold text-ink-900">Auswahl</p>
            {selectedComponent ? (
              <div className="space-y-3">
                <div>
                  <label className="label" htmlFor="comp-label">
                    Bezeichnung
                  </label>
                  <input
                    id="comp-label"
                    className="input py-1.5 text-sm"
                    value={selectedComponent.label}
                    onChange={(event) =>
                      editor.updateComponents([{ id: selectedComponent.id, patch: { label: event.target.value } }])
                    }
                  />
                  <button
                    type="button"
                    className="btn-ghost btn-sm mt-1"
                    onClick={() =>
                      editor.updateComponents([
                        {
                          id: selectedComponent.id,
                          patch: {
                            label: nextLabel(
                              selectedComponent.type,
                              editor.state.components.filter((item) => item.id !== selectedComponent.id),
                            ),
                          },
                        },
                      ])
                    }
                  >
                    Automatisch benennen
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label" htmlFor="comp-x">
                      X (px)
                    </label>
                    <input
                      id="comp-x"
                      type="number"
                      step={GRID}
                      className="input py-1.5 text-sm"
                      value={selectedComponent.x}
                      onChange={(event) =>
                        editor.updateComponents([
                          { id: selectedComponent.id, patch: { x: snap(Number(event.target.value)) } },
                        ])
                      }
                    />
                  </div>
                  <div>
                    <label className="label" htmlFor="comp-y">
                      Y (px)
                    </label>
                    <input
                      id="comp-y"
                      type="number"
                      step={GRID}
                      className="input py-1.5 text-sm"
                      value={selectedComponent.y}
                      onChange={(event) =>
                        editor.updateComponents([
                          { id: selectedComponent.id, patch: { y: snap(Number(event.target.value)) } },
                        ])
                      }
                    />
                  </div>
                </div>
                <div>
                  <label className="label" htmlFor="comp-rotation">
                    Drehung
                  </label>
                  <select
                    id="comp-rotation"
                    className="input py-1.5 text-sm"
                    value={selectedComponent.rotation}
                    onChange={(event) =>
                      editor.updateComponents([
                        { id: selectedComponent.id, patch: { rotation: Number(event.target.value) } },
                      ])
                    }
                  >
                    {[0, 90, 180, 270].map((value) => (
                      <option key={value} value={value}>
                        {value}°
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-secondary btn-sm mt-1" onClick={() => editor.rotateSelection(90)}>
                    Um 90° drehen (R)
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <button type="button" className="btn-secondary btn-sm" onClick={editor.duplicateSelection}>
                    Duplizieren
                  </button>
                  <button type="button" className="btn-danger btn-sm" onClick={editor.removeSelection}>
                    Löschen
                  </button>
                </div>
              </div>
            ) : selectedWire ? (
              <div className="space-y-3">
                <p className="text-sm text-ink-600">Leitung ausgewählt</p>
                <div>
                  <label className="label" htmlFor="wire-color">
                    Farbe
                  </label>
                  <select
                    id="wire-color"
                    className="input py-1.5 text-sm"
                    value={selectedWire.color ?? "#1e293b"}
                    onChange={(event) =>
                      editor.commit((current) => ({
                        ...current,
                        wires: current.wires.map((wire) =>
                          wire.id === selectedWire.id ? { ...wire, color: event.target.value } : wire,
                        ),
                      }))
                    }
                  >
                    <option value="#1e293b">Schwarz (Außenleiter)</option>
                    <option value="#2563eb">Blau (Neutralleiter)</option>
                    <option value="#16a34a">Grün (Schutzleiter)</option>
                    <option value="#ca8a04">Braun (Außenleiter)</option>
                    <option value="#7c3aed">Violett</option>
                  </select>
                </div>
                <button type="button" className="btn-danger btn-sm" onClick={editor.removeSelection}>
                  Leitung löschen
                </button>
              </div>
            ) : (
              <p className="text-sm text-ink-500">
                Nichts ausgewählt. Bauteil anklicken oder mit gedrückter Maustaste ein Rechteck aufziehen.
              </p>
            )}
          </div>

          <div className="rounded-xl bg-ink-50 p-3">
            <p className="text-xs font-semibold text-ink-700">Projekt</p>
            <dl className="mt-2 space-y-1 text-xs text-ink-600">
              <div className="flex justify-between">
                <dt>Bauteile</dt>
                <dd>{editor.state.components.length}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Leitungen</dt>
                <dd>{editor.state.wires.length}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Verbindungspunkte</dt>
                <dd>{editor.state.junctions.length}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Raster</dt>
                <dd>{GRID} px</dd>
              </div>
            </dl>
          </div>

          {validation && (
            <div>
              <p className="mb-2 text-sm font-semibold text-ink-900">Prüfung</p>
              {validation.ok ? (
                <Alert tone="success" title="Keine Fehler">
                  Der Entwurf ist technisch schlüssig.
                </Alert>
              ) : (
                <Alert tone="danger" title={`${validation.errors.length} Fehler`}>
                  <ul className="list-disc space-y-1 pl-4">
                    {validation.errors.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </Alert>
              )}
              {validation.warnings.length > 0 && (
                <div className="mt-2">
                  <Alert tone="warning" title="Hinweise">
                    <ul className="list-disc space-y-1 pl-4">
                      {validation.warnings.slice(0, 6).map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </Alert>
                </div>
              )}
              {validation.free_pins.length > 0 && (
                <p className="mt-2 text-xs text-ink-500">
                  {validation.free_pins.length} nicht angeschlossene Anschlüsse.
                </p>
              )}
            </div>
          )}

          <div className="text-xs text-ink-500">
            <p className="font-semibold text-ink-700">Tastenkürzel</p>
            <ul className="mt-1 space-y-0.5">
              <li>V / W / J / H: Werkzeug</li>
              <li>R: drehen, Entf: löschen</li>
              <li>Strg+Z / Strg+Y: Undo/Redo</li>
              <li>Strg+C / Strg+V / Strg+D</li>
              <li>Pfeiltasten: verschieben</li>
            </ul>
          </div>

          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => navigate("/schaltplan")}
          >
            Projektliste
          </button>
        </aside>
      </div>

      {editingLabel && (
        <LabelDialog
          componentId={editingLabel}
          current={
            editor.state.components.find((component) => component.id === editingLabel)?.label ?? ""
          }
          onClose={() => setEditingLabel(null)}
          onSave={(label) => {
            editor.updateComponents([{ id: editingLabel, patch: { label } }]);
            setEditingLabel(null);
          }}
        />
      )}
    </div>
  );
}

function LabelDialog({
  componentId,
  current,
  onClose,
  onSave,
}: {
  componentId: string;
  current: string;
  onClose: () => void;
  onSave: (label: string) => void;
}) {
  const [value, setValue] = useState(current);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 p-4"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-lift">
        <h3 className="text-base font-semibold text-ink-900">Bezeichnung ändern</h3>
        <p className="mt-1 text-xs text-ink-500">Bauteil {componentId}</p>
        <input
          autoFocus
          className="input mt-3"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSave(value);
            if (event.key === "Escape") onClose();
          }}
        />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Abbrechen
          </button>
          <button type="button" className="btn-primary" onClick={() => onSave(value)}>
            Übernehmen
          </button>
        </div>
      </div>
    </div>
  );
}
