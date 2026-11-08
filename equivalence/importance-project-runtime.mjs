// Real provider-none indexing and public search. This adapter supplies files,
// host options and observations; native preparation/publication/read/rank owners
// perform every semantic operation.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export async function runImportanceProjectRuntime(input, runtimeConfig) {
  if (input.kind !== "stored-search") {
    throw Error(`Unsupported stored importance/project operation: ${input.kind}`);
  }
  if (!runtimeConfig?.runtimeRoot || !path.isAbsolute(runtimeConfig.runtimeRoot) ||
      !runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Authenticated absolute runtime and evidence directories are required");
  }
  if (input.temporalDecay?.enabled) {
    throw Error("Stored-search fixtures use clock-neutral decay; fixed-clock composition is a source comparison");
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-project-ranking-"));
  const workspace = path.join(directory, "workspace");
  await fs.mkdir(workspace);
  const rawSnapshots = [];
  let manager;
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((name) =>
    [name, process.env[name]]));
  process.env.OPENCLAW_STATE_DIR = runtimeConfig.stateDirectory;
  process.env.OPENCLAW_CONFIG_PATH = runtimeConfig.configPath;
  function filename(relative) {
    if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
      throw Error("Fixture files must stay inside their owned workspace");
    }
    return path.join(workspace, relative);
  }
  async function write(files, mtimeMs) {
    for (const [relative, text] of Object.entries(files ?? {})) {
      const absolute = filename(relative);
      await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, text, "utf8");
      await fs.utimes(absolute, mtimeMs / 1000, mtimeMs / 1000);
    }
  }
  try {
    const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
    const { MemoryIndexManager } = await imp("dist/extensions/memory-core/manager-runtime.js");
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core", options));
    const cfg = {
      agents: { defaults: { workspace } },
      memory: { search: {
        enabled: true, provider: "none", fallback: "none", sources: ["memory"],
        store: { vector: { enabled: false } },
        ...(input.chunking ? { chunking: structuredClone(input.chunking) } : {}),
        query: { minScore: 0, maxResults: 200,
          hybrid: { temporalDecay: { enabled: false } } },
      } },
    };
    const acquire = () => MemoryIndexManager.get({ cfg, agentId: "main", purpose: "cli" });
    function persisted() {
      const db = manager.db;
      const chunks = db.prepare("SELECT id,path,source,start_line AS startLine,end_line AS endLine," +
        "text,hash,model,updated_at AS updatedAt,hex(embedding) AS embeddingHex " +
        "FROM memory_index_chunks ORDER BY source,path,start_line,end_line,text,id").all();
      const recall = db.prepare("SELECT chunk_id AS chunkId,importance,triggers,project_key AS projectKey " +
        "FROM memory_index_chunk_recall_metadata ORDER BY chunk_id").all();
      const provenance = db.prepare("SELECT chunk_id AS chunkId,origin_class AS originClass," +
        "session_kind AS sessionKind,observed_at AS observedAt,supersedes_key AS supersedesKey " +
        "FROM memory_index_chunk_provenance ORDER BY chunk_id").all();
      const rows = db.prepare("SELECT c.path,c.source,c.start_line AS startLine,c.end_line AS endLine,c.text," +
        "r.importance,r.triggers,r.project_key AS projectKey,p.origin_class AS originClass," +
        "p.session_kind AS sessionKind,p.observed_at AS observedAt,p.supersedes_key AS supersedesKey " +
        "FROM memory_index_chunks c LEFT JOIN memory_index_chunk_recall_metadata r ON r.chunk_id=c.id " +
        "LEFT JOIN memory_index_chunk_provenance p ON p.chunk_id=c.id " +
        "ORDER BY c.source,c.path,c.start_line,c.end_line,c.text,c.id").all();
      const published = rows.map(({ originClass, sessionKind, observedAt, supersedesKey, ...row }) =>
        ({ ...row, provenance: { originClass, sessionKind, observedAt, supersedesKey } }));
      return {
        published,
        raw: { chunks, recall, provenance,
          sources: db.prepare("SELECT * FROM memory_index_sources ORDER BY source,path").all() },
      };
    }
    await write(input.files, input.mtimeMs);
    manager = await acquire();
    if (!manager) throw Error("The native provider-none memory manager was unavailable");
    manager.markMemoryWatchDirty();
    await manager.sync({ reason: "fixture" });
    const steps = [];
    for (const [index, step] of input.steps.entries()) {
      const mtimeMs = step.mtimeMs ?? input.mtimeMs;
      await write(step.write, mtimeMs);
      for (const relative of step.remove ?? []) await fs.unlink(filename(relative));
      if (step.reopen) {
        await manager.close();
        manager = await acquire();
        if (!manager) throw Error("The native memory manager could not reopen");
      }
      if (step.write || step.remove?.length || step.sync) {
        manager.markMemoryWatchDirty();
        await manager.sync({ reason: "fixture" });
      }
      const options = { maxResults: step.maxResults, minScore: step.minScore };
      for (const name of ["activeProjectKeys", "sources"]) {
        if (Object.hasOwn(step, name)) options[name] = structuredClone(step[name]);
      }
      const rows = await manager.search(step.query, options);
      const state = persisted();
      steps.push({ rows, published: state.published });
      rawSnapshots.push({ index, query: step.query, options, rows, ...state.raw,
        constructorExecuted: true, provider: "none" });
    }
    return { provider: "none", steps };
  } finally {
    await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"),
      JSON.stringify(rawSnapshots));
    await manager?.close();
    for (const [name, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}
