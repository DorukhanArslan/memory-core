// ui/kit.js: chips, badges, buttons, segmented controls, switches, JSON disclosure,
// empty / skeleton / honesty / "henüz yok" / error cards. Every status carries an icon and text.
import { h, icon, fmtN, copyText } from './dom.js';
import { t, has } from '../i18n/index.js';
import { toast } from './overlay.js';
import { store } from '../store.js';

/* ---------- chips and badges ---------- */
export function chip({ label, tone = 'neutral', ic = null, onClick = null, aria = null, testid = null, ext = false, title = null, dot = null, cls = '', target = null }) {
  const Tag = onClick ? 'button' : 'span';
  // A long label may be cut with an ellipsis (max-width: 100%); its full text stays in the tooltip.
  const tip = title || (typeof label === 'string' && label.length > 36 ? label : null);
  return h(Tag, {
    class: ['chip', `tone-${tone}`, onClick ? 'is-button' : '', cls], type: onClick ? 'button' : null,
    'aria-label': aria, 'data-testid': testid, 'data-tip': tip, 'data-target': target, onclick: onClick,
  },
  dot ? h('span', { class: `dot dot-${dot}`, 'aria-hidden': 'true' }) : null,
  ic ? icon(ic, 12) : null,
  h('span', { class: 'chip-label' }, label),
  ext ? h('span', { class: 'chip-ext' }, icon('puzzle', 10), t('badge.extension')) : null);
}

export const BADGES = {
  injected: { tone: 'ok', ic: 'check' },
  truncated: { tone: 'warn', ic: 'scissors' },
  missing: { tone: 'danger', ic: 'alert-octagon' },
  absent: { tone: 'neutral', ic: 'minus' },
  excluded: { tone: 'neutral', ic: 'minus' },
  unreadable: { tone: 'danger', ic: 'alert-octagon' },
  retired: { tone: 'warn', ic: 'merge' },
  pending: { tone: 'accent', ic: 'clock' },
  empty: { tone: 'neutral', ic: 'circle' },
  extension: { tone: 'ext', ic: 'puzzle' },
  outside_layout: { tone: 'neutral', ic: 'minus' },
  session: { tone: 'info', ic: 'clock' },
  today: { tone: 'neutral', ic: 'dot' },
  yesterday: { tone: 'neutral', ic: 'dot' },
};
export const badgeLabel = (type) => t(`badge.${type}`);
export function badge(type, title = null) {
  const b = BADGES[type];
  if (!b) return h('span', { class: 'badge tone-neutral', 'data-testid': `badge-${type}`, 'data-tip': title }, icon('dot', 10), String(type));
  return h('span', { class: ['badge', `tone-${b.tone}`], 'data-testid': `badge-${type}`, 'data-tip': title }, icon(b.ic, 10), badgeLabel(type));
}

/* ---------- buttons ---------- */
export function btn(label, { ic = null, kind = 'default', size = 'md', onClick = null, kbd: k = null, disabled = false, testid = null, target = null, title = null, aria = null, type = 'button', busy = false, cls = '' } = {}) {
  return h('button', {
    type, class: ['btn', `btn-${kind}`, `btn-${size}`, busy ? 'is-busy' : '', cls], onclick: onClick, disabled: disabled || busy,
    'data-testid': testid, 'data-target': target, 'data-tip': title, 'aria-label': aria || (label ? null : title), 'aria-busy': busy ? 'true' : null,
  }, busy ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : ic ? icon(ic, 14) : null, label ? h('span', null, label) : null, k ? kbd(k) : null);
}
export function iconBtn(ic, title, onClick, { testid = null, pressed = null, cls = '', size = 'md', disabled = false } = {}) {
  return h('button', { type: 'button', class: ['icon-btn', `icon-btn-${size}`, cls], 'aria-label': title, 'data-tip': title, onclick: onClick, 'data-testid': testid, disabled, 'aria-pressed': pressed === null ? null : String(pressed) }, icon(ic, 16));
}
export function kbd(text) { return h('kbd', { class: 'kbd' }, text); }
export function spinner(cls = '') { return h('span', { class: ['spinner', cls], 'aria-hidden': 'true' }); }

