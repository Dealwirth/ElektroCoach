/** Prüfungen: Simulation mit Zeitlimit, Auswertung und Vergleich. */

import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { AnswerField } from "../components/AnswerField";
import {
  Alert,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  ProgressBar,
  SectionTitle,
  Spinner,
  StatusBadge,
  Tabs,
  formatDate,
  formatNumber,
  useAsync,
} from "../components/ui";
import type { Exam, ExamResult } from "../types";

type TabId = "liste" | "neu" | "vergleich";

export default function ExamsPage() {
  const { examId } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabId>("liste");
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);

  if (examId) {
    return (
      <ExamRunner
        examId={examId}
        onExit={() => navigate("/pruefungen")}
        onMessage={setMessage}
        message={message}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Prüfungssimulation"
        subtitle="Realistische Prüfungen mit Zeitlimit, gemischten Aufgaben und Auswertung."
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
          { id: "liste", label: "Meine Prüfungen" },
          { id: "neu", label: "Neue Prüfung" },
          { id: "vergleich", label: "Vergleich" },
        ]}
      />

      {tab === "liste" && <ExamList onOpen={(id) => navigate(`/pruefungen/${id}`)} onMessage={setMessage} />}
      {tab === "neu" && <NewExam onCreated={(id) => navigate(`/pruefungen/${id}`)} onMessage={setMessage} />}
      {tab === "vergleich" && <ExamComparison />}
    </div>
  );
}

