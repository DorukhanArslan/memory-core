// Fixture IO and observations only. All apply/store/lease decisions are original.
import fs from "node:fs/promises";
import { callObservers } from "./promotion-apply-family-observers.mjs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { modelRuntimeIdentity, modelError } from "./model-runtime-observation.mjs";
const OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID = "memory-core";

const CASE_HASHES = {
  "promotion-apply-authoritative-store-and-moved-source": "f8cfb6b12c5b22438dcab17420e781969753a9dac768943b0771d89560da25a4",
  "promotion-apply-mixed-authoritative-rejection-receipts": "035445f91f34c49149d3a5db914ad241b95fef15fc3083e45db80a4b6abf7f46",
  "promotion-apply-daily-file-quarantine": "962d7b1b414e4687ab0fbb2a3163cae9e014a8a6de6e0f3cb3243a4c76c3ef20",
  "promotion-apply-direct-candidate-without-stored-entry": "1efb4565c7a6eaa9c0ea9d42541922256701ace47f1bce0d4f3f38e5d34bc834",
  "promotion-apply-prelock-store-change": "4f55f99f9430a4f688ad1c7ac9dcbf626db7bec694a5384f4ca5396c5e1bc956",
  "promotion-apply-prelock-source-change": "d848b8b374976c8398de4c397ab9ea0e576ca3385ca035b10ec07c1885e781f9",
  "promotion-apply-prelock-marker-reconciliation": "62954ad5591378a27eaa48747268213b3148d43baa0583a7f1f4a6d3b9af5105",
  "promotion-apply-add-only-preimage-origin-and-dreams-publication": "c4fb4bbac7df8a72ea601527332e6035b53dd3cb37244607f8689669a27af231"
};
const stable = value => Array.isArray(value) ? value.map(stable) : value !== null && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
const hash = value => createHash("sha256").update(value).digest("hex");
const sqlValue = value => value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
  : typeof value === "bigint" ? { type: "bigint", value: value.toString() } : value;

async function tree(root) {
  const result = [];
  async function visit(filename) {
    const info = await fs.lstat(filename, { bigint: true });
    const kind = info.isDirectory() ? "directory" : info.isFile() ? "file" : info.isSymbolicLink() ? "symlink" : "other";
    const observation = { path: filename, kind, mode: Number(info.mode), dev: info.dev.toString(), ino: info.ino.toString(),
      nlink: info.nlink.toString(), size: info.size.toString(), atimeNs: info.atimeNs.toString(),
      mtimeNs: info.mtimeNs.toString(), ctimeNs: info.ctimeNs.toString(), birthtimeNs: info.birthtimeNs.toString(),
      rawStat: Object.fromEntries(Object.getOwnPropertyNames(info).map(key =>
        [key, typeof info[key] === "bigint" ? info[key].toString() : info[key]])) };
    if (kind === "file") observation.bytes = (await fs.readFile(filename)).toString("hex");
    if (kind === "symlink") observation.target = await fs.readlink(filename);
    result.push(observation);
    if (kind === "directory") for (const name of (await fs.readdir(filename)).sort()) await visit(path.join(filename, name));
  }
  await visit(root);
  return result;
}

async function physical(root) {
  const filenames = [];
  async function visit(directory) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(filename);
      else if (entry.isFile() && filename.endsWith(".sqlite")) filenames.push(filename);
    }
  }
  await visit(root);
  return filenames.sort().map(filename => {
    const db = new DatabaseSync(filename, { readOnly: true });
    try {
      db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
      const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
      const result = { path: filename, schema, schemaCount: db.prepare("SELECT COUNT(*) AS count FROM sqlite_schema").get().count,
        snapshotTransaction: { mode: "deferred", active: db.isTransaction },
        tables: schema.filter(row => row.type === "table").map(row => {
          const quoted = '"' + row.name.replaceAll('"', '""') + '"';
          return { name: row.name, columns: db.prepare(`PRAGMA table_info(${quoted})`).all(),
            rowCount: db.prepare(`SELECT COUNT(*) AS count FROM ${quoted}`).get().count,
            rows: db.prepare(`SELECT * FROM ${quoted}`).all().map(value => Object.fromEntries(
              Object.entries(value).map(([key, item]) => [key, sqlValue(item)]))) };
        }) };
      db.exec("ROLLBACK");
      return result;
    } finally { db.close(); }
  });
}

