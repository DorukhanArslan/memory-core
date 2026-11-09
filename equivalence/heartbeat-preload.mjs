// Independent, compiled-only capability for the fixed heartbeat scratch lane.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { registerHooks, syncBuiltinESMExports } from "node:module";
import { fileURLToPath } from "node:url";
import { threadId, isMainThread } from "node:worker_threads";
import net from "node:net";
import http from "node:http";
import https from "node:https";
import dgram from "node:dgram";
import { Console } from "node:console";

const sha = (value) => crypto.createHash("sha256").update(value).digest("hex");
const contextPath = process.env.MEMORY_EQ_HEARTBEAT_CONTEXT;
if (process.env.MEMORY_EQ_DOCTOR_CONTEXT || process.env.MEMORY_EQ_RELEASE_CONTEXT) throw Error("STORE cannot borrow Doctor or release context authority");
if (!contextPath || !path.isAbsolute(contextPath)) throw Error("Owned heartbeat context is required");
const raw = fs.readFileSync(contextPath);
if (raw.length > 64 * 1024 * 1024) throw Error("Heartbeat context exceeds its bound");
const context = JSON.parse(raw);
const cap = context.capability;
if (context.kind !== "heartbeat-scratch-execution" || context.providerMode !== "none" || context.fetchPolicy !== "deny" ||
    !cap || Object.keys(cap).sort().join() !== "kind,node,profile" || cap.kind !== "heartbeat-scratch-node-capability" ||
    cap.profile !== "heartbeat-scratch-store" ||
    Object.keys(context).sort().join() !== "allowedLocal,capability,fetchPolicy,kind,providerMode,requestPath,requestSha256,runtime,traceDirectory") {
  throw Error("Only the explicit heartbeat scratch capability is accepted");
}
const required = { nodeVersion: "v24.16.0", icuVersion: "78.3", unicodeVersion: "17.0",
  sha256: "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd" };
const actual = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
  icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode, sha256: sha(fs.readFileSync(process.execPath)) };
if (!cap.node || Object.keys(cap.node).sort().join() !== "execPath,icuVersion,nodeVersion,sha256,unicodeVersion" ||
    !path.isAbsolute(cap.node.execPath) || Object.entries(required).some(([key, value]) => cap.node[key] !== value) ||
    JSON.stringify(actual) !== JSON.stringify({ execPath: cap.node.execPath, ...required })) {
  throw Error("The heartbeat process changed its exact executable or Unicode engine");
}
const permitted = new Map();
if (!Array.isArray(context.allowedLocal) || context.allowedLocal.length !== 2 ||
    context.allowedLocal.map((item) => path.basename(item.path)).sort().join() !== "heartbeat-preload.mjs,heartbeat-runtime.mjs") {
  throw Error("Heartbeat authority accepts only its own exact preload and runner");
}
for (const item of context.allowedLocal) {
  if (!path.isAbsolute(item.path) || fs.realpathSync(item.path) !== item.path || sha(fs.readFileSync(item.path)) !== item.sha256) {
    throw Error("A reviewed heartbeat adapter changed");
  }
  permitted.set(item.path, { kind: "heartbeat-adapter", path: item.path, sha256: item.sha256 });
}
for (const item of context.runtime.packages) {
  if (fs.realpathSync(item.directory) !== item.directory) throw Error("An artifact package root is aliased");
  for (const file of item.files) {
    const filename = path.resolve(item.directory, file.path);
    if (!filename.startsWith(item.directory + path.sep) || permitted.has(filename)) throw Error("Duplicate or escaping heartbeat artifact");
    permitted.set(filename, { kind: "official-release", package: item.location, path: file.path, sha256: file.sha256 });
  }
}
const own = permitted.get(fs.realpathSync(fileURLToPath(import.meta.url)));
if (!own || own.kind !== "heartbeat-adapter") throw Error("Unreviewed heartbeat preload");
const tracePath = path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`);
function trace(event) {
  if (fs.existsSync(tracePath) && fs.statSync(tracePath).size > 8 * 1024 * 1024) throw Error("Heartbeat trace exceeds its bound");
  fs.appendFileSync(tracePath, JSON.stringify({ ...event, pid: process.pid, threadId }) + "\n", { mode: 0o600 });
}
trace({ event: "bootstrap", isMainThread, ppid: process.ppid, node: actual,
  contextSha256: sha(raw), profile: cap.profile, requestSha256: context.requestSha256, preloadSha256: own.sha256 });
function denied() {
  trace({ event: "network-denied" });
  throw Error("Network access is disabled in heartbeat scratch diagnostics");
}
Object.defineProperty(globalThis, "fetch", { configurable: false, writable: false, value: async () => denied() });
net.connect = denied; net.createConnection = denied; net.Socket.prototype.connect = denied;
http.request = denied; http.get = denied; https.request = denied; https.get = denied; dgram.createSocket = denied;
syncBuiltinESMExports();
const diagnostic = new Console({ stdout: process.stderr, stderr: process.stderr });
for (const name of ["log", "info", "debug"]) Object.defineProperty(console, name, {
  configurable: false, writable: false, value: diagnostic[name].bind(diagnostic),
});
function authority(url) {
  if (url.startsWith("node:")) return undefined;
  if (!url.startsWith("file:")) throw Error("Heartbeat modules require authenticated file bytes");
  const filename = fs.realpathSync(fileURLToPath(url)), item = permitted.get(filename);
  if (!item || sha(fs.readFileSync(filename)) !== item.sha256) {
    trace({ event: "rejected", basename: path.basename(filename) });
    throw Error("An imported module has no heartbeat artifact authority");
  }
  return item;
}
registerHooks({
  resolve(specifier, options, next) { const result = next(specifier, options); authority(result.url); return result; },
  load(url, options, next) { const item = authority(url); if (item) trace({ event: "load", ...item }); return next(url, options); },
});
const originalDlopen = process.dlopen;
process.dlopen = function heartbeatDlopen(module, filename, ...args) {
  const item = authority(new URL(`file://${filename}`).href);
  trace({ event: "native-load", ...item });
  return originalDlopen.call(this, module, filename, ...args);
};
