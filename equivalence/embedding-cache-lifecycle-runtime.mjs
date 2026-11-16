// Input-only whole-manager cache observations through the original plugin API.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { gzipSync } from "node:zlib";

const BRIDGE = Symbol.for("memory-core.equivalence.embedding-cache-provider");
const PLUGIN = "fixture-embedding-cache";
const MODE = "deterministic-embedding-fixture";
const MANAGER = "dist/extensions/memory-core/manager-runtime.js";
const TRIGGER = "embedding_cache_publication_failure";
const TRIGGER_SQL = "CREATE TRIGGER embedding_cache_publication_failure BEFORE INSERT ON memory_index_chunks " +
  "BEGIN SELECT RAISE(ABORT,'embedding-cache-publication-blocked'); END";
const sha = value => createHash("sha256").update(value).digest("hex");
const clone = value => JSON.parse(JSON.stringify(value));
const json = value => JSON.stringify(value);
const bytes = value => ({ hex: value.toString("hex"), sha256: sha(value), size: value.length });

function transported(value, seen = new Map()) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", value: String(value) };
  if (typeof value === "function") return { type: "function", name: value.name,
    source: Function.prototype.toString.call(value) };
  if (typeof value === "symbol") return { type: "symbol", description: String(value) };
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return { type: "reference", target: seen.get(value) };
  seen.set(value, seen.size);
  if (value instanceof Uint8Array) return { type: "bytes", ...bytes(Buffer.from(value)) };
  if (value instanceof AbortSignal) return { type: "AbortSignal", aborted: value.aborted,
    reason: transported(value.reason, seen) };
  if (Array.isArray(value)) return value.map(item => transported(item, seen));
  return { ...(value instanceof Error ? { name: value.name, message: value.message } : {}),
    ...Object.fromEntries(Reflect.ownKeys(value).map(key => [String(key), transported(value[key], seen)])) };
}
const returned = value => ({ type: value === undefined ? "undefined" : typeof value,
  ...(value === undefined ? {} : { value: transported(value) }) });
const errorRecord = error => transported(error);

function owned(root, relative) {
  if (typeof relative !== "string" || !relative || relative.includes("\\") ||
      path.posix.isAbsolute(relative) || path.posix.normalize(relative) !== relative ||
      relative.split("/").some(part => part === "." || part === ".."))
    throw Error("An embedding cache fixture path must be canonical and owned");
  const result = path.resolve(root, relative);
  if (!result.startsWith(path.resolve(root) + path.sep)) throw Error("An embedding fixture escaped its owner");
  return result;
}

async function tree(root, withIdentity = false) {
  const result = {};
  async function walk(directory) {
    let entries;
    try { entries = await fs.readdir(directory, { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const filename = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw Error("Embedding physical evidence contains a symbolic link");
      if (entry.isDirectory()) await walk(filename);
      else if (entry.isFile()) {
        const payload = await fs.readFile(filename), relative = path.relative(root, filename).split(path.sep).join("/");
        if (withIdentity) {
          const stat = await fs.stat(filename, { bigint: true });
          result[relative] = { path: filename, bytes: bytes(payload), identity: { device: String(stat.dev),
            inode: String(stat.ino), size: Number(stat.size), mtimeNs: String(stat.mtimeNs), ctimeNs: String(stat.ctimeNs) } };
        } else result[relative] = payload;
      }
    }
  }
  await walk(root);
  return result;
}

function database(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try {
    db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
    const rows = sql => db.prepare(sql).all().map(row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
      [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
        : typeof value === "bigint" ? { type: "bigint", value: String(value) } : value])));
    const schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name");
    const tables = Object.fromEntries(schema.filter(row => row.type === "table").map(row =>
      [row.name, rows('SELECT * FROM "' + row.name.replaceAll('"', '""') + '"')]));
    return { schema, tables, transaction: { mode: "deferred", active: db.isTransaction } };
  } finally { if (db.isTransaction) db.exec("ROLLBACK"); db.close(); }
}

