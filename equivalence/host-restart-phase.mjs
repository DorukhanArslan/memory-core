// Real compiled coding/memory tools are passed unchanged to the original
// AgentLoop, including their non-enumerable execution preparers. Only the model
// transport is controlled: later replies are derived from actual tool messages.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { mock } from "node:test";

const OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID = "memory-core";
const transported = value => JSON.parse(JSON.stringify(value));
const errorRecord = error => ({ name: error.name, message: error.message, stack: error.stack });

function validSourcePolicy(policy) {
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) return false;
  const keys = ["configuredSessionMemory", "configuredSources", "rememberAcrossConversations", "sourceMtimeMs"];
  if (Object.hasOwn(policy, "producerPublication")) {
    const publication = policy.producerPublication;
    if (!publication || typeof publication !== "object" || Array.isArray(publication) ||
        Object.keys(publication).join(",") !== "operation" ||
        publication.operation !== "force-rebuild-after-source-metadata") return false;
    keys.push("producerPublication");
  }
  if (Object.hasOwn(policy, "indexLifecycle") || Object.hasOwn(policy, "runtimeIdentity")) {
    if (!Object.hasOwn(policy, "producerPublication") || !["managed", "session-managed"].includes(policy.indexLifecycle) ||
        policy.runtimeIdentity !== "openclaw-compatible") return false;
    keys.push("indexLifecycle", "runtimeIdentity");
  }
  return Object.keys(policy).sort().join(",") === keys.sort().join(",") &&
    Array.isArray(policy.configuredSources) && policy.configuredSources.every(source => ["memory", "sessions"].includes(source)) &&
    typeof policy.rememberAcrossConversations === "boolean" && typeof policy.configuredSessionMemory === "boolean" &&
    Number.isFinite(policy.sourceMtimeMs);
}

function decodeEnvelope(envelope) {
  const value = transported(envelope);
  if (value?.content?.[0]?.type !== "text" || typeof value.content[0].text !== "string") {
    throw Error("The original memory tool supplied no JSON carrier");
  }
  const payload = JSON.parse(value.content[0].text);
  if (!isDeepStrictEqual(payload, value.details)) throw Error("The complete memory carrier differs from details");
  return payload;
}

function contextResult(context, toolName) {
  const message = [...context.messages].reverse().find(item => item.role === "toolResult" && item.toolName === toolName);
  if (!message) throw Error(`The actual model context has no ${toolName} tool result`);
  const carrier = message.content?.find(item => item.type === "text");
  if (!carrier || typeof carrier.text !== "string") throw Error("The actual model context lost its JSON carrier");
  return { message, payload: JSON.parse(carrier.text) };
}

function mutationObservation(filename) {
  try {
    const stat = fsSync.lstatSync(filename);
    const result = { absolutePath: filename, kind: stat.isDirectory() ? "directory" : stat.isFile() ? "file" : "other",
      size: stat.size, mtimeMs: stat.mtimeMs };
    if (stat.isFile()) {
      const bytes = fsSync.readFileSync(filename);
      result.text = bytes.toString("utf8"); result.hex = bytes.toString("hex");
    }
    return result;
  } catch (error) {
    if (error.code === "ENOENT") return { absolutePath: filename, kind: "missing" };
    throw error;
  }
}

async function sourceObservation(workspace, relative) {
  const filename = path.join(workspace, relative);
  try {
    const stat = await fs.lstat(filename);
    if (!stat.isFile()) return { path: relative, kind: stat.isDirectory() ? "directory" : "other" };
    const bytes = await fs.readFile(filename);
    return { path: relative, kind: "file", text: bytes.toString("utf8"), hex: bytes.toString("hex") };
  } catch (error) {
    if (error.code === "ENOENT") return { path: relative, kind: "missing" };
    throw error;
  }
}

