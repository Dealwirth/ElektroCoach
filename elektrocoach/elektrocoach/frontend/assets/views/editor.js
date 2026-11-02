/**
 * Schematic editor view.
 *
 * Wires the canvas engine to the symbol library, the electrical model checks and
 * the export endpoints. Symbol previews are drawn with the same primitives the
 * canvas uses, so the palette matches the drawing exactly.
 */

import { api, downloadBinary } from '../api.js';
import {
  el, card, button, spinner, errorBox, toast, formatDate, field, input,
  infoBox, table, statusDot,
} from '../ui.js';
import { DrawingEditor } from '../editor-canvas.js';

function drawSymbolPreview(symbol, size = 34) {
  const canvas = el('canvas', {
    attrs: { width: size, height: size },
    style: { width: `${size}px`, height: `${size}px` },
  });
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, size, size);
  const scale = size / (Math.max(symbol.width, symbol.height) * 20 + 6);
  context.save();
  context.scale(scale, scale);
  context.translate(3, 3);
  context.strokeStyle = '#1f2937';
  context.fillStyle = '#1f2937';
  context.lineWidth = 1.4;
  context.lineCap = 'round';
  (symbol.shapes || []).forEach((shape) => {
    context.beginPath();
    if (shape.type === 'line') {
      context.moveTo(shape.x1 * 20, shape.y1 * 20);
      context.lineTo(shape.x2 * 20, shape.y2 * 20);
      context.stroke();
    } else if (shape.type === 'rect') {
      if (shape.filled) context.fillRect(shape.x * 20, shape.y * 20, shape.w * 20, shape.h * 20);
      else context.strokeRect(shape.x * 20, shape.y * 20, shape.w * 20, shape.h * 20);
    } else if (shape.type === 'circle') {
      context.arc(shape.cx * 20, shape.cy * 20, shape.r * 20, 0, Math.PI * 2);
      if (shape.filled) context.fill();
      else context.stroke();
    } else if (shape.type === 'polyline') {
      const points = shape.points || [];
      if (points.length < 2) return;
      context.moveTo(points[0][0] * 20, points[0][1] * 20);
      points.slice(1).forEach((point) => context.lineTo(point[0] * 20, point[1] * 20));
      if (shape.filled) context.fill();
      else context.stroke();
    }
  });
  context.restore();
  return canvas;
}

