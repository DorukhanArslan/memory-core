// events.js: the global Lab event stream (GET /api/lab/events, SSE).
// Frames carry no `event:` line: every LabEvent arrives as a default `message` whose JSON has the
// `type` (docs/lab.md › GET /events), so only onmessage is read. The browser's own reconnect
// resends Last-Event-ID; when the stream closes for good it is recreated with a 1/2/5/10 s backoff
// and `?lastEventId=` (a fresh EventSource cannot resume on its own), and the store refetches state.
// A `lab.resync` frame (gap older than the 1,000-event ring) reaches onEvent like any other event.

const PATH = '/api/lab/events';
const BACKOFF = [1000, 2000, 5000, 10000];

export function connectEvents({ onEvent, onStatus, onReconnect, lastEventId = () => 0 }) {
  let es = null; let attempt = 0; let everOpened = false; let timer = null; let stopped = false;

  const emit = (state) => onStatus?.({ state, attempt });
  const handle = (msg) => {
    let data;
    try { data = JSON.parse(msg.data); } catch { return; }
    if (!data || typeof data !== 'object') return;
    if (data.id === undefined && msg.lastEventId) data.id = Number(msg.lastEventId);
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
    const since = everOpened ? Number(lastEventId()) || 0 : 0;
    es = new EventSource(since ? `${PATH}?lastEventId=${since}` : PATH);
    es.onopen = () => {
      const wasReconnect = everOpened || attempt > 0;
      everOpened = true; attempt = 0; emit('open');
      if (wasReconnect) onReconnect?.();
    };
    es.onmessage = handle;
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
