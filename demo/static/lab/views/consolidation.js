// views/consolidation.js: curated writes (extension) beside scored promotion. Gates, weights,
// candidates and evidence labels all come from GET /api/lab/consolidation; the sweeps call the
// kept endpoints (/api/memory/promote, /api/dreaming/run, /api/memory/audit, /api/memory/repair).
import { h, icon, replace, fmtN, fmtTime, fmtScore } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, refresh, loadConsolidation, loadFiles, providerBody } from '../store.js';
import { api } from '../api.js';
import { chip, btn, segmented, emptyState, failCard, skeleton, jsonDisclosure } from '../ui/kit.js';
import { toast, confirmDialog } from '../ui/overlay.js';
import { parseUnified, diffView } from '../ui/diff.js';
import { viewHead } from './heartbeat.js';

const COMP_ORDER = ['frequency', 'relevance', 'diversity', 'recency', 'consolidation', 'conceptual', 'phaseBoost'];
const compLabel = (k) => (has(`cons.comp.${k}`) ? t(`cons.comp.${k}`) : k);
const busy = new Set();

async function act(name, fn) {
  if (busy.has(name)) return;
  busy.add(name); refresh('center');
  try {
    const res = await fn();
    store.data.consResults = [{ name, ts: Date.now(), res }, ...(store.data.consResults || [])].slice(0, 6);
  } catch (err) {
    store.data.consResults = [{ name, ts: Date.now(), err }, ...(store.data.consResults || [])].slice(0, 6);
  }
  busy.delete(name);
  await loadConsolidation(); loadFiles();
  refresh('center', 'inspector');
}
const promote = () => act('promote', () => api.post('/api/memory/promote', { ...providerBody() }));
const dream = (phase) => act(`dream:${phase}`, () => api.post('/api/dreaming/run', { phase, ...providerBody() }));
const audit = () => act('audit', () => api.get('/api/memory/audit'));
const repair = () => act('repair', () => api.post('/api/memory/repair', {}));
function revertCurated(w) {
  confirmDialog({ title: t('cons.revertTitle'), lines: [t('cons.revertLine', { p: w.path })], confirmLabel: t('act.revert'), danger: false, onConfirm: async () => {
    try { await api.post('/api/lab/curation/revert', { writeId: w.id }); toast(t('toast.reverted', { p: w.path }), { tone: 'ok' }); }
    catch (err) { toast(err.status === 409 ? t('cons.revertConflict', { p: w.path }) : err.missing ? t('state.waitsFor', { m: err.module || err.path }) : err.message, { tone: 'warn' }); }
    loadConsolidation(); loadFiles();
  } });
}

function componentBar(c, weights, minScore) {
  const keys = COMP_ORDER.filter((k) => c.components?.[k] !== undefined);
  const part = (k) => (k === 'phaseBoost' ? c.components[k] : (weights?.[k] ?? 0) * c.components[k]);
  return h('span', { class: 'comp-bar', role: 'img', 'aria-label': keys.map((k) => `${compLabel(k)} ${fmtScore(part(k), 3)}`).join(', '), 'data-testid': 'component-bar' },
    keys.map((k, i) => h('span', { class: 'comp-seg', style: { '--w': `${Math.max(0, part(k)) * 100}%`, '--c': `var(--seg-${i + 1})` }, 'data-tip': k === 'phaseBoost' ? `${compLabel(k)} + ${fmtScore(c.components[k], 3)}` : `${compLabel(k)} · ${fmtScore(c.components[k], 2)} × ${fmtScore(weights?.[k], 2)} = ${fmtScore(part(k), 3)}` })),
    minScore !== undefined ? h('span', { class: 'comp-gate', style: { '--x': `${Math.min(100, minScore * 100)}%` } }) : null);
}
function stat(k, v, ok = null) { return h('span', { class: ['stat', ok === true ? 'is-ok' : ok === false ? 'is-bad' : ''] }, h('span', { class: 'muted' }, k), h('b', { class: 'num' }, String(v ?? '—'))); }

function resultCard(r) {
  const title = t(`cons.result.${r.name.split(':')[0]}`) + (r.name.includes(':') ? `: ${r.name.split(':')[1]}` : '');
  if (r.err) return h('article', { class: 'rcard' }, h('div', { class: 'rcard-head' }, icon('alert-octagon', 14), h('b', null, title), h('span', { class: 'muted num' }, fmtTime(r.ts))), failCard(r.err, { compact: true }));
  const res = r.res || {};
  const sweep = res.promotionSweep || res.promotion || res.dreamingSweep || res;
  const diff = sweep?.diff || sweep?.promotion?.diff || null;
  const changed = !!(diff || (sweep?.filesChanged || []).length);
  return h('article', { class: 'rcard', 'data-testid': 'cons-result' },
    h('div', { class: 'rcard-head' }, icon('merge', 14), h('b', null, title), h('span', { class: 'muted num' }, fmtTime(r.ts)), h('span', { class: 'spacer' }),
      changed ? chip({ label: t('cons.memoryChanged'), tone: 'accent', cls: 'chip-xs' }) : chip({ label: t('cons.noFileChange'), tone: 'neutral', cls: 'chip-xs' })),
    diff ? diffView(parseUnified(diff), { maxLines: 60 }) : null,
    jsonDisclosure(res, { title: r.name }));
}

