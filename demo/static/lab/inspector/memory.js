// inspector/memory.js: Bellek tab. Index status strip, this turn's automatic recall (from the
// stored TurnDetail) and the Deneme alanı (POST /api/search, real memory_search payloads).
import { h, icon, fmtN, fmtMs, fmtTime, fmtScore, wordTokens } from '../ui/dom.js';
import { highlightWords } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, providerBody, loadIndex } from '../store.js';
import { api } from '../api.js';
import { chip, btn, segmented, jsonDisclosure, emptyState, failCard, skeleton, honesty, howItWorks } from '../ui/kit.js';
import { selectEl } from './common.js';
import { cooldownLeft } from '../views/shell.js';

const MODES = ['hybrid', 'vector', 'text'];

export async function runSearch() {
  const q = store.ui.search;
  q.running = true; q.error = null; refresh('inspector');
  const started = performance.now();
  try {
    const res = await api.post('/api/search', { query: q.query, mode: q.mode, corpus: q.corpus, maxResults: q.maxResults, minScore: q.minScore, ...providerBody() });
    q.result = { ...res, clientMs: Math.round(performance.now() - started), request: { query: q.query, mode: q.mode, corpus: q.corpus, maxResults: q.maxResults, minScore: q.minScore } };
  } catch (err) {
    // A 400 carries the tool's own error text; show it verbatim like an error payload.
    q.result = err.body && !err.missing ? { ...err.body, results: [], disabled: true, httpStatus: err.status, request: { ...q } } : null;
    q.error = err.missing || !err.body ? err : null;
  }
  q.running = false;
  loadIndex();
  refresh('inspector', 'status', 'top');
  return q.result;
}

function scoreBar(label, v) {
  const off = v === null || v === undefined;
  return h('span', { class: 'sbar', 'data-tip': off ? t('search.legOff') : `${label === 'v' ? t('search.vector') : t('search.text')} ${fmtScore(v)}` },
    h('span', { class: 'sbar-k' }, label), h('span', { class: 'sbar-track' }, off ? null : h('span', { class: `sbar-fill sbar-${label}`, style: { '--p': `${Math.min(100, v * 100)}%` } })),
    h('span', { class: 'sbar-v num' }, off ? '—' : fmtScore(v, 2)));
}
function formula(r, weights) {
  if (r.vectorScore === null || r.vectorScore === undefined || r.textScore === null || r.textScore === undefined) return fmtScore(r.score);
  if (weights) return `${fmtScore(weights.vector, 1)} × ${fmtScore(r.vectorScore)} + ${fmtScore(weights.text, 1)} × ${fmtScore(r.textScore)} = ${fmtScore(r.score)}`;
  return `v ${fmtScore(r.vectorScore)} · t ${fmtScore(r.textScore)} → ${fmtScore(r.score)}`;
}
/** Legs the search ran with, from the payload: provider none / model fts-only means no vector leg. */
export function legsOf(res) {
  const ftsOnly = res?.provider === 'none' || res?.model === 'fts-only';
  const mode = res?.mode || res?.request?.mode;
  return { vector: !ftsOnly && mode !== 'text', text: mode !== 'vector' };
}
export function resultRow(r, rank, { terms = [], used = null, filtered = null, compact = false, minScore = null, weights = null, legs = null } = {}) {
  const words = r.matchedTerms || terms;
  const vScore = legs && !legs.vector ? null : r.vectorScore;
  const tScore = legs && !legs.text ? null : r.textScore;
  return h('div', { class: ['result', used ? 'is-used' : '', filtered ? 'is-filtered' : ''], 'data-testid': 'search-result' },
    h('span', { class: 'r-rank num' }, String(rank)),
    h('div', { class: 'r-main' },
      h('div', { class: 'r-top' },
        h('button', { type: 'button', class: 'cite', onclick: () => store.actions.openFile(r.path, r.startLine, r.endLine), 'data-tip': t('search.openAt') }, icon('file-text', 12), r.citation || `${r.path}#L${r.startLine}`),
        used ? h('span', { class: 'chip chip-xs tone-ok' }, icon('check', 10), t('search.inPrompt')) : null,
        filtered ? h('span', { class: 'chip chip-xs tone-neutral', 'data-tip': filtered }, icon('minus', 10), t('search.filtered')) : null,
        r.corpus && r.corpus !== 'memory' ? h('span', { class: 'chip chip-xs tone-neutral' }, r.corpus) : null,
        h('span', { class: 'spacer' }),
        h('span', { class: 'r-score num', 'data-tip': formula({ ...r, vectorScore: vScore, textScore: tScore }, weights) }, fmtScore(r.score))),
      compact ? null : h('div', { class: 'r-bars' }, scoreBar('v', vScore), scoreBar('t', tScore),
        minScore ? h('span', { class: 'r-gate', style: { '--x': `${Math.min(100, minScore * 100)}%` }, 'data-tip': `minScore ${fmtScore(minScore, 2)}` }) : null),
      h('div', { class: 'r-snippet' }, highlightWords(String(r.snippet || '').replace(/\n+/g, ' '), words))));
}

