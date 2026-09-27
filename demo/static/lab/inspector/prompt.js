// inspector/prompt.js: Prompt tab. "Bu tur" renders the PromptView stored with the turn
// (GET /api/lab/turns/{id}); "Önizleme" asks /api/lab/prompt/preview for the current disk state.
import { h, icon, fmtN, fmtK, fmtTime } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadTurn, loadFiles } from '../store.js';
import { api } from '../api.js';
import { badge, segmented, toggle, jsonDisclosure, honesty, skeleton, failCard, chip } from '../ui/kit.js';
import { openMenu } from '../ui/overlay.js';
import { lineDiff, diffStats, hunks, diffView } from '../ui/diff.js';
import { section, promptPre, notice, kvRow, selectEl, splitFileSections, truncationMarker } from './common.js';
import { toolCard } from '../views/chat.js';
import { SESSION_KINDS } from '../views/composer.js';

const EXTRA_KINDS = ['channel', 'direct'];
const RELEVANT = /^(file\.|bootstrap\.|settings\.changed|curation\.|flush\.written|session_memory\.|workspace\.reset)/;
const previews = new Map();

function relevantVersion() {
  const evs = store.data.events;
  for (let i = evs.length - 1; i >= 0; i--) if (RELEVANT.test(evs[i].type)) return evs[i].id ?? i;
  return 0;
}
/** Cached PromptView preview for the current disk state; re-fetched after any file or settings event. */
export function previewFor(kind, opts = {}) {
  const body = { sessionKind: kind, ...opts };
  if (store.data.settings?.layout && !body.layout) body.layout = store.data.settings.layout;
  const key = JSON.stringify(body);
  const version = relevantVersion();
  const hit = previews.get(key);
  if (hit && hit.version === version) return hit;
  const entry = { version, loading: true, pv: hit?.pv || null, err: null };
  previews.set(key, entry);
  entry.promise = api.post('/api/lab/prompt/preview', body)
    .then((pv) => { entry.pv = pv; entry.err = null; })
    .catch((err) => { entry.err = err; entry.pv = null; })
    .finally(() => { entry.loading = false; refresh('inspector'); });
  return entry;
}
export async function fetchPreview(kind, opts = {}) {
  const e = previewFor(kind, opts);
  await e.promise;
  const again = previewFor(kind, opts);
  if (again.promise && again !== e) await again.promise;
  return again.pv ? again : e;
}

