// Prepared row fixtures and independent-reader observations only. The original
// native schema/transaction/publication owners execute every publication.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const metaKey = "memory_index_meta_v1";
const compact = (value) => JSON.stringify(value);

export async function runIndexPublication(input, importReference) {
  const schema = await importReference("packages/memory-host-sdk/src/host/memory-schema.ts");
  const kernel = await importReference("extensions/memory-core/src/memory/manager-db-kernel.ts");
  const codec = await importReference("packages/memory-host-sdk/src/host/embedding-vector.ts");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "openclaw-publication-"));
  // Configure the original logger through its real host API. Failure fixtures
  // must not write into a shared default OpenClaw log directory.
  const logging = await importReference("src/logging/logger.ts");
  logging.applyLoggingConfig({level:"silent",consoleLevel:"silent",file:path.join(directory,"native.log")});
  const filename = path.join(directory, "index.sqlite");
  const sourceName = path.join(directory, "shadow.sqlite");
  let target, source, reader, held;
  const failure = input.failure;
  let phase = "start";
  function open(filename) {
    const db = new DatabaseSync(filename);
    db.exec("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON");
    const status = schema.ensureMemoryIndexSchema({db, cacheEnabled:true, ftsEnabled:true});
    if (!status.ftsAvailable) throw Error("Native FTS fixture could not be prepared");
    return db;
  }
  function seed(db, revision) {
    for (const entry of revision.sources) {
      db.prepare("INSERT INTO memory_index_sources(path,source,hash,mtime,size) VALUES(?,?,?,?,?)")
        .run(entry.path,entry.source,entry.hash,entry.mtime,entry.size);
    }
    for (const chunk of revision.chunks) {
      db.prepare("INSERT INTO memory_index_chunks(id,path,source,start_line,end_line,hash,model,text,embedding,updated_at) " +
        "VALUES(?,?,?,?,?,?,?,?,?,?)").run(chunk.id,chunk.path,chunk.source,chunk.startLine,chunk.endLine,
          chunk.hash,chunk.model,chunk.text,codec.encodeMemoryEmbedding(chunk.embedding),chunk.updatedAt);
      const provenance = chunk.provenance;
      db.prepare("INSERT INTO memory_index_chunk_provenance VALUES(?,?,?,?,?)")
        .run(chunk.id,provenance.originClass,provenance.sessionKind,provenance.observedAt,provenance.supersedesKey);
      const recall = chunk.recall;
      db.prepare("INSERT INTO memory_index_chunk_recall_metadata VALUES(?,?,?,?)")
        .run(chunk.id,recall.importance,recall.triggers === null ? null : compact(recall.triggers),recall.projectKey);
    }
    db.prepare("INSERT INTO memory_index_meta(key,value) VALUES(?,?)").run(metaKey,compact(revision.meta));
  }
  function state(db) {
    const provenance = db.prepare("SELECT chunk_id AS chunkId,origin_class AS originClass,session_kind AS sessionKind," +
      "observed_at AS observedAt,supersedes_key AS supersedesKey FROM memory_index_chunk_provenance ORDER BY chunk_id").all();
    const recall = db.prepare("SELECT chunk_id AS chunkId,importance,triggers,project_key AS projectKey " +
      "FROM memory_index_chunk_recall_metadata ORDER BY chunk_id").all();
    const provenanceById = new Map(provenance.map((row) => [row.chunkId,row]));
    const recallById = new Map(recall.map((row) => [row.chunkId,row]));
    const chunks = db.prepare("SELECT id,path,source,start_line AS startLine,end_line AS endLine,text,embedding," +
      "hash,model,updated_at AS updatedAt FROM memory_index_chunks ORDER BY id").all().map((row) => {
      const {chunkId: _p, ...p} = provenanceById.get(row.id) ?? {};
      const {chunkId: _r, ...r} = recallById.get(row.id) ?? {};
      return {...row,embedding:codec.decodeMemoryEmbedding(row.embedding),
        provenance:provenanceById.has(row.id) ? p : null,recall:recallById.has(row.id) ? r : null};
    });
    return {
      sources:db.prepare("SELECT path,source,hash,mtime,size FROM memory_index_sources ORDER BY source,path").all(),
      chunks,
      fts:db.prepare("SELECT id,text,path,source,start_line AS startLine,end_line AS endLine,model " +
        "FROM memory_index_chunks_fts ORDER BY id").all(),
      paths:db.prepare("SELECT path,source FROM memory_index_paths_fts ORDER BY source,path").all(),
      provenance,recall,
      details:chunks.map((row) => ({chunkId:row.id,hash:row.hash,model:row.model,updatedAt:row.updatedAt})),
      meta:db.prepare("SELECT key,value FROM memory_index_meta ORDER BY key").all(),
      bodyMatches:Object.fromEntries(["alpha","beta","gamma"].map((query) => [query,
        db.prepare("SELECT id FROM memory_index_chunks_fts WHERE memory_index_chunks_fts MATCH ? ORDER BY id")
          .all(query).map((row) => row.id)])),
      pathMatches:Object.fromEntries(["old","new","empty"].map((query) => [query,
        db.prepare("SELECT path,source FROM memory_index_paths_fts WHERE memory_index_paths_fts MATCH ? ORDER BY source,path")
          .all(query).map((row) => [row.path,row.source])])),
    };
  }
  function normalizeError(error) {
    if (!error) return null;
    if (failure === "after-commit" && phase === "after-commit") return {kind:"post-commit-failure"};
    if (error.name === "MemoryIndexRevisionConflictError") return {kind:"revision-conflict"};
    const marker = "injected publication failure:";
    if (error.message.includes(marker)) return {kind:"injected-failure",stage:error.message.split(marker)[1]};
    return {kind:"unexpected",type:error.name,message:error.message};
  }
  try {
    target = open(filename);
    seed(target,input.initial);
    target.prepare("INSERT INTO memory_index_meta(key,value) VALUES ('unrelated-key','target-retained')").run();
    target.prepare("INSERT INTO memory_embedding_cache VALUES " +
      "('fixture-provider','fixture-model','fixture-key','retained',X'000000000000D03F',1,1)").run();
    if (input.orphans) {
      target.exec("PRAGMA foreign_keys=OFF");
      target.exec("INSERT INTO memory_index_chunk_provenance VALUES ('orphan','untrusted','unknown',77,NULL);" +
        "INSERT INTO memory_index_chunk_recall_metadata VALUES ('orphan',2,'[]','orphan-project')");
      target.exec("PRAGMA foreign_keys=ON");
    }
    source = open(sourceName);
    seed(source,input.replacement);
    source.prepare("INSERT INTO memory_index_meta(key,value) VALUES ('unrelated-key','shadow-ignored')").run();
    source.close(); source = null;
    reader = new DatabaseSync(filename);
    held = new DatabaseSync(filename);
    if (input.holdReader) { held.exec("BEGIN"); held.prepare("SELECT COUNT(*) FROM memory_index_chunks").get(); }
    const tables = {sources:"memory_index_sources",chunks:"memory_index_chunks",details:"memory_index_chunks",
      recall:"memory_index_chunk_recall_metadata",provenance:"memory_index_chunk_provenance"};
    if (tables[failure]) target.exec(`CREATE TRIGGER fixture_failure BEFORE INSERT ON ${tables[failure]} ` +
      `BEGIN SELECT RAISE(ABORT,'injected publication failure:${failure}'); END`);
    const expected = kernel.readMemoryDatabaseRevision(target);
    if (input.stale) target.exec("UPDATE memory_index_state SET revision=revision+1 WHERE id=1");
    const baseRevision = kernel.readMemoryDatabaseRevision(target);
    const before = state(target);
    const events = [];
    function observe(label) {
      events.push({phase:label,writer:state(target),reader:state(reader),heldReader:input.holdReader ? state(held) : null});
    }
    let error;
    try {
      kernel.publishMemoryDatabaseTables({targetDb:target,sourcePath:sourceName,metaKey,expectedRevision:expected,
        onBegin:() => {
          phase = "begin"; observe("begin");
          if (failure === "begin") throw Error("injected publication failure:begin");
        },
        withCommit:(commit) => {
          phase = "commit"; observe("commit");
          if (failure === "commit") throw Error("injected publication failure:commit");
          commit();
          if (failure === "after-commit") { phase = "after-commit"; throw Error("injected publication failure:after-commit"); }
        },
      });
    } catch (err) { error = err; }
    const after = state(reader);
    const heldAfter = input.holdReader ? state(held) : null;
    if (input.holdReader) held.exec("ROLLBACK");
    const reopened = new DatabaseSync(filename);
    try {
      const cache = reopened.prepare("SELECT provider,model,provider_key,hash,hex(embedding),dims,updated_at " +
        "FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash").all().map((row) => Object.values(row));
      const attachmentReleased = !target.isOpen || target.prepare("PRAGMA database_list").all()
        .every((row) => row.name !== "memory_reindex");
      return {before,events,after,heldAfter,reopened:state(reopened),error:normalizeError(error),
        revisionAdvanced:kernel.readMemoryDatabaseRevision(reopened) !== baseRevision,
        cache,attachmentReleased,attachments:reopened.prepare("PRAGMA database_list").all().map((row) => row.name)};
    } finally { reopened.close(); }
  } finally {
    for (const db of [source,target,reader,held]) { try { db?.close(); } catch {} }
    fs.rmSync(directory,{recursive:true,force:true});
  }
}
