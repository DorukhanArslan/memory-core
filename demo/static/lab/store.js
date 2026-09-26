// store.js: app state, render scheduling, loaders over the Lab API and the LabEvent reducer.
// Nothing here computes memory behaviour: every value shown comes from a backend payload.
import { api, ApiError } from './api.js';
import { lsGet, lsSet, ssGet, ssSet, captureState, restoreState } from './ui/dom.js';

const saved = lsGet('lab.ui', {});
const EVENT_RING = 1000;

export const store = {
  data: {
    snap: null, snapErr: null,
    files: null, filesErr: null, filesKey: '',
    settings: null, settingsErr: null,
    index: null, indexErr: null,
    turns: [],
    details: new Map(),
    detailErr: new Map(),
    events: [],
    lastEventId: 0,
    fileCache: new Map(),
    changed: new Set(),
    changedLines: new Map(),
    heartbeat: null, heartbeatErr: null,
    consolidation: null, consolidationErr: null,
    parity: null, parityErr: null,
    live: { state: null, err: null, turns: [], events: [], engine: null, streaming: null },
    parityTrace: null,
  },
  conn: { state: 'connecting', attempt: 0 },
  keys: { chat: ssGet('lab.key.chat', ''), embedding: ssGet('lab.key.embedding', ''), remember: !!ssGet('lab.key.remember', false), ignoreEnvKey: false },
  stream: null,
  ui: {
    view: 'chat',
    centerTab: 'view',
    openTabs: [],
    drafts: {},
    draftBase: {},
    editing: {},
    preview: {},
    focusLine: {},
    inspectorTab: saved.inspectorTab || 'prompt',
    follow: true,
    pinnedTurn: null,
    promptKind: 'main',
    promptMode: 'turn',
    promptOpts: { contextInjection: null, lightContext: false },
    compare: false,
    openSections: new Set(saved.openSections || ['notices', 'budget', 'stable', 'dynamic', 'recall', 'tools']),
    openFolds: new Set(),
    explorerOrder: saved.explorerOrder || 'prompt',
    showHidden: false,
    expanded: new Set(saved.expanded || ['memory', 'memory/daily', 'memory/session']),
    composerKind: 'main',
    theme: saved.theme || 'dark',
    lang: saved.lang || 'tr',
    density: saved.density || 'compact',
    motion: saved.motion || 'system',
    singleKeys: saved.singleKeys !== false,
    widths: saved.widths || {},
    explorerCollapsed: false,
    inspectorCollapsed: false,
    drawer: false,
    mobilePane: 'center',
    sheet: { open: false, detent: 0.5 },
    timeline: { cats: new Set(), text: '', thisTurn: false, expanded: new Set(), stick: true },
    diffBase: 'turn',
    search: { query: '', mode: 'text', corpus: 'all', maxResults: 5, minScore: 0, result: null, error: null, running: false },
    hbSelected: null,
    hbCompare: [],
    hbStripInput: '',
    hbStripResult: null,
    consolidationPane: 'scored',
    liveSession: 'demo_session',
    liveSubject: 'demo_subject',
    liveInput: '',
    scenario: null,
    scenarioResults: lsGet('lab.scenarioResults', {}),
    scenarioFilter: 'all',
    keepMemory: false,
  },
  actions: {},
};

/* ---------- render scheduling ---------- */
const renderers = new Map();
const dirty = new Set();
let scheduled = false;
// Region -> root element; focus, <details> state and inner scroll survive each rebuild.
const REGION_ROOT = { top: 'topbar', rail: 'rail', status: 'statusbar', mobile: 'mobile-nav', explorer: 'explorer', center: 'center', inspector: 'inspector' };
export function registerRenderer(region, fn) { renderers.set(region, fn); }
export function refresh(...regions) {
  for (const r of regions.length ? regions : [...renderers.keys()]) dirty.add(r);
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    const list = [...dirty]; dirty.clear();
    for (const r of list) renderNow(r);
  });
}
/** Rebuilds one region now, keeping focus, <details> state and inner scroll. */
export function renderNow(r) {
  const fn = renderers.get(r); if (!fn) return;
  dirty.delete(r);
  const root = document.getElementById(REGION_ROOT[r] || '');
  const kept = root ? captureState(root) : null;
  try { fn(); } catch (err) { console.error(`render ${r}`, err); }
  if (kept) { try { restoreState(root, kept); } catch (err) { console.error(`restore ${r}`, err); } }
}
export function persistUi() {
  const u = store.ui;
  lsSet('lab.ui', {
    inspectorTab: u.inspectorTab, explorerOrder: u.explorerOrder, expanded: [...u.expanded], theme: u.theme, lang: u.lang,
    density: u.density, motion: u.motion, widths: u.widths, openSections: [...u.openSections], singleKeys: u.singleKeys,
  });
}

