// views/chat.js: Sohbet. Turn blocks, the live stage stepper (stages render in the order the
// server streams them), inline tool calls, memory-activity chips, system rows and the turn
// stream client (POST /api/lab/chat/stream via fetch + ReadableStream).
import { h, icon, replace, fmtMs, fmtTime } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, refresh, mergeTurns, providerBody, loadState, loadFiles, loadIndex, chatKeyState, loadTurn, SYS_TYPES } from '../store.js';
import { api, postStream } from '../api.js';
import { chip, btn, iconBtn, jsonDisclosure, emptyState, honesty, missingCard, howItWorks } from '../ui/kit.js';
import { openMenu, announce, toast } from '../ui/overlay.js';
import { markdown } from '../ui/markdown.js';
import { composerEl, updateComposer, SESSION_KINDS } from './composer.js';

const CHIP_TONE = { recall: 'info', write: 'accent', flush: 'accent', flush_skip: 'neutral', session_memory: 'accent', startup: 'info', bootstrap: 'ok', truncation: 'warn', heartbeat: 'accent', error: 'danger', tool: 'neutral', refused: 'warn' };
const CHIP_IC = { recall: 'search', write: 'plus', flush: 'plus', flush_skip: 'minus', session_memory: 'plus', startup: 'layers', bootstrap: 'check', truncation: 'scissors', heartbeat: 'heart-pulse', error: 'alert-octagon', tool: 'tool', refused: 'alert-triangle' };

export function identityName() { return store.data.snap?.identityName || t('chat.assistant'); }
export const stageLabel = (name) => (has(`stage.${name}`) ? t(`stage.${name}`) : name);

/* ---------- streaming ---------- */
let abortCtl = null;
export function stopStream() { if (abortCtl) { store.stream && (store.stream.stopped = true); abortCtl.abort(); } }

function ensureChatVisible() {
  const u = store.ui;
  if (u.view !== 'chat' || u.centerTab !== 'view') { u.view = 'chat'; u.centerTab = 'view'; refresh('rail'); }
  if (window.matchMedia('(max-width: 820px)').matches) { u.mobilePane = 'center'; refresh('mobile'); }
}

