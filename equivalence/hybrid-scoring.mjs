// Fixture transport for unchanged native hybrid merge and selection owners.
// All candidate fields and returned fields are retained; ranking runs upstream.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const asMap = (value) => value === null ? null : new Map(Object.entries(value));

export async function runHybridScoring(input, importReference) {
  if (!["merge", "select", "merge-select"].includes(input.kind)) {
    throw Error(`Unsupported hybrid scoring operation: ${input.kind}`);
  }
  const owner = await importReference("extensions/memory-core/src/memory/hybrid.ts");
  const workspace = Object.hasOwn(input, "workspaceFiles")
    ? fs.mkdtempSync(path.join(os.tmpdir(), "memory-hybrid-scoring-")) : undefined;
  try {
    for (const file of input.workspaceFiles ?? []) {
      if (path.isAbsolute(file.path) || file.path.split(/[\\/]/).includes("..")) {
        throw Error("Workspace fixture files must stay within their owned directory");
      }
      const filename = path.join(workspace, file.path);
      fs.mkdirSync(path.dirname(filename), { recursive: true });
      fs.writeFileSync(filename, file.text ?? "");
      fs.utimesSync(filename, file.mtimeMs / 1000, file.mtimeMs / 1000);
    }
    let merged;
    if (input.kind === "select") {
      merged = structuredClone(input.merged);
    } else {
      const params = {
        vector: structuredClone(input.vector),
        keyword: structuredClone(input.keyword),
        vectorWeight: input.vectorWeight,
        textWeight: input.textWeight,
      };
      for (const name of ["workspaceDir", "temporalDecay", "mmr", "nowMs", "activeProjectKeys"]) {
        if (Object.hasOwn(input, name)) params[name] = structuredClone(input[name]);
      }
      if (workspace !== undefined) params.workspaceDir = workspace;
      for (const name of ["sessionSourceMtimes", "memorySourceMtimes"]) {
        if (Object.hasOwn(input, name)) params[name] = asMap(input[name]);
      }
      if (Object.hasOwn(input, "mediaPaths")) {
        const paths = new Set(input.mediaPaths);
        params.isNonTextMediaPath = (path) => paths.has(path);
      }
      merged = await owner.mergeHybridResults(params);
    }
    if (input.kind === "merge") return { merged };
    const selected = owner.selectHybridSearchResults({
      merged, keyword: structuredClone(input.keyword),
      maxResults: input.maxResults, minScore: input.minScore,
    });
    return input.kind === "select" ? { selected } : { merged, selected };
  } finally {
    if (workspace !== undefined) fs.rmSync(workspace, { recursive: true, force: true });
  }
}
