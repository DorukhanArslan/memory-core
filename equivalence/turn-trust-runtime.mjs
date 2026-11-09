// Controlled host caller over original tool, taint, coding-write and AgentLoop
// owners. Scripted model responses and registered outer results are literals;
// no taint decision, writer classification or assistant stamp is supplied.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

function publicError(error) {
  return { name: error.name, message: error.message,
    ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) =>
      !["name", "message", "stack"].includes(key)).map((key) => [key, error[key]])) };
}

export async function runTurnTrustRuntime(input, runtimeConfig) {
  if (input.kind !== "turn-trust" || !Array.isArray(input.turns) || !Number.isFinite(input.nowMs) ||
      runtimeConfig.approvedReferenceSources?.length !== 1) throw Error("An explicit mixed turn-trust profile is required");
  if (input.turns.some((turn) => turn.attempts.some((attempt) => attempt.responses.some((message) =>
    Object.hasOwn(message, "__openclaw"))))) throw Error("Scripted assistants cannot supply trusted taint metadata");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-turn-trust-"));
  const workspace = path.join(directory, "workspace"), state = path.join(directory, "state");
  await fs.mkdir(workspace); await fs.mkdir(state);
  const configPath = path.join(directory, "openclaw.json");
  const agentId = input.agentId ?? "main";
  const cfg = { agents: { defaults: { workspace }, list: [{ id: agentId, default: true }] },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { maintenance: { mode: "warn" } }, memory: { search: { enabled: false } },
    tools: { profile: "coding", loopDetection: { enabled: false }, fs: { workspaceOnly: true } } };
  await fs.writeFile(configPath, JSON.stringify(cfg));
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = state; process.env.OPENCLAW_CONFIG_PATH = configPath;
  const beforeDate = Date, beforeTimeout = setTimeout, beforePerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { fixtureBase: directory, kind: "turn-trust", pid: process.pid, config: cfg, input,
    sourceAuthority: runtimeConfig.approvedReferenceSources[0],
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== beforeDate,
      setTimeoutUnchanged: setTimeout === beforeTimeout, performanceNowUnchanged: performance.now === beforePerformance },
    taintCreations: [], toolFactoryCalls: [], toolInvocations: [], nativeObservations: [], innerWrites: [],
    modelCalls: [], events: [], persistence: [], attempts: [], reopen: null };
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let clearConfig;
  try {
    const runtime = await imp("dist/plugin-sdk/config-runtime.js");
    runtime.setRuntimeConfigSnapshot(cfg); clearConfig = runtime.clearRuntimeConfigSnapshot;
    const taint = await import(pathToFileURL(runtimeConfig.approvedReferenceSources[0].path).href);
    const { t: createCodingTools } = await imp("dist/agent-tools-HIqp3eTk.mjs");
    const { l: wrapBeforeToolCall } = await imp("dist/agent-tools.before-tool-call-Cg8vCu9u.mjs");
    const core = await imp("dist/plugin-sdk/agent-core.js");
    const { x: createStream } = await imp("dist/llm-ASoRyt-k.mjs");
    const artifacts = await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs");
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const storePath = sessions.resolveStorePath(undefined, { agentId });
    const scope = { agentId, storePath, sessionKey: input.sessionKey, sessionId: input.sessionId };
    const upsertRequest = { ...scope, entry: { sessionId: input.sessionId, updatedAt: input.nowMs } };
    const upsertResult = await sessions.upsertSessionEntry(upsertRequest);
    raw.sessionUpsert = { request: upsertRequest, result: upsertResult, returnedUndefined: upsertResult === undefined };
    raw.sessionScope = scope;
    const history = [], outputTurns = [], touched = new Set();
    async function fileFacts() {
      const result = {};
      for (const relativePath of touched) {
        const filename = path.join(workspace, relativePath);
        result[relativePath] = await fs.readFile(filename, "utf8");
      }
      return result;
    }
    const model = { id: "fixture-trust-model", name: "Fixture trust model", api: "openai-completions", provider: "openai",
      baseUrl: "https://fixture.invalid", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 10000, maxTokens: 1000 };
    for (const turn of input.turns) {
      const sticky = taint.createAgentTurnTaintState();
      raw.taintCreations.push({ turnId: turn.id, initiallyTainted: sticky.isTainted() });
      const trust = () => ({ tainted: sticky.isTainted() });
      let activeAttemptId, activeInvocation;
      const observe = (observation, origin = "dispatched-tool") => {
        const before = sticky.isTainted(); sticky.observe(observation);
        raw.nativeObservations.push({ turnId: turn.id, attemptId: activeAttemptId,
          toolCallId: activeInvocation?.toolCallId, observation: structuredClone(observation),
          origin, before, after: sticky.isTainted() });
      };
      for (const observation of turn.presentationObservations ?? []) {
        observe(observation, "trusted-host-presentation");
      }
      const outputs = [];
      let messageIndex = 0;
      for (const [attemptIndex, attempt] of turn.attempts.entries()) {
        activeAttemptId = attempt.id;
        const runId = `${turn.id}:${attempt.id}`;
        const factoryOptions = { config: cfg, agentId, workspaceDir: workspace, cwd: workspace,
          sessionId: input.sessionId, sessionKey: input.sessionKey, runId,
          senderIsOwner: turn.senderIsOwner, isTurnTainted: sticky.isTainted,
          onToolOutcome: observe, requireWorkspaceOnly: true, wrapBeforeToolCallHook: false,
          toolConstructionPlan: { includeBaseCodingTools: true, includeShellTools: false,
            includeChannelTools: false, includeOpenClawTools: false, includePluginTools: false } };
        const codingTools = createCodingTools(factoryOptions);
        const codingWrite = codingTools.find((tool) => tool.name === "write");
        if (!codingWrite) throw Error("The original coding factory did not supply its real write tool");
        raw.toolFactoryCalls.push({ turnId: turn.id, attemptId: attempt.id,
          options: { ...factoryOptions, isTurnTainted: "actual-state.isTainted", onToolOutcome: "actual-state.observe" },
          callbackIdentity: { sameTurnTaintReader: factoryOptions.isTurnTainted === sticky.isTainted,
            sameTurnOutcomeObserver: factoryOptions.onToolOutcome === observe },
          toolNames: codingTools.map((tool) => tool.name), taintedAtConstruction: sticky.isTainted() });
        const definitions = [...input.tools, { name: "write_memory", result: input.writeResult }];
        if (new Set(definitions.map((tool) => tool.name)).size !== definitions.length) throw Error("Duplicate fixture tool registration");
        const toolOutcomes = [];
        const tools = definitions.map((definition) => {
          const tool = { name: definition.name, label: definition.name, description: "Literal fixture tool",
            parameters: { type: "object", properties: {}, additionalProperties: true },
            ...(definition.resultContentSource ? { resultContentSource: definition.resultContentSource } : {}),
            execute: async (toolCallId, args, signal, onUpdate) => {
              if (definition.name === "write_memory") {
                if (typeof args.path !== "string" || path.isAbsolute(args.path) || args.path.split(/[\\/]/).includes("..")) {
                  throw Error("Fixture writes must remain owned");
                }
                const before = sticky.isTainted();
                const result = await codingWrite.execute(toolCallId, args, signal, onUpdate);
                raw.innerWrites.push({ turnId: turn.id, attemptId: attempt.id, toolCallId, args: structuredClone(args),
                  taintedAtWrite: before, result }); touched.add(args.path);
              }
              if (definition.error) {
                const error = new Error(definition.error.message); error.name = definition.error.name;
                for (const [key, value] of Object.entries(definition.error)) if (!["message", "name"].includes(key)) error[key] = value;
                throw error;
              }
              return structuredClone(definition.result);
            } };
          const wrapped = wrapBeforeToolCall(tool, { config: cfg, agentId, cwd: workspace, workspaceDir: workspace,
            sessionId: input.sessionId, sessionKey: input.sessionKey, runId,
            loopDetection: { enabled: false }, onToolOutcome: observe }, { protectNetworkErrors: false });
          // A fixture host registration delegates to the original wrapped
          // method. Its private execution preparer stays on the unchanged
          // original tool; the public execute route owns this sequential call.
          const delegate = { name: wrapped.name, label: wrapped.label, description: wrapped.description,
            parameters: wrapped.parameters,
            ...(wrapped.resultContentSource ? { resultContentSource: wrapped.resultContentSource } : {}),
            execute: async function (...args) {
            const call = { turnId: turn.id, attemptId: attempt.id, toolCallId: args[0],
              toolName: definition.name, arguments: structuredClone(args[1]) };
            const receiver = wrapped, forwardedArguments = args;
            const identity = { receiverIsOriginalWrapped: receiver === wrapped,
              argumentArrayForwardedUnchanged: forwardedArguments === args };
            activeInvocation = call;
            try {
              const result = await wrapped.execute.apply(receiver, forwardedArguments);
              const forwardedResult = result;
              raw.toolInvocations.push({ ...call, result,
                identity: { ...identity, resultReturnedUnchanged: forwardedResult === result } });
              toolOutcomes.push({ id: call.toolCallId, name: call.toolName, input: call.arguments, result });
              return forwardedResult;
            } catch (error) {
              const forwardedError = error;
              const detail = publicError(error); raw.toolInvocations.push({ ...call, error: detail, stack: error.stack,
                identity: { ...identity, errorRethrownUnchanged: forwardedError === error } });
              toolOutcomes.push({ id: call.toolCallId, name: call.toolName, input: call.arguments, error: detail });
              throw forwardedError;
            } finally { activeInvocation = undefined; }
          } };
          return delegate;
        });
        let responseIndex = 0;
        const streamFn = (_model, context, options) => {
          const response = attempt.responses[responseIndex++];
          if (!response) throw Error("The original AgentLoop requested an undeclared model response");
          raw.modelCalls.push({ turnId: turn.id, attemptId: attempt.id, responseIndex: responseIndex - 1,
            model: _model, context: JSON.parse(JSON.stringify(context)), options,
            response: structuredClone(response) });
          const stream = createStream();
          queueMicrotask(() => { stream.push({ type: "done", reason: response.stopReason,
            message: structuredClone(response) }); stream.end(); });
          return stream;
        };
        const emit = async (event) => {
          raw.events.push({ turnId: turn.id, attemptId: attempt.id, event: structuredClone(event) });
          if (event.type === "message_end") {
            const options = { message: event.message, eventId: `${turn.id}:message:${messageIndex++}`,
              now: input.nowMs, cwd: "/fixture/workspace" };
            const result = await accessor.appendTranscriptMessage(scope, options);
            raw.persistence.push({ turnId: turn.id, attemptId: attempt.id, scope, options, result });
          }
        };
        const messages = await core.runAgentLoop(attemptIndex === 0 ? [turn.prompt] : [],
          { systemPrompt: "", messages: history, tools },
          { model, convertToLlm: core.convertToLlm,
            shouldStopAfterTurn: () => responseIndex === attempt.responses.length }, emit, undefined, streamFn);
        history.push(...messages);
        const snapshot = { id: attempt.id, messages, toolOutcomes, trust: trust(),
          artifacts: await artifacts.n({ workspaceDir: workspace }), files: await fileFacts() };
        outputs.push(snapshot); raw.attempts.push({ turnId: turn.id, ...snapshot });
      }
      outputTurns.push({ id: turn.id, attempts: outputs, trust: trust() });
    }
    const request = { directory, runtimeRoot: runtimeConfig.runtimeRoot, input: {
      nowMs: input.nowMs, agentId, sessionId: input.sessionId, sessionKey: input.sessionKey } };
    const child = spawn(process.execPath, [fileURLToPath(new URL("./turn-trust-reopen-cli.mjs", import.meta.url))],
      { env: { ...process.env }, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; }); child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.stdin.end(JSON.stringify(request));
    const exit = await new Promise((resolve, reject) => {
      child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
    });
    raw.reopen = { pid: child.pid, request, exit, stdout, stderr };
    if (exit.code !== 0 || !stdout) throw Error(`The actual fresh-process storage read failed: ${JSON.stringify(raw.reopen)}`);
    const reopened = JSON.parse(stdout); raw.reopen.result = reopened;
    if (reopened.fatal) throw Error(`Fresh-process reader failed: ${JSON.stringify(reopened.fatal)}`);
    return mapGetFixturePaths({ provider: "none", turns: outputTurns,
      storedEvents: reopened.events, sourceEntry: reopened.sourceEntry,
      artifacts: reopened.artifacts, files: await fileFacts() }, directory);
  } finally {
    clearConfig?.(); mock.timers.reset();
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}
