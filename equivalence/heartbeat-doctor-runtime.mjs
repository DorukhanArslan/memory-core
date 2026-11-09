// Literal filesystem/config transport into genuine whole Doctor callers.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { deserialize } from "node:v8";
import crypto from "node:crypto";
import syncFs from "node:fs";
import { DatabaseSync } from "node:sqlite";

const contextBytes = await fs.readFile(process.env.MEMORY_EQ_DOCTOR_CONTEXT);
if (globalThis[Symbol.for("memory-equivalence.heartbeatDoctorProtectedBootstrap")] !==
    crypto.createHash("sha256").update(contextBytes).digest("hex")) throw Error("Doctor runner requires its actual protected bootstrap");
const context = JSON.parse(contextBytes);
if (process.argv[2] !== context.requestPath) throw Error("Doctor request path differs from its approved context");
const request = JSON.parse(await fs.readFile(context.requestPath, "utf8")), input = request.input;
const root = request.fixtureDirectory, workspace = path.join(root, "workspace"), state = path.join(root, "state");
await fs.mkdir(workspace, { recursive: true });
process.env.OPENCLAW_STATE_DIR = state;
process.env.OPENCLAW_CONFIG_PATH = path.join(root, "openclaw.json");
process.env.OPENCLAW_HOME = path.join(root, "home");
process.env.OPENCLAW_SUPPRESS_NOTES = "1";
const cfg = { agents: { defaults: { workspace }, list: input.agents.map((agent, index) => ({
  id: agent.id, ...(index === 0 ? { default: true } : {}), workspace, heartbeat: { every: agent.every } })) },
  logging: { level: "silent", consoleLevel: "silent", file: path.join(root, "native.log") },
  memory: { search: { enabled: true, provider: "none", fallback: "none" } },
  ...(input.customStore ? { cron: { store: path.join(root, "custom-cron", "jobs.json") } } : {}) };
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
const imp = (name) => import(pathToFileURL(path.join(context.runtime.runtimeRoot, name)).href);
const doctor = await imp("dist/doctor-heartbeat-scratch-migration-DZDMSbFc.mjs");
const cadence = await imp("dist/doctor-heartbeat-cadence-migration-B8HOzYOl.mjs");
const scratch = await imp("dist/scratch-store-BsjpiVxl.mjs");
const paths = await imp("dist/paths-D_dyKtfo.mjs");
const cache = await imp("dist/openclaw-state-db-cache-IdIaBoUp.mjs");
const storePath = paths.n(cfg, process.env), env = { ...process.env };
function wire(value) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
  if (ArrayBuffer.isView(value)) return { type: value.constructor.name, base64: Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString("base64") };
  if (value instanceof ArrayBuffer) return { type: "ArrayBuffer", base64: Buffer.from(value).toString("base64") };
  if (value instanceof Set) return { type: "Set", values: Array.from(value, wire) };
  if (value instanceof Map) return { type: "Map", entries: Array.from(value, ([key, item]) => [wire(key), wire(item)]) };
  if (Array.isArray(value)) return value.map(wire);
  if (value instanceof Error) return { name: value.name, message: value.message, constructorName: value.constructor?.name,
    ownProperties: Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, wire(value[key])])) };
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, wire(item)]));
  return value;
}
function readonlyState() {
  const observations = [];
  function visit(directory) {
    if (!syncFs.existsSync(directory)) return;
    for (const entry of syncFs.readdirSync(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) { visit(filename); continue; }
      if (!entry.isFile()) continue;
      const record = { path: filename };
      observations.push(record);
      let db;
      try {
        const bytes = syncFs.readFileSync(filename);
        record.bytes = { type: "bytes", base64: bytes.toString("base64") };
        if (bytes.subarray(0, 16).toString("binary") !== "SQLite format 3\0") continue;
        // Read-only observer only: no schema preparation, original state cache
        // admission, worker operation, revision fabrication or persistence.
        db = new DatabaseSync(filename, { readOnly: true });
        db.exec("PRAGMA query_only=ON");
        record.queryOnly = wire(db.prepare("PRAGMA query_only").get());
        db.exec("BEGIN");
        const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name");
        schema.setReadBigInts(true);
        record.schema = wire(schema.all());
        record.tables = [];
        for (const row of db.prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").all()) {
          const table = { name: row.name }; record.tables.push(table);
          try {
            const statement = db.prepare('SELECT * FROM "' + row.name.replaceAll('"', '""') + '"');
            statement.setReadBigInts(true);
            table.columns = wire(statement.columns());
            table.rows = wire(statement.all());
          } catch (error) { table.error = wire(error); }
        }
        db.exec("ROLLBACK");
      } catch (error) { record.error = wire(error); }
      finally { if (db) { try { db.close(); record.closed = true; } catch (error) { record.closeError = wire(error); } } }
    }
  }
  visit(state);
  return observations;
}
async function tree(directory) {
  const rows = [];
  async function visit(current) {
    let names;
    try { names = (await fs.readdir(current)).sort(); }
    catch (error) { rows.push({ path: path.relative(directory, current), error: wire(error) }); return; }
    for (const name of names) {
      const target = path.join(current, name);
      let stat;
      try { stat = await fs.lstat(target); }
      catch (error) { rows.push({ path: path.relative(directory, target), error: wire(error) }); continue; }
      const row = { path: path.relative(directory, target).replaceAll(path.sep, "/"), mode: stat.mode & 0o777,
        kind: stat.isSymbolicLink() ? "symlink" : stat.isDirectory() ? "directory" : stat.isFile() ? "file" : "other",
        physical: { dev: stat.dev, ino: stat.ino, nlink: stat.nlink, size: stat.size, mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs } };
      if (stat.isSymbolicLink()) { try { row.target = await fs.readlink(target); } catch (error) { row.error = wire(error); } }
      if (stat.isFile()) { try { row.bytes = { type: "bytes", base64: (await fs.readFile(target)).toString("base64") }; } catch (error) { row.error = wire(error); } }
      rows.push(row);
      if (stat.isDirectory()) await visit(target);
    }
  }
  try {
    const rootStat = await fs.lstat(directory);
    rows.push({ path: ".", kind: rootStat.isDirectory() ? "directory" : "other", mode: rootStat.mode & 0o777,
      physical: { dev: rootStat.dev, ino: rootStat.ino, nlink: rootStat.nlink, size: rootStat.size, mtimeMs: rootStat.mtimeMs, ctimeMs: rootStat.ctimeMs } });
    await visit(directory);
  } catch (error) {
    rows.push(error.code === "ENOENT" && rows.length === 0 ? { path: ".", kind: "absent" }
      : { path: path.relative(directory, error.path ?? directory), error: wire(error) });
  }
  return rows;
}
const raw = { fixtureDirectory: root, cfg: wire(cfg), storePath, env: wire(env), calls: [], snapshots: [], pid: process.pid,
  nowMs: Date.now(), sourceBuildReproduced: false, gatewayMutationContextInstalled: false };
