// views/heartbeat.js: Heartbeat view over GET /api/lab/heartbeat, the run stream
// (POST /api/lab/heartbeat/run), the demo-only virtual clock and the pure reply parser.
import { h, icon, replace, fmtMs, fmtTime, fmtRelMin } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadHeartbeat, providerBody, chatKeyState } from '../store.js';
import { api, postStream } from '../api.js';
import { chip, btn, toggle, emptyState, failCard, skeleton, honesty } from '../ui/kit.js';
import { openDialog, toast } from '../ui/overlay.js';
import { promptPre } from '../inspector/common.js';
import { toolCard } from './chat.js';
import { fileEntry } from './explorer.js';

export function viewHead(title, ic, chips = [], actions = []) {
  return h('div', { class: 'view-head' }, h('div', { class: 'vh-title' }, icon(ic, 16), h('h2', { class: 'vh-name' }, title)), chips.length ? h('div', { class: 'vh-chips' }, chips) : null, actions.length ? h('div', { class: 'vh-actions' }, actions) : null);
}
export const card = (title, body, { ic = null, right = null, cls = '', target = null, testid = null } = {}) => h('section', { class: ['card', cls], 'data-target': target, 'data-testid': testid },
  title ? h('div', { class: 'card-head' }, ic ? icon(ic, 14) : null, h('h3', { class: 'card-title' }, title), h('span', { class: 'spacer' }), right) : null, h('div', { class: 'card-body' }, body));
const kv = (k, v) => h('div', { class: 'kv-grid-row' }, h('div', { class: 'kv-k' }, k), h('div', { class: 'kv-v' }, v));

export async function runHeartbeat({ fromChat = false } = {}) {
  const d = store.data;
  if (d.hbRunning) return null;
  const run = { id: null, ts: Date.now(), userMessage: '', systemSection: '', files: [], reply: '', toolCalls: [], decision: null, skipped: null, streaming: true };
  d.hbRunning = run;
  refresh('center', 'inspector');
  let final = null; let error = null;
  try {
    await postStream('/api/lab/heartbeat/run', { lightContext: store.ui.hbLightContext ?? undefined, ...providerBody() }, {
      onEvent: ({ event, data }) => {
        if (event === 'skipped') run.skipped = data.reason;
        else if (event === 'prompt') Object.assign(run, { userMessage: data.userMessage ?? '', systemSection: data.systemSection ?? '', files: data.files || [] });
        else if (event === 'tool_call') run.toolCalls.push({ id: data.id, name: data.name, arguments: data.arguments, status: 'running' });
        else if (event === 'tool_result') { const tc = run.toolCalls.find((x) => x.id === data.id); if (tc) Object.assign(tc, data, { status: data.ok === false ? 'error' : 'ok' }); }
        else if (event === 'assistant_delta') run.reply += data.text ?? '';
        else if (event === 'decision') run.decision = data;
        else if (event === 'flush') run.flushReason = data.decision?.reason || data.reason;
        else if (event === 'done') final = data.run || data;
        else if (event === 'error') error = data;
        if (store.ui.view === 'heartbeat') refresh('center', 'inspector');
      },
    });
  } catch (err) { error = err.missing ? { missing: true, module: err.module || err.path, error: err.message } : { error: err.message, code: err.code }; }
  d.hbRunning = null;
  d.hbLastError = error;
  await loadHeartbeat();
  if (final?.id !== undefined) store.ui.hbSelected = final.id;
  refresh('center', 'inspector', 'status');
  if (error) toast(error.missing ? t('state.waitsFor', { m: error.module }) : `${t('hb.runFailed')}: ${error.error || ''}`, { tone: error.missing ? 'info' : 'danger' });
  else if (fromChat || store.ui.view !== 'heartbeat') {
    const r = final || run;
    const msg = r.skipped ? t('hb.toastSkipped', { r: r.skipped }) : r.decision?.delivered ? t('hb.toastDelivered') : t('hb.toastAck');
    toast(msg, { tone: r.decision?.delivered ? 'warn' : 'ok', action: { label: t('view.heartbeat'), onClick: () => store.actions.setView('heartbeat') } });
  }
  return final;
}
async function shiftClock(ms) {
  try {
    await api.post('/api/lab/clock', ms === null ? { reset: true } : { offsetMs: (store.data.heartbeat?.clock?.offsetMs || 0) + ms });
  } catch (err) { toast(err.missing ? t('state.waitsFor', { m: err.module || err.path }) : err.message, { tone: 'warn' }); }
  loadHeartbeat();
}
async function runStrip(text) {
  const u = store.ui;
  u.hbStripInput = text;
  try { u.hbStripResult = { text, res: await api.post('/api/lab/heartbeat/strip', { text, ackMaxChars: store.data.heartbeat?.ackMaxChars }) }; }
  catch (err) { u.hbStripResult = { text, err }; }
  refresh('center');
}

