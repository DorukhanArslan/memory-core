// Doctor-only bootstrap and transport observers. No business decisions supplied.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { registerHooks, syncBuiltinESMExports } from "node:module";
import { fileURLToPath } from "node:url";
import { Worker, MessagePort, threadId, isMainThread } from "node:worker_threads";
import { mock } from "node:test";
import net from "node:net";
import http from "node:http";
import https from "node:https";
import dgram from "node:dgram";
import { Console } from "node:console";

const hash = (value) => crypto.createHash("sha256").update(value).digest("hex");
const contextPath = process.env.MEMORY_EQ_DOCTOR_CONTEXT;
if (!contextPath || !path.isAbsolute(contextPath)) throw Error("Doctor requires its exclusive owned context");
const contextBytes = fs.readFileSync(contextPath);
if (contextBytes.length > 64 * 1024 * 1024) throw Error("Doctor context exceeds its bound");
const context = JSON.parse(contextBytes), capability = context.capability;
if (context.kind !== "heartbeat-doctor-execution" || context.providerMode !== "none" || context.fetchPolicy !== "deny" ||
    Object.keys(context).sort().join() !== "allowedLocal,bindingsSha256,capability,codecSha256,fetchPolicy,kind,providerMode,requestPath,requestSha256,runtime,traceDirectory" ||
    !capability || Object.keys(capability).sort().join() !== "kind,node,profile" ||
    capability.kind !== "heartbeat-doctor-node-capability" || capability.profile !== "heartbeat-scratch-doctor" ||
    process.env.MEMORY_EQ_HEARTBEAT_CONTEXT || process.env.MEMORY_EQ_RELEASE_CONTEXT ||
    context.bindingsSha256 !== "e08e2474e9582bac3fed1730cefe66c5c10a4d001380559191c85ba9bc1622c2" ||
    context.codecSha256 !== "86671a5b11a40cfcd5299c5a867a7c8f27898112055bdaa7c3bbc2eeccd54a38") {
  throw Error("Doctor authority cannot borrow STORE, model, source or other runtime capabilities");
}
const required = { nodeVersion: "v24.16.0", icuVersion: "78.3", unicodeVersion: "17.0",
  sha256: "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd" };
const node = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
  icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode, sha256: hash(fs.readFileSync(process.execPath)) };