async function filesystemObservation(directory) {
  const entries = [];
  async function visit(relative) {
    for (const entry of await fs.readdir(path.join(directory, relative), { withFileTypes: true })) {
      const name = path.join(relative, entry.name), filename = path.join(directory, name);
      const stat = await fs.lstat(filename);
      const row = { path: name.replaceAll(path.sep, "/"), kind: entry.isDirectory() ? "directory" : entry.isFile() ? "file" : "other",
        size: stat.size, mtimeMs: stat.mtimeMs };
      if (entry.isFile()) row.sha256 = createHash("sha256").update(await fs.readFile(filename)).digest("hex");
      entries.push(row);
      if (entry.isDirectory()) await visit(name);
    }
  }
  await visit("");
  return entries;
}

function sqlObservation(manager) {
  const db = manager.db;
  const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
  return { schema, tables: schema.filter(row => row.type === "table").map(({ name }) => {
    const quoted = '"' + name.replaceAll('"', '""') + '"';
    return { name, columns: db.prepare(`PRAGMA table_info(${quoted})`).all(),
      rows: db.prepare(`SELECT * FROM ${quoted}`).all().map(row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
        [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) };
  }) };
}

export async function runHostRestartPhase(request, stdin = JSON.stringify(request)) {
  const { directory, runtimeRoot, nowMs, identity, phase, sourcePath, policy } = request;
  if (![directory, runtimeRoot].every(value => typeof value === "string" && path.isAbsolute(value)) ||
      !Number.isFinite(nowMs) || !["produce", "restart"].includes(phase?.label) ||
      typeof sourcePath !== "string" || path.isAbsolute(sourcePath) || sourcePath.split(/[\\/]/).includes("..")) {
    throw Error("A bounded host phase requires owned locations and its own literal input");
  }
  if (phase.label === "restart" && Object.keys(phase).some(key => !["label", "recall", "beforeGet"].includes(key))) {
    throw Error("The fresh process cannot receive a producer phase or saved content");
  }
  if (policy !== undefined && !validSourcePolicy(policy)) {
    throw Error("The host phase requires the unchanged optional explicit source policy");
  }
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  process.env.OPENCLAW_HOME = directory;
  const cfg = JSON.parse(await fs.readFile(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const workspace = path.join(directory, "workspace"), isolatedWorkspace = path.join(directory, "isolated-workspace");
  const beforeDate = Date, beforeTimeout = setTimeout, beforePerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: nowMs });
  const raw = { kind: "host-restart-recall-phase", label: phase.label, pid: process.pid, ppid: process.ppid,
    executable: process.execPath, execArgv: process.execArgv, request, stdin, config: cfg,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== beforeDate,
      setTimeoutUnchanged: setTimeout === beforeTimeout, performanceNowUnchanged: performance.now === beforePerformance },
    sessions: [], loops: [], toolFactoryCalls: [], toolOutcomes: [], maintenance: [], snapshots: [], mutations: [], closeReceipts: [] };
  const imp = file => import(pathToFileURL(path.join(runtimeRoot, file)).href);
  let clearConfig, closeManagers, closeAgentDatabases, strictTranscriptAppend,
    readTranscriptUpdateVersion, unsubscribeTranscriptUpdates;
  const managers = new Map();
  let output, failure;
  try {
    const runtimeConfig = await imp("dist/plugin-sdk/config-runtime.js");
    runtimeConfig.setRuntimeConfigSnapshot(cfg); clearConfig = runtimeConfig.clearRuntimeConfigSnapshot;
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js");
    closeManagers = runtime.closeAllMemoryIndexManagers;
    if (policy !== undefined) {
      const { t: resolveMemorySearchConfig } = await imp("dist/memory-search-CIhUURbE.mjs");
      raw.resolvedMemorySearch = [identity.agentId, identity.isolatedAgentId].map(agentId => ({
        agentId, config: resolveMemorySearchConfig(cfg, agentId),
      }));
      raw.sourceMetadataSetup = [];
    }
    const lifecycle = await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs");
    closeAgentDatabases = lifecycle.s;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState(options => createPluginStateKeyedStore(OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID, options));
    const { t: createCodingTools } = await imp("dist/agent-tools-HIqp3eTk.mjs");
    const { createMemorySearchTool, createMemoryGetTool } = await imp("dist/tools-DotaQGXh.mjs");
    const core = await imp("dist/plugin-sdk/agent-core.js");
    const { x: createStream } = await imp("dist/llm-ASoRyt-k.mjs");
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    if (policy?.producerPublication !== undefined) {
      const transcript = await imp("dist/plugin-sdk/session-transcript-runtime.js");
      strictTranscriptAppend = transcript.appendSessionTranscriptMessageByIdentityStrict;
      const notifications = await imp("dist/transcript-events-Ce9wKss8.mjs");
      readTranscriptUpdateVersion = notifications.s;
      raw.transcriptUpdates = [];
      raw.transcriptUpdateVersions = { beforeRegistration: readTranscriptUpdateVersion() };
      unsubscribeTranscriptUpdates = notifications.r(update => {
        raw.transcriptUpdates.push({ version: readTranscriptUpdateVersion(), update: transported(update) });
      });
    }
    const artifacts = await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs");
    const model = { id: "fixture-restart-model", name: "Fixture restart model", api: "openai-completions", provider: "openai",
      baseUrl: "https://fixture.invalid", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 10000, maxTokens: 1000 };
    const assistant = (content, stopReason = "stop") => ({ role: "assistant", content, api: model.api,
      provider: model.provider, model: model.id, stopReason, timestamp: nowMs,
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
    const call = (id, name, args) => assistant([{ type: "toolCall", id, name, arguments: args }], "toolUse");
    const terminal = text => assistant([{ type: "text", text }]);

    async function getManager(agentId) {
      if (!managers.has(agentId)) {
        const manager = await runtime.MemoryIndexManager.get({ cfg, agentId });
        if (!manager) throw Error("The original memory manager was unavailable");
        managers.set(agentId, manager);
        raw.maintenance.push({ operation: "MemoryIndexManager.get", agentId, status: manager.status() });
      }
      return managers.get(agentId);
    }

    async function snapshot(label) {
      const memory = [];
      for (const [agentId, manager] of managers) memory.push({ agentId, status: manager.status(), sql: sqlObservation(manager) });
      const transcript = raw.sessions.map(item => ({ scope: item.scope,
        currentEntry: sessions.getSessionEntry(item.scope), events: accessor.loadTranscriptEventsSync(item.scope),
        databasePath: accessor.resolveSessionTranscriptDatabasePath(item.scope) }));
      raw.snapshots.push({ label, memory, transcript,
        source: await sourceObservation(workspace, sourcePath),
        isolatedSource: await sourceObservation(isolatedWorkspace, sourcePath),
        artifacts: await artifacts.n({ workspaceDir: workspace }),
        isolatedArtifacts: await artifacts.n({ workspaceDir: isolatedWorkspace }),
        filesystem: await filesystemObservation(directory) });
    }

    async function runLoop(label, sessionIdentity, agentId, prompt, save) {
      const activeWorkspace = agentId === identity.agentId ? workspace : isolatedWorkspace;
      const scope = { agentId, storePath: sessions.resolveStorePath(undefined, { agentId }),
        sessionKey: sessionIdentity.sessionKey, sessionId: sessionIdentity.sessionId };
      const loadRequest = { storePath: scope.storePath, options: { skipCache: true } };
      const loadedStore = sessions.loadSessionStore(loadRequest.storePath, loadRequest.options);
      if (Object.hasOwn(loadedStore, scope.sessionKey)) throw Error("A declared fresh session already has a persisted store entry");
      const upsertRequest = { ...scope, entry: { sessionId: scope.sessionId, updatedAt: nowMs } };
      const upsert = await sessions.upsertSessionEntry(upsertRequest);
      const initialEvents = accessor.loadTranscriptEventsSync(scope);
      if (initialEvents.length !== 0) throw Error("A declared fresh session already has persisted transcript events");
      const initialMessages = initialEvents.flatMap(event => event.message ? [event.message] : []);
      const session = { label, scope, upsertRequest, upsertResult: upsert, upsertReturnedUndefined: upsert === undefined,
        loadRequest, loadedStore, initialEvents, historyConstruction: { owner: "loadTranscriptEventsSync",
          scope, events: initialEvents, messages: initialMessages, noDiscardedEvents: initialEvents.length === initialMessages.length }, persistence: [] };
      raw.sessions.push(session);
      const loop = { label, scope, modelCalls: [], events: [], toolEvents: [], initialMessages, tools: [] };
      raw.loops.push(loop);
      let tools;
      if (save) {
        const onToolOutcome = value => raw.toolOutcomes.push({ session: label, observation: transported(value) });
        const options = { config: cfg, agentId, workspaceDir: activeWorkspace, cwd: activeWorkspace,
          sessionId: scope.sessionId, sessionKey: scope.sessionKey, runId: `host-restart:${label}`,
          senderIsOwner: true, onToolOutcome, requireWorkspaceOnly: true,
          toolConstructionPlan: { includeBaseCodingTools: true, includeShellTools: false,
            includeChannelTools: false, includeOpenClawTools: false, includePluginTools: false } };
        const supplied = createCodingTools(options);
        const write = supplied.find(tool => tool.name === "write");
        if (!write) throw Error("The genuine coding factory supplied no write tool");
        tools = [write];
        raw.toolFactoryCalls.push({ label, options: { ...options, onToolOutcome: "read-only-original-outcome-recorder" },
          names: supplied.map(tool => tool.name), originalToolObjectPassedToAgentLoop: tools[0] === write,
          hasOwnTaintOption: Object.hasOwn(options, "isTurnTainted") });
      } else {
        const options = { config: cfg, getConfig: () => cfg, agentId, agentSessionKey: scope.sessionKey };
        tools = [createMemorySearchTool(options), createMemoryGetTool(options)];
        if (tools.some(tool => !tool)) throw Error("The original memory factories supplied no tools");
        raw.toolFactoryCalls.push({ label, options: { ...options, getConfig: "actual-config-reader" },
          names: tools.map(tool => tool.name), originalToolObjectsPassedToAgentLoop: true });
      }
      loop.tools = tools.map(tool => ({ name: tool.name, label: tool.label,
        description: tool.description, parameters: transported(tool.parameters),
        ...(tool.resultContentSource ? { resultContentSource: tool.resultContentSource } : {}) }));
      let index = 0, done = false, finalAnswer;
      const streamFn = (_model, context, options) => {
        const ordinal = index++;
        let response, derivation;
        if (save) {
          if (ordinal === 0) response = call(`${label}:write`, "write", { path: save.path, content: save.content });
          else if (ordinal === 1) {
            if (policy !== undefined) {
              const actualWrite = loop.toolEvents.find(event => event.toolName === "write");
              if (!actualWrite || actualWrite.isError) throw Error("Source metadata setup requires a completed genuine write result");
              const filename = path.join(activeWorkspace, save.path);
              const metadata = { operation: "set-source-mtime", trigger: transported(actualWrite),
                before: mutationObservation(filename), calls: [] };
              raw.sourceMetadataSetup.push(metadata);
              const arguments_ = [filename, policy.sourceMtimeMs / 1000, policy.sourceMtimeMs / 1000];
              const result = fsSync.utimesSync(...arguments_);
              metadata.calls.push({ operation: "utimesSync", arguments: arguments_, returnedUndefined: result === undefined });
              metadata.after = mutationObservation(filename);
              metadata.contentUnchanged = metadata.before.hex === metadata.after.hex;
              if (!metadata.contentUnchanged) throw Error("The source metadata operation changed the actual saved corpus bytes");
            }
            response = terminal(phase.saveAck ?? "Saved."); done = true;
          }
          else throw Error("The save model requested an undeclared response");
        } else if (ordinal === 0) {
          response = call(`${label}:search`, "memory_search", { query: phase.recall.query, maxResults: 5, minScore: 0, corpus: "memory" });
        } else if (ordinal === 1) {
          const actual = contextResult(context, "memory_search");
          const hit = actual.payload.results?.[0];
          derivation = { source: "actual-model-context", toolName: "memory_search", message: transported(actual.message), payload: actual.payload };
          if (hit) {
            if (typeof hit.path !== "string" || !Number.isInteger(hit.startLine) || !Number.isInteger(hit.endLine) || hit.startLine < 1 || hit.endLine < hit.startLine) {
              throw Error("The real search hit supplied no valid source range");
            }
            if (label === "restarted" && phase.beforeGet) {
              if (phase.beforeGet.operation !== "replace-source-with-directory" || hit.path !== sourcePath) {
                throw Error("The declared operational mutation must target the selected owned source");
              }
              const selected = path.join(activeWorkspace, hit.path), retired = path.join(directory, "retired-source.md");
              const mutation = { operation: phase.beforeGet.operation, selectedHit: transported(hit),
                before: { source: mutationObservation(selected), retired: mutationObservation(retired) }, calls: [] };
              raw.mutations.push(mutation);
              const renamed = fsSync.renameSync(selected, retired);
              mutation.calls.push({ operation: "renameSync", arguments: [selected, retired], returnedUndefined: renamed === undefined });
              const created = fsSync.mkdirSync(selected);
              mutation.calls.push({ operation: "mkdirSync", arguments: [selected], returnedUndefined: created === undefined });
              mutation.after = { source: mutationObservation(selected), retired: mutationObservation(retired) };
            }
            response = call(`${label}:get`, "memory_get", { path: hit.path, from: hit.startLine,
              lines: hit.endLine - hit.startLine + 1, corpus: "memory" });
          } else { finalAnswer = "No source-backed memory found."; response = terminal(finalAnswer); done = true; }
        } else if (ordinal === 2) {
          const actual = contextResult(context, "memory_get");
          finalAnswer = typeof actual.payload.text === "string" && actual.payload.text.length > 0
            ? actual.payload.text : JSON.stringify(actual.payload);
          derivation = { source: "actual-model-context", toolName: "memory_get", message: transported(actual.message), payload: actual.payload };
          response = terminal(finalAnswer); done = true;
        } else throw Error("The recall model requested an undeclared response");
        loop.modelCalls.push({ ordinal, model: transported(_model), context: transported(context),
          options: transported(options), response: transported(response), ...(derivation ? { derivation } : {}) });
        const stream = createStream();
        queueMicrotask(() => { stream.push({ type: "done", reason: response.stopReason, message: response }); stream.end(); });
        return stream;
      };
      let eventIndex = 0;
      const emit = async event => {
        loop.events.push(transported(event));
        if (event.type === "tool_execution_end") loop.toolEvents.push(transported(event));
        if (event.type === "message_end") {
          const options = { message: event.message, eventId: `${label}:message:${eventIndex++}`, now: nowMs, cwd: activeWorkspace };
          if (strictTranscriptAppend) {
            const params = { ...scope, ...options, config: cfg, updateMode: "inline", runId: `host-restart:${label}` };
            const receipt = { scope, options: transported(options), event: transported(event),
              method: "appendSessionTranscriptMessageByIdentityStrict", params: transported(params),
              versionBefore: readTranscriptUpdateVersion(), updateOffsetBefore: raw.transcriptUpdates.length };
            session.persistence.push(receipt);
            try {
              const result = await strictTranscriptAppend(params);
              Object.assign(receipt, { result, returnedUndefined: result === undefined,
                versionAfter: readTranscriptUpdateVersion(), updateOffsetAfter: raw.transcriptUpdates.length });
              if (result.kind !== "result") throw Error(`The original strict transcript append returned ${result.kind}`);
            } catch (error) {
              receipt.error = errorRecord(error);
              receipt.versionAfter = readTranscriptUpdateVersion();
              receipt.updateOffsetAfter = raw.transcriptUpdates.length;
              throw error;
            }
          } else {
            const result = await accessor.appendTranscriptMessage(scope, options);
            session.persistence.push({ scope, options: transported(options), result, returnedUndefined: result === undefined });
          }
        }
      };
      const user = { role: "user", content: [{ type: "text", text: prompt }], timestamp: nowMs };
      const context = { systemPrompt: "", messages: initialMessages, tools };
      loop.initialContext = { systemPrompt: context.systemPrompt, messages: context.messages, tools: loop.tools };
      loop.prompt = user;
      const messages = await core.runAgentLoop([user], context,
        { model, convertToLlm: core.convertToLlm, toolExecution: "sequential", shouldStopAfterTurn: () => done },
        emit, undefined, streamFn);
      loop.messages = transported(messages);
      if (loop.toolEvents.some(event => event.isError)) throw Error("A genuine host tool failed; complete original result is retained");
      if (save) return { messages, toolEvents: loop.toolEvents };
      const searchEvent = loop.toolEvents.find(event => event.toolName === "memory_search");
      if (!searchEvent) throw Error("The actual AgentLoop did not dispatch memory_search");
      const getEvent = loop.toolEvents.find(event => event.toolName === "memory_get");
      const lastAssistant = [...messages].reverse().find(message => message.role === "assistant");
      const answer = lastAssistant?.content?.filter(item => item.type === "text").map(item => item.text).join("");
      if (answer !== finalAnswer) throw Error("The terminal AgentLoop message differs from its actual tool-derived reply");
      return { session: label, query: phase.recall.query, search: decodeEnvelope(searchEvent.result),
        get: getEvent ? decodeEnvelope(getEvent.result) : null, answer };
    }

    const reads = [];
    if (phase.label === "produce") {
      raw.initialSource = await sourceObservation(workspace, sourcePath);
      if (raw.initialSource.kind !== "missing" || phase.write.path !== sourcePath) throw Error("The producer source must begin absent at its declared location");
      await runLoop("writer", identity.writer, identity.agentId, phase.savePrompt, phase.write);
      const manager = await getManager(identity.agentId);
      manager.markMemoryWatchDirty(); raw.maintenance.push({ operation: "markMemoryWatchDirty", agentId: identity.agentId });
      const syncRequest = policy?.producerPublication !== undefined
        ? { reason: "host-restart-producer-publication", force: true }
        : { reason: "host-restart-fixture" };
      const synced = await manager.sync(syncRequest);
      raw.maintenance.push({ operation: "sync", request: syncRequest, agentId: identity.agentId,
        result: synced, returnedUndefined: synced === undefined, status: manager.status() });
      await snapshot("after-real-write-and-explicit-sync");
      reads.push(await runLoop("fresh", identity.fresh, identity.agentId, phase.recall.prompt));
    } else {
      // No dirty marker, repair, force or sync occurs in this process before search.
      reads.push(await runLoop("restarted", identity.restarted, identity.agentId, phase.recall.prompt));
      reads.push(await runLoop("isolated", identity.isolated, identity.isolatedAgentId, phase.recall.prompt));
      await getManager(identity.agentId);
      await getManager(identity.isolatedAgentId);
    }
    await snapshot("after-active-recall");
    output = { result: { label: phase.label, reads, source: await sourceObservation(workspace, sourcePath) }, raw };
  } catch (error) {
    failure = error;
    raw.failure = errorRecord(error);
  } finally {
    for (const [operation, close] of [["closeAllMemoryIndexManagers", closeManagers],
      ["closeOpenClawAgentDatabasesAsync", closeAgentDatabases]]) {
      if (!close) continue;
      try {
        const result = operation === "closeOpenClawAgentDatabasesAsync" ? await close(directory) : await close();
        raw.closeReceipts.push({ operation, completed: true, result, returnedUndefined: result === undefined });
      } catch (error) {
        raw.closeReceipts.push({ operation, completed: false, error: errorRecord(error) });
        failure ??= error;
      }
    }
    if (readTranscriptUpdateVersion) raw.transcriptUpdateVersions.afterClose = readTranscriptUpdateVersion();
    unsubscribeTranscriptUpdates?.();
    clearConfig?.(); mock.timers.reset();
    await fs.writeFile(path.join(directory, `${phase.label}-raw.json`), JSON.stringify(raw));
  }
  if (failure) {
    const error = new Error(failure.message, { cause: failure });
    error.name = failure.name;
    throw error;
  }
  return output;
}
