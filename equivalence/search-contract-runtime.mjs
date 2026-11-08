// Execute authenticated official tool exports. Files, options, a paired clock
// and registered wiki-provider callbacks are fixtures; native code owns parsing,
// indexing, visibility, ranking, aggregation, presentation and the full envelope.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const publicError = (error) => ({ name: error.name,
  ...(error.status === undefined ? {} : { status: error.status }), message: error.message });

// Explicit transport codec: the text carrier must round-trip to the complete
// details payload. Preserve every other envelope key/item and retain raw text
// independently. Pretty whitespace and 1.0/1 spelling are not a JS-engine claim.
export function decodeSearchToolEnvelope(envelope) {
  // This is the complete actual JSON transport, including its native omission
  // of undefined object properties; no selected fields are projected away.
  const transported = JSON.parse(JSON.stringify(envelope));
  if (!transported || !Array.isArray(transported.content) || !transported.content.length ||
      transported.content[0]?.type !== "text" || typeof transported.content[0].text !== "string") {
    throw Error("The native tool returned no JSON text carrier");
  }
  const decoded = JSON.parse(transported.content[0].text);
  if (!isDeepStrictEqual(decoded, transported.details)) {
    throw Error("The native JSON text carrier does not exactly round-trip to details");
  }
  const result = transported;
  result.content[0].text = decoded;
  return result;
}

