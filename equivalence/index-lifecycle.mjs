// Real release MemoryIndexManager operations. This adapter only arranges host
// fixtures, drives dirty notifications/sync, and observes persisted SQL state.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const compact = (value) => JSON.stringify(value);
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.keys(value).sort()
    .map((key) => `${compact(key)}:${canonical(value[key])}`).join(",")}}`;
  return compact(value);
}
const clone = (value) => structuredClone(value);
function normalize(raw, previous) {
  const semanticKey = (row) => canonical([row.source,row.path,row.startLine,row.endLine,row.text]);
  const keys = new Map(raw.chunks.map((row) => [row.id,semanticKey(row)]));
  const old = new Map((previous?.chunks ?? []).map((row) => [semanticKey(row),row]));
  const clocks = new Map();
  const chunks = raw.chunks.map((original) => {
    const row = clone(original), before = old.get(keys.get(row.id));
    clocks.set(row.id,!before ? "new" : before.updatedAt === row.updatedAt ? "retained" : "rewritten");
    row.updatedAt = clocks.get(row.id);
    row.identityRetained = Boolean(before && before.id === row.id);
    return row;
  });
  const oldSources = new Map((previous?.sources ?? []).map((row) => [canonical([row.source,row.path]),row]));
  const sources = raw.sources.map((original) => {
    const row = clone(original), before = oldSources.get(canonical([row.source,row.path]));
    row.hashRetained = Boolean(before && before.hash === row.hash);
    if (row.source === "sessions") {
      if (row.hash.startsWith("sqlite:")) row.hash = row.hash.split(":").slice(2).join(":");
      const size = row.size;
      row.size = {empty:size === 0,retained:Boolean(before && before.size === size),
        direction:before ? Math.sign(size - before.size) : null};
    }
    return row;
  });
  const result = {sources,chunks,paths:clone(raw.paths)};
  for (const [collection,field] of [["fts","id"],["details","chunkId"],["provenance","chunkId"],["recall","chunkId"]]) {
    result[collection] = raw[collection].map((original) => {
      const row = clone(original);
      if ("updatedAt" in row) row.updatedAt = clocks.get(row[field]) ?? "orphan";
      return row;
    });
  }
  result.meta = raw.meta.filter((row) => row.key === "memory_index_meta_v1")
    .map((row) => ({key:row.key,value:JSON.parse(row.value)}));
  for (const rows of Object.values(result)) rows.sort((a,b) => canonical(a) < canonical(b) ? -1 : canonical(a) > canonical(b) ? 1 : 0);
  return result;
}

export async function runIndexLifecycle(input, runtimeConfig) {
  const runtimeRoot = runtimeConfig?.runtimeRoot;
  if (!runtimeRoot || !path.isAbsolute(runtimeRoot)) throw Error("An authenticated absolute release runtimeRoot is required");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),"openclaw-index-lifecycle-"));
  const workspace = path.join(directory,"workspace");
  await fs.mkdir(workspace);
  const priorEnvironment = Object.fromEntries(["OPENCLAW_STATE_DIR","OPENCLAW_CONFIG_PATH"].map((name) => [name,process.env[name]]));
  process.env.OPENCLAW_STATE_DIR = runtimeConfig.stateDirectory ?? path.join(directory,"state");
  process.env.OPENCLAW_CONFIG_PATH = runtimeConfig.configPath ?? path.join(directory,"absent-config.json");
  let manager;
  const rawSnapshots = [];
  try {
    const imp = (relative) => import(pathToFileURL(path.join(runtimeRoot,relative)).href);
    const { MemoryIndexManager } = await imp("dist/extensions/memory-core/manager-runtime.js");
    const { configureMemoryCoreDreamingState } = await imp("dist/extensions/memory-core/runtime-api.js");
    const { createPluginStateKeyedStore } = await imp("dist/plugin-sdk/plugin-state-store-runtime.js");
    const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
    const transcript = await imp("dist/plugin-sdk/session-transcript-runtime.js");
    configureMemoryCoreDreamingState((options) => createPluginStateKeyedStore("memory-core",options));
    const cfg = {agents:{defaults:{workspace}},memory:{search:{enabled:true,provider:"none",fallback:"none",
      sources:["memory","sessions"],experimental:{sessionMemory:true},store:{vector:{enabled:false}}}}};
    const acquire = () => MemoryIndexManager.get({cfg,agentId:"main",purpose:"cli"});
    const scope = (identifier) => ({agentId:"main",sessionKey:`agent:main:${identifier}`,sessionId:identifier,config:cfg});
    async function writeFiles(files) {
      for (const [relative,text] of Object.entries(files ?? {})) {
        const filename = path.join(workspace,relative);
        await fs.mkdir(path.dirname(filename),{recursive:true});
        await fs.writeFile(filename,text,"utf8");
        await fs.utimes(filename,input.mtimeMs / 1000,input.mtimeMs / 1000);
      }
    }
    async function appendSession(identifier,messages,create=false) {
      if (create) await sessions.upsertSessionEntry({...scope(identifier),entry:{sessionId:identifier,
        updatedAt:Math.max(input.mtimeMs,...messages.map((message) => message.timestamp)),chatType:"direct"}});
      for (const message of messages) {
        const result = await transcript.appendSessionTranscriptMessageByIdentity({...scope(identifier),message});
        if (!result.appended) throw Error(`Native transcript append failed: ${compact(result)}`);
      }
    }
    await writeFiles(input.files);
    for (const [identifier,messages] of Object.entries(input.sessions ?? {})) await appendSession(identifier,messages,true);
    manager = await acquire();
    if (!manager) throw Error("Native FTS MemoryIndexManager was unavailable");
    function state() {
      const db = manager.db;
      const provenance = db.prepare("SELECT chunk_id AS chunkId,origin_class AS originClass,session_kind AS sessionKind," +
        "observed_at AS observedAt,supersedes_key AS supersedesKey FROM memory_index_chunk_provenance").all();
      const recall = db.prepare("SELECT chunk_id AS chunkId,importance,triggers,project_key AS projectKey " +
        "FROM memory_index_chunk_recall_metadata").all();
      const byProvenance = new Map(provenance.map((row) => [row.chunkId,row]));
      const byRecall = new Map(recall.map((row) => [row.chunkId,row]));
      const chunks = db.prepare("SELECT id,path,source,start_line AS startLine,end_line AS endLine,text," +
        "hash,model,updated_at AS updatedAt,hex(embedding) AS vectorHex FROM memory_index_chunks").all().map((row) => {
        const {chunkId:_p,...p} = byProvenance.get(row.id) ?? {};
        const {chunkId:_r,...r} = byRecall.get(row.id) ?? {};
        // provider:none must have actual empty persisted vectors, not hidden data.
        if (row.vectorHex !== "") throw Error("Unexpected native vector in provider:none lifecycle");
        const {vectorHex,...chunk} = row;
        return {...chunk,embedding:[],provenance:p,recall:r};
      });
      return {
        sources:db.prepare("SELECT path,source,hash,mtime,size FROM memory_index_sources").all(),chunks,
        fts:db.prepare("SELECT id,text,path,source,start_line AS startLine,end_line AS endLine,model FROM memory_index_chunks_fts").all(),
        paths:db.prepare("SELECT path,source FROM memory_index_paths_fts").all(),provenance,recall,
        details:chunks.map((row) => ({chunkId:row.id,hash:row.hash,model:row.model,updatedAt:row.updatedAt})),
        meta:db.prepare("SELECT key,value FROM memory_index_meta").all(),
      };
    }
    const snapshots = [];
    let previous;
    for (const step of input.steps) {
      await writeFiles(step.write);
      for (const [source,destination] of Object.entries(step.rename ?? {})) {
        await fs.mkdir(path.dirname(path.join(workspace,destination)),{recursive:true});
        await fs.rename(path.join(workspace,source),path.join(workspace,destination));
      }
      for (const relative of step.remove ?? []) await fs.unlink(path.join(workspace,relative));
      for (const [identifier,messages] of Object.entries(step.createSessions ?? {})) await appendSession(identifier,messages,true);
      for (const [identifier,messages] of Object.entries(step.appendSessions ?? {})) await appendSession(identifier,messages);
      for (const [identifier,renamed] of Object.entries(step.renameSessions ?? {})) {
        // The public host API has identity creation/deletion, rather than a
        // transcript-filesystem rename. Transfer the actual persisted messages
        // in order, keeping the declared activity timestamp under the new ID.
        const entry = sessions.getSessionEntry(scope(identifier));
        if (!entry) throw Error(`Cannot transfer absent native session ${identifier}`);
        const messages = sessions.loadTranscriptEventsSync(scope(identifier))
          .filter((event) => event.type === "message").map((event) => event.message);
        if (!await sessions.deleteSessionEntry({...scope(identifier),archiveTranscript:false})) {
          throw Error(`Native host did not delete transferred session ${identifier}`);
        }
        await sessions.upsertSessionEntry({...scope(renamed),entry:{sessionId:renamed,
          updatedAt:entry.updatedAt,chatType:entry.chatType}});
        await appendSession(renamed,messages);
      }
      for (const identifier of step.deleteSessions ?? []) await sessions.deleteSessionEntry({...scope(identifier),archiveTranscript:false});
      if (step.reopen) { await manager.close(); manager = await acquire(); }
      if (step.failChunkWrite) manager.db.exec("CREATE TRIGGER lifecycle_failure BEFORE INSERT ON memory_index_chunks " +
        "BEGIN SELECT RAISE(ABORT,'injected lifecycle chunk failure'); END");
      let error = null;
      try {
        // CLI mode omits OS watchers: send their existing dirty notification
        // explicitly, then run the genuine owner sync planner and writer.
        manager.markMemoryWatchDirty();
        const targets = [...Object.keys(step.createSessions ?? {}),...Object.keys(step.appendSessions ?? {})].map((identifier) => {
          const {agentId,sessionId,sessionKey} = scope(identifier); return {agentId,sessionId,sessionKey};
        });
        if (step.deleteSessions?.length || Object.keys(step.renameSessions ?? {}).length) {
          manager.sessionsReconcileDirty = true; manager.sessionsDirty = true;
        }
        if (Object.keys(step.renameSessions ?? {}).length) {
          // CLI mode omits startup/watch admission. Use the native complete
          // corpus inspection to admit new dirty files before one reconciliation.
          await manager.markSessionStartupCatchupDirtyFiles();
        }
        await manager.sync({reason:"fixture",...(targets.length ? {sessions:targets} : {})});
      } catch (cause) {
        let cursor = cause, injected = false;
        while (cursor) { if (String(cursor.message).includes("injected lifecycle chunk failure")) injected = true; cursor = cursor.cause; }
        if (!injected) throw cause;
        error = {kind:"injected-chunk-write-failure"};
      } finally {
        if (step.failChunkWrite) manager.db.exec("DROP TRIGGER lifecycle_failure");
      }
      const raw = state();
      snapshots.push({label:step.label,error,state:normalize(raw,previous)});
      rawSnapshots.push({label:step.label,raw,sessionCorpus:await manager.listSessionCorpusEntries()});
      previous = raw;
    }
    return {snapshots,provider:"none"};
  } finally {
    if (runtimeConfig.evidenceDirectory) {
      await fs.mkdir(runtimeConfig.evidenceDirectory,{recursive:true});
      await fs.writeFile(path.join(runtimeConfig.evidenceDirectory,"native-raw.json"),compact(rawSnapshots));
    }
    await manager?.close();
    for (const [name,value] of Object.entries(priorEnvironment)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
    await fs.rm(directory,{recursive:true,force:true});
  }
}
