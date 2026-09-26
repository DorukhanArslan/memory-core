// views/scenarios.js: Senaryolar list, the ScenarioStrip pinned at the top of the center and the
// scenario result card (Markdown copy for reports).
import { h, icon, replace, fmtMs, fmtTime, copyText } from '../ui/dom.js';
import { t, has } from '../i18n/index.js';
import { store, refresh } from '../store.js';
import { chip, btn, iconBtn, segmented, emptyState } from '../ui/kit.js';
import { toast } from '../ui/overlay.js';
import { SCENARIOS, FULL_RUN, fullRunMinutes } from '../scenarios/catalog.js';
import { sc, startScenario, stopScenario, nextStep, doStepAction, evaluate, setManual, closeResult } from '../scenarios/runner.js';
import { viewHead } from './heartbeat.js';

const STATUS = { passed: { tone: 'ok', ic: 'check' }, failed: { tone: 'danger', ic: 'x' }, partial: { tone: 'warn', ic: 'alert-triangle' }, blocked: { tone: 'neutral', ic: 'minus' }, none: { tone: 'neutral', ic: 'circle' }, running: { tone: 'accent', ic: 'play' } };
const CHECK_IC = { pass: 'check', fail: 'x', gap: 'alert-triangle', manual: 'circle', observe: 'eye', pending: 'dot', blocked: 'minus' };
const kindTag = (k) => t(`scn.kind.${k}`);
const title = (d) => t(`scn.${d.id}.title`);
const goal = (d) => t(`scn.${d.id}.goal`);
const tagLabel = (x) => (has(`tag.${x}`) ? t(`tag.${x}`) : x);
/** Manual and model check labels are i18n ids (scn.*); auto labels are check expressions. */
export const checkLabel = (label) => (String(label).startsWith('scn.') ? t(label) : String(label));
const tagTone = (x) => (/uzantı/.test(x) ? 'ext' : /demo|scripted|D2/.test(x) ? 'warn' : /model/.test(x) ? 'info' : 'neutral');

