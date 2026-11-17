// Genuine embedded harness, registered memory capability and offline model transport.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { gzipSync } from "node:zlib";

const BRIDGE = Symbol.for("memory-core.equivalence.prompt-runtime-provider");
const PROVIDER = "fixture-prompt-runtime-model", MODEL = "fixture-model";
const TOOL_NAMES = ["memory_search", "memory_get", "sessions_search", "sessions_history", "session_status"];
const HARNESS = "dist/builtin-openclaw-D1Xfnzzr.mjs";
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
  if (value instanceof Set) return { type: "Set", values: [...value].map(item => wire(item, seen)) };
  if (value instanceof Map) return { type: "Map", entries: [...value].map(item => wire(item, seen)) };
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
    throw Error("A prompt fixture path must be canonical and owned");
  const filename = path.resolve(root, relative);
  if (!filename.startsWith(path.resolve(root) + path.sep)) throw Error("A prompt fixture escaped its owner");
  return filename;
}
async function tree(root, identities = false, links = null) {
  const files = {};
  async function walk(directory) {
    let entries;
    try { entries = await fs.readdir(directory, { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const name of ordered(entries.map(entry => entry.name))) {
      const entry = entries.find(item => item.name === name), filename = path.join(directory, name);
      const relative = path.relative(root, filename).split(path.sep).join("/");
      if (entry.isSymbolicLink()) {
        if (!links) throw Error("Prompt source evidence contains a symbolic link");
        const stat = await fs.lstat(filename, { bigint: true }), target = await fs.readlink(filename);
        links[relative] = { target, resolvedTarget: path.resolve(path.dirname(filename), target),
          lstatIdentity: { device: String(stat.dev), inode: String(stat.ino), mode: String(stat.mode), nlink: String(stat.nlink),
            uid: String(stat.uid), gid: String(stat.gid), size: String(stat.size), mtimeNs: String(stat.mtimeNs), ctimeNs: String(stat.ctimeNs) } };
      } else if (entry.isDirectory()) await walk(filename);
      else if (entry.isFile()) {
        const payload = await fs.readFile(filename);
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
  const links = {}, files = await tree(root, false, links), databases = {};
  for (const [name, payload] of Object.entries(files))
    if (payload.subarray(0, 16).equals(Buffer.from("SQLite format 3\0"))) databases[name] = database(path.join(root, name));
  return { root, files: Object.fromEntries(Object.entries(files).map(([name, payload]) => [name, bytes(payload)])), databases, links };
}

export async function runPromptRuntimeContextRuntime(input, runtimeConfig) {
  if (input?.kind !== "prompt-runtime-context" || input.identity !== "openclaw" ||
      !Number.isSafeInteger(input.nowMs) || !Array.isArray(input.messages) || !Array.isArray(input.operations))
    throw Error("Prompt runtime context requires its frozen complete input");
  for (const name of ["runtimeRoot", "stateDirectory", "configPath", "evidenceDirectory"])
    if (typeof runtimeConfig?.[name] !== "string" || !path.isAbsolute(runtimeConfig[name]))
      throw Error("Prompt runtime context requires authenticated absolute runtime paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-prompt-runtime-"));
  const workspace = path.join(base, "workspace"), agentDir = path.join(base, "agent"), storePath = path.join(base, "sessions.json");
  await fs.mkdir(workspace); await fs.mkdir(agentDir); await fs.mkdir(path.join(workspace, "memory"));
  for (const [relative, text] of Object.entries(input.files)) {
    const filename = owned(workspace, relative); await fs.mkdir(path.dirname(filename), { recursive: true }); await fs.writeFile(filename, text);
  }
  const environment = { OPENCLAW_STATE_DIR: runtimeConfig.stateDirectory, OPENCLAW_CONFIG_PATH: runtimeConfig.configPath,
    OPENCLAW_HOME: base, TZ: input.hostTimezone, JITI_FS_CACHE: "false", FS_SAFE_NATIVE_MODE: "require" };
  const previousEnvironment = Object.fromEntries(Object.keys(environment).map(key => [key, process.env[key]]));
  Object.assign(process.env, environment);
  const originalDate = Date, originalTimeout = setTimeout, originalPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: "prompt-runtime-context-native-raw", input: clone(input), request: clone(input), fixtureBase: base,
    workspace, stateDirectory: runtimeConfig.stateDirectory, runtimeRoot: runtimeConfig.runtimeRoot, configPath: runtimeConfig.configPath,
    storePath, environment, pid: process.pid, ppid: process.ppid, node: { version: process.version, executable: process.execPath },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate,
      setTimeoutUnchanged: setTimeout === originalTimeout, performanceNowUnchanged: performance.now === originalPerformance,
      readings: [{ operationIndex: -1, requestedNowMs: input.nowMs, actualNowMs: Date.now(), iso: new Date().toISOString() }] },
    calls: [], codeOwners: [], transcriptSeeds: [], operations: [], states: [], physical: [], providerEvents: [], toolCalls: [], closeReceipts: [], closed: false };
  const imp = relative => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let operationIndex = -1, active, clearConfig, sessions, scope, agentPath, statePath, flushLogs,
    closeManagers, closeAgents, closeState, closeMcp, scheduler, capability, descriptor, observedBuilder, memoryRegistration;
  let cfg;
  async function owner(modulePath, exportName, name, fn) {
    if (typeof fn !== "function") throw Error("A pinned prompt owner is unavailable: " + name);
    const source = Function.prototype.toString.call(fn);
    raw.codeOwners.push({ name, modulePath, exportName, functionName: fn.name, functionLength: fn.length,
      functionSource: source, functionSourceSha256: sha(source), compiledSha256: sha(await fs.readFile(path.join(runtimeConfig.runtimeRoot, modulePath))) });
  }
  async function call(operation, fn, args) {
    const record = { operation, operationIndex, arguments: wire(args) }; raw.calls.push(record);
    try { const result = await fn(...args); record.returnValue = returned(result); return result; }
    catch (error) { record.error = wire(error); throw error; }
  }
  const sql = () => ({ agent: database(agentPath), state: database(statePath) });
  async function snapshot() {
    const record = { operationIndex, transcript: await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]),
      sql: sql(), sources: await tree(workspace, true) };
    raw.states.push(record); return record;
  }
  async function capture(label) {
    if (flushLogs) await call("flushLogger", flushLogs, []);
    const value = { fixture: await physical(base), state: await physical(runtimeConfig.stateDirectory),
      config: bytes(await fs.readFile(runtimeConfig.configPath)) };
    const payload = JSON.stringify(value) + "\n", filename = path.join(runtimeConfig.evidenceDirectory, `native-physical-${label}.json`);
    await fs.writeFile(filename, payload);
    raw.physical.push({ path: filename, sha256: sha(payload), uncompressedBytes: Buffer.byteLength(payload),
      encoding: "gzip-json-base64", data: gzipSync(Buffer.from(payload)).toString("base64") });
  }
  try {
    const pluginPath = fileURLToPath(new URL("./prompt-runtime-provider/index.mjs", import.meta.url));
    const model = { id: MODEL, name: "Offline prompt fixture", provider: PROVIDER, api: "openai-completions",
      baseUrl: "http://127.0.0.1:1/v1", reasoning: false, input: ["text", "image"], contextWindow: 32000, maxTokens: 1024,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
    cfg = { logging: { level: "debug", consoleLevel: "silent", file: path.join(base, "native.log") },
      plugins: { allow: [PROVIDER, "memory-core"], load: { paths: [pluginPath] },
        entries: { [PROVIDER]: { enabled: true }, "memory-core": { enabled: true } }, slots: { memory: "memory-core" } },
      agents: { defaults: { workspace, model: { primary: PROVIDER + "/" + MODEL },
        compaction: { enabled: false, memoryFlush: { enabled: false } } }, list: [{ id: "main", default: true, workspace, agentDir }] },
      session: { store: storePath, maintenance: { mode: "warn" } },
      tools: { allow: ["read", ...TOOL_NAMES], deny: [], loopDetection: { enabled: false }, fs: { workspaceOnly: true } },
      memory: { citations: "auto", search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"],
        rememberAcrossConversations: false, experimental: { sessionMemory: false }, store: { vector: { enabled: false } }, query: { maxResults: 6, minScore: 0 } } },
      models: { providers: { [PROVIDER]: { api: model.api, baseUrl: model.baseUrl, apiKey: "fixture-not-a-credential",
        models: [{ id: model.id, name: model.name, api: model.api, reasoning: model.reasoning,
          input: model.input, contextWindow: model.contextWindow, maxTokens: model.maxTokens, cost: model.cost }] } } } };
    await fs.mkdir(path.dirname(runtimeConfig.configPath), { recursive: true }); await fs.writeFile(runtimeConfig.configPath, JSON.stringify(cfg) + "\n");
    raw.config = clone(cfg);
    const configuration = await imp("dist/plugin-sdk/config-runtime.js"); clearConfig = configuration.clearRuntimeConfigSnapshot;
    await call("setRuntimeConfigSnapshot", configuration.setRuntimeConfigSnapshot, [cfg]);
    const dates = await imp("dist/date-time-B8B56dzx.mjs"), clock = (await imp("dist/current-time-CgCswWtv.mjs")).n;
    raw.host = { requestedTimezone: input.hostTimezone, requestedTimeFormat: input.hostTimeFormat,
      actualTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      actualTimeFormat: await call("resolveUserTimeFormat", dates.a, [undefined]),
      intlResolvedOptions: clone(Intl.DateTimeFormat().resolvedOptions()) };
    if (raw.host.actualTimezone !== input.hostTimezone || raw.host.actualTimeFormat !== input.hostTimeFormat)
      throw Error("Actual original host timezone or clock format differs from the declared fixture");
    const { createAssistantMessageEventStream } = await imp("dist/plugin-sdk/llm.js");
    const stream = (actualModel, context, options) => {
      if (!active) throw Error("An unowned model request escaped the prompt operation");
      const index = active.providerCalls.length, script = active.operation.scriptedTools ?? [];
      const item = script[index], content = item ? [{ type: "toolCall", ...clone(item) }]
        : [{ type: "text", text: "prompt fixture complete" }];
      const response = { role: "assistant", content, api: actualModel.api, provider: actualModel.provider,
        model: actualModel.id, stopReason: item ? "toolUse" : "stop", timestamp: Date.now(),
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
      active.providerCalls.push({ request: { model: clone(actualModel), context: clone(context), options: wire(options) }, response: clone(response) });
      const result = createAssistantMessageEventStream();
      queueMicrotask(() => { result.push({ type: "done", reason: response.stopReason, message: response }); result.end(response); });
      return result;
    };
    globalThis[BRIDGE] = { stream, progress: event => raw.providerEvents.push({ operationIndex, event, timestamp: Date.now() }),
      observeTool: (hook, event, context) => {
        const record = { operationIndex, hook, event: wire(event), context: wire(context), timestamp: Date.now() };
        raw.toolCalls.push(record); active?.toolCalls.push(record);
      } };
    const registryRuntime = await imp("dist/runtime-9cxii0oQ.mjs"), empty = await imp("dist/registry-empty-BTjzcMW2.mjs");
    await call("setActivePluginRegistry", registryRuntime.w, [empty.t(), "startup-registry", "gateway-bindable", workspace]);
    // This is the original scheduler registration, not a Gateway server startup.
    const { t: GatewayScheduler } = await imp("dist/gateway-scheduler-TywODsdc.mjs"); scheduler = new GatewayScheduler();
    const mcp = await imp("dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs"); closeMcp = mcp.i;
    await call("setSessionMcpScheduler", mcp.p, [scheduler]);
    const metadataModule = await imp("dist/plugin-metadata-snapshot-DT_pRp6g.mjs"), loader = await imp("dist/loader-DpAS3szV.mjs");
    const metadata = await call("loadPluginMetadataSnapshot", metadataModule.o, [{ config: cfg, workspaceDir: workspace }]);
    const registry = await call("loadAndActivateRootPluginRegistry", loader.t, [{ config: cfg, workspaceDir: workspace,
      manifestRegistry: metadata.manifestRegistry, discovery: metadata.discovery, onlyPluginIds: [PROVIDER, "memory-core"],
      runtimeOptions: { allowGatewaySubagentBinding: true }, cache: false, throwOnLoadError: true }]);
    raw.pluginRegistry = { plugins: registry.plugins.map(item => ({ id: item.id, status: item.status, source: item.source })),
      providers: registry.providers.map(item => ({ pluginId: item.pluginId, id: item.provider.id })), diagnostics: wire(registry.diagnostics) };
    memoryRegistration = registry.memoryCapabilities.find(item => item.pluginId === "memory-core");
    capability = memoryRegistration?.capability; descriptor = capability && Object.getOwnPropertyDescriptor(capability, "promptBuilder");
    if (!descriptor || !Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "function" || !descriptor.configurable)
      throw Error("The original registered memory prompt builder has no observable function descriptor");
    const originalBuilder = capability.promptBuilder;
    raw.memoryPromptObserver = { pluginId: memoryRegistration.pluginId, originalFunctionSource: Function.prototype.toString.call(originalBuilder),
      descriptor: { configurable: descriptor.configurable, enumerable: descriptor.enumerable, writable: descriptor.writable }, calls: [], restored: false };
    observedBuilder = function observedMemoryPromptBuilder(...args) {
      const record = { operationIndex, arguments: wire(args), originalInvocations: 0,
        toolAvailability: Object.fromEntries(TOOL_NAMES.map(name => [name, args[0].availableTools.has(name)])) };
      raw.memoryPromptObserver.calls.push(record); active?.memoryPromptCalls.push(record);
      try { record.originalInvocations++; const value = Reflect.apply(originalBuilder, this, args);
        record.returnValue = returned(value); record.returnedExactOriginalValue = true; return value; }
      catch (error) { record.error = wire(error); record.rethrownExactOriginalError = true; throw error; }
    };
    // Keep the plugin's original value view intact. Only this registry edge
    // observes its callback; every other member forwards to the exact owner.
    const observedCapability = new Proxy(capability, { get(target, key) {
      return key === "promptBuilder" ? observedBuilder : Reflect.get(target, key, target);
    } });
    memoryRegistration.capability = observedCapability;
    const authModule = await imp("dist/model-registry-CyECwbEb.mjs"), auth = authModule.i.inMemory(), models = authModule.t.inMemory(auth);
    await call("AuthStorage.setRuntimeApiKey", (provider, key) => auth.setRuntimeApiKey(provider, key), [PROVIDER, "fixture-not-a-credential"]);
    await call("ModelRegistry.registerProvider", (provider, options) => models.registerProvider(provider, options), [PROVIDER, { api: model.api, streamSimple: stream }]);
    sessions = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const headerModule = await imp("dist/transcript-header-CP-ow2Zr.mjs");
    scope = { agentId: "main", sessionId: "prompt-runtime-session", sessionKey: "agent:main:main", storePath };
    raw.scope = clone(scope);
    await call("replaceSessionEntry", sessions.replaceSessionEntry, [{ agentId: scope.agentId, sessionKey: scope.sessionKey, storePath },
      { sessionId: scope.sessionId, updatedAt: input.nowMs }]);
    const header = await call("createSessionTranscriptHeader", headerModule.t, [{ sessionId: scope.sessionId,
      version: input.sessionVersion, cwd: workspace, timestamp: new Date(input.nowMs).toISOString() }]);
    const events = [header, ...input.messages.map((message, index) => ({ type: "message", id: "initial-" + index,
      parentId: index ? "initial-" + (index - 1) : null, message: clone(message) }))];
    const seed = { scope: clone(scope), header: clone(header), literalMessages: clone(input.messages), events: clone(events) }; raw.transcriptSeeds.push(seed);
    seed.returnValue = returned(await call("replaceTranscriptEvents", sessions.replaceTranscriptEvents, [scope, events]));
    seed.actualStoredEvents = await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]);
    agentPath = seed.databasePath = await call("resolveSessionTranscriptDatabasePath", sessions.resolveSessionTranscriptDatabasePath, [scope]);
    raw.transcriptDatabasePath = agentPath;
    const shared = await imp("dist/openclaw-state-db-Dh2awMJ8.mjs"); const stateHandle = await call("openOpenClawStateDatabase", shared.r, [{ env: environment }]);
    statePath = stateHandle.path;
    raw.stateDatabasePath = statePath;
    const managerRuntime = await imp("dist/extensions/memory-core/manager-runtime.js"); closeManagers = managerRuntime.closeAllMemoryIndexManagers;
    closeAgents = (await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s;
    closeState = (await imp("dist/plugin-state-store-BPUaLoVD.mjs")).u;
    flushLogs = (await imp("dist/logger-Cn5hoa7J.mjs")).n;
    const recorderModule = await imp("dist/user-turn-transcript-Dig8rv9R.mjs");
    const preparationModule = await imp("dist/dreaming-dreams-file-BJzlZFlf.mjs");
    raw.recallModulePreload = wire(await call("importOriginalRecallModule", () => imp("dist/short-term-promotion-record-CEpBdgKW.mjs"), []));
    const admissionModule = await imp("dist/admitted-run-context-hIkojwNE.mjs"), harnessModule = await imp(HARNESS);
    const harness = await call("createOpenClawAgentHarness", harnessModule.t, []);
    for (const spec of [
      [HARNESS, "t", "createOpenClawAgentHarness", harnessModule.t], [HARNESS, "t", "OpenClawAgentHarness.runAttempt", harness.runAttempt],
      ["dist/admitted-run-context-hIkojwNE.mjs", "d", "prepareSystemAgentRunAdmission", admissionModule.d],
      ["dist/current-time-CgCswWtv.mjs", "n", "resolveCronStyleNow", clock],
      ["dist/date-time-B8B56dzx.mjs", "a", "resolveUserTimeFormat", dates.a],
      ["dist/transcript-header-CP-ow2Zr.mjs", "t", "createSessionTranscriptHeader", headerModule.t],
      ...["replaceSessionEntry", "replaceTranscriptEvents", "loadTranscriptEventsSync", "resolveSessionTranscriptDatabasePath"].map(name =>
        ["dist/session-accessor-CiKKTlbe.mjs", name, name, sessions[name]]),
      ["dist/model-registry-CyECwbEb.mjs", "i", "AuthStorage.inMemory", authModule.i.inMemory],
      ["dist/model-registry-CyECwbEb.mjs", "t", "ModelRegistry.inMemory", authModule.t.inMemory],
      ["dist/model-registry-CyECwbEb.mjs", "t", "ModelRegistry.registerProvider", models.registerProvider],
      ["dist/openclaw-state-db-Dh2awMJ8.mjs", "r", "openOpenClawStateDatabase", shared.r],
      ["dist/extensions/memory-core/manager-runtime.js", "closeAllMemoryIndexManagers", "closeAllMemoryIndexManagers", closeManagers],
      ["dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s", "closeOpenClawAgentDatabasesAsync", closeAgents],
      ["dist/plugin-state-store-BPUaLoVD.mjs", "u", "closePluginStateDatabaseAsync", closeState],
      ["dist/logger-Cn5hoa7J.mjs", "n", "flushLogger", flushLogs],
      ["dist/user-turn-transcript-Dig8rv9R.mjs", "t", "createUserTurnTranscriptRecorder", recorderModule.t],
      ["dist/dreaming-dreams-file-BJzlZFlf.mjs", "_", "withMemoryWorkspacePreparation", preparationModule._],
    ]) await owner(...spec);
    raw.initialState = await snapshot(); await capture("initial");
    const observations = [];
    for (operationIndex = 0; operationIndex < input.operations.length; operationIndex++) {
      const operation = input.operations[operationIndex]; mock.timers.setTime(operation.nowMs);
      raw.clock.readings.push({ operationIndex, requestedNowMs: operation.nowMs, actualNowMs: Date.now(), iso: new Date().toISOString() });
      active = { operation: clone(operation), beforeTranscript: await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]),
        beforeSql: sql(), sourcesBefore: await tree(workspace, true), memoryPromptCalls: [], providerCalls: [], toolCalls: [] };
      raw.operations.push(active);
      let memoryGuidance = null, actualClock = null;
      try {
        if (operation.op === "reopen") {
          active.apiOutcome = { kind: "return", returnValue: returned(await call("closeAllMemoryIndexManagers", closeManagers, [])) };
          await call("closeOpenClawAgentDatabasesAsync", closeAgents, []);
        } else if (operation.op === "submit") {
          cfg = clone(cfg); cfg.tools.deny = TOOL_NAMES.filter(name => !operation.tools.includes(name)); cfg.memory.citations = operation.citationsMode;
          if (Object.hasOwn(operation, "timezone")) cfg.agents.defaults.userTimezone = operation.timezone;
          else delete cfg.agents.defaults.userTimezone;
          await fs.writeFile(runtimeConfig.configPath, JSON.stringify(cfg) + "\n");
          await call("setRuntimeConfigSnapshot", configuration.setRuntimeConfigSnapshot, [cfg]); active.config = clone(cfg);
          const fragments = clone(operation.fragments);
          if (operation.includeClock) {
            active.clockCall = { owner: "resolveCronStyleNow", modulePath: "dist/current-time-CgCswWtv.mjs", arguments: wire([cfg, operation.nowMs]) };
            actualClock = await call("resolveCronStyleNow", clock, [cfg, operation.nowMs]);
            active.clockCall.returnValue = returned(actualClock); fragments.push({ kind: "runtime-instruction", text: actualClock.timeLine });
          }
          if (operation.scriptedTools?.length && Object.keys(input.files).length) {
            active.indexPreparation = { utimes: [] };
            for (const relative of Object.keys(input.files)) {
              const filename = owned(workspace, relative), before = await fs.stat(filename, { bigint: true });
              const value = await fs.utimes(filename, input.fileMtimeMs / 1000, input.fileMtimeMs / 1000), after = await fs.stat(filename, { bigint: true });
              active.indexPreparation.utimes.push({ path: relative, mtimeMs: input.fileMtimeMs, returnValue: returned(value),
                before: { mtimeNs: String(before.mtimeNs), ctimeNs: String(before.ctimeNs) },
                after: { mtimeNs: String(after.mtimeNs), ctimeNs: String(after.ctimeNs) } });
            }
            const manager = await call("MemoryIndexManager.get", managerRuntime.MemoryIndexManager.get.bind(managerRuntime.MemoryIndexManager), [{ cfg, agentId: "main", purpose: "cli" }]);
            if (!manager) throw Error("The original recall manager was unavailable");
            active.indexPreparation.syncReturn = returned(await call("MemoryIndexManager.sync", params => manager.sync(params), [{ reason: "search-bootstrap", force: false }]));
            active.indexPreparation.status = wire(manager.status());
            await call("MemoryIndexManager.close", () => manager.close(), []);
          }
          const runId = "prompt-runtime-" + operationIndex;
          const transcriptInputText = operation.transcriptPrompt ?? operation.effectivePrompt;
          let recorder;
          active.userTurnRecorder = { supplied: false, transcriptInputText };
          if (transcriptInputText.trim()) {
            const recorderInput = { text: transcriptInputText, idempotencyKey: runId, timestamp: operation.nowMs };
            const recorderTarget = { ...scope, expectedSessionId: scope.sessionId, cwd: workspace, config: cfg,
              sessionEntry: await call("loadSessionEntry", sessions.loadSessionEntry,
                [{ agentId: scope.agentId, sessionKey: scope.sessionKey, storePath }]) };
            recorder = await call("createUserTurnTranscriptRecorder", recorderModule.t, [{ input: recorderInput, target: recorderTarget }]);
            active.userTurnRecorder = { supplied: true, transcriptInputText, owner: "createUserTurnTranscriptRecorder",
              input: clone(recorderInput), target: wire(recorderTarget) };
          }
          const admission = await call("prepareSystemAgentRunAdmission", admissionModule.d, [cfg, runId, "main", "prompt-runtime-context-fixture"]);
          try {
            const admittedRunContext = await call("PreparedAgentRunAdmission.admit", kind => admission.admit(kind), ["embedded"]);
            const params = { admittedRunContext, sessionId: scope.sessionId, sessionKey: scope.sessionKey,
              sessionTarget: clone(scope), sessionFile: `sqlite:main:${scope.sessionId}:${storePath}`,
              agentId: "main", workspaceDir: workspace, cwd: workspace, agentDir, config: cfg,
              prompt: operation.effectivePrompt, runtimeContextFragments: fragments,
              ...(recorder === undefined ? {} : { userTurnTranscriptRecorder: recorder }),
              ...(Object.hasOwn(operation, "transcriptPrompt") ? { transcriptPrompt: operation.transcriptPrompt } : {}),
              ...(Object.hasOwn(operation, "currentInboundContext") ? { currentInboundContext: clone(operation.currentInboundContext) } : {}),
              ...(Object.hasOwn(operation, "suppressNextUserMessagePersistence") ? { suppressNextUserMessagePersistence: operation.suppressNextUserMessagePersistence } : {}),
              timeoutMs: 30000, runId, provider: PROVIDER, modelId: MODEL, model, authStorage: auth,
              authProfileStore: { version: 1, profiles: {} }, modelRegistry: models, thinkLevel: "off",
              contextTokenBudget: 32000, disableToolSearch: true, disableTrajectory: true, disableMessageTool: true,
              promptMode: "full", trigger: "user", skillsSnapshot: { prompt: "", skills: [] } };
            active.userTurnRecorder.parameterPresent = Object.hasOwn(params, "userTurnTranscriptRecorder");
            active.callArguments = wire([params]);
            const result = await call("OpenClawAgentHarness.runAttempt", values => harness.runAttempt(values), [params]);
            active.apiOutcome = { kind: "return", returnValue: returned(result) };
          } finally { active.admissionClose = returned(await call("PreparedAgentRunAdmission.close", () => admission.close(), [])); }
          if (recorder !== undefined) active.userTurnRecorder.after = { message: wire(recorder.message),
            hasPersisted: await call("UserTurnTranscriptRecorder.hasPersisted", () => recorder.hasPersisted(), []) };
          if (operation.scriptedTools?.some(item => item.name === "memory_search")) {
            active.recallDrain = { importPath: "dist/short-term-promotion-record-CEpBdgKW.mjs",
              moduleObservation: wire(await call("importOriginalRecallModule", () => imp("dist/short-term-promotion-record-CEpBdgKW.mjs"), [])),
              preparationReturn: returned(await call("withMemoryWorkspacePreparation", preparationModule._, [workspace, async () => undefined])) };
          }
          const successful = active.memoryPromptCalls.filter(record => Object.hasOwn(record, "returnValue"));
          const effective = successful.at(-1);
          if (!effective) throw Error("No actual registered memory prompt builder produced an effective section");
          memoryGuidance = { toolAvailability: clone(effective.toolAvailability), lines: clone(effective.returnValue.value) };
        } else throw Error("An undeclared operation reached the original prompt harness");
      } catch (error) { active.apiOutcome = { kind: "throw", error: wire(error) }; }
      active.afterTranscript = await call("loadTranscriptEventsSync", sessions.loadTranscriptEventsSync, [scope]);
      active.afterSql = sql(); active.sourcesAfter = await tree(workspace, true); active.effectiveMemoryGuidance = clone(memoryGuidance);
      const observation = { operation: clone(operation), memoryGuidance, clock: actualClock,
        modelCalls: active.providerCalls.map(record => ({ messages: clone(record.request.context.messages) })) };
      active.observation = clone(observation); observations.push(observation);
      await snapshot(); await capture(String(operationIndex)); active = undefined;
    }
    raw.output = { observations }; return clone(raw.output);
  } catch (error) { raw.error = wire(error); throw error; }
  finally {
    let completed = true;
    if (memoryRegistration && capability && observedBuilder) {
      try {
        memoryRegistration.capability = capability;
        raw.memoryPromptObserver.restored = memoryRegistration.capability === capability
          && capability.promptBuilder === descriptor.value;
      } catch (error) { completed = false; raw.memoryPromptObserver.restoreError = wire(error); }
    }
    for (const [operation, fn] of [["closeAllMemoryIndexManagers", closeManagers], ["disposeSessionMcpRuntime", closeMcp],
      ["GatewayScheduler.stop", scheduler ? () => scheduler.stop() : undefined],
      ["closeOpenClawAgentDatabasesAsync", closeAgents], ["closePluginStateDatabaseAsync", closeState]]) {
      if (!fn) continue;
      try { raw.closeReceipts.push({ operation, returnValue: returned(await call(operation, fn, [])) }); }
      catch (error) { completed = false; raw.closeReceipts.push({ operation, error: wire(error) }); }
    }
    try { await capture("closed"); } catch (error) { completed = false; raw.closeCaptureError = wire(error); }
    if (clearConfig) {
      try { raw.configClearReturn = returned(await call("clearRuntimeConfigSnapshot", clearConfig, [])); }
      catch (error) { completed = false; raw.configClearError = wire(error); }
    }
    delete globalThis[BRIDGE]; raw.closed = completed; mock.timers.reset();
    raw.clock.originalDateRestored = Date === originalDate;
    for (const [key, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
  }
}
