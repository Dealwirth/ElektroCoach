/**
 * Small DOM helpers.
 *
 * Security: `el()` assigns text with `textContent`. User content, AI answers and
 * document text therefore never pass through `innerHTML`, which removes the XSS
 * risk from imported documents or model output. The `html` option is only for
 * literal, developer-authored markup and is never used with external data.
 */

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  const { className, text, html, attrs, dataset, on, style } = options || {};

  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (html !== undefined) node.innerHTML = html; // trusted literal markup only
  if (attrs) {
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null || value === false) return;
      if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    });
  }
  if (dataset) {
    Object.entries(dataset).forEach(([key, value]) => {
      node.dataset[key] = value;
    });
  }
  if (style && typeof style === 'object') {
    Object.assign(node.style, style);
  }
  if (on) {
    Object.entries(on).forEach(([event, handler]) => {
      node.addEventListener(event, handler);
    });
  }

  append(node, children);
  return node;
}

export function append(parent, children) {
  const list = Array.isArray(children) ? children : [children];
  list.forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) {
      append(parent, child);
      return;
    }
    if (child instanceof Node) parent.appendChild(child);
    else parent.appendChild(document.createTextNode(String(child)));
  });
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function card(title, body, options = {}) {
  const header = title
    ? el('div', { className: 'card-header' }, [
        el('h3', { className: 'card-title', text: title }),
        options.actions || null,
      ])
    : null;
  return el('section', { className: `card ${options.className || ''}`.trim() }, [
    header,
    el('div', { className: 'card-body' }, body),
  ]);
}

export function badge(text, tone = 'neutral') {
  return el('span', { className: `badge badge-${tone}`, text });
}

export function statusDot(status) {
  const tone =
    {
      ok: 'ok',
      warning: 'warning',
      error: 'error',
      critical: 'critical',
      disabled: 'disabled',
      running: 'info',
      not_started: 'neutral',
      needs_input: 'warning',
      failed: 'error',
      done: 'ok',
      queued: 'neutral',
      cancelled: 'neutral',
    }[status] || 'neutral';
  return el('span', { className: `dot dot-${tone}`, attrs: { 'aria-hidden': 'true' } });
}

export function progressBar(value) {
  const percent = Math.max(0, Math.min(100, Math.round((value || 0) * 100)));
  return el('div', { className: 'progress' }, [
    el('div', { className: 'progress-fill', style: { width: `${percent}%` } }),
  ]);
}

export function button(label, options = {}) {
  return el('button', {
    className: `btn ${options.variant ? `btn-${options.variant}` : ''} ${
      options.className || ''
    }`.trim(),
    text: label,
    attrs: {
      type: options.type || 'button',
      disabled: options.disabled ? true : undefined,
      title: options.title,
    },
    on: options.onClick ? { click: options.onClick } : undefined,
  });
}

export function input(options = {}) {
  return el('input', {
    className: `input ${options.className || ''}`.trim(),
    attrs: {
      type: options.type || 'text',
      value: options.value ?? '',
      placeholder: options.placeholder,
      min: options.min,
      max: options.max,
      step: options.step,
      name: options.name,
      id: options.id,
      autocomplete: options.autocomplete,
    },
    on: options.onInput ? { input: options.onInput } : undefined,
  });
}

export function select(options = {}) {
  return el(
    'select',
    {
      className: `input ${options.className || ''}`.trim(),
      attrs: { name: options.name, id: options.id },
      on: options.onChange ? { change: options.onChange } : undefined,
    },
    (options.options || []).map((entry) =>
      el('option', {
        text: entry.label ?? entry,
        attrs: {
          value: entry.value ?? entry,
          selected:
            String(entry.value ?? entry) === String(options.value ?? '')
              ? true
              : undefined,
        },
      }),
    ),
  );
}

export function textarea(options = {}) {
  return el('textarea', {
    className: `input ${options.className || ''}`.trim(),
    text: options.value || '',
    attrs: {
      rows: options.rows || 5,
      placeholder: options.placeholder,
      name: options.name,
      id: options.id,
    },
    on: options.onInput ? { input: options.onInput } : undefined,
  });
}

export function field(labelText, control, hint) {
  return el('label', { className: 'field' }, [
    el('span', { className: 'field-label', text: labelText }),
    control,
    hint ? el('span', { className: 'field-hint', text: hint }) : null,
  ]);
}

export function checkbox(labelText, checked, onChange) {
  const box = el('input', {
    attrs: { type: 'checkbox', checked: checked ? true : undefined },
    on: onChange ? { change: onChange } : undefined,
  });
  return el('label', { className: 'checkbox' }, [box, el('span', { text: labelText })]);
}

export function table(headers, rows) {
  return el('div', { className: 'table-wrap' }, [
    el('table', { className: 'table' }, [
      el('thead', {}, [
        el('tr', {}, headers.map((header) => el('th', { text: header }))),
      ]),
      el(
        'tbody',
        {},
        rows.map((row) =>
          el(
            'tr',
            {},
            row.map((cell) =>
              el('td', {}, [cell instanceof Node ? cell : String(cell ?? '')]),
            ),
          ),
        ),
      ),
    ]),
  ]);
}

export function spinner(label = 'Wird geladen …') {
  return el('div', { className: 'loading' }, [
    el('span', { className: 'spinner', attrs: { 'aria-hidden': 'true' } }),
    el('span', { text: label }),
  ]);
}

export function emptyState(title, message, action) {
  return el('div', { className: 'empty' }, [
    el('h3', { text: title }),
    el('p', { className: 'muted', text: message }),
    action || null,
  ]);
}

/** Show a transient message. `tone` is one of info, success, warning, error. */
export function toast(message, tone = 'info', timeout = 6000) {
  const container = document.getElementById('toasts');
  if (!container) return;
  const node = el('div', { className: `toast toast-${tone}` }, [
    el('span', { className: 'toast-text', text: message }),
    el('button', {
      className: 'toast-close',
      text: '×',
      attrs: { 'aria-label': 'Meldung schließen' },
      on: { click: () => node.remove() },
    }),
  ]);
  container.appendChild(node);
  if (timeout > 0) setTimeout(() => node.remove(), timeout);
}

/** Render an error with its guidance, if the API supplied any. */
export function errorBox(error) {
  const message = error && error.message ? error.message : 'Unbekannter Fehler.';
  const guidance =
    error && error.payload
      ? error.payload.guidance || (error.payload.detail && error.payload.detail.guidance)
      : null;
  return el('div', { className: 'alert alert-error' }, [
    el('strong', { text: 'Es ist ein Problem aufgetreten: ' }),
    el('span', { text: message }),
    guidance ? el('p', { className: 'alert-guidance', text: guidance }) : null,
  ]);
}

export function infoBox(message, tone = 'info') {
  return el('div', { className: `alert alert-${tone}`, text: message });
}

export function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

export function formatDate(value) {
  if (!value) return '–';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, '0')} min`;
}

export function percent(value) {
  return `${Math.round((Number(value) || 0) * 100)} %`;
}
