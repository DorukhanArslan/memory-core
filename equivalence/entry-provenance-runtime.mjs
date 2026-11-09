// Genuine preparation/publication owners over literal files and persisted sessions.
// This adapter supplies no chunk hash, identity, provenance or invalidation policy.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

function physical(db) {
  const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
  return { schema, tables: schema.filter(row => row.type === "table").map(row => ({ name: row.name,
    rows: db.prepare('SELECT * FROM "' + row.name.replaceAll('"', '""') + '"').all().map(row =>
      Object.fromEntries(Object.entries(row).map(([key, value]) => [key,
        value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) })) };
}

function logical(db, decode) {
  const chunks = db.prepare("SELECT id,path,source,start_line AS startLine,end_line AS endLine,text,hash,model,updated_at AS updatedAt,embedding FROM memory_index_chunks ORDER BY id").all();
  const provenance = db.prepare("SELECT chunk_id AS chunkId,origin_class AS originClass,session_kind AS sessionKind,observed_at AS observedAt,supersedes_key AS supersedesKey FROM memory_index_chunk_provenance ORDER BY chunk_id").all();
  const recall = db.prepare("SELECT chunk_id AS chunkId,importance,triggers,project_key AS projectKey FROM memory_index_chunk_recall_metadata ORDER BY chunk_id").all();
  const byId = rows => new Map(rows.map(({ chunkId, ...row }) => [chunkId, row]));
  const origins = byId(provenance), annotations = byId(recall);
  return { sources: db.prepare("SELECT path,source,hash,mtime,size FROM memory_index_sources ORDER BY source,path").all(),
    chunks: chunks.map(row => ({ ...row, embedding: decode(row.embedding), provenance: origins.get(row.id), recall: annotations.get(row.id) })),
    provenance, recall, details: chunks.map(row => ({ chunkId: row.id, hash: row.hash, model: row.model, updatedAt: row.updatedAt })),
    fts: db.prepare("SELECT id,text,path,source,start_line AS startLine,end_line AS endLine,model FROM memory_index_chunks_fts ORDER BY id,text").all(),
    paths: db.prepare("SELECT path,source FROM memory_index_paths_fts ORDER BY source,path").all() };
}

export async function runEntryProvenanceRuntime(input, runtimeConfig) {
  if (!["published-memory", "prepared-provider", "session-projection"].includes(input.kind))
    throw Error("An explicit bounded entry-provenance profile is required");
  if (![runtimeConfig?.runtimeRoot, runtimeConfig?.evidenceDirectory].every(value =>
      typeof value === "string" && path.isAbsolute(value)))
    throw Error("Entry provenance requires absolute authenticated runtime and evidence paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-entry-provenance-"));
  const workspace = path.join(base, "workspace"); await fs.mkdir(workspace);
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME"].map(name => [name, process.env[name]]));
  Object.assign(process.env, { OPENCLAW_STATE_DIR: path.join(base, "state"), OPENCLAW_CONFIG_PATH: path.join(base, "openclaw.json"), OPENCLAW_HOME: base });
  const cfg = { agents: { defaults: { workspace } }, logging: { level: "silent", consoleLevel: "silent", file: path.join(base, "native.log") },
    session: { maintenance: { mode: "warn" } }, memory: { search: { enabled: true, provider: "none", fallback: "none",
      sources: input.kind === "session-projection" ? ["sessions"] : ["memory"], rememberAcrossConversations: true,
      experimental: { sessionMemory: true }, store: { vector: { enabled: false } } } } };
  await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
  const now = input.nowMs ?? input.steps[0].nowMs, originalDate = Date, originalTimeout = setTimeout;
  mock.timers.enable({ apis: ["Date"], now });
  const raw = { kind: input.kind, fixtureBase: base, input, config: cfg, pid: process.pid, calls: [], snapshots: [], preparations: [], providerCalls: [],
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate, setTimeoutUnchanged: setTimeout === originalTimeout } };
  const imp = file => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, file)).href);
  let manager, clearConfig, closeManagers;
  async function write(files) {
    for (const [relative, content] of Object.entries(files ?? {})) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) throw Error("Source files must remain owned");
      const filename = path.join(workspace, relative); await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, content); await fs.utimes(filename, input.mtimeMs / 1000, input.mtimeMs / 1000);
      raw.calls.push({ operation: "write", relative, content, mtimeMs: input.mtimeMs });
    }
  }
  try {
    const config = await imp("dist/plugin-sdk/config-runtime.js"); config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js"); closeManagers = runtime.closeAllMemoryIndexManagers;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState(options => createPluginStateKeyedStore("memory-core", options));
    const storage = await imp("dist/plugin-sdk/memory-core-host-engine-storage.js");
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js"), accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const scope = item => ({ agentId: "main", storePath: sessions.resolveStorePath(undefined, { agentId: "main" }), sessionKey: item.sessionKey ?? input.sessionKey, sessionId: item.entry?.sessionId ?? item.sessionId ?? input.sessionId });
    for (const item of input.sessions ?? []) {
      const target = scope(item); const result = await sessions.upsertSessionEntry({ ...target, entry: item.entry });
      raw.calls.push({ operation: "upsertSessionEntry", target, entry: item.entry, returnedUndefined: result === undefined });
      const replaced = await accessor.replaceTranscriptEvents(target, item.events);
      raw.calls.push({ operation: "replaceTranscriptEvents", target, events: item.events,
        ...(replaced === undefined ? { returnedUndefined: true } : { result: replaced }) });
    }
    await write(input.files);
    manager = await runtime.MemoryIndexManager.get({ cfg, agentId: "main", purpose: "cli" });
    if (!manager) throw Error("The actual provider-none manager was unavailable");
    raw.calls.push({ operation: "get", cfg, agentId: "main", purpose: "cli", status: manager.status() });
    if (input.kind === "prepared-provider") {
      await write({ [input.path]: input.content });
      const filename = path.join(workspace, input.path), entry = await storage.buildFileEntry(filename, workspace);
      const { t: classify } = await imp("dist/memory-path-provenance-C84vBRrO.mjs");
      const classification = await classify({ absolutePath: filename, source: "memory", workspaceDir: workspace });
      const request = { entry, source: "memory", content: await fs.readFile(filename, "utf8"), pathClassification: classification,
        chunking: input.chunking, hardMaxInputTokens: input.hardMaxInputTokens, provider: input.provider };
      const { t: prepare } = await imp("dist/manager-index-preparation-wXpJtJiU.mjs");
      const prepared = prepare(request); raw.preparations.push({ request, result: structuredClone(prepared) });
      const embeddings = prepared.chunks.map(chunk => { const result = structuredClone(input.embeddingVector); raw.providerCalls.push({ input: chunk.embeddingInput, result }); return result; });
      const { t: Kernel } = await imp("dist/manager-source-index-kernel-D-njga00.mjs");
      const sql = await imp("dist/plugin-sdk/sqlite-runtime.js");
      const header = { entry: { path: entry.path, hash: prepared.contentHash, mtimeMs: entry.mtimeMs, size: entry.size }, source: "memory", model: input.provider.model, now, vectorReady: false };
      raw.calls.push({ operation: "replaceRows", header, chunks: structuredClone(prepared.chunks), embeddings });
      sql.runSqliteImmediateTransactionSync(manager.db, () => new Kernel(manager.db, { vector: manager.vector, fts: manager.fts }).replaceRows(header,
        prepared.chunks.map((chunk, index) => ({ chunk, embedding: embeddings[index] }))));
      const state = logical(manager.db, storage.decodeMemoryEmbedding);
      raw.snapshots.push({ state, physical: physical(manager.db) });
      const fragments = prepared.chunks.map(chunk => {
        const persisted = state.chunks.find(row => row.startLine === chunk.startLine && row.endLine === chunk.endLine && row.hash === chunk.hash && row.text === chunk.text);
        if (!persisted) throw Error("An actual prepared fragment lost its published canonical identity");
        return { id: persisted.id, startLine: chunk.startLine, endLine: chunk.endLine,
          ...(chunk.entryStartLine === undefined ? {} : { entryStartLine: chunk.entryStartLine, entryEndLine: chunk.entryEndLine }),
          text: chunk.text, hash: chunk.hash, provenance: persisted.provenance, recall: persisted.recall };
      });
      return { provider: "none", contentHash: prepared.contentHash, fragments, state };
    }
    const steps = [];
    const engine = await imp("dist/plugin-sdk/memory-core-host-engine-sessions.js"), { a: readCutoff } = await imp("dist/session-files-DVVT4Ngb.mjs");
    for (const step of input.steps) {
      mock.timers.setTime(step.nowMs); await write(step.write);
      if (step.events) {
        const target = scope({}); const replaced = await accessor.replaceTranscriptEvents(target, step.events);
        raw.calls.push({ operation: "replaceTranscriptEvents", target, events: step.events,
          ...(replaced === undefined ? { returnedUndefined: true } : { result: replaced }) });
      }
      manager.markMemoryWatchDirty(); raw.calls.push({ operation: "markMemoryWatchDirty", label: step.label });
      const request = { reason: "entry-provenance-fixture", force: step.force ?? false,
        ...(step.syncSessions ? { sessions: step.syncSessions } : {}) };
      const result = await manager.sync(request); raw.calls.push({ operation: "sync", request, returnedUndefined: result === undefined, label: step.label });
      const state = logical(manager.db, storage.decodeMemoryEmbedding), sources = [];
      if (input.kind === "session-projection") {
        for (const source of await manager.listSessionCorpusEntries()) {
          const options = manager.buildSessionEntryOptions(source), entry = await engine.buildSessionEntry(source.sessionFile, options);
          sources.push({ source, entry, resetRecallCutoff: readCutoff(entry) });
          raw.calls.push({ operation: "buildSessionEntry", source, options, entry, resetRecallCutoff: readCutoff(entry) });
        }
      }
      const snapshot = { label: step.label, state, sources };
      steps.push(snapshot); raw.snapshots.push({ ...snapshot, physical: physical(manager.db) });
    }
    return mapGetFixturePaths({ provider: "none", steps }, base);
  } finally {
    await manager?.close(); raw.calls.push({ operation: "close", completed: true }); await closeManagers?.(); clearConfig?.(); mock.timers.reset();
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [name, value] of Object.entries(prior)) { if (value === undefined) delete process.env[name]; else process.env[name] = value; }
    await fs.rm(base, { recursive: true, force: true });
  }
}
