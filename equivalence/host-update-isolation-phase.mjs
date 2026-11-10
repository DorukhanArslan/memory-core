// Real compiled coding/memory tools are passed unchanged to the original
// AgentLoop. Only the model transport is controlled: every later reply is
// derived from the actual tool messages. The update replaces one saved
// preference through the original `edit` tool; declared faults are real
// filesystem states, never simulated results.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { mock } from "node:test";

const OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID = "memory-core";
const FAULTS = ["source-hard-link-during-update", "index-publication-sidecar-symlink"];
const transported = value => JSON.parse(JSON.stringify(value));
const errorRecord = error => ({ name: error.name, message: error.message, code: error.code, stack: error.stack });

function validSourcePolicy(policy) {
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) return false;
  const keys = ["configuredSessionMemory", "configuredSources", "indexLifecycle", "producerPublication",
    "rememberAcrossConversations", "runtimeIdentity", "sourceMtimeMs"];
  const publication = policy.producerPublication;
  return Object.keys(policy).sort().join(",") === keys.join(",") &&
    publication && typeof publication === "object" && !Array.isArray(publication) &&
    Object.keys(publication).join(",") === "operation" &&
    publication.operation === "force-rebuild-after-source-metadata" &&
    policy.indexLifecycle === "session-managed" && policy.runtimeIdentity === "openclaw-compatible" &&
    Array.isArray(policy.configuredSources) && policy.configuredSources.join(",") === "memory" &&
    policy.rememberAcrossConversations === false && policy.configuredSessionMemory === false &&
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
  if (!carrier || typeof carrier.text !== "string") throw Error("The actual model context lost its text carrier");
  return { message, text: carrier.text };
}

