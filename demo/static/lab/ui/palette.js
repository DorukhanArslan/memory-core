// ui/palette.js: the ⌘K command palette (opens instantly, no animation) and the shortcuts sheet.
// Prefixes: > actions · @ files · # scenarios · ? memory search. Turkish-aware fuzzy matching.
import { h, icon, replace, fuzzyScore, lsGet, lsSet } from './dom.js';
import { t } from '../i18n/index.js';
import { store } from '../store.js';
import { openDialog } from './overlay.js';
import { kbd, chip } from './kit.js';
import { SCENARIOS } from '../scenarios/catalog.js';
import { VIEWS, viewLabel } from '../views/shell.js';

const STATUS_TONE = { passed: 'ok', failed: 'danger', partial: 'warn', blocked: 'neutral' };

function items() {
  const a = store.actions; const u = store.ui; const res = u.scenarioResults || {};
  const list = [];
  for (const d of SCENARIOS) list.push({ group: 'scenarios', prefix: '#', id: `sc:${d.id}`, label: `${d.id} · ${t(`scn.${d.id}.title`)}`, ic: 'flask', meta: res[d.id] ? chip({ label: t(`scn.status.${res[d.id].status}`), tone: STATUS_TONE[res[d.id].status] || 'neutral', cls: 'chip-xs' }) : null, run: () => a.startScenario(d.id) });
  for (const v of VIEWS) list.push({ group: 'views', prefix: '>', id: `v:${v.id}`, label: viewLabel(v.id), ic: v.ic, hint: v.key, run: () => a.setView(v.id) });
  for (const f of store.data.files || []) {
    if (f.kind === 'folder' || (f.kind === 'hidden' && !u.showHidden)) continue;
    list.push({ group: 'files', prefix: '@', id: `f:${f.path}`, label: f.path, ic: 'file-text', run: () => a.openFile(f.path) });
  }
  const acts = [
    ['pal.newSession', 'plus', '/new', () => a.runCommand('/new')],
    ['pal.flush', 'minus', '/flush', () => a.runCommand('/flush')],
    ['act.runHeartbeat', 'heart-pulse', '/heartbeat', () => a.runHeartbeat({ fromChat: true })],
    ['act.reindex', 'database', null, () => a.reindex()],
    ['pal.seed', 'rotate-ccw', null, () => a.confirmReset('seeded')],
    ['pal.fresh', 'plus', null, () => a.confirmReset('fresh')],
    ['pal.theme', 'sun', null, () => a.setTheme(u.theme === 'light' ? 'dark' : 'light')],
    ['act.langToggle', 'globe', null, () => a.setLang(u.lang === 'tr' ? 'en' : 'tr')],
    ['pal.density', 'sliders', null, () => a.setDensity(u.density === 'compact' ? 'comfortable' : 'compact')],
    ['pal.singleKeys', 'keyboard', null, () => a.setSingleKeys(!u.singleKeys)],
    ['pal.explorer', 'sidebar-left', '⌘B', () => a.toggleExplorer()],
    ['pal.inspector', 'sidebar-right', '⌘⌥B', () => a.toggleInspector()],
    ['shortcuts.title', 'keyboard', '?', () => a.openShortcuts()],
    ['pal.inspPrompt', 'prompt', '[ ]', () => a.openInspector('prompt')],
    ['pal.inspMemory', 'database', null, () => a.openInspector('memory')],
    ['pal.inspTimeline', 'activity', null, () => a.openInspector('timeline')],
    ['pal.inspDiff', 'diff', null, () => a.openInspector('diff')],
  ];
  for (const [key, ic, hint, run] of acts) list.push({ group: 'actions', prefix: '>', id: `a:${key}`, label: t(key), ic, hint, run });
  return list;
}

