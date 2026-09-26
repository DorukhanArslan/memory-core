// views/shell.js: top bar, activity rail, center tab strip, status bar and the mobile nav.
// Each state has one home (critique #19): the workspace path lives in the explorer and the
// flush gate meter lives in the status bar.
import { h, icon, replace, fmtN, fmtTime, middleTruncate } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, registerRenderer, setView, chatKeyState } from '../store.js';
import { chip, iconBtn, segmented, kbd } from '../ui/kit.js';
import { openMenu } from '../ui/overlay.js';

export const VIEWS = [
  { id: 'chat', ic: 'message', key: 'g s' },
  { id: 'heartbeat', ic: 'heart-pulse', key: 'g h' },
  { id: 'consolidation', ic: 'merge', key: 'g k' },
  { id: 'live', ic: 'waveform', key: 'g l' },
  { id: 'parity', ic: 'scale', key: 'g p' },
  { id: 'scenarios', ic: 'flask', key: 'g t' },
  { id: 'settings', ic: 'sliders', key: 'g a' },
];
export const viewLabel = (id) => t(`view.${id}`);
export const viewById = (id) => VIEWS.find((v) => v.id === id) || VIEWS[0];

/* ---------- derived shell state (all from payloads) ---------- */
export function layoutLabel() {
  const d = store.data;
  const layout = d.settings?.layout || d.snap?.workspace?.layout;
  if (!layout) return null;
  if (layout === 'pin' || String(layout).endsWith('-pin')) {
    const pin = d.snap?.pin || d.parity?.pin;
    return pin ? `pin ${String(pin).slice(0, 8)}` : 'pin';
  }
  return 'MEMORY-CORE';
}
/** Model health from the latest chat outcome or provider check (no settings field exists for it). */
export function modelHealth() {
  const evs = store.data.events;
  for (let i = evs.length - 1; i >= 0; i--) {
    const e = evs[i];
    if (e.type === 'chat.turn.completed') return 'ok';
    if (e.type === 'chat.turn.failed') return 'error';
    if (e.type === 'provider.check' && (e.data?.which || e.data?.kind || 'chat') === 'chat') return e.data?.ok ? 'ok' : 'error';
  }
  return 'untested';
}
export function cooldownLeft() {
  const cd = store.data.index?.cooldown;
  if (!cd || !cd.until) return 0;
  return Math.max(0, Math.ceil((cd.until - Date.now()) / 1000));
}

function statusChips() {
  const d = store.data; const s = d.settings; const snap = d.snap;
  const list = [];
  const lay = layoutLabel();
  if (lay) list.push(chip({ label: lay, tone: lay.startsWith('pin') ? 'info' : 'neutral', onClick: () => store.actions.openSettings('layout'), title: lay.startsWith('pin') ? t('top.layoutPinTip') : t('top.layoutMemoryCoreTip'), testid: 'chip-layout', cls: 'chip-mono' }));
  const bs = snap?.bootstrap;
  if (bs?.status) {
    const pending = bs.status === 'pending';
    const modeTip = bs.mode ? `${t('prompt.bootstrapMode')}: ${bs.mode}${bs.modeReason ? ` · ${bs.modeReason}` : ''}` : '';
    list.push(chip({ label: `bootstrap: ${pending ? t('state.pending') : t('state.complete')}`, tone: pending ? 'accent' : 'ok', ic: pending ? 'clock' : 'check', onClick: () => store.actions.openInspector('prompt'), title: [pending ? t('top.bootstrapPendingTip') : t('top.bootstrapDoneTip'), modeTip].filter(Boolean).join(' · '), testid: 'chip-bootstrap' }));
  }
  if (s?.chat) {
    const ks = chatKeyState();
    const health = modelHealth();
    const dot = ks === 'none' ? 'grey' : health === 'error' ? 'danger' : health === 'ok' ? 'ok' : 'warn';
    const src = ks === 'page' ? t('settings.keyPage') : ks === 'env' ? '.env (MEMORY_CORE_DEMO_OPENAI_API_KEY)' : t('settings.keyNone');
    const healthText = { ok: t('top.lastCallOk'), error: t('top.lastCallError'), untested: t('top.untested') }[health];
    list.push(chip({ label: ks === 'none' ? t('top.noKey') : (s.chat.model || '—'), dot, tone: dot === 'danger' ? 'danger' : 'neutral', onClick: () => store.actions.openSettings('chat'), title: `${t('top.chatModel')}: ${s.chat.model || '—'} · ${t('settings.keySource')}: ${src} · ${healthText}`, aria: `${t('top.chatModel')} ${s.chat.model || ''}, ${healthText}`, testid: 'chip-model', cls: 'chip-mono' }));
  }
  if (s?.embedding) {
    const fts = s.embedding.mode === 'fts-only';
    list.push(chip({ label: fts ? t('search.ftsOnly') : `${t('search.hybrid')} · ${s.embedding.model || '—'}`, tone: fts ? 'warn' : 'info', ic: fts ? 'alert-triangle' : 'layers', onClick: () => store.actions.openSettings('embedding'), title: fts ? (s.embedding.reason || t('search.noEmbedder')) : t('search.hybridTip'), testid: 'chip-embedding' }));
  }
  if (s?.flush?.mode === 'per_turn') list.push(chip({ label: t('top.flushPerTurn'), tone: 'warn', ic: 'alert-triangle', onClick: () => store.actions.openSettings('flush'), title: t('top.flushPerTurnTip'), testid: 'chip-flush-mode' }));
  const cd = cooldownLeft();
  if (cd) list.push(chip({ label: `${t('search.cooldown')} ${cd} ${t('unit.sec')}`, tone: 'warn', ic: 'clock', testid: 'chip-cooldown', title: store.data.index?.cooldown?.error || '' }));
  return list;
}