function pathObservation(filename) {
  try {
    const stat = fsSync.lstatSync(filename);
    const result = { absolutePath: filename, kind: stat.isSymbolicLink() ? "symlink" : stat.isDirectory() ? "directory"
      : stat.isFile() ? "file" : "other", size: stat.size, mtimeMs: stat.mtimeMs, nlink: stat.nlink };
    if (stat.isSymbolicLink()) result.target = fsSync.readlinkSync(filename);
    if (stat.isFile()) {
      const bytes = fsSync.readFileSync(filename);
      result.sha256 = createHash("sha256").update(bytes).digest("hex");
      if (bytes.length <= 65536) result.hex = bytes.toString("hex");
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

// A diagnostic listing only; no guard reads it. A detached synchronization of the
// original may still hold its lease when the listing starts and delete the lease
// journal while it runs. Such an entry is recorded as vanished, not treated as a
// host failure. Every other error still fails the host.
export async function filesystemObservation(directory, api = fs) {
  const entries = [];
  const vanished = error => error?.code === "ENOENT";
  async function visit(relative) {
    let listing;
    try {
      listing = await api.readdir(path.join(directory, relative), { withFileTypes: true });
    } catch (error) {
      if (!vanished(error) || relative === "") throw error;
      entries.push({ path: relative.replaceAll(path.sep, "/"), kind: "vanished" });
      return;
    }
    for (const entry of listing) {
      const name = path.join(relative, entry.name), filename = path.join(directory, name);
      const row = { path: name.replaceAll(path.sep, "/"), kind: entry.isDirectory() ? "directory" : entry.isFile() ? "file" : "other" };
      try {
        const stat = await api.lstat(filename);
        Object.assign(row, { size: stat.size, mtimeMs: stat.mtimeMs });
        if (entry.isFile()) row.sha256 = createHash("sha256").update(await api.readFile(filename)).digest("hex");
      } catch (error) {
        if (!vanished(error)) throw error;
        entries.push({ path: row.path, kind: "vanished" });
        continue;
      }
      entries.push(row);
      if (entry.isDirectory()) await visit(name);
    }
  }
  await visit("");
  return entries;
}

function memoryIndexObservation(manager) {
  const db = manager.db;
  const names = db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name LIKE 'memory_index_%' ORDER BY name").all()
    .map(row => row.name).filter(name => !/_fts_(config|content|data|docsize|idx)$/.test(name));
  return names.map(name => {
    const quoted = '"' + name.replaceAll('"', '""') + '"';
    return { name, rows: db.prepare(`SELECT * FROM ${quoted}`).all().map(row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
      [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) };
  });
}

export async function runHostUpdateIsolationPhase(request, stdin = JSON.stringify(request)) {
  const { directory, runtimeRoot, nowMs, identity, phase, sourcePath, policy } = request;
  if (![directory, runtimeRoot].every(value => typeof value === "string" && path.isAbsolute(value)) ||
      !Number.isFinite(nowMs) || !["produce", "update"].includes(phase?.label) || sourcePath !== "MEMORY.md" ||
      Object.keys(request).sort().join(",") !== "directory,identity,nowMs,phase,policy,runtimeRoot,sourcePath") {
    throw Error("A bounded host phase requires owned locations and its own literal input");
  }
  const phaseKeys = Object.keys(phase).sort().join(",");
  if (phase.label === "produce" ? phaseKeys !== "isolatedSave,label,recall,save,supersededRecall"
    : !["label,recalls,update", "fault,label,recalls,update"].includes(phaseKeys)) {
    throw Error("A host phase accepts only its own declared instructions");
  }
  if (phase.fault !== undefined && (Object.keys(phase.fault).join(",") !== "operation" || !FAULTS.includes(phase.fault.operation))) {
    throw Error("Only the two declared real fault boundaries are admitted");
  }
  if (!validSourcePolicy(policy)) throw Error("The host phase requires the unchanged explicit source policy");
  const fault = phase.fault?.operation;
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  process.env.OPENCLAW_HOME = directory;
  const cfg = JSON.parse(await fs.readFile(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const workspaces = { [identity.agentId]: path.join(directory, "workspace"),
    [identity.isolatedAgentId]: path.join(directory, "isolated-workspace") };
  const sourceFile = agentId => path.join(workspaces[agentId], sourcePath);
  const beforeDate = Date, beforeTimeout = setTimeout, beforePerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: nowMs });
  const raw = { kind: "host-update-isolation-phase", label: phase.label, pid: process.pid, ppid: process.ppid,
    executable: process.execPath, execArgv: process.execArgv, request, stdin, config: cfg,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== beforeDate,
      setTimeoutUnchanged: setTimeout === beforeTimeout, performanceNowUnchanged: performance.now === beforePerformance },
    sessions: [], loops: [], toolFactoryCalls: [], toolOutcomes: [], maintenance: [], snapshots: [],
    mutations: [], sourceMetadataSetup: [], publications: [], transcriptUpdates: [], closeReceipts: [] };
  const imp = file => import(pathToFileURL(path.join(runtimeRoot, file)).href);
  let clearConfig, closeManagers, closeAgentDatabases, readTranscriptUpdateVersion, unsubscribeTranscriptUpdates;
  const managers = new Map();
  let output, failure;
  try {
    const runtimeConfig = await imp("dist/plugin-sdk/config-runtime.js");
    runtimeConfig.setRuntimeConfigSnapshot(cfg); clearConfig = runtimeConfig.clearRuntimeConfigSnapshot;
    const runtime = await imp("dist/extensions/memory-core/manager-runtime.js");
    closeManagers = runtime.closeAllMemoryIndexManagers;
    const { t: resolveMemorySearchConfig } = await imp("dist/memory-search-CIhUURbE.mjs");
    raw.resolvedMemorySearch = [identity.agentId, identity.isolatedAgentId].map(agentId => ({
      agentId, config: resolveMemorySearchConfig(cfg, agentId) }));
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
    const transcript = await imp("dist/plugin-sdk/session-transcript-runtime.js");
    const strictTranscriptAppend = transcript.appendSessionTranscriptMessageByIdentityStrict;
    const notifications = await imp("dist/transcript-events-Ce9wKss8.mjs");
    readTranscriptUpdateVersion = notifications.s;
    raw.transcriptUpdateVersions = { beforeRegistration: readTranscriptUpdateVersion() };
    unsubscribeTranscriptUpdates = notifications.r(update => {
      raw.transcriptUpdates.push({ version: readTranscriptUpdateVersion(), update: transported(update) });
    });
    const artifacts = await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs");
    const model = { id: "fixture-update-model", name: "Fixture update model", api: "openai-completions", provider: "openai",
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
      for (const [agentId, manager] of managers) memory.push({ agentId, status: manager.status(), index: memoryIndexObservation(manager) });
      raw.snapshots.push({ label, memory,
        transcript: raw.sessions.map(item => ({ scope: item.scope, currentEntry: sessions.getSessionEntry(item.scope),
          events: accessor.loadTranscriptEventsSync(item.scope),
          databasePath: accessor.resolveSessionTranscriptDatabasePath(item.scope) })),
        source: await sourceObservation(workspaces[identity.agentId], sourcePath),
        isolatedSource: await sourceObservation(workspaces[identity.isolatedAgentId], sourcePath),
        artifacts: await artifacts.n({ workspaceDir: workspaces[identity.agentId] }),
        isolatedArtifacts: await artifacts.n({ workspaceDir: workspaces[identity.isolatedAgentId] }),
        filesystem: await filesystemObservation(directory) });
    }

    // One explicit source-metadata operation after every completed genuine write.
    function setSourceMtime(agentId, trigger) {
      const filename = sourceFile(agentId);
      const metadata = { operation: "set-source-mtime", agentId, trigger: transported(trigger),
        before: pathObservation(filename), calls: [] };
      raw.sourceMetadataSetup.push(metadata);
      const arguments_ = [filename, policy.sourceMtimeMs / 1000, policy.sourceMtimeMs / 1000];
      const result = fsSync.utimesSync(...arguments_);
      metadata.calls.push({ operation: "utimesSync", arguments: arguments_, returnedUndefined: result === undefined });
      metadata.after = pathObservation(filename);
      if (metadata.before.sha256 !== metadata.after.sha256) throw Error("The source metadata operation changed the actual saved corpus bytes");
    }

    // The original forced producer publication. A failure is returned, never hidden.
    async function publish(agentId, stage) {
      const manager = await getManager(agentId);
      manager.markMemoryWatchDirty();
      const request_ = { reason: "host-update-isolation-producer-publication", force: true };
      const record = { stage, agentId, operation: "sync", request: request_, statusBefore: manager.status() };
      raw.publications.push(record);
      try {
        const synced = await manager.sync(request_);
        Object.assign(record, { failed: false, returnedUndefined: synced === undefined, statusAfter: manager.status() });
      } catch (error) {
        Object.assign(record, { failed: true, error: errorRecord(error), statusAfter: manager.status() });
      }
      return { agentId, stage, failed: record.failed, error: record.failed ? record.error.message : null };
    }

    async function runLoop(label, sessionIdentity, agentId, prompt, script) {
      const activeWorkspace = workspaces[agentId];
      const scope = { agentId, storePath: sessions.resolveStorePath(undefined, { agentId }),
        sessionKey: sessionIdentity.sessionKey, sessionId: sessionIdentity.sessionId };
      const loadRequest = { storePath: scope.storePath, options: { skipCache: true } };
      const loadedStore = sessions.loadSessionStore(loadRequest.storePath, loadRequest.options);
      if (Object.hasOwn(loadedStore, scope.sessionKey)) throw Error("A declared fresh session already has a persisted store entry");
      const upsertRequest = { ...scope, entry: { sessionId: scope.sessionId, updatedAt: nowMs } };
      const upsert = await sessions.upsertSessionEntry(upsertRequest);
      const initialEvents = accessor.loadTranscriptEventsSync(scope);
      if (initialEvents.length !== 0) throw Error("A declared fresh session already has persisted transcript events");
      const initialMessages = [];
      const session = { label, scope, upsertRequest, upsertResult: upsert, upsertReturnedUndefined: upsert === undefined,
        loadRequest, loadedStore, initialEvents, persistence: [] };
      raw.sessions.push(session);
      const loop = { label, kind: script.kind, scope, modelCalls: [], events: [], toolEvents: [], initialMessages, tools: [] };
      raw.loops.push(loop);
      let tools;
      const mutating = script.kind === "save" || script.kind === "update";
      if (mutating) {
        const onToolOutcome = value => raw.toolOutcomes.push({ session: label, observation: transported(value) });
        const options = { config: cfg, agentId, workspaceDir: activeWorkspace, cwd: activeWorkspace,
          sessionId: scope.sessionId, sessionKey: scope.sessionKey, runId: `host-update-isolation:${label}`,
          senderIsOwner: true, onToolOutcome, requireWorkspaceOnly: true,
          toolConstructionPlan: { includeBaseCodingTools: true, includeShellTools: false,
            includeChannelTools: false, includeOpenClawTools: false, includePluginTools: false } };
        const supplied = createCodingTools(options);
        const name = script.kind === "save" ? "write" : "edit";
        const tool = supplied.find(item => item.name === name);
        if (!tool) throw Error(`The genuine coding factory supplied no ${name} tool`);
        tools = [tool];
        raw.toolFactoryCalls.push({ label, options: { ...options, onToolOutcome: "read-only-original-outcome-recorder" },
          names: supplied.map(item => item.name), originalToolObjectPassedToAgentLoop: tools[0] === tool });
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
      let index = 0, done = false, finalAnswer, committed;
      const linked = path.join(directory, "retained-source-link.md");
      const streamFn = (_model, context, options) => {
        const ordinal = index++;
        let response, derivation;
        if (script.kind === "save") {
          if (ordinal === 0) response = call(`${label}:write`, "write", { path: sourcePath, content: script.save.content });
          else if (ordinal === 1) {
            const actualWrite = loop.toolEvents.find(event => event.toolName === "write");
            if (!actualWrite || actualWrite.isError) throw Error("The producer requires a completed genuine write result");
            setSourceMtime(agentId, actualWrite);
            finalAnswer = script.save.ack; response = terminal(finalAnswer); done = true;
          } else throw Error("The save model requested an undeclared response");
        } else if (script.kind === "update") {
          if (ordinal === 0) {
            if (fault === "source-hard-link-during-update") {
              const mutation = { operation: fault, stage: "before-update-tool", before: pathObservation(sourceFile(agentId)), calls: [] };
              raw.mutations.push(mutation);
              const result = fsSync.linkSync(sourceFile(agentId), linked);
              mutation.calls.push({ operation: "linkSync", arguments: [sourceFile(agentId), linked], returnedUndefined: result === undefined });
              mutation.after = pathObservation(sourceFile(agentId));
            }
            response = call(`${label}:edit`, "edit", { path: sourcePath,
              edits: [{ oldText: script.update.old, newText: script.update.new }] });
          } else if (ordinal === 1) {
            const actual = contextResult(context, "edit");
            const event = loop.toolEvents.find(item => item.toolName === "edit");
            if (!event) throw Error("The actual AgentLoop did not dispatch edit");
            committed = event.isError !== true;
            derivation = { source: "actual-model-context", toolName: "edit", message: transported(actual.message), committed };
            if (fault === "source-hard-link-during-update") {
              const mutation = { operation: fault, stage: "after-update-tool", before: pathObservation(sourceFile(agentId)), calls: [] };
              raw.mutations.push(mutation);
              const result = fsSync.unlinkSync(linked);
              mutation.calls.push({ operation: "unlinkSync", arguments: [linked], returnedUndefined: result === undefined });
              mutation.after = pathObservation(sourceFile(agentId));
            }
            if (committed) setSourceMtime(agentId, event);
            finalAnswer = committed ? script.update.ack : script.update.failureAck;
            response = terminal(finalAnswer); done = true;
          } else throw Error("The update model requested an undeclared response");
        } else if (ordinal === 0) {
          response = call(`${label}:search`, "memory_search", { query: script.recall.query, maxResults: 5, minScore: 0, corpus: "memory" });
        } else if (ordinal === 1) {
          const actual = contextResult(context, "memory_search");
          const payload = JSON.parse(actual.text);
          const hit = payload.results?.[0];
          derivation = { source: "actual-model-context", toolName: "memory_search", message: transported(actual.message), payload };
          if (hit) {
            if (typeof hit.path !== "string" || !Number.isInteger(hit.startLine) || !Number.isInteger(hit.endLine) || hit.startLine < 1 || hit.endLine < hit.startLine) {
              throw Error("The real search hit supplied no valid source range");
            }
            response = call(`${label}:get`, "memory_get", { path: hit.path, from: hit.startLine,
              lines: hit.endLine - hit.startLine + 1, corpus: "memory" });
          } else { finalAnswer = "No source-backed memory found."; response = terminal(finalAnswer); done = true; }
        } else if (ordinal === 2) {
          const actual = contextResult(context, "memory_get");
          const payload = JSON.parse(actual.text);
          finalAnswer = typeof payload.text === "string" && payload.text.length > 0 ? payload.text : JSON.stringify(payload);
          derivation = { source: "actual-model-context", toolName: "memory_get", message: transported(actual.message), payload };
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
          const params = { ...scope, ...options, config: cfg, updateMode: "inline", runId: `host-update-isolation:${label}` };
          const receipt = { scope, options: transported(options), event: transported(event),
            method: "appendSessionTranscriptMessageByIdentityStrict", params: transported(params),
            versionBefore: readTranscriptUpdateVersion(), updateOffsetBefore: raw.transcriptUpdates.length };
          session.persistence.push(receipt);
          try {
            const result = await strictTranscriptAppend(params);
            Object.assign(receipt, { result, versionAfter: readTranscriptUpdateVersion(), updateOffsetAfter: raw.transcriptUpdates.length });
            if (result.kind !== "result") throw Error(`The original strict transcript append returned ${result.kind}`);
          } catch (error) {
            receipt.error = errorRecord(error);
            throw error;
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
      const lastAssistant = [...messages].reverse().find(message => message.role === "assistant");
      const answer = lastAssistant?.content?.filter(item => item.type === "text").map(item => item.text).join("");
      if (answer !== finalAnswer) throw Error("The terminal AgentLoop message differs from its actual tool-derived reply");
      const failed = loop.toolEvents.filter(event => event.isError);
      if (script.kind === "update") {
        if (loop.toolEvents.length !== 1 || loop.toolEvents[0].toolName !== "edit") throw Error("The update requires exactly one genuine edit result");
        if ((fault === "source-hard-link-during-update") === committed) {
          throw Error("The declared update outcome did not occur; complete original result is retained");
        }
        return { committed, answer };
      }
      if (failed.length) throw Error("A genuine host tool failed; complete original result is retained");
      if (script.kind === "save") return { answer };
      const searchEvent = loop.toolEvents.find(event => event.toolName === "memory_search");
      if (!searchEvent) throw Error("The actual AgentLoop did not dispatch memory_search");
      const getEvent = loop.toolEvents.find(event => event.toolName === "memory_get");
      return { session: label, query: script.recall.query, search: decodeEnvelope(searchEvent.result),
        get: getEvent ? decodeEnvelope(getEvent.result) : null, answer };
    }

    const reads = [], publications = [];
    const recall = (label, agentId, instruction) => runLoop(label, identity[label], agentId, instruction.prompt, { kind: "recall", recall: instruction });
    let update;
    if (phase.label === "produce") {
      for (const agentId of [identity.agentId, identity.isolatedAgentId]) {
        if ((await sourceObservation(workspaces[agentId], sourcePath)).kind !== "missing") throw Error("Every producer source must begin absent");
      }
      await runLoop("writer", identity.writer, identity.agentId, phase.save.prompt, { kind: "save", save: phase.save });
      await runLoop("isolatedWriter", identity.isolatedWriter, identity.isolatedAgentId, phase.isolatedSave.prompt,
        { kind: "save", save: phase.isolatedSave });
      publications.push(await publish(identity.agentId, "produce"), await publish(identity.isolatedAgentId, "produce"));
      if (publications.some(item => item.failed)) throw Error("The producer publication failed; complete original result is retained");
      await snapshot("after-real-writes-and-explicit-publication");
      reads.push(await recall("before", identity.agentId, phase.recall));
      // Positive control: the query that must find nothing after a committed update finds the entry now.
      reads.push(await recall("supersededBefore", identity.agentId, phase.supersededRecall));
      reads.push(await recall("isolatedBefore", identity.isolatedAgentId, phase.recall));
    } else {
      const sidecar = path.join(directory, "state", "agents", identity.agentId, "agent", "openclaw-agent.sqlite.reindex-lock.sqlite");
      const retired = path.join(directory, "retired-reindex-lock.sqlite");
      if (fault === "index-publication-sidecar-symlink") {
        const mutation = { operation: fault, stage: "before-update", sidecar, before: pathObservation(sidecar), calls: [] };
        raw.mutations.push(mutation);
        if (mutation.before.kind !== "file") throw Error("The original publication sidecar must exist before the declared fault");
        const renamed = fsSync.renameSync(sidecar, retired);
        mutation.calls.push({ operation: "renameSync", arguments: [sidecar, retired], returnedUndefined: renamed === undefined });
        const target = path.join(directory, "missing-sidecar-directory", "lock");
        const linked = fsSync.symlinkSync(target, sidecar);
        mutation.calls.push({ operation: "symlinkSync", arguments: [target, sidecar], returnedUndefined: linked === undefined });
        mutation.after = pathObservation(sidecar);
      }
      update = await runLoop("updater", identity.updater, identity.agentId, phase.update.prompt, { kind: "update", update: phase.update });
      if (fault === "index-publication-sidecar-symlink") {
        const faulted = await publish(identity.agentId, "faulted");
        publications.push(faulted);
        if (!faulted.failed) throw Error("The declared publication failure did not occur; complete original result is retained");
        reads.push(await recall("stale", identity.agentId, phase.recalls.current));
        const mutation = { operation: fault, stage: "after-stale-read", sidecar, before: pathObservation(sidecar), calls: [] };
        raw.mutations.push(mutation);
        const removed = fsSync.unlinkSync(sidecar);
        mutation.calls.push({ operation: "unlinkSync", arguments: [sidecar], returnedUndefined: removed === undefined });
        const restored = fsSync.renameSync(retired, sidecar);
        mutation.calls.push({ operation: "renameSync", arguments: [retired, sidecar], returnedUndefined: restored === undefined });
        mutation.after = pathObservation(sidecar);
      }
      const final = await publish(identity.agentId, "final");
      publications.push(final);
      if (final.failed) throw Error("The final producer publication failed; complete original result is retained");
      await snapshot("after-update-and-explicit-publication");
      reads.push(await recall("current", identity.agentId, phase.recalls.current));
      reads.push(await recall("superseded", identity.agentId, phase.recalls.superseded));
      reads.push(await recall("unrelated", identity.agentId, phase.recalls.unrelated));
      reads.push(await recall("isolated", identity.isolatedAgentId, phase.recalls.isolated));
      await getManager(identity.isolatedAgentId);
    }
    await snapshot("after-active-recall");
    output = { result: { label: phase.label, ...(update ? { update } : {}), publications, reads,
      source: await sourceObservation(workspaces[identity.agentId], sourcePath),
      isolatedSource: await sourceObservation(workspaces[identity.isolatedAgentId], sourcePath) }, raw };
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
