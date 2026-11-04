/**
 * Wiederverwendbare Oberflaechenbausteine.
 * Einheitliche Gestaltung fuer alle Seiten der Anwendung.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Karten und Abschnitte
// ---------------------------------------------------------------------------
export function Card({
  children,
  className = "",
  pad = true,
}: {
  children: React.ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return <div className={`card ${pad ? "card-pad" : ""} ${className}`}>{children}</div>;
}

export function SectionTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-ink-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-900 sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

// ---------------------------------------------------------------------------
// Statistik-Karten
// ---------------------------------------------------------------------------
export function StatCard({
  label,
  value,
  unit,
  hint,
  tone = "brand",
}: {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  tone?: "brand" | "success" | "warning" | "danger" | "neutral";
}) {
  const tones: Record<string, string> = {
    brand: "text-brand-700 bg-brand-50",
    success: "text-emerald-700 bg-emerald-50",
    warning: "text-amber-700 bg-amber-50",
    danger: "text-red-700 bg-red-50",
    neutral: "text-ink-700 bg-ink-100",
  };
  return (
    <div className="card card-pad">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink-500">{label}</p>
        {unit && <span className={`badge ${tones[tone]}`}>{unit}</span>}
      </div>
      <p className="mt-3 text-3xl font-bold tracking-tight text-ink-900">{value}</p>
      {hint && <p className="mt-1.5 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export function ProgressBar({
  value,
  max = 100,
  tone = "brand",
  label,
}: {
  value: number;
  max?: number;
  tone?: "brand" | "success" | "warning" | "danger";
  label?: string;
}) {
  const percent = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const tones: Record<string, string> = {
    brand: "bg-brand-600",
    success: "bg-emerald-600",
    warning: "bg-amber-500",
    danger: "bg-red-600",
  };
  return (
    <div>
      {label && (
        <div className="mb-1.5 flex justify-between text-xs text-ink-500">
          <span>{label}</span>
          <span>{percent.toFixed(0)} %</span>
        </div>
      )}
      <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
        <div
          className={`h-full rounded-full transition-all duration-500 ${tones[tone]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Statusanzeigen
// ---------------------------------------------------------------------------
export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; text: string }> = {
    ready: { cls: "badge-success", text: "Bereit" },
    needs_review: { cls: "badge-warning", text: "Zu prüfen" },
    processing: { cls: "badge-brand", text: "In Arbeit" },
    pending: { cls: "badge-neutral", text: "Wartend" },
    error: { cls: "badge-danger", text: "Fehler" },
    queued: { cls: "badge-neutral", text: "In Warteschlange" },
    running: { cls: "badge-brand", text: "Läuft" },
    done: { cls: "badge-success", text: "Fertig" },
    cancelled: { cls: "badge-neutral", text: "Abgebrochen" },
    created: { cls: "badge-neutral", text: "Erstellt" },
    finished: { cls: "badge-success", text: "Ausgewertet" },
    open: { cls: "badge-brand", text: "Offen" },
    closed: { cls: "badge-neutral", text: "Abgeschlossen" },
  };
  const entry = map[status] ?? { cls: "badge-neutral", text: status };
  return <span className={entry.cls}>{entry.text}</span>;
}

export function Alert({
  tone = "info",
  title,
  children,
  onClose,
}: {
  tone?: "info" | "success" | "warning" | "danger";
  title?: string;
  children?: React.ReactNode;
  onClose?: () => void;
}) {
  const tones: Record<string, string> = {
    info: "border-brand-200 bg-brand-50 text-brand-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    danger: "border-red-200 bg-red-50 text-red-900",
  };
  return (
    <div className={`rounded-xl border p-4 text-sm ${tones[tone]}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          {title && <p className="font-semibold">{title}</p>}
          {children && <div className={title ? "mt-1" : ""}>{children}</div>}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Meldung schließen"
            className="rounded p-1 text-current opacity-60 hover:opacity-100"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

export function Spinner({ label = "Lädt …" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-ink-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-300 border-t-brand-600" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-ink-200 bg-white px-6 py-12 text-center">
      <p className="text-base font-semibold text-ink-800">{title}</p>
      {description && <p className="mt-1.5 max-w-md text-sm text-ink-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink-900/40 p-0 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-lift sm:rounded-2xl ${
          wide ? "sm:max-w-4xl" : "sm:max-w-lg"
        }`}
      >
        <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
          <h3 className="text-base font-semibold text-ink-900">{title}</h3>
          <button type="button" onClick={onClose} className="btn-ghost btn-sm" aria-label="Schließen">
            ✕
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-ink-100 px-5 py-4">{footer}</div>
        )}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: Array<{ id: T; label: string; badge?: number }>;
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="mb-5 flex flex-wrap gap-1 rounded-xl bg-ink-100 p-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
            active === tab.id
              ? "bg-white text-brand-700 shadow-card"
              : "text-ink-600 hover:text-ink-900"
          }`}
        >
          {tab.label}
          {tab.badge !== undefined && tab.badge > 0 && (
            <span className="badge-neutral">{tab.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function ProgressRing({
  percent,
  label,
  size = 132,
}: {
  percent: number;
  label?: string;
  size?: number;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="9"
          className="text-white/25"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#ffffff"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 700ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-white">
        <span className="text-3xl font-bold tracking-tight">{clamped}</span>
        <span className="text-[11px] font-medium uppercase tracking-wide text-white/70">%</span>
        {label && <span className="mt-0.5 text-[10px] uppercase tracking-wide text-white/60">{label}</span>}
      </div>
    </div>
  );
}

export function BarChart({
  data,
  height = 140,
  valueKey = "minutes",
  labelKey = "day",
  formatValue,
}: {
  data: Array<Record<string, unknown>>;
  height?: number;
  valueKey?: string;
  labelKey?: string;
  formatValue?: (value: number) => string;
}) {
  const values = data.map((item) => Number(item[valueKey] ?? 0));
  const max = Math.max(1, ...values);
  return (
    <div className="flex items-end gap-1.5" style={{ height }}>
      {data.map((item, index) => {
        const value = values[index];
        const percent = (value / max) * 100;
        const label = String(item[labelKey] ?? "");
        return (
          <div key={label + index} className="group flex flex-1 flex-col items-center justify-end">
            <div className="relative flex w-full flex-1 items-end">
              <div
                className="w-full rounded-t bg-brand-500 transition-all group-hover:bg-brand-600"
                style={{ height: `${Math.max(percent, value > 0 ? 4 : 1.5)}%` }}
                title={`${label}: ${formatValue ? formatValue(value) : value}`}
              />
            </div>
            <span className="mt-1.5 hidden text-[10px] text-ink-400 sm:block">
              {label.slice(5)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Datenladen
// ---------------------------------------------------------------------------
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((result) => {
        if (mounted.current) setData(result);
      })
      .catch((err: unknown) => {
        if (mounted.current) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, loading, error, reload };
}

export function formatNumber(value: number, digits = 1): string {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${formatNumber(bytes / 1024 ** index, index > 1 ? 1 : 0)} ${units[index]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeDays(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  const days = Math.round((date.getTime() - Date.now()) / 86400000);
  if (days === 0) return "heute";
  if (days === 1) return "morgen";
  if (days === -1) return "gestern";
  if (days > 1) return `in ${days} Tagen`;
  return `vor ${Math.abs(days)} Tagen`;
}
