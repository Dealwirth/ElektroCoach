/** Bibliothek: importierte Dokumente, Seiten, Volltextsuche und Prüfansicht. */

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import {
  Alert,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  SectionTitle,
  Spinner,
  StatusBadge,
  Tabs,
  formatBytes,
  formatDate,
  useAsync,
} from "../components/ui";
import type { DocumentItem, PageItem } from "../types";

type TabId = "dokumente" | "suche" | "pruefen";

export default function LibraryPage() {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabId>("dokumente");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Array<Record<string, unknown>>>([]);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);

  const documents = useAsync(() => api.documents({ limit: 200 }), []);
  const review = useAsync(() => api.reviewPages(100), [tab]);

  const openDocument = documentId ?? null;

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setMessage(null);
    try {
      const result = await api.search(query.trim(), 30);
      setSearchResults(result.results);
      if (result.count === 0) {
        setMessage({ tone: "warning", text: "Keine Treffer gefunden." });
      }
    } catch (error) {
      setMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setSearching(false);
    }
  };

  const removeDocument = async (id: string) => {
    if (!window.confirm("Dieses Dokument und alle erkannten Abschnitte löschen?")) return;
    try {
      await api.deleteDocument(id);
      setMessage({ tone: "success", text: "Dokument gelöscht." });
      documents.reload();
      if (openDocument === id) navigate("/bibliothek");
    } catch (error) {
      setMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bibliothek"
        subtitle="Alle importierten Aufzeichnungen, erkannter Text und Volltextsuche."
        actions={
          <Link to="/import" className="btn-primary">
            Weitere Aufzeichnungen importieren
          </Link>
        }
      />

      {message && (
        <Alert tone={message.tone} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <Tabs<TabId>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "dokumente", label: "Dokumente", badge: documents.data?.total },
          { id: "suche", label: "Volltextsuche" },
          { id: "pruefen", label: "Prüfen", badge: review.data?.count },
        ]}
      />

      {tab === "dokumente" && (
        <Card>
          <SectionTitle
            title="Importierte Dokumente"
            subtitle={`${documents.data?.total ?? 0} Dokumente in der Wissensbasis.`}
          />
          {documents.loading && <Spinner />}
          {documents.error && <Alert tone="danger">{documents.error}</Alert>}
          {documents.data && documents.data.items.length === 0 && (
            <EmptyState
              title="Noch keine Dokumente"
              description="Importiere PDF-, Bild- oder Textdateien, um die Wissensbasis aufzubauen."
              action={
                <Link to="/import" className="btn-primary">
                  Jetzt importieren
                </Link>
              }
            />
          )}
          {documents.data && documents.data.items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table-base min-w-[720px]">
                <thead>
                  <tr>
                    <th>Datei</th>
                    <th>Sammlung</th>
                    <th>Seiten</th>
                    <th>Status</th>
                    <th>Importiert</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {documents.data.items.map((document) => (
                    <DocumentRow
                      key={document.id}
                      document={document}
                      onOpen={() => navigate(`/bibliothek/${document.id}`)}
                      onDelete={() => removeDocument(document.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === "suche" && (
        <Card>
          <SectionTitle
            title="Volltextsuche"
            subtitle="Schnelle Suche über alle erkannten Abschnitte (SQLite FTS5)."
          />
          <div className="flex flex-wrap gap-2">
            <input
              className="input flex-1 min-w-[220px]"
              placeholder="z. B. Spannungsfall, RCD, Sternschaltung"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && runSearch()}
            />
            <button type="button" className="btn-primary" onClick={runSearch} disabled={searching}>
              {searching ? "Suche …" : "Suchen"}
            </button>
          </div>
          <div className="mt-5 space-y-3">
            {searchResults.length === 0 && !searching && (
              <p className="text-sm text-ink-500">Noch keine Suche durchgeführt.</p>
            )}
            {searchResults.map((hit, index) => (
              <article key={index} className="rounded-xl border border-ink-100 p-4">
                <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-500">
                  <span className="badge-brand">
                    Seite {String(hit.page_number ?? "–")}
                  </span>
                  <span className="truncate">{String(hit.filename ?? "")}</span>
                  {hit.heading ? <span className="truncate">· {String(hit.heading)}</span> : null}
                </div>
                <p className="text-sm leading-relaxed text-ink-800">{String(hit.text ?? "")}</p>
                {hit.document_id ? (
                  <button
                    type="button"
                    className="btn-ghost btn-sm mt-2"
                    onClick={() => navigate(`/bibliothek/${String(hit.document_id)}`)}
                  >
                    Im Dokument öffnen
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        </Card>
      )}

      {tab === "pruefen" && (
        <Card>
          <SectionTitle
            title="Unsicher erkannte Seiten"
            subtitle="Diese Seiten wurden mit geringer Sicherheit erkannt. Bitte Text kontrollieren und korrigieren."
          />
          {review.loading && <Spinner />}
          {review.data && review.data.items.length === 0 && (
            <EmptyState title="Nichts zu prüfen" description="Alle Seiten wurden sicher erkannt." />
          )}
          <div className="space-y-3">
            {review.data?.items.map((item, index) => (
              <ReviewPageCard
                key={index}
                page={item as unknown as PageItem & { filename?: string }}
                onSaved={() => {
                  review.reload();
                  documents.reload();
                }}
              />
            ))}
          </div>
        </Card>
      )}

      {openDocument && (
        <DocumentModal
          documentId={openDocument}
          onClose={() => navigate("/bibliothek")}
          onChanged={() => documents.reload()}
        />
      )}
    </div>
  );
}

function DocumentRow({
  document,
  onOpen,
  onDelete,
}: {
  document: DocumentItem;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <tr>
      <td className="max-w-[260px]">
        <button type="button" className="truncate font-medium text-brand-700 hover:underline" onClick={onOpen}>
          {document.filename}
        </button>
        <p className="text-xs text-ink-400">{formatBytes(document.size_bytes)}</p>
      </td>
      <td className="text-ink-600">{document.collection || "–"}</td>
      <td className="text-ink-600">{document.page_count}</td>
      <td>
        <StatusBadge status={document.status} />
        {document.needs_review_count > 0 && (
          <span className="badge-warning ml-1">{document.needs_review_count}</span>
        )}
      </td>
      <td className="whitespace-nowrap text-ink-500">{formatDate(document.created_at)}</td>
      <td className="text-right">
        <div className="flex justify-end gap-1">
          <button type="button" className="btn-ghost btn-sm" onClick={onOpen}>
            Öffnen
          </button>
          <button type="button" className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
            Löschen
          </button>
        </div>
      </td>
    </tr>
  );
}

function DocumentModal({
  documentId,
  onClose,
  onChanged,
}: {
  documentId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .document(documentId)
      .then((data) => {
        if (!active) return;
        setName(data.filename);
        setPages(data.pages);
      })
      .catch((err: unknown) => active && setError(err instanceof Error ? err.message : String(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [documentId]);

  return (
    <Modal open title={name || "Dokument"} onClose={onClose} wide>
      {loading && <Spinner />}
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="space-y-5">
        {pages.map((page) => (
          <div key={page.id} className="rounded-xl border border-ink-100 p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="badge-brand">Seite {page.page_number}</span>
                {page.needs_review ? <span className="badge-warning">unsicher erkannt</span> : null}
                {page.ocr_confidence !== null && (
                  <span className="badge-neutral">
                    OCR {Math.round(page.ocr_confidence)} %
                  </span>
                )}
              </div>
              <a
                href={api.pageImageUrl(page.id)}
                target="_blank"
                rel="noreferrer"
                className="btn-ghost btn-sm"
              >
                Originalbild
              </a>
            </div>
            {page.image_path ? (
              <img
                src={api.pageImageUrl(page.id)}
                alt={`Original Seite ${page.page_number}`}
                className="mb-3 max-h-72 w-full rounded-lg border border-ink-100 object-contain"
                loading="lazy"
              />
            ) : null}
            <PageTextEditor
              pageId={page.id}
              initialText={page.text}
              onSaved={() => {
                api.document(documentId).then((data) => setPages(data.pages)).catch(() => undefined);
                onChanged();
              }}
            />
          </div>
        ))}
      </div>
    </Modal>
  );
}

function PageTextEditor({
  pageId,
  initialText,
  onSaved,
}: {
  pageId: string;
  initialText: string;
  onSaved: () => void;
}) {
  const [text, setText] = useState(initialText);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setText(initialText);
  }, [initialText]);

  const save = async () => {
    setBusy(true);
    setSaved(false);
    try {
      await api.updatePageText(pageId, text, true);
      setSaved(true);
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <label className="label" htmlFor={`page-${pageId}`}>
        Erkannter Text (bearbeitbar)
      </label>
      <textarea
        id={`page-${pageId}`}
        className="input min-h-[140px] font-mono text-xs leading-relaxed"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="mt-2 flex items-center gap-2">
        <button type="button" className="btn-secondary btn-sm" onClick={save} disabled={busy}>
          {busy ? "Speichern …" : "Text speichern"}
        </button>
        {saved && <span className="text-xs text-emerald-700">Gespeichert und neu indexiert.</span>}
      </div>
    </div>
  );
}

function ReviewPageCard({
  page,
  onSaved,
}: {
  page: PageItem & { filename?: string };
  onSaved: () => void;
}) {
  const [text, setText] = useState(page.text);
  const [busy, setBusy] = useState(false);

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-600">
        <span className="badge-warning">zu prüfen</span>
        <span>Seite {page.page_number}</span>
        <span className="truncate">{page.filename}</span>
        {page.ocr_confidence !== null && <span>OCR {Math.round(page.ocr_confidence)} %</span>}
      </div>
      <textarea
        className="input min-h-[120px] font-mono text-xs"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          className="btn-primary btn-sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.updatePageText(page.id, text, true);
              onSaved();
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Speichern …" : "Bestätigen und speichern"}
        </button>
        <a href={api.pageImageUrl(page.id)} target="_blank" rel="noreferrer" className="btn-secondary btn-sm">
          Original ansehen
        </a>
      </div>
    </div>
  );
}
