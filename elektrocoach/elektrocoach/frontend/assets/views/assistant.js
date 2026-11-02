/** AI assistant: ask questions, see provider, token use, models and decisions. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, field, input, select,
  infoBox, table, statusDot, formatDate,
} from '../ui.js';

export async function renderAssistant(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'KI-Assistent' }),
    el('p', { text:
      'Stellen Sie fachliche Fragen. Einfache Aufgaben bleiben lokal bei Ollama und übertragen keine Daten nach außen. Für schwierige Fragen und Handschrift wird – nur mit Ihrer Konfiguration und im kostenlosen Kontingent – Gemini verwendet. Kostenpflichtige Anfragen sind ausgeschlossen.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const chatHost = el('div');
  const sideHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [chatHost, sideHost]));

  const useNotes = el('input', { attrs: { type: 'checkbox', checked: true } });
  const prefer = select({
    options: [
      { label: 'Automatisch (empfohlen)', value: 'auto' },
      { label: 'Nur lokal (Ollama)', value: 'ollama' },
      { label: 'Gemini bevorzugen', value: 'gemini' },
    ],
    value: 'auto',
  });
  const questionInput = el('textarea', {
    className: 'input',
    attrs: { rows: 3, placeholder: 'Ihre Frage, z. B.: Wie berechne ich den Spannungsfall bei 25 m Leitungslänge?' },
  });
  const log = el('div', { className: 'chat-log' });

  function appendMessage(role, text, meta) {
    const node = el('div', { className: `chat-message chat-${role}` }, [
      el('div', { className: 'avatar', text: role === 'user' ? 'Ich' : 'EC' }),
      el('div', {}, [
        el('div', { className: 'chat-bubble', text }),
        meta ? el('div', { className: 'chat-meta', text: meta }) : null,
      ]),
    ]);
    log.appendChild(node);
    node.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function ask() {
    const question = questionInput.value.trim();
    if (!question) {
      toast('Bitte geben Sie zuerst eine Frage ein.', 'warning');
      return;
    }
    appendMessage('user', question);
    questionInput.value = '';
    const pending = el('div', { className: 'chat-message chat-ai' }, [
      el('div', { className: 'avatar', text: 'EC' }),
      el('div', { className: 'chat-bubble' }, [spinner('Antwort wird erstellt …')]),
    ]);
    log.appendChild(pending);
    try {
      const response = await api.post('api/ai/ask', {
        question,
        use_notes: useNotes.checked,
        prefer: prefer.value,
      });
      const metaParts = [
        `KI: ${response.provider} (${response.model})`,
        response.cached ? 'aus dem Zwischenspeicher' : null,
        `Token: ${response.tokens.total}`,
        `${response.latency_ms} ms`,
      ].filter(Boolean).join(' · ');
      pending.replaceChildren(
        el('div', { className: 'avatar', text: 'EC' }),
        el('div', {}, [
          el('div', { className: 'chat-bubble', text: response.answer }),
          el('div', { className: 'chat-meta', text: metaParts }),
          response.sources && response.sources.length
            ? el('div', { className: 'chat-meta', text:
                `Verwendete Quellen: ${response.sources.map((s) => `${s.title || 'Notiz'} (${s.source || '?'} S. ${s.page ?? '?'})`).join('; ')}` })
            : el('div', { className: 'chat-meta', text: response.note }),
        ]),
      );
    } catch (error) {
      pending.replaceChildren(
        el('div', { className: 'avatar', text: 'EC' }),
        el('div', {}, [errorBox(error)]),
      );
    }
  }

  questionInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) ask();
  });

  chatHost.appendChild(card('Frage stellen', [
    field('Frage', questionInput, 'Mit Strg+Enter senden Sie die Frage direkt.'),
    el('div', { className: 'grid grid-2' }, [
      field('KI-Auswahl', prefer),
      el('label', { className: 'checkbox' }, [
        useNotes,
        el('span', { text: 'Ausschnitte aus meinen Notizen verwenden' }),
      ]),
    ]),
    el('div', { className: 'btn-row' }, [
      button('Frage senden', { variant: 'primary', onClick: ask }),
      button('Verlauf leeren', { onClick: () => log.replaceChildren() }),
    ]),
    infoBox('Es werden nur die unten aufgeführten Ausschnitte an eine externe KI übertragen, niemals die gesamte Wissensdatenbank und niemals Ihr API-Schlüssel.'),
  ]));

  const transcriptHost = el('div', { style: { marginTop: '16px' } }, [log]);
  chatHost.appendChild(transcriptHost);

  // -- side panel ------------------------------------------------------------

  const statusHost = el('div');
  const usageHost = el('div');
  const decisionsHost = el('div');
  const modelsHost = el('div');
  sideHost.appendChild(statusHost);
  sideHost.appendChild(el('div', { style: { marginTop: '16px' } }, [usageHost]));
  sideHost.appendChild(el('div', { style: { marginTop: '16px' } }, [modelsHost]));
  sideHost.appendChild(el('div', { style: { marginTop: '16px' } }, [decisionsHost]));

  async function loadStatus() {
    statusHost.replaceChildren(spinner('KI-Status wird geladen …'));
    try {
      const status = await api.get('api/ai/status');
      statusHost.replaceChildren(card('KI-Status', [
        table(['Dienst', 'Zustand'], [
          ['Ollama', el('span', {}, [
            statusDot(status.ollama && status.ollama.available ? 'ok' : 'warning'),
            ` ${status.ollama ? (status.ollama.available ? 'erreichbar' : 'nicht erreichbar') : 'nicht eingebunden'}`,
          ])],
          ['Modell (lokal)', (status.ollama && status.ollama.configured_model) || '–'],
          ['Gemini', el('span', {}, [
            statusDot(status.gemini && status.gemini.available ? 'ok' : 'disabled'),
            ` ${status.gemini ? (status.gemini.available ? 'erreichbar' : 'nicht verfügbar') : 'nicht aktiviert'}`,
          ])],
          ['Modell (Gemini)', (status.gemini && status.gemini.model) || '–'],
        ]),
        el('div', { className: 'btn-row', style: { marginTop: '10px' } }, [
          button('Status erneut prüfen', { className: 'btn-sm', onClick: loadStatus }),
          button('Modell entladen', {
            className: 'btn-sm',
            onClick: async () => {
              try {
                const response = await api.post('api/ai/models/unload');
                toast(response.message, response.unloaded ? 'success' : 'warning');
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
        ]),
      ]));
    } catch (error) {
      statusHost.replaceChildren(errorBox(error));
    }
  }

  async function loadUsage() {
    usageHost.replaceChildren(spinner('Verbrauch wird geladen …'));
    try {
      const usage = await api.get('api/ai/usage');
      const today = usage.gemini_today || {};
      usageHost.replaceChildren(card('Verbrauch und Kontingent', [
        el('p', { text:
          `Gemini heute: ${today.requests_used || 0} von ${today.budget || 0} Anfragen (${today.remaining || 0} übrig).` }),
        el('p', { className: 'muted small', text: usage.note }),
        el('p', { className: 'muted small', text:
          `Zwischenspeicher: ${usage.cache.entries} Einträge, ${usage.cache.hits} Treffer, ${usage.cache.misses} Fehlgriffe.` }),
        table(
          ['Tag', 'Dienst', 'Anfragen', 'Fehler', 'Token'],
          (usage.summary_7d || []).map((row) => [
            row.day, row.provider, String(row.requests), String(row.failures),
            String(row.total_tokens || 0),
          ]),
        ),
      ]));
    } catch (error) {
      usageHost.replaceChildren(errorBox(error));
    }
  }

  async function loadModels() {
    modelsHost.replaceChildren(spinner('Modelle werden geladen …'));
    try {
      const data = await api.get('api/ai/models');
      const localModels = (data.ollama.models || []).map((model) => model.name);
      const geminiModels = (data.gemini.models || []).map((model) => model.name);
      modelsHost.replaceChildren(card('Verfügbare Modelle', [
        el('p', { className: 'small', text: `Lokal (Ollama): ${localModels.length ? localModels.join(', ') : 'keine'}` }),
        data.ollama.error ? infoBox(`Ollama: ${data.ollama.error}`, 'warning') : null,
        el('p', { className: 'small', text: `Gemini: ${geminiModels.length ? geminiModels.slice(0, 8).join(', ') : (data.gemini.error || 'nicht abgefragt')}` }),
        el('p', { className: 'muted small', text:
          'Die Gemini-Modellliste wird live von Google geladen. So verwenden Sie nie einen veralteten Modellnamen.' }),
        el('div', { className: 'btn-row' }, [
          button('Liste neu laden', {
            className: 'btn-sm',
            onClick: () => loadModels(),
          }),
          button('Modell laden', {
            className: 'btn-sm',
            onClick: async () => {
              const name = window.prompt('Name des Ollama-Modells (z. B. qwen2.5:1.5b):', 'qwen2.5:1.5b');
              if (!name) return;
              try {
                const response = await api.post('api/ai/models/pull', { model: name });
                toast(response.message, 'info', 9000);
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
        ]),
      ]));
    } catch (error) {
      modelsHost.replaceChildren(errorBox(error));
    }
  }

  async function loadDecisions() {
    decisionsHost.replaceChildren(spinner('Entscheidungen werden geladen …'));
    try {
      const data = await api.get('api/ai/decisions', { limit: 10 });
      decisionsHost.replaceChildren(card('Warum welche KI?', [
        el('p', { className: 'muted small', text: data.explanation }),
        data.items.length
          ? table(
              ['Zeit', 'Aufgabe', 'Gewählt', 'Grund'],
              data.items.map((item) => [
                formatDate(item.at),
                item.task || '–',
                item.provider || '–',
                item.reason || '–',
              ]),
            )
          : el('p', { className: 'muted small', text: 'Noch keine KI-Aufgaben ausgeführt.' }),
      ]));
    } catch (error) {
      decisionsHost.replaceChildren(errorBox(error));
    }
  }

  loadStatus();
  loadUsage();
  loadModels();
  loadDecisions();
}
