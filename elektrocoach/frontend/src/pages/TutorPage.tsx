/** KI-Tutor: Fragen zu den eigenen Aufzeichnungen, Erklärungen und Transparenz. */

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import {
  Alert,
  Card,
  EmptyState,
  PageHeader,
  SectionTitle,
  Spinner,
  Tabs,
  useAsync,
} from "../components/ui";

type TabId = "chat" | "erklaeren";

interface ChatEntry {
  role: "user" | "assistant" | "system";
  text: string;
  provider?: string;
  external?: boolean;
  fallback?: boolean;
  sources?: Array<Record<string, unknown>>;
  hint?: string;
}

export default function TutorPage() {
  const [tab, setTab] = useState<TabId>("chat");
  const status = useAsync(() => api.aiStatus(), []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="KI-Tutor"
        subtitle="Fragen zu deinen Aufzeichnungen. Lokale KI bevorzugt, Cloud nur bei Bedarf."
      />

      {status.data && !status.data.any_available && (
        <Alert tone="warning" title="Keine KI erreichbar">
          ElektroCoach arbeitet weiterhin vollständig: Bibliothek, Suche, Lernen, Prüfungen und der
          Schaltplan-Editor benötigen keine KI. Für Tutor-Antworten richte bitte Ollama oder einen
          Gemini-Schlüssel ein (Einstellungen → KI).
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Tabs<TabId>
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "chat", label: "Fragen stellen" },
              { id: "erklaeren", label: "Thema erklären" },
            ]}
          />
          {tab === "chat" && <ChatPanel />}
          {tab === "erklaeren" && <ExplainPanel />}
        </div>

        <Card>
          <SectionTitle title="KI-Status" subtitle="Transparenz über verwendete Dienste." />
          {status.loading && <Spinner />}
          {status.data && (
            <div className="space-y-4 text-sm">
              <div>
                <p className="font-medium text-ink-800">Lokales Modell (Ollama)</p>
                <p className="text-xs text-ink-500">
                  {status.data.ollama.available
                    ? `Bereit · Modell ${status.data.ollama.model ?? "–"}`
                    : `Inaktiv${status.data.ollama.reason ? ` · ${status.data.ollama.reason}` : ""}`}
                </p>
                {status.data.ollama.models && status.data.ollama.models.length > 0 && (
                  <p className="mt-1 text-xs text-ink-400">
                    Installiert: {status.data.ollama.models.slice(0, 5).join(", ")}
                  </p>
                )}
              </div>
              <div>
                <p className="font-medium text-ink-800">Cloud (Gemini Free Tier)</p>
                <p className="text-xs text-ink-500">
                  {status.data.gemini.available
                    ? `Bereit · Modell ${status.data.gemini.text_model ?? "–"}`
                    : `Inaktiv${status.data.gemini.reason ? ` · ${status.data.gemini.reason}` : ""}`}
                </p>
                {status.data.gemini.quota && (
                  <p className="mt-1 text-xs text-ink-400">
                    Kontingent heute: {status.data.gemini.quota.used} von {status.data.gemini.quota.limit}
                  </p>
                )}
              </div>
              <Alert tone="info" title="Datenschutz">
                Anfragen laufen zuerst lokal. Nur wenn du die Cloud ausdrücklich nutzt oder das lokale
                Modell nicht erreichbar ist, werden Inhalte an Gemini gesendet. Antworten sind mit der
                Quelle gekennzeichnet.
              </Alert>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function ChatPanel() {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [useLibrary, setUseLibrary] = useState(true);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  const send = async () => {
    const message = input.trim();
    if (!message) return;
    setEntries((current) => [...current, { role: "user", text: message }]);
    setInput("");
    setBusy(true);
    try {
      const result = await api.chat(message, useLibrary);
      setEntries((current) => [
        ...current,
        result.ok
          ? {
              role: "assistant",
              text: result.answer ?? "",
              provider: result.provider,
              external: result.external,
              fallback: result.fallback_used,
              sources: result.sources,
            }
          : {
              role: "system",
              text: result.error ?? "Keine Antwort erhalten.",
              hint: result.hint,
            },
      ]);
    } catch (error) {
      setEntries((current) => [
        ...current,
        { role: "system", text: error instanceof ApiError ? error.message : String(error) },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between gap-3">
        <SectionTitle title="Fragen zu deinen Unterlagen" />
        <label className="flex items-center gap-2 text-xs text-ink-600">
          <input
            type="checkbox"
            checked={useLibrary}
            onChange={(event) => setUseLibrary(event.target.checked)}
            className="h-4 w-4 rounded border-ink-300"
          />
          Wissensbasis einbeziehen
        </label>
      </div>

      <div className="max-h-[440px] space-y-3 overflow-y-auto pr-1 scrollbar-thin">
        {entries.length === 0 && (
          <EmptyState
            title="Stelle deine erste Frage"
            description="Zum Beispiel: „Erkläre den Unterschied zwischen RCD und Leitungsschutzschalter.“"
          />
        )}
        {entries.map((entry, index) => (
          <div
            key={index}
            className={`rounded-xl px-4 py-3 text-sm ${
              entry.role === "user"
                ? "ml-8 bg-brand-600 text-white"
                : entry.role === "assistant"
                  ? "mr-8 border border-ink-100 bg-white"
                  : "border border-amber-200 bg-amber-50 text-amber-900"
            }`}
          >
            <p className="whitespace-pre-wrap leading-relaxed">{entry.text}</p>
            {entry.role === "assistant" && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {entry.provider && (
                  <span className={entry.external ? "badge-warning" : "badge-success"}>
                    {entry.external ? `Cloud: ${entry.provider}` : `lokal: ${entry.provider}`}
                  </span>
                )}
                {entry.fallback && <span className="badge-neutral">Ausweichmodell</span>}
              </div>
            )}
            {entry.sources && entry.sources.length > 0 && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer text-ink-500">Quellen aus deinen Unterlagen</summary>
                <ul className="mt-1.5 space-y-1">
                  {entry.sources.map((source, sourceIndex) => (
                    <li key={sourceIndex} className="rounded-lg bg-ink-50 p-2 text-ink-600">
                      Seite {String(source.page_number ?? "–")} · {String(source.filename ?? "")}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {entry.hint && <p className="mt-1.5 text-xs opacity-80">{entry.hint}</p>}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="mt-4 flex gap-2">
        <input
          className="input flex-1"
          placeholder="Frage eingeben …"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && !busy && send()}
          disabled={busy}
        />
        <button type="button" className="btn-primary" onClick={send} disabled={busy || !input.trim()}>
          {busy ? "Denkt …" : "Senden"}
        </button>
      </div>
    </Card>
  );
}

function ExplainPanel() {
  const [question, setQuestion] = useState("");
  const [level, setLevel] = useState("pruefung");
  const [answer, setAnswer] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      const result = await api.explain(question.trim(), undefined, level);
      if (result.ok) {
        setAnswer(result.answer ?? "");
        setProvider(result.provider ?? null);
      } else {
        setError(result.error ?? "Keine Antwort erhalten.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <SectionTitle
        title="Thema erklären lassen"
        subtitle="Ausführliche Erklärung mit Formeln und Beispielen."
      />
      <div className="space-y-4">
        <div>
          <label className="label" htmlFor="explain-question">
            Frage oder Thema
          </label>
          <textarea
            id="explain-question"
            className="input min-h-[90px]"
            placeholder="z. B. Wie berechne ich den Spannungsfall in einer Drehstromleitung?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="explain-level">
            Tiefe
          </label>
          <select
            id="explain-level"
            className="input"
            value={level}
            onChange={(event) => setLevel(event.target.value)}
          >
            <option value="grundlagen">Grundlagen</option>
            <option value="pruefung">Prüfungsniveau</option>
            <option value="vertiefung">Vertiefung</option>
          </select>
        </div>
        <button type="button" className="btn-primary" onClick={submit} disabled={busy || !question.trim()}>
          {busy ? "Wird erstellt …" : "Erklärung erstellen"}
        </button>
      </div>

      {error && (
        <div className="mt-4">
          <Alert tone="warning" title="Keine Erklärung möglich">
            {error}
          </Alert>
        </div>
      )}

      {answer && (
        <div className="mt-5 rounded-xl border border-ink-100 bg-ink-50 p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="badge-brand">{provider ?? "KI"}</span>
            <span className="text-xs text-ink-500">Antwort mit KI erstellt – bitte fachlich prüfen.</span>
          </div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink-800">{answer}</div>
        </div>
      )}
    </Card>
  );
}
