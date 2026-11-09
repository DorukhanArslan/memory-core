// Original memory-budget/promotion owners. No compaction or apply decisions live here.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { mock } from "node:test";
import { createHash } from "node:crypto";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

const errorValue = (error) => ({ name: error.name, message: error.message,
  ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) => !["name", "message"].includes(key))
    .map((key) => [key, key === "cause" && error[key] instanceof Error ? errorValue(error[key]) : error[key]])) });
const sqlValue = (value) => value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") }
  : typeof value === "bigint" ? { type: "bigint", value: value.toString() } : value;

async function allFiles(root) {
  const rows = [];
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const name = path.join(root, entry.name);
    if (entry.isDirectory()) rows.push(...await allFiles(name));
    else if (entry.isFile()) rows.push(name);
    else throw Error("Unexpected nonregular fixture artifact");
  }
  return rows.sort();
}

async function tree(root) {
  const rows = [];
  async function visit(filename) {
    const info = await fs.lstat(filename, { bigint: true });
    rows.push({ path: filename, kind: info.isDirectory() ? "directory" : info.isFile() ? "file" : info.isSymbolicLink() ? "symlink" : "other",
      mode: Number(info.mode), dev: info.dev.toString(), ino: info.ino.toString(), nlink: info.nlink.toString(),
      size: info.size.toString(), mtimeNs: info.mtimeNs.toString(), ctimeNs: info.ctimeNs.toString(),
      ...(info.isSymbolicLink() ? { target: await fs.readlink(filename) } : {}) });
    if (info.isDirectory()) for (const name of (await fs.readdir(filename)).sort()) await visit(path.join(filename, name));
  }
  await visit(root);
  return rows;
}

async function physical(root) {
  const result = [];
  for (const filename of await allFiles(root)) {
    if (!filename.endsWith(".sqlite")) continue;
    const db = new DatabaseSync(filename, { readOnly: true });
    try {
      db.exec("BEGIN");
      const schema = db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();
      const tables = schema.filter((row) => row.type === "table").map(({ name }) => {
        const quoted = '"' + name.replaceAll('"', '""') + '"';
        return { name, columns: db.prepare(`PRAGMA table_info(${quoted})`).all(),
          rowCount: db.prepare(`SELECT COUNT(*) AS count FROM ${quoted}`).get().count,
          rows: db.prepare(`SELECT * FROM ${quoted}`).all().map((row) =>
            Object.fromEntries(Object.entries(row).map(([key, value]) => [key, sqlValue(value)]))) };
      });
      result.push({ path: filename, schema, schemaCount: db.prepare("SELECT COUNT(*) AS count FROM sqlite_schema").get().count,
        snapshotTransaction: { mode: "deferred", active: db.isTransaction }, tables });
      db.exec("ROLLBACK");
    } finally { db.close(); }
  }
  return result;
}

async function documents(workspace, names) {
  const result = [];
  for (const relative of new Set([...names, "MEMORY.md", "DREAMS.md"])) {
    try {
      const content = await fs.readFile(path.join(workspace, relative));
      result.push({ path: relative, exists: true, bytes: content.toString("hex"), text: content.toString("utf8") });
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      result.push({ path: relative, exists: false });
    }
  }
  return result;
}

