// inspector/heartbeat.js: Prompt tab while the Heartbeat view is active. It shows the selected
// run's assembled prompt (as streamed or stored by /api/lab/heartbeat) above the heartbeat-kind
// Project Context preview, so the inspector never shows a chat turn inside the Heartbeat view.
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
    wrap.append(section('hb-system', t('hb.systemSection'), { count: (run.systemSection || '').length, copy: run.systemSection || '', empty: !run.systemSection, body: () => promptPre(run.systemSection || '—') }));
    wrap.append(section('hb-files', t('hb.files'), { count: (run.files || []).length, empty: !(run.files || []).length, body: () => h('div', { class: 'chip-wrap' }, (run.files || []).map((f) => chip({ label: f, tone: 'neutral', cls: 'chip-mono chip-xs' }))) }));
    const tools = run.toolCalls || run.tools || [];
    wrap.append(section('hb-tools', t('prompt.tools'), { count: tools.length, empty: !tools.length, body: () => (tools.length ? h('div', { class: 'stack-tight' }, tools.map((tc) => toolCard({ ...tc, status: tc.status || (tc.ok === false ? 'error' : 'ok') }))) : h('div', { class: 'muted' }, t('hb.noTools'))) }));
  }
  wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('hb.previewKind'))));
  wrap.append(promptTab(null, { ctx: 'heartbeat' }));
  return wrap;
}
