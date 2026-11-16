// Real bundled hooks, transcript storage, trust publication and memory tools.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { gzipSync } from "node:zlib";
import { isDeepStrictEqual } from "node:util";

const HANDLER = "dist/bundled/session-memory/handler.js";
const MANAGER = "dist/extensions/memory-core/manager-runtime.js";
const RECALL_MODULE = "dist/short-term-promotion-record-CEpBdgKW.mjs";
const PREPARATION_MODULE = "dist/dreaming-dreams-file-BJzlZFlf.mjs";
const AUDIT = "reset_boundary_trust_audit";
const TRUST_PREDICATE = "plugin_id='core:memory-artifact-provenance' AND namespace='workspace-files'";
const sha = value => createHash("sha256").update(value).digest("hex");
const clone = value => JSON.parse(JSON.stringify(value));
const bytes = value => ({ hex: value.toString("hex"), sha256: sha(value), size: value.length });
const ordered = values => values.sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
function wire(value, seen = new Map()) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", value: String(value) };
  if (typeof value === "function") return { type: "function", name: value.name, source: Function.prototype.toString.call(value) };
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return { type: "reference", target: seen.get(value) };
  seen.set(value, seen.size);
  if (value instanceof Date) return { type: "Date", epochMs: value.getTime(), iso: value.toISOString() };
  if (value instanceof Uint8Array) return { type: "bytes", ...bytes(Buffer.from(value)) };
  if (value instanceof AbortSignal) return { type: "AbortSignal", aborted: value.aborted, reason: wire(value.reason, seen) };
  if (Array.isArray(value)) return value.map(item => wire(item, seen));
  return { ...(value instanceof Error ? { name: value.name, message: value.message } : {}),
    ...Object.fromEntries(Reflect.ownKeys(value).map(key => [String(key), wire(value[key], seen)])) };
}
const returned = value => ({ type: value === undefined ? "undefined" : typeof value,
  ...(value === undefined ? {} : { value: wire(value) }) });
function owned(root, relative) {
  if (typeof relative !== "string" || !relative || relative.includes("\\") || path.posix.isAbsolute(relative) ||
      path.posix.normalize(relative) !== relative || relative.split("/").some(part => [".", ".."].includes(part)))
    throw Error("A reset fixture path must be canonical and owned");
  const filename = path.resolve(root, relative);
  if (!filename.startsWith(path.resolve(root) + path.sep)) throw Error("A reset fixture escaped its owner");
  return filename;
}
async function tree(root, identities = false) {
  const files = {};
  async function walk(directory) {
    let entries;
    try { entries = await fs.readdir(directory, { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const name of ordered(entries.map(entry => entry.name))) {
      const entry = entries.find(item => item.name === name), filename = path.join(directory, name);
      if (entry.isSymbolicLink()) throw Error("Reset source evidence contains a symbolic link");
      if (entry.isDirectory()) await walk(filename);
      else if (entry.isFile()) {
        const payload = await fs.readFile(filename), relative = path.relative(root, filename).split(path.sep).join("/");
        if (identities) {
          const stat = await fs.lstat(filename, { bigint: true });
          files[relative] = { path: filename, bytes: bytes(payload), identity: { device: String(stat.dev), inode: String(stat.ino),
            mode: String(stat.mode), nlink: String(stat.nlink), uid: String(stat.uid), gid: String(stat.gid),
            size: String(stat.size), mtimeNs: String(stat.mtimeNs), ctimeNs: String(stat.ctimeNs) } };
        } else files[relative] = payload;
      }
    }
  }
  await walk(root); return files;
}
function database(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try {
    db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
    const rows = sql => db.prepare(sql).all().map(row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
      [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
        : typeof value === "bigint" ? { type: "bigint", value: String(value) } : value])));
    const schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name");
    return { schema, tables: Object.fromEntries(schema.filter(row => row.type === "table").map(row =>
      [row.name, rows('SELECT * FROM "' + row.name.replaceAll('"', '""') + '"')])),
    transaction: { mode: "deferred", active: db.isTransaction } };
  } finally { if (db.isTransaction) db.exec("ROLLBACK"); db.close(); }
}
async function physical(root) {
  const files = await tree(root), databases = {};
  for (const [name, payload] of Object.entries(files))
    if (payload.subarray(0, 16).equals(Buffer.from("SQLite format 3\0"))) databases[name] = database(path.join(root, name));
  return { root, files: Object.fromEntries(Object.entries(files).map(([name, payload]) => [name, bytes(payload)])), databases, links: {} };
}