/* ---------- segmented / radiogroup with roving tabindex ---------- */
export function segmented({ options, value, onChange, aria, size = 'md', testid = null, disabled = false }) {
  const root = h('div', { class: ['seg', `seg-${size}`], role: 'radiogroup', 'aria-label': aria, 'data-testid': testid });
  const btns = options.map((o) => {
    const on = o.value === value;
    return h('button', {
      type: 'button', role: 'radio', class: ['seg-item', on ? 'is-on' : ''], 'aria-checked': String(on), tabindex: on ? '0' : '-1',
      disabled: disabled || o.disabled, 'data-tip': o.title, 'data-value': o.value, onclick: () => { if (!on) onChange(o.value); },
    }, o.ic ? icon(o.ic, 12) : null, o.label);
  });
  if (!btns.some((b) => b.tabIndex === 0) && btns[0]) btns[0].tabIndex = 0;
  root.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const enabled = btns.filter((b) => !b.disabled);
    if (!enabled.length) return;
    let i = enabled.indexOf(document.activeElement);
    if (e.key === 'Home') i = 0; else if (e.key === 'End') i = enabled.length - 1;
    else i = (i + (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1) + enabled.length) % enabled.length;
    enabled[i].focus(); enabled[i].click();
  });
  root.append(...btns);
  return root;
}
export function toggle({ checked, onChange, label, testid = null, disabled = false, hint = null, id = null }) {
  const b = h('button', { id, type: 'button', role: 'switch', class: 'switch', 'aria-checked': String(!!checked), 'aria-label': typeof label === 'string' ? label : null, 'data-testid': testid, disabled, onclick: () => onChange(!checked) }, h('span', { class: 'switch-knob', 'aria-hidden': 'true' }));
  return h('span', { class: ['switch-row', disabled ? 'is-disabled' : ''] }, b, h('span', { class: 'switch-label', 'aria-hidden': 'true' }, label, hint ? h('span', { class: 'switch-hint' }, hint) : null));
}

/* ---------- JSON disclosure (closed by default, built lazily) ---------- */
export function jsonDisclosure(value, { title = 'JSON', open = false } = {}) {
  let text;
  try { text = JSON.stringify(value, null, 2) ?? String(value); } catch { text = String(value); }
  const type = Array.isArray(value) ? `array · ${value.length}` : value && typeof value === 'object' ? `object · ${Object.keys(value).length} ${t('json.fields')}` : typeof value;
  const d = h('details', { class: 'json', 'data-testid': 'json' });
  if (open) d.open = true;
  const pre = h('pre', { class: 'json-pre' });
  let built = false;
  const build = () => { if (built) return; built = true; pre.append(highlightJson(text)); };
  if (open) build();
  d.addEventListener('toggle', () => { if (d.open) build(); });
  d.append(
    h('summary', null, icon('chevron-right', 12, 'json-chev'), h('span', { class: 'json-title' }, title), h('span', { class: 'json-meta' }, `${type} · ${fmtN(text.length)} ${t('unit.chars')}`)),
    pre);
  // No interactive content inside <summary>: the copy button is a sibling over the summary row.
  return h('div', { class: 'json-box' }, d,
    h('button', { type: 'button', class: 'json-copy', 'aria-label': `${t('act.copy')}: ${title}`, 'data-tip': t('act.copy'), onclick: () => copyText(text).then(() => toast(t('toast.copied'), { tone: 'ok' })) }, icon('copy', 12)));
}
function highlightJson(text) {
  const frag = document.createDocumentFragment();
  const re = /("(?:\\.|[^"\\])*"(\s*:)?|\b-?\d+(?:\.\d+)?(?:e[+-]?\d+)?\b|\btrue\b|\bfalse\b|\bnull\b)/g;
  let last = 0; let m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    const v = m[0];
    const cls = v.startsWith('"') ? (m[2] ? 'j-key' : 'j-str') : /true|false/.test(v) ? 'j-bool' : v === 'null' ? 'j-null' : 'j-num';
    frag.append(h('span', { class: cls }, v));
    last = m.index + v.length;
  }
  if (last < text.length) frag.append(text.slice(last));
  return frag;
}

