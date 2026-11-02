/** Diagnostics: events, repair actions, and the full step-by-step error report. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, formatDate, table,
  statusDot, infoBox, field, input, formatBytes,
} from '../ui.js';

export async function renderDiagnostics(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Fehlerdiagnose' }),
    el('p', { text:
      'Hier sehen Sie alle Probleme, die durchgeführten Reparaturversuche und – wenn ein Fehler nicht automatisch behoben werden konnte – eine vollständige Anleitung in der richtigen Reihenfolge.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const eventsHost = el('div');
  const actionsHost = el('div');
  const reportHost = el('div');
  const logsHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [eventsHost, actionsHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [reportHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [logsHost]));

  async function loadEvents() {
    eventsHost.replaceChildren(spinner('Ereignisse werden geladen …'));
    try {
      const data = await api.get('api/events', { limit: 100 });
      eventsHost.replaceChildren(card('Ereignisse und Warnungen', [
        el('p', { className: 'muted small', text:
          `${data.counts.critical || 0} kritisch, ${data.counts.error || 0} Fehler, ${data.counts.warning || 0} Warnungen, ${data.counts.info || 0} Informationen.` }),
        data.items.length
          ? table(
              ['Zeit', 'Stufe', 'Meldung', 'Aktion'],
              data.items.map((event) => [
                formatDate(event.created_at),
                el('span', {}, [statusDot(event.level), ` ${event.level}`]),
                el('div', {}, [
                  el('span', { text: event.message }),
                  event.resolved ? el('div', { className: 'muted small', text: 'erledigt' }) : null,
                ]),
                el('span', { className: 'btn-row' }, [
                  button('Anleitung', {
                    className: 'btn-sm',
                    onClick: () => loadReport({ eventId: event.id }),
                  }),
                  !event.resolved
                    ? button('Erledigt', {
                        variant: 'ghost',
                        className: 'btn-sm',
                        onClick: async () => {
                          try {
                            await api.post(`api/events/${event.id}/resolve`);
                            loadEvents();
                          } catch (error) {
                            toast(error.message, 'error');
                          }
                        },
                      })
                    : null,
                ]),
              ]),
            )
          : infoBox('Es liegen keine Probleme vor.', 'success'),
      ]));
    } catch (error) {
      eventsHost.replaceChildren(errorBox(error));
    }
  }

  async function loadActions() {
    actionsHost.replaceChildren(spinner('Reparaturaktionen werden geladen …'));
    try {
      const data = await api.get('api/diagnostics/repairs');
      actionsHost.replaceChildren(card('Automatische Reparatur', [
        el('p', { className: 'muted small', text:
          `Automatische Reparatur ist ${data.auto_repair_enabled ? 'aktiviert' : 'deaktiviert'}. Sichere Reparaturen laufen ohne Rückfrage. Alles, was Daten verändert, benötigt Ihre ausdrückliche Bestätigung.` }),
        table(
          ['Aktion', 'Beschreibung', 'Art', 'Ausführen'],
          data.actions.map((action) => [
            action.name,
            action.description,
            action.destructive
              ? badge('verändert Daten', 'warning')
              : badge('sicher', 'ok'),
            button('Ausführen', {
              className: 'btn-sm',
              onClick: () => runAction(action),
            }),
          ]),
        ),
        el('h4', { style: { marginTop: '14px' }, text: 'Verlauf der Reparaturen' }),
        data.history.length
          ? table(
              ['Zeit', 'Aktion', 'Status', 'Ergebnis'],
              data.history.map((entry) => [
                formatDate(entry.created_at),
                entry.action,
                entry.status,
                entry.detail,
              ]),
            )
          : el('p', { className: 'muted small', text: 'Es wurden noch keine Reparaturen ausgeführt.' }),
      ]));
    } catch (error) {
      actionsHost.replaceChildren(errorBox(error));
    }
  }

  async function runAction(action) {
    let confirmed = false;
    if (action.requires_confirmation) {
      confirmed = window.confirm(
        `${action.description}\n\n${action.guidance || ''}\n\nWirklich ausführen?`);
      if (!confirmed) return;
    }
    try {
      const result = await api.post('api/diagnostics/actions', {
        action: action.name,
        confirmed,
      });
      toast(result.detail, result.status === 'repaired' ? 'success' : 'warning', 9000);
      loadActions();
      loadEvents();
    } catch (error) {
      toast(error.message, 'error', 9000);
    }
  }

  async function loadReport({ eventId, component } = {}) {
    reportHost.replaceChildren(spinner('Fehlerbericht wird erstellt …'));
    try {
      const report = await api.get('api/diagnostics/report', {
        event_id: eventId,
        component,
      });
      reportHost.replaceChildren(card('Vollständiger Fehlerbericht', [
        el('div', { className: 'grid grid-2' }, [
          el('div', {}, [
            el('h4', { text: 'Fehlerbeschreibung' }),
            el('p', { text: report.description }),
            el('p', { className: 'muted small', text: `Zeitpunkt: ${formatDate(report.time)}` }),
            el('p', { className: 'muted small', text: `Betroffene Komponente: ${report.component}` }),
            el('h4', { text: 'Vermutete Ursache' }),
            el('p', { text: report.suspected_cause }),
            report.confirmed_cause
              ? el('div', {}, [el('h4', { text: 'Festgestellte Ursache' }), el('p', { text: report.confirmed_cause })])
              : null,
            el('h4', { text: 'Wer führt die Lösung aus?' }),
            el('p', { text: report.responsible_action }),
          ]),
          el('div', {}, [
            el('h4', { text: 'Bereits durchgeführte Reparaturversuche' }),
            report.repair_attempts.length
              ? el('ul', {}, report.repair_attempts.map((attempt) =>
                  el('li', { text: `${formatDate(attempt.at)} – ${attempt.action}: ${attempt.detail} (${attempt.status})` })))
              : el('p', { className: 'muted small', text: 'Es wurden noch keine Reparaturversuche unternommen.' }),
            el('h4', { text: 'Relevante Protokollzeilen' }),
            el('pre', { text: report.log_excerpt.map((entry) =>
              `${entry.time} ${entry.level} ${entry.logger}: ${entry.message}`).join('\n') || 'Keine passenden Zeilen.' }),
          ]),
        ]),
        el('h4', { text: 'Lösung – bitte in dieser Reihenfolge ausführen' }),
        el('ol', { className: 'instructions' }, report.steps.map((step) => el('li', { text: step }))),
        infoBox(`Erfolgskontrolle: ${report.success_criteria}`, 'success'),
        infoBox(`Wenn das Problem bleibt: ${report.if_error}`, 'warning'),
        infoBox(report.what_happens_next, 'info'),
      ]));
      reportHost.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      reportHost.replaceChildren(errorBox(error));
    }
  }

  async function loadLogs() {
    logsHost.replaceChildren(spinner('Protokoll wird geladen …'));
    try {
      const data = await api.get('api/logs', { limit: 200 });
      logsHost.replaceChildren(card('Aktuelles Protokoll', [
        el('pre', { text: data.items.map((entry) =>
          `${entry.time} ${entry.level} ${entry.logger}: ${entry.message}`).join('\n') || 'Keine Einträge.' }),
      ]));
    } catch (error) {
      logsHost.replaceChildren(errorBox(error));
    }
  }

  loadEvents();
  loadActions();
  loadLogs();
}
