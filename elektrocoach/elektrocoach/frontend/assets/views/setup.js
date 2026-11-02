/** Setup wizard: run each check, read the exact next step, only finish when ok. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, infoBox, statusDot,
  progressBar, table, formatDate,
} from '../ui.js';

const STATUS_LABELS = {
  not_started: 'Noch nicht begonnen',
  running: 'In Bearbeitung',
  ok: 'Erfolgreich',
  warning: 'Warnung',
  failed: 'Fehlgeschlagen',
  needs_input: 'Benutzereingabe erforderlich',
};

export async function renderSetup(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Einrichtungsassistent' }),
    el('p', { text:
      'Der Assistent prüft der Reihe nach alle Voraussetzungen und sagt Ihnen genau, was als Nächstes zu tun ist – abgestimmt auf Ihren tatsächlichen Systemzustand. Er meldet keinen Erfolg, solange eine wichtige Prüfung fehlt.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const summaryHost = el('div');
  const stepsHost = el('div');
  host.appendChild(summaryHost);
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [stepsHost]));

  let state = null;

  function renderSummary() {
    const progress = state.progress || {};
    summaryHost.replaceChildren(card('Fortschritt', [
      el('div', { className: 'grid grid-4' }, [
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: `${progress.percent || 0} %` }),
          el('div', { className: 'stat-label', text: 'abgeschlossen' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String(progress.ok || 0) }),
          el('div', { className: 'stat-label', text: 'erfolgreich' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String((progress.failed || 0) + (progress.needs_input || 0)) }),
          el('div', { className: 'stat-label', text: 'offen' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String(progress.warning || 0) }),
          el('div', { className: 'stat-label', text: 'Warnungen' }),
        ]),
      ]),
      el('div', { style: { marginTop: '10px' } }, [progressBar((progress.percent || 0) / 100)]),
      el('p', { style: { marginTop: '10px' }, text: state.summary }),
      el('div', { className: 'btn-row' }, [
        button('Alle offenen Prüfungen starten', {
          variant: 'primary',
          onClick: async (event) => {
            event.target.disabled = true;
            summaryHost.replaceChildren(spinner('Prüfungen laufen … Das kann beim ersten Mal einige Minuten dauern, weil auch ein Testdokument verarbeitet wird.'));
            try {
              const result = await api.post('api/setup/run');
              state = result;
              render();
              toast('Die Prüfungen sind abgeschlossen.', 'success');
            } catch (error) {
              summaryHost.replaceChildren(errorBox(error));
            } finally {
              event.target.disabled = false;
            }
          },
        }),
        button('Alles neu prüfen', {
          onClick: async () => {
            summaryHost.replaceChildren(spinner('Prüfungen laufen …'));
            try {
              const result = await api.post('api/setup/run?only_pending=false');
              state = result;
              render();
            } catch (error) {
              summaryHost.replaceChildren(errorBox(error));
            }
          },
        }),
        button('Modell jetzt laden', {
          onClick: async () => {
            try {
              const response = await api.post('api/setup/models/pull');
              toast(response.message, 'info', 9000);
            } catch (error) {
              toast(error.message, 'error');
            }
          },
        }),
        button('Zurücksetzen', {
          variant: 'ghost',
          onClick: async () => {
            if (!window.confirm('Den Einrichtungsstatus zurücksetzen?')) return;
            try {
              state = await api.post('api/setup/reset');
              render();
            } catch (error) {
              toast(error.message, 'error');
            }
          },
        }),
      ]),
      state.completed
        ? infoBox('Die Einrichtung ist abgeschlossen. ElektroCoach ist einsatzbereit.', 'success')
        : (state.can_complete
            ? el('div', { className: 'btn-row' }, [
                button('Einrichtung abschließen', {
                  variant: 'primary',
                  onClick: async () => {
                    try {
                      state = await api.post('api/setup/complete');
                      render();
                      toast('Die Einrichtung wurde abgeschlossen.', 'success');
                    } catch (error) {
                      toast(error.message, 'error', 9000);
                    }
                  },
                }),
              ])
            : infoBox('Die Einrichtung kann erst abgeschlossen werden, wenn alle erforderlichen Prüfungen erfolgreich waren.', 'warning')),
    ]));
  }

  function renderSteps() {
    const nodes = (state.steps || []).map((step) => {
      const guidanceHost = el('div', {}, step.guidance
        ? [el('div', { className: 'step-guidance', text: step.guidance })]
        : []);
      return el('div', { className: 'step' }, [
        el('span', { style: { paddingTop: '3px' } }, [statusDot(step.status)]),
        el('div', { className: 'step-body' }, [
          el('div', { className: 'step-title' }, [
            el('span', { text: step.title }),
            badge(STATUS_LABELS[step.status] || step.status,
              step.status === 'ok' ? 'ok'
                : step.status === 'warning' ? 'warning'
                  : step.status === 'failed' ? 'error'
                    : step.status === 'needs_input' ? 'warning' : 'neutral'),
            step.manual ? badge('Ihre Handlung nötig', 'info') : null,
            !step.required ? badge('optional', 'neutral') : null,
          ]),
          step.message ? el('div', { className: 'step-message', text: step.message }) : null,
          el('div', { className: 'step-why', text: step.why }),
          step.checked_at ? el('div', { className: 'muted small', text: `Geprüft: ${formatDate(step.checked_at)}` }) : null,
          guidanceHost,
          el('div', { className: 'btn-row', style: { marginTop: '8px' } }, [
            button('Diesen Schritt prüfen', {
              className: 'btn-sm',
              onClick: async (event) => {
                event.target.disabled = true;
                guidanceHost.replaceChildren(spinner('Prüfung läuft …'));
                try {
                  const response = await api.post(`api/setup/steps/${step.key}`);
                  state = response.state;
                  render();
                } catch (error) {
                  guidanceHost.replaceChildren(errorBox(error));
                } finally {
                  event.target.disabled = false;
                }
              },
            }),
          ]),
        ]),
      ]);
    });
    stepsHost.replaceChildren(card('Prüfschritte', nodes.length ? nodes : [
      el('p', { className: 'muted', text: 'Es sind keine Schritte definiert.' }),
    ]));
  }

  function render() {
    renderSummary();
    renderSteps();
  }

  try {
    state = await api.get('api/setup');
    render();
  } catch (error) {
    host.replaceChildren(errorBox(error));
  }
}