async function physical(root) {
  const files = await tree(root), databases = {};
  for (const [relative, payload] of Object.entries(files))
    if (payload.subarray(0, 16).equals(Buffer.from("SQLite format 3\0")))
      databases[relative] = database(path.join(root, relative));
  return { root, files: Object.fromEntries(Object.entries(files).map(([name, payload]) => [name, bytes(payload)])), databases };
}

export async function runEmbeddingCacheLifecycleRuntime(input, runtimeConfig) {
  if (input?.kind !== "embedding-cache-lifecycle" || !Number.isSafeInteger(input.nowMs) ||
      !input.files || !input.providers || !Array.isArray(input.operations))
    throw Error("Embedding cache lifecycle requires its frozen common input");
  for (const name of ["runtimeRoot", "stateDirectory", "configPath", "evidenceDirectory"])
    if (typeof runtimeConfig?.[name] !== "string" || !path.isAbsolute(runtimeConfig[name]))
      throw Error("Embedding cache lifecycle requires authenticated absolute runtime paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-embedding-cache-"));
  const workspace = path.join(base, "workspace"), agentDir = path.join(base, "agent");
  await fs.mkdir(workspace); await fs.mkdir(agentDir);
  const environment = { OPENCLAW_STATE_DIR: runtimeConfig.stateDirectory,
    OPENCLAW_CONFIG_PATH: runtimeConfig.configPath, OPENCLAW_HOME: base, JITI_FS_CACHE: "false" };
  const previous = Object.fromEntries(Object.keys(environment).map(name => [name, process.env[name]]));
  Object.assign(process.env, environment);
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input: clone(input), request: clone(input), fixtureBase: base, workspace,
    stateDirectory: runtimeConfig.stateDirectory, configPath: runtimeConfig.configPath, environment,
    pid: process.pid, ppid: process.ppid, node: { version: process.version, executable: process.execPath },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    calls: [], codeOwners: [], providerCreates: [], providerDisposals: [], providerIdentityResolutions: [],
    providerCalls: [], operations: [], physical: [], closeReceipts: [], closed: false };
  const imp = relative => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  const providerCalls = [];
  let selected = input.provider, cacheEnabled = input.cacheEnabled ?? true, manager, configRuntime, closeManagers, closeDatabases;
  let control = {}, documentOrdinal = 0, mutationFired = false, operationIndex = -1;
  let queryFailures = 0, documentFailures = 0, decode, originalHash;
  const profile = () => {
    const value = input.providers[selected];
    if (!value || !["ollama", "fixture-cache-a", "fixture-cache-b"].includes(value.id) || ![2, 3].includes(value.dimensions))
      throw Error("An undeclared embedding provider profile reached its owner");
    return value;
  };
  const pluginPath = fileURLToPath(new URL("./embedding-cache-provider/index.mjs", import.meta.url));
  const cfg = { logging: { level: "silent", consoleLevel: "silent", file: path.join(base, "native.log") },
    plugins: { allow: [PLUGIN], load: { paths: [pluginPath] }, entries: { [PLUGIN]: { enabled: true } }, slots: { memory: "none" } },
    agents: { defaults: { workspace }, list: [{ id: "main", default: true, workspace, agentDir }] },
    memory: { citations: "off", search: { enabled: true, fallback: "none", sources: ["memory"],
      rememberAcrossConversations: false, experimental: { sessionMemory: false }, store: { vector: { enabled: false } },
      query: { maxResults: 5, minScore: 0 } } } };
  async function updateConfig() {
    const p = profile();
    Object.assign(cfg.memory.search, { provider: p.id, model: p.model, outputDimensionality: p.dimensions,
      remote: { baseUrl: p.cacheKeyData.endpoint, batch: { enabled: false } },
      cache: { enabled: cacheEnabled } });
    await fs.mkdir(path.dirname(runtimeConfig.configPath), { recursive: true });
    await fs.writeFile(runtimeConfig.configPath, json(cfg) + "\n");
    configRuntime?.setRuntimeConfigSnapshot(cfg);
    raw.config = clone(cfg);
  }
  async function owner(modulePath, exportName, name, fn) {
    if (typeof fn !== "function") throw Error("A pinned embedding owner is unavailable: " + name);
    const source = Function.prototype.toString.call(fn);
    raw.codeOwners.push({ name, modulePath, exportName, functionName: fn.name, functionLength: fn.length,
      functionSource: source, functionSourceSha256: sha(source),
      compiledSha256: sha(await fs.readFile(path.join(runtimeConfig.runtimeRoot, modulePath))) });
  }
  async function call(operation, fn, args) {
    const row = { operation, arguments: transported(args) }; raw.calls.push(row);
    try { const result = await fn(...args); row.returnValue = returned(result); return result; }
    catch (error) { row.error = errorRecord(error); throw error; }
  }
  async function capture(label) {
    const value = { fixture: await physical(base), state: await physical(runtimeConfig.stateDirectory),
      config: bytes(await fs.readFile(runtimeConfig.configPath)) };
    const payload = json(value) + "\n", filename = path.join(runtimeConfig.evidenceDirectory, `native-physical-${label}.json`);
    await fs.writeFile(filename, payload);
    raw.physical.push({ path: filename, sha256: sha(payload), uncompressedBytes: Buffer.byteLength(payload),
      encoding: "gzip-json-base64", data: gzipSync(Buffer.from(payload)).toString("base64") });
  }
  async function writeFiles(files, reason) {
    const row = { operation: reason, files: clone(files), sourcesBefore: await tree(workspace, true) };
    raw.calls.push(row);
    for (const [relative, text] of Object.entries(files)) {
      if (typeof text !== "string") throw Error("Embedding source content must be a literal string");
      const filename = owned(workspace, relative); await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, text);
    }
    row.sourcesAfter = await tree(workspace, true);
  }
  function requireProfile(id, options) {
    const p = profile();
    if (id !== p.id || (options.model && options.model !== p.model))
      throw Error("The original embedding adapter requested an unowned provider identity");
    return clone(p);
  }
  async function embed(p, kind, inputs, options) {
    const semantic = { kind, provider: p.id, model: p.model, inputs: clone(inputs), completed: false };
    const actual = { ordinal: raw.providerCalls.length + 1, operationIndex, nowMs: Date.now(),
      arguments: transported(kind === "document" ? [inputs, options] : [inputs[0], options]),
      control: clone(control), documentOrdinal: kind === "document" ? ++documentOrdinal : null, semantic };
    raw.providerCalls.push(actual); providerCalls.push(semantic);
    try {
      actual.sourcesBefore = await tree(workspace, true);
      actual.databaseBefore = manager ? database(manager.settings.store.databasePath) : null;
      if (kind === "document" && !mutationFired && control.mutateOnDocumentCall?.call === documentOrdinal) {
        mutationFired = true;
        await writeFiles(control.mutateOnDocumentCall.files, "mutateSourceInsideActualDocumentCallback");
      }
      const fixtureError = (message, status, retry = false) => Object.assign(Error(message),
        { status, ...(retry ? { retryAfterMs: 0 } : {}) });
      if (kind === "document" && Number.isInteger(control.maxItems) && inputs.length > control.maxItems)
        throw fixtureError("input array max " + control.maxItems, 400);
      if (kind === "document" && control.failText && inputs.some(text => text.includes(control.failText)))
        throw fixtureError("embedding fixture terminal document failure", 400);
      if (kind === "document" && documentFailures > 0) {
        documentFailures--; throw fixtureError("embedding fixture transient document failure", 503, true);
      }
      if (kind === "query" && queryFailures > 0) {
        queryFailures--; throw fixtureError("embedding fixture transient query failure", 503, true);
      }
      const vector = text => [1, Buffer.byteLength(text, "utf8"),
        ...((p.dimensions === 3 || (kind === "document" && control.response === "dimensions-3")) ? [0.5] : [])];
      const result = kind === "document" ? control.response === "empty" ? [] : inputs.map(vector) : vector(inputs[0]);
      semantic.completed = true; semantic.returnValue = clone(result); actual.returnValue = returned(result);
      return result;
    } catch (error) {
      actual.error = errorRecord(error);
      semantic.error = { name: error.name, message: error.message,
        ...(Object.hasOwn(error, "status") ? { status: error.status } : {}),
        ...(Object.hasOwn(error, "retryAfterMs") ? { retryAfterMs: error.retryAfterMs } : {}) };
      throw error;
    } finally {
      actual.sourcesAfter = await tree(workspace, true);
      actual.databaseAfter = manager ? database(manager.settings.store.databasePath) : null;
    }
  }
  globalThis[BRIDGE] = {
    registered() { raw.pluginRegistered = { atMs: Date.now(), operationIndex }; },
    normalizeModel(id, options) { return requireProfile(id, options).model; },
    resolveIndexIdentity(id, options) {
      const p = requireProfile(id, options), result = { model: p.model, cacheKeyData: clone(p.cacheKeyData),
        aliases: clone(p.indexIdentityAliases ?? []) };
      raw.providerIdentityResolutions.push({ operationIndex, arguments: transported([id, options]), returnValue: returned(result) });
      return result;
    },
    async create(id, options) {
      const p = requireProfile(id, options);
      const provider = { id: p.id, model: p.model, dimensions: p.dimensions,
        embed: (text, opts) => embed(p, "query", [text], opts),
        embedBatch: (texts, opts) => embed(p, "document", texts, opts),
        close() { raw.providerDisposals.push({ operationIndex, nowMs: Date.now(), provider: p.id, model: p.model,
          returnValue: returned(undefined) }); } };
      const result = { provider, runtime: { id: p.id, cacheKeyData: clone(p.cacheKeyData),
        indexIdentityAliases: clone(p.indexIdentityAliases ?? []) } };
      raw.providerCreates.push({ operationIndex, nowMs: Date.now(), arguments: transported([id, options]),
        returnValue: returned(result) });
      return result;
    },
  };
  async function state() {
    const status = await call("MemoryIndexManager.status", () => manager.status(), []);
    const configured = await call("MemoryIndexManager.resolveConfiguredIndexIdentity", () => manager.resolveConfiguredIndexIdentity(), []);
    if (!configured?.cacheKeyData) throw Error("The original configured provider identity was not resolved");
    const identity = { provider: configured.provider.id, model: configured.provider.model,
      providerKey: originalHash(JSON.stringify(configured.cacheKeyData)), cacheKeyData: clone(configured.cacheKeyData),
      indexIdentityAliases: (configured.aliases ?? []).map(alias => ({ model: alias.model,
        providerKey: originalHash(JSON.stringify(alias.cacheKeyData)), cacheKeyData: clone(alias.cacheKeyData) })),
      cacheEnabled: manager.cache.enabled };
    const filename = manager.settings.store.databasePath, db = new DatabaseSync(filename, { readOnly: true });
    let cache;
    try {
      db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
      cache = db.prepare("SELECT * FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash").all()
        .map(row => ({ ...row, embedding: decode(row.embedding), embeddingHex: Buffer.from(row.embedding).toString("hex") }));
    } finally { if (db.isTransaction) db.exec("ROLLBACK"); db.close(); }
    const value = { cache, identity, providerCalls: clone(providerCalls) };
    raw.states ??= [];
    raw.states.push({ operationIndex, state: clone(value), status: transported(status),
      configuredIdentity: transported(configured), activeProvider: transported(manager.provider),
      activeProviderRuntime: transported(manager.providerRuntime), settings: transported(manager.settings),
      indexIdentity: transported(manager.indexIdentityState),
      actualIndexConcurrency: await call("MemoryIndexManager.getIndexConcurrency", () => manager.getIndexConcurrency(), []),
      rawSQL: database(filename), sources: await tree(workspace, true) });
    return value;
  }
  try {
    await writeFiles(input.files, "seedLiteralSources");
    await updateConfig();
    configRuntime = await imp("dist/plugin-sdk/config-runtime.js");
    await call("setRuntimeConfigSnapshot", configRuntime.setRuntimeConfigSnapshot, [cfg]);
    const { w: setRegistry } = await imp("dist/runtime-9cxii0oQ.mjs");
    const { t: emptyRegistry } = await imp("dist/registry-empty-BTjzcMW2.mjs");
    await call("setActivePluginRegistry", setRegistry, [emptyRegistry(), "startup-registry", "gateway-bindable", workspace]);
    const { o: metadataSnapshot } = await imp("dist/plugin-metadata-snapshot-DT_pRp6g.mjs");
    const { t: loadRegistry } = await imp("dist/loader-DpAS3szV.mjs");
    const metadata = metadataSnapshot({ config: cfg, workspaceDir: workspace });
    const registry = loadRegistry({ config: cfg, workspaceDir: workspace, manifestRegistry: metadata.manifestRegistry,
      discovery: metadata.discovery, onlyPluginIds: [PLUGIN], cache: false, throwOnLoadError: true });
    raw.pluginRegistry = { plugins: transported(registry.plugins), embeddingProviders: transported(registry.embeddingProviders),
      diagnostics: transported(registry.diagnostics) };
    const runtime = await imp(MANAGER); closeManagers = runtime.closeAllMemoryIndexManagers;
    closeDatabases = (await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s;
    decode = (await imp("dist/embedding-vector-CGPWflQ5.mjs")).n;
    originalHash = (await imp("dist/hash-CAMhNIP1.mjs")).t;
    for (const [modulePath, exportName, name, fn] of [
      [MANAGER, "MemoryIndexManager", "MemoryIndexManager.get", runtime.MemoryIndexManager.get],
      [MANAGER, "MemoryIndexManager", "MemoryIndexManager", runtime.MemoryIndexManager],
      [MANAGER, "closeAllMemoryIndexManagers", "closeAllMemoryIndexManagers", closeManagers],
      ["dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s", "closeOpenClawAgentDatabasesAsync", closeDatabases],
      ["dist/plugin-metadata-snapshot-DT_pRp6g.mjs", "o", "loadPluginMetadataSnapshot", metadataSnapshot],
      ["dist/loader-DpAS3szV.mjs", "t", "loadAndActivateRootPluginRegistry", loadRegistry],
      ["dist/embedding-vector-CGPWflQ5.mjs", "n", "decodeMemoryEmbedding", decode],
      ["dist/hash-CAMhNIP1.mjs", "t", "hashText", originalHash],
    ]) await owner(modulePath, exportName, name, fn);
    async function openManager() {
      const args = { cfg, agentId: "main", purpose: "cli" };
      const actual = { operation: "MemoryIndexManager.get", arguments: transported([args]) }; raw.calls.push(actual);
      try {
        manager = await runtime.MemoryIndexManager.get(args);
        if (!manager) throw Error("The original cache manager was not constructed");
        actual.nativeHandleObservation = { constructor: manager.constructor.name, dbPath: manager.settings.store.databasePath,
          workspaceDir: manager.workspaceDir, purpose: manager.purpose, providerRequirement: transported(manager.providerRequirement),
          settings: transported(manager.settings), isOpen: manager.db.isOpen };
      } catch (error) { actual.error = errorRecord(error); throw error; }
    }
    await openManager();
    for (const name of ["sync", "search", "close", "status", "resolveConfiguredIndexIdentity", "resolveProviderIndexIdentities",
      "embedChunksInBatches", "embedBatchWithRetry", "embedQueryWithRetry", "persistGeneratedEmbeddings", "getIndexConcurrency"])
      await owner(MANAGER, "MemoryIndexManager", "MemoryIndexManager." + name, manager[name]);
    raw.initialState = await state(); await capture("initial");
    const observations = [];
    for (operationIndex = 0; operationIndex < input.operations.length; operationIndex++) {
      const operation = input.operations[operationIndex];
      if (!Number.isSafeInteger(operation.nowMs)) throw Error("Each embedding operation requires its literal clock");
      mock.timers.setTime(operation.nowMs);
      control = clone(operation.providerControl ?? {}); documentOrdinal = 0; mutationFired = false;
      documentFailures = control.documentFailures ?? 0; queryFailures = control.queryFailures ?? 0;
      const actual = { operation: clone(operation), sourcesBefore: await tree(workspace, true) }; raw.operations.push(actual);
      let triggerDb;
      try {
        let result;
        if (operation.op === "sync") {
          if (operation.publicationFailure) {
            triggerDb = new DatabaseSync(manager.settings.store.databasePath); triggerDb.exec(TRIGGER_SQL);
            actual.publicationFailure = { databasePath: manager.settings.store.databasePath, name: TRIGGER,
              statement: TRIGGER_SQL, schemaBeforeDispatch: database(manager.settings.store.databasePath).schema };
          }
          actual.arguments = { reason: "search-bootstrap", force: operation.force ?? false };
          result = await call("MemoryIndexManager.sync", args => manager.sync(args), [actual.arguments]);
        } else if (operation.op === "query") {
          const opts = { maxResults: 5, minScore: 0 };
          actual.arguments = [operation.query, opts];
          result = await call("MemoryIndexManager.search", (query, options) => manager.search(query, options), actual.arguments);
        } else if (operation.op === "write") {
          result = await writeFiles({ [operation.path]: operation.text }, "writeLiteralSource");
        } else if (operation.op === "rename") {
          const destination = owned(workspace, operation.to); await fs.mkdir(path.dirname(destination), { recursive: true });
          result = await fs.rename(owned(workspace, operation.path), destination);
        } else if (operation.op === "remove") result = await fs.unlink(owned(workspace, operation.path));
        else if (operation.op === "reopen") {
          await call("MemoryIndexManager.close", () => manager.close(), []);
          selected = operation.provider ?? selected; cacheEnabled = operation.cacheEnabled ?? cacheEnabled;
          control = {}; await updateConfig(); result = await openManager();
        } else throw Error("An undeclared embedding lifecycle operation reached its owner");
        actual.apiOutcome = { kind: "return", returnValue: returned(result) };
      } catch (error) { actual.apiOutcome = { kind: "throw", error: errorRecord(error) }; }
      try {
        actual.sourcesAfter = await tree(workspace, true);
        const observation = { operation: clone(operation), state: await state() };
        actual.observed = clone(observation); observations.push(observation);
        await capture(String(operationIndex));
      } finally {
        if (triggerDb) {
          triggerDb.exec("DROP TRIGGER " + TRIGGER);
          actual.publicationFailure.schemaAfterDrop = database(manager.settings.store.databasePath).schema;
          triggerDb.close();
        }
      }
    }
    raw.output = { provider: MODE, before: raw.initialState, observations };
    return clone(raw.output);
  } catch (error) { raw.error = errorRecord(error); throw error; }
  finally {
    let cleanupComplete = true;
    for (const [operation, fn] of [["closeAllMemoryIndexManagers", closeManagers],
      ["closeOpenClawAgentDatabasesAsync", closeDatabases]]) {
      if (!fn) continue;
      try {
        const value = await call(operation, fn, []);
        raw.closeReceipts.push({ operation, returnValue: returned(value) });
      } catch (error) { cleanupComplete = false; raw.closeReceipts.push({ operation, error: errorRecord(error) }); }
    }
    configRuntime?.clearRuntimeConfigSnapshot(); raw.closed = cleanupComplete;
    delete globalThis[BRIDGE];
    try { await capture("closed"); } catch (error) { raw.closePhysicalError = errorRecord(error); }
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), json([raw]) + "\n");
    mock.timers.reset();
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
}
