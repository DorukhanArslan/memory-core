// scenarios/checks.js: the scenario check DSL (DESIGN §3.0). Every check is a pure function of
// a context the runner assembles from real API payloads (diffs, files, prompt views, turn
// details, search, heartbeat, consolidation, live-task state and LabEvents). No key patterns,
// no dates, no line numbers are hardcoded; step-captured references resolve at run time.
import { parseUnified, sourceNames } from '../ui/diff.js';
import { splitFileSections } from '../inspector/common.js';

/* ---------- check constructors ---------- */
export const auto = (label, fn, needs = [], o = {}) => ({ kind: 'auto', label, fn, needs, ...o });
export const model = (label, fn, needs = [], o = {}) => ({ kind: 'model', label, fn, needs, ...o });
export const manual = (label, o = {}) => ({ kind: 'manual', label, needs: [], ...o });
export const observe = (label, fn, needs = [], o = {}) => ({ kind: 'observe', label, fn, needs, ...o });

/* ---------- path specs ---------- */
/** `daily()` is today's canonical daily file, with the date taken from the server (Europe/Istanbul). */
export const daily = () => (ctx) => `memory/${ctx.today}.md`;
const resolve = (spec, ctx) => (typeof spec === 'function' ? spec(ctx) : spec);
const resolveAll = (specs, ctx) => specs.map((s) => resolve(s, ctx)).flat().filter(Boolean);
/** Path of the first file added in an earlier step (1-based step number) matching `re`. */
export const pathAt = (step, re = /.*/) => (ctx) => (ctx.captured[step - 1]?.diff || []).find((d) => d.status === 'added' && re.test(d.path))?.path || null;
/** Paths changed (not deleted) in an earlier step. */
export const changedAt = (step) => (ctx) => (ctx.captured[step - 1]?.diff || []).filter((d) => d.status !== 'deleted').map((d) => d.path);
/** Lines added to `path` in an earlier step (from that step's server diff). */
export const addedAt = (step, path) => (ctx) => {
  const p = resolve(path, ctx);
  const d = (ctx.captured[step - 1]?.diff || []).find((x) => x.path === p);
  return d ? parseUnified(d.diff).flatMap((hk) => hk.lines.filter((l) => l.t === '+' && l.text.trim()).map((l) => l.text)) : [];
};

/* ---------- helpers ---------- */
const diffFor = (ctx, p) => (ctx.diff || []).find((d) => d.path === p);
function sectionText(pv, section) {
  if (!pv) return '';
  if (section === 'stable') return pv.stableText || '';
  if (section === 'bootstrap') return pv.bootstrapText || '';
  if (section === 'startup') return pv.startup?.text || '';
  if (section === 'flush') return `${pv.flush?.prompt || ''}\n${pv.flush?.target || ''}`;
  if (section === 'wsfiles') return pv.workspaceFilesText || '';
  return '';
}
const fileNames = (pv) => (pv?.files || []).map((f) => f.name);
const test = (re, s) => (re instanceof RegExp ? re.test(s) : String(s).includes(String(re)));

/* ---------- files and diffs (step window = since the step's diff mark) ---------- */
export const fileChanged = (spec, { source = null } = {}) => (ctx) => { const p = resolve(spec, ctx); const d = diffFor(ctx, p); return !!d && d.status !== 'deleted' && (!source || sourceNames(d).includes(source)); };
export const anyFileChanged = (specs, o = {}) => (ctx) => resolveAll(specs, ctx).some((p) => fileChanged(p, o)(ctx));
export const fileUnchanged = (specs, { source = null } = {}) => (ctx) => { const ps = resolveAll(specs, ctx); return !(ctx.diff || []).some((d) => ps.includes(d.path) && (!source || sourceNames(d).includes(source))); };
export const onlyFileBySource = (spec, source) => (ctx) => { const p = resolve(spec, ctx); const list = (ctx.diff || []).filter((d) => sourceNames(d).includes(source)); return list.length === 1 && list[0].path === p; };
export const fileAdded = (re) => (ctx) => (ctx.diff || []).some((d) => d.status === 'added' && re.test(d.path));
export const noFileAdded = (except = []) => (ctx) => { const ok = resolveAll(except, ctx); return !(ctx.diff || []).some((d) => d.status === 'added' && !ok.includes(d.path)); };
export const fileDeleted = (path, { source = null } = {}) => (ctx) => (ctx.diff || []).some((d) => d.path === path && d.status === 'deleted' && (!source || sourceNames(d).includes(source)));
export const fileMatches = (spec, re) => (ctx) => { const p = resolve(spec, ctx); return !!p && test(re, ctx.fileText[p] ?? ''); };
/** Append-only: the step's diff for the file removes nothing and adds only after the existing lines. */
export const appendOnly = (spec) => (ctx) => {
  const d = diffFor(ctx, resolve(spec, ctx)); if (!d) return false;
  if ((d.removed ?? 0) > 0) return false;
  return parseUnified(d.diff).every((hk) => { let seenAdd = false; for (const l of hk.lines) { if (l.t === '-') return false; if (l.t === '+') seenAdd = true; else if (seenAdd && l.text.trim()) return false; } return true; });
};

