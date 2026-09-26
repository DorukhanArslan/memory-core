// views/live.js: Canlı SDK görevi over the kept /api/live-task/* endpoints (LiveTaskDemo).
// Replies, sentences, the engine and the summary all come from the stream and the state
// payload; the Lab invents no live-task text.
import { h, icon, replace, fmtN, basename } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadLive, providerBody } from '../store.js';
import { api, postStream } from '../api.js';
import { chip, btn, honesty, jsonDisclosure, emptyState, failCard, skeleton, howItWorks } from '../ui/kit.js';
import { toast } from '../ui/overlay.js';
import { viewHead, card } from './heartbeat.js';

// DESIGN §2.9 step order; the state payload carries only the current step (contract gap).
const STEPS = ['verify_identity', 'collect_new_time', 'confirm_change', 'completed'];
let inputEl = null;

function ids() { return { sessionId: store.ui.liveSession, subjectId: store.ui.liveSubject }; }
async function reset() {
  const L = store.data.live;
  try { L.state = await api.post('/api/live-task/reset', ids()); L.turns = []; L.events = []; L.engine = null; L.summary = null; L.summaryDiff = null; L.err = null; }
  catch (err) { toast(err.message, { tone: 'danger' }); L.lastError = err; }
  refresh('center', 'inspector');
  window.dispatchEvent(new CustomEvent('lab:local', { detail: 'live.reset' }));
}
async function summary() {
  const L = store.data.live;
  L.summarizing = true; refresh('center');
  const before = { ...(L.state?.subjectMemoryFiles || {}) };
  try {
    const res = await api.post('/api/live-task/summary', { ...ids(), ...providerBody() });
    L.summary = res.summary || res; L.state = res.state || L.state;
    const after = L.state?.subjectMemoryFiles || {};
    const key = Object.keys(after).find((k) => basename(k) === basename(L.summary?.path || '')) || Object.keys(after).find((k) => after[k] !== before[k]);
    if (key) L.summaryDiff = { path: `subjects/${store.ui.liveSubject}/${key}`, before: before[key] ?? '', after: after[key] };
    toast(L.summary?.wrote ? t('live.summaryWrote') : t('live.summarySkipped', { r: L.summary?.skip_reason || L.summary?.skipReason || '—' }), { tone: L.summary?.wrote ? 'ok' : 'info', action: { label: t('inspector.diff'), onClick: () => store.actions.openInspector('diff') } });
  } catch (err) { L.summary = { error: err.message }; toast(err.message, { tone: 'danger' }); }
  L.summarizing = false;
  refresh('center', 'inspector');
  window.dispatchEvent(new CustomEvent('lab:local', { detail: 'live.summary' }));
}
export async function liveSend(textArg = null) {
  const L = store.data.live; const u = store.ui;
  const text = String(textArg ?? u.liveInput).trim();
  if (!text || L.streaming) return;
  u.liveInput = '';
  const turn = { user: text, sentences: [], text: '', events: [], latency: {}, error: null };
  L.streaming = turn; refresh('center');
  try {
    await postStream('/api/live-task/turn-stream', { message: text, ...ids(), ...providerBody() }, {
      onEvent: ({ event, data }) => {
        if (event === 'live_task_state') { L.state = data; return; }
        if (event === 'error') { turn.error = data.error || data.message || 'error'; return; }
        const ev = { type: data.type || event, text: data.text, data: data.data || {}, elapsed_ms: data.elapsed_ms };
        turn.events.push(ev); L.events.push(ev);
        if (ev.type === 'provider_event' && (ev.data.type === 'llm' || ev.data.provider)) L.engine = { provider: ev.data.provider, model: ev.data.model };
        if (ev.type === 'text_delta') { turn.text += ev.text || ''; if (turn.latency.firstToken === undefined) turn.latency.firstToken = ev.elapsed_ms; }
        if (ev.type === 'sentence') { turn.sentences.push({ text: ev.text, elapsed: ev.elapsed_ms }); if (turn.latency.firstSentence === undefined) turn.latency.firstSentence = ev.elapsed_ms; }
        if (ev.type === 'live_turn_completed') turn.latency.total = ev.elapsed_ms;
        if (ev.type === 'live_turn_failed') turn.error = ev.data.error || ev.data.error_type || 'live_turn_failed';
        refresh('center');
      },
    });
  } catch (err) { turn.error = err.message; }
  turn.step = L.state?.workflow?.current_step;
  L.turns.push(turn); L.streaming = null;
  refresh('center', 'inspector');
  requestAnimationFrame(() => inputEl?.focus());
}

