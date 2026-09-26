// inspector/index.js: Denetçi header (turn picker, follow toggle, tabs) bound to the active
// view's selection (critique #19): chat turns, a heartbeat run, the live task or consolidation.
import { h, icon, replace, fmtTime } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, registerRenderer, currentTurn, persistUi, loadTurn } from '../store.js';
import { iconBtn } from '../ui/kit.js';
import { openMenu } from '../ui/overlay.js';
import { promptTab } from './prompt.js';
import { memoryTab } from './memory.js';
import { timelineTab } from './timeline.js';
import { diffTab } from './diff.js';
import { liveTab } from './live.js';
import { heartbeatTab } from './heartbeat.js';

export const TABS = [
  { id: 'prompt', ic: 'prompt' },
  { id: 'memory', ic: 'database' },
  { id: 'timeline', ic: 'activity' },
  { id: 'diff', ic: 'diff' },
];
export function inspectorContext() {
  const v = store.ui.view;
  if (v === 'live') return 'live';
  if (v === 'heartbeat') return 'heartbeat';
  if (v === 'consolidation') return 'consolidation';
  return 'turn';
}
const scrollMemo = {};

function renderInspector() {
  const el = document.getElementById('inspector');
  const u = store.ui;
  const prev = el.querySelector('.insp-scroll');
  if (prev) scrollMemo[prev.dataset.key] = prev.scrollTop;
  const ctx = inspectorContext();
  const turn = ctx === 'turn' ? currentTurn() : null;
  if (turn && typeof turn.id === 'number' && !store.data.details.has(turn.id) && !store.data.detailErr.has(turn.id)) loadTurn(turn.id);
  let title;
  if (ctx === 'turn') {
    title = h('button', { type: 'button', class: 'turn-picker', 'aria-haspopup': 'menu', 'data-testid': 'turn-picker', onclick: (e) => turnMenu(e.currentTarget) },
      h('span', null, turn ? `${t('inspector.turn')} #${turn.id}` : t('inspector.noTurn')), turn?.sessionKind ? h('span', { class: 'kind-tag', 'data-kind': turn.sessionKind }, turn.sessionKind) : null, icon('chevron-down', 12));
  } else {
    const label = { live: t('view.live'), heartbeat: t('inspector.hbContext'), consolidation: t('view.consolidation') }[ctx];
    title = h('h2', { class: 'insp-title', tabindex: '-1' }, icon({ live: 'waveform', heartbeat: 'heart-pulse', consolidation: 'merge' }[ctx], 14), label);
  }
  const header = h('div', { class: 'insp-head' },
    h('div', { class: 'insp-row' },
      h('span', { class: 'sheet-grab', 'aria-hidden': 'true' }),
      title,
      ctx === 'turn' ? h('button', { type: 'button', class: ['follow-btn', u.follow ? 'is-on' : ''], 'aria-pressed': String(u.follow), 'data-tip': u.follow ? t('inspector.followingTip') : t('inspector.pinnedTip'), 'data-testid': 'follow-toggle', onclick: () => { u.follow = !u.follow; u.pinnedTurn = u.follow ? null : turn?.id ?? null; refresh('inspector', 'center'); } }, icon('rotate-ccw', 12), u.follow ? t('inspector.follow') : t('inspector.pinned')) : null,
      h('span', { class: 'spacer' }),
      iconBtn('x', t('act.close'), () => store.actions.closeInspector(), { size: 'sm', cls: 'insp-close' })),
    h('div', { class: 'insp-tabs', role: 'tablist', 'aria-label': t('inspector.tabs') }, TABS.map((tb) => h('button', {
      type: 'button', role: 'tab', id: `itab-${tb.id}`, class: ['itab', u.inspectorTab === tb.id ? 'is-active' : ''], 'aria-selected': String(u.inspectorTab === tb.id), 'aria-controls': 'insp-panel', tabindex: u.inspectorTab === tb.id ? '0' : '-1',
      onclick: () => { u.inspectorTab = tb.id; persistUi(); refresh('inspector'); }, 'data-testid': `itab-${tb.id}`,
    }, icon(tb.ic, 14), t(`inspector.${tb.id}`)))));
  header.querySelector('.insp-tabs').addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const i = TABS.findIndex((x) => x.id === u.inspectorTab);
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
    u.inspectorTab = TABS[j].id; persistUi(); refresh('inspector');
    requestAnimationFrame(() => document.querySelector('.itab.is-active')?.focus());
  });
  const key = `${ctx}:${u.inspectorTab}`;
  const scroll = h('div', { class: 'insp-scroll', id: 'insp-panel', 'data-key': key, role: 'tabpanel', 'aria-labelledby': `itab-${u.inspectorTab}`, tabindex: '-1' });
  try {
    if (ctx === 'live') scroll.append(liveTab(u.inspectorTab));
    else if (ctx === 'heartbeat' && u.inspectorTab === 'prompt') scroll.append(heartbeatTab());
    else if (u.inspectorTab === 'prompt') scroll.append(promptTab(turn, { ctx }));
    else if (u.inspectorTab === 'memory') scroll.append(memoryTab(turn, { ctx }));
    else if (u.inspectorTab === 'timeline') scroll.append(timelineTab(turn, { ctx }));
    else scroll.append(diffTab(turn, { ctx }));
  } catch (err) { console.error(err); scroll.append(h('div', { class: 'error-card is-flat' }, String(err))); }
  replace(el, header, scroll);
  const tl = u.timeline;
  if (u.inspectorTab === 'timeline' && tl.stick) requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  else if (scrollMemo[key] !== undefined) scroll.scrollTop = scrollMemo[key];
  scroll.addEventListener('scroll', () => {
    if (u.inspectorTab !== 'timeline') return;
    tl.stick = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 30;
    scroll.querySelector('.new-pill')?.toggleAttribute('hidden', tl.stick);
  });
}
function turnMenu(anchor) {
  const u = store.ui; const turns = store.data.turns;
  openMenu(anchor, [
    { label: t('inspector.followLatest'), checked: u.follow, onSelect: () => { u.follow = true; u.pinnedTurn = null; refresh('inspector', 'center'); } },
    '-',
    ...turns.slice().reverse().slice(0, 20).map((tr) => ({ label: `#${tr.id} · ${tr.sessionKind || 'main'} · ${tr.user ? tr.user.slice(0, 32) : t('chat.resetTurn')}`, hint: fmtTime(tr.startedAt, { seconds: false }), checked: !u.follow && u.pinnedTurn === tr.id, onSelect: () => { u.follow = false; u.pinnedTurn = tr.id; refresh('inspector', 'center'); } })),
  ]);
}

registerRenderer('inspector', renderInspector);