export async function runTurn(text, kind = 'main', { reset = false } = {}) {
  if (store.stream) return null;
  ensureChatVisible();
  const st = { user: text, kind, reset, stages: [], text: '', tools: [], recall: null, prompt: null, flush: null, curation: [], error: null, turnId: null, startedAt: Date.now(), stopped: false, done: null };
  store.stream = st;
  abortCtl = new AbortController();
  updateComposer();
  store.actions.renderCenterNow();
  const body = { message: text, sessionKind: kind, ...providerBody() };
  if (reset) body.reset = true;
  let turnDone = null;
  try {
    await postStream('/api/lab/chat/stream', body, {
      signal: abortCtl.signal,
      onEvent: ({ event, data }) => {
        switch (event) {
          case 'turn_started': st.turnId = data.turnId ?? data.id ?? st.turnId; if (data.sessionKey) st.sessionKey = data.sessionKey; break;
          case 'stage': upsertStage(st, data); if (data.turnId) st.turnId = data.turnId; paintStepper(); break;
          case 'recall': st.recall = data; break;
          case 'prompt': st.prompt = data; break;
          case 'tool_call': st.tools.push({ id: data.id, name: data.name, arguments: data.arguments, status: 'running' }); paintTools(); break;
          case 'tool_result': { const tc = st.tools.find((x) => x.id === data.id) || st.tools.find((x) => x.name === data.name && x.status === 'running'); if (tc) Object.assign(tc, data, { status: data.ok === false ? 'error' : 'ok' }); else st.tools.push({ ...data, status: data.ok === false ? 'error' : 'ok' }); paintTools(); break; }
          case 'assistant_delta': st.text += data.text ?? ''; paintText(); break;
          case 'curation': st.curation.push(data); break;
          case 'flush': st.flush = data; break;
          case 'turn_done': turnDone = data.turn || data; if (data.detail) store.data.details.set(turnDone.id, data.detail); break;
          case 'error': st.error = data; break;
          default: break;
        }
      },
    });
  } catch (err) {
    if (err?.name === 'AbortError') st.stopped = true;
    else if (err?.missing) st.error = { error: err.message, code: 'module_missing', module: err.module || err.path, missing: true };
    else st.error = { error: err.message, code: err.code || (err.status ? `http_${err.status}` : 'network'), status: err.status };
  }
  abortCtl = null;
  if (turnDone) {
    mergeTurns([turnDone]);
    if (store.ui.follow) store.ui.pinnedTurn = null;
    store.data.localTurns = (store.data.localTurns || []).filter((x) => x.id !== turnDone.id);
  } else {
    // A failed or stopped turn the server did not summarise stays visible locally with its error.
    const local = { id: st.turnId ?? `local-${Date.now()}`, local: true, sessionKind: kind, startedAt: st.startedAt, ms: Date.now() - st.startedAt, user: text, assistant: st.text, chips: [], stopped: st.stopped, error: st.error, reset, stages: st.stages, tools: st.tools };
    store.data.localTurns = [...(store.data.localTurns || []), local];
  }
  store.stream = null;
  updateComposer();
  await Promise.all([loadState(), loadFiles(), loadIndex()]);
  if (turnDone?.id !== undefined) loadTurn(turnDone.id, { force: true });
  refresh('center', 'inspector', 'explorer', 'status', 'top');
  const n = turnDone?.chips?.length ?? 0;
  if (st.error) announce(t('chat.failedAnnounce', { c: st.error.code || st.error.stage || 'error' }), true);
  else if (st.stopped) announce(t('chat.stopped'));
  else announce(t('chat.doneAnnounce', { n }));
  return turnDone;
}
function upsertStage(st, data) {
  const i = st.stages.findIndex((x) => x.name === data.name);
  if (i >= 0) st.stages[i] = { ...st.stages[i], ...data }; else st.stages.push({ ...data });
}

/* ---------- commands ---------- */
export async function runCommand(raw) {
  const [cmd, ...rest] = raw.split(' '); const arg = rest.join(' ').trim();
  const c = cmd.toLocaleLowerCase('tr');
  if (c === '/new' || c === '/reset') return sessionNew(c.slice(1), arg);
  if (c === '/flush') return forceFlush();
  if (c === '/heartbeat') { store.actions.runHeartbeat({ fromChat: true }); return null; }
  if (c === '/ara') { store.actions.searchMemory(arg); return null; }
  if (c === '/tür' || c === '/tur') {
    if (SESSION_KINDS.includes(arg)) { store.ui.composerKind = arg; updateComposer(); toast(t('chat.nextKind', { k: arg }), { tone: 'info' }); }
    else toast(t('chat.unknownKind', { k: arg || '—' }), { tone: 'warn' });
    return null;
  }
  toast(t('chat.unknownCommand', { c: cmd }), { tone: 'warn' });
  return null;
}
async function sessionNew(command, text) {
  ensureChatVisible();
  let res;
  try {
    res = await api.post('/api/lab/session/new', { command, text: text || undefined, sessionKind: store.ui.composerKind, ...providerBody() });
  } catch (err) {
    pushLocalRow({ kind: err.missing ? 'missing' : 'error', text: err.missing ? t('state.waitsFor', { m: err.module || err.path }) : `${command}: ${err.message}` });
    refresh('center');
    return null;
  }
  pushLocalRow({ kind: 'session', command, text, sessionMemory: res?.sessionMemory?.path || null, startup: res?.startup || null, sessionId: res?.sessionId, sessionKey: res?.sessionKey || null });
  await Promise.all([loadState(), loadFiles()]);
  if (!text) {
    // Bare /new or /reset: the reset turn streams separately; a 501 shows "henüz yok: reset istemi".
    if (chatKeyState() === 'none') return res;
    return runTurn('', store.ui.composerKind, { reset: true });
  }
  if (chatKeyState() === 'none') return res;
  return runTurn(text, store.ui.composerKind);
}
async function forceFlush() {
  ensureChatVisible();
  try {
    const res = await api.post('/api/chat/flush', { forced: true, ...providerBody() });
    const reason = res?.decision?.reason || res?.flush?.parsed?.reason || res?.reason || '—';
    const wrote = res?.flush?.parsed?.shouldWrite ?? res?.wrote;
    pushLocalRow({ kind: 'flush', text: t(wrote ? 'chat.flushWrote' : 'chat.flushNoWrite', { r: reason }), payload: res });
  } catch (err) {
    pushLocalRow({ kind: err.missing ? 'missing' : 'error', text: err.missing ? t('state.waitsFor', { m: err.module || err.path }) : `/flush: ${err.message}`, payload: err.body });
  }
  await Promise.all([loadState(), loadFiles()]);
  refresh('center');
}
function pushLocalRow(row) {
  store.data.localRows = [...(store.data.localRows || []), { ...row, ts: Date.now(), local: true }];
}

