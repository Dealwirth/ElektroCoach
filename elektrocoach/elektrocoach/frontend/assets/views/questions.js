/** Questions: browse, create, generate and delete tasks. */

import { api } from '../api.js';
import {
  el, card, badge, button, table, spinner, errorBox, toast, formatDate, field,
  input, select, textarea, infoBox, progressBar,
} from '../ui.js';

const TYPE_LABELS = {
  multiple_choice: 'Auswahlaufgabe',
  freetext: 'Freitext',
  numeric: 'Rechenaufgabe',
  matching: 'Zuordnung',
  cloze: 'Lückentext',
  error_analysis: 'Fehleranalyse',
  circuit_analysis: 'Schaltungsanalyse',
  practical: 'Praxissituation',
  exam_question: 'Prüfungsfrage',
};

export async function renderQuestions(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Aufgaben' }),
    el('p', { text:
      'Erstellen und verwalten Sie Aufgaben. Rechenaufgaben, Lückentexte und Zuordnungen funktionieren ohne KI. Für KI-generierte Aufgaben wird bevorzugt das lokale Modell verwendet.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const generationHost = el('div');
  const listHost = el('div');
  const manualHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [generationHost, manualHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [listHost]));

  let taxonomy = { subjects: [], question_types: [], difficulty_labels: {} };
  try {
    taxonomy = await api.get('api/learning/taxonomy');
  } catch (error) {
    /* keep defaults */
  }

  const subjectOptions = [{ label: '– alle Fachgebiete –', value: '' }]
    .concat(taxonomy.subjects.map((s) => ({ label: s, value: s })));

  // -- generation ------------------------------------------------------------
  const generateSubject = select({ options: subjectOptions });
  const generateCount = input({ type: 'number', value: '6', min: '1', max: '30' });
  const generateUseAi = el('input', { attrs: { type: 'checkbox', checked: true } });
  const jobStatus = el('div');

  generationHost.appendChild(card('Aufgaben erstellen', [
    field('Fachgebiet', generateSubject),
    field('Anzahl', generateCount, 'Rechenaufgaben, Lückentexte und Zuordnungen entstehen immer. KI-Aufgaben zusätzlich, wenn ein Modell verfügbar ist.'),
    el('label', { className: 'checkbox' }, [
      generateUseAi,
      el('span', { text: 'Zusätzlich KI-Aufgaben erzeugen (Ollama bevorzugt)' }),
    ]),
    el('div', { className: 'btn-row' }, [
      button('Aufgaben erzeugen', {
        variant: 'primary',
        onClick: async (event) => {
          event.target.disabled = true;
          jobStatus.replaceChildren(spinner('Auftrag wird gestartet …'));
          try {
            const response = await api.post('api/questions/generate', {
              subject: generateSubject.value || null,
              count: Number(generateCount.value) || 5,
              use_ai: generateUseAi.checked,
            });
            jobStatus.replaceChildren(infoBox(response.message));
            pollJob(response.job_id, jobStatus, () => loadQuestions());
          } catch (error) {
            jobStatus.replaceChildren(errorBox(error));
          } finally {
            event.target.disabled = false;
          }
        },
      }),
    ]),
    jobStatus,
  ]));

  // -- manual creation -------------------------------------------------------
  const manualType = select({
    options: taxonomy.question_types.map((t) => ({ label: TYPE_LABELS[t] || t, value: t })),
    value: 'freetext',
  });
  const manualSubject = select({ options: subjectOptions });
  const manualTopic = input({ placeholder: 'z. B. Spannungsfall' });
  const manualPrompt = textarea({ rows: 4, placeholder: 'Aufgabenstellung' });
  const manualPayload = textarea({ rows: 3, placeholder: 'Zusatzdaten als JSON (optional)' });
  const manualSolution = textarea({ rows: 5, placeholder: 'Lösung als JSON' });
  const manualHost2 = el('div');

  const solutionHelp = el('p', { className: 'muted small', text:
    'Lösung je Typ: Auswahlaufgabe {"correct_index": 1, "max_points": 1}; Freitext {"model_answer": "...", "keywords": ["..."], "max_points": 4}; Rechenaufgabe {"expected": 230, "unit": "V", "max_points": 2}.' });

  manualHost.appendChild(card('Aufgabe manuell anlegen', [
    field('Typ', manualType),
    field('Fachgebiet', manualSubject),
    field('Thema', manualTopic),
    field('Aufgabenstellung', manualPrompt),
    field('Zusatzdaten (JSON)', manualPayload),
    field('Lösung (JSON)', manualSolution),
    solutionHelp,
    manualHost2,
    el('div', { className: 'btn-row' }, [
      button('Aufgabe speichern', {
        variant: 'primary',
        onClick: async (event) => {
          manualHost2.replaceChildren();
          let payload = {};
          let solution = {};
          try {
            if (manualPayload.value.trim()) payload = JSON.parse(manualPayload.value);
          } catch (error) {
            manualHost2.replaceChildren(infoBox('Die Zusatzdaten sind kein gültiges JSON.', 'error'));
            return;
          }
          try {
            if (manualSolution.value.trim()) solution = JSON.parse(manualSolution.value);
          } catch (error) {
            manualHost2.replaceChildren(infoBox('Die Lösung ist kein gültiges JSON.', 'error'));
            return;
          }
          event.target.disabled = true;
          try {
            await api.post('api/questions', {
              type: manualType.value,
              prompt: manualPrompt.value,
              subject: manualSubject.value || null,
              topic: manualTopic.value || null,
              payload,
              solution,
            });
            toast('Die Aufgabe wurde gespeichert.', 'success');
            manualPrompt.value = '';
            manualSolution.value = '';
            manualPayload.value = '';
            loadQuestions();
          } catch (error) {
            manualHost2.replaceChildren(errorBox(error));
          } finally {
            event.target.disabled = false;
          }
        },
      }),
    ]),
  ]));

  // -- list ------------------------------------------------------------------
  const filterSubject = select({
    options: subjectOptions,
    onChange: () => loadQuestions(),
  });

  async function loadQuestions() {
    listHost.replaceChildren(spinner('Aufgaben werden geladen …'));
    try {
      const data = await api.get('api/questions', {
        subject: filterSubject.value || undefined,
        limit: 100,
      });
      listHost.replaceChildren(card('Vorhandene Aufgaben', [
        el('div', { className: 'btn-row', style: { marginBottom: '10px' } }, [
          field('Nach Fachgebiet filtern', filterSubject),
        ]),
        data.items.length
          ? table(
              ['ID', 'Typ', 'Fachgebiet', 'Thema', 'Schwierigkeit', 'Erstellt', 'Statistik', 'Aktionen'],
              data.items.map((question) => [
                String(question.id),
                TYPE_LABELS[question.type] || question.type,
                question.subject || '–',
                question.topic || '–',
                String(question.difficulty ?? '–'),
                formatDate(question.created_at),
                question.times_served !== undefined
                  ? `${question.times_correct || 0}/${question.times_served || 0}`
                  : '–',
                button('Löschen', {
                  variant: 'ghost',
                  className: 'btn-sm',
                  onClick: async () => {
                    if (!window.confirm('Diese Aufgabe wirklich löschen?')) return;
                    try {
                      await api.del(`api/questions/${question.id}`);
                      toast('Die Aufgabe wurde gelöscht.', 'success');
                      loadQuestions();
                    } catch (error) {
                      toast(error.message, 'error');
                    }
                  },
                }),
              ]),
            )
          : el('p', { className: 'muted', text: 'Es sind noch keine Aufgaben vorhanden.' }),
        el('p', { className: 'muted small', text: `${data.total} Aufgabe(n) insgesamt.` }),
      ]));
    } catch (error) {
      listHost.replaceChildren(errorBox(error));
    }
  }

  function pollJob(jobId, target, onDone) {
    let attempts = 0;
    const timer = setInterval(async () => {
      attempts += 1;
      try {
        const job = await api.get(`api/questions/generate/${jobId}`);
        const progress = job.progress || 0;
        target.replaceChildren(
          el('div', {}, [
            progressBar(progress),
            el('p', { className: 'muted small', text: job.message || `Status: ${job.status}` }),
          ]),
        );
        if (job.status === 'done') {
          clearInterval(timer);
          const created = job.result && job.result.total ? job.result.total : 0;
          target.replaceChildren(infoBox(
            `Fertig: ${created} Aufgabe(n) wurden erstellt und in den Lernplan aufgenommen.`,
            'success',
          ));
          if (onDone) onDone();
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          clearInterval(timer);
          target.replaceChildren(infoBox(
            `Die Erzeugung ist fehlgeschlagen: ${job.error || 'unbekannter Grund'}`,
            'error',
          ));
        }
      } catch (error) {
        clearInterval(timer);
        target.replaceChildren(errorBox(error));
      }
      if (attempts > 300) clearInterval(timer);
    }, 2000);
  }

  loadQuestions();
}
