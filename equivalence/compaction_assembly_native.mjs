// Invoke the published OpenAI Responses transport on an in-memory HTTP boundary.
// The reopened model turn goes through original admission, history, context engine and plugin.
import fs from "node:fs/promises";
import path from "node:path";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";

const [requestFile, root, directory, phase] = process.argv.slice(2);
const { input } = JSON.parse(await fs.readFile(requestFile, "utf8"));
if (!["seed", "reopen"].includes(phase)) throw Error("Unknown assembly phase");
const workspace = path.join(directory, "workspace"), agentDir = path.join(directory, "agent");
const storePath = path.join(directory, "sessions.json"), tracePath = path.join(directory, "cache.jsonl");
const scope = { sessionId: input.sessionId, sessionKey: input.sessionKey, agentId: "main", storePath };
const active = input.activeHistory;
const model = { ...input.model, id: phase === "seed" ? input.model.id : input.attemptModelId };
const clock = phase === "seed" ? input.seedMs : input.attemptMs;
const config = {
  agents: { defaults: { workspace, model: { primary: model.provider + "/" + model.id },
    compaction: { enabled: false, memoryFlush: { enabled: false } } },
    list: [{ id: "main", default: true, workspace, agentDir }] },
  session: { store: storePath }, channels: { telegram: { dmHistoryLimit: input.historyLimit } },
  plugins: { allow: ["openai", "memory-core"], entries: { openai: { enabled: true }, "memory-core": { enabled: true } },
    slots: { memory: "memory-core" } },
  memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"], store: { vector: { enabled: false } } } },
  tools: { allow: ["memory_get"], fs: { workspaceOnly: true } }, diagnostics: { cacheTrace: { enabled: true } },
  logging: { level: "debug", consoleLevel: "silent", file: path.join(directory, phase + ".log") },
};
Object.assign(process.env, { OPENCLAW_CONFIG_PATH: path.join(directory, "config.json"), OPENCLAW_CACHE_TRACE: "true",
  OPENCLAW_CACHE_TRACE_FILE: tracePath, OPENCLAW_CACHE_TRACE_MESSAGES: "true", OPENCLAW_CACHE_TRACE_PROMPT: "true",
  OPENCLAW_CACHE_TRACE_SYSTEM: "true", FS_SAFE_NATIVE_MODE: "require" });
mock.timers.enable({ apis: ["Date"], now: clock });
await fs.mkdir(workspace, { recursive: true }); await fs.mkdir(agentDir, { recursive: true });
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
globalThis.fetch = async () => { throw Error("Unexpected external fetch during offline compaction measurement"); };
const imp = name => import(pathToFileURL(path.join(root, "dist", name)).href);
const fromAi = name => import(pathToFileURL(path.join(root, "..", "@openclaw", "ai", "dist", name)).href);
const ai = await fromAi("index.mjs");
const { streamOpenAIResponses } = await fromAi("internal/openai.mjs");
const sessions = await imp("session-accessor-CiKKTlbe.mjs");
const configuration = await imp("plugin-sdk/config-runtime.js");
configuration.setRuntimeConfigSnapshot(config);
const raw = { phase, pid: process.pid, ppid: process.ppid, node: process.execPath, clock: Date.now(), config,
  scope, model, requests: [], databasePath: sessions.resolveSessionTranscriptDatabasePath(scope) };