/* ---------- rendering: stepper, tools, text (patched in place while streaming) ---------- */
function stageNode(stg, running) {
  const status = stg.status === 'run' || stg.status === 'running' ? 'run' : stg.status || 'none';
  const ic = { ok: 'check', run: null, none: 'circle', skip: 'minus', fail: 'x' }[status];
  return h('span', { class: ['stage', `is-${status}`], role: 'listitem', 'data-tip': stg.detail || stg.reason || null },
    ic ? icon(ic, 10) : h('span', { class: 'spinner spinner-xs' }), h('span', { class: 'stage-name' }, stageLabel(stg.name)),
    status === 'ok' && stg.ms !== undefined ? h('span', { class: 'stage-ms' }, fmtMs(stg.ms)) : status === 'run' || running ? h('span', { class: 'stage-ms' }, '…') : null);
}
function paintStepper() {
  const el = document.querySelector('[data-pending] .stepper'); const st = store.stream;
  if (!el || !st) return;
  replace(el, st.stages.map((s) => stageNode(s, false)), h('span', { class: 'stepper-stop' }, btn(t('composer.stop'), { size: 'xs', kind: 'ghost', kbd: 'Esc', onClick: stopStream })));
}
function paintText() {
  const el = document.querySelector('[data-pending] .stream-text'); if (el && store.stream) el.textContent = store.stream.text;
  scrollLog();
}
function paintTools() {
  const el = document.querySelector('[data-pending] .tool-list'); if (!el || !store.stream) return;
  replace(el, store.stream.tools.map((tc) => toolCard(tc)));
}
export function toolCard(tc, { onExpand = null } = {}) {
  const status = tc.status || (tc.ok === false ? 'error' : tc.ok === true ? 'ok' : 'running');
  const refused = tc.refused || tc.result?.refused || tc.result?.status === 'refused';
  const tone = status === 'error' ? 'danger' : refused ? 'warn' : status === 'ok' ? 'ok' : 'neutral';
  const d = h('details', { class: ['tool-card', `tone-${tone}`], 'data-testid': 'tool-call' },
    h('summary', null, icon('tool', 12), h('span', { class: 'tool-name mono' }, tc.name || '?'),
      status === 'running' ? h('span', { class: 'spinner spinner-xs' }) : chip({ label: refused ? t('tool.refused') : status === 'ok' ? t('tool.ok') : t('tool.error'), tone, ic: refused ? 'alert-triangle' : status === 'ok' ? 'check' : 'alert-octagon', cls: 'chip-xs' }),
      tc.ms !== undefined ? h('span', { class: 'muted small mono' }, fmtMs(tc.ms)) : null,
      tc.summary ? h('span', { class: 'tool-sum muted small' }, tc.summary) : null),
    h('div', { class: 'tool-body' },
      tc.arguments !== undefined ? jsonDisclosure(tc.arguments, { title: t('tool.args') }) : null,
      tc.error ? h('div', { class: 'error-msg mono' }, String(tc.error)) : null,
      tc.result !== undefined ? jsonDisclosure(tc.result, { title: t('tool.result') }) : null,
      tc.arguments === undefined && tc.result === undefined && !tc.error ? h('div', { class: 'muted small' }, t('tool.detailInInspector')) : null));
  if (onExpand) d.addEventListener('toggle', () => { if (d.open) onExpand(); }, { once: true });
  return d;
}

