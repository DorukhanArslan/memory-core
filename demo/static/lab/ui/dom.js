// ui/dom.js: safe DOM building, formatting and Turkish-aware matching.
// Model and file text never reaches an HTML parser: every node is built with
// createElement / createTextNode, and dynamic sizes go through CSSOM.

const SVGNS = 'http://www.w3.org/2000/svg';
export const TZ = 'Europe/Istanbul';

let LANG = 'tr';
export function setFormatLang(lang) { LANG = lang === 'en' ? 'en' : 'tr'; }
export const locale = () => (LANG === 'tr' ? 'tr-TR' : 'en-GB');

/* ---------- element builder ---------- */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  applyProps(el, props);
  append(el, children);
  return el;
}

function applyProps(el, props) {
  if (!props) return;
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = Array.isArray(v) ? v.filter(Boolean).join(' ') : v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'style') for (const [sk, sv] of Object.entries(v)) el.style.setProperty(sk, sv);
    else if (k === 'dataset') for (const [dk, dv] of Object.entries(v)) el.dataset[dk] = dv;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === '') continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function replace(el, ...children) { clear(el); append(el, children); return el; }

export function icon(name, size = 16, cls = '') {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('class', `icon ${cls}`.trim());
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVGNS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

/* ---------- formatting (tr-TR / en-GB, Europe/Istanbul) ---------- */
export function fmtN(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString(locale());
}
export function fmtK(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1000) return String(n);
  return `${(n / 1000).toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })}k`;
}
export function fmtScore(x, digits = 3) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return '—';
  return Number(x).toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function fmtMs(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = (ms / 1000).toLocaleString(locale(), { maximumFractionDigits: 1, minimumFractionDigits: 0 });
  return `${s} ${LANG === 'tr' ? 'sn' : 's'}`;
}
const fmtCache = new Map();
function dtf(opts) {
  const key = locale() + JSON.stringify(opts);
  if (!fmtCache.has(key)) fmtCache.set(key, new Intl.DateTimeFormat(locale(), { timeZone: TZ, hour12: false, ...opts }));
  return fmtCache.get(key);
}
export function fmtTime(ts, { seconds = true, ms = false } = {}) {
  if (ts === null || ts === undefined || Number.isNaN(Number(ts))) return '—';
  const base = dtf({ hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) }).format(ts);
  return ms ? `${base}.${String(Math.floor(Number(ts) % 1000)).padStart(3, '0')}` : base;
}
export function fmtDateTime(ts) {
  if (ts === null || ts === undefined) return '—';
  return dtf({ year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(ts);
}
export function fmtRelMin(ms) {
  const m = Math.round(ms / 60000);
  const [dk, sa] = LANG === 'tr' ? ['dk', 'sa'] : ['min', 'h'];
  if (Math.abs(m) < 60) return `${m} ${dk}`;
  const hh = Math.floor(m / 60); const mm = m % 60;
  return mm ? `${hh} ${sa} ${mm} ${dk}` : `${hh} ${sa}`;
}
export function middleTruncate(s, max = 34) {
  const str = String(s ?? '');
  if (str.length <= max) return str;
  const keep = max - 1; const head = Math.ceil(keep * 0.35); const tail = keep - head;
  return `${str.slice(0, head)}…${str.slice(str.length - tail)}`;
}
export function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
export const basename = (p) => String(p || '').split('/').pop();

/* ---------- Turkish-aware folding, tokens, fuzzy match ---------- */
export function trFold(s) {
  return String(s || '')
    .toLocaleLowerCase('tr')
    .replace(/ı/g, 'i').replace(/ş/g, 's').replace(/ğ/g, 'g')
    .replace(/ü/g, 'u').replace(/ö/g, 'o').replace(/ç/g, 'c')
    .normalize('NFD').replace(/[̀-ͯ]/g, '');
}
/** Word tokens (letters and digits), folded. Used for whole-word highlighting only. */
export function wordTokens(s) {
  return trFold(s).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}
export function fuzzyScore(query, text) {
  const q = trFold(query).replace(/\s+/g, ''); const tx = trFold(text);
  if (!q) return 1;
  const idx = tx.indexOf(q);
  if (idx >= 0) return 1000 - idx - tx.length * 0.01;
  let ti = 0; let score = 0; let run = 0; let gaps = 0;
  for (const ch of q) {
    const found = tx.indexOf(ch, ti);
    if (found < 0) return -1;
    const gap = ti === 0 ? 0 : found - ti;
    run = gap === 0 && ti > 0 ? run + 1 : 0;
    gaps += gap;
    const wordStart = found === 0 || /[\s\-_/.·]/.test(tx[found - 1]);
    score += 10 + run * 6 + (wordStart ? 8 : 0) - gap * 2;
    ti = found + 1;
  }
  if (gaps > q.length * 3) return -1;
  return score;
}
/**
 * Marks whole words of `text` whose folded form equals one of `terms`
 * (word boundaries only, so "ne" never lights up inside "yerine").
 */
export function highlightWords(text, terms) {
  const frag = document.createDocumentFragment();
  const wanted = new Set((terms || []).map((x) => trFold(x)).filter((x) => x.length >= 2));
  const str = String(text ?? '');
  if (!wanted.size) { frag.append(str); return frag; }
  const re = /[\p{L}\p{N}]+/gu;
  let last = 0; let m;
  while ((m = re.exec(str))) {
    if (!wanted.has(trFold(m[0]))) continue;
    if (m.index > last) frag.append(str.slice(last, m.index));
    frag.append(h('mark', null, m[0]));
    last = m.index + m[0].length;
  }
  if (last < str.length) frag.append(str.slice(last));
  return frag;
}

/* ---------- misc ---------- */
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch {
    try {
      const ta = h('textarea', { class: 'sr-only' }); ta.value = text; document.body.append(ta); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return ok;
    } catch { return false; }
  }
}
export function lsGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}
export function lsSet(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } }
export function ssGet(key, fallback) {
  try { const v = sessionStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}
export function ssSet(key, value) {
  try { if (value === null || value === undefined) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
export const prefersReducedMotion = () => document.documentElement.dataset.motion === 'reduced'
  || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
export function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
export function isTyping(target) {
  const el = target || document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}
export function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

/* ---------- re-render preservation: focus, <details> state and inner scroll ----------
 * Regions are rebuilt with replace(); before a rebuild the renderer loop records where focus
 * was, which <details> were open or closed and how far inner scroll containers were scrolled,
 * keyed by a DOM path of stable attributes (else the index among same-tag siblings). After the
 * rebuild the same path is looked up again, so an unrelated LabEvent never sends focus to <body>
 * or collapses a disclosure (WCAG 2.4.3). */
const KEY_ATTRS = ['id', 'data-view', 'data-key', 'data-path', 'data-folder', 'data-turn', 'data-target', 'data-cmd', 'data-value', 'data-how'];
const SCROLLERS = '.view-scroll, .pane-scroll, .table-wrap, .json-pre, .parity-tests, .code, .hb-history';
function segment(el) {
  for (const a of KEY_ATTRS) { const v = el.getAttribute(a); if (v) return { tag: el.tagName, attr: a, value: v }; }
  const same = [...el.parentElement.children].filter((c) => c.tagName === el.tagName);
  const tid = el.getAttribute('data-testid');
  if (tid) return { tag: el.tagName, tid, n: same.filter((c) => c.getAttribute('data-testid') === tid).indexOf(el) };
  return { tag: el.tagName, n: same.indexOf(el) };
}
export function pathKey(root, el) {
  const segs = [];
  let n = el;
  while (n && n !== root) { if (!n.parentElement) return null; segs.unshift(segment(n)); n = n.parentElement; }
  return n === root ? segs : null;
}
export function resolvePath(root, segs) {
  if (!segs) return null;
  let cur = root;
  for (const s of segs) {
    const kids = [...cur.children].filter((c) => c.tagName === s.tag);
    const next = s.attr ? kids.find((c) => c.getAttribute(s.attr) === s.value) : s.tid ? kids.filter((c) => c.getAttribute('data-testid') === s.tid)[s.n] : kids[s.n];
    if (!next) return null;
    cur = next;
  }
  return cur;
}
const fingerprint = (el) => [el.tagName, el.getAttribute('data-testid') || '', el.getAttribute('aria-label') || '', (el.textContent || '').trim().slice(0, 60)].join('|');
function byFingerprint(root, fp) {
  const hits = [...root.querySelectorAll('button, input, textarea, select, a[href], [tabindex]')].filter((x) => fingerprint(x) === fp);
  return hits.length === 1 ? hits[0] : null;
}
export function captureState(root) {
  const st = { active: null, details: [], scroll: [] };
  const a = document.activeElement;
  if (a && a !== document.body && root.contains(a)) {
    const text = a.tagName === 'INPUT' || a.tagName === 'TEXTAREA';
    st.active = { el: a, path: pathKey(root, a), fp: fingerprint(a), sel: text && typeof a.selectionStart === 'number' ? [a.selectionStart, a.selectionEnd, a.selectionDirection || 'none'] : null, top: a.scrollTop };
  }
  for (const d of root.querySelectorAll('details')) { const p = pathKey(root, d); if (p) st.details.push({ p, open: d.open }); }
  for (const el of root.querySelectorAll(SCROLLERS)) if (el.scrollTop || el.scrollLeft) { const p = pathKey(root, el); if (p) st.scroll.push({ p, top: el.scrollTop, left: el.scrollLeft }); }
  return st;
}
export function restoreState(root, st) {
  for (const d of st.details) { const el = resolvePath(root, d.p); if (el && el.tagName === 'DETAILS' && el.open !== d.open) el.open = d.open; }
  for (const s of st.scroll) { const el = resolvePath(root, s.p); if (el) { el.scrollTop = s.top; el.scrollLeft = s.left; } }
  const a = st.active;
  if (!a) return;
  const cur = document.activeElement;
  if (cur && cur !== document.body && cur.isConnected) return; // the renderer placed focus itself
  const el = (a.el.isConnected && root.contains(a.el) ? a.el : null) || resolvePath(root, a.path) || byFingerprint(root, a.fp);
  if (!el || el.closest('[inert], [hidden]')) return;
  el.focus({ preventScroll: true });
  if (a.sel && document.activeElement === el) { try { el.setSelectionRange(a.sel[0], a.sel[1], a.sel[2]); } catch { /* not a text input */ } el.scrollTop = a.top; }
}
const REGION_IDS = ['topbar', 'rail', 'statusbar', 'mobile-nav', 'explorer', 'center', 'inspector'];
/** A getter for `el` that survives a region rebuild (menus and dialogs return focus through it). */
export function focusHandle(el) {
  const root = el ? REGION_IDS.map((id) => document.getElementById(id)).find((r) => r && r.contains(el)) : null;
  const path = root ? pathKey(root, el) : null; const fp = el ? fingerprint(el) : '';
  return () => (el?.isConnected ? el : root ? resolvePath(root, path) || byFingerprint(root, fp) : null);
}
