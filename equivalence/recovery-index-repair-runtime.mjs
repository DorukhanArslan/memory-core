// Drive the published manager. SQLite only injects damage and records its effects.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";
import { logical } from "./entry-provenance-runtime.mjs";
import { modelRuntimeIdentity } from "./model-runtime-observation.mjs";

const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const search = "SELECT id,path,text FROM memory_index_chunks_fts WHERE memory_index_chunks_fts MATCH ? ORDER BY id,text";

export async function runRecoveryIndexRepairRuntime(input, runtimeConfig) {
  const { evidenceDirectory, runtimeRoot } = runtimeConfig;
  if (![runtimeRoot, evidenceDirectory].every(p => path.isAbsolute(p))) throw Error("Absolute fixture roots required");
  await fs.mkdir(evidenceDirectory, { recursive: true });
  const base = await fs.mkdtemp(path.join(evidenceDirectory, "native-index-repair-"));
  const workspace = path.join(base, "workspace");
  await fs.mkdir(workspace);
  const env = { OPENCLAW_STATE_DIR: path.join(base, "state"), OPENCLAW_CONFIG_PATH: path.join(base, "openclaw.json"), OPENCLAW_HOME: base };
  const prior = Object.fromEntries(Object.keys(env).map(k => [k, process.env[k]]));
  Object.assign(process.env, env);
  const cfg = { agents: { defaults: { workspace } }, logging: { level: "silent", consoleLevel: "silent", file: path.join(base, "native.log") },
    memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"],
      store: { vector: { enabled: false } } } } };
  const raw = { input, fixtureBase: base, runtime: modelRuntimeIdentity(), pid: process.pid, ppid: process.ppid,
    config: cfg, calls: [], snapshots: [], blobs: {} };
  const load = relative => import(pathToFileURL(path.join(runtimeRoot, relative)).href);
  let manager, config, authority, closeState;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  try {
    await fs.writeFile(env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
    for (const [relative, text] of Object.entries(input.files)) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) throw Error("Invalid note path");
      const filename = path.join(workspace, relative);
      await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, text);
      await fs.utimes(filename, input.mtimeMs / 1000, input.mtimeMs / 1000);
    }
    config = await load("dist/plugin-sdk/config-runtime.js");
    config.setRuntimeConfigSnapshot(cfg);
    const { configureMemoryCoreDreamingState } = await load("dist/extensions/memory-core/runtime-api.js");
    const keyed = await load("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState(options => keyed.createPluginStateKeyedStore("memory-core", options));
    closeState = keyed.closePluginStateDatabaseAsync;
    authority = await load("dist/extensions/memory-core/manager-runtime.js");
    const { decodeMemoryEmbedding } = await load("dist/plugin-sdk/memory-core-host-engine-storage.js");
    manager = await authority.MemoryIndexManager.get({ cfg, agentId: "main", purpose: "cli" });
    const methods = { get: authority.MemoryIndexManager.get, markMemoryWatchDirty: manager.markMemoryWatchDirty,
      sync: manager.sync, close: manager.close, status: manager.status };
    raw.owners = Object.fromEntries(Object.entries(methods).map(([name, method]) => [name, digest(String(method))]));
    raw.calls.push({ operation: "get", agentId: "main", purpose: "cli", status: manager.status() });
    for (const stage of input.stages) {
      if (stage === "damaged") {
        const result = manager.db.prepare(input.damage.sql).run(...input.damage.args);
        raw.calls.push({ operation: "inject", stage, sql: input.damage.sql, args: input.damage.args, result });
      } else {
        manager.markMemoryWatchDirty();
        const request = { reason: "repair-diagnostics-fixture", force: true };
        const result = await manager.sync(request);
        raw.calls.push({ operation: "sync", stage, markedDirty: true, request,
          ...(result === undefined ? { returnedUndefined: true } : { result }) });
      }
      const db = manager.db;
      const documents = {};
      for (const relative of Object.keys(input.files)) documents[relative] = await fs.readFile(path.join(workspace, relative), "utf8");
      const state = logical(db, decodeMemoryEmbedding);
      const searches = input.searches.map(query => ({ query, rows: db.prepare(search).all(query) }));
      const integrity = db.prepare("PRAGMA integrity_check").all().map(row => row.integrity_check);
      const image = path.join(base, stage + ".sqlite");
      db.prepare("VACUUM INTO ?").run(image);
      const bytes = await fs.readFile(image);
      const sha256 = digest(bytes);
      raw.blobs[sha256] ??= { size: bytes.length, gzip: gzipSync(bytes).toString("base64") };
      const status = manager.status();
      raw.snapshots.push({ observation: { stage, documents, state, searches, integrity, indexIdentity: status.custom.indexIdentity }, sha256,
        status, databaseList: db.prepare("PRAGMA database_list").all() });
    }
    return { observations: raw.snapshots.map(row => row.observation) };
  } finally {
    try {
      if (manager) { await manager.close(); raw.calls.push({ operation: "close", completed: true }); }
      await authority?.closeAllMemoryIndexManagers();
      await closeState?.();
      config?.clearRuntimeConfigSnapshot();
    } finally {
      mock.timers.reset();
      for (const [key, value] of Object.entries(prior)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
      await fs.writeFile(path.join(evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    }
  }
}