function renderTopbar() {
  const el = document.getElementById('topbar');
  const u = store.ui;
  replace(el,
    h('div', { class: 'tb-left' },
      h('div', { class: 'brand' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('mark', 18)), h('h1', { class: 'brand-name' }, 'memory-core Lab')),
      h('div', { class: 'tb-chips', role: 'group', 'aria-label': t('top.status') }, statusChips())),
    h('div', { class: 'tb-right' },
      h('button', { type: 'button', class: 'tb-status-btn', 'aria-label': t('top.status'), 'aria-haspopup': 'menu', onclick: (e) => openStatusPopover(e.currentTarget), 'data-testid': 'status-popover-btn' }, icon('activity', 14), h('span', null, t('top.status'))),
      h('button', { type: 'button', class: 'palette-btn', onclick: () => store.actions.openPalette(), 'aria-label': t('palette.title'), 'data-testid': 'open-palette' }, icon('search', 14), h('span', { class: 'palette-btn-label' }, t('palette.search')), kbd('⌘K')),
      segmented({ options: [{ value: 'tr', label: 'TR' }, { value: 'en', label: 'EN' }], value: u.lang, onChange: (v) => store.actions.setLang(v), aria: t('settings.language'), size: 'sm', testid: 'lang-toggle' }),
      iconBtn(u.theme === 'light' ? 'moon' : 'sun', t('settings.theme'), () => store.actions.setTheme(u.theme === 'light' ? 'dark' : 'light'), { testid: 'theme-toggle' })));
  // Chips that do not fit are hidden whole (never clipped); the Durum popover then lists them.
  requestAnimationFrame(() => {
    const box = el.querySelector('.tb-chips'); if (!box) return;
    const chips = [...box.children];
    chips.forEach((c) => { c.hidden = false; });
    for (let i = chips.length - 1; i >= 0 && box.scrollWidth > box.clientWidth + 1; i--) chips[i].hidden = true;
    el.classList.toggle('has-hidden-chips', chips.some((c) => c.hidden));
  });
}
function openStatusPopover(anchor) {
  const d = store.data; const s = d.settings; const f = d.snap?.flush;
  openMenu(anchor, [
    { heading: t('top.status') },
    d.snap?.bootstrap ? { label: `bootstrap: ${d.snap.bootstrap.status === 'pending' ? t('state.pending') : t('state.complete')}`, ic: 'check', onSelect: () => store.actions.openInspector('prompt') } : null,
    layoutLabel() ? { label: `${t('settings.layout')}: ${layoutLabel()}`, ic: 'layers', onSelect: () => store.actions.openSettings('layout') } : null,
    s?.chat ? { label: `${t('top.chatModel')}: ${chatKeyState() === 'none' ? t('top.noKey') : s.chat.model}`, ic: 'key', onSelect: () => store.actions.openSettings('chat') } : null,
    s?.embedding ? { label: s.embedding.mode === 'fts-only' ? t('search.ftsOnly') : `${t('search.hybrid')} · ${s.embedding.model}`, ic: 'search', onSelect: () => store.actions.openSettings('embedding') } : null,
    f ? { label: `flush ${f.threshold ? `${fmtN(f.totalTokens)} / ${fmtN(f.threshold)}` : '—'}`, ic: 'minus', onSelect: () => store.actions.openInspector('prompt') } : null,
    '-',
    { label: t('act.langToggle'), ic: 'globe', hint: store.ui.lang.toUpperCase(), onSelect: () => store.actions.setLang(store.ui.lang === 'tr' ? 'en' : 'tr') },
  ], { align: 'end', testid: 'status-popover' });
}

