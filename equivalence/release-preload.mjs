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
const permitted = new Map();
for (const entry of context.allowedLocal) {
  permitted.set(fs.realpathSync(entry.path), { kind: "oracle", path: fs.realpathSync(entry.path), sha256: entry.sha256 });
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
trace({ event: "bootstrap", isMainThread, contextSha256: hash(rawContext), preloadSha256: own.sha256,
        fetchDenied: true, providerMode: "none" });
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
function authority(url) {
  if (url.startsWith("node:")) return undefined;
  if (!url.startsWith("file:")) {
    trace({ event: "rejected", code: "unsupported-module-source" });
    throw Error("Runtime imports require authenticated artifact files");
  }
  const filename = fs.realpathSync(fileURLToPath(url));
  const record = permitted.get(filename);
  if (!record || hash(fs.readFileSync(filename)) !== record.sha256) {
    trace({ event: "rejected", code: "unverified-module-bytes" });
    throw Error("Runtime import is not an authenticated artifact or reviewed oracle file");
  }
  return record;
}
registerHooks({
  resolve(specifier, resolveContext, nextResolve) {
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
