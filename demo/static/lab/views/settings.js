// views/settings.js: Ayarlar over GET/PUT /api/lab/settings (process memory only, never .env).
// Defaults, flag names and validation come from the backend; keys stay in this tab's memory
// (sessionStorage only when "Bu sekmede hatırla" is on) and travel only in request bodies.
import { h, icon, replace, fmtN, copyText } from '../ui/dom.js';
import { t } from '../i18n/index.js';
import { store, refresh, loadSettings, loadState, loadFiles, loadIndex, setPageKey, setRemember, chatKeyState, refreshAll } from '../store.js';
import { api } from '../api.js';
import { chip, btn, iconBtn, segmented, toggle, failCard, skeleton, honesty } from '../ui/kit.js';
import { toast, confirmDialog } from '../ui/overlay.js';
import { viewHead } from './heartbeat.js';

export async function putSettings(patch, { quiet = false } = {}) {
  try {
    const res = await api.put('/api/lab/settings', patch);
    if (res) store.data.settings = res;
    if (!quiet) toast(t('settings.saved'), { tone: 'ok' });
    await Promise.all([loadState(), loadFiles(), loadIndex()]);
    return res;
  } catch (err) {
    toast(err.missing ? t('state.waitsFor', { m: err.module || err.path }) : `${t('settings.rejected')}: ${err.message}`, { tone: err.missing ? 'info' : 'danger' });
    await loadSettings();
    return null;
  }
}
export async function checkProvider(which) {
  const body = which === 'chat'
    ? { openai: { ...(store.keys.chat ? { apiKey: store.keys.chat } : {}), ...(store.keys.ignoreEnvKey ? { ignoreEnvKey: true } : {}) } }
    : { embedding: { ...(store.keys.embedding ? { apiKey: store.keys.embedding } : {}) } };
  store.data.providerCheck = { ...(store.data.providerCheck || {}), [which]: { loading: true } };
  refresh('center');
  try {
    const res = await api.post('/api/lab/provider/check', body);
    store.data.providerCheck[which] = { res };
    toast(res.ok ? t('settings.checkOk', { ms: fmtN(res.latencyMs) }) : `${t('settings.checkFailed')}: ${res.error || ''}`, { tone: res.ok ? 'ok' : 'danger' });
  } catch (err) {
    store.data.providerCheck[which] = { err };
    toast(err.missing ? t('state.waitsFor', { m: err.module || err.path }) : err.message, { tone: 'danger' });
  }
  loadIndex();
  refresh('center', 'top');
}
export function confirmReset(mode) {
  const fresh = mode === 'fresh';
  confirmDialog({
    title: fresh ? t('settings.freshTitle') : t('settings.seedTitle'),
    lines: fresh ? [t('settings.freshLine1'), t('settings.freshLine2'), t('settings.freshLine3')] : [t('settings.seedLine1'), t('settings.seedLine2')],
    confirmLabel: fresh ? t('settings.freshConfirm') : t('settings.seedConfirm'),
    onConfirm: () => resetWorkspace(mode),
  });
}
export async function resetWorkspace(mode) {
  try {
    await api.post('/api/lab/workspace/reset', { mode, keepMemory: !!store.ui.keepMemory });
    const u = store.ui; const d = store.data;
    Object.assign(u, { openTabs: [], drafts: {}, draftBase: {}, editing: {}, centerTab: 'view', pinnedTurn: null, follow: true });
    d.turns = []; d.details.clear(); d.detailErr.clear(); d.fileCache.clear(); d.changed.clear(); d.localTurns = []; d.localRows = [];
    await refreshAll();
    toast(mode === 'fresh' ? t('toast.fresh') : t('toast.seeded'), { tone: 'info' });
    return true;
  } catch (err) {
    toast(err.missing ? t('state.waitsFor', { m: err.module || err.path }) : err.message, { tone: 'danger' });
    return false;
  }
}

