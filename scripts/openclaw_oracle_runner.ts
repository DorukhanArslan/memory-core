import fs from "node:fs/promises";
import crypto from "node:crypto";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Payload = {
  repoPath: string;
  operation: string;
  workspaceDir?: string;
  stateDir?: string;
  nowMs?: number;
  timezone?: string;
  config?: Record<string, unknown>;
  query?: string;
  corpus?: "memory" | "sessions" | "wiki" | "all";
  maxResults?: number;
  results?: unknown[];
  wikiResults?: unknown[];
  sessionTranscripts?: Array<{
    fileName?: string;
    entries?: unknown[];
  }>;
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
  from?: number;
  lines?: number;
  snippet?: string;
  conceptLimit?: number;
  limit?: number;
  minScore?: number;
  vectorWeight?: number;
  textWeight?: number;
  minRecallCount?: number;
  minUniqueQueries?: number;
  maxAgeDays?: number;
  recencyHalfLifeDays?: number;
  memoryFileMaxChars?: number;
  maxPromotedSnippetTokens?: number;
  entry?: Record<string, unknown>;
  tokenCount?: number;
  contextWindowTokens?: number;
  reserveTokensFloor?: number;
  softThresholdTokens?: number;
  reserveTokens?: number;
  toolResultMaxChars?: number;
  maxChars?: number;
  aggregateMaxChars?: number;
  protectTrailingToolResults?: boolean;
  text?: string;
  erroredAssistantResultPolicy?: "preserve" | "drop";
  systemPrompt?: string;
  prompt?: string;
  messages?: Array<Record<string, unknown>>;
  unwindowedMessages?: Array<Record<string, unknown>>;
  sessionEntries?: Array<Record<string, unknown>>;
};

