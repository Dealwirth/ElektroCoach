/** Dashboard: Kennzahlen, Lernplan, Fortschritt und Schwachstellen. */

import { Link } from "react-router-dom";
import { api } from "../api";
import {
  Alert,
  BarChart,
  Card,
  EmptyState,
  PageHeader,
  ProgressBar,
  SectionTitle,
  Spinner,
  StatCard,
  formatNumber,
  relativeDays,
  useAsync,
} from "../components/ui";

export default function DashboardPage() {
  const { data, loading, error, reload } = useAsync(() => api.dashboard(), []);

  if (loading) return <Spinner label="Übersicht wird geladen …" />;
  if (error) {
    return (
      <Alert tone="danger" title="Übersicht konnte nicht geladen werden">
        {error}
        <button type="button" className="btn-secondary btn-sm mt-3" onClick={reload}>
          Erneut versuchen
        </button>
      </Alert>
    );
  }
  if (!data) return null;

  const { stats, series, weak_areas: weakAreas, plan, ai, activity } = data;
  const progressPercent = stats.topics
    ? Math.min(100, (stats.topics > 0 ? stats.attempts / (stats.topics * 20) : 0) * 100)
    : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Übersicht"
        subtitle="Lernstand, Tagesplan und offene Punkte auf einen Blick."
        actions={
          <Link to="/lernen" className="btn-primary">
            Lernrunde starten
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Fällige Wiederholungen"
          value={stats.due_reviews}
          unit="Aufgaben"
          tone={stats.due_reviews > 0 ? "warning" : "success"}
          hint={stats.due_reviews > 0 ? "Heute einplanen" : "Alles wiederholt"}
        />
        <StatCard
          label="Lernzeit heute"
          value={formatNumber(stats.today_minutes, 0)}
          unit="min"
          hint={`Tagesziel ${stats.daily_goal_minutes} min`}
          tone="brand"
        />
        <StatCard
          label="Trefferquote"
          value={`${formatNumber(stats.accuracy * 100, 0)} %`}
          unit="gesamt"
          hint={`${stats.attempts} beantwortete Aufgaben`}
          tone={stats.accuracy >= 0.7 ? "success" : stats.accuracy >= 0.5 ? "warning" : "danger"}
        />
        <StatCard
          label="Lernserie"
          value={stats.streak_days}
          unit="Tage"
          hint={stats.streak_days > 0 ? "Weiter so" : "Heute starten"}
          tone={stats.streak_days > 2 ? "success" : "neutral"}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle
            title="Lernaktivität der letzten 14 Tage"
            subtitle="Lernzeit in Minuten pro Tag, geschätzt aus beantworteten Aufgaben."
          />
          {series.some((point) => point.minutes > 0) ? (
            <BarChart
              data={series as unknown as Array<Record<string, unknown>>}
              valueKey="minutes"
              labelKey="day"
              formatValue={(value) => `${formatNumber(value, 0)} min`}
            />
          ) : (
            <EmptyState
              title="Noch keine Aktivität"
              description="Sobald du Aufgaben beantwortest, erscheint hier dein Verlauf."
              action={
                <Link to="/lernen" className="btn-primary">
                  Erste Aufgabe beantworten
                </Link>
              }
            />
          )}
        </Card>

        <Card>
          <SectionTitle title="Tagesplan" subtitle={`${plan.minutes_available} Minuten verfügbar`} />
          <div className="space-y-4">
            <div>
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-ink-600">Wiederholungen</span>
                <span className="text-lg font-semibold text-ink-900">
                  {plan.schedule.review_count}
                </span>
              </div>
              <ProgressBar
                value={plan.schedule.review_count}
                max={Math.max(plan.schedule.review_count, plan.due_total, 1)}
                tone="brand"
              />
            </div>
            <div>
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-ink-600">Neue Aufgaben</span>
                <span className="text-lg font-semibold text-ink-900">
                  {plan.schedule.new_count}
                </span>
              </div>
              <ProgressBar value={plan.schedule.planned_minutes} max={plan.minutes_available} tone="success" />
            </div>
            <p className="text-xs text-ink-500">
              Geplant: {formatNumber(plan.schedule.planned_minutes, 0)} von {plan.minutes_available} Minuten.
            </p>
            {plan.due_total > plan.schedule.review_count && (
              <p className="text-xs text-amber-700">
                {plan.due_total - plan.schedule.review_count} weitere Wiederholungen warten auf die nächsten Tage.
              </p>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle
            title="Themenfortschritt"
            subtitle="Abdeckung durch eigene Aufzeichnungen und Trefferquote."
            action={
              <Link to="/lernen" className="btn-secondary btn-sm">
                Alle Themen
              </Link>
            }
          />
          {data.topics.length === 0 ? (
            <EmptyState
              title="Noch keine Themen erkannt"
              description="Importiere Aufzeichnungen und starte die Themenanalyse."
            />
          ) : (
            <ul className="space-y-3">
              {data.topics.slice(0, 8).map((topic) => (
                <li key={topic.id}>
                  <div className="mb-1 flex items-baseline justify-between gap-3">
                    <span className="truncate text-sm font-medium text-ink-800">{topic.name}</span>
                    <span className="shrink-0 text-xs text-ink-500">
                      {topic.mastery.level} · {topic.chunk_count} Abschnitte · {topic.question_count} Fragen
                    </span>
                  </div>
                  <ProgressBar
                    value={topic.mastery.score}
                    tone={topic.mastery.score >= 65 ? "success" : topic.mastery.score >= 40 ? "brand" : "warning"}
                  />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionTitle title="Schwachstellen" subtitle="Themen mit niedriger Trefferquote." />
            {weakAreas.length === 0 ? (
              <p className="text-sm text-ink-500">
                Noch keine Auswertung möglich. Beantworte mehr Aufgaben.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {weakAreas.map((area) => (
                  <li key={area.id} className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm text-ink-700">{area.name}</span>
                    <span
                      className={`badge ${
                        area.accuracy < 0.5 ? "badge-danger" : "badge-warning"
                      }`}
                    >
                      {formatNumber(area.accuracy * 100, 0)} %
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <SectionTitle title="KI-Status" />
            <ul className="space-y-2 text-sm">
              <li className="flex items-center justify-between">
                <span className="text-ink-600">Lokales Modell (Ollama)</span>
                <span className={ai.ollama.available ? "badge-success" : "badge-neutral"}>
                  {ai.ollama.available ? "bereit" : "inaktiv"}
                </span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-ink-600">Cloud (Gemini)</span>
                <span className={ai.gemini.available ? "badge-success" : "badge-neutral"}>
                  {ai.gemini.available ? "bereit" : "inaktiv"}
                </span>
              </li>
              {ai.gemini.quota && (
                <li>
                  <div className="mb-1 flex justify-between text-xs text-ink-500">
                    <span>Tageskontingent Gemini</span>
                    <span>
                      {ai.gemini.quota.used} / {ai.gemini.quota.limit}
                    </span>
                  </div>
                  <ProgressBar
                    value={ai.gemini.quota.used}
                    max={ai.gemini.quota.limit || 1}
                    tone={ai.gemini.quota.exhausted ? "danger" : "brand"}
                  />
                </li>
              )}
            </ul>
            <p className="mt-3 text-xs text-ink-500">Modus: {ai.mode}</p>
          </Card>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle title="Letzte Aktivitäten" />
          {activity.length === 0 ? (
            <p className="text-sm text-ink-500">Noch keine Aktivitäten erfasst.</p>
          ) : (
            <ul className="divide-y divide-ink-100">
              {activity.map((item, index) => (
                <li key={index} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="truncate text-sm text-ink-700">{item.detail || item.kind}</span>
                  <span className="shrink-0 text-xs text-ink-400">{relativeDays(item.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionTitle title="Wissensbasis" />
          <dl className="space-y-2.5 text-sm">
            {[
              ["Dokumente", stats.documents],
              ["Seiten", stats.pages],
              ["Abschnitte", stats.chunks],
              ["Fragen", stats.questions],
              ["Themen", stats.topics],
              ["Prüfungen", stats.exams_finished],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex items-center justify-between">
                <dt className="text-ink-600">{label}</dt>
                <dd className="font-semibold text-ink-900">{value}</dd>
              </div>
            ))}
          </dl>
          {(stats.needs_review_pages > 0 || stats.needs_review_questions > 0) && (
            <div className="mt-4">
              <Alert tone="warning" title="Prüfbedürftige Inhalte">
                {stats.needs_review_pages} Seiten und {stats.needs_review_questions} Fragen sind
                unsicher erkannt und sollten kontrolliert werden.
                <Link to="/bibliothek" className="btn-secondary btn-sm mt-3">
                  Jetzt prüfen
                </Link>
              </Alert>
            </div>
          )}
          <div className="mt-4">
            <ProgressBar
              value={progressPercent}
              label="Gesamtfortschritt (Orientierung)"
              tone="brand"
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
