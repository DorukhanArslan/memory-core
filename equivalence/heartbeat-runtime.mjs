// Fixture transport around actual compiled scratch owners; no scratch rules here.
import fs from "node:fs/promises";
import syncFs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";

const context = JSON.parse(await fs.readFile(process.env.MEMORY_EQ_HEARTBEAT_CONTEXT, "utf8"));
if (process.argv[2] !== context.requestPath) throw Error("Heartbeat request does not match its capability");
const bytes = await fs.readFile(context.requestPath);
if (crypto.createHash("sha256").update(bytes).digest("hex") !== context.requestSha256) throw Error("Heartbeat input changed");
const request = JSON.parse(bytes), input = request.input;
if (context.capability.profile !== "heartbeat-scratch-store" || request.kind !== "store" ||
    !path.isAbsolute(request.fixtureDirectory) || !Number.isSafeInteger(input.nowMs) || !Array.isArray(input.steps)) {
  throw Error("Only literal fixed heartbeat store inputs are accepted");
}
const directory = request.fixtureDirectory, state = path.join(directory, "state");
await fs.mkdir(directory, { recursive: true });
process.env.OPENCLAW_STATE_DIR = state;
process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
process.env.OPENCLAW_HOME = path.join(directory, "home");
process.env.OPENCLAW_SUPPRESS_NOTES = "1";
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify({ logging: {
  level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") } }));
const beforeDate = Date, beforeTimeout = setTimeout;
mock.timers.enable({ apis: ["Date"], now: input.nowMs });
const raw = { fixtureDirectory: directory, profile: context.capability.profile,
  clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: beforeDate !== Date,
    setTimeoutUnchanged: beforeTimeout === setTimeout }, calls: [], observations: [], initialization: [] };
const imp = (name) => import(pathToFileURL(path.join(context.runtime.runtimeRoot, name)).href);
const contract = await imp("dist/scratch-contract-B-Laspel.mjs");
const scratch = await imp("dist/scratch-store-BsjpiVxl.mjs");
const database = await imp("dist/openclaw-state-db-Dh2awMJ8.mjs");
const rows = await imp("dist/row-codec-CFdZvBgt.mjs");
const keys = await imp("dist/key-BBZ40bDq.mjs");
const options = { env: { ...process.env } };
const partition = (name = "main") => {
  if (!/^[a-z0-9-]+$/.test(name)) throw Error("Heartbeat partition escapes the owned fixture");
  return path.join(directory, "cron", `${name}.json`);
};
const text = (value) => typeof value === "string" ? value
  : String(value.unit ?? "").repeat(value.count ?? 0) + (value.suffix ?? "");
const errorValue = (error) => ({ name: error?.name ?? typeof error, message: error?.message ?? String(error),
  ...Object.fromEntries(Object.getOwnPropertyNames(error ?? {}).filter((key) => !["name", "message", "stack"].includes(key))
    .map((key) => [key, error[key] instanceof Error ? errorValue(error[key]) : error[key]])) });
const rawError = (error) => ({ ...errorValue(error), stack: error?.stack ?? null,
  ...(error?.cause instanceof Error ? { cause: rawError(error.cause) } : {}) });
function wireRaw(value) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
  if (value instanceof Set) return { type: "Set", values: Array.from(value, wireRaw) };
  if (value instanceof Map) return { type: "Map", entries: Array.from(value, ([key, item]) => [wireRaw(key), wireRaw(item)]) };
  if (Array.isArray(value)) return value.map(wireRaw);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, wireRaw(item)]));
  return value;
}
const clean = (value) => value === undefined ? { absent: true } : value;
function call(module, symbol, fn, args) {
  const record = { module, export: symbol, args };
  raw.calls.push(record);
  try { const result = fn(...args); record.result = clean(result); return clean(result); }
  catch (error) { record.error = rawError(error); throw error; }
}
const fixtureJob = (owner) => ({ id: owner.jobId, agentId: owner.agentId, declarationKey: `heartbeat:${owner.agentId}`,
  displayName: `Heartbeat (${owner.agentId})`, name: `heartbeat-${owner.agentId}`, enabled: true,
  createdAtMs: input.nowMs, updatedAtMs: input.nowMs,
  schedule: { kind: "every", everyMs: 1800000, anchorMs: 0 },
  payload: { kind: "heartbeat" }, sessionTarget: "main", wakeMode: "next-heartbeat", state: {} });
