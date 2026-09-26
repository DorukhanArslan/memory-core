// views/editor.js: file tab. Raw view with line numbers (raw is what gets injected), safe
// preview, textarea edit, SaveConfirmSheet (server diff + budget impact from
// /api/lab/file/diff-preview), PUT with baseSha256 and the 409 ConflictBanner.
import { h, icon, replace, fmtN, fmtTime, copyText } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadFile, loadFiles, loadState } from '../store.js';
import { api } from '../api.js';
import { badge, btn, iconBtn, honesty, skeleton, failCard, chip } from '../ui/kit.js';
import { openDialog, confirmDialog, toast, openMenu } from '../ui/overlay.js';
import { markdown } from '../ui/markdown.js';
import { parseUnified, unifiedStats, diffView } from '../ui/diff.js';
import { fileEntry, isMemoryPath } from './explorer.js';

const MAX_LINES = 2000;
const conflicts = new Map(); // path -> {sha256, content} from a 409
const showAll = new Set();

function flagOn(name) { return store.data.settings?.flags?.[name]?.on; }
export function readOnlyReason(path, file) {
  if (file && file.writable === false) return file.readOnlyReason || t('editor.readOnly');
  if (flagOn('lab_file_editing') === false) return t('editor.editingOff');
  return null;
}

