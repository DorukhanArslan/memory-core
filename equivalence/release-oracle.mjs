// One official provider-none runtime case per fresh process. Fixture transport only.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const contextPath = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!contextPath) throw Error("Trusted release execution context required");
const context = JSON.parse(fs.readFileSync(contextPath, "utf8"));
const request = JSON.parse(fs.readFileSync(0, "utf8"));
if (!Array.isArray(request.cases) || request.cases.length !== 1) throw Error("Use one fresh release process per case");
if (context.providerMode !== "none") throw Error("Only provider-none release comparisons are supported");
const operations = {
  "index-lifecycle-runtime": ["index-lifecycle.mjs", "runIndexLifecycle"],
  "flush-trigger-runtime": ["flush-runtime.mjs", "runFlushRuntime"],
  "flush-execution-runtime": ["flush-execution.mjs", "runFlushExecution"],
};
const results = [];
for (const testCase of request.cases) {
  const caseHash = crypto.createHash("sha256").update(testCase.id).digest("hex");
  const evidenceDirectory = path.join(context.evidenceDirectory, caseHash);
  fs.mkdirSync(evidenceDirectory, { recursive: true });
  try {
    const binding = operations[testCase.operation];
    if (!Object.hasOwn(operations, testCase.operation)) throw Error("Unsupported release oracle operation");
    const adapter = await import(new URL(binding[0], import.meta.url).href);
    const result = await adapter[binding[1]](testCase.input, {
      ...context.runtime, evidenceDirectory,
      stateDirectory: context.stateDirectory, configPath: context.configPath,
    });
    results.push({ id: testCase.id, ok: true, result });
  } catch (error) {
    results.push({ id: testCase.id, ok: false, error: { type: error.name, message: error.message } });
  }
}
process.stdout.write(JSON.stringify({kind: "official-release-runtime-comparison", results, sources: []}) + "\n");
