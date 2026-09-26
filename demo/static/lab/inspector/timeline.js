// inspector/timeline.js: Zaman tab over the LabEvent stream (plus client-only senaryo.* rows).
// Rows carry a coloured left rule per category; the summary wraps to two lines (critique #22).
import { h, icon, fmtN, fmtMs, fmtTime, trFold } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, refresh } from '../store.js';
import { toggle, jsonDisclosure, emptyState } from '../ui/kit.js';

export const CATS = ['sohbet', 'bellek', 'dosya', 'flush', 'bootstrap', 'heartbeat', 'konsolidasyon', 'canlı', 'ayar', 'senaryo', 'hata'];
const VIEW_CATS = { heartbeat: ['heartbeat'], consolidation: ['konsolidasyon'], live: ['canlı'] };
const WINDOW = 300;
let windowSize = WINDOW;
let tm = null;
export const catLabel = (c) => (has(`cat.${c}`) ? t(`cat.${c}`) : c);

export function timelineTab(turn, { ctx = 'turn' } = {}) {
  const tl = store.ui.timeline;
  const preset = VIEW_CATS[ctx] || null;
  const cats = tl.cats.size ? tl.cats : new Set(preset || []);
  let evs = [...store.data.events].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0) || (a.id > b.id ? 1 : -1));
  if (cats.size) evs = evs.filter((e) => cats.has(e.category));
  if (tl.text) { const f = trFold(tl.text); evs = evs.filter((e) => trFold(`${e.type} ${e.summary}`).includes(f)); }
  if (tl.thisTurn && turn) evs = evs.filter((e) => e.turnId === turn.id);
  const shown = evs.slice(-windowSize);
  const wrap = h('div', { class: 'timeline-tab' });
  wrap.append(h('div', { class: 'tl-filters' },
    h('div', { class: 'filter-chips', role: 'group', 'aria-label': t('timeline.categories') }, CATS.map((c) => h('button', {
      type: 'button', class: ['fchip', `cat-${c}`, cats.has(c) ? 'is-on' : ''], 'aria-pressed': String(cats.has(c)), 'data-testid': 'filter-chip',
      onclick: () => { if (!tl.cats.size && preset) preset.forEach((x) => tl.cats.add(x)); if (tl.cats.has(c)) tl.cats.delete(c); else tl.cats.add(c); refresh('inspector'); },
    }, catLabel(c)))),
    h('div', { class: 'sf-row' },
      h('input', { class: 'input', type: 'search', placeholder: t('timeline.filter'), value: tl.text, 'aria-label': t('timeline.filter'), oninput: (e) => { tl.text = e.target.value; clearTimeout(tm); tm = setTimeout(() => { refresh('inspector'); requestAnimationFrame(() => { const i = document.querySelector('.tl-filters input'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }); }, 180); } }),
      turn ? toggle({ checked: tl.thisTurn, onChange: (v) => { tl.thisTurn = v; refresh('inspector'); }, label: t('timeline.thisTurn') }) : null)));
  if (preset && !tl.cats.size) wrap.append(h('div', { class: 'muted small' }, t('timeline.presetNote', { c: preset.map(catLabel).join(', ') })));
  if (!shown.length) { wrap.append(emptyState({ title: t('timeline.empty'), testid: 'empty-timeline', level: 4 })); return wrap; }
  if (evs.length > shown.length) wrap.append(h('div', { class: 'muted pad small' }, t('timeline.window', { a: fmtN(shown.length), n: fmtN(evs.length) }), ' ',
    h('button', { type: 'button', class: 'link', onclick: () => { windowSize += WINDOW; refresh('inspector'); } }, t('timeline.older'))));
  const list = h('div', { class: 'tl-list', role: 'list' });
  for (const e of shown) {
    const key = e.id ?? `${e.ts}-${e.type}`;
    const open = tl.expanded.has(key);
    list.append(h('div', { class: ['ev', `cat-${e.category || 'x'}`, open ? 'is-open' : '', turn && e.turnId === turn.id ? 'is-turn' : ''], role: 'listitem', 'data-testid': 'event-row', 'data-type': e.type },
      h('button', { type: 'button', class: 'ev-head', 'aria-expanded': String(open), 'aria-label': `${fmtTime(e.ts)} ${catLabel(e.category)} ${e.type} ${e.summary || ''}`, onclick: () => { if (open) tl.expanded.delete(key); else tl.expanded.add(key); tl.stick = false; refresh('inspector'); } },
        h('span', { class: 'ev-time mono' }, fmtTime(e.ts, { ms: true })),
        h('span', { class: 'ev-main' }, h('span', { class: 'ev-sum' }, e.summary || e.type), h('span', { class: 'ev-type mono' }, `${catLabel(e.category)} · ${e.type}`)),
        e.data?.ms !== undefined ? h('span', { class: 'ev-ms num' }, fmtMs(e.data.ms)) : null),
      open ? h('div', { class: 'ev-body' }, jsonDisclosure({ id: e.id, ts: e.ts, type: e.type, category: e.category, turnId: e.turnId, data: e.data }, { title: 'payload', open: true })) : null));
  }
  wrap.append(list);
  wrap.append(h('button', { type: 'button', class: 'new-pill', hidden: tl.stick, onclick: () => { tl.stick = true; const sc = document.querySelector('.insp-scroll'); if (sc) sc.scrollTop = sc.scrollHeight; } }, t('timeline.newEvents'), icon('arrow-down', 12)));
  return wrap;
}
