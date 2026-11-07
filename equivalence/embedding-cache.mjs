// Fixtures and serialization only. Cache decisions execute original pinned TS.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const identity = { provider: "provider-a", model: "model-a", providerKey: "key-a" };
const special = (value) => {
  if (value && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).length === 1 && Object.hasOwn(value, "special")) {
    return { nan: NaN, infinity: Infinity, "-infinity": -Infinity }[value.special];
  }
  return Array.isArray(value) ? value.map(special) : value;
};

export async function runEmbeddingCache(input, importReference) {
  const cache = await importReference("extensions/memory-core/src/memory/manager-embedding-cache.ts");
  const codec = await importReference("packages/memory-host-sdk/src/host/embedding-vector.ts");
  if (input.kind === "validate") {
    return cache.isValidMemoryEmbedding(special(input.vector), input.dimensions);
  }
  if (input.kind === "decode") return codec.decodeMemoryEmbedding(Buffer.from(input.hex, "hex"));
  if (input.kind === "codec") {
    try {
      const encoded = codec.encodeMemoryEmbedding(special(input.vector));
      return { hex: Buffer.from(encoded).toString("hex"), decoded: codec.decodeMemoryEmbedding(encoded) };
    } catch (error) { return { error: error.message }; }
  }
  if (input.kind !== "script") throw Error(`Unsupported embedding cache operation: ${input.kind}`);

  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "openclaw-cache-"));
  const filename = path.join(directory, "cache.sqlite");
  let db = new DatabaseSync(filename);
  // Schema fixture matches the cache owner's columns; no index/manager stubs.
  db.exec(`CREATE TABLE memory_embedding_cache (
    provider TEXT NOT NULL, model TEXT NOT NULL, provider_key TEXT NOT NULL,
    hash TEXT NOT NULL, embedding BLOB NOT NULL, dims INTEGER,
    updated_at INTEGER NOT NULL, PRIMARY KEY(provider,model,provider_key,hash))`);
  function snapshot() {
    return db.prepare("SELECT provider,model,provider_key,hash,embedding,CAST(dims AS TEXT) AS dims,updated_at " +
      "FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash").all().map((row) => ({
        provider: row.provider, model: row.model, providerKey: row.provider_key, hash: row.hash,
        embedding: codec.decodeMemoryEmbedding(row.embedding), dims: row.dims, updatedAt: row.updated_at,
      }));
  }
  const outcomes = [];
  try {
    for (const step of input.steps) {
      const outcome = { action: step.action };
      try {
        switch (step.action) {
          case "put":
            cache.upsertMemoryEmbeddingCache({
              db, enabled: step.enabled ?? true,
              provider: Object.hasOwn(step, "provider") ? step.provider : { id: "provider-a", model: "model-a" },
              providerKey: Object.hasOwn(step, "providerKey") ? step.providerKey : "key-a",
              entries: step.entries.map((entry) => entry == null ? entry : ({
                ...entry, embedding: special(entry.embedding),
              })), maxEntries: special(step.maxEntries), now: step.now ?? 100,
            });
            break;
          case "load": {
            const loaded = cache.loadMemoryEmbeddingCache({
              db, enabled: step.enabled ?? true, providerIdentities: step.identities ?? [identity], hashes: step.hashes,
            });
            outcome.loaded = [...loaded].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
            break;
          }
          case "clear": cache.clearMemoryEmbeddingCacheIdentities(db, step.identities); break;
          case "seed":
            for (const row of step.rows) {
              db.prepare("INSERT OR REPLACE INTO memory_embedding_cache VALUES (?,?,?,?,?,?,?)").run(
                row.provider, row.model, row.providerKey, row.hash, Buffer.from(row.hex, "hex"),
                typeof row.dims === "string" ? BigInt(row.dims) : row.dims, row.updatedAt,
              );
            }
            break;
          case "collect":
            outcome.collected = cache.collectMemoryCachedEmbeddings({ chunks: step.chunks, cached: new Map(step.cached) });
            break;
          case "begin": case "commit": case "rollback": db.exec(step.action.toUpperCase()); break;
          case "reopen": db.close(); db = new DatabaseSync(filename); break;
          default: throw Error(`Unsupported cache script action: ${step.action}`);
        }
      } catch (error) { outcome.error = error.message; }
      outcome.state = snapshot();
      outcomes.push(outcome);
    }
    return outcomes;
  } finally {
    db.close();
    fs.rmSync(directory, { recursive: true, force: true });
  }
}
