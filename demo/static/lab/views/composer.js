// views/composer.js: the persistent composer (autosize 1-8 rows, Enter sends, Shift+Enter
// newline), the session-kind chip, the slash menu (opens instantly) and the no-key notice.
import { h, icon, replace, trFold } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, chatKeyState } from '../store.js';
import { btn, kbd } from '../ui/kit.js';
import { openMenu } from '../ui/overlay.js';

export const SESSION_KINDS = ['main', 'group', 'subagent', 'cron', 'heartbeat'];
const SLASH = [
  { cmd: '/new', args: '[metin]', hint: 'slash.new' },
  { cmd: '/reset', args: '[metin]', hint: 'slash.reset' },
  { cmd: '/flush', args: '', hint: 'slash.flush', tag: 'slash.forced' },
  { cmd: '/heartbeat', args: '', hint: 'slash.heartbeat' },
  { cmd: '/ara', args: '<sorgu>', hint: 'slash.search' },
  { cmd: '/tür', args: '<main|group|subagent|cron|heartbeat>', hint: 'slash.kind' },
];

let dock = null; let input = null; let sendBtn = null; let kindBtn = null; let slashEl = null; let noKeyEl = null; let row = null; let hintEl = null;
let slashIndex = 0;

export function composerEl() { if (!dock) build(); return dock; }
function build() {
  input = h('textarea', { id: 'composer-input', class: 'composer-input', rows: '1', 'aria-label': t('composer.label'), 'aria-describedby': 'composer-hint', 'data-testid': 'composer-input', spellcheck: 'false' });
  kindBtn = h('button', { type: 'button', class: 'kind-chip', 'aria-haspopup': 'menu', 'data-testid': 'composer-kind', onclick: (e) => openMenu(e.currentTarget, SESSION_KINDS.map((k) => ({ label: k, checked: store.ui.composerKind === k, onSelect: () => { store.ui.composerKind = k; updateComposer(); } }))) });
  sendBtn = h('button', { type: 'button', class: 'send-btn', 'data-testid': 'composer-send', onclick: () => (store.stream ? store.actions.stopStream() : submit()) });
  slashEl = h('div', { class: 'slash-menu', role: 'listbox', id: 'slash-menu', 'data-testid': 'slash-menu', hidden: true });
  noKeyEl = h('div', { class: 'nokey', role: 'status', 'data-testid': 'composer-nokey' });
  row = h('div', { class: 'composer' }, kindBtn, input, sendBtn);
  hintEl = h('div', { class: 'composer-hint', id: 'composer-hint' });
  dock = h('div', { class: 'composer-dock', 'data-testid': 'composer' }, noKeyEl, slashEl, row, hintEl);
  input.addEventListener('input', () => { autosize(); updateSlash(); });
  input.addEventListener('keydown', onKey);
  updateComposer();
}
function onKey(e) {
  if (!slashEl.hidden) {
    const items = [...slashEl.querySelectorAll('.slash-item')];
    if (e.key === 'ArrowDown') { e.preventDefault(); slashIndex = (slashIndex + 1) % items.length; paintSlash(items); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); slashIndex = (slashIndex - 1 + items.length) % items.length; paintSlash(items); return; }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && items.length && !input.value.includes(' '))) {
      e.preventDefault(); const it = items[slashIndex];
      if (it) { input.value = `${it.dataset.cmd} `; autosize(); updateSlash(); }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); slashEl.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
  }
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); store.actions.scenarioInsertSend?.(); return; }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!store.stream) submit(); }
}
function autosize() {
  input.style.height = 'auto';
  const lh = parseFloat(getComputedStyle(input).lineHeight) || 20;
  input.style.height = `${Math.min(input.scrollHeight, lh * 8 + 12)}px`;
}
function updateSlash() {
  const v = input.value;
  if (!v.startsWith('/') || v.includes('\n')) { slashEl.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
  const q = trFold(v.split(' ')[0]);
  const items = SLASH.filter((s) => trFold(s.cmd).startsWith(q) || q === '/');
  if (!items.length || (v.includes(' ') && items.length === 1 && trFold(items[0].cmd) === q)) { slashEl.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
  slashIndex = Math.min(slashIndex, items.length - 1);
  replace(slashEl, items.map((s, i) => h('div', {
    class: ['slash-item', i === slashIndex ? 'is-active' : ''], role: 'option', id: `slash-${i}`, 'aria-selected': String(i === slashIndex), 'data-cmd': s.cmd,
    onpointerdown: (e) => { e.preventDefault(); input.value = `${s.cmd} `; autosize(); updateSlash(); input.focus(); },
  }, h('span', { class: 'slash-cmd' }, s.cmd), h('span', { class: 'slash-args' }, s.args), h('span', { class: 'slash-hint' }, t(s.hint)), s.tag ? h('span', { class: 'chip tone-warn chip-xs' }, t(s.tag)) : null)));
  slashEl.hidden = false;
  input.setAttribute('aria-expanded', 'true'); input.setAttribute('aria-controls', 'slash-menu'); input.setAttribute('aria-activedescendant', `slash-${slashIndex}`);
}
function paintSlash(items) {
  items.forEach((it, i) => { it.classList.toggle('is-active', i === slashIndex); it.setAttribute('aria-selected', String(i === slashIndex)); });
  input.setAttribute('aria-activedescendant', `slash-${slashIndex}`);
}
export function updateComposer() {
  if (!dock) return;
  const u = store.ui; const streaming = !!store.stream;
  replace(kindBtn, h('span', { class: 'kind-dot', 'data-kind': u.composerKind, 'aria-hidden': 'true' }), u.composerKind, icon('chevron-down', 12));
  kindBtn.setAttribute('aria-label', `${t('composer.kind')}: ${u.composerKind}`);
  replace(sendBtn, icon(streaming ? 'stop' : 'send', 14), h('span', null, streaming ? t('composer.stop') : t('composer.send')), streaming ? kbd('Esc') : null);
  sendBtn.classList.toggle('is-stop', streaming);
  sendBtn.setAttribute('aria-label', streaming ? t('composer.stopAria') : t('composer.sendAria'));
  const compact = window.matchMedia('(max-width: 640px)').matches;
  input.placeholder = compact ? t('composer.placeholderShort') : t('composer.placeholder');
  const noKey = chatKeyState() === 'none';
  replace(noKeyEl, noKey ? [icon('key', 14), h('span', null, t('composer.noKey')), btn(t('act.goSettings'), { size: 'sm', kind: 'ghost', onClick: () => store.actions.openSettings('chat') })] : []);
  noKeyEl.hidden = !noKey;
  row.hidden = noKey;
  replace(hintEl, h('span', null, kbd('Enter'), ` ${t('composer.hintSend')} · `, kbd('⇧Enter'), ` ${t('composer.hintNewline')} · `, kbd('/'), ` ${t('composer.hintCommands')}`));
}
export function composerInsert(text, { send = false, kind = null } = {}) {
  if (!dock) build();
  if (kind) store.ui.composerKind = kind;
  input.value = text; autosize(); updateSlash(); updateComposer();
  input.focus();
  if (send) submit();
}
export function focusComposer() { input?.focus(); }
async function submit() {
  const raw = input.value.trim();
  if (!raw || store.stream) return;
  if (chatKeyState() === 'none' && !raw.startsWith('/')) return;
  input.value = ''; autosize(); slashEl.hidden = true;
  if (raw.startsWith('/')) { await store.actions.runCommand(raw); return; }
  await store.actions.runTurn(raw, store.ui.composerKind);
}
