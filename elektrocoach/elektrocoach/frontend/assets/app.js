/**
 * Application shell: navigation, routing, live status and error handling.
 *
 * The shell owns the WebSocket connection and the toast container so that view
 * modules stay focused on their own content. Navigation uses a hash route so the
 * back button works and a reload keeps the current view.
 */

import { api, initSession, openSocket, ApiError } from './api.js';
import { el, clear, toast, errorBox, statusDot, formatDate } from './ui.js';

import { renderDashboard } from './views/dashboard.js';
import { renderLearning } from './views/learning.js';
import { renderQuestions } from './views/questions.js';
import { renderExams } from './views/exams.js';
import { renderPlan } from './views/plan.js';
import { renderKnowledge } from './views/knowledge.js';
import { renderDocuments } from './views/documents.js';
import { renderEditor } from './views/editor.js';
import { renderAssistant } from './views/assistant.js';
import { renderSystem } from './views/system.js';
import { renderDiagnostics } from './views/diagnostics.js';
import { renderSettings } from './views/settings.js';
import { renderSetup } from './views/setup.js';

const ROUTES = [
  { id: 'dashboard', label: 'Dashboard', icon: '◧', group: 'Übersicht', render: renderDashboard },
  { id: 'learning', label: 'Lernen', icon: '✦', group: 'Lernen', render: renderLearning },
  { id: 'questions', label: 'Aufgaben', icon: '✎', group: 'Lernen', render: renderQuestions },
  { id: 'exams', label: 'Prüfungen', icon: '⏱', group: 'Lernen', render: renderExams },
  { id: 'plan', label: 'Lernplan', icon: '🗓', group: 'Lernen', render: renderPlan },
  { id: 'knowledge', label: 'Wissensdatenbank', icon: '📖', group: 'Inhalte', render: renderKnowledge },
  { id: 'documents', label: 'Dokumentenimport', icon: '📥', group: 'Inhalte', render: renderDocuments },
  { id: 'editor', label: 'Schaltplaneditor', icon: '⌗', group: 'Inhalte', render: renderEditor },
  { id: 'assistant', label: 'KI-Assistent', icon: '🤖', group: 'KI und System', render: renderAssistant },
  { id: 'system', label: 'Systemstatus', icon: '❤', group: 'KI und System', render: renderSystem },
  { id: 'diagnostics', label: 'Fehlerdiagnose', icon: '🛠', group: 'KI und System', render: renderDiagnostics },
  { id: 'settings', label: 'Einstellungen', icon: '⚙', group: 'KI und System', render: renderSettings },
  { id: 'setup', label: 'Einrichtungsassistent', icon: '✓', group: 'KI und System', render: renderSetup },
];

const state = {
  route: 'dashboard',
  live: null,
  meta: null,
  events: { info: 0, warning: 0, error: 0, critical: 0 },
  jobs: {},
  socket: null,
  connection: 'offline',
};

function currentRoute() {
  const hash = window.location.hash.replace(/^#\/?/, '');
  return ROUTES.some((route) => route.id === hash) ? hash : 'dashboard';
}

function buildSidebar() {
  const sidebar = document.getElementById('sidebar');
  clear(sidebar);
  const groups = [];
  ROUTES.forEach((route) => {
    let group = groups.find((entry) => entry.name === route.group);
    if (!group) {
      group = { name: route.group, routes: [] };
      groups.push(group);
    }
    group.routes.push(route);
  });

  groups.forEach((group) => {
    sidebar.appendChild(
      el('div', { className: 'nav-group' }, [
        el('div', { className: 'nav-group-label', text: group.name }),
        ...group.routes.map((route) => {
          const badge =
            route.id === 'diagnostics' && problemCount() > 0
              ? el('span', { className: 'nav-badge', text: String(problemCount()) })
              : null;
          return el(
            'button',
            {
              className: `nav-item ${state.route === route.id ? 'active' : ''}`,
              dataset: { route: route.id },
              attrs: { type: 'button' },
              on: {
                click: () => {
                  window.location.hash = `#/${route.id}`;
                  closeSidebar();
                },
              },
            },
            [
              el('span', { className: 'nav-icon', text: route.icon, attrs: { 'aria-hidden': 'true' } }),
              el('span', { text: route.label }),
              badge,
            ],
          );
        }),
      ]),
    );
  });
}

function problemCount() {
  return (state.events.error || 0) + (state.events.critical || 0);
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar) sidebar.classList.remove('open');
}

