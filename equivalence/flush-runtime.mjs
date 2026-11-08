// Fixture transport for the unmodified official runMemoryFlushIfNeeded owner.
// Real native SQLite transcript/accounting and failure persistence execute.
// The original memory plugin supplies each initial plan; its second resolution
// deliberately fails after the gate. No provider/model execution is admitted.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ENTRY_FIELDS = ["totalTokens", "totalTokensFresh", "totalTokensVersion", "compactionCount", "memoryFlush", "incognito"];
const ownedEntry = (entry) => entry == null ? null : Object.fromEntries(
  ENTRY_FIELDS.filter((key) => Object.hasOwn(entry, key)).map((key) => [key, structuredClone(entry[key])]),
);
const select = (step, input, key, fallback) => Object.hasOwn(step, key) ? step[key]
  : Object.hasOwn(input, key) ? input[key] : fallback;

export async function runFlushRuntime(input, config) {
  if (!config?.runtimeRoot || !path.isAbsolute(config.runtimeRoot)) {
    throw Error("An authenticated absolute release runtimeRoot is required");
  }
  if (!config.evidenceDirectory || !config.stateDirectory || !config.configPath) {
    throw Error("Owned release evidence, state and configuration paths are required");
  }
  await fs.mkdir(config.stateDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(config.stateDirectory, "flush-trigger-"));
  const workspace = path.join(directory, "workspace");
  await fs.mkdir(workspace);
  const imp = (relative) => import(pathToFileURL(path.join(config.runtimeRoot, relative)).href);
  const raw = [];
  const snapshots = [];
  const { t: runMemoryFlushIfNeeded } = await imp("dist/agent-runner-memory-Cc4lCZcs.mjs");
  const { w: setActivePluginRegistry } = await imp("dist/runtime-9cxii0oQ.mjs");
  const { t: createEmptyPluginRegistry } = await imp("dist/registry-empty-BTjzcMW2.mjs");
  const { p: registerMemoryCapability, r: clearMemoryPluginState } = await imp("dist/memory-state-BmtUbXjH.mjs");
  const { r: isIncognitoSessionKey } = await imp("dist/session-key-DDIJxXfQ.mjs");
  const sessions = await imp("dist/session-accessor-CiKKTlbe.mjs");
  const registry = createEmptyPluginRegistry();
  // A provider label alone is not a CLI runtime in this release. Supply the
  // same plugin backend registration that the actual runtime classifier reads.
  // Classification stays in native resolveCliBackendConfig/isCliProvider; this
  // command is metadata only and no CLI process is ever dispatched.
  const cliBackendRegistered = [input, ...(input.steps ?? [])].some((value) => value.isCli === true);
  if (cliBackendRegistered) registry.cliBackends.push({
    pluginId: "fixture-cli", source: "test",
    backend: { id: "codex-cli", config: { command: "fixture-cli-command-not-executed" } },
  });
  setActivePluginRegistry(registry);
  try {
    // Capture the actual plugin's plan resolver through its registration API.
    // Stop registration at that boundary; unrelated tools/hooks never execute.
    const { default: memoryPlugin } = await imp("dist/extensions/memory-core/index.js");
    const captured = Symbol("native flush plan registered");
    let originalPlanResolver;
    const noop = () => {};
    const api = new Proxy({
      runtime: { llm: {}, state: {}, config: {} }, config: {},
      logger: { info: noop, warn: noop, error: noop, debug: noop },
      registerMemoryCapability(capability) {
        originalPlanResolver = capability.flushPlanResolver;
        throw captured;
      },
    }, { get: (target, name) => target[name] ?? noop });
    try { memoryPlugin.register(api); } catch (error) { if (error !== captured) throw error; }
    if (typeof originalPlanResolver !== "function") throw Error("Original native flush plan resolver unavailable");

    const storePath = path.join(directory, "sessions.json");
    const sessionKey = input.sessionKey ?? "agent:main:main";
    let entry = input.entry == null ? undefined : structuredClone(input.entry);
    if (entry) {
      entry.sessionId ??= "session";
      entry.updatedAt ??= 1777824000000;
    }
    const scope = { agentId: "main", sessionKey, storePath };
    const transcriptScope = { ...scope, sessionId: entry?.sessionId ?? "session" };
    let events = structuredClone(input.events ?? []);
    // Incognito state is deliberately process-local under the native contract.
    const processOnly = entry?.incognito === true || isIncognitoSessionKey(sessionKey);
    if (entry && !processOnly) {
      await sessions.replaceSessionEntry(scope, entry);
      await sessions.replaceTranscriptEvents(transcriptScope, events);
    }

    for (const step of input.steps ?? [{}]) {
      if (step.entryPatch) {
        entry = { ...entry, ...structuredClone(step.entryPatch) };
        if (!processOnly) await sessions.replaceSessionEntry(scope, entry);
      }
      if (Object.hasOwn(step, "events")) {
        events = structuredClone(step.events);
        if (entry && !processOnly) await sessions.replaceTranscriptEvents(transcriptScope, events);
      }
      const provider = select(step, input, "isCli", false) ? "codex-cli" : "anthropic";
      const contextTokens = select(step, input, "contextWindowTokens", 200000);
      const cfg = {
        agents: { defaults: {
          workspace, compaction: { memoryFlush: select(step, input, "flushConfig", {}) },
          ...(select(step, input, "memoryFlushWritable", true) ? {}
            : { sandbox: { mode: "all", workspaceAccess: "ro" } }),
        } },
        models: { providers: { [provider]: {
          baseUrl: "http://127.0.0.1:1", models: [{ id: "fixture", contextTokens }],
        } } },
      };
      let planCalls = 0;
      let preparationAttempts = 0;
      registerMemoryCapability("memory-core", { flushPlanResolver(params) {
        planCalls += 1;
        if (planCalls === 1) return originalPlanResolver(params);
        preparationAttempts += 1;
        // This is an injected infrastructure failure, never a trigger decision.
        throw Error("fixture preparation failed");
      } });
      const followupRun = {
        prompt: select(step, input, "promptForEstimate", ""), summaryLine: "",
        enqueuedAt: 1777824000000,
        run: {
          agentId: "main", agentDir: path.join(directory, "agent"),
          sessionId: entry?.sessionId ?? "session", sessionKey,
          sessionFile: path.join(directory, "session.jsonl"), workspaceDir: workspace,
          config: cfg, skillsSnapshot: { prompt: "", skills: [] }, provider, model: "fixture",
          thinkingCatalog: [{ provider, id: "fixture", input: ["text"] }],
          thinkLevel: "off", verboseLevel: "off", elevatedLevel: "off",
          bashElevated: { enabled: false, allowed: false, defaultLevel: "off" },
          timeoutMs: 1000, blockReplyBreak: "message_end", skipProviderRuntimeHints: true,
        },
      };
      const sessionStore = entry ? { [sessionKey]: entry } : {};
      const visibleErrors = [];
      const before = entry == null ? null : structuredClone(entry);
      const result = await runMemoryFlushIfNeeded({
        cfg, followupRun, promptForEstimate: select(step, input, "promptForEstimate", ""),
        defaultModel: "fixture", resolvedVerboseLevel: "off", sessionEntry: entry,
        sessionStore, sessionKey, storePath,
        isHeartbeat: select(step, input, "isHeartbeat", false),
        onVisibleErrorPayloads: (payloads) => visibleErrors.push(...payloads),
      });
      entry = result.sessionEntry;
      const persisted = !processOnly ? sessions.loadSessionEntry(scope) : null;
      const stats = entry && !processOnly ? sessions.readSessionTranscriptActiveStats(transcriptScope) : null;
      const snapshot = {
        outcome: result.outcome, triggered: preparationAttempts > 0,
        entry: ownedEntry(entry), persistedEntry: ownedEntry(persisted),
        transcriptByteSize: stats?.sizeBytes ?? null, preparationAttempts,
      };
      snapshots.push(snapshot);
      raw.push({ ...snapshot, before, entry: entry ?? null, persistedEntry: persisted ?? null,
        sessionStoreEntry: sessionStore[sessionKey] ?? null, planCalls, visibleErrors,
        transcriptStats: stats, events, sourceBuildReproduced: false,
        invokedOwner: "runMemoryFlushIfNeeded",
        provider, cliBackendRegistered,
        injectedFailure: preparationAttempts > 0 ? "second-plan-resolution" : null,
      });
    }
    return { provider: "none", snapshots };
  } finally {
    clearMemoryPluginState();
    await fs.mkdir(config.evidenceDirectory, { recursive: true });
    await fs.writeFile(path.join(config.evidenceDirectory, "native-raw.json"), JSON.stringify(raw) + "\n");
  }
}
