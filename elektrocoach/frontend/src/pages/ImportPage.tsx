/**
 * Import: Samsung Notes, PDF, Bilder, Text und ZIP-Sammlungen.
 * Drag-and-Drop, Mehrfachauswahl und Fortschrittsanzeige.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import {
  Alert,
  Card,
  EmptyState,
  PageHeader,
  ProgressBar,
  SectionTitle,
  StatusBadge,
  formatBytes,
  formatDate,
} from "../components/ui";
import type { ImportJob, RefineJob } from "../types";

interface Formats {
  samsung_direct: { supported: boolean; suffixes: string[]; note: string };
  recommended: { format: string; note: string };
  accepted: string[];
  note?: string;
}

export default function ImportPage() {
  const [formats, setFormats] = useState<Formats | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [collection, setCollection] = useState("");
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [activeJob, setActiveJob] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [refineJobs, setRefineJobs] = useState<RefineJob[]>([]);
  const [activeRefine, setActiveRefine] = useState<RefineJob | null>(null);
  const [refineBusy, setRefineBusy] = useState(false);
  const [refineMessage, setRefineMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);
  const refinePollRef = useRef<number | null>(null);

  const loadRefineJobs = useCallback(async () => {
    try {
      const data = await api.refineJobs(10);
      setRefineJobs(data.items);
    } catch {
      /* Liste ist nicht kritisch */
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const data = await api.importJobs(10);
      setJobs(data.items);
    } catch {
      /* Liste ist nicht kritisch */
    }
  }, []);

  useEffect(() => {
    api
      .importFormats()
      .then((data) => setFormats(data as unknown as Formats))
      .catch(() => undefined);
    loadJobs();
    loadRefineJobs();
  }, [loadJobs, loadRefineJobs]);

  useEffect(() => {
    if (!activeJob || ["done", "error", "cancelled"].includes(activeJob.status)) {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const job = await api.importJob(activeJob.id);
        setActiveJob(job);
        if (["done", "error", "cancelled"].includes(job.status)) {
          loadJobs();
        }
      } catch {
        /* kurze Netzfehler ignorieren */
      }
    }, 1000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [activeJob, loadJobs]);

  useEffect(() => {
    if (!activeRefine || ["done", "error", "cancelled"].includes(activeRefine.status)) {
      if (refinePollRef.current) {
        window.clearInterval(refinePollRef.current);
        refinePollRef.current = null;
      }
      return;
    }
    refinePollRef.current = window.setInterval(async () => {
      try {
        const job = await api.refineJob(activeRefine.id);
        setActiveRefine(job);
        if (["done", "error", "cancelled"].includes(job.status)) {
          loadRefineJobs();
        }
      } catch {
        /* kurze Netzfehler ignorieren */
      }
    }, 1500);
    return () => {
      if (refinePollRef.current) window.clearInterval(refinePollRef.current);
    };
  }, [activeRefine, loadRefineJobs]);

  const addFiles = (incoming: FileList | File[]) => {
    const list = Array.from(incoming);
    setFiles((current) => {
      const known = new Set(current.map((file) => `${file.name}:${file.size}`));
      const merged = [...current];
      list.forEach((file) => {
        if (!known.has(`${file.name}:${file.size}`)) merged.push(file);
      });
      return merged;
    });
    setMessage(null);
  };

  const startImport = async () => {
    if (files.length === 0) {
      setMessage({ tone: "warning", text: "Bitte zuerst Dateien auswählen." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.upload(files, collection.trim() || undefined);
      const rejected = result.rejected ?? [];
      setMessage({
        tone: rejected.length ? "warning" : "success",
        text:
          `${result.accepted} Datei(en) angenommen.` +
          (rejected.length
            ? ` ${rejected.length} abgelehnt: ${rejected
                .map((item) => `${item.filename} (${item.error})`)
                .join(", ")}`
            : ""),
      });
      setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
      const job = await api.importJob(result.job_id);
      setActiveJob(job);
      loadJobs();
    } catch (error) {
      setMessage({
        tone: "danger",
        text: error instanceof ApiError ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async (id: string) => {
    try {
      await api.cancelJob(id);
      const job = await api.importJob(id);
      setActiveJob(job);
      loadJobs();
    } catch (error) {
      setMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    }
  };

  const startRefine = async (scope: "review" | "document", documentId?: string | null) => {
    setRefineBusy(true);
    setRefineMessage(null);
    try {
      const result = await api.startRefine(documentId ?? null, scope);
      const job = await api.refineJob(result.job_id);
      setActiveRefine(job);
      setRefineMessage({ tone: "success", text: "Nachbearbeitung gestartet." });
      loadRefineJobs();
    } catch (error) {
      setRefineMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setRefineBusy(false);
    }
  };

  const cancelRefine = async (id: string) => {
    try {
      await api.cancelRefine(id);
      const job = await api.refineJob(id);
      setActiveRefine(job);
      loadRefineJobs();
    } catch (error) {
      setRefineMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    }
  };

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Aufzeichnungen importieren"
        subtitle="Samsung Notes, PDF, Bilder, Text und ZIP-Sammlungen. Mehrere Dateien oder ganze Ordner auf einmal."
      />

      {message && (
        <Alert tone={message.tone} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle
            title="Dateien auswählen"
            subtitle="Ziehe Dateien hierher oder wähle sie über den Button."
          />
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
            }}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
              dragging ? "border-brand-500 bg-brand-50" : "border-ink-200 bg-ink-50"
            }`}
          >
            <p className="text-sm font-medium text-ink-700">
              Dateien hier ablegen
            </p>
            <p className="mt-1 text-xs text-ink-500">
              Unterstützt: PDF, PNG, JPG, WEBP, TIFF, TXT, HTML, ZIP, SDOC, SNOTE, TAR
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              accept={formats?.accepted?.join(",") ?? undefined}
              onChange={(event) => event.target.files && addFiles(event.target.files)}
            />
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <button type="button" className="btn-primary" onClick={() => inputRef.current?.click()}>
                Dateien wählen
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setFiles([]);
                  if (inputRef.current) inputRef.current.value = "";
                }}
                disabled={files.length === 0}
              >
                Liste leeren
              </button>
            </div>
          </div>

          {files.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span className="font-medium text-ink-700">
                  {files.length} Datei(en), {formatBytes(totalSize)}
                </span>
              </div>
              <ul className="max-h-56 space-y-1.5 overflow-y-auto rounded-xl border border-ink-100 p-2 scrollbar-thin">
                {files.map((file) => (
                  <li
                    key={`${file.name}:${file.size}`}
                    className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-ink-50"
                  >
                    <span className="truncate text-ink-700">{file.name}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="text-xs text-ink-400">{formatBytes(file.size)}</span>
                      <button
                        type="button"
                        className="text-xs text-red-600 hover:underline"
                        onClick={() =>
                          setFiles((current) =>
                            current.filter(
                              (item) => !(item.name === file.name && item.size === file.size),
                            ),
                          )
                        }
                      >
                        entfernen
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-end gap-3">
            <div className="min-w-[200px] flex-1">
              <label className="label" htmlFor="collection">
                Sammlung (optional)
              </label>
              <input
                id="collection"
                className="input"
                placeholder="z. B. Lehrjahr 2"
                value={collection}
                onChange={(event) => setCollection(event.target.value)}
              />
            </div>
            <button type="button" className="btn-primary" onClick={startImport} disabled={busy || files.length === 0}>
              {busy ? "Wird hochgeladen …" : "Import starten"}
            </button>
          </div>
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionTitle title="Samsung Notes" />
            <div className="space-y-3 text-sm text-ink-600">
              <p>
                Direkter Import von Samsung-Notes-Sicherungen (.sdoc, .snote) ist möglich, wenn
                darin enthaltene Texte und Bilder als Archiv vorliegen.
              </p>
              <p className="text-xs text-ink-500">
                Empfohlen: {formats?.recommended.format ?? "PDF-Export"}. {formats?.recommended.note ?? ""}
              </p>
              <div className="rounded-xl bg-ink-50 p-3 text-xs text-ink-600">
                <p className="font-semibold text-ink-700">So exportierst du aus Samsung Notes</p>
                <ol className="mt-1.5 list-decimal space-y-1 pl-4">
                  <li>In Samsung Notes die Notiz öffnen.</li>
                  <li>Menü → Teilen → Als PDF exportieren.</li>
                  <li>Die PDF-Dateien hier hochladen (auch als ZIP).</li>
                </ol>
              </div>
            </div>
          </Card>

          {activeJob && (
            <Card>
              <SectionTitle title="Aktueller Import" />
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <StatusBadge status={activeJob.status} />
                  <span className="text-xs text-ink-500">
                    {activeJob.processed_files} / {activeJob.total_files}
                  </span>
                </div>
                <ProgressBar
                  value={activeJob.progress_percent ?? (activeJob.processed_files / Math.max(1, activeJob.total_files)) * 100}
                />
                {activeJob.current_item && (
                  <p className="truncate text-xs text-ink-500">Aktuell: {activeJob.current_item}</p>
                )}
                {activeJob.message && <p className="text-xs text-ink-600">{activeJob.message}</p>}
                {activeJob.imported !== undefined && (
                  <p className="text-xs text-ink-500">
                    Importiert: {activeJob.imported} · Duplikate: {activeJob.duplicates ?? 0} · Fehler:{" "}
                    {activeJob.failed_files}
                  </p>
                )}
                {!["done", "error", "cancelled"].includes(activeJob.status) && (
                  <button
                    type="button"
                    className="btn-secondary btn-sm"
                    onClick={() => cancelJob(activeJob.id)}
                  >
                    Import abbrechen
                  </button>
                )}
                {Array.isArray(activeJob.results) && activeJob.results.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-ink-600">Ergebnisse je Datei</summary>
                    <ul className="mt-2 space-y-1">
                      {activeJob.results.map((item, index) => (
                        <li key={index} className="flex justify-between gap-2 text-ink-600">
                          <span className="truncate">{String(item.filename ?? "")}</span>
                          <span>{String(item.status ?? item.error ?? "")}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>

      <Card>
        <SectionTitle
          title="KI-Nachbearbeitung erkannter Texte"
          subtitle="Verbessert unsicher erkannte Seiten mit dem lokalen Modell (kostenlos, offline)."
        />
        <div className="space-y-3">
          <p className="text-xs text-ink-500">
            Die Nachbearbeitung korrigiert OCR-Fehler und Formeln. Sie ist optional: Bibliothek, Lernen und
            Schaltplan-Editor funktionieren auch ohne KI vollständig.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() => startRefine("review")}
              disabled={refineBusy}
            >
              Unsichere Seiten nachbearbeiten
            </button>
            <button type="button" className="btn-ghost" onClick={loadRefineJobs} disabled={refineBusy}>
              Status aktualisieren
            </button>
          </div>
          {refineMessage && <Alert tone={refineMessage.tone}>{refineMessage.text}</Alert>}
          {activeRefine && (
            <div className="space-y-2 rounded-xl bg-ink-50 p-3">
              <div className="flex items-center justify-between">
                <StatusBadge status={activeRefine.status} />
                <span className="text-xs text-ink-500">
                  {activeRefine.processed_pages} / {activeRefine.total_pages}
                </span>
              </div>
              <ProgressBar
                value={
                  activeRefine.progress_percent ??
                  (activeRefine.processed_pages / Math.max(1, activeRefine.total_pages)) * 100
                }
              />
              {activeRefine.message && <p className="text-xs text-ink-600">{activeRefine.message}</p>}
              {!["done", "error", "cancelled"].includes(activeRefine.status) && (
                <button type="button" className="btn-secondary btn-sm" onClick={() => cancelRefine(activeRefine.id)}>
                  Nachbearbeitung abbrechen
                </button>
              )}
            </div>
          )}
          {refineJobs.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-ink-600">Verlauf der Nachbearbeitungen</summary>
              <ul className="mt-2 space-y-1">
                {refineJobs.map((job) => (
                  <li key={job.id} className="flex justify-between gap-2 text-ink-600">
                    <span className="truncate">{formatDate(job.created_at)}</span>
                    <span>
                      {job.status} · {job.processed_pages}/{job.total_pages}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="Importverlauf"
          subtitle="Die letzten Aufträge. Fehlgeschlagene Dateien werden einzeln aufgeführt."
        />
        {jobs.length === 0 ? (
          <EmptyState title="Noch keine Importe" description="Starte oben den ersten Import." />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base min-w-[640px]">
              <thead>
                <tr>
                  <th>Zeitpunkt</th>
                  <th>Status</th>
                  <th>Dateien</th>
                  <th>Ergebnis</th>
                  <th>Meldung</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td className="whitespace-nowrap text-ink-600">{formatDate(job.created_at)}</td>
                    <td>
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="text-ink-600">
                      {job.processed_files}/{job.total_files}
                    </td>
                    <td className="text-ink-600">
                      {job.imported !== undefined
                        ? `${job.imported} importiert, ${job.duplicates ?? 0} Duplikate, ${job.failed_files} Fehler`
                        : "–"}
                    </td>
                    <td className="max-w-[280px] truncate text-ink-500">{job.message || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
