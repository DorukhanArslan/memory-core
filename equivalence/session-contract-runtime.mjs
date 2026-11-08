// Genuine catalog/accessor/index/read/tool owners over private persisted facts.
// No accepted corpus, visibility decision or search hit is supplied by a fixture.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { mock } from "node:test";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

function publicError(error) {
  return { name: error.name, message: error.message,
    ...Object.fromEntries(Object.getOwnPropertyNames(error)
      .filter((key) => !["name", "message", "stack"].includes(key)).map((key) => [key, error[key]])) };
}

export async function runSessionContractHelperRuntime(input, runtimeConfig) {
  if (input.kind !== "admission-policy") throw Error("Only admission-policy helpers belong to this profile");
  const owner = await import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, "dist/session-ingestion-Dy5uAq-_.mjs")).href);
  const result = Array.isArray(input.configs)
    ? { policies: input.configs.map((config) => owner.s(config)) }
    : { policy: owner.s(input.pluginConfig) };
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([{ result }]));
  return { provider: "none", ...result };
}

export async function runSessionContractRuntime(input, runtimeConfig) {
  if (input.kind !== "flow" || !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") ||
      !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "") || !Number.isFinite(input.nowMs)) {
    throw Error("Real session flows require an explicit clock and authenticated owned runtime");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-session-fixture-"));
  const workspace = path.join(directory, "workspace"), stateDirectory = path.join(directory, "state");
  await fs.mkdir(workspace); await fs.mkdir(stateDirectory);
  const configPath = path.join(directory, "openclaw.json");
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = stateDirectory; process.env.OPENCLAW_CONFIG_PATH = configPath;
  const beforeDate = Date, beforeSetTimeout = setTimeout;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { fixtureBase: directory, constructorSkipped: false, managerFixture: false,
    sessionWrites: [], gatewayRequests: [], snapshots: [], lifecycle: [], archiveWrites: [], reads: [],
    nativeEnvelopes: [], queryErrors: [], catalogRequests: [], managerAcquisitions: [],
    queryRequests: [], readRequests: [], mutations: [],
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== beforeDate,
      setTimeoutUnchanged: setTimeout === beforeSetTimeout } };
  let manager, closeManagers, projection, clearConfig;
  const agentId = input.agentId ?? "main";
  const agentIds = input.config?.agentIds ?? [agentId];
  const store = input.config?.sessionStore === "shared" ? path.join(stateDirectory, "shared", "sessions.json")
    : input.config?.sessionStore === "custom-template" ? path.join(stateDirectory, "custom", "{agentId}", "sessions.json") : undefined;
  const cfg = { agents: { defaults: { workspace,
    ...(input.config?.sandboxVisibility === undefined ? {} : { sandbox: { sessionToolsVisibility: input.config.sandboxVisibility } }) },
    list: agentIds.map((id) => ({ id, ...(id === agentId ? { default: true } : {}) })) },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { ...(store ? { store } : {}), maintenance: { mode: "warn" }, ...(input.config?.session ?? {}) },
    tools: { sessions: { visibility: input.config?.visibility ?? "agent" }, ...(input.config?.tools ?? {}) },
    memory: { search: { enabled: true, provider: "none", fallback: "none",
      sources: input.config?.sources ?? ["memory", "sessions"],
      rememberAcrossConversations: input.config?.rememberAcrossConversations ?? true,
      experimental: { sessionMemory: input.config?.configuredSessionMemory ?? true },
      store: { vector: { enabled: false } },
      sync: { onSessionStart: false, onSearch: false, watch: false },
      query: { minScore: 0, maxResults: 200, hybrid: { temporalDecay: { enabled: false } } },
      ...(input.config?.chunking ? { chunking: input.config.chunking } : {}),
    } } };
  raw.config = cfg;
  await fs.writeFile(configPath, JSON.stringify(cfg));
  try {
    const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
    const config = await imp("dist/plugin-sdk/config-runtime.js");
    config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const sessionKeys = await imp("dist/plugin-sdk/session-key-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const engine = await imp("dist/plugin-sdk/memory-core-host-engine-sessions.js");
    const { a: readCutoff } = await imp("dist/session-files-DVVT4Ngb.mjs");
    const transcript = await imp("dist/plugin-sdk/session-transcript-runtime.js");
    const sql = await imp("dist/plugin-sdk/sqlite-runtime.js");
    const ingestion = await imp("dist/session-ingestion-Dy5uAq-_.mjs");
    const visibility = await imp("dist/plugin-sdk/session-visibility.js");
    const { l: resolveAccess } = await imp("dist/sessions-helpers-DM7oZCRf.mjs");
    const { t: canonicalMain } = await imp("dist/main-session-key-BoL-e9po.mjs");
    const agentScope = await imp("dist/plugin-sdk/agent-scope-runtime.js");
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js");
    closeManagers = runtime.closeAllMemoryIndexManagers;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const scope = (entry) => ({ agentId: entry.agentId ?? agentId, sessionKey: entry.sessionKey,
      sessionId: entry.sessionId ?? entry.entry?.sessionId,
      storePath: sessions.resolveStorePath(cfg.session.store, { agentId: entry.agentId ?? agentId }) });
    async function seed(entry) {
      const target = scope(entry);
      const written = await sessions.upsertSessionEntry({ ...target,
        entry: { updatedAt: input.nowMs, ...entry.entry } });
      if (entry.events) await accessor.replaceTranscriptEvents(target, entry.events);
      const participants = [];
      for (const participant of entry.participants ?? []) participants.push(await accessor.recordSessionParticipant(target,
        { ...participant, promptedAt: participant.promptedAt ?? input.nowMs, sessionAgentId: target.agentId }));
      const databasePath = accessor.resolveSessionTranscriptDatabasePath(target);
      let pathExists;
      try { await fs.stat(databasePath); pathExists = true; }
      catch (error) { if (error.code !== "ENOENT") throw error; pathExists = false; }
      raw.sessionWrites.push({ target, written, events: entry.events,
        storage: { incognito: sessionKeys.isIncognitoSessionKey(target.sessionKey), databasePath, pathExists },
        participants, participantRecords: Object.fromEntries(accessor.listSessionParticipantsReadOnly(target)),
        readBack: sessions.getSessionEntry(target), transcript: accessor.loadTranscriptEventsSync(target) });
    }
    function database(entry) {
      const target = scope(entry);
      return sql.openOpenClawAgentDatabase({ agentId: target.agentId,
        path: accessor.resolveSessionTranscriptDatabasePath(target) });
    }
    function sessionSql(db) {
      const names = db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND " +
        "(name GLOB 'session_*' OR name GLOB 'transcript_*' OR name IN ('memory_entry_origins','memory_session_tombstones')) ORDER BY name").all();
      return Object.fromEntries(names.map(({ name }) => {
        if (!/^[A-Za-z0-9_]+$/.test(name)) throw Error("Unexpected owned session schema identifier");
        return [name, { columns: db.prepare(`PRAGMA table_info("${name}")`).all(),
          rows: db.prepare(`SELECT * FROM "${name}"`).all().map((row) => Object.fromEntries(Object.entries(row)
            .map(([key, value]) => [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) }];
      }));
    }
    async function archive(entry) {
      const owner = entry.agentId ?? agentId;
      const storePath = sessions.resolveStorePath(cfg.session.store, { agentId: owner });
      if (path.basename(entry.name) !== entry.name) throw Error("Archive fixture names must remain owned");
      const filename = path.join(path.dirname(storePath), entry.name);
      const bytes = entry.compressedBytes ? Buffer.from(entry.compressedBytes)
        : Buffer.from(entry.events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
      await fs.mkdir(path.dirname(filename), { recursive: true }); await fs.writeFile(filename, bytes);
      await fs.utimes(filename, input.nowMs / 1000, input.nowMs / 1000);
      if (entry.identity) {
        const { persistSessionTranscriptArchive } = await imp("dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs");
        const identity = entry.identity;
        const db = database({ agentId: owner, sessionKey: identity.sessionKey, sessionId: identity.sessionId });
        const descriptor = { archiveName: entry.name, bytes, createdAt: identity.createdAt ?? input.nowMs,
          encoding: entry.compressedBytes ? "zstd" : "identity", sha256: createHash("sha256").update(bytes).digest("hex") };
        const plan = { agentId: owner, sessionId: identity.sessionId,
          reason: identity.reason, archive: descriptor,
          snapshot: { sessionKey: identity.sessionKey, generation: identity.generation } };
        sql.runSqliteImmediateTransactionSync(db.db, () => persistSessionTranscriptArchive(db, plan));
        raw.archiveWrites.push({ filename, descriptor, plan,
          rows: db.db.prepare("SELECT * FROM session_transcript_archives ORDER BY session_id,generation").all() });
      } else raw.archiveWrites.push({ filename, bytes });
    }
    for (const [relative, text] of Object.entries(input.files ?? {})) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) throw Error("Fixture files must remain owned");
      const filename = path.join(workspace, relative);
      await fs.mkdir(path.dirname(filename), { recursive: true }); await fs.writeFile(filename, text, "utf8");
      await fs.utimes(filename, input.nowMs / 1000, input.nowMs / 1000);
    }
    for (const entry of input.sessions ?? []) await seed(entry);
    for (const entry of input.archives ?? []) await archive(entry);
    manager = await runtime.MemoryIndexManager.get({ cfg, agentId });
    if (!manager) throw Error("The real provider-none session manager was unavailable");
    raw.managerAcquisitions.push({ agentId, status: manager.status() });
    let gatewayContext, withGateway;
    if (input.gateway || ["tree", "all"].includes(cfg.tools.sessions.visibility) ||
        input.steps?.some((step) => step.reads?.length)) {
      const { t: createProjection } = await imp("dist/session-row-projection-B5-QIpdH.mjs");
      const { t: bindProjection } = await imp("dist/session-row-projection-access-CUCrJD4M.mjs");
      const { s: bindContext } = await imp("dist/gateway-request-scope-Btza1qbw.mjs");
      projection = await createProjection({ cfg, getConfig: () => cfg, modelCatalog: [] });
      gatewayContext = bindProjection({ getRuntimeConfig: () => cfg, getCommittedRuntimeConfig: () => cfg,
        trackExecution: (run) => Promise.resolve().then(run), forgetConnectionAncestors: () => {},
        requestEntryLifetime: { enter: ({ req }) => {
          raw.gatewayRequests.push({ method: req.method, params: req.params });
          return { assertOpen() {}, release() {} };
        } }, logGateway: { debug() {}, info() {}, warn() {}, error() {} } }, () => projection);
      withGateway = (run) => bindContext(() => gatewayContext, run);
    } else withGateway = (run) => run();
    const { createMemorySearchTool } = await imp("dist/tools-DotaQGXh.mjs");
    const outputs = [];
    for (const step of input.steps ?? [{ label: "initial" }]) {
      for (const entry of step.sessions ?? []) await seed(entry);
      for (const entry of step.replaceEvents ?? []) {
        const target = scope(entry);
        const result = await accessor.replaceTranscriptEvents(target, entry.events);
        raw.mutations.push({ step: step.label, operation: "replaceEvents", target, events: entry.events, result });
      }
      for (const entry of step.archives ?? []) await archive(entry);
      if (step.resetSessions?.length) throw Error("This profile drives persisted reset records through the common transcript writer");
      for (const entry of step.deleteSessions ?? []) {
        if (entry.archiveTranscript) throw Error("The common deletion profile explicitly disables generated archival publication");
        const target = { ...scope(entry), archiveTranscript: false };
        const result = await sessions.deleteSessionEntry(target);
        raw.mutations.push({ step: step.label, operation: "deleteSession", target, result });
      }
      if (step.forgetSessions?.length) {
        const { o: recordTombstones } = await imp("dist/memory-entry-origins-BCQSIB3X.mjs");
        const ids = step.forgetSessions.map((entry) => typeof entry === "string" ? entry : entry.sessionId);
        const first = (step.forgetSessions.find((entry) => typeof entry !== "string") ?? input.sessions?.[0]);
        const db = first ? database(first) : { db: manager.db };
        const recorded = recordTombstones(db.db, { agentId, sessionIds: ids, createdAt: input.nowMs });
        raw.lifecycle.push({ operation: "tombstones", ids, recorded });
        raw.mutations.push({ step: step.label, operation: "tombstones", ids, recorded });
      }
      await manager.sync({ reason: "session-contract-fixture", force: true });
      const catalog = await engine.listSessionTranscriptCorpusEntriesForAgent(agentId,
        { includeContentRevision: false, includeRetainedSqlite: input.includeRetainedSqlite === true });
      raw.catalogRequests.push({ agentId, includeContentRevision: false,
        includeRetainedSqlite: input.includeRetainedSqlite === true });
      const admitted = await manager.listSessionCorpusEntries();
      const sourceEntries = [];
      for (const entry of admitted) {
        const built = await engine.buildSessionEntry(entry.sessionFile, manager.buildSessionEntryOptions(entry));
        sourceEntries.push({ source: entry, entry: built, resetRecallCutoff: readCutoff(built) });
      }
      const chunks = manager.db.prepare("SELECT id,path,source,start_line AS startLine,end_line AS endLine,text,hash,model,updated_at AS updatedAt FROM memory_index_chunks ORDER BY source,path,start_line,end_line,id").all();
      const provenance = manager.db.prepare("SELECT * FROM memory_index_chunk_provenance ORDER BY chunk_id").all();
      const privateChunks = manager.db.prepare("SELECT *,hex(embedding) AS embeddingHex FROM memory_index_chunks ORDER BY source,path,start_line,end_line,id").all();
      if (privateChunks.some((row) => row.embeddingHex !== "")) throw Error("The provider-none profile must persist actual empty vectors");
      const fullSql = { chunks: privateChunks, provenance,
        sources: manager.db.prepare("SELECT * FROM memory_index_sources ORDER BY source,path").all(),
        recall: manager.db.prepare("SELECT * FROM memory_index_chunk_recall_metadata ORDER BY chunk_id").all(),
        fts: manager.db.prepare("SELECT * FROM memory_index_chunks_fts ORDER BY source,path,start_line,end_line,id").all() };
      const published = manager.db.prepare("SELECT c.path,c.source,c.start_line AS startLine,c.end_line AS endLine,c.text," +
        "r.importance,r.triggers,r.project_key AS projectKey,p.origin_class AS originClass,p.session_kind AS sessionKind," +
        "p.observed_at AS observedAt,p.supersedes_key AS supersedesKey FROM memory_index_chunks c " +
        "LEFT JOIN memory_index_chunk_recall_metadata r ON r.chunk_id=c.id " +
        "LEFT JOIN memory_index_chunk_provenance p ON p.chunk_id=c.id " +
        "ORDER BY c.source,c.path,c.start_line,c.end_line,c.id").all()
        .map(({ originClass, sessionKind, observedAt, supersedesKey, ...row }) =>
          ({ ...row, provenance: { originClass, sessionKind, observedAt, supersedesKey } }));
      const indexSources = fullSql.sources.map(({ path, source }) => ({ path, source }));
      const queries = [];
      for (const query of step.queries ?? []) {
        const queryAgentId = query.agentId ?? agentId;
        const queryManager = queryAgentId === agentId ? manager : await runtime.MemoryIndexManager.get({ cfg, agentId: queryAgentId });
        if (!queryManager) throw Error("The requested actual agent manager was unavailable");
        if (queryManager !== manager) {
          raw.managerAcquisitions.push({ agentId: queryAgentId, status: queryManager.status() });
          await queryManager.sync({ reason: "session-contract-query-agent", force: true });
        }
        const candidates = await queryManager.search(query.query, { maxResults: query.maxResults ?? 200,
          minScore: query.minScore ?? 0, sources: ["sessions"] });
        try {
          const toolOptions = { config: cfg, agentId: queryAgentId, agentSessionKey: query.requesterSessionKey,
            conversationRecall: query.conversationRecall, sandboxed: query.sandboxed };
          const parameters = { query: query.query,
            maxResults: query.maxResults ?? 200, minScore: query.minScore ?? 0, corpus: query.corpus ?? "sessions" };
          raw.queryRequests.push({ step: step.label, queryId: query.id, toolOptions, parameters });
          const tool = createMemorySearchTool(toolOptions);
          const result = await withGateway(() => tool.execute(query.id, parameters));
          queries.push({ id: query.id, candidates, result: decodeSearchToolEnvelope(result) });
          raw.nativeEnvelopes.push({ step: step.label, queryId: query.id, nativeEnvelope: result });
        } catch (error) {
          const detail = publicError(error);
          queries.push({ id: query.id, candidates, error: detail });
          raw.queryErrors.push({ step: step.label, queryId: query.id, error: detail, stack: error.stack });
        }
      }
      const reads = [];
      for (const read of step.reads ?? []) {
        const requested = { step: step.label, readId: read.id, input: read };
        raw.readRequests.push(requested);
        try {
          const requesterAgentId = read.requesterAgentId ?? agentScope.resolveSessionAgentIdStrict({ config: cfg, sessionKey: read.requesterSessionKey });
          const targetAgentId = read.targetAgentId ?? read.agentId ?? agentScope.resolveSessionAgentIdStrict({ config: cfg, sessionKey: read.targetSessionKey });
          const guard = { action: "history", requesterAgentId,
            requesterSessionKey: read.requesterSessionKey, targetAgentId, targetSessionKey: read.targetSessionKey,
            requesterOwned: false, sessionReadScopeKey: read.sessionReadScopeKey,
            mainSessionKey: !read.sandboxed || visibility.resolveSandboxSessionToolsVisibility(cfg) === "all"
              ? canonicalMain({ agentId: requesterAgentId, mainKey: cfg.session.mainKey, sessionScope: cfg.session.scope }) : undefined,
            visibility: visibility.resolveEffectiveSessionToolsVisibility({ cfg, sandboxed: read.sandboxed === true }),
            a2aPolicy: visibility.createAgentToAgentPolicy(cfg) };
          requested.guard = guard;
          const access = await withGateway(() => resolveAccess(guard));
          const target = { agentId: targetAgentId, sessionKey: read.targetSessionKey };
          const current = sessions.getSessionEntry({ ...target,
            storePath: sessions.resolveStorePath(cfg.session.store, { agentId: targetAgentId }) });
          const result = { id: read.id, access, events: [] };
          if (access.allowed && current?.sessionId) {
            if (access.expectedSessionId && access.expectedSessionId !== current.sessionId) {
              throw Error(`Session "${read.targetSessionKey}" changed after access was granted.`);
            }
            const reader = { ...target, sessionId: current.sessionId,
              storePath: sessions.resolveStorePath(cfg.session.store, { agentId: targetAgentId }) };
            requested.reader = reader;
            result.events = await transcript.readSessionTranscriptEvents(reader);
            if (access.expectedSessionId && sessions.getSessionEntry({ ...target,
              storePath: sessions.resolveStorePath(cfg.session.store, { agentId: targetAgentId }) })?.sessionId !== access.expectedSessionId) {
              throw Error(`Session "${read.targetSessionKey}" changed after access was granted.`);
            }
            result.sessionId = current.sessionId;
          }
          raw.reads.push({ step: step.label, ...result }); reads.push(result);
        } catch (error) {
          const result = { id: read.id, error: publicError(error) };
          raw.reads.push({ step: step.label, ...result }); reads.push(result);
        }
      }
      const policy = ingestion.s(input.pluginConfig);
      const ingestionDecisions = catalog.map((entry) => {
        const source = ingestion.u(entry);
        return { source, ...(source ? { reason: ingestion.l(source, policy) } : {}) };
      });
      const participantRecords = Object.fromEntries(accessor.listSessionParticipantsReadOnly({ agentId,
        storePath: sessions.resolveStorePath(cfg.session.store, { agentId }) }));
      const snapshot = { label: step.label, catalog, admitted, sourceEntries, published, indexSources, queries, reads,
        ingestionDecisions, participantRecords };
      raw.snapshots.push({ ...snapshot, fullSql, sessionSql: sessionSql(manager.db) }); outputs.push(snapshot);
    }
    return mapGetFixturePaths({ provider: "none", steps: outputs }, directory);
  } finally {
    mock.timers.reset();
    await manager?.close(); await closeManagers?.(); await projection?.dispose(); clearConfig?.();
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}