function fileFold(f, text, { changed = null, prevText = null } = {}) {
  const u = store.ui; const key = f.path;
  const open = u.openFolds.has(key) || !!changed;
  const marker = f.truncated ? truncationMarker(text) : null;
  return h('div', { class: ['fold', open ? 'is-open' : '', f.truncated ? 'is-truncated' : '', changed ? 'is-changed' : ''], 'data-testid': 'prompt-fold' },
    h('button', { type: 'button', class: 'fold-head', 'aria-expanded': String(open), onclick: () => { if (u.openFolds.has(key)) u.openFolds.delete(key); else u.openFolds.add(key); refresh('inspector'); } },
      icon(open ? 'chevron-down' : 'chevron-right', 12), h('span', { class: 'fold-name mono' }, `## …/${f.name}`),
      f.missing ? badge('missing') : null, f.truncated ? badge('truncated') : null,
      changed ? h('span', { class: 'chip chip-xs tone-accent' }, `${t('prompt.changed')} +${changed.added} −${changed.removed}`) : null,
      h('span', { class: 'fold-count num' }, fmtN(f.chars))),
    open ? h('div', { class: 'fold-body' },
      marker ? h('div', { class: 'fold-tools' }, h('span', { class: 'muted' }, t('prompt.headTail', { h: fmtN(marker.head), t: fmtN(marker.tail), n: fmtN(marker.raw) })),
        h('button', { type: 'button', class: 'link', onclick: () => store.actions.openFile(f.name) }, t('prompt.openFile'))) : null,
      changed && prevText !== null ? diffView(hunks(lineDiff(prevText, text), 2)) : promptPre(text)) : null);
}
function budgetBody(pv) {
  const total = pv.budget?.totalMaxChars ?? store.data.settings?.budgets?.totalMaxChars ?? null;
  const cap = pv.budget?.maxChars ?? store.data.settings?.budgets?.maxChars ?? null;
  const files = pv.files || [];
  const sum = files.reduce((a, f) => a + (f.chars || 0), 0);
  if (!total) return h('div', { class: 'muted' }, t('prompt.noBudget'));
  const bar = h('div', { class: 'budget-bar', role: 'img', 'aria-label': t('explorer.budgetAria', { a: fmtN(sum), b: fmtN(total) }) },
    files.map((f, i) => h('span', {
      class: ['budget-seg', f.truncated ? 'is-truncated' : ''], style: { '--w': `${(f.chars / total) * 100}%`, '--c': `var(--seg-${(i % 8) + 1})` }, 'data-tip': `${f.name} · ${fmtN(f.chars)}`,
      onmouseenter: () => document.querySelector(`.tree-row[data-path="${CSS.escape(f.name)}"]`)?.classList.add('is-hover-link'),
      onmouseleave: () => document.querySelector(`.tree-row[data-path="${CSS.escape(f.name)}"]`)?.classList.remove('is-hover-link'),
    })),
    cap ? h('span', { class: 'budget-cap', style: { '--x': `${Math.min(100, (cap / total) * 100)}%` }, 'data-tip': t('prompt.capLine', { c: fmtN(cap) }) }) : null);
  const rows = files.map((f, i) => h('div', { class: 'brow' },
    h('span', { class: 'bswatch', style: { '--c': `var(--seg-${(i % 8) + 1})` } }), h('span', { class: 'mono bname' }, f.name),
    h('span', { class: 'bmeter' }, h('span', { class: f.truncated ? 'is-truncated' : '', style: { '--p': `${cap ? Math.min(100, (f.chars / cap) * 100) : 0}%` } })),
    h('span', { class: 'num bval' }, fmtN(f.chars)), f.truncated && f.raw ? h('span', { class: 'num muted bval' }, `/ ${fmtN(f.raw)}`) : h('span', { class: 'bval' })));
  const upstream = pv.budget?.upstreamDefaults || null;
  const isTest = upstream ? (upstream.maxChars !== cap || upstream.totalMaxChars !== total) : null;
  return h('div', { class: 'stack' }, bar,
    h('div', { class: 'budget-legend muted' }, h('span', null, '0'), cap ? h('span', null, `${t('prompt.fileCap')} ${fmtK(cap)}`) : null, h('span', null, `${t('prompt.total')} ${fmtK(total)}`)),
    h('div', { class: 'brows' }, rows),
    isTest === null ? null : isTest ? chip({ label: t('settings.testValue'), tone: 'warn', cls: 'chip-xs' }) : chip({ label: t('settings.upstreamDefault', { a: fmtN(upstream.maxChars), b: fmtN(upstream.totalMaxChars) }), tone: 'neutral', cls: 'chip-xs' }));
}

