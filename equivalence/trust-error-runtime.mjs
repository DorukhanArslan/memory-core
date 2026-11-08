// Uncredited diagnostics over genuine release error and whole-tool owners.
// This adapter transports literal credentials and controlled provider failures;
// it implements no redaction or error-formatting algorithm.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";

const request = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const { input, runtimeRoot, fixtureDirectory } = request;
if (![runtimeRoot, fixtureDirectory].every((value) => typeof value === "string" && path.isAbsolute(value))) {
  throw Error("Authenticated absolute runtime and owned fixture directories required");
}
await fs.mkdir(fixtureDirectory, { recursive: true });
const workspace = path.join(fixtureDirectory, "workspace");
await fs.mkdir(workspace);
const config = {
  agents: { defaults: { workspace } },
  logging: { level: "silent", consoleLevel: "silent",
    ...(input.patterns ? { redactPatterns: input.patterns } : {}) },
  memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"] } },
};
process.env.OPENCLAW_STATE_DIR = path.join(fixtureDirectory, "state");
process.env.OPENCLAW_CONFIG_PATH = path.join(fixtureDirectory, "openclaw.json");
process.env.OPENCLAW_HOME = fixtureDirectory;
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
const imp = (name) => import(pathToFileURL(path.join(runtimeRoot, "dist", name)).href);
const { s: register } = await imp("secret-redaction-registry-b2B9lcfy.mjs");
for (const secret of input.registeredSecrets ?? []) register(secret);
const { t: format } = await imp("errors-DlCDP-e5.mjs");
function fixtureError(spec) {
  if (typeof spec === "string") return spec;
  const error = new Error(spec.message);
  if (spec.code !== undefined) error.code = spec.code;
  if (spec.cause !== undefined) error.cause = fixtureError(spec.cause);
  return error;
}
const error = fixtureError(input.error);
const raw = { formatter: format(error), nativeEnvelopes: [], requests: [] };
await imp("tools.runtime.js");
const { m: registerSupplement } = await imp("memory-state-BmtUbXjH.mjs");
registerSupplement("wiki-demo", {
  search: async (query) => { raw.requests.push({ tool: "search", query }); throw error; },
  get: async (query) => { raw.requests.push({ tool: "get", query }); throw error; },
});
const { createMemoryGetTool, createMemorySearchTool } = await imp("tools-DotaQGXh.mjs");
const result = { formatter: raw.formatter };
for (const [name, factory, params] of [
  ["get", createMemoryGetTool, { path: "topic", corpus: "wiki" }],
  ["search", createMemorySearchTool, { query: "topic", corpus: "wiki" }],
]) {
  const tool = factory({ config, getConfig: () => config, agentId: "main" });
  if (!tool) throw Error("The genuine memory tool was unavailable");
  const envelope = await tool.execute(`diagnostic-${name}`, params);
  raw.nativeEnvelopes.push({ tool: name, envelope });
  result[name] = decodeSearchToolEnvelope(envelope);
}
process.stdout.write(JSON.stringify({ covers: [], result, raw }) + "\n");
