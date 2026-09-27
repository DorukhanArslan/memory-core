// views/heartbeat.js: Heartbeat view over GET /api/lab/heartbeat in the v2026.9.6 shape: the
// agent's monitor scratch (PUT /api/lab/heartbeat/scratch, compare-and-swap), the automation
// jobs with their due state on the demo-only virtual clock, the leftover HEARTBEAT.md with its
// doctor findings (POST /api/lab/heartbeat/migrate), the run stream (POST /api/lab/heartbeat/run)
// and the reply decision rule (POST /api/lab/heartbeat/reply, no model).
import { h, icon, replace, fmtMs, fmtTime, fmtRelMin, fmtN } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadHeartbeat, providerBody, chatKeyState } from '../store.js';
import { api, postStream } from '../api.js';
import { chip, btn, toggle, emptyState, failCard, skeleton, honesty, apiErrorCard, howItWorks } from '../ui/kit.js';
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
  const run = { id: null, ts: Date.now(), userMessage: '', scratchShown: false, files: [], reply: '', toolCalls: [], decision: null, skipped: null, streaming: true };
  d.hbRunning = run;
  refresh('center', 'inspector');
  let final = null; let error = null;
  d.hbLastError = null;
  try {
    await postStream('/api/lab/heartbeat/run', { lightContext: store.ui.hbLightContext ?? undefined, ...providerBody() }, {
      onEvent: ({ event, data }) => {
        if (event === 'skipped') run.skipped = data.reason;
        else if (event === 'prompt') Object.assign(run, { userMessage: data.userMessage ?? '', scratchShown: !!data.scratchShown, files: data.files || [] });
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
  if (error && (fromChat || store.ui.view !== 'heartbeat')) toast(error.missing ? t('state.waitsFor', { m: error.module }) : `${t('hb.runFailed')}: ${error.error || ''}`, { tone: error.missing ? 'info' : 'danger' });
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
export async function saveScratch(content) {
  const u = store.ui; const sc = store.data.heartbeat?.scratch;
  u.hbScratchError = null;
  try {
    const res = await api.put('/api/lab/heartbeat/scratch', { content, expectedRevision: sc?.currentRevision ?? 0 });
    if (!res.write?.ok) u.hbScratchError = { code: 'revision-conflict', message: t('hb.scratchConflict', { n: res.write?.currentRevision ?? '—' }) };
    else { u.hbScratchDraft = null; toast(content === null ? t('hb.scratchUnset') : t('hb.scratchSaved', { n: res.write.currentRevision }), { tone: 'ok' }); }
  } catch (err) { u.hbScratchError = { code: err.code, message: err.message }; }
  await loadHeartbeat();
}
async function migrateLegacy() {
  const u = store.ui;
  try { u.hbMigration = await api.post('/api/lab/heartbeat/migrate'); } catch (err) { u.hbMigration = { error: err.message }; }
  await Promise.all([loadHeartbeat(), store.actions.loadFiles?.()]);
}
async function runReply(text) {
  const u = store.ui;
  u.hbReplyInput = text;
  try { u.hbReplyResult = { text, res: await api.post('/api/lab/heartbeat/reply', { text }) }; }
  catch (err) { u.hbReplyResult = { text, err }; }
  refresh('center');
}

function decisionChip(r) {
  if (r.skipped) return chip({ label: `${t('hb.skipped')}: ${r.skipped} · ${t('hb.noModelCall')}`, tone: 'neutral', ic: 'minus', testid: 'hb-decision' });
  if (!r.decision) return chip({ label: t('hb.awaitingDecision'), tone: 'neutral', ic: 'clock' });
  return r.decision.delivered ? chip({ label: t('hb.delivered'), tone: 'accent', ic: 'send', testid: 'hb-decision' }) : chip({ label: t('hb.ack'), tone: 'ok', ic: 'check', testid: 'hb-decision' });
}
function decisionDetail(dec) {
  if (!dec) return null;
  return h('div', { class: 'chip-wrap' },
    dec.silentReply ? chip({ label: 'NO_REPLY', tone: 'neutral', cls: 'chip-xs chip-mono' }) : null,
    dec.eventStatus ? chip({ label: dec.eventStatus, tone: 'neutral', cls: 'chip-xs chip-mono' }) : null,
    dec.silent ? chip({ label: t('hb.silent'), tone: 'neutral', cls: 'chip-xs' }) : null);
}
function runCard(run, running) {
  const d = run.decision;
  const tools = run.toolCalls || [];
  const rows = run.skipped ? [kv(t('hb.decision'), decisionChip(run))] : [
    kv(t('hb.userPrompt'), promptPre(run.userMessage || '')),
    kv(t('hb.files'), h('div', { class: 'chip-wrap' }, chip({ label: t('hb.kindHeartbeat'), tone: 'info' }), (run.files || []).map((f) => chip({ label: f, tone: 'neutral', cls: 'chip-mono' })), run.lightContext ? chip({ label: 'lightContext', tone: 'warn' }) : null, run.scratchShown ? chip({ label: t('hb.scratchInPrompt'), tone: 'info', ic: 'file' }) : null)),
    tools.length ? kv(t('prompt.tools'), h('div', { class: 'tool-list' }, tools.map((tc) => toolCard(tc)))) : null,
    kv(t('hb.reply'), running && !run.reply ? h('span', { class: 'caret' }) : h('pre', { class: 'ptext' }, run.reply || '')),
    kv(t('hb.decision'), h('div', { class: 'chip-wrap' }, decisionChip(run), decisionDetail(d), run.flushReason ? chip({ label: `flush: ${run.flushReason}`, tone: 'neutral' }) : null)),
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
    r.skipped ? h('div', { class: 'muted' }, `${t('hb.skipped')}: ${r.skipped}`) : [promptPre(r.userMessage || ''), h('div', { class: 'muted small' }, t('hb.reply')), h('pre', { class: 'ptext' }, r.reply || ''), h('div', null, decisionChip(r))]);
  const dlg = openDialog({ title: t('hb.compareTitle'), body: h('div', { class: 'cmp' }, col(a), col(b)), cls: 'dialog-lg', actions: [btn(t('act.close'), { onClick: () => dlg.close() })] });
}
function replyCard() {
  const u = store.ui; const sr = u.hbReplyResult;
  const input = h('input', { class: 'input mono', value: u.hbReplyInput, 'aria-label': t('hb.replyText'), placeholder: 'NO_REPLY', 'data-testid': 'hb-reply-input', onkeydown: (e) => { if (e.key === 'Enter') runReply(e.target.value); } });
  const res = sr?.res;
  return card(t('hb.parser'), [
    h('div', { class: 'sf-row' }, input, btn(t('hb.parse'), { size: 'sm', onClick: () => runReply(input.value) })),
    sr?.err ? failCard(sr.err, { compact: true }) : res ? h('div', { class: 'sf-row sf-wrap', 'data-testid': 'hb-reply-result' }, h('span', { class: 'mono muted small' }, `"${sr.text}"`), h('span', { class: 'arrow muted', 'aria-hidden': 'true' }, '→'),
      res.delivered ? chip({ label: t('hb.deliver'), tone: 'accent', ic: 'send' }) : chip({ label: t('hb.skip'), tone: 'ok', ic: 'check' }),
      res.delivered ? h('span', { class: 'mono muted small' }, `"${res.text ?? ''}"`) : null, decisionDetail(res), res.legacyAck?.didStrip ? chip({ label: 'HEARTBEAT_OK', tone: 'neutral', cls: 'chip-xs chip-mono' }) : null) : null,
  ], { ic: 'scale', target: 'hb-reply', testid: 'hb-reply', right: h('span', { class: 'chip chip-xs tone-neutral' }, t('hb.parserOnly')) });
}
const SCRATCH_TONE = { none: 'neutral', unset: 'neutral', empty: 'neutral', active: 'ok' };
function scratchCard(sc) {
  const u = store.ui;
  const draft = u.hbScratchDraft ?? sc?.content ?? '';
  const ta = h('textarea', { class: 'hb-scratch-ta', spellcheck: 'false', 'aria-label': t('hb.scratch'), 'data-testid': 'hb-scratch-input', placeholder: t('hb.scratchPlaceholder'), oninput: (e) => { u.hbScratchDraft = e.target.value; } });
  ta.value = draft;
  const err = u.hbScratchError;
  return card(t('hb.scratch'), [
    h('div', { class: 'hb-scratch-bar' },
      h('div', { class: 'chip-wrap' },
        chip({ label: t(`hb.scratchState.${sc?.status || 'none'}`), tone: SCRATCH_TONE[sc?.status] || 'neutral', testid: 'hb-scratch-state' }),
        chip({ label: `rev ${sc?.currentRevision ?? 0}`, tone: 'neutral', cls: 'chip-xs chip-mono' }),
        chip({ label: `${fmtN(sc?.bytes ?? 0)} / ${fmtN(sc?.maxBytes ?? 262144)} ${t('unit.bytes')}`, tone: 'neutral', cls: 'chip-xs' }),
        sc?.sourceSha256 ? chip({ label: t('hb.scratchMigrated'), tone: 'info', cls: 'chip-xs', title: sc.sourceSha256 }) : null),
      h('div', { class: 'chip-wrap' },
        btn(t('act.save'), { size: 'sm', kind: 'primary', onClick: () => saveScratch(ta.value), target: 'hb-scratch-save', testid: 'hb-scratch-save' }),
        btn(t('hb.scratchUnsetBtn'), { size: 'sm', kind: 'ghost', disabled: !sc || sc.status === 'none' || sc.status === 'unset', onClick: () => saveScratch(null) }))),
    ta,
    err ? h('div', { class: 'muted small tone-text-warn', 'data-testid': 'hb-scratch-error' }, err.message) : null,
  ], { ic: 'file', target: 'hb-scratch', testid: 'hb-scratch', right: h('span', { class: 'muted small mono' }, store.data.heartbeat?.store || '') });
}
function everyLabel(ms) {
  if (!ms) return '—';
  const min = ms / 60000;
  return Number.isInteger(min) ? `${fmtN(min)} ${t('unit.min')}` : fmtMs(ms);
}
function jobsCard(jobs, now, skipped = []) {
  const table = jobs.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['task', 'interval', 'prompt', 'last', 'next', 'state'].map((c) => h('th', { scope: 'col' }, t(`hb.col.${c}`))))),
    h('tbody', null, jobs.map((job) => h('tr', { 'data-testid': 'hb-job' },
      h('td', { class: 'mono', 'data-tip': job.displayName || job.name }, job.name), h('td', { class: 'mono nowrap' }, everyLabel(job.everyMs)),
      h('td', { class: 'td-clip', 'data-tip': job.prompt }, job.prompt),
      h('td', { class: 'num nowrap' }, job.lastRunAtMs ? fmtTime(job.lastRunAtMs, { seconds: false }) : '—'),
      h('td', { class: 'num nowrap' }, job.nextRunAtMs ? fmtTime(job.nextRunAtMs, { seconds: false }) : '—'),
      h('td', { class: 'td-state' }, !job.enabled ? chip({ label: t('hb.jobDisabled'), tone: 'neutral' }) : job.due && !job.heartbeatTask ? chip({ label: t('hb.dueHost'), tone: 'neutral', ic: 'dot', title: t('hb.dueHostTip') }) : job.due ? chip({ label: t('hb.due'), tone: 'accent', ic: 'dot' }) : chip({ label: `${t('hb.waiting')} (${fmtRelMin((job.nextRunAtMs ?? now) - now)})`, tone: 'neutral', ic: 'clock' })))))))
    : h('div', { class: 'muted pad' }, t('hb.noJobs'));
  const skippedChip = skipped.length ? chip({ label: t('hb.skippedRows', { n: skipped.length }), tone: 'warn', cls: 'chip-xs', title: skipped.map((r) => `#${r.index}${r.id ? ` ${r.id}` : ''}: ${r.reason}`).join('\n'), testid: 'hb-skipped-rows' }) : null;
  return card(t('hb.jobs'), table, { ic: 'layers', target: 'hb-jobs', testid: 'hb-jobs', right: h('span', { class: 'chip-wrap' }, skippedChip, h('span', { class: 'muted small mono' }, 'due_automation_jobs · heartbeat_scheduled_tasks')) });
}
function legacyCard(hb) {
  const u = store.ui;
  const findings = hb.migrationFindings || [];
  if (!hb.legacyFile?.exists && !findings.length && !u.hbMigration) return null;
  const m = u.hbMigration;
  const lines = m?.error ? [m.error] : m ? [...(m.scratch?.changes || []), ...(m.tasks?.changes || []), ...(m.scratch?.warnings || []), ...(m.tasks?.warnings || [])] : [];
  return card(t('hb.legacy'), [
    findings.map((f) => h('div', { class: 'sf-row sf-wrap', 'data-testid': 'hb-finding' }, chip({ label: f.requirement, tone: f.severity === 'error' ? 'danger' : 'warn', cls: 'chip-xs chip-mono' }), h('span', { class: 'small' }, f.message))),
    findings.length ? h('div', { class: 'muted small' }, t('hb.legacyNote')) : null,
    lines.length ? h('ul', { class: 'small', 'data-testid': 'hb-migration-result' }, lines.map((l) => h('li', null, l))) : null,
    findings.length ? h('div', null, btn(t('hb.migrate'), { size: 'sm', kind: 'primary', ic: 'merge', onClick: () => migrateLegacy(), target: 'hb-migrate', testid: 'hb-migrate' })) : null,
  ], { ic: 'alert-triangle', target: 'hb-legacy', testid: 'hb-legacy', right: chip({ label: 'HEARTBEAT.md', tone: hb.legacyFile?.exists ? 'warn' : 'neutral', cls: 'chip-xs chip-mono', onClick: hb.legacyFile?.exists ? () => store.actions.openFile('HEARTBEAT.md') : null }) });
}
function nextPromptCard(pre) {
  const d = h('details', { class: 'card-details', 'data-testid': 'hb-next-prompt' },
    h('summary', null, t('hb.nextPrompt'), pre.skipReason ? chip({ label: `${t('hb.skipped')}: ${pre.skipReason}`, tone: 'neutral', cls: 'chip-xs' }) : null),
    pre.message ? promptPre(pre.message) : h('div', { class: 'muted small' }, t('hb.noModelCall')));
  return card(null, d, { target: 'hb-next' });
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
  const sc = hb.scratch || {};
  const pp = fileEntry('PROACTIVE_PREFERENCES.md');
  const ppState = !pp ? null : (pp.badges || []).includes('outside_layout') ? t('badge.outside_layout') : (pp.badges || []).includes('empty') ? t('badge.empty') : (pp.badges || []).includes('injected') ? t('badge.injected') : t('badge.excluded');
  const now = hb.clock?.nowMs ?? Date.now(); const off = hb.clock?.offsetMs || 0;
  const running = d.hbRunning;
  const latest = running || hb.runs?.find((r) => r.id === u.hbSelected) || hb.runs?.[0] || null;
  const noKey = chatKeyState() === 'none';
  // The preflight (skip decisions) runs without a key; only a run that would call the model answers
  // no_api_key (docs/lab.md › /heartbeat/run), so the button stays enabled and the reason is text.
  const pre = hb.preflight || {};
  const preChip = pre.skipReason ? chip({ label: `${t('hb.preflight')}: ${pre.skipReason} · ${t('hb.noModelCall')}`, tone: 'neutral', ic: 'minus', testid: 'hb-preflight' })
    : (pre.dueTasks || []).length ? chip({ label: `${t('hb.preflight')}: ${t('hb.preflightDue', { n: pre.dueTasks.length })}`, tone: 'accent', ic: 'dot', title: pre.dueTasks.join(', '), testid: 'hb-preflight' })
      : chip({ label: `${t('hb.preflight')}: ${pre.scratchShown ? t('hb.preflightScratch') : t('hb.preflightGeneric')}`, tone: 'neutral', ic: 'check', testid: 'hb-preflight' });
  const lastErr = d.hbLastError && !d.hbRunning ? d.hbLastError : null;
  replace(body, strip,
    viewHead(t('view.heartbeat'), 'heart-pulse', [
      chip({ label: `${t('hb.scratch')}: ${t(`hb.scratchState.${sc.status || 'none'}`)}`, tone: SCRATCH_TONE[sc.status] || 'neutral', target: 'hb-scratch', testid: 'hb-scratch-chip', onClick: () => document.querySelector('[data-testid="hb-scratch-input"]')?.focus() }),
      chip({ label: `${t('hb.every')} ${hb.every ?? '—'} · ${t('hb.noScheduler')}`, tone: 'neutral', ic: 'clock', title: t('hb.runtimeOnlyTip') }),
      chip({ label: `ack ≤ ${hb.ackLimit ?? '—'}`, tone: 'neutral', title: t('hb.ackTip') }),
      ppState ? chip({ label: `PROACTIVE_PREFERENCES.md: ${ppState}`, tone: 'ext', ic: 'puzzle', onClick: () => store.actions.openFile('PROACTIVE_PREFERENCES.md') }) : null,
    ].filter(Boolean)),
    h('div', { class: 'view-scroll' },
      howItWorks('heartbeat'),
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
          btn(running ? t('hb.running') : t('hb.runNow'), { kind: 'primary', ic: 'play', onClick: () => runHeartbeat(), busy: !!running, target: 'hb-run', testid: 'hb-run-btn' }))),
      h('div', { class: 'hb-pre' }, preChip, noKey ? h('span', { class: 'muted small', 'data-testid': 'hb-nokey' }, t('hb.noKeyNote')) : null),
      lastErr ? h('div', { class: 'stack-tight', 'data-testid': 'hb-error' }, apiErrorCard({ code: lastErr.code, message: lastErr.error || lastErr.message || '', body: lastErr }, { title: t('hb.runFailed') }),
        lastErr.code === 'no_api_key' ? btn(t('act.goSettings'), { size: 'sm', kind: 'ghost', onClick: () => store.actions.openSettings('chat') }) : null) : null,
      legacyCard(hb),
      scratchCard(sc),
      jobsCard(hb.jobs || [], now, hb.skippedJobRows || []),
      nextPromptCard(pre),
      latest ? runCard(latest, !!running) : emptyState({ title: t('hb.noRuns'), text: t('hb.noRunsText'), level: 3 }),
      historyCard(hb.runs || []),
      replyCard(),
      honesty(t('hb.storeNote'), 'info', 'info')));
}
