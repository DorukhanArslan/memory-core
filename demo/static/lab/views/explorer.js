// views/explorer.js: Sistem Dosyaları. Rows, badges and both orders come from
// GET /api/lab/files (FileEntry[], DESIGN §4.3); nothing about the layout is hardcoded here.
import { h, icon, replace, fmtN, fmtK, fmtTime, middleTruncate, copyText, trFold, clamp, basename } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, registerRenderer, persistUi, loadFiles } from '../store.js';
import { badge, badgeLabel, iconBtn, segmented, skeleton, failCard, emptyState, btn } from '../ui/kit.js';
import { openMenu, toast } from '../ui/overlay.js';
import { layoutLabel } from './shell.js';
import { previewFor } from '../inspector/prompt.js';

const BADGE_ORDER = ['pending', 'missing', 'truncated', 'outside_layout', 'dynamic', 'injected', 'empty', 'excluded', 'absent', 'session', 'today', 'yesterday', 'extension'];
export const isMemoryPath = (p) => p === 'MEMORY.md' || p.startsWith('memory/');

export function badgeTip(type, e) {
  switch (type) {
    case 'injected': return t('badgeTip.injected', { n: fmtN(e.truncation?.injected ?? e.chars) });
    case 'truncated': return e.truncation?.warningLine || '';
    case 'missing': return t('badgeTip.missing');
    case 'absent': return t('badgeTip.absent');
    case 'excluded': return e.excludedReason || '';
    case 'dynamic': return t('badgeTip.dynamic');
    case 'pending': return t('badgeTip.pending');
    case 'empty': return e.excludedReason || '';
    case 'extension': return t('badgeTip.extension');
    case 'outside_layout': return t('badgeTip.outsideLayout');
    case 'session': return t('badgeTip.session');
    case 'today': return t('badgeTip.today');
    case 'yesterday': return t('badgeTip.yesterday');
    default: return '';
  }
}
export function fileEntry(path) { return (store.data.files || []).find((e) => e.path === path) || null; }
export function injectedChars(e) { return e.badges?.includes('injected') ? (e.truncation?.injected ?? e.chars ?? 0) : 0; }

function fileRow(e, { level = 1, idx = null } = {}) {
  const u = store.ui;
  const open = u.centerTab === e.path;
  const sorted = [...(e.badges || [])].sort((a, b) => BADGE_ORDER.indexOf(a) - BADGE_ORDER.indexOf(b));
  const shown = sorted.slice(0, 1); const extra = sorted.length - shown.length;
  const changed = store.data.changed.has(e.path);
  const tip = `${fmtN(e.chars)} ${t('unit.charsUtf16')} · ${fmtN(e.bytes)} ${t('unit.bytes')}${e.mtimeMs ? ` · ${t('explorer.changedAt')} ${fmtTime(e.mtimeMs)}` : ''}`;
  const allLabels = sorted.map((b) => `${badgeLabel(b)}${badgeTip(b, e) ? `: ${badgeTip(b, e)}` : ''}`).join('\n');
  return h('div', {
    class: ['tree-row', open ? 'is-selected' : '', e.exists === false ? 'is-missing' : '', sorted.includes('outside_layout') ? 'is-outside' : ''],
    role: 'treeitem', 'aria-level': String(level), 'aria-selected': String(open), tabindex: '-1', 'data-path': e.path, 'data-testid': 'file-row',
    'aria-label': `${e.path}, ${sorted.map(badgeLabel).join(', ')}${changed ? `, ${t('explorer.changedThisTurn')}` : ''}`,
    style: { '--level': String(level) }, onclick: () => store.actions.openFile(e.path),
    oncontextmenu: (ev) => { ev.preventDefault(); rowMenu(ev.currentTarget, e); },
  },
  h('span', { class: 'tree-idx', 'aria-hidden': 'true' }, idx ? String(idx) : ''),
  icon(e.kind === 'bootstrap' ? 'file-text' : 'file', 14, 'tree-ic'),
  h('span', { class: 'tree-name', 'data-tip': tip }, basename(e.path)),
  h('span', { class: 'tree-badges', 'data-tip': allLabels }, shown.map((b) => { const el = badge(b); if (extra > 0) el.append(h('span', { class: 'badge-more', 'aria-label': t('explorer.moreBadges', { n: extra }) }, `+${extra}`)); return el; })),
  changed ? h('span', { class: 'change-dot', 'data-tip': t('explorer.changedThisTurn') }) : null,
  h('span', { class: 'tree-size' }, e.exists === false ? '—' : fmtK(e.chars)),
  h('button', { type: 'button', class: 'tree-more', tabindex: '-1', 'aria-label': t('explorer.fileMenu'), onclick: (ev) => { ev.stopPropagation(); rowMenu(ev.currentTarget, e); } }, icon('more', 14)));
}
function rowMenu(anchor, e) {
  const root = store.data.snap?.workspace?.root || '';
  openMenu(anchor, [
    { label: t('act.open'), ic: 'file-text', onSelect: () => store.actions.openFile(e.path) },
    { label: t('act.copyPath'), ic: 'copy', onSelect: () => copyText(root ? `${root}/${e.path}` : e.path).then(() => toast(t('toast.pathCopied'), { tone: 'ok' })) },
    { label: t('act.viewDiff'), ic: 'diff', onSelect: () => { store.ui.diffBase = 'reset'; store.actions.openInspector('diff'); } },
    isMemoryPath(e.path) ? { label: t('act.memoryGet'), ic: 'database', onSelect: () => store.actions.memoryGet(e.path) } : null,
    { label: t('act.searchFile'), ic: 'search', onSelect: () => store.actions.searchMemory(basename(e.path).replace(/\.md$/, '')) },
  ]);
}
function folderRow(id, label, { level = 1, meta = null, count = null, tone = null, tip = null } = {}) {
  const open = store.ui.expanded.has(id);
  return h('div', {
    class: 'tree-row tree-folder', role: 'treeitem', 'aria-level': String(level), 'aria-expanded': String(open), tabindex: '-1', 'data-folder': id,
    style: { '--level': String(level) }, onclick: () => toggleFolder(id),
  }, h('span', { class: 'tree-idx', 'aria-hidden': 'true' }), icon(open ? 'chevron-down' : 'chevron-right', 12, 'tree-chev'), icon(open ? 'folder-open' : 'folder', 14, 'tree-ic'),
  h('span', { class: 'tree-name' }, label), meta ? h('span', { class: ['tree-meta', tone ? `tone-${tone}` : ''], 'data-tip': tip }, meta) : null, count !== null ? h('span', { class: 'tree-size' }, String(count)) : null);
}
function toggleFolder(id) { const ex = store.ui.expanded; if (ex.has(id)) ex.delete(id); else ex.add(id); persistUi(); refresh('explorer'); }

