/** System status: the monitoring table, jobs, backups and Home Assistant. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, formatBytes, formatDate,
  table, statusDot, progressBar, infoBox, field, input,
} from '../ui.js';

const STATUS_LABELS = {
  ok: 'in Ordnung',
  warning: 'Warnung',
  error: 'Fehler',
  critical: 'Kritischer Fehler',
  disabled: 'deaktiviert',
};

export async function renderSystem(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Systemstatus' }),
    el('p', { text:
      'Alle Prüfungen laufen tatsächlich und zeigen den echten Zustand. Ist eine Komponente nicht erreichbar, steht hier eine genaue Anleitung.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const overallHost = el('div');
  const checksHost = el('div');
  const jobsHost = el('div');
  const backupHost = el('div');
  const haHost = el('div');
  host.appendChild(overallHost);
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [checksHost]));
  host.appendChild(el('div', { className: 'grid grid-2', style: { marginTop: '16px' } }, [jobsHost, backupHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [haHost]));

  async function loadStatus() {
    overallHost.replaceChildren(spinner('Systemprüfung läuft …'));
    checksHost.replaceChildren();
    try {
      const report = await api.get('api/system/status');
      const tone = { ok: 'success', warning: 'warning', error: 'error', critical: 'error' }[report.overall] || 'info';
      overallHost.replaceChildren(
        el('div', { className: `alert alert-${tone}` }, [
          el('strong', { text: report.overall === 'ok'
            ? 'Alle Systeme sind in Ordnung. '
            : 'Es gibt Punkte, die Aufmerksamkeit benötigen. ' }),
          el('span', { text:
            `${report.counts.ok} in Ordnung, ${report.counts.warning} Warnungen, ${report.counts.error} Fehler, ${report.counts.critical} kritisch, ${report.counts.disabled} deaktiviert.` }),
          el('div', { className: 'small', text: `Geprüft: ${formatDate(report.generated_at)}` }),
          el('div', { className: 'btn-row', style: { marginTop: '8px' } }, [
            button('Erneut prüfen', { variant: 'primary', className: 'btn-sm', onClick: loadStatus }),
            button('Diagnose mit Reparatur', {
              className: 'btn-sm',
              onClick: async () => {
                overallHost.replaceChildren(spinner('Diagnose und sichere Reparaturen laufen …'));
                try {
                  const result = await api.post('api/diagnostics/run');
                  toast(result.auto_repairs && result.auto_repairs.length
                    ? `${result.auto_repairs.length} Reparatur(en) ausgeführt.`
                    : 'Die Diagnose ist abgeschlossen.', 'success');
                  loadStatus();
                } catch (error) {
                  overallHost.replaceChildren(errorBox(error));
                }
              },
            }),
            button('Fehlerdiagnose', { className: 'btn-sm', onClick: () => navigate('diagnostics') }),
          ]),
        ]),
      );

      checksHost.replaceChildren(card('Prüfungen', [
        table(
          ['Komponente', 'Status', 'Ergebnis', 'Dauer'],
          report.checks.map((check) => [
            check.name,
            el('span', {}, [statusDot(check.status), ` ${STATUS_LABELS[check.status] || check.status}`]),
            el('div', {}, [
              el('span', { text: check.message }),
              check.guidance ? el('div', { className: 'muted small', text: check.guidance }) : null,
            ]),
            `${check.duration_ms} ms`,
          ]),
        ),
        el('p', { className: 'muted small', text:
          'Diese Prüfung läuft regelmäßig im Hintergrund und belastet das System kaum: Sie liest /proc, führt eine kurze Datenbankprüfung aus und fragt die KI-Dienste ab.' }),
      ]));
    } catch (error) {
      overallHost.replaceChildren(errorBox(error));
    }
  }

  async function loadJobs() {
    jobsHost.replaceChildren(spinner('Aufgaben werden geladen …'));
    try {
      const data = await api.get('api/jobs', { limit: 30 });
      jobsHost.replaceChildren(card('Hintergrundaufgaben', [
        el('p', { className: 'muted small', text:
          `Worker: ${data.worker.alive ? 'läuft' : 'gestoppt'} · ${data.counts.running || 0} laufend, ${data.counts.queued || 0} wartend, ${data.counts.failed || 0} fehlgeschlagen.` }),
        data.items.length
          ? table(
              ['ID', 'Typ', 'Status', 'Fortschritt', 'Meldung', 'Aktion'],
              data.items.map((job) => [
                String(job.id),
                job.type,
                el('span', {}, [statusDot(job.status), ` ${job.status}`]),
                el('div', {}, [progressBar(job.progress || 0)]),
                job.error || job.message || '–',
                job.status === 'failed'
                  ? button('Erneut', {
                      className: 'btn-sm',
                      onClick: async () => {
                        try {
                          const result = await api.post(`api/jobs/${job.id}/retry`);
                          toast(result.detail, result.status === 'repaired' ? 'success' : 'warning');
                          loadJobs();
                        } catch (error) {
                          toast(error.message, 'error');
                        }
                      },
                    })
                  : '–',
              ]),
            )
          : el('p', { className: 'muted', text: 'Zurzeit sind keine Aufgaben vorhanden.' }),
      ]));
    } catch (error) {
      jobsHost.replaceChildren(errorBox(error));
    }
  }

  async function loadBackups() {
    backupHost.replaceChildren(spinner('Backups werden geladen …'));
    try {
      const data = await api.get('api/backups');
      backupHost.replaceChildren(card('Backups', [
        el('p', { className: 'small', text: `Zielordner: ${data.target.path}` }),
        data.target.warning ? infoBox(data.target.warning, 'warning') : null,
        el('p', { className: 'muted small', text:
          `${data.count} Backup(s), ${data.total_human}. Automatisch: ${data.enabled ? `alle ${data.interval_hours} h` : 'deaktiviert'}. Aufbewahrt werden ${data.keep} Sicherungen.` }),
        el('div', { className: 'btn-row' }, [
          button('Backup jetzt erstellen', {
            variant: 'primary',
            className: 'btn-sm',
            onClick: async () => {
              try {
                const response = await api.post('api/backups');
                toast(response.message, 'success');
                loadBackups();
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
        ]),
      ]));
    } catch (error) {
      backupHost.replaceChildren(errorBox(error));
    }
  }

  async function loadHomeAssistant() {
    haHost.replaceChildren(spinner('Home-Assistant-Verbindung wird geprüft …'));
    try {
      const data = await api.get('api/homeassistant/status');
      haHost.replaceChildren(card('Home Assistant', [
        el('p', { className: 'small' }, [
          statusDot(data.available ? 'ok' : 'warning'),
          el('span', { text: data.available
            ? ` Verbunden${data.version ? ` (Home Assistant ${data.version})` : ''}.`
            : ` ${data.message || 'Nicht verbunden.'}` }),
        ]),
        el('p', { className: 'muted small', text:
          `Benachrichtigungen: ${data.notifications.enabled ? 'aktiviert' : 'deaktiviert'} · Dienst: ${data.notifications.service}` }),
        el('h4', { text: 'Sensoren' }),
        table(['Entität', 'Name', 'Einheit'], (data.sensors || []).map((sensor) => [
          sensor.entity_id, sensor.name, sensor.unit || '–',
        ])),
        el('div', { className: 'btn-row', style: { marginTop: '10px' } }, [
          button('Werte jetzt senden', {
            className: 'btn-sm',
            onClick: async () => {
              try {
                const response = await api.post('api/homeassistant/publish');
                toast(response.message, 'success');
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
          button('Testbenachrichtigung', {
            className: 'btn-sm',
            onClick: async () => {
              try {
                const response = await api.post('api/homeassistant/notify-test');
                toast(response.message, response.ok ? 'success' : 'warning', 9000);
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
        ]),
      ]));
    } catch (error) {
      haHost.replaceChildren(errorBox(error));
    }
  }

  loadStatus();
  loadJobs();
  loadBackups();
  loadHomeAssistant();
}
