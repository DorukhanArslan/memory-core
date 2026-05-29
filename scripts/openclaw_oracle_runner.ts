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
  recalls?: Array<{
    query?: string;
    results?: unknown[];
    nowMs?: number;
    timezone?: string;
  }>;
  candidates?: unknown[];
  keys?: string[];
  phase?: "light" | "rem";
  path?: string;
  snippet?: string;
  conceptLimit?: number;
  limit?: number;
  minScore?: number;
  minRecallCount?: number;
  minUniqueQueries?: number;
  maxAgeDays?: number;
  recencyHalfLifeDays?: number;
};

type PromotionPolicy = {
  enabled?: boolean;
  limit?: number;
  minScore?: number;
  minRecallCount?: number;
  minUniqueQueries?: number;
  maxAgeDays?: number;
  recencyHalfLifeDays?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

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

async function resolvePromotionPolicy(repoPath: string, payload: Payload): Promise<PromotionPolicy> {
  const dreaming = await importFromRepo(repoPath, "src/memory-host-sdk/dreaming.ts");
  const pluginConfig = resolveMemoryCorePluginConfig(payload.config);
  const resolved = dreaming.resolveMemoryDeepDreamingConfig({
    pluginConfig,
    cfg: payload.config ?? {},
  });

  // Match managed deep dreaming defaults, while allowing explicit oracle payload overrides.
  return {
    enabled: resolved.enabled,
    limit: payload.limit ?? resolved.limit,
    minScore: payload.minScore ?? resolved.minScore,
    minRecallCount: payload.minRecallCount ?? resolved.minRecallCount,
    minUniqueQueries: payload.minUniqueQueries ?? resolved.minUniqueQueries,
    maxAgeDays: payload.maxAgeDays ?? resolved.maxAgeDays,
    recencyHalfLifeDays: payload.recencyHalfLifeDays ?? resolved.recencyHalfLifeDays,
  };
}

function resolveMemoryCorePluginConfig(config?: Record<string, unknown>): Record<string, unknown> {
  const plugins = isRecord(config?.plugins) ? config.plugins : undefined;
  const entries = isRecord(plugins?.entries) ? plugins.entries : undefined;
  const memoryCore = isRecord(entries?.["memory-core"]) ? entries["memory-core"] : undefined;
  const memoryCoreConfig = isRecord(memoryCore?.config) ? memoryCore.config : undefined;
  return memoryCoreConfig ?? config ?? {};
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
    const resolved = await resolvePromotionPolicy(repoPath, payload);
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

  if (payload.operation === "deriveConceptTags") {
    const vocabulary = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/concept-vocabulary.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: {
        conceptTags: vocabulary.deriveConceptTags({
          path: payload.path ?? "",
          snippet: payload.snippet ?? "",
          limit: payload.conceptLimit,
        }),
      },
    };
  }

  if (payload.operation === "flushPlan") {
    const flushPlan = await importFromRepo(repoPath, "extensions/memory-core/src/flush-plan.ts");
    const plan = flushPlan.buildMemoryFlushPlan({
      cfg: payload.config ?? {},
      nowMs,
    });
    return {
      ok: true,
      operation: payload.operation,
      result: plan
        ? {
            softThresholdTokens: plan.softThresholdTokens,
            forceFlushTranscriptBytes: plan.forceFlushTranscriptBytes,
            reserveTokensFloor: plan.reserveTokensFloor,
            relativePath: plan.relativePath,
            prompt: plan.prompt,
            systemPrompt: plan.systemPrompt,
            model: plan.model ?? null,
          }
        : null,
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

  if (payload.operation === "recordShortTermRecallSequence") {
    for (const recall of payload.recalls ?? []) {
      await promotion.recordShortTermRecalls({
        workspaceDir: payload.workspaceDir,
        query: recall.query ?? "",
        results: recall.results ?? [],
        nowMs: Number.isFinite(recall.nowMs) ? Number(recall.nowMs) : nowMs,
        timezone: recall.timezone ?? timezone,
      });
    }
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
    const policy = await resolvePromotionPolicy(repoPath, payload);
    const candidates = await promotion.rankShortTermPromotionCandidates({
      workspaceDir: payload.workspaceDir,
      nowMs,
      limit: policy.limit,
      minScore: policy.minScore,
      minRecallCount: policy.minRecallCount,
      minUniqueQueries: policy.minUniqueQueries,
      maxAgeDays: policy.maxAgeDays,
      recencyHalfLifeDays: policy.recencyHalfLifeDays,
    });
    return { ok: true, operation: payload.operation, result: { candidates } };
  }

  if (payload.operation === "applyShortTermPromotions") {
    const policy = await resolvePromotionPolicy(repoPath, payload);
    const result = await promotion.applyShortTermPromotions({
      workspaceDir: payload.workspaceDir,
      nowMs,
      timezone,
      candidates: payload.candidates ?? [],
      limit: policy.limit,
      minScore: policy.minScore,
      minRecallCount: policy.minRecallCount,
      minUniqueQueries: policy.minUniqueQueries,
      maxAgeDays: policy.maxAgeDays,
      memoryFileMaxChars:
        typeof payload.memoryFileMaxChars === "number" ? payload.memoryFileMaxChars : undefined,
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