export async function runSessionResetBoundariesRuntime(input, runtimeConfig) {
  if (input?.kind !== "session-reset-boundaries" || input.provider !== "none" || input.llmSlug !== false ||
      !Number.isSafeInteger(input.nowMs) || !input.sessions || !Array.isArray(input.operations))
    throw Error("Reset boundaries require their frozen common input");
  for (const name of ["runtimeRoot", "stateDirectory", "configPath", "evidenceDirectory"])
    if (typeof runtimeConfig?.[name] !== "string" || !path.isAbsolute(runtimeConfig[name]))
      throw Error("Reset boundaries require authenticated absolute runtime paths");
  if (input.preconditions?.nonRootPosix && (process.platform === "win32" || process.getuid?.() === 0))
    throw Error("The approved publication permission fault requires a non-root POSIX process");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-session-reset-"));
  const workspace = path.join(base, "workspace"), agentDir = path.join(base, "agent");
  await fs.mkdir(workspace); await fs.mkdir(agentDir); await fs.mkdir(path.join(workspace, "memory"));
  const storePath = path.join(base, "sessions.json"), logPath = path.join(base, "native.log");
  const environment = { OPENCLAW_STATE_DIR: runtimeConfig.stateDirectory, OPENCLAW_CONFIG_PATH: runtimeConfig.configPath,
    OPENCLAW_HOME: base, FS_SAFE_NATIVE_MODE: "require" };
  const previous = Object.fromEntries(Object.keys(environment).map(name => [name, process.env[name]]));
  Object.assign(process.env, environment);
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const cfg = { logging: { level: "debug", consoleLevel: "silent", file: logPath },
    agents: { defaults: { workspace, userTimezone: input.timezone },
      list: [{ id: input.agentId, default: true, workspace, agentDir }] },
    hooks: { internal: { enabled: true, entries: { "session-memory": { enabled: true, llmSlug: false } } } },
    session: { store: storePath, maintenance: { mode: "warn" } },
    memory: { citations: "auto", search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"],
      rememberAcrossConversations: false, experimental: { sessionMemory: false }, store: { vector: { enabled: false } },
      query: { maxResults: 6, minScore: 0 } } } };
  if (Object.hasOwn(input, "messages")) cfg.hooks.internal.entries["session-memory"].messages = input.messages;
  await fs.mkdir(path.dirname(runtimeConfig.configPath), { recursive: true });
  await fs.writeFile(runtimeConfig.configPath, JSON.stringify(cfg) + "\n");
  const raw = { kind: "session-reset-boundaries-native-raw", input: clone(input), request: clone(input), fixtureBase: base,
    workspace, stateDirectory: runtimeConfig.stateDirectory, runtimeRoot: runtimeConfig.runtimeRoot,
    configPath: runtimeConfig.configPath, config: clone(cfg), environment, storePath, logPath,
    pid: process.pid, ppid: process.ppid, node: { version: process.version, executable: process.execPath },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    calls: [], codeOwners: [], transcriptSeeds: [], operations: [], states: [], physical: [], toolEnvelopes: [], recallDrains: [],
    closeReceipts: [], closed: false };
  const imp = relative => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let operationIndex = -1, configRuntime, hooks, handler, flush, closeManagers, closeAgents, closeState,
    managerRuntime, manager, stateHandle, statePath, agentPath, listProvenance, sessions, captureTranscript,
    searchTool, getTool, flushLogs, preparationBarrier;
  const toolCalls = [];
  async function owner(modulePath, exportName, name, fn) {
    if (typeof fn !== "function") throw Error("A pinned reset owner is unavailable: " + name);
    const source = Function.prototype.toString.call(fn);
    raw.codeOwners.push({ name, modulePath, exportName, functionName: fn.name, functionLength: fn.length,
      functionSource: source, functionSourceSha256: sha(source),
      compiledSha256: sha(await fs.readFile(path.join(runtimeConfig.runtimeRoot, modulePath))) });
  }
  async function call(operation, fn, args) {
    const row = { operation, operationIndex, arguments: wire(args) }; raw.calls.push(row);
    try { const result = await fn(...args); row.returnValue = returned(result); return result; }
    catch (error) { row.error = wire(error); throw error; }
  }
  async function logBytes() {
    if (flushLogs) await call("flushLogger", flushLogs, []);
    try { return bytes(await fs.readFile(logPath)); } catch (error) { if (error.code === "ENOENT") return null; throw error; }
  }
  async function artifactFiles() {
    return Object.fromEntries(Object.entries(await tree(workspace)).filter(([name]) => name.startsWith("memory/") && name.endsWith(".md"))
      .map(([name, payload]) => [name, payload.toString("utf8")]));
  }
  function auditRows() { return stateHandle.db.prepare(`SELECT * FROM ${AUDIT} ORDER BY seq`).all().map(row => ({ ...row })); }
  async function state() {
    const orderedProvenanceRows = await call("listMemoryArtifactProvenance", listProvenance, [{ workspaceDir: workspace }]);
    const provenance = {};
    for (const row of orderedProvenanceRows) {
      if (Object.hasOwn(provenance, row.relativePath)) throw Error("A duplicate trust path reached the business map");
      provenance[row.relativePath] = clone(row.provenance);
    }
    const value = { files: await artifactFiles(), provenance, toolCalls: clone(toolCalls) };
    raw.states.push({ operationIndex, state: clone(value), orderedProvenanceRows: clone(orderedProvenanceRows),
      rawSql: { state: database(statePath), agent: database(agentPath) }, auditRows: auditRows(),
      sources: await tree(workspace, true), logBytes: await logBytes() });
    return value;
  }
  async function capture(label) {
    const value = { fixture: await physical(base), state: await physical(runtimeConfig.stateDirectory),
      config: bytes(await fs.readFile(runtimeConfig.configPath)) };
    const payload = JSON.stringify(value) + "\n", filename = path.join(runtimeConfig.evidenceDirectory, `native-physical-${label}.json`);
    await fs.writeFile(filename, payload);
    raw.physical.push({ path: filename, sha256: sha(payload), uncompressedBytes: Buffer.byteLength(payload),
      encoding: "gzip-json-base64", data: gzipSync(Buffer.from(payload)).toString("base64") });
  }
  async function executeTool(toolName, args) {
    const tool = toolName === "memory_search" ? searchTool : getTool;
    const envelope = await call(toolName + ".execute", (id, params) => tool.execute(id, params),
      ["reset-boundary-" + operationIndex + "-" + toolCalls.length, args]);
    const transported = clone(envelope), parsed = JSON.parse(transported.content[0].text);
    if (!isDeepStrictEqual(parsed, transported.details)) throw Error("A whole memory tool carrier disagrees with its details");
    raw.toolEnvelopes.push({ operationIndex, tool: toolName, arguments: clone(args), envelope: transported, decoded: clone(parsed) });
    toolCalls.push({ tool: toolName, arguments: clone(args), result: parsed });
    if (toolName === "memory_search") {
      const drain = { operationIndex, importPath: RECALL_MODULE }; raw.recallDrains.push(drain);
      const namespace = await call("importOriginalRecallModule", () => imp(RECALL_MODULE), []);
      drain.moduleObservation = wire(namespace);
      drain.preparationReturn = returned(await call("withMemoryWorkspacePreparation", preparationBarrier,
        [workspace, async () => undefined]));
    }
    return envelope;
  }
  try {
    for (const [relative, text] of Object.entries(input.files)) {
      const target = owned(workspace, relative); await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, text);
    }
    configRuntime = await imp("dist/plugin-sdk/config-runtime.js");
    await call("setRuntimeConfigSnapshot", configRuntime.setRuntimeConfigSnapshot, [cfg]);
    flushLogs = (await imp("dist/logger-Cn5hoa7J.mjs")).n;
    const { w: setRegistry } = await imp("dist/runtime-9cxii0oQ.mjs");
    const { t: emptyRegistry } = await imp("dist/registry-empty-BTjzcMW2.mjs");
    await call("setActivePluginRegistry", setRegistry, [emptyRegistry(), "startup-registry", "gateway-bindable", workspace]);
    const dreaming = await imp("dist/dreaming-state-VYUvbU-n.mjs"), keyed = await imp("dist/plugin-state-store-BPUaLoVD.mjs");
    closeState = keyed.u;
    await call("configureMemoryCoreDreamingState", dreaming.p, [options => keyed.r("memory-core", { ...options, env: environment })]);
    raw.recallModulePreload = wire(await call("importOriginalRecallModule", () => imp(RECALL_MODULE), []));
    preparationBarrier = (await imp(PREPARATION_MODULE))._;
    const shared = await imp("dist/openclaw-state-db-Dh2awMJ8.mjs");
    stateHandle = shared.r({ env: environment }); statePath = stateHandle.path;
    raw.calls.push({ operation: "openOpenClawStateDatabase", arguments: [{ env: clone(environment) }],
      nativeHandleObservation: { path: stateHandle.path, databaseConstructor: stateHandle.db.constructor.name, isOpen: stateHandle.db.isOpen } });
    const auditStatements = [
      `CREATE TABLE ${AUDIT}(seq INTEGER PRIMARY KEY,event TEXT NOT NULL,store_key TEXT NOT NULL,old_value TEXT,new_value TEXT)`,
      ...["INSERT", "UPDATE", "DELETE"].map(event => {
        const selected = event === "DELETE" ? "OLD" : "NEW";
        return `CREATE TRIGGER reset_boundary_trust_${event.toLowerCase()} AFTER ${event} ON plugin_state_entries WHEN ${selected}.plugin_id='core:memory-artifact-provenance' AND ${selected}.namespace='workspace-files' BEGIN INSERT INTO ${AUDIT}(event,store_key,old_value,new_value) VALUES('${event.toLowerCase()}',${selected}.entry_key,${event === "INSERT" ? "NULL" : "OLD.value_json"},${event === "DELETE" ? "NULL" : "NEW.value_json"}); END`;
      }),
    ];
    for (const statement of auditStatements) stateHandle.db.exec(statement);
    raw.auditDefinition = { table: AUDIT, predicate: TRUST_PREDICATE, statements: auditStatements, databasePath: statePath,
      schema: database(statePath).schema };
    sessions = await imp("dist/session-accessor-CiKKTlbe.mjs");
    captureTranscript = (await imp("dist/capture-C0uwbnBj.mjs")).t;
    listProvenance = (await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs")).n;
    for (const [profile, session] of Object.entries(input.sessions)) {
      const scope = { agentId: input.agentId, sessionId: session.sessionId, sessionKey: input.sessionKey, storePath };
      const seed = { profile, scope, literalEvents: clone(session.events) }; raw.transcriptSeeds.push(seed);
      seed.returnValue = returned(await call("replaceTranscriptEvents", sessions.replaceTranscriptEvents, [scope, session.events]));
      seed.actualStoredEvents = await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]);
    }
    agentPath = (await imp("dist/openclaw-agent-db.paths-Dv3PPTNK.mjs")).c({ agentId: input.agentId });
    hooks = await imp("dist/internal-hooks-CwVYIajG.mjs");
    const hookModule = await imp(HANDLER); handler = hookModule.default; flush = hookModule.flushSessionMemoryWritesForTest;
    for (const key of ["command:new", "command:reset"]) await call("registerInternalHook", hooks.c, [key, handler]);
    managerRuntime = await imp(MANAGER); closeManagers = managerRuntime.closeAllMemoryIndexManagers;
    closeAgents = (await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s;
    const tools = await imp("dist/tools-DotaQGXh.mjs");
    const options = { config: cfg, agentId: input.agentId, agentSessionKey: input.sessionKey, oneShotCliRun: true };
    searchTool = await call("createMemorySearchTool", tools.createMemorySearchTool, [options]);
    getTool = await call("createMemoryGetTool", tools.createMemoryGetTool, [options]);
    if (!searchTool || !getTool) throw Error("The original memory tools were unavailable");
    raw.toolDefinitions = { search: { name: searchTool.name, parameters: wire(searchTool.parameters), description: searchTool.description },
      get: { name: getTool.name, parameters: wire(getTool.parameters), description: getTool.description }, options: clone(options) };
    for (const spec of [
      [HANDLER, "default", "saveSessionToMemory", handler], [HANDLER, "flushSessionMemoryWritesForTest", "flushSessionMemoryWritesForTest", flush],
      ["dist/internal-hooks-CwVYIajG.mjs", "c", "registerInternalHook", hooks.c],
      ["dist/internal-hooks-CwVYIajG.mjs", "n", "createInternalHookEvent", hooks.n],
      ["dist/internal-hooks-CwVYIajG.mjs", "u", "triggerInternalHook", hooks.u],
      ["dist/internal-hooks-CwVYIajG.mjs", "d", "unregisterInternalHook", hooks.d],
      ["dist/session-accessor-CiKKTlbe.mjs", "replaceTranscriptEvents", "replaceTranscriptEvents", sessions.replaceTranscriptEvents],
      ["dist/session-accessor-CiKKTlbe.mjs", "loadTranscriptEventsSync", "loadTranscriptEventsSync", sessions.loadTranscriptEventsSync],
      ["dist/session-accessor-CiKKTlbe.mjs", "replaceSessionEntry", "replaceSessionEntry", sessions.replaceSessionEntry],
      ["dist/session-accessor-CiKKTlbe.mjs", "loadSessionEntry", "loadSessionEntry", sessions.loadSessionEntry],
      ["dist/capture-C0uwbnBj.mjs", "t", "captureSessionMemoryTranscript", captureTranscript],
      ["dist/memory-artifact-provenance-DhnyWiV1.mjs", "n", "listMemoryArtifactProvenance", listProvenance],
      ["dist/tools-DotaQGXh.mjs", "createMemorySearchTool", "createMemorySearchTool", tools.createMemorySearchTool],
      ["dist/tools-DotaQGXh.mjs", "createMemoryGetTool", "createMemoryGetTool", tools.createMemoryGetTool],
      [MANAGER, "MemoryIndexManager", "MemoryIndexManager.get", managerRuntime.MemoryIndexManager.get],
      ["dist/openclaw-state-db-Dh2awMJ8.mjs", "r", "openOpenClawStateDatabase", shared.r],
      ["dist/dreaming-state-VYUvbU-n.mjs", "p", "configureMemoryCoreDreamingState", dreaming.p],
      ["dist/plugin-state-store-BPUaLoVD.mjs", "r", "createPluginStateKeyedStore", keyed.r],
      ["dist/plugin-state-store-BPUaLoVD.mjs", "u", "closePluginStateDatabaseAsync", closeState],
      [MANAGER, "closeAllMemoryIndexManagers", "closeAllMemoryIndexManagers", closeManagers],
      ["dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s", "closeOpenClawAgentDatabasesAsync", closeAgents],
      ["dist/logger-Cn5hoa7J.mjs", "n", "flushLogger", flushLogs],
      [PREPARATION_MODULE, "_", "withMemoryWorkspacePreparation", preparationBarrier],
    ]) await owner(...spec);
    raw.initialState = await state(); await capture("initial");
    const observations = [];
    for (operationIndex = 0; operationIndex < input.operations.length; operationIndex++) {
      const operation = input.operations[operationIndex]; mock.timers.setTime(operation.nowMs);
      const actual = { operation: clone(operation), sourcesBefore: await tree(workspace, true),
        logBefore: await logBytes(), auditBefore: auditRows(), sqlBefore: { state: database(statePath), agent: database(agentPath) } };
      raw.operations.push(actual);
      try {
        let result;
        if (operation.op === "hook") {
          const session = input.sessions[operation.session];
          if (!session) throw Error("The reset operation selected an unowned transcript profile");
          const scope = { agentId: input.agentId, sessionId: session.sessionId, sessionKey: input.sessionKey, storePath };
          const catalogScope = { agentId: input.agentId, sessionKey: input.sessionKey, storePath };
          actual.activation = { scope, catalogScope,
            previousEntry: await call("loadSessionEntry", sessions.loadSessionEntry, [catalogScope]) };
          actual.activation.entryReturn = returned(await call("replaceSessionEntry", sessions.replaceSessionEntry,
            [catalogScope, { sessionId: session.sessionId, updatedAt: operation.nowMs }]));
          actual.activation.transcriptReturn = returned(await call("replaceTranscriptEvents", sessions.replaceTranscriptEvents,
            [scope, session.events]));
          actual.activation.currentEntry = await call("loadSessionEntry", sessions.loadSessionEntry, [catalogScope]);
          actual.actualStoredEvents = await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]);
          actual.capture = await call("captureSessionMemoryTranscript", captureTranscript, [scope, cfg]);
          const context = { agentId: input.agentId, cfg, previousSessionEntry: { sessionId: session.sessionId },
            commandSource: operation.source, storePath, workspaceDir: workspace };
          const event = await call("createInternalHookEvent", hooks.n, ["command", operation.action, input.sessionKey, context]);
          actual.hookEvent = wire(event);
          result = await call("triggerInternalHook", hooks.u, [event]); actual.dispatchReturn = returned(result);
          actual.drainReturn = returned(await call("flushSessionMemoryWritesForTest", flush, []));
          actual.hookEventAfter = wire(event);
        } else if (operation.op === "sync") {
          actual.utimes = [];
          for (const relative of Object.keys(await artifactFiles())) {
            const filename = owned(workspace, relative), before = await fs.stat(filename, { bigint: true });
            const value = await fs.utimes(filename, operation.mtimeMs / 1000, operation.mtimeMs / 1000);
            const after = await fs.stat(filename, { bigint: true });
            actual.utimes.push({ path: relative, mtimeMs: operation.mtimeMs, returnValue: returned(value),
              before: { mtimeNs: String(before.mtimeNs), ctimeNs: String(before.ctimeNs) },
              after: { mtimeNs: String(after.mtimeNs), ctimeNs: String(after.ctimeNs) } });
          }
          if (manager) await call("MemoryIndexManager.close", () => manager.close(), []);
          const args = { cfg, agentId: input.agentId, purpose: "cli" };
          manager = await managerRuntime.MemoryIndexManager.get(args);
          if (!manager) throw Error("The original provider-none CLI manager was unavailable");
          raw.calls.push({ operation: "MemoryIndexManager.get", arguments: wire([args]), nativeHandleObservation: {
            constructor: manager.constructor.name, dbPath: manager.settings.store.databasePath, purpose: manager.purpose,
            settings: wire(manager.settings), isOpen: manager.db.isOpen } });
          if (!raw.managerMethods) {
            for (const name of ["sync", "search", "readFile", "close", "status"])
              await owner(MANAGER, "MemoryIndexManager", "MemoryIndexManager." + name, manager[name]);
            raw.managerMethods = true;
          }
          actual.arguments = { reason: "search-bootstrap", force: operation.force };
          result = await call("MemoryIndexManager.sync", args => manager.sync(args), [actual.arguments]);
          actual.status = await call("MemoryIndexManager.status", () => manager.status(), []);
        } else if (operation.op === "search") result = await executeTool("memory_search",
          { query: operation.query, maxResults: operation.maxResults, minScore: operation.minScore });
        else if (operation.op === "get-all") {
          actual.enumeratedPaths = Object.keys(await artifactFiles()); result = [];
          for (const relative of actual.enumeratedPaths)
            result.push(await executeTool("memory_get", { path: relative, from: operation.from, lines: operation.lines }));
        } else if (operation.op === "memory-mode") {
          const target = path.join(workspace, "memory"), before = await fs.stat(target, { bigint: true });
          result = await fs.chmod(target, operation.mode); const after = await fs.stat(target, { bigint: true });
          actual.mode = { path: target, requested: operation.mode, before: String(before.mode), after: String(after.mode),
            uid: String(after.uid), gid: String(after.gid), processUid: process.getuid?.(), processGid: process.getgid?.() };
        } else if (operation.op === "trust-failure") {
          if (!/^[a-z][a-z0-9_]*$/.test(operation.fault.name)) throw Error("The frozen SQL trigger name is invalid");
          actual.trigger = { databasePath: statePath, name: operation.fault.name, schemaBefore: database(statePath).schema,
            statement: operation.enabled ? operation.fault.nativeSql : "DROP TRIGGER " + operation.fault.name };
          result = stateHandle.db.exec(actual.trigger.statement); actual.trigger.schemaAfter = database(statePath).schema;
        } else throw Error("An undeclared reset operation reached its owner");
        actual.apiOutcome = { kind: "return", returnValue: returned(result) };
      } catch (error) { actual.apiOutcome = { kind: "throw", error: wire(error) }; }
      actual.sourcesAfter = await tree(workspace, true); actual.logAfter = await logBytes(); actual.auditAfter = auditRows();
      actual.sqlAfter = { state: database(statePath), agent: database(agentPath) };
      const observation = { operation: clone(operation), state: await state() };
      actual.observed = clone(observation); observations.push(observation); await capture(String(operationIndex));
    }
    raw.output = { provider: "none", before: raw.initialState, observations }; return clone(raw.output);
  } catch (error) { raw.error = wire(error); throw error; }
  finally {
    let completed = true;
    for (const [operation, fn] of [["flushSessionMemoryWritesForTest", flush], ["closeAllMemoryIndexManagers", closeManagers],
      ["closeOpenClawAgentDatabasesAsync", closeAgents], ["closePluginStateDatabaseAsync", closeState]]) {
      if (!fn) continue;
      try { raw.closeReceipts.push({ operation, returnValue: returned(await call(operation, fn, [])) }); }
      catch (error) { completed = false; raw.closeReceipts.push({ operation, error: wire(error) }); }
    }
    if (hooks && handler) for (const key of ["command:new", "command:reset"])
      await call("unregisterInternalHook", hooks.d, [key, handler]);
    try { await fs.chmod(path.join(workspace, "memory"), 0o700); } catch (error) { raw.cleanupModeError = wire(error); }
    if (flushLogs) await call("flushLogger", flushLogs, []);
    configRuntime?.clearRuntimeConfigSnapshot(); raw.closed = completed;
    try { await capture("closed"); } catch (error) { raw.closePhysicalError = wire(error); }
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]) + "\n");
    mock.timers.reset();
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
}