export function openPalette(initial = '') {
  const recent = lsGet('lab.recent', []);
  const input = h('input', { class: 'palette-input', type: 'text', placeholder: t('palette.placeholder'), 'aria-label': t('palette.title'), role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'palette-list', 'aria-autocomplete': 'list', spellcheck: 'false', autocomplete: 'off', 'data-testid': 'palette-input' });
  input.value = initial;
  const listEl = h('div', { class: 'palette-list', id: 'palette-list', role: 'listbox', 'aria-label': t('palette.results') });
  let flat = []; let active = 0;
  const render = () => {
    let q = input.value.trim(); let only = null;
    if (/^[>@#?]/.test(q)) { only = q[0]; q = q.slice(1).trim(); }
    let all = items();
    if (only === '>') all = all.filter((x) => x.prefix === '>');
    else if (only === '@') all = all.filter((x) => x.group === 'files');
    else if (only === '#') all = all.filter((x) => x.group === 'scenarios');
    let scored = all.map((x) => ({ x, s: fuzzyScore(q, x.label) })).filter((y) => y.s >= 0);
    scored.sort((a, b) => (q ? b.s - a.s : 0) || (recent.indexOf(b.x.id) >= 0 ? 1 : 0) - (recent.indexOf(a.x.id) >= 0 ? 1 : 0));
    if (!q && !only) scored = scored.filter((y) => y.x.group !== 'files' || recent.includes(y.x.id)).slice(0, 40);
    const groups = new Map();
    if (q && !['>', '@', '#'].includes(only)) groups.set('memory', [{ id: 'mem', label: t('palette.searchMemory', { q }), ic: 'search', run: () => store.actions.searchMemory(q) }]);
    if (only === '?') { groups.clear(); groups.set('memory', [{ id: 'mem', label: t('palette.searchMemory', { q: q || '…' }), ic: 'search', run: () => q && store.actions.searchMemory(q) }]); scored = []; }
    for (const { x } of scored) { if (!groups.has(x.group)) groups.set(x.group, []); if (groups.get(x.group).length < 8) groups.get(x.group).push(x); }
    flat = [];
    const nodes = [];
    for (const g of ['scenarios', 'views', 'files', 'actions', 'memory']) {
      const arr = groups.get(g); if (!arr?.length) continue;
      nodes.push(h('div', { class: 'palette-group', role: 'presentation', lang: store.ui.lang }, t(`palette.group.${g}`)));
      for (const it of arr) {
        const idx = flat.length; flat.push(it);
        nodes.push(h('div', { class: ['palette-item', idx === active ? 'is-active' : ''], role: 'option', id: `pi-${idx}`, 'aria-selected': String(idx === active), onpointermove: () => { if (active !== idx) { active = idx; paint(); } }, onclick: () => runItem(it) },
          icon(it.ic, 14), h('span', { class: 'pi-label' }, it.label), it.meta || null, it.hint ? kbd(it.hint) : null));
      }
    }
    if (!flat.length) nodes.push(h('div', { class: 'palette-empty muted' }, t('palette.empty')));
    active = Math.min(active, Math.max(0, flat.length - 1));
    replace(listEl, nodes);
    input.setAttribute('aria-activedescendant', flat.length ? `pi-${active}` : '');
  };
  const paint = () => {
    listEl.querySelectorAll('.palette-item').forEach((el, i) => { el.classList.toggle('is-active', i === active); el.setAttribute('aria-selected', String(i === active)); });
    input.setAttribute('aria-activedescendant', `pi-${active}`);
    listEl.querySelector('.is-active')?.scrollIntoView({ block: 'nearest' });
  };
  let d;
  const runItem = (it) => {
    if (it.id !== 'mem') lsSet('lab.recent', [it.id, ...recent.filter((x) => x !== it.id)].slice(0, 12));
    d.close();
    setTimeout(() => it.run(), 0);
  };
  input.addEventListener('input', () => { active = 0; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % Math.max(1, flat.length); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + flat.length) % Math.max(1, flat.length); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (flat[active]) runItem(flat[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); d.close(); }
  });
  const foot = h('div', { class: 'palette-foot muted' }, kbd('↑↓'), ` ${t('palette.select')}`, kbd('↵'), ` ${t('palette.run')}`, kbd('Esc'), ` ${t('act.close')}`, h('span', { class: 'spacer' }), '> @ # ?');
  d = openDialog({ title: t('palette.title'), label: t('palette.title'), body: h('div', { class: 'palette-body' }, h('div', { class: 'palette-search' }, icon('search', 16), input), listEl, foot), cls: 'palette', testid: 'palette', noHeader: true, initialFocus: '.palette-input' });
  render();
  requestAnimationFrame(() => { input.focus(); input.setSelectionRange(input.value.length, input.value.length); });
}

export function openShortcuts() {
  const single = store.ui.singleKeys;
  const groups = [
    [t('shortcuts.general'), [['⌘K', t('palette.title')], ['/', t('shortcuts.focusComposer'), true], ['Esc', t('shortcuts.esc')], ['?', t('shortcuts.thisSheet'), true], ['⌘B', t('pal.explorer')], ['⌘⌥B', t('pal.inspector')]]],
    [t('rail.views'), VIEWS.map((v) => [v.key, viewLabel(v.id), true])],
    [t('view.chat'), [['Enter', t('composer.send')], ['⇧Enter', t('composer.hintNewline')], ['⌘↵', t('shortcuts.scenarioSend')], ['j / k', t('shortcuts.turns'), true], ['Enter', t('shortcuts.pinTurn')]]],
    [t('inspector.title'), [['[ / ]', t('shortcuts.tabs'), true]]],
    [t('shortcuts.editor'), [['e', t('editor.edit'), true], ['⌘S', t('shortcuts.save')], ['⌘W', t('shortcuts.closeTab')]]],
    [t('explorer.title'), [['↑ ↓', t('shortcuts.row')], ['← →', t('shortcuts.fold')], ['Home End', t('shortcuts.firstLast')], [t('shortcuts.letter'), t('shortcuts.typeahead')], ['⇧F10', t('shortcuts.contextMenu')]]],
  ];
  const d = openDialog({ title: t('shortcuts.title'), testid: 'shortcuts', cls: 'dialog-md', body: h('div', { class: 'shortcuts' },
    h('p', { class: 'muted small shortcuts-note' }, single ? t('shortcuts.singleOn') : t('shortcuts.singleOff')),
    groups.map(([g, rows]) => h('section', { class: 'sc-group' }, h('h3', { class: 'sc-group-title' }, g), h('table', { class: 'sc-table' }, h('tbody', null, rows.map(([k, v, isSingle]) => h('tr', { class: isSingle && !single ? 'is-off' : '' }, h('td', null, k.split(' / ').map((x, i) => [i ? ' / ' : '', kbd(x)])), h('td', null, v)))))))) });
  return d;
}