async function documents(workspace, names) {
  const result = [];
  for (const relative of new Set([...names, "MEMORY.md", "DREAMS.md"])) {
    const filename = path.join(workspace, relative);
    let info;
    try { info = await fs.lstat(filename); }
    catch (error) {
      if (error.code !== "ENOENT") throw error;
      result.push({ path: relative, exists: false, kind: "missing" }); continue;
    }
    const kind = info.isDirectory() ? "directory" : info.isFile() ? "file" : info.isSymbolicLink() ? "symlink" : "other";
    const observation = { path: relative, exists: true, kind };
    if (kind === "file") {
      const bytes = await fs.readFile(filename);
      Object.assign(observation, { bytes: bytes.toString("hex"), text: bytes.toString("utf8") });
    }
    if (kind === "symlink") observation.target = await fs.readlink(filename);
    result.push(observation);
  }
  return result;
}

function mapPaths(value, prefix) {
  if (typeof value === "string") return value === prefix ? "$FIXTURE" : value.replaceAll(prefix + "/", "$FIXTURE/");
  if (Array.isArray(value)) return value.map(item => mapPaths(item, prefix));
  return value !== null && typeof value === "object"
    ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, mapPaths(item, prefix)])) : value;
}

export async function runPromotionApplyFamily(testCase, runtimeConfig) {
  const input = testCase.input;
  if (testCase.operation !== "promotion-apply-family-runtime" || !Object.hasOwn(CASE_HASHES, testCase.id) ||
      hash(JSON.stringify(stable({ id: testCase.id, operation: testCase.operation, input }))) !== CASE_HASHES[testCase.id] ||
      !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") || !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "")) {
    throw Error("Apply requires its exact reviewed literal input and authenticated absolute owned roots");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const root = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-promotion-apply-"));
  const workspace = path.join(root, "workspace");
  const environment = { OPENCLAW_STATE_DIR: path.join(root, "state"), OPENCLAW_CONFIG_PATH: path.join(root, "openclaw.json"),
    OPENCLAW_HOME: root };
  const previous = Object.fromEntries(Object.keys(environment).map(key => [key, process.env[key]]));
  Object.assign(process.env, environment);
  await fs.mkdir(workspace);
  const config = { agents: { defaults: { workspace }, list: [{ id: "main", workspace }] },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(root, "native.log") } };
  await fs.writeFile(environment.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input: structuredClone(input), fixtureBase: root, workspace,
    pid: process.pid, ppid: process.ppid, runtime: modelRuntimeIdentity(), environment, config,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    ioReceipts: [], setup: [], factoryCalls: [], calls: [], snapshots: [], completions: [], closed: false };
  const imp = name => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, name)).href);
  const observer = callObservers(raw.ioReceipts);
  let close;
  try {
    const binding = (await imp("../@openclaw/fs-safe/dist/native.js")).getNativeBinding();
    if (!binding) throw Error("The original fs-safe native backend is required");
    raw.observedBindingMethods = Object.keys(binding).filter(name => typeof binding[name] === "function");
    observer.observeBinding(binding);
    for (const relative of input.directories) {
      const filename = path.join(workspace, relative);
      const returned = await fs.mkdir(filename, { recursive: true });
      raw.setup.push({ operation: "mkdir", path: filename, recursive: true,
        ...(returned === undefined ? { returnedUndefined: true } : { result: returned }) });
    }
    for (const [relative, text] of Object.entries(input.files)) {
      const filename = path.join(workspace, relative); await fs.mkdir(path.dirname(filename), { recursive: true });
      const returned = await fs.writeFile(filename, text);
      raw.setup.push({ operation: "writeFile", path: filename, text, returnedUndefined: returned === undefined });
    }
    const dreaming = await imp("dist/dreaming-state-VYUvbU-n.mjs");
    const keyed = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    close = (await imp("dist/plugin-state-store-BPUaLoVD.mjs")).u;
    const configured = dreaming.p(options => {
      const selectedOptions = { ...options, env: environment };
      const selected = keyed.createPluginStateKeyedStore(OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID, selectedOptions);
      raw.factoryCalls.push({ pluginId: OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID, options: structuredClone(options),
        selectedOptions: structuredClone(selectedOptions), returnedMethods: Object.keys(selected) });
      return observer.observeStore(selected, options.namespace);
    });
    raw.calls.push({ operation: "configureMemoryCoreDreamingState", returnedUndefined: configured === undefined });
    const recall = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
    const paths = await imp("dist/openclaw-state-db.paths-rJI64Ab5.mjs");
    const events = await imp("dist/memory-host-events-C8-U38f1.mjs");
    const apply = (await imp("dist/short-term-promotion-MX1vHJuE.mjs")).a;
    raw.databasePath = paths.s(environment);
    const seed = structuredClone(input.recall);
    const write = { operation: "writeStore", workspaceDir: workspace, argumentBefore: structuredClone(seed) };
    raw.calls.push(write); const written = await recall.l(workspace, seed);
    Object.assign(write, { argumentAfter: structuredClone(seed), returnedUndefined: written === undefined });
    for (const entry of input.artifactProvenanceWrites ?? []) {
      const request = { workspaceDir: workspace, ...entry };
      const rollback = await (await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs")).a(request);
      raw.calls.push({ operation: "recordMemoryArtifactWriteProvenance", request,
        returnedType: typeof rollback });
    }
    const names = [...new Set([...Object.keys(input.files), ...input.candidates.map(candidate => candidate.path),
      ...Object.values(input.recall.entries).map(entry => entry.path)])];
    async function snapshot(label) {
      const observed = { label, fsTree: await tree(root), physical: await physical(root) };
      raw.snapshots.push(observed); return observed;
    }
    async function read(label) {
      const docs = await documents(workspace, names);
      const nowIso = new Date(input.nowMs).toISOString();
      const physicalStore = await recall.i(workspace, "recall", nowIso);
      raw.calls.push({ operation: "readShortTermStore", label, workspaceDir: workspace, kind: "recall",
        nowIso, result: structuredClone(physicalStore) });
      const normalized = recall.k(physicalStore, nowIso);
      raw.calls.push({ operation: "normalizeShortTermRecallStore", label, input: structuredClone(physicalStore),
        nowIso, result: structuredClone(normalized) });
      const inputBefore = structuredClone(normalized);
      const retention = recall._(normalized);
      raw.calls.push({ operation: "enforceShortTermRecallStoreRetention", label, inputBefore,
        result: structuredClone(normalized), returned: retention });
      const stored = await recall.a(workspace, nowIso);
      raw.calls.push({ operation: "readStore", label, workspaceDir: workspace, nowIso, result: structuredClone(stored) });
      const eventRecords = await events.n({ workspaceDir: workspace, env: environment });
      raw.calls.push({ operation: "readMemoryHostEventRecords", label, request: { workspaceDir: workspace, env: environment },
        result: structuredClone(eventRecords) });
      return { documents: docs, recall: stored, eventRecords };
    }
    const before = await read("before"); await snapshot("before");
    const request = { workspaceDir: workspace, nowMs: input.nowMs, candidates: structuredClone(input.candidates), ...input.options };
    if (input.completion) {
      request.consolidation = { logger: {
        info: (...args) => raw.calls.push({ operation: "logger.info", args }),
        warn: (...args) => raw.calls.push({ operation: "logger.warn", args }),
      }, subagent: { complete: async argument => {
        const invocation = observer.begin("host.complete", [argument]);
        const entry = { request: structuredClone(argument), mutations: [] }; raw.completions.push(entry);
        for (const mutation of input.completion.mutationsBeforeReturn) {
          let result;
          if (mutation.operation === "write-recall-store") result = await recall.l(workspace, structuredClone(mutation.value));
          else if (mutation.operation === "write-file") result = await fs.writeFile(path.join(workspace, mutation.path), mutation.text);
          else if (mutation.operation === "append-file") result = await fs.appendFile(path.join(workspace, mutation.path), mutation.text);
          else throw Error("Unsupported literal host mutation");
          entry.mutations.push({ input: structuredClone(mutation), returnedUndefined: result === undefined });
        }
        const result = { text: input.completion.text }; entry.result = structuredClone(result);
        observer.end("host.complete", invocation, result); return result;
      } } };
    }
    const call = { operation: "applyShortTermPromotions", request: { ...structuredClone({ ...request, consolidation: undefined }),
      ...(request.consolidation ? { consolidation: { subagent: { complete: "literal host callback" }, logger: "observed" } } : {}) } }; raw.calls.push(call);
    let outcome;
    observer.start();
    try { const result = await apply(request); call.result = structuredClone(result); outcome = { result }; }
    catch (error) { call.error = modelError(error); outcome = { error: call.error }; }
    observer.stop();
    call.requestAfter = structuredClone({ ...request, consolidation: undefined });
    await snapshot("settlement-before-readback");
    const after = await read("after"); await snapshot("after-readback");
    const publicResult = mapPaths({ provider: "none", outcome, before, after,
      completionCalls: raw.completions.map(({ request, result }) => ({ request, result })) }, root);
    raw.output = structuredClone(publicResult);
    return publicResult;
  } catch (error) { raw.observationError = modelError(error); throw error; }
  finally {
    observer.restore();
    try {
      if (close) {
        const returned = await close();
        raw.calls.push({ operation: "closePluginStateStoreSqliteHandles",
          ...(returned === undefined ? { returnedUndefined: true } : { result: returned }) });
      }
      raw.closed = true;
    }
    finally {
      await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
      mock.timers.reset();
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
  }
}
