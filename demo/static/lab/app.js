// app.js: boot, center router, the action registry, keyboard shortcuts (single-key ones can be
// switched off, WCAG 2.1.4), theme/language/motion/density, pane resizers, the explorer drawer
// and the inspector bottom sheet (detents 50% / 92%, velocity-aware dismiss).
import { h, replace, isTyping, clamp, prefersReducedMotion } from './ui/dom.js';
import { setLang, t } from './i18n/index.js';
import { store, refresh, renderNow, registerRenderer, persistUi, setView, refreshAll, loadFiles, loadFile, loadIndex, loadState, ingestEvent, loadParity } from './store.js';
import { api } from './api.js';
import { connectEvents } from './events.js';
import { initTooltips, toast, closeTop, topLayerOpen, confirmDialog, announce, openDialog, pulse } from './ui/overlay.js';
import { jsonDisclosure, btn } from './ui/kit.js';
import { tabStrip, viewLabel } from './views/shell.js';
import './views/explorer.js';
import './inspector/index.js';
import { renderChat, runTurn as chatRunTurn, runCommand, stopStream, focusTurnRelative, pinFocusedTurn } from './views/chat.js';
import { composerInsert, focusComposer, updateComposer } from './views/composer.js';
import { renderEditor, saveActive, startEdit, fixture, applyEdit, openSaveConfirm } from './views/editor.js';
import { renderHeartbeat, runHeartbeat as hbRun } from './views/heartbeat.js';
import { renderConsolidation } from './views/consolidation.js';
import { renderLive, liveSend as liveSendRaw } from './views/live.js';
import { renderParity } from './views/parity.js';
import { renderSettings, putSettings, checkProvider, confirmReset, resetWorkspace } from './views/settings.js';
import { renderScenarios, scenarioStrip } from './views/scenarios.js';
import { startScenario, stopScenario, insertAndSend, notify } from './scenarios/runner.js';
import { runSearch } from './inspector/memory.js';
import { openPalette, openShortcuts } from './ui/palette.js';

const app = document.getElementById('app');
const mq = { two: window.matchMedia('(max-width: 1279px)'), stacked: window.matchMedia('(max-width: 820px)'), compact: window.matchMedia('(max-width: 640px)') };
const layoutMode = () => (mq.compact.matches ? 'compact' : mq.stacked.matches ? 'stacked' : mq.two.matches ? 'two' : 'wide');

/* ---------- center router ---------- */
const VIEW_RENDER = { chat: renderChat, heartbeat: renderHeartbeat, consolidation: renderConsolidation, live: renderLive, parity: renderParity, settings: renderSettings, scenarios: renderScenarios };
// Focus, open <details> and inner scroll are kept by the refresh loop (store.js, ui/dom.js).
function renderCenter() {
  const el = document.getElementById('center');
  const u = store.ui;
  const body = h('div', { class: 'view-body', 'data-view': u.centerTab === 'view' ? u.view : `file:${u.centerTab}` });
  replace(el, tabStrip(), body);
  if (u.centerTab !== 'view') renderEditor(body, u.centerTab);
  else (VIEW_RENDER[u.view] || renderChat)(body);
}
registerRenderer('center', renderCenter);