async function executeSearchContractRuntime(input, runtimeConfig) {
  if (!runtimeConfig?.runtimeRoot || !path.isAbsolute(runtimeConfig.runtimeRoot) ||
      !runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Authenticated absolute runtime and evidence directories are required");
  }
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  const raw = { kind: input.kind, nativeEnvelopes: [], dispatches: [] };
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const persist = () => fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
  if (input.kind === "definition" || input.kind === "prepare-arguments") {
    try {
      const { n: contract } = await imp("dist/memory-tool-contract-DOz26L8b.mjs");
      const { createMemorySearchTool } = await imp("dist/tools-DotaQGXh.mjs");
      let result;
      if (input.kind === "prepare-arguments") {
        const prepared = contract.prepareArguments(input.params);
        result = { params: prepared, sameInput: prepared === input.params, inputAfter: input.params };
      }
      else {
        const cfg = { agents: { defaults: { workspace: "/fixture/workspace" } }, memory: { search: {
          enabled: input.enabled !== false, provider: "none", fallback: "none",
          sources: input.indexSessions ? ["memory", "sessions"] : ["memory"],
          extraPaths: input.extraPaths ?? [],
          ...(input.indexSessions ? { experimental: { sessionMemory: true } } : {}),
        } } };
        const tool = createMemorySearchTool({ config: input.missingConfig ? undefined : cfg, agentId: "main" });
        result = { definition: tool ? { label: tool.label, name: tool.name,
          parameters: tool.parameters, description: tool.description } : null };
      }
      raw.result = result;
      return { provider: "none", ...result };
    } catch (error) {
      return { provider: "none", error: publicError(error) };
    } finally { await persist(); }
  }
  if (input.kind !== "tool") throw Error(`Unsupported search-contract runtime operation: ${input.kind}`);
  if (!Number.isFinite(input.nowMs) || !Number.isFinite(input.mtimeMs)) {
    throw Error("Whole-tool fixtures require explicit finite paired clock and file mtime inputs");
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-search-contract-"));
  const workspace = path.join(directory, "workspace");
  await fs.mkdir(workspace);
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = runtimeConfig.stateDirectory;
  process.env.OPENCLAW_CONFIG_PATH = runtimeConfig.configPath;
  const originalNow = Date.now;
  let closeManagers;
  try {
    for (const [relative, text] of Object.entries(input.files ?? {})) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
        throw Error("Fixture files must stay inside their owned workspace");
      }
      const filename = path.join(workspace, relative);
      await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, text, "utf8");
      await fs.utimes(filename, input.mtimeMs / 1000, input.mtimeMs / 1000);
    }
    const { MemoryIndexManager, closeAllMemoryIndexManagers } = await imp("dist/extensions/memory-core/manager-runtime.js");
    closeManagers = closeAllMemoryIndexManagers;
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const cfg = {
      agents: { defaults: { workspace } },
      memory: { ...(Object.hasOwn(input.config ?? {}, "citations") ? { citations: input.config.citations } : {}),
        search: {
          enabled: true, provider: "none", fallback: "none", sources: input.config?.sources ?? ["memory"],
          ...(input.config?.extraPaths ? { extraPaths: input.config.extraPaths.map((value) => path.join(workspace, value)) } : {}),
          store: { vector: { enabled: false } },
          sync: { onSessionStart: false, onSearch: false, watch: false },
          query: { ...(input.config?.query ?? {}), hybrid: { temporalDecay: { enabled: false } } },
        } },
    };
    if (cfg.memory.search.sources.includes("sessions")) cfg.memory.search.experimental = { sessionMemory: true };
    // This real construction/publication occurs even for a step that is rejected
    // before dispatch. It does not claim that rejected step searched the index.
    const manager = await MemoryIndexManager.get({ cfg, agentId: "main" });
    if (!manager) throw Error("The native provider-none memory manager was unavailable");
    manager.markMemoryWatchDirty();
    await manager.sync({ reason: "fixture" });
    raw.constructorExecuted = true;
    raw.provider = "none";
    const originalSearch = manager.search;
    manager.search = async function (...args) {
      raw.dispatches.push({ query: args[0], options: args[1] });
      return await originalSearch.apply(this, args);
    };
    if (input.supplements?.length) {
      const { m: register } = await imp("dist/memory-state-BmtUbXjH.mjs");
      for (const fixture of input.supplements) register(fixture.pluginId, {
        search: async (query) => {
          raw.dispatches.push({ pluginId: fixture.pluginId, supplementQuery: query });
          if (fixture.error !== undefined) throw Error(fixture.error);
          return structuredClone(fixture.results ?? []);
        },
        get: async () => null,
      });
    }
    const { createMemorySearchTool } = await imp("dist/tools-DotaQGXh.mjs");
    let liveConfig = cfg;
    const tool = createMemorySearchTool({ config: cfg, getConfig: () => liveConfig,
      agentId: "main", ...structuredClone(input.options ?? {}) });
    if (!tool) throw Error("The native memory search tool was unavailable");
    const steps = [];
    for (const [index, step] of input.steps.entries()) {
      liveConfig = step.disableConfig ? { ...cfg, memory: { ...cfg.memory, search: { ...cfg.memory.search, enabled: false } } } : cfg;
      Date.now = () => step.nowMs ?? input.nowMs;
      let result;
      let completed = false;
      try {
        const controller = new AbortController();
        if (step.abortBefore) controller.abort(new Error("Fixture caller aborted"));
        const params = step.prepareArguments ? tool.prepareArguments(step.params) : step.params;
        result = await tool.execute(`fixture-${index}`, params, controller.signal);
        completed = true;
      } catch (error) {
        const value = { error: publicError(error) };
        raw.nativeEnvelopes.push({ index, ...value });
        steps.push(value);
      } finally { Date.now = originalNow; }
      if (completed) {
        raw.nativeEnvelopes.push({ index, result });
        steps.push({ result: decodeSearchToolEnvelope(result) });
      }
    }
    raw.status = manager.status();
    return { provider: "none", steps };
  } finally {
    Date.now = originalNow;
    await persist();
    await closeManagers?.();
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}

export async function runSearchContractHelperRuntime(input, runtimeConfig) {
  if (input.kind !== "definition" && input.kind !== "prepare-arguments") {
    throw Error("Only genuine definition/preparation helpers belong to the worker-free profile");
  }
  return await executeSearchContractRuntime(input, runtimeConfig);
}

export async function runSearchContractRuntime(input, runtimeConfig) {
  if (input.kind !== "tool") throw Error("The protected search runtime accepts only whole-tool fixtures");
  return await executeSearchContractRuntime(input, runtimeConfig);
}