/* ---------- rail ---------- */
function renderRail() {
  const el = document.getElementById('rail');
  const u = store.ui;
  const failing = Object.values(u.scenarioResults || {}).filter((r) => r.status === 'failed').length;
  const mk = (v, extra = null) => h('button', {
    type: 'button', role: 'tab', class: ['rail-btn', u.view === v.id ? 'is-active' : ''], 'aria-selected': String(u.view === v.id),
    tabindex: u.view === v.id ? '0' : '-1', 'aria-label': viewLabel(v.id), 'data-tip': `${viewLabel(v.id)} · ${v.key}`, 'data-testid': `rail-${v.id}`, onclick: () => setView(v.id),
  }, icon(v.ic, 18), extra);
  const list = h('div', { class: 'rail-group', role: 'tablist', 'aria-orientation': 'vertical', 'aria-label': t('rail.views') },
    VIEWS.filter((v) => v.id !== 'settings').map((v) => mk(v, v.id === 'scenarios' && failing ? h('span', { class: 'rail-badge', 'aria-label': t('rail.failing', { n: failing }) }, String(failing)) : null)));
  list.addEventListener('keydown', (e) => {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const btns = [...list.querySelectorAll('.rail-btn')];
    let i = btns.indexOf(document.activeElement);
    if (e.key === 'Home') i = 0; else if (e.key === 'End') i = btns.length - 1; else i = (i + (e.key === 'ArrowDown' ? 1 : -1) + btns.length) % btns.length;
    btns[i].focus(); btns[i].click();
  });
  replace(el,
    h('button', { type: 'button', class: ['rail-btn', 'rail-files', u.drawer || !u.explorerCollapsed ? 'is-on' : ''], 'aria-label': t('explorer.title'), 'aria-pressed': String(u.drawer || !u.explorerCollapsed), 'data-tip': `${t('explorer.title')} · ⌘B`, onclick: () => store.actions.toggleExplorer(), 'data-testid': 'rail-files' }, icon('sidebar-left', 18)),
    h('div', { class: 'rail-sep', 'aria-hidden': 'true' }),
    list,
    h('div', { class: 'rail-spacer' }),
    h('button', { type: 'button', class: ['rail-btn', !u.inspectorCollapsed ? 'is-on' : ''], 'aria-label': t('inspector.title'), 'aria-pressed': String(!u.inspectorCollapsed), 'data-tip': `${t('inspector.title')} · ⌘⌥B`, onclick: () => store.actions.toggleInspector(), 'data-testid': 'rail-inspector' }, icon('sidebar-right', 18)),
    mk(viewById('settings')),
    h('button', { type: 'button', class: 'rail-btn', 'aria-label': t('shortcuts.title'), 'data-tip': `${t('shortcuts.title')} · ?`, onclick: () => store.actions.openShortcuts(), 'data-testid': 'rail-shortcuts' }, icon('keyboard', 18)));
}

