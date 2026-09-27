// inspector/heartbeat.js: Prompt tab while the Heartbeat view is active. It shows the selected
// run's user turn (as streamed or stored by /api/lab/heartbeat: due tasks, monitor scratch and
// the current-time lines; v2026.9.6 has no "## Heartbeats" system section) above the next
// heartbeat prompt and the heartbeat-kind Project Context preview.
import { h } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store } from '../store.js';
import { chip, emptyState } from '../ui/kit.js';
import { section, promptPre } from './common.js';
import { promptTab } from './prompt.js';
import { toolCard } from '../views/chat.js';

export function selectedRun() {
  const hb = store.data.heartbeat; const u = store.ui;
  const running = store.data.hbRunning;
  if (running) return running;
  const runs = hb?.runs || [];
  return runs.find((r) => r.id === u.hbSelected) || runs[0] || null;
}
export function heartbeatTab() {
  const run = selectedRun();
  const wrap = h('div', { class: 'prompt-tab' });
  if (!run) wrap.append(emptyState({ title: t('hb.noRuns'), level: 4 }));
  else {
    wrap.append(h('div', { class: 'psummary' }, h('b', null, `${t('hb.run')} #${run.id ?? '…'}`), run.skipped ? chip({ label: `${t('hb.skipped')}: ${run.skipped}`, tone: 'neutral', cls: 'chip-xs' }) : null));
    wrap.append(section('hb-user', t('hb.userPrompt'), { count: (run.userMessage || '').length, copy: run.userMessage || '', empty: !run.userMessage, body: () => promptPre(run.userMessage || '—') }));
    wrap.append(section('hb-files', t('hb.files'), { count: (run.files || []).length, empty: !(run.files || []).length, body: () => h('div', { class: 'chip-wrap' }, (run.files || []).map((f) => chip({ label: f, tone: 'neutral', cls: 'chip-mono chip-xs' }))) }));
    const tools = run.toolCalls || run.tools || [];
    wrap.append(section('hb-tools', t('prompt.tools'), { count: tools.length, empty: !tools.length, body: () => (tools.length ? h('div', { class: 'stack-tight' }, tools.map((tc) => toolCard({ ...tc, status: tc.status || (tc.ok === false ? 'error' : 'ok') }))) : h('div', { class: 'muted' }, t('hb.noTools'))) }));
  }
  const next = store.data.heartbeat?.preflight;
  if (next) wrap.append(section('hb-next', t('hb.nextPrompt'), { count: (next.message || '').length, copy: next.message || '', empty: !next.message, body: () => (next.message ? promptPre(next.message) : h('div', { class: 'muted' }, `${t('hb.skipped')}: ${next.skipReason} · ${t('hb.noModelCall')}`)) }));
  wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('hb.previewKind'))));
  wrap.append(promptTab(null, { ctx: 'heartbeat' }));
  return wrap;
}