/**
 * Groups FileEntry[] into the tree. Folder entries (kind "folder") carry the folder's own meta:
 * `memory` (note "indexed, not injected") heads the memory section; `user/` and `workspace/`
 * are extension folders only when their badges say "extension" (else "outside_layout", hidden).
 */
export function groupFiles(files) {
  const g = { root: [], daily: [], session: [], other: [], hidden: [], ext: new Map(), hiddenDirs: [], memoryEntry: null };
  for (const e of files) {
    const p = e.path;
    if (e.kind === 'folder') {
      const dir = p.replace(/\/$/, '');
      if (dir === 'memory') { g.memoryEntry = e; continue; }
      if (!g.ext.has(dir)) g.ext.set(dir, { entry: e, files: [] }); else g.ext.get(dir).entry = e;
      continue;
    }
    if (!p.includes('/')) { g.root.push(e); continue; }
    if (p.startsWith('memory/')) {
      if (e.kind === 'hidden' || p.startsWith('memory/.')) g.hidden.push(e);
      else if (e.kind === 'memory_daily') g.daily.push(e);
      else if (e.kind === 'memory_session') g.session.push(e);
      else g.other.push(e);
      continue;
    }
    const dir = p.split('/')[0];
    if (!g.ext.has(dir)) g.ext.set(dir, { entry: null, files: [] });
    g.ext.get(dir).files.push(e);
  }
  const byDateDesc = (a, b) => (a.path < b.path ? 1 : -1);
  g.daily.sort(byDateDesc); g.session.sort(byDateDesc); g.other.sort((a, b) => (a.path > b.path ? 1 : -1));
  for (const [dir, v] of g.ext) if (!(v.entry?.badges || v.files[0]?.badges || []).includes('extension')) g.hiddenDirs.push(dir);
  return g;
}

