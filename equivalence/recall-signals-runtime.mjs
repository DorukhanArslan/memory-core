// Input-only recall operations over original compiled owners and durable stores.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { gzipSync } from "node:zlib";

const hash = value => createHash("sha256").update(value).digest("hex");
const clone = value => JSON.parse(JSON.stringify(value));
const json = value => JSON.stringify(value, (_key, item) => typeof item === "bigint"
  ? { type: "bigint", value: item.toString() } : item);
const returned = value => value === undefined ? { type: "undefined" }
  : { type: typeof value, value: clone(value) };
const failure = error => ({ name: error.name, message: error.message,
  ...Object.fromEntries(Object.getOwnPropertyNames(error).filter(key => !["name", "message"].includes(key))
    .map(key => [key, error[key]])) });
const bytes = value => ({ hex: value.toString("hex"), sha256: hash(value), size: value.length });
const TRIGGER = "recall_signal_origin_failure";
const TRIGGER_SQL = "CREATE TRIGGER recall_signal_origin_failure BEFORE INSERT ON memory_entry_origins " +
  "BEGIN SELECT RAISE(ABORT,'recall-origin-write-blocked'); END";

function owned(root, relative) {
  if (typeof relative !== "string" || !relative || relative.includes("\\") ||
      path.posix.isAbsolute(relative) || path.posix.normalize(relative) !== relative ||
      relative.split("/").some(part => part === "." || part === ".."))
    throw Error("A recall fixture path must be canonical and owned");
  const result = path.resolve(root, relative);
  if (!result.startsWith(path.resolve(root) + path.sep)) throw Error("A recall fixture escaped its owner");
  return result;
}

async function tree(root) {
  const result = {};
  async function walk(directory) {
    let entries;
    try { entries = await fs.readdir(directory, { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const filename = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw Error("Physical recall evidence contains a symbolic link");
      if (entry.isDirectory()) await walk(filename);
      else if (entry.isFile()) result[path.relative(root, filename).split(path.sep).join("/")] = await fs.readFile(filename);
    }
  }
  await walk(root);
  return result;
}

function database(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try {
    db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
    const rows = sql => db.prepare(sql).all().map(row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
      [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
        : typeof value === "bigint" ? { type: "bigint", value: value.toString() } : value])));
    const schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name");
    const tables = Object.fromEntries(schema.filter(row => row.type === "table").map(row =>
      [row.name, rows('SELECT * FROM "' + row.name.replaceAll('"', '""') + '"')]));
    return { schema, tables, transaction: { mode: "deferred", active: db.isTransaction } };
  } finally { if (db.isTransaction) db.exec("ROLLBACK"); db.close(); }
}

async function physical(root) {
  const files = await tree(root), databases = {};
  for (const [relative, payload] of Object.entries(files))
    if (payload.subarray(0, 16).equals(Buffer.from("SQLite format 3\0")))
      databases[relative] = database(path.join(root, relative));
  return { root, files: Object.fromEntries(Object.entries(files).map(([name, payload]) => [name, bytes(payload)])), databases };
}

