// Complete published helper values and real object-identity observations.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { modelEncode, modelMarkerState, modelRuntimeIdentity } from "./model-runtime-observation.mjs";

export async function runModelToolResultPhase(request) {
  const { input, runtimeRoot, directory } = request;
  if (Object.keys(request).sort().join() !== "directory,input,runtimeRoot" || input.kind !== "model-helper" ||
      ![directory, runtimeRoot].every((value) => typeof value === "string" && path.isAbsolute(value))) {
    throw Error("A helper observation requires an exact owned request");
  }
  await fs.mkdir(directory, { recursive: true });
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  process.env.OPENCLAW_HOME = directory; process.env.HOME = directory;
  const logging = { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log"),
    ...(Object.hasOwn(input, "patterns") ? { redactPatterns: input.patterns } : {}) };
  const cfg = { logging }; await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg), { flag: "wx" });
  const raw = { pid: process.pid, ppid: process.ppid, request: structuredClone(request), runtime: modelRuntimeIdentity(),
    config: cfg, registry: [], stages: [], result: {}, identity: {} };
  const imp = (file) => import(pathToFileURL(path.join(runtimeRoot, file)).href);
  const config = await imp("dist/plugin-sdk/config-runtime.js"); config.setRuntimeConfigSnapshot(cfg);
  try {
    const registry = await imp("dist/secret-redaction-registry-b2B9lcfy.mjs");
    const capture = (stage, secret) => raw.registry.push({ stage, ...(secret === undefined ? {} : { secret }), snapshot: modelEncode(registry.t()) });
    capture("initial");
    if (registry.t().revision !== 0 || registry.t().values.length) throw Error("A helper inherited a populated secret registry");
    for (const value of input.registeredSecrets ?? []) { registry.s(value); capture("literal-registration", value); }
    const { u: sanitize, l: sanitizeArgs } = await imp("dist/embedded-agent-tool-results-Bhhd5B_V.mjs");
    const redaction = await imp("dist/redact-BCoakatc.mjs");
    const { c: store } = await imp("dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs");
    const result = {}, identity = {};
    if (Object.hasOwn(input, "value")) {
      const prepared = sanitize(input.value); result.sanitized = prepared; result.arguments = sanitizeArgs(input.value);
      identity.sanitizedOutputReuse = sanitize(prepared) === prepared; identity.originalInputReuse = sanitize(input.value) === prepared;
      raw.stages.push({ stage: "whole-sanitize", input: modelEncode(input.value), output: modelEncode(prepared),
        arguments: modelEncode(result.arguments), identity: { ...identity }, policy: modelEncode(redaction.W(logging)) });
    }
    if (Object.hasOwn(input, "block")) {
      const prepared = redaction.o(input.block, logging); result.prepared = prepared;
      identity.preparedBlockReuse = redaction.o(prepared, logging) === prepared;
      raw.stages.push({ stage: "prepared-block", input: modelEncode(input.block), output: modelEncode(prepared),
        identity: { preparedBlockReuse: identity.preparedBlockReuse }, markers: modelMarkerState({ content: [prepared] }, redaction, logging),
        policy: modelEncode(redaction.W(logging)) });
      for (const value of input.laterRegisteredSecrets ?? []) { registry.s(value); capture("later-registration", value); }
      if (Object.hasOwn(input, "replacePreparedText")) prepared.text = input.replacePreparedText;
      const message = { ...input.message, content: [prepared] };
      raw.storageRequest = { message: modelEncode(message), config: { logging },
        markers: modelMarkerState(message, redaction, logging), policy: modelEncode(redaction.W(logging)) };
      const persisted = store(message, { config: { logging } }); result.stored = persisted;
      identity.storageMessageReuse = persisted === message;
      identity.storageBlockPrepared = redaction.U(persisted.content[0], persisted.content[0].text, logging);
      raw.stages.push({ stage: "storage-return", output: modelEncode(persisted),
        markers: modelMarkerState(persisted, redaction, logging), policy: modelEncode(redaction.W(logging)),
        identity: { storageMessageReuse: identity.storageMessageReuse, storageBlockPrepared: identity.storageBlockPrepared } });
    }
    capture("final"); raw.result = modelEncode(result); raw.identity = { ...identity };
    return { result: { provider: "none", result, identity }, raw };
  } finally { config.clearRuntimeConfigSnapshot(); }
}