function renderExplorer() {
  const el = document.getElementById('explorer');
  const d = store.data; const u = store.ui;
  const root = d.snap?.workspace?.root || '';
  const head = h('div', { class: 'pane-head' },
    h('h2', { class: 'eyebrow', lang: u.lang }, t('explorer.title')),
    h('div', { class: 'pane-head-actions' },
      h('span', { class: 'kind-hint', 'data-tip': t('explorer.kindHint') }, u.promptKind),
      iconBtn('more', t('explorer.menu'), (e) => openMenu(e.currentTarget, [
        { label: t('explorer.showHidden'), checked: u.showHidden, onSelect: () => { u.showHidden = !u.showHidden; if (u.showHidden) u.expanded.add('memory/.hidden'); refresh('explorer'); } },
        { label: t('explorer.orderPrompt'), checked: u.explorerOrder === 'prompt', onSelect: () => { u.explorerOrder = 'prompt'; persistUi(); refresh('explorer'); } },
        { label: t('explorer.orderBudget'), checked: u.explorerOrder === 'budget', onSelect: () => { u.explorerOrder = 'budget'; persistUi(); refresh('explorer'); } },
        '-',
        { label: t('act.refresh'), ic: 'rotate-ccw', onSelect: () => loadFiles() },
        { label: t('act.reindex'), ic: 'database', onSelect: () => store.actions.reindex() },
      ], { align: 'end' }), { size: 'sm', testid: 'explorer-menu' })));
  const rootRow = root || layoutLabel() ? h('button', { type: 'button', class: 'root-row', 'data-tip': root ? `${root}\n${t('explorer.clickCopy')}` : null, 'aria-label': t('explorer.copyRoot'), onclick: () => root && copyText(root).then(() => toast(t('toast.pathCopied'), { tone: 'ok' })), 'data-testid': 'workspace-path' },
    icon('folder-open', 14), h('span', { class: 'root-path' }, root ? middleTruncate(root, 34) : '—'),
    layoutLabel() ? h('span', { class: 'chip tone-neutral chip-mono chip-xs' }, layoutLabel()) : null) : null;
  if (!d.files) {
    replace(el, head, rootRow, d.filesErr ? h('div', { class: 'pad-x' }, failCard(d.filesErr, { title: t('explorer.loadFailed'), onRetry: () => loadFiles() })) : skeleton(8));
    return;
  }
  if (!d.files.length) {
    replace(el, head, rootRow, emptyState({ title: t('explorer.empty'), actions: [btn(t('act.seed'), { size: 'sm', onClick: () => store.actions.confirmReset('seeded') })], testid: 'empty-explorer' }));
    return;
  }
  const g = groupFiles(d.files);
  const idxKey = u.explorerOrder === 'budget' ? 'loadIndex' : 'renderIndex';
  const rootSorted = [...g.root].sort((a, b) => (a[idxKey] ?? 999) - (b[idxKey] ?? 999) || (a.path > b.path ? 1 : -1));
  const rows = [];
  rootSorted.forEach((e) => rows.push(fileRow(e, { idx: e[idxKey] && !(e.badges || []).includes('outside_layout') ? e[idxKey] : null })));
  const memCount = g.daily.length + g.session.length + g.other.length;
  if (g.memoryEntry || memCount) rows.push(folderRow('memory', 'memory/', { meta: t('explorer.memoryMeta'), tip: g.memoryEntry?.note || null, count: memCount }));
  if ((g.memoryEntry || memCount) && u.expanded.has('memory')) {
    rows.push(folderRow('memory/daily', t('explorer.daily'), { level: 2, count: g.daily.length }));
    if (u.expanded.has('memory/daily')) g.daily.forEach((e) => rows.push(fileRow(e, { level: 3 })));
    rows.push(folderRow('memory/session', t('explorer.session'), { level: 2, count: g.session.length }));
    if (u.expanded.has('memory/session')) g.session.forEach((e) => rows.push(fileRow(e, { level: 3 })));
    g.other.forEach((e) => rows.push(fileRow(e, { level: 2 })));
    if (u.showHidden && g.hidden.length) {
      rows.push(folderRow('memory/.hidden', t('explorer.hiddenFolder'), { level: 2, meta: 'demo-only', tone: 'warn', count: g.hidden.length }));
      if (u.expanded.has('memory/.hidden')) g.hidden.forEach((e) => rows.push(fileRow(e, { level: 3 })));
    }
  }
  for (const [dir, v] of g.ext) {
    if (g.hiddenDirs.includes(dir)) continue;
    rows.push(folderRow(dir, `${dir}/`, { meta: t('explorer.extMeta'), tip: v.entry?.note || null, tone: 'ext', count: v.files.length }));
    if (u.expanded.has(dir)) v.files.forEach((e) => rows.push(fileRow(e, { level: 2 })));
  }
  const tree = h('div', { class: 'tree', role: 'tree', 'aria-label': t('explorer.title') }, rows);
  initTreeKeys(tree);
  // footer: the injected budget of the current preview (same numbers as Prompt › Bütçe);
  // until the preview answers, the FileEntry badges and truncation give an approximate sum.
  const pv = previewFor(u.promptKind).pv;
  const segs = pv ? (pv.files || []).map((f) => ({ name: f.name, chars: f.chars || 0, truncated: !!f.truncated }))
    : g.root.filter((e) => (e.badges || []).includes('injected')).map((e) => ({ name: e.path, chars: injectedChars(e), truncated: (e.badges || []).includes('truncated') }));
  const total = segs.reduce((a, x) => a + x.chars, 0);
  const cap = pv?.budget?.totalMaxChars ?? d.settings?.budgets?.totalMaxChars ?? null;
  const truncCount = segs.filter((x) => x.truncated).length;
  const injected = segs;
  const bar = h('button', { type: 'button', class: 'budget-mini', 'data-testid': 'budget-meter', 'aria-label': t('explorer.budgetAria', { a: fmtN(total), b: cap ? fmtN(cap) : '—' }), onclick: () => { u.openSections.add('budget'); store.actions.openInspector('prompt'); } },
    h('span', { class: 'budget-track' }, segs.map((x, i) => h('span', { class: ['budget-seg', x.truncated ? 'is-truncated' : ''], style: { '--w': `${cap ? (x.chars / cap) * 100 : 0}%`, '--c': `var(--seg-${(i % 8) + 1})` }, 'data-tip': `${x.name} · ${fmtN(x.chars)}` }))));
  replace(el, head, rootRow,
    g.hiddenDirs.length ? h('div', { class: 'tree-note' }, icon('eye', 12), t('explorer.hiddenDirs', { d: g.hiddenDirs.map((x) => `${x}/`).join(', ') })) : null,
    h('div', { class: 'pane-scroll' }, tree),
    h('div', { class: 'explorer-foot' },
      h('div', { class: 'budget-line' },
        h('span', null, t('explorer.injected'), ' ', h('b', { class: 'num' }, fmtN(total)), h('span', { class: 'muted' }, ` / ${cap ? fmtN(cap) : '—'}`)),
        h('span', { class: 'muted' }, `${injected.length} ${t('unit.files')}`),
        truncCount ? h('span', { class: 'tone-text-warn' }, `${truncCount} ${t('badge.truncated')}`) : null),
      bar,
      h('div', { class: 'order-line' }, h('span', { class: 'muted' }, t('explorer.order')),
        segmented({ options: [{ value: 'prompt', label: 'prompt', title: t('explorer.orderPromptTip') }, { value: 'budget', label: t('explorer.budget'), title: t('explorer.orderBudgetTip') }], value: u.explorerOrder, onChange: (v) => { u.explorerOrder = v; persistUi(); refresh('explorer'); }, aria: t('explorer.order'), size: 'xs' }))));
  const sel = tree.querySelector('.is-selected') || tree.querySelector('[role="treeitem"]');
  if (sel) sel.tabIndex = 0;
}

