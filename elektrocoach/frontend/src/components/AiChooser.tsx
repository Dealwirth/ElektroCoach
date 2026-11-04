/**
 * Auswahl der KI fuer eine einzelne Anfrage.
 *
 * Der Lernende entscheidet selbst, welcher Dienst antwortet:
 *   Auto   – die App waehlt (lokal bevorzugt, Cloud nur bei Bedarf)
 *   Ollama – lokal, kostenlos, offline
 *   Gemini – Cloud, kostenlos im Kontingent
 *
 * Zusaetzlich gibt es den Schalter fuer den Webzugriff des lokalen Modells.
 * Die Wahl gilt nur fuer diese Anfrage und wird im Browser gemerkt.
 */

import { useEffect, useState } from "react";

export type AiProvider = "auto" | "ollama" | "gemini";
export type WebMode = "auto" | "on" | "off";

const STORAGE_KEY = "elektrocoach.aiChoice";

interface StoredChoice {
  provider: AiProvider;
  web: WebMode;
}

function load(): StoredChoice {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { provider: "auto", web: "auto" };
    const parsed = JSON.parse(raw) as Partial<StoredChoice>;
    const provider = (["auto", "ollama", "gemini"] as string[]).includes(parsed.provider ?? "")
      ? (parsed.provider as AiProvider)
      : "auto";
    const web = (["auto", "on", "off"] as string[]).includes(parsed.web ?? "")
      ? (parsed.web as WebMode)
      : "auto";
    return { provider, web };
  } catch {
    return { provider: "auto", web: "auto" };
  }
}

export function useAiChoice() {
  const [choice, setChoice] = useState<StoredChoice>(load);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(choice));
    } catch {
      /* Speichern ist nicht kritisch. */
    }
  }, [choice]);

  return {
    provider: choice.provider,
    web: choice.web,
    setProvider: (provider: AiProvider) => setChoice((c) => ({ ...c, provider })),
    setWeb: (web: WebMode) => setChoice((c) => ({ ...c, web })),
  };
}

const PROVIDERS: Array<{ id: AiProvider; label: string; hint: string; icon: string }> = [
  {
    id: "auto",
    label: "Auto",
    hint: "Die App wählt: lokal zuerst, Cloud nur bei Bedarf.",
    icon: "M12 3v3m0 12v3M3 12h3m12 0h3M6.3 6.3l2.1 2.1m7.2 7.2l2.1 2.1m0-11.4l-2.1 2.1m-7.2 7.2l-2.1 2.1",
  },
  {
    id: "ollama",
    label: "Ollama",
    hint: "Lokales Modell. Kostenlos, offline, keine Daten verlassen das Haus.",
    icon: "M4 6h16v10H4zM8 20h8M12 16v4",
  },
  {
    id: "gemini",
    label: "Gemini",
    hint: "Cloud (kostenloses Kontingent). Stärker bei Bildern und schweren Aufgaben.",
    icon: "M6 18a4 4 0 010-8 5 5 0 019.6-1.6A4 4 0 0118 18z",
  },
];

const WEB_MODES: Array<{ id: WebMode; label: string; hint: string }> = [
  { id: "auto", label: "Web automatisch", hint: "Nur bei Fragen nach aktuellen Angaben (Normen, Förderung, Preise)." },
  { id: "on", label: "Web immer", hint: "Immer im Internet nachsehen. Immer mit Quellenangabe." },
  { id: "off", label: "Web aus", hint: "Kein Internet. Nur eigenes Wissen und deine Aufzeichnungen." },
];

function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4 shrink-0"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

export function AiChooser({
  provider,
  web,
  onProvider,
  onWeb,
  compact = false,
}: {
  provider: AiProvider;
  web: WebMode;
  onProvider: (value: AiProvider) => void;
  onWeb: (value: WebMode) => void;
  compact?: boolean;
}) {
  const [showWeb, setShowWeb] = useState(false);
  const activeProvider = PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0];
  const activeWeb = WEB_MODES.find((w) => w.id === web) ?? WEB_MODES[0];

  return (
    <div className="space-y-2">
      <div
        className="flex flex-wrap items-center gap-1 rounded-xl bg-ink-100 p-1"
        role="radiogroup"
        aria-label="KI auswählen"
      >
        {PROVIDERS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={provider === item.id}
            title={item.hint}
            onClick={() => onProvider(item.id)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors sm:text-sm ${
              provider === item.id
                ? "bg-white text-brand-700 shadow-card"
                : "text-ink-600 hover:text-ink-900"
            }`}
          >
            <Icon path={item.icon} />
            {item.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setShowWeb((value) => !value)}
          aria-expanded={showWeb}
          title="Internet für das lokale Modell"
          className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors sm:text-sm ${
            web === "off" ? "text-ink-500" : "text-emerald-700"
          } ${showWeb ? "bg-white shadow-card" : "hover:bg-white/60"}`}
        >
          <Icon path="M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18" />
          {web === "off" ? "Web aus" : "Web"}
        </button>
      </div>

      {!compact && (
        <p className="px-1 text-[11px] leading-relaxed text-ink-500">
          {activeProvider.hint}
          {web !== "off" && ` ${activeWeb.hint}`}
        </p>
      )}

      {showWeb && (
        <div className="rounded-xl border border-ink-200 bg-white p-2">
          <p className="px-1 pb-1.5 text-[11px] font-medium text-ink-600">Internet für Ollama</p>
          <div className="flex flex-wrap gap-1">
            {WEB_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => onWeb(mode.id)}
                title={mode.hint}
                className={`rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
                  web === mode.id
                    ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200"
                    : "bg-ink-50 text-ink-600 hover:bg-ink-100"
                }`}
              >
                {mode.label}
              </button>
            ))}
          </div>
          <p className="px-1 pt-1.5 text-[10px] leading-relaxed text-ink-400">{activeWeb.hint}</p>
        </div>
      )}
    </div>
  );
}

export function ProviderBadge({
  provider,
  external,
  fallback,
  webUsed,
}: {
  provider?: string;
  external?: boolean;
  fallback?: boolean;
  webUsed?: boolean;
}) {
  if (!provider) return null;
  const label = external ? `Cloud: ${provider}` : `lokal: ${provider}`;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={external ? "badge-warning" : "badge-success"}>{label}</span>
      {fallback && <span className="badge-neutral">Ausweichmodell</span>}
      {webUsed && <span className="badge-brand">mit Webquellen</span>}
    </span>
  );
}