/* ---------- actions ---------- */
const A = store.actions;
Object.assign(A, {
  renderCenterNow: () => renderNow('center'),
  syncShell: () => syncShell(),
  setView: (v) => { setView(v); if (v === 'parity') loadParity(); },
  openFile(path, lineA = null, lineB = null) {
    const u = store.ui;
    if (!path) return;
    u.openTabs = [path, ...u.openTabs.filter((p) => p !== path)].slice(0, 6);
    u.centerTab = path;
    if (lineA) u.focusLine[path] = [lineA, lineB || lineA]; else delete u.focusLine[path];
    store.data.changed.delete(path);
    loadFile(path, { force: !!store.data.fileCache.get(path)?.stale });
    if (layoutMode() === 'two') u.drawer = false;
    if (['stacked', 'compact'].includes(layoutMode())) { u.mobilePane = 'center'; u.sheet.open = false; }
    refresh('center', 'explorer', 'mobile', 'rail', 'inspector');
    syncShell();
  },
  closeTab(path) {
    const u = store.ui; const f = store.data.fileCache.get(path);
    const dirty = u.drafts[path] !== undefined && u.drafts[path] !== f?.content;
    const doIt = () => { u.openTabs = u.openTabs.filter((p) => p !== path); delete u.drafts[path]; delete u.draftBase[path]; u.editing[path] = false; if (u.centerTab === path) u.centerTab = u.openTabs[0] || 'view'; refresh('center', 'explorer'); };
    if (dirty) confirmDialog({ title: t('editor.unsavedTitle'), lines: [t('editor.closeDiscard', { p: path })], confirmLabel: t('editor.closeAndDiscard'), onConfirm: doIt });
    else doIt();
  },
  openInspector(tab) {
    const u = store.ui; u.inspectorTab = tab; persistUi();
    const mode = layoutMode();
    if (mode === 'stacked' || mode === 'compact') A.openSheet(); else u.inspectorCollapsed = false;
    refresh('inspector', 'center', 'rail'); syncShell();
  },
  closeInspector() { const u = store.ui; if (['stacked', 'compact'].includes(layoutMode())) A.closeSheet(); else { u.inspectorCollapsed = true; syncShell(); refresh('center', 'rail'); } },
  openSettings(section) {
    A.setView('settings');
    requestAnimationFrame(() => requestAnimationFrame(() => { const el = document.getElementById(`settings-${section}`); if (el) { el.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' }); pulse(el); } }));
  },
  toggleExplorer() {
    const u = store.ui; const mode = layoutMode();
    if (mode === 'wide') u.explorerCollapsed = !u.explorerCollapsed;
    else if (mode === 'two') u.drawer = !u.drawer;
    else { u.mobilePane = u.mobilePane === 'files' ? 'center' : 'files'; refresh('mobile', 'center', 'explorer'); }
    syncShell(); refresh('rail', 'center');
    if (u.drawer) requestAnimationFrame(() => document.querySelector('#explorer [role="treeitem"][tabindex="0"]')?.focus());
  },
  toggleInspector() {
    const u = store.ui; const mode = layoutMode();
    if (mode === 'stacked' || mode === 'compact') { if (u.sheet.open) A.closeSheet(); else A.openSheet(); return; }
    u.inspectorCollapsed = !u.inspectorCollapsed; syncShell(); refresh('center', 'inspector', 'rail');
  },
  openSheet() { const u = store.ui; u.sheet.open = true; u.sheet.detent = u.sheet.detent || 0.5; syncShell(); refresh('inspector', 'mobile'); },
  closeSheet() { const u = store.ui; u.sheet.open = false; syncShell(); refresh('mobile'); },
  openPalette, openShortcuts,
  async runTurn(text, kind, opts) { const r = await chatRunTurn(text, kind, opts); notify(r ? 'chat.turn.completed' : 'chat.turn.failed'); return r; },
  async runCommand(raw) { const r = await runCommand(raw); if (/^\/(new|reset)/i.test(raw)) notify('session.new'); if (/^\/flush/i.test(raw)) notify('flush.decided'); return r; },
  stopStream,
  async runHeartbeat(opts) { const r = await hbRun(opts); notify(r?.skipped ? 'heartbeat.skipped' : 'heartbeat.decided'); return r; },
  async liveSend(text) { await liveSendRaw(text); notify('live.turn'); },
  loadFile, loadFiles, loadIndex,
  startScenario, stopScenario, scenarioStrip,
  scenarioInsertSend: insertAndSend,
  focusScenario: () => document.querySelector('.scenario-strip')?.scrollIntoView({ block: 'start' }),
  fixture, applyEdit, openSaveConfirm, runSearch, composerInsert, putSettings, checkProvider, confirmReset, resetWorkspace,
  searchMemory(q) { const u = store.ui; u.search.query = q || ''; A.openInspector('memory'); if (q) runSearch(); },
  async memoryGet(path) {
    try {
      const res = await api.post('/api/get', { path });
      const d = openDialog({ title: `memory_get · ${path}`, cls: 'dialog-lg', testid: 'memory-get', body: h('div', { class: 'stack' }, h('pre', { class: 'ptext' }, res?.text ?? ''), jsonDisclosure(res, { title: 'memory_get' })), actions: [btn(t('act.open'), { onClick: () => { d.close(); A.openFile(path); } }), btn(t('act.close'), { kind: 'ghost', onClick: () => d.close() })] });
    } catch (err) { toast(err.message, { tone: 'danger' }); }
  },
  async reindex() {
    try { const r = await api.post('/api/reindex', {}); toast(t('toast.reindexed', { f: r?.indexedFiles ?? '—', c: r?.chunks ?? '—' }), { tone: 'ok' }); }
    catch (err) { toast(err.message, { tone: 'danger' }); }
    loadIndex();
  },
  setTheme(v) { store.ui.theme = v; applyPrefs(); persistUi(); refresh('top', 'center'); },
  setLang(v) { store.ui.lang = v; setLang(v); persistUi(); applyPrefs(); refresh(); updateComposer(); },
  setMotion(v) { store.ui.motion = v; applyPrefs(); persistUi(); refresh('center'); },
  setDensity(v) { store.ui.density = v; applyPrefs(); persistUi(); refresh('center'); },
  setSingleKeys(v) { store.ui.singleKeys = !!v; persistUi(); refresh('center'); toast(v ? t('shortcuts.singleOn') : t('shortcuts.singleOff'), { tone: 'info' }); },
});

/* ---------- preferences ---------- */
function applyPrefs() {
  const u = store.ui; const root = document.documentElement;
  if (u.theme === 'system') delete root.dataset.theme; else root.dataset.theme = u.theme;
  if (u.motion === 'reduced') root.dataset.motion = 'reduced'; else delete root.dataset.motion;
  if (u.density === 'comfortable') root.dataset.density = 'comfortable'; else delete root.dataset.density;
  // landmark names follow the language
  document.getElementById('rail')?.setAttribute('aria-label', t('rail.views'));
  document.getElementById('explorer')?.setAttribute('aria-label', t('explorer.title'));
  document.getElementById('inspector')?.setAttribute('aria-label', t('inspector.title'));
  document.getElementById('mobile-nav')?.setAttribute('aria-label', t('mobile.sections'));
  document.querySelector('.skip-link')?.replaceChildren(t('a11y.skip'));
}

/* ---------- shell (layout classes, widths, drawer, sheet) ---------- */
const DEFAULT_W = () => (window.innerWidth >= 1440 ? { explorer: 288, inspector: 448 } : { explorer: 256, inspector: 400 });
function syncShell() {
  const u = store.ui; const mode = layoutMode();
  app.dataset.layout = mode;
  const w = { ...DEFAULT_W(), ...u.widths };
  app.style.setProperty('--w-explorer', `${u.explorerCollapsed ? 0 : w.explorer}px`);
  app.style.setProperty('--w-inspector', `${u.inspectorCollapsed ? 0 : w.inspector}px`);
  app.classList.toggle('explorer-collapsed', u.explorerCollapsed && mode === 'wide');
  app.classList.toggle('inspector-collapsed', u.inspectorCollapsed && (mode === 'wide' || mode === 'two'));
  app.classList.toggle('drawer-open', u.drawer && mode === 'two');
  const sheetOpen = u.sheet.open && (mode === 'stacked' || mode === 'compact');
  app.classList.toggle('sheet-open', sheetOpen);
  const insp = document.getElementById('inspector');
  if (mode === 'stacked' || mode === 'compact') {
    insp.setAttribute('role', 'dialog'); insp.setAttribute('aria-modal', 'false'); insp.setAttribute('aria-hidden', String(!sheetOpen));
    if (!sheetOpen) insp.setAttribute('inert', ''); else insp.removeAttribute('inert');
    const H = window.innerHeight * 0.92;
    const y = sheetOpen ? H - window.innerHeight * u.sheet.detent : H + 24;
    insp.style.transform = `translateY(${Math.max(0, y)}px)`;
  } else { insp.removeAttribute('role'); insp.removeAttribute('aria-modal'); insp.removeAttribute('aria-hidden'); insp.removeAttribute('inert'); insp.style.transform = ''; }
  const exp = document.getElementById('explorer');
  if (mode === 'two' && !u.drawer) exp.setAttribute('inert', ''); else exp.removeAttribute('inert');
  document.getElementById('drawer-scrim').hidden = !(u.drawer && mode === 'two');
  document.getElementById('sheet-scrim').hidden = !sheetOpen;
}
Object.values(mq).forEach((m) => m.addEventListener('change', () => { const u = store.ui; if (!mq.two.matches) u.drawer = false; if (!mq.stacked.matches) { u.sheet.open = false; u.mobilePane = 'center'; } syncShell(); refresh(); }));
window.addEventListener('resize', () => { if (store.ui.sheet.open) syncShell(); });

function initResizers() {
  for (const el of document.querySelectorAll('.resizer')) {
    const pane = el.dataset.pane;
    const lim = pane === 'explorer' ? [224, 360] : [340, 560];
    const cur = () => ({ ...DEFAULT_W(), ...store.ui.widths })[pane];
    const set = (v) => { store.ui.widths = { ...store.ui.widths, [pane]: clamp(Math.round(v), lim[0], lim[1]) }; el.setAttribute('aria-valuenow', String(store.ui.widths[pane])); syncShell(); };
    el.setAttribute('aria-valuemin', String(lim[0])); el.setAttribute('aria-valuemax', String(lim[1])); el.setAttribute('aria-valuenow', String(cur()));
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add('is-dragging'); app.classList.add('is-resizing');
      const x0 = e.clientX; const w0 = cur();
      const move = (ev) => set(pane === 'explorer' ? w0 + (ev.clientX - x0) : w0 - (ev.clientX - x0));
      const up = () => { el.classList.remove('is-dragging'); app.classList.remove('is-resizing'); el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); persistUi(); };
      el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
    });
    el.addEventListener('dblclick', () => { const w = { ...store.ui.widths }; delete w[pane]; store.ui.widths = w; syncShell(); persistUi(); });
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault(); const dir = e.key === 'ArrowRight' ? 1 : -1;
      set(cur() + (pane === 'explorer' ? dir : -dir) * 16); persistUi();
    });
  }
}
function initSheet() {
  const insp = document.getElementById('inspector');
  let drag = null;
  insp.addEventListener('pointerdown', (e) => {
    if (!['stacked', 'compact'].includes(layoutMode()) || !store.ui.sheet.open) return;
    if (!e.target.closest('.insp-row') || e.target.closest('button')) return;
    const m = /translateY\(([-\d.]+)px\)/.exec(insp.style.transform); const y0 = m ? Number(m[1]) : 0;
    drag = { id: e.pointerId, start: e.clientY, y0, hist: [[performance.now(), e.clientY]] };
    insp.setPointerCapture(e.pointerId); insp.classList.add('is-dragging');
  });
  insp.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    let y = drag.y0 + (e.clientY - drag.start);
    if (y < 0) y = -Math.sqrt(-y) * 2;
    insp.style.transform = `translateY(${y}px)`;
    drag.hist.push([performance.now(), e.clientY]); if (drag.hist.length > 5) drag.hist.shift();
  });
  const end = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    insp.classList.remove('is-dragging');
    const [t0, y0] = drag.hist[0]; const [t1, y1] = drag.hist[drag.hist.length - 1];
    const v = (y1 - y0) / Math.max(1, t1 - t0);
    const H = window.innerHeight * 0.92; const cur = drag.y0 + (e.clientY - drag.start);
    drag = null;
    if (v > 0.11 || cur > H * 0.3 + (H - window.innerHeight * 0.5)) { A.closeSheet(); return; }
    const d50 = H - window.innerHeight * 0.5;
    store.ui.sheet.detent = Math.abs(cur - d50) < Math.abs(cur) ? 0.5 : 0.92;
    syncShell();
  };
  insp.addEventListener('pointerup', end); insp.addEventListener('pointercancel', end);
  document.getElementById('sheet-scrim').addEventListener('click', () => A.closeSheet());
  document.getElementById('drawer-scrim').addEventListener('click', () => { store.ui.drawer = false; syncShell(); refresh('rail'); });
}