function liveTurn(tr, streaming = false) {
  return h('article', { class: ['lturn', streaming ? 'is-streaming' : ''], 'data-testid': 'live-turn' },
    h('div', { class: 'msg msg-user' }, h('span', { class: 'role' }, t('live.customer')), h('div', { class: 'msg-text' }, tr.user)),
    h('div', { class: 'lsentences' }, tr.sentences.map((sn) => h('div', { class: 'lsentence', 'data-testid': 'live-sentence' }, h('span', { class: 'chip chip-xs tone-neutral num' }, `+${fmtN(sn.elapsed)} ms`), h('span', null, sn.text))), streaming ? h('span', { class: 'caret', 'aria-hidden': 'true' }) : null),
    tr.error ? h('div', { class: 'error-card is-flat', role: 'alert' }, h('div', { class: 'error-title' }, icon('alert-octagon', 14), t('state.error')), h('div', { class: 'error-msg' }, String(tr.error))) : null,
    tr.latency?.total !== undefined ? h('div', { class: 'latency', 'data-testid': 'latency-strip' },
      h('span', null, t('live.firstToken'), ' ', h('b', { class: 'num' }, `${fmtN(tr.latency.firstToken)} ms`)),
      h('span', null, t('live.firstSentence'), ' ', h('b', { class: 'num' }, `${fmtN(tr.latency.firstSentence)} ms`)),
      h('span', null, t('live.total'), ' ', h('b', { class: 'num' }, `${fmtN(tr.latency.total)} ms`)),
      tr.step ? h('span', { class: 'muted' }, `→ ${tr.step}`) : null) : null);
}