type PromotionPolicy = {
  enabled?: boolean;
  limit?: number;
  minScore?: number;
  minRecallCount?: number;
  minUniqueQueries?: number;
  maxAgeDays?: number;
  recencyHalfLifeDays?: number;
  maxPromotedSnippetTokens?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeRepairMessage(message: unknown): unknown {
  if (!isRecord(message)) {
    return message;
  }
  const out: Record<string, unknown> = { ...message };
  if (typeof out.timestamp === "number" && Number.isFinite(out.timestamp)) {
    out.timestamp = "__number__";
  }
  return out;
}

function normalizeTimestampedMessage(message: unknown): unknown {
  if (!isRecord(message)) {
    return message ?? null;
  }
  const out: Record<string, unknown> = { ...message };
  if (typeof out.timestamp === "number" && Number.isFinite(out.timestamp)) {
    out.timestamp = "__number__";
  }
  return out;
}

function deterministicEmbedding(text: string, dimensions = 8): number[] {
  const digest = crypto.createHash("sha256").update(text).digest();
  return Array.from({ length: dimensions }, (_, index) => digest[index % digest.length] / 255);
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

const SHORT_TERM_RECALL_JSON = path.join("memory", ".dreams", "short-term-recall.json");
const SHORT_TERM_PHASE_SIGNAL_JSON = path.join("memory", ".dreams", "phase-signals.json");

type PromotionStateModule = {
  __testing: {
    readRecallStore: (workspaceDir: string, nowIso: string) => Promise<Record<string, unknown>>;
    readPhaseSignalStore: (
      workspaceDir: string,
      nowIso: string,
    ) => Promise<Record<string, unknown>>;
    writeRawRecallStore: (workspaceDir: string, raw: unknown) => Promise<void>;
    writeRawPhaseSignalStore: (workspaceDir: string, raw: unknown) => Promise<void>;
  };
};

async function readJsonFixture(filePath: string): Promise<unknown | undefined> {
  let raw: string;
  try {
    raw = await fs.readFile(filePath, "utf-8");
  } catch {
    return undefined;
  }
  try {
    return JSON.parse(raw);
  } catch {
    // Unreadable stores behave like missing stores upstream.
    return undefined;
  }
}

async function seedPromotionStateFromWorkspace(
  promotion: PromotionStateModule,
  workspaceDir?: string,
): Promise<void> {
  if (!workspaceDir) {
    return;
  }
  const recallRaw = await readJsonFixture(path.join(workspaceDir, SHORT_TERM_RECALL_JSON));
  if (recallRaw !== undefined) {
    await promotion.__testing.writeRawRecallStore(workspaceDir, recallRaw);
  }
  const phaseRaw = await readJsonFixture(path.join(workspaceDir, SHORT_TERM_PHASE_SIGNAL_JSON));
  if (phaseRaw !== undefined) {
    await promotion.__testing.writeRawPhaseSignalStore(workspaceDir, phaseRaw);
  }
}

function withSortedEntries(store: Record<string, unknown>): Record<string, unknown> {
  const entries = isRecord(store.entries) ? store.entries : {};
  return {
    ...store,
    entries: Object.fromEntries(
      Object.entries(entries).toSorted(([a], [b]) => a.localeCompare(b)),
    ),
  };
}

async function exportPromotionStateToWorkspace(
  promotion: PromotionStateModule,
  workspaceDir: string | undefined,
  nowMs: number,
): Promise<void> {
  if (!workspaceDir) {
    return;
  }
  const nowIso = new Date(nowMs).toISOString();
  const [recallStore, phaseStore] = await Promise.all([
    promotion.__testing.readRecallStore(workspaceDir, nowIso),
    promotion.__testing.readPhaseSignalStore(workspaceDir, nowIso),
  ]);
  await fs.mkdir(path.join(workspaceDir, "memory", ".dreams"), { recursive: true });
  await Promise.all([
    fs.writeFile(
      path.join(workspaceDir, SHORT_TERM_RECALL_JSON),
      `${JSON.stringify(withSortedEntries(recallStore), null, 2)}\n`,
      "utf-8",
    ),
    fs.writeFile(
      path.join(workspaceDir, SHORT_TERM_PHASE_SIGNAL_JSON),
      `${JSON.stringify(withSortedEntries(phaseStore), null, 2)}\n`,
      "utf-8",
    ),
  ]);
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

async function writeSessionTranscriptFixtures(payload: Payload): Promise<void> {
  if (!payload.stateDir || !payload.sessionTranscripts?.length) {
    return;
  }
  const sessionsDir = path.join(payload.stateDir, "agents", "main", "sessions");
  await fs.mkdir(sessionsDir, { recursive: true });
  const sessionStore: Record<string, Record<string, unknown>> = {};
  for (const transcript of payload.sessionTranscripts) {
    const fileName = transcript.fileName?.trim() || "session-oracle.jsonl";
    if (fileName.includes("/") || fileName.includes("\\") || !fileName.endsWith(".jsonl")) {
      throw new Error(`invalid session transcript fixture name: ${fileName}`);
    }
    const lines = (transcript.entries ?? []).map((entry) => JSON.stringify(entry));
    await fs.writeFile(path.join(sessionsDir, fileName), `${lines.join("\n")}\n`, "utf-8");
    const sessionId = fileName.slice(0, -".jsonl".length);
    sessionStore[`agent:main:${sessionId}`] = {
      sessionId,
      sessionFile: fileName,
      updatedAt: Date.now(),
    };
  }
  await fs.writeFile(
    path.join(sessionsDir, "sessions.json"),
    `${JSON.stringify(sessionStore, null, 2)}\n`,
    "utf-8",
  );
}

async function registerWikiCorpusFixture(repoPath: string, payload: Payload): Promise<void> {
  if (!payload.wikiResults?.length) {
    return;
  }
  const memoryState = await importFromRepo(repoPath, "src/plugins/memory-state.ts");
  memoryState.registerMemoryCorpusSupplement("memory-wiki", {
    search: async () => payload.wikiResults ?? [],
    get: async () => null,
  });
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
    maxPromotedSnippetTokens:
      payload.maxPromotedSnippetTokens ?? resolved.maxPromotedSnippetTokens,
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
        maxPromotedSnippetTokens: resolved.maxPromotedSnippetTokens,
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

  if (payload.operation === "memoryFlushGate") {
    const memoryFlush = await importFromRepo(repoPath, "src/auto-reply/reply/memory-flush.ts");
    const entry = payload.entry ?? undefined;
    return {
      ok: true,
      operation: payload.operation,
      result: {
        shouldRunMemoryFlush: memoryFlush.shouldRunMemoryFlush({
          entry,
          tokenCount: payload.tokenCount,
          contextWindowTokens: payload.contextWindowTokens ?? 100_000,
          reserveTokensFloor: payload.reserveTokensFloor ?? 20_000,
          softThresholdTokens: payload.softThresholdTokens ?? 4_000,
        }),
        hasAlreadyFlushedForCurrentCompaction: entry
          ? memoryFlush.hasAlreadyFlushedForCurrentCompaction(entry)
          : false,
      },
    };
  }

  if (payload.operation === "toolResultReductionPotential") {
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    const result = truncation.estimateToolResultReductionPotential({
      messages: payload.messages ?? [],
      contextWindowTokens: payload.contextWindowTokens ?? 100_000,
      maxCharsOverride: payload.toolResultMaxChars,
      aggregateMaxCharsOverride: payload.aggregateMaxChars,
    });
    return {
      ok: true,
      operation: payload.operation,
      result,
    };
  }

  if (payload.operation === "truncateToolResultText") {
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: {
        text: truncation.truncateToolResultText(
          payload.text ?? "",
          payload.maxChars ?? payload.toolResultMaxChars ?? 16_000,
        ),
      },
    };
  }

  if (payload.operation === "truncateToolResultsInSession") {
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    const sessions = await importFromRepo(repoPath, "src/agents/sessions/index.ts");
    const tmpDir = await fs.mkdtemp(path.join(process.cwd(), ".openclaw-oracle-session-"));
    try {
      const manager = sessions.SessionManager.create(tmpDir, tmpDir);
      for (const entry of payload.sessionEntries ?? []) {
        if (entry.type === "message" && isRecord(entry.message)) {
          manager.appendMessage(entry.message);
        }
      }
      const sessionFile = manager.getSessionFile();
      if (!sessionFile) {
        throw new Error("session file missing");
      }
      const result = await truncation.truncateOversizedToolResultsInSession({
        sessionFile,
        contextWindowTokens: payload.contextWindowTokens ?? 100_000,
        maxCharsOverride: payload.maxChars ?? payload.toolResultMaxChars,
        aggregateMaxCharsOverride: payload.aggregateMaxChars,
        protectTrailingToolResults: payload.protectTrailingToolResults,
      });
      const afterManager = sessions.SessionManager.open(sessionFile);
      const toolResultMessages = afterManager
        .getBranch()
        .filter((entry: Record<string, unknown>) => {
          const message = entry.message as Record<string, unknown> | undefined;
          return entry.type === "message" && message?.role === "toolResult";
        })
        .map((entry: Record<string, unknown>) => entry.message as Record<string, unknown>);
      const findTextBlock = (message: Record<string, unknown>) => {
        const content = Array.isArray(message.content) ? message.content : [];
        return content.find(
          (block: unknown) =>
            isRecord(block) &&
            (block.type === "text" || block.type === "toolResult") &&
            typeof block.text === "string",
        ) as { text?: string; content?: unknown } | undefined;
      };
      const toolTexts = toolResultMessages.map((message) => findTextBlock(message)?.text ?? "");
      const toolContents = toolResultMessages.map((message) => {
        const blockContent = findTextBlock(message)?.content;
        return typeof blockContent === "string" ? blockContent : null;
      });
      return {
        ok: true,
        operation: payload.operation,
        result: {
          truncated: result.truncated,
          truncatedCount: result.truncatedCount,
          reason: result.reason ?? null,
          toolTexts,
          toolContents,
        },
      };
    } finally {
      await fs.rm(tmpDir, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "preemptiveCompaction") {
    const preemptive = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/run/preemptive-compaction.ts",
    );
    const result = preemptive.shouldPreemptivelyCompactBeforePrompt({
      messages: payload.messages ?? [],
      unwindowedMessages: payload.unwindowedMessages,
      systemPrompt: payload.systemPrompt,
      prompt: payload.prompt ?? "",
      contextTokenBudget: payload.contextWindowTokens ?? 100_000,
      reserveTokens: payload.reserveTokens ?? 0,
      toolResultMaxChars: payload.toolResultMaxChars,
    });
    return {
      ok: true,
      operation: payload.operation,
      result,
    };
  }

  if (payload.operation === "historyLimit") {
    const history = await importFromRepo(repoPath, "src/agents/embedded-agent-runner/history.ts");
    const limits: Record<string, number | null> = {};
    for (const key of payload.keys ?? []) {
      limits[key] = history.getHistoryLimitFromSessionKey(key, payload.config ?? {}) ?? null;
    }
    return {
      ok: true,
      operation: payload.operation,
      result: {
        limitedMessages: history.limitHistoryTurns(payload.messages ?? [], payload.limit),
        limits,
      },
    };
  }

  if (payload.operation === "repairToolUseResultPairing") {
    const repair = await importFromRepo(repoPath, "src/agents/session-transcript-repair.ts");
    const result = repair.repairToolUseResultPairing(payload.messages ?? [], {
      ...(payload.erroredAssistantResultPolicy
        ? { erroredAssistantResultPolicy: payload.erroredAssistantResultPolicy }
        : {}),
      ...(typeof payload.text === "string" ? { missingToolResultText: payload.text } : {}),
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        messages: result.messages.map(normalizeRepairMessage),
        added: result.added.map(normalizeRepairMessage),
        droppedDuplicateCount: result.droppedDuplicateCount,
        droppedOrphanCount: result.droppedOrphanCount,
        moved: result.moved,
      },
    };
  }

  if (payload.operation === "runtimeContextPrompt") {
    const runtimeContextPrompt = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/run/runtime-context-prompt.ts",
    );
    const runtimeContext = "secret runtime context";
    return {
      ok: true,
      operation: payload.operation,
      result: {
        parts: runtimeContextPrompt.resolveRuntimeContextPromptParts({
          effectivePrompt: payload.prompt ?? "",
          transcriptPrompt: payload.text,
          modelPrompt: payload.systemPrompt,
        }),
        currentInboundPrompt: runtimeContextPrompt.buildCurrentInboundPrompt({
          context: payload.entry,
          prompt: "What do you mean hidden?",
        }),
        customMessage: normalizeTimestampedMessage(
          runtimeContextPrompt.buildRuntimeContextCustomMessage(runtimeContext),
        ),
      },
    };
  }

  if (payload.operation === "contextEngineLifecycle") {
    const lifecycle = await importFromRepo(repoPath, "src/agents/harness/context-engine-lifecycle.ts");
    let assembleMessages: unknown[] = [];
    let snapshotParams: { messages?: unknown[]; prePromptMessageCount?: number } = {};
    const contextEngine = {
      info: { id: "oracle", name: "Oracle context engine" },
      ingest: async () => ({ ingested: true }),
      assemble: async (params: { messages?: unknown[] }) => {
        assembleMessages = params.messages ?? [];
        return { messages: params.messages ?? [], estimatedTokens: 0 };
      },
      afterTurn: async (params: { messages?: unknown[]; prePromptMessageCount?: number }) => {
        snapshotParams = {
          messages: params.messages ?? [],
          prePromptMessageCount: params.prePromptMessageCount,
        };
      },
      compact: async () => ({ ok: true, compacted: false }),
    };
    await lifecycle.assembleHarnessContextEngine({
      contextEngine,
      sessionId: "session-1",
      sessionKey: "agent:main",
      messages: payload.messages ?? [],
      modelId: "gpt-test",
    });
    await lifecycle.finalizeHarnessContextEngineTurn({
      contextEngine,
      promptError: false,
      aborted: false,
      yieldAborted: false,
      sessionIdUsed: "session-1",
      sessionKey: "agent:main",
      sessionFile: "sessions/main.jsonl",
      messagesSnapshot: payload.messages ?? [],
      prePromptMessageCount: payload.limit ?? 0,
      tokenBudget: payload.contextWindowTokens,
      runtimeContext: {},
      runMaintenance: async () => undefined,
      warn: () => {},
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        assembleMessages,
        conversationSnapshot: {
          messages: snapshotParams.messages ?? [],
          prePromptMessageCount: snapshotParams.prePromptMessageCount ?? 0,
        },
      },
    };
  }

  if (payload.operation === "normalizeAssistantReplayContent") {
    const replayHistory = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/replay-history.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: {
        messages: replayHistory.normalizeAssistantReplayContent(payload.messages ?? []),
      },
    };
  }

  if (payload.operation === "overflowErrorHelpers") {
    const helpers = await importFromRepo(repoPath, "src/agents/embedded-agent-helpers.ts");
    const text = payload.text ?? "";
    return {
      ok: true,
      operation: payload.operation,
      result: {
        isLikelyContextOverflowError: helpers.isLikelyContextOverflowError(text),
        isCompactionFailureError: helpers.isCompactionFailureError(text),
        extractObservedOverflowTokenCount:
          helpers.extractObservedOverflowTokenCount(text) ?? null,
      },
    };
  }

  if (payload.operation === "memoryGet") {
    const runtimeFiles = await importFromRepo(
      repoPath,
      "packages/memory-host-sdk/src/host/read-file.ts",
    );
    const baseConfig = payload.config ?? {};
    const agents = isRecord(baseConfig.agents) ? baseConfig.agents : {};
    const defaults = isRecord(agents.defaults) ? agents.defaults : {};
    const cfg = {
      ...baseConfig,
      agents: {
        ...agents,
        defaults: {
          ...defaults,
          ...(payload.workspaceDir ? { workspace: payload.workspaceDir } : {}),
        },
      },
    };
    let result: unknown;
    try {
      result = await runtimeFiles.readAgentMemoryFile({
        cfg,
        agentId: "main",
        relPath: payload.path ?? "",
        from: payload.from,
        lines: payload.lines,
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      result = { path: payload.path ?? "", text: "", disabled: true, error: message };
    }
    return {
      ok: true,
      operation: payload.operation,
      result,
    };
  }

  if (payload.operation === "memorySearch") {
    // OpenClaw HEAD ignores agents.defaults.memorySearch.store.path: the index
    // always lives at <stateDir>/agents/<agentId>/agent/openclaw-agent.sqlite
    // (resolveOpenClawAgentSqlitePath). Point OPENCLAW_STATE_DIR at a
    // per-invocation directory before importing repo modules so fixtures never
    // share an index with each other or with the real user state dir.
    const stateDir =
      payload.stateDir ??
      (payload.workspaceDir
        ? path.join(payload.workspaceDir, ".openclaw-state")
        : await fs.mkdtemp(path.join(process.cwd(), ".openclaw-oracle-state-")));
    process.env.OPENCLAW_STATE_DIR = stateDir;
    await writeSessionTranscriptFixtures({ ...payload, stateDir });
    await registerWikiCorpusFixture(repoPath, payload);
    const embeddingProviders = await importFromRepo(
      repoPath,
      "src/plugins/memory-embedding-providers.ts",
    );
    embeddingProviders.registerMemoryEmbeddingProvider({
      id: "memory-core-fake",
      defaultModel: "fake-deterministic",
      create: async () => ({
        provider: {
          id: "memory-core-fake",
          model: "fake-deterministic",
          embedQuery: async (text: string) => deterministicEmbedding(`query:${text}`),
          embedBatch: async (texts: string[]) =>
            texts.map((text) => deterministicEmbedding(`document:${text}`)),
        },
      }),
    });

    const tools = await importFromRepo(repoPath, "extensions/memory-core/src/tools.ts");
    const memoryIndex = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory/index.ts",
    );
    const baseConfig = payload.config ?? {};
    const agents = isRecord(baseConfig.agents) ? baseConfig.agents : {};
    const defaults = isRecord(agents.defaults) ? agents.defaults : {};
    const defaultMemorySearch = isRecord(defaults.memorySearch) ? defaults.memorySearch : {};
    const defaultQuery = isRecord(defaultMemorySearch.query) ? defaultMemorySearch.query : {};
    const defaultHybrid = isRecord(defaultQuery.hybrid) ? defaultQuery.hybrid : {};
    const cfg = {
      ...baseConfig,
      memory: {
        ...(isRecord(baseConfig.memory) ? baseConfig.memory : {}),
        backend: "builtin",
        citations: "on",
      },
      agents: {
        ...agents,
        defaults: {
          ...defaults,
          ...(payload.workspaceDir ? { workspace: payload.workspaceDir } : {}),
          memorySearch: {
            ...defaultMemorySearch,
            provider: "memory-core-fake",
            model: "fake-deterministic",
            sync: {
              ...(isRecord(defaultMemorySearch.sync) ? defaultMemorySearch.sync : {}),
              watch: false,
              onSessionStart: false,
              onSearch: false,
            },
            query: {
              ...defaultQuery,
              minScore: payload.minScore ?? defaultQuery.minScore ?? 0,
              maxResults: payload.maxResults ?? defaultQuery.maxResults ?? 5,
              hybrid: {
                ...defaultHybrid,
                enabled: true,
                vectorWeight: payload.vectorWeight ?? 0,
                textWeight: payload.textWeight ?? 1,
              },
            },
            cache: { enabled: false },
          },
        },
        list: [{ id: "main", default: true }],
      },
    };
    const firstSessionFileName = payload.sessionTranscripts?.[0]?.fileName?.trim();
    const requesterSessionId =
      firstSessionFileName && firstSessionFileName.endsWith(".jsonl")
        ? firstSessionFileName.slice(0, -".jsonl".length)
        : "oracle";
    try {
      const tool = tools.createMemorySearchTool({
        config: cfg,
        agentId: "main",
        agentSessionKey: `agent:main:${requesterSessionId}`,
      });
      if (!tool) {
        throw new Error("memory_search tool missing");
      }
      const result = await tool.execute("memory_search_oracle", {
        query: payload.query ?? "",
        corpus: payload.corpus ?? "all",
        maxResults: payload.maxResults,
        minScore: payload.minScore,
      });
      return {
        ok: true,
        operation: payload.operation,
        result: result.details,
      };
    } finally {
      await memoryIndex.closeAllMemorySearchManagers();
    }
  }

  const promotionOperations = new Set([
    "recordShortTermRecalls",
    "recordShortTermRecallSequence",
    "recordDreamingPhaseSignals",
    "rankShortTermPromotionCandidates",
    "applyShortTermPromotions",
  ]);
  if (!promotionOperations.has(payload.operation)) {
    throw new Error(`unsupported operation: ${payload.operation}`);
  }

  // OpenClaw HEAD stores recall/phase-signal/lock state in SQLite-backed plugin
  // state instead of memory/.dreams/*.json. Every oracle invocation is a fresh
  // process, so the workspace JSON files remain the durable fixture contract:
  // seed plugin state from them before the operation and export plugin state
  // back to them afterwards. Fixtures can therefore keep reading and editing
  // the JSON files between invocations.
  const promotionStateDir = await fs.mkdtemp(
    path.join(os.tmpdir(), "openclaw-oracle-dream-state-"),
  );
  process.env.OPENCLAW_STATE_DIR = promotionStateDir;
  const dreamingState = await importFromRepo(
    repoPath,
    "extensions/memory-core/src/dreaming-state.ts",
  );
  await dreamingState.configureMemoryCoreDreamingStateForTests();
  const promotion = await importFromRepo(
    repoPath,
    "extensions/memory-core/src/short-term-promotion.ts",
  );

  try {
    await seedPromotionStateFromWorkspace(promotion, payload.workspaceDir);
    const snapshotPromotionFiles = async () => {
      await exportPromotionStateToWorkspace(promotion, payload.workspaceDir, nowMs);
      return snapshotFiles(payload.workspaceDir);
    };

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
        files: await snapshotPromotionFiles(),
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
        files: await snapshotPromotionFiles(),
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
        files: await snapshotPromotionFiles(),
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
      maxPromotedSnippetTokens: policy.maxPromotedSnippetTokens,
    });
    return {
      ok: true,
      operation: payload.operation,
      result,
      files: await snapshotPromotionFiles(),
    };
  } finally {
    await fs.rm(promotionStateDir, { recursive: true, force: true }).catch(() => {});
  }
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
