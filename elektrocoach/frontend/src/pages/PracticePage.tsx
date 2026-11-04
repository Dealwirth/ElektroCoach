/**
 * Lernen: Themenkatalog, Fragengenerierung, Übungsrunde und Lernplan.
 */

import { useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { AiChooser, useAiChoice } from "../components/AiChooser";
import { HandwritingCanvas, type HandwritingCanvasHandle } from "../components/HandwritingCanvas";
import {
  Alert,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  ProgressBar,
  SectionTitle,
  Spinner,
  Tabs,
  formatDate,
  formatNumber,
  relativeDays,
  useAsync,
} from "../components/ui";
import type { GradeResult, Question, Topic } from "../types";

type TabId = "ueben" | "themen" | "plan" | "fragen";

const QTYPE_LABELS: Record<string, string> = {
  multiple_choice: "Multiple-Choice",
  open: "Offene Frage",
  calculation: "Rechenaufgabe",
  practical: "Praxisaufgabe",
  cloze: "Lückentext",
  true_false: "Richtig/Falsch",
};

export default function PracticePage() {
  const [tab, setTab] = useState<TabId>("ueben");
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning" | "info"; text: string } | null>(null);

  const due = useAsync(() => api.dueQuestions(30), [tab]);
  const topics = useAsync(() => api.topics(), [tab]);
  const plan = useAsync(() => api.plan(), [tab]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lernen"
        subtitle="Aufgaben mit Spaced Repetition, Themenkatalog und persönlicher Lernplan."
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
          { id: "ueben", label: "Üben", badge: due.data?.count },
          { id: "themen", label: "Themen", badge: topics.data?.items.length },
          { id: "plan", label: "Lernplan" },
          { id: "fragen", label: "Fragenkatalog" },
        ]}
      />

      {tab === "ueben" && (
        <PracticeSession
          onMessage={setMessage}
          onFinished={() => {
            due.reload();
            plan.reload();
          }}
        />
      )}

      {tab === "themen" && (
        <TopicCatalogue
          topics={topics.data?.items ?? []}
          loading={topics.loading}
          onMessage={setMessage}
          onReload={() => {
            topics.reload();
            plan.reload();
          }}
        />
      )}

      {tab === "plan" && <StudyPlanView plan={plan.data} loading={plan.loading} onReload={() => plan.reload()} />}

      {tab === "fragen" && <QuestionCatalogue onMessage={setMessage} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Übungsrunde
// ---------------------------------------------------------------------------
function PracticeSession({
  onMessage,
  onFinished,
}: {
  onMessage: (message: { tone: "success" | "danger" | "warning" | "info"; text: string } | null) => void;
  onFinished: () => void;
}) {
  const [queue, setQueue] = useState<Question[]>([]);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<GradeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState({ answered: 0, correct: 0, points: 0, maxPoints: 0 });
  const { provider, web, setProvider, setWeb } = useAiChoice();
  const [drawMode, setDrawMode] = useState(false);
  const [handwritingBusy, setHandwritingBusy] = useState(false);
  const [handwritingError, setHandwritingError] = useState<string | null>(null);
  const canvasRef = useRef<HandwritingCanvasHandle | null>(null);

  const current = queue[index];

  const transcribe = async () => {
    const handle = canvasRef.current;
    if (!handle || handle.isEmpty()) {
      setHandwritingError("Bitte zuerst schreiben.");
      return;
    }
    setHandwritingBusy(true);
    setHandwritingError(null);
    try {
      const browserText = await handle.browserText();
      const result = await api.aiTranscribe(handle.toDataUrl(), current?.prompt ?? "", browserText);
      if (result.ok && result.text) {
        setAnswer(result.text);
        setDrawMode(false);
      } else {
        setHandwritingError(result.error ?? "Handschrift konnte nicht erkannt werden.");
      }
    } catch (error) {
      setHandwritingError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setHandwritingBusy(false);
    }
  };

  const start = async (useAi: boolean) => {
    setBusy(true);
    onMessage(null);
    try {
      const dueData = await api.dueQuestions(20);
      let items = (dueData.items as unknown as Question[]) ?? [];
      if (items.length < 5) {
        // Wenige fällige Aufgaben: zusätzliche generieren.
        const generated = await api.generateQuestions({
          count: 10,
          use_ai: useAi,
          qtype: "mixed",
          difficulty: 2,
        });
        items = [...items, ...generated.questions];
        if (generated.note) {
          onMessage({ tone: "info", text: generated.note });
        }
      }
      if (items.length === 0) {
        onMessage({
          tone: "warning",
          text: "Keine Aufgaben verfügbar. Bitte zuerst Aufzeichnungen importieren und Themen analysieren.",
        });
        return;
      }
      setQueue(items);
      setIndex(0);
      setResult(null);
      setAnswer("");
      setSelected(null);
      setStats({ answered: 0, correct: 0, points: 0, maxPoints: 0 });
    } catch (error) {
      onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  const submit = async (useAi: boolean) => {
    if (!current) return;
    const value = current.qtype === "multiple_choice" ? selected ?? "" : answer;
    if (!value.trim()) {
      onMessage({ tone: "warning", text: "Bitte eine Antwort eingeben." });
      return;
    }
    setBusy(true);
    try {
      const graded = await api.answerQuestion(current.id, {
        answer: value,
        use_ai: useAi,
        provider: useAi ? provider : "local_only",
      });
      setResult(graded);
      setStats((previous) => ({
        answered: previous.answered + 1,
        correct: previous.correct + (graded.correct ? 1 : 0),
        points: previous.points + graded.score,
        maxPoints: previous.maxPoints + graded.max_points,
      }));
      onFinished();
    } catch (error) {
      onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  const next = () => {
    setResult(null);
    setAnswer("");
    setSelected(null);
    setIndex((value) => value + 1);
  };

  if (queue.length === 0) {
    return (
      <Card>
        <SectionTitle
          title="Übungsrunde starten"
          subtitle="Fällige Wiederholungen werden zuerst gestellt, danach neue Aufgaben."
        />
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" onClick={() => start(true)} disabled={busy}>
            {busy ? "Wird vorbereitet …" : "Runde starten"}
          </button>
          <button type="button" className="btn-secondary" onClick={() => start(false)} disabled={busy}>
            Nur lokal (ohne Cloud-KI)
          </button>
        </div>
        <p className="mt-3 text-xs text-ink-500">
          Ohne erreichbare KI erstellt ElektroCoach automatisch Lückentext- und Verständnisfragen aus
          deinen Aufzeichnungen. Diese sind als prüfbedürftig gekennzeichnet.
        </p>
      </Card>
    );
  }

  if (index >= queue.length) {
    const percent = stats.maxPoints > 0 ? (stats.points / stats.maxPoints) * 100 : 0;
    return (
      <Card>
        <SectionTitle title="Runde abgeschlossen" />
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-sm text-ink-500">Beantwortet</p>
            <p className="text-2xl font-bold text-ink-900">{stats.answered}</p>
          </div>
          <div>
            <p className="text-sm text-ink-500">Richtig</p>
            <p className="text-2xl font-bold text-emerald-700">{stats.correct}</p>
          </div>
          <div>
            <p className="text-sm text-ink-500">Punkte</p>
            <p className="text-2xl font-bold text-brand-700">
              {formatNumber(stats.points, 1)} / {formatNumber(stats.maxPoints, 1)}
            </p>
          </div>
        </div>
        <div className="mt-4">
          <ProgressBar value={percent} tone={percent >= 70 ? "success" : percent >= 50 ? "warning" : "danger"} />
        </div>
        <button
          type="button"
          className="btn-primary mt-5"
          onClick={() => {
            setQueue([]);
            setIndex(0);
          }}
        >
          Neue Runde
        </button>
      </Card>
    );
  }

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-ink-500">
          Aufgabe {index + 1} von {queue.length}
        </span>
        <div className="flex items-center gap-2">
          <span className="badge-neutral">{QTYPE_LABELS[current.qtype] ?? current.qtype}</span>
          <span className="badge-neutral">Schwierigkeit {current.difficulty}</span>
          {current.topic_name ? <span className="badge-brand">{current.topic_name}</span> : null}
          {current.needs_review ? <span className="badge-warning">ungeprüft</span> : null}
        </div>
      </div>

      <ProgressBar value={index} max={queue.length} tone="brand" />

      <p className="mt-5 whitespace-pre-wrap text-base font-medium leading-relaxed text-ink-900">
        {current.prompt}
      </p>

      <div className="mt-5">
        {current.qtype === "multiple_choice" && current.options.length > 0 ? (
          <div className="space-y-2">
            {current.options.map((option) => {
              const letter = option.split(":")[0]?.trim() ?? option;
              const isSelected = selected === letter || selected === option;
              const isCorrect = result && letter === result.reference_answer;
              return (
                <button
                  key={option}
                  type="button"
                  disabled={!!result}
                  onClick={() => setSelected(letter)}
                  className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors ${
                    isCorrect
                      ? "border-emerald-300 bg-emerald-50"
                      : isSelected
                        ? "border-brand-400 bg-brand-50"
                        : "border-ink-200 bg-white hover:bg-ink-50"
                  }`}
                >
                  <span className="font-semibold text-ink-500">{letter}</span>
                  <span className="text-ink-800">{option.replace(/^[A-Z]:\s*/, "")}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-lg bg-ink-100 p-0.5">
                <button
                  type="button"
                  onClick={() => setDrawMode(false)}
                  className={`rounded-md px-3 py-1 text-xs font-medium ${
                    !drawMode ? "bg-white text-brand-700 shadow-card" : "text-ink-600"
                  }`}
                >
                  Tippen
                </button>
                <button
                  type="button"
                  onClick={() => setDrawMode(true)}
                  disabled={!!result}
                  className={`rounded-md px-3 py-1 text-xs font-medium ${
                    drawMode ? "bg-white text-brand-700 shadow-card" : "text-ink-600"
                  }`}
                >
                  Mit Stift schreiben
                </button>
              </div>
              <span className="text-[11px] text-ink-400">
                Schreiben wird in Text umgewandelt und kann danach korrigiert werden.
              </span>
            </div>

            {drawMode && !result ? (
              <div className="space-y-3">
                <HandwritingCanvas onReady={(handle) => (canvasRef.current = handle)} />
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={transcribe}
                  disabled={handwritingBusy}
                >
                  {handwritingBusy ? "Wird erkannt …" : "Handschrift in Text umwandeln"}
                </button>
                {handwritingError && <Alert tone="warning">{handwritingError}</Alert>}
              </div>
            ) : (
              <textarea
                className="input min-h-[120px]"
                placeholder={
                  current.qtype === "calculation"
                    ? "Rechenweg und Ergebnis angeben, z. B. U = 6,9 V"
                    : "Antwort formulieren …"
                }
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                disabled={!!result}
              />
            )}
          </div>
        )}
      </div>

      {!result ? (
        <div className="mt-4 space-y-3">
          <AiChooser provider={provider} web={web} onProvider={setProvider} onWeb={setWeb} compact />
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={() => submit(true)} disabled={busy}>
              {busy ? "Wird bewertet …" : "Antwort prüfen"}
            </button>
            <button type="button" className="btn-secondary" onClick={() => submit(false)} disabled={busy}>
              Nur lokal bewerten
            </button>
            <button type="button" className="btn-ghost" onClick={next}>
              Überspringen
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          <Alert
            tone={result.correct ? "success" : result.partial ? "warning" : "danger"}
            title={
              result.correct
                ? "Richtig"
                : result.partial
                  ? `Teilweise richtig (${formatNumber(result.score, 1)} von ${formatNumber(result.max_points, 1)} Punkten)`
                  : `Noch nicht richtig (${formatNumber(result.score, 1)} von ${formatNumber(result.max_points, 1)} Punkten)`
            }
          >
            <p>{result.feedback}</p>
            {result.needs_review && (
              <p className="mt-1.5 text-xs">
                Diese Bewertung ist eine Orientierung ohne KI. Bei offenen Antworten bitte fachlich
                selbst prüfen.
              </p>
            )}
          </Alert>

          <div className="rounded-xl border border-ink-100 bg-ink-50 p-4">
            <p className="text-sm font-semibold text-ink-800">Musterlösung</p>
            <p className="mt-1 whitespace-pre-wrap text-sm text-ink-700">{result.reference_answer || "–"}</p>
            {result.solution_steps && (
              <>
                <p className="mt-3 text-sm font-semibold text-ink-800">Rechenweg</p>
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-3 font-mono text-xs text-ink-700">
                  {result.solution_steps}
                </pre>
              </>
            )}
          </div>

          {result.sources.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-semibold text-ink-800">Quellen aus deinen Unterlagen</p>
              <ul className="space-y-2">
                {result.sources.map((source) => (
                  <li key={source.id} className="rounded-lg border border-ink-100 p-3 text-sm">
                    <p className="text-xs text-ink-500">
                      Seite {source.page_number ?? "–"} · {source.filename}
                      {source.heading ? ` · ${source.heading}` : ""}
                    </p>
                    <p className="mt-1 text-ink-700">{source.excerpt}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className="btn-primary" onClick={next}>
              Nächste Aufgabe
            </button>
            <span className="text-xs text-ink-500">
              Nächste Wiederholung: {relativeDays(result.srs.due_at)}
            </span>
            {result.ai_used && <span className="badge-neutral">mit KI bewertet</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Themenkatalog
// ---------------------------------------------------------------------------
function TopicCatalogue({
  topics,
  loading,
  onMessage,
  onReload,
}: {
  topics: Topic[];
  loading: boolean;
  onMessage: (message: { tone: "success" | "danger" | "warning" | "info"; text: string } | null) => void;
  onReload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState<Array<{ id: string; name: string; chunks: number }> | null>(null);
  const [generateFor, setGenerateFor] = useState<Topic | null>(null);
  const [genCount, setGenCount] = useState(5);
  const [genType, setGenType] = useState("mixed");
  const [genDifficulty, setGenDifficulty] = useState(3);
  const [genAi, setGenAi] = useState(true);

  const analyze = async (useAi: boolean) => {
    setBusy(true);
    try {
      const report = await api.analyzeTopics(useAi);
      onMessage({
        tone: "success",
        text: `Themenanalyse fertig: ${report.assigned_chunks ?? 0} Abschnitte zugeordnet.`,
      });
      const missingData = await api.missingTopics();
      setMissing(missingData.items);
      onReload();
    } catch (error) {
      onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!generateFor) return;
    setBusy(true);
    try {
      const result = await api.generateQuestions({
        topic_id: generateFor.id,
        qtype: genType,
        count: genCount,
        difficulty: genDifficulty,
        use_ai: genAi,
      });
      onMessage({
        tone: "success",
        text: `${result.created} Aufgabe(n) zu „${generateFor.name}“ erstellt.${result.note ? ` ${result.note}` : ""}`,
      });
      setGenerateFor(null);
      onReload();
    } catch (error) {
      onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card>
        <SectionTitle
          title="Themenanalyse"
          subtitle="Ordnet importierte Abschnitte den Prüfungsthemen zu und findet Lücken."
          action={
            <div className="flex gap-2">
              <button type="button" className="btn-secondary btn-sm" onClick={() => analyze(false)} disabled={busy}>
                Lokal analysieren
              </button>
              <button type="button" className="btn-primary btn-sm" onClick={() => analyze(true)} disabled={busy}>
                {busy ? "Läuft …" : "Mit KI analysieren"}
              </button>
            </div>
          }
        />
        {missing && missing.length > 0 && (
          <Alert tone="warning" title="Unzureichend behandelte Themen">
            Für {missing.length} Themen liegt noch wenig Material vor. Diese Themen sind
            prüfungsrelevant und sollten ergänzt werden:{" "}
            {missing.slice(0, 8).map((item) => item.name).join(", ")}
            {missing.length > 8 ? " …" : ""}
          </Alert>
        )}
      </Card>

      {loading && <Spinner />}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {topics.map((topic) => (
          <Card key={topic.id}>
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-ink-900">{topic.name}</h3>
              <span
                className={`badge ${
                  topic.mastery.score >= 65
                    ? "badge-success"
                    : topic.mastery.score >= 40
                      ? "badge-brand"
                      : "badge-warning"
                }`}
              >
                {topic.mastery.level}
              </span>
            </div>
            {topic.description && <p className="mt-1 text-xs text-ink-500">{topic.description}</p>}
            <div className="mt-3">
              <ProgressBar value={topic.mastery.score} />
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
              <span>
                {topic.chunk_count} Abschnitte · {topic.question_count} Fragen
              </span>
              <button type="button" className="btn-ghost btn-sm" onClick={() => setGenerateFor(topic)}>
                Aufgaben
              </button>
            </div>
          </Card>
        ))}
      </div>

      <Modal
        open={!!generateFor}
        title={`Aufgaben zu „${generateFor?.name ?? ""}“`}
        onClose={() => setGenerateFor(null)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setGenerateFor(null)}>
              Abbrechen
            </button>
            <button type="button" className="btn-primary" onClick={generate} disabled={busy}>
              {busy ? "Wird erstellt …" : "Aufgaben erstellen"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="gen-type">
              Aufgabenart
            </label>
            <select
              id="gen-type"
              className="input"
              value={genType}
              onChange={(event) => setGenType(event.target.value)}
            >
              <option value="mixed">Gemischt</option>
              <option value="multiple_choice">Multiple-Choice</option>
              <option value="open">Offene Frage</option>
              <option value="calculation">Rechenaufgabe</option>
              <option value="practical">Praxisaufgabe</option>
              <option value="cloze">Lückentext</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="gen-count">
                Anzahl
              </label>
              <input
                id="gen-count"
                type="number"
                min={1}
                max={30}
                className="input"
                value={genCount}
                onChange={(event) => setGenCount(Number(event.target.value))}
              />
            </div>
            <div>
              <label className="label" htmlFor="gen-difficulty">
                Schwierigkeit
              </label>
              <input
                id="gen-difficulty"
                type="number"
                min={1}
                max={5}
                className="input"
                value={genDifficulty}
                onChange={(event) => setGenDifficulty(Number(event.target.value))}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={genAi}
              onChange={(event) => setGenAi(event.target.checked)}
              className="h-4 w-4 rounded border-ink-300"
            />
            KI verwenden, wenn erreichbar (sonst automatisch aus Aufzeichnungen)
          </label>
        </div>
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lernplan
// ---------------------------------------------------------------------------
function StudyPlanView({
  plan,
  loading,
  onReload,
}: {
  plan: import("../types").StudyPlan | null;
  loading: boolean;
  onReload: () => void;
}) {
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [goals, setGoals] = useState<import("../types").Goal[]>([]);
  const [newGoal, setNewGoal] = useState("");

  useAsync(() => api.goals().then((data) => {
    setGoals(data.items);
    return data;
  }), []);

  if (loading) return <Spinner />;
  if (!plan) return null;

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <SectionTitle
          title="Lernplan"
          subtitle="Verteilung auf Wiederholungen und neue Aufgaben nach Spaced Repetition."
          action={
            <div className="flex items-end gap-2">
              <div>
                <label className="label" htmlFor="plan-minutes">
                  Minuten
                </label>
                <input
                  id="plan-minutes"
                  type="number"
                  min={5}
                  max={240}
                  className="input w-24"
                  value={minutes}
                  onChange={(event) => setMinutes(Number(event.target.value))}
                />
              </div>
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.plan(minutes);
                    onReload();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Neu planen
              </button>
            </div>
          }
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl bg-brand-50 p-4">
            <p className="text-xs font-medium text-brand-700">Wiederholungen</p>
            <p className="mt-1 text-2xl font-bold text-brand-900">{plan.schedule.review_count}</p>
          </div>
          <div className="rounded-xl bg-emerald-50 p-4">
            <p className="text-xs font-medium text-emerald-700">Neue Aufgaben</p>
            <p className="mt-1 text-2xl font-bold text-emerald-900">{plan.schedule.new_count}</p>
          </div>
          <div className="rounded-xl bg-ink-100 p-4">
            <p className="text-xs font-medium text-ink-700">Geplante Zeit</p>
            <p className="mt-1 text-2xl font-bold text-ink-900">
              {formatNumber(plan.schedule.planned_minutes, 0)} min
            </p>
          </div>
        </div>
        <p className="mt-4 text-sm text-ink-600">
          Insgesamt {plan.due_total} fällige Aufgaben. Serie: {plan.streak} Tage, heute{" "}
          {formatNumber(plan.today_minutes, 0)} Minuten gelernt.
        </p>
      </Card>

      <Card>
        <SectionTitle title="Schwerpunkte" subtitle="Themen mit niedriger Trefferquote." />
        {plan.weak_topics.length === 0 ? (
          <p className="text-sm text-ink-500">Noch keine Auswertung möglich.</p>
        ) : (
          <ul className="space-y-2.5">
            {plan.weak_topics.map((topic) => (
              <li key={topic.id} className="flex items-center justify-between gap-3">
                <span className="truncate text-sm text-ink-700">{topic.name}</span>
                <span className={`badge ${topic.accuracy < 0.5 ? "badge-danger" : "badge-warning"}`}>
                  {formatNumber(topic.accuracy * 100, 0)} %
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="lg:col-span-3">
        <SectionTitle title="Lernziele" subtitle="Eigene Ziele setzen und Fortschritt verfolgen." />
        <div className="mb-4 flex flex-wrap gap-2">
          <input
            className="input min-w-[220px] flex-1"
            placeholder="Neues Lernziel, z. B. Leitungsberechnung sicher beherrschen"
            value={newGoal}
            onChange={(event) => setNewGoal(event.target.value)}
          />
          <button
            type="button"
            className="btn-primary"
            disabled={!newGoal.trim()}
            onClick={async () => {
              await api.createGoal({ title: newGoal.trim() });
              setNewGoal("");
              const data = await api.goals();
              setGoals(data.items);
            }}
          >
            Ziel hinzufügen
          </button>
        </div>
        {goals.length === 0 ? (
          <EmptyState title="Keine Lernziele" description="Setze Ziele, um deinen Fortschritt zu messen." />
        ) : (
          <ul className="space-y-3">
            {goals.map((goal) => (
              <li key={goal.id} className="rounded-xl border border-ink-100 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-ink-900">{goal.title}</p>
                    {goal.target && <p className="text-xs text-ink-500">{goal.target}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-ink-500">{formatDate(goal.due_date)}</span>
                    <button
                      type="button"
                      className="btn-ghost btn-sm text-red-600"
                      onClick={async () => {
                        await api.deleteGoal(goal.id);
                        const data = await api.goals();
                        setGoals(data.items);
                      }}
                    >
                      Löschen
                    </button>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={goal.progress}
                    className="flex-1 accent-brand-600"
                    onChange={(event) => {
                      const progress = Number(event.target.value);
                      setGoals((current) =>
                        current.map((item) => (item.id === goal.id ? { ...item, progress } : item)),
                      );
                    }}
                    onMouseUp={async (event) => {
                      await api.updateGoal(goal.id, { progress: Number((event.target as HTMLInputElement).value) });
                    }}
                    onTouchEnd={async (event) => {
                      await api.updateGoal(goal.id, { progress: Number((event.target as HTMLInputElement).value) });
                    }}
                  />
                  <span className="w-12 text-right text-sm font-semibold text-ink-800">
                    {formatNumber(goal.progress, 0)} %
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fragenkatalog
// ---------------------------------------------------------------------------
function QuestionCatalogue({
  onMessage,
}: {
  onMessage: (message: { tone: "success" | "danger" | "warning" | "info"; text: string } | null) => void;
}) {
  const [filters, setFilters] = useState<Record<string, unknown>>({ limit: 100 });
  const questions = useAsync(() => api.questions(filters), [JSON.stringify(filters)]);
  const [detail, setDetail] = useState<Question | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);

  useMemo(() => {
    api.topics().then((data) => setTopics(data.items)).catch(() => undefined);
  }, []);

  const remove = async (id: string) => {
    if (!window.confirm("Frage wirklich löschen?")) return;
    try {
      await api.deleteQuestion(id);
      questions.reload();
    } catch (error) {
      onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    }
  };

  return (
    <Card>
      <SectionTitle
        title="Fragenkatalog"
        subtitle={`${questions.data?.total ?? 0} Aufgaben in der Wissensbasis.`}
        action={
          <div className="flex flex-wrap gap-2">
            <select
              className="input w-auto"
              value={String(filters.qtype ?? "")}
              onChange={(event) =>
                setFilters((current) => ({ ...current, qtype: event.target.value || undefined }))
              }
            >
              <option value="">Alle Arten</option>
              {Object.entries(QTYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <select
              className="input w-auto"
              value={String(filters.topic_id ?? "")}
              onChange={(event) =>
                setFilters((current) => ({ ...current, topic_id: event.target.value || undefined }))
              }
            >
              <option value="">Alle Themen</option>
              {topics.map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.name}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-sm text-ink-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-ink-300"
                checked={!!filters.needs_review}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    needs_review: event.target.checked ? true : undefined,
                  }))
                }
              />
              nur ungeprüfte
            </label>
          </div>
        }
      />
      {questions.loading && <Spinner />}
      {questions.data && questions.data.items.length === 0 && (
        <EmptyState
          title="Noch keine Aufgaben"
          description="Erzeuge Aufgaben über den Themenkatalog oder starte eine Übungsrunde."
        />
      )}
      <div className="space-y-2">
        {questions.data?.items.map((question) => (
          <div
            key={question.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ink-100 px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-ink-800">{question.prompt}</p>
              <p className="mt-0.5 text-xs text-ink-500">
                {QTYPE_LABELS[question.qtype] ?? question.qtype} · Schwierigkeit {question.difficulty} ·{" "}
                {question.points} Punkte
                {question.topic_name ? ` · ${question.topic_name}` : ""}
                {question.ai_source === "ai" ? " · KI-erstellt" : ""}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {question.needs_review ? <span className="badge-warning">ungeprüft</span> : null}
              <button type="button" className="btn-ghost btn-sm" onClick={() => setDetail(question)}>
                Ansehen
              </button>
              <button type="button" className="btn-ghost btn-sm text-red-600" onClick={() => remove(question.id)}>
                Löschen
              </button>
            </div>
          </div>
        ))}
      </div>

      <Modal open={!!detail} title="Aufgabe" onClose={() => setDetail(null)}>
        {detail && (
          <div className="space-y-4 text-sm">
            <p className="whitespace-pre-wrap font-medium text-ink-900">{detail.prompt}</p>
            {detail.options.length > 0 && (
              <ul className="space-y-1">
                {detail.options.map((option) => (
                  <li key={option} className="rounded-lg bg-ink-50 px-3 py-2 text-ink-700">
                    {option}
                  </li>
                ))}
              </ul>
            )}
            <div>
              <p className="font-semibold text-ink-800">Musterlösung</p>
              <p className="mt-1 whitespace-pre-wrap text-ink-700">{detail.answer || "–"}</p>
            </div>
            {detail.solution_steps && (
              <div>
                <p className="font-semibold text-ink-800">Rechenweg</p>
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-ink-50 p-3 font-mono text-xs">
                  {detail.solution_steps}
                </pre>
              </div>
            )}
            {detail.explanation && (
              <div>
                <p className="font-semibold text-ink-800">Erklärung</p>
                <p className="mt-1 text-ink-700">{detail.explanation}</p>
              </div>
            )}
          </div>
        )}
      </Modal>
    </Card>
  );
}