function renderTopbar() {
  const status = document.getElementById('topbar-status');
  if (!status) return;
  clear(status);

  const liveTone = state.connection === 'online' ? 'ok' : 'warning';
  status.appendChild(
    el('span', { className: 'topbar-status-item', attrs: { title: 'Live-Verbindung' } }, [
      el('span', { className: `dot dot-${liveTone}` }),
      el('span', { text: state.connection === 'online' ? 'Live' : 'Offline' }),
    ]),
  );

  const running = (state.live && state.live.running) || [];
  if (running.length) {
    status.appendChild(
      el('span', { className: 'topbar-status-item', text: `${running.length} Aufgabe(n) laufen` }),
    );
  }

  const errors = problemCount();
  if (errors > 0) {
    status.appendChild(
      el('span', { className: 'topbar-status-item' }, [
        statusDot('error'),
        el('span', { text: `${errors} Problem(e)` }),
      ]),
    );
  }

  if (state.live && typeof state.live.due_cards === 'number') {
    status.appendChild(
      el('span', { className: 'topbar-status-item', text: `${state.live.due_cards} fällig` }),
    );
  }
}

async function renderView() {
  const main = document.getElementById('main');
  const route = ROUTES.find((entry) => entry.id === state.route);
  document.getElementById('topbar-title').textContent = route.label;
  clear(main);
  const container = el('div', { className: 'view' });
  main.appendChild(container);
  try {
    await route.render(container, { state, navigate: navigate });
  } catch (error) {
    container.appendChild(errorBox(error));
    if (!(error instanceof ApiError)) console.error(error);
  }
}

function navigate(routeId) {
  window.location.hash = `#/${routeId}`;
}

function onRouteChange() {
  state.route = currentRoute();
  buildSidebar();
  renderView();
}

function handleLiveMessage(message) {
  state.live = message;
  state.events = message.events || state.events;
  state.jobs = message.jobs || state.jobs;
  renderTopbar();
  buildSidebar();
  document.dispatchEvent(new CustomEvent('elektrocoach:live', { detail: message }));
}

async function boot() {
  buildSidebar();
  document.getElementById('nav-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
  });

  window.addEventListener('hashchange', onRouteChange);

  try {
    await initSession();
  } catch (error) {
    document.getElementById('main').appendChild(errorBox(error));
    return;
  }

  try {
    state.meta = await api.get('api/meta');
  } catch (error) {
    state.meta = null;
  }

  // Show the setup wizard first when setup is not finished.
  try {
    const setup = await api.get('api/setup');
    if (!setup.completed && !window.location.hash) {
      window.location.hash = '#/setup';
    }
  } catch (error) {
    /* a failing setup check must not block the app */
  }

  state.route = currentRoute();
  buildSidebar();
  await renderView();
  renderTopbar();

  state.socket = openSocket(handleLiveMessage, (status) => {
    state.connection = status;
    renderTopbar();
  });

  // Refresh the footer version label.
  const versionLabel = document.getElementById('app-version');
  if (versionLabel && state.meta) {
    versionLabel.textContent = `Version ${state.meta.version}`;
  }

  // Surface a warning when no AI is usable, without blocking anything.
  try {
    const status = await api.get('api/system/status', { checks: 'false' });
    const summary = status.summary || {};
    if (!summary.ollama_model) return;
  } catch (error) {
    /* ignore */
  }
}

document.addEventListener('DOMContentLoaded', boot);
