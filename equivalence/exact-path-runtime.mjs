// Actual authenticated release keyword merge/limit methods. The manager
// constructor, providers and full search orchestration are not exercised here.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

export async function runExactPathRuntime(input, runtimeConfig) {
  if (!["limit", "merge-limit"].includes(input.kind)) {
    throw Error(`Unsupported compiled exact-path operation: ${input.kind}`);
  }
  const runtimeRoot = runtimeConfig?.runtimeRoot;
  if (!runtimeRoot || !path.isAbsolute(runtimeRoot)) {
    throw Error("An authenticated absolute release runtimeRoot is required");
  }
  const relative = "dist/extensions/memory-core/manager-runtime.js";
  const { MemoryIndexManager } = await import(pathToFileURL(path.join(runtimeRoot, relative)).href);
  const manager = Object.create(MemoryIndexManager.prototype);
  let merged;
  if (input.kind === "merge-limit") {
    merged = manager.mergeKeywordSearchHits(structuredClone(input.resultSets), input.query);
  } else {
    merged = structuredClone(input.rows);
  }
  const rows = manager.limitKeywordSearchHits(merged, input.limit);
  if (!runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("An authenticated absolute runtime evidence directory is required");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([{
    owner: relative, constructorExecuted: false, provider: "none",
    kind: input.kind, input: structuredClone(input), merged, rows,
  }]));
  return { provider: "none", rows };
}
