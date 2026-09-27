// scenarios/runner.js: runs a scenario over the real Lab. Each step gets a server diff mark
// (POST /api/lab/diff/mark); when the step's event arrives the runner gathers exactly the
// payloads its checks need and evaluates the pure checks from checks.js. Sending a message is
// always Doruk's keypress ("Yerleştir" only fills the composer); setting steps are restored
// to their previous values when the scenario ends.
import { lsSet, sleep } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, onLabEvents, loadState, loadTurn, loadHeartbeat, loadConsolidation, chatKeyState } from '../store.js';
import { api } from '../api.js';
import { confirmDialog, toast, pulse } from '../ui/overlay.js';
import { SCENARIOS, byId } from './catalog.js';

let localSeq = 0;
function pushLocal(type, summary, data = {}) {
  const ev = { id: `s${++localSeq}`, ts: Date.now(), type, category: 'senaryo', summary, data, local: true };
  store.data.events.push(ev);
  refresh('inspector', 'status');
}
export const sc = () => store.ui.scenario;

async function mark() {
  try { const r = await api.post('/api/lab/diff/mark', {}); return r?.markId ?? null; } catch { return null; }
}
function watermarks() {
  const d = store.data;
  const numericIds = d.events.map((e) => e.id).filter((x) => typeof x === 'number');
  return {
    eventId: numericIds.length ? Math.max(...numericIds) : 0,
    ts: Date.now(),
    turnIds: new Set(d.turns.map((x) => x.id)),
    localTurns: (d.localTurns || []).length,
    localRows: (d.localRows || []).length,
    hbRunIds: new Set((d.heartbeat?.runs || []).map((r) => r.id)),
    liveEvents: d.live.events.length,
    liveTurns: d.live.turns.length,
  };
}

