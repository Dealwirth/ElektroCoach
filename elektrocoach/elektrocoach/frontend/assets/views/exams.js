/** Exams: create, run and evaluate exam simulations with a time limit. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, formatDate, formatDuration,
  field, input, select, infoBox, progressBar, table, percent,
} from '../ui.js';

let timerHandle = null;

function clearTimer() {
  if (timerHandle) {
    clearInterval(timerHandle);
    timerHandle = null;
  }
}

function renderAnalysis(analysis) {
  if (!analysis) return el('p', { className: 'muted', text: 'Keine Auswertung vorhanden.' });
  return el('div', {}, [
    el('div', { className: 'alert alert-info', text: analysis.disclaimer }),
    el('div', { className: 'grid grid-4', style: { marginBottom: '14px' } }, [
      el('div', { className: 'stat' }, [
        el('div', { className: 'stat-value', text: `${analysis.percent} %` }),
        el('div', { className: 'stat-label', text: 'Erreichte Punkte' }),
      ]),
      el('div', { className: 'stat' }, [
        el('div', { className: 'stat-value', text: analysis.grade }),
        el('div', { className: 'stat-label', text: 'Bewertung' }),
      ]),
      el('div', { className: 'stat' }, [
        el('div', { className: 'stat-value', text: analysis.passed ? 'bestanden' : 'nicht bestanden' }),
        el('div', { className: 'stat-label', text: 'Ergebnis (Grenze 50 %)' }),
      ]),
      el('div', { className: 'stat' }, [
        el('div', { className: 'stat-value', text: String(analysis.unanswered) }),
        el('div', { className: 'stat-label', text: 'Nicht beantwortet' }),
      ]),
    ]),
    el('h4', { text: 'Ergebnis nach Fachgebiet' }),
    table(
      ['Fachgebiet', 'Punkte', 'Möglich', 'Anteil'],
      (analysis.by_subject || []).map((entry) => [
        entry.name, String(entry.awarded), String(entry.possible), percent(entry.ratio),
      ]),
    ),
    (analysis.weaknesses || []).length
      ? el('div', { style: { marginTop: '14px' } }, [
          el('h4', { text: 'Schwachstellen' }),
          el('div', { className: 'issue-list' }, analysis.weaknesses.map((weak) =>
            el('div', { className: 'issue issue-warning' }, [
              el('strong', { text: weak.name }),
              el('div', { className: 'small', text: `Anteil ${percent(weak.ratio)}` }),
            ]))),
        ])
      : null,
    (analysis.recommendations || []).length
      ? el('div', { style: { marginTop: '14px' } }, [
          el('h4', { text: 'Empfehlungen' }),
          el('ul', {}, analysis.recommendations.map((text) => el('li', { text }))),
        ])
      : null,
  ]);
}

export async function renderExams(container, { navigate }) {
  clearTimer();
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Prüfungen' }),
    el('p', { text:
      'Stellen Sie Prüfungssimulationen aus Ihren Aufgaben zusammen – mit Zeitlimit, Punkteverteilung und Auswertung. Eine Simulation entspricht nicht einer offiziellen IHK-Prüfung.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const createHost = el('div');
  const listHost = el('div');
  const runHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [createHost, listHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [runHost]));

  const timeLimit = input({ type: 'number', value: '90', min: '5', max: '600' });
  const title = input({ placeholder: 'z. B. Prüfungssimulation Januar' });

  createHost.appendChild(card('Neue Prüfungssimulation', [
    field('Bezeichnung', title, 'Optional. Ohne Angabe wird ein Datum verwendet.'),
    field('Zeitlimit in Minuten', timeLimit, 'Üblich sind 90 bis 120 Minuten.'),
    infoBox('Die Aufgaben werden automatisch nach einer Gewichtung der Fachgebiete ausgewählt. Nicht jede Fachgebiet wird immer abgedeckt, wenn zu wenige Aufgaben vorhanden sind.'),
    el('div', { className: 'btn-row' }, [
      button('Prüfung erstellen', {
        variant: 'primary',
        onClick: async (event) => {
          event.target.disabled = true;
          try {
            const exam = await api.post('api/exams', {
              title: title.value || null,
              time_limit_minutes: Number(timeLimit.value) || 90,
            });
            toast('Die Prüfung wurde erstellt.', 'success');
            loadExams();
            openExam(exam.id);
          } catch (error) {
            createHost.appendChild(errorBox(error));
          } finally {
            event.target.disabled = false;
          }
        },
      }),
    ]),
  ]));

  async function loadExams() {
    listHost.replaceChildren(spinner('Prüfungen werden geladen …'));
    try {
      const data = await api.get('api/exams');
      listHost.replaceChildren(card('Vorhandene Prüfungen', [
        data.items.length
          ? table(
              ['ID', 'Bezeichnung', 'Status', 'Punkte', 'Erstellt', 'Aktionen'],
              data.items.map((exam) => [
                String(exam.id),
                exam.title,
                exam.status,
                exam.max_score ? `${exam.total_score} / ${exam.max_score}` : '–',
                formatDate(exam.created_at),
                el('span', { className: 'btn-row' }, [
                  button('Öffnen', { className: 'btn-sm', onClick: () => openExam(exam.id) }),
                  button('Löschen', {
                    variant: 'ghost',
                    className: 'btn-sm',
                    onClick: async () => {
                      if (!window.confirm('Diese Prüfung wirklich löschen?')) return;
                      try {
                        await api.del(`api/exams/${exam.id}`);
                        loadExams();
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                ]),
              ]),
            )
          : el('p', { className: 'muted', text: 'Es sind noch keine Prüfungen vorhanden.' }),
      ]));
    } catch (error) {
      listHost.replaceChildren(errorBox(error));
    }
  }

  async function openExam(examId) {
    clearTimer();
    runHost.replaceChildren(spinner('Prüfung wird geladen …'));
    let exam;
    try {
      exam = await api.get(`api/exams/${examId}`);
    } catch (error) {
      runHost.replaceChildren(errorBox(error));
      return;
    }

    if (exam.status === 'finished') {
      runHost.replaceChildren(card(exam.title, [
        renderAnalysis(exam.analysis),
        el('div', { className: 'btn-row' }, [
          button('Zur Liste', { onClick: () => { runHost.replaceChildren(); loadExams(); } }),
          button('Neue Prüfung', { variant: 'primary', onClick: () => { runHost.replaceChildren(); } }),
        ]),
      ]));
      return;
    }

    if (exam.status === 'created') {
      runHost.replaceChildren(card(exam.title, [
        el('p', { text: `Diese Prüfung enthält ${exam.items.length} Aufgaben und hat ein Zeitlimit von ${formatDuration(exam.time_limit_seconds)}.` }),
        el('p', { className: 'muted small', text: exam.disclaimer }),
        el('div', { className: 'btn-row' }, [
          button('Prüfung starten', {
            variant: 'primary',
            onClick: async () => {
              try {
                await api.post(`api/exams/${examId}/start`);
                openExam(examId);
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
        ]),
      ]));
      return;
    }

    // Running exam.
    const remaining = el('span', { className: 'badge badge-info', text: formatDuration(exam.remaining_seconds) });
    const itemHost = el('div');
    let currentIndex = 0;

    const renderItem = () => {
      const item = exam.items[currentIndex];
      if (!item) {
        itemHost.replaceChildren(infoBox('Alle Aufgaben wurden bearbeitet. Klicken Sie auf „Prüfung abgeben“.', 'info'));
        return;
      }
      const question = item.question;
      const payload = question.payload || {};
      let control;
      if (question.type === 'multiple_choice') {
        control = el('div', {}, (payload.options || []).map((option, index) =>
          el('label', { className: 'checkbox' }, [
            el('input', { attrs: { type: 'radio', name: 'exam-mc', value: String(index), checked: item.answer === String(index) ? true : undefined } }),
            el('span', { text: `${String.fromCharCode(65 + index)}) ${option}` }),
          ])));
      } else if (question.type === 'numeric') {
        control = el('input', { className: 'input', attrs: { id: 'exam-answer', value: item.answer || '', placeholder: payload.unit ? `Ergebnis in ${payload.unit}` : 'Ergebnis' } });
      } else if (question.type === 'matching') {
        const left = payload.left || [];
        const right = payload.right || [];
        control = el('div', {}, left.map((entry, index) =>
          el('label', { className: 'field' }, [
            el('span', { className: 'field-label', text: `${index + 1}. ${entry}` }),
            el('select', { className: 'input', attrs: { 'data-left': String(index) } },
              [{ label: '– bitte wählen –', value: '' }].concat(
                right.map((r, ri) => ({ label: `${String.fromCharCode(65 + ri)}) ${r}`, value: String(ri) })),
              )),
          ])));
      } else {
        control = el('textarea', { className: 'input', attrs: { id: 'exam-answer', rows: 6, placeholder: 'Ihre Antwort' }, text: item.answer || '' });
      }

      itemHost.replaceChildren(card(`Aufgabe ${currentIndex + 1} von ${exam.items.length}`, [
        el('p', { className: 'muted small', text: `${question.subject || '–'} · ${question.topic || '–'} · ${item.max_points} Punkte` }),
        el('p', { className: 'prompt', text: question.prompt }),
        control,
        el('div', { className: 'btn-row' }, [
          button('Antwort speichern', {
            variant: 'primary',
            onClick: async (event) => {
              let answer = '';
              if (question.type === 'multiple_choice') {
                const checked = document.querySelector('input[name="exam-mc"]:checked');
                answer = checked ? checked.value : '';
              } else if (question.type === 'matching') {
                answer = Array.from(document.querySelectorAll('select[data-left]'))
                  .map((node) => `${node.dataset.left}:${node.value === '' ? -1 : node.value}`)
                  .join(';');
              } else {
                const node = document.getElementById('exam-answer');
                answer = node ? node.value : '';
              }
              event.target.disabled = true;
              try {
                await api.post('api/exams/answer', { item_id: item.item_id, answer });
                toast('Die Antwort wurde gespeichert.', 'success');
                currentIndex += 1;
                renderItem();
              } catch (error) {
                itemHost.appendChild(errorBox(error));
              } finally {
                event.target.disabled = false;
              }
            },
          }),
          button('Weiter ohne Antwort', { onClick: () => { currentIndex += 1; renderItem(); } }),
          button('Zurück', { onClick: () => { currentIndex = Math.max(0, currentIndex - 1); renderItem(); } }),
        ]),
      ]));
    };

    runHost.replaceChildren(card(exam.title, [
      el('div', { className: 'btn-row', style: { marginBottom: '10px' } }, [
        el('span', { text: 'Verbleibende Zeit: ' }),
        remaining,
        el('span', { className: 'muted small', text: ' (wird automatisch aktualisiert)' }),
      ]),
      progressBar(exam.items.filter((i) => i.answer).length / Math.max(1, exam.items.length)),
      el('p', { className: 'muted small', text:
        `${exam.items.filter((i) => i.answer).length} von ${exam.items.length} Aufgaben beantwortet.` }),
      itemHost,
      el('div', { className: 'btn-row', style: { marginTop: '12px' } }, [
        button('Prüfung abgeben', {
          variant: 'danger',
          onClick: async () => {
            if (!window.confirm('Prüfung jetzt abgeben? Nicht beantwortete Aufgaben zählen als falsch.')) return;
            try {
              await api.post(`api/exams/${examId}/finish`);
              clearTimer();
              openExam(examId);
              loadExams();
            } catch (error) {
              toast(error.message, 'error');
            }
          },
        }),
      ]),
    ]));

    renderItem();

    // Local countdown, re-synchronised from the server every 30 s.
    let seconds = exam.remaining_seconds || 0;
    timerHandle = setInterval(async () => {
      seconds = Math.max(0, seconds - 1);
      remaining.textContent = formatDuration(seconds);
      if (seconds === 0) {
        clearTimer();
        toast('Die Zeit ist abgelaufen. Die Prüfung wird abgegeben.', 'warning');
        try {
          await api.post(`api/exams/${examId}/finish`);
          openExam(examId);
        } catch (error) {
          /* the user can still submit manually */
        }
      }
    }, 1000);
  }

  loadExams();
  window.addEventListener('hashchange', clearTimer, { once: true });
}
