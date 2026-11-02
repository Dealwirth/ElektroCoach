/** Study plan: build a dynamic plan from mastery, due cards and the exam date. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, table, field, input,
  infoBox, percent, progressBar,
} from '../ui.js';

export async function renderPlan(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Lernplan' }),
    el('p', { text:
      'Der Lernplan wird aus Ihrem tatsächlichen Lernstand erzeugt: aus fälligen Wiederholungen, schwachen Themen und dem Prüfungstermin. Er wird bei jeder Erstellung neu berechnet.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const controls = el('div');
  const planHost = el('div');
  const masteryHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [controls, masteryHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [planHost]));

  const horizon = input({ type: 'number', value: '14', min: '1', max: '90' });
  const examDate = input({ type: 'date' });

  try {
    const settings = await api.get('api/settings');
    const stored = settings.settings || {};
    if (stored['learning.exam_date']) examDate.value = stored['learning.exam_date'];
  } catch (error) {
    /* optional */
  }

  controls.appendChild(card('Plan erstellen', [
    field('Zeitraum in Tagen', horizon, 'Für wie viele Tage soll der Plan erstellt werden?'),
    field('Prüfungstermin', examDate, 'Optional. Mit Datum werden die verbleibenden Tage berücksichtigt.'),
    el('div', { className: 'btn-row' }, [
      button('Lernplan erstellen', {
        variant: 'primary',
        onClick: async (event) => {
          event.target.disabled = true;
          planHost.replaceChildren(spinner('Lernplan wird berechnet …'));
          try {
            const response = await api.post('api/learning/plan', {
              horizon_days: Number(horizon.value) || 14,
              exam_date: examDate.value || null,
            });
            renderPlan(response.plan);
            toast('Der Lernplan wurde erstellt.', 'success');
          } catch (error) {
            planHost.replaceChildren(errorBox(error));
          } finally {
            event.target.disabled = false;
          }
        },
      }),
      button('Lernplan laden', {
        onClick: async () => {
          planHost.replaceChildren(spinner('Lernplan wird geladen …'));
          try {
            const response = await api.get('api/learning/plan');
            if (response.plan) renderPlan(response.plan);
            else planHost.replaceChildren(infoBox(response.message || 'Es liegt noch kein Lernplan vor.'));
          } catch (error) {
            planHost.replaceChildren(errorBox(error));
          }
        },
      }),
    ]),
  ]));

  function renderPlan(plan) {
    if (!plan) {
      planHost.replaceChildren(infoBox('Es liegt noch kein Lernplan vor. Klicken Sie auf „Lernplan erstellen“.'));
      return;
    }
    const summary = plan.summary || {};
    planHost.replaceChildren(card('Aktueller Lernplan', [
      el('div', { className: 'grid grid-4', style: { marginBottom: '14px' } }, [
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String(plan.days ? plan.days.length : 0) }),
          el('div', { className: 'stat-label', text: 'geplante Tage' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String(summary.total_tasks || 0) }),
          el('div', { className: 'stat-label', text: 'Aufgaben insgesamt' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: `${summary.minutes_per_day || 0}` }),
          el('div', { className: 'stat-label', text: 'Minuten pro Tag' }),
        ]),
        el('div', { className: 'stat' }, [
          el('div', { className: 'stat-value', text: String(summary.days_until_exam ?? '–') }),
          el('div', { className: 'stat-label', text: 'Tage bis zur Prüfung' }),
        ]),
      ]),
      el('p', { className: 'muted small', text: plan.note }),
      table(
        ['Tag', 'Datum', 'Schwerpunkte', 'Aufgaben'],
        (plan.days || []).map((day) => [
          String(day.index),
          day.date,
          (day.topics || []).join(', ') || 'Wiederholung',
          String(day.task_count),
        ]),
      ),
      el('div', { className: 'btn-row', style: { marginTop: '12px' } }, [
        button('Jetzt lernen', { variant: 'primary', onClick: () => navigate('learning') }),
      ]),
    ]));
  }

  async function loadMastery() {
    masteryHost.replaceChildren(spinner('Themenstände werden geladen …'));
    try {
      const data = await api.get('api/learning/mastery');
      masteryHost.replaceChildren(card('Themenstände', [
        data.items.length
          ? table(
              ['Fachgebiet', 'Thema', 'Stand', 'Versuche'],
              data.items.map((row) => [
                row.subject || '–',
                row.topic || '–',
                el('div', {}, [
                  progressBar(Number(row.mastery)),
                  el('span', { className: 'small', text: percent(row.mastery) }),
                ]),
                String(row.attempts),
              ]),
            )
          : el('p', { className: 'muted', text: 'Es liegen noch keine Ergebnisse vor.' }),
        (data.weak || []).length
          ? el('p', { className: 'muted small', text:
              `${data.weak.length} Thema(en) liegen unter 70 % – diese werden im Plan bevorzugt.` })
          : null,
      ]));
    } catch (error) {
      masteryHost.replaceChildren(errorBox(error));
    }
  }

  loadMastery();
  try {
    const response = await api.get('api/learning/plan');
    if (response.plan) renderPlan(response.plan);
    else planHost.replaceChildren(infoBox(response.message || 'Es liegt noch kein Lernplan vor.'));
  } catch (error) {
    planHost.replaceChildren(errorBox(error));
  }
}