/* ---------- empty, skeleton, honesty, module missing, error ---------- */
export function emptyState({ title, text = null, actions = [], testid = null, ic = null, level = 3 }) {
  return h('div', { class: 'empty', 'data-testid': testid },
    ic ? h('div', { class: 'empty-ic', 'aria-hidden': 'true' }, icon(ic, 20)) : null,
    h(`h${level}`, { class: 'empty-title' }, title),
    text ? h('p', { class: 'empty-text' }, text) : null,
    actions.length ? h('div', { class: 'empty-actions' }, actions) : null);
}
export function skeleton(rows = 3) {
  return h('div', { class: 'skeleton-wrap', 'aria-busy': 'true', 'data-testid': 'skeleton' },
    Array.from({ length: rows }, (_, i) => h('div', { class: 'skeleton', style: { width: `${92 - (i % 3) * 14}%` } })));
}
export function honesty(text, tone = 'warn', ic = 'info', { testid = null } = {}) {
  return h('div', { class: ['honesty', `tone-${tone}`], role: 'note', 'data-testid': testid }, icon(ic, 12), h('span', null, text));
}
/** "henüz yok" card for a 501 module_missing (or 404: endpoint not landed yet). Controls stay disabled. */
export function missingCard(err, { compact = false } = {}) {
  const module = err?.module || err?.path || '?';
  return h('div', { class: ['missing-card', compact ? 'is-compact' : ''], role: 'status', 'data-testid': 'module-missing' },
    h('span', { class: 'chip tone-neutral chip-xs' }, icon('minus', 10), t('state.notYet')),
    h('span', { class: 'missing-text' }, t('state.waitsFor', { m: module })),
    err?.status === 404 ? h('span', { class: 'muted small' }, t('state.endpointMissing', { p: err.path || '' })) : null);
}
export function apiErrorCard(err, { title = null, onRetry = null } = {}) {
  return h('div', { class: 'error-card is-flat', role: 'alert', 'data-testid': 'error-card', tabindex: '-1' },
    h('div', { class: 'error-title' }, icon('alert-octagon', 14), title || t('state.error'), err?.code ? h('span', { class: 'chip tone-danger chip-xs chip-mono' }, err.code) : null, err?.status ? h('span', { class: 'muted small mono' }, `HTTP ${err.status}`) : null),
    h('div', { class: 'error-msg' }, String(err?.message || err || '')),
    onRetry ? h('div', { class: 'error-actions' }, btn(t('act.retry'), { size: 'sm', ic: 'rotate-ccw', onClick: onRetry })) : null,
    err?.body ? jsonDisclosure(err.body, { title: t('act.details') }) : null);
}
/** 404 not_found from the backend: the file is not on disk (never created, or deleted). */
export function notFoundCard(err, { path = null } = {}) {
  return h('div', { class: 'missing-card', role: 'status', 'data-testid': 'not-found' },
    h('span', { class: 'chip tone-neutral chip-xs' }, icon('minus', 10), t('state.notFound')),
    h('span', { class: 'missing-text' }, t('state.notFoundText', { p: path || err?.body?.path || '—' })),
    err?.code ? h('span', { class: 'muted small mono' }, `404 ${err.code}`) : null);
}
/**
 * Renders the right card for a failed load: "henüz yok" only for module_missing (or an unknown
 * route), "dosya yok / silindi" for not_found, otherwise the error card.
 */
export function failCard(err, opts = {}) {
  if (err?.missing) return missingCard(err, opts);
  if (err?.code === 'not_found') return notFoundCard(err, opts);
  return apiErrorCard(err, opts);
}

/* ---------- feature flags: short translated label, backend label and id in the tooltip ---------- */
export const flagLabel = (id, f) => (has(`flag.${id}`) ? t(`flag.${id}`) : f?.label || id);
export const flagTip = (id, f) => [id, f?.label].filter(Boolean).join(' · ');

/* ---------- "Nasıl çalışır?" (DESIGN §10 D6): short, collapsed per-view explanations ----------
 * Wording comes from docs/lab.md and docs/*.md only (the removed /memory-system page is not a
 * source for numbers); the source line names the doc. Open state is kept per view for the session. */
const HOW = { chat: 7, heartbeat: 4, consolidation: 5, live: 4, parity: 4, memory: 4 };
export function howItWorks(id) {
  const n = HOW[id] || 0;
  const key = id === 'parity' ? 'parity.how' : `how.${id}`; // the parity surface keeps its own ids
  const open = store.ui.howOpen?.has(id);
  const d = h('details', { class: 'how', 'data-how': id, 'data-testid': `how-${id}` },
    h('summary', null, icon('help', 12), h('span', { class: 'how-title' }, t('how.title'))),
    h('ul', { class: 'how-list' }, Array.from({ length: n }, (_, i) => h('li', null, t(`${key}.${i + 1}`)))),
    h('p', { class: 'how-src' }, `${t('how.source')}: `, h('span', { class: 'mono' }, t(`${key}.src`))));
  if (open) d.open = true;
  d.addEventListener('toggle', () => { const set = store.ui.howOpen || (store.ui.howOpen = new Set()); if (d.open) set.add(id); else set.delete(id); });
  return d;
}