function ExamList({
  onOpen,
  onMessage,
}: {
  onOpen: (id: string) => void;
  onMessage: (message: { tone: "success" | "danger" | "warning"; text: string } | null) => void;
}) {
  const exams = useAsync(() => api.exams(50), []);

  if (exams.loading) return <Spinner />;
  if (exams.error) return <Alert tone="danger">{exams.error}</Alert>;

  if (!exams.data || exams.data.items.length === 0) {
    return <EmptyState title="Noch keine Prüfungen" description="Erstelle im Reiter „Neue Prüfung“ eine Simulation." />;
  }

  return (
    <Card>
      <SectionTitle title="Prüfungsverlauf" />
      <div className="overflow-x-auto">
        <table className="table-base min-w-[720px]">
          <thead>
            <tr>
              <th>Name</th>
              <th>Dauer</th>
              <th>Status</th>
              <th>Ergebnis</th>
              <th>Bestanden</th>
              <th>Erstellt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {exams.data.items.map((exam) => (
              <tr key={exam.id}>
                <td className="font-medium text-ink-800">{exam.name}</td>
                <td className="text-ink-600">{exam.duration_minutes} min</td>
                <td>
                  <StatusBadge status={exam.status} />
                </td>
                <td className="text-ink-600">
                  {exam.score !== null ? `${formatNumber(exam.score, 1)} %` : "–"}
                </td>
                <td>
                  {exam.passed === null ? (
                    <span className="text-ink-400">–</span>
                  ) : exam.passed ? (
                    <span className="badge-success">ja</span>
                  ) : (
                    <span className="badge-danger">nein</span>
                  )}
                </td>
                <td className="whitespace-nowrap text-ink-500">{formatDate(exam.created_at)}</td>
                <td className="text-right">
                  <button type="button" className="btn-ghost btn-sm" onClick={() => onOpen(exam.id)}>
                    {exam.status === "finished" ? "Ergebnis" : "Fortsetzen"}
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-sm text-red-600"
                    onClick={async () => {
                      if (!window.confirm("Prüfung löschen?")) return;
                      try {
                        await api.deleteExam(exam.id);
                        exams.reload();
                      } catch (error) {
                        onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
                      }
                    }}
                  >
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function NewExam({
  onCreated,
  onMessage,
}: {
  onCreated: (id: string) => void;
  onMessage: (message: { tone: "success" | "danger" | "warning"; text: string } | null) => void;
}) {
  const presets = useAsync(() => api.examPresets(), []);
  const [name, setName] = useState("Abschlussprüfung Simulation");
  const [minutes, setMinutes] = useState(90);
  const [questions, setQuestions] = useState(20);
  const [points, setPoints] = useState(100);
  const [difficulty, setDifficulty] = useState<"ausgewogen" | "leicht" | "schwer">("ausgewogen");
  const [busy, setBusy] = useState(false);

  const applyPreset = (key: string) => {
    const preset = presets.data?.presets?.[key];
    if (!preset) return;
    setName(preset.name);
    setMinutes(preset.minutes);
    setQuestions(preset.questions);
    setPoints(preset.points);
  };

  return (
    <Card>
      <SectionTitle title="Neue Prüfung erstellen" subtitle="Zeitlimit, Aufgabenanzahl und Punkte festlegen." />
      {presets.data?.presets && (
        <div className="mb-5 flex flex-wrap gap-2">
          {Object.entries(presets.data.presets).map(([key, preset]) => (
            <button key={key} type="button" className="btn-secondary btn-sm" onClick={() => applyPreset(key)}>
              {preset.name} ({preset.minutes} min)
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label" htmlFor="exam-name">
            Bezeichnung
          </label>
          <input id="exam-name" className="input" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="exam-minutes">
            Dauer (Minuten)
          </label>
          <input
            id="exam-minutes"
            type="number"
            min={5}
            max={300}
            className="input"
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
        </div>
        <div>
          <label className="label" htmlFor="exam-questions">
            Anzahl Aufgaben
          </label>
          <input
            id="exam-questions"
            type="number"
            min={1}
            max={60}
            className="input"
            value={questions}
            onChange={(event) => setQuestions(Number(event.target.value))}
          />
        </div>
        <div>
          <label className="label" htmlFor="exam-points">
            Gesamtpunkte
          </label>
          <input
            id="exam-points"
            type="number"
            min={10}
            max={200}
            className="input"
            value={points}
            onChange={(event) => setPoints(Number(event.target.value))}
          />
        </div>
        <div>
          <label className="label" htmlFor="exam-difficulty">
            Schwierigkeit
          </label>
          <select
            id="exam-difficulty"
            className="input"
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value as typeof difficulty)}
          >
            <option value="leicht">Einstieg</option>
            <option value="ausgewogen">Ausgewogen</option>
            <option value="schwer">Prüfungsniveau</option>
          </select>
        </div>
      </div>
      <button
        type="button"
        className="btn-primary mt-5"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const result = await api.createExam({
              name,
              minutes,
              question_count: questions,
              total_points: points,
              difficulty,
            });
            if (!result.ok) {
              onMessage({ tone: "warning", text: "Es sind noch keine Aufgaben vorhanden." });
              return;
            }
            onCreated(result.exam.id);
          } catch (error) {
            onMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Wird erstellt …" : "Prüfung erstellen"}
      </button>
    </Card>
  );
}

function ExamComparison() {
  const comparison = useAsync(() => api.compareExams(), []);

  if (comparison.loading) return <Spinner />;
  if (comparison.error) return <Alert tone="danger">{comparison.error}</Alert>;
  if (!comparison.data) return null;

  const items = (comparison.data.items ?? []) as Array<{
    name: string;
    percentage: number;
    passed: boolean;
    created_at: string;
  }>;

  if (items.length === 0) {
    return <EmptyState title="Noch keine Auswertung" description="Schließe mindestens eine Prüfung ab." />;
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <p className="text-sm text-ink-500">Durchschnitt</p>
          <p className="mt-1 text-3xl font-bold text-ink-900">
            {formatNumber(Number(comparison.data.average ?? 0), 1)} %
          </p>
        </Card>
        <Card>
          <p className="text-sm text-ink-500">Beste Prüfung</p>
          <p className="mt-1 text-3xl font-bold text-emerald-700">
            {formatNumber(Number(comparison.data.best ?? 0), 1)} %
          </p>
        </Card>
        <Card>
          <p className="text-sm text-ink-500">Bestehensquote</p>
          <p className="mt-1 text-3xl font-bold text-brand-700">
            {formatNumber(Number(comparison.data.pass_rate ?? 0) * 100, 0)} %
          </p>
        </Card>
      </div>
      <Card>
        <SectionTitle title="Entwicklung" subtitle="Ergebnisse aller abgeschlossenen Prüfungen." />
        <ul className="space-y-3">
          {items.map((item, index) => (
            <li key={index}>
              <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
                <span className="truncate text-ink-800">{item.name}</span>
                <span className="text-ink-500">
                  {formatNumber(item.percentage, 1)} % · {formatDate(item.created_at)}
                </span>
              </div>
              <ProgressBar
                value={item.percentage}
                tone={item.passed ? "success" : item.percentage >= 50 ? "warning" : "danger"}
              />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Prüfungsdurchführung
// ---------------------------------------------------------------------------
function ExamRunner({
  examId,
  onExit,
  onMessage,
  message,
}: {
  examId: string;
  onExit: () => void;
  onMessage: (message: { tone: "success" | "danger" | "warning"; text: string } | null) => void;
  message: { tone: "success" | "danger" | "warning"; text: string } | null;
}) {
  const [exam, setExam] = useState<Exam | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [remaining, setRemaining] = useState<number | null>(null);
  const [result, setResult] = useState<ExamResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showFinish, setShowFinish] = useState(false);
  const [handwritingAvailable, setHandwritingAvailable] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .handwritingStatus()
      .then((status) => active && setHandwritingAvailable(status.available))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .exam(examId)
      .then(async (data) => {
        if (!active) return;
        if (data.status === "created") {
          const started = await api.startExam(examId);
          if (active) setExam(started);
        } else {
          setExam(data);
        }
        const initial: Record<string, string> = {};
        data.questions.forEach((question) => {
          if (question.answer) initial[question.question_id] = question.answer;
        });
        setAnswers(initial);
      })
      .catch((err: unknown) => active && setError(err instanceof Error ? err.message : String(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [examId]);

  const elapsed = exam?.elapsed_seconds ?? 0;
  const totalSeconds = (exam?.duration_minutes ?? 0) * 60;
  const left = remaining ?? Math.max(0, totalSeconds - elapsed);

  useEffect(() => {
    if (!exam || exam.status === "finished" || result) return;
    if (totalSeconds <= 0) return;
    setRemaining(Math.max(0, totalSeconds - elapsed));
    const timer = window.setInterval(() => {
      setRemaining((value) => {
        if (value === null) return value;
        if (value <= 1) {
          window.clearInterval(timer);
          return 0;
        }
        return value - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [exam, elapsed, totalSeconds, result]);

  const answeredCount = useMemo(
    () => Object.values(answers).filter((value) => value.trim().length > 0).length,
    [answers],
  );

  const finish = async () => {
    if (!exam) return;
    setBusy(true);
    onMessage(null);
    try {
      const data = await api.finishExam(exam.id, exam.session_id, true);
      setResult(data);
      setShowFinish(false);
    } catch (err) {
      onMessage({ tone: "danger", text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (remaining === 0 && exam && !result && !busy) {
      void finish();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining]);

  if (loading) return <Spinner label="Prüfung wird vorbereitet …" />;
  if (error) return <Alert tone="danger" title="Prüfung konnte nicht geladen werden">{error}</Alert>;
  if (!exam) return null;

  if (result) {
    return (
      <div className="space-y-5">
        <PageHeader title="Prüfungsergebnis" subtitle={result.name} actions={<button type="button" className="btn-secondary" onClick={onExit}>Zur Übersicht</button>} />
        <div className="grid gap-4 sm:grid-cols-4">
          <Card>
            <p className="text-sm text-ink-500">Erreichte Punkte</p>
            <p className="mt-1 text-3xl font-bold text-ink-900">
              {formatNumber(result.achieved, 1)}
            </p>
            <p className="text-xs text-ink-500">von {formatNumber(result.total, 1)}</p>
          </Card>
          <Card>
            <p className="text-sm text-ink-500">Ergebnis</p>
            <p className="mt-1 text-3xl font-bold text-ink-900">{formatNumber(result.percentage, 1)} %</p>
          </Card>
          <Card>
            <p className="text-sm text-ink-500">Bestanden</p>
            <p className={`mt-1 text-3xl font-bold ${result.passed ? "text-emerald-700" : "text-red-700"}`}>
              {result.passed ? "ja" : "nein"}
            </p>
            <p className="text-xs text-ink-500">Grenze 50 %</p>
          </Card>
          <Card>
            <p className="text-sm text-ink-500">Bestehenswahrscheinlichkeit</p>
            <p className="mt-1 text-3xl font-bold text-brand-700">
              {formatNumber(result.pass_probability, 0)} %
            </p>
            <p className="text-xs text-ink-500">unverbindliche Orientierung</p>
          </Card>
        </div>

        {result.weak_topics.length > 0 && (
          <Card>
            <SectionTitle title="Wissenslücken" subtitle="Themen mit Verbesserungsbedarf." />
            <ul className="space-y-2">
              {result.weak_topics.map((topic) => (
                <li key={topic.topic} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-ink-700">{topic.topic}</span>
                  <span className={`badge ${topic.accuracy < 0.5 ? "badge-danger" : "badge-warning"}`}>
                    {formatNumber(topic.accuracy * 100, 0)} %
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <Card>
          <SectionTitle title="Auswertung je Aufgabe" />
          <div className="space-y-3">
            {result.results.map((item, index) => (
              <div key={item.question_id} className="rounded-xl border border-ink-100 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-ink-500">
                    Aufgabe {index + 1} · {item.topic ?? "ohne Thema"}
                  </span>
                  <span
                    className={`badge ${
                      item.achieved >= item.points ? "badge-success" : item.achieved > 0 ? "badge-warning" : "badge-danger"
                    }`}
                  >
                    {formatNumber(item.achieved, 1)} / {formatNumber(item.points, 1)} Punkte
                  </span>
                </div>
                <p className="mt-2 text-sm text-ink-700">{item.feedback}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    );
  }

  const minutes = Math.floor(left / 60);
  const seconds = left % 60;

  return (
    <div className="space-y-5">
      <PageHeader
        title={exam.name}
        subtitle={`${exam.questions.length} Aufgaben · ${formatNumber(exam.total_points, 0)} Punkte`}
        actions={
          <>
            <span
              className={`badge ${left < 300 ? "badge-danger" : "badge-brand"} px-3 py-2 text-sm`}
              aria-live="polite"
            >
              {String(minutes).padStart(2, "0")}:{String(seconds).padStart(2, "0")}
            </span>
            <button type="button" className="btn-primary" onClick={() => setShowFinish(true)}>
              Prüfung abgeben
            </button>
            <button type="button" className="btn-ghost" onClick={onExit}>
              Später
            </button>
          </>
        }
      />

      {message && <Alert tone={message.tone}>{message.text}</Alert>}

      <Card>
        <div className="flex items-center justify-between text-sm text-ink-600">
          <span>
            Beantwortet: {answeredCount} von {exam.questions.length}
          </span>
          <span>Fortschritt</span>
        </div>
        <div className="mt-2">
          <ProgressBar value={answeredCount} max={exam.questions.length} tone="brand" />
        </div>
      </Card>

      <div className="space-y-4">
        {exam.questions.map((question, index) => (
          <Card key={question.exam_question_id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-ink-900">Aufgabe {index + 1}</span>
              <div className="flex items-center gap-2">
                <span className="badge-neutral">{formatNumber(question.points, 1)} Punkte</span>
                {question.topic_name ? <span className="badge-brand">{question.topic_name}</span> : null}
              </div>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-800">{question.prompt}</p>
            <div className="mt-4">
              {question.qtype === "multiple_choice" && question.options.length > 0 ? (
                <div className="space-y-2">
                  {question.options.map((option) => {
                    const letter = option.split(":")[0]?.trim() ?? option;
                    const isSelected = answers[question.question_id] === letter;
                    return (
                      <label
                        key={option}
                        className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-sm ${
                          isSelected ? "border-brand-400 bg-brand-50" : "border-ink-200 hover:bg-ink-50"
                        }`}
                      >
                        <input
                          type="radio"
                          name={question.question_id}
                          className="mt-0.5 h-4 w-4 accent-brand-600"
                          checked={isSelected}
                          onChange={() =>
                            setAnswers((current) => ({ ...current, [question.question_id]: letter }))
                          }
                        />
                        <span className="text-ink-800">{option.replace(/^[A-Z]:\s*/, "")}</span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <AnswerField
                  value={answers[question.question_id] ?? ""}
                  onChange={(next) =>
                    setAnswers((current) => ({ ...current, [question.question_id]: next }))
                  }
                  examId={exam.id}
                  questionId={question.question_id}
                  handwritingAvailable={handwritingAvailable}
                />
              )}
            </div>
          </Card>
        ))}
      </div>

      <div className="sticky bottom-20 z-30 flex justify-end md:bottom-4">
        <button type="button" className="btn-primary shadow-lift" onClick={() => setShowFinish(true)}>
          Prüfung abgeben
        </button>
      </div>

      <Modal
        open={showFinish}
        title="Prüfung abgeben?"
        onClose={() => setShowFinish(false)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowFinish(false)}>
              Weiter bearbeiten
            </button>
            <button type="button" className="btn-primary" onClick={finish} disabled={busy}>
              {busy ? "Wird ausgewertet …" : "Jetzt abgeben"}
            </button>
          </>
        }
      >
        <p className="text-sm text-ink-700">
          {answeredCount} von {exam.questions.length} Aufgaben beantwortet. Nicht beantwortete Aufgaben
          erhalten 0 Punkte. Die Auswertung erfolgt anschließend.
        </p>
      </Modal>
    </div>
  );
}