/* ---------- prompts ---------- */
export const promptHas = (kind, section, re) => (ctx) => test(re, sectionText(ctx.prompts[kind], section));
export const promptLacks = (kind, section, re) => (ctx) => !!ctx.prompts[kind] && !test(re, sectionText(ctx.prompts[kind], section));
export const promptFiles = (op, names, kind = 'main') => (ctx) => {
  const pv = ctx.prompts[kind]; if (!pv) return false;
  const f = fileNames(pv); const want = typeof names === 'function' ? names(ctx) : names;
  if (op === 'equals') return f.length === want.length && want.every((n) => f.includes(n));
  if (op === 'includes') return want.every((n) => f.includes(n));
  return want.every((n) => !f.includes(n));
};
export const promptOrder = (names, kind = 'main') => (ctx) => { const f = fileNames(ctx.prompts[kind]); const idx = names.map((n) => f.indexOf(n)); return idx.every((x, i) => x >= 0 && (i === 0 || x > idx[i - 1])); };
export const injectedChars = (name, op, n, kind = 'main') => (ctx) => { const f = (ctx.prompts[kind]?.files || []).find((x) => x.name === name); if (!f) return false; return op === '<=' ? f.chars <= n : f.chars >= n; };
export const truncated = (name, kind = 'main') => (ctx) => !!(ctx.prompts[kind]?.files || []).find((x) => x.name === name)?.truncated;
export const noTruncation = (kind = 'main') => (ctx) => !!ctx.prompts[kind] && !(ctx.prompts[kind].files || []).some((f) => f.truncated);
/** Head share of a truncated file, read from its `…(truncated NAME: kept H+T chars of N)…` marker. */
export const headRatio = (name, ratio, tol, kind = 'main') => (ctx) => {
  const pv = ctx.prompts[kind]; if (!pv) return false;
  const block = splitFileSections(pv.stableText, pv.files).files.find((x) => x.file.name === name)?.text || '';
  const m = /…\(truncated [^:]+: kept (\d+)\+(\d+) chars of \d+\)…/.exec(block);
  if (!m) return false;
  const hd = Number(m[1]); const tl = Number(m[2]);
  return Math.abs(hd / (hd + tl) - ratio) <= tol;
};
export const warningLine = (re, kind = 'main') => (ctx) => (ctx.prompts[kind]?.truncationWarningLines || []).some((l) => re.test(l)) || (ctx.prompts[kind]?.warnings || []).some((l) => re.test(l));
export const totalInjectedAtMost = (n, kind = 'main') => (ctx) => !!ctx.prompts[kind] && (ctx.prompts[kind].files || []).reduce((a, f) => a + (f.chars || 0), 0) <= n;
export const excludedFor = (re, kind = 'main') => (ctx) => (ctx.prompts[kind]?.excluded || []).some((e) => re.test(e.reason || ''));
export const bootstrapMode = (kind = 'main') => (ctx) => ctx.prompts[kind]?.bootstrapMode || '—';
/** "includes BOOTSTRAP.md" only holds in full mode; the check reports the mode otherwise. */
export const bootstrapInContextIfFull = (kind = 'main') => (ctx) => { const pv = ctx.prompts[kind]; if (!pv) return false; return pv.bootstrapMode !== 'full' || fileNames(pv).includes('BOOTSTRAP.md'); };

