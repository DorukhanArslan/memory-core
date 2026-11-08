// Model-free provider fixture. Native code owns session preparation, the agent
// tool loop, append/provenance, index search and the final cycle stamp.
import fs from "node:fs/promises";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const FIXTURE_PROVIDER = "fixture-memory-model";
const BRIDGE = Symbol.for("memory-core.equivalence.flush-model-bridge");
const ENTRY_FIELDS = ["totalTokens", "totalTokensFresh", "totalTokensVersion", "compactionCount", "memoryFlush"];
const jsonValue = (value) => JSON.parse(JSON.stringify(value));
const ownedEntry = (entry) => Object.fromEntries(ENTRY_FIELDS.filter((key) => Object.hasOwn(entry, key)).map((key) => [key, jsonValue(entry[key])]));

export default {
  id: FIXTURE_PROVIDER,
  register(api) {
    globalThis[BRIDGE]?.progress("provider-plugin-registered");
    api.registerProvider({
      id: FIXTURE_PROVIDER, label: "Memory equivalence scripted provider", auth: [],
      createStreamFn() {
        const bridge = globalThis[BRIDGE];
        if (!bridge) throw Error("The owned scripted provider bridge is unavailable");
        bridge.progress("provider-stream-created");
        return bridge.stream;
      },
    });
  },
};

