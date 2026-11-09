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
  "promotion-ranking-runtime": ["promotion-ranking-runtime.mjs", "runPromotionRankingRuntime"],
  "promotion-apply-reconcile-runtime": ["promotion-apply-runtime.mjs", "runPromotionApplyRuntime"],
};
function sameGetReadRaceLiteral(actual, expected) {
  if (actual === expected) return true;
  if (Array.isArray(expected)) return Array.isArray(actual) && actual.length === expected.length &&
    expected.every((value, index) => sameGetReadRaceLiteral(actual[index], value));
  if (expected === null || typeof expected !== "object" || actual === null ||
      typeof actual !== "object" || Array.isArray(actual)) return false;
  const keys = Object.keys(expected).sort();
  return JSON.stringify(Object.keys(actual).sort()) === JSON.stringify(keys) &&
    keys.every((key) => sameGetReadRaceLiteral(actual[key], expected[key]));
}
const reviewedGetReadRaceInput = {
  kind: "tool", normalizeFixturePaths: true, observeFilesystem: true,
  readRace: { kind: "owned-leaf-to-symlink", hook: "afterPreOpenLstat" },
  files: { "memory/race.md": "Original admitted bytes.\n" },
  outsideFiles: { "secret.md": "Owned outside sentinel must not be read.\n" },
  steps: [{ params: { path: "memory/race.md" } }],
};
const results = [];
for (const testCase of request.cases) {
  const caseHash = crypto.createHash("sha256").update(testCase.id).digest("hex");
  const evidenceDirectory = path.join(context.evidenceDirectory, caseHash);
  fs.mkdirSync(evidenceDirectory, { recursive: true });
  try {
    const entryProfile = context.entryProvenanceProfile;
    const entryKinds = { "entry-memory-publication-runtime": "published-memory",
      "entry-session-publication-runtime": "session-projection", "entry-provider-preparation-runtime": "prepared-provider" };
    if ((entryProfile !== undefined) !== Object.hasOwn(entryKinds, testCase.operation) ||
        entryProfile !== undefined && (entryProfile.operation !== testCase.operation ||
          entryProfile.inputKind !== entryKinds[testCase.operation] || testCase.input?.kind !== entryProfile.inputKind)) {
      throw Error("The entry capability cannot execute another operation or input contract before import");
    }
    const atomicProfile = context.atomicPublicationProfile;
    const atomicKinds = { "atomic-commit-runtime": "commit", "atomic-append-runtime": "append", "atomic-bootstrap-runtime": "bootstrap" };
    if ((atomicProfile !== undefined) !== Object.hasOwn(atomicKinds, testCase.operation) ||
        atomicProfile !== undefined && (atomicProfile.operation !== testCase.operation ||
          atomicProfile.inputKind !== atomicKinds[testCase.operation] || testCase.input?.kind !== atomicProfile.inputKind)) {
      throw Error("The atomic capability cannot execute another operation or input contract before import");
    }
    if (atomicProfile !== undefined) {
      const binding = context.atomicCaseBinding;
      if (!binding || binding.id !== testCase.id || binding.operation !== testCase.operation ||
          typeof binding.inputJson !== "string" ||
          crypto.createHash("sha256").update(binding.inputJson).digest("hex") !== binding.inputSha256 ||
          !sameGetReadRaceLiteral(testCase.input, JSON.parse(binding.inputJson))) {
        throw Error("The atomic capability requires its complete literal return-checkpoint input before import");
      }
    }
    const modelKinds = { "model-session-runtime": "model-session", "model-tool-result-runtime": "model-helper",
      "trust-worker-runtime": null, "model-tool-error-runtime": null };
    const modelAuthority = context.approvedNodeRuntime !== undefined && context.entryProvenanceProfile === undefined &&
      context.atomicPublicationProfile === undefined && context.memoryBudgetProfile === undefined &&
      context.promotionRankingProfile === undefined && context.promotionApplyProfile === undefined;
    if (modelAuthority !== Object.hasOwn(modelKinds, testCase.operation) ||
        modelAuthority && modelKinds[testCase.operation] !== null && testCase.input?.kind !== modelKinds[testCase.operation]) {
      throw Error("The model binary capability cannot execute another operation or input contract before import");
    }
    const mixedTurnSource = (context.approvedReferenceSources ?? []).length !== 0;
    if (mixedTurnSource !== (testCase.operation === "turn-trust-runtime") ||
        mixedTurnSource && testCase.input?.kind !== "turn-trust") {
      throw Error("The single-source turn capability cannot execute another operation or input contract before import");
    }
    if (((context.fixtureSourceCaptures ?? []).length !== 0) !== (testCase.operation === "flush-execution-runtime")) {
      throw Error("The fixture source capture capability cannot execute another operation before import");
    }
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
    const promotionProfile = context.promotionRankingProfile;
    if ((promotionProfile !== undefined) !== (testCase.operation === "promotion-ranking-runtime") ||
        promotionProfile !== undefined && (promotionProfile.operation !== testCase.operation ||
          promotionProfile.inputKind !== "promotion-ranking" || testCase.input?.kind !== promotionProfile.inputKind)) {
      throw Error("The independent ranking capability cannot execute another operation or input contract before import");
    }
    const promotionApplyProfile = context.promotionApplyProfile;
    if ((promotionApplyProfile !== undefined) !== (testCase.operation === "promotion-apply-reconcile-runtime")) {
      throw Error("The apply capability cannot execute a different original caller before import");
    }
    if (promotionApplyProfile !== undefined) {
      const stable = value => Array.isArray(value) ? value.map(stable) : value !== null && typeof value === "object"
        ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
      const wire = JSON.stringify(stable({ id: testCase.id, operation: testCase.operation, input: testCase.input }));
      if (promotionApplyProfile.operation !== testCase.operation ||
          promotionApplyProfile.inputKind !== testCase.input?.kind ||
          crypto.createHash("sha256").update(wire).digest("hex") !== promotionApplyProfile.caseWireSha256) {
        throw Error("The apply capability cannot execute a changed literal case before import");
      }
    }
    const binding = operations[testCase.operation];
    if (!Object.hasOwn(operations, testCase.operation)) throw Error("Unsupported release oracle operation");
    const getReadRaceProfile = context.getReadRaceProfile;
    const requestsReadRace = Object.hasOwn(testCase.input ?? {}, "readRace");
    if ((getReadRaceProfile !== undefined) !== requestsReadRace) {
      throw Error("The native read race requires its exact explicit whole-get capability before import");
    }
    if (getReadRaceProfile !== undefined && (testCase.operation !== "get-contract-runtime" ||
        testCase.id !== "storage-path-read-race-owned-leaf-to-symlink" ||
        !sameGetReadRaceLiteral(testCase.input, reviewedGetReadRaceInput))) {
      throw Error("The native read race capability is restricted to its exact whole-tool input");
    }
    const adapter = await import(new URL(binding[0], import.meta.url).href);
    const result = await adapter[binding[1]](testCase.input, {
      ...context.runtime, evidenceDirectory,
      stateDirectory: context.stateDirectory, configPath: context.configPath,
      approvedReferenceSources: context.approvedReferenceSources ?? [],
      getReadRaceProfile: context.getReadRaceProfile,
    });
    results.push({ id: testCase.id, ok: true, result });
  } catch (error) {
    results.push({ id: testCase.id, ok: false, error: { type: error.name, message: error.message } });
  }
}
await new Promise((resolve, reject) => process.stdout.write(
  JSON.stringify({kind: "official-release-runtime-comparison", results, sources: []}) + "\n", "utf8",
  (error) => error ? reject(error) : resolve()));
