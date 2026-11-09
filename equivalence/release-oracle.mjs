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
  "bootstrap-discovery-runtime": ["bootstrap-discovery-runtime.mjs", "runBootstrapDiscoveryRuntime"],
  "importance-project-runtime": ["importance-project-runtime.mjs", "runImportanceProjectRuntime"],
  "exact-path-runtime": ["exact-path-runtime.mjs", "runExactPathRuntime"],
  "index-lifecycle-runtime": ["index-lifecycle.mjs", "runIndexLifecycle"],
  "flush-trigger-runtime": ["flush-runtime.mjs", "runFlushRuntime"],
  "flush-execution-runtime": ["flush-execution.mjs", "runFlushExecution"],
  "search-contract-runtime": ["search-contract-runtime.mjs", "runSearchContractRuntime"],
  "search-contract-helper-runtime": ["search-contract-runtime.mjs", "runSearchContractHelperRuntime"],
  "get-contract-runtime": ["get-contract-runtime.mjs", "runGetContractRuntime"],
  "get-contract-helper-runtime": ["get-contract-runtime.mjs", "runGetContractHelperRuntime"],
  "deadline-partial-runtime": ["deadline-partial-runtime.mjs", "runDeadlinePartialRuntime"],
  "deadline-partial-get-runtime": ["deadline-partial-runtime.mjs", "runDeadlineGetRuntime"],
  "session-contract-runtime": ["session-contract-runtime.mjs", "runSessionContractRuntime"],
  "session-contract-helper-runtime": ["session-contract-runtime.mjs", "runSessionContractHelperRuntime"],
  "transcript-boundary-runtime": ["transcript-boundary-runtime.mjs", "runTranscriptBoundaryRuntime"],
  "durable-session-runtime": ["durable-session-runtime.mjs", "runDurableSessionRuntime"],
  "turn-trust-runtime": ["turn-trust-runtime.mjs", "runTurnTrustRuntime"],
  "workspace-isolation-runtime": ["workspace-isolation-runtime.mjs", "runWorkspaceIsolationRuntime"],
  "model-session-runtime": ["model-session-runtime.mjs", "runModelSessionRuntime"],
  "model-tool-result-runtime": ["model-tool-result-runtime.mjs", "runModelToolResultRuntime"],
  "trust-worker-runtime": ["trust-worker-profile-runtime.mjs", "runTrustWorkerRuntime"],
  "model-tool-error-runtime": ["model-tool-error-runtime.mjs", "runModelToolErrorRuntime"],
  "entry-memory-publication-runtime": ["entry-provenance-runtime.mjs", "runEntryMemoryPublicationRuntime"],
  "entry-session-publication-runtime": ["entry-provenance-runtime.mjs", "runEntrySessionPublicationRuntime"],
  "entry-provider-preparation-runtime": ["entry-provenance-runtime.mjs", "runEntryProviderPreparationRuntime"],
  "atomic-commit-runtime": ["atomic-publication-runtime.mjs", "runAtomicCommitRuntime"],
  "atomic-append-runtime": ["atomic-publication-runtime.mjs", "runAtomicAppendRuntime"],
  "atomic-bootstrap-runtime": ["atomic-publication-runtime.mjs", "runAtomicBootstrapRuntime"],
  "memory-budget-runtime": ["memory-budget-runtime.mjs", "runMemoryBudgetRuntime"],
  "memory-budget-apply-runtime": ["memory-budget-runtime.mjs", "runMemoryBudgetRuntime"],
};
const results = [];
for (const testCase of request.cases) {
  const caseHash = crypto.createHash("sha256").update(testCase.id).digest("hex");
  const evidenceDirectory = path.join(context.evidenceDirectory, caseHash);
  fs.mkdirSync(evidenceDirectory, { recursive: true });
  try {
    const bootstrapProfile = context.bootstrapDiscoveryProfile;
    if ((bootstrapProfile !== undefined) !== (testCase.operation === "bootstrap-discovery-runtime")) {
      throw Error("The bootstrap executable capability is restricted to its exact compiled caller before import");
    }
    if (bootstrapProfile !== undefined &&
        (bootstrapProfile.operation !== testCase.operation || testCase.input?.kind !== bootstrapProfile.inputKind)) {
      throw Error("A different operation or input kind cannot borrow the bootstrap caller before import");
    }
    const budgetProfile = context.memoryBudgetProfile;
    const budgetKinds = { "memory-budget-runtime": "memory-budget", "memory-budget-apply-runtime": "memory-budget-apply" };
    if ((budgetProfile !== undefined) !== Object.hasOwn(budgetKinds, testCase.operation)) {
      throw Error("The memory-budget executable capability is restricted to its exact compiled callers before import");
    }
    if (budgetProfile !== undefined && (budgetProfile.operation !== testCase.operation ||
        budgetProfile.inputKind !== budgetKinds[testCase.operation] || testCase.input?.kind !== budgetProfile.inputKind)) {
      throw Error("A different operation or input kind cannot borrow the memory-budget caller before import");
    }
    const binding = operations[testCase.operation];
    if (!Object.hasOwn(operations, testCase.operation)) throw Error("Unsupported release oracle operation");
    const adapter = await import(new URL(binding[0], import.meta.url).href);
    const result = await adapter[binding[1]](testCase.input, {
      ...context.runtime, evidenceDirectory,
      stateDirectory: context.stateDirectory, configPath: context.configPath,
      approvedReferenceSources: context.approvedReferenceSources ?? [],
    });
    results.push({ id: testCase.id, ok: true, result });
  } catch (error) {
    results.push({ id: testCase.id, ok: false, error: { type: error.name, message: error.message } });
  }
}
await new Promise((resolve, reject) => process.stdout.write(
  JSON.stringify({kind: "official-release-runtime-comparison", results, sources: []}) + "\n", "utf8",
  (error) => error ? reject(error) : resolve()));