export async function runRecallSignalsRuntime(input, runtimeConfig) {
  if (input?.kind !== "recall-signals" || !Number.isSafeInteger(input.nowMs) ||
      !Array.isArray(input.operations) || !input.files || !input.store || !Array.isArray(input.tombstones))
    throw Error("Recall signals require their frozen common input");
  for (const name of ["runtimeRoot", "stateDirectory", "configPath", "evidenceDirectory"])
    if (typeof runtimeConfig?.[name] !== "string" || !path.isAbsolute(runtimeConfig[name]))
      throw Error("Recall signals require authenticated absolute runtime paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-recall-signals-"));
  const workspace = path.join(base, "workspace");
  await fs.mkdir(workspace);
  const environment = { OPENCLAW_STATE_DIR: runtimeConfig.stateDirectory,
    OPENCLAW_CONFIG_PATH: runtimeConfig.configPath, OPENCLAW_HOME: base };
  const previous = Object.fromEntries(Object.keys(environment).map(name => [name, process.env[name]]));
  Object.assign(process.env, environment);
  const cfg = { agents: { defaults: { workspace }, list: [{ id: "main", workspace }] },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(base, "native.log") } };
  await fs.mkdir(path.dirname(runtimeConfig.configPath), { recursive: true });
  await fs.writeFile(runtimeConfig.configPath, json(cfg) + "\n");
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input: clone(input), fixtureBase: base, workspace, environment,
    stateDirectory: runtimeConfig.stateDirectory, configPath: runtimeConfig.configPath, config: cfg,
    pid: process.pid, ppid: process.ppid, node: { version: process.version, executable: process.execPath },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    calls: [], codeOwners: [], physical: [], operations: [], closed: false };
  const imp = name => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, name)).href);
  const persist = () => fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), json([raw]) + "\n");
  let config, closeAgents, closeState;
  async function owner(modulePath, exportName, name, fn) {
    if (typeof fn !== "function") throw Error("A pinned recall owner is unavailable: " + name);
    const source = Function.prototype.toString.call(fn);
    raw.codeOwners.push({ name, modulePath, exportName, functionName: fn.name, functionLength: fn.length,
      functionSource: source, functionSourceSha256: hash(source),
      compiledSha256: hash(await fs.readFile(path.join(runtimeConfig.runtimeRoot, modulePath))) });
  }
  async function call(operation, fn, args) {
    const row = { operation, arguments: clone(args) }; raw.calls.push(row);
    try { const value = await fn(...args); row.returnValue = returned(value); return value; }
    catch (error) { row.error = failure(error); throw error; }
  }
  async function capture(label) {
    const value = { fixture: await physical(base), state: await physical(runtimeConfig.stateDirectory),
      config: bytes(await fs.readFile(runtimeConfig.configPath)) };
    const payload = json(value) + "\n", filename = path.join(runtimeConfig.evidenceDirectory, `native-physical-${label}.json`);
    await fs.writeFile(filename, payload);
    raw.physical.push({ path: filename, sha256: hash(payload), uncompressedBytes: Buffer.byteLength(payload),
      encoding: "gzip-json-base64", data: gzipSync(Buffer.from(payload)).toString("base64") });
  }
  try {
    config = await imp("dist/plugin-sdk/config-runtime.js");
    await call("setRuntimeConfigSnapshot", config.setRuntimeConfigSnapshot, [cfg]);
    const dreaming = await imp("dist/dreaming-state-VYUvbU-n.mjs");
    const keyed = await imp("dist/plugin-state-store-BPUaLoVD.mjs");
    dreaming.p(options => keyed.r("memory-core", { ...options, env: environment }));
    const record = await imp("dist/short-term-promotion-record-DrLa1fiO.mjs");
    const store = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
    const origins = await imp("dist/memory-entry-origins-BCQSIB3X.mjs");
    const events = await imp("dist/memory-host-events-C8-U38f1.mjs");
    const ingestion = await imp("dist/session-ingestion-Dy5uAq-_.mjs");
    const agent = await imp("dist/openclaw-agent-db-DRy3ui_B.mjs");
    const schema = await imp("dist/memory-core-host-engine-storage-Dn-n8hud.mjs");
    const agentPaths = await imp("dist/openclaw-agent-db.paths-Dv3PPTNK.mjs");
    closeAgents = (await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s;
    closeState = keyed.u;
    const specs = [
      ["dist/short-term-promotion-record-DrLa1fiO.mjs", "i", "recordShortTermRecalls", record.i],
      ["dist/short-term-promotion-record-DrLa1fiO.mjs", "r", "recordGroundedShortTermCandidates", record.r],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "a", "readStore", store.a],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "l", "writeStore", store.l],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "D", "normalizeMemoryPath", store.D],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "n", "listMemoryEntryOrigins", origins.n],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "r", "listMemorySessionTombstones", origins.r],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "o", "recordMemorySessionTombstonesInDatabase", origins.o],
      ["dist/memory-host-events-C8-U38f1.mjs", "n", "readMemoryHostEventRecords", events.n],
      ["dist/session-ingestion-Dy5uAq-_.mjs", "r", "appendSessionCorpusLines", ingestion.r],
      ["dist/openclaw-agent-db-DRy3ui_B.mjs", "c", "openOpenClawAgentDatabase", agent.c],
      ["dist/memory-core-host-engine-storage-Dn-n8hud.mjs", "t", "ensureMemoryEntryOriginsSchema", schema.t],
      ["dist/openclaw-agent-db.paths-Dv3PPTNK.mjs", "c", "resolveOpenClawAgentSqlitePath", agentPaths.c],
    ];
    for (const spec of specs) await owner(...spec);
    for (const [relative, content] of Object.entries(input.files)) {
      const target = owned(workspace, relative); await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, content, { flag: "wx" });
      raw.calls.push({ operation: "seedLiteralFile", relative, content });
    }
    const originHandle = agent.c({ agentId: "main" });
    const databasePath = agentPaths.c({ agentId: "main" });
    // A native database handle is not JSON data. Describe its actual observed
    // handle identity explicitly; never substitute it for a business return.
    raw.calls.push({ operation: "openOpenClawAgentDatabase", arguments: [{ agentId: "main" }],
      nativeHandleObservation: { path: originHandle.path, agentId: originHandle.agentId,
        databaseConstructor: originHandle.db.constructor.name, isOpen: originHandle.db.isOpen } });
    const ensured = schema.t(originHandle.db);
    raw.calls.push({ operation: "ensureMemoryEntryOriginsSchema", arguments: [{ databasePath, nativeHandle: true }],
      returnValue: returned(ensured) });
    for (const tombstone of input.tombstones) {
      if (tombstone.agentId !== "main") throw Error("Recall tombstone seed escaped the fixed agent");
      const args = { ...tombstone, createdAt: input.nowMs };
      const value = origins.o(originHandle.db, args);
      raw.calls.push({ operation: "recordMemorySessionTombstonesInDatabase",
        arguments: [{ databasePath, nativeHandle: true }, args], returnValue: returned(value) });
    }
    await call("writeStore", store.l, [workspace, clone(input.store)]);
    async function state(nowMs) {
      const nowIso = new Date(nowMs).toISOString();
      return { recall: await call("readStore", store.a, [workspace, nowIso]),
        origins: { main: await call("listMemoryEntryOrigins", origins.n, [{ agentId: "main" }]) },
        tombstones: { main: await call("listMemorySessionTombstones", origins.r, [{ agentId: "main" }]) },
        events: await call("readMemoryHostEventRecords", events.n, [{ workspaceDir: workspace, env: environment }]) };
    }
    async function sources(items) {
      const groups = new Map();
      for (const item of items) {
        const relative = store.D(item.path), ranges = groups.get(relative) ?? [];
        ranges.push({ startLine: item.startLine, endLine: item.endLine }); groups.set(relative, ranges);
      }
      const result = [];
      for (const [relative, ranges] of groups) {
        const filename = owned(workspace, relative);
        let payload, stat;
        try { payload = await fs.readFile(filename); stat = await fs.stat(filename, { bigint: true }); }
        catch (error) { if (error.code !== "ENOENT") throw error; }
        const lines = payload?.toString("utf8").replace(/\r\n/g, "\n").split("\n");
        result.push({ path: relative, absolutePath: filename, exists: Boolean(payload),
          bytes: payload ? bytes(payload) : null, identity: stat ? { device: String(stat.dev), inode: String(stat.ino),
            size: Number(stat.size), mtimeNs: String(stat.mtimeNs), ctimeNs: String(stat.ctimeNs) } : null,
          ranges: ranges.map(range => ({ ...range, lines: lines ? lines.slice(range.startLine - 1, range.endLine) : null })) });
      }
      return result;
    }
    raw.initialState = await state(input.nowMs); await capture("initial");
    const observations = [];
    for (let index = 0; index < input.operations.length; index++) {
      const operation = input.operations[index]; mock.timers.setTime(operation.nowMs);
      const actual = { operation: clone(operation) }; raw.operations.push(actual);
      const observed = { operation: clone(operation), completed: false };
      let db;
      try {
        let items = operation.op === "recall" ? operation.results : operation.items;
        if (operation.op === "append-grounded") {
          const relative = "memory/.dreams/session-corpus/" + operation.append.day + ".txt";
          const requests = [{ path: relative, startLine: 1, endLine: 1 }];
          actual.producer = { owner: "appendSessionCorpusLines", arguments: { workspaceDir: workspace, ...clone(operation.append) },
            sourcesBefore: await sources(requests) };
          items = await call("appendSessionCorpusLines", ingestion.r, [actual.producer.arguments]);
          actual.producer.returnValue = returned(items);
          actual.producer.sourcesAfter = await sources(items);
        }
        if (!Array.isArray(items)) throw Error("An undeclared recall operation reached its owner");
        const args = { workspaceDir: workspace, nowMs: operation.nowMs, timezone: input.timezone, query: operation.query };
        for (const field of ["dedupeByQueryPerDay", "dayBucket", "signalType"])
          if (Object.hasOwn(operation, field)) args[field] = operation[field];
        if (operation.op === "recall") args.results = items; else args.items = items;
        actual.arguments = clone(args); actual.sourcesBefore = await sources(items);
        if (operation.failOrigins) {
          const filename = agentPaths.c({ agentId: "main" }); db = new DatabaseSync(filename);
          db.exec(TRIGGER_SQL);
          actual.trigger = { name: TRIGGER, statement: TRIGGER_SQL, databasePath: filename,
            schemaBeforeDispatch: db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all() };
        }
        const fn = operation.op === "recall" ? record.i : record.r;
        const result = await call(operation.op === "recall" ? "recordShortTermRecalls" : "recordGroundedShortTermCandidates", fn, [args]);
        actual.returnValue = returned(result); observed.completed = true;
      } catch (error) { actual.error = failure(error); }
      try {
        observed.state = await state(operation.nowMs);
        actual.observed = clone(observed);
        const args = actual.arguments;
        actual.sourcesAfter = args ? await sources(args.results ?? args.items) : [];
        await capture(String(index));
      } finally {
        if (db) {
          db.exec("DROP TRIGGER " + TRIGGER);
          actual.trigger.afterDropSchema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
          db.close();
        }
      }
      observations.push(observed);
    }
    const result = { before: raw.initialState, observations };
    raw.output = clone(result);
    return result;
  } catch (error) { raw.error = failure(error); throw error; }
  finally {
    try {
      await closeAgents?.(); await closeState?.(); config?.clearRuntimeConfigSnapshot(); raw.closed = true;
    } finally {
      await persist(); mock.timers.reset();
      for (const [name, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[name]; else process.env[name] = value;
      }
    }
  }
}