/* ---------- center tab strip (hidden while only the view tab would show) ---------- */
export function tabStrip() {
  const u = store.ui;
  if (!u.openTabs.length) return null;
  const v = viewById(u.view);
  const tabs = [h('button', { type: 'button', role: 'tab', class: ['ctab', 'ctab-view', u.centerTab === 'view' ? 'is-active' : ''], 'aria-selected': String(u.centerTab === 'view'), onclick: () => { u.centerTab = 'view'; refresh('center', 'explorer'); }, 'data-testid': 'center-tab' }, icon(v.ic, 14), h('span', null, viewLabel(v.id)), icon('pin', 10, 'ctab-pin'))];
  for (const p of u.openTabs) {
    const cached = store.data.fileCache.get(p);
    const dirty = u.drafts[p] !== undefined && cached && u.drafts[p] !== cached.content;
    tabs.push(h('div', { class: ['ctab', u.centerTab === p ? 'is-active' : ''], role: 'presentation' },
      h('button', { type: 'button', role: 'tab', class: 'ctab-main', 'aria-selected': String(u.centerTab === p), 'data-tip': p, onclick: () => { u.centerTab = p; refresh('center', 'explorer'); }, 'data-testid': 'center-tab' }, icon('file-text', 14), h('span', null, p.split('/').pop()), dirty ? h('span', { class: 'dirty-dot', 'aria-label': t('editor.unsaved') }) : null),
      h('button', { type: 'button', class: 'ctab-x', 'aria-label': t('editor.closeTab', { p }), onclick: () => store.actions.closeTab(p) }, icon('x', 12))));
  }
  return h('div', { class: 'tabstrip' }, h('div', { class: 'tabs', role: 'tablist', 'aria-label': t('center.tabs') }, tabs));
}

/* ---------- status bar ---------- */
export function flushMeter() {
  const f = store.data.snap?.flush;
  if (!f) return null;
  const thr = f.threshold;
  const pct = thr ? (f.totalTokens / thr) * 100 : 0;
  return { f, thr, pct, over: pct >= 100 };
}
function renderStatus() {
  const el = document.getElementById('statusbar');
  const d = store.data; const u = store.ui;
  const idx = d.index;
  const fm = flushMeter();
  const sc = u.scenario;
  const conn = store.conn;
  const connLabel = { open: t('status.eventsOpen'), connecting: t('status.eventsConnecting'), retrying: t('status.eventsRetry', { n: conn.attempt }), missing: t('status.eventsMissing') }[conn.state] || conn.state;
  const connDot = { open: 'ok', connecting: 'warn', retrying: 'danger', missing: 'grey' }[conn.state] || 'grey';
  const identity = idx?.identity;
  const idTone = { valid: 'ok', mismatched: 'danger', missing: 'warn' }[identity?.status] || 'grey';
  const offset = d.snap?.clock?.offsetMs || d.heartbeat?.clock?.offsetMs || 0;
  const flushTip = fm ? [
    `${t('flush.formula')}: ${fm.f.contextWindowTokens ? fmtN(fm.f.contextWindowTokens) : '—'} − ${fmtN(fm.f.reserveFloorTokens ?? 20000)} − ${fmtN(fm.f.softThresholdTokens ?? 4000)} = ${thr0(fm.thr)}`,
    `${t('flush.lastReason')}: ${fm.f.lastReason || '—'}`,
    fm.f.mode ? `${t('flush.mode')}: ${fm.f.mode === 'per_turn' ? t('settings.flushPerTurn') : t('settings.flushThreshold')}` : null,
  ].filter(Boolean).join('\n') : t('state.notYet');
  replace(el,
    idx ? h('button', { type: 'button', class: 'sb-item', onclick: () => store.actions.openInspector('memory'), 'data-tip': t('status.lastReindex') }, icon('database', 12), `${t('status.index')} ${fmtN(idx.files)} ${t('unit.files')} · ${fmtN(idx.chunks)} ${t('unit.chunks')} · ${fmtTime(idx.lastReindexAt)}`)
      : h('span', { class: 'sb-item' }, icon('database', 12), `${t('status.index')} ${d.indexErr?.missing ? t('state.notYet') : '—'}`),
    h('span', { class: 'sb-sep', 'aria-hidden': 'true' }),
    h('button', { type: 'button', class: 'sb-item', 'data-tip': `${identity?.reason || ''}\n${t('memory.identityNotFile')}`.trim(), 'data-testid': 'index-identity', onclick: () => store.actions.openInspector('memory') }, h('span', { class: `dot dot-${idTone}`, 'aria-hidden': 'true' }), `${t('memory.identity')}: ${identity?.status ? t(`identity.${identity.status}`) : '—'}`),
    h('span', { class: 'sb-sep', 'aria-hidden': 'true' }),
    h('button', { type: 'button', class: ['sb-item', fm?.over ? 'is-over' : ''], 'data-tip': flushTip, 'data-testid': 'flush-meter', onclick: () => { u.openSections.add('flush'); store.actions.openInspector('prompt'); } },
      'flush', h('span', { class: ['sb-meter', fm?.over ? 'is-over' : fm && fm.pct >= 85 ? 'is-near' : ''], role: 'meter', 'aria-label': t('flush.gate'), 'aria-valuemin': '0', 'aria-valuemax': String(fm?.thr || 0), 'aria-valuenow': String(fm?.f.totalTokens || 0) }, h('span', { style: { '--p': `${Math.min(100, fm?.pct || 0)}%` } })),
      fm && fm.thr ? `${fmtN(fm.f.totalTokens)}/${fmtN(fm.thr)}` : '—',
      fm?.over ? h('span', { class: 'sb-over' }, fm.f.flushedThisCycle ? t('flush.overFlushed', { n: fm.f.cycle ?? '?' }) : t('flush.over')) : null),
    h('span', { class: 'sb-sep', 'aria-hidden': 'true' }),
    h('span', { class: 'sb-item', 'data-testid': 'events-status', 'data-tip': t('status.eventsTip') }, h('span', { class: ['dot', `dot-${connDot}`, conn.state === 'open' ? 'is-live' : ''], 'aria-hidden': 'true' }), `${connLabel} · ${fmtN(d.events.length)}`),
    sc ? h('span', { class: 'sb-sep', 'aria-hidden': 'true' }) : null,
    sc ? h('button', { type: 'button', class: 'sb-item tone-text-accent', onclick: () => store.actions.focusScenario() }, icon('flask', 12), `${sc.id} · ${t('scenario.step')} ${Math.min(sc.step + 1, sc.def.steps.length)}/${sc.def.steps.length}`) : null,
    h('span', { class: 'sb-spacer' }),
    offset ? h('span', { class: 'sb-item tone-text-warn', 'data-tip': t('hb.clockTip') }, icon('clock', 12), `${t('hb.virtual')} +${Math.round(offset / 60000)} ${t('unit.min')}`) : null,
    h('span', { class: 'sb-item', 'data-tip': 'Europe/Istanbul' }, `${fmtTime(Date.now(), { seconds: false })} ${t('status.tz')}`));
}
const thr0 = (v) => (v === null || v === undefined ? '—' : fmtN(v));