/* ---------- debounced loaders ---------- */
const timers = new Map();
function later(name, fn, ms = 120) { clearTimeout(timers.get(name)); timers.set(name, setTimeout(fn, ms)); }

async function guard(fn, onErr) {
  try { return await fn(); } catch (err) {
    if (err?.name === 'AbortError') return null;
    const e = err instanceof ApiError ? err : new ApiError({ message: String(err?.message || err) });
    onErr?.(e);
    return null;
  }
}

export async function loadState() {
  const d = store.data;
  const snap = await guard(() => api.get('/api/lab/state', { sessionKind: 'main' }), (e) => { d.snapErr = e; });
  if (snap) {
    d.snap = snap; d.snapErr = null;
    if (Array.isArray(snap.turns)) mergeTurns(snap.turns, { replace: true });
    if (typeof snap.lastEventId === 'number' && snap.lastEventId > d.lastEventId) d.lastEventId = snap.lastEventId;
    if (snap.index) d.index = { ...(d.index || {}), ...snap.index };
  }
  refresh('top', 'status', 'center', 'explorer', 'inspector', 'rail');
  return snap;
}
export async function loadFiles() {
  const d = store.data; const u = store.ui;
  const params = { sessionKind: u.promptKind, layout: d.settings?.layout };
  const res = await guard(() => api.get('/api/lab/files', params), (e) => { d.filesErr = e; });
  if (res) { d.files = Array.isArray(res) ? res : (res.files || []); d.filesErr = null; d.filesKey = JSON.stringify(params); }
  refresh('explorer', 'center', 'inspector');
  return res;
}
export async function loadSettings() {
  const d = store.data;
  const res = await guard(() => api.get('/api/lab/settings'), (e) => { d.settingsErr = e; });
  if (res) { d.settings = res; d.settingsErr = null; }
  refresh('top', 'center', 'status', 'inspector');
  return res;
}
export async function loadIndex() {
  const d = store.data;
  const res = await guard(() => api.get('/api/lab/index/status'), (e) => { d.indexErr = e; });
  if (res) { d.index = res; d.indexErr = null; }
  refresh('status', 'inspector', 'top');
  return res;
}
export async function loadTurn(id, { force = false } = {}) {
  const d = store.data;
  if (!id) return null;
  if (!force && d.details.has(id)) return d.details.get(id);
  const res = await guard(() => api.get(`/api/lab/turns/${encodeURIComponent(id)}`), (e) => { d.detailErr.set(id, e); });
  if (res) { d.details.set(id, res); d.detailErr.delete(id); }
  refresh('inspector', 'center');
  return res;
}
export async function loadFile(path, { force = false } = {}) {
  const d = store.data;
  if (!force && d.fileCache.has(path) && !d.fileCache.get(path).err) return d.fileCache.get(path);
  const res = await guard(() => api.get('/api/lab/file', { path }), (e) => { d.fileCache.set(path, { err: e }); });
  if (res) d.fileCache.set(path, { ...res, loadedAt: Date.now() });
  refresh('center');
  return d.fileCache.get(path);
}
export async function loadHeartbeat() {
  const d = store.data;
  const res = await guard(() => api.get('/api/lab/heartbeat'), (e) => { d.heartbeatErr = e; });
  if (res) { d.heartbeat = res; d.heartbeatErr = null; }
  refresh('center', 'inspector', 'status');
  return res;
}
export async function loadConsolidation() {
  const d = store.data;
  const res = await guard(() => api.get('/api/lab/consolidation'), (e) => { d.consolidationErr = e; });
  if (res) { d.consolidation = res; d.consolidationErr = null; }
  refresh('center');
  return res;
}
export async function loadParity() {
  const d = store.data;
  const res = await guard(() => api.get('/api/lab/parity'), (e) => { d.parityErr = e; });
  if (res) { d.parity = res; d.parityErr = null; }
  refresh('center', 'top');
  return res;
}
export async function loadLive() {
  const L = store.data.live;
  const res = await guard(() => api.get('/api/live-task/state'), (e) => { L.err = e; });
  if (res) { L.state = res; L.err = null; }
  refresh('center', 'inspector');
  return res;
}
export async function refreshAll() {
  await Promise.all([loadSettings(), loadState()]);
  await Promise.all([loadFiles(), loadIndex()]);
}