if (input.initialize) {
  database.l(({ db }) => {
    for (const [index, owner] of input.owners.entries()) {
      const storeKey = keys.t(partition(owner.partition));
      const result = rows.h(db, storeKey, fixtureJob(owner), index);
      raw.initialization.push({ export: "upsertCronJobRow", storeKey, input: fixtureJob(owner), result });
    }
  }, options, { operationLabel: "heartbeat.fixture.owners" });
}
for (const step of input.steps) {
  const storePath = partition(step.partition), jobId = step.jobId ?? "owner-main", agentId = step.agentId ?? "main";
  let value;
  try {
    if (step.op === "cap") {
      call("dist/scratch-contract-B-Laspel.mjs", "assertCronJobScratchContent", contract.n, [text(step.content)]);
      value = { ok: true, maxBytes: contract.t };
    } else if (step.op === "hash") value = call("dist/scratch-store-BsjpiVxl.mjs", "hashCronScratchSource", scratch.n, [text(step.content)]);
    else if (step.op === "read") value = call("dist/scratch-store-BsjpiVxl.mjs", "readCronJobScratchState", scratch.r, [storePath, jobId, options]);
    else if (step.op === "readMonitor" || step.op === "readMonitorReadOnly") value = call("dist/scratch-store-BsjpiVxl.mjs",
      step.op === "readMonitor" ? "readHeartbeatMonitorScratch" : "readHeartbeatMonitorScratchReadOnly",
      step.op === "readMonitor" ? scratch.i : scratch.a, [storePath, agentId, options]);
    else if (step.op === "write") value = call("dist/scratch-store-BsjpiVxl.mjs", "writeCronJobScratch", scratch.o, [{
      storePath, jobId, content: step.content === null ? null : text(step.content), nowMs: step.nowMs ?? input.nowMs,
      ...(Object.hasOwn(step, "expectedRevision") ? { expectedRevision: step.expectedRevision } : {}),
      ...(Object.hasOwn(step, "sourceSha256") ? { sourceSha256: step.sourceSha256 } : {}), options }]);
    else if (step.op === "delete") value = call("dist/scratch-store-BsjpiVxl.mjs", "deleteCronJobScratch", scratch.t,
      [storePath, jobId, options, ...(Object.hasOwn(step, "expectedRevision") ? [{ expectedRevision: step.expectedRevision }] : [])]);
    else if (step.op === "removeOwner") {
      const retained = step.retainedOwners ?? [];
      database.l(({ db }) => {
        const result = step.cleanupScratch
          ? rows.n(db, keys.t(storePath), jobId)
          : rows.u(db, keys.t(storePath), { version: 1, jobs: retained.map(fixtureJob) });
        raw.calls.push({ module: "dist/row-codec-CFdZvBgt.mjs", export: step.cleanupScratch ? "deleteCronJobRowInDatabase" : "replaceCronRows",
          fixtureMutation: true, storePath, jobId, retainedOwners: retained, result: clean(result) });
      }, options, { operationLabel: "heartbeat.fixture.remove-owner" });
      value = null;
    } else throw Error("Undeclared heartbeat fixture operation");
  } catch (error) { value = { error: errorValue(error) }; }
  raw.observations.push({ step, value });
}
raw.process = { pid: process.pid, execPath: process.execPath };
await fs.writeFile(path.join(directory, `native-observations-${request.phase}.json`), JSON.stringify(wireRaw(raw)));
mock.timers.reset();
const result = { kind: "heartbeat-scratch-store", covers: [], result: raw.observations.map((item) => item.value), raw: wireRaw(raw) };
await new Promise((resolve, reject) => process.stdout.write(JSON.stringify(result) + "\n", (error) => error ? reject(error) : resolve()));