function group(id, title, rows, { note = null, ic = 'sliders', tag = null } = {}) {
  return h('section', { class: 'sgroup', id: `settings-${id}`, 'data-testid': `settings-${id}`, 'aria-labelledby': `sg-${id}` },
    h('div', { class: 'sgroup-head' }, icon(ic, 14), h('h3', { class: 'sgroup-title', id: `sg-${id}` }, title), tag), h('div', { class: 'sgroup-body' }, rows), note ? h('div', { class: 'sgroup-note muted' }, note) : null);
}
function row(label, control, help = null, { forId = null } = {}) {
  return h('div', { class: 'srow' }, forId ? h('label', { class: 'srow-label', for: forId }, label) : h('span', { class: 'srow-label' }, label), h('div', { class: 'srow-control' }, control, help ? h('div', { class: 'srow-help muted' }, help) : null));
}
function textInput(id, value, onCommit, { placeholder = '', type = 'text' } = {}) {
  return h('input', { id, class: 'input mono', type, value: value ?? '', placeholder, autocomplete: 'off', spellcheck: 'false', onchange: (e) => onCommit(e.target.value.trim()) });
}
function numberInput(id, value, onCommit, { step = 1 } = {}) {
  return h('input', { id, class: 'input input-num mono', type: 'number', value: value === null || value === undefined ? '' : String(value), step: String(step), onchange: (e) => onCommit(e.target.value === '' ? null : Number(e.target.value)) });
}
function keyField(id, which) {
  const has = !!store.keys[which];
  const input = h('input', { id, class: 'input mono', type: 'password', placeholder: has ? t('settings.keyIsSet') : t('settings.apiKey'), autocomplete: 'off', spellcheck: 'false', 'data-testid': `settings-key-${which}`, value: '',
    onchange: (e) => { const v = e.target.value.trim(); if (!v) return; setPageKey(which, v); e.target.value = ''; refresh('top', 'center'); toast(t('settings.keySet'), { tone: 'info' }); } });
  const reveal = iconBtn('eye', t('settings.reveal'), () => { input.type = input.type === 'password' ? 'text' : 'password'; }, { size: 'sm' });
  const clearBtn = has ? btn(t('settings.keyClear'), { size: 'xs', kind: 'ghost', onClick: () => { setPageKey(which, ''); refresh('top', 'center'); toast(t('settings.keyCleared'), { tone: 'info' }); } }) : null;
  const s = store.data.settings;
  const src = which === 'chat' ? chatKeyState() : (store.keys.embedding ? 'page' : s?.embedding?.keySource === 'env' ? 'env' : 'none');
  const label = src === 'page' ? t('settings.keyPage') : src === 'env' ? `.env (${which === 'chat' ? 'MEMORY_CORE_DEMO_OPENAI_API_KEY' : 'MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY'})` : t('settings.keyNone');
  return h('div', { class: 'keyfield' }, input, reveal, clearBtn, h('span', { id: `${id}-src`, class: ['chip', 'chip-xs', src === 'none' ? 'tone-neutral' : 'tone-ok'], 'data-testid': `key-source-${which}` }, icon('key', 10), label));
}
function checkLine(which) {
  const pc = store.data.providerCheck?.[which];
  return h('span', { class: 'inline-group' },
    btn(t('settings.check'), { size: 'sm', ic: 'play', busy: !!pc?.loading, onClick: () => checkProvider(which), testid: `settings-check-${which}` }),
    h('span', { class: 'muted small' }, which === 'chat' ? t('settings.checkChatNote') : t('settings.checkEmbNote')),
    pc?.res ? chip({ label: pc.res.ok ? `${t('settings.checkOkShort')} · ${fmtN(pc.res.latencyMs)} ms` : t('settings.unreachable'), tone: pc.res.ok ? 'ok' : 'danger', ic: pc.res.ok ? 'check' : 'alert-octagon', title: pc.res.error || pc.res.model || '' }) : null,
    pc?.err ? chip({ label: pc.err.missing ? t('state.notYet') : t('settings.unreachable'), tone: pc.err.missing ? 'neutral' : 'danger', title: pc.err.message }) : null);
}