function instruction(step) {
  const s = sc();
  const verb = (k) => h('span', { class: 'ss-verb' }, t(k));
  if (step.act === 'send' || step.act === 'cmd') return [verb(step.act === 'cmd' ? 'scn.verb.cmd' : 'scn.verb.send'), h('q', { class: 'ss-msg', lang: 'tr' }, step.text),
    step.live ? chip({ label: t('view.live'), tone: 'info', cls: 'chip-xs' }) : null,
    step.kind && step.kind !== 'main' ? h('span', { class: 'kind-tag', 'data-kind': step.kind }, step.kind) : null, h('span', { class: 'spacer' }),
    btn(t('scn.insert'), { size: 'xs', kind: 'ghost', onClick: () => doStepAction(step), testid: 'scenario-insert' }),
    btn(t('scn.insertSend'), { size: 'xs', kind: 'primary', kbd: '⌘↵', onClick: () => doStepAction(step, { send: true }), testid: 'scenario-send' })];
  if (step.act === 'press') return [verb('scn.verb.press'), h('span', { class: 'ss-msg' }, t(step.label)), h('span', { class: 'spacer' }), btn(t('scn.show'), { size: 'xs', kind: 'ghost', ic: 'eye', onClick: () => doStepAction(step) })];
  if (step.act === 'look') return [verb('scn.verb.look'), h('span', { class: 'ss-msg' }, t(step.label)), h('span', { class: 'spacer' }), btn(t('scn.show'), { size: 'xs', kind: 'ghost', ic: 'eye', onClick: () => doStepAction(step), testid: 'scenario-look' }), btn(t('scn.check'), { size: 'xs', onClick: () => evaluate(), busy: !!s?.evaluating })];
  if (step.act === 'edit') return [verb('scn.verb.edit'), h('span', { class: 'ss-msg' }, t(step.label)), h('span', { class: 'spacer' }), btn(t('scn.apply'), { size: 'xs', kind: 'primary', ic: 'pencil', onClick: () => doStepAction(step), title: t('scn.applyEditTip'), testid: 'scenario-edit' })];
  if (step.act === 'strip') return [verb('scn.verb.look'), h('span', { class: 'ss-msg' }, t(step.label)), h('span', { class: 'spacer' }), btn(t('scn.apply'), { size: 'xs', kind: 'primary', onClick: () => doStepAction(step) })];
  return [verb('scn.verb.setting'), h('span', { class: 'ss-msg' }, t(step.label)), h('span', { class: 'spacer' }), btn(t('scn.apply'), { size: 'xs', kind: 'primary', ic: 'sliders', onClick: () => doStepAction(step), testid: 'scenario-apply' })];
}
export function scenarioStrip() {
  const s = sc(); if (!s) return null;
  const def = s.def;
  if (s.finished) return resultCard(def, s.finished, { inStrip: true });
  const step = def.steps[s.step]; if (!step) return null;
  const res = s.stepResults[s.step];
  const checks = step.checks.map((c, i) => {
    const r = res?.[i] || { status: c.kind === 'manual' ? 'manual' : 'pending' };
    const content = [icon(CHECK_IC[r.status] || 'dot', 12), h('span', { class: 'ck-label mono', 'data-tip': checkLabel(c.label) }, checkLabel(c.label)), r.value ? h('span', { class: 'ck-val' }, r.value) : null, h('span', { class: ['ck-kind', `k-${c.kind}`] }, kindTag(c.kind)), c.gap ? h('span', { class: 'chip chip-xs tone-warn' }, t('scn.knownGap')) : null, r.status === 'blocked' ? h('span', { class: 'chip chip-xs tone-neutral' }, t('scn.status.blocked')) : null];
    if (c.kind === 'manual') return h('label', { class: ['check', `is-${r.status}`], 'data-testid': `check-${i}` }, h('input', { type: 'checkbox', checked: !!s.manual[`${s.step}:${i}`], onchange: (e) => setManual(i, e.target.checked) }), ...content);
    return h('div', { class: ['check', `is-${r.status}`], 'data-testid': `check-${i}`, role: 'status', 'aria-label': `${checkLabel(c.label)}: ${t(`scn.check.${r.status}`)}` }, ...content);
  });
  const passed = res && res.every((r, i) => step.checks[i].kind !== 'auto' || r.status === 'pass' || r.status === 'gap');
  const n = def.steps.length; const cur = Math.min(s.step + 1, n);
  return h('section', { class: ['scenario-strip', s.collapsed ? 'is-collapsed' : ''], 'data-testid': 'scenario-strip', 'aria-label': t('scn.stripAria', { id: def.id }) },
    h('div', { class: 'ss-top' },
      icon('flask', 14), h('b', null, def.id), h('span', { class: 'ss-title' }, title(def)),
      h('span', { class: 'ss-progress', 'aria-label': t('scn.progress', { a: cur, b: n }) }, def.steps.map((_, i) => h('span', { class: ['ss-dot', i < s.step ? 'is-done' : i === s.step ? 'is-current' : ''] })), h('span', { class: 'num' }, `${cur}/${n}`)),
      [...(def.labels || []), ...(step.labels || [])].map((l) => h('span', { class: `chip chip-xs tone-${l.tone}` }, t(l.text))),
      h('span', { class: 'spacer' }),
      s.evaluating ? h('span', { class: 'chip chip-xs tone-neutral' }, h('span', { class: 'spinner spinner-xs' }), t('scn.evaluating')) : null,
      s.autoAdvance && passed ? h('span', { class: 'chip chip-xs tone-ok ss-auto' }, t('scn.autoNext'), h('button', { type: 'button', class: 'link', onclick: () => { s.autoAdvance = null; refresh('center'); } }, t('act.cancel'))) : null,
      res && !passed && !s.blocked ? btn(t('scn.recheck'), { size: 'xs', kind: 'ghost', onClick: () => evaluate() }) : null,
      btn(s.step + 1 >= n ? t('scn.finish') : t('scn.skip'), { size: 'xs', kind: 'ghost', onClick: () => nextStep(), testid: 'scenario-next' }),
      btn(t('scn.stop'), { size: 'xs', kind: 'ghost', ic: 'stop', onClick: () => stopScenario() }),
      iconBtn(s.collapsed ? 'chevron-down' : 'chevron-right', s.collapsed ? t('scn.expand') : t('scn.collapse'), () => { s.collapsed = !s.collapsed; refresh('center'); }, { size: 'xs' })),
    s.collapsed ? null : h('div', { class: 'ss-instr' }, instruction(step)),
    s.collapsed ? null : s.blocked ? h('div', { class: 'ss-expect' }, chip({ label: `${t('scn.status.blocked')}: ${t(s.blocked)}`, tone: 'neutral', ic: 'minus' })) : h('div', { class: 'ss-expect' }, h('span', { class: 'muted' }, t('scn.expected')), ' ', t(step.expect)),
    s.collapsed ? null : h('div', { class: 'ss-checks' }, checks));
}
export function resultCard(def, r, { inStrip = false } = {}) {
  const st = STATUS[r.status] || STATUS.none;
  const md = () => [`### ${def.id} · ${title(def)}`, `${t(`scn.status.${r.status}`)} · ${kindTag('auto')} ${r.auto?.[0]}/${r.auto?.[1]} · model ${r.model?.[0]}/${r.model?.[1]} · ${kindTag('manual')} ${r.manual?.[0]}/${r.manual?.[1]} · ${fmtMs(r.ms || 0)}`, '',
    ...(r.detail || []).map((x) => `- [${x.status === 'pass' ? 'x' : ' '}] ${t('scenario.step')} ${x.step} · ${kindTag(x.kind)} · \`${checkLabel(x.label)}\`${x.value ? ` → ${x.value}` : ''} (${x.status})`)].join('\n');
  const count = (k, pair) => (!pair || !pair[1] ? null : h('span', { class: ['rc-count', pair[0] === pair[1] ? 'is-ok' : 'is-bad'] }, h('span', { class: 'muted' }, k), h('b', { class: 'num' }, `${pair[0]}/${pair[1]}`)));
  return h('article', { class: ['result-card', `tone-${st.tone}`], 'data-testid': 'scenario-result' },
    h('div', { class: 'rc-head' }, icon(st.ic, 16), h('h2', { class: 'rc-title' }, `${def.id} · ${t(`scn.status.${r.status}`)}`), h('span', { class: 'muted' }, title(def)), h('span', { class: 'spacer' }),
      btn(t('scn.copyMd'), { size: 'xs', kind: 'ghost', ic: 'copy', onClick: () => copyText(md()).then(() => toast(t('toast.copied'), { tone: 'ok' })) }),
      inStrip ? btn(t('act.close'), { size: 'xs', kind: 'ghost', onClick: () => closeResult() }) : null),
    h('div', { class: 'rc-counts' }, count(kindTag('auto'), r.auto), count('model', r.model), count(kindTag('manual'), r.manual), r.blocked ? h('span', { class: 'muted small' }, t('scn.blockedCount', { n: r.blocked })) : null, h('span', { class: 'muted num' }, fmtMs(r.ms || 0)), r.note ? h('span', { class: 'chip chip-xs tone-warn' }, t(r.note)) : null),
    r.detail ? h('ul', { class: 'rc-list' }, r.detail.map((x) => h('li', { class: `is-${x.status}` }, icon(CHECK_IC[x.status] || 'dot', 12), h('span', { class: 'muted num' }, `${x.step}`), h('span', { class: 'mono' }, checkLabel(x.label)), x.value ? h('span', { class: 'ck-val' }, x.value) : null, h('span', { class: ['ck-kind', `k-${x.kind}`] }, kindTag(x.kind))))) : null,
    inStrip && sc()?.queue?.length ? h('div', { class: 'muted small' }, t('scn.nextInRun', { id: sc().queue[0] })) : null);
}

