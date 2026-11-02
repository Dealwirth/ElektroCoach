/**
 * Learning view: answer due cards, see the immediate feedback, solution,
 * explanation, sources and the next review date.
 */

import { api } from '../api.js';
import {
  el, card, button, spinner, errorBox, toast, formatDate, percent, progressBar,
  infoBox,
} from '../ui.js';

const state = { queue: [], index: 0 };

function renderQuestionInput(question) {
  const type = question.type;
  const payload = question.payload || {};

  if (type === 'multiple_choice') {
    const options = payload.options || [];
    return el('div', { className: 'options' }, options.map((option, index) =>
      el('label', { className: 'checkbox' }, [
        el('input', { attrs: { type: 'radio', name: 'mc', value: String(index) } }),
        el('span', { text: `${String.fromCharCode(65 + index)}) ${option}` }),
      ]),
    ));
  }
  if (type === 'numeric') {
    return el('label', { className: 'field' }, [
      el('span', { className: 'field-label', text: `Ergebnis${payload.unit ? ` in ${payload.unit}` : ''}` }),
      el('input', { className: 'input', attrs: { id: 'answer-input', placeholder: 'z. B. 12,5', inputmode: 'decimal' } }),
      el('span', { className: 'field-hint', text: 'Geben Sie das Ergebnis mit Einheit an, z. B. „230 V“ oder „0,5 kV“. Die Bewertung rechnet Einheiten um.' }),
    ]);
  }
  if (type === 'matching') {
    const left = payload.left || [];
    const right = payload.right || [];
    return el('div', {}, [
      infoBox('Ordnen Sie jedem Begriff links die passende Erläuterung rechts zu.'),
      ...left.map((item, index) =>
        el('label', { className: 'field' }, [
          el('span', { className: 'field-label', text: `${index + 1}. ${item}` }),
          el('select', { className: 'input', attrs: { 'data-left': String(index) } },
            [{ label: '– bitte wählen –', value: '' }].concat(
              right.map((entry, rightIndex) => ({
                label: `${String.fromCharCode(65 + rightIndex)}) ${entry}`,
                value: String(rightIndex),
              })),
            )),
        ])),
    ]);
  }
  if (type === 'cloze') {
    return el('label', { className: 'field' }, [
      el('span', { className: 'field-label', text: 'Ergänzung' }),
      el('input', { className: 'input', attrs: { id: 'answer-input', placeholder: 'Fehlender Begriff' } }),
      el('span', { className: 'field-hint', text: 'Geben Sie die Lösung für die Lücke ein.' }),
    ]);
  }
  return el('label', { className: 'field' }, [
    el('span', { className: 'field-label', text: 'Ihre Antwort' }),
    el('textarea', { className: 'input', attrs: { id: 'answer-input', rows: 7, placeholder: 'Formulieren Sie Ihre Antwort in eigenen Worten.' } }),
    el('span', { className: 'field-hint', text: 'Bei Freitextaufgaben wird Ihre Antwort fachlich bewertet. Sinngemäß richtige Formulierungen gelten als richtig.' }),
  ]);
}

function collectAnswer(question) {
  const type = question.type;
  if (type === 'multiple_choice') {
    const checked = document.querySelector('input[name="mc"]:checked');
    return checked ? checked.value : '';
  }
  if (type === 'matching') {
    const selects = Array.from(document.querySelectorAll('select[data-left]'));
    return selects.map((node) => `${node.dataset.left}:${node.value === '' ? -1 : node.value}`).join(';');
  }
  const input = document.getElementById('answer-input');
  return input ? input.value : '';
}

function renderResult(result) {
  const grading = result.grading || {};
  const tone = grading.is_correct ? 'success' : 'error';
  const parts = [
    el('div', { className: `alert alert-${tone}` }, [
      el('strong', { text: grading.is_correct ? 'Richtig. ' : 'Nicht richtig. ' }),
      el('span', { text: `Erreichte Punkte: ${grading.score} von ${grading.max_score}.` }),
      el('div', { className: 'small', text: `Bewertungsmethode: ${grading.method}` }),
    ]),
    el('p', { text: grading.feedback }),
  ];

  const solution = result.solution || {};
  if (solution.model_answer) {
    parts.push(el('div', {}, [
      el('h4', { text: 'Musterlösung' }),
      el('p', { text: solution.model_answer }),
    ]));
  }
  if (solution.steps) {
    parts.push(el('div', {}, [el('h4', { text: 'Rechenweg' }), el('p', { text: solution.steps })]));
  }
  if (Array.isArray(solution.keywords) && solution.keywords.length) {
    parts.push(el('p', { className: 'muted small', text:
      `Erwartete Fachbegriffe: ${solution.keywords.map((k) => (Array.isArray(k) ? k[0] : k)).join(', ')}` }));
  }
  if (result.explanation) {
    parts.push(el('div', {}, [el('h4', { text: 'Erklärung' }), el('p', { text: result.explanation })]));
  }
  if (result.sources && result.sources.length) {
    parts.push(el('div', {}, [
      el('h4', { text: 'Quellen aus Ihren Notizen' }),
      el('ul', {}, result.sources.map((source) =>
        el('li', { text: `${source.title || 'Notiz'} – ${source.source || 'unbekannt'}, Seite ${source.page ?? '?'}${source.uncertainty ? ' (unsichere Erkennung)' : ''}` }))),
    ]));
  }
  if (result.schedule) {
    parts.push(el('p', { className: 'muted small', text:
      `Nächste Wiederholung: ${formatDate(result.schedule.due_at)} (${result.schedule.description})` }));
  }
  if (result.mastery) {
    parts.push(el('p', { className: 'muted small', text:
      `Themenstand „${result.mastery.topic}“: ${percent(result.mastery.mastery)} aus ${result.mastery.attempts} Versuchen.` }));
  }
  return el('div', {}, parts);
}