export function renderSettings(body) {
  const d = store.data; const u = store.ui; const s = d.settings;
  const strip = store.actions.scenarioStrip?.() || null;
  const appearance = group('appearance', t('settings.appearance'), [
    row(t('settings.language'), segmented({ options: [{ value: 'tr', label: 'Türkçe' }, { value: 'en', label: 'English' }], value: u.lang, onChange: (v) => store.actions.setLang(v), aria: t('settings.language'), size: 'sm' })),
    row(t('settings.theme'), segmented({ options: [{ value: 'dark', label: t('settings.dark') }, { value: 'light', label: t('settings.light') }, { value: 'system', label: t('settings.system') }], value: u.theme, onChange: (v) => store.actions.setTheme(v), aria: t('settings.theme'), size: 'sm' })),
    row(t('settings.motion'), segmented({ options: [{ value: 'system', label: t('settings.system') }, { value: 'reduced', label: t('settings.reduced') }], value: u.motion, onChange: (v) => store.actions.setMotion(v), aria: t('settings.motion'), size: 'sm' })),
    row(t('settings.density'), segmented({ options: [{ value: 'compact', label: t('settings.compact') }, { value: 'comfortable', label: t('settings.comfortable') }], value: u.density, onChange: (v) => store.actions.setDensity(v), aria: t('settings.density'), size: 'sm' }), t('settings.densityHelp')),
    row(t('settings.singleKeys'), toggle({ checked: u.singleKeys, onChange: (v) => store.actions.setSingleKeys(v), label: t('settings.singleKeysLabel'), testid: 'settings-single-keys' }), t('settings.singleKeysHelp')),
  ], { ic: 'sun' });
  if (!s) {
    replace(body, strip, viewHead(t('view.settings'), 'sliders'), h('div', { class: 'view-scroll settings' }, d.settingsErr ? failCard(d.settingsErr, { onRetry: () => loadSettings() }) : skeleton(6), appearance));
    return;
  }
  const flags = Object.entries(s.flags || {});
  const curationFlags = flags.filter(([k]) => /curat/i.test(k));
  const otherFlags = flags.filter(([k]) => !/curat/i.test(k));
  const flagRow = ([k, f]) => row(f.label || k, toggle({ checked: !!f.on, onChange: (v) => putSettings({ flags: { [k]: { on: v } } }), label: k, testid: `settings-flag-${k}` }), f.extension ? t('settings.extensionFlag') : null);
  const bud = s.budgets || {};
  const defaults = bud.defaults || bud.upstreamDefaults || null;
  const budTag = defaults ? (defaults.maxChars !== bud.maxChars || defaults.totalMaxChars !== bud.totalMaxChars ? chip({ label: t('settings.testValue'), tone: 'warn', cls: 'chip-xs' }) : chip({ label: t('settings.upstreamDefault', { a: fmtN(defaults.maxChars), b: fmtN(defaults.totalMaxChars) }), tone: 'neutral', cls: 'chip-xs' })) : null;
  const fl = d.snap?.flush;
  const root = d.snap?.workspace?.root;
  replace(body, strip,
    viewHead(t('view.settings'), 'sliders', [chip({ label: t('settings.processOnly'), tone: 'neutral', ic: 'info' })]),
    h('div', { class: 'view-scroll settings' },
      group('chat', t('settings.provider'), [
        row(t('settings.baseUrl'), textInput('set-chat-url', s.chat?.baseUrl, (v) => putSettings({ chat: { baseUrl: v } })), t('settings.baseUrlHelp'), { forId: 'set-chat-url' }),
        row(t('settings.model'), textInput('set-chat-model', s.chat?.model, (v) => putSettings({ chat: { model: v } })), null, { forId: 'set-chat-model' }),
        row(t('settings.apiKey'), keyField('set-chat-key', 'chat'), t('settings.keyHelp'), { forId: 'set-chat-key' }),
        row(t('settings.remember'), toggle({ checked: store.keys.remember, onChange: (v) => { setRemember(v); refresh('center'); }, label: 'sessionStorage', hint: t('settings.rememberHint') })),
        row(t('settings.serverKey'), toggle({ checked: store.keys.ignoreEnvKey, onChange: (v) => { store.keys.ignoreEnvKey = v; refresh('center', 'top'); }, label: t('settings.ignoreEnvKey'), testid: 'settings-ignore-env' })),
        row('', checkLine('chat')),
      ], { ic: 'key' }),
      group('embedding', 'Embedding', [
        row(t('settings.baseUrl'), textInput('set-emb-url', s.embedding?.baseUrl, (v) => putSettings({ embedding: { baseUrl: v || null } })), null, { forId: 'set-emb-url' }),
        row(t('settings.model'), textInput('set-emb-model', s.embedding?.model, (v) => putSettings({ embedding: { model: v || null } })), null, { forId: 'set-emb-model' }),
        row(t('settings.apiKey'), keyField('set-emb-key', 'embedding'), null, { forId: 'set-emb-key' }),
        row(t('settings.result'), h('span', { class: 'inline-group' }, s.embedding?.mode === 'fts-only' ? chip({ label: `${t('search.ftsOnly')}${s.embedding.reason ? `: ${s.embedding.reason}` : ''}`, tone: 'warn', ic: 'alert-triangle' }) : chip({ label: `${t('search.hybrid')} · ${s.embedding?.model || '—'}`, tone: 'info', ic: 'layers' })), t('settings.noFakeEmbeddings')),
        row('', checkLine('embedding')),
      ], { ic: 'layers' }),
      group('layout', t('settings.layout'), [
        row(t('settings.layout'), segmented({ options: [{ value: 'memory-core', label: 'MEMORY-CORE' }, { value: 'pin', label: t('settings.layoutPin') }], value: s.layout, onChange: (v) => putSettings({ layout: v }), aria: t('settings.layout'), size: 'sm', testid: 'settings-layout-seg' }), t('settings.layoutHelp')),
      ], { ic: 'layers' }),
      group('budget', t('settings.budget'), [
        row(t('settings.perFile'), numberInput('set-max', bud.maxChars, (v) => putSettings({ budgets: { maxChars: v } }), { step: 1000 }), null, { forId: 'set-max' }),
        row(t('settings.total'), numberInput('set-total', bud.totalMaxChars, (v) => putSettings({ budgets: { totalMaxChars: v } }), { step: 1000 }), null, { forId: 'set-total' }),
        row(t('settings.warnMode'), segmented({ options: ['off', 'once', 'always'].map((x) => ({ value: x, label: x })), value: bud.warningMode, onChange: (v) => putSettings({ budgets: { warningMode: v } }), aria: t('settings.warnMode'), size: 'sm' })),
      ], { ic: 'scissors', tag: budTag }),
      group('injection', t('settings.injection'), [
        row('contextInjection', segmented({ options: ['always', 'continuation-skip', 'never'].map((x) => ({ value: x, label: x })), value: s.contextInjection, onChange: (v) => putSettings({ contextInjection: v }), aria: 'contextInjection', size: 'sm' })),
      ], { ic: 'prompt' }),
      group('flush', 'Flush', [
        row(t('flush.mode'), segmented({ options: [{ value: 'threshold', label: t('settings.flushThreshold') }, { value: 'per_turn', label: t('settings.flushPerTurn') }], value: s.flush?.mode, onChange: (v) => putSettings({ flush: { mode: v } }), aria: t('flush.mode'), size: 'sm' }), t('settings.flushHelp')),
        row(t('settings.contextWindow'), h('span', { class: 'inline-group' }, numberInput('set-window', s.flush?.contextWindowTokens, (v) => putSettings({ flush: { contextWindowTokens: v } }), { step: 500 }),
          fl?.threshold !== undefined ? h('span', { class: 'muted mono small' }, `→ ${t('flush.threshold')} ${fl.threshold === null ? '—' : fmtN(fl.threshold)} token`) : null), t('settings.contextWindowHelp'), { forId: 'set-window' }),
      ], { ic: 'minus' }),
      group('heartbeat', 'Heartbeat', [
        row('every', textInput('set-hb-every', s.heartbeat?.every, (v) => putSettings({ heartbeat: { every: v } })), null, { forId: 'set-hb-every' }),
        row('ackMaxChars', numberInput('set-hb-ack', s.heartbeat?.ackMaxChars, (v) => putSettings({ heartbeat: { ackMaxChars: v } })), null, { forId: 'set-hb-ack' }),
        row('lightContext', toggle({ checked: !!s.heartbeat?.lightContext, onChange: (v) => putSettings({ heartbeat: { lightContext: v } }), label: t('settings.lightContext') })),
      ], { ic: 'heart-pulse' }),
      curationFlags.length ? group('curation', t('settings.curation'), curationFlags.map(flagRow), { ic: 'puzzle', tag: chip({ label: t('badge.extension'), tone: 'ext', ic: 'puzzle', cls: 'chip-xs' }) }) : group('curation', t('settings.curation'), [h('div', { class: 'srow' }, h('span', { class: 'muted' }, t('settings.noCurationFlags')))], { ic: 'puzzle' }),
      otherFlags.length ? group('editing', t('settings.flags'), otherFlags.map(flagRow), { ic: 'pencil' }) : null,
      group('workspace', t('settings.workspace'), [
        row(t('settings.path'), h('span', { class: 'inline-group' }, h('code', { class: 'mono path-code' }, root || '—'), root ? iconBtn('copy', t('act.copy'), () => copyText(root).then(() => toast(t('toast.pathCopied'), { tone: 'ok' })), { size: 'sm' }) : null)),
        row('', h('div', { class: 'btn-row' },
          btn(t('act.seedReset'), { size: 'sm', kind: 'danger', ic: 'rotate-ccw', onClick: () => confirmReset('seeded'), testid: 'settings-seed' }),
          btn(t('act.freshWorkspace'), { size: 'sm', kind: 'danger', ic: 'plus', onClick: () => confirmReset('fresh'), testid: 'settings-fresh' }),
          toggle({ checked: !!u.keepMemory, onChange: (v) => { u.keepMemory = v; refresh('center'); }, label: t('settings.keepMemory') }))),
      ], { ic: 'folder' }),
      appearance,
      group('tz', t('settings.timezone'), [row('timezone', h('code', { class: 'mono' }, s.timezone || 'Europe/Istanbul'), t('settings.readOnly'))], { ic: 'clock' }),
      honesty(t('settings.noEnvWrite'), 'neutral', 'info')));
}