export async function runMemoryBudgetRuntime(input, runtimeConfig) {
  if (!["memory-budget", "memory-budget-apply"].includes(input.kind) || !Number.isFinite(input.nowMs)
      || !path.isAbsolute(runtimeConfig.runtimeRoot) || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Memory budget requires one explicit profile and owned absolute runtime/evidence roots");
  }
  const fields = input.kind === "memory-budget" ? ["cases", "kind", "nowMs"]
    : ["candidates", "files", "kind", "nowMs", "options", "recall"];
  if (Object.keys(input).sort().join() !== fields.sort().join() || input.kind === "memory-budget-apply" &&
      Object.keys(input.options).sort().join() !== ["timezone", "memoryFileMaxChars", "maxPriorEntryLossFraction", "minScore",
        "minRecallCount", "minUniqueQueries", "limit"].sort().join()) {
    throw Error("The ordinary budget profile cannot borrow model, host or other runtime options");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const root = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-memory-budget-"));
  const previous = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = path.join(root, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(root, "config.json");
  await fs.mkdir(process.env.OPENCLAW_STATE_DIR);
  const config = { logging: { level: "silent", consoleLevel: "silent", file: path.join(root, "native.log") } };
  await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config));
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input: structuredClone(input), fixtureBase: root, pid: process.pid, ppid: process.ppid,
    runtime: { execPath: process.execPath, nodeVersion: process.version, icuVersion: process.versions.icu,
      unicodeVersion: process.versions.unicode, sha256: createHash("sha256").update(await fs.readFile(process.execPath)).digest("hex") },
    config, ownedEnvironment: { OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH: process.env.OPENCLAW_CONFIG_PATH },
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance }, calls: [] };
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let publicResult;
  try {
    if (input.kind === "memory-budget") {
      const budget = await imp("dist/memory-budget-BodJnew-.mjs");
      raw.constants = { defaultMemoryFileMaxChars: budget.t };
      const rows = [];
      for (const item of input.cases) {
        try {
          const result = budget.n(item.params);
          raw.calls.push({ operation: "compactMemoryForBudget", params: item.params, result });
          rows.push({ id: item.id, result });
        } catch (error) {
          raw.calls.push({ operation: "compactMemoryForBudget", params: item.params, error: errorValue(error) });
          rows.push({ id: item.id, error: errorValue(error) });
        }
      }
      publicResult = { provider: "none", defaultMemoryFileMaxChars: budget.t, cases: rows };
    } else {
      const workspace = path.join(root, "workspace");
      await fs.mkdir(workspace);
      for (const [relative, text] of Object.entries(input.files)) {
        if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) throw Error("Literal document escaped owned workspace");
        const filename = path.join(workspace, relative);
        await fs.mkdir(path.dirname(filename), { recursive: true });
        await fs.writeFile(filename, text);
        raw.calls.push({ operation: "write", path: filename, text });
      }
      const state = await imp("dist/dreaming-state-VYUvbU-n.mjs");
      const keyed = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
      raw.keyedStoreRequests = [];
      const configured = state.p((options) => {
        const request = { ...options, env: process.env };
        raw.keyedStoreRequests.push({ pluginId: "memory-core", request: structuredClone(request) });
        return keyed.createPluginStateKeyedStore("memory-core", request);
      });
      raw.calls.push({ operation: "configureMemoryCoreDreamingState", factory: "createPluginStateKeyedStore", pluginId: "memory-core",
        returnedUndefined: configured === undefined });
      const recall = await imp("dist/short-term-promotion-store-B6T388Bo.mjs");
      const seed = structuredClone(input.recall);
      const before = structuredClone(seed);
      const seedReturn = await recall.l(workspace, seed);
      raw.calls.push({ operation: "writeStore", workspaceDir: workspace, valueBefore: before, valueAfter: seed,
        returnedUndefined: seedReturn === undefined });
      const promotion = await imp("dist/short-term-promotion-MX1vHJuE.mjs");
      const request = { workspaceDir: workspace, nowMs: input.nowMs, candidates: input.candidates, ...input.options };
      try {
        const result = await promotion.a(request);
        raw.calls.push({ operation: "applyShortTermPromotions", request, result });
        publicResult = { provider: "none", result };
      } catch (error) {
        raw.calls.push({ operation: "applyShortTermPromotions", request, error: errorValue(error) });
        publicResult = { provider: "none", error: errorValue(error) };
      }
      const events = await imp("dist/memory-host-events-C8-U38f1.mjs");
      const storeResult = await recall.a(workspace, new Date(input.nowMs).toISOString());
      const eventRecords = await events.n({ workspaceDir: workspace, env: process.env });
      raw.calls.push({ operation: "readStore", workspaceDir: workspace, result: storeResult });
      raw.calls.push({ operation: "readMemoryHostEventRecords", workspaceDir: workspace, result: eventRecords });
      publicResult = { ...publicResult, documents: await documents(workspace, Object.keys(input.files)), recall: storeResult, eventRecords };
      raw.physical = await physical(root);
      raw.fsTree = await tree(root);
      raw.files = await Promise.all((await allFiles(root)).map(async (filename) => ({ path: filename,
        bytes: (await fs.readFile(filename)).toString("hex") })));
    }
    return mapGetFixturePaths(publicResult, root);
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    mock.timers.reset();
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const request = JSON.parse(input);
  try {
    const result = await runMemoryBudgetRuntime(request.input, request.runtimeConfig);
    await new Promise((resolve, reject) => process.stdout.write(JSON.stringify({ ok: true, result }), "utf8",
      (error) => error ? reject(error) : resolve()));
  } catch (error) {
    await new Promise((resolve, reject) => process.stdout.write(JSON.stringify({ ok: false, error: errorValue(error) }), "utf8",
      (writeError) => writeError ? reject(writeError) : resolve()));
    process.exitCode = 1;
  }
}