raw.stateBeforeCalls = readonlyState();
async function snapshot() {
  const monitors = {};
  for (const agent of input.agents) monitors[agent.id] = wire(scratch.a(storePath, agent.id, { env }));
  const sourceTree = await tree(workspace);
  const archiveTree = await tree(path.join(state, "backups", "heartbeat-migration"));
  return { monitors, sourceTree, archiveTree };
}
raw.snapshots.push(await snapshot());
for (const op of input.ops) {
  const call = { operation: op, clockMs: Date.now() };
  raw.calls.push(call);
  try {
    if (op.op === "findings") {
      call.request = { cfg: wire(cfg) };
      call.result = wire(await doctor.collectHeartbeatScratchMigrationFindings(cfg));
    }
    else if (op.op === "preview" || op.op === "repair") {
      const actual = { cfg, shouldRepair: op.op === "repair", env };
      call.request = wire(actual);
      call.result = wire(await doctor.maybeMigrateHeartbeatFilesToScratch(actual));
      call.argumentsAfter = wire(actual);
    } else {
      call.request = { cfg: wire(cfg), storePath, env: wire(env), content: op.content, agentId: op.agentId };
      const monitors = await cadence.n(cfg, storePath, env);
      const selected = monitors.get(op.agentId);
      call.preparation = wire(monitors);
      const actual = { storePath, jobId: selected.id, content: op.content, nowMs: Date.now(), options: { env } };
      call.writeRequest = wire(actual);
      call.result = wire(scratch.o(actual));
      call.argumentsAfter = wire(actual);
    }
  } catch (error) { call.error = wire(error); }
  // Synchronous readonly snapshot at the actual awaited return cut, before any
  // further await or original diagnostic accessor can settle additional work.
  call.stateAtReturn = readonlyState();
  raw.snapshots.push(await snapshot());
}
raw.close = { module: "dist/openclaw-state-db-cache-IdIaBoUp.mjs", export: "closeOpenClawStateDatabaseAsync" };
try { raw.close.result = wire(await cache.a()); }
catch (error) { raw.close.error = wire(error); }
raw.stateAfterCanonicalClose = readonlyState();
raw.fixtureTreeAfterClose = await tree(root);
raw.workerDecoded = [];
for (const filename of (await fs.readdir(context.traceDirectory)).sort()) {
  const lines = (await fs.readFile(path.join(context.traceDirectory, filename), "utf8")).trim().split("\n");
  for (const [line, text] of lines.entries()) {
    const event = JSON.parse(text);
    if (!["worker-send", "worker-reply"].includes(event.event)) continue;
    for (const field of ["input", "value", "preparation"]) {
      const encoded = event.message?.[field];
      if (!encoded || typeof encoded.base64 !== "string") continue;
      const decoded = { trace: filename, line: line + 1, event: event.event, messageType: wire(event.message.type),
        targetThreadId: event.targetThreadId, field, bytes: encoded };
      try { decoded.value = wire(deserialize(Buffer.from(encoded.base64, "base64"))); }
      catch (error) { decoded.error = wire(error); }
      raw.workerDecoded.push(decoded);
    }
  }
}
const result = { operations: raw.calls.map((call) => call.error ? { error: call.error } : call.result),
  snapshots: raw.snapshots };
await fs.writeFile(path.join(path.dirname(context.requestPath), "native.observation.raw.json"), JSON.stringify(raw));
await new Promise((resolve, reject) => process.stdout.write(JSON.stringify({ kind: "heartbeat-doctor-observation", covers: [], result, raw }) + "\n", (error) => error ? reject(error) : resolve()));
