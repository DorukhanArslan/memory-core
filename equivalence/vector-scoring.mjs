// Fixture transport for the original portable vector candidate owners.
// SQLite, binary64 decoding, scoring, top-k selection and projection are native.
// The declared host capability is vectorReady:false; sqlite-vec is not exercised.
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function number(value) {
  const name = value && typeof value === "object" && !Array.isArray(value)
    ? value.special : typeof value === "string" ? value.toLowerCase() : undefined;
  if (name === undefined) return value;
  if (name === "nan") return NaN;
  if (name === "infinity") return Infinity;
  if (name === "-infinity") return -Infinity;
  throw Error("Unsupported vector numeric transport value");
}

function numericResult(value) {
  return Number.isFinite(value) ? { value }
    : { nonfinite: Number.isNaN(value) ? "nan" : value > 0 ? "infinity" : "-infinity" };
}

const vector = (value) => value.map(number);

export async function runVectorScoring(input, importReference) {
  const codec = await importReference("packages/memory-host-sdk/src/host/embedding-vector.ts");
  if (input.kind === "cosine") return numericResult(codec.cosineSimilarity(vector(input.a), vector(input.b)));
  if (input.kind !== "search") throw Error(`Unsupported vector scoring operation: ${input.kind}`);
  if ((input.backend ?? "scan") !== "scan") throw Error("The portable vector fixture does not verify sqlite-vec KNN");
  const owner = await importReference("extensions/memory-core/src/memory/manager-search-vector.ts");
  const encoding = input.encoding ?? "UTF-8";
  if (!["UTF-8", "UTF-16le", "UTF-16be"].includes(encoding)) throw Error("Unsupported fixture SQLite encoding");
  const directory = input.externalDuringScan
    ? fs.mkdtempSync(path.join(os.tmpdir(), "memory-vector-snapshot-")) : undefined;
  const filename = directory ? path.join(directory, "index.sqlite") : ":memory:";
  const db = new DatabaseSync(filename);
  let writer;
  const observed = Boolean(input.observe || input.preAborted || input.abortAfterBatch ||
    input.mutateAfterBatch || input.externalDuringScan);
  const physicalTable = observed ? "vector_fixture_chunks" : "memory_index_chunks";
  db.exec(`PRAGMA encoding = '${encoding}'`);
  if (input.externalDuringScan) db.exec("PRAGMA journal_mode=WAL");
  // The exact columns consumed by the unchanged original vector owner. This is
  // real SQLite storage, with the native implicit signed INTEGER rowid domain.
  db.exec(`CREATE TABLE ${physicalTable} (
    id TEXT PRIMARY KEY NOT NULL, path TEXT NOT NULL, source TEXT NOT NULL,
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, hash TEXT NOT NULL,
    model TEXT NOT NULL, text TEXT NOT NULL, embedding BLOB NOT NULL,
    updated_at INTEGER NOT NULL) STRICT`);
  const insert = db.prepare(`INSERT OR REPLACE INTO ${physicalTable} ` +
    "(rowid,id,path,source,start_line,end_line,hash,model,text,embedding,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)");
  function seed(row, index) {
    const bytes = Object.hasOwn(row, "embeddingBytesHex")
      ? Buffer.from(row.embeddingBytesHex, "hex")
      : codec.encodeMemoryEmbedding(vector(row.embedding ?? []));
    insert.run(BigInt(row.rowid ?? index + 1), row.id, row.path, row.source ?? "memory",
      row.startLine ?? 1, row.endLine ?? 1, row.id, row.model ?? input.providerModel ?? "target-model",
      row.text ?? "", bytes, 1);
  }
  try {
    for (const [index, row] of input.rows.entries()) seed(row, index);
    const filter = (column) => input.sources?.length ? {
      sql: ` AND ${column} IN (${input.sources.map(() => "?").join(", ")})`, params: input.sources,
    } : { sql: "", params: [] };
    const controller = new AbortController();
    const cancelReason = new Error("fixture vector scan cancelled");
    const scannedRowids = [];
    let externallyReplaced = false;
    if (input.externalDuringScan) writer = new DatabaseSync(filename);
    function externalMutation() {
      if (externallyReplaced) return;
      externallyReplaced = true;
      writer.exec("BEGIN IMMEDIATE");
      try {
        const update = writer.prepare(`UPDATE ${physicalTable} SET id=?,path=?,source=?,
          start_line=?,end_line=?,model=?,text=?,embedding=? WHERE rowid=?`);
        for (const row of input.externalDuringScan.replaceRows ?? []) {
          const bytes = Object.hasOwn(row, "embeddingBytesHex")
            ? Buffer.from(row.embeddingBytesHex, "hex")
            : codec.encodeMemoryEmbedding(vector(row.embedding ?? []));
          update.run(row.id, row.path, row.source ?? "memory", row.startLine ?? 1,
            row.endLine ?? 1, row.model ?? input.providerModel ?? "target-model", row.text ?? "",
            bytes, BigInt(row.rowid));
        }
        writer.exec("COMMIT");
      } catch (error) {
        writer.exec("ROLLBACK");
        throw error;
      }
    }
    function observations() {
      return { scannedRowids,
        ...(writer ? { externalRows: (input.externalDuringScan.replaceRows ?? []).map((row) =>
          writer.prepare(`SELECT id,text FROM ${physicalTable} WHERE rowid=?`).get(BigInt(row.rowid))) } : {}),
      };
    }
    let transitionScheduled = false;
    let transitionFinished = false;
    function transition() {
      if (transitionFinished) return;
      transitionFinished = true;
      const mutation = input.mutateAfterBatch;
      for (const id of mutation?.deleteIds ?? []) {
        db.prepare(`DELETE FROM ${physicalTable} WHERE id = ?`).run(id);
      }
      for (const [index, row] of [
        ...(mutation?.replaceRows ?? []), ...(mutation?.insertRows ?? []),
      ].entries()) seed(row, input.rows.length + index);
      if (input.abortAfterBatch) controller.abort(cancelReason);
    }
    if (observed) {
      db.function("observe_embedding", { useBigIntArguments: true }, (embedding, rowid) => {
        scannedRowids.push(String(rowid));
        if (input.externalDuringScan && !externallyReplaced) externalMutation();
        if (!transitionScheduled && scannedRowids.length === 256 &&
            (input.abortAfterBatch || input.mutateAfterBatch)) {
          transitionScheduled = true;
          setImmediate(transition);
        }
        return embedding;
      });
      db.exec(`CREATE VIEW memory_index_chunks AS SELECT rowid AS rowid, id,path,source,
        start_line,end_line,hash,model,text,observe_embedding(embedding,rowid) AS embedding,
        updated_at FROM ${physicalTable}`);
    }
    if (input.preAborted) controller.abort(cancelReason);
    const queryVec = vector(input.queryVec);
    let rows;
    try {
      rows = await owner.searchVector({
      vectorTable: "memory_index_chunks_vec", providerModel: input.providerModel ?? "target-model",
      providerModelAliases: input.providerModelAliases,
      queryVec, limit: input.limit, snippetMaxChars: input.snippetMaxChars,
      signal: controller.signal, sourceFilterVec: filter("c.source"),
      ensureVectorReady: async () => false,
      runFallback: () => owner.searchChunksByEmbedding({
        db, providerModel: input.providerModel ?? "target-model", providerModelAliases: input.providerModelAliases,
        sourceFilter: filter("source"), queryVec, limit: input.limit, snippetMaxChars: input.snippetMaxChars,
        signal: controller.signal,
      }),
      });
    } catch (error) {
      if (error !== cancelReason) throw error;
      return { rows: null, aborted: true, observations: observations() };
    }
    return { rows, ...(observed ? { observations: observations() } : {}) };
  } finally {
    writer?.close();
    db.close();
    if (directory) fs.rmSync(directory, { recursive: true, force: true });
  }
}