export function promptTab(turn, { ctx = 'turn' } = {}) {
  const u = store.ui; const d = store.data;
  const wrap = h('div', { class: 'prompt-tab' });
  const canTurn = ctx === 'turn' && turn && typeof turn.id === 'number';
  const fixedKind = ctx === 'heartbeat' ? 'heartbeat' : null;
  const mode = canTurn ? u.promptMode : 'preview';
  let pv = null; let loading = false; let err = null; let detail = null;
  if (mode === 'turn') {
    detail = d.details.get(turn.id);
    err = d.detailErr.get(turn.id) || null;
    pv = detail?.prompt || null;
    loading = !detail && !err;
  } else {
    const opts = {};
    if (u.promptOpts.contextInjection) opts.contextInjection = u.promptOpts.contextInjection;
    if (fixedKind === 'heartbeat' || u.promptKind === 'heartbeat') { if (u.promptOpts.lightContext) opts.contextMode = 'lightweight'; }
    const entry = previewFor(fixedKind || u.promptKind, opts);
    pv = entry.pv; err = entry.err; loading = entry.loading && !pv;
  }
  const kind = fixedKind || (mode === 'turn' ? (pv?.sessionKind || turn?.sessionKind || 'main') : u.promptKind);
  const narrow = window.matchMedia('(max-width: 820px)').matches;
  const kindControl = narrow
    ? h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, t('composer.kind')), selectEl([...SESSION_KINDS, ...EXTRA_KINDS], kind, (v) => setKind(v), { aria: t('composer.kind') }))
    : h('div', { class: 'inline-group' },
      segmented({ options: SESSION_KINDS.map((k) => ({ value: k, label: k })), value: SESSION_KINDS.includes(kind) ? kind : null, onChange: (v) => setKind(v), aria: t('composer.kind'), size: 'sm', testid: 'session-kind' }),
      h('button', { type: 'button', class: ['icon-btn', 'icon-btn-sm', EXTRA_KINDS.includes(kind) ? 'is-on' : ''], 'aria-label': t('prompt.moreKinds'), 'data-tip': t('prompt.moreKinds'), onclick: (e) => openMenu(e.currentTarget, EXTRA_KINDS.map((k) => ({ label: k, checked: kind === k, onSelect: () => setKind(k) }))) }, icon('more', 16)));
  wrap.append(h('div', { class: 'controls' },
    h('div', { class: 'controls-row' }, fixedKind ? h('span', { class: 'kind-tag', 'data-kind': fixedKind }, fixedKind) : kindControl,
      segmented({ options: [{ value: 'turn', label: t('prompt.thisTurn'), disabled: !canTurn }, { value: 'preview', label: t('prompt.preview') }], value: mode, onChange: (v) => { u.promptMode = v; if (v === 'turn' && turn) u.promptKind = turn.sessionKind || 'main'; refresh('inspector'); }, aria: t('prompt.mode'), size: 'sm', testid: 'prompt-mode' })),
    h('div', { class: 'controls-row' },
      mode === 'turn' ? toggle({ checked: u.compare, onChange: (v) => { u.compare = v; refresh('inspector'); }, label: t('prompt.compare'), testid: 'compare-toggle' }) : null,
      mode === 'preview' ? h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, 'contextInjection'), selectEl([{ value: '', label: t('prompt.fromSettings') }, 'always', 'continuation-skip', 'never'], u.promptOpts.contextInjection || '', (v) => { u.promptOpts.contextInjection = v || null; refresh('inspector'); }, { aria: 'contextInjection' })) : null,
      mode === 'preview' && kind === 'heartbeat' ? toggle({ checked: u.promptOpts.lightContext, onChange: (v) => { u.promptOpts.lightContext = v; refresh('inspector'); }, label: 'lightContext' }) : null)));
  if (mode === 'preview') wrap.append(honesty(t('prompt.previewNote'), 'info', 'eye'));
  if (loading) { wrap.append(skeleton(4)); return wrap; }
  if (err) { wrap.append(failCard(err, { title: t('prompt.loadFailed'), onRetry: () => (mode === 'turn' ? loadTurn(turn.id, { force: true }) : refresh('inspector')) })); return wrap; }
  if (!pv) { wrap.append(h('div', { class: 'muted pad' }, t('prompt.none'))); return wrap; }

  // compare with the previous turn's stored prompt
  let changedMap = {}; let prevTurn = null;
  // v2026.9.6 renders every file in Project Context, above the cache boundary (no dynamic block).
  const stableSplit = splitFileSections(pv.stableText, pv.files || []);
  if (mode === 'turn' && u.compare) {
    const list = d.turns.filter((x) => typeof x.id === 'number' && !x.failedStage);
    const i = list.findIndex((x) => x.id === turn.id);
    prevTurn = i > 0 ? list[i - 1] : null;
    if (prevTurn) {
      const prev = d.details.get(prevTurn.id);
      if (!prev) loadTurn(prevTurn.id);
      else if (prev.prompt) {
        const prevSplit = splitFileSections(prev.prompt.stableText, prev.prompt.files || []);
        const prevBy = new Map(prevSplit.files.map((x) => [x.file.name, x.text]));
        for (const x of stableSplit.files) {
          const before = prevBy.get(x.file.name);
          if (before === undefined) changedMap[x.file.name] = { ...diffStats(lineDiff('', x.text)), prev: '' };
          else if (before !== x.text) changedMap[x.file.name] = { ...diffStats(lineDiff(before, x.text)), prev: before };
        }
        for (const name of prevBy.keys()) if (!stableSplit.files.some((x) => x.file.name === name)) changedMap[name] = { added: 0, removed: 1, prev: prevBy.get(name), gone: true };
      }
    }
  }
  const trunc = (pv.files || []).filter((f) => f.truncated).length;
  const totalChars = (pv.files || []).reduce((a, f) => a + (f.chars || 0), 0);
  wrap.append(h('div', { class: 'psummary' },
    h('span', null, h('b', { class: 'num' }, fmtN(totalChars)), ` ${t('unit.chars')}`), h('span', null, `${(pv.files || []).length} ${t('unit.files')}`),
    trunc ? h('span', { class: 'tone-text-warn' }, `${trunc} ${t('badge.truncated')}`) : null,
    h('span', { class: 'muted', 'data-tip': pv.bootstrapModeReason || null }, `${t('prompt.bootstrapMode')}: ${pv.bootstrapMode || '—'}${pv.bootstrapModeReason ? ` · ${pv.bootstrapModeReason}` : ''}`),
    pv.runKind ? h('span', { class: 'muted' }, `${t('prompt.runKind')}: ${pv.runKind}`) : null,
    mode === 'turn' ? h('span', { class: 'muted' }, fmtTime(turn.startedAt, { seconds: false })) : null));
  if (mode === 'turn' && u.compare) {
    const names = Object.keys(changedMap);
    wrap.append(h('div', { class: 'compare-note', 'data-testid': 'compare-note' }, icon('diff', 12),
      !prevTurn ? t('prompt.noPrevTurn') : !d.details.get(prevTurn.id) ? t('prompt.loadingPrev') : names.length ? t('prompt.compareChanged', { a: prevTurn.id, b: turn.id, n: names.join(', ') }) : t('prompt.compareSame', { a: prevTurn.id, b: turn.id })));
  }
  // 1. Bildirimler
  const notices = [];
  if (pv.bootstrapText) notices.push(notice('bootstrap', pv.bootstrapText, { tone: pv.bootstrapStatus === 'pending' ? 'accent' : 'info', title: t('prompt.bootstrapNotice'), ic: 'clock' }));
  for (const n of pv.workspaceNotes || []) notices.push(notice('workspace', n, { tone: 'info', title: t('prompt.workspaceNote') }));
  for (const f of pv.migrationFindings || []) notices.push(notice('migration', `${f.message}\n${f.fixHint}`, { tone: f.severity === 'error' ? 'danger' : 'warn', title: t('prompt.migrationFinding'), ic: 'alert-triangle', note: f.requirement }));
  if ((pv.truncationWarningLines || []).length) notices.push(notice('warning', pv.truncationWarningLines.join('\n'), { tone: 'warn', title: t('prompt.truncWarning'), ic: 'alert-triangle', note: t('prompt.runtimeWarning') }));
  if (pv.truncationWarning && pv.truncationWarning.shown === false && (pv.files || []).some((f) => f.truncated)) notices.push(honesty(t('prompt.warnOnceShown'), 'neutral', 'info'));
  if (pv.injectionSkipped) notices.push(notice('injection', `injection_skipped: contextInjection=${pv.contextInjection || '—'}`, { tone: 'neutral', title: 'contextInjection' }));
  for (const w of pv.warnings || []) notices.push(notice('filter', w, { tone: 'neutral', title: t('prompt.filterWarning') }));
  wrap.append(section('notices', t('prompt.notices'), { count: notices.length, empty: !notices.length, body: () => h('div', { class: 'stack' }, notices.length ? notices : h('div', { class: 'muted' }, t('prompt.noNotices'))) }));
  // 2. Bütçe
  const total = pv.budget?.totalMaxChars ?? d.settings?.budgets?.totalMaxChars;
  wrap.append(section('budget', t('prompt.budget'), { count: total ? `${fmtN(totalChars)} / ${fmtN(total)}` : fmtN(totalChars), body: () => budgetBody(pv) }));
  // 3. Çalışma alanı dosyaları
  wrap.append(section('wsfiles', t('prompt.wsFiles'), { count: (pv.workspaceFilesText || '').length, copy: pv.workspaceFilesText || '', empty: !pv.workspaceFilesText, body: () => promptPre(pv.workspaceFilesText || '—') }));
  // 4. Kararlı kısım
  wrap.append(section('stable', t('prompt.stable'), { count: (pv.stableText || '').length, copy: pv.stableText || '', empty: !pv.stableText, testid: 'prompt-section-stable',
    body: () => h('div', { class: 'stack-tight' }, stableSplit.head ? promptPre(stableSplit.head) : null, stableSplit.files.map((x) => fileFold(x.file, x.text, { changed: changedMap[x.file.name], prevText: changedMap[x.file.name]?.prev ?? null }))) }));
  // 5. Önbellek sınırı
  wrap.append(h('div', { class: 'cache-boundary', role: 'separator', 'aria-label': t('prompt.cacheBoundary'), 'data-testid': 'cache-boundary' },
    h('span', { class: 'cb-line' }), h('span', { class: 'cb-label' }, icon('layers', 12), t('prompt.cacheBoundary')), h('span', { class: 'cb-line' }),
    h('span', { class: 'chip chip-xs tone-neutral cb-chip', 'data-tip': t('prompt.visualOnlyTip') }, t('prompt.visualOnly'))));
  // 6. Hariç tutulanlar
  const excl = pv.excluded || [];
  wrap.append(section('excluded', t('prompt.excluded'), { count: excl.length, empty: !excl.length, testid: 'prompt-section-excluded',
    body: () => (excl.length ? h('ul', { class: 'kv-list' }, excl.map((e) => h('li', null, h('span', { class: 'mono' }, e.name), badge(/empty|boş/.test(e.reason || '') ? 'empty' : 'excluded'), h('span', { class: 'muted' }, e.reason)))) : h('div', { class: 'muted' }, t('prompt.noExcluded'))) }));
  if (kind === 'group') wrap.append(honesty(t('prompt.groupNote'), 'info', 'info'));
  // 7b. Heartbeat user turn (v2026.9.6: the monitor scratch and due jobs, no system section)
  if (pv.heartbeatPrompt) {
    const hp = pv.heartbeatPrompt;
    wrap.append(section('hb-prompt', t('hb.nextPrompt'), { count: hp.skipReason ? hp.skipReason : (hp.message || '').length, copy: hp.message || '', empty: !hp.message && !hp.skipReason, testid: 'prompt-section-heartbeat',
      body: () => (hp.message ? promptPre(hp.message) : h('div', { class: 'muted' }, `${t('hb.skipped')}: ${hp.skipReason} · ${t('hb.noModelCall')}`)) }));
  }
  // 8. Hatırlama
  if (pv.recall) wrap.append(section('recall', t('prompt.recall'), { count: (pv.recall.lines || []).length, tags: [{ text: 'demo-only', tone: 'warn' }],
    body: () => h('div', { class: 'stack-tight' }, (pv.recall.memoryRecallSection || []).length ? promptPre(pv.recall.memoryRecallSection.join('\n')) : h('div', { class: 'muted' }, t('prompt.noRecallSection')), (pv.recall.lines || []).length ? promptPre(pv.recall.lines.join('\n')) : h('div', { class: 'muted' }, t('prompt.noRecallLines'))) }));
  // 8b. Araçlar (tool loop)
  if (mode === 'turn') {
    const tools = detail?.toolCalls || [];
    const offered = pv.tools || detail?.toolsOffered || null;
    wrap.append(section('tools', t('prompt.tools'), { count: tools.length, empty: !tools.length && !offered,
      body: () => h('div', { class: 'stack-tight' },
        offered ? h('div', { class: 'chip-wrap' }, h('span', { class: 'muted small' }, t('prompt.toolsOffered')), offered.map((x) => chip({ label: typeof x === 'string' ? x : x.name, tone: 'neutral', cls: 'chip-mono chip-xs' }))) : h('div', { class: 'muted small' }, t('prompt.toolsUnknown')),
        tools.length ? tools.map((tc) => toolCard({ ...tc, status: tc.ok === false ? 'error' : 'ok' })) : h('div', { class: 'muted' }, t('prompt.noToolCalls'))) }));
  }
  // 9. Başlangıç bağlamı
  if (mode === 'turn') wrap.append(section('startup', t('prompt.startup'), { count: pv.startup ? (pv.startup.text || '').length : 0, empty: !pv.startup,
    body: () => (pv.startup ? h('div', { class: 'stack-tight' }, h('div', { class: 'muted' }, t('prompt.startupFiles', { f: (pv.startup.files || []).join(', ') || '—' })), promptPre(pv.startup.text)) : h('div', { class: 'muted' }, t('prompt.startupOnlyReset'))) }));
  // 10. Flush
  if (mode === 'turn') {
    const fl = detail?.flush;
    wrap.append(section('flush', 'Flush', { count: fl?.decision?.reason || '—', empty: !fl,
      body: () => {
        if (!fl) return h('div', { class: 'muted' }, t('prompt.noFlush'));
        const dd = fl.decision || {};
        // The decision (explain_memory_flush_trigger) and what happened to the flush turn are separate:
        // a scripted engine decides "run" but skips the turn (stage flush: skip).
        const st = (detail?.stages || []).find((x) => x.name === 'flush');
        const outcome = fl.run ? `${t('flush.ran')} · ${fl.run.error ? t('flush.failed') : fl.run.wrote ? t('flush.wrote') : t('flush.noWrite')}`
          : st?.status === 'skip' ? `${t('flush.skipped')} (${st.detail || '—'})` : '—';
        const b = h('div', { class: 'stack-tight' }, h('div', { class: 'kv' },
          kvRow(t('flush.decision'), dd.shouldRun ? t('flush.decideRun') : t('flush.decideSkip')), kvRow(t('flush.reason'), h('span', { class: 'mono' }, dd.reason || '—')),
          kvRow(t('flush.outcome'), h('span', { 'data-testid': 'prompt-flush-outcome' }, outcome)),
          dd.threshold !== undefined ? kvRow('token', `${fmtN(dd.totalTokens)} / ${fmtN(dd.threshold)}`) : null,
          dd.reserveTokensFloor !== undefined ? kvRow(t('flush.formula'), h('span', { class: 'mono' }, `${fmtN(dd.contextWindowTokens)} − ${fmtN(dd.reserveTokensFloor)} − ${fmtN(dd.softThresholdTokens)} = ${fmtN(dd.threshold)}`)) : null,
          dd.memoryFlush ? kvRow(t('flush.state'), h('span', { class: 'mono' }, [dd.memoryFlush.kind, dd.memoryFlush.compactionCount !== undefined ? `compactionCount ${dd.memoryFlush.compactionCount}` : null, dd.memoryFlush.failureCount ? `failureCount ${dd.memoryFlush.failureCount}` : null].filter(Boolean).join(' · '))) : null,
          dd.tokenSource ? kvRow(t('flush.tokenSource'), h('span', { class: 'mono' }, dd.tokenSource)) : null,
          dd.timeFormat ? kvRow(t('flush.timeFormat'), h('span', null, h('span', { class: 'mono' }, `${dd.timeFormat}h`), ' ', h('span', { class: 'muted small' }, t('flush.timeFormatNote')))) : null,
          kvRow(t('flush.order'), t('flush.beforeTurn'))));
        if (pv.flush) b.append(kvRow(t('flush.target'), h('span', { class: 'mono' }, pv.flush.target)), h('div', { class: 'muted small' }, 'prompt'), promptPre(pv.flush.prompt));
        if (fl.run) b.append(jsonDisclosure(fl.run, { title: 'flush run' }));
        return b;
      } }));
    // 11. Konuşma penceresi
    const tr = pv.transcript;
    wrap.append(section('transcript', t('prompt.transcript'), { count: tr ? `${tr.sent} / ${tr.omitted}` : '—', tags: [{ text: 'demo-only', tone: 'warn' }], empty: !tr,
      body: () => (tr ? h('div', { class: 'muted' }, tr.sent === 0 ? t('prompt.transcriptNone') : t('prompt.transcriptLine', { a: tr.sent, b: tr.omitted })) : h('div', { class: 'muted' }, '—')) }));
    // 12. Ham istek
    wrap.append(section('raw', t('prompt.raw'), { count: pv.messages ? 'JSON' : '—', empty: !pv.messages, body: () => (pv.messages ? jsonDisclosure(pv.messages, { title: 'messages' }) : h('div', { class: 'muted' }, '—')) }));
  }
  wrap.append(h('div', { class: 'insp-foot muted' }, icon('info', 12), t('prompt.honestyFoot')));
  return wrap;
}
function setKind(v) {
  const u = store.ui; u.promptKind = v; u.promptMode = 'preview';
  loadFiles();
  refresh('inspector', 'explorer');
}