/* ---------- turns ---------- */
export function mergeTurns(list, { replace = false } = {}) {
  const d = store.data;
  const byId = new Map((replace ? [] : d.turns).map((x) => [x.id, x]));
  for (const tr of list || []) if (tr && tr.id !== undefined && tr.id !== null) byId.set(tr.id, { ...(byId.get(tr.id) || {}), ...tr });
  d.turns = [...byId.values()].sort((a, b) => (a.startedAt ?? 0) - (b.startedAt ?? 0) || (a.id > b.id ? 1 : -1));
}
export function currentTurn() {
  const { turns } = store.data; const u = store.ui;
  if (!u.follow && u.pinnedTurn !== null) return turns.find((x) => x.id === u.pinnedTurn) || turns[turns.length - 1] || null;
  return turns[turns.length - 1] || null;
}

/* ---------- keys and provider bodies (keys stay in memory; sessionStorage only when asked) ---------- */
export function setPageKey(which, value) {
  store.keys[which] = value || '';
  if (store.keys.remember) ssSet(`lab.key.${which}`, store.keys[which] || null);
}
export function setRemember(on) {
  store.keys.remember = !!on;
  ssSet('lab.key.remember', on ? true : null);
  for (const w of ['chat', 'embedding']) ssSet(`lab.key.${w}`, on && store.keys[w] ? store.keys[w] : null);
}
export function providerBody() {
  const k = store.keys; const body = { openai: {}, embedding: {} };
  if (k.chat) body.openai.apiKey = k.chat;
  if (k.ignoreEnvKey) body.openai.ignoreEnvKey = true;
  if (k.embedding) body.embedding.apiKey = k.embedding;
  return body;
}
/** Chat key state as the UI sees it: 'page' | 'env' | 'none' (no value is ever read back). */
export function chatKeyState() {
  const s = store.data.settings; const k = store.keys;
  if (k.chat) return 'page';
  if (!k.ignoreEnvKey && s?.chat?.keySource === 'env') return 'env';
  if (!s) return 'unknown';
  return 'none';
}

/* ---------- LabEvent reducer ---------- */
const subs = new Set();
export function onLabEvents(fn) { subs.add(fn); return () => subs.delete(fn); }
function emit(evs) { for (const fn of subs) { try { fn(evs); } catch (err) { console.error(err); } } }

