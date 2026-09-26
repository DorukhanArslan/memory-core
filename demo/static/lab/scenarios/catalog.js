// scenarios/catalog.js: Test Senaryoları S01-S14 (DESIGN §3 with the critique fixes).
// Messages to send stay Turkish in EN mode (they are test inputs); instructions translate.
// Every scenario builds the state it needs through its own steps: the seed holds only the
// Lab's DEFAULT workspace files, so no check leans on invented seed content.
import {
  auto, model, manual, observe, daily, pathAt, changedAt, addedAt,
  fileChanged, anyFileChanged, fileUnchanged, onlyFileBySource, fileAdded, noFileAdded, fileDeleted, fileMatches, appendOnly,
  promptHas, promptLacks, promptFiles, promptOrder, injectedChars, truncated, noTruncation, headRatio, warningLine, totalInjectedAtMost, excludedFor, bootstrapMode, bootstrapInContextIfFull,
  turnPromptHas, turnPromptLacks, turnPromptFilesExclude, turnKind, promptDiffOnly, recallUsedAtLeast, recallUsedIncludes, assistantMatches, flushTarget, flushReasonIn,
  startupLoaded, startupAbsent, startupHas, startupDailyAtMost,
  bootstrapStatus, badge, fileAbsent, event, noEvent, eventOrder,
  searchTop, citationsFormat, allVectorOff, hybridScores, allScoresAtLeast, rowsAtMost, searchError, searchUnavailable, cooldownActive,
  hbTask, hbDelivered, hbSkipped, hbUserHas, hbUserLacks, hbReplyMatches, hbReplyLacks, stripSequence,
  candidate, candidateGatesConsistent, auditClean,
  liveStep, liveOrder, businessAction, liveSummaryWrote, proofAbsentFromSummary,
  turnErrorCode, turnErrorMatches, errorRedacted, providerCheck,
} from './checks.js';
import { sourceNames } from '../ui/diff.js';

const SESSION_FILE = /^memory\/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$/;
const BOOTSTRAP_FILES = ['AGENTS.md', 'SOUL.md', 'TOOLS.md', 'IDENTITY.md', 'USER.md', 'HEARTBEAT.md', 'PROACTIVE_PREFERENCES.md'];
const TURN = ['turn', 'diff'];
const curationUserFlagOff = (ctx) => {
  const flags = ctx.settings?.flags || {};
  const entry = Object.entries(flags).find(([k]) => /curat/i.test(k) && /user/i.test(k)) || Object.entries(flags).find(([k]) => /curat/i.test(k));
  return entry && entry[1].on === false ? 'scn.blockedUserCuration' : null;
};
const needsKey = (ctx) => (ctx.keyState === 'none' ? 'scn.blockedNoKey' : null);
const needsHybrid = (ctx) => (ctx.settings?.embedding?.mode === 'fts-only' ? 'scn.blockedFtsOnly' : null);
const fileOf = (ctx, path) => (ctx.files || []).find((e) => e.path === path) || null;
// The seed holds no MEMORY.md (docs/lab.md › workspace/reset seeded); a check that needs it is blocked.
const needsMemoryMd = (ctx) => (fileOf(ctx, 'MEMORY.md')?.exists ? null : 'scn.blockedNoMemoryMd');
// An empty PROACTIVE_PREFERENCES.md is excluded in both layouts, so a layout check would prove nothing.
const needsProactive = (ctx) => { const e = fileOf(ctx, 'PROACTIVE_PREFERENCES.md'); return e?.exists && e.chars > 0 && !(e.badges || []).includes('empty') ? null : 'scn.blockedProactiveEmpty'; };