function codeView(path, content, { focus = null, changed = new Set() } = {}) {
  let lines = content.split('\n');
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();
  const total = lines.length;
  const cut = content.length > 200_000 && !showAll.has(path) && total > MAX_LINES;
  if (cut) lines = lines.slice(0, MAX_LINES);
  const isHb = /(^|\/)HEARTBEAT\.md$/.test(path);
  let inComment = false; let inTasks = false;
  const rows = lines.map((line, i) => {
    const n = i + 1; const tr = line.trim();
    let cls = '';
    if (inComment || tr.startsWith('<!--')) { cls = 'tk-comment'; inComment = !tr.includes('-->'); }
    else if (/^#{1,6}\s/.test(tr)) cls = 'tk-head';
    else if (isHb && tr === 'tasks:') { cls = 'tk-tasks'; inTasks = true; }
    else if (isHb && inTasks && (/^\s/.test(line) || tr.startsWith('- '))) cls = 'tk-tasks';
    else if (/^\s*[-*]\s/.test(line)) { cls = 'tk-bullet'; inTasks = false; }
    else if (/\[\.\.\.truncated|…\(truncated/.test(line)) cls = 'tk-warn';
    else inTasks = false;
    return h('div', { class: ['code-line', cls, focus && n >= focus[0] && n <= focus[1] ? 'is-focus' : '', changed.has(n) ? 'is-changed' : ''], 'data-line': String(n) },
      h('span', { class: 'ln', 'aria-hidden': 'true' }, String(n)), h('span', { class: 'lt' }, inlineTokens(line)));
  });
  const code = h('div', { class: 'code', role: 'textbox', 'aria-readonly': 'true', 'aria-multiline': 'true', 'aria-label': path, tabindex: '0', 'data-testid': 'code-view' },
    rows.length ? rows : h('div', { class: 'code-line' }, h('span', { class: 'ln' }, '1'), h('span', { class: 'lt muted' }, t('editor.emptyFile'))));
  if (cut) code.append(h('div', { class: 'code-more' }, h('span', { class: 'muted' }, t('editor.firstLines', { n: fmtN(MAX_LINES), total: fmtN(total) })), btn(t('editor.loadAll'), { size: 'xs', onClick: () => { showAll.add(path); refresh('center'); } })));
  return code;
}
function inlineTokens(line) {
  const frag = document.createDocumentFragment();
  const re = /(<!--.*?-->|`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0; let m;
  while ((m = re.exec(line))) {
    if (m.index > last) frag.append(line.slice(last, m.index));
    const v = m[0];
    frag.append(h('span', { class: v.startsWith('<!--') ? 'tk-comment' : v.startsWith('`') ? 'tk-code' : 'tk-strong' }, v));
    last = m.index + v.length;
  }
  if (last < line.length) frag.append(line.slice(last));
  if (!line) frag.append(' ');
  return frag;
}

export function renderEditor(body, path) {
  const d = store.data; const u = store.ui;
  const file = d.fileCache.get(path);
  if (!file) { replace(body, skeleton(8)); loadFile(path); return; }
  if (file.err) {
    replace(body, h('div', { class: 'editor-missing' }, failCard(file.err, { title: t('editor.readFailed', { p: path }), path, onRetry: () => loadFile(path, { force: true }) }), btn(t('editor.closeTabBtn'), { size: 'sm', kind: 'ghost', onClick: () => store.actions.closeTab(path) })));
    return;
  }
  const entry = fileEntry(path);
  const isBootstrap = entry?.kind === 'bootstrap';
  const cap = d.settings?.budgets?.maxChars ?? null;
  const editing = !!u.editing[path];
  const preview = !!u.preview[path];
  const ro = readOnlyReason(path, file);
  const draft = u.drafts[path];
  const content = file.content ?? '';
  const dirty = draft !== undefined && draft !== content;
  const conflict = conflicts.get(path) || (dirty && u.draftBase[path] && file.sha256 && u.draftBase[path] !== file.sha256 ? { sha256: file.sha256, content } : null);
  const shown = editing ? (draft ?? content) : content;
  const pct = cap ? Math.min(100, (shown.length / cap) * 100) : 0;
  const head = h('div', { class: 'editor-head', 'data-testid': 'file-editor' },
    h('div', { class: 'eh-path' }, icon('file-text', 14), h('h2', { class: 'eh-name' }, path),
      h('span', { class: 'eh-badges' }, (entry?.badges || []).slice(0, 3).map((b) => badge(b))),
      dirty ? h('span', { class: 'chip tone-accent chip-xs' }, t('editor.unsaved')) : null),
    h('div', { class: 'eh-meta' },
      isBootstrap && cap ? h('span', { class: ['size-meter', pct >= 100 ? 'is-over' : pct >= 85 ? 'is-near' : ''], 'data-tip': t('editor.capTip', { a: fmtN(shown.length), b: fmtN(cap) }) }, h('span', { class: 'sm-bar' }, h('span', { style: { '--p': `${pct}%` } })), h('span', { class: 'num' }, `${fmtN(shown.length)} / ${fmtN(cap)}`))
        : h('span', { class: 'muted num' }, `${fmtN(file.chars ?? content.length)} ${t('unit.chars')} · ${fmtN(file.bytes)} ${t('unit.bytes')}`),
      file.mtimeMs ? h('span', { class: 'muted' }, `${t('explorer.changedAt')} ${fmtTime(file.mtimeMs)}`) : null,
      h('span', { class: 'chip tone-ext chip-xs', 'data-tip': t('editor.extTagTip') }, icon('puzzle', 10), t('editor.extTag'))),
    h('div', { class: 'eh-actions' },
      editing ? null : btn(preview ? t('editor.raw') : t('editor.preview'), { size: 'sm', kind: 'ghost', ic: 'eye', onClick: () => { u.preview[path] = !preview; refresh('center'); } }),
      editing ? btn(t('act.cancel'), { size: 'sm', kind: 'ghost', onClick: () => cancelEdit(path) }) : btn(t('editor.edit'), { size: 'sm', ic: 'pencil', kbd: 'E', disabled: !!ro, title: ro, onClick: () => startEdit(path), testid: 'edit-btn' }),
      btn(t('act.save'), { size: 'sm', kind: 'primary', kbd: '⌘S', disabled: !dirty, onClick: () => openSaveConfirm(path), testid: 'save-btn' }),
      btn(t('act.viewDiff'), { size: 'sm', kind: 'ghost', ic: 'diff', onClick: () => { u.diffBase = 'session'; store.actions.openInspector('diff'); } }),
      iconBtn('more', t('explorer.fileMenu'), (e) => openMenu(e.currentTarget, [
        isBootstrap ? { label: t('editor.fixture', { n: fmtN((cap ?? 20000) + 5000) }), ic: 'copy', disabled: !!ro, onSelect: () => fixture(path, (cap ?? 20000) + 5000) } : null,
        isMemoryPath(path) ? { label: t('act.memoryGet'), ic: 'database', onSelect: () => store.actions.memoryGet(path) } : null,
        { label: t('act.copyPath'), ic: 'copy', onSelect: () => { const root = d.snap?.workspace?.root; copyText(root ? `${root}/${path}` : path).then(() => toast(t('toast.pathCopied'), { tone: 'ok' })); } },
      ], { align: 'end' }), { size: 'sm' })));
  const banners = [];
  if (conflict) banners.push(h('div', { class: 'conflict-banner', role: 'alert', 'data-testid': 'conflict-banner' }, icon('alert-triangle', 14),
    h('span', null, t('editor.conflict', { s: lastSourceFor(path) || '—' })),
    btn(t('act.viewDiff'), { size: 'xs', kind: 'ghost', onClick: () => openSaveConfirm(path, { compareDisk: true }) }),
    btn(t('editor.takeDisk'), { size: 'xs', kind: 'ghost', onClick: () => { conflicts.delete(path); delete u.drafts[path]; delete u.draftBase[path]; u.editing[path] = false; loadFile(path, { force: true }); } }),
    btn(t('editor.overwrite'), { size: 'xs', kind: 'danger', onClick: () => { u.draftBase[path] = conflict.sha256; conflicts.delete(path); openSaveConfirm(path); } })));
  if (ro) banners.push(honesty(ro, 'neutral', 'eye'));
  if (entry?.kind === 'memory_session') banners.push(honesty(t('editor.sessionRaw'), 'warn', 'alert-triangle'));
  if (path.startsWith('memory/') && entry?.kind !== 'hidden') banners.push(honesty(t('editor.memoryNote'), 'info', 'info'));
  if (/^(user|workspace)\//.test(path)) banners.push(honesty(t('editor.extFolderNote'), 'ext', 'puzzle'));
  let main;
  if (editing) {
    const ta = h('textarea', { class: 'editor-ta', spellcheck: 'false', 'aria-label': t('editor.editAria', { p: path }), 'data-testid': 'editor-textarea' });
    ta.value = draft ?? content;
    const gutter = h('div', { class: 'editor-gutter', 'aria-hidden': 'true' }, ta.value.split('\n').map((_, i) => h('span', null, String(i + 1))));
    ta.addEventListener('input', () => { u.drafts[path] = ta.value; syncHead(); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); const a = ta.selectionStart; const b = ta.selectionEnd; ta.value = `${ta.value.slice(0, a)}  ${ta.value.slice(b)}`; ta.selectionStart = ta.selectionEnd = a + 2; u.drafts[path] = ta.value; syncHead(); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelEdit(path); }
    });
    ta.addEventListener('scroll', () => { gutter.scrollTop = ta.scrollTop; });
    main = h('div', { class: 'editor-edit' }, gutter, ta);
    requestAnimationFrame(() => { if (!body.contains(document.activeElement)) ta.focus(); });
    const syncHead = () => {
      const dd = u.drafts[path]; const isDirty = dd !== undefined && dd !== content;
      const sb = body.querySelector('[data-testid="save-btn"]'); if (sb) sb.disabled = !isDirty;
      const num = body.querySelector('.size-meter .num'); if (num && cap) num.textContent = `${fmtN((dd ?? '').length)} / ${fmtN(cap)}`;
      const n = (dd ?? '').split('\n').length;
      if (gutter.childElementCount !== n) replace(gutter, Array.from({ length: n }, (_, i) => h('span', null, String(i + 1))));
    };
  } else if (preview) main = h('div', { class: 'editor-preview' }, markdown(content, { onCite: (p, a, b) => store.actions.openFile(p, a, b) }));
  else main = codeView(path, content, { focus: u.focusLine[path] || null, changed: d.changedLines.get(path) || new Set() });
  replace(body, store.actions.scenarioStrip?.() || null, head, ...banners, h('div', { class: 'editor-body' }, main));
  const fl = u.focusLine[path];
  if (fl && !editing) requestAnimationFrame(() => body.querySelector(`.code-line[data-line="${fl[0]}"]`)?.scrollIntoView({ block: 'center' }));
}
function lastSourceFor(path) {
  const evs = store.data.events;
  for (let i = evs.length - 1; i >= 0; i--) {
    const e = evs[i];
    if (e.data?.path === path && (e.type === 'file.changed' || e.type === 'file.saved')) return `${e.data.source || e.type} ${fmtTime(e.ts, { seconds: false })}`;
  }
  return null;
}

export function startEdit(path) {
  const u = store.ui; const file = store.data.fileCache.get(path);
  const ro = readOnlyReason(path, file);
  if (ro) { toast(ro, { tone: 'warn' }); return; }
  if (!file || file.err) return;
  u.editing[path] = true;
  if (u.drafts[path] === undefined) { u.drafts[path] = file.content ?? ''; u.draftBase[path] = file.sha256 || null; }
  refresh('center');
}
function cancelEdit(path) {
  const u = store.ui; const file = store.data.fileCache.get(path);
  const dirty = u.drafts[path] !== undefined && u.drafts[path] !== file?.content;
  const doIt = () => { u.editing[path] = false; delete u.drafts[path]; delete u.draftBase[path]; refresh('center'); };
  if (dirty) confirmDialog({ title: t('editor.discardTitle'), lines: [t('editor.discardLine', { p: path })], confirmLabel: t('editor.discard'), onConfirm: doIt });
  else doIt();
}
/** Fixture: repeat the file's own content until it reaches `minChars` (no invented text). */
export function fixture(path, minChars) {
  const u = store.ui; const file = store.data.fileCache.get(path);
  const base = file?.content ?? '';
  if (!base.trim()) { toast(t('editor.fixtureEmpty'), { tone: 'warn' }); return; }
  let out = `${base.trimEnd()}\n\n${base.trimEnd()}`;
  while (out.length < minChars) out = `${out}\n\n${base.trimEnd()}`;
  u.drafts[path] = `${out}\n`; u.draftBase[path] = file.sha256 || null; u.editing[path] = false;
  openSaveConfirm(path, { fixture: true });
}
/** Prepares a draft from a scenario step (content or from→to replacement); saving stays Doruk's click. */
export async function applyEdit(path, { content = null, from = null, to = null, append = null } = {}) {
  const u = store.ui;
  const file = await loadFile(path, { force: true });
  if (!file || file.err) { toast(t('editor.readFailed', { p: path }), { tone: 'danger' }); return; }
  const base = file.content ?? '';
  let next = content;
  if (next === null && append !== null) next = `${base.trimEnd()}\n\n${append.trimEnd()}\n`;
  if (next === null && from !== null) {
    if (!base.includes(from)) { toast(t('editor.fromMissing', { s: from }), { tone: 'warn' }); store.actions.openFile(path); return; }
    next = base.replace(from, to);
  }
  if (next === null) return;
  u.drafts[path] = next; u.draftBase[path] = file.sha256 || null;
  store.actions.openFile(path);
  openSaveConfirm(path);
}

export async function openSaveConfirm(path, { fixture: isFixture = false, compareDisk = false } = {}) {
  const d = store.data; const u = store.ui;
  const file = d.fileCache.get(path);
  const content = u.drafts[path] ?? file?.content ?? '';
  const summary = h('div', { class: 'save-summary' }, h('span', { class: 'spinner' }), t('editor.previewing'));
  const diffBox = h('div', { class: 'save-diff' });
  const saveBtn = btn(t('act.save'), { kind: 'primary', kbd: '↵', onClick: () => doSave(), testid: 'save-confirm-ok', disabled: true });
  const body = h('div', { class: 'save-body' }, summary, compareDisk ? honesty(t('editor.compareDisk'), 'warn') : null, diffBox,
    h('div', { class: 'save-foot muted' }, t('editor.saveFoot')));
  const dlg = openDialog({ title: t('editor.saveTitle', { p: path }), body, cls: 'dialog-lg', testid: 'save-confirm', actions: [btn(t('act.cancel'), { kind: 'ghost', onClick: () => dlg.close() }), saveBtn] });
  dlg.panel.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && e.target.tagName !== 'TEXTAREA' && !saveBtn.disabled) { e.preventDefault(); doSave(); } });
  let pv;
  try {
    pv = await api.post('/api/lab/file/diff-preview', { path, content });
  } catch (err) {
    replace(summary, failCard(err, { title: t('editor.previewFailed') }));
    if (err.missing) return;
    saveBtn.disabled = false; // the diff preview failed, the save itself may still work
    return;
  }
  const st = unifiedStats(pv.diff);
  const b = pv.budget;
  const impact = b ? (b.wouldTruncate
    ? t('editor.impactTruncate', { p: path, a: fmtN(pv.charsBefore), b: fmtN(pv.charsAfter), c: fmtN(b.maxChars), d: fmtN(b.injectedAfter) })
    : t('editor.impactOk', { p: path, a: fmtN(pv.charsBefore), b: fmtN(pv.charsAfter), c: fmtN(b.maxChars) }))
    : t('editor.impactNone', { p: path, a: fmtN(pv.charsBefore), b: fmtN(pv.charsAfter) });
  replace(summary,
    isFixture ? chip({ label: t('editor.fixtureTag'), tone: 'warn', ic: 'copy' }) : null,
    chip({ label: `+${st.added}`, tone: 'ok' }), chip({ label: `−${st.removed}`, tone: 'danger' }),
    h('span', { class: ['impact', b?.wouldTruncate ? 'tone-text-warn' : ''] }, impact));
  replace(diffBox, diffView(parseUnified(pv.diff), { maxLines: 300 }));
  saveBtn.disabled = false;

  async function doSave() {
    saveBtn.disabled = true;
    try {
      const res = await api.put('/api/lab/file', { path, content, baseSha256: u.draftBase[path] ?? file?.sha256 ?? null });
      delete u.drafts[path]; delete u.draftBase[path]; u.editing[path] = false; conflicts.delete(path);
      dlg.close();
      await loadFile(path, { force: true });
      loadFiles(); loadState();
      window.dispatchEvent(new CustomEvent('lab:saved', { detail: path }));
      const deleted = (res?.events || []).some((e) => e.type === 'bootstrap.file_deleted');
      toast(deleted ? t('toast.savedBootstrapDone') : t('toast.saved', { p: path }), { tone: deleted ? 'ok' : 'info', action: { label: t('inspector.timeline'), onClick: () => store.actions.openInspector('timeline') } });
    } catch (err) {
      if (err.status === 409 && err.body?.current) {
        conflicts.set(path, err.body.current);
        dlg.close();
        toast(t('editor.conflictToast'), { tone: 'warn' });
        refresh('center');
        return;
      }
      saveBtn.disabled = false;
      replace(summary, failCard(err, { title: t('editor.saveFailed') }));
    }
  }
}
export function saveActive() {
  const p = store.ui.centerTab;
  if (p === 'view') return false;
  const u = store.ui; const file = store.data.fileCache.get(p);
  if (u.drafts[p] !== undefined && u.drafts[p] !== file?.content) { openSaveConfirm(p); return true; }
  toast(t('toast.nothingToSave'), { tone: 'info' });
  return true;
}
