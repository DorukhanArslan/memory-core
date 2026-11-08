// Fixture transport only. Every annotation, SQL lookup and ranking operation
// executes its unchanged pinned owner; no expected results are reconstructed.
import { DatabaseSync } from "node:sqlite";
import { runHybridScoring } from "./hybrid-scoring.mjs";

export async function runImportanceProject(input, importReference) {
  if (input.kind === "hybrid") {
    return runHybridScoring({ ...input, kind: "merge" }, importReference);
  }
  if (input.kind === "modifiers") {
    const importance = await importReference("extensions/memory-core/src/memory/importance.ts");
    const project = await importReference("extensions/memory-core/src/memory/project-ranking.ts");
    const active = project.prepareActiveProjectKeys(input.activeProjectKeys);
    const importanceOnly = importance.applyImportanceMultiplier(structuredClone(input.results));
    const projectOnly = project.applyProjectRanking(structuredClone(input.results), active);
    return {
      importanceOnly,
      projectOnly,
      results: project.applyProjectRanking(importance.applyImportanceMultiplier(
        structuredClone(input.results),
      ), active),
    };
  }
  if (input.kind === "prepare") {
    const owner = await importReference("extensions/memory-core/src/memory/manager-index-preparation.ts");
    const { kind: _kind, ...params } = structuredClone(input);
    return { prepared: owner.prepareMemoryIndexChunks(params) };
  }
  if (input.kind !== "recall") {
    throw Error(`Unsupported importance/project source operation: ${input.kind}`);
  }
  const schema = await importReference("packages/memory-host-sdk/src/host/memory-schema.ts");
  const owner = await importReference("packages/memory-host-sdk/src/host/memory-recall-metadata.ts");
  const db = new DatabaseSync(":memory:");
  try {
    db.exec("PRAGMA foreign_keys=ON");
    schema.ensureMemoryIndexSchema({ db, cacheEnabled: false, ftsEnabled: false });
    if (input.ignoreChecks) db.exec("PRAGMA ignore_check_constraints=ON");
    if (input.foreignKeys === false) db.exec("PRAGMA foreign_keys=OFF");
    const chunk = db.prepare("INSERT INTO memory_index_chunks " +
      "(id,path,source,start_line,end_line,hash,model,text,embedding,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)");
    for (const row of input.chunks) {
      chunk.run(row.id, row.path, row.source, row.startLine, row.endLine,
        row.hash ?? row.id, row.model ?? "fts-only", row.text, new Uint8Array(), row.updatedAt ?? 0);
    }
    const recall = db.prepare("INSERT INTO memory_index_chunk_recall_metadata " +
      "(chunk_id,importance,triggers,project_key) VALUES(?,?,?,?)");
    for (const row of input.recall ?? []) {
      recall.run(row.chunkId, row.importance ?? null, row.triggers ?? null, row.projectKey ?? null);
    }
    const provenance = db.prepare("INSERT INTO memory_index_chunk_provenance " +
      "(chunk_id,origin_class,session_kind,observed_at,supersedes_key) VALUES(?,?,?,?,?)");
    for (const row of input.provenance ?? []) {
      provenance.run(row.chunkId, row.originClass, row.sessionKind, row.observedAt,
        row.supersedesKey ?? null);
    }
    return { rows: [...owner.readMemoryRecallMetadata(db, input.ids).values()] };
  } finally {
    db.close();
  }
}
