// Six input-only diagnostics over the published CLI and durable state owners.
// This fixture supplies facts, never deletion, admission or persistence outcomes.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";

const STATE_PATHS = new Set([
  "memory/.dreams/short-term-recall.json", "memory/.dreams/phase-signals.json",
  "memory/.dreams/consolidation-preimages.json", "memory/.dreams/session-ingestion.json",
]);
const hash = value => createHash("sha256").update(value).digest("hex");
const clone = value => JSON.parse(JSON.stringify(value));
const failure = error => ({ name: error.name, message: error.message });
const returned = value => value === undefined ? { type: "undefined" } :
  { type: typeof value, value: clone(value) };
const json = value => JSON.stringify(value, (_key, item) =>
  typeof item === "bigint" ? { type: "bigint", value: item.toString() } : item);
const bytes = value => ({ hex: value.toString("hex"), sha256: hash(value), size: value.length });

function owned(root, relative) {
  if (typeof relative !== "string" || !relative || relative.includes("\\") ||
      path.posix.isAbsolute(relative) || path.posix.normalize(relative) !== relative ||
      relative.split("/").some(part => part === ".." || part === "."))
    throw Error("A diagnostic fixture path must be canonical and owned");
  const target = path.resolve(root, relative);
  if (!target.startsWith(path.resolve(root) + path.sep)) throw Error("A fixture escaped its owner");
  return target;
}

async function tree(root) {
  const result = {};
  async function walk(directory) {
    let entries;
    try { entries = await fs.readdir(directory, { withFileTypes: true }); }
    catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const absolute = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw Error("A bounded fixture unexpectedly contains a symlink");
      if (entry.isDirectory()) await walk(absolute);
      else if (entry.isFile()) result[path.relative(root, absolute).split(path.sep).join("/")] = await fs.readFile(absolute);
      else throw Error("A bounded fixture unexpectedly contains a special file");
    }
  }
  await walk(root);
  return result;
}

