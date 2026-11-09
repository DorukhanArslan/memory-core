// Thin ordinary caller over one unchanged authenticated TypeScript graph.
// The oracle's existing source loader owns all resolution and byte authority.
import path from "node:path";

const frames = [];
export const readRedactionPolicySourceFrames = () => frames;

export async function runRedactionPolicySource(input, source) {
  if (input.kind !== "source-policy" || !Array.isArray(input.registeredSecrets) ||
      !Array.isArray(input.declaredRegistryValues) || process.env.VITEST || process.env.NODE_ENV) {
    throw Error("The source policy case requires a fresh ordinary synthetic-only process");
  }
  const [redact, internal, registry, logger, transcript, configRegex] = await Promise.all([
    source("src/logging/redact.ts"), source("src/logging/redact-internal-state.ts"),
    source("src/logging/secret-redaction-registry.ts"), source("src/logging/logger.ts"),
    source("src/agents/transcript-redact.ts"), source("src/security/config-regex.ts"),
  ]);
  const before = registry.captureSecretRedactionRegistrySnapshot();
  if (before.revision !== 0 || before.values.length !== 0) {
    throw Error("The source policy registry was not initially empty");
  }
  const configPath = process.env.OPENCLAW_CONFIG_PATH;
  if (typeof configPath !== "string" || !path.isAbsolute(configPath)) {
    throw Error("The source policy needs its owned host configuration");
  }
  const base = { level: "silent", consoleLevel: "silent", file: path.join(path.dirname(configPath), "native.log"),
    ...(input.patterns ? { redactPatterns: input.patterns } : {}) };
  const logging = input.fullContext ? internal.fullContextToolPayloadRedactionState.mark(base) : base;
  logger.applyLoggingConfig(logging);
  try {
    for (const secret of input.registeredSecrets) registry.registerSecretValueForRedaction(secret);
    const after = registry.captureSecretRedactionRegistrySnapshot();
    const allowed = new Set(input.declaredRegistryValues);
    if (after.values.some((value) => !allowed.has(value))) {
      throw Error("The source policy registry contains an undeclared value");
    }
    const calls = [];
    const call = (name, invoke) => {
      const result = invoke();
      calls.push({ name, result });
      return result;
    };
    const result = {
      explicitSensitiveText: call("redactSensitiveText", () => redact.redactSensitiveText(input.text, { mode: input.mode ?? "tools", ...(input.patterns ? { patterns: input.patterns } : {}) })),
      toolText: call("redactToolPayloadText", () => redact.redactToolPayloadText(input.text)),
      modelText: call("redactModelVisibleToolPayloadText", () => redact.redactModelVisibleToolPayloadText(input.text)),
      structuredTool: call("redactSecrets", () => redact.redactSecrets(input.value)),
      structuredModel: call("redactModelVisibleSecrets", () => redact.redactModelVisibleSecrets(input.value)),
      transcript: call("redactTranscriptMessage", () => transcript.redactTranscriptMessage(input.message, { logging })),
      policy: call("captureModelVisibleRedactionPolicy", () => internal.captureModelVisibleRedactionPolicy(logging)),
      ...(input.directRegex ? { directCompiler: call("compileConfigRegex", () => {
        const compiled = configRegex.compileConfigRegex(input.directRegex.source, input.directRegex.flags);
        return compiled && { pattern: compiled.pattern, flags: compiled.flags, reason: compiled.reason,
          accepted: Boolean(compiled.regex) };
      }) } : {}),
    };
    const output = { provider: "none", result, registry: { before, after } };
    frames.push({ input, registry: { before, after }, calls, output,
      logging: { json: { ...logging }, marked: internal.fullContextToolPayloadRedactionState.isMarked(logging) } });
    return output;
  } finally {
    logger.resetLogger();
  }
}