if (!capability.node || Object.keys(capability.node).sort().join() !== "execPath,icuVersion,nodeVersion,sha256,unicodeVersion" ||
    JSON.stringify(node) !== JSON.stringify({ execPath: capability.node.execPath, ...required })) {
  throw Error("Doctor process or worker changed its exact Node/Unicode identity");
}
const requestBytes = fs.readFileSync(context.requestPath);
if (requestBytes.length > 4 * 1024 * 1024 || hash(requestBytes) !== context.requestSha256) throw Error("Doctor input changed");
const request = JSON.parse(requestBytes), input = request.input;
const plain = (value) => value && Object.getPrototypeOf(value) === Object.prototype;
const keys = (value, expected) => plain(value) && Object.keys(value).sort().join() === [...expected].sort().join();
if (!keys(request, ["kind", "phase", "input", "fixtureDirectory"]) || request.kind !== "heartbeat-doctor-sequence" ||
    !Number.isSafeInteger(request.phase) || request.phase < 0 || !path.isAbsolute(request.fixtureDirectory) ||
    !keys(input, ["nowMs", "agents", "host", "ops", "customStore"]) ||
    !Number.isSafeInteger(input.nowMs) || input.nowMs < 0 || input.nowMs > 8640000000000000 ||
    !Array.isArray(input.agents) || !input.agents.length || input.agents.length > 4 ||
    input.agents.some((agent) => !keys(agent, ["id", "every"]) || !/^[a-z][a-z0-9_-]{0,31}$/.test(agent.id) || !["30m", "0m"].includes(agent.every)) ||
    new Set(input.agents.map((agent) => agent.id)).size !== input.agents.length ||
    !keys(input.host, ["agentIds", "retainSource"]) || !Array.isArray(input.host.agentIds) ||
    input.host.agentIds.some((id) => !input.agents.some((agent) => agent.id === id)) || typeof input.host.retainSource !== "boolean" ||
    typeof input.customStore !== "boolean" || !Array.isArray(input.ops) || !input.ops.length || input.ops.length > 30) {
  throw Error("Doctor accepts only its exact literal bounded fixture kind/config/clock before imports");
}
for (const op of input.ops) {
  if (!plain(op) || !["findings", "preview", "repair", "seedScratch"].includes(op.op)) throw Error("Undeclared Doctor operation");
  if (op.op === "seedScratch") {
    if (!keys(op, ["op", "agentId", "content"]) || !input.agents.some((agent) => agent.id === op.agentId) ||
        !(typeof op.content === "string" || op.content === null)) throw Error("Doctor scratch fixture must use literal owned input");
  } else if (!keys(op, ["op"])) throw Error("Doctor operation has unreviewed parameters");
}
const phaseDirectory = path.dirname(context.requestPath), caseDirectory = path.dirname(phaseDirectory);
if (path.basename(context.requestPath) !== "native-input.json" || contextPath !== path.join(phaseDirectory, "context.json") ||
    context.traceDirectory !== path.join(phaseDirectory, "traces") || path.basename(phaseDirectory) !== String(request.phase) ||
    request.fixtureDirectory !== path.join(caseDirectory, "native-fixture") ||
    [contextPath, context.requestPath, context.traceDirectory, request.fixtureDirectory].some((target) => fs.realpathSync(target) !== target)) {
  throw Error("Doctor source/context paths must remain the exact owned case/phase fixture");
}
const permitted = new Map();
if (!Array.isArray(context.allowedLocal) || context.allowedLocal.length !== 2 ||
    context.allowedLocal.map((item) => path.basename(item.path)).sort().join() !== "heartbeat-doctor-preload.mjs,heartbeat-doctor-runtime.mjs") {
  throw Error("Doctor admits only its own exact preload and runner adapters");
}
for (const item of context.allowedLocal) {
  if (!path.isAbsolute(item.path) || fs.realpathSync(item.path) !== item.path || hash(fs.readFileSync(item.path)) !== item.sha256) throw Error("Doctor adapter changed");
  permitted.set(item.path, { kind: "doctor-adapter", path: item.path, sha256: item.sha256 });
}
if (context.runtime.runtimeRoot !== "/workspace/scratch/memory-core-heartbeat-doctor-lane/.reference/release-runtime/node_modules/openclaw" ||
    context.runtime.manifestSha256 !== "5f8d7efe63635bdcf633f75b028aa748d8cf3547b66efe1781b02b09bc648cf5" ||
    context.runtime.reference?.commit !== "bcfc88812a35243893585dbeca87ca41b48272ca" || context.runtime.buildAttestation?.sourceBuildReproduced !== false ||
    !Array.isArray(context.runtime.packages) || context.runtime.packages.length !== 84 ||
    context.runtime.packages.filter((item) => item.name === "croner" && item.version === "10.0.1").length !== 1) throw Error("Doctor requires its exact private84 package authority");
for (const item of context.runtime.packages) {
  if (item.directory !== path.join(path.resolve(context.runtime.runtimeRoot, "../.."), item.location) ||
      fs.realpathSync(item.directory) !== item.directory) throw Error("Doctor package root is aliased or outside its private installation");
  if (item.name === "croner" && (item.archiveSha256 !== "d6d93c286125fed567b986a576ff1daa74e72d56bb63fe28248ca17cfcb00cee" ||
      item.filesSha256 !== "dbf132f1899f1bbb92ec5f8fcc8519a7569337139c0004292862eeab87ce38e1" || item.fileCount !== 8)) throw Error("Doctor croner artifact changed");
  for (const file of item.files) {
    const target = path.resolve(item.directory, file.path);
    if (!target.startsWith(item.directory + path.sep) || permitted.has(target)) throw Error("Doctor artifact path escapes or duplicates authority");
    permitted.set(target, { kind: "official-release", package: item.location, path: file.path, sha256: file.sha256 });
  }
}
const own = permitted.get(fs.realpathSync(fileURLToPath(import.meta.url)));
const carrier = path.join(context.runtime.runtimeRoot, "dist/infra/sqlite-store.worker.js");
const runner = context.allowedLocal.find((item) => item.path.endsWith("/heartbeat-doctor-runtime.mjs")).path;
if (!own || own.kind !== "doctor-adapter" || !process.argv[1] ||
    fs.realpathSync(process.argv[1]) !== (isMainThread ? runner : carrier)) throw Error("Unreviewed Doctor process/worker entry");