/* ---------- start / steps ---------- */
export async function startScenario(id, { queue = null } = {}) {
  const def = byId(id); if (!def) return;
  if (sc() && !sc().finished) { toast(t('scn.alreadyRunning'), { tone: 'warn' }); return; }
  const base = await baseCtx();
  const blocked = def.blockedIf?.(base);
  if (blocked) {
    saveResult(id, { status: 'blocked', note: blocked, at: new Date().toISOString() });
    toast(`${id} · ${t('scn.status.blocked')}: ${t(blocked)}`, { tone: 'warn', action: { label: t('view.settings'), onClick: () => store.actions.setView('settings') } });
    refresh('center', 'rail');
    return;
  }
  const begin = async () => {
    const startMark = await mark();
    store.ui.scenario = { id, def, step: -1, startedAt: Date.now(), startMark, startWm: watermarks(), stepResults: def.steps.map(() => null), captured: [], manual: {}, queue, collapsed: false, finished: null, saved: {}, savedKeys: null, reply: {}, savedUi: { promptKind: store.ui.promptKind, promptMode: store.ui.promptMode, compare: store.ui.compare } };
    pushLocal('senaryo.started', `${id} ${t('scn.started')}`, { id });
    await beginStep(0);
  };
  if (def.setup?.reset) {
    confirmDialog({
      title: t('scn.setupTitle', { id }),
      lines: def.setup.reset === 'fresh' ? [t('settings.freshLine1'), t('settings.freshLine3')] : [t('settings.seedLine1')],
      confirmLabel: t('scn.setupConfirm'),
      onConfirm: async () => { const ok = await store.actions.resetWorkspace(def.setup.reset); if (ok) await begin(); },
    });
  } else await begin();
}
async function beginStep(i) {
  const s = sc(); if (!s) return;
  s.step = i; s.autoAdvance = null; s.evaluating = false;
  s.markId = await mark();
  s.wm = watermarks();
  const step = s.def.steps[i];
  pushLocal('senaryo.step', `${s.id} ${t('scenario.step')} ${i + 1}/${s.def.steps.length}`, { id: s.id, step: i + 1 });
  const view = step.view || (step.live ? 'live' : (step.act === 'send' || step.act === 'cmd') ? 'chat' : null);
  if (view && store.ui.view !== view) store.actions.setView(view);
  if (step.kind && step.act === 'send') store.ui.composerKind = step.kind;
  const base = await baseCtx();
  s.blocked = step.blockedIf?.(base) || null;
  if (s.blocked) s.stepResults[i] = step.checks.map(() => ({ status: 'blocked' }));
  refresh('center', 'status', 'inspector');
}
/** The server diff since a step's mark, read when the step ends: what later steps compare with. */
async function stepDiff(markId) {
  if (!markId) return null;
  try { const r = await api.get('/api/lab/diff', { since: `mark:${markId}` }); return Array.isArray(r) ? r : (r?.files || []); } catch { return null; }
}
export async function nextStep() {
  const s = sc(); if (!s || s.advancing) return;
  s.advancing = true; s.autoAdvance = null;
  const i = s.step;
  const diff = await stepDiff(s.markId);
  if (sc() !== s || s.step !== i) { s.advancing = false; return; }
  s.captured[i] = { diff: diff ?? s.captured[i]?.diff ?? [], sent: s.sent || s.captured[i]?.sent || '' };
  s.sent = '';
  s.advancing = false;
  if (i + 1 >= s.def.steps.length) { finish(); return; }
  beginStep(i + 1);
}
export async function stopScenario() {
  const s = sc(); if (!s) return;
  pushLocal('senaryo.stopped', `${s.id} ${t('scn.stopped')}`, { id: s.id });
  await restore(s);
  store.ui.scenario = null;
  refresh('center', 'status', 'inspector');
}
async function finish() {
  const s = sc(); if (!s) return;
  const flat = s.def.steps.flatMap((st, i) => st.checks.map((c, j) => ({ c, r: s.stepResults[i]?.[j] || { status: 'pending' }, step: i + 1 })));
  const autoChecks = flat.filter((x) => x.c.kind === 'auto' && x.r.status !== 'blocked');
  const modelChecks = flat.filter((x) => x.c.kind === 'model' && x.r.status !== 'blocked');
  const manualChecks = flat.filter((x) => x.c.kind === 'manual' && x.r.status !== 'blocked');
  const blockedN = flat.filter((x) => x.r.status === 'blocked').length;
  const pass = autoChecks.filter((x) => x.r.status === 'pass').length;
  const gaps = autoChecks.filter((x) => x.r.status === 'gap').length;
  const status = !autoChecks.length ? (blockedN ? 'blocked' : 'passed') : pass === autoChecks.length ? (blockedN ? 'partial' : 'passed') : pass + gaps === autoChecks.length ? 'partial' : 'failed';
  const res = {
    status, auto: [pass, autoChecks.length], model: [modelChecks.filter((x) => x.r.status === 'pass').length, modelChecks.length], manual: [manualChecks.filter((x) => x.r.status === 'pass').length, manualChecks.length],
    blocked: blockedN, at: new Date().toISOString(), ms: Date.now() - s.startedAt, note: gaps ? 'scn.knownGap' : blockedN ? 'scn.someBlocked' : null,
    detail: flat.map((x) => ({ step: x.step, kind: x.c.kind, label: x.c.label, status: x.r.status, value: x.r.value })),
  };
  saveResult(s.id, res);
  pushLocal('senaryo.finished', `${s.id} · ${t(`scn.status.${status}`)} · ${t('scn.kind.auto')} ${pass}/${autoChecks.length}`, { id: s.id, ...res });
  s.finished = res; s.step = s.def.steps.length;
  await restore(s);
  refresh('center', 'status', 'rail');
}
function saveResult(id, res) { store.ui.scenarioResults = { ...(store.ui.scenarioResults || {}), [id]: res }; lsSet('lab.scenarioResults', store.ui.scenarioResults); }
export function closeResult() {
  const q = sc()?.queue; store.ui.scenario = null; refresh('center', 'status');
  if (q?.length) startScenario(q[0], { queue: q.slice(1) });
}