export function memoryTab(turn) {
  const d = store.data; const u = store.ui; const q = u.search;
  const idx = d.index; const s = d.settings;
  const fts = s?.embedding?.mode === 'fts-only' || idx?.embeddings?.mode === 'fts-only';
  const cd = cooldownLeft();
  const wrap = h('div', { class: 'memory-tab' });
  wrap.append(howItWorks('memory'));
  const identity = idx?.identity;
  wrap.append(h('div', { class: 'status-strip' },
    idx ? chip({ label: `${t('memory.identity')}: ${identity?.status ? t(`identity.${identity.status}`) : '—'}`, tone: { valid: 'ok', mismatched: 'danger', missing: 'warn' }[identity?.status] || 'neutral', ic: identity?.status === 'valid' ? 'check' : 'alert-triangle', title: `${identity?.reason || ''}\n${t('memory.identityNotFile')}`.trim(), testid: 'index-identity' }) : null,
    s?.embedding || idx?.embeddings ? chip({ label: fts ? t('search.ftsOnly') : `${t('search.hybrid')} · ${s?.embedding?.model || idx?.embeddings?.model || '—'}`, title: fts ? (s?.embedding?.reason || idx?.embeddings?.reason || t('search.noEmbedder')) : null, tone: fts ? 'warn' : 'info', ic: 'layers', testid: 'memory-embedding' }) : null,
    idx ? chip({ label: `${fmtN(idx.chunks)} ${t('unit.chunks')} · ${fmtTime(idx.lastReindexAt)}`, tone: 'neutral', ic: 'database' }) : null,
    cd ? chip({ label: `${t('search.cooldown')} ${cd} ${t('unit.sec')}`, tone: 'warn', ic: 'clock', testid: 'chip-cooldown', title: idx?.cooldown?.error || '' }) : null,
    idx?.deadlineMs ? chip({ label: `${t('search.deadline')} ${fmtMs(idx.deadlineMs)}`, tone: 'neutral', ic: 'clock' }) : null,
    btn(t('act.reindex'), { size: 'xs', kind: 'ghost', ic: 'rotate-ccw', onClick: () => store.actions.reindex() })));
  if (d.indexErr && !idx) wrap.append(failCard(d.indexErr, { compact: true }));

  // Bu tur
  const detail = turn && typeof turn.id === 'number' ? d.details.get(turn.id) : null;
  const rc = detail?.recall;
  wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('memory.thisTurn')), turn ? h('span', { class: 'muted' }, `#${turn.id}`) : null, h('span', { class: 'chip chip-xs tone-warn', 'data-tip': t('memory.autoRecallTip') }, 'demo-only'),
    h('span', { class: 'spacer' }), rc && (rc.maxResults !== undefined || rc.minScore !== undefined) ? h('span', { class: 'muted small' }, t('memory.autoRecallParams', { m: rc.maxResults ?? '—', s: rc.minScore ?? '—' })) : null));
  if (!turn) wrap.append(h('div', { class: 'muted pad' }, t('inspector.noTurn')));
  else if (!detail && !d.detailErr.get(turn.id)) wrap.append(skeleton(2));
  else if (!detail) wrap.append(failCard(d.detailErr.get(turn.id), { compact: true }));
  else if (!rc) wrap.append(h('div', { class: 'muted pad' }, turn.reset ? t('memory.resetNoRecall') : t('memory.noRecall')));
  else {
    wrap.append(h('div', { class: 'query-line' }, icon('search', 12), h('span', { class: 'mono' }, rc.query || '—')));
    const results = rc.results || [];
    if (!results.length) wrap.append(h('div', { class: 'muted pad' }, t('memory.recallZero')));
    const usedSet = new Set(rc.used || []);
    const filteredBy = new Map((rc.filtered || []).map((x) => [x.path, x.reason]));
    results.forEach((r, i) => wrap.append(resultRow(r, i + 1, { terms: wordTokens(rc.query), used: usedSet.has(r.path) || usedSet.has(r.citation), filtered: filteredBy.get(r.path) || null, compact: true })));
  }

  // Deneme alanı
  wrap.append(h('div', { class: 'subhead' }, h('h3', null, t('memory.playground')), h('span', { class: 'spacer' }),
    h('span', { class: 'chip chip-xs tone-neutral', 'data-tip': t('memory.upstreamDefaultsTip') }, t('memory.upstreamDefaults'))));
  const qInput = h('input', { class: 'input', type: 'search', value: q.query, placeholder: t('memory.query'), 'aria-label': t('memory.query'), 'data-testid': 'search-query', oninput: (e) => { q.query = e.target.value; } });
  const form = h('form', { class: 'search-form', 'data-testid': 'search-form', onsubmit: (e) => { e.preventDefault(); q.query = qInput.value; runSearch(); } },
    h('div', { class: 'sf-row' }, qInput, btn(q.running ? t('search.running') : t('search.run'), { kind: 'primary', size: 'sm', type: 'submit', busy: q.running, testid: 'search-run' })),
    h('div', { class: 'sf-row sf-wrap' },
      segmented({ options: MODES.map((m) => ({ value: m, label: t(`search.mode.${m}`), disabled: fts && m !== 'text', title: fts && m !== 'text' ? t('search.ftsOnlyTip') : null })), value: fts ? 'text' : q.mode, onChange: (v) => { q.mode = v; refresh('inspector'); }, aria: t('search.modeLabel'), size: 'sm', testid: 'search-mode' }),
      h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, 'corpus'), selectEl(['all', 'memory', 'sessions', 'wiki'], q.corpus, (v) => { q.corpus = v; }, { aria: 'corpus' })),
      h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, 'maxResults'), numInput(q.maxResults, (v) => { q.maxResults = v; }, { step: 1, aria: 'maxResults', testid: 'search-max' })),
      h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, 'minScore'), numInput(q.minScore, (v) => { q.minScore = v; }, { step: 0.05, aria: 'minScore', testid: 'search-min' }))));
  if (fts && q.mode !== 'text') q.mode = 'text';
  wrap.append(form);
  const res = q.result;
  if (q.error) wrap.append(failCard(q.error));
  else if (!res) wrap.append(h('div', { class: 'muted pad' }, t('memory.runQuery')));
  else if (res.error || res.disabled) {
    wrap.append(h('div', { class: 'error-card is-flat', role: 'alert', 'data-testid': 'search-error' },
      h('div', { class: 'error-title' }, icon('alert-octagon', 14), res.unavailable ? 'unavailable' : t('search.toolError'), res.cooldown ? h('span', { class: 'chip chip-xs tone-warn' }, t('search.cooledDown')) : null),
      h('div', { class: 'error-msg mono' }, String(res.error || '')),
      res.warning ? h('div', { class: 'error-msg' }, h('b', null, 'warning: '), res.warning) : null,
      res.action ? h('div', { class: 'error-msg' }, h('b', null, 'action: '), res.action) : null,
      jsonDisclosure(res, { title: 'memory_search' })));
  } else {
    const rows = res.results || [];
    wrap.append(h('div', { class: 'result-meta muted', 'data-testid': 'search-meta' },
      `${rows.length} ${t('search.results')} · ${t(`search.mode.${res.mode || res.request?.mode || 'text'}`)}${res.provider ? ` · ${res.provider}/${res.model}` : ''} · ${fmtMs(res.ms ?? res.clientMs)}`));
    if (!rows.length) wrap.append(emptyState({ title: t('search.noMatch'), text: t('search.noMatchText'), testid: 'empty-memory', level: 4 }));
    rows.forEach((r, i) => wrap.append(resultRow(r, i + 1, { terms: wordTokens(res.request?.query || ''), minScore: res.request?.minScore, weights: res.weights || null, legs: legsOf(res) })));
    if (!res.matchedTermsSupported && rows.length) wrap.append(honesty(t('search.highlightNote'), 'neutral', 'info'));
    wrap.append(jsonDisclosure(res, { title: 'memory_search' }));
  }
  return wrap;
}
function numInput(value, onChange, { step = 1, aria = null, testid = null } = {}) {
  return h('input', { class: 'input input-num', type: 'number', value: String(value), step: String(step), 'aria-label': aria, 'data-testid': testid, onchange: (e) => onChange(e.target.value === '' ? '' : Number(e.target.value)) });
}