export async function renderLearning(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Lernen' }),
    el('p', { text:
      'Beantworten Sie fällige Wiederholungen. Nach jeder Antwort erhalten Sie sofort eine Bewertung, die Musterlösung, eine Erklärung und die Quellen aus Ihren Notizen.' }),
  ]));

  const body = el('div');
  container.appendChild(body);
  body.appendChild(spinner('Lernkarten werden geladen …'));

  let data;
  try {
    data = await api.get('api/learning/due', { limit: 30 });
  } catch (error) {
    body.replaceChildren(errorBox(error));
    return;
  }

  state.queue = data.items || [];
  state.index = 0;
  body.replaceChildren();

  if (!state.queue.length) {
    body.appendChild(card('Zurzeit ist nichts fällig', [
      el('p', { text:
        'Es sind keine Wiederholungen offen. Sie können neue Aufgaben erstellen oder den Lernplan ansehen.' }),
      el('div', { className: 'btn-row' }, [
        button('Aufgaben erstellen', { variant: 'primary', onClick: () => navigate('questions') }),
        button('Lernplan ansehen', { onClick: () => navigate('plan') }),
        button('Lernstatistik', { onClick: () => navigate('dashboard') }),
      ]),
    ]));
    return;
  }

  const progressHost = el('div');
  const cardHost = el('div');
  body.appendChild(el('div', { className: 'grid grid-2' }, [progressHost, cardHost]));

  const renderCard = () => {
    const item = state.queue[state.index];
    if (!item) {
      progressHost.replaceChildren(card('Runde abgeschlossen', [
        el('p', { text: 'Sie haben alle fälligen Karten dieser Runde bearbeitet.' }),
        el('div', { className: 'btn-row' }, [
          button('Neu laden', {
            variant: 'primary',
            onClick: () => renderLearning(container, { navigate }),
          }),
          button('Lernplan ansehen', { onClick: () => navigate('plan') }),
        ]),
      ]));
      cardHost.replaceChildren();
      return;
    }
    const question = item.question;

    progressHost.replaceChildren(card('Fortschritt', [
      el('p', { text: `Karte ${state.index + 1} von ${state.queue.length}` }),
      progressBar(state.index / state.queue.length),
      el('p', { className: 'muted small', text:
        `${question.subject || 'Ohne Fachgebiet'} · ${question.topic || 'Allgemein'} · Schwierigkeit ${question.difficulty}/3` }),
      el('p', { className: 'muted small', text: `Fällig seit ${formatDate(item.due_at)}` }),
    ]));

    const answerHost = el('div');
    answerHost.appendChild(renderQuestionInput(question));
    cardHost.replaceChildren(card('Aufgabe', [
      el('p', { className: 'prompt', text: question.prompt }),
      answerHost,
      el('div', { className: 'btn-row' }, [
        button('Antwort prüfen', {
          variant: 'primary',
          onClick: async (event) => {
            const answer = collectAnswer(question);
            if (!answer || !answer.trim()) {
              toast('Bitte geben Sie zuerst eine Antwort ein.', 'warning');
              return;
            }
            event.target.disabled = true;
            const started = Date.now();
            try {
              const result = await api.post(`api/questions/${question.id}/answer`, {
                answer,
                use_ai: true,
                duration_ms: Date.now() - started,
              });
              answerHost.replaceChildren(renderResult(result));
              event.target.replaceWith(
                button('Nächste Karte', {
                  variant: 'primary',
                  onClick: () => { state.index += 1; renderCard(); },
                }),
              );
            } catch (error) {
              event.target.disabled = false;
              answerHost.replaceChildren(errorBox(error));
            }
          },
        }),
        button('Überspringen', {
          onClick: () => { state.index += 1; renderCard(); },
        }),
      ]),
    ]));

    const input = cardHost.querySelector('#answer-input');
    if (input) input.focus();
  };

  renderCard();
}