/* ---------- settings the scenario changed are put back ---------- */
const getPath = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
function patchFor(path, value) { const parts = path.split('.'); const root = {}; let o = root; parts.slice(0, -1).forEach((k) => { o[k] = {}; o = o[k]; }); o[parts[parts.length - 1]] = value; return root; }
function flatten(obj, prefix = '') { return Object.entries(obj).flatMap(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v) ? flatten(v, `${prefix}${k}.`) : [[`${prefix}${k}`, v]])); }
async function applySettings(s, patch) {
  for (const [path] of flatten(patch)) if (!(path in s.saved)) s.saved[path] = getPath(store.data.settings, path);
  await store.actions.putSettings(patch, { quiet: true });
}
async function restorePaths(s, paths) {
  for (const p of paths) {
    if (!(p in s.saved)) continue;
    await store.actions.putSettings(patchFor(p, s.saved[p]), { quiet: true });
    delete s.saved[p];
  }
}
async function restore(s) {
  await restorePaths(s, Object.keys(s.saved));
  if (s.savedUi) { Object.assign(store.ui, s.savedUi); s.savedUi = null; store.actions.loadFiles?.(); }
  if (s.savedKeys) { Object.assign(store.keys, s.savedKeys); s.savedKeys = null; refresh('top', 'center'); }
}