export async function renderEditor(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Schaltplaneditor' }),
    el('p', { text:
      'Zeichnen Sie Schaltpläne nach IEC-Darstellung. Raster 20 Pixel, Rastereinrastung, Rückgängig, Zoom, Export als SVG und PDF. Elektrische Verbindungen und die reine Darstellung sind getrennt: die Prüfung nutzt die elektrischen Verbindungen, nicht die gezeichneten Linien.' }),
  ]));

  const shell = el('div', { className: 'editor-shell' });
  container.appendChild(shell);

  const palettePanel = el('div', { className: 'editor-panel' }, [
    el('div', { className: 'editor-panel-header', text: 'Symbole' }),
    el('div', { className: 'editor-panel-body', id: 'symbol-palette' }, [
      spinner('Symbole werden geladen …'),
    ]),
  ]);

  const canvasWrap = el('div', { className: 'editor-canvas-wrap' });
  const canvas = el('canvas', { attrs: { id: 'drawing-canvas' } });
  canvasWrap.appendChild(canvas);

  const toolbar = el('div', { className: 'editor-toolbar' });
  canvasWrap.appendChild(toolbar);
  const hint = el('div', { className: 'editor-hint', text: 'Raster 20 px · Rastereinrastung aktiv' });
  canvasWrap.appendChild(hint);

  const sidePanel = el('div', { className: 'editor-panel' }, [
    el('div', { className: 'editor-panel-header', text: 'Prüfung und Speichern' }),
    el('div', { className: 'editor-panel-body', id: 'editor-side' }),
  ]);

  shell.appendChild(palettePanel);
  shell.appendChild(canvasWrap);
  shell.appendChild(sidePanel);

  const editor = new DrawingEditor(canvas, { grid: 20 });
  const side = sidePanel.querySelector('#editor-side');

  let symbols = [];
  let currentDrawingId = null;
  let currentName = 'Unbenannter Schaltplan';

  editor.on('notice', (message) => toast(message, 'info', 4000));
  editor.on('selection', () => renderInspector());

  const nameInput = input({ value: currentName, placeholder: 'Name des Schaltplans' });

  function renderInspector() {
    const selected = editor.selectedComponents();
    const listHost = el('div');
    side.replaceChildren(
      card('Schaltplan', [
        field('Name', nameInput),
        el('div', { className: 'btn-row' }, [
          button('Speichern', {
            variant: 'primary',
            className: 'btn-sm',
            onClick: async () => {
              currentName = nameInput.value || 'Unbenannter Schaltplan';
              try {
                if (currentDrawingId) {
                  await api.put(`api/drawing/drawings/${currentDrawingId}`, {
                    name: currentName,
                    data: editor.serialize(),
                  });
                } else {
                  const response = await api.post('api/drawing/drawings', {
                    name: currentName,
                    data: editor.serialize(),
                  });
                  currentDrawingId = response.id;
                }
                editor.dirty = false;
                toast('Der Schaltplan wurde gespeichert.', 'success');
                loadDrawings();
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          }),
          button('Neu', {
            className: 'btn-sm',
            onClick: () => {
              if (editor.dirty && !window.confirm('Nicht gespeicherte Änderungen verwerfen?')) return;
              editor.load({});
              currentDrawingId = null;
              currentName = 'Unbenannter Schaltplan';
              nameInput.value = currentName;
              renderInspector();
            },
          }),
        ]),
      ]),
      card('Auswahl', selected.length
        ? el('div', {}, selected.map((component) => {
            const label = input({ value: component.label || '', placeholder: 'Bezeichnung, z. B. F1' });
            label.addEventListener('input', () => editor.setLabel(component.id, label.value));
            return el('div', {}, [
              field(`${component.id} (${component.symbol})`, label),
            ]);
          }))
        : el('p', { className: 'muted small', text: 'Kein Bauteil ausgewählt. Klicken Sie ein Bauteil an.' })),
      card('Elektrische Prüfung', [
        button('Schaltung prüfen', {
          variant: 'primary',
          className: 'btn-sm',
          onClick: async () => {
            listHost.replaceChildren(spinner('Prüfung läuft …'));
            try {
              const report = await api.post('api/drawing/validate', { data: editor.serialize() });
              listHost.replaceChildren(renderReport(report));
            } catch (error) {
              listHost.replaceChildren(errorBox(error));
            }
          },
        }),
        listHost,
      ]),
      card('Export', [
        el('div', { className: 'btn-row' }, [
          button('Als PDF', {
            className: 'btn-sm',
            onClick: () => doExport('pdf'),
          }),
          button('Als SVG', {
            className: 'btn-sm',
            onClick: () => doExport('svg'),
          }),
          button('Drucken', {
            className: 'btn-sm',
            onClick: () => window.print(),
          }),
        ]),
      ]),
      card('Gespeicherte Schaltpläne', [el('div', { id: 'drawing-list' }, spinner())]),
    );
    loadDrawings();
  }

  function renderReport(report) {
    const issues = report.issues || [];
    return el('div', {}, [
      el('p', { className: 'small' }, [
        statusDot(report.ok ? 'ok' : 'error'),
        el('span', { text: report.ok
          ? ` Keine Fehler gefunden. ${report.components} Bauteile, ${report.connections} elektrische Verbindungen.`
          : ` ${report.counts.error} Fehler, ${report.counts.warning} Warnungen, ${report.counts.info} Hinweise.` }),
      ]),
      issues.length
        ? el('div', { className: 'issue-list' }, issues.map((issue) =>
            el('div', { className: `issue issue-${issue.severity}` }, [
              el('strong', { text: `${issue.severity === 'error' ? 'Fehler' : issue.severity === 'warning' ? 'Warnung' : 'Hinweis'}: ` }),
              el('span', { text: issue.message }),
            ])))
        : infoBox('Die Schaltung ist elektrisch schlüssig.', 'success'),
      el('p', { className: 'muted small', text:
        'Hinweis: Die Prüfung bewertet die elektrischen Verbindungen. Gezeichnete Linien allein erzeugen keine elektrische Verbindung – nutzen Sie dazu das Werkzeug „Verbinden“.' }),
    ]);
  }

  async function doExport(format) {
    try {
      await downloadBinary(
        `api/drawing/export/${format}`,
        { data: editor.serialize(), title: currentName, grid: true },
        `${currentName.replace(/[^\w\-äöüÄÖÜß]+/g, '_')}.${format}`,
      );
      toast(`Der Export als ${format.toUpperCase()} wurde gestartet.`, 'success');
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function loadDrawings() {
    const listHost = sidePanel.querySelector('#drawing-list');
    if (!listHost) return;
    try {
      const data = await api.get('api/drawing/drawings');
      listHost.replaceChildren(
        data.items.length
          ? table(
              ['Name', 'Geändert', ''],
              data.items.map((drawing) => [
                el('span', {}, [
                  el('strong', { text: drawing.name }),
                  el('div', { className: 'muted small', text: `${drawing.component_count ?? 0} Bauteile` }),
                ]),
                formatDate(drawing.updated_at),
                el('span', { className: 'btn-row' }, [
                  button('Öffnen', {
                    className: 'btn-sm',
                    onClick: async () => {
                      try {
                        const full = await api.get(`api/drawing/drawings/${drawing.id}`);
                        editor.load(full.data);
                        currentDrawingId = full.id;
                        currentName = full.name;
                        nameInput.value = full.name;
                        toast(`„${full.name}“ wurde geladen.`, 'success');
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                  button('Löschen', {
                    variant: 'ghost',
                    className: 'btn-sm',
                    onClick: async () => {
                      if (!window.confirm(`Schaltplan „${drawing.name}“ löschen?`)) return;
                      try {
                        await api.del(`api/drawing/drawings/${drawing.id}`);
                        loadDrawings();
                      } catch (error) {
                        toast(error.message, 'error');
                      }
                    },
                  }),
                ]),
              ]),
            )
          : el('p', { className: 'muted small', text: 'Noch keine Schaltpläne gespeichert.' }),
      );
    } catch (error) {
      listHost.replaceChildren(errorBox(error));
    }
  }

  // -- toolbar ---------------------------------------------------------------

  function buildToolbar() {
    toolbar.replaceChildren(
      button('Auswählen', {
        className: `btn-sm ${editor.tool === 'select' ? 'btn-primary' : ''}`,
        onClick: () => { editor.tool = 'select'; editor.pendingSymbol = null; buildToolbar(); },
      }),
      button('Verbinden', {
        className: `btn-sm ${editor.tool === 'wire' ? 'btn-primary' : ''}`,
        title: 'Elektrische Verbindung zwischen zwei Anschlüssen herstellen',
        onClick: () => {
          editor.tool = 'wire';
          editor.pendingSymbol = null;
          editor.wireStart = null;
          editor.wireStartTerminal = null;
          buildToolbar();
          toast('Verbinden: Klicken Sie zuerst den ersten Anschluss, dann den zweiten.', 'info', 5000);
        },
      }),
      button('Freie Linie', {
        className: `btn-sm ${editor.tool === 'freeline' ? 'btn-primary' : ''}`,
        onClick: () => {
          editor.tool = 'wire';
          editor.pendingSymbol = null;
          buildToolbar();
        },
      }),
      button('Text', {
        className: `btn-sm ${editor.tool === 'text' ? 'btn-primary' : ''}`,
        onClick: () => { editor.tool = 'text'; editor.pendingSymbol = null; buildToolbar(); },
      }),
      button('Verschieben (Pan)', {
        className: `btn-sm ${editor.tool === 'pan' ? 'btn-primary' : ''}`,
        onClick: () => { editor.tool = 'pan'; editor.pendingSymbol = null; buildToolbar(); },
      }),
      button('↶ Rückgängig', {
        className: 'btn-sm',
        onClick: () => { if (!editor.undo()) toast('Nichts zum Rückgängigmachen.', 'warning'); },
      }),
      button('↷ Wiederholen', {
        className: 'btn-sm',
        onClick: () => { if (!editor.redo()) toast('Nichts zum Wiederholen.', 'warning'); },
      }),
      button('Kopieren', {
        className: 'btn-sm',
        onClick: () => editor.duplicateSelection(),
      }),
      button('Drehen', { className: 'btn-sm', onClick: () => editor.rotateSelection() }),
      button('Spiegeln', { className: 'btn-sm', onClick: () => editor.mirrorSelection() }),
      button('Löschen', {
        className: 'btn-sm',
        onClick: () => {
          if (editor.selection.size && window.confirm('Auswahl löschen?')) editor.removeSelection();
        },
      }),
      button('Zoom +', { className: 'btn-sm', onClick: () => editor.zoomBy(1.2) }),
      button('Zoom −', { className: 'btn-sm', onClick: () => editor.zoomBy(1 / 1.2) }),
      button('Ansicht einpassen', { className: 'btn-sm', onClick: () => editor.fitView() }),
    );
  }

  async function loadSymbols() {
    const palette = palettePanel.querySelector('#symbol-palette');
    try {
      const data = await api.get('api/drawing/library');
      symbols = data.items || [];
      editor.setSymbols(symbols);
      const categories = data.categories || [];
      const grouped = new Map();
      symbols.forEach((symbol) => {
        if (!grouped.has(symbol.category)) grouped.set(symbol.category, []);
        grouped.get(symbol.category).push(symbol);
      });
      const nodes = [];
      categories.forEach((category) => {
        const entries = grouped.get(category);
        if (!entries || !entries.length) return;
        nodes.push(el('div', { className: 'symbol-group-label', text: category }));
        entries.forEach((symbol) => {
          nodes.push(el('button', {
            className: 'symbol-item',
            attrs: { type: 'button', title: `${symbol.name} – ${symbol.description || ''}` },
            on: {
              click: (event) => {
                editor.pendingSymbol = symbol.id;
                editor.tool = 'select';
                buildToolbar();
                palettePanel.querySelectorAll('.symbol-item').forEach((node) => node.classList.remove('selected'));
                event.currentTarget.classList.add('selected');
                toast(`${symbol.name} ausgewählt. Klicken Sie in die Zeichenfläche.`, 'info', 4000);
              },
            },
          }, [
            drawSymbolPreview(symbol),
            el('span', { text: symbol.name }),
          ]));
        });
      });
      palette.replaceChildren(...nodes);
    } catch (error) {
      palette.replaceChildren(errorBox(error));
    }
  }

  buildToolbar();
  renderInspector();
  loadSymbols();
  editor.resetView();

  // Redraw on container resize (rotating a tablet changes the canvas size).
  const observer = new ResizeObserver(() => editor.resize());
  observer.observe(canvasWrap);
  window.addEventListener('hashchange', () => observer.disconnect(), { once: true });

  window.addEventListener('beforeunload', (event) => {
    if (editor.dirty) {
      event.preventDefault();
      event.returnValue = '';
    }
  });

  // Keyboard shortcuts, matching common drawing tools.
  const keyHandler = (event) => {
    if (event.target.matches('input, textarea, select')) return;
    if (event.ctrlKey && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      if (event.shiftKey) editor.redo();
      else editor.undo();
    } else if (event.ctrlKey && event.key.toLowerCase() === 'y') {
      event.preventDefault();
      editor.redo();
    } else if (event.ctrlKey && event.key.toLowerCase() === 'd') {
      event.preventDefault();
      editor.duplicateSelection();
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      if (editor.selection.size) {
        event.preventDefault();
        editor.removeSelection();
      }
    } else if (event.key.toLowerCase() === 'r') {
      editor.rotateSelection();
    }
  };
  document.addEventListener('keydown', keyHandler);
  window.addEventListener('hashchange', () => document.removeEventListener('keydown', keyHandler), { once: true });
}
