// Genuine AgentSession, registered tool, guarded append and fresh-process read.
// Only provider output is a literal scripted stream; no network/model is called.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";
import crypto from "node:crypto";

const request = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const { input, phase, directory, runtimeRoot } = request;
if (![directory, runtimeRoot].every((value) => typeof value === "string" && path.isAbsolute(value)) ||
    !["write", "continue", "verify"].includes(phase)) throw Error("An owned literal session phase is required");
await fs.mkdir(directory, { recursive: true });
const workspace = path.join(directory, "workspace"), state = path.join(directory, "state");
await fs.mkdir(workspace, { recursive: true });
process.env.OPENCLAW_STATE_DIR = state;
process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
process.env.OPENCLAW_HOME = directory;
const logging = { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log"),
  ...(input.patterns ? { redactPatterns: input.patterns } : {}) };
const cfg = { agents: { defaults: { workspace } }, logging, session: { maintenance: { mode: "warn" } } };
if (phase === "write") await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
else if (await fs.readFile(process.env.OPENCLAW_CONFIG_PATH, "utf8") !== JSON.stringify(cfg)) throw Error("The saved host config changed");
Object.defineProperty(globalThis, "fetch", { value: async () => { throw Error("Network fetch is disabled in literal session probes"); }, writable: false });
const originalDate = Date, originalTimeout = setTimeout;
mock.timers.enable({ apis: ["Date"], now: input.nowMs });
const raw = { phase, pid: process.pid, ppid: process.ppid, request, clock: {
  owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate,
  setTimeoutUnchanged: setTimeout === originalTimeout }, events: [], contexts: [], executions: [], persisted: [] };
raw.runtime = { execPath: await fs.realpath(process.execPath), nodeVersion: process.version,
  icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode,
  sha256: crypto.createHash("sha256").update(await fs.readFile(process.execPath)).digest("hex") };
const encode = (value) => JSON.parse(JSON.stringify(value, (_key, item) => typeof item === "function"
  ? { $type: "function", name: item.name, source: String(item) } : item));
const imp = (file) => import(pathToFileURL(path.join(runtimeRoot, file)).href);
let session, closeDatabases, clearConfig;
try {
  const config = await imp("dist/plugin-sdk/config-runtime.js");
  config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
  const registry = await imp("dist/secret-redaction-registry-b2B9lcfy.mjs");
  for (const value of input.registeredSecrets ?? []) registry.s(value);
  const redaction = await imp("dist/redact-BCoakatc.mjs");
  const { u: sanitizeToolResult } = await imp("dist/embedded-agent-tool-results-Bhhd5B_V.mjs");
  const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
  const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
  const { t: SessionManager } = await imp("dist/session-manager-a8MFS1Kk.mjs");
  const { s: close } = await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs"); closeDatabases = close;
  const scope = { agentId: "main", sessionId: input.sessionId, sessionKey: input.sessionKey,
    storePath: sessions.resolveStorePath(undefined, { agentId: "main" }) };
  raw.scope = scope;
  if (phase === "write") await sessions.upsertSessionEntry({ ...scope, entry: { sessionId: input.sessionId, updatedAt: input.nowMs } });
  const manager = SessionManager.open(scope, workspace);
  raw.before = accessor.loadTranscriptEventsSync(scope);
  if (phase !== "verify") {
    const { createAssistantMessageEventStream } = await imp("dist/plugin-sdk/llm.js");
    const { i: AuthStorage, t: ModelRegistry } = await imp("dist/model-registry-CyECwbEb.mjs");
    const { w: SettingsManager, t: DefaultResourceLoader } = await imp("dist/resource-loader-N7_h4_No.mjs");
    const { i: guardSessionManager, n: createAgentSession } = await imp("dist/resource-loader-DhipPm1N.mjs");
    const guarded = guardSessionManager(manager, { config: cfg,
      onMessagePersisted: (message) => raw.persisted.push(encode(message)) });
    if (phase === "write" && input.directGuardMessage) {
      guarded.appendMessage(structuredClone(input.directGuardMessage));
      raw.directGuardMessages = accessor.loadTranscriptEventsSync(scope)
        .filter((entry) => entry.type === "message").map((entry) => entry.message);
    }
    const settings = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const loader = new DefaultResourceLoader({ cwd: workspace, agentDir: workspace, settingsManager: settings,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      systemPrompt: input.systemPrompt });
    await loader.reload();
    const auth = AuthStorage.inMemory();
    auth.setRuntimeApiKey(input.model.provider, "synthetic-probe-auth");
    const models = ModelRegistry.inMemory(auth);
    const responses = phase === "write" ? input.writeResponses : input.continueResponses;
    let consumed = 0;
    models.registerProvider(input.model.provider, { api: input.model.api, streamSimple: (_model, context, options) => {
      raw.contexts.push({ context: encode(context), options: encode(options) });
      if (consumed >= responses.length) throw Error("The literal provider script was exhausted");
      const message = structuredClone(responses[consumed++]);
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => { stream.push({ type: "done", reason: message.stopReason, message }); stream.end(); });
      return stream;
    } });
    const created = await createAgentSession({ cwd: workspace, agentDir: workspace, model: input.model,
      authStorage: auth, modelRegistry: models, settingsManager: settings, sessionManager: guarded,
      resourceLoader: loader, noTools: "builtin", customTools: [{
        name: "lookup", label: "Lookup", description: "Return a declared synthetic fixture result.",
        parameters: { type: "object", properties: { query: { type: "string" } } },
        execute: async (callId, arguments_) => {
          const result = structuredClone(input.toolResult);
          const telemetry = sanitizeToolResult(result);
          raw.executions.push({ callId, arguments: encode(arguments_), result: encode(result),
            telemetry: encode(telemetry), identities: { preparedOutputReuse: sanitizeToolResult(telemetry) === telemetry,
              originalInputReuse: sanitizeToolResult(result) === telemetry } });
          return result;
        },
      }] });
    session = created.session;
    session.subscribe((event) => {
      raw.events.push(encode(event));
      if (event.type === "message_end" && event.message.role === "toolResult" && input.lateRegisteredSecret) {
        registry.s(input.lateRegisteredSecret);
      }
    });
    await session.prompt(phase === "write" ? input.writePrompt : input.continuePrompt);
    raw.responsesConsumed = consumed;
    if (consumed !== responses.length) throw Error("The original session did not consume its complete literal provider script");
    raw.activeToolNames = session.getActiveToolNames();
    if (phase === "write" && input.modeProbe) raw.explicitOffDiagnostic = redaction._(input.modeProbe, { mode: "off" });
  }
  raw.entries = manager.getEntries();
  raw.after = accessor.loadTranscriptEventsSync(scope);
  const context = manager.buildSessionContext();
  const { u: convertToLlm } = await imp("dist/session-BA9qunLx.mjs");
  const result = { phase, providerMessages: raw.contexts.map((entry) => entry.context.messages),
    toolExecutions: raw.executions.map(({ callId, arguments: arguments_, result, telemetry }) =>
      ({ callId, arguments: arguments_, result, telemetry })),
    persistedMessages: raw.persisted, storedMessages: raw.after.filter((entry) => entry.type === "message").map((entry) => entry.message),
    modelContext: context, modelMessages: convertToLlm(context.messages),
    ...(raw.explicitOffDiagnostic === undefined ? {} : { explicitOffDiagnostic: raw.explicitOffDiagnostic }) };
  process.stdout.write(JSON.stringify({ result, raw }) + "\n");
} finally {
  session?.dispose();
  await closeDatabases?.();
  clearConfig?.();
  mock.timers.reset();
}
