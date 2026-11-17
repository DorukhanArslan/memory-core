// Trusted process/worker bootstrap. No memory algorithm is supplied here.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { Console } from "node:console";
import { registerHooks } from "node:module";
import { fileURLToPath } from "node:url";
import { isMainThread, threadId } from "node:worker_threads";

const hash = (data) => crypto.createHash("sha256").update(data).digest("hex");
const contextPath = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!contextPath || !path.isAbsolute(contextPath)) throw Error("Trusted release execution context required");
const rawContext = fs.readFileSync(contextPath);
if (rawContext.byteLength > 64 * 1024 * 1024) throw Error("Release execution context is excessive");
const context = JSON.parse(rawContext);
const embeddingMode = context.embeddingCacheProfile !== undefined;
const promptMode = context.promptRuntimeContextProfile !== undefined;
if (context.dreamLightProfile !== undefined) {
  const profile = context.dreamLightProfile;
  if (!profile || Object.keys(profile).sort().join() !== "caseId,inputSha256,nodeRuntime,operation" ||
      profile.operation !== "dream-light-runtime" || !profile.caseId?.startsWith("dream-light-") ||
      !/^[a-f0-9]{64}$/.test(profile.inputSha256) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      Object.keys(context).some(k => k.endsWith("Profile") && k !== "dreamLightProfile") ||
      (context.fixtureSourceCaptures ?? []).length || (context.approvedReferenceSources ?? []).length) {
    throw Error("Unapproved light dreaming process authority");
  }
}
const historyMode = context.promptHistoryRepairProfile !== undefined;
const expectedProviderMode = embeddingMode ? "deterministic-embedding-fixture" : "none";
if (context.schemaVersion !== 1 || context.providerMode !== expectedProviderMode || context.fetchPolicy !== "deny") {
  throw Error("Unsupported release execution policy");
}
if (embeddingMode &&
    ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
     "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile",
     "forgetLineageProfile", "forgetBoundariesProfile", "recallSignalsProfile", "sessionResetBoundariesProfile", "promptRuntimeContextProfile", "promptHistoryRepairProfile"].some(key => context[key] !== undefined)) {
  throw Error("Embedding cache cannot borrow another compiled, model, source or hook capability");
}
if (!embeddingMode && context.embeddingFixtureSourceCaptures !== undefined) {
  throw Error("An embedding provider source capture requires its own exact manager capability");
}
if (context.recallSignalsProfile !== undefined &&
    ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
     "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile",
     "forgetLineageProfile", "forgetBoundariesProfile"].some(key => context[key] !== undefined)) {
  throw Error("Recall signals cannot borrow another compiled, model, source or hook capability");
}
if (context.entryProvenanceProfile !== undefined) {
  const profile = context.entryProvenanceProfile;
  const kinds = { "entry-memory-publication-runtime": "published-memory",
    "entry-session-publication-runtime": "session-projection", "entry-provider-preparation-runtime": "prepared-provider" };
  if (!profile || Object.keys(profile).sort().join() !== "inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-entry-provenance-profile" || !Object.hasOwn(kinds, profile.operation) ||
      profile.inputKind !== kinds[profile.operation] || context.bootstrapDiscoveryProfile !== undefined ||
      context.memoryBudgetProfile !== undefined || context.getReadRaceProfile !== undefined ||
      context.promotionRankingProfile !== undefined || context.promotionApplyProfile !== undefined ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved compiled entry provenance profile capability");
  }
}
if (context.atomicPublicationProfile !== undefined) {
  const profile = context.atomicPublicationProfile;
  const kinds = { "atomic-commit-runtime": "commit", "atomic-append-runtime": "append", "atomic-bootstrap-runtime": "bootstrap" };
  if (!profile || Object.keys(profile).sort().join() !== "inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-atomic-publication-profile" || !Object.hasOwn(kinds, profile.operation) ||
      profile.inputKind !== kinds[profile.operation] ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      !context.atomicCaseBinding || context.atomicCaseBinding.operation !== profile.operation ||
      context.entryProvenanceProfile !== undefined || context.bootstrapDiscoveryProfile !== undefined ||
      context.memoryBudgetProfile !== undefined || context.getReadRaceProfile !== undefined ||
      context.promotionRankingProfile !== undefined || context.promotionApplyProfile !== undefined ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved atomic original-owner profile capability");
  }
}
const bootstrapProfile = context.bootstrapDiscoveryProfile;
let bootstrapRuntime;
if (bootstrapProfile !== undefined) {
  const approved = { nodeVersion: "v24.16.0", icuVersion: "78.3", unicodeVersion: "17.0",
    sha256: "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd" };
  const identity = bootstrapProfile?.nodeRuntime;
  if (JSON.stringify(Object.keys(bootstrapProfile ?? {}).sort()) !== JSON.stringify(["inputKind", "kind", "nodeRuntime", "operation"]) ||
      bootstrapProfile.kind !== "approved-bootstrap-discovery-profile" || bootstrapProfile.operation !== "bootstrap-discovery-runtime" ||
      bootstrapProfile.inputKind !== "workspace-bootstrap" || !identity ||
      context.approvedNodeRuntime !== undefined || context.entryProvenanceProfile !== undefined ||
      context.atomicPublicationProfile !== undefined || context.atomicCaseBinding !== undefined ||
      context.memoryBudgetProfile !== undefined || context.getReadRaceProfile !== undefined ||
      context.promotionRankingProfile !== undefined || context.promotionApplyProfile !== undefined ||
      JSON.stringify(Object.keys(identity).sort()) !== JSON.stringify(["execPath", "icuVersion", "nodeVersion", "sha256", "unicodeVersion"]) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved compiled bootstrap execution scope");
  }
  bootstrapRuntime = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
    icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode,
    sha256: hash(fs.readFileSync(process.execPath)) };
  if (Object.entries(approved).some(([key, value]) => identity[key] !== value) ||
      Object.entries(bootstrapRuntime).some(([key, value]) => identity[key] !== value)) throw Error("Unapproved bootstrap Node/ICU/Unicode executable");
}
if (context.memoryBudgetProfile !== undefined) {
  const profile = context.memoryBudgetProfile;
  const kinds = { "memory-budget-runtime": "memory-budget", "memory-budget-apply-runtime": "memory-budget-apply" };
  if (!profile || Object.keys(profile).sort().join() !== "inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-memory-budget-profile" || !Object.hasOwn(kinds, profile.operation) ||
      profile.inputKind !== kinds[profile.operation] ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      context.entryProvenanceProfile !== undefined || context.atomicPublicationProfile !== undefined ||
      context.atomicCaseBinding !== undefined || context.bootstrapDiscoveryProfile !== undefined ||
      context.getReadRaceProfile !== undefined || context.promotionRankingProfile !== undefined || context.promotionApplyProfile !== undefined ||
      (context.approvedReferenceSources ?? []).length ||
      (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved compiled memory-budget profile capability");
  }
}
if (context.getReadRaceProfile !== undefined) {
  const value = context.getReadRaceProfile;
  if (!value || Object.keys(value).sort().join() !== "hook,inputKind,kind,module,mutation,operation,sha256" ||
      value.kind !== "approved-get-read-race-profile" || value.operation !== "get-contract-runtime" ||
      value.inputKind !== "tool" || value.hook !== "afterPreOpenLstat" || value.mutation !== "owned-leaf-to-symlink" ||
      value.module !== "node_modules/@openclaw/fs-safe/dist/test-hooks.js" ||
      value.sha256 !== "207753c214f21d77c7cc82b947f24705c937009a73057ddb08a8ef058334e273" ||
      !isMainThread || context.entryProvenanceProfile !== undefined || context.approvedNodeRuntime !== undefined ||
      context.atomicPublicationProfile !== undefined || context.atomicCaseBinding !== undefined ||
      context.bootstrapDiscoveryProfile !== undefined || context.memoryBudgetProfile !== undefined ||
      context.promotionRankingProfile !== undefined || context.promotionApplyProfile !== undefined ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved get read race hook capability");
  }
}
if (context.promotionRankingProfile !== undefined) {
  const profile = context.promotionRankingProfile;
  if (!profile || Object.keys(profile).sort().join() !== "inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-promotion-ranking-profile" || profile.operation !== "promotion-ranking-runtime" ||
      profile.inputKind !== "promotion-ranking" || context.entryProvenanceProfile !== undefined ||
      context.atomicPublicationProfile !== undefined || context.atomicCaseBinding !== undefined ||
      context.bootstrapDiscoveryProfile !== undefined || context.memoryBudgetProfile !== undefined ||
      context.getReadRaceProfile !== undefined || context.promotionApplyProfile !== undefined ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved compiled promotion ranking profile capability");
  }
}
if (context.promotionApplyProfile !== undefined) {
  const profile = context.promotionApplyProfile;
  if (!profile || Object.keys(profile).sort().join() !== "caseWireSha256,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-promotion-apply-profile" || profile.operation !== "promotion-apply-reconcile-runtime" ||
      profile.inputKind !== "promotion-apply-reconcile" ||
      profile.caseWireSha256 !== "2c2bcfc960b729ae64acd3878f1f5a3dcd847fe9dabf8dd4b7e12bc277f8379a" ||
      context.entryProvenanceProfile !== undefined || context.atomicPublicationProfile !== undefined ||
      context.atomicCaseBinding !== undefined || context.bootstrapDiscoveryProfile !== undefined ||
      context.memoryBudgetProfile !== undefined || context.getReadRaceProfile !== undefined ||
      context.promotionRankingProfile !== undefined ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved separate compiled promotion apply capability");
  }
}
if (context.forgetLineageProfile !== undefined) {
  const profile = context.forgetLineageProfile;
  const bindings = profile?.caseBindings;
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-forget-lineage-profile" || profile.operation !== "forget-lineage-runtime" ||
      profile.inputKind !== "forget-lineage-tombstones" || !bindings || Object.keys(bindings).length !== 6 ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !==
        "f969f52453664edcc52c4a8f4ac25f47817cc5b02f786e602348c66939c8209d" ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
       "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile", "forgetBoundariesProfile"]
        .some(key => context[key] !== undefined) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent six-case forget/lineage capability");
  }
}
if (context.forgetBoundariesProfile !== undefined) {
  const profile = context.forgetBoundariesProfile;
  const bindings = profile?.caseBindings;
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-forget-boundaries-profile" || profile.operation !== "forget-boundaries-runtime" ||
      profile.inputKind !== "forget-lineage-tombstones" || !bindings || Object.keys(bindings).length !== 1 ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !==
        "939914d3a8a64c7a128cb634c67773ffe8e37b3851c48549458b084ba05fbc6c" ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
       "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile", "forgetLineageProfile"]
        .some(key => context[key] !== undefined) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent durable forget/admission capability");
  }
}
if (context.recallSignalsProfile !== undefined) {
  const profile = context.recallSignalsProfile;
  const bindings = profile?.caseBindings;
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-recall-signals-profile" || profile.operation !== "recall-signals-runtime" ||
      profile.inputKind !== "recall-signals" || !bindings || Object.keys(bindings).length !== 6 ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !==
        "9f193bac51d7e944796148d1f0119083217084ace56d4da83dc16708491bec5e" ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent complete recall-signals capability");
  }
}
if (context.sessionResetBoundariesProfile !== undefined) {
  const profile = context.sessionResetBoundariesProfile, bindings = profile?.caseBindings;
  const approvedBindingsSha256 = "6d2d4043125f71ae236fe4482af8e2aec408d9a63b0ea00de201d315daa500ae";
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-session-reset-boundaries-profile" || profile.operation !== "session-reset-boundaries-runtime" ||
      profile.inputKind !== "session-reset-boundaries" || !bindings || Object.keys(bindings).length !== 7 ||
      !/^[0-9a-f]{64}$/.test(approvedBindingsSha256) ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !== approvedBindingsSha256 ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
       "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile",
       "forgetLineageProfile", "forgetBoundariesProfile", "recallSignalsProfile", "embeddingCacheProfile"]
        .some(key => context[key] !== undefined) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent complete session reset boundary capability");
  }
}
if ((context.promptRuntimeContextProfile !== undefined) !==
    (context.promptRuntimeContextHostTimezone !== undefined)) {
  throw Error("A prompt host timezone requires its distinct complete composition capability");
}
if (context.promptRuntimeContextProfile !== undefined) {
  const profile = context.promptRuntimeContextProfile, bindings = profile?.caseBindings;
  const approvedBindingsSha256 = "1a245537eb8ca6f96d8987756ae607a24f6fef010acc2a26f803d18f6358fe22";
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-prompt-runtime-context-profile" || profile.operation !== "prompt-runtime-context-runtime" ||
      context.promptRuntimeContextHostTimezone !== "America/Los_Angeles" ||
      process.env.TZ !== context.promptRuntimeContextHostTimezone ||
      profile.inputKind !== "prompt-runtime-context" || !bindings || Object.keys(bindings).length !== 10 ||
      !/^[0-9a-f]{64}$/.test(approvedBindingsSha256) ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !== approvedBindingsSha256 ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
       "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile",
       "forgetLineageProfile", "forgetBoundariesProfile", "recallSignalsProfile", "embeddingCacheProfile", "sessionResetBoundariesProfile", "promptHistoryRepairProfile"]
        .some(key => context[key] !== undefined) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent complete prompt runtime context capability");
  }
}
if ((context.promptHistoryRepairProfile !== undefined) !==
    (context.promptHistoryRepairHostTimezone !== undefined)) {
  throw Error("A history host timezone requires its distinct complete repair capability");
}
if (context.promptHistoryRepairProfile !== undefined) {
  const profile = context.promptHistoryRepairProfile, bindings = profile?.caseBindings;
  const approvedBindingsSha256 = "656ca2012bb7f8f53a9f44109d93153a79ce910c5afc33a56fdebad78881ebb2";
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,driverScopeSha256,inputKind,kind,nodeRuntime,operation,policySha256" ||
      profile.kind !== "approved-prompt-history-repair-profile" || profile.operation !== "prompt-history-repair-runtime" ||
      context.promptHistoryRepairHostTimezone !== "UTC" ||
      process.env.TZ !== context.promptHistoryRepairHostTimezone ||
      profile.policySha256 !== "354c67f4dc0ca90bb6e6d989d5a0a7ceb6b0404465891a04104dadac6056621e" ||
      profile.driverScopeSha256 !== "2e3ce984de0537c4316b10a912eb3a8ce1e25556ad10c21b28ea5de4d23f5f16" ||
      profile.inputKind !== "prompt-history-repair" || !bindings || Object.keys(bindings).length !== 8 ||
      !/^[0-9a-f]{64}$/.test(approvedBindingsSha256) ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !== approvedBindingsSha256 ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      ["entryProvenanceProfile", "atomicPublicationProfile", "atomicCaseBinding", "bootstrapDiscoveryProfile",
       "memoryBudgetProfile", "getReadRaceProfile", "promotionRankingProfile", "promotionApplyProfile",
       "forgetLineageProfile", "forgetBoundariesProfile", "recallSignalsProfile", "embeddingCacheProfile", "sessionResetBoundariesProfile", "promptRuntimeContextProfile"]
        .some(key => context[key] !== undefined) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent complete prompt history repair capability");
  }
}
if (embeddingMode) {
  const profile = context.embeddingCacheProfile, bindings = profile?.caseBindings;
  const approvedBindingsSha256 = "3856a25129df0b84e9b49906b8f08b462290bd9ddd1720ddfb2ca6f5429d1790";
  if (!profile || Object.keys(profile).sort().join() !== "caseBindings,caseId,inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-embedding-cache-lifecycle-profile" || profile.operation !== "embed-cache-lifecycle-runtime" ||
      profile.inputKind !== "embedding-cache-lifecycle" || !bindings || Object.keys(bindings).length !== 8 ||
      !/^[0-9a-f]{64}$/.test(approvedBindingsSha256) ||
      hash(JSON.stringify(Object.fromEntries(Object.keys(bindings).sort().map(key => [key, bindings[key]])))) !== approvedBindingsSha256 ||
      !Object.hasOwn(bindings, profile.caseId) ||
      JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved independent complete embedding-cache manager capability");
  }
}
const permitted = new Map();
for (const entry of context.allowedLocal) {
  permitted.set(fs.realpathSync(entry.path), { kind: "oracle", path: fs.realpathSync(entry.path), sha256: entry.sha256 });
}
const sourceAuthorities = context.approvedReferenceSources ?? [];
if (!Array.isArray(sourceAuthorities) || sourceAuthorities.length > 1) throw Error("Unsupported reference source authority");
for (const entry of sourceAuthorities) {
  if (entry.kind !== "pinned-reference-source" || entry.referenceCommit !== "bcfc88812a35243893585dbeca87ca41b48272ca" ||
      entry.relativePath !== "src/agents/embedded-agent-runner/run/turn-taint-state.ts" ||
      entry.sha256 !== "7fd28e4064c555256feeaace2dbabb8b08d31ce1e0d7baaf1a1d7b20380723fe" ||
      entry.export !== "createAgentTurnTaintState" || entry.zeroRuntimeDependencies !== true ||
      !path.isAbsolute(entry.checkout) || entry.path !== path.join(entry.checkout, entry.relativePath) ||
      fs.realpathSync(entry.path) !== entry.path || permitted.has(entry.path)) throw Error("Unapproved reference source import");
  permitted.set(entry.path, { kind: "reference-source", path: entry.path, relativePath: entry.relativePath,
    sha256: entry.sha256, referenceCommit: entry.referenceCommit });
}
for (const entry of context.runtime.packages) {
  const directory = fs.realpathSync(entry.directory);
  for (const file of entry.files) {
    const filename = path.resolve(directory, file.path);
    if (filename !== directory && !filename.startsWith(directory + path.sep)) throw Error("Invalid release artifact path");
    if (permitted.has(filename)) throw Error("Duplicate release artifact authority");
    permitted.set(filename, { kind: "release", package: entry.location, path: file.path, sha256: file.sha256 });
  }
}
const ownPath = fs.realpathSync(fileURLToPath(import.meta.url));
const own = permitted.get(ownPath);
if (!own || own.kind !== "oracle" || hash(fs.readFileSync(ownPath)) !== own.sha256) {
  throw Error("Unreviewed release preload");
}
const traceFile = path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`);
function trace(event) {
  if (fs.existsSync(traceFile) && fs.statSync(traceFile).size > 8 * 1024 * 1024) throw Error("Runtime trace limit exceeded");
  fs.appendFileSync(traceFile, JSON.stringify({ ...event, pid: process.pid, threadId }) + "\n", { mode: 0o600 });
}
let approvedNodeRuntime;
if (context.approvedNodeRuntime !== undefined) {
  const expected = context.approvedNodeRuntime;
  const required = { nodeVersion: "v24.16.0", icuVersion: "78.3", unicodeVersion: "17.0",
    sha256: "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd" };
  if (!expected || Object.keys(expected).sort().join() !== "execPath,icuVersion,nodeVersion,sha256,unicodeVersion" ||
      !path.isAbsolute(expected.execPath) || Object.entries(required).some(([key, value]) => expected[key] !== value)) {
    throw Error("Unapproved model boundary executable capability");
  }
  approvedNodeRuntime = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
    icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode, sha256: hash(fs.readFileSync(process.execPath)) };
  if (JSON.stringify(approvedNodeRuntime) !== JSON.stringify({ execPath: expected.execPath, ...required })) {
    throw Error("The actual process or worker changed the approved binary or Unicode engine");
  }
}
trace({ event: "bootstrap", isMainThread, ppid: process.ppid, contextSha256: hash(rawContext), preloadSha256: own.sha256,
        fetchDenied: true, providerMode: context.providerMode, ...(approvedNodeRuntime ? { runtime: approvedNodeRuntime } : {}),
        ...(context.entryProvenanceProfile ? { entryProfile: context.entryProvenanceProfile } : {}),
        ...(context.atomicPublicationProfile ? { atomicProfile: context.atomicPublicationProfile } : {}),
        ...(bootstrapProfile ? { runtime: bootstrapRuntime, bootstrapProfile } : {}),
        ...(context.memoryBudgetProfile ? { budgetProfile: context.memoryBudgetProfile } : {}),
        ...(context.getReadRaceProfile ? { getReadRaceProfile: context.getReadRaceProfile } : {}),
        ...(context.promotionRankingProfile ? { promotionProfile: context.promotionRankingProfile } : {}),
        ...(context.promotionApplyProfile ? { promotionApplyProfile: context.promotionApplyProfile } : {}),
        ...(context.forgetLineageProfile ? { forgetLineageProfile: context.forgetLineageProfile } : {}),
        ...(context.forgetBoundariesProfile ? { forgetBoundariesProfile: context.forgetBoundariesProfile } : {}),
        ...(context.dreamLightProfile ? {dreamLightProfile: context.dreamLightProfile} : {}),
        ...(context.recallSignalsProfile ? { recallSignalsProfile: context.recallSignalsProfile } : {}),
        ...(context.sessionResetBoundariesProfile ? { sessionResetBoundariesProfile: context.sessionResetBoundariesProfile } : {}),
        ...(context.promptRuntimeContextProfile ? { promptRuntimeContextProfile: context.promptRuntimeContextProfile,
          promptRuntimeContextHostTimezone: context.promptRuntimeContextHostTimezone } : {}),
        ...(context.promptHistoryRepairProfile ? { promptHistoryRepairProfile: context.promptHistoryRepairProfile,
          promptHistoryRepairHostTimezone: context.promptHistoryRepairHostTimezone } : {}),
        ...(embeddingMode ? { embeddingCacheProfile: context.embeddingCacheProfile } : {}) });
// Native workers can log directly while retiring after the result is ready.
// Reserve stdout for the runner's single process.stdout.write JSON envelope.
// This executes in every worker as well as the parent, before native imports.
const diagnostics = new Console({ stdout: process.stderr, stderr: process.stderr });
const diagnosticMethods = Object.fromEntries(["log", "info", "debug"].map(
  (method) => [method, diagnostics[method].bind(diagnostics)],
));
function routeConsoleDiagnostics() {
  for (const [method, implementation] of Object.entries(diagnosticMethods)) {
    if (console[method] === implementation) continue;
    Object.defineProperty(console, method, {
      configurable: false, writable: false, value: implementation,
    });
  }
}
routeConsoleDiagnostics();
Object.defineProperty(globalThis, "fetch", {
  configurable: false, writable: false,
  value: async function deniedRuntimeFetch() {
    trace({ event: "network-denied", code: "runtime-network-disabled" });
    throw Error(embeddingMode ? "Network requests are disabled in deterministic embedding fixture comparisons"
      : "Network requests are disabled in provider-none release comparisons");
  },
});
const captureArea = path.join(context.stateDirectory, "tmp", "plugin-captures");
const capturePattern = /^tmp\/plugin-captures\/[0-9a-f-]{36}\/captures\/openclaw-plugin-build-[A-Za-z0-9]{6}\/package-0\/node_modules\/equivalence\/flush-execution\.mjs$/;
const capturePolicies = context.fixtureSourceCaptures ?? [];
if (!Array.isArray(capturePolicies) || capturePolicies.length > 1) throw Error("Invalid fixture source capture policy");
const captureSource = capturePolicies[0];
if (captureSource && (captureSource.basename !== "flush-execution.mjs"
    || path.basename(captureSource.sourcePath) !== "flush-execution.mjs"
    || permitted.get(captureSource.sourcePath)?.kind !== "oracle"
    || permitted.get(captureSource.sourcePath)?.sha256 !== captureSource.sha256)) {
  throw Error("Fixture captures require the specific reviewed provider fixture");
}
const embeddingCapturePolicies = context.embeddingFixtureSourceCaptures ?? [];
if (!Array.isArray(embeddingCapturePolicies) ||
    embeddingCapturePolicies.length !== (embeddingMode ? 1 : 0)) throw Error("Invalid independent embedding source capture policy");
const embeddingCaptureSource = embeddingCapturePolicies[0];
if (embeddingCaptureSource) {
  const entry = embeddingCaptureSource;
  if (Object.keys(entry).sort().join() !== "capturePackage,manifestPath,manifestSha256,sha256,sourcePath" ||
      entry.capturePackage !== "embedding-cache-provider" || typeof entry.sourcePath !== "string" ||
      entry.sha256 !== "c692c352828b05c43991f7c96a95119f6e83244e46839d5207431885cbe7701e" ||
      entry.manifestSha256 !== "66ea471ac56d24949725e50fe60c53395bd6b478d1f65b9e6d725544e32b2873" ||
      path.basename(entry.sourcePath) !== "index.mjs" || path.basename(path.dirname(entry.sourcePath)) !== "embedding-cache-provider" ||
      entry.manifestPath !== path.join(path.dirname(entry.sourcePath), "openclaw.plugin.json") ||
      permitted.get(entry.sourcePath)?.kind !== "oracle" || permitted.get(entry.sourcePath)?.sha256 !== entry.sha256 ||
      permitted.get(entry.manifestPath)?.kind !== "oracle" || permitted.get(entry.manifestPath)?.sha256 !== entry.manifestSha256 ||
      fs.realpathSync(entry.sourcePath) !== entry.sourcePath || fs.realpathSync(entry.manifestPath) !== entry.manifestPath ||
      hash(fs.readFileSync(entry.manifestPath)) !== entry.manifestSha256) {
    throw Error("Embedding fixtures require their exact reviewed provider source and manifest");
  }
}
const embeddingCapturePattern = /^tmp\/plugin-captures\/[0-9a-f-]{36}\/captures\/openclaw-plugin-build-[A-Za-z0-9]{6}\/package-0\/node_modules\/embedding-cache-provider\/index\.mjs$/;
const promptCapturePolicies = context.promptFixtureSourceCaptures ?? [];
if (!Array.isArray(promptCapturePolicies) ||
    promptCapturePolicies.length !== (promptMode || historyMode ? 1 : 0)) throw Error("Invalid independent prompt source capture policy");
const promptCaptureSource = promptCapturePolicies[0];
if (promptCaptureSource) {
  const entry = promptCaptureSource;
  if (Object.keys(entry).sort().join() !== "capturePackage,manifestPath,manifestSha256,sha256,sourcePath" ||
      entry.capturePackage !== "prompt-runtime-provider" || typeof entry.sourcePath !== "string" ||
      entry.sha256 !== "30569e909a0efdd6a5162a85475935528f7c99394d37e891eb6ab777217d143f" ||
      entry.manifestSha256 !== "118098ca3ea9ec4c0b5e5977ddc2ea7a8e6e3541753c817b4c0ab4de10f666c5" ||
      path.basename(entry.sourcePath) !== "index.mjs" || path.basename(path.dirname(entry.sourcePath)) !== "prompt-runtime-provider" ||
      entry.manifestPath !== path.join(path.dirname(entry.sourcePath), "openclaw.plugin.json") ||
      permitted.get(entry.sourcePath)?.kind !== "oracle" || permitted.get(entry.sourcePath)?.sha256 !== entry.sha256 ||
      permitted.get(entry.manifestPath)?.kind !== "oracle" || permitted.get(entry.manifestPath)?.sha256 !== entry.manifestSha256 ||
      fs.realpathSync(entry.sourcePath) !== entry.sourcePath || fs.realpathSync(entry.manifestPath) !== entry.manifestPath ||
      hash(fs.readFileSync(entry.manifestPath)) !== entry.manifestSha256) {
    throw Error("Prompt fixtures require their exact reviewed provider source and manifest");
  }
}
const promptCapturePattern = /^tmp\/plugin-captures\/[0-9a-f-]{36}\/captures\/openclaw-plugin-build-[A-Za-z0-9]{6}\/package-0\/node_modules\/prompt-runtime-provider\/index\.mjs$/;
function isCapturePath(filename) {
  return filename === captureArea || filename.startsWith(captureArea + path.sep);
}
function rejectCapture(filename) {
  const relative = path.relative(context.stateDirectory, filename).replaceAll(path.sep, "/");
  trace({ event: "rejected", code: "unverified-fixture-source-capture",
    basename: path.basename(filename),
    ...(relative && relative !== ".." && !relative.startsWith("../") && !path.isAbsolute(relative)
      ? { ownedStatePath: relative } : {}),
  });
  throw Error("Fixture code requires an independent exact reviewed source capture");
}
function fixtureCaptureAuthority(filename) {
  const absolute = path.resolve(filename);
  const relative = path.relative(context.stateDirectory, absolute).replaceAll(path.sep, "/");
  if (!captureSource || !capturePattern.test(relative)) return rejectCapture(absolute);
  let cursor = context.stateDirectory;
  for (const component of relative.split("/").slice(0, -1)) {
    const directory = fs.lstatSync(cursor);
    if (!directory.isDirectory() || directory.isSymbolicLink()) return rejectCapture(absolute);
    cursor = path.join(cursor, component);
  }
  const parent = fs.lstatSync(path.dirname(absolute));
  const info = fs.lstatSync(absolute);
  if (!parent.isDirectory() || parent.isSymbolicLink() || !info.isFile()
      || info.isSymbolicLink() || info.nlink !== 1 || fs.realpathSync(absolute) !== absolute
      || info.size !== fs.statSync(captureSource.sourcePath).size) return rejectCapture(absolute);
  const raw = fs.readFileSync(absolute);
  if (hash(raw) !== captureSource.sha256) return rejectCapture(absolute);
  const proofRelative = `fixture-source-captures/${hash(Buffer.from(relative + "\0" + captureSource.sha256))}.mjs`;
  const proofDirectory = path.join(context.evidenceDirectory, "fixture-source-captures");
  fs.mkdirSync(proofDirectory, { recursive: true, mode: 0o700 });
  const proofParent = fs.lstatSync(proofDirectory);
  if (!proofParent.isDirectory() || proofParent.isSymbolicLink()
      || fs.realpathSync(proofDirectory) !== proofDirectory) return rejectCapture(absolute);
  const proof = path.join(context.evidenceDirectory, proofRelative);
  if (!fs.existsSync(proof)) fs.writeFileSync(proof, raw, { flag: "wx", mode: 0o600 });
  const proofInfo = fs.lstatSync(proof);
  if (!proofInfo.isFile() || proofInfo.isSymbolicLink() || proofInfo.nlink !== 1
      || hash(fs.readFileSync(proof)) !== captureSource.sha256) return rejectCapture(absolute);
  return { kind: "fixture-capture", path: captureSource.sourcePath, sourcePath: captureSource.sourcePath,
    capturePath: relative, proofPath: proofRelative, sha256: captureSource.sha256 };
}
function embeddingFixtureCaptureAuthority(filename) {
  const absolute = path.resolve(filename);
  const relative = path.relative(context.stateDirectory, absolute).replaceAll(path.sep, "/");
  if (!embeddingMode || !embeddingCaptureSource || !embeddingCapturePattern.test(relative)) return rejectCapture(absolute);
  let cursor = context.stateDirectory;
  for (const component of relative.split("/").slice(0, -1)) {
    const directory = fs.lstatSync(cursor);
    if (!directory.isDirectory() || directory.isSymbolicLink()) return rejectCapture(absolute);
    cursor = path.join(cursor, component);
  }
  const parent = fs.lstatSync(path.dirname(absolute)), info = fs.lstatSync(absolute);
  if (!parent.isDirectory() || parent.isSymbolicLink() || !info.isFile() || info.isSymbolicLink()
      || info.nlink !== 1 || fs.realpathSync(absolute) !== absolute
      || info.size !== fs.statSync(embeddingCaptureSource.sourcePath).size) return rejectCapture(absolute);
  const raw = fs.readFileSync(absolute);
  if (hash(raw) !== embeddingCaptureSource.sha256) return rejectCapture(absolute);
  const proofRelative = `embedding-fixture-source-captures/${hash(Buffer.from(relative + "\0" + embeddingCaptureSource.sha256))}.mjs`;
  const proofDirectory = path.join(context.evidenceDirectory, "embedding-fixture-source-captures");
  fs.mkdirSync(proofDirectory, { recursive: true, mode: 0o700 });
  const proofParent = fs.lstatSync(proofDirectory);
  if (!proofParent.isDirectory() || proofParent.isSymbolicLink()
      || fs.realpathSync(proofDirectory) !== proofDirectory) return rejectCapture(absolute);
  const proof = path.join(context.evidenceDirectory, proofRelative);
  if (!fs.existsSync(proof)) fs.writeFileSync(proof, raw, { flag: "wx", mode: 0o600 });
  const proofInfo = fs.lstatSync(proof);
  if (!proofInfo.isFile() || proofInfo.isSymbolicLink() || proofInfo.nlink !== 1
      || hash(fs.readFileSync(proof)) !== embeddingCaptureSource.sha256) return rejectCapture(absolute);
  return { kind: "embedding-fixture-capture", path: embeddingCaptureSource.sourcePath,
    sourcePath: embeddingCaptureSource.sourcePath, capturePath: relative,
    proofPath: proofRelative, sha256: embeddingCaptureSource.sha256 };
}
function promptFixtureCaptureAuthority(filename) {
  const absolute = path.resolve(filename);
  const relative = path.relative(context.stateDirectory, absolute).replaceAll(path.sep, "/");
  if (!(promptMode || historyMode) || !promptCaptureSource || !promptCapturePattern.test(relative)) return rejectCapture(absolute);
  let cursor = context.stateDirectory;
  for (const component of relative.split("/").slice(0, -1)) {
    const directory = fs.lstatSync(cursor);
    if (!directory.isDirectory() || directory.isSymbolicLink()) return rejectCapture(absolute);
    cursor = path.join(cursor, component);
  }
  const parent = fs.lstatSync(path.dirname(absolute)), info = fs.lstatSync(absolute);
  if (!parent.isDirectory() || parent.isSymbolicLink() || !info.isFile() || info.isSymbolicLink()
      || info.nlink !== 1 || fs.realpathSync(absolute) !== absolute
      || info.size !== fs.statSync(promptCaptureSource.sourcePath).size) return rejectCapture(absolute);
  const raw = fs.readFileSync(absolute);
  if (hash(raw) !== promptCaptureSource.sha256) return rejectCapture(absolute);
  const proofRelative = `prompt-fixture-source-captures/${hash(Buffer.from(relative + "\0" + promptCaptureSource.sha256))}.mjs`;
  const proofDirectory = path.join(context.evidenceDirectory, "prompt-fixture-source-captures");
  fs.mkdirSync(proofDirectory, { recursive: true, mode: 0o700 });
  const proofParent = fs.lstatSync(proofDirectory);
  if (!proofParent.isDirectory() || proofParent.isSymbolicLink()
      || fs.realpathSync(proofDirectory) !== proofDirectory) return rejectCapture(absolute);
  const proof = path.join(context.evidenceDirectory, proofRelative);
  if (!fs.existsSync(proof)) fs.writeFileSync(proof, raw, { flag: "wx", mode: 0o600 });
  const proofInfo = fs.lstatSync(proof);
  if (!proofInfo.isFile() || proofInfo.isSymbolicLink() || proofInfo.nlink !== 1
      || hash(fs.readFileSync(proof)) !== promptCaptureSource.sha256) return rejectCapture(absolute);
  return { kind: "prompt-fixture-capture", path: promptCaptureSource.sourcePath,
    sourcePath: promptCaptureSource.sourcePath, capturePath: relative,
    proofPath: proofRelative, sha256: promptCaptureSource.sha256 };
}
function authority(url) {
  if (url.startsWith("node:")) return undefined;
  if (!url.startsWith("file:")) {
    trace({ event: "rejected", code: "unsupported-module-source" });
    throw Error("Runtime imports require authenticated artifact files");
  }
  const lexical = path.resolve(fileURLToPath(url));
  if (isCapturePath(lexical)) return embeddingMode ? embeddingFixtureCaptureAuthority(lexical)
    : promptMode || historyMode ? promptFixtureCaptureAuthority(lexical) : fixtureCaptureAuthority(lexical);
  const filename = fs.realpathSync(lexical);
  const record = permitted.get(filename);
  if (!record || hash(fs.readFileSync(filename)) !== record.sha256) {
    const relative = path.relative(context.stateDirectory, filename).replaceAll(path.sep, "/");
    trace({ event: "rejected", code: "unverified-module-bytes",
      basename: path.basename(filename),
      ...(relative && relative !== ".." && !relative.startsWith("../") && !path.isAbsolute(relative)
        ? { ownedStatePath: relative } : {}),
    });
    throw Error("Runtime import is not an authenticated artifact or reviewed oracle file");
  }
  return record;
}
registerHooks({
  resolve(specifier, resolveContext, nextResolve) {
    // Node resolves a symlink before returning its URL. Validate the lexical
    // native-capture path first so a link cannot inherit the original's authority.
    let lexical;
    if (specifier.startsWith("file:")) lexical = path.resolve(fileURLToPath(specifier));
    else if (path.isAbsolute(specifier)) lexical = path.resolve(specifier);
    else if (specifier.startsWith(".") && resolveContext.parentURL?.startsWith("file:")) {
      lexical = path.resolve(path.dirname(fileURLToPath(resolveContext.parentURL)), specifier);
    }
    if (lexical && isCapturePath(lexical)) {
      if (embeddingMode) embeddingFixtureCaptureAuthority(lexical);
      else if (promptMode || historyMode) promptFixtureCaptureAuthority(lexical);
      else fixtureCaptureAuthority(lexical);
    }
    const resolved = nextResolve(specifier, resolveContext);
    const record = authority(resolved.url);
    if (record?.kind === "release" && record.package === "node_modules/@openclaw/fs-safe" &&
        record.path === "dist/test-hooks.js" && resolveContext.parentURL?.startsWith("file:")) {
      const parent = authority(resolveContext.parentURL);
      if (parent?.kind === "oracle" && (!isMainThread || !context.getReadRaceProfile ||
          path.basename(parent.path) !== "get-contract-runtime.mjs" || record.sha256 !== context.getReadRaceProfile.sha256)) {
        throw Error("Only the declared whole-get race profile may import the official test hook directly");
      }
    }
    if (record && resolved.url.endsWith(".node")) trace({ event: "resolve-native", ...record });
    return resolved;
  },
  load(url, loadContext, nextLoad) {
    // Node can install its worker console after preloads have run. Apply the
    // same transport policy again before the authenticated worker entry loads.
    routeConsoleDiagnostics();
    const record = authority(url);
    if (record) trace({ event: "load", ...record });
    return nextLoad(url, loadContext);
  },
});
if (context.atomicPublicationProfile) {
  const { installAtomicReturnCheckpoint } = await import(new URL("./atomic-return-checkpoint.mjs", import.meta.url).href);
  installAtomicReturnCheckpoint(context, trace);
} else if (context.atomicCaseBinding !== undefined) {
  throw Error("An atomic case cannot borrow another profile's trusted return observer");
}
