// ui/overlay.js: tooltips (delayed first, instant after), toasts, dialogs with a focus trap,
// confirm dialogs, origin-aware menus, live-region announcements and the one-shot "Göster" pulse.
import { h, icon, clear, prefersReducedMotion } from './dom.js';
import { t } from '../i18n/index.js';

const layer = () => document.getElementById('layer-root');
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/* ---------- tooltip ---------- */
let tipEl = null; let tipTimer = null; let lastHide = 0; let tipTarget = null;
export function initTooltips() {
  tipEl = h('div', { class: 'tooltip', role: 'tooltip', id: 'tooltip' });
  layer().append(tipEl);
  const show = (target) => {
    const text = target.getAttribute('data-tip'); if (!text || !target.isConnected) return;
    tipTarget = target;
    tipEl.textContent = text;
    tipEl.classList.toggle('is-instant', Date.now() - lastHide < 700);
    const r = target.getBoundingClientRect();
    tipEl.style.left = '0px'; tipEl.style.top = '0px';
    tipEl.classList.add('is-measuring');
    const tr = tipEl.getBoundingClientRect();
    tipEl.classList.remove('is-measuring');
    let left = r.left + r.width / 2 - tr.width / 2; left = Math.max(8, Math.min(window.innerWidth - tr.width - 8, left));
    let top = r.bottom + 6; let origin = 'top';
    if (top + tr.height > window.innerHeight - 8) { top = r.top - tr.height - 6; origin = 'bottom'; }
    tipEl.style.left = `${left}px`; tipEl.style.top = `${top}px`;
    tipEl.style.transformOrigin = `${r.left + r.width / 2 - left}px ${origin}`;
    target.setAttribute('aria-describedby', 'tooltip');
    tipEl.classList.add('is-open');
  };
  const hide = () => {
    clearTimeout(tipTimer);
    if (tipEl.classList.contains('is-open')) lastHide = Date.now();
    tipEl.classList.remove('is-open');
    if (tipTarget) { tipTarget.removeAttribute('aria-describedby'); tipTarget = null; }
  };
  const schedule = (target) => {
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => show(target), Date.now() - lastHide < 700 ? 0 : 400);
  };
  document.addEventListener('pointerover', (e) => {
    const target = e.target.closest?.('[data-tip]');
    if (!target) { hide(); return; }
    if (target === tipTarget) return;
    hide(); if (e.pointerType === 'mouse') schedule(target);
  });
  document.addEventListener('focusin', (e) => { const target = e.target.closest?.('[data-tip]'); if (target && target.matches(':focus-visible')) { hide(); schedule(target); } else hide(); });
  document.addEventListener('focusout', hide);
  document.addEventListener('pointerdown', hide);
  document.addEventListener('scroll', hide, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
}

/* ---------- toasts (auto-dismiss 5 s, paused on hover and while the tab is hidden) ---------- */
let toastRoot = null;
export function toast(text, { tone = 'info', action = null, ms = 5000 } = {}) {
  if (!layer()) return () => {};
  if (!toastRoot) { toastRoot = h('div', { class: 'toasts' }); layer().append(toastRoot); }
  const ic = { ok: 'check', warn: 'alert-triangle', danger: 'alert-octagon', info: 'info' }[tone] || 'info';
  const el = h('div', { class: ['toast', `tone-${tone}`], role: tone === 'danger' ? 'alert' : 'status', 'data-testid': 'toast' },
    icon(ic, 14), h('span', { class: 'toast-text' }, text),
    action ? h('button', { type: 'button', class: 'toast-action', onclick: () => { action.onClick(); close(); } }, action.label) : null,
    h('button', { type: 'button', class: 'toast-x', 'aria-label': t('act.close'), onclick: () => close() }, icon('x', 12)));
  let remaining = ms; let started = Date.now(); let timer = null;
  const run = () => { started = Date.now(); clearTimeout(timer); timer = setTimeout(close, remaining); };
  const pause = () => { clearTimeout(timer); remaining -= Date.now() - started; };
  el.addEventListener('pointerenter', pause); el.addEventListener('pointerleave', run);
  const vis = () => (document.hidden ? pause() : run());
  document.addEventListener('visibilitychange', vis);
  let closed = false;
  function close() {
    if (closed) return; closed = true;
    clearTimeout(timer); document.removeEventListener('visibilitychange', vis);
    el.classList.add('is-leaving'); setTimeout(() => el.remove(), prefersReducedMotion() ? 0 : 150);
  }
  toastRoot.append(el);
  requestAnimationFrame(() => el.classList.add('is-in'));
  run();
  return close;
}