export function renderScenarios(body) {
  const u = store.ui; const res = u.scenarioResults || {};
  const filt = u.scenarioFilter;
  const list = SCENARIOS.filter((d) => filt === 'all' || (filt === 'failing' && ['failed', 'partial'].includes(res[d.id]?.status)) || (filt === 'key' && d.requires.some((r) => r.startsWith('anahtar'))));
  const counts = { passed: 0, failed: 0, partial: 0, blocked: 0, none: 0 };
  SCENARIOS.forEach((d) => { const s = res[d.id]?.status || 'none'; counts[s] = (counts[s] || 0) + 1; });
  const running = !!sc() && !sc().finished;
  replace(body, scenarioStrip(),
    viewHead(t('scn.title'), 'flask', [
      chip({ label: `${counts.passed} ${t('scn.status.passed')}`, tone: 'ok', ic: 'check' }), chip({ label: `${counts.partial} ${t('scn.status.partial')}`, tone: 'warn', ic: 'alert-triangle' }),
      chip({ label: `${counts.failed} ${t('scn.status.failed')}`, tone: 'danger', ic: 'x' }), chip({ label: `${counts.none} ${t('scn.status.none')}`, tone: 'neutral', ic: 'circle' }),
    ], [
      segmented({ options: [{ value: 'all', label: t('scn.filterAll') }, { value: 'failing', label: t('scn.filterFailing') }, { value: 'key', label: t('scn.filterKey') }], value: filt, onChange: (v) => { u.scenarioFilter = v; refresh('center'); }, aria: t('scn.filter'), size: 'sm' }),
      btn(t('scn.fullRun', { n: fullRunMinutes() }), { size: 'sm', kind: 'primary', ic: 'play', disabled: running, onClick: () => startScenario(FULL_RUN[0], { queue: FULL_RUN.slice(1) }), title: FULL_RUN.join(' → ') }),
    ]),
    h('div', { class: 'view-scroll' },
      h('p', { class: 'legend-line muted small' }, t('scn.legend')),
      list.length ? h('div', { class: 'sc-grid' }, list.map((d) => {
        const r = res[d.id];
        const st = STATUS[r?.status || 'none'];
        return h('article', { class: ['sc-card', `st-${r?.status || 'none'}`], 'data-testid': 'scenario-card' },
          h('div', { class: 'sc-head' }, h('span', { class: 'sc-id mono' }, d.id), h('h3', { class: 'sc-title' }, title(d))),
          h('p', { class: 'sc-goal' }, goal(d)),
          h('div', { class: 'sc-tags' }, d.tags.map((x) => h('span', { class: ['chip', 'chip-xs', `tone-${tagTone(x)}`] }, tagLabel(x))), d.requires.map((x) => h('span', { class: 'chip chip-xs tone-neutral' }, icon(x.startsWith('anahtar') ? 'key' : 'dot', 10), tagLabel(x)))),
          h('div', { class: 'sc-foot' },
            chip({ label: r?.status === 'blocked' && r.note ? `${t('scn.status.blocked')}: ${t(r.note)}` : t(`scn.status.${r?.status || 'none'}`), tone: st.tone, ic: st.ic, title: r?.at ? `${fmtTime(Date.parse(r.at), { seconds: false })}${r.note ? ` · ${t(r.note)}` : ''}` : null }),
            r?.auto ? h('span', { class: 'muted small num' }, `${kindTag('auto')} ${r.auto[0]}/${r.auto[1]}${r.model?.[1] ? ` · model ${r.model[0]}/${r.model[1]}` : ''}`) : null,
            h('span', { class: 'spacer' }), h('span', { class: 'muted small' }, t('scn.meta', { n: d.steps.length, m: d.minutes })),
            btn(t('scn.start'), { size: 'xs', ic: 'play', onClick: () => startScenario(d.id), disabled: running, testid: `scenario-start-${d.id}` })));
      })) : emptyState({ title: t('scn.none'), level: 3 })));
}