export function renderConsolidation(body) {
  const d = store.data; const u = store.ui;
  const c = d.consolidation;
  if (!c && !d.consolidationErr) loadConsolidation();
  const strip = store.actions.scenarioStrip?.() || null;
  if (!c) { replace(body, strip, viewHead(t('view.consolidation'), 'merge'), h('div', { class: 'view-scroll' }, d.consolidationErr ? failCard(d.consolidationErr, { onRetry: () => loadConsolidation() }) : skeleton(6))); return; }
  const flags = d.settings?.flags || {};
  const curationFlags = Object.entries(flags).filter(([k]) => /curat/i.test(k));
  const gates = c.gates || {};
  const weights = c.weights || {};
  const labels = c.labels || {};
  const curated = [...(c.curated || [])].sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0));
  const left = h('div', { class: 'col' },
    h('div', { class: 'col-head' }, h('h3', { class: 'col-title' }, t('cons.curated')), h('span', { class: 'chip chip-xs tone-ext' }, icon('puzzle', 10), t('badge.extension')), labels.curated ? h('span', { class: 'chip chip-xs tone-neutral' }, labels.curated) : null),
    curated.length ? curated.map((w) => h('article', { class: 'cw', 'data-testid': 'curated-write' },
      h('div', { class: 'cw-head' }, h('span', { class: 'num muted' }, fmtTime(w.ts, { seconds: false })),
        w.turnId !== undefined ? h('button', { type: 'button', class: 'link', onclick: () => { u.follow = false; u.pinnedTurn = w.turnId; store.actions.setView('chat'); store.actions.openInspector('diff'); } }, `#${w.turnId}`) : null,
        h('span', { class: 'mono' }, w.path), chip({ label: t(`cons.kind.${w.kind}`), tone: w.refused ? 'warn' : 'accent', cls: 'chip-xs' }), w.flag ? h('span', { class: 'mono muted small' }, w.flag) : null,
        w.refused ? chip({ label: `${t('tool.refused')}: ${w.reason || ''}`, tone: 'warn', ic: 'alert-triangle', cls: 'chip-xs' }) : null,
        h('span', { class: 'spacer' }),
        w.refused ? null : btn(t('act.revert'), { size: 'xs', kind: 'ghost', ic: 'rotate-ccw', onClick: () => revertCurated(w) })),
      w.diff ? h('div', { class: 'cw-diff' }, diffView(parseUnified(w.diff).map((hk) => ({ ...hk, lines: hk.lines.filter((l) => l.t !== '=') })), { compact: true, maxLines: 8 })) : null))
      : emptyState({ title: t('cons.noCurated'), level: 4 }));
  const cands = c.candidates || [];
  const right = h('div', { class: 'col' },
    h('div', { class: 'col-head' }, h('h3', { class: 'col-title' }, t('cons.scored'))),
    // labels.scored is built from docs/parity_matrix.md rows: a long line, so a wrapping note.
    labels.scored ? h('p', { class: 'col-note', 'data-testid': 'cons-scored-label' }, labels.scored) : null,
    h('div', { class: 'gates' },
      gates.minScore !== undefined ? chip({ label: t('cons.gate.score', { v: fmtScore(gates.minScore, 2) }), tone: 'neutral', cls: 'chip-xs' }) : null,
      gates.minRecallCount !== undefined ? chip({ label: t('cons.gate.recall', { v: gates.minRecallCount }), tone: 'neutral', cls: 'chip-xs' }) : null,
      gates.minUniqueQueries !== undefined ? chip({ label: t('cons.gate.unique', { v: gates.minUniqueQueries }), tone: 'neutral', cls: 'chip-xs' }) : null,
      gates.limit !== undefined ? chip({ label: t('cons.gate.limit', { v: gates.limit }), tone: 'neutral', cls: 'chip-xs' }) : null,
      gates.maxAgeDays !== undefined ? chip({ label: t('cons.gate.age', { v: gates.maxAgeDays }), tone: 'neutral', cls: 'chip-xs' }) : null),
    h('div', { class: 'legend' }, COMP_ORDER.filter((k) => weights[k] !== undefined || (k === 'phaseBoost' && cands.some((x) => x.components?.phaseBoost !== undefined))).map((k, i) => h('span', { class: 'legend-item' }, h('span', { class: 'bswatch', style: { '--c': `var(--seg-${i + 1})` } }), `${compLabel(k)}${weights[k] !== undefined ? ` ${fmtScore(weights[k], 2)}` : ''}`))),
    c.shortTerm ? h('div', { class: 'st-stats muted small' }, t('cons.shortTerm', { a: fmtN(c.shortTerm.entries), b: fmtN(c.shortTerm.promoted) }), ' · ', h('span', { class: 'mono' }, c.shortTerm.storePath || '')) : null,
    h('div', { class: 'actions-row' },
      btn(t('cons.promote'), { size: 'sm', kind: 'primary', ic: 'merge', target: 'promote', busy: busy.has('promote'), onClick: promote, testid: 'cons-promote' }),
      h('div', { class: 'btn-group', role: 'group', 'aria-label': t('cons.dreamPhase') }, ['light', 'rem', 'deep'].map((p) => btn(`${t('cons.dream')}: ${p}`, { size: 'sm', kind: 'ghost', ic: 'moon', busy: busy.has(`dream:${p}`), onClick: () => dream(p) }))),
      btn(t('cons.audit'), { size: 'sm', ic: 'check', target: 'audit', busy: busy.has('audit'), onClick: audit, testid: 'cons-audit' }),
      btn(t('cons.repair'), { size: 'sm', kind: 'ghost', ic: 'rotate-ccw', busy: busy.has('repair'), onClick: repair })),
    cands.length ? h('div', { class: 'cands' }, cands.map((x) => h('article', { class: ['cand', x.selected ? 'is-selected' : ''], 'data-testid': 'candidate-row' },
      h('div', { class: 'cand-score' }, h('span', { class: 'num cand-num' }, fmtScore(x.score)), h('span', { class: 'gate-mini' }, h('span', { class: 'gm-fill', style: { '--p': `${Math.min(100, x.score * 100)}%` } }), gates.minScore !== undefined ? h('span', { class: 'gm-gate', style: { '--x': `${gates.minScore * 100}%` } }) : null)),
      h('div', { class: 'cand-main' },
        h('div', { class: 'cand-top' }, h('button', { type: 'button', class: 'cite', onclick: () => store.actions.openFile(x.path, x.startLine, x.endLine) }, icon('file-text', 12), `${x.path}#L${x.startLine}-L${x.endLine}`),
          x.selected ? chip({ label: t('cons.selected'), tone: 'accent', ic: 'check', cls: 'chip-xs' }) : chip({ label: `${t('cons.gated')}${x.reasons?.[0] ? `: ${x.reasons[0]}` : ''}`, tone: 'neutral', ic: 'minus', cls: 'chip-xs' })),
        h('div', { class: 'cand-snippet' }, x.snippet),
        h('div', { class: 'cand-stats' },
          stat(t('cons.recallCount'), x.recallCount, x.gates?.recall), stat(t('cons.uniqueQueries'), x.uniqueQueries, x.gates?.unique), stat(t('cons.dailyCount'), x.dailyCount), stat(t('cons.grounded'), x.groundedCount), stat(t('cons.age'), x.ageDays !== undefined ? `${fmtScore(x.ageDays, 1)} ${t('unit.days')}` : '—'),
          componentBar(x, weights, gates.minScore)),
        h('div', { class: 'cand-tags' }, (x.conceptTags || []).map((tag) => h('span', { class: 'tag' }, tag)),
          (x.reasons || []).length > 1 ? h('details', { class: 'reasons' }, h('summary', null, t('cons.reasons', { n: x.reasons.length })), h('ul', null, x.reasons.map((r) => h('li', null, r)))) : null)))))
      : emptyState({ title: t('cons.noCandidates'), text: t('cons.noCandidatesText'), level: 4 }),
    (d.consResults || []).map(resultCard),
    c.audit ? jsonDisclosure(c.audit, { title: 'audit' }) : null);
  replace(body, strip,
    viewHead(t('view.consolidation'), 'merge', curationFlags.map(([k, f]) => chip({ label: `${f.label || k}: ${f.on ? t('state.on') : t('state.off')}`, tone: f.on ? 'ok' : 'neutral', ext: !!f.extension, onClick: () => store.actions.openSettings('curation'), title: k }))),
    h('div', { class: 'view-scroll' },
      h('div', { class: 'cons-switch' }, segmented({ options: [{ value: 'curated', label: t('cons.curatedShort') }, { value: 'scored', label: t('cons.scoredShort') }], value: u.consolidationPane, onChange: (v) => { u.consolidationPane = v; refresh('center'); }, aria: t('cons.pane'), size: 'sm' })),
      h('div', { class: ['cons-grid', `show-${u.consolidationPane}`] }, left, right),
      h('div', { class: 'insp-foot muted' }, icon('info', 12), t('cons.footer'))));
}
