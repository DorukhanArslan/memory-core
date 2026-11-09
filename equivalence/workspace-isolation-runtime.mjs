// One genuine host configuration selects all workspaces, managers and state
// owners. Inputs are literal writes/requests, never expected isolation decisions.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";

const publicError = (error) => ({ name: error.name, message: error.message,
  ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) =>
    !["name", "message", "stack"].includes(key)).map((key) => [key, error[key]])) });
const sqliteValue = (value) => value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
  : typeof value === "bigint" ? { type: "bigint", value: value.toString() } : value;
function fullSql(db) {
  return Object.fromEntries(db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()
    .map(({ name }) => {
      if (!/^[A-Za-z0-9_]+$/.test(name)) throw Error("Unexpected diagnostic SQLite table name");
      return [name, { columns: db.prepare(`PRAGMA table_info("${name}")`).all(),
        rows: db.prepare(`SELECT * FROM "${name}"`).all().map((row) =>
          Object.fromEntries(Object.entries(row).map(([key, value]) => [key, sqliteValue(value)]))) }];
    }));
}
async function sqliteFiles(root) {
  const files = [];
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const filename = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...await sqliteFiles(filename));
    else if (entry.isFile() && /\.sqlite(?:3)?$/.test(entry.name)) files.push(filename);
  }
  return files;
}
function published(db) {
  return db.prepare("SELECT c.path,c.source,c.start_line AS startLine,c.end_line AS endLine,c.text," +
    "r.importance,r.triggers,r.project_key AS projectKey,p.origin_class AS originClass,p.session_kind AS sessionKind," +
    "p.observed_at AS observedAt,p.supersedes_key AS supersedesKey FROM memory_index_chunks c " +
    "LEFT JOIN memory_index_chunk_recall_metadata r ON r.chunk_id=c.id " +
    "LEFT JOIN memory_index_chunk_provenance p ON p.chunk_id=c.id " +
    "ORDER BY c.source,c.path,c.start_line,c.end_line,c.text,c.id").all()
    .map(({ originClass, sessionKind, observedAt, supersedesKey, ...row }) =>
      ({ ...row, provenance: { originClass, sessionKind, observedAt, supersedesKey } }));
}

