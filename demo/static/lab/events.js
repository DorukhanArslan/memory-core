// events.js: the global Lab event stream (GET /api/lab/events, SSE).
// The browser's own reconnect resends Last-Event-ID; if the stream closes for good we
// recreate it with a 1/2/5/10 s backoff and ask the store to refetch /api/lab/state, since a
// fresh EventSource cannot resume. A 501/404 on the stream shows as "henüz yok".

const PATH = '/api/lab/events';
const BACKOFF = [1000, 2000, 5000, 10000];
// Named frames are accepted too, in case the server sets `event: <type>` (DESIGN §4.3 taxonomy).
const KNOWN_TYPES = [
  'chat.turn.started', 'chat.turn.completed', 'chat.turn.failed', 'index.reindexed', 'recall.completed', 'prompt.assembled',
  'curation.written', 'curation.refused', 'curation.reverted', 'flush.decided', 'flush.written', 'flush.no_write', 'session.new', 'session_memory.written', 'startup_context.loaded',
  'bootstrap.seeded', 'bootstrap.completed', 'bootstrap.file_deleted', 'file.saved', 'file.changed',
  'search.completed', 'search.unavailable', 'search.cooldown', 'embedding.request',
  'heartbeat.skipped', 'heartbeat.run', 'heartbeat.llm', 'heartbeat.decided', 'clock.changed',
  'promotion.swept', 'dreaming.swept', 'audit.completed', 'repair.completed',
  'settings.changed', 'provider.check', 'workspace.reset', 'error', 'lab',
];

export function connectEvents({ onEvent, onStatus, onReconnect }) {
  let es = null; let attempt = 0; let everOpened = false; let timer = null; let stopped = false;

  const emit = (state) => onStatus?.({ state, attempt });
  const handle = (msg) => {
    let data;
    try { data = JSON.parse(msg.data); } catch { return; }
    if (!data || typeof data !== 'object') return;
    if (data.id === undefined && msg.lastEventId) data.id = Number(msg.lastEventId);
    if (!data.type && msg.type && msg.type !== 'message') data.type = msg.type;
    onEvent?.(data);
  };

  async function probe() {
    try {
      const ctl = new AbortController();
      const res = await fetch(PATH, { signal: ctl.signal, headers: { Accept: 'text/event-stream' }, cache: 'no-store' });
      ctl.abort();
      return res.status;
    } catch { return 0; }
  }

  function open() {
    if (stopped) return;
    clearTimeout(timer);
    emit(everOpened ? 'retrying' : 'connecting');
    es = new EventSource(PATH);
    es.onopen = () => {
      const wasReconnect = everOpened || attempt > 0;
      everOpened = true; attempt = 0; emit('open');
      if (wasReconnect) onReconnect?.();
    };
    es.onmessage = handle;
    for (const type of KNOWN_TYPES) es.addEventListener(type, handle);
    es.onerror = async () => {
      if (!es) return;
      if (es.readyState === EventSource.CONNECTING) { attempt += 1; emit('retrying'); return; }
      es.close(); es = null;
      const status = await probe();
      if (status === 501 || status === 404) { emit('missing'); timer = setTimeout(open, 15000); return; }
      const wait = BACKOFF[Math.min(attempt, BACKOFF.length - 1)];
      attempt += 1; emit('retrying');
      timer = setTimeout(open, wait);
    };
  }

  open();
  return {
    close() { stopped = true; clearTimeout(timer); es?.close(); es = null; },
    reconnectNow() { attempt = 0; es?.close(); es = null; open(); },
  };
}
