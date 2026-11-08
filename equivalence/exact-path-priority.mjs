// Fixture transport for original exact-path matcher, SQLite reader and hybrid.
// Ranking, path admission, row projection and score selection execute upstream.
import { DatabaseSync } from "node:sqlite";

function arrangeDatabase(input) {
  if ((input.ftsTokenizer ?? "unicode61") !== "unicode61") {
    throw Error("Only the paired unicode61 path-index capability is verified");
  }
  const db = new DatabaseSync(":memory:");
  try {
    const encoding = input.encoding ?? "UTF-8";
    if (!["UTF-8", "UTF-16le", "UTF-16be"].includes(encoding)) throw Error("Unsupported SQLite encoding");
    db.exec(`PRAGMA encoding='${encoding}'`);
    db.exec("CREATE TABLE memory_index_chunks (id TEXT PRIMARY KEY,path TEXT NOT NULL," +
      "source TEXT NOT NULL,start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,text TEXT NOT NULL)");
    db.exec("CREATE VIRTUAL TABLE memory_index_paths_fts USING fts5(path,source UNINDEXED,tokenize='unicode61')");
    const insert = db.prepare("INSERT INTO memory_index_chunks(id,path,source,start_line,end_line,text) VALUES (?,?,?,?,?,?)");
    for (const row of input.chunks) {
      insert.run(row.id, row.path, row.source, row.startLine, row.endLine, row.text);
    }
    const paths = input.paths ?? [...new Map(input.chunks.map((row) =>
      [JSON.stringify([row.path, row.source]), { path: row.path, source: row.source }])).values()];
    const insertPath = db.prepare("INSERT INTO memory_index_paths_fts(path,source) VALUES (?,?)");
    for (const row of paths) insertPath.run(row.path, row.source);
    return db;
  } catch (error) {
    db.close();
    throw error;
  }
}

const asMap = (value) => value === null ? null : new Map(Object.entries(value));

export async function runExactPathPriority(input, importReference) {
  if (!["matcher", "path-search", "path-hybrid", "pipeline"].includes(input.kind)) {
    throw Error(`Unsupported source exact-path operation: ${input.kind}`);
  }
  const owner = await importReference("extensions/memory-core/src/memory/manager-search.ts");
  if (input.kind === "matcher") {
    const match = owner.prepareExactPathMatcher(input.query);
    return { specificities: input.paths.map((path) => match(path)) };
  }
  const query = await importReference("extensions/memory-core/src/memory/keyword-query.ts");
  const db = arrangeDatabase(input);
  try {
    const sourceFilter = input.sources?.length ? {
      sql: ` AND memory_index_paths_fts.source IN (${input.sources.map(() => "?").join(",")})`,
      params: input.sources,
    } : { sql: "", params: [] };
    const params = {
      db, pathFtsTable: "memory_index_paths_fts", query: input.query,
      limit: input.limit, snippetMaxChars: input.snippetMaxChars,
      ftsTokenizer: input.ftsTokenizer ?? "unicode61", sourceFilter,
      buildFtsQuery: query.buildFtsQuery, bm25RankToScore: query.bm25RankToScore,
    };
    for (const name of ["exactPathQuery", "exactPathLimit"]) {
      if (Object.hasOwn(input, name)) params[name] = input[name];
    }
    const pathRows = await owner.searchPathKeyword(params);
    if (input.kind === "path-search") return { rows: pathRows };
    // These are declared body candidates at the hybrid boundary. The separately
    // authenticated runtime cases execute private keyword merge/limit behavior;
    // this transport does not replace those owners with an oracle algorithm.
    const match = owner.prepareExactPathMatcher(input.exactPathQuery ?? input.query);
    const keywordRows = [...pathRows, ...structuredClone(input.bodyRows ?? []).map((row) =>
      ({ ...row, exactPathSpecificity: match(row.path) }))];
    const hybrid = await importReference("extensions/memory-core/src/memory/hybrid.ts");
    const mergeParams = {
      vector: structuredClone(input.vector ?? []).map((row) =>
        ({ ...row, exactPathSpecificity: match(row.path) })),
      keyword: keywordRows.map(({ score, ...row }) => ({ ...row, rankingScore: score })),
      vectorWeight: input.vectorWeight, textWeight: input.textWeight,
    };
    for (const name of ["temporalDecay", "mmr", "nowMs", "activeProjectKeys"]) {
      if (Object.hasOwn(input, name)) mergeParams[name] = structuredClone(input[name]);
    }
    for (const name of ["sessionSourceMtimes", "memorySourceMtimes"]) {
      if (Object.hasOwn(input, name)) mergeParams[name] = asMap(input[name]);
    }
    const merged = await hybrid.mergeHybridResults(mergeParams);
    const selected = hybrid.selectHybridSearchResults({
      merged, keyword: mergeParams.keyword, maxResults: input.maxResults, minScore: input.minScore,
    });
    return { pathRows, merged, selected };
  } finally {
    db.close();
  }
}
