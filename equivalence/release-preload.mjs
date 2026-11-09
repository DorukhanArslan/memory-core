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
if (context.schemaVersion !== 1 || context.providerMode !== "none" || context.fetchPolicy !== "deny") {
  throw Error("Unsupported release execution policy");
}
if (context.entryProvenanceProfile !== undefined) {
  const profile = context.entryProvenanceProfile;
  const kinds = { "entry-memory-publication-runtime": "published-memory",
    "entry-session-publication-runtime": "session-projection", "entry-provider-preparation-runtime": "prepared-provider" };
  if (!profile || Object.keys(profile).sort().join() !== "inputKind,kind,nodeRuntime,operation" ||
      profile.kind !== "approved-entry-provenance-profile" || !Object.hasOwn(kinds, profile.operation) ||
      profile.inputKind !== kinds[profile.operation] ||
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
      context.entryProvenanceProfile !== undefined ||
      (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
    throw Error("Unapproved atomic original-owner profile capability");
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
        fetchDenied: true, providerMode: "none", ...(approvedNodeRuntime ? { runtime: approvedNodeRuntime } : {}),
        ...(context.entryProvenanceProfile ? { entryProfile: context.entryProvenanceProfile } : {}),
        ...(context.atomicPublicationProfile ? { atomicProfile: context.atomicPublicationProfile } : {}) });
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
    throw Error("Network requests are disabled in provider-none release comparisons");
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
function authority(url) {
  if (url.startsWith("node:")) return undefined;
  if (!url.startsWith("file:")) {
    trace({ event: "rejected", code: "unsupported-module-source" });
    throw Error("Runtime imports require authenticated artifact files");
  }
  const lexical = path.resolve(fileURLToPath(url));
  if (isCapturePath(lexical)) return fixtureCaptureAuthority(lexical);
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
    if (lexical && isCapturePath(lexical)) fixtureCaptureAuthority(lexical);
    const resolved = nextResolve(specifier, resolveContext);
    const record = authority(resolved.url);
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
