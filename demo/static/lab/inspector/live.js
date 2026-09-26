// inspector/live.js: the four inspector tabs while Canlı görev is active. Everything comes from
// /api/live-task/state and the streamed SDK events of each turn (plus live.* bus events).
import { h, fmtN, fmtTime } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store } from '../store.js';
import { emptyState, honesty, jsonDisclosure } from '../ui/kit.js';
import { lineDiff, hunks, diffView } from '../ui/diff.js';
import { promptPre } from './common.js';

function lastEvent(type) {
  const L = store.data.live;
  for (let i = L.events.length - 1; i >= 0; i--) if (L.events[i].type === type) return L.events[i];
  return null;
}
export function liveTab(tab) {
  const L = store.data.live; const st = L.state;
  const wrap = h('div', { class: 'live-insp' });
  if (tab === 'prompt') {
    wrap.append(honesty(t('live.promptNote'), 'info'));
    const identity = st?.workspaceInjectedFiles || {};
    const names = Object.keys(identity);
    wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('live.identitySections')), h('span', { class: 'muted small' }, `${names.length} ${t('unit.files')}`)));
    if (!names.length) wrap.append(h('div', { class: 'muted pad' }, t('live.noState')));
    for (const n of names) wrap.append(h('details', { class: 'fold' }, h('summary', { class: 'fold-head' }, h('span', { class: 'fold-name mono' }, `## ${n}`), h('span', { class: 'fold-count num' }, fmtN(String(identity[n]).length))), h('div', { class: 'fold-body' }, promptPre(identity[n]))));
    const recall = lastEvent('memory_recall_completed');
    wrap.append(h('div', { class: 'subhead' }, h('h3', null, '## Recalled Subject Memory')));
    const ctx = recall?.data?.memory_context;
    wrap.append(recall ? promptPre(Array.isArray(ctx) ? ctx.join('\n') : String(ctx ?? '') || t('live.recallEmpty')) : h('div', { class: 'muted pad' }, t('live.noTurnYet')));
    const assembled = lastEvent('prompt_assembled');
    wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('live.runtimeContext'))));
    wrap.append(assembled ? promptPre(typeof assembled.data?.runtime_context === 'string' ? assembled.data.runtime_context : JSON.stringify(assembled.data?.runtime_context ?? null, null, 2)) : h('div', { class: 'muted pad' }, t('live.noTurnYet')));
    if (assembled?.data?.trace_context) wrap.append(jsonDisclosure(assembled.data.trace_context, { title: 'trace_context' }));
  } else if (tab === 'memory') {
    const files = st?.subjectMemoryFiles || {};
    wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('live.subjectMemory')), h('span', { class: 'muted mono small' }, `subjects/${store.ui.liveSubject}/`)));
    if (!Object.keys(files).length) wrap.append(h('div', { class: 'muted pad' }, t('live.noSubjectFiles')));
    for (const [p, text] of Object.entries(files)) wrap.append(h('details', { class: 'fold', open: true }, h('summary', { class: 'fold-head' }, h('span', { class: 'fold-name mono' }, p), h('span', { class: 'fold-count num' }, fmtN(String(text).length))), h('div', { class: 'fold-body' }, promptPre(text))));
    wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('live.recallPerTurn'))));
    if (!L.turns.length) wrap.append(h('div', { class: 'muted pad' }, t('live.noTurnYet')));
    L.turns.forEach((tr, i) => {
      const rc = tr.events.find((e) => e.type === 'memory_recall_completed');
      const n = Array.isArray(rc?.data?.results) ? rc.data.results.length : null;
      wrap.append(h('div', { class: 'kv-row' }, h('span', { class: 'kv-k' }, `#${i + 1}`), h('span', { class: 'kv-v' }, n === null ? '—' : t('live.hits', { n }))));
    });
  } else if (tab === 'timeline') {
    const bus = store.data.events.filter((e) => String(e.type).startsWith('live.'));
    if (!L.events.length && !bus.length) { wrap.append(emptyState({ title: t('timeline.empty'), level: 4 })); return wrap; }
    const list = h('div', { class: 'tl-list' });
    L.turns.forEach((tr, i) => tr.events.forEach((e) => list.append(h('div', { class: 'ev cat-canlı' }, h('div', { class: 'ev-head is-static' },
      h('span', { class: 'ev-time mono' }, `+${fmtN(e.elapsed_ms)} ms`),
      h('span', { class: 'ev-main' }, h('span', { class: 'ev-sum' }, e.text ? e.text : e.type), h('span', { class: 'ev-type mono' }, `#${i + 1} · ${e.type}`)))))));
    for (const e of bus) list.append(h('div', { class: 'ev cat-canlı' }, h('div', { class: 'ev-head is-static' }, h('span', { class: 'ev-time mono' }, fmtTime(e.ts, { ms: true })), h('span', { class: 'ev-main' }, h('span', { class: 'ev-sum' }, e.summary || e.type), h('span', { class: 'ev-type mono' }, e.type)))));
    wrap.append(list);
  } else {
    const sd = L.summaryDiff;
    if (!sd) wrap.append(emptyState({ title: t('live.diffEmpty'), ic: 'diff', level: 4 }));
    else wrap.append(h('article', { class: 'dcard' }, h('div', { class: 'dcard-head' }, h('span', { class: 'chip chip-xs tone-info' }, t('source.live_summary')), h('span', { class: 'mono dcard-path' }, sd.path)), diffView(hunks(lineDiff(sd.before ?? '', sd.after ?? ''), 3))));
    if (st?.workspace) wrap.append(h('div', { class: 'muted small pad' }, t('live.root', { r: st.workspace })));
  }
  return wrap;
}
