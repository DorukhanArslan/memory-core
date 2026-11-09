// Genuine published AgentSession, guarded append and persisted context owners.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";
import { modelEncode, modelMarkerState, modelRuntimeIdentity, modelSessionSql } from "./model-runtime-observation.mjs";

export async function runModelSessionPhase(request) {
  const { input, phase, directory, runtimeRoot } = request;
  if (Object.keys(request).sort().join() !== "directory,input,phase,runtimeRoot" ||
      ![directory, runtimeRoot].every((value) => typeof value === "string" && path.isAbsolute(value)) ||
      !["write", "continue", "verify"].includes(phase?.label) || input.agentId !== "main") {
    throw Error("A model phase requires its exact owned request and original session identity");
  }
  if (phase.label === "verify" && (Object.keys(input).sort().join() !== "agentId,nowMs,sessionId,sessionKey" ||
      Object.keys(phase).join() !== "label")) throw Error("A fresh verifier cannot receive scripts, secrets or prior history");
  const runtime = modelRuntimeIdentity();
  const workspace = path.join(directory, "workspace"), state = path.join(directory, "state");
  await fs.mkdir(workspace, { recursive: true });
  process.env.OPENCLAW_STATE_DIR = state; process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  process.env.OPENCLAW_HOME = directory; process.env.HOME = directory;
  const proposedLogging = { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log"),
    ...(Object.hasOwn(input, "patterns") ? { redactPatterns: input.patterns } : {}) };
  const proposedConfig = { agents: { defaults: { workspace } }, logging: proposedLogging,
    session: { maintenance: { mode: "warn" } } };
  if (phase.label === "write") await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(proposedConfig), { flag: "wx" });
  const configBytes = await fs.readFile(process.env.OPENCLAW_CONFIG_PATH, "utf8");
  const cfg = JSON.parse(configBytes), logging = cfg.logging;
  if (phase.label !== "verify" && configBytes !== JSON.stringify(proposedConfig)) throw Error("The persisted literal host configuration changed");
  const originalDate = Date, originalTimeout = setTimeout, originalPerformanceNow = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { phase: phase.label, pid: process.pid, ppid: process.ppid, request, runtime, configBytes, config: cfg,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate,
      setTimeoutUnchanged: setTimeout === originalTimeout, performanceNowUnchanged: performance.now === originalPerformanceNow },
    registry: [], stages: [], events: [], contexts: [], executions: [], persisted: [], applicationWrites: [] };
  const imp = (file) => import(pathToFileURL(path.join(runtimeRoot, file)).href);
  let session, closeDatabases, clearConfig;
  try {
    const config = await imp("dist/plugin-sdk/config-runtime.js");
    config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
    const registry = await imp("dist/secret-redaction-registry-b2B9lcfy.mjs");
    const captureRegistry = (stage, secret) => raw.registry.push({ stage, ...(secret === undefined ? {} : { secret }),
      snapshot: modelEncode(registry.t()) });
    captureRegistry("initial");
    if (registry.t().revision !== 0 || registry.t().values.length) throw Error("A fresh phase inherited a populated secret registry");
    if (phase.label !== "verify") for (const value of input.registeredSecrets ?? []) {
      registry.s(value); captureRegistry("literal-registration", value);
    }
    const redaction = await imp("dist/redact-BCoakatc.mjs");
    const { u: sanitizeToolResult } = await imp("dist/embedded-agent-tool-results-Bhhd5B_V.mjs");
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const { t: SessionManager } = await imp("dist/session-manager-a8MFS1Kk.mjs");
    const { s: close } = await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs"); closeDatabases = close;
    const scope = { agentId: input.agentId, sessionId: input.sessionId, sessionKey: input.sessionKey,
      storePath: sessions.resolveStorePath(undefined, { agentId: input.agentId }) };
    raw.scope = scope;
    if (phase.label === "write") {
      const entry = { sessionId: input.sessionId, updatedAt: input.nowMs };
      const result = await sessions.upsertSessionEntry({ ...scope, entry });
      raw.applicationWrites.push({ target: scope, entry, returnedUndefined: result === undefined,
        ...(result === undefined ? {} : { result: modelEncode(result) }) });
    }
    const manager = SessionManager.open(scope, workspace);
    raw.before = accessor.loadTranscriptEventsSync(scope);
    const sql = await imp("dist/plugin-sdk/sqlite-runtime.js");
    raw.databasePath = accessor.resolveSessionTranscriptDatabasePath(scope);
    const database = sql.openOpenClawAgentDatabase({ agentId: input.agentId, path: raw.databasePath });
    raw.sessionSqlBefore = modelSessionSql(database.db);
    const observe = (stage, message) => raw.stages.push({ stage, message: modelEncode(message),
      policy: modelEncode(redaction.W(logging)), registry: modelEncode(registry.t()),
      markers: modelMarkerState(message, redaction, logging) });
    if (phase.label !== "verify") {
      const { createAssistantMessageEventStream } = await imp("dist/plugin-sdk/llm.js");
      const { i: AuthStorage, t: ModelRegistry } = await imp("dist/model-registry-CyECwbEb.mjs");
      const { w: SettingsManager, t: DefaultResourceLoader } = await imp("dist/resource-loader-N7_h4_No.mjs");
      const { i: guardSessionManager, n: createAgentSession } = await imp("dist/resource-loader-DhipPm1N.mjs");
      raw.guardRequest = { config: cfg, onMessagePersisted: true };
      const guarded = guardSessionManager(manager, { config: cfg, onMessagePersisted: (message) => {
        raw.persisted.push(modelEncode(message)); observe("persisted-callback", message);
      } });
      if (Object.hasOwn(phase, "directGuardMessage")) {
        raw.directGuardRequest = structuredClone(phase.directGuardMessage); guarded.appendMessage(structuredClone(phase.directGuardMessage));
      }
      const settingsInput = { compaction: { enabled: false }, retry: { enabled: false } };
      const settings = SettingsManager.inMemory(settingsInput);
      const loaderInput = { cwd: workspace, agentDir: workspace, noExtensions: true, noSkills: true,
        noPromptTemplates: true, noThemes: true, noContextFiles: true, systemPrompt: input.systemPrompt };
      const loader = new DefaultResourceLoader({ ...loaderInput, settingsManager: settings }); await loader.reload();
      const auth = AuthStorage.inMemory(); auth.setRuntimeApiKey(input.model.provider, "synthetic-probe-auth");
      captureRegistry("provider-fixture-auth");
      const models = ModelRegistry.inMemory(auth); let consumed = 0;
      raw.providerRegistration = { provider: input.model.provider, api: input.model.api, streamSimple: true };
      models.registerProvider(input.model.provider, { api: input.model.api, streamSimple: (_model, context, options) => {
        raw.contexts.push({ model: modelEncode(_model), context: modelEncode(context), options: modelEncode(options) });
        if (consumed >= phase.responses.length) throw Error("The literal provider script was exhausted");
        const message = structuredClone(phase.responses[consumed++]);
        const stream = createAssistantMessageEventStream();
        queueMicrotask(() => { stream.push({ type: "done", reason: message.stopReason, message }); stream.end(); });
        return stream;
      } });
      raw.createRequest = { cwd: workspace, agentDir: workspace, model: input.model, settingsInput, loaderInput,
        noTools: "builtin", customTools: [{ name: "lookup", label: "Lookup", description: "Return a declared synthetic fixture result.",
          parameters: { type: "object", properties: { query: { type: "string" } } } }] };
      const created = await createAgentSession({ cwd: workspace, agentDir: workspace, model: input.model, authStorage: auth,
        modelRegistry: models, settingsManager: settings, sessionManager: guarded, resourceLoader: loader, noTools: "builtin",
        customTools: [{ ...raw.createRequest.customTools[0], execute: async (callId, arguments_) => {
          const result = structuredClone(phase.toolResult); const telemetry = sanitizeToolResult(result);
          raw.executions.push({ callId, arguments: modelEncode(arguments_), result: modelEncode(result), telemetry: modelEncode(telemetry),
            identities: { preparedOutputReuse: sanitizeToolResult(telemetry) === telemetry,
              originalInputReuse: sanitizeToolResult(result) === telemetry } });
          observe("tool-return", result); return result;
        } }] });
      session = created.session;
      session.subscribe((event) => {
        raw.events.push(modelEncode(event));
        if (event.message) observe(`event:${event.type}`, event.message);
        if (event.type === "message_end" && event.message.role === "toolResult" && phase.lateRegisteredSecret) {
          registry.s(phase.lateRegisteredSecret); captureRegistry("live-event-registration", phase.lateRegisteredSecret);
        }
      });
      raw.prompt = phase.prompt; await session.prompt(phase.prompt); raw.responsesConsumed = consumed;
      if (consumed !== phase.responses.length) throw Error("The original session did not consume the complete literal provider script");
      raw.activeToolNames = session.getActiveToolNames();
      if (Object.hasOwn(phase, "modeProbe")) raw.explicitOffDiagnostic = redaction._(phase.modeProbe, { mode: "off" });
    }
    raw.entries = manager.getEntries(); raw.after = accessor.loadTranscriptEventsSync(scope);
    raw.currentEntry = sessions.getSessionEntry(scope); raw.sessionSqlAfter = modelSessionSql(database.db);
    const context = manager.buildSessionContext(); const { u: convertToLlm } = await imp("dist/session-BA9qunLx.mjs");
    const modelMessages = convertToLlm(context.messages); raw.context = modelEncode(context); raw.modelMessages = modelEncode(modelMessages);
    captureRegistry("final");
    const result = { phase: phase.label, providerMessages: raw.contexts.map((entry) => entry.context.messages),
      toolExecutions: raw.executions.map(({ callId, arguments: args, result, telemetry }) => ({ callId, arguments: args, result, telemetry })),
      persistedMessages: raw.persisted, storedMessages: raw.after.filter((event) => event.type === "message").map((event) => event.message),
      modelContext: context, modelMessages,
      ...(raw.explicitOffDiagnostic === undefined ? {} : { explicitOffDiagnostic: raw.explicitOffDiagnostic }) };
    return { result, raw };
  } finally {
    session?.dispose(); await closeDatabases?.(); clearConfig?.(); mock.timers.reset();
  }
}