/* ---------- chips ---------- */
const animated = new Set();
// A flush chip is a write only when the server says so (source/family); a decision chip is neutral.
const isFlushSkip = (c) => c.type === 'flush' && (c.source === 'skip' || c.family === 'neutral' || c.wrote === false);
function chipTone(c) {
  if (c.refused) return 'warn';
  if (c.tone) return c.tone;
  if (c.type === 'recall' && !c.count) return 'neutral';
  if (isFlushSkip(c)) return 'neutral';
  return CHIP_TONE[c.type] || 'neutral';
}
const chipIcon = (c) => (c.refused ? 'alert-triangle' : isFlushSkip(c) ? 'minus' : CHIP_IC[c.type]);
function turnChips(turn) {
  const entering = !animated.has(turn.id); animated.add(turn.id);
  const row = h('div', { class: ['chip-row', entering ? 'is-entering' : ''], role: 'group', 'aria-label': t('chat.chipsAria'), 'data-testid': 'chip-row' });
  (turn.chips || []).forEach((c, i) => {
    const el = chip({ label: c.label, tone: chipTone(c), ic: chipIcon(c), ext: !!c.extension, aria: c.aria || c.label, testid: `chip-${c.type}`, title: c.detail || null, onClick: () => chipClick(turn, c) });
    el.style.setProperty('--i', String(Math.min(i, 5)));
    el.tabIndex = i === 0 ? 0 : -1;
    row.append(el);
  });
  row.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const items = [...row.querySelectorAll('.chip')]; const i = items.indexOf(document.activeElement);
    const n = items[(i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length];
    items.forEach((x) => { x.tabIndex = x === n ? 0 : -1; }); n.focus(); e.preventDefault();
  });
  return row;
}
function chipClick(turn, c) {
  const u = store.ui;
  u.follow = false; u.pinnedTurn = turn.id;
  if (c.type === 'recall') store.actions.openInspector('memory');
  else if (c.type === 'write' || c.type === 'refused') { u.diffBase = 'turn'; store.actions.openInspector('diff'); }
  else if (c.type === 'flush') { u.openSections.add('flush'); store.actions.openInspector('prompt'); }
  else if (c.type === 'session_memory' && c.target) store.actions.openFile(c.target);
  else if (c.type === 'startup') { u.openSections.add('startup'); store.actions.openInspector('prompt'); }
  else if (c.type === 'truncation') { u.openSections.add('notices'); store.actions.openInspector('prompt'); }
  else if (c.type === 'tool') { u.openSections.add('tools'); store.actions.openInspector('prompt'); }
  else if (c.type === 'heartbeat') store.actions.setView('heartbeat');
  else if (c.type === 'bootstrap') store.actions.openInspector('timeline');
  else if (c.type === 'error') document.querySelector(`[data-turn="${turn.id}"] .error-card`)?.focus();
  refresh('center', 'inspector');
}

