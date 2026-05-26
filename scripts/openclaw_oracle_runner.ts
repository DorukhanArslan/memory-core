import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Payload = {
  repoPath: string;
  operation: string;
  workspaceDir?: string;
  nowMs?: number;
  timezone?: string;
  config?: Record<string, unknown>;
  query?: string;
  results?: unknown[];
  candidates?: unknown[];
  keys?: string[];
  phase?: "light" | "rem";
};

async function readStdin(): Promise<Payload> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf-8")) as Payload;
}

async function importFromRepo(repoPath: string, relativePath: string) {
  const fullPath = path.join(repoPath, relativePath);
  return await import(pathToFileURL(fullPath).href);
}

async function snapshotFiles(workspaceDir?: string): Promise<Record<string, string>> {
  if (!workspaceDir) {
    return {};
  }
  const files = [
    "MEMORY.md",
    "DREAMS.md",
    path.join("memory", ".dreams", "short-term-recall.json"),
    path.join("memory", ".dreams", "phase-signals.json"),
  ];
  const out: Record<string, string> = {};
  for (const rel of files) {
    try {
      out[rel.replaceAll("\\", "/")] = await fs.readFile(path.join(workspaceDir, rel), "utf-8");
    } catch {
      out[rel.replaceAll("\\", "/")] = "";
    }
  }
  return out;
}

async function main() {
  const payload = await readStdin();
  const repoPath = payload.repoPath;
  if (!repoPath) {
    throw new Error("repoPath is required");
  }
  const nowMs = Number.isFinite(payload.nowMs) ? Number(payload.nowMs) : Date.now();
  const timezone = payload.timezone || "UTC";

  if (payload.operation === "deepPolicy") {
    const dreaming = await importFromRepo(repoPath, "src/memory-host-sdk/dreaming.ts");
    const resolved = dreaming.resolveMemoryDeepDreamingConfig({
      pluginConfig: payload.config ?? {},
      cfg: payload.config ?? {},
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        enabled: resolved.enabled,
        limit: resolved.limit,
        minScore: resolved.minScore,
        minRecallCount: resolved.minRecallCount,
        minUniqueQueries: resolved.minUniqueQueries,
        recencyHalfLifeDays: resolved.recencyHalfLifeDays,
        maxAgeDays: resolved.maxAgeDays,
      },
    };
  }

  const promotion = await importFromRepo(
    repoPath,
    "extensions/memory-core/src/short-term-promotion.ts",
  );

  if (payload.operation === "recordShortTermRecalls") {
    await promotion.recordShortTermRecalls({
      workspaceDir: payload.workspaceDir,
      query: payload.query ?? "",
      results: payload.results ?? [],
      nowMs,
      timezone,
    });
    return {
      ok: true,
      operation: payload.operation,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  if (payload.operation === "recordDreamingPhaseSignals") {
    await promotion.recordDreamingPhaseSignals({
      workspaceDir: payload.workspaceDir,
      phase: payload.phase ?? "light",
      keys: payload.keys ?? [],
      nowMs,
    });
    return {
      ok: true,
      operation: payload.operation,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  if (payload.operation === "rankShortTermPromotionCandidates") {
    const candidates = await promotion.rankShortTermPromotionCandidates({
      workspaceDir: payload.workspaceDir,
      nowMs,
      limit: 10,
      minScore: 0.75,
      minRecallCount: 3,
      minUniqueQueries: 2,
    });
    return { ok: true, operation: payload.operation, result: { candidates } };
  }

  if (payload.operation === "applyShortTermPromotions") {
    const result = await promotion.applyShortTermPromotions({
      workspaceDir: payload.workspaceDir,
      nowMs,
      timezone,
      candidates: payload.candidates ?? [],
    });
    return {
      ok: true,
      operation: payload.operation,
      result,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  throw new Error(`unsupported operation: ${payload.operation}`);
}

main()
  .then((result) => {
    process.stdout.write(JSON.stringify(result));
  })
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    process.stdout.write(JSON.stringify({ ok: false, error: { code: "runner-error", message } }));
    process.exitCode = 1;
  });
