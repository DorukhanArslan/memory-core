// api.js: JSON calls and POST-SSE streams (fetch + ReadableStream + TextDecoder) against the
// Lab contract (DESIGN §4). Keys only ever travel in request bodies, never in URLs.
//
// Error model: every non-2xx response becomes an ApiError {status, code, message, module, body}.
// `missing` is true for 501 {code:"module_missing"} and for a 404 on an /api/lab/* path (the
// endpoint has not landed yet); views render both as a "henüz yok" state and never fake data.

export class ApiError extends Error {
  constructor({ status = 0, code = null, message = '', module = null, body = null, path = '' }) {
    super(message || code || `HTTP ${status}`);
    this.status = status; this.code = code; this.module = module; this.body = body; this.path = path;
    this.missing = code === 'module_missing' || (status === 404 && path.startsWith('/api/lab/')) || status === 501;
  }
}

function qs(params) {
  if (!params) return '';
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : '';
}

async function toError(res, path) {
  let body = null; let text = '';
  try { text = await res.text(); body = text ? JSON.parse(text) : null; } catch { body = text ? { raw: text.slice(0, 2000) } : null; }
  const message = (body && (body.error || body.detail || body.message)) || `HTTP ${res.status}`;
  return new ApiError({ status: res.status, code: body?.code || null, message: typeof message === 'string' ? message : JSON.stringify(message), module: body?.module || null, body, path });
}

async function request(method, path, { params = null, body, signal } = {}) {
  let res;
  try {
    res = await fetch(`${path}${qs(params)}`, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new ApiError({ status: 0, code: 'network', message: String(err?.message || err), path });
  }
  if (!res.ok) throw await toError(res, path);
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return { raw: text }; }
}

export const api = {
  get: (path, params, opts = {}) => request('GET', path, { ...opts, params }),
  post: (path, body = {}, opts = {}) => request('POST', path, { ...opts, body }),
  put: (path, body = {}, opts = {}) => request('PUT', path, { ...opts, body }),
};

/** Parses one SSE frame block ("event:", "id:", "data:" lines). */
function parseFrame(block) {
  let event = 'message'; let id = null; const data = [];
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    const i = line.indexOf(':');
    const field = i < 0 ? line : line.slice(0, i);
    const value = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '');
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
    else if (field === 'id') id = value;
  }
  if (!data.length) return null;
  const raw = data.join('\n');
  let payload;
  try { payload = JSON.parse(raw); } catch { payload = { raw }; }
  return { event, id, data: payload };
}

/**
 * POST a JSON body and read the text/event-stream answer frame by frame.
 * onEvent({event, id, data}) is called per frame. Resolves with {ended:'done'|'error'|'eof'}.
 * A non-2xx answer (for example 501 module_missing) rejects with ApiError before any frame.
 */
export async function postStream(path, body, { onEvent, signal } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body ?? {}),
      signal,
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new ApiError({ status: 0, code: 'network', message: String(err?.message || err), path });
  }
  if (!res.ok) throw await toError(res, path);
  if (!res.body) throw new ApiError({ status: res.status, code: 'no_stream', message: 'no response body', path });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = ''; let ended = 'eof';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n');
    let cut;
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, cut); buf = buf.slice(cut + 2);
      const frame = parseFrame(block);
      if (!frame) continue;
      if (frame.event === 'done') ended = 'done';
      if (frame.event === 'error') ended = 'error';
      onEvent?.(frame);
    }
  }
  buf += decoder.decode();
  if (buf.trim()) { const frame = parseFrame(buf.replace(/\r\n?/g, '\n')); if (frame) { if (frame.event === 'error') ended = 'error'; onEvent?.(frame); } }
  return { ended };
}
