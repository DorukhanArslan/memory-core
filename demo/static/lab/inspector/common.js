// inspector/common.js: shared inspector pieces (collapsible sections, prompt text blocks,
// notices, key/value rows) and the Project Context splitter used for per-file folds.
import { h, icon, fmtN, copyText, highlightWords } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, persistUi } from '../store.js';
import { iconBtn } from '../ui/kit.js';
import { toast } from '../ui/overlay.js';

export function section(id, title, { count = null, tags = [], body, copy = null, empty = false, testid = null, hint = null }) {
  const u = store.ui; const open = u.openSections.has(id);
  return h('section', { class: ['psec', open ? 'is-open' : '', empty ? 'is-empty' : ''], 'data-testid': testid || `prompt-section-${id}` },
    h('div', { class: 'psec-head' },
      h('button', { type: 'button', class: 'psec-toggle', 'aria-expanded': String(open), onclick: () => { if (open) u.openSections.delete(id); else u.openSections.add(id); persistUi(); refresh('inspector'); } },
        icon(open ? 'chevron-down' : 'chevron-right', 12), h('h3', { class: 'psec-title' }, title),
        count !== null ? h('span', { class: 'psec-count num' }, typeof count === 'number' ? fmtN(count) : count) : null,
        tags.map((x) => h('span', { class: ['chip', 'chip-xs', `tone-${x.tone || 'neutral'}`], 'data-tip': x.tip || null }, x.text))),
      hint ? h('span', { class: 'psec-hint muted' }, hint) : null,
      copy !== null ? iconBtn('copy', t('act.copy'), () => copyText(copy).then(() => toast(t('toast.copied'), { tone: 'ok' })), { size: 'xs' }) : null),
    open ? h('div', { class: 'psec-body' }, body()) : null);
}
export function promptPre(text, { terms = null, testid = null } = {}) {
  const pre = h('pre', { class: 'ptext', 'data-testid': testid });
  for (const line of String(text ?? '').split('\n')) {
    let cls = '';
    if (/^# /.test(line)) cls = 'pl-h1';
    else if (/^## /.test(line)) cls = 'pl-h2';
    else if (/\[\.\.\.truncated|…\(truncated|^\[Policy digest/.test(line)) cls = 'pl-warn';
    else if (/^\[MISSING\]/.test(line)) cls = 'pl-danger';
    else if (/^\[(Startup context|Untrusted daily memory|Bootstrap truncation warning)/.test(line)) cls = 'pl-info';
    else if (/^<!--.*-->$/.test(line.trim())) cls = 'pl-dim';
    pre.append(h('span', { class: ['pl', cls] }, terms ? highlightWords(line, terms) : (line || ' ')), '\n');
  }
  return pre;
}
export function notice(kind, text, { tone = 'info', title = null, ic = 'info', note = null } = {}) {
  return h('div', { class: ['notice', `tone-${tone}`], role: 'note', 'data-testid': `notice-${kind}` },
    h('div', { class: 'notice-head' }, icon(ic, 12), h('span', null, title || kind), note ? h('span', { class: 'chip chip-xs tone-neutral' }, note) : null),
    promptPre(text));
}
export function kvRow(k, v) { return h('div', { class: 'kv-row' }, h('span', { class: 'kv-k' }, k), h('span', { class: 'kv-v' }, v)); }
export function selectEl(options, value, onChange, { aria = null, id = null } = {}) {
  const sel = h('select', { class: 'select', id, 'aria-label': aria, onchange: (e) => onChange(e.target.value) }, options.map((o) => {
    const v = typeof o === 'string' ? o : o.value; const l = typeof o === 'string' ? o : o.label;
    return h('option', { value: v }, l);
  }));
  sel.value = value ?? '';
  return sel;
}
/**
 * Splits a rendered Project Context (stable or dynamic text) into its head and one block per
 * injected file, keyed by the `## <path>` heading lines of PromptView.files. Display only.
 */
export function splitFileSections(text, files) {
  const lines = String(text || '').split('\n');
  const heads = new Map();
  for (const f of files || []) heads.set(`## ${f.path}`, f);
  const out = { head: [], files: [] };
  let cur = null;
  for (const line of lines) {
    const f = heads.get(line) || (line.startsWith('## ') ? (files || []).find((x) => line.endsWith(`/${x.name}`) || line === `## ${x.name}`) : null);
    if (f) { cur = { file: f, lines: [line] }; out.files.push(cur); continue; }
    if (cur) cur.lines.push(line); else out.head.push(line);
  }
  return { head: out.head.join('\n').trimEnd(), files: out.files.map((x) => ({ file: x.file, text: x.lines.join('\n').trimEnd() })) };
}
/** Reads the `…(truncated NAME: kept H+T chars of N)…` marker from a rendered file block. */
export function truncationMarker(text) {
  const m = /…\(truncated [^:]+: kept (\d+)\+(\d+) chars of (\d+)\)…/.exec(text || '');
  return m ? { head: Number(m[1]), tail: Number(m[2]), raw: Number(m[3]) } : null;
}
