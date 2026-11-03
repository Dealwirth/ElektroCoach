/**
 * App-Geruest: Navigation, Kopfzeile, Inhalt.
 *
 * Responsive: auf dem Smartphone eine untere Navigationsleiste, ab Tablet
 * eine feste Seitenspalte. Alle Bedienelemente sind auch mit Touch bedienbar.
 */

import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { Alert } from "./components/ui";
import DashboardPage from "./pages/DashboardPage";
import ImportPage from "./pages/ImportPage";
import LibraryPage from "./pages/LibraryPage";
import PracticePage from "./pages/PracticePage";
import ExamsPage from "./pages/ExamsPage";
import SchematicPage from "./pages/SchematicPage";
import SchematicEditorPage from "./pages/SchematicEditorPage";
import TutorPage from "./pages/TutorPage";
import SettingsPage from "./pages/SettingsPage";
import SystemPage from "./pages/SystemPage";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  short: string;
}

const NAV: NavItem[] = [
  { to: "/", label: "Übersicht", icon: "M3 12l9-8 9 8v8a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z", short: "Start" },
  { to: "/import", label: "Import", icon: "M12 3v12m0 0l-4-4m4 4l4-4M4 21h16", short: "Import" },
  { to: "/bibliothek", label: "Bibliothek", icon: "M4 5h7v14H4zM13 5h7v14h-7z", short: "Bücher" },
  { to: "/lernen", label: "Lernen", icon: "M12 4l9 5-9 5-9-5zM5 12v5l7 4 7-4v-5", short: "Lernen" },
  { to: "/pruefungen", label: "Prüfungen", icon: "M9 4h6v3H9zM6 7h12v13H6zM9 12h6M9 16h4", short: "Prüfung" },
  { to: "/schaltplan", label: "Schaltplan", icon: "M3 7h4v4H3zM17 7h4v4h-4zM7 9h10M3 17h4v4H3zM17 17h4v4h-4zM7 19h10", short: "Plan" },
  { to: "/tutor", label: "KI-Tutor", icon: "M12 3a6 6 0 00-6 6v4l-2 3h16l-2-3V9a6 6 0 00-6-6zM9 21h6", short: "Tutor" },
  { to: "/einstellungen", label: "Einstellungen", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM4 12l2-1-2-1m16 2l-2-1 2-1M12 4l1 2 1-2m-2 16l1-2 1 2", short: "Optionen" },
  { to: "/system", label: "System", icon: "M4 5h16v10H4zM8 19h8M12 15v4", short: "System" },
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
      className="h-5 w-5 shrink-0"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

export default function App() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [aiWarning, setAiWarning] = useState<string | null>(null);
  const location = useLocation();

  useEffect(() => {
    let active = true;
    api
      .health()
      .then(() => active && setOnline(true))
      .catch(() => active && setOnline(false));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    api
      .aiStatus()
      .then((status) => {
        if (!active) return;
        if (!status.any_available) {
          setAiWarning(
            "Keine KI erreichbar. Wissenssuche, Lernen und Schaltplan-Editor arbeiten weiterhin vollständig.",
          );
        } else {
          setAiWarning(null);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [location.pathname]);

  const isEditor = location.pathname.startsWith("/schaltplan/editor");

  return (
    <div className="flex min-h-screen bg-ink-50">
      {/* Seitenspalte ab Tablet */}
      <aside className="hidden w-60 shrink-0 border-r border-ink-200 bg-white md:flex md:flex-col">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white">
            <Icon path="M13 2L4 14h6l-1 8 9-12h-6z" />
          </span>
          <div>
            <p className="text-sm font-bold leading-tight text-ink-900">ElektroCoach</p>
            <p className="text-[11px] leading-tight text-ink-400">Energie & Gebäudetechnik</p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3 pb-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand-50 text-brand-700"
                    : "text-ink-600 hover:bg-ink-50 hover:text-ink-900"
                }`
              }
            >
              <Icon path={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-ink-100 px-5 py-3">
          <p className="flex items-center gap-2 text-xs text-ink-500">
            <span
              className={`h-2 w-2 rounded-full ${
                online === null ? "bg-ink-300" : online ? "bg-emerald-500" : "bg-red-500"
              }`}
            />
            {online === null ? "Verbinde …" : online ? "Verbunden" : "Nicht erreichbar"}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Kopfzeile für Smartphone */}
        <header className="flex items-center justify-between border-b border-ink-200 bg-white px-4 py-3 md:hidden">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Icon path="M13 2L4 14h6l-1 8 9-12h-6z" />
            </span>
            <span className="text-sm font-bold text-ink-900">ElektroCoach</span>
          </div>
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              online === null ? "bg-ink-300" : online ? "bg-emerald-500" : "bg-red-500"
            }`}
            aria-label={online ? "Verbunden" : "Nicht erreichbar"}
          />
        </header>

        <main className={`min-w-0 flex-1 ${isEditor ? "" : "px-4 pb-28 pt-5 sm:px-6 md:pb-10 md:pt-7"}`}>
          {aiWarning && !isEditor && (
            <div className="mb-5">
              <Alert tone="warning" title="Eingeschränkter KI-Betrieb">
                {aiWarning}
              </Alert>
            </div>
          )}
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/bibliothek" element={<LibraryPage />} />
            <Route path="/bibliothek/:documentId" element={<LibraryPage />} />
            <Route path="/lernen" element={<PracticePage />} />
            <Route path="/pruefungen" element={<ExamsPage />} />
            <Route path="/pruefungen/:examId" element={<ExamsPage />} />
            <Route path="/schaltplan" element={<SchematicPage />} />
            <Route path="/schaltplan/editor/:projectId" element={<SchematicEditorPage />} />
            <Route path="/tutor" element={<TutorPage />} />
            <Route path="/einstellungen" element={<SettingsPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route
              path="*"
              element={
                <div className="card card-pad">
                  <p className="text-lg font-semibold text-ink-900">Seite nicht gefunden</p>
                  <p className="mt-1 text-sm text-ink-500">
                    Bitte über die Navigation eine vorhandene Seite wählen.
                  </p>
                </div>
              }
            />
          </Routes>
        </main>

        {/* Untere Navigationsleiste auf dem Smartphone */}
        <nav className="fixed bottom-0 left-0 right-0 z-40 grid grid-cols-5 border-t border-ink-200 bg-white/95 backdrop-blur md:hidden">
          {NAV.slice(0, 5).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium ${
                  isActive ? "text-brand-700" : "text-ink-500"
                }`
              }
            >
              <Icon path={item.icon} />
              {item.short}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