/* ---------- turn block ---------- */
function turnBlock(turn) {
  const u = store.ui;
  const pinned = !u.follow && u.pinnedTurn === turn.id;
  const failed = !!(turn.error || turn.failedStage);
  const detail = store.data.details.get(turn.id);
  const tools = turn.tools || detail?.toolCalls || turn.toolCalls || [];
  const key = turn.sessionKey || turn.sessionId;
  const el = h('article', { class: ['turn', pinned ? 'is-pinned' : '', failed ? 'is-failed' : '', turn.stopped ? 'is-stopped' : ''], 'data-turn': String(turn.id), tabindex: '-1', 'data-testid': 'turn-block', 'aria-label': t('chat.turnAria', { n: turn.id }) },
    h('header', { class: 'turn-head' },
      h('span', { class: 'turn-no' }, typeof turn.id === 'number' ? `#${turn.id}` : '#—'),
      h('span', { class: 'kind-tag', 'data-kind': turn.sessionKind }, turn.sessionKind || 'main'),
      key ? h('span', { class: 'turn-key mono', 'data-tip': `${t('chat.sessionKey')}: ${key}` }, String(key).slice(0, 18)) : null,
      turn.reset ? h('span', { class: 'chip tone-info chip-xs' }, t('chat.resetTurn')) : null,
      h('span', { class: 'turn-meta' }, fmtTime(turn.startedAt)),
      turn.ms !== undefined ? h('span', { class: 'turn-meta' }, fmtMs(turn.ms)) : null,
      turn.stopped ? h('span', { class: 'chip tone-warn chip-xs' }, t('chat.stoppedTag')) : null,
      turn.engine?.model ? h('span', { class: 'turn-engine-real mono', 'data-tip': `${turn.engine.provider || ''} · ${turn.engine.model}` }, turn.engine.model) : null,
      h('span', { class: 'spacer' }),
      turn.local ? null : btn(t('chat.inspect'), { size: 'xs', kind: 'ghost', ic: 'layers', cls: 'btn-compact', onClick: () => { u.follow = false; u.pinnedTurn = turn.id; store.actions.openInspector(u.inspectorTab || 'prompt'); refresh('center'); }, title: t('chat.inspectTip') })),
    // A reset turn stores `[memory-core session new]` as its user text; it renders as the system row.
    turn.user && !turn.reset ? h('div', { class: 'msg msg-user' }, h('span', { class: 'role' }, t('chat.you')), h('div', { class: 'msg-text' }, turn.user))
      : h('div', { class: 'msg msg-sys' }, h('span', { class: 'role' }, t('chat.system')), h('div', { class: 'msg-text muted' }, t('chat.resetTurnNote'))),
    tools.length ? h('div', { class: 'msg msg-tools' }, h('span', { class: 'role' }, t('tool.title', { n: tools.length })), h('div', { class: 'tool-list' }, tools.map((tc) => toolCard(tc, { onExpand: () => loadTurn(turn.id) })))) : null,
    failed ? errorCard(turn) : h('div', { class: 'msg msg-asst' }, h('span', { class: 'role role-asst' }, identityName()), h('div', { class: 'msg-text' }, markdown(turn.assistant || '', { onCite: (p, a, b) => store.actions.openFile(p, a, b) }))),
    (turn.chips || []).length ? turnChips(turn) : null);
  return el;
}
function errorCard(turn) {
  const e = turn.error || { stage: turn.failedStage, error: (turn.chips || []).find((c) => c.type === 'error')?.label, code: turn.errorCode };
  if (e.missing) return h('div', { class: 'error-card' }, missingCard({ module: e.module }));
  const code = e.code || null;
  return h('div', { class: 'error-card', role: 'alert', tabindex: '-1', 'data-testid': 'error-card' },
    h('div', { class: 'error-title' }, icon('alert-octagon', 14), `${t('state.error')}${e.stage ? `: ${stageLabel(e.stage)}` : ''}`, code ? h('span', { class: 'chip tone-danger chip-xs chip-mono' }, code) : null,
      e.redacted ? h('span', { class: 'chip tone-ok chip-xs', 'data-tip': t('chat.redactedTip') }, icon('check', 10), t('chat.redacted')) : null),
    h('div', { class: 'error-msg' }, String(e.error || e.message || '—')),
    h('div', { class: 'error-actions' },
      turn.user && !turn.reset ? btn(t('act.retry'), { size: 'sm', ic: 'rotate-ccw', onClick: () => runTurn(turn.user, turn.sessionKind || 'main') }) : null,
      /no_api_key|provider|network|http_/.test(code || '') ? btn(t('act.goSettings'), { size: 'sm', kind: 'ghost', onClick: () => store.actions.openSettings('chat') }) : null),
    jsonDisclosure(e, { title: t('act.details') }));
}
function systemRows() {
  const rows = [];
  const evs = store.data.events;
  // One divider per /new: this tab's own row (it carries the session-memory path and the startup
  // files from the response) replaces the bus session.new event with the same sessionKey.
  const localKeys = new Set((store.data.localRows || []).filter((r) => r.kind === 'session' && r.sessionKey).map((r) => r.sessionKey));
  let from = 0;
  for (let i = evs.length - 1; i >= 0; i--) if (evs[i].type === 'workspace.reset' || evs[i].type === 'bootstrap.seeded') { from = i; break; }
  for (const e of evs.slice(from)) {
    if (!SYS_TYPES.has(e.type)) continue;
    if (e.type === 'heartbeat.decided' && !e.data?.delivered) continue;
    if (e.type === 'session.new' && localKeys.has(e.data?.sessionKey)) continue;
    rows.push({ ts: e.ts, kind: e.type, text: e.summary, data: e.data || {} });
  }
  for (const r of store.data.localRows || []) rows.push({ ...r, kind: `local.${r.kind}` });
  return rows;
}
function systemRow(item) {
  const time = fmtTime(item.ts, { seconds: false });
  if (item.kind === 'session.new' || item.kind === 'local.session') {
    const d = item.data || item;
    const mem = d.sessionMemory?.path || d.sessionMemory || d.path || null;
    return h('div', { class: 'sysrow sysrow-session', role: 'group', 'aria-label': t('chat.newSession'), 'data-testid': 'system-row' },
      h('span', { class: 'sys-line', 'aria-hidden': 'true' }),
      h('span', { class: 'sys-body' }, icon('plus', 12), h('b', null, t('chat.newSession')), ` · ${time}${d.command ? ` · /${d.command}${d.text ? ` ${d.text}` : ''}` : ''}`,
        mem ? chip({ label: t('chip.sessionMemory'), tone: 'accent', ic: 'plus', onClick: () => store.actions.openFile(mem), title: mem, testid: 'chip-session_memory' }) : null,
        d.startup?.files?.length ? chip({ label: `${t('chip.startup')} ${d.startup.files.length}`, tone: 'info', ic: 'layers', title: d.startup.files.join(', ') }) : null),
      h('span', { class: 'sys-line', 'aria-hidden': 'true' }));
  }
  const map = {
    'heartbeat.decided': { ic: 'heart-pulse', title: t('chat.hbNotice'), tone: 'accent' },
    'bootstrap.completed': { ic: 'check', title: t('chat.bootstrapDone'), tone: 'ok' },
    'settings.changed': { ic: 'sliders', title: t('chat.settingChanged'), tone: 'neutral' },
    'workspace.reset': { ic: 'rotate-ccw', title: t('chat.workspaceReset'), tone: 'neutral' },
    'bootstrap.seeded': { ic: 'rotate-ccw', title: t('chat.workspaceReset'), tone: 'neutral' },
    'local.flush': { ic: 'minus', title: t('chat.flushRow'), tone: 'neutral' },
    'local.error': { ic: 'alert-octagon', title: t('state.error'), tone: 'danger' },
    'local.missing': { ic: 'minus', title: t('state.notYet'), tone: 'neutral' },
  }[item.kind] || { ic: 'info', title: item.kind, tone: 'neutral' };
  let text = item.kind === 'heartbeat.decided' ? (item.data.text || item.text) : item.text;
  // The server summary often repeats the row title in lower case ("çalışma alanı sıfırlandı (seeded)").
  const fold = (x) => String(x).toLocaleLowerCase('tr');
  if (text && fold(text).startsWith(fold(map.title))) text = text.slice(map.title.length).replace(/^[\s:·-]+/, '');
  return h('div', { class: ['sysrow', `sysrow-${item.kind.replace(/\W/g, '-')}`], role: 'note', 'data-testid': 'system-row' },
    h('span', { class: ['sys-ic', `tone-${map.tone}`], 'aria-hidden': 'true' }, icon(map.ic, 12)),
    h('span', { class: 'sys-title' }, map.title), h('span', { class: 'sys-time' }, time),
    text ? h('span', { class: 'sys-text' }, text) : null,
    item.kind === 'heartbeat.decided' ? btn(t('view.heartbeat'), { size: 'xs', kind: 'ghost', onClick: () => store.actions.setView('heartbeat') }) : null,
    item.payload ? jsonDisclosure(item.payload, { title: 'payload' }) : null);
}