let typeBuf = ''; let typeTimer = null;
function initTreeKeys(tree) {
  tree.addEventListener('focusin', (e) => { const r = e.target.closest('[role="treeitem"]'); if (!r) return; tree.querySelectorAll('[role="treeitem"]').forEach((x) => { x.tabIndex = x === r ? 0 : -1; }); });
  tree.addEventListener('keydown', (e) => {
    const items = [...tree.querySelectorAll('[role="treeitem"]')];
    const cur = document.activeElement.closest('[role="treeitem"]');
    const i = items.indexOf(cur);
    const go = (j) => { const n = items[clamp(j, 0, items.length - 1)]; if (n) n.focus(); };
    const refocus = (sel) => requestAnimationFrame(() => document.querySelector(sel)?.focus());
    if (e.key === 'ArrowDown') { e.preventDefault(); go(i + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); go(i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); go(0); }
    else if (e.key === 'End') { e.preventDefault(); go(items.length - 1); }
    else if (e.key === 'ArrowRight' && cur?.dataset.folder) { e.preventDefault(); if (!store.ui.expanded.has(cur.dataset.folder)) { toggleFolder(cur.dataset.folder); refocus(`[data-folder="${cur.dataset.folder}"]`); } else go(i + 1); }
    else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      if (cur?.dataset.folder && store.ui.expanded.has(cur.dataset.folder)) { const id = cur.dataset.folder; toggleFolder(id); refocus(`[data-folder="${id}"]`); }
      else { const lvl = Number(cur?.getAttribute('aria-level') || 1); for (let j = i - 1; j >= 0; j--) if (Number(items[j].getAttribute('aria-level')) < lvl) { items[j].focus(); break; } }
    } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); cur?.click(); }
    else if (e.key === 'F10' && e.shiftKey && cur?.dataset.path) { e.preventDefault(); cur.querySelector('.tree-more')?.click(); }
    else if (e.key.length === 1 && /\S/.test(e.key) && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault(); e.stopPropagation();
      typeBuf += e.key; clearTimeout(typeTimer); typeTimer = setTimeout(() => { typeBuf = ''; }, 600);
      const name = (x) => trFold(x.querySelector('.tree-name')?.textContent || '');
      const hit = items.find((x, j) => j > i && name(x).startsWith(trFold(typeBuf))) || items.find((x) => name(x).startsWith(trFold(typeBuf)));
      hit?.focus();
    }
  });
}

registerRenderer('explorer', renderExplorer);