export function renderLive(body) {
  const L = store.data.live; const u = store.ui;
  if (!L.state && !L.err) loadLive();
  const strip = store.actions.scenarioStrip?.() || null;
  const st = L.state;
  const wf = st?.workflow || {};
  const steps = Array.isArray(wf.steps) ? wf.steps : STEPS;
  const idx = steps.indexOf(wf.current_step);
  // The engine of the next turn: the last streamed turn's, else the state's engine {mode, model}
  // (which resolves the .env key only). A page key or "ignore .env key" makes that guess wrong,
  // so the view then waits for the first turn.
  const pageOverride = !!store.keys.chat || !!store.keys.ignoreEnvKey;
  const engine = L.engine || (!pageOverride && st?.engine ? { provider: st.engine.mode === 'scripted' ? 'scripted' : st.engine.mode, model: st.engine.model, fromState: true } : null);
  const scripted = engine?.provider === 'scripted';
  const idInput = (key, label, testid) => h('label', { class: 'mini-field' }, h('span', { class: 'muted' }, label),
    h('input', { class: 'input mono', value: u[key], 'aria-label': label, 'data-testid': testid, onchange: (e) => { u[key] = e.target.value.trim(); } }));
  inputEl = h('input', { class: 'input', placeholder: t('live.placeholder'), 'aria-label': t('live.inputLabel'), value: u.liveInput, 'data-testid': 'live-input', oninput: (e) => { u.liveInput = e.target.value; }, onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); liveSend(); } } });
  const transcript = st?.transcript || [];
  const streamed = L.turns;
  replace(body, strip,
    viewHead(t('live.title'), 'waveform', [
      engine ? (scripted ? chip({ label: `SCRIPTED · ${engine.model || '—'}`, tone: 'warn', ic: 'alert-triangle', title: t('live.scriptedTip'), testid: 'engine-chip' }) : chip({ label: `${t('live.realModel')}: ${engine.model || '—'}`, tone: 'ok', ic: 'check', title: engine.fromState ? t('live.engineFromState') : null, testid: 'engine-chip' })) : st ? chip({ label: t('live.engineUnknown'), tone: 'neutral', ic: 'circle', testid: 'engine-chip' }) : null,
      chip({ label: 'adapter-only · memory_core.live', tone: 'neutral' }),
    ]),
    h('div', { class: 'view-scroll' },
      howItWorks('live'),
      scripted ? h('div', { class: 'honesty tone-warn', role: 'status', 'data-testid': 'scripted-banner' }, icon('alert-triangle', 12), h('span', null, t('live.scriptedBanner'))) : null,
      honesty(t('live.stepMachineNote'), 'info', 'info'),
      h('div', { class: 'live-controls' },
        idInput('liveSession', t('live.session'), 'live-session'), idInput('liveSubject', t('live.subject'), 'live-subject'),
        btn(t('live.reset'), { size: 'sm', ic: 'rotate-ccw', target: 'live-reset', onClick: reset, testid: 'live-reset' }),
        btn(t('live.summary'), { size: 'sm', ic: 'file-text', target: 'live-summary', busy: !!L.summarizing, disabled: !transcript.length && !streamed.length, onClick: summary, testid: 'live-summary' })),
      L.err ? failCard(L.err, { onRetry: () => loadLive() }) : !st ? skeleton(3) : null,
      st ? h('ol', { class: 'live-stepper', 'data-testid': 'live-stepper' }, steps.map((s, i) => {
        const done = i < idx || (wf.current_step === 'completed' && s === 'completed');
        return h('li', { class: ['ls', done ? 'is-done' : '', i === idx ? 'is-current' : ''], 'aria-current': i === idx ? 'step' : null }, h('span', { class: 'ls-dot', 'aria-hidden': 'true' }, done ? icon('check', 10) : String(i + 1)), h('span', { class: 'mono' }, s));
      })) : null,
      st ? h('div', { class: 'live-meta' }, h('span', { class: 'muted' }, 'requested_slot'), h('span', { class: 'mono' }, wf.requested_slot ?? 'null'), wf.business_action ? jsonDisclosure(wf.business_action, { title: 'business_action' }) : h('span', { class: 'muted small' }, 'business_action: null')) : null,
      h('div', { class: 'live-transcript' },
        !streamed.length && !L.streaming && transcript.length ? card(t('live.transcriptTitle'), transcript.map((m) => h('div', { class: 'msg' }, h('span', { class: 'role' }, m.role === 'user' ? t('live.customer') : t('chat.assistant')), h('div', { class: 'msg-text' }, m.content))), { ic: 'message' }) : null,
        !streamed.length && !L.streaming && !transcript.length ? emptyState({ title: t('live.empty'), text: t('live.emptyText'), level: 3 }) : null,
        streamed.map((tr) => liveTurn(tr)), L.streaming ? liveTurn(L.streaming, true) : null),
      L.summary ? card(t('live.summaryTitle'), L.summary.error ? h('div', { class: 'error-msg' }, L.summary.error) : [
        L.summary.wrote ? chip({ label: `${t('live.wroteTo')} ${L.summary.path || ''}`, tone: 'accent', ic: 'plus' }) : chip({ label: `${t('hb.skipped')}: ${L.summary.skip_reason || L.summary.skipReason || '—'}`, tone: 'neutral', ic: 'minus' }),
        L.summary.text ? h('pre', { class: 'ptext' }, L.summary.text) : null,
        jsonDisclosure(L.summary, { title: 'summary' }),
      ], { ic: 'file-text', testid: 'live-summary-card' }) : null,
      h('div', { class: 'live-composer' }, inputEl, btn(L.streaming ? t('live.streaming') : t('composer.send'), { kind: 'primary', size: 'sm', ic: 'send', busy: !!L.streaming, onClick: () => liveSend(), testid: 'live-send' })),
      st?.workspace ? h('div', { class: 'muted small pad' }, t('live.root', { r: st.workspace })) : null));
}