/* ---------- mobile nav (stacked < 820, bottom tab bar < 640) ---------- */
function renderMobile() {
  const el = document.getElementById('mobile-nav');
  const u = store.ui;
  const item = (id, label, ic, onClick, active) => h('button', { type: 'button', class: ['mnav-btn', active ? 'is-active' : ''], 'aria-pressed': String(!!active), onclick: onClick, 'data-testid': `mnav-${id}` }, icon(ic, 18), h('span', null, label));
  replace(el,
    item('chat', viewLabel('chat'), 'message', () => { u.mobilePane = 'center'; setView('chat'); }, u.mobilePane === 'center' && u.view === 'chat' && !u.sheet.open),
    item('files', t('mobile.files'), 'folder', () => { u.mobilePane = 'files'; u.sheet.open = false; store.actions.syncShell(); refresh('mobile', 'center', 'inspector', 'explorer'); window.scrollTo(0, 0); }, u.mobilePane === 'files'),
    item('inspector', t('inspector.title'), 'layers', () => store.actions.openSheet(), u.sheet.open),
    item('scenarios', viewLabel('scenarios'), 'flask', () => { u.mobilePane = 'center'; setView('scenarios'); }, u.mobilePane === 'center' && u.view === 'scenarios' && !u.sheet.open),
    item('more', t('mobile.more'), 'more', (e) => openMenu(e.currentTarget, [
      ...VIEWS.filter((v) => !['chat', 'scenarios'].includes(v.id)).map((v) => ({ label: viewLabel(v.id), ic: v.ic, checked: u.view === v.id && u.mobilePane === 'center', onSelect: () => { u.mobilePane = 'center'; setView(v.id); } })),
      '-', { label: t('shortcuts.title'), ic: 'keyboard', onSelect: () => store.actions.openShortcuts() },
    ], { align: 'end' }), u.mobilePane === 'center' && !['chat', 'scenarios'].includes(u.view) && !u.sheet.open));
  document.getElementById('app').dataset.mpane = u.mobilePane;
}

registerRenderer('top', renderTopbar);
registerRenderer('rail', renderRail);
registerRenderer('status', renderStatus);
registerRenderer('mobile', renderMobile);