/* ---------- step actions (Doruk triggers each one) ---------- */
export async function doStepAction(step, { send = false } = {}) {
  const s = sc(); if (!s) return;
  const a = store.actions; const u = store.ui;
  if (step.act === 'send' || step.act === 'cmd') {
    s.sent = step.text;
    if (step.live) { a.setView('live'); u.liveInput = step.text; refresh('center'); if (send) { await sleep(20); await a.liveSend(step.text); } return; }
    a.setView('chat'); await sleep(20);
    a.composerInsert(step.text, { send, kind: step.kind || 'main' });
    return;
  }
  if (step.act === 'look') {
    if (step.view) a.setView(step.view);
    if (step.promptKind) { u.promptKind = step.promptKind; u.promptMode = 'preview'; store.actions.loadFiles(); }
    if (step.compare) { u.compare = true; u.promptMode = 'turn'; u.follow = true; }
    if (step.tab) a.openInspector(step.tab);
    if (step.search) { Object.assign(u.search, step.search); await a.runSearch(); }
    if (step.target) setTimeout(() => pulse(step.target), 120);
    setTimeout(() => evaluate(), 200);
    return;
  }
  if (step.act === 'press') { if (step.view) a.setView(step.view); setTimeout(() => pulse(step.target), 160); return; }
  if (step.act === 'edit') {
    if (step.fixture) { a.openFile(step.path); await a.loadFile(step.path, { force: true }); const cap = store.data.settings?.budgets?.maxChars ?? 20000; a.fixture(step.path, cap + 5000); }
    else await a.applyEdit(step.path, { content: step.content ?? null, from: step.from ?? null, to: step.to ?? null, append: step.append ?? null });
    return;
  }
  if (step.act === 'reply') {
    a.setView('heartbeat');
    for (const input of step.inputs) {
      try { s.reply[input] = await api.post('/api/lab/heartbeat/reply', { text: input }); } catch (err) { s.reply[input] = null; s.replyErr = err; }
    }
    if (step.target) setTimeout(() => pulse(step.target), 120);
    evaluate();
    return;
  }
  if (step.act === 'legacyFile') {
    // Demo-only: a retired HEARTBEAT.md for the doctor migration (POST /api/lab/heartbeat/legacy-file).
    a.setView('heartbeat');
    try { await api.post('/api/lab/heartbeat/legacy-file', { content: step.content ?? '' }); } catch (err) { toast(err.message, { tone: 'warn' }); }
    await Promise.all([loadHeartbeat(), store.actions.loadFiles?.()]);
    if (step.then) setTimeout(() => pulse(step.then), 250);
    return;
  }
  if (step.act === 'scratch') {
    // The monitor scratch replaced HEARTBEAT.md (v2026.9.6): written by compare-and-swap.
    a.setView('heartbeat');
    try {
      const current = store.data.heartbeat?.scratch?.currentRevision ?? 0;
      await api.put('/api/lab/heartbeat/scratch', { content: step.content ?? null, expectedRevision: current });
    } catch (err) { toast(err.message, { tone: 'warn' }); }
    await loadHeartbeat();
    if (step.then) setTimeout(() => pulse(step.then), 250);
    return;
  }
  if (step.act === 'revert') {
    for (const p of step.paths || []) { try { await api.post('/api/lab/diff/revert', { path: p, since: s.startMark ? `mark:${s.startMark}` : 'session' }); } catch (err) { toast(`${p}: ${err.message}`, { tone: 'warn' }); } }
    await restorePaths(s, step.restore || []);
    await Promise.all([store.actions.loadFiles(), loadState()]);
    evaluate();
    return;
  }
  if (step.act === 'setting') {
    const ap = step.apply || {};
    if (ap.page?.suspendKeys) { s.savedKeys = { chat: store.keys.chat, ignoreEnvKey: store.keys.ignoreEnvKey }; store.keys.chat = ''; store.keys.ignoreEnvKey = true; }
    if (ap.page?.restoreKeys && s.savedKeys) { Object.assign(store.keys, s.savedKeys); s.savedKeys = null; }
    if (ap.restore) await restorePaths(s, ap.restore);
    if (ap.settings) await applySettings(s, ap.settings);
    refresh('top', 'center');
    if (step.then === 'check-embedding') await store.actions.checkProvider('embedding');
    await loadState();
    setTimeout(() => evaluate(), 150);
  }
}
export function insertAndSend() {
  const s = sc(); if (!s || s.finished) return;
  const st = s.def.steps[s.step];
  if (st && (st.act === 'send' || st.act === 'cmd')) doStepAction(st, { send: true });
}
export function setManual(i, checked) {
  const s = sc(); if (!s) return;
  s.manual[`${s.step}:${i}`] = checked;
  if (s.stepResults[s.step]) s.stepResults[s.step][i] = { status: checked ? 'pass' : 'manual' };
  refresh('center');
}