function decisionChip(r) {
  if (r.skipped) return chip({ label: `${t('hb.skipped')}: ${r.skipped} · ${t('hb.noModelCall')}`, tone: 'neutral', ic: 'minus', testid: 'hb-decision' });
  if (!r.decision) return chip({ label: t('hb.awaitingDecision'), tone: 'neutral', ic: 'clock' });
  return r.decision.delivered ? chip({ label: t('hb.delivered'), tone: 'accent', ic: 'send', testid: 'hb-decision' }) : chip({ label: t('hb.ack'), tone: 'ok', ic: 'check', testid: 'hb-decision' });
}
function runCard(run, running) {
  const d = run.decision;
  const tools = run.toolCalls || [];
  const rows = run.skipped ? [kv(t('hb.decision'), decisionChip(run))] : [
    kv(t('hb.userPrompt'), promptPre(run.userMessage || '')),
    kv(t('hb.systemSection'), promptPre(run.systemSection || '')),
    kv(t('hb.files'), h('div', { class: 'chip-wrap' }, chip({ label: t('hb.kindHeartbeat'), tone: 'info' }), (run.files || []).map((f) => chip({ label: f, tone: f === 'HEARTBEAT.md' ? 'info' : 'neutral', cls: 'chip-mono' })), run.lightContext ? chip({ label: 'lightContext', tone: 'warn' }) : null)),
    tools.length ? kv(t('prompt.tools'), h('div', { class: 'tool-list' }, tools.map((tc) => toolCard(tc)))) : null,
    kv(t('hb.reply'), running && !run.reply ? h('span', { class: 'caret' }) : h('pre', { class: 'ptext' }, run.reply || '')),
    kv(t('hb.decision'), h('div', { class: 'chip-wrap' }, decisionChip(run), d ? h('span', { class: 'muted small' }, t('hb.remainder', { n: d.remainderChars, m: store.data.heartbeat?.ackMaxChars ?? '—' })) : null, run.flushReason ? chip({ label: `flush: ${run.flushReason}`, tone: 'neutral' }) : null)),
  ];
  return card(`${t('hb.run')} #${run.id ?? '…'} · ${fmtTime(run.ts, { seconds: false })}${run.ms ? ` · ${fmtMs(run.ms)}` : ''}`, h('div', { class: 'kv-grid' }, rows), { ic: 'play', cls: running ? 'is-running' : '', testid: 'hb-run', right: run.dueTasks?.length ? h('span', { class: 'muted small' }, `${t('hb.dueTasks')}: ${run.dueTasks.join(', ')}`) : null });
}
function historyCard(runs) {
  const u = store.ui;
  const toggleSel = (id) => { const i = u.hbCompare.indexOf(id); if (i >= 0) u.hbCompare.splice(i, 1); else { u.hbCompare.push(id); if (u.hbCompare.length > 2) u.hbCompare.shift(); } refresh('center'); };
  return card(t('hb.history'), runs.length ? h('div', { class: 'hb-history' }, runs.slice(0, 20).map((r) => h('div', { class: ['hist-row', u.hbCompare.includes(r.id) ? 'is-selected' : '', u.hbSelected === r.id ? 'is-current' : ''] },
    h('input', { type: 'checkbox', checked: u.hbCompare.includes(r.id), onchange: () => toggleSel(r.id), 'aria-label': t('hb.selectRun', { n: r.id }) }),
    h('button', { type: 'button', class: 'link mono', onclick: () => { u.hbSelected = r.id; refresh('center', 'inspector'); } }, `#${r.id}`),
    h('span', { class: 'num muted' }, fmtTime(r.ts, { seconds: false })),
    r.skipped ? chip({ label: `${t('hb.skipped')}: ${r.skipped}`, tone: 'neutral', cls: 'chip-xs' }) : r.decision?.delivered ? chip({ label: t('hb.delivered'), tone: 'accent', cls: 'chip-xs' }) : chip({ label: 'OK', tone: 'ok', cls: 'chip-xs' }),
    h('span', { class: 'hist-reply muted' }, r.reply ? r.reply.slice(0, 80) : '')))) : h('div', { class: 'muted' }, t('hb.noRuns')),
  { ic: 'clock', target: 'hb-compare', right: btn(t('hb.compare'), { size: 'xs', disabled: u.hbCompare.length !== 2, onClick: () => compareRuns(runs), ic: 'diff' }) });
}
function compareRuns(runs) {
  const [a, b] = store.ui.hbCompare.map((id) => runs.find((r) => r.id === id)).filter(Boolean).sort((x, y) => x.id - y.id);
  if (!a || !b) return;
  const col = (r) => h('div', { class: 'cmp-col' }, h('div', { class: 'cmp-head' }, `#${r.id} · ${fmtTime(r.ts, { seconds: false })}`),
    r.skipped ? h('div', { class: 'muted' }, `${t('hb.skipped')}: ${r.skipped}`) : [promptPre(r.userMessage || ''), h('div', { class: 'muted small' }, t('hb.systemSection')), promptPre(r.systemSection || ''), h('div', { class: 'muted small' }, t('hb.reply')), h('pre', { class: 'ptext' }, r.reply || ''), h('div', null, decisionChip(r))]);
  const dlg = openDialog({ title: t('hb.compareTitle'), body: h('div', { class: 'cmp' }, col(a), col(b)), cls: 'dialog-lg', actions: [btn(t('act.close'), { onClick: () => dlg.close() })] });
}
function stripCard() {
  const u = store.ui; const sr = u.hbStripResult;
  const input = h('input', { class: 'input mono', value: u.hbStripInput, 'aria-label': t('hb.replyText'), placeholder: 'HEARTBEAT_OK', 'data-testid': 'hb-strip-input', onkeydown: (e) => { if (e.key === 'Enter') runStrip(e.target.value); } });
  const res = sr?.res;
  return card(t('hb.parser'), [
    h('div', { class: 'sf-row' }, input, btn(t('hb.parse'), { size: 'sm', onClick: () => runStrip(input.value) })),
    sr?.err ? failCard(sr.err, { compact: true }) : res ? h('div', { class: 'sf-row sf-wrap', 'data-testid': 'hb-strip-result' }, h('span', { class: 'mono muted small' }, `"${sr.text}"`), h('span', { class: 'arrow muted', 'aria-hidden': 'true' }, '→'),
      res.shouldSkip ? chip({ label: t('hb.skip'), tone: 'ok', ic: 'check' }) : chip({ label: t('hb.deliver'), tone: 'accent', ic: 'send' }),
      h('span', { class: 'mono muted small' }, `"${res.text ?? ''}"`), res.didStrip ? chip({ label: 'didStrip', tone: 'neutral', cls: 'chip-xs' }) : null) : null,
  ], { ic: 'scale', target: 'hb-strip', testid: 'hb-strip', right: h('span', { class: 'chip chip-xs tone-neutral' }, t('hb.parserOnly')) });
}

