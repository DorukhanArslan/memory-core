// One genuine fresh process in the durable-session experiment. The coordinator
// passes only this phase's literal mutations and the common persisted root.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

const errorRecord = (error) => ({ name: error.name, message: error.message,
  ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) =>
    !["name", "message", "stack"].includes(key)).map((key) => [key, error[key]])) });
const preludeFlags = (messages) => messages.map((message) =>
  message[Symbol.for("openclaw.sessionHistoryPrelude")] === true);

export async function runDurableSessionPhase(request) {
  const { input, phase, directory, runtimeRoot } = request;
  if (!path.isAbsolute(directory) || !path.isAbsolute(runtimeRoot) ||
      !["write", "continue", "verify"].includes(phase.label) || !Number.isFinite(phase.nowMs ?? input.nowMs)) {
    throw Error("A durable phase requires an explicit persisted root, clock and phase identity");
  }
  const stateDirectory = path.join(directory, "state"), workspace = path.join(directory, "workspace");
  const configPath = path.join(directory, "openclaw.json");
  await fs.mkdir(workspace, { recursive: true }); await fs.mkdir(stateDirectory, { recursive: true });
  process.env.OPENCLAW_STATE_DIR = stateDirectory; process.env.OPENCLAW_CONFIG_PATH = configPath;
  const agentId = input.agentId ?? "main", nowMs = phase.nowMs ?? input.nowMs;
  const cfg = { agents: { defaults: { workspace }, list: [{ id: agentId, default: true }] },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { maintenance: { mode: "warn" } }, tools: { sessions: { visibility: "agent" } },
    memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["sessions"],
      rememberAcrossConversations: true, experimental: { sessionMemory: true }, store: { vector: { enabled: false } },
      sync: { onSessionStart: false, onSearch: false, watch: false },
      query: { minScore: 0, maxResults: 200, hybrid: { temporalDecay: { enabled: false } } } } } };
  // The verify phase cannot rewrite even the host configuration.
  if (phase.label === "write") await fs.writeFile(configPath, JSON.stringify(cfg));
  else if (await fs.readFile(configPath, "utf8") !== JSON.stringify(cfg)) throw Error("Persisted host configuration changed");
  const beforeDate = Date, beforeTimeout = setTimeout, beforePerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: nowMs });
  const raw = { label: phase.label, pid: process.pid, ppid: process.ppid, fixtureBase: directory,
    request, config: cfg, clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(),
      dateConstructorReplaced: Date !== beforeDate, setTimeoutUnchanged: setTimeout === beforeTimeout,
      performanceNowUnchanged: performance.now === beforePerformance }, sessionWrites: [], appendWrites: [],
    sourceReads: [], contextRequests: [], queries: [], snapshot: null };
  let manager, closeManagers, clearConfig;
  const imp = (relative) => import(pathToFileURL(path.join(runtimeRoot, relative)).href);
  try {
    const config = await imp("dist/plugin-sdk/config-runtime.js");
    config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const reads = await imp("dist/session-accessor.sqlite-read-BsSfe2AE.mjs");
    const context = await imp("dist/session-BA9qunLx.mjs");
    const engine = await imp("dist/plugin-sdk/memory-core-host-engine-sessions.js");
    const files = await imp("dist/session-files-DVVT4Ngb.mjs");
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js"); closeManagers = runtime.closeAllMemoryIndexManagers;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const storePath = sessions.resolveStorePath(undefined, { agentId });
    const scope = (value = {}) => ({ agentId, storePath, sessionKey: value.sessionKey ?? input.sessionKey,
      ...(value.sessionId !== undefined ? { sessionId: value.sessionId } : {}) });
    raw.storePaths = { catalogStorePath: storePath,
      databasePath: accessor.resolveSessionTranscriptDatabasePath(scope({ sessionId: input.sessionId })) };
    if (phase.label === "verify" && ((phase.sessions?.length ?? 0) || (phase.appendMessages?.length ?? 0))) {
      throw Error("The third process is a mutation-free reopen verification");
    }
    for (const seed of phase.sessions ?? []) {
      const target = scope({ ...seed, sessionId: seed.entry.sessionId });
      const result = await sessions.upsertSessionEntry({ ...target, entry: { updatedAt: nowMs, ...seed.entry } });
      if (seed.events !== undefined) await accessor.replaceTranscriptEvents(target, seed.events);
      const participantWrites = [];
      for (const record of seed.participants ?? []) participantWrites.push(await accessor.recordSessionParticipant(target,
        { ...record, promptedAt: record.promptedAt ?? nowMs, sessionAgentId: agentId }));
      raw.sessionWrites.push({ target, entry: seed.entry, events: seed.events, result, participantWrites,
        readBack: sessions.getSessionEntry(target), transcript: accessor.loadTranscriptEventsSync(target) });
    }
    const appendResults = [];
    for (const append of phase.appendMessages ?? []) {
      const current = sessions.getSessionEntry(scope(append));
      const target = scope({ ...append, sessionId: append.sessionId ?? current?.sessionId });
      if (!target.sessionId || !append.eventId) throw Error("Durable appends require actual current identity and a caller event id");
      const options = { message: append.message, eventId: append.eventId, now: append.now ?? nowMs,
        cwd: append.cwd ?? workspace, ...(Object.hasOwn(append, "parentId") ? { parentId: append.parentId } : {}),
        ...(append.appendIntent ? { appendIntent: append.appendIntent } : {}) };
      try {
        const result = await accessor.appendTranscriptMessage(target, options);
        appendResults.push({ id: append.eventId, result }); raw.appendWrites.push({ target, options, result });
      } catch (error) {
        const detail = errorRecord(error); appendResults.push({ id: append.eventId, error: detail });
        raw.appendWrites.push({ target, options, error: detail, stack: error.stack });
      }
    }
    // A new manager and its real index worker are constructed independently in
    // each OS process over the same already-persisted SQLite state.
    manager = await runtime.MemoryIndexManager.get({ cfg, agentId });
    if (!manager) throw Error("The genuine durable phase manager was unavailable");
    if (!manager.settings || typeof manager.settings !== "object") throw Error("The genuine resolved manager settings were unavailable");
    raw.resolvedManagerSettings = structuredClone(manager.settings);
    const indexState = () => Object.fromEntries([
      ["chunks", "SELECT *,hex(embedding) AS embeddingHex FROM memory_index_chunks ORDER BY source,path,start_line,end_line,id"],
      ["provenance", "SELECT * FROM memory_index_chunk_provenance ORDER BY chunk_id"],
      ["recall", "SELECT * FROM memory_index_chunk_recall_metadata ORDER BY chunk_id"],
      ["sources", "SELECT * FROM memory_index_sources ORDER BY source,path"],
      ["fts", "SELECT * FROM memory_index_chunks_fts ORDER BY source,path,start_line,end_line,id"],
    ].map(([name, query]) => [name, manager.db.prepare(query).all()]));
    raw.indexBeforeSync = indexState();
    raw.syncRequest = { reason: "durable-session-reopen", force: phase.label !== "verify" };
    await manager.sync({ reason: "durable-session-reopen", force: phase.label !== "verify" });
    const catalog = await engine.listSessionTranscriptCorpusEntriesForAgent(agentId,
      { includeContentRevision: false, includeRetainedSqlite: true });
    const admitted = await manager.listSessionCorpusEntries();
    const sourceEntries = [];
    for (const source of admitted) {
      const options = manager.buildSessionEntryOptions(source);
      const entry = await engine.buildSessionEntry(source.sessionFile, options);
      const built = { source, entry, resetRecallCutoff: files.a(entry) };
      sourceEntries.push(built); raw.sourceReads.push({ source, options, result: built });
    }
    function continuation(target, id) {
      const entry = sessions.getSessionEntry(target);
      const eventScope = { ...target, sessionId: target.sessionId ?? entry?.sessionId };
      const events = eventScope.sessionId ? accessor.loadTranscriptEventsSync(eventScope) : [];
      const visibleEvents = reads.F(events);
      const builtContext = context.t(visibleEvents);
      const modelMessages = context.u(builtContext.messages);
      const result = { ...(id === undefined ? {} : { id }), entry, events, visibleEvents,
        context: builtContext, modelMessages, preludeFlags: preludeFlags(builtContext.messages),
        modelPreludeFlags: preludeFlags(modelMessages) };
      raw.contextRequests.push({ input: { ...target, ...(id === undefined ? {} : { id }) }, target: eventScope, result });
      return result;
    }
    const mainContinuation = continuation(scope(), undefined);
    const { entry: currentEntry, events, visibleEvents, context: builtContext, modelMessages,
      preludeFlags: contextPreludeFlags, modelPreludeFlags } = mainContinuation;
    const identityReads = (phase.identityReads ?? []).map((read) => continuation(scope(read), read.id));
    const queries = [];
    for (const query of phase.queries ?? []) {
      const options = { maxResults: query.maxResults ?? 200, minScore: query.minScore ?? 0, sources: ["sessions"] };
      const results = await manager.search(query.query, options);
      queries.push({ id: query.id, results }); raw.queries.push({ input: query, options, results });
    }
    const db = manager.db;
    const sessionSql = Object.fromEntries(db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND " +
      "(name GLOB 'session_*' OR name GLOB 'transcript_*') ORDER BY name").all().map(({ name }) => {
      if (!/^[A-Za-z0-9_]+$/.test(name)) throw Error("Unexpected real SQL identifier");
      return [name, { columns: db.prepare(`PRAGMA table_info("${name}")`).all(),
        rows: db.prepare(`SELECT * FROM "${name}"`).all().map((row) => Object.fromEntries(Object.entries(row).map(([key, value]) =>
          [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) }];
    }));
    const fullSql = { chunks: db.prepare("SELECT *,hex(embedding) AS embeddingHex FROM memory_index_chunks ORDER BY source,path,start_line,end_line,id").all(),
      provenance: db.prepare("SELECT * FROM memory_index_chunk_provenance ORDER BY chunk_id").all(),
      recall: db.prepare("SELECT * FROM memory_index_chunk_recall_metadata ORDER BY chunk_id").all(),
      sources: db.prepare("SELECT * FROM memory_index_sources ORDER BY source,path").all(),
      fts: db.prepare("SELECT * FROM memory_index_chunks_fts ORDER BY source,path,start_line,end_line,id").all() };
    const published = db.prepare("SELECT c.path,c.source,c.start_line AS startLine,c.end_line AS endLine,c.text," +
      "r.importance,r.triggers,r.project_key AS projectKey,p.origin_class AS originClass,p.session_kind AS sessionKind," +
      "p.observed_at AS observedAt,p.supersedes_key AS supersedesKey FROM memory_index_chunks c " +
      "LEFT JOIN memory_index_chunk_recall_metadata r ON r.chunk_id=c.id LEFT JOIN memory_index_chunk_provenance p ON p.chunk_id=c.id " +
      "ORDER BY c.source,c.path,c.start_line,c.end_line,c.id").all().map(({ originClass, sessionKind, observedAt, supersedesKey, ...row }) =>
      ({ ...row, provenance: { originClass, sessionKind, observedAt, supersedesKey } }));
    const snapshot = { label: phase.label, currentEntry,
      instances: accessor.listSessionTranscriptInstances({ agentId, storePath }), catalog, admitted, sourceEntries,
      participantRecords: Object.fromEntries(accessor.listSessionParticipantsReadOnly({ agentId, storePath })),
      events, visibleEvents, context: builtContext, modelMessages,
      preludeFlags: contextPreludeFlags, modelPreludeFlags, identityReads,
      ...(phase.anchorEntryId ? { activeAnchor: accessor.readActiveTranscriptEntryAnchor({
        ...scope({ sessionId: currentEntry?.sessionId ?? input.sessionId }), entryId: phase.anchorEntryId }) } : {}),
      appendResults, published, indexSources: fullSql.sources.map(({ path, source }) => ({ path, source })), queries };
    raw.snapshot = { ...snapshot, sessionSql, fullSql, managerStatus: manager.status() };
    return { result: mapGetFixturePaths(snapshot, directory), raw };
  } finally {
    await manager?.close(); await closeManagers?.(); clearConfig?.(); mock.timers.reset();
  }
}

