// Complete official memory_get factory and execute boundary. This reader does
// not construct an index manager; genuine secure file IO and wiki registrations
// exercise the native read and corpus owners without an invented index worker.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";

const publicError = (error) => ({ name: error.name,
  ...(error.status === undefined ? {} : { status: error.status }), message: error.message });

// Host identity transport only. Preserve all values and path suffixes; no OS
// wording, cause, code, provider content or envelope field is selected away.
export function mapGetFixturePaths(value, fixtureBase) {
  if (typeof value === "string") return value === fixtureBase ? "$FIXTURE"
    : value.replaceAll(`${fixtureBase}/`, "$FIXTURE/");
  if (Array.isArray(value)) return value.map((item) => mapGetFixturePaths(item, fixtureBase));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [key, mapGetFixturePaths(item, fixtureBase)]));
  return value;
}

async function executeGetContractRuntime(input, runtimeConfig) {
  if (!runtimeConfig?.runtimeRoot || !path.isAbsolute(runtimeConfig.runtimeRoot) ||
      !runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Authenticated absolute runtime and evidence directories are required");
  }
  if (input.kind !== "definition" && input.kind !== "tool") {
    throw Error("The protected get runtime accepts only definition or whole-tool fixtures");
  }
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-get-fixture-"));
  const raw = { kind: input.kind, fixtureBase: directory,
    nativeEnvelopes: [], requests: [], indexManagerConstructed: false };
  const workspace = path.join(directory, "workspace");
  const outside = path.join(directory, "outside");
  await fs.mkdir(workspace);
  await fs.mkdir(outside);
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = runtimeConfig.stateDirectory;
  process.env.OPENCLAW_CONFIG_PATH = runtimeConfig.configPath;
  function filename(relative, root = workspace) {
    if (typeof relative !== "string" || path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
      throw Error("Fixture paths must stay inside their owned workspace");
    }
    return path.join(root, relative);
  }
  try {
    for (const relative of input.directories ?? []) await fs.mkdir(filename(relative), { recursive: true });
    for (const [relative, text] of Object.entries(input.files ?? {})) {
      const absolute = filename(relative);
      await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, text, "utf8");
    }
    for (const [relative, octets] of Object.entries(input.fileBytes ?? {})) {
      if (!Array.isArray(octets) || octets.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) {
        throw Error("Byte fixtures require arrays of octets");
      }
      const absolute = filename(relative);
      await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, Uint8Array.from(octets));
    }
    for (const [relative, text] of Object.entries(input.outsideFiles ?? {})) {
      const absolute = filename(relative, outside);
      await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, text, "utf8");
    }
    for (const [relative, target] of Object.entries(input.symlinks ?? {})) {
      if (target.scope !== "workspace" && target.scope !== "outside") throw Error("Unknown fixture symlink scope");
      const absolute = filename(relative);
      await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.symlink(filename(target.path, target.scope === "outside" ? outside : workspace), absolute);
    }
    const cfg = { agents: { defaults: { workspace,
      ...(Object.hasOwn(input.config ?? {}, "maxChars") ? { contextLimits: { memoryGetMaxChars: input.config.maxChars } } : {}),
    } }, memory: { search: {
      enabled: input.enabled !== false, provider: "none", fallback: "none",
      sources: input.indexSessions ? ["memory", "sessions"] : ["memory"],
      extraPaths: (input.extraPaths ?? input.config?.extraPaths ?? []).map((value) => {
        if (typeof value === "string" && value.startsWith("$WORKSPACE/")) {
          return filename(value.slice("$WORKSPACE/".length));
        }
        // Validate fixture ownership but let the native host resolve its real
        // relative configuration value, rather than pre-resolving it here.
        filename(value);
        return value;
      }),
      ...(input.indexSessions ? { experimental: { sessionMemory: true } } : {}),
    } } };
    if (input.supplements?.length) {
      const { m: register } = await imp("dist/memory-state-BmtUbXjH.mjs");
      for (const fixture of input.supplements) register(fixture.pluginId, {
        search: async () => [],
        get: async (query) => {
          raw.requests.push({ pluginId: fixture.pluginId, query });
          if (fixture.error !== undefined) throw Error(fixture.error);
          return structuredClone(Object.hasOwn(fixture.resultsByLookup ?? {}, query.lookup)
            ? fixture.resultsByLookup[query.lookup] : fixture.result ?? null);
        },
      });
    }
    const { createMemoryGetTool } = await imp("dist/tools-DotaQGXh.mjs");
    let liveConfig = input.missingConfig ? undefined : cfg;
    const tool = createMemoryGetTool({ config: liveConfig, getConfig: () => liveConfig,
      agentId: "main", ...structuredClone(input.options ?? {}) });
    if (input.kind === "definition") {
      const definition = tool ? { label: tool.label, name: tool.name,
        description: tool.description, parameters: tool.parameters } : null;
      raw.definition = definition;
      return { provider: "none", definition };
    }
    if (!tool) throw Error("The native memory get tool was unavailable");
    const steps = [];
    for (const [index, step] of input.steps.entries()) {
      liveConfig = step.missingConfig ? undefined : step.disableConfig
        ? { ...cfg, memory: { ...cfg.memory, search: { ...cfg.memory.search, enabled: false } } } : cfg;
      let result;
      let completed = false;
      try {
        const params = structuredClone(step.params);
        if (typeof params?.path === "string" && params.path.startsWith("$WORKSPACE/")) {
          params.path = filename(params.path.slice("$WORKSPACE/".length));
        }
        result = await tool.execute(`fixture-${index}`, params);
        completed = true;
      } catch (error) {
        const value = { error: publicError(error) };
        raw.nativeEnvelopes.push({ index, ...value });
        steps.push(value);
      }
      if (completed) {
        raw.nativeEnvelopes.push({ index, result });
        steps.push({ result: decodeSearchToolEnvelope(result) });
      }
    }
    const result = { provider: "none", steps, requests: raw.requests };
    return input.normalizeFixturePaths ? mapGetFixturePaths(result, directory) : result;
  } finally {
    await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}

export async function runGetContractRuntime(input, runtimeConfig) {
  if (input.kind !== "tool") throw Error("The get tool runtime accepts only genuine whole-tool fixtures");
  return await executeGetContractRuntime(input, runtimeConfig);
}

export async function runGetContractHelperRuntime(input, runtimeConfig) {
  if (input.kind !== "definition") throw Error("The get helper runtime accepts only genuine definition fixtures");
  return await executeGetContractRuntime(input, runtimeConfig);
}