export async function runFlushExecution(input, config) {
  if (!config?.runtimeRoot || !path.isAbsolute(config.runtimeRoot)) throw Error("An authenticated absolute runtime root is required");
  const imp = (relative) => import(pathToFileURL(path.join(config.runtimeRoot, relative)).href);
  // Use the original loader's tested cache opt-out. Generated filesystem code
  // must never acquire authority alongside authenticated package/fixture bytes.
  const previousJitiCache = process.env.JITI_FS_CACHE;
  process.env.JITI_FS_CACHE = "false";
  await fs.mkdir(config.stateDirectory, { recursive: true });
  await fs.mkdir(config.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(config.stateDirectory, "flush-execution-"));
  const workspace = path.join(directory, "workspace");
  await fs.mkdir(workspace);
  const provider = FIXTURE_PROVIDER;
  const modelId = "scripted-model";
  const nowMs = input.nowMs ?? 1777824000000;
  const raw = [];
  const snapshots = [];
  const progressRows = [];
  const progress = (phase) => {
    progressRows.push({ phase, at: Date.now() });
    writeFileSync(path.join(config.evidenceDirectory, "native-progress.json"), JSON.stringify(progressRows));
  };
  const { t: runMemoryFlushIfNeeded } = await imp("dist/agent-runner-memory-Cc4lCZcs.mjs");
  const { w: setActivePluginRegistry } = await imp("dist/runtime-9cxii0oQ.mjs");
  const { t: createEmptyPluginRegistry } = await imp("dist/registry-empty-BTjzcMW2.mjs");
  const { p: registerMemoryCapability, r: clearMemoryPluginState } = await imp("dist/memory-state-BmtUbXjH.mjs");
  const sessions = await imp("dist/session-accessor-CiKKTlbe.mjs");
  const { t: createSessionTranscriptHeader } = await imp("dist/transcript-header-CP-ow2Zr.mjs");
  const { t: GatewayScheduler } = await imp("dist/gateway-scheduler-TywODsdc.mjs");
  const { p: setSessionMcpRuntimeScheduler, i: disposeAllSessionMcpRuntimes } = await imp("dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs");
  const { f: onAgentEvent } = await imp("dist/agent-events-CwU5G442.mjs");
  const { n: listMemoryArtifactProvenance } = await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs");
  const aiPackage = config.packages.find((entry) => entry.name === "@openclaw/ai");
  const { createAssistantMessageEventStream } = await import(pathToFileURL(path.join(aiPackage.directory, "dist/event-stream.mjs")).href);
  const scheduler = new GatewayScheduler();
  await setSessionMcpRuntimeScheduler(scheduler);
  let manager;
  let removeObserver;
  let target;
  let activeStep;
  let replyIndex = 0;
  let activeReplies = [];
  let modelCalls = [];
  let toolEvents = [];
  let activeController;
  let sourceScope;
  let duringRunPatchApplied = false;

  const stream = (model, context) => {
    progress("model-stream-called");
    const reply = activeReplies[replyIndex++];
    if (!reply) throw Error("The fixture script exhausted its labelled model replies");
    const runContexts = [...(globalThis[Symbol.for("openclaw.agentRunRegistry.state")]?.contexts ?? [])]
      .filter(([, value]) => value.sessionKey?.includes(":internal-session-effects:"))
      .map(([runId, value]) => ({ runId, sessionId: value.sessionId, sessionKey: value.sessionKey,
        isControlUiVisible: value.isControlUiVisible, projectSessionMessages: value.projectSessionMessages }));
    modelCalls.push({ model: { id: model.id, provider: model.provider, api: model.api },
      context: jsonValue(context), reply: jsonValue(reply), runContexts });
    const content = reply.toolCalls?.length ? reply.toolCalls.map((call, index) => ({
      type: "toolCall", id: call.id ?? `fixture-${replyIndex}-${index}`, name: call.name,
      arguments: { ...call.arguments, ...(call.arguments.path === "@target" ? { path: target } : {}) },
    })) : [{ type: "text", text: reply.text ?? "" }];
    const assistant = {
      role: "assistant", content, api: model.api, provider: model.provider, model: model.id,
      stopReason: reply.cancel ? "aborted" : reply.error ? "error" : reply.toolCalls?.length ? "toolUse" : "stop",
      timestamp: Date.now(),
      ...(reply.error ? { errorMessage: reply.error, content: [] } : {}),
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    };
    const result = createAssistantMessageEventStream();
    queueMicrotask(async () => {
      try {
        if (activeStep?.duringRunEntryPatch && !duringRunPatchApplied) {
          duringRunPatchApplied = true;
          await sessions.updateSessionEntry(sourceScope, () => activeStep.duringRunEntryPatch,
            { skipMaintenance: true, takeCacheOwnership: true });
        }
        if (reply.cancel) activeController.abort(new Error("fixture caller cancelled"));
        if (reply.error || reply.cancel) result.push({ type: "error", reason: assistant.stopReason, error: assistant });
        else result.push({ type: "done", reason: assistant.stopReason, message: assistant });
        result.end(assistant);
      } catch (error) {
        assistant.stopReason = "error";
        assistant.errorMessage = error.message;
        result.push({ type: "error", reason: "error", error: assistant });
        result.end(assistant);
      }
    });
    return result;
  };
  globalThis[BRIDGE] = { stream, progress };
  setActivePluginRegistry(createEmptyPluginRegistry(), "startup-registry", "gateway-bindable", workspace);
  try {
    const { default: memoryPlugin } = await imp("dist/extensions/memory-core/index.js");
    const captured = Symbol("native flush plan registered");
    let originalPlanResolver;
    const noop = () => {};
    const api = new Proxy({ runtime: { llm: {}, state: {}, config: {} }, config: {},
      logger: { info: noop, warn: noop, error: noop, debug: noop },
      registerMemoryCapability(capability) { originalPlanResolver = capability.flushPlanResolver; throw captured; },
    }, { get: (object, name) => object[name] ?? noop });
    try { memoryPlugin.register(api); } catch (error) { if (error !== captured) throw error; }
    if (typeof originalPlanResolver !== "function") throw Error("The original native flush plan is unavailable");
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const cfg = {
      plugins: { allow: [provider], load: { paths: [fileURLToPath(import.meta.url)] },
        entries: { [provider]: { enabled: true } }, slots: { memory: "none" } },
      agents: { list: [{ id: "main", default: true, workspace, agentDir: path.join(directory, "agent") }],
        defaults: { workspace, model: { primary: `${provider}/${modelId}` }, compaction: { memoryFlush: {} } } },
      memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"],
        store: { vector: { enabled: false } } } },
      models: { providers: { [provider]: { api: "openai-completions", baseUrl: "http://127.0.0.1:1/v1",
        apiKey: "fixture-not-a-credential", models: [{ id: modelId, name: "Scripted fixture", api: "openai-completions",
          reasoning: false, input: ["text"], contextWindow: 200000, maxTokens: 4096,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } },
    };
    const planCapability = { flushPlanResolver(params) {
      progress("plan-resolved");
      const plan = originalPlanResolver({ ...params, nowMs });
      target = plan?.relativePath; return plan;
    } };
    target = originalPlanResolver({ cfg, nowMs, contextWindowTokens: 200000 }).relativePath;
    if (input.target && input.target !== target) throw Error("The fixture target disagrees with the original native plan");
    const targetFile = path.join(workspace, target);
    if (input.initialText !== null && input.initialText !== undefined) {
      await fs.mkdir(path.dirname(targetFile), { recursive: true });
      await fs.writeFile(targetFile, input.initialText, "utf8");
    }
    for (const [relative, text] of Object.entries(input.protectedFiles ?? {})) {
      await fs.mkdir(path.dirname(path.join(workspace, relative)), { recursive: true });
      await fs.writeFile(path.join(workspace, relative), text, "utf8");
    }
    const { o: loadPluginMetadataSnapshot } = await imp("dist/plugin-metadata-snapshot-DT_pRp6g.mjs");
    const { t: loadAndActivateRootPluginRegistry } = await imp("dist/loader-DpAS3szV.mjs");
    const metadata = loadPluginMetadataSnapshot({ config: cfg, workspaceDir: workspace });
    progress("provider-metadata-loaded");
    const loadedRegistry = loadAndActivateRootPluginRegistry({ config: cfg, workspaceDir: workspace,
      manifestRegistry: metadata.manifestRegistry, discovery: metadata.discovery, onlyPluginIds: [provider],
      runtimeOptions: { allowGatewaySubagentBinding: true }, cache: false, throwOnLoadError: true });
    const pluginRegistryProof = {
      providers: loadedRegistry.providers.map((p) => ({ pluginId: p.pluginId, id: p.provider.id })),
      diagnostics: jsonValue(loadedRegistry.diagnostics),
      plugins: loadedRegistry.plugins.map((p) => ({ id: p.id, status: p.status, source: p.source })),
    };
    progress("provider-root-registry-loaded");
    const storePath = path.join(directory, "sessions.json");
    const sessionKey = input.sessionKey ?? "agent:main:main";
    let entry = { sessionId: "session", updatedAt: nowMs, compactionCount: 0,
      totalTokens: 176000, totalTokensFresh: true, totalTokensVersion: 1, ...input.entry };
    sourceScope = { agentId: "main", sessionKey, storePath };
    const transcriptScope = { ...sourceScope, sessionId: entry.sessionId };
    await sessions.replaceSessionEntry(sourceScope, entry);
    const messages = input.sourceMessages ?? [];
    const events = input.events ?? [
      createSessionTranscriptHeader({ sessionId: entry.sessionId, cwd: workspace }),
      ...messages.map((message, index) => ({ type: "message", id: `source-${index}`,
        parentId: index > 0 ? `source-${index - 1}` : null, message: { ...message, timestamp: nowMs + index } })),
    ];
    await sessions.replaceTranscriptEvents(transcriptScope, events);
    const sourceBefore = JSON.stringify(sessions.loadTranscriptEventsSync(transcriptScope));
    const { MemoryIndexManager } = await imp("dist/extensions/memory-core/manager-runtime.js");
    manager = await MemoryIndexManager.get({ cfg, agentId: "main", purpose: "search" });
    if (!manager) throw Error("The real provider-none native memory manager is unavailable");
    if (input.warmIndex) await manager.sync({ reason: "fixture-pre-run-warm-index" });
    async function queries() {
      const rows = {};
      for (const query of input.queries ?? []) {
        const results = await manager.search(query, { maxResults: 20, minScore: 0, sources: ["memory"] });
        rows[query] = { available: true, results: results.map((hit) => ({ path: hit.path,
          startLine: hit.startLine, endLine: hit.endLine, snippet: hit.snippet })) };
      }
      return rows;
    }
    const fileBytes = async (relative) => {
      try { return (await fs.readFile(path.join(workspace, relative))).toString("base64"); }
      catch (error) { if (error.code === "ENOENT") return null; throw error; }
    };
    removeObserver = onAgentEvent((event) => {
      if (event.stream === "tool" && event.data.phase === "result") toolEvents.push(jsonValue(event));
    });
    for (const step of input.steps ?? [{ label: "single-write", replies: input.replies ?? [
      { toolCalls: [{ name: "write", arguments: { path: "@target", content: "- glacier tea\n" } }] }, { text: "NO_REPLY" },
    ] }]) {
      activeStep = step;
      replyIndex = 0;
      activeReplies = step.replies;
      modelCalls = [];
      toolEvents = [];
      duringRunPatchApplied = false;
      entry = { ...sessions.loadSessionEntry(sourceScope), ...step.entryPatch };
      await sessions.replaceSessionEntry(sourceScope, entry);
      if (Object.hasOwn(step, "externalText")) await fs.writeFile(targetFile, step.externalText, "utf8");
      registerMemoryCapability("memory-core", planCapability);
      activeController = new AbortController();
      const deadline = setTimeout(() => activeController.abort(new Error("fixture execution deadline")), 45000);
      deadline.unref();
      const followupRun = { prompt: "", summaryLine: "", enqueuedAt: nowMs,
        run: { agentId: "main", agentDir: path.join(directory, "agent"), sessionId: entry.sessionId, sessionKey,
          sessionFile: path.join(directory, "session.jsonl"), workspaceDir: workspace, config: cfg,
          skillsSnapshot: { prompt: "", skills: [] }, provider, model: modelId,
          thinkingCatalog: [{ provider, id: modelId, input: ["text"] }],
          thinkLevel: "off", verboseLevel: "off", elevatedLevel: "off",
          senderIsOwner: !(step.untrusted ?? input.untrusted ?? false),
          bashElevated: { enabled: false, allowed: false, defaultLevel: "off" },
          timeoutMs: 15000, blockReplyBreak: "message_end", skipProviderRuntimeHints: true,
        } };
      const visibleErrors = [];
      const before = jsonValue(entry);
      progress(`before-native-run:${step.label}`);
      const result = await runMemoryFlushIfNeeded({ cfg, followupRun, promptForEstimate: "", defaultModel: modelId,
        resolvedVerboseLevel: "off", sessionEntry: entry, sessionStore: { [sessionKey]: entry }, sessionKey, storePath,
        isHeartbeat: false, abortSignal: activeController.signal,
        replyOperation: { abortSignal: activeController.signal, setPhase: (phase) => progress(`reply-phase:${phase}`) },
        onVisibleErrorPayloads: (payloads) => visibleErrors.push(...payloads) });
      clearTimeout(deadline);
      progress(`after-native-run:${step.label}`);
      entry = result.sessionEntry;
      const firstRecall = input.warmIndex ? await queries() : null;
      manager.markMemoryWatchDirty();
      await manager.sync({ reason: "fixture-explicit-post-run-index-barrier" });
      const afterSyncRecall = await queries();
      const provenanceRaw = await listMemoryArtifactProvenance({ workspaceDir: workspace });
      const executionIdentity = modelCalls.flatMap((call) => call.runContexts)[0] ?? null;
      const provenance = provenanceRaw.map(({ relativePath, provenance: p }) => ({
        path: relativePath, fileHash: p.fileHash, originClass: p.originClass,
        writer: { internalSession: p.sessionId?.startsWith("internal-session-effects-") === true,
          internalKey: /^agent:[^:]+:internal-session-effects:[^:]+$/.test(p.sessionKey ?? ""),
          sameSourceSession: p.sessionId === entry.sessionId, sameSourceKey: p.sessionKey === sessionKey,
          matchesRunSession: p.sessionId === executionIdentity?.sessionId,
          matchesRunKey: p.sessionKey === executionIdentity?.sessionKey },
      })).sort((a, b) => a.path.localeCompare(b.path));
      const toolResults = toolEvents.map((event) => {
        const value = { name: event.data.name, isError: event.data.isError === true,
          content: jsonValue(event.data.result.content) };
        if (Object.hasOwn(event.data.result, "details")) value.details = jsonValue(event.data.result.details);
        return value;
      });
      const protectedFiles = {};
      for (const relative of Object.keys(input.protectedFiles ?? {})) protectedFiles[relative] = await fileBytes(relative);
      const snapshot = {
        label: step.label, outcome: result.outcome, cancelled: activeController.signal.aborted,
        entry: ownedEntry(entry), persistedEntry: ownedEntry(sessions.loadSessionEntry(sourceScope)),
        bytesBase64: await fileBytes(target), protectedFiles,
        toolsAvailable: [...new Set(modelCalls.flatMap((call) => (call.context.tools ?? []).map((tool) => tool.name)))].sort(),
        modelCalls: modelCalls.length, toolResults, provenance,
        sourceUnchanged: sourceBefore === JSON.stringify(sessions.loadTranscriptEventsSync(transcriptScope)),
        firstRecall, afterSyncRecall,
      };
      snapshots.push(snapshot);
      raw.push({ ...snapshot, before, result: jsonValue(result), persistedEntry: sessions.loadSessionEntry(sourceScope),
        modelCalls: jsonValue(modelCalls), toolEvents: jsonValue(toolEvents), visibleErrors,
        provenanceRaw, executionIdentity, target, pluginRegistryProof, progress: jsonValue(progressRows),
        index: { sources: manager.db.prepare("SELECT path,source,hash FROM memory_index_sources").all(),
          chunks: manager.db.prepare("SELECT id,path,text,start_line,end_line FROM memory_index_chunks").all() },
        sourceTranscript: sessions.loadTranscriptEventsSync(transcriptScope),
        invokedOwner: "runMemoryFlushIfNeeded", sourceBuildReproduced: false,
      });
    }
    return { provider: "none", snapshots };
  } finally {
    removeObserver?.();
    clearMemoryPluginState();
    delete globalThis[BRIDGE];
    await manager?.close();
    await disposeAllSessionMcpRuntimes();
    await scheduler.stop();
    if (previousJitiCache === undefined) delete process.env.JITI_FS_CACHE;
    else process.env.JITI_FS_CACHE = previousJitiCache;
    await fs.writeFile(path.join(config.evidenceDirectory, "native-raw.json"), JSON.stringify(raw) + "\n");
  }
}