const FILE_EVENTS = new Set(['file.changed', 'file.saved', 'bootstrap.file_deleted', 'curation.written', 'flush.written', 'session_memory.written']);
/** Bus event types the chat log shows as system rows (views/chat.js). */
export const SYS_TYPES = new Set(['session.new', 'heartbeat.decided', 'settings.changed', 'workspace.reset', 'bootstrap.seeded', 'bootstrap.completed']);
// Events that invalidate the Diff tab list and the prompt preview (inspector/diff.js, inspector/prompt.js).
const DIFF_EVENT = /^(file\.|bootstrap\.file_deleted|curation\.|flush\.written|session_memory\.|promotion\.|dreaming\.|workspace\.reset|chat\.turn\.completed|live\.)/;
const PROMPT_EVENT = /^(file\.|bootstrap\.|settings\.changed|curation\.|flush\.written|session_memory\.|workspace\.reset)/;
/** Only the regions whose output depends on this event are rebuilt (loaders refresh their own). */
function regionsFor(type) {
  const u = store.ui; const r = new Set(['status']);
  if (FILE_EVENTS.has(type) || PROMPT_EVENT.test(type)) r.add('explorer');
  if (u.view === 'chat' && u.centerTab === 'view' && SYS_TYPES.has(type)) r.add('center');
  if (/^chat\.turn\./.test(type) || type === 'provider.check') r.add('top');
  const tab = u.inspectorTab;
  if (tab === 'timeline' || (u.view === 'live' && type.startsWith('live.'))) r.add('inspector');
  else if (tab === 'diff' && DIFF_EVENT.test(type)) r.add('inspector');
  else if (tab === 'prompt' && PROMPT_EVENT.test(type)) r.add('inspector');
  return [...r];
}
let pending = [];
// Dedupe on id + type + ts: a restarted server may reuse ids, so the id alone is not enough.
const seen = new Set();
const evKey = (ev) => `${ev.id}|${ev.type}|${ev.ts}`;
export function ingestEvent(ev) {
  const d = store.data;
  if (!ev || ev.type === undefined) return;
  const key = evKey(ev);
  if (seen.has(key)) return;
  seen.add(key);
  if (typeof ev.id === 'number' && ev.id > d.lastEventId) d.lastEventId = ev.id;
  d.events.push(ev);
  if (d.events.length > EVENT_RING) for (const old of d.events.splice(0, d.events.length - EVENT_RING)) seen.delete(evKey(old));
  const type = String(ev.type);
  const data = ev.data || {};
  if (FILE_EVENTS.has(type) && data.path) {
    d.changed.add(data.path);
    const cached = d.fileCache.get(data.path);
    if (cached) cached.stale = true;
    later('files', loadFiles, 150);
    later(`file:${data.path}`, () => reloadOpenFile(data.path), 160);
  }
  if (type === 'chat.turn.started') d.changed.clear();
  if (type === 'chat.turn.completed' || type === 'chat.turn.failed') { if (!store.stream) later('state', loadState, 200); }
  if (type === 'index.reindexed' || type.startsWith('search.')) later('index', loadIndex, 150);
  if (type === 'settings.changed' || type === 'provider.check') later('settings', loadSettings, 100);
  if (type === 'bootstrap.completed' || type === 'bootstrap.seeded' || type === 'workspace.reset' || type === 'session.new') { later('state', loadState, 150); later('files', loadFiles, 150); }
  if (type.startsWith('heartbeat.') || type === 'clock.changed') { if (d.heartbeat || store.ui.view === 'heartbeat') later('hb', loadHeartbeat, 200); }
  if (/^(promotion|dreaming|audit|repair|curation)\./.test(type)) { if (d.consolidation || store.ui.view === 'consolidation') later('cons', loadConsolidation, 200); }
  pending.push(ev);
  later('emit', () => { const evs = pending; pending = []; emit(evs); }, 30);
  refresh(...regionsFor(type));
}
/** A clean open file reloads on change; a dirty one keeps its draft and shows the conflict banner. */
async function reloadOpenFile(path) {
  const u = store.ui; const d = store.data;
  if (!u.openTabs.includes(path)) return;
  const before = d.fileCache.get(path);
  const dirtyDraft = u.drafts[path] !== undefined && before && u.drafts[path] !== before.content;
  if (dirtyDraft) { refresh('center'); return; }
  const after = await loadFile(path, { force: true });
  if (before?.content !== undefined && after?.content !== undefined && before.content !== after.content) {
    const a = before.content.split('\n'); const b = after.content.split('\n');
    const changed = new Set();
    b.forEach((line, i) => { if (a[i] !== line) changed.add(i + 1); });
    d.changedLines.set(path, changed);
  }
  refresh('center');
}

/* ---------- view switch ---------- */
export function setView(view) {
  store.ui.view = view; store.ui.centerTab = 'view';
  if (window.matchMedia('(max-width: 820px)').matches) store.ui.mobilePane = 'center';
  refresh('rail', 'center', 'mobile', 'inspector', 'status');
}
