// Execute the published OpenClaw run orchestrator against its registered, offline provider.
import fs from "node:fs/promises";
import path from "node:path";
import { mock } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const [requestPath, root, directory] = process.argv.slice(2);
const { input } = JSON.parse(await fs.readFile(requestPath, "utf8"));
const workspace = path.join(directory, "workspace"), agentDir = path.join(directory, "agent");
const storePath = path.join(directory, "sessions.json"), logFile = path.join(directory, "log.jsonl");
const plugin = fileURLToPath(new URL("./prompt-runtime-provider/", import.meta.url));
const { provider, model: modelId } = input;
const zeroCost = () => ({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 });
const usage = (tokens = 1) => ({ input: tokens, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: tokens + 1, cost: zeroCost() });
const config = {
  plugins: { allow: [provider, "memory-core"], load: { paths: [plugin] },
    entries: { [provider]: { enabled: true }, "memory-core": { enabled: true } }, slots: { memory: "memory-core" } },
  agents: { list: [{ id: "main", default: true, workspace, agentDir }], defaults: { workspace,
    model: { primary: provider + "/" + modelId }, compaction: { memoryFlush: { enabled: false }, ...input.compaction } } },
  session: { store: storePath },
  models: { providers: { [provider]: { api: "openai-completions", baseUrl: "http://127.0.0.1:1/v1", apiKey: "unusable-offline-fixture",
    models: [{ id: modelId, name: "offline", api: "openai-completions", reasoning: false, input: ["text"],
      contextWindow: input.contextWindow, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } },
  memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"], store: { vector: { enabled: false } } } },
  tools: { allow: ["memory_get"], fs: { workspaceOnly: true } },
  logging: { level: "debug", consoleLevel: "silent", file: logFile },
};
const scope = { sessionId: "orchard-session", sessionKey: "agent:main:main", agentId: "main", storePath };
const raw = { pid: process.pid, parent: process.ppid, node: process.execPath, calls: [], toolEvents: [], progress: [], config, scope };
const clone = value => JSON.parse(JSON.stringify(value));
const imp = name => import(pathToFileURL(path.join(root, "dist", name)).href);
await fs.mkdir(workspace); await fs.mkdir(agentDir);
await fs.writeFile(path.join(workspace, "MEMORY.md"), "pear trees " + "water ".repeat(input.fileRepeat) + "\n");
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
globalThis.fetch = () => { throw Error("Unexpected external fetch during offline overflow measurement"); };
mock.timers.enable({ apis: ["Date"], now: input.clock });
const { createAssistantMessageEventStream } = await imp("plugin-sdk/llm.js");
const { t: Scheduler } = await imp("gateway-scheduler-TywODsdc.mjs");
const mcp = await imp("agent-bundle-mcp-manager-api--Y4zt2wo.mjs"), scheduler = new Scheduler();
const configuration = await imp("plugin-sdk/config-runtime.js");
mcp.p(scheduler); configuration.setRuntimeConfigSnapshot(config);

function scriptedStream(model, context) {
  const index = raw.calls.length, reply = input.sequence[index];
  if (!reply) throw Error("The original asked for an unplanned provider dispatch");
  const content = reply.error ? [] : reply.read ? Array.from({ length: reply.read }, (_, k) => ({
    type: "toolCall", id: "call_orchard_" + index + "_" + k, name: "memory_get",
    arguments: { path: "MEMORY.md", from: 1, lines: 1 },
  })) : [{ type: "text", text: reply.text }];
  const assistant = { role: "assistant", api: model.api, provider: model.provider, model: model.id,
    timestamp: Date.now(), usage: usage(), content, stopReason: reply.error ? "error" : reply.read ? "toolUse" : "stop",
    ...(reply.error ? { errorMessage: reply.error } : {}) };
  raw.calls.push({ model: clone(model), context: clone(context), assistant: clone(assistant) });
  const stream = createAssistantMessageEventStream();
  queueMicrotask(() => {
    stream.push(reply.error ? { type: "error", reason: "error", error: assistant } :
      { type: "done", reason: assistant.stopReason, message: assistant });
    stream.end(assistant);
  });
  return stream;
}

try {
  const registry = await imp("runtime-9cxii0oQ.mjs"), empty = await imp("registry-empty-BTjzcMW2.mjs");
  registry.w(empty.t(), "startup-registry", "gateway-bindable", workspace);
  globalThis[Symbol.for("memory-core.equivalence.prompt-runtime-provider")] = {
    progress: detail => raw.progress.push(detail), stream: scriptedStream,
    observeTool: (when, event, context) => raw.toolEvents.push({ when, event: clone(event), context: clone(context) }),
  };
  const meta = await imp("plugin-metadata-snapshot-DT_pRp6g.mjs"), loader = await imp("loader-DpAS3szV.mjs");
  const metadata = await meta.o({ config, workspaceDir: workspace });
  const loaded = await loader.t({ config, workspaceDir: workspace, manifestRegistry: metadata.manifestRegistry,
    discovery: metadata.discovery, onlyPluginIds: [provider, "memory-core"],
    runtimeOptions: { allowGatewaySubagentBinding: true }, cache: false, throwOnLoadError: true });
  raw.plugins = loaded.plugins.map(({ id, status, source }) => ({ id, status, source }));
  const sessions = await imp("session-accessor-CiKKTlbe.mjs");
  await sessions.replaceSessionEntry({ agentId: scope.agentId, sessionKey: scope.sessionKey, storePath },
    { sessionId: scope.sessionId, updatedAt: input.clock });
  const events = [{ type: "session", version: 3, id: scope.sessionId, timestamp: new Date(input.clock).toISOString(), cwd: workspace }];
  for (const [index, item] of input.history.entries()) {
    const timestamp = input.clock + index, text = item.text.repeat(item.repeat ?? 1);
    const message = item.role === "user" ? { role: "user", content: text, timestamp } : {
      role: "assistant", api: "openai-completions", provider, model: modelId, content: [{ type: "text", text }],
      stopReason: "stop", timestamp, usage: usage(2) };
    events.push({ type: "message", id: "seed-" + index, parentId: index ? "seed-" + (index - 1) : null,
      timestamp: new Date(timestamp).toISOString(), message });
  }
  await sessions.replaceTranscriptEvents(scope, events);
  raw.before = sessions.loadTranscriptEventsSync(scope);
  const { t: run } = await imp("embedded-agent-gxn-c3nS.mjs"), { d: prepare } = await imp("admitted-run-context-hIkojwNE.mjs");
  const runId = "provider-overflow", admission = await prepare(config, runId, "main", "overflow-fixture");
  try {
    raw.result = await run({ preparedRunAdmission: admission, ...scope, sessionTarget: scope,
      sessionFile: "sqlite:main:" + scope.sessionId + ":" + storePath, workspaceDir: workspace, cwd: workspace, agentDir,
      config, prompt: input.prompt.repeat(input.promptRepeat), runId, provider, model: modelId, modelId,
      timeoutMs: 40000, thinkLevel: "off", trigger: "user", promptMode: "minimal", skillsSnapshot: { prompt: "", skills: [] },
      disableMessageTool: true, disableToolSearch: true, disableTrajectory: true });
  } finally { await admission.close(); }
  raw.after = sessions.loadTranscriptEventsSync(scope);
  const { F: selectVisible } = await imp("session-accessor.sqlite-read-BsSfe2AE.mjs");
  raw.visible = selectVisible(raw.after);
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
// The embedded scheduler may retain idle timers after the durable run and all store owners have closed.
raw.remainingResources = process.getActiveResourcesInfo();
await fs.writeFile(path.join(directory, "capture.json"), JSON.stringify(raw));
process.exit(0);