function chatHeader() {
  const d = store.data; const sess = d.snap?.session;
  const turns = d.turns.filter((x) => !sess?.id || x.sessionId === sess.id).length;
  return h('div', { class: 'view-head' },
    h('div', { class: 'vh-title' }, icon('message', 16),
      h('h2', { class: 'vh-name' }, sess?.id ? `${t('chat.session')} ${String(sess.id).slice(0, 6)}` : t('view.chat')),
      sess?.kind ? h('span', { class: 'kind-tag', 'data-kind': sess.kind }, sess.kind) : null,
      h('span', { class: 'muted' }, `· ${turns} ${t('unit.turns')}`),
      sess?.key ? h('span', { class: 'muted mono small vh-hide-sm', 'data-tip': t('chat.sessionKey') }, sess.key) : null),
    h('div', { class: 'vh-actions' },
      btn(t('chat.newSession'), { size: 'sm', ic: 'plus', onClick: () => runCommand('/new'), title: '/new', cls: 'btn-compact', disabled: !!store.stream }),
      iconBtn('more', t('chat.menu'), (e) => openMenu(e.currentTarget, [
        { label: t('chat.forceFlush'), ic: 'minus', hint: '/flush', onSelect: () => runCommand('/flush') },
        { label: t('act.runHeartbeat'), ic: 'heart-pulse', hint: '/heartbeat', onSelect: () => runCommand('/heartbeat') },
        { label: t('chat.bareReset'), ic: 'rotate-ccw', hint: '/reset', onSelect: () => runCommand('/reset') },
        '-',
        { label: t('inspector.follow'), checked: store.ui.follow, onSelect: () => { store.ui.follow = !store.ui.follow; store.ui.pinnedTurn = null; refresh('center', 'inspector'); } },
      ], { align: 'end' }), { size: 'sm' })));
}