/* ---------- keyboard ---------- */
let gPending = 0;
document.addEventListener('keydown', (e) => {
  const u = store.ui; const mod = e.metaKey || e.ctrlKey; const typing = isTyping(e.target);
  if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); if (!topLayerOpen()) openPalette(); return; }
  if (e.key === 'Escape') {
    // The top layer (palette, menu, save sheet, dialog) closes first; a running turn stops only
    // when no overlay is open.
    if (topLayerOpen()) { e.preventDefault(); closeTop(); return; }
    if (store.stream) { e.preventDefault(); stopStream(); return; }
    if (u.drawer) { u.drawer = false; syncShell(); refresh('rail'); return; }
    if (u.sheet.open) { A.closeSheet(); return; }
    return;
  }
  if (topLayerOpen()) return;
  if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); saveActive(); return; }
  if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); if (e.altKey) A.toggleInspector(); else A.toggleExplorer(); return; }
  if (mod && e.key === 'Enter') { e.preventDefault(); insertAndSend(); return; }
  if ((mod || e.altKey) && e.key.toLowerCase() === 'w' && u.centerTab !== 'view') { e.preventDefault(); A.closeTab(u.centerTab); return; }
  if (typing || mod || e.altKey || !u.singleKeys) return;
  if (gPending && Date.now() - gPending < 1000) {
    gPending = 0;
    const map = { s: 'chat', h: 'heartbeat', k: 'consolidation', l: 'live', p: 'parity', t: 'scenarios', a: 'settings' };
    if (map[e.key]) { e.preventDefault(); A.setView(map[e.key]); announce(t('a11y.view', { v: viewLabel(map[e.key]) })); }
    return;
  }
  if (e.key === 'g') { gPending = Date.now(); return; }
  if (e.key === '/') { e.preventDefault(); goToContent(); return; }
  if (e.key === '?') { e.preventDefault(); openShortcuts(); return; }
  if (e.key === '[' || e.key === ']') {
    const tabs = ['prompt', 'memory', 'timeline', 'diff']; const i = tabs.indexOf(u.inspectorTab);
    A.openInspector(tabs[(i + (e.key === ']' ? 1 : -1) + tabs.length) % tabs.length]); return;
  }
  if (e.key === 'e' && u.centerTab !== 'view') { e.preventDefault(); startEdit(u.centerTab); return; }
  if (u.view === 'chat' && u.centerTab === 'view') {
    if (e.key === 'j') { e.preventDefault(); focusTurnRelative(1); return; }
    if (e.key === 'k') { e.preventDefault(); focusTurnRelative(-1); return; }
    if (e.key === 'Enter' && pinFocusedTurn()) { e.preventDefault(); A.openInspector(u.inspectorTab); }
  }
});

