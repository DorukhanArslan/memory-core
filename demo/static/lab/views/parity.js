// views/parity.js: the only surface that names OpenClaw. Numbers come from GET /api/lab/parity
// (results file joined with docs/parity_matrix.md rows); nothing is hardcoded. Direct
// Python==TS tests and TS-vs-literal tests are counted apart (critique #14).
import { h, icon, replace, fmtN, fmtScore, copyText } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, loadParity, refresh } from '../store.js';
import { api } from '../api.js';
import { chip, btn, iconBtn, jsonDisclosure, emptyState, failCard, skeleton, honesty } from '../ui/kit.js';
import { toast } from '../ui/overlay.js';
import { viewHead, card } from './heartbeat.js';

const EV_TONE = { 'oracle-backed': 'ok', 'source-backed': 'info', 'adapter-only': 'neutral', 'demo-only': 'warn', 'known-gap': 'danger' };
const ST_TONE = { match: 'ok', partial: 'warn', mismatch: 'danger', missing: 'danger', 'out of scope': 'neutral' };
const CMD_TESTS = '.venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_openclaw_ts_oracle.py tests/integration/test_memory_tools.py --junitxml=<tmp>/memory-core-lab/oracle.xml';
const CMD_RESULTS = 'python -m demo.parity_results <tmp>/memory-core-lab/oracle.xml --out <tmp>/memory-core-lab/parity-results.json';

function counts(tests, kind) {
  const list = (tests || []).filter((x) => (x.comparison || x.kind) === kind);
  return { passed: list.filter((x) => x.outcome === 'passed').length, total: list.length };
}
async function runTrace() {
  const d = store.data;
  d.parityTrace = { loading: true };
  refresh('center');
  try { d.parityTrace = { res: await api.post('/api/parity/trace', {}) }; } catch (err) { d.parityTrace = { err }; }
  refresh('center');
}
const cmdLine = (cmd) => h('div', { class: 'cmd' }, h('code', { class: 'mono' }, cmd), iconBtn('copy', t('act.copy'), () => copyText(cmd).then(() => toast(t('toast.copied'), { tone: 'ok' })), { size: 'xs' }));

export function renderParity(body) {
  const d = store.data;
  const p = d.parity;
  if (!p && !d.parityErr) loadParity();
  const strip = store.actions.scenarioStrip?.() || null;
  if (!p) { replace(body, strip, viewHead(t('parity.title'), 'scale'), h('div', { class: 'view-scroll' }, d.parityErr ? failCard(d.parityErr, { onRetry: () => loadParity() }) : skeleton(6))); return; }
  const r = p.results;
  const matrix = p.matrix || [];
  const byArea = new Map((r?.byArea || []).map((a) => [a.area, a]));
  const areas = [...new Set([...matrix.map((m) => m.area), ...byArea.keys()])];
  const hasKinds = (r?.byArea || []).some((a) => (a.tests || []).some((x) => x.comparison || x.kind));
  const tr = d.parityTrace;
  replace(body, strip,
    viewHead(t('parity.title'), 'scale', [
      p.pin ? chip({ label: `pin ${String(p.pin).slice(0, 8)}`, tone: 'info', cls: 'chip-mono', onClick: () => copyText(p.pin).then(() => toast(t('parity.hashCopied'), { tone: 'ok' })), title: p.pin, testid: 'parity-pin' }) : null,
      p.oracleRepo ? chip({ label: `OPENCLAW_ORACLE_REPO: ${p.oracleRepo.path || '—'}`, tone: p.oracleRepo.exists ? 'ok' : 'danger', ic: p.oracleRepo.exists ? 'check' : 'alert-octagon', title: p.oracleRepo.head ? `HEAD ${p.oracleRepo.head}` : t('parity.noCheckout'), cls: 'chip-mono' }) : null,
      chip({ label: p.node?.version ? `node ${p.node.version}` : t('parity.noNode'), tone: p.node?.version ? 'neutral' : 'warn', cls: 'chip-mono' }),
    ].filter(Boolean)),
    h('div', { class: 'view-scroll' },
      !r ? card(t('parity.noResults'), [h('p', { class: 'muted' }, t('parity.noResultsText')), cmdLine(CMD_TESTS), cmdLine(CMD_RESULTS), h('div', { class: 'muted small' }, t('parity.cmdNote'))], { ic: 'command', testid: 'empty-parity' }) : [
        h('div', { class: 'kpis' },
          kpi(t('parity.passed'), r.totals?.passed, 'ok'), kpi(t('parity.failed'), r.totals?.failed, r.totals?.failed ? 'danger' : 'neutral'), kpi(t('parity.skipped'), r.totals?.skipped, 'neutral'),
          kpi(t('parity.duration'), r.durationS !== undefined ? `${fmtScore(r.durationS, 0)} ${t('unit.sec')}` : '—', 'neutral'),
          h('div', { class: 'kpi kpi-wide' }, h('span', { class: 'kpi-k muted' }, t('parity.matrix')), h('span', { class: 'kpi-v' }, `${fmtN(matrix.length)} ${t('parity.rows')}`),
            h('span', { class: 'kpi-sub muted' }, Object.entries(matrix.reduce((acc, m) => { acc[m.status] = (acc[m.status] || 0) + 1; return acc; }, {})).map(([k, v]) => `${v} ${k}`).join(' · ')))),
        h('div', { class: 'muted small pad' }, h('span', { class: 'mono' }, r.path || ''), ` · generatedAt ${r.generatedAt || '—'} · commit `, h('span', { class: 'mono' }, r.commit || '—'), r.pin ? ` · pin ${String(r.pin).slice(0, 8)}` : ''),
        hasKinds ? null : honesty(t('parity.noKinds'), 'neutral', 'info'),
      ],
      matrix.length || byArea.size ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, [t('parity.col.area'), t('parity.col.evidence'), t('parity.col.status'), hasKinds ? t('parity.col.direct') : t('parity.col.tests'), hasKinds ? t('parity.col.literal') : null, t('parity.col.gaps')].filter(Boolean).map((c) => h('th', { scope: 'col' }, c)))),
        h('tbody', null, areas.map((name) => {
          const m = matrix.find((x) => x.area === name) || {};
          const a = byArea.get(name);
          const total = a ? a.passed + a.failed + a.skipped : 0;
          const dir = a && hasKinds ? counts(a.tests, 'python_ts') : null;
          const lit = a && hasKinds ? counts(a.tests, 'ts_literal') : null;
          const gaps = m.gaps || [];
          return h('tr', { 'data-testid': 'parity-area' },
            h('td', null, name),
            h('td', null, m.evidence ? chip({ label: m.evidence, tone: EV_TONE[m.evidence] || 'neutral', cls: 'chip-xs' }) : '—'),
            h('td', null, m.status ? chip({ label: m.status, tone: ST_TONE[m.status] || 'neutral', cls: 'chip-xs' }) : '—'),
            hasKinds ? h('td', { class: 'num' }, dir?.total ? `${dir.passed}/${dir.total}` : '—') : h('td', { class: 'num' }, a ? `${a.passed}/${total}` : h('span', { class: 'muted' }, t('parity.noOracle'))),
            hasKinds ? h('td', { class: 'num', 'data-tip': t('parity.literalTip') }, lit?.total ? `${lit.passed}/${lit.total}` : '—') : null,
            h('td', null, gaps.length ? h('details', { class: 'reasons' }, h('summary', null, t('parity.gaps', { n: gaps.length })), h('ul', null, gaps.map((g) => h('li', null, g)))) : h('span', { class: 'muted' }, '—')));
        })))) : null,
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
export { emptyState };