/* ---------- the turn of this step (stored TurnDetail) ---------- */
export const turnPromptHas = (section, re) => (ctx) => { const pv = ctx.turn?.prompt; if (!pv) return false; const want = typeof re === 'function' ? re(ctx) : re; return Array.isArray(want) ? want.length > 0 && want.every((line) => sectionText(pv, section).includes(line)) : test(want, sectionText(pv, section)); };
export const turnPromptLacks = (section, re) => (ctx) => !!ctx.turn?.prompt && !test(re, sectionText(ctx.turn.prompt, section));
export const turnPromptFilesExclude = (names) => (ctx) => !!ctx.turn?.prompt && !fileNames(ctx.turn.prompt).some((n) => names.includes(n));
export const turnKind = (kind) => (ctx) => (ctx.turn?.sessionKind || ctx.turn?.prompt?.sessionKind) === kind;
export const promptDiffOnly = (names) => (ctx) => {
  const a = ctx.prevTurn?.prompt; const b = ctx.turn?.prompt; if (!a || !b) return false;
  const blocks = (pv) => new Map(splitFileSections(pv.stableText, pv.files).files.map((x) => [x.file.name, x.text]));
  const A = blocks(a); const B = blocks(b);
  const changed = [...new Set([...A.keys(), ...B.keys()])].filter((n) => A.get(n) !== B.get(n));
  return changed.length === names.length && names.every((n) => changed.includes(n));
};
export const recallUsedAtLeast = (n) => (ctx) => (ctx.turn?.recall?.used || []).length >= n;
export const recallUsedIncludes = (specs) => (ctx) => { const ps = resolveAll([specs], ctx); const used = ctx.turn?.recall?.used || []; return ps.length > 0 && ps.some((p) => used.some((u) => u === p || String(u).startsWith(`${p}#`) || String(u).includes(`${p}#`))); };
export const assistantMatches = (re) => (ctx) => re.test(ctx.turn?.assistant || '');
export const flushTarget = (re) => (ctx) => re.test(ctx.turn?.flush?.run?.target || ctx.turn?.prompt?.flush?.target || '');
export const flushReasonIn = (reasons) => (ctx) => reasons.includes(ctx.turn?.flush?.decision?.reason) || (ctx.events || []).some((e) => e.type === 'flush.decided' && reasons.includes(e.data?.reason));

/* ---------- startup context (from the /api/lab/session/new answer of this step) ---------- */
export const startupLoaded = () => (ctx) => !!ctx.sessionNew?.startup;
export const startupAbsent = () => (ctx) => !!ctx.sessionNew && !ctx.sessionNew.startup;
export const startupHas = (re) => (ctx) => re.test(ctx.sessionNew?.startup?.text || '');
/** The 2.800-char cap covers the daily-memory blocks only, so the prelude is not counted. */
export const startupDailyAtMost = (n) => (ctx) => { const text = ctx.sessionNew?.startup?.text || ''; const i = text.indexOf('[Untrusted daily memory:'); return i >= 0 && text.slice(i).length <= n; };

/* ---------- bootstrap, files, chips ---------- */
export const bootstrapStatus = (v) => (ctx) => ctx.snap?.bootstrap?.status === v;
export const badge = (file, b) => (ctx) => !!(ctx.files || []).find((e) => e.path === file)?.badges?.includes(b);
export const noBadge = (b) => (ctx) => !!ctx.files && !ctx.files.some((e) => (e.badges || []).includes(b));
export const fileAbsent = (path) => (ctx) => !!ctx.files && !ctx.files.some((e) => e.path === path && e.exists !== false);

/* ---------- events (step window) ---------- */
export const event = (type, pred = null) => (ctx) => (ctx.events || []).some((e) => e.type === type && (!pred || pred(e.data || {})));
export const noEvent = (type) => (ctx) => !(ctx.events || []).some((e) => e.type === type);
export const eventOrder = (types) => (ctx) => { let i = 0; for (const e of ctx.events || []) if (e.type === types[i]) i++; return i === types.length; };