function installHttp(items, responseId) {
  const events = items.flatMap((item, output_index) => [
    { type: "response.output_item.added", output_index, item }, { type: "response.output_item.done", output_index, item }]);
  events.push({ type: "response.completed", response: { id: responseId, status: "completed", output: items } });
  const eventStream = events.map(event => "event: " + event.type + "\ndata: " + JSON.stringify(event) + "\n\n").join("") + "data: [DONE]\n\n";
  ai.configureAiTransportHost({ ...ai.getAiTransportHost(), buildModelFetch: () => async (url, init) => {
    const request = new Request(url, init);
    if (request.url !== input.model.baseUrl + "/responses" || request.method !== "POST") throw Error("Unowned provider request");
    const body = await request.text();
    raw.requests.push({ method: request.method, url: request.url, headers: Object.fromEntries(request.headers), body,
      reply: { status: 200, contentType: "text/event-stream", body: eventStream } });
    return new Response(eventStream, { status: 200, headers: { "content-type": "text/event-stream" } });
  } });
}
async function captureAssistant(items, identifier, messages) {
  installHttp(items, identifier);
  const stream = streamOpenAIResponses(model, { messages }, { apiKey: "offline-placeholder", sessionId: input.sessionId });
  const message = await stream.result();
  if (message.stopReason === "error") throw Error(message.errorMessage);
  return message;
}
const user = text => ({ role: "user", content: text, timestamp: Date.now() });
try {
  if (phase === "seed") {
    const filePath = path.join(workspace, input.file.path);
    await fs.writeFile(filePath, active ? 'START ' + active.repeat.repeat(active.repeatCount) + ' END legacy file bytes.\n' : input.file.text);
    const history = [];
    for (const [index, text] of input.users.entries()) {
      history.push(user(text));
      if (index === input.checkpointAfterUser) {
        raw.checkpointAssistant = await captureAssistant([input.checkpointItem, input.checkpointTextItem], input.seedResponseIds[0], history);
        history.push(raw.checkpointAssistant);
      }
    }
    raw.callAssistant = await captureAssistant([input.callItem], input.seedResponseIds[1], history);
    const [call] = raw.callAssistant.content;
    const { createMemoryGetTool } = await imp("tools-DotaQGXh.mjs");
    const tool = createMemoryGetTool({ config, agentId: "main" });
    if (call.type !== "toolCall" || call.name !== tool.name || tool.name !== "memory_get") throw Error("Unexpected streamed tool request");
    raw.tool = await tool.execute(call.id, call.arguments);
    history.push(raw.callAssistant, { role: "toolResult", toolCallId: call.id, toolName: call.name,
      content: raw.tool.content, details: raw.tool.details, isError: false, timestamp: Date.now() });
    await sessions.replaceSessionEntry({ agentId: "main", sessionKey: input.sessionKey, storePath },
      { sessionId: input.sessionId, updatedAt: clock });
    const { t: header } = await imp("transcript-header-CP-ow2Zr.mjs");
    raw.events = [header({ sessionId: input.sessionId, version: 4, cwd: workspace, timestamp: new Date(clock).toISOString() }),
      ...history.map((message, i) => ({ type: "message", id: "assembly-entry-" + i, parentId: i ? "assembly-entry-" + (i - 1) : null,
        timestamp: new Date(clock + i * 1000).toISOString(), message }))];
    await sessions.replaceTranscriptEvents(scope, raw.events);
    if (active) {
      const { t: SessionManager } = await imp("session-manager-a8MFS1Kk.mjs");
      const manager = SessionManager.open(scope, workspace);
      const origin = manager.getLeafId();
      manager.appendMessage(user(active.inactive));
      manager.branch(origin);
      manager.appendMessage(user(active.recent));
      if (active.compact) manager.appendCompaction(active.summary, "assembly-entry-2", 2000);
      const reconcile = await imp("session-transcript-reconcile-CUGsfxWk.mjs");
      await reconcile.i({agentId: "main", path: raw.databasePath});
      raw.reconcile = await reconcile.n({agentId: "main", path: raw.databasePath, sessionIds: [input.sessionId]});
      raw.events = sessions.loadTranscriptEventsSync(scope);
    }
    raw.persisted = sessions.loadTranscriptEventsSync(scope);
  } else {
    raw.before = sessions.loadTranscriptEventsSync(scope);
    await imp("ai-transport-runtime-host-YZJr2FQP.mjs");
    const { t: GatewayScheduler } = await imp("gateway-scheduler-TywODsdc.mjs");
    const scheduler = new GatewayScheduler(), mcp = await imp("agent-bundle-mcp-manager-api--Y4zt2wo.mjs");
    mcp.p(scheduler);
    try {
      const registry = await imp("runtime-9cxii0oQ.mjs"), empty = await imp("registry-empty-BTjzcMW2.mjs");
      registry.w(empty.t(), "startup-registry", "gateway-bindable", workspace);
      const meta = await imp("plugin-metadata-snapshot-DT_pRp6g.mjs"), loader = await imp("loader-DpAS3szV.mjs");
      const metadata = await meta.o({ config, workspaceDir: workspace });
      const loaded = await loader.t({ config, workspaceDir: workspace, manifestRegistry: metadata.manifestRegistry,
        discovery: metadata.discovery, onlyPluginIds: ["openai", "memory-core"], runtimeOptions: { allowGatewaySubagentBinding: true },
        cache: false, throwOnLoadError: true });
      raw.plugins = loaded.plugins.map(({ id, status, source }) => ({ id, status, source }));
      const { t: createHarness } = await imp("builtin-openclaw-D1Xfnzzr.mjs");
      const { d: prepare } = await imp("admitted-run-context-hIkojwNE.mjs");
      const { i: Auth, t: Models } = await imp("model-registry-CyECwbEb.mjs");
      const auth = Auth.inMemory(); auth.setRuntimeApiKey(model.provider, "offline-placeholder");
      const models = Models.inMemory(auth);
      installHttp([input.replyItem], input.attemptResponseId);
      const runId = "assembly-reopen", admission = await prepare(config, runId, "main", "assembly-fixture");
      try {
        const params = { sessionId: input.sessionId, sessionKey: input.sessionKey, sessionTarget: scope,
          sessionFile: "sqlite:main:" + input.sessionId + ":" + storePath, agentId: "main", workspaceDir: workspace, cwd: workspace,
          agentDir, config, prompt: input.prompt, runtimeContextFragments: [], agentAccountId: "default",
          conversationRoutePeerId: "assembly-peer", chatType: "direct", timeoutMs: 30000, runId,
          provider: model.provider, modelId: model.id, model, authProfileStore: { version: 1, profiles: {} },
          thinkLevel: "off", contextTokenBudget: active?.contextTokenBudget ?? model.contextWindow, disableToolSearch: true, disableTrajectory: true,
          disableMessageTool: true, promptMode: "minimal", trigger: "user", skillsSnapshot: { prompt: "", skills: [] } };
        raw.call = params;
        raw.result = await createHarness().runAttempt({ ...params, admittedRunContext: await admission.admit("embedded"),
          authStorage: auth, modelRegistry: models });
      } finally { await admission.close(); }
      raw.after = sessions.loadTranscriptEventsSync(scope);
    } finally { await mcp.i(); await scheduler.stop(); }
  }
} finally {
  await (await imp("openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s();
  await (await imp("plugin-state-store-BPUaLoVD.mjs")).u();
  await (await imp("logger-Cn5hoa7J.mjs")).n();
  configuration.clearRuntimeConfigSnapshot(); mock.timers.reset();
}
await fs.writeFile(path.join(directory, phase + ".json"), JSON.stringify(raw));
