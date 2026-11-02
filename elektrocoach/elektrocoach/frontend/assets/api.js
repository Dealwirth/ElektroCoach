/**
 * API client.
 *
 * Ingress safety: Home Assistant serves the add-on under a dynamic path
 * (e.g. /api/hassio_ingress/<token>/). All requests therefore use a path that is
 * derived from the document's <base> element at runtime, never a hard-coded
 * absolute path. The <base> tag is injected by the backend template, so the same
 * code works locally (path "/") and behind Ingress.
 *
 * CSRF: every state-changing request carries the token from GET /api/session in
 * the X-CSRF-Token header. The token is bound to the session cookie.
 */

const BASE = (() => {
  const base = document.querySelector('base');
  if (!base) return '/';
  try {
    const url = new URL(base.href, window.location.href);
    return url.pathname.endsWith('/') ? url.pathname : url.pathname + '/';
  } catch (error) {
    return '/';
  }
})();

let csrfToken = null;
let sessionPromise = null;

/** Join the ingress base with an API path. */
export function apiUrl(path) {
  const clean = String(path).replace(/^\/+/, '');
  return BASE + clean;
}

/** Join the ingress base with a static asset path. */
export function assetUrl(path) {
  const clean = String(path).replace(/^\/+/, '');
  return BASE + clean;
}

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload || {};
  }
}

async function ensureSession(force = false) {
  if (csrfToken && !force) return csrfToken;
  if (sessionPromise && !force) return sessionPromise;
  sessionPromise = (async () => {
    const response = await fetch(apiUrl('api/session'), {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new ApiError(
        'Die Sitzung konnte nicht geladen werden. Bitte laden Sie die Seite neu.',
        response.status,
      );
    }
    const data = await response.json();
    csrfToken = data.csrf_token;
    return csrfToken;
  })();
  try {
    return await sessionPromise;
  } finally {
    sessionPromise = null;
  }
}

function describeNetworkError(error) {
  if (error instanceof ApiError) return error.message;
  return (
    'Die Verbindung zu ElektroCoach wurde unterbrochen. Prüfen Sie, ob das ' +
    'Add-on läuft, und laden Sie die Seite neu.'
  );
}

async function request(path, options = {}, retry = true) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  const init = { method, credentials: 'same-origin', headers };

  if (options.body instanceof FormData) {
    init.body = options.body;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRF-Token'] = await ensureSession();
  }

  let response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch (error) {
    throw new ApiError(describeNetworkError(error), 0, {});
  }

  // A 403 usually means the session expired; refresh it once and retry.
  if (response.status === 403 && retry) {
    await ensureSession(true);
    return request(path, options, false);
  }

  let payload = {};
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
  }

  if (!response.ok) {
    const detail = payload.detail || payload.message || '';
    throw new ApiError(
      typeof detail === 'string' && detail
        ? detail
        : `Die Anfrage ist fehlgeschlagen (HTTP ${response.status}).`,
      response.status,
      payload,
    );
  }
  return payload;
}

export const api = {
  get: (path, params) => {
    if (!params) return request(path);
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        search.append(key, value);
      }
    });
    const query = search.toString();
    return request(query ? `${path}?${query}` : path);
  },
  post: (path, body) => request(path, { method: 'POST', body: body ?? {} }),
  put: (path, body) => request(path, { method: 'PUT', body: body ?? {} }),
  patch: (path, body) => request(path, { method: 'PATCH', body: body ?? {} }),
  del: (path) => request(path, { method: 'DELETE' }),
  upload: (path, formData) => request(path, { method: 'POST', body: formData }),
  url: apiUrl,
  base: () => BASE,
};

/** Download a binary response (export, backup) through a POST request. */
export async function downloadBinary(path, body, filename) {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': await ensureSession(),
    },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) {
    let detail = `Der Export ist fehlgeschlagen (HTTP ${response.status}).`;
    try {
      const payload = await response.json();
      if (payload.detail) detail = payload.detail;
    } catch (error) {
      /* keep the generic message */
    }
    throw new ApiError(detail, response.status, {});
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Release the object URL once the browser has started the download.
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function getCsrfToken() {
  return csrfToken;
}

export async function initSession() {
  return ensureSession();
}

/** Open a WebSocket for live updates, using the ingress-aware base path. */
export function openSocket(onMessage, onStatus) {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = `${BASE}api/ws`.replace(/\/{2,}/g, '/');
  const url = `${scheme}//${window.location.host}${path}`;
  let socket = null;
  let closed = false;
  let retry = 1000;

  const scheduleReconnect = () => {
    if (closed) return;
    // Back off up to 30 s so a stopped add-on does not spin the browser.
    retry = Math.min(retry * 1.6, 30000);
    setTimeout(connect, retry);
  };

  const connect = () => {
    if (closed) return;
    try {
      socket = new WebSocket(url);
    } catch (error) {
      if (onStatus) onStatus('offline');
      scheduleReconnect();
      return;
    }
    socket.addEventListener('open', () => {
      retry = 1000;
      if (onStatus) onStatus('online');
    });
    socket.addEventListener('message', (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch (error) {
        /* ignore malformed frames */
      }
    });
    socket.addEventListener('close', () => {
      if (onStatus) onStatus('offline');
      scheduleReconnect();
    });
    socket.addEventListener('error', () => {
      if (socket) socket.close();
    });
  };

  connect();
  return {
    close: () => {
      closed = true;
      if (socket) socket.close();
    },
  };
}
