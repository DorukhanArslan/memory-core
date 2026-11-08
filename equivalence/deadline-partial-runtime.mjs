// Genuine tool/deadline/corpus/cooldown owners over controlled provider callbacks.
// The manager constructor is deliberately bypassed in this separate profile;
// indexed-search comparisons keep their real index worker requirement.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";
import { awaitDeadlineFixture, enableDeadlineFixtureClock, fixtureAbortReason,
  fixtureError, flushDeadlineFixture } from "./deadline-partial.mjs";

const publicError = (error) => ({ name: error.name,
  ...(error.status === undefined ? {} : { status: error.status }), message: error.message,
  ...(error.code === undefined ? {} : { code: error.code }) });

export const CONTROLLED_MANAGER_STATUS = {
  backend: "builtin", files: 1, chunks: 1, dirty: false,
  workspaceDir: "/fixture/workspace", dbPath: "/fixture/index.sqlite",
  provider: "none", requestedProvider: "none", sources: ["memory"],
  sourceCounts: [{ source: "memory", files: 1, chunks: 1 }],
  fts: { enabled: true, available: true },
};

async function executeDeadlinePartialRuntime(input, runtimeConfig, toolName) {
  if (input.kind !== "tool" || !runtimeConfig?.runtimeRoot || !path.isAbsolute(runtimeConfig.runtimeRoot) ||
      !runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Controlled whole-tool fixtures require authenticated absolute runtime/evidence directories");
  }
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  // Initialization completes before the genuine timer APIs are controlled.
  const MemoryIndexManager = toolName === "memory_search"
    ? (await imp("dist/extensions/memory-core/manager-runtime.js")).MemoryIndexManager : undefined;
  await imp("dist/tools.runtime.js");
  const { createMemorySearchTool, createMemoryGetTool, testing } = await imp("dist/tools-DotaQGXh.mjs");
  const { t: deadlineControlKey } = await imp("dist/search-deadline-control-CvwcTLrz.mjs");
  const { m: registerSupplement } = await imp("dist/memory-state-BmtUbXjH.mjs");
  const originalGet = MemoryIndexManager?.get;
  const raw = { toolName, managerFixture: Boolean(MemoryIndexManager), constructorSkipped: Boolean(MemoryIndexManager),
    ...(toolName === "memory_get" ? { managerAcquisition: "not-required", indexManagerConstructed: false } : {}),
    globalEvents: [], nativeEnvelopes: [], managerGets: [], statusReads: [], closes: [],
    clockSteps: [], clockObservationCuts: [], clockOutcomeCuts: [], clockClearCuts: [] };
  let fixtureDirectory, workspace = "/fixture/workspace";
  if (toolName === "memory_get") {
    await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
    fixtureDirectory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "deadline-get-fixture-"));
    raw.fixtureBase = fixtureDirectory;
    workspace = path.join(fixtureDirectory, "workspace");
    await fs.mkdir(workspace);
    for (const [relative, text] of Object.entries(input.files ?? {})) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
        throw Error("Real get fixtures must remain within their owned workspace");
      }
      const filename = path.join(workspace, relative);
      await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, text, "utf8");
    }
  }
  const lanes = new Map(), calls = new Map(), memoryDispatches = [], wikiDispatches = {};
  function lane(name) {
    if (!lanes.has(name)) lanes.set(name, { events: [], invocations: [] });
    return lanes.get(name);
  }
  function log(name, invocation, event, data = {}) {
    const value = { event, invocation, time: Date.now(), ...data };
    lane(name).events.push(value);
    raw.globalEvents.push({ lane: name, ...value });
  }
  function startProvider(name, args, signal, options) {
    const entry = lane(name), invocation = entry.invocations.length + 1;
    let resolve, reject;
    const pending = new Promise((yes, no) => { resolve = yes; reject = no; });
    const record = { signal, options, resolve, reject, finished: false, aborted: false };
    entry.invocations.push(record);
    log(name, invocation, "start", { args });
    signal?.addEventListener("abort", () => {
      record.aborted = true;
      log(name, invocation, "abort", { reason: signal.reason instanceof Error ? publicError(signal.reason) : signal.reason });
      if (input.abortBehavior !== "ignore") reject(input.abortError ? fixtureError(input.abortError) : signal.reason);
    }, { once: true });
    return (async () => {
      try {
        const value = await pending;
        log(name, invocation, "fulfilled", { value });
        return value;
      } catch (error) {
        log(name, invocation, "rejected", { error: publicError(error), sameAsSignalReason: error === signal?.reason });
        throw error;
      } finally { record.finished = true; }
    })();
  }
  const status = { ...structuredClone(CONTROLLED_MANAGER_STATUS), ...structuredClone(input.status ?? {}) };
  const manager = {
    status() { raw.statusReads.push({ time: Date.now(), status: structuredClone(status) }); return structuredClone(status); },
    async search(query, options) {
      const args = { maxResults: options.maxResults,
        ...(options.minScore === undefined ? {} : { minScore: options.minScore }),
        ...(options.sessionKey === undefined ? {} : { sessionKey: options.sessionKey }),
        ...(options.activeProjectKeys === undefined ? {} : { activeProjectKeys: options.activeProjectKeys }),
        ...(options.sources === undefined ? {} : { sources: options.sources }),
        signalPresent: Boolean(options.signal), partialCallbackPresent: typeof options.onPartialResults === "function",
        deadlineControlPresent: Boolean(options[deadlineControlKey]), onDebugPresent: typeof options.onDebug === "function" };
      memoryDispatches.push({ query, options: args });
      raw.memoryOptionSurfaces ??= [];
      raw.memoryOptionSurfaces.push({ ownKeys: Object.keys(options),
        symbols: Object.getOwnPropertySymbols(options).map((key) => key.description) });
      return await startProvider("memory", { query, options: args }, options.signal, options);
    },
    async close() { raw.closes.push({ time: Date.now() }); },
  };
  if (MemoryIndexManager) MemoryIndexManager.get = async function (params) {
    raw.managerGets.push({ time: Date.now(), agentId: params.agentId, purpose: params.purpose,
      cfg: structuredClone(params.cfg) });
    const failure = input.acquisitionErrors?.[raw.managerGets.length - 1];
    if (failure) throw fixtureError(failure);
    return manager;
  };
  for (const fixture of input.supplements ?? []) {
    lane(`wiki:${fixture.pluginId}`);
    wikiDispatches[fixture.pluginId] = [];
    registerSupplement(fixture.pluginId, {
      search: async (query) => {
        wikiDispatches[fixture.pluginId].push(structuredClone(query));
        return await startProvider(`wiki:${fixture.pluginId}`, query);
      }, get: async (query) => {
        wikiDispatches[fixture.pluginId].push(structuredClone(query));
        return await startProvider(`wiki:${fixture.pluginId}`, query);
      },
    });
  }
  lane("memory");
  const cfg = { agents: { defaults: { workspace } },
    memory: { search: { enabled: true, provider: "none", fallback: "none",
      sources: input.config?.sources ?? ["memory"],
      ...(input.config?.sources?.includes("sessions") ? { experimental: { sessionMemory: true } } : {}),
      query: { ...(input.config?.query ?? {}) },
      ...(input.config?.extra ?? {}),
    } } };
  let currentConfig = cfg;
  const tool = (toolName === "memory_get" ? createMemoryGetTool : createMemorySearchTool)({ config: cfg, getConfig: () => currentConfig,
    agentId: "main", ...structuredClone(input.options ?? {}) });
  if (!tool) throw Error("The actual memory tool was unavailable");
  const clock = enableDeadlineFixtureClock(input.startMs);
  raw.timerDriver = { kind: "node-test-mock-timers", apis: ["Date", "setTimeout"],
    ...clock.evidence, performanceNowMatchesDateNow: performance.now() === Date.now() };
  raw.timerClears = clock.clearEvents;
  const stateCounts = () => ({
    dispatchCounts: Object.fromEntries([...lanes].map(([name, item]) => [name, item.invocations.length])),
    activeCounts: Object.fromEntries([...lanes].map(([name, item]) => [name, item.invocations.filter((value) => !value.finished).length])),
    abortCounts: Object.fromEntries([...lanes].map(([name, item]) => [name, item.invocations.filter((value) => value.aborted).length])),
    settledCalls: [...calls].filter(([, value]) => value.settled).map(([name]) => name),
  });
  async function barrier(command) {
    await awaitDeadlineFixture(() => {
      const failed = [...calls.values()].find((value) => value.protocolError);
      if (failed) throw failed.protocolError;
      return Object.entries(command.dispatches ?? {}).every(([name, count]) => lane(name).invocations.length >= count) &&
      Object.entries(command.finished ?? {}).every(([name, count]) => lane(name).invocations.filter((item) => item.finished).length >= count) &&
      (command.settled ?? []).every((id) => calls.get(id)?.settled) &&
      (command.timerClears === undefined || clock.clearEvents.length >= command.timerClears);
    }, "explicit provider/control observations");
  }
  try {
    testing.resetMemorySearchToolCooldowns();
    for (const command of input.commands) {
      if (command.op === "call") {
        if (calls.has(command.id)) throw Error("Controlled calls require unique ids");
        if (command.configPatch) currentConfig = { ...cfg, memory: { search: { ...cfg.memory.search, ...command.configPatch } } };
        const controller = new AbortController();
        if (Object.hasOwn(command, "parentPreAbort")) controller.abort(fixtureAbortReason(command.parentPreAbort));
        const record = { controller, settled: false };
        calls.set(command.id, record);
        tool.execute(command.id, command.params, controller.signal).then((result) => {
          raw.nativeEnvelopes.push({ id: command.id, time: Date.now(), result });
          try { record.output = { id: command.id, result: decodeSearchToolEnvelope(result) }; }
          catch (error) { record.protocolError = error; }
          record.settled = true;
        }, (error) => {
          const output = { id: command.id, error: publicError(error) };
          raw.nativeEnvelopes.push({ ...output, time: Date.now() }); record.output = output; record.settled = true;
        });
      } else if (command.op === "tick") clock.tick(command.ms);
      else if (command.op === "set-time") clock.setTime(command.nowMs);
      else if (command.op === "abort") calls.get(command.id).controller.abort(fixtureAbortReason(command.reason));
      else if (["resolve", "reject", "partial", "pause", "resume"].includes(command.op)) {
        const target = lane(command.lane).invocations[command.invocation - 1];
        if (!target) throw Error("Provider commands require a previously observed invocation");
        if (command.op === "resolve") target.resolve(structuredClone(command.value));
        else if (command.op === "reject") target.reject(fixtureError(command.error));
        else if (command.op === "partial") {
          log(command.lane, command.invocation, "partial", { rows: structuredClone(command.rows) });
          target.options.onPartialResults(structuredClone(command.rows));
        } else {
          log(command.lane, command.invocation, command.op);
          target.options[deadlineControlKey].report(command.op);
        }
      } else if (command.op !== "barrier" && command.op !== "settle" && command.op !== "flush" && command.op !== "await-dispatch") {
        throw Error(`Unsupported controlled deadline command: ${command.op}`);
      }
      await flushDeadlineFixture();
      await barrier(command.op === "settle" ? { ...command, settled: [command.id] }
        : command.op === "await-dispatch" ? { ...command, dispatches: { ...command.dispatches, [command.lane]: command.count } } : command);
      raw.clockObservationCuts.push(raw.globalEvents.length);
      raw.clockOutcomeCuts.push(raw.nativeEnvelopes.length);
      raw.clockClearCuts.push(clock.clearEvents.length);
      raw.clockSteps.push({ ...command, time: Date.now(),
        ...(Object.hasOwn(command, "timerClears") ? { timerClearCount: clock.clearEvents.length } : {}),
        ...(["barrier", "tick", "set-time", "pause", "resume", "settle"].includes(command.op) ? stateCounts() : {}) });
    }
    await awaitDeadlineFixture(() => [...calls.values()].every((value) => value.settled), "all tool replies");
    if (MemoryIndexManager) raw.status = status;
    return { provider: "none", calls: [...calls.values()].map((value) => value.output),
      memoryDispatches, wikiDispatches, lanes: Object.fromEntries([...lanes].map(([name, value]) => [name, value.events])),
      clockSteps: raw.clockSteps };
  } finally {
    clock.restore();
    if (MemoryIndexManager) {
      MemoryIndexManager.get = originalGet;
      raw.managerGetRestoredBeforeExit = MemoryIndexManager.get === originalGet;
    }
    await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    if (fixtureDirectory) await fs.rm(fixtureDirectory, { recursive: true, force: true });
  }
}

export async function runDeadlinePartialRuntime(input, runtimeConfig) {
  if (input.toolName !== undefined && input.toolName !== "memory_search") {
    throw Error("The controlled-manager deadline profile accepts only memory_search");
  }
  return await executeDeadlinePartialRuntime(input, runtimeConfig, "memory_search");
}

export async function runDeadlineGetRuntime(input, runtimeConfig) {
  if (input.toolName !== "memory_get") throw Error("The real-file get deadline profile accepts only memory_get");
  return await executeDeadlinePartialRuntime(input, runtimeConfig, "memory_get");
}