const tracePath = path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`);
const portIds = new WeakMap(); let portCounter = 0;
const sharedIds = new WeakMap(), observedShared = new Map(); let sharedCounter = 0;
function portId(value) { if (!portIds.has(value)) portIds.set(value, ++portCounter); return portIds.get(value); }
function sharedId(value) {
  if (!sharedIds.has(value)) { sharedIds.set(value, ++sharedCounter); observedShared.set(sharedCounter, value); }
  return sharedIds.get(value);
}
function sharedObservations() {
  return Array.from(observedShared, ([observerBuffer, value]) => ({ observerBuffer,
    type: "SharedArrayBuffer", base64: Buffer.from(value).toString("base64") }));
}
function wire(value, seen = new WeakSet()) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
  if (typeof value === "symbol") return { type: "symbol", description: value.description };
  if (value instanceof MessagePort) return { type: "MessagePort", observerChannel: portId(value) };
  if (value instanceof SharedArrayBuffer) return { type: "SharedArrayBuffer", observerBuffer: sharedId(value), base64: Buffer.from(value).toString("base64") };
  if (value instanceof ArrayBuffer) return { type: "ArrayBuffer", base64: Buffer.from(value).toString("base64") };
  if (ArrayBuffer.isView(value)) return { type: value.constructor.name, base64: Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString("base64") };
  if (value && typeof value === "object") {
    if (seen.has(value)) throw Error("Doctor raw transport refuses an untracked cyclic message");
    seen.add(value);
    let result;
    if (value instanceof Set) result = { type: "Set", values: Array.from(value, (item) => wire(item, seen)) };
    else if (value instanceof Map) result = { type: "Map", entries: Array.from(value, ([key, item]) => [wire(key, seen), wire(item, seen)]) };
    else if (Array.isArray(value)) result = value.map((item) => wire(item, seen));
    else if (value instanceof Error) result = { type: "Error", name: value.name, message: value.message,
      constructorName: value.constructor?.name ?? null,
      ownProperties: Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, wire(value[key], seen)])) };
    else result = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, wire(item, seen)]));
    seen.delete(value);
    return result;
  }
  return value;
}
function trace(event) {
  if (fs.existsSync(tracePath) && fs.statSync(tracePath).size > 32 * 1024 * 1024) throw Error("Doctor trace bound exceeded");
  fs.appendFileSync(tracePath, JSON.stringify({ ...event, pid: process.pid, threadId }) + "\n", { mode: 0o600 });
}
const oldDate = Date, oldTimeout = setTimeout, oldInterval = setInterval, oldPerformanceNow = performance.now;
mock.timers.enable({ apis: ["Date"], now: input.nowMs });
trace({ event: "bootstrap", isMainThread, ppid: process.ppid, node, contextSha256: hash(contextBytes),
  requestSha256: context.requestSha256, entry: fs.realpathSync(process.argv[1]), execArgv: process.execArgv,
  processEnv: { ...process.env },
  profile: capability.profile, preloadSha256: own.sha256,
  clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: oldDate !== Date,
    setTimeoutUnchanged: oldTimeout === setTimeout, setIntervalUnchanged: oldInterval === setInterval,
    performanceNowUnchanged: oldPerformanceNow === performance.now } });
Object.defineProperty(globalThis, Symbol.for("memory-equivalence.heartbeatDoctorProtectedBootstrap"), {
  configurable: false, writable: false, value: hash(contextBytes),
});
function denied() { trace({ event: "network-denied" }); throw Error("Doctor fixture network policy is deny"); }
Object.defineProperty(globalThis, "fetch", { configurable: false, writable: false, value: async () => denied() });
net.connect = denied; net.createConnection = denied; net.Socket.prototype.connect = denied;
http.request = denied; http.get = denied; https.request = denied; https.get = denied; dgram.createSocket = denied;
syncBuiltinESMExports();
const diagnostics = new Console({ stdout: process.stderr, stderr: process.stderr });
const routed = Object.fromEntries(["log", "info", "debug"].map((name) => [name, diagnostics[name].bind(diagnostics)]));
function route() { for (const [name, implementation] of Object.entries(routed)) if (console[name] !== implementation) console[name] = implementation; }
route();
function authority(url) {
  if (url.startsWith("node:")) return undefined;
  if (!url.startsWith("file:")) throw Error("Doctor imports require authenticated file bytes");
  const target = fs.realpathSync(fileURLToPath(url)), item = permitted.get(target);
  if (!item || hash(fs.readFileSync(target)) !== item.sha256) { trace({ event: "rejected", basename: path.basename(target) }); throw Error("Doctor imported unreviewed artifact bytes"); }
  return item;
}
registerHooks({
  resolve(specifier, options, next) { const result = next(specifier, options); authority(result.url); return result; },
  load(url, options, next) { route(); const item = authority(url); if (item) trace({ event: "load", ...item }); return next(url, options); },
});
const nativeDlopen = process.dlopen;
process.dlopen = function(module, filename, ...args) { const item = authority(new URL(`file://${filename}`).href); trace({ event: "native-load", ...item }); return nativeDlopen.call(this, module, filename, ...args); };
const workerIds = new WeakMap(), workerPost = Worker.prototype.postMessage, workerEmit = Worker.prototype.emit;
const workerTerminate = Worker.prototype.terminate;
Worker.prototype.postMessage = function(message, ...args) {
  if (!isMainThread) { trace({ event: "rejected", reason: "nested-worker" }); throw Error("Doctor profile permits no nested workers"); }
  if (this.threadId > 0) workerIds.set(this, this.threadId);
  trace({ event: "worker-send", targetThreadId: workerIds.get(this), message: wire(message), remainingArguments: wire(args) });
  try {
    const result = workerPost.call(this, message, ...args);
    trace({ event: "worker-send-return", targetThreadId: workerIds.get(this), result: wire(result) });
    return result;
  } catch (error) { trace({ event: "worker-send-error", targetThreadId: workerIds.get(this), error: wire(error) }); throw error; }
};
Worker.prototype.emit = function(event, ...args) {
  if (this.threadId > 0) workerIds.set(this, this.threadId);
  if (event === "message") trace({ event: "worker-reply", targetThreadId: workerIds.get(this), message: wire(args[0]) });
  if (event === "exit") trace({ event: "worker-exit", targetThreadId: workerIds.get(this), code: args[0] });
  const result = workerEmit.call(this, event, ...args);
  if (["message", "exit"].includes(event)) trace({ event: "worker-emit-return", targetThreadId: workerIds.get(this), emittedEvent: event, result: wire(result) });
  return result;
};
Worker.prototype.terminate = function(...args) {
  if (this.threadId > 0) workerIds.set(this, this.threadId);
  const targetThreadId = workerIds.get(this);
  trace({ event: "worker-terminate", targetThreadId, arguments: wire(args) });
  let actual;
  try { actual = workerTerminate.apply(this, args); }
  catch (error) { trace({ event: "worker-terminate-error", targetThreadId, error: wire(error) }); throw error; }
  actual.then((code) => trace({ event: "worker-terminate-return", targetThreadId, code }),
    (error) => trace({ event: "worker-terminate-error", targetThreadId, error: wire(error) }));
  return actual;
};
const portPost = MessagePort.prototype.postMessage;
MessagePort.prototype.postMessage = function(message, ...args) {
  const capturedMessage = wire(message), capturedArguments = wire(args);
  trace({ event: "port-send", observerChannel: portId(this), message: capturedMessage,
    remainingArguments: capturedArguments, observedSharedMemory: sharedObservations() });
  try {
    const result = portPost.call(this, message, ...args);
    trace({ event: "port-send-return", observerChannel: portId(this), result: wire(result) });
    return result;
  } catch (error) { trace({ event: "port-send-error", observerChannel: portId(this), error: wire(error) }); throw error; }
};