/* ---------- dialog stack with focus trap ---------- */
const stack = [];
export function topLayerOpen() { return stack.length > 0; }
export function closeTop() { const top = stack[stack.length - 1]; if (top) { top.close(); return true; } return false; }
export function openDialog({ title, body, actions = [], role = 'dialog', cls = '', testid = null, initialFocus = null, onClose = null, label = null, noHeader = false }) {
  const trigger = document.activeElement;
  const titleId = `dlg-${Math.random().toString(36).slice(2, 8)}`;
  const scrim = h('div', { class: 'scrim', onclick: () => close() });
  const panel = h('div', { class: ['dialog', cls], role, 'aria-modal': 'true', 'aria-labelledby': noHeader ? null : titleId, 'aria-label': noHeader ? (label || title) : null, 'data-testid': testid, tabindex: '-1' },
    noHeader ? null : h('div', { class: 'dialog-head' }, h('h2', { class: 'dialog-title', id: titleId }, title),
      h('button', { type: 'button', class: 'icon-btn icon-btn-sm', 'aria-label': t('act.close'), onclick: () => close() }, icon('x', 16))),
    h('div', { class: 'dialog-body' }, body),
    actions.length ? h('div', { class: 'dialog-actions' }, actions) : null);
  const wrap = h('div', { class: ['dialog-wrap', cls.includes('palette') ? 'has-palette' : ''] }, scrim, panel);
  layer().append(wrap);
  panel.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const f = [...panel.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0]; const last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  const entry = { close };
  stack.push(entry);
  requestAnimationFrame(() => { wrap.classList.add('is-open'); (initialFocus ? panel.querySelector(initialFocus) : panel.querySelector(FOCUSABLE) || panel)?.focus(); });
  let closed = false;
  function close() {
    if (closed) return; closed = true;
    const i = stack.indexOf(entry); if (i >= 0) stack.splice(i, 1);
    wrap.classList.remove('is-open'); wrap.classList.add('is-leaving');
    setTimeout(() => wrap.remove(), prefersReducedMotion() || cls.includes('palette') ? 0 : 120);
    if (onClose) onClose();
    if (trigger && trigger.focus && document.contains(trigger)) trigger.focus();
  }
  return { close, panel };
}
export function confirmDialog({ title, lines = [], confirmLabel, danger = true, onConfirm, testid = 'confirm-dialog' }) {
  let d;
  const body = h('div', { class: 'confirm-body' }, h('ul', { class: 'confirm-list' }, lines.map((l) => h('li', null, icon(danger ? 'alert-triangle' : 'info', 12), l))));
  const cancel = h('button', { type: 'button', class: 'btn btn-ghost btn-md', 'data-testid': 'confirm-cancel', onclick: () => d.close() }, h('span', null, t('act.cancel')));
  const ok = h('button', { type: 'button', class: ['btn', danger ? 'btn-danger' : 'btn-primary', 'btn-md'], 'data-testid': 'confirm-ok', onclick: () => { d.close(); onConfirm(); } }, h('span', null, confirmLabel));
  d = openDialog({ title, body, actions: [cancel, ok], role: 'alertdialog', testid, cls: 'dialog-sm' });
  requestAnimationFrame(() => cancel.focus());
  return d;
}

