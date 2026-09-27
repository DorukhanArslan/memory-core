// views/parity.js: the only surface that names OpenClaw. Everything comes from GET /api/lab/parity:
// `matrix[]` are the docs/parity_matrix.md rows (MatrixRow {area, openclawSource, pythonSource,
// oracleOperation, status, knownGaps, nextTest, priority}); `results` is the parity-results.json
// file (byArea[].evidence and byEvidence counted per evidence kind, demo/parity_results.py);
// `commands[]` produce it. The two tables are not joined: matrix rows and result areas use
// different ids. Direct Python==TS tests and TS-vs-literal tests are counted apart (critique #14).
import { h, replace, fmtN, fmtScore, copyText } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, loadParity, refresh } from '../store.js';
import { api } from '../api.js';
import { chip, btn, iconBtn, jsonDisclosure, failCard, skeleton, honesty, howItWorks } from '../ui/kit.js';
import { toast } from '../ui/overlay.js';
import { viewHead, card } from './heartbeat.js';

const ST_TONE = { match: 'ok', partial: 'warn', mismatch: 'danger', missing: 'danger', 'out of scope': 'neutral' };
const EV_TONE = { 'oracle-backed': 'ok', 'oracle-backed-gaps': 'warn', 'source-backed': 'info', 'known-gap': 'danger' };
// Evidence kinds of demo/parity_results.py, in display order.
const KINDS = ['python_eq_ts', 'ts_literal', 'python_eq_source', 'python_literal', 'other'];
const NO_OP = /^(not added|not planned|)$/i;

/**
 * Evidence label derived from the matrix status (the project's mapping: match = oracle-backed;
 * partial = oracle-backed with gaps when the row names an oracle operation, else source-backed;
 * mismatch, missing = known-gap). Out-of-scope rows get no evidence label.
 */
