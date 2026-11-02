/** Document import: upload, watch progress, review pages, manage documents. */

import { api, downloadBinary } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, formatBytes, formatDate,
  field, input, select, infoBox, table, progressBar, textarea, statusDot,
} from '../ui.js';

let pollHandle = null;

export async function renderDocuments(container, { navigate }) {
  if (pollHandle) clearInterval(pollHandle);
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Dokumentenimport' }),
    el('p', { text:
      'Importieren Sie PDF-Dateien, Fotos und Scans Ihrer Notizen. Gedruckter Text wird lokal erkannt. Handschriftliche Seiten werden – wenn Gemini eingerichtet ist – über Gemini gelesen und unsicher erkannte Stellen ausdrücklich markiert.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const uploadHost = el('div');
  const jobsHost = el('div');
  const reviewHost = el('div');
  const listHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [uploadHost, jobsHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [reviewHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [listHost]));

  const subjectSelect = select({ options: [{ label: '– automatisch erkennen –', value: '' }] });
  try {
    const taxonomy = await api.get('api/learning/taxonomy');
    taxonomy.subjects.forEach((subject) => {
      subjectSelect.appendChild(el('option', { text: subject, attrs: { value: subject } }));
    });
  } catch (error) {
    /* optional */
  }

  const visionToggle = el('input', { attrs: { type: 'checkbox', checked: true } });
  const fileInput = el('input', {
    attrs: { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff' },
  });
  const uploadStatus = el('div');

  async function uploadFiles(files) {
    const list = Array.from(files || []);
    if (!list.length) {
      toast('Bitte wählen Sie mindestens eine Datei aus.', 'warning');
      return;
    }
    uploadStatus.replaceChildren();
    for (const file of list) {
      const form = new FormData();
      form.append('file', file);
      if (subjectSelect.value) form.append('subject', subjectSelect.value);
      form.append('use_vision', visionToggle.checked ? 'true' : 'false');
      const row = el('div', { className: 'issue issue-info' }, [
        el('strong', { text: file.name }),
        el('p', { className: 'muted small', text: `${formatBytes(file.size)} – wird hochgeladen …` }),
      ]);
      uploadStatus.appendChild(row);
      try {
        const response = await api.upload('api/documents/upload', form);
        row.className = 'issue issue-info';
        row.replaceChildren(
          el('strong', { text: file.name }),
          el('p', { className: 'muted small', text: response.message }),
        );
        toast(`${file.name}: ${response.message}`, 'success');
      } catch (error) {
        row.className = 'issue issue-error';
        row.replaceChildren(
          el('strong', { text: file.name }),
          el('p', { className: 'small', text: error.message }),
          error.payload && error.payload.guidance
            ? el('p', { className: 'muted small', text: error.payload.guidance })
            : null,
        );
      }
    }
    fileInput.value = '';
    loadJobs();
    loadDocuments();
  }

  uploadHost.appendChild(card('Dateien importieren', [
    field('Fachgebiet', subjectSelect, 'Wenn Sie „automatisch erkennen“ wählen, ordnet ElektroCoach die Inhalte selbst ein.'),
    el('label', { className: 'checkbox' }, [
      visionToggle,
      el('span', { text: 'Handschrift und Bilder mit Gemini lesen (empfohlen für handschriftliche Notizen)' }),
    ]),
    el('div', { className: 'dropzone', id: 'dropzone' }, [
      el('p', { text: 'Dateien hier ablegen oder auswählen.' }),
      fileInput,
      el('p', { className: 'muted small', text:
        'Unterstützt: PDF, PNG, JPG, WEBP, BMP, TIFF. Maximal 64 MB pro Datei. Die Verarbeitung läuft im Hintergrund und ist nach einem Neustart fortsetzbar.' }),
    ]),
    el('div', { className: 'btn-row' }, [
      button('Ausgewählte Dateien importieren', {
        variant: 'primary',
        onClick: () => uploadFiles(fileInput.files),
      }),
    ]),
    uploadStatus,
  ]));

  // Drag and drop support.
  const dropzone = uploadHost.querySelector('#dropzone');
  if (dropzone) {
    ['dragenter', 'dragover'].forEach((eventName) =>
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add('dragging');
      }));
    ['dragleave', 'drop'].forEach((eventName) =>
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove('dragging');
      }));
    dropzone.addEventListener('drop', (event) => {
      uploadFiles(event.dataTransfer.files);
    });
  }

  async function loadJobs() {
    try {
      const data = await api.get('api/documents/jobs', { limit: 20 });
      jobsHost.replaceChildren(card('Laufende Verarbeitung', [
        data.items.length
          ? table(
              ['Auftrag', 'Typ', 'Status', 'Fortschritt', 'Meldung'],
              data.items.map((job) => [
                String(job.id),
                job.type,
                el('span', {}, [statusDot(job.status), ` ${job.status}`]),
                el('div', {}, [
                  progressBar(job.progress || 0),
                  el('span', { className: 'small', text: `${Math.round((job.progress || 0) * 100)} %` }),
                ]),
                job.error || job.message || '–',
              ]),
            )
          : el('p', { className: 'muted', text: 'Zurzeit läuft keine Verarbeitung.' }),
      ]));
    } catch (error) {
      jobsHost.replaceChildren(errorBox(error));
    }
  }

  async function loadReview() {
    reviewHost.replaceChildren(spinner('Prüfbedarf wird geladen …'));
    try {
      const data = await api.get('api/documents/pages/review', { limit: 30 });
      reviewHost.replaceChildren(card(`Seiten zur Prüfung (${data.count})`, [
        data.count
          ? el('div', { className: 'issue-list' }, data.items.map((page) => {
              const textBox = textarea({ rows: 6, value: page.text || '' });
              return el('div', { className: 'issue issue-warning' }, [
                el('strong', { text: `${page.document_name || 'Dokument'} – Seite ${page.page_number}` }),
                el('p', { className: 'muted small', text: page.review_reason || 'Die Erkennung war unsicher.' }),
                page.has_image
                  ? el('img', {
                      attrs: { src: api.url(`api/documents/pages/${page.id}/image`), alt: 'Seitenbild', loading: 'lazy' },
                      style: { maxWidth: '100%', borderRadius: '8px', border: '1px solid var(--border)' },
                    })
                  : null,
                field('Erkannter Text (bitte prüfen und korrigieren)', textBox,
                  'Unsichere Inhalte werden absichtlich nicht als sicher übernommen. Korrigieren Sie den Text und bestätigen Sie.'),
                el('div', { className: 'btn-row' }, [
                  button('Text bestätigen und speichern', {
                    variant: 'primary',
                    className: 'btn-sm',
                    onClick: async () => {
                      try {
                        await api.patch(`api/documents/pages/${page.id}`, { text: textBox.value });
                        toast('Der Text wurde gespeichert.', 'success');
                        loadReview();
                        loadDocuments();
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                ]),
              ]);
            }))
          : infoBox('Alle Seiten wurden erfolgreich erkannt. Es ist nichts zu prüfen.', 'success'),
      ]));
    } catch (error) {
      reviewHost.replaceChildren(errorBox(error));
    }
  }

  async function loadDocuments() {
    listHost.replaceChildren(spinner('Dokumente werden geladen …'));
    try {
      const data = await api.get('api/documents', { limit: 100 });
      listHost.replaceChildren(card(`Dokumente (${data.total})`, [
        data.items.length
          ? table(
              ['Name', 'Status', 'Größe', 'Seiten', 'Importiert', 'Aktionen'],
              data.items.map((document) => [
                el('span', {}, [
                  el('strong', { text: document.original_name }),
                  el('div', { className: 'muted small', text: document.subject || 'ohne Fachgebiet' }),
                ]),
                document.status,
                document.size_human || formatBytes(document.size_bytes),
                String(document.page_count ?? '–'),
                formatDate(document.created_at),
                el('span', { className: 'btn-row' }, [
                  button('Erneut verarbeiten', {
                    className: 'btn-sm',
                    onClick: async () => {
                      try {
                        const response = await api.post(`api/documents/${document.id}/reprocess`);
                        toast(response.message, 'success');
                        loadJobs();
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                  button('Löschen', {
                    variant: 'ghost',
                    className: 'btn-sm',
                    onClick: async () => {
                      if (!window.confirm(
                        `Dokument „${document.original_name}“ wirklich löschen? ` +
                        'Die zugehörigen Wissenseinträge werden ebenfalls entfernt. ' +
                        'Erstellen Sie vorher ein Backup.')) return;
                      try {
                        const response = await api.del(`api/documents/${document.id}?confirmed=true`);
                        toast(response.message, 'success');
                        loadDocuments();
                        loadReview();
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                ]),
              ]),
            )
          : el('p', { className: 'muted', text: 'Es wurden noch keine Dokumente importiert.' }),
      ]));
    } catch (error) {
      listHost.replaceChildren(errorBox(error));
    }
  }

  loadJobs();
  loadReview();
  loadDocuments();
  pollHandle = setInterval(() => { loadJobs(); }, 5000);
  window.addEventListener('hashchange', () => clearInterval(pollHandle), { once: true });
}