function database(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  const sqlValue = value => value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value;
  const rows = query => db.prepare(query).all().map(row =>
    Object.fromEntries(Object.entries(row).map(([key, value]) => [key, sqlValue(value)])));
  try {
    db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
    const schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name");
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

export async function runForgetLineageRuntime(input, runtimeConfig) {
  if (input.kind !== "forget-lineage-tombstones" || !Number.isSafeInteger(input.nowMs) ||
      !Array.isArray(input.operations) || Object.hasOwn(input, "tombstones"))
    throw Error("The six-case forget lineage profile requires its exact common input");
  for (const name of ["runtimeRoot", "stateDirectory", "configPath", "evidenceDirectory"])
    if (typeof runtimeConfig?.[name] !== "string" || !path.isAbsolute(runtimeConfig[name]))
      throw Error("Forget lineage requires authenticated absolute runtime context paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-forget-lineage-"));
  const workspace = path.join(base, "workspace");
  await fs.mkdir(workspace);
  const agents = [...new Set([input.agentId, ...input.sessions.map(item => item.agentId),
    ...input.origins.map(item => item.agentId)])].sort();
  for (const agent of agents) if (!/^[a-z0-9_-]+$/.test(agent)) throw Error("Nonliteral agent scope");
  const previous = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME"].map(name => [name, process.env[name]]));
  Object.assign(process.env, { OPENCLAW_STATE_DIR: runtimeConfig.stateDirectory,
    OPENCLAW_CONFIG_PATH: runtimeConfig.configPath, OPENCLAW_HOME: base });
  const cfg = { agents: { defaults: { workspace }, list: agents.map(id => ({ id, workspace })) },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(base, "native.log") },
    session: { maintenance: { mode: "warn" } },
    memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory", "sessions"],
      rememberAcrossConversations: true, experimental: { sessionMemory: true }, store: { vector: { enabled: false } } } } };
  await fs.mkdir(path.dirname(runtimeConfig.configPath), { recursive: true });
  await fs.writeFile(runtimeConfig.configPath, json(cfg) + "\n");
  const originalDate = Date, originalTimeout = setTimeout, originalPerformanceNow = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input: clone(input), fixtureBase: base, workspace,
    stateDirectory: runtimeConfig.stateDirectory, configPath: runtimeConfig.configPath, config: cfg,
    pid: process.pid, ppid: process.ppid, node: { version: process.version, executable: process.execPath },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate,
      setTimeoutUnchanged: setTimeout === originalTimeout, performanceNowUnchanged: performance.now === originalPerformanceNow },
    calls: [], codeOwners: [], physical: [], operations: [], closed: false };
  const persist = () => fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), json([raw]) + "\n");
  const imp = name => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, name)).href);
  let config, closeAgents, closeState;
  async function owner(modulePath, exportName, name, fn) {
    if (typeof fn !== "function") throw Error("A pinned original owner is unavailable: " + name);
    const source = Function.prototype.toString.call(fn);
    raw.codeOwners.push({ name, modulePath, exportName, functionName: fn.name, functionLength: fn.length,
      functionSource: source, functionSourceSha256: hash(source),
      compiledSha256: hash(await fs.readFile(path.join(runtimeConfig.runtimeRoot, modulePath))) });
    return fn;
  }
  async function capture(label) {
    const record = { fixture: await physical(base), state: await physical(runtimeConfig.stateDirectory),
      config: bytes(await fs.readFile(runtimeConfig.configPath)) };
    const filename = path.join(runtimeConfig.evidenceDirectory, `native-physical-${label}.json`);
    const payload = json(record) + "\n";
    await fs.writeFile(filename, payload);
    // The oracle removes its owned tree on close; the raw transport must carry
    // the complete bytes and SQL rows itself, not only a temporary file receipt.
    raw.physical.push({ path: filename, sha256: hash(payload), snapshot: record });
  }
  async function call(name, fn, args) {
    const record = { operation: name, arguments: clone(args) }; raw.calls.push(record);
    try { const value = await fn(...args); record.returnValue = returned(value); return value; }
    catch (error) { record.error = failure(error); throw error; }
  }
  try {
    config = await imp("dist/plugin-sdk/config-runtime.js");
    await call("setRuntimeConfigSnapshot", config.setRuntimeConfigSnapshot, [cfg]);
    const api = await imp("dist/extensions/memory-core/runtime-api.js");
    const keyed = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    api.configureMemoryCoreDreamingState(options => keyed.createPluginStateKeyedStore("memory-core", options));
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
    const participants = await imp("dist/session-sharing-store.native-BimL-D2p.mjs");
    const origins = await imp("dist/memory-entry-origins-BCQSIB3X.mjs");
    const store = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
    const ingestion = await imp("dist/dreaming-ingestion-state-licbtf_y.mjs");
    const artifacts = await imp("dist/short-term-promotion-MX1vHJuE.mjs");
    const dreaming = await imp("dist/dreaming-state-VYUvbU-n.mjs");
    const corpus = await imp("dist/session-files-DVVT4Ngb.mjs");
    const admission = await imp("dist/session-ingestion-Dy5uAq-_.mjs");
    const record = await imp("dist/short-term-promotion-record-DrLa1fiO.mjs");
    const cli = await imp("dist/cli.runtime-CVRN4xUp.mjs");
    const runtimeIO = (await imp("dist/runtime-BC29JSZp.mjs")).r;
    const originalWriteJson = runtimeIO.writeJson;
    closeAgents = (await imp("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs")).s;
    closeState = (await imp("dist/openclaw-state-db-cache-IdIaBoUp.mjs")).a;
    const specs = [
      ["dist/cli.runtime-CVRN4xUp.mjs", "runMemoryForget", "runMemoryForget", cli.runMemoryForget],
      ["dist/runtime-BC29JSZp.mjs", "r.writeJson", "defaultRuntime.writeJson", originalWriteJson],
      ["dist/plugin-sdk/session-store-runtime.js", "upsertSessionEntry", "upsertSessionEntry", sessions.upsertSessionEntry],
      ["dist/session-accessor-CiKKTlbe.mjs", "replaceTranscriptEventsSync", "replaceTranscriptEventsSync", accessor.replaceTranscriptEventsSync],
      ["dist/session-accessor-CiKKTlbe.mjs", "loadTranscriptEventsSync", "loadTranscriptEventsSync", accessor.loadTranscriptEventsSync],
      ["dist/session-sharing-store.native-BimL-D2p.mjs", "i", "recordSessionParticipant", participants.i],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "a", "recordMemoryEntryOrigins", origins.a],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "n", "listMemoryEntryOrigins", origins.n],
      ["dist/memory-entry-origins-BCQSIB3X.mjs", "r", "listMemorySessionTombstones", origins.r],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "a", "readStore", store.a],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "l", "writeStore", store.l],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "r", "readPhaseSignalStore", store.r],
      ["dist/short-term-promotion-store-B6T388Bo.mjs", "c", "writePhaseSignalStore", store.c],
      ["dist/dreaming-ingestion-state-licbtf_y.mjs", "l", "readSessionIngestionState", ingestion.l],
      ["dist/dreaming-ingestion-state-licbtf_y.mjs", "d", "writeSessionIngestionState", ingestion.d],
      ["dist/short-term-promotion-MX1vHJuE.mjs", "o", "readMemoryPreimages", artifacts.o],
      ["dist/dreaming-state-VYUvbU-n.mjs", "b", "writeMemoryCoreWorkspaceEntries", dreaming.b],
      ["dist/session-files-DVVT4Ngb.mjs", "l", "listSessionTranscriptCorpusEntriesForAgent", corpus.l],
      ["dist/session-ingestion-Dy5uAq-_.mjs", "u", "sessionIngestionSourceFromCorpus", admission.u],
      ["dist/session-ingestion-Dy5uAq-_.mjs", "l", "sessionExclusionReason", admission.l],
      ["dist/short-term-promotion-record-DrLa1fiO.mjs", "r", "recordGroundedShortTermCandidates", record.r],
    ];
    for (const spec of specs) await owner(...spec);
    for (const [relative, content] of Object.entries(input.files)) {
      const target = owned(workspace, relative); await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, content, { flag: "wx" });
      raw.calls.push({ operation: "seedLiteralFile", relative, content });
    }
    for (const agentId of agents) {
      const facts = input.origins.filter(item => item.agentId === agentId);
      if (facts.length) await call("recordMemoryEntryOrigins", origins.a, [{ agentId, origins: clone(facts) }]);
    }
    for (const item of input.sessions) {
      const scope = { agentId: item.agentId, sessionId: item.sessionId, sessionKey: item.sessionKey,
        storePath: sessions.resolveStorePath(undefined, { agentId: item.agentId }) };
      const entry = { sessionId: item.sessionId, sessionStartedAt: item.createdAt, updatedAt: input.nowMs, delivery: { kind: "none" } };
      if (Object.hasOwn(item, "hookExternalContentSource")) entry.hookExternalContentSource = item.hookExternalContentSource;
      await call("upsertSessionEntry", sessions.upsertSessionEntry, [{ ...scope, entry }]);
      const events = [{ type: "session", id: item.sessionId }, ...item.messages.map(message => ({ type: "message", message: clone(message) }))];
      if (await call("replaceTranscriptEventsSync", accessor.replaceTranscriptEventsSync, [scope, events]) !== true)
        throw Error("The actual session transcript replacement did not commit");
      for (const identity of item.participants ?? [])
        await call("recordSessionParticipant", participants.i, [scope, { identity: clone(identity), promptedAt: input.nowMs, sessionAgentId: item.agentId }]);
      const actualEvents = await call("loadTranscriptEventsSync", accessor.loadTranscriptEventsSync, [scope]);
      if (!Array.isArray(actualEvents)) throw Error("An actual persisted transcript is unavailable");
      const filename = path.join(path.dirname(scope.storePath), item.sessionId + ".jsonl");
      await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, actualEvents.map(event => json(event) + "\n").join(""));
      raw.calls.push({ operation: "exportActualTranscript", scope, filename, events: actualEvents });
    }
    if (input.recall) await call("writeStore", store.l, [workspace, clone(input.recall)]);
    if (input.phase) await call("writePhaseSignalStore", store.c, [workspace, clone(input.phase)]);
    if (input.ingestion) await call("writeSessionIngestionState", ingestion.d, [workspace, clone(input.ingestion)]);
    if (input.preimages) await call("writeMemoryCoreWorkspaceEntries", dreaming.b, [{ workspaceDir: workspace,
      namespace: dreaming.n, entries: input.preimages.map(value => ({
        key: `${value.createdAt}:${value.contentHash.slice(0, 12)}`, value: clone(value) })) }]);
    const nowIso = new Date(input.nowMs).toISOString();
    async function state() {
      const files = await tree(workspace);
      return { files: Object.fromEntries(Object.entries(files).filter(([name]) => !STATE_PATHS.has(name))
          .map(([name, payload]) => [name, payload.toString("utf8")])),
        recall: await store.a(workspace, nowIso), phase: await store.r(workspace, nowIso),
        preimages: await artifacts.o(workspace), ingestion: await ingestion.l(workspace),
        origins: Object.fromEntries(agents.map(agentId => [agentId, origins.n({ agentId })])),
        tombstones: Object.fromEntries(agents.map(agentId => [agentId, origins.r({ agentId })])) };
    }
    raw.initialState = await state(); await capture("initial"); await persist();
    const observations = [];
    for (const [number, operation] of input.operations.entries()) {
      const observed = { operation: clone(operation), error: null, report: null, replay: null };
      const privateOperation = { operation: clone(operation) }; raw.operations.push(privateOperation);
      try {
        if (operation.op === "forget") {
          const opts = { agent: input.agentId, session: operation.sessionIds, hookSource: operation.hookSources,
            participant: operation.participants, since: operation.since, dryRun: operation.dryRun, json: true };
          const stdout = [], stderr = [], stdoutWrite = process.stdout.write, stderrWrite = process.stderr.write;
          privateOperation.arguments = clone(opts);
          process.stdout.write = function (chunk, ...args) {
            stdout.push(typeof chunk === "string" ? Buffer.from(chunk, typeof args[0] === "string" ? args[0] : undefined) : Buffer.from(chunk));
            return stderrWrite.call(process.stderr, chunk, ...args);
          };
          process.stderr.write = function (chunk, ...args) {
            stderr.push(typeof chunk === "string" ? Buffer.from(chunk, typeof args[0] === "string" ? args[0] : undefined) : Buffer.from(chunk));
            return stderrWrite.call(this, chunk, ...args);
          };
          try { privateOperation.returnValue = returned(await cli.runMemoryForget(opts)); }
          finally {
            process.stdout.write = stdoutWrite; process.stderr.write = stderrWrite;
            privateOperation.stdout = { ...bytes(Buffer.concat(stdout)), text: Buffer.concat(stdout).toString("utf8") };
            privateOperation.stderr = { ...bytes(Buffer.concat(stderr)), text: Buffer.concat(stderr).toString("utf8") };
            privateOperation.originalWriteJsonUnchanged = runtimeIO.writeJson === originalWriteJson;
          }
          if (!privateOperation.originalWriteJsonUnchanged) throw Error("Original CLI report owner changed");
          observed.report = JSON.parse(privateOperation.stdout.text);
          if (!observed.report || typeof observed.report !== "object" || Array.isArray(observed.report))
            throw Error("The complete actual CLI output was not a JSON report object");
        } else if (operation.op === "reopen") {
          await call("closeOpenClawAgentDatabasesAsync", closeAgents, []);
          await call("closeOpenClawStateDatabaseAsync", closeState, []);
        } else if (operation.op === "replay") {
          const decisions = [], actualAdmissions = [];
          for (const agentId of operation.agentIds) {
            const entries = await call("listSessionTranscriptCorpusEntriesForAgent", corpus.l, [agentId, { includeRetainedSqlite: true }]);
            for (const entry of entries) {
              const source = admission.u(entry);
              if (!source) throw Error("A literal interactive session has no actual ingestion source");
              const reason = admission.l(source);
              decisions.push({ agentId, sessionId: entry.sessionId, reason: reason ?? null });
              actualAdmissions.push({ entry, source, arguments: [source], returnValue: returned(reason) });
            }
          }
          const before = await store.a(workspace, nowIso), backfill = operation.backfill;
          const params = { workspaceDir: workspace, query: "__dreaming_session_backfill__:" + backfill.day,
            items: backfill.results.map(item => ({ ...clone(item), dayBucket: backfill.day })),
            dedupeByQueryPerDay: true, nowMs: input.nowMs, timezone: input.timezone };
          const result = await call("recordGroundedShortTermCandidates", record.r, [params]);
          const after = await store.a(workspace, nowIso);
          observed.replay = { admission: decisions, backfill: { returnValue: returned(result),
            beforeCount: Object.keys(before.entries).length, afterCount: Object.keys(after.entries).length } };
          privateOperation.replay = { admission: actualAdmissions, backfill: { arguments: params, returnValue: returned(result) } };
        } else throw Error("Unknown frozen forget lineage diagnostic operation");
      } catch (error) { observed.error = failure(error); privateOperation.error = failure(error); }
      observed.state = await state(); observations.push(observed);
      privateOperation.observed = clone(observed);
      await capture(String(number)); await persist();
    }
    return { kind: input.kind, provider: "none", acceptancePointsAwarded: 0, observations };
  } finally {
    try { if (closeAgents) await call("closeOpenClawAgentDatabasesAsync", closeAgents, []); }
    finally {
      try { if (closeState) await call("closeOpenClawStateDatabaseAsync", closeState, []); }
      finally {
        raw.closed = true;
        try { await persist(); }
        finally {
          config?.clearRuntimeConfigSnapshot(); mock.timers.reset();
          for (const [name, value] of Object.entries(previous))
            if (value === undefined) delete process.env[name]; else process.env[name] = value;
        }
      }
    }
  }
}
