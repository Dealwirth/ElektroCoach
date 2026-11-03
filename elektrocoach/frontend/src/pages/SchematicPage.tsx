/** Übersicht der Schaltplan-Projekte: anlegen, duplizieren, exportieren. */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import {
  Alert,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  SectionTitle,
  Spinner,
  formatDate,
  useAsync,
} from "../components/ui";

export default function SchematicPage() {
  const navigate = useNavigate();
  const projects = useAsync(() => api.schematicProjects(), []);
  const library = useAsync(() => api.schematicLibrary(), []);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState<"leer" | "stromkreis" | "verteilung">("stromkreis");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const result = await api.createSchematic({
        name: name.trim() || "Neuer Schaltplan",
        description,
        data: templateData(template),
      });
      navigate(`/schaltplan/editor/${result.id}`);
    } catch (error) {
      setMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Schaltplan-Editor"
        subtitle="Elektrische Schalt- und Verdrahtungspläne nach IEC-Konventionen erstellen."
        actions={
          <button type="button" className="btn-primary" onClick={() => setShowNew(true)}>
            Neuer Schaltplan
          </button>
        }
      />

      {message && (
        <Alert tone={message.tone} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle title="Meine Projekte" subtitle="Gespeicherte Schaltpläne." />
          {projects.loading && <Spinner />}
          {projects.data && projects.data.items.length === 0 && (
            <EmptyState
              title="Noch keine Projekte"
              description="Erstelle einen Schaltplan mit 20-px-Raster, echten Anschlüssen und Leitungen."
              action={
                <button type="button" className="btn-primary" onClick={() => setShowNew(true)}>
                  Erstes Projekt anlegen
                </button>
              }
            />
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {projects.data?.items.map((project) => (
              <div key={project.id} className="rounded-xl border border-ink-100 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-ink-900">{project.name}</p>
                    {project.description && (
                      <p className="truncate text-xs text-ink-500">{project.description}</p>
                    )}
                  </div>
                  <span className="badge-neutral">{project.grid} px</span>
                </div>
                {project.stats && (
                  <p className="mt-2 text-xs text-ink-500">
                    {project.stats.components} Bauteile · {project.stats.wires} Leitungen ·{" "}
                    {project.stats.wire_length_m} m Leitungslänge
                  </p>
                )}
                <p className="mt-1 text-xs text-ink-400">Geändert {formatDate(project.updated_at)}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    className="btn-primary btn-sm"
                    onClick={() => navigate(`/schaltplan/editor/${project.id}`)}
                  >
                    Öffnen
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-sm"
                    onClick={async () => {
                      const copy = await api.duplicateSchematic(project.id);
                      projects.reload();
                      navigate(`/schaltplan/editor/${copy.id}`);
                    }}
                  >
                    Kopie
                  </button>
                  <a className="btn-secondary btn-sm" href={api.schematicSvgUrl(project.id)} download>
                    SVG
                  </a>
                  <a className="btn-secondary btn-sm" href={api.schematicJsonUrl(project.id)} download>
                    JSON
                  </a>
                  <button
                    type="button"
                    className="btn-ghost btn-sm text-red-600"
                    onClick={async () => {
                      if (!window.confirm(`Projekt „${project.name}“ löschen?`)) return;
                      await api.deleteSchematic(project.id);
                      projects.reload();
                    }}
                  >
                    Löschen
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle title="Symbolbibliothek" subtitle="Verfügbare IEC-Bauteile." />
          {library.loading && <Spinner />}
          <div className="max-h-[420px] space-y-4 overflow-y-auto pr-1 scrollbar-thin">
            {library.data &&
              Object.entries(library.data.categories).map(([category, symbols]) => (
                <div key={category}>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
                    {category}
                  </p>
                  <ul className="space-y-1">
                    {symbols.map((symbol) => (
                      <li key={symbol.type} className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate text-ink-700">{symbol.name}</span>
                        <span className="shrink-0 text-xs text-ink-400">
                          {symbol.pins.length} Anschlüsse
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
          </div>
        </Card>
      </div>

      <Modal
        open={showNew}
        title="Neuer Schaltplan"
        onClose={() => setShowNew(false)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowNew(false)}>
              Abbrechen
            </button>
            <button type="button" className="btn-primary" onClick={create} disabled={busy}>
              {busy ? "Wird erstellt …" : "Anlegen und öffnen"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="proj-name">
              Name
            </label>
            <input
              id="proj-name"
              className="input"
              placeholder="z. B. Ausschaltung mit Steckdose"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="proj-desc">
              Beschreibung (optional)
            </label>
            <input
              id="proj-desc"
              className="input"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="proj-template">
              Vorlage
            </label>
            <select
              id="proj-template"
              className="input"
              value={template}
              onChange={(event) => setTemplate(event.target.value as typeof template)}
            >
              <option value="stromkreis">Stromkreis (L1 – LS – Leuchte – N)</option>
              <option value="verteilung">Verteilung (RCD – LS – Steckdose)</option>
              <option value="leer">Leere Zeichenfläche</option>
            </select>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function templateData(template: "leer" | "stromkreis" | "verteilung") {
  if (template === "leer") {
    return { components: [], wires: [], junctions: [] };
  }
  if (template === "verteilung") {
    return {
      components: [
        { id: "c1", type: "supply_l1", x: 40, y: 60, rotation: 0, label: "L1" },
        { id: "c2", type: "supply_n", x: 40, y: 200, rotation: 0, label: "N" },
        { id: "c3", type: "supply_pe", x: 40, y: 300, rotation: 0, label: "PE" },
        { id: "c4", type: "rcd", x: 160, y: 60, rotation: 0, label: "FI1" },
        { id: "c5", type: "mcb", x: 340, y: 60, rotation: 0, label: "F1" },
        { id: "c6", type: "socket", x: 520, y: 60, rotation: 0, label: "X1" },
      ],
      wires: [
        {
          id: "w1",
          from: { component_id: "c1", pin_id: "L1" },
          to: { component_id: "c4", pin_id: "L1" },
          points: [{ x: 120, y: 80 }, { x: 120, y: 80 }],
        },
        {
          id: "w2",
          from: { component_id: "c4", pin_id: "L1'" },
          to: { component_id: "c5", pin_id: "1" },
          points: [{ x: 300, y: 80 }],
        },
        {
          id: "w3",
          from: { component_id: "c5", pin_id: "2" },
          to: { component_id: "c6", pin_id: "L" },
          points: [{ x: 460, y: 80 }, { x: 460, y: 75 }, { x: 520, y: 75 }],
        },
      ],
      junctions: [],
    };
  }
  return {
    components: [
      { id: "c1", type: "supply_l1", x: 40, y: 80, rotation: 0, label: "L1" },
      { id: "c2", type: "mcb", x: 160, y: 80, rotation: 0, label: "F1" },
      { id: "c3", type: "switch", x: 300, y: 80, rotation: 0, label: "S1" },
      { id: "c4", type: "lamp", x: 460, y: 80, rotation: 0, label: "H1" },
      { id: "c5", type: "supply_n", x: 620, y: 80, rotation: 0, label: "N" },
    ],
    wires: [
      {
        id: "w1",
        from: { component_id: "c1", pin_id: "L1" },
        to: { component_id: "c2", pin_id: "1" },
        points: [{ x: 120, y: 100 }, { x: 120, y: 95 }, { x: 160, y: 95 }],
      },
      {
        id: "w2",
        from: { component_id: "c2", pin_id: "2" },
        to: { component_id: "c3", pin_id: "1" },
        points: [{ x: 260, y: 95 }, { x: 260, y: 100 }, { x: 300, y: 100 }],
      },
      {
        id: "w3",
        from: { component_id: "c3", pin_id: "2" },
        to: { component_id: "c4", pin_id: "1" },
        points: [{ x: 400, y: 100 }, { x: 460, y: 100 }],
      },
      {
        id: "w4",
        from: { component_id: "c4", pin_id: "2" },
        to: { component_id: "c5", pin_id: "N" },
        points: [{ x: 560, y: 110 }, { x: 560, y: 100 }, { x: 660, y: 100 }],
      },
    ],
    junctions: [],
  };
}
