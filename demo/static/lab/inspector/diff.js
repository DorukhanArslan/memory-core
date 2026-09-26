// inspector/diff.js: Diff tab over GET /api/lab/diff?since=… (server snapshot store).
// Unified diffs come from the server; revert posts /api/lab/diff/revert after a confirmation.
import { h } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, refresh, loadFiles, loadState } from '../store.js';
import { api } from '../api.js';
import { segmented, iconBtn, emptyState, skeleton, failCard } from '../ui/kit.js';
import { confirmDialog, toast } from '../ui/overlay.js';
import { parseUnified, diffView } from '../ui/diff.js';

const cache = new Map();
const FILE_EVENT = /^(file\.|bootstrap\.file_deleted|curation\.|flush\.written|session_memory\.|promotion\.|dreaming\.|workspace\.reset|chat\.turn\.completed|live\.)/;
function version() {
  const evs = store.data.events;
  for (let i = evs.length - 1; i >= 0; i--) if (FILE_EVENT.test(evs[i].type)) return evs[i].id ?? i;
  return 0;
}
export const sourceLabel = (s) => (has(`source.${s}`) ? t(`source.${s}`) : s);
const SOURCE_TONE = { curation: 'ext', lifecycle: 'warn', flush: 'accent', promotion: 'info', dreaming: 'info', editor: 'neutral', session_memory: 'accent', live_summary: 'info' };

/** Diff list for a baseline; cached until a file-changing event arrives. */
export function diffFor(since) {
  const v = version();
  const hit = cache.get(since);
  if (hit && hit.version === v) return hit;
  const entry = { version: v, loading: true, list: hit?.list || null, err: null };
  cache.set(since, entry);
  entry.promise = api.get('/api/lab/diff', { since })
    .then((res) => { entry.list = Array.isArray(res) ? res : (res?.files || []); entry.err = null; })
    .catch((err) => { entry.err = err; entry.list = null; })
    .finally(() => { entry.loading = false; refresh('inspector'); });
  return entry;
}
export async function fetchDiff(since) {
  cache.delete(since);
  const e = diffFor(since);
  await e.promise;
  return e;
}
export function sinceFor(base, turn) {
  if (base === 'turn') return turn && typeof turn.id === 'number' ? `turn:${turn.id}` : 'session';
  if (base === 'mark') return store.ui.scenario?.markId ? `mark:${store.ui.scenario.markId}` : 'session';
  return base;
}

export function diffTab(turn, { ctx = 'turn' } = {}) {
  const u = store.ui;
  const defaultBase = ctx === 'turn' ? 'turn' : 'reset';
  let base = u.diffBase || defaultBase;
  if (base === 'mark' && !u.scenario?.markId) base = 'session';
  if (base === 'turn' && ctx !== 'turn') base = 'reset';
  const since = sinceFor(base, turn);
  const wrap = h('div', { class: 'diff-tab' });
  wrap.append(h('div', { class: 'controls-row' }, segmented({
    options: [
      { value: 'turn', label: t('diff.thisTurn'), disabled: ctx !== 'turn' || !turn },
      { value: 'session', label: t('diff.session') },
      { value: 'reset', label: t('diff.sinceReset') },
      { value: 'mark', label: t('diff.scenarioStep'), disabled: !u.scenario?.markId },
    ],
    value: base, onChange: (v) => { u.diffBase = v; refresh('inspector'); }, aria: t('diff.baseline'), size: 'sm', testid: 'diff-base',
  })));
  const entry = diffFor(since);
  if (entry.loading && !entry.list) { wrap.append(skeleton(3)); return wrap; }
  if (entry.err) { wrap.append(failCard(entry.err, { title: t('diff.loadFailed') })); return wrap; }
  const list = entry.list || [];
  if (!list.length) { wrap.append(emptyState({ title: t('diff.empty'), testid: 'empty-diff', ic: 'diff', level: 4 })); return wrap; }
  for (const d of list) {
    const sources = d.sources || (d.source ? [d.source] : []);
    const status = d.status === 'modified' || d.status === 'changed' ? 'modified' : d.status;
    wrap.append(h('article', { class: 'dcard', 'data-testid': 'diff-card', 'data-path': d.path },
      h('div', { class: 'dcard-head' },
        h('span', { class: ['chip', 'chip-xs', status === 'added' ? 'tone-ok' : status === 'deleted' ? 'tone-danger' : 'tone-accent'] }, t(`diff.status.${status}`)),
        h('button', { type: 'button', class: 'dcard-path mono', onclick: () => (status !== 'deleted' ? store.actions.openFile(d.path) : null), disabled: status === 'deleted' }, d.path),
        h('span', { class: 'num tone-text-ok' }, `+${d.added ?? 0}`), h('span', { class: 'num tone-text-danger' }, `−${d.removed ?? 0}`),
        h('span', { class: 'spacer' }),
        sources.map((src) => h('span', { class: ['chip', 'chip-xs', `tone-${SOURCE_TONE[src] || 'neutral'}`] }, sourceLabel(src))),
        iconBtn('rotate-ccw', t('diff.revert'), () => revert(d, since), { size: 'xs' })),
      status === 'deleted' ? h('div', { class: 'muted pad small' }, t('diff.deletedBy', { s: sources.map(sourceLabel).join(', ') || '—' })) : null,
      d.diff ? diffView(parseUnified(d.diff), { maxLines: 200 }) : null));
  }
  return wrap;
}
function revert(d, since) {
  confirmDialog({ title: t('diff.revertTitle'), lines: [t('diff.revertLine', { p: d.path })], confirmLabel: t('diff.revert'), danger: false, onConfirm: async () => {
    try {
      await api.post('/api/lab/diff/revert', { path: d.path, since });
      toast(t('toast.reverted', { p: d.path }), { tone: 'ok' });
      loadFiles(); loadState();
    } catch (err) {
      toast(err.status === 409 ? t('diff.revertConflict', { p: d.path }) : err.missing ? t('state.waitsFor', { m: err.module || err.path }) : err.message, { tone: err.status === 409 ? 'warn' : 'danger' });
    }
    refresh('inspector');
  } });
}