export function renderHeartbeat(body) {
  const d = store.data; const u = store.ui;
  const hb = d.heartbeat;
  if (!hb && !d.heartbeatErr) loadHeartbeat();
  const strip = store.actions.scenarioStrip?.() || null;
  if (!hb) {
    replace(body, strip, viewHead(t('view.heartbeat'), 'heart-pulse'), h('div', { class: 'view-scroll' }, d.heartbeatErr ? failCard(d.heartbeatErr, { onRetry: () => loadHeartbeat() }) : skeleton(6)));
    return;
  }
  const file = hb.file || {};
  const fileState = !file.exists ? { label: t('hb.fileMissing'), tone: 'neutral' } : file.effectivelyEmpty ? { label: t('hb.fileEmpty'), tone: 'neutral' } : { label: t('hb.fileActive'), tone: 'ok' };
  const pp = fileEntry('PROACTIVE_PREFERENCES.md');
  const ppState = !pp ? null : (pp.badges || []).includes('outside_layout') ? t('badge.outside_layout') : (pp.badges || []).includes('empty') ? t('badge.empty') : (pp.badges || []).includes('injected') ? t('badge.injected') : t('badge.excluded');
  const now = hb.clock?.nowMs ?? Date.now(); const off = hb.clock?.offsetMs || 0;
  const running = d.hbRunning;
  const tasks = hb.tasks || [];
  const taskTable = tasks.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['task', 'interval', 'prompt', 'last', 'next', 'state'].map((c) => h('th', { scope: 'col' }, t(`hb.col.${c}`))))),
    h('tbody', null, tasks.map((tk) => h('tr', { 'data-testid': 'hb-task' },
      h('td', { class: 'mono' }, tk.name), h('td', { class: 'mono' }, tk.interval),
      h('td', { class: 'td-clip', 'data-tip': tk.prompt }, tk.prompt),
      h('td', { class: 'num nowrap' }, tk.lastRunMs ? fmtTime(tk.lastRunMs, { seconds: false }) : '—'),
      h('td', { class: 'num nowrap' }, tk.nextDueMs ? fmtTime(tk.nextDueMs, { seconds: false }) : '—'),
      h('td', { class: 'td-state' }, tk.lastRunMs === null || tk.lastRunMs === undefined ? chip({ label: t('hb.neverRan'), tone: 'accent', ic: 'dot' }) : tk.due ? chip({ label: t('hb.due'), tone: 'accent', ic: 'dot' }) : chip({ label: `${t('hb.waiting')} (${fmtRelMin((tk.nextDueMs ?? now) - now)})`, tone: 'neutral', ic: 'clock' })))))))
    : h('div', { class: 'muted pad' }, t('hb.noTasks'));
  const latest = running || hb.runs?.find((r) => r.id === u.hbSelected) || hb.runs?.[0] || null;
  const noKey = chatKeyState() === 'none';
  replace(body, strip,
    viewHead(t('view.heartbeat'), 'heart-pulse', [
      chip({ label: `HEARTBEAT.md: ${fileState.label}`, tone: fileState.tone, onClick: () => store.actions.openFile('HEARTBEAT.md'), testid: 'hb-file-state' }),
      chip({ label: `${t('hb.every')} ${hb.every ?? '—'} · ${t('hb.noScheduler')}`, tone: 'neutral', ic: 'clock', title: t('hb.runtimeOnlyTip') }),
      chip({ label: `ack ≤ ${hb.ackMaxChars ?? '—'}`, tone: 'neutral' }),
      ppState ? chip({ label: `PROACTIVE_PREFERENCES.md: ${ppState}`, tone: 'ext', ic: 'puzzle', onClick: () => store.actions.openFile('PROACTIVE_PREFERENCES.md') }) : null,
    ].filter(Boolean)),
    h('div', { class: 'view-scroll' },
      hb.memoryTools === false ? honesty(t('hb.noMemoryTools'), 'warn', 'alert-triangle', { testid: 'hb-no-tools' }) : null,
      h('div', { class: 'hb-bar' },
        h('div', { class: 'vclock', 'data-testid': 'virtual-clock' },
          h('span', { class: 'vclock-k' }, icon('clock', 14), t('hb.virtualClock')),
          h('span', { class: ['vclock-v', 'num', off ? 'tone-text-warn' : ''] }, fmtTime(now, { seconds: false })),
          off ? h('span', { class: 'chip chip-xs tone-warn' }, `+${Math.round(off / 60000)} ${t('unit.min')}`) : null,
          btn(t('hb.plus10'), { size: 'xs', onClick: () => shiftClock(600_000) }), btn(t('hb.plus30'), { size: 'xs', onClick: () => shiftClock(1_800_000), target: 'hb-clock30' }), btn(t('hb.plus60'), { size: 'xs', onClick: () => shiftClock(3_600_000) }),
          btn(t('hb.clockReset'), { size: 'xs', kind: 'ghost', onClick: () => shiftClock(null), disabled: !off }),
          h('span', { class: 'chip chip-xs tone-warn', 'data-tip': t('hb.clockTip') }, 'demo-only')),
        h('div', { class: 'hb-run-group' },
          toggle({ checked: u.hbLightContext ?? !!hb.lightContext, onChange: (v) => { u.hbLightContext = v; refresh('center'); }, label: 'lightContext' }),
          btn(running ? t('hb.running') : t('hb.runNow'), { kind: 'primary', ic: 'play', onClick: () => runHeartbeat(), busy: !!running, disabled: noKey, title: noKey ? t('composer.noKey') : null, target: 'hb-run', testid: 'hb-run-btn' }))),
      card(t('hb.tasks'), [taskTable, hb.unparsedCount ? h('div', { class: 'muted small' }, t('hb.unparsed', { n: hb.unparsedCount })) : null], { ic: 'layers', right: h('span', { class: 'muted small mono' }, 'parse_heartbeat_tasks · is_task_due') }),
      latest ? runCard(latest, !!running) : emptyState({ title: t('hb.noRuns'), text: file.exists ? t('hb.noRunsText') : t('hb.fileMissingText'), level: 3 }),
      historyCard(hb.runs || []),
      stripCard()));
}
