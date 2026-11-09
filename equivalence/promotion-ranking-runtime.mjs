// Original rank/store owners only. The caller supplies literal stored signals;
// this adapter supplies no scoring, eligibility, sorting or candidate fields.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { modelRuntimeIdentity } from "./model-runtime-observation.mjs";

function physical(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try {
    db.exec("PRAGMA query_only=ON; BEGIN DEFERRED");
    const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
    const snapshot = { schema, schemaCount: db.prepare("SELECT COUNT(*) AS count FROM sqlite_schema").get().count,
      tables: schema.filter(row => row.type === "table").map(row => {
        const name = '"' + row.name.replaceAll('"', '""') + '"';
        return { name: row.name, columns: db.prepare(`PRAGMA table_info(${name})`).all(),
          rowCount: db.prepare(`SELECT COUNT(*) AS count FROM ${name}`).get().count,
          rows: db.prepare(`SELECT * FROM ${name}`).all().map(value => Object.fromEntries(Object.entries(value).map(
            ([key, item]) => [key, item instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(item).toString("hex") }
              : typeof item === "bigint" ? { type: "bigint", value: item.toString() } : item]))) };
      }), snapshotTransaction: { mode: "deferred", active: db.isTransaction } };
    db.exec("ROLLBACK");
    return snapshot;
  } finally { db.close(); }
}

export async function runPromotionRankingRuntime(input, runtimeConfig) {
  if (input?.kind !== "promotion-ranking" || !Number.isFinite(input.nowMs) ||
      !Number.isFinite(new Date(input.nowMs).getTime()) || !Array.isArray(input.queries) ||
      !input.store || !input.phase || !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") ||
      !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "")) {
    throw Error("Promotion ranking requires literal stores, requests, clock and authenticated owned runtime roots");
  }
  for (const query of input.queries) {
    if (typeof query?.label !== "string" || !query.options || typeof query.options !== "object" ||
        Array.isArray(query.options) || Object.hasOwn(query.options, "workspaceDir") || Object.hasOwn(query.options, "nowMs")) {
      throw Error("A ranking request cannot replace the owned workspace or common clock");
    }
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-promotion-ranking-"));
  const workspace = path.join(directory, "workspace");
  const env = { OPENCLAW_STATE_DIR: path.join(directory, "state"),
    OPENCLAW_CONFIG_PATH: path.join(directory, "openclaw.json"), OPENCLAW_HOME: directory };
  const previous = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  await fs.mkdir(workspace);
  await fs.writeFile(env.OPENCLAW_CONFIG_PATH, JSON.stringify({ agents: { defaults: { workspace } } }));
  const originalDate = Date, originalTimeout = setTimeout, originalPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, fixtureBase: directory, workspace, environment: env,
    pid: process.pid, ppid: process.ppid, runtime: modelRuntimeIdentity(), input: structuredClone(input),
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== originalDate,
      setTimeoutUnchanged: setTimeout === originalTimeout, performanceNowUnchanged: performance.now === originalPerformance },
    factoryCalls: [], writes: [], reads: [], rankings: [], snapshots: [], closed: false };
  const imp = filename => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, filename)).href);
  const handles = new Map();
  let close;
  try {
    const store = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
    const keyed = await imp("dist/plugin-state-store-BPUaLoVD.mjs"); close = keyed.u;
    const dreaming = await imp("dist/dreaming-state-VYUvbU-n.mjs");
    const paths = await imp("dist/openclaw-state-db.paths-rJI64Ab5.mjs");
    const rank = (await imp("dist/short-term-promotion-MX1vHJuE.mjs")).t;
    raw.databasePath = paths.s(env);
    dreaming.p(options => {
      const selectedOptions = { ...options, env };
      const selected = keyed.r("memory-core", selectedOptions);
      raw.factoryCalls.push({ pluginId: "memory-core", options: structuredClone(options),
        selectedOptions: structuredClone(selectedOptions), returnedMethods: Object.keys(selected) });
      handles.set(options.namespace, selected);
      return selected;
    });
    const nowIso = new Date(input.nowMs).toISOString();
    async function write(kind, value, invoke) {
      const actual = structuredClone(value);
      const observation = { kind, workspace, argumentBefore: structuredClone(actual) };
      raw.writes.push(observation);
      const result = await invoke(workspace, actual);
      observation.argumentAfter = structuredClone(actual);
      if (result === undefined) observation.returnedUndefined = true;
      else observation.result = result;
    }
    await write("recall", input.store, store.l);
    await write("phase", input.phase, store.c);
    async function read(label) {
      // Capture the original read/normalization owners as well as the complete
      // public readers. This binds logical normalization to physical rows
      // without implementing that normalization in the evidence validator.
      const recallInput = await store.i(workspace, "recall", nowIso);
      const phaseInput = await store.i(workspace, "phase", nowIso);
      const normalizedRecall = store.k(structuredClone(recallInput), nowIso);
      store._(normalizedRecall);
      const normalizedPhase = store.n(structuredClone(phaseInput), nowIso);
      const recall = await store.a(workspace, nowIso), phase = await store.r(workspace, nowIso);
      raw.reads.push({ label, workspace, nowIso, recallInput, phaseInput, normalizedRecall, normalizedPhase, recall, phase });
      const keyedRows = [];
      for (const [namespace, handle] of handles) keyedRows.push({ namespace, entries: await handle.entries() });
      raw.snapshots.push({ label, databasePath: raw.databasePath, keyedRows, physical: physical(raw.databasePath) });
      return { recall, phase };
    }
    const before = await read("before"), queries = [];
    for (const query of input.queries) {
      const request = { ...query.options, workspaceDir: workspace, nowMs: input.nowMs };
      const observation = { label: query.label, request: structuredClone(request) };
      raw.rankings.push(observation);
      const candidates = await rank(request);
      observation.candidates = structuredClone(candidates);
      queries.push({ label: query.label, candidates });
    }
    const after = await read("after");
    const result = { before, queries, after };
    raw.output = structuredClone(result);
    return result;
  } catch (error) {
    raw.error = { name: error?.name, message: error?.message, stack: error?.stack };
    throw error;
  } finally {
    try {
      await close?.(); raw.closed = true;
    } finally {
      await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
      mock.timers.reset();
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
  }
}