/* ---------- search (the Deneme alanı result of this step) ---------- */
const rows = (ctx) => ctx.search?.results || [];
export const searchTop = (spec, rank = 1) => (ctx) => rows(ctx)[rank - 1]?.path === resolve(spec, ctx);
/** memory_search citations read `Source: path#Lx` or `Source: path#Lx-Ly` (memory_core/tools/citations.py). */
export const citationsFormat = () => (ctx) => rows(ctx).length > 0 && rows(ctx).every((r) => /^Source: \S+#L\d+(?:-L\d+)?$/.test(r.citation || ''));
/** The vector leg is off: every row has no vector score, or the payload itself reports provider none / fts-only. */
export const allVectorOff = () => (ctx) => rows(ctx).length > 0 && (ctx.search.provider === 'none' || ctx.search.model === 'fts-only' || ctx.search.embeddings?.mode === 'fts-only' || rows(ctx).every((r) => r.vectorScore === null || r.vectorScore === undefined));
export const hybridScores = (wv, wt, tol) => (ctx) => rows(ctx).length > 0 && rows(ctx).every((r) => typeof r.vectorScore === 'number' && typeof r.textScore === 'number' && Math.abs(r.score - (wv * r.vectorScore + wt * r.textScore)) <= tol);
export const allScoresAtLeast = (x) => (ctx) => !!ctx.search && !ctx.search.error && rows(ctx).every((r) => r.score >= x);
export const rowsAtMost = (n) => (ctx) => !!ctx.search && !ctx.search.error && rows(ctx).length <= n;
export const searchError = (re) => (ctx) => re.test(String(ctx.search?.error || ''));
export const searchUnavailable = () => (ctx) => !!ctx.search && (ctx.search.unavailable === true || (!!ctx.search.warning && !!ctx.search.action));
export const cooldownActive = () => (ctx) => !!ctx.index?.cooldown && (ctx.index.cooldown.until ?? 0) > ctx.now;

/* ---------- heartbeat ---------- */
export const hbTask = (name, pred = null) => (ctx) => (ctx.heartbeat?.tasks || []).some((x) => x.name === name && (!pred || pred(x)));
export const hbDelivered = (v) => (ctx) => ctx.hbRun?.decision?.delivered === v;
export const hbSkipped = (reason) => (ctx) => ctx.hbRun?.skipped === reason;
export const hbUserHas = (re) => (ctx) => re.test(ctx.hbRun?.userMessage || '');
export const hbUserLacks = (re) => (ctx) => !!ctx.hbRun && !re.test(ctx.hbRun.userMessage || '');
export const hbReplyMatches = (re) => (ctx) => re.test(ctx.hbRun?.reply || '');
export const hbReplyLacks = (re) => (ctx) => !!ctx.hbRun && !re.test(ctx.hbRun.reply || '');
export const stripSequence = (inputs, expected) => (ctx) => inputs.map((x) => (ctx.strip[x]?.shouldSkip ? 'skip' : ctx.strip[x] ? 'deliver' : '?')).join(',') === expected.join(',');

/* ---------- consolidation ---------- */
export const candidate = (pred) => (ctx) => (ctx.consolidation?.candidates || []).some((c) => pred(c, ctx));
export const candidateGatesConsistent = () => (ctx) => { const cs = ctx.consolidation?.candidates || []; return cs.length > 0 && cs.every((c) => !c.selected || (c.gates?.score && c.gates?.recall && c.gates?.unique)); };
export const auditClean = () => (ctx) => (ctx.events || []).some((e) => e.type === 'audit.completed' && ((e.data?.issues ?? []).length === 0 || e.data?.issues === 0)) || (ctx.consolidation?.audit ? (ctx.consolidation.audit.issues || []).length === 0 : false);

/* ---------- live task ---------- */
export const liveStep = (s) => (ctx) => ctx.live?.state?.workflow?.current_step === s;
export const liveOrder = (types) => (ctx) => { let i = 0; for (const e of ctx.live?.events || []) if (e.type === types[i]) i++; return i === types.length; };
export const businessAction = (type) => (ctx) => ctx.live?.state?.workflow?.business_action?.type === type;
export const liveSummaryWrote = () => (ctx) => ctx.live?.summary?.wrote === true;
/** The identity proof given in an earlier step must not appear in the subject daily file. */
export const proofAbsentFromSummary = (step) => (ctx) => {
  const proof = (ctx.captured[step - 1]?.sent || '').trim();
  if (!proof) return false;
  const digits = proof.match(/\d[\d./-]*\d|\d/g) || [];
  const text = Object.values(ctx.live?.state?.subjectMemoryFiles || {}).join('\n');
  return digits.length > 0 && digits.every((dgt) => !text.includes(dgt));
};

/* ---------- provider and errors ---------- */
export const turnErrorCode = (code) => (ctx) => ctx.lastError?.code === code || (ctx.events || []).some((e) => e.type === 'chat.turn.failed' && e.data?.code === code);
export const turnErrorMatches = (re) => (ctx) => re.test(String(ctx.lastError?.error || '')) || (ctx.events || []).some((e) => e.type === 'chat.turn.failed' && re.test(String(e.data?.error || e.data?.message || '')));
/** Redaction is asserted server-side: the failure carries `redacted: true` (critique #5). */
export const errorRedacted = () => (ctx) => ctx.lastError?.redacted === true || (ctx.events || []).some((e) => e.type === 'chat.turn.failed' && e.data?.redacted === true);
/** provider.check bus events carry {target: chat|embedding, ok, latencyMs, error} (demo/lab_settings.py). */
export const providerCheck = (which, ok) => (ctx) => (ctx.events || []).some((e) => e.type === 'provider.check' && e.data?.target === which && !!e.data?.ok === ok);