/* ---------- menus ---------- */
export function openMenu(anchor, items, { align = 'start', testid = 'menu' } = {}) {
  const menu = h('div', { class: 'menu', role: 'menu', 'data-testid': testid });
  const entry = { close };
  const btns = [];
  for (const it of items) {
    if (!it) continue;
    if (it === '-') { menu.append(h('div', { class: 'menu-sep', role: 'separator' })); continue; }
    if (it.heading) { menu.append(h('div', { class: 'menu-heading', role: 'presentation' }, it.heading)); continue; }
    const b = h('button', {
      type: 'button', role: it.checked !== undefined ? 'menuitemcheckbox' : 'menuitem', 'aria-checked': it.checked !== undefined ? String(!!it.checked) : null,
      class: ['menu-item', it.danger ? 'is-danger' : '', it.checked ? 'is-checked' : ''], disabled: it.disabled, tabindex: '-1', 'data-tip': it.title || null,
      onclick: () => { close(); it.onSelect?.(); },
    }, icon(it.checked ? 'check' : (it.ic || 'dot'), 14, it.ic || it.checked ? '' : 'is-blank'), h('span', { class: 'menu-label' }, it.label), it.hint ? h('span', { class: 'menu-hint' }, it.hint) : null);
    btns.push(b); menu.append(b);
  }
  menu.addEventListener('keydown', (e) => {
    const enabled = btns.filter((b) => !b.disabled);
    const i = enabled.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); enabled[(i + 1) % enabled.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); enabled[(i - 1 + enabled.length) % enabled.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); enabled[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); enabled[enabled.length - 1]?.focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Tab') { e.preventDefault(); close(); }
  });
  layer().append(menu);
  const r = anchor.getBoundingClientRect();
  const mr = menu.getBoundingClientRect();
  let left = align === 'end' ? r.right - mr.width : r.left; left = Math.max(8, Math.min(window.innerWidth - mr.width - 8, left));
  let top = r.bottom + 4; let originY = 'top';
  if (top + mr.height > window.innerHeight - 8) { top = Math.max(8, r.top - mr.height - 4); originY = 'bottom'; }
  menu.style.left = `${left}px`; menu.style.top = `${top}px`;
  menu.style.transformOrigin = `${align === 'end' ? 'right' : 'left'} ${originY}`;
  const outside = (e) => { if (!menu.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) close(); };
  document.addEventListener('pointerdown', outside, true);
  stack.push(entry);
  anchor.setAttribute('aria-expanded', 'true');
  requestAnimationFrame(() => { menu.classList.add('is-open'); btns.find((b) => !b.disabled)?.focus(); });
  let closed = false;
  function close() {
    if (closed) return; closed = true;
    anchor.setAttribute('aria-expanded', 'false');
    menu.classList.remove('is-open');
    document.removeEventListener('pointerdown', outside, true);
    setTimeout(() => menu.remove(), prefersReducedMotion() ? 0 : 100);
    const i = stack.indexOf(entry); if (i >= 0) stack.splice(i, 1);
    if (anchor.isConnected) anchor.focus?.();
  }
  return close;
}

/* ---------- live regions and pulse ---------- */
export function announce(text, assertive = false) {
  const el = document.getElementById(assertive ? 'live-assertive' : 'live-polite');
  if (!el) return; clear(el); setTimeout(() => { el.textContent = text; }, 30);
}
/** One outline flash (≤ 200 ms), no motion under reduced motion. */
export function pulse(target) {
  const el = typeof target === 'string' ? document.querySelector(`[data-target="${target}"]`) : target;
  if (!el) return false;
  el.scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  el.classList.remove('is-pulsing'); void el.offsetWidth; el.classList.add('is-pulsing');
  setTimeout(() => el.classList.remove('is-pulsing'), 600);
  return true;
}
