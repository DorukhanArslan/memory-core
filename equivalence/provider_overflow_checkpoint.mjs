// Reopen the original SQLite checkpoint and let the whole embedded run own its recovery.
import fs from "node:fs/promises";
import path from "node:path";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";

const [requestFile, root, directory] = process.argv.slice(2);
const { input } = JSON.parse(await fs.readFile(requestFile, "utf8"));
const workspace = path.join(directory, "workspace"), agentDir = path.join(directory, "agent");
const storePath = path.join(directory, "sessions.json");
const scope = { sessionId: input.sessionId, sessionKey: input.sessionKey, agentId: "main", storePath };
const model = { ...input.model, id: input.attemptModelId };
const config = {
  agents: { defaults: { workspace, model: { primary: model.provider + "/" + model.id },
    compaction: { enabled: false, memoryFlush: { enabled: false } } },
    list: [{ id: "main", default: true, workspace, agentDir }] },
  models: { providers: { openai: { api: model.api, baseUrl: model.baseUrl, apiKey: "offline-placeholder",
    models: [{ id: model.id, name: model.name, api: model.api, contextWindow: model.contextWindow,
      maxTokens: model.maxTokens, input: ["text"], reasoning: false, cost: model.cost }] } } },
  session: { store: storePath }, channels: { telegram: { dmHistoryLimit: input.historyLimit } },
  plugins: { allow: ["openai", "memory-core"], entries: { openai: { enabled: true }, "memory-core": { enabled: true } },
    slots: { memory: "memory-core" } },
  memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"], store: { vector: { enabled: false } } } },
  tools: { allow: ["memory_get"], fs: { workspaceOnly: true } }, diagnostics: { cacheTrace: { enabled: true } },
  logging: { level: "debug", consoleLevel: "silent", file: path.join(directory, "recovery.log") },
};
Object.assign(process.env, { OPENCLAW_CACHE_TRACE: "true", OPENCLAW_CACHE_TRACE_FILE: path.join(directory, "cache.jsonl"),
  OPENCLAW_CACHE_TRACE_MESSAGES: "true", OPENCLAW_CACHE_TRACE_PROMPT: "true", OPENCLAW_CACHE_TRACE_SYSTEM: "true",
  FS_SAFE_NATIVE_MODE: "require" });
mock.timers.enable({ apis: ["Date"], now: input.attemptMs });
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
globalThis.fetch = () => { throw Error("Outgoing network disabled during checkpoint recovery"); };
const imp = name => import(pathToFileURL(path.join(root, "dist", name)).href);
const ai = await import(pathToFileURL(path.join(root, "..", "@openclaw", "ai", "dist", "index.mjs")).href);
await imp("ai-transport-runtime-host-YZJr2FQP.mjs");
const sessions = await imp("session-accessor-CiKKTlbe.mjs"), configuration = await imp("plugin-sdk/config-runtime.js");
const { t: Scheduler } = await imp("gateway-scheduler-TywODsdc.mjs");
const mcp = await imp("agent-bundle-mcp-manager-api--Y4zt2wo.mjs"), scheduler = new Scheduler();
configuration.setRuntimeConfigSnapshot(config); mcp.p(scheduler);
const raw = { pid: process.pid, parent: process.ppid, node: process.execPath, config, scope, model, requests: [] };
try {
  raw.before = sessions.loadTranscriptEventsSync(scope);
  const registry = await imp("runtime-9cxii0oQ.mjs"), empty = await imp("registry-empty-BTjzcMW2.mjs");
  registry.w(empty.t(), "startup-registry", "gateway-bindable", workspace);
  const meta = await imp("plugin-metadata-snapshot-DT_pRp6g.mjs"), loader = await imp("loader-DpAS3szV.mjs");
  const metadata = await meta.o({ config, workspaceDir: workspace });
  const loaded = await loader.t({ config, workspaceDir: workspace, manifestRegistry: metadata.manifestRegistry,
    discovery: metadata.discovery, onlyPluginIds: ["openai", "memory-core"], runtimeOptions: { allowGatewaySubagentBinding: true },
    cache: false, throwOnLoadError: true });
  raw.plugins = loaded.plugins.map(({ id, status, source }) => ({ id, status, source }));
  ai.configureAiTransportHost({ ...ai.getAiTransportHost(), buildModelFetch: () => async (url, init) => {
    const request = new Request(url, init), index = raw.requests.length, response = input.sequence[index];
    if (!response || request.url !== model.baseUrl + "/responses" || request.method !== "POST")
      throw Error("Unexpected checkpoint model call");
    const item = { ...input.replyItem, content: [{ ...input.replyItem.content[0], text: response.text }] };
    const events = [{ type: "response.output_item.added", output_index: 0, item },
      { type: "response.output_item.done", output_index: 0, item }, { type: "response.completed",
        response: { id: input.attemptResponseId + "_" + index, status: "completed", output: [item] } }];
    const body = events.map(e => "event: " + e.type + "\ndata: " + JSON.stringify(e) + "\n\n").join("") + "data: [DONE]\n\n";
    raw.requests.push({ url: request.url, method: request.method, headers: Object.fromEntries(request.headers),
      body: await request.text(), response: { status: 200, contentType: "text/event-stream", body } });
    return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  } });
  const { t: run } = await imp("embedded-agent-gxn-c3nS.mjs"), { d: prepare } = await imp("admitted-run-context-hIkojwNE.mjs");
  const runId = "overflow-checkpoint", admission = await prepare(config, runId, "main", "overflow-fixture");
  try {
    raw.result = await run({ preparedRunAdmission: admission, ...scope, sessionTarget: scope,
      sessionFile: "sqlite:main:" + scope.sessionId + ":" + storePath, workspaceDir: workspace, cwd: workspace,
      agentDir, config, prompt: input.prompt, runtimeContextFragments: [], agentAccountId: "default",
      conversationRoutePeerId: "assembly-peer", chatType: "direct", timeoutMs: 40000, runId, provider: model.provider,
      model: model.id, modelId: model.id, authProfileStore: { version: 1, profiles: {} }, thinkLevel: "off",
      disableToolSearch: true, disableTrajectory: true, disableMessageTool: true, promptMode: "minimal",
      trigger: "user", skillsSnapshot: { prompt: "", skills: [] } });
  } finally { await admission.close(); }
  raw.after = sessions.loadTranscriptEventsSync(scope);
  raw.database = sessions.resolveSessionTranscriptDatabasePath(scope);
} finally {
  await (await imp("extensions/memory-core/manager-runtime.js")).closeAllMemoryIndexManagers();
  await (await imp("memory-runtime-BzdCLKPx.mjs")).i();
  await mcp.i(); await scheduler.stop();
  await (await imp("openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s();
  await (await imp("plugin-state-store-BPUaLoVD.mjs")).u();
  await (await imp("logger-Cn5hoa7J.mjs")).n();
  configuration.clearRuntimeConfigSnapshot(); mock.timers.reset();
}
raw.remainingResources = process.getActiveResourcesInfo();
await fs.writeFile(path.join(directory, "recovery.json"), JSON.stringify(raw));
process.exit(0);