export const SCENARIOS = [
  {
    id: 'S01', minutes: 4, view: 'chat', tags: ['uzantı', 'model'], requires: ['anahtar'],
    blockedIf: (ctx) => needsKey(ctx) || curationUserFlagOff(ctx),
    steps: [
      { act: 'send', text: 'Açıklamaları uzun paragraflarla yap.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S01.e0',
        checks: [auto('fileChanged(USER.md,{source:curation})', fileChanged('USER.md', { source: 'curation' }), TURN)] },
      { act: 'send', text: 'Bundan sonra bana hep kısa ve madde madde cevap ver. Bu kalıcı bir tercih.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S01.e1',
        checks: [
          auto('fileChanged(USER.md,{source:curation})', fileChanged('USER.md', { source: 'curation' }), TURN),
          auto('fileUnchanged([MEMORY.md],{source:curation})', fileUnchanged(['MEMORY.md'], { source: 'curation' }), TURN),
          model('fileMatches(USER.md,/status: superseded/)', fileMatches('USER.md', /status: superseded/), [{ file: 'USER.md' }]),
          model('fileMatches(USER.md,/kısa|madde/i)', fileMatches('USER.md', /kısa|madde/i), [{ file: 'USER.md' }]),
        ] },
      { act: 'send', text: 'Liste ile tuple arasındaki fark ne?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S01.e2',
        checks: [auto('promptHas(stable, added(2,USER.md))', turnPromptHas('stable', addedAt(2, 'USER.md')), TURN), manual('scn.S01.m2')] },
      { act: 'look', tab: 'prompt', compare: true, label: 'scn.S01.l3', expect: 'scn.S01.e3',
        checks: [auto('promptDiffOnly([USER.md])', promptDiffOnly(['USER.md']), ['turn', 'prevTurn'])] },
    ],
  },
  {
    id: 'S02', minutes: 4, view: 'chat', tags: ['uzantı', 'upstream-uyumlu', 'model'], requires: ['anahtar'], blockedIf: needsKey,
    steps: [
      { act: 'send', text: 'Karar: ödeme servisinde PostgreSQL yerine SQLite kullanıyoruz, çünkü servis tek kiracılı. Bunu uzun vadeli belleğe al.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S02.e0',
        checks: [auto('fileChanged(MEMORY.md,{source:curation})', fileChanged('MEMORY.md', { source: 'curation' }), TURN), auto('fileUnchanged([USER.md])', fileUnchanged(['USER.md']), TURN), model('fileMatches(MEMORY.md,/SQLite/)', fileMatches('MEMORY.md', /SQLite/), [{ file: 'MEMORY.md' }])] },
      { act: 'send', text: "Bugün müşteri demosunu 16:00'ya aldık, bunu bugünün notuna yaz.", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S02.e1',
        checks: [auto('fileChanged(daily(bugün))', fileChanged(daily()), TURN), auto('appendOnly(daily(bugün))', appendOnly(daily()), TURN), auto('fileUnchanged([MEMORY.md,USER.md])', fileUnchanged(['MEMORY.md', 'USER.md']), TURN), auto('fileAdded: yalnız daily(bugün)', noFileAdded([daily()]), TURN)] },
      { act: 'look', tab: 'memory', search: { query: 'müşteri demosu', mode: 'text', minScore: 0, maxResults: 5 }, label: 'scn.S02.l2', expect: 'scn.S02.e2',
        checks: [model('searchTop(daily(bugün),1)', searchTop(daily(), 1), ['search']), auto('citationsFormat()', citationsFormat(), ['search'])] },
    ],
  },
  {
    id: 'S03', minutes: 4, view: 'chat', tags: ['upstream-uyumlu', 'D2'], requires: ['anahtar', '≥ 2 tur'], blockedIf: needsKey,
    labels: [{ tone: 'warn', text: 'scn.S03.rawLines' }],
    steps: [
      { act: 'cmd', text: '/new', waitFor: 'session.new|chat.turn.completed|chat.turn.failed', expect: 'scn.S03.e0',
        checks: [
          auto(`fileAdded(${SESSION_FILE.source})`, fileAdded(SESSION_FILE), ['diff']),
          auto('fileMatches(new,/^# Session: /m)', fileMatches(pathAt(1, SESSION_FILE), /^# Session: /m), ['diff', { file: pathAt(1, SESSION_FILE) }]),
          auto('fileMatches(new,/^## Conversation Summary$/m)', fileMatches(pathAt(1, SESSION_FILE), /^## Conversation Summary$/m), ['diff', { file: pathAt(1, SESSION_FILE) }]),
          auto('fileUnchanged([daily(bugün)])', fileUnchanged([daily()]), ['diff']),
          auto('startupLoaded()', startupLoaded(), ['sessionNew']),
          auto('startupHas(/^\\[Startup context loaded by runtime\\]$/m)', startupHas(/^\[Startup context loaded by runtime\]$/m), ['sessionNew']),
          auto('startupHas(/\\[Untrusted daily memory: memory\\/…\\.md\\]/)', startupHas(/\[Untrusted daily memory: memory\/\d{4}-\d{2}-\d{2}\.md\]/), ['sessionNew']),
          auto('startupDailyBlocks ≤ 2800', startupDailyAtMost(2800), ['sessionNew']),
        ] },
      { act: 'send', text: 'Nerede kalmıştık?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S03.e1',
        checks: [auto('promptLacks(startup,/./)', turnPromptLacks('startup', /./), TURN), model('assistantMatches(/16[:.]00/)', assistantMatches(/16[:.]00/), ['turn'])] },
      { act: 'cmd', text: '/new Selam, yeni konu.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S03.e2',
        checks: [auto(`fileAdded(${SESSION_FILE.source})`, fileAdded(SESSION_FILE), ['diff']), auto('startupAbsent()', startupAbsent(), ['sessionNew']), auto('noEvent(startup_context.loaded)', noEvent('startup_context.loaded'))] },
    ],
  },
  {
    id: 'S04', minutes: 4, view: 'chat', tags: ['upstream-uyumlu', 'demo-only', 'model'], requires: ['anahtar'], blockedIf: needsKey,
    steps: [
      { act: 'send', text: "Not al: haftalık sürüm toplantısı her perşembe 10:30'da.", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S04.e0',
        checks: [auto('fileChanged(daily(bugün)) ∨ fileChanged(MEMORY.md)', anyFileChanged([daily(), 'MEMORY.md']), TURN)] },
      { act: 'cmd', text: '/new', waitFor: 'session.new|chat.turn.completed|chat.turn.failed', expect: 'scn.S04.e1', checks: [auto('event(session.new)', event('session.new'))] },
      { act: 'send', text: 'Sürüm toplantısı hangi gün ve saatte?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S04.e2',
        checks: [auto('recall.used ≥ 1', recallUsedAtLeast(1), ['turn']), auto('recallUsedIncludes(changed@1)', recallUsedIncludes(changedAt(1)), ['turn']), model('assistantMatches(/perşembe/i)', assistantMatches(/perşembe/i), ['turn']), model('assistantMatches(/10[:.]30/)', assistantMatches(/10[:.]30/), ['turn'])] },
      { act: 'send', text: 'Release toplantısı ne zaman?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S04.e3', labels: [{ tone: 'warn', text: 'scn.S04.gap' }],
        checks: [observe('recall hits', (ctx) => `recall ${(ctx.turn?.recall?.used || []).length}`, ['turn'])] },
    ],
  },
  {
    id: 'S05', minutes: 3, view: 'chat', tags: ['upstream-uyumlu'], requires: ['embedding (2. adım)'],
    steps: [
      { act: 'look', tab: 'memory', search: { query: 'perşembe toplantı', mode: 'text', maxResults: 5, minScore: 0 }, label: 'scn.S05.l0', expect: 'scn.S05.e0',
        checks: [auto('allRows(vectorScore == null)', allVectorOff(), ['search']), auto('citationsFormat()', citationsFormat(), ['search'])] },
      { act: 'look', tab: 'memory', search: { mode: 'hybrid' }, label: 'scn.S05.l1', expect: 'scn.S05.e1', blockedIf: needsHybrid,
        checks: [auto('hybridScores(0.5,0.5,0.001)', hybridScores(0.5, 0.5, 0.001), ['search'])] },
      { act: 'look', tab: 'memory', search: { minScore: 0.35 }, label: 'scn.S05.l2', expect: 'scn.S05.e2',
        checks: [auto('allScores(≥,0.35)', allScoresAtLeast(0.35), ['search']), auto('rows ≤ maxResults', rowsAtMost(5), ['search'])] },
      { act: 'look', tab: 'memory', search: { query: '' }, label: 'scn.S05.l3', expect: 'scn.S05.e3', checks: [auto('errorShown(/query required/)', searchError(/query required/), ['search'])] },
      { act: 'look', tab: 'memory', search: { query: 'perşembe', maxResults: 0 }, label: 'scn.S05.l4', expect: 'scn.S05.e4', checks: [auto('errorShown(/maxResults must be a positive integer/)', searchError(/maxResults must be a positive integer/), ['search'])] },
    ],
  },
  {
    id: 'S06', minutes: 5, view: 'chat', tags: ['upstream-uyumlu', 'uzantı: Lab düzenleme'], requires: ['taze çalışma alanı', 'anahtar (3. adım)'],
    setup: { reset: 'fresh' },
    steps: [
      { act: 'look', tab: 'prompt', promptKind: 'main', label: 'scn.S06.l0', expect: 'scn.S06.e0',
        checks: [auto('bootstrapStatus(pending)', bootstrapStatus('pending'), ['snap']), auto('promptHas(bootstrap,/^## Bootstrap Pending$/m)', promptHas('main', 'bootstrap', /^## Bootstrap Pending$/m), ['prompt:main']),
          auto('promptFiles(includes,[BOOTSTRAP.md]) · full ise', bootstrapInContextIfFull('main'), ['prompt:main']), observe('bootstrap modu', bootstrapMode('main'), ['prompt:main'])] },
      { act: 'look', tab: 'prompt', promptKind: 'heartbeat', label: 'scn.S06.l1', expect: 'scn.S06.e1',
        checks: [auto('promptFiles(excludes,[BOOTSTRAP.md],{kind:heartbeat})', promptFiles('excludes', ['BOOTSTRAP.md'], 'heartbeat'), ['prompt:heartbeat']), auto('promptFiles(excludes,[BOOTSTRAP.md],{kind:cron})', promptFiles('excludes', ['BOOTSTRAP.md'], 'cron'), ['prompt:cron'])] },
      { act: 'send', text: 'Merhaba', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S06.e2', blockedIf: needsKey, checks: [manual('scn.S06.m2')] },
      { act: 'edit', path: 'IDENTITY.md', from: 'Vibe: pragmatic memory lab assistant', to: 'Vibe: kısa ve net test asistanı', waitFor: 'bootstrap.file_deleted|file.saved', label: 'scn.S06.l3', expect: 'scn.S06.e3',
        checks: [auto('eventOrder([file.saved,bootstrap.completed,bootstrap.file_deleted])', eventOrder(['file.saved', 'bootstrap.completed', 'bootstrap.file_deleted'])), auto('fileDeleted(BOOTSTRAP.md,{source:lifecycle})', fileDeleted('BOOTSTRAP.md', { source: 'lifecycle' }), ['diff']), auto('bootstrapStatus(complete)', bootstrapStatus('complete'), ['snap'])] },
      { act: 'send', text: 'Devam edelim.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S06.e4', blockedIf: needsKey,
        checks: [auto('promptLacks(bootstrap,/Bootstrap Pending/)', turnPromptLacks('bootstrap', /Bootstrap Pending/), ['turn']), auto('promptFiles(excludes,[BOOTSTRAP.md])', turnPromptFilesExclude(['BOOTSTRAP.md']), ['turn'])] },
    ],
  },
  {
    id: 'S07', minutes: 4, view: 'chat', tags: ['upstream-uyumlu', 'demo-only: fikstür'], requires: [], setup: { reset: 'seeded' },
    steps: [
      { act: 'edit', path: 'SOUL.md', fixture: true, waitFor: 'file.saved', label: 'scn.S07.l0', expect: 'scn.S07.e0',
        checks: [auto('badge(SOUL.md,truncated)', badge('SOUL.md', 'truncated'), ['files']), auto('promptHas(stable,/…(truncated SOUL.md: kept H+T chars of N)…/)', promptHas('main', 'stable', /…\(truncated SOUL\.md: kept \d+\+\d+ chars of \d+\)…/), ['prompt:main']),
          auto('injectedChars(SOUL.md,≤,maxChars)', (ctx) => injectedChars('SOUL.md', '<=', ctx.settings?.budgets?.maxChars ?? 0)(ctx), ['prompt:main']), auto('headRatio(SOUL.md,0.75,0.01)', headRatio('SOUL.md', 0.75, 0.01), ['prompt:main']),
          auto('promptHas(bootstrap,/^\\[Bootstrap truncation warning\\]$/m)', promptHas('main', 'bootstrap', /^\[Bootstrap truncation warning\]$/m), ['prompt:main'])] },
      { act: 'edit', path: 'AGENTS.md', fixture: true, waitFor: 'file.saved', label: 'scn.S07.l1', expect: 'scn.S07.e1',
        checks: [auto('promptHas(stable,/^\\[Policy digest from AGENTS\\.md\\]$/m)', promptHas('main', 'stable', /^\[Policy digest from AGENTS\.md\]$/m), ['prompt:main']), auto('warningLine(/AGENTS\\.md was truncated/)', warningLine(/AGENTS\.md was truncated/), ['prompt:main'])] },
      { act: 'setting', apply: { settings: { budgets: { totalMaxChars: 12000 } } }, label: 'scn.S07.l2', expect: 'scn.S07.e2',
        checks: [auto('sum(injectedChars) ≤ 12000', totalInjectedAtMost(12000), ['prompt:main']), auto('excluded: max/total', (ctx) => excludedFor(/total|toplam/i)(ctx) || (ctx.prompts.main?.budget?.files || []).some((f) => (f.causes || []).includes('max/total')), ['prompt:main'])] },
      { act: 'revert', paths: ['SOUL.md', 'AGENTS.md'], restore: ['budgets.totalMaxChars'], label: 'scn.S07.l3', expect: 'scn.S07.e3',
        checks: [auto('noBadge(truncated)', noTruncation('main'), ['prompt:main'])] },
    ],
  },
  {
    id: 'S08', minutes: 4, view: 'chat', tags: ['upstream-uyumlu', 'uzantı: cron PROACTIVE', 'model'], requires: ['düzen MEMORY-CORE'],
    steps: [
      { act: 'look', tab: 'prompt', promptKind: 'main', label: 'scn.S08.l0', expect: 'scn.S08.e0',
        checks: [auto('promptFiles(equals, upstream main set)', promptFiles('equals', (ctx) => {
          const nonEmpty = (n) => (ctx.files || []).some((e) => e.path === n && e.exists !== false && !(e.badges || []).includes('empty'));
          const base = ['AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'TOOLS.md', 'MEMORY.md', 'HEARTBEAT.md'].filter(nonEmpty);
          if (nonEmpty('PROACTIVE_PREFERENCES.md')) base.push('PROACTIVE_PREFERENCES.md');
          if (ctx.snap?.bootstrap?.status === 'pending' && nonEmpty('BOOTSTRAP.md')) base.push('BOOTSTRAP.md');
          return base;
        }, 'main'), ['prompt:main', 'files', 'snap'])] },
      { act: 'look', tab: 'prompt', promptKind: 'subagent', label: 'scn.S08.l1', expect: 'scn.S08.e1',
        checks: [auto('promptFiles(equals,[AGENTS.md,TOOLS.md],{kind:subagent})', promptFiles('equals', ['AGENTS.md', 'TOOLS.md'], 'subagent'), ['prompt:subagent'])] },
      { act: 'look', tab: 'prompt', promptKind: 'cron', label: 'scn.S08.l2', expect: 'scn.S08.e2',
        checks: [auto('promptFiles(excludes,[MEMORY.md,HEARTBEAT.md],{kind:cron})', promptFiles('excludes', ['MEMORY.md', 'HEARTBEAT.md'], 'cron'), ['prompt:cron']), auto('promptFiles(includes,[AGENTS.md,TOOLS.md,SOUL.md,IDENTITY.md,USER.md],{kind:cron})', promptFiles('includes', ['AGENTS.md', 'TOOLS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md'], 'cron'), ['prompt:cron'])] },
      { act: 'look', tab: 'prompt', promptKind: 'group', label: 'scn.S08.l3', expect: 'scn.S08.e3', blockedIf: needsMemoryMd,
        checks: [auto('promptFiles(includes,[MEMORY.md],{kind:group})', promptFiles('includes', ['MEMORY.md'], 'group'), ['prompt:group'])] },
      { act: 'send', kind: 'subagent', text: 'Sana nasıl cevap vermemi istediğimi biliyor musun?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S08.e4', blockedIf: needsKey,
        checks: [auto('turn kind = subagent', turnKind('subagent'), ['turn']), auto('turnPromptFiles(excludes,[USER.md,MEMORY.md])', turnPromptFilesExclude(['USER.md', 'MEMORY.md']), ['turn']), manual('scn.S08.m4')] },
      { act: 'setting', apply: { settings: { layout: 'pin' } }, label: 'scn.S08.l5', expect: 'scn.S08.e5', blockedIf: needsProactive,
        checks: [auto('promptFiles(excludes,[PROACTIVE_PREFERENCES.md],{layout:pin})', promptFiles('excludes', ['PROACTIVE_PREFERENCES.md'], 'main'), ['prompt:main'])] },
    ],
  },
  {
    // Keyless: the preflight answers skip decisions without a model (steps 1, 6, 7); steps that need
    // a model reply, or a task state only a model run records (step 3), are blocked per step.
    id: 'S09', minutes: 6, view: 'heartbeat', tags: ['upstream-uyumlu', 'demo-only: sanal saat', 'model'], requires: ['anahtar (2.-5. adım)'], setup: { reset: 'seeded' },
    steps: [
      { act: 'edit', path: 'HEARTBEAT.md', append: 'tasks:\n  - name: gunluk-takip\n    interval: 30m\n    prompt: Bugünün günlük notunda açık bir takip maddesi var mı kontrol et. Yoksa yalnızca HEARTBEAT_OK yaz.', waitFor: 'file.saved', label: 'scn.S09.l0', expect: 'scn.S09.e0',
        checks: [auto('heartbeatTasks({name:gunluk-takip,due})', hbTask('gunluk-takip', (x) => x.due || x.lastRunMs === null || x.lastRunMs === undefined), ['heartbeat'])] },
      { act: 'press', view: 'heartbeat', target: 'hb-run', waitFor: 'heartbeat.decided|heartbeat.skipped', label: 'scn.S09.l1', expect: 'scn.S09.e1', blockedIf: needsKey,
        checks: [auto('promptHas(heartbeatUser,/^Run the following periodic tasks/)', hbUserHas(/^Run the following periodic tasks/), ['hbRun']), auto('event(flush.decided,{reason:runtime_skip:heartbeat})', event('flush.decided', (d) => d.reason === 'runtime_skip:heartbeat')), model('heartbeatDelivered(false)', hbDelivered(false), ['hbRun'])] },
      { act: 'press', view: 'heartbeat', target: 'hb-run', waitFor: 'heartbeat.decided|heartbeat.skipped', label: 'scn.S09.l2', expect: 'scn.S09.e2', blockedIf: needsKey,
        checks: [auto('heartbeatSkipped(no-tasks-due)', hbSkipped('no-tasks-due'), ['hbRun']), auto('noEvent(heartbeat.llm)', noEvent('heartbeat.llm'))] },
      { act: 'send', text: 'Yarın 09:00\'da tedarikçiye fatura gönderilecek; bunu bugünün notuna takip maddesi olarak yaz.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S09.e3', blockedIf: needsKey,
        checks: [auto('fileChanged(daily(bugün))', fileChanged(daily()), TURN)] },
      { act: 'press', view: 'heartbeat', target: 'hb-clock30', then: 'hb-run', waitFor: 'heartbeat.decided|heartbeat.skipped', label: 'scn.S09.l4', expect: 'scn.S09.e4', blockedIf: needsKey,
        checks: [model('heartbeatDelivered(true)', hbDelivered(true), ['hbRun']), auto('delivered → heartbeat notice row', (ctx) => !ctx.hbRun?.decision?.delivered || (ctx.events || []).some((e) => e.type === 'heartbeat.decided' && e.data?.delivered), ['hbRun'])] },
      { act: 'strip', inputs: ['HEARTBEAT_OK', '**HEARTBEAT_OK**.', 'All good. HEARTBEAT_OK', 'Alert: disk full'], view: 'heartbeat', target: 'hb-strip', label: 'scn.S09.l5', expect: 'scn.S09.e5',
        checks: [auto('strip → [skip,skip,skip,deliver]', stripSequence(['HEARTBEAT_OK', '**HEARTBEAT_OK**.', 'All good. HEARTBEAT_OK', 'Alert: disk full'], ['skip', 'skip', 'skip', 'deliver']), ['strip'])] },
      { act: 'edit', path: 'HEARTBEAT.md', content: '# HEARTBEAT.md\n\n<!-- boş -->\n', then: 'hb-run', waitFor: 'heartbeat.skipped|heartbeat.decided', label: 'scn.S09.l6', expect: 'scn.S09.e6',
        checks: [auto('heartbeatSkipped(empty-heartbeat-file)', hbSkipped('empty-heartbeat-file'), ['hbRun']), auto('noEvent(heartbeat.llm)', noEvent('heartbeat.llm'))] },
    ],
  },
  {
    id: 'S10', minutes: 5, view: 'heartbeat', tags: ['uzantı', 'model'], requires: ['S09 görevleri', 'düzen MEMORY-CORE'], blockedIf: needsKey,
    steps: [
      { act: 'edit', path: 'PROACTIVE_PREFERENCES.md', content: '# PROACTIVE_PREFERENCES.md\n\n- Fatura ve ödeme takiplerini her zaman bildir.\n- Toplantı hatırlatmaları için bildirim gönderme; HEARTBEAT_OK yaz.\n', waitFor: 'file.saved', label: 'scn.S10.l0', expect: 'scn.S10.e0',
        checks: [auto('badge(PROACTIVE_PREFERENCES.md,injected)', badge('PROACTIVE_PREFERENCES.md', 'injected'), ['files']), auto('promptOrder([USER.md,PROACTIVE_PREFERENCES.md,TOOLS.md],{kind:heartbeat})', promptOrder(['USER.md', 'PROACTIVE_PREFERENCES.md', 'TOOLS.md'], 'heartbeat'), ['prompt:heartbeat'])] },
      { act: 'send', text: 'Bugünün notuna takip maddesi ekle: cuma 11:00 ekip toplantısı.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S10.e1',
        checks: [auto('fileChanged(daily(bugün))', fileChanged(daily()), TURN)] },
      { act: 'press', view: 'heartbeat', target: 'hb-clock30', then: 'hb-run', waitFor: 'heartbeat.decided|heartbeat.skipped', label: 'scn.S10.l2', expect: 'scn.S10.e2',
        checks: [model('heartbeatDelivered(true)', hbDelivered(true), ['hbRun']), model('replyMatches(/fatura/i)', hbReplyMatches(/fatura/i), ['hbRun']), model('replyLacks(/toplantı/i)', hbReplyLacks(/toplantı/i), ['hbRun'])] },
      { act: 'look', view: 'heartbeat', target: 'hb-compare', label: 'scn.S10.l3', expect: 'scn.S10.e3', checks: [manual('scn.S10.m3')] },
      { act: 'setting', apply: { settings: { layout: 'pin' } }, label: 'scn.S10.l4', expect: 'scn.S10.e4',
        checks: [auto('promptFiles(excludes,[PROACTIVE_PREFERENCES.md],{kind:heartbeat})', promptFiles('excludes', ['PROACTIVE_PREFERENCES.md'], 'heartbeat'), ['prompt:heartbeat'])] },
    ],
  },
  {
    id: 'S11', minutes: 5, view: 'chat', tags: ['upstream-uyumlu', 'demo-only: token sayımı'], requires: ['anahtar'], blockedIf: needsKey,
    steps: [
      { act: 'setting', apply: { settings: { flush: { mode: 'threshold', contextWindowTokens: 26000 } } }, label: 'scn.S11.l0', expect: 'scn.S11.e0',
        checks: [observe('flush eşiği', (ctx) => `${ctx.snap?.flush?.totalTokens ?? '—'} / ${ctx.snap?.flush?.threshold ?? '—'}`, ['snap'])] },
      { act: 'send', text: "Bugün staging ortamında Redis'i 7.2 sürümüne yükselttik.", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S11.e1',
        checks: [observe('flush', (ctx) => `${ctx.turn?.flush?.decision?.reason || '—'} · ${ctx.snap?.flush?.totalTokens ?? '—'}/${ctx.snap?.flush?.threshold ?? '—'}`, ['turn', 'snap'])] },
      { act: 'send', text: 'CI süresi 14 dakikadan 9 dakikaya indi; önbellek katmanını değiştirdik.', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S11.e2',
        checks: [observe('flush', (ctx) => `${ctx.turn?.flush?.decision?.reason || '—'} · ${ctx.snap?.flush?.totalTokens ?? '—'}/${ctx.snap?.flush?.threshold ?? '—'}`, ['turn', 'snap'])] },
      { act: 'send', text: "Yarın sabah 08:00'de yük testi var, sonuçları akşam paylaşacağız.", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S11.e3',
        checks: [auto('scenario: flush.decided reason ∈ [token_threshold, transcript_size]', (ctx) => (ctx.scenarioEvents || []).some((e) => e.type === 'flush.decided' && ['token_threshold', 'transcript_size'].includes(e.data?.reason))),
          auto('scenario: fileChanged(daily(bugün),{source:flush})', (ctx) => (ctx.scenarioDiff || []).some((d) => d.path === `memory/${ctx.today}.md` && sourceNames(d).includes('flush')), ['scenarioDiff']),
          auto('onlyFileBySource(daily(bugün), flush)', (ctx) => { const list = (ctx.scenarioDiff || []).filter((d) => sourceNames(d).includes('flush')); return list.length === 1 && list[0].path === `memory/${ctx.today}.md`; }, ['scenarioDiff']),
          auto('fileUnchanged(bootstrap ∪ MEMORY.md,{source:flush})', (ctx) => !(ctx.scenarioDiff || []).some((d) => [...BOOTSTRAP_FILES, 'MEMORY.md'].includes(d.path) && sourceNames(d).includes('flush')), ['scenarioDiff'])] },
      { act: 'look', tab: 'prompt', label: 'scn.S11.l4', expect: 'scn.S11.e4',
        checks: [auto('flush prompt has NO_REPLY', (ctx) => /NO_REPLY/.test(ctx.flushTurn?.prompt?.flush?.prompt || ''), ['flushTurn']), auto('flushTarget(/^memory\\/\\d{4}-\\d{2}-\\d{2}\\.md$/)', (ctx) => /^memory\/\d{4}-\d{2}-\d{2}\.md$/.test(ctx.flushTurn?.flush?.run?.target || ctx.flushTurn?.prompt?.flush?.target || ''), ['flushTurn'])] },
      { act: 'cmd', text: '/flush', waitFor: 'flush.decided|flush.no_write|flush.written', expect: 'scn.S11.e5', labels: [{ tone: 'warn', text: 'scn.S11.forced' }],
        checks: [auto('noChange(daily(bugün))', fileUnchanged([daily()]), ['diff'])] },
      { act: 'cmd', text: '/heartbeat', waitFor: 'heartbeat.decided|heartbeat.skipped', expect: 'scn.S11.e6',
        checks: [observe('flush kararı', (ctx) => ((ctx.events || []).find((e) => e.type === 'flush.decided')?.data?.reason) || '—')] },
    ],
  },
  {
    id: 'S12', minutes: 6, view: 'consolidation', tags: ['uzantı', 'model'], requires: ['S11 günlük notu'], blockedIf: needsKey,
    steps: [
      { act: 'send', text: "Staging'de Redis hangi sürümde?", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S12.e0',
        checks: [observe('recallCount (Redis)', (ctx) => String(Math.max(0, ...(ctx.consolidation?.candidates || []).filter((c) => c.path === `memory/${ctx.today}.md` && /redis/i.test(c.snippet || '')).map((c) => c.recallCount))), ['consolidation'])] },
      { act: 'send', text: 'Redis yükseltmesini ne zaman yaptık?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S12.e1',
        checks: [observe('recallCount (Redis)', (ctx) => String(Math.max(0, ...(ctx.consolidation?.candidates || []).filter((c) => c.path === `memory/${ctx.today}.md` && /redis/i.test(c.snippet || '')).map((c) => c.recallCount))), ['consolidation'])] },
      { act: 'send', text: 'Önbellek katmanında hangi Redis sürümünü kullanıyoruz?', waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S12.e2',
        checks: [auto('candidate({path:daily(bugün),snippet~Redis,recallCount≥3,uniqueQueries≥3})', candidate((c, ctx) => c.path === `memory/${ctx.today}.md` && /redis/i.test(c.snippet || '') && c.recallCount >= 3 && c.uniqueQueries >= 3), ['consolidation'])] },
      { act: 'press', view: 'consolidation', target: 'promote', waitFor: 'promotion.swept', label: 'scn.S12.l3', expect: 'scn.S12.e3',
        checks: [auto('candidateGatesConsistent()', candidateGatesConsistent(), ['consolidation']), auto('if selected → fileChanged(MEMORY.md,{source:promotion})', (ctx) => !(ctx.consolidation?.candidates || []).some((c) => c.selected) || fileChanged('MEMORY.md', { source: 'promotion' })(ctx), ['consolidation', 'diff'])] },
      { act: 'send', text: "Bunu uzun vadeli belleğe al: staging Redis 7.2'de.", waitFor: 'chat.turn.completed|chat.turn.failed', expect: 'scn.S12.e4',
        checks: [auto('fileChanged(MEMORY.md,{source:curation})', fileChanged('MEMORY.md', { source: 'curation' }), TURN), auto('noEvent(promotion.swept)', noEvent('promotion.swept'))] },
      { act: 'press', view: 'consolidation', target: 'audit', waitFor: 'audit.completed', label: 'scn.S12.l5', expect: 'scn.S12.e5', checks: [auto('audit issues == 0', auditClean(), ['consolidation'])] },
    ],
  },
  {
    id: 'S13', minutes: 4, view: 'live', tags: ['adapter-only', 'scripted (anahtarsız)'], requires: [],
    steps: [
      { act: 'press', view: 'live', target: 'live-reset', waitFor: 'live.reset', label: 'scn.S13.l0', expect: 'scn.S13.e0', checks: [auto('liveStep(verify_identity)', liveStep('verify_identity'), ['live'])] },
      { act: 'send', live: true, text: 'Merhaba, randevumu değiştirmek istiyorum.', waitFor: 'live.turn', expect: 'scn.S13.e1',
        checks: [auto('eventOrder([live_turn_started,memory_recall_completed,prompt_assembled,text_delta,sentence,live_turn_completed])', liveOrder(['live_turn_started', 'memory_recall_completed', 'prompt_assembled', 'text_delta', 'sentence', 'live_turn_completed']), ['live']), observe('motor', (ctx) => ctx.live?.engine?.provider ? `${ctx.live.engine.provider} · ${ctx.live.engine.model || ''}` : '—', ['live'])] },
      { act: 'send', live: true, text: 'Doğum tarihim 01.01.1990.', waitFor: 'live.turn', expect: 'scn.S13.e2', labels: [{ tone: 'info', text: 'scn.S13.synthetic' }],
        checks: [auto('liveStep(collect_new_time)', liveStep('collect_new_time'), ['live'])] },
      { act: 'send', live: true, text: 'Yarın saat 14:30 olabilir mi?', waitFor: 'live.turn', expect: 'scn.S13.e3', checks: [auto('liveStep(confirm_change)', liveStep('confirm_change'), ['live'])] },
      { act: 'send', live: true, text: 'Evet, onaylıyorum.', waitFor: 'live.turn', expect: 'scn.S13.e4', checks: [auto('liveStep(completed)', liveStep('completed'), ['live']), auto('businessAction(appointment_rescheduled)', businessAction('appointment_rescheduled'), ['live'])] },
      { act: 'press', view: 'live', target: 'live-summary', waitFor: 'live.summary|live.session_summary', label: 'scn.S13.l5', expect: 'scn.S13.e5',
        checks: [auto('summary wrote to subject daily file', liveSummaryWrote(), ['live']), auto('bus: event(live.session_summary)', event('live.session_summary'))] },
      { act: 'look', view: 'live', label: 'scn.S13.l6', expect: 'scn.S13.e6',
        checks: [auto('textAbsent(subjectDaily, proof@3)', proofAbsentFromSummary(3), ['live'])] },
    ],
  },
  {
    id: 'S14', minutes: 5, view: 'chat', tags: ['upstream-uyumlu', 'demo'], requires: [],
    steps: [
      { act: 'setting', apply: { page: { suspendKeys: true } }, label: 'scn.S14.l0', expect: 'scn.S14.e0',
        checks: [auto('chip(model, grey dot)', (ctx) => ctx.modelChip?.grey === true)] },
      { act: 'send', live: true, text: 'Merhaba', waitFor: 'live.turn', expect: 'scn.S14.e1',
        checks: [auto('liveEngine(scripted)', (ctx) => ctx.live?.engine?.provider === 'scripted', ['live']), observe('state engine.mode', (ctx) => ctx.live?.state?.engine?.mode || '—', ['live'])] },
      { act: 'setting', apply: { page: { restoreKeys: true }, settings: { chat: { baseUrl: 'http://127.0.0.1:9/v1' } } }, label: 'scn.S14.l2', expect: 'scn.S14.e2', checks: [] },
      { act: 'send', text: 'Merhaba', waitFor: 'chat.turn.failed|chat.turn.completed', expect: 'scn.S14.e3', blockedIf: needsKey,
        checks: [auto('errorShown(/chat send failed/)', turnErrorMatches(/chat send failed/)), auto('error.redacted (server-side)', errorRedacted()), auto('elapsed ≤ 10000 ms', (ctx) => (ctx.turnMs ?? Infinity) <= 10000, ['turn'])] },
      { act: 'setting', apply: { restore: ['chat.baseUrl'], settings: { embedding: { baseUrl: 'http://127.0.0.1:9/v1' } } }, label: 'scn.S14.l4', expect: 'scn.S14.e4', checks: [] },
      { act: 'look', tab: 'memory', search: { query: 'toplantı', mode: 'hybrid', maxResults: 5, minScore: 0 }, label: 'scn.S14.l5', expect: 'scn.S14.e5', blockedIf: needsHybrid,
        checks: [auto('searchUnavailable({warning,action})', searchUnavailable(), ['search']), auto('chip(cooldown)', cooldownActive(), ['index'])] },
      { act: 'look', tab: 'memory', search: { query: 'toplantı' }, label: 'scn.S14.l6', expect: 'scn.S14.e6', blockedIf: needsHybrid,
        checks: [auto('event(search.cooldown)', event('search.cooldown')), auto('noEvent(embedding.request)', noEvent('embedding.request'))] },
      { act: 'setting', apply: { restore: ['embedding.baseUrl'] }, then: 'check-embedding', label: 'scn.S14.l7', expect: 'scn.S14.e7', blockedIf: needsHybrid,
        checks: [auto('event(provider.check,{ok:true})', providerCheck('embedding', true))] },
    ],
  },
];

export const FULL_RUN = ['S06', 'S01', 'S02', 'S03', 'S04', 'S05', 'S07', 'S08', 'S11', 'S12', 'S09', 'S10', 'S13', 'S14'];
export const fullRunMinutes = () => FULL_RUN.reduce((a, id) => a + (SCENARIOS.find((s) => s.id === id)?.minutes || 0), 0);
export const byId = (id) => SCENARIOS.find((s) => s.id === id) || null;