/* ---------- evaluation over real payloads ---------- */
async function baseCtx() {
  const d = store.data;
  return { today: d.snap?.today, now: Date.now(), keyState: chatKeyState(), settings: d.settings, snap: d.snap, heartbeat: d.heartbeat, index: d.index, files: d.files };
}
async function gather(s, step) {
  const d = store.data;
  const needs = new Set(); const fileSpecs = [];
  for (const c of step.checks) for (const n of c.needs || []) { if (typeof n === 'string') needs.add(n); else if (n.file) fileSpecs.push(n.file); }
  const wm = s.wm;
  if (needs.has('snap') || needs.has('turn')) await loadState();
  const chipEl = document.querySelector('[data-testid="chip-model"]');
  const ctx = { ...(await baseCtx()), captured: s.captured, prompts: {}, fileText: {}, reply: s.reply, modelChip: chipEl ? { grey: !!chipEl.querySelector('.dot-grey'), label: chipEl.textContent } : null };
  ctx.events = d.events.filter((e) => typeof e.id === 'number' ? e.id > wm.eventId : (!e.local && (e.ts ?? 0) >= wm.ts));
  ctx.scenarioEvents = d.events.filter((e) => typeof e.id === 'number' ? e.id > s.startWm.eventId : (!e.local && (e.ts ?? 0) >= s.startWm.ts));
  // server diff since the step mark (always: it also becomes the step's captured reference)
  try { const r = await api.get('/api/lab/diff', { since: s.markId ? `mark:${s.markId}` : 'session' }); ctx.diff = Array.isArray(r) ? r : (r?.files || []); } catch { ctx.diff = []; }
  s.lastDiff = ctx.diff;
  if (needs.has('scenarioDiff')) { try { const r = await api.get('/api/lab/diff', { since: s.startMark ? `mark:${s.startMark}` : 'reset' }); ctx.scenarioDiff = Array.isArray(r) ? r : (r?.files || []); } catch { ctx.scenarioDiff = []; } }
  if (needs.has('files')) { try { const r = await api.get('/api/lab/files', { sessionKind: 'main' }); ctx.files = Array.isArray(r) ? r : (r?.files || []); } catch { ctx.files = null; } }
  for (const n of needs) {
    if (!n.startsWith('prompt:')) continue;
    const kind = n.slice(7);
    try { ctx.prompts[kind] = await api.post('/api/lab/prompt/preview', { sessionKind: kind, layout: d.settings?.layout }); } catch { ctx.prompts[kind] = null; }
  }
  const newTurns = d.turns.filter((x) => !wm.turnIds.has(x.id) && typeof x.id === 'number');
  if (needs.has('turn') || needs.has('prevTurn')) {
    // A step that sends reads its own turn; a look step reads the latest turn of the scenario.
    const own = step.act === 'send' || step.act === 'cmd';
    const pool = own ? newTurns : d.turns.filter((x) => !s.startWm.turnIds.has(x.id) && typeof x.id === 'number');
    const last = pool[pool.length - 1] || null;
    ctx.turn = last ? await loadTurn(last.id, { force: true }) : null;
    if (ctx.turn) ctx.turnMs = ctx.turn.ms;
    const all = d.turns.filter((x) => typeof x.id === 'number');
    const i = last ? all.findIndex((x) => x.id === last.id) : -1;
    ctx.prevTurn = i > 0 ? await loadTurn(all[i - 1].id) : null;
  }
  if (needs.has('flushTurn')) {
    const scTurns = d.turns.filter((x) => !s.startWm.turnIds.has(x.id) && typeof x.id === 'number');
    ctx.flushTurn = null;
    for (const tr of scTurns.reverse()) { const det = await loadTurn(tr.id); if (det?.flush?.decision?.shouldRun) { ctx.flushTurn = det; break; } }
  }
  const localTurns = (d.localTurns || []).slice(wm.localTurns).reverse();
  ctx.lastError = localTurns.find((x) => x.error)?.error || null;
  if (ctx.turnMs === undefined && localTurns.length) ctx.turnMs = localTurns[0].ms;
  const rows = (d.localRows || []).slice(wm.localRows).filter((r) => r.kind === 'session');
  ctx.sessionNew = rows.length ? rows[rows.length - 1] : null;
  if (needs.has('search')) {
    const q = store.ui.search;
    ctx.search = q.error ? { error: q.error.message, results: [] } : q.result ? { ...q.result } : null;
  }
  if (needs.has('heartbeat') || needs.has('hbRun')) {
    const hb = await loadHeartbeat();
    ctx.heartbeat = hb;
    ctx.hbRun = (hb?.runs || []).find((r) => !wm.hbRunIds.has(r.id)) || null;
  }
  if (needs.has('consolidation')) ctx.consolidation = await loadConsolidation();
  if (needs.has('index')) ctx.index = await store.actions.loadIndex();
  if (needs.has('live')) {
    const L = d.live;
    // The workflow comes from the server: with a real model the streamed state was still the
    // previous step when the live check ran, while the server was already done (2026-09-26).
    try { L.state = await api.get('/api/live-task/state'); } catch { /* keep the streamed state */ }
    ctx.live = { state: L.state, events: L.events.slice(wm.liveEvents), engine: L.engine, summary: L.summary };
  }
  for (const spec of fileSpecs) {
    const p = typeof spec === 'function' ? spec(ctx) : spec;
    if (!p || p in ctx.fileText) continue;
    try { const f = await api.get('/api/lab/file', { path: p }); ctx.fileText[p] = f?.content ?? ''; } catch { ctx.fileText[p] = ''; }
  }
  return ctx;
}
export async function evaluate() {
  const s = sc(); if (!s || s.step < 0 || s.finished) return;
  // A request while an evaluation runs is queued: the running one may have read stale state.
  if (s.evaluating) { s.reEvaluate = true; return; }
  const i = s.step;
  const step = s.def.steps[i];
  if (s.blocked) { refresh('center'); return; }
  s.evaluating = true; s.reEvaluate = false; refresh('center');
  let ctx;
  try { ctx = await gather(s, step); } catch (err) { console.error('scenario gather', err); s.evaluating = false; refresh('center'); return; }
  if (sc() !== s || s.step !== i) { s.evaluating = false; return; } // the step moved on meanwhile
  const res = step.checks.map((c, i) => {
    if (c.kind === 'manual') return { status: s.manual[`${s.step}:${i}`] ? 'pass' : 'manual' };
    if (c.kind === 'observe') { let v = '—'; try { v = String(c.fn(ctx)); } catch { v = '—'; } return { status: 'observe', value: v }; }
    let ok = false;
    try { ok = !!c.fn(ctx); } catch (err) { console.warn('check', c.label, err); ok = false; }
    return { status: ok ? 'pass' : c.gap ? 'gap' : 'fail' };
  });
  if (sc() !== s || s.step !== i) { s.evaluating = false; return; }
  s.stepResults[i] = res;
  s.captured[i] = { diff: ctx.diff, sent: s.sent || s.captured[i]?.sent || '' };
  s.evaluating = false;
  if (s.reEvaluate) { s.reEvaluate = false; refresh('center'); evaluate(); return; }
  const autoOk = res.every((r, j) => step.checks[j].kind !== 'auto' || r.status === 'pass' || r.status === 'gap');
  pushLocal('senaryo.checked', `${s.id} ${t('scenario.step')} ${i + 1}: ${res.filter((r) => r.status === 'pass').length}/${res.length}`, { results: res.map((r) => r.status) });
  if (autoOk && step.checks.some((c) => c.kind === 'auto')) {
    const token = {}; s.autoAdvance = token;
    setTimeout(() => { if (sc() === s && s.step === i && s.autoAdvance === token) nextStep(); }, 600);
  }
  refresh('center', 'status');
}
/** Local completions (a turn stream, a live turn, a save) count like bus events for waitFor. */
export function notify(type) {
  const s = sc(); if (!s || s.step < 0 || s.finished || s.blocked) return;
  const step = s.def.steps[s.step];
  // An edit step with a follow-up button (Kaydet → Şimdi çalıştır) returns to its view after the save.
  if (type === 'file.saved' && step.act === 'edit' && step.then) {
    const view = step.view || s.def.view;
    if (view) store.actions.setView(view);
    setTimeout(() => pulse(step.then), 250);
  }
  if (!step.waitFor) return;
  if (new RegExp(`^(${step.waitFor})$`).test(type)) setTimeout(evaluate, 350);
}
onLabEvents((evs) => {
  const s = sc(); if (!s || s.step < 0 || s.finished || s.blocked) return;
  const step = s.def.steps[s.step];
  if (!step.waitFor) return;
  // While this tab streams a chat turn, its own completion notify() evaluates once the turn is merged.
  if (store.stream && /chat\.turn/.test(step.waitFor)) return;
  const re = new RegExp(`^(${step.waitFor})$`);
  if (evs.some((e) => re.test(e.type))) setTimeout(evaluate, 350);
});
export { SCENARIOS };