export async function runWorkspaceIsolationRuntime(input, runtimeConfig) {
  if (input.kind !== "flow" || !Number.isFinite(input.nowMs) || !Array.isArray(input.owners) ||
      !input.owners.length || !Array.isArray(input.steps) ||
      !["explicit", "legacy-default"].includes(input.config?.layout) ||
      !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") || !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "")) {
    throw Error("Workspace isolation requires literal owners, phases, clock and authenticated runtime roots");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-workspace-isolation-"));
  const stateDirectory = path.join(directory, "state"), configPath = path.join(directory, "openclaw.json");
  await fs.mkdir(stateDirectory);
  const previousEnvironment = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = stateDirectory; process.env.OPENCLAW_CONFIG_PATH = configPath;
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: "flow", fixtureBase: directory, pid: process.pid, input,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    configuration: null, workspaceResolutions: [], managerAcquisitions: [], writes: [], removals: [],
    ledgerWrites: [], recallRequests: [], nativeSearchEnvelopes: [], nativeGetEnvelopes: [], snapshots: [] };
  const managers = new Map(), owners = new Map();
  let closeManagers, clearConfig;
  function ownedFilename(root, relative) {
    if (typeof relative !== "string" || path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
      throw Error("Literal paths must remain inside their owned workspace");
    }
    return path.join(root, relative);
  }
  const owner = (agentId) => {
    const value = owners.get(agentId);
    if (!value) throw Error(`Unknown declared workspace owner ${agentId}`);
    return value;
  };
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  try {
    const foundation = await imp("dist/plugin-sdk/memory-core-host-engine-foundation.js");
    const hostConfig = await imp("dist/config-utils-DioOBKyj.mjs");
    const storage = await imp("dist/plugin-sdk/memory-core-host-engine-storage.js");
    const { createMemorySearchTool, createMemoryGetTool } = await imp("dist/tools-DotaQGXh.mjs");
    const configRuntime = await imp("dist/plugin-sdk/config-runtime.js");
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js");
    closeManagers = runtime.closeAllMemoryIndexManagers;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    const recallOwner = await imp("dist/short-term-promotion-record-DrLa1fiO.mjs");
    const recallStore = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
    const ingestion = await imp("dist/dreaming-ingestion-state-licbtf_y.mjs");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const first = input.owners[0];
    const agentEntries = input.owners.map((item, index) => ({ id: item.agentId, ...(index === 0 ? { default: true } : {}),
      ...(input.config.layout === "explicit" ? { workspace: ownedFilename(directory, item.workspace) } : {}) }));
    const cfg = { agents: { defaults: { workspace: input.config.layout === "legacy-default"
      ? ownedFilename(directory, first.workspace) : directory }, list: agentEntries },
      logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
      plugins: { entries: { "memory-core": { config: { dreaming: { enabled: false } } } } },
      memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"],
        store: { vector: { enabled: false } }, sync: { onSessionStart: false, onSearch: false, watch: false },
        query: { minScore: 0, maxResults: 200, hybrid: { temporalDecay: { enabled: false } } } } } };
    raw.configuration = cfg;
    await fs.writeFile(configPath, JSON.stringify(cfg));
    configRuntime.setRuntimeConfigSnapshot(cfg); clearConfig = configRuntime.clearRuntimeConfigSnapshot;
    for (const item of input.owners) {
      if (owners.has(item.agentId)) throw Error("Declared workspace owners must be unique");
      const workspace = foundation.resolveAgentWorkspaceDir(cfg, item.agentId);
      const hostWorkspace = hostConfig.i(cfg, item.agentId);
      raw.workspaceResolutions.push({ agentId: item.agentId, requestedWorkspace: ownedFilename(directory, item.workspace),
        engineWorkspace: workspace, hostWorkspace, settings: foundation.resolveMemorySearchConfig(cfg, item.agentId) });
      await fs.mkdir(workspace, { recursive: true });
      owners.set(item.agentId, { ...item, workspace });
    }
    async function acquire(agentId, reason) {
      const manager = await runtime.MemoryIndexManager.get({ cfg, agentId });
      if (!manager) throw Error(`The genuine provider-none manager is unavailable for ${agentId}`);
      managers.set(agentId, manager);
      raw.managerAcquisitions.push({ agentId, reason, workspace: owner(agentId).workspace,
        settingsDatabasePath: foundation.resolveMemorySearchConfig(cfg, agentId).store.databasePath,
        status: manager.status() });
      return manager;
    }
    async function write(item, label) {
      const selected = owner(item.agentId), filename = ownedFilename(selected.workspace, item.path);
      await fs.mkdir(path.dirname(filename), { recursive: true }); await fs.writeFile(filename, item.text);
      await fs.utimes(filename, input.nowMs / 1000, input.nowMs / 1000);
      raw.writes.push({ label, input: item, selectedWorkspace: selected.workspace, filename });
    }
    for (const item of input.files ?? []) await write(item, "initial");
    for (const item of input.owners) await acquire(item.agentId, "initial");
    const steps = [];
    for (const step of input.steps) {
      for (const item of step.writes ?? []) await write(item, step.label);
      for (const item of step.removeFiles ?? []) {
        const selected = owner(item.agentId), filename = ownedFilename(selected.workspace, item.path);
        await fs.unlink(filename); raw.removals.push({ label: step.label, input: item, filename });
      }
      for (const agentId of step.reopenAgents ?? []) { await managers.get(agentId).close(); await acquire(agentId, step.label); }
      for (const agentId of step.syncAgents ?? []) {
        const manager = managers.get(agentId); owner(agentId);
        manager.markMemoryWatchDirty(); await manager.sync({ reason: "workspace-isolation", force: true });
      }
      for (const item of step.maintenanceWrites ?? []) {
        const selected = owner(item.agentId);
        await ingestion.u(selected.workspace, ingestion.i(item.state));
        raw.ledgerWrites.push({ label: step.label, input: item, selectedWorkspace: selected.workspace });
      }
      const queries = new Map(input.owners.map((item) => [item.agentId, []]));
      const reads = new Map(input.owners.map((item) => [item.agentId, []]));
      for (const query of step.queries ?? []) {
        const selected = owner(query.agentId), manager = managers.get(query.agentId);
        const options = { maxResults: 200, minScore: 0, sources: ["memory"] };
        const candidates = await manager.search(query.query, options);
        const tool = createMemorySearchTool({ config: cfg, agentId: query.agentId });
        if (!tool) throw Error("The genuine memory_search tool is unavailable");
        const envelope = await tool.execute(query.id, { query: query.query, maxResults: 200, minScore: 0 });
        raw.nativeSearchEnvelopes.push({ label: step.label, input: query, options, candidates, envelope });
        const result = decodeSearchToolEnvelope(envelope);
        if (query.recordRecall) {
          const request = { workspaceDir: selected.workspace, query: query.query, results: candidates, nowMs: input.nowMs };
          await recallOwner.i(request);
          raw.recallRequests.push({ label: step.label, agentId: query.agentId, request });
        }
        queries.get(query.agentId).push({ id: query.id, candidates, result });
      }
      for (const read of step.reads ?? []) {
        owner(read.agentId);
        const tool = createMemoryGetTool({ config: cfg, agentId: read.agentId });
        if (!tool) throw Error("The genuine memory_get tool is unavailable");
        try {
          const envelope = await tool.execute(read.id, { path: read.path });
          raw.nativeGetEnvelopes.push({ label: step.label, input: read, envelope });
          reads.get(read.agentId).push({ id: read.id, result: decodeSearchToolEnvelope(envelope) });
        } catch (error) {
          const detail = publicError(error); raw.nativeGetEnvelopes.push({ label: step.label, input: read, error: detail });
          reads.get(read.agentId).push({ id: read.id, error: detail });
        }
      }
      const snapshots = [], publicOwners = [];
      for (const selected of owners.values()) {
        const manager = managers.get(selected.agentId);
        const paths = await storage.listMemoryFiles(selected.workspace);
        const files = await Promise.all(paths.map(async (filename) => ({
          path: path.relative(selected.workspace, filename).split(path.sep).join("/"), text: await fs.readFile(filename, "utf8") })));
        const observable = { agentId: selected.agentId, workspace: selected.workspace, files,
          published: published(manager.db),
          indexSources: manager.db.prepare("SELECT path,source FROM memory_index_sources ORDER BY source,path").all(),
          queries: queries.get(selected.agentId), reads: reads.get(selected.agentId),
          recallStore: await recallStore.a(selected.workspace, new Date(input.nowMs).toISOString()),
          dailyIngestionState: await ingestion.c(selected.workspace) };
        publicOwners.push(observable);
        snapshots.push({ ...observable, status: manager.status(), fullSql: fullSql(manager.db) });
      }
      const pluginStateSql = [];
      for (const filename of await sqliteFiles(stateDirectory)) {
        const db = new DatabaseSync(filename, { readOnly: true });
        try { pluginStateSql.push({ filename, fullSql: fullSql(db) }); } finally { db.close(); }
      }
      const snapshot = { label: step.label, owners: snapshots, pluginStateSql };
      raw.snapshots.push(snapshot); steps.push({ label: step.label, owners: publicOwners });
    }
    const result = { provider: "none", steps }; raw.result = result;
    return mapGetFixturePaths(result, directory);
  } catch (error) {
    raw.failure = { ...publicError(error), stack: error.stack }; throw error;
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    await Promise.allSettled([...managers.values()].map((manager) => manager.close()));
    await closeManagers?.(); clearConfig?.(); mock.timers.reset();
    for (const [key, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}
