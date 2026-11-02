/** Knowledge base: search, browse, inspect sources and correct entries. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, formatDate, field, input,
  select, textarea, infoBox, table, emptyState,
} from '../ui.js';

export async function renderKnowledge(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Wissensdatenbank' }),
    el('p', { text:
      'Alle erkannten Inhalte aus Ihren Dokumenten – mit Quelle, Seitenzahl und Kennzeichnung unsicher erkannter Stellen. Unsichere Inhalte werden nie als sicher dargestellt.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const searchHost = el('div');
  const reviewHost = el('div');
  const listHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [searchHost, reviewHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [listHost]));

  const query = input({ placeholder: 'Suchbegriff, z. B. Spannungsfall' });
  const subjectFilter = select({ options: [{ label: '– alle –', value: '' }] });

  try {
    const knowledge = await api.get('api/knowledge', { limit: 1 });
    (knowledge.topics || []).forEach((topic) => {
      subjectFilter.appendChild(el('option', { text: topic, attrs: { value: topic } }));
    });
  } catch (error) {
    /* optional */
  }

  searchHost.appendChild(card('Suche', [
    field('Suchbegriff', query, 'Die Suche nutzt die Volltextsuche (FTS5). Kurze Stichwörter liefern die besten Ergebnisse.'),
    field('Fachgebiet', subjectFilter),
    el('div', { className: 'btn-row' }, [
      button('Suchen', {
        variant: 'primary',
        onClick: async () => {
          if (!query.value.trim()) {
            toast('Bitte geben Sie einen Suchbegriff ein.', 'warning');
            return;
          }
          listHost.replaceChildren(spinner('Suche läuft …'));
          try {
            const data = await api.get('api/knowledge/search', {
              q: query.value.trim(),
              subject: subjectFilter.value || undefined,
              limit: 50,
            });
            listHost.replaceChildren(card(`Suchergebnisse (${data.count})`, [
              el('p', { className: 'muted small', text: `Suchverfahren: ${data.engine}` }),
              data.items.length
                ? renderKnowledgeList(data.items)
                : infoBox('Es wurden keine passenden Inhalte gefunden. Versuchen Sie einen anderen Begriff.', 'warning'),
            ]));
          } catch (error) {
            listHost.replaceChildren(errorBox(error));
          }
        },
      }),
      button('Alle anzeigen', { onClick: () => loadAll() }),
    ]),
  ]));

  function renderKnowledgeList(items) {
    return el('div', { className: 'issue-list' }, items.map((item) =>
      el('div', { className: `issue ${item.uncertainty ? 'issue-warning' : 'issue-info'}` }, [
        el('div', { className: 'step-title' }, [
          el('strong', { text: item.title || 'Ohne Titel' }),
          item.uncertainty ? badge('unsichere Erkennung', 'warning') : null,
          badge(item.subject || 'ohne Fachgebiet', 'neutral'),
        ]),
        el('p', { className: 'small', text: (item.content || item.excerpt || '').slice(0, 600) }),
        el('p', { className: 'muted small', text:
          `Quelle: ${item.source_label || item.source || 'unbekannt'} · Seite ${item.page_number ?? '?'} · Qualität ${item.quality ?? '–'} · verarbeitet ${formatDate(item.processed_at || item.created_at)}` }),
        el('div', { className: 'btn-row' }, [
          button('Bearbeiten', {
            className: 'btn-sm',
            onClick: () => openEditor(item),
          }),
        ]),
      ]),
    ));
  }

  const editorHost = el('div');

  async function openEditor(item) {
    let full = item;
    try {
      full = await api.get(`api/knowledge/${item.id}`);
    } catch (error) {
      toast(error.message, 'error');
      return;
    }
    const title = input({ value: full.title || '' });
    const content = textarea({ rows: 8, value: full.content || '' });
    const topic = input({ value: full.topic || '' });
    const uncertainty = el('input', { attrs: { type: 'checkbox', checked: full.uncertainty ? true : undefined } });
    editorHost.replaceChildren(card(`Wissenseintrag ${full.id} bearbeiten`, [
      field('Titel', title),
      field('Inhalt', content, 'Korrigieren Sie hier unleserlich erkannte Stellen. Die Quelle und Seitenzahl bleiben erhalten.'),
      field('Thema', topic),
      el('label', { className: 'checkbox' }, [
        uncertainty,
        el('span', { text: 'Als unsicher erkannt kennzeichnen' }),
      ]),
      el('div', { className: 'btn-row' }, [
        button('Speichern', {
          variant: 'primary',
          onClick: async () => {
            try {
              await api.patch(`api/knowledge/${full.id}`, {
                title: title.value,
                content: content.value,
                topic: topic.value,
                uncertainty: uncertainty.checked,
              });
              toast('Der Wissenseintrag wurde gespeichert.', 'success');
              editorHost.replaceChildren();
              loadAll();
            } catch (error) {
              editorHost.appendChild(errorBox(error));
            }
          },
        }),
        button('Abbrechen', { onClick: () => editorHost.replaceChildren() }),
      ]),
    ]));
    editorHost.scrollIntoView({ behavior: 'smooth' });
  }

  async function loadReview() {
    reviewHost.replaceChildren(spinner('Prüfbedarf wird geladen …'));
    try {
      const data = await api.get('api/documents/pages/review', { limit: 20 });
      reviewHost.replaceChildren(card('Seiten mit unsicherer Erkennung', [
        data.items.length
          ? el('div', { className: 'issue-list' }, data.items.map((page) =>
              el('div', { className: 'issue issue-warning' }, [
                el('strong', { text: `${page.document_name || 'Dokument'} – Seite ${page.page_number}` }),
                el('p', { className: 'small', text: page.text_preview || 'Kein Text erkannt.' }),
                el('p', { className: 'muted small', text: page.review_reason || 'Erkennung unsicher.' }),
                button('Im Dokumentenimport prüfen', {
                  className: 'btn-sm',
                  onClick: () => navigate('documents'),
                }),
              ])))
          : infoBox('Zurzeit sind keine Seiten zur Prüfung markiert.', 'success'),
        el('p', { className: 'muted small', text:
          'Diese Stellen wurden absichtlich nicht als sicher übernommen. Bitte prüfen Sie sie und korrigieren Sie den Text bei Bedarf.' }),
      ]));
    } catch (error) {
      reviewHost.replaceChildren(errorBox(error));
    }
  }

  async function loadAll() {
    listHost.replaceChildren(spinner('Wissensdatenbank wird geladen …'));
    try {
      const data = await api.get('api/knowledge', { limit: 100 });
      listHost.replaceChildren(card(`Wissensdatenbank (${data.total} Einträge)`, [
        data.items.length ? renderKnowledgeList(data.items) : emptyState(
          'Noch keine Inhalte',
          'Importieren Sie zuerst Ihre Notizen im Bereich „Dokumentenimport“.',
          button('Zum Dokumentenimport', { variant: 'primary', onClick: () => navigate('documents') }),
        ),
      ]));
    } catch (error) {
      listHost.replaceChildren(errorBox(error));
    }
  }

  host.appendChild(editorHost);
  loadAll();
  loadReview();
}