/* ---------- skip link and '/': the composer, else the no-key notice, else the center ---------- */
function goToContent() {
  const u = store.ui;
  const land = () => {
    if (focusComposer()) return;
    const c = document.getElementById('center');
    const head = c.querySelector('.vh-name');
    const target = head || c;
    target.setAttribute('tabindex', '-1'); target.focus();
  };
  if (u.view !== 'chat' || u.centerTab !== 'view') { A.setView('chat'); requestAnimationFrame(() => requestAnimationFrame(land)); } else land();
}

/* ---------- boot ---------- */
function boot() {
  setLang(store.ui.lang);
  applyPrefs();
  initTooltips();
  initResizers();
  initSheet();
  syncShell();
  refresh();
  document.querySelector('.skip-link')?.addEventListener('click', (e) => { e.preventDefault(); goToContent(); });
  refreshAll();
  connectEvents({
    onEvent: (ev) => {
      ingestEvent(ev);
      if (ev.type === 'file.saved') notify('file.saved');
    },
    onStatus: (st) => { store.conn = st; refresh('status'); },
    onReconnect: () => { refreshAll(); },
    lastEventId: () => store.data.lastEventId,
  });
  // status clock and the cooldown countdown
  let lastMinute = -1;
  setInterval(() => {
    const minute = Math.floor(Date.now() / 60000);
    const cd = store.data.index?.cooldown?.until && store.data.index.cooldown.until > Date.now() - 1000;
    if (minute !== lastMinute || cd) { lastMinute = minute; refresh('status', 'top'); if (cd && store.ui.inspectorTab === 'memory') refresh('inspector'); }
  }, 1000);
  window.addEventListener('lab:saved', () => notify('file.saved'));
  window.addEventListener('lab:local', (e) => notify(String(e.detail)));
  document.getElementById('boot-fallback')?.remove();
}
boot();