export function evidenceOf(row) {
  const st = row.status;
  if (st === 'match') return 'oracle-backed';
  if (st === 'partial') return NO_OP.test(String(row.oracleOperation || '').trim()) ? 'source-backed' : 'oracle-backed-gaps';
  if (st === 'mismatch' || st === 'missing') return 'known-gap';
  return null;
}
const evLabel = (ev) => t(`parity.ev.${ev}`);
const kindLabel = (k) => (has(`parity.kind.${k}`) ? t(`parity.kind.${k}`) : k);
const stKey = (st) => `parity.st.${String(st).replace(/\W+/g, '_')}`;
const stTip = (st) => (has(stKey(st)) ? t(stKey(st)) : null);
const plain = (s) => String(s || '').replace(/`/g, '');
const sumCounts = (c) => (c ? (c.passed || 0) + (c.failed || 0) + (c.skipped || 0) : 0);
const ratio = (c) => (sumCounts(c) ? `${c.passed || 0}/${sumCounts(c)}` : '—');

async function runTrace() {
  const d = store.data;
  d.parityTrace = { loading: true };
  refresh('center');
  try { d.parityTrace = { res: await api.post('/api/parity/trace', {}) }; } catch (err) { d.parityTrace = { err }; }
  refresh('center');
}
const cmdLine = (cmd) => h('div', { class: 'cmd' }, h('code', { class: 'mono' }, cmd), iconBtn('copy', t('act.copy'), () => copyText(cmd).then(() => toast(t('toast.copied'), { tone: 'ok' })), { size: 'xs' }));

function resultsBlock(p, r) {
  const byEv = r.byEvidence || {};
  const kinds = KINDS.filter((k) => byEv[k]).concat(Object.keys(byEv).filter((k) => !KINDS.includes(k)));
  const areas = r.byArea || [];
  return [
    h('div', { class: 'kpis kpis-auto' },
      kpi(t('parity.passed'), r.totals?.passed, 'ok'), kpi(t('parity.failed'), r.totals?.failed, r.totals?.failed ? 'danger' : 'neutral'), kpi(t('parity.skipped'), r.totals?.skipped, 'neutral'),
      kpi(t('parity.duration'), r.durationS !== undefined ? `${fmtScore(r.durationS, 0)} ${t('unit.sec')}` : '—', 'neutral')),
    h('div', { class: 'kpis kpis-auto', 'data-testid': 'parity-evidence' }, kinds.map((k) => h('div', { class: ['kpi', k === 'python_eq_ts' ? 'tone-ok' : 'tone-neutral'], 'data-tip': r.evidenceKinds?.[k] || null },
      h('span', { class: 'kpi-k muted' }, kindLabel(k)), h('span', { class: 'kpi-v num' }, ratio(byEv[k]))))),
    h('div', { class: 'muted small pad parity-meta' }, h('span', { class: 'mono' }, r.path || p.resultsPath || ''), ` · generatedAt ${r.generatedAt || '—'} · commit `, h('span', { class: 'mono' }, r.commit || '—'), r.pin ? ` · pin ${String(r.pin).slice(0, 8)}` : ''),
    areas.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table', 'data-testid': 'parity-results' },
      h('caption', { class: 'sr-only' }, t('parity.resultsCaption')),
      h('thead', null, h('tr', null, [t('parity.col.area'), t('parity.passed'), t('parity.failed'), t('parity.skipped'), kindLabel('python_eq_ts'), kindLabel('ts_literal'), t('parity.col.otherKinds'), t('parity.col.tests')].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', null, areas.map((a) => {
        const ev = a.evidence || {};
        const other = Object.entries(ev).filter(([k]) => k !== 'python_eq_ts' && k !== 'ts_literal');
        return h('tr', { 'data-testid': 'parity-area' },
          h('td', null, a.label || a.area),
          h('td', { class: 'num' }, fmtN(a.passed)), h('td', { class: ['num', a.failed ? 'tone-text-danger' : ''] }, fmtN(a.failed)), h('td', { class: 'num' }, fmtN(a.skipped)),
          h('td', { class: 'num' }, ratio(ev.python_eq_ts)), h('td', { class: 'num', 'data-tip': t('parity.literalTip') }, ratio(ev.ts_literal)),
          h('td', { class: 'small' }, other.length ? other.map(([k, c]) => `${kindLabel(k)} ${ratio(c)}`).join(' · ') : '—'),
          h('td', null, (a.tests || []).length ? h('details', { class: 'reasons' }, h('summary', null, t('parity.testsN', { n: a.tests.length })),
            h('ul', { class: 'parity-tests' }, a.tests.map((x) => h('li', { class: `is-${x.outcome}` }, h('span', { class: 'mono' }, x.nodeid), ` · ${x.outcome} · ${kindLabel(x.evidence)}`)))) : '—'));
      })))) : null,
  ];
}

function matrixBlock(matrix) {
  const counts = matrix.reduce((acc, m) => { acc[m.status] = (acc[m.status] || 0) + 1; return acc; }, {});
  return [
    h('div', { class: 'parity-matrix-head' },
      h('h3', { class: 'card-title' }, `${t('parity.matrix')} · ${fmtN(matrix.length)} ${t('parity.rows')}`),
      h('span', { class: 'muted small' }, Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(' · '))),
    honesty(t('parity.evidenceDerived'), 'neutral', 'info'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table parity-matrix', 'data-testid': 'parity-matrix' },
      h('caption', { class: 'sr-only' }, t('parity.matrixCaption')),
      h('thead', null, h('tr', null, [t('parity.col.area'), t('parity.col.status'), t('parity.col.evidence'), t('parity.col.oracleOp'), t('parity.col.priority'), t('parity.col.gaps')].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', null, matrix.map((m) => {
        const ev = evidenceOf(m);
        const op = plain(m.oracleOperation);
        return h('tr', { 'data-testid': 'parity-row' },
          h('td', { class: 'parity-area-cell' }, plain(m.area)),
          h('td', null, m.status ? chip({ label: m.status, tone: ST_TONE[m.status] || 'neutral', cls: 'chip-xs', title: stTip(m.status) }) : '—'),
          h('td', null, ev ? chip({ label: evLabel(ev), tone: EV_TONE[ev] || 'neutral', cls: 'chip-xs' }) : h('span', { class: 'muted', 'data-tip': t('parity.noEvidenceTip') }, '—')),
          h('td', { class: ['small', NO_OP.test(op.trim()) ? 'muted' : 'mono'] }, op || '—'),
          h('td', { class: 'mono small' }, m.priority || '—'),
          h('td', null, m.knownGaps || m.nextTest ? h('details', { class: 'reasons' }, h('summary', null, t('parity.gapsShow')),
            m.knownGaps ? h('p', { class: 'parity-gap' }, plain(m.knownGaps)) : null,
            m.nextTest ? h('p', { class: 'parity-gap muted' }, h('b', null, `${t('parity.nextTest')}: `), plain(m.nextTest)) : null) : h('span', { class: 'muted' }, '—')));
      })))),
  ];
}

export function renderParity(body) {
  const d = store.data;
  const p = d.parity;
  if (!p && !d.parityErr) loadParity();
  const strip = store.actions.scenarioStrip?.() || null;
  if (!p) { replace(body, strip, viewHead(t('parity.title'), 'scale'), h('div', { class: 'view-scroll' }, d.parityErr ? failCard(d.parityErr, { onRetry: () => loadParity() }) : skeleton(6))); return; }
  const r = p.results;
  const matrix = p.matrix || [];
  const commands = p.commands || [];
  const tr = d.parityTrace;
  replace(body, strip,
    viewHead(t('parity.title'), 'scale', [
      p.pin ? chip({ label: `pin ${String(p.pin).slice(0, 8)}`, tone: 'info', cls: 'chip-mono', onClick: () => copyText(p.pin).then(() => toast(t('parity.hashCopied'), { tone: 'ok' })), title: p.pin, testid: 'parity-pin' }) : null,
      p.oracleRepo ? chip({ label: `OPENCLAW_ORACLE_REPO: ${p.oracleRepo.path || '—'}`, tone: !p.oracleRepo.exists ? 'danger' : p.oracleRepo.pinned === false ? 'warn' : 'ok', ic: !p.oracleRepo.exists ? 'alert-octagon' : p.oracleRepo.pinned === false ? 'alert-triangle' : 'check', title: p.oracleRepo.head ? `HEAD ${p.oracleRepo.head}${p.oracleRepo.pinned === false ? ` (${t('parity.notPinned')})` : ''}` : p.oracleRepo.exists ? t('parity.noGitHead') : t('parity.noCheckout'), cls: 'chip-mono', testid: 'parity-oracle-repo' }) : null,
      chip({ label: p.node?.version ? `node ${p.node.version}` : t('parity.noNode'), tone: !p.node?.version ? 'warn' : p.node.satisfies === false || p.node.namedNode === false ? 'danger' : 'neutral', ic: p.node?.satisfies === false || p.node?.namedNode === false ? 'alert-octagon' : undefined, cls: 'chip-mono', title: p.node ? [p.node.env ? `${p.node.env}=${p.node.path}` : p.node.path, p.node.namedNode === false ? t('parity.nodeNotNamedNode') : null, p.node.engines ? `engines ${p.node.engines}${p.node.satisfies === false ? ` (${t('parity.nodeOutOfRange')})` : ''}` : null].filter(Boolean).join(' · ') : null, testid: 'parity-node' }),
    ].filter(Boolean)),
    h('div', { class: 'view-scroll' },
      howItWorks('parity'),
      r ? resultsBlock(p, r) : card(t('parity.noResults'), [
        h('p', { class: 'muted' }, t('parity.noResultsText')),
        p.resultsPath ? h('div', { class: 'muted small' }, t('parity.resultsPath'), ' ', h('code', { class: 'mono' }, p.resultsPath)) : null,
        commands.map(cmdLine),
        h('div', { class: 'muted small' }, t('parity.cmdNote')),
        h('div', { class: 'muted small' }, t('parity.cmdNodeNote')),
      ], { ic: 'command', testid: 'empty-parity' }),
      matrix.length ? matrixBlock(matrix) : null,
      card(t('parity.trace'), [
        h('div', { class: 'sf-row sf-wrap' }, btn(t('parity.runTrace'), { size: 'sm', ic: 'play', busy: !!tr?.loading, onClick: runTrace, testid: 'parity-trace' }), h('span', { class: 'muted small' }, t('parity.traceCoverage'))),
        tr?.err ? failCard(tr.err, { compact: true }) : null,
        tr?.res ? h('div', { class: 'trace' },
          h('div', { class: 'trace-head' }, h('span', null, t('parity.step')), h('span', null, 'Python'), h('span', null, 'OpenClaw TS'), h('span', null, '')),
          (tr.res.steps || []).map((x) => {
            const ok = x.diff?.status === 'match';
            return h('div', { class: 'trace-row' }, h('span', { 'data-tip': x.condition || '' }, x.label || x.id),
              h('span', { class: 'mono' }, x.python?.decision ?? '—'), h('span', { class: 'mono' }, x.openclaw?.decision ?? '—'),
              chip({ label: x.diff?.status || '—', tone: ok ? 'ok' : 'danger', ic: ok ? 'check' : 'x', cls: 'chip-xs' }));
          }),
          jsonDisclosure(tr.res, { title: 'parity trace' })) : null,
      ], { ic: 'activity', right: h('span', { class: 'muted small mono' }, '/api/parity/trace') })));
}
function kpi(k, v, tone) { return h('div', { class: ['kpi', `tone-${tone}`] }, h('span', { class: 'kpi-k muted' }, k), h('span', { class: 'kpi-v num' }, v === undefined || v === null ? '—' : String(v))); }