let logEl = null; let stickBottom = true;
const stackedMq = window.matchMedia('(max-width: 820px)');
function scrollLog() {
  // Only while the chat is on screen: in the stacked layouts the page itself scrolls.
  if (!logEl || !stickBottom || !logEl.offsetParent || store.ui.view !== 'chat' || store.ui.centerTab !== 'view') return;
  if (stackedMq.matches) { const se = document.scrollingElement; se.scrollTop = se.scrollHeight; } else logEl.scrollTop = logEl.scrollHeight;
}
export function renderChat(body) {
  const d = store.data;
  // Stick to the bottom when the previous log was at (or near) its end, or when there was none.
  const old = logEl && logEl.isConnected ? logEl : null;
  const se = document.scrollingElement;
  const wasBottom = !old || (stackedMq.matches ? se.scrollHeight - se.scrollTop - window.innerHeight < 80 : old.scrollHeight - old.scrollTop - old.clientHeight < 40);
  const prevTop = old ? old.scrollTop : null;
  logEl = h('div', { class: 'chat-log', role: 'log', 'aria-label': t('view.chat'), 'aria-live': 'off', 'data-testid': 'chat-log' });
  logEl.addEventListener('scroll', () => { stickBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40; });
  const turns = [...d.turns, ...(d.localTurns || [])];
  const items = [...turns.map((x) => ({ ts: x.startedAt ?? 0, turn: x })), ...systemRows().map((r) => ({ ts: r.ts ?? 0, row: r }))].sort((a, b) => a.ts - b.ts);
  if (!items.length && !store.stream) {
    if (!d.snap && d.snapErr) logEl.append(h('div', { class: 'pad-x' }, d.snapErr.missing ? missingCard(d.snapErr) : honesty(d.snapErr.message, 'danger', 'alert-octagon')));
    logEl.append(emptyState({ ic: 'message', title: t('chat.empty'), text: t('chat.emptyText'), testid: 'empty-chat', level: 3, actions: ['S06', 'S01', 'S09'].map((id) => btn(id, { size: 'sm', ic: 'play', onClick: () => store.actions.startScenario(id) })) }));
  } else {
    for (const it of items) logEl.append(it.turn ? turnBlock(it.turn) : systemRow(it.row));
  }
  const st = store.stream;
  if (st) {
    logEl.append(h('article', { class: 'turn is-streaming', 'data-pending': '1', 'aria-busy': 'true', 'data-testid': 'turn-block' },
      h('header', { class: 'turn-head' }, h('span', { class: 'turn-no' }, st.turnId ? `#${st.turnId}` : '#…'), h('span', { class: 'kind-tag', 'data-kind': st.kind }, st.kind), st.reset ? h('span', { class: 'chip tone-info chip-xs' }, t('chat.resetTurn')) : null, h('span', { class: 'turn-meta' }, t('chat.streaming'))),
      st.user ? h('div', { class: 'msg msg-user' }, h('span', { class: 'role' }, t('chat.you')), h('div', { class: 'msg-text' }, st.user)) : null,
      h('div', { class: 'msg msg-tools' }, h('span', { class: 'role' }, t('tool.label')), h('div', { class: 'tool-list' }, st.tools.map((tc) => toolCard(tc)))),
      h('div', { class: 'msg msg-asst' }, h('span', { class: 'role role-asst' }, identityName()), h('div', { class: 'msg-text' }, h('span', { class: 'stream-text' }, st.text), h('span', { class: 'caret', 'aria-hidden': 'true' }))),
      h('div', { class: 'stepper', role: 'list', 'aria-label': t('chat.stages'), 'data-testid': 'stage-stepper' })));
  }
  replace(body, store.actions.scenarioStrip?.() || null, chatHeader(), h('div', { class: 'how-bar' }, howItWorks('chat')), logEl, composerEl());
  updateComposer();
  if (st) paintStepper();
  requestAnimationFrame(() => { if (wasBottom || st) { stickBottom = true; scrollLog(); } else if (prevTop !== null && !stackedMq.matches) logEl.scrollTop = prevTop; });
}

export function focusTurnRelative(delta) {
  const turns = [...document.querySelectorAll('.chat-log .turn[data-turn]')];
  if (!turns.length) return;
  const cur = document.activeElement.closest?.('.turn[data-turn]');
  let i = turns.indexOf(cur);
  i = i < 0 ? (delta > 0 ? 0 : turns.length - 1) : Math.max(0, Math.min(turns.length - 1, i + delta));
  turns[i].focus(); turns[i].scrollIntoView({ block: 'nearest' });
}
export function pinFocusedTurn() {
  const cur = document.activeElement.closest?.('.turn[data-turn]');
  if (!cur) return false;
  const id = cur.dataset.turn; const num = Number(id);
  store.ui.follow = false; store.ui.pinnedTurn = Number.isNaN(num) ? id : num;
  refresh('center', 'inspector');
  return true;
}
