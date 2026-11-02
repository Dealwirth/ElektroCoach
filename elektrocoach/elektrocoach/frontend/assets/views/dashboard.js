/** Dashboard: the current state of learning and the system at a glance. */

import { api } from '../api.js';
import {
  el, card, statusDot, button, table, spinner, errorBox, formatDate, percent,
} from '../ui.js';

function statCard(value, label, hint) {
  return card(
    null,
    el('div', { className: 'stat' }, [
      el('div', { className: 'stat-value', text: value }),
      el('div', { className: 'stat-label', text: label }),
      hint ? el('div', { className: 'stat-hint', text: hint }) : null,
    ]),
  );
}

function sparkline(points) {
  if (!points || !points.length) {
    return el('p', { className: 'muted small', text: 'Noch keine Daten.' });
  }
  const width = 320;
  const height = 70;
  const max = Math.max(...points.map((p) => p.value), 1);
  const canvas = el('canvas', {
    attrs: { width, height },
    style: { width: '100%', height: '70px' },
  });
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, width, height);
  context.strokeStyle = '#1d5fd0';
  context.lineWidth = 2;
  context.beginPath();
  points.forEach((point, index) => {
    const x = (index / Math.max(1, points.length - 1)) * (width - 8) + 4;
    const y = height - 6 - (point.value / max) * (height - 14);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  context.fillStyle = 'rgba(29, 95, 208, 0.12)';
  context.lineTo(width - 4, height - 4);
  context.lineTo(4, height - 4);
  context.closePath();
  context.fill();
  return canvas;
}

export async function renderDashboard(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Dashboard' }),
    el('p', { text: 'Ihr aktueller Lernstand, die nächsten Schritte und der Zustand des Systems.' }),
  ]));

  const body = el('div');
  container.appendChild(body);
  body.appendChild(spinner('Übersicht wird geladen …'));

  let data;
  try {
    data = await api.get('api/dashboard');
  } catch (error) {
    body.replaceChildren(errorBox(error));
    return;
  }

  body.replaceChildren();

  const attempts7 = data.attempts_7d || { total: 0, correct: 0, avg_ratio: 0 };
  const accuracy = attempts7.total ? attempts7.correct / attempts7.total : 0;

  body.appendChild(
    el('div', { className: 'grid grid-4', style: { marginBottom: '16px' } }, [
      statCard(String(data.due_now), 'Fällige Wiederholungen',
        data.due_now ? 'Jetzt lernen' : 'Nichts fällig'),
      statCard(percent(accuracy), 'Trefferquote (7 Tage)',
        `${attempts7.correct} von ${attempts7.total} richtig`),
      statCard(String(data.counts.questions), 'Aufgaben verfügbar',
        `${data.counts.knowledge} Wissenseinträge`),
      statCard(String(data.counts.documents), 'Importierte Dokumente',
        `${data.counts.drawings} Schaltpläne`),
    ]),
  );

  const activityCard = card('Lernaktivität (14 Tage)', [
    sparkline((data.activity || []).map((entry) => ({ value: entry.attempts }))),
    el('p', { className: 'muted small', text:
      (data.activity || []).length
        ? `${data.activity.reduce((sum, e) => sum + e.attempts, 0)} beantwortete Aufgaben.`
        : 'Noch keine Aufgaben beantwortet. Beginnen Sie im Bereich „Lernen“.' }),
    el('div', { className: 'btn-row' }, [
      button('Jetzt lernen', { variant: 'primary', onClick: () => navigate('learning') }),
      button('Aufgaben erstellen', { onClick: () => navigate('questions') }),
    ]),
  ]);

  const dueForecast = card('Wiederholungen in den nächsten Tagen', [
    (data.review_forecast || []).length
      ? table(
          ['Tag', 'Fällig'],
          data.review_forecast.slice(0, 7).map((entry) => [entry.day, String(entry.count)]),
        )
      : el('p', { className: 'muted small', text: 'Zurzeit keine geplanten Wiederholungen.' }),
  ]);

  const weakCard = card('Ihre Schwachstellen', [
    (data.weak_topics || []).length
      ? el('div', { className: 'issue-list' }, data.weak_topics.map((topic) =>
          el('div', { className: 'issue issue-warning' }, [
            el('strong', { text: `${topic.subject} – ${topic.topic}` }),
            el('div', { className: 'small', text:
              `Trefferquote ${percent(topic.mastery)} aus ${topic.attempts} Versuchen.` }),
          ])))
      : el('p', { className: 'muted small', text:
          'Es liegen noch zu wenige Ergebnisse vor. Nach einigen Aufgaben erscheinen hier Ihre Schwachstellen.' }),
    el('div', { className: 'btn-row', style: { marginTop: '10px' } }, [
      button('Lernplan ansehen', { onClick: () => navigate('plan') }),
    ]),
  ]);

  const systemCard = card('System', [
    table(
      ['Bereich', 'Zustand'],
      [
        ['Backend', el('span', {}, [statusDot('ok'), ' läuft'])],
        ['Aufgaben', `${data.jobs.running || 0} laufend, ${data.jobs.queued || 0} wartend, ${data.jobs.failed || 0} fehlgeschlagen`],
        ['Fehler und Warnungen', `${data.events.error || 0} Fehler, ${data.events.warning || 0} Warnungen`],
        ['Letztes Backup', data.last_backup ? formatDate(data.last_backup.created_at) : 'noch keines'],
        ['Letzte Systemprüfung', data.last_diagnostics ? formatDate(data.last_diagnostics) : 'noch keine'],
        ['Letzte Reparatur', data.last_repair ? `${data.last_repair.action} (${data.last_repair.status})` : 'keine'],
      ],
    ),
    el('div', { className: 'btn-row', style: { marginTop: '10px' } }, [
      button('Systemstatus', { onClick: () => navigate('system') }),
      button('Fehlerdiagnose', { onClick: () => navigate('diagnostics') }),
    ]),
  ]);

  const goalsCard = card('Lernziel und Prüfungstermin', [
    el('p', { text: `Tägliches Lernziel: ${data.daily_goal_minutes} Minuten` }),
    el('p', { text: data.exam_date
      ? `Prüfungstermin: ${data.exam_date}`
      : 'Es ist noch kein Prüfungstermin hinterlegt.' }),
    el('div', { className: 'btn-row' }, [
      button('Einstellungen öffnen', { onClick: () => navigate('settings') }),
      button('Lernplan erstellen', { variant: 'primary', onClick: () => navigate('plan') }),
    ]),
  ]);

  body.appendChild(
    el('div', { className: 'grid grid-2' }, [
      activityCard,
      weakCard,
      dueForecast,
      systemCard,
    ]),
  );
  body.appendChild(el('div', { style: { marginTop: '16px' } }, [goalsCard]));

  if (!data.counts.documents) {
    body.appendChild(
      el('div', { style: { marginTop: '16px' } }, [
        card('Erster Schritt: Notizen importieren', [
          el('p', { text:
            'Damit ElektroCoach aus Ihren eigenen Unterlagen lernen kann, importieren Sie zuerst Ihre Notizen. Unterstützt werden PDF-Dateien, Bilder und Scans. Handschriftliche Seiten werden – wenn Gemini eingerichtet ist – über Gemini gelesen und als „unsicher“ markiert, wenn etwas nicht sicher erkennbar ist.' }),
          el('div', { className: 'btn-row' }, [
            button('Zum Dokumentenimport', { variant: 'primary', onClick: () => navigate('documents') }),
            button('Einrichtungsassistent', { onClick: () => navigate('setup') }),
          ]),
        ]),
      ]),
    );
  }
}
