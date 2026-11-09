// Complete genuine formatter and whole memory-tool supplemental error boundaries.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";
import { modelRuntimeIdentity, modelEncode } from "./model-runtime-observation.mjs";

function fixtureError(spec) {
  if (typeof spec === "string") return spec;
  const error = new Error(spec.message);
  if (Object.hasOwn(spec, "code")) error.code = spec.code;
  if (Object.hasOwn(spec, "cause")) error.cause = fixtureError(spec.cause);
  return error;
}

function actualError(value) {
  if (!(value instanceof Error)) return modelEncode(value);
  return { name: value.name, message: value.message, own: Object.fromEntries(
    Object.getOwnPropertyNames(value).map((key) => [key, key === "cause" ? actualError(value[key]) : modelEncode(value[key])])) };
}

export async function runModelToolErrorPhase(request) {
  const { input, directory, runtimeRoot } = request;
  if (![directory, runtimeRoot].every((item) => typeof item === "string" && path.isAbsolute(item)) ||
      !input || !Object.hasOwn(input, "error") || Object.keys(input).some((key) => !["error", "patterns", "registeredSecrets"].includes(key))) {
    throw Error("A fixed literal error and owned absolute runtime paths are required");
  }
  const runtime = modelRuntimeIdentity();
  await fs.mkdir(directory, { recursive: true });
  const workspace = path.join(directory, "workspace"); await fs.mkdir(workspace);
  const config = { agents: { defaults: { workspace } },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log"),
      ...(input.patterns ? { redactPatterns: input.patterns } : {}) },
    memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"] } } };
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  process.env.OPENCLAW_HOME = directory;
  await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
  const imp = (file) => import(pathToFileURL(path.join(runtimeRoot, file)).href);
  const registry = await imp("dist/secret-redaction-registry-b2B9lcfy.mjs");
  const registryJournal = { before: modelEncode(registry.t()), registrations: [] };
  if (registryJournal.before.revision !== 0 || registryJournal.before.values.length !== 0) {
    throw Error("A fresh error case must start with the actual empty process registry");
  }
  for (const secret of input.registeredSecrets ?? []) {
    const before = modelEncode(registry.t()); registry.s(secret);
    registryJournal.registrations.push({ secret, before, after: modelEncode(registry.t()) });
  }
  const { t: formatErrorMessage } = await imp("dist/errors-DlCDP-e5.mjs");
  const error = fixtureError(input.error);
  const raw = { kind: "model-tool-error", pid: process.pid, ppid: process.ppid,
    request, runtime, config, registry: registryJournal, error: actualError(error),
    formatter: formatErrorMessage(error), requests: [], invocations: [] };
  const fail = (tool, query) => {
    const thrown = error;
    raw.requests.push({ tool, query: modelEncode(query), thrownErrorIsOriginal: thrown === error,
      error: actualError(thrown) });
    throw thrown;
  };
  await imp("dist/tools.runtime.js");
  const { m: registerSupplement } = await imp("dist/memory-state-BmtUbXjH.mjs");
  registerSupplement("wiki-demo", {
    get: async (query) => fail("get", query),
    search: async (query) => fail("search", query),
  });
  const { createMemoryGetTool, createMemorySearchTool } = await imp("dist/tools-DotaQGXh.mjs");
  const tools = [];
  for (const [name, factory, params] of [["get", createMemoryGetTool, { path: "topic", corpus: "wiki" }],
      ["search", createMemorySearchTool, { query: "topic", corpus: "wiki" }]]) {
    const tool = factory({ config, getConfig: () => config, agentId: "main" });
    if (!tool) throw Error("The genuine original memory tool was unavailable");
    const callId = `diagnostic-${name}`;
    const invocation = { name, callId, params: modelEncode(params), definition: modelEncode(tool) };
    const envelope = await tool.execute(callId, params);
    Object.assign(invocation, { envelope: modelEncode(envelope), decoded: decodeSearchToolEnvelope(envelope) });
    raw.invocations.push(invocation);
    tools.push({ name, envelope: modelEncode(envelope), decoded: decodeSearchToolEnvelope(envelope) });
  }
  registryJournal.after = modelEncode(registry.t());
  return { result: { provider: "none", formatter: raw.formatter, tools }, raw };
}
