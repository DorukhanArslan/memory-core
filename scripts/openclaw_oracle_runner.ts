import fsSync from "node:fs";
import fs from "node:fs/promises";
import crypto from "node:crypto";
import * as nodeModule from "node:module";
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
  rawParams?: unknown;
  embeddingModel?: string;
  identity?: {
    states?: Array<Record<string, unknown>>;
    providerIdentities?: Array<Record<string, unknown>>;
    sources?: string[][];
    scopes?: Array<Record<string, unknown>>;
  };
  unavailableCases?: Array<{ error?: string | null; warning?: string; action?: string }>;
  searchSteps?: Array<{
    rawParams: unknown;
    embedQuery?: string;
    supplement?: string;
    advanceMs?: number;
    deadlineFireMs?: number;
  }>;
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
  maxPriorEntryLossFraction?: number;
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
  bootstrapFiles?: Array<{ name?: string; path?: string; content?: string; missing?: boolean }>;
  contextFiles?: Array<{ path: string; content: string }>;
  totalMaxChars?: number;
  warningMode?: "off" | "once" | "always";
  seenSignatures?: string[];
  bootstrapMode?: "full" | "limited" | "none";
  bootstrapTruncationNotice?: string;
  runs?: Array<{
    sessionKey?: string;
    contextMode?: "full" | "lightweight";
    runKind?: "default" | "heartbeat" | "cron";
  }>;
  steps?: Array<{
    op: "write" | "remove" | "mkdir" | "ensure" | "migrate" | "findings" | "scratch";
    path?: string;
    content?: string | null;
    skipOptional?: string[];
  }>;
  startupContext?: Record<string, unknown>;
  texts?: Array<string | null>;
  repeat?: number;
  stateDirIsFile?: boolean;
  seedArchive?: "same" | "different";
  bootstrapMaxChars?: number;
  cases?: Array<Record<string, any>>;
  scenarios?: Array<Record<string, any>>;
  historySteps?: Array<Record<string, any>>;
  consolidation?: Record<string, any>;
  promotionScenarios?: Array<Record<string, any>>;
  originSteps?: Array<Record<string, any>>;
  recallScenarios?: Array<Record<string, any>>;
  backfillScenarios?: Array<Record<string, any>>;
  ingestScenarios?: Array<Record<string, any>>;
  provenanceScenarios?: Array<Record<string, any>>;
  sessionScenarios?: Array<Record<string, any>>;
  agentIds?: string[];
  lockProbe?: Record<string, any>;
};

const WORKSPACE_STATE_SNAPSHOT_SKIP = new Set([
  "openclaw-workspace-state.json",
  ".openclaw",
  ".memory-core",
  ".git",
]);

async function snapshotWorkspaceTree(workspaceDir: string): Promise<Record<string, string | null>> {
  // Relative path -> file content (null for directories), skipping state files
  // whose location intentionally differs between OpenClaw and memory-core.
  const out: Record<string, string | null> = {};
  const walk = async (relativeDir: string) => {
    const entries = await fs.readdir(path.join(workspaceDir, relativeDir), { withFileTypes: true });
    for (const entry of entries) {
      if (!relativeDir && WORKSPACE_STATE_SNAPSHOT_SKIP.has(entry.name)) {
        continue;
      }
      const rel = relativeDir ? `${relativeDir}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        out[`${rel}/`] = null;
        await walk(rel);
      } else {
        out[rel] = await fs.readFile(path.join(workspaceDir, rel), "utf-8");
      }
    }
  };
  await walk("");
  return Object.fromEntries(Object.entries(out).toSorted(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

function normalizeSetupStateTimestamps(
  raw: string | null,
): Record<string, unknown> | { unparsed: string } | null {
  if (raw === null) {
    return null;
  }
  // At v2026.9.6 upstream no longer writes this file (setup state is in SQLite), so what is
  // read here is a fixture's own legacy file, which may be deliberately corrupt.
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return { unparsed: raw };
  }
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(parsed)) {
    out[key] =
      typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
        ? "__iso__"
        : value;
  }
  return out;
}

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

// Runs one upstream call and returns its thrown message as data, so an op that covers several
// calls reports an upstream refusal (e.g. v2026.9.6's "Legacy workspace setup state requires
// migration") in place instead of failing the whole op.
async function captureUpstreamError<T>(run: () => Promise<T> | T): Promise<T | { error: string }> {
  try {
    return await run();
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
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

async function withIsolatedRuntimeState<T>(prefix: string, run: () => Promise<T>): Promise<T> {
  // Every bootstrap operation gets its own OPENCLAW_STATE_DIR and HOME (set before any repo
  // module is imported) and removes them afterwards, so no operation can read or leave
  // state in the user's real ~/.openclaw or leak temp dirs between test cases.
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), prefix));
  process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
  process.env.HOME = path.join(sandbox, "home");
  await fs.mkdir(process.env.OPENCLAW_STATE_DIR, { recursive: true });
  await fs.mkdir(process.env.HOME, { recursive: true });
  try {
    return await run();
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
  }
}

function bootstrapSectionsText(prompt: string, workspaceIndex: number): string {
  // The bootstrap sections as the prompt carries them: from the first "## Bootstrap Pending" /
  // "## Bootstrap Context Notice" heading up to "## Workspace Files (injected)". The stable prefix
  // is joined with lines.filter(Boolean).join("\n") (src/agents/system-prompt.ts:1143 at
  // v2026.9.6), so upstream itself drops the builder's empty separator lines; blank lines inside
  // one entry (a multi-line truncation notice) survive and are compared as they are.
  const end = workspaceIndex === -1 ? prompt.length : workspaceIndex;
  const starts = ["## Bootstrap Pending\n", "## Bootstrap Context Notice\n"]
    .map((heading) => prompt.indexOf(heading))
    .filter((index) => index !== -1 && index < end);
  if (starts.length === 0) {
    return "";
  }
  return prompt.slice(Math.min(...starts), end).replace(/\n$/, "");
}

// Workspace-step sandbox shared by workspaceLifecycle and workspaceBootstrapFiles: HOME points
// at a temp dir, PATH is emptied so git is unavailable (memory-core does not port git init), and
// one OPENCLAW_STATE_DIR keeps the agent's SQLite setup state across the steps.
async function withWorkspaceStepSandbox<T>(run: () => Promise<T>): Promise<T> {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-workspace-"));
  process.env.HOME = path.join(sandbox, "home");
  process.env.PATH = "";
  process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
  await fs.mkdir(process.env.HOME, { recursive: true });
  try {
    return await run();
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
  }
}

type WorkspaceStep = NonNullable<Payload["steps"]>[number];

// write / remove / mkdir edit the fixture; ensure runs the real ensureAgentWorkspace and
// snapshots the tree, the fixture's own legacy state file (upstream writes none), the stored
// setup state (src/agents/workspace-state-store.ts readWorkspaceStateSnapshot(dir).setup: the
// SQLite row, read without the legacy-state gate, timestamps as "__iso__"), the bootstrap
// status and the setup-completed flag.
async function runWorkspaceSteps(repoPath: string, workspaceDir: string, steps: WorkspaceStep[]) {
  const workspace = await importFromRepo(repoPath, "src/agents/workspace.ts");
  const stateStore = await importFromRepo(repoPath, "src/agents/workspace-state-store.ts");
  const snapshots = [];
  for (const step of steps) {
    const target = step.path ? path.join(workspaceDir, step.path) : workspaceDir;
    if (step.op === "write") {
      await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, step.content ?? "", "utf-8");
      continue;
    }
    if (step.op === "remove") {
      await fs.rm(target, { recursive: true, force: true });
      continue;
    }
    if (step.op === "mkdir") {
      await fs.mkdir(target, { recursive: true });
      continue;
    }
    const ensured = await captureUpstreamError(() =>
      workspace.ensureAgentWorkspace({
        dir: workspaceDir,
        ensureBootstrapFiles: true,
        skipOptionalBootstrapFiles: step.skipOptional,
      }),
    );
    let stateRaw: string | null = null;
    try {
      stateRaw = await fs.readFile(path.join(workspaceDir, "openclaw-workspace-state.json"), "utf-8");
    } catch {
      stateRaw = null;
    }
    snapshots.push({
      ...(isRecord(ensured) && typeof ensured.error === "string" ? { error: ensured.error } : {}),
      tree: await snapshotWorkspaceTree(workspaceDir),
      state: normalizeSetupStateTimestamps(stateRaw),
      setupState: await captureUpstreamError(async () =>
        normalizeSetupStateTimestamps(
          JSON.stringify((await stateStore.readWorkspaceStateSnapshot(workspaceDir)).setup),
        ),
      ),
      status: await captureUpstreamError(() => workspace.resolveWorkspaceBootstrapStatus(workspaceDir)),
      setupCompleted: await captureUpstreamError(() =>
        workspace.isWorkspaceSetupCompleted(workspaceDir),
      ),
    });
  }
  return snapshots;
}

async function importFromRepo(repoPath: string, relativePath: string) {
  const fullPath = path.join(repoPath, relativePath);
  return await import(pathToFileURL(fullPath).href);
}

// Load a repo module with extra export lines appended (private functions the oracle needs). The
// patched copy sits beside the original so its relative imports resolve, and is removed again.
async function importPatched(repoPath: string, relativePath: string, extraExports: string) {
  const sourcePath = path.join(repoPath, relativePath);
  const parsed = path.parse(sourcePath);
  const patchedPath = path.join(parsed.dir, `${parsed.name}.oracle-${process.pid}${parsed.ext}`);
  const original = await fs.readFile(sourcePath, "utf-8");
  await fs.writeFile(patchedPath, `${original}\n${extraExports}\n`);
  try {
    return await import(pathToFileURL(patchedPath).href);
  } finally {
    await fs.unlink(patchedPath).catch(() => {});
  }
}

// src/infra/heartbeat-runner.test-utils.ts seedHeartbeatScratchForTest without its scratch write
// (that file imports vitest): the real CronService adds the system-owned heartbeat monitor job of
// one agent, whose declaration key heartbeat:<agentId> joins it to cron_job_scratch.
async function seedHeartbeatMonitorJob(
  repoPath: string,
  storePath: string,
  agentId: string,
): Promise<string> {
  const { CronService } = await importFromRepo(repoPath, "src/cron/service.ts");
  const noop = () => {};
  const cron = new CronService({
    storePath,
    cronEnabled: false,
    defaultAgentId: "main",
    log: { debug: noop, info: noop, warn: noop, error: noop },
    enqueueSystemEvent: () => false,
    requestHeartbeat: noop,
    runIsolatedAgentJob: async () => ({ status: "skipped", error: "oracle" }),
  });
  const added = await cron.add(
    {
      declarationKey: `heartbeat:${agentId}`,
      displayName: `Heartbeat (${agentId})`,
      name: `heartbeat-${agentId}`,
      agentId,
      enabled: true,
      schedule: { kind: "every", everyMs: 30 * 60_000, anchorMs: 0 },
      payload: { kind: "heartbeat" },
      sessionTarget: "main",
      wakeMode: "next-heartbeat",
    },
    { enabledExplicit: true, systemOwned: true },
  );
  return ("job" in added ? added.job : added).id;
}

// One heartbeat scenario's monitor scratch in its own cron store partition: {monitor: false}
// adds no heartbeat job (readHeartbeatMonitorScratch is undefined), {content: null} a job
// without a scratch row, {content: "..."} a job plus writeCronJobScratch, {unset: true} a
// written then unset scratch (a revision-2 tombstone).
async function seedHeartbeatScratchCase(
  repoPath: string,
  cronStorePath: string,
  scratch: Record<string, any> | undefined,
): Promise<void> {
  if (!scratch || scratch.monitor === false) {
    return;
  }
  const store = await importFromRepo(repoPath, "src/cron/scratch-store.ts");
  const jobId = await seedHeartbeatMonitorJob(repoPath, cronStorePath, "main");
  if (scratch.unset) {
    store.writeCronJobScratch({ storePath: cronStorePath, jobId, content: "unset me" });
    store.writeCronJobScratch({ storePath: cronStorePath, jobId, content: null });
  } else if (typeof scratch.content === "string") {
    store.writeCronJobScratch({ storePath: cronStorePath, jobId, content: scratch.content });
  }
}

// extensions/memory-core/src/test-helpers.ts: at v2026.9.6 the SQLite-backed dreaming and
// short-term state store is configured by configureMemoryCoreDreamingStateForTests (moved out
// of dreaming-state.ts), and the raw store readers/writers the pin exposed as
// short-term-promotion.ts `__testing` are `shortTermTestState`. Memory indexing reads flush
// provenance from that store too (memory/test-runtime-mocks.ts), so memory search ops configure
// it as upstream's manager tests do. It must run after OPENCLAW_STATE_DIR is set.
async function loadMemoryCoreTestHelpers(repoPath: string) {
  return await importFromRepo(repoPath, "extensions/memory-core/src/test-helpers.ts");
}

async function configureDreamingStateForOracle(repoPath: string): Promise<void> {
  const helpers = await loadMemoryCoreTestHelpers(repoPath);
  await helpers.configureMemoryCoreDreamingStateForTests();
}

const SHORT_TERM_RECALL_JSON = path.join("memory", ".dreams", "short-term-recall.json");
const SHORT_TERM_PHASE_SIGNAL_JSON = path.join("memory", ".dreams", "phase-signals.json");

type PromotionStateModule = {
  readRecallStore: (workspaceDir: string, nowIso: string) => Promise<Record<string, unknown>>;
  readPhaseSignalStore: (workspaceDir: string, nowIso: string) => Promise<Record<string, unknown>>;
  writeRawRecallStore: (workspaceDir: string, raw: unknown) => Promise<void>;
  writeRawPhaseSignalStore: (workspaceDir: string, raw: unknown) => Promise<void>;
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
  promotionState: PromotionStateModule,
  workspaceDir?: string,
): Promise<void> {
  if (!workspaceDir) {
    return;
  }
  const recallRaw = await readJsonFixture(path.join(workspaceDir, SHORT_TERM_RECALL_JSON));
  if (recallRaw !== undefined) {
    await promotionState.writeRawRecallStore(workspaceDir, recallRaw);
  }
  const phaseRaw = await readJsonFixture(path.join(workspaceDir, SHORT_TERM_PHASE_SIGNAL_JSON));
  if (phaseRaw !== undefined) {
    await promotionState.writeRawPhaseSignalStore(workspaceDir, phaseRaw);
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
  promotionState: PromotionStateModule,
  workspaceDir: string | undefined,
  nowMs: number,
): Promise<void> {
  if (!workspaceDir) {
    return;
  }
  const nowIso = new Date(nowMs).toISOString();
  const [recallStore, phaseStore] = await Promise.all([
    promotionState.readRecallStore(workspaceDir, nowIso),
    promotionState.readPhaseSignalStore(workspaceDir, nowIso),
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

async function writeSessionTranscriptFixtures(repoPath: string, payload: Payload): Promise<void> {
  // v2026.9.6 keeps sessions and transcripts in the per-agent SQLite store (0a8e3604ba2, #98236;
  // the file-era transcript runtime went in 4273ca9dbd9, #113233), so the fixture's JSONL entries
  // are written the way upstream's memory manager tests seed them
  // (manager-index.test-support.ts seedSessionTranscript): upsertSessionEntry for the session,
  // then appendSessionTranscriptMessageByIdentity for each message entry. The session header
  // entry has no counterpart (the store owns session metadata). Must run after
  // OPENCLAW_STATE_DIR is set.
  if (!payload.stateDir || !payload.sessionTranscripts?.length) {
    return;
  }
  const paths = await importFromRepo(repoPath, "src/config/sessions/paths.ts");
  const sessionStore = await importFromRepo(repoPath, "src/plugin-sdk/session-store-runtime.ts");
  const transcriptStore = await importFromRepo(
    repoPath,
    "src/plugin-sdk/session-transcript-runtime.ts",
  );
  const sessionsDir: string = paths.resolveSessionTranscriptsDirForAgent("main");
  const storePath = path.join(sessionsDir, "sessions.json");
  await fs.mkdir(sessionsDir, { recursive: true });
  for (const transcript of payload.sessionTranscripts) {
    const fileName = transcript.fileName?.trim() || "session-oracle.jsonl";
    if (fileName.includes("/") || fileName.includes("\\") || !fileName.endsWith(".jsonl")) {
      throw new Error(`invalid session transcript fixture name: ${fileName}`);
    }
    const sessionId = fileName.slice(0, -".jsonl".length);
    const sessionKey = `agent:main:${sessionId}`;
    await sessionStore.upsertSessionEntry({
      agentId: "main",
      sessionKey,
      storePath,
      entry: { sessionId, updatedAt: Date.now() },
    });
    for (const entry of transcript.entries ?? []) {
      if (!isRecord(entry) || entry.type !== "message" || !isRecord(entry.message)) {
        continue;
      }
      await transcriptStore.appendSessionTranscriptMessageByIdentity({
        agentId: "main",
        sessionId,
        sessionKey,
        storePath,
        message: entry.message,
      });
    }
  }
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

function buildMemorySearchOracleConfig(payload: Payload): Record<string, unknown> {
  // Builtin memory backend with the fake embedding provider and no embedding cache. At
  // v2026.9.6 memory search reads `memory.search` (src/agents/memory-search.ts
  // resolveMemorySearchIndexConfig; `agents.defaults.memorySearch` is a legacy key that
  // doctor migrates), and hybrid weights, MMR, temporal decay, chunking and sync are fixed
  // defaults (#111382), so the payload's vectorWeight/textWeight have no upstream knob.
  // plugins.enabled=false follows the upstream isolateMemoryManagerTestConfig.
  const baseConfig = payload.config ?? {};
  const memory = isRecord(baseConfig.memory) ? baseConfig.memory : {};
  const search = isRecord(memory.search) ? memory.search : {};
  const query = isRecord(search.query) ? search.query : {};
  const agents = isRecord(baseConfig.agents) ? baseConfig.agents : {};
  const defaults = isRecord(agents.defaults) ? agents.defaults : {};
  const plugins = isRecord(baseConfig.plugins) ? baseConfig.plugins : {};
  return {
    ...baseConfig,
    plugins: { ...plugins, enabled: plugins.enabled ?? false },
    memory: {
      ...memory,
      backend: "builtin",
      citations: "on",
      search: {
        ...search,
        provider: "memory-core-fake",
        model: payload.embeddingModel ?? "fake-deterministic",
        query: {
          ...query,
          minScore: payload.minScore ?? query.minScore ?? 0,
          maxResults: payload.maxResults ?? query.maxResults ?? 5,
        },
        cache: { enabled: false },
      },
    },
    agents: {
      ...agents,
      defaults: {
        ...defaults,
        ...(payload.workspaceDir ? { workspace: payload.workspaceDir } : {}),
      },
      list: [{ id: "main", default: true }],
    },
  };
}

function embeddingInputText(input: unknown): string {
  // src/plugins/embedding-provider-types.ts EmbeddingInput: a string or {text, parts?}.
  return typeof input === "string" ? input : isRecord(input) ? String(input.text ?? "") : "";
}

async function registerFakeEmbeddingProvider(
  repoPath: string,
  params: {
    model: string;
    embedQuery?: (text: string, options?: { signal?: AbortSignal }) => Promise<number[]>;
  },
): Promise<void> {
  // v2026.9.6 removed the memory-specific registerMemoryEmbeddingProvider (compat code
  // deprecated-memory-embedding-provider-api, src/plugins/compat/registry-records.ts); memory
  // search resolves adapters from the generic registry (src/plugins/embedding-providers.ts
  // registerEmbeddingProvider, the export upstream tests use through
  // plugin-sdk/plugin-test-runtime). Providers expose embed(input, {inputType}) instead of
  // embedQuery; manager-embedding-ops.ts passes inputType "query" for queries and "document"
  // for indexed chunks, which keeps the query:/document: split of the Python fake provider.
  const registry = await importFromRepo(repoPath, "src/plugins/embedding-providers.ts");
  registry.registerEmbeddingProvider({
    id: "memory-core-fake",
    defaultModel: params.model,
    create: async () => ({
      provider: {
        id: "memory-core-fake",
        model: params.model,
        embed: async (input: unknown, options?: { signal?: AbortSignal; inputType?: string }) => {
          const text = embeddingInputText(input);
          if (options?.inputType === "query") {
            return params.embedQuery
              ? await params.embedQuery(text, options)
              : deterministicEmbedding(`query:${text}`);
          }
          return deterministicEmbedding(`document:${text}`);
        },
        embedBatch: async (inputs: unknown[]) =>
          inputs.map((input) => deterministicEmbedding(`document:${embeddingInputText(input)}`)),
      },
    }),
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

// The session-memory slug oracles run the real generateSlugViaLLM without a model: its
// ../agents/embedded-agent.js import resolves to this stub, which hands the run params
// (the real prompt) to the current case and returns the case's reply as the first payload.
const EMBEDDED_AGENT_STUB_URL = `data:text/javascript,${encodeURIComponent(
  "export async function runEmbeddedAgent(params) { return globalThis.__memoryCoreEmbeddedAgentStub(params); }",
)}`;
let embeddedAgentStubInstalled = false;

function installEmbeddedAgentStub(): void {
  if (embeddedAgentStubInstalled) {
    return;
  }
  const registerHooks = (nodeModule as { registerHooks?: (hooks: unknown) => unknown })
    .registerHooks;
  if (typeof registerHooks !== "function") {
    throw new Error("node:module registerHooks is required (Node >= 22.15)");
  }
  registerHooks({
    resolve(
      specifier: string,
      context: { parentURL?: string },
      nextResolve: (specifier: string, context: unknown) => unknown,
    ) {
      if (
        specifier === "../agents/embedded-agent.js" &&
        context.parentURL?.endsWith("/src/hooks/llm-slug-generator.ts")
      ) {
        return { url: EMBEDDED_AGENT_STUB_URL, format: "module", shortCircuit: true };
      }
      return nextResolve(specifier, context);
    },
  });
  embeddedAgentStubInstalled = true;
}

function setEmbeddedAgentStubReply(reply: unknown, prompts: string[]): void {
  (globalThis as Record<string, unknown>).__memoryCoreEmbeddedAgentStub = async (params: {
    prompt?: string;
  }) => {
    prompts.push(String(params.prompt));
    if (isRecord(reply) && "throw" in reply) {
      throw new Error(String(reply.throw));
    }
    return { payloads: reply === null || reply === undefined ? [] : [reply] };
  };
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
    // v2026.9.6 buildMemoryFlushPlan derives the reserve floor and the soft threshold from the
    // model's context window (6b6f1969c11 #130072); the payload passes it through. Its
    // resolveCronStyleNow ignores the timeFormat config and detects the host's 12/24-hour
    // format (edecdbd05ef #111527, date-time.ts resolveUserTimeFormat(undefined)); the runner
    // reports that detected format as hostTimeFormat so the Python side can pass it on.
    const flushPlan = await importFromRepo(repoPath, "extensions/memory-core/src/flush-plan.ts");
    const dateTime = await importFromRepo(repoPath, "src/agents/date-time.ts");
    const plan = flushPlan.buildMemoryFlushPlan({
      cfg: payload.config ?? {},
      nowMs,
      contextWindowTokens: payload.contextWindowTokens,
    });
    return {
      ok: true,
      operation: payload.operation,
      hostTimeFormat: dateTime.resolveUserTimeFormat(undefined),
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
    // v2026.9.6 shouldRunMemoryFlush takes a precomputed `threshold` instead of the window,
    // reserve floor and soft threshold. Its only caller (agent-runner-memory.ts:1254-1260
    // runMemoryFlushIfNeeded, inline, not exported) derives it as
    // max(0, resolveCompactionThreshold({contextWindowTokens, reserveTokensFloor}) - soft), so
    // the runner applies that expression with the real resolveCompactionThreshold. Without an
    // explicit reserveTokensFloor/softThresholdTokens both come from the real
    // buildMemoryFlushPlan for the window, as runMemoryFlushIfNeeded takes them from its plan.
    // Entries use the tag's fields: fresh totals need totalTokensFresh + totalTokensVersion,
    // the same-cycle guard reads entry.memoryFlush.compactionCount (8ee1d046d33 #115299).
    const memoryFlush = await importFromRepo(repoPath, "src/auto-reply/reply/memory-flush.ts");
    const entry = payload.entry ?? undefined;
    const contextWindowTokens = payload.contextWindowTokens ?? 100_000;
    let reserveTokensFloor = payload.reserveTokensFloor;
    let softThresholdTokens = payload.softThresholdTokens;
    if (reserveTokensFloor === undefined || softThresholdTokens === undefined) {
      const flushPlan = await importFromRepo(repoPath, "extensions/memory-core/src/flush-plan.ts");
      const plan = flushPlan.buildMemoryFlushPlan({
        cfg: payload.config ?? {},
        nowMs,
        contextWindowTokens,
      });
      if (!plan) {
        // memoryFlush.enabled false: runMemoryFlushIfNeeded (agent-runner-memory.ts:1243-1245)
        // returns outcome "skipped" before any threshold or gate.
        return { ok: true, operation: payload.operation, result: { disabled: true } };
      }
      reserveTokensFloor ??= plan.reserveTokensFloor;
      softThresholdTokens ??= plan.softThresholdTokens;
    }
    const threshold = Math.max(
      0,
      memoryFlush.resolveCompactionThreshold({
        contextWindowTokens,
        reserveTokensFloor,
      }) - Math.max(0, Math.floor(softThresholdTokens)),
    );
    return {
      ok: true,
      operation: payload.operation,
      result: {
        shouldRunMemoryFlush: memoryFlush.shouldRunMemoryFlush({
          entry,
          tokenCount: payload.tokenCount,
          threshold,
        }),
        hasAlreadyFlushedForCurrentCompaction: entry
          ? memoryFlush.hasAlreadyFlushedForCurrentCompaction(entry)
          : false,
        threshold,
        reserveTokensFloor,
        softThresholdTokens,
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
          payload.minimumRawWeight === undefined
            ? {}
            : { minimumRawWeight: payload.minimumRawWeight },
        ),
      },
    };
  }

  if (payload.operation === "truncateToolResultsInSession") {
    // v2026.9.6 removed the file-era session runtime (4273ca9dbd9, #113233): SessionManager.create
    // and truncateOversizedToolResultsInSession(sessionFile) are gone, and the embedded runner
    // truncates through truncateOversizedToolResultsInSessionManager on a SessionManager. The op
    // builds an in-memory SessionManager (SessionManager.inMemory, as upstream's tests do) from
    // the fixture's message entries and reads the tool results back from its branch.
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    const sessions = await importFromRepo(repoPath, "src/agents/sessions/index.ts");
    const manager = sessions.SessionManager.inMemory(process.cwd());
    for (const entry of payload.sessionEntries ?? []) {
      if (entry.type === "message" && isRecord(entry.message)) {
        manager.appendMessage(entry.message);
      }
    }
    const result = await truncation.truncateOversizedToolResultsInSessionManager({
      sessionManager: manager,
      contextWindowTokens: payload.contextWindowTokens ?? 100_000,
      maxCharsOverride: payload.maxChars ?? payload.toolResultMaxChars,
      aggregateMaxCharsOverride: payload.aggregateMaxChars,
      protectTrailingToolResults: payload.protectTrailingToolResults,
    });
    const toolResultMessages = manager
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
  }

  if (payload.operation === "toolResultProjection") {
    // Prompt projection of tool results (tool-result-truncation.ts + session-prompt-state.ts): one
    // ToolResultPromptProjectionState shared by a scripted sequence of the exported entry points
    // (projectToolResultBranch itself is private and is reached through them). Every step reports
    // its own result plus a canonical dump of the state.
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    const promptState = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/session-prompt-state.ts",
    );
    const sessions = await importFromRepo(repoPath, "src/agents/sessions/index.ts");
    const state = promptState.createToolResultPromptProjectionState();
    const clean = <T>(value: T): T => JSON.parse(JSON.stringify(value ?? null)) as T;
    const byKey = (a: [string, unknown], b: [string, unknown]) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
    const dumpState = () => ({
      replacements: clean(
        [...state.replacements].map(([key, value]: [string, Record<string, unknown>]) => [
          key,
          { cacheTtl: value.cacheTtl ?? null, content: value.content },
        ]),
      ).toSorted(byKey),
      frozen: [...state.frozen].toSorted(),
      ambiguousBaseKeys: [...state.ambiguousBaseKeys],
      sourceHashByKey: [...state.sourceHashByKey].toSorted(byKey),
      restoredCacheTtl: clean([...state.restoredCacheTtl]).toSorted(byKey),
      lastWrittenSnapshotHash: state.lastWrittenSnapshotHash ?? null,
    });
    const stepResults: Array<Record<string, unknown>> = [];
    for (const step of (payload.steps ?? []) as Array<Record<string, any>>) {
      let result: Record<string, unknown> = {};
      if (step.op === "truncateMessages") {
        const out = truncation.truncateOversizedToolResultsInMessages(
          step.messages ?? [],
          step.contextWindowTokens ?? 100_000,
          step.maxChars,
          step.aggregateMaxChars,
          step.withState === false ? undefined : state,
        );
        result = {
          messages: clean(out.messages),
          truncatedCount: out.truncatedCount,
          aggregateTruncatedCount: out.aggregateTruncatedCount,
          aggregatePressureEngaged: out.aggregatePressureEngaged,
          aggregateBudgetChars: out.aggregateBudgetChars,
        };
      } else if (step.op === "prune") {
        const settings = truncation.resolveCacheTtlPruningSettings(step.config);
        let pruned = false;
        const out = settings
          ? truncation.pruneExpiredCacheTtlToolResults({
              messages: step.messages ?? [],
              settings,
              contextWindowTokens: step.contextWindowTokens ?? 100_000,
              lastCacheTouchAt: step.lastCacheTouchAt ?? null,
              dropThinkingBlocksForEstimate: step.dropThinkingBlocksForEstimate === true,
              now: step.now ?? 0,
              projectionState: state,
              pruneNewRounds: step.pruneNewRounds !== false,
              onPruned: () => {
                pruned = true;
              },
            })
          : step.messages;
        result = {
          settings: settings
            ? {
                ttlMs: settings.ttlMs,
                hardClear: settings.hardClear,
                placeholder: settings.placeholder,
                prunable: Object.fromEntries(
                  (step.probeTools ?? []).map((name: string) => [name, settings.isToolPrunable(name)]),
                ),
              }
            : null,
          messages: clean(out),
          pruned,
        };
      } else if (step.op === "restore") {
        truncation.restoreCacheTtlToolResultProjections(state, step.entries ?? []);
      } else if (step.op === "reconcile") {
        truncation.reconcileToolResultPromptProjectionState(step.messages ?? [], state);
      } else if (step.op === "serialize") {
        const snapshot = promptState.serializeCacheTtlToolResultProjections(state);
        const persisted: unknown[] = [];
        promptState.persistToolResultProjections(state, (customType: string, data: unknown) => {
          persisted.push({ customType, data: clean(data) });
        });
        result = {
          snapshot: clean(snapshot),
          hash: promptState.hashToolResultProjectionSnapshot(snapshot),
          persisted,
        };
      } else if (step.op === "session") {
        const manager = sessions.SessionManager.inMemory(process.cwd());
        const idMap = new Map<string, string>();
        for (const entry of step.sessionEntries ?? []) {
          if (entry.type === "message" && isRecord(entry.message)) {
            idMap.set(entry.id, manager.appendMessage(entry.message));
          } else if (entry.type === "compaction") {
            idMap.set(
              entry.id,
              manager.appendCompaction(
                entry.summary ?? "summary",
                idMap.get(entry.firstKeptEntryId) ?? entry.firstKeptEntryId,
                entry.tokensBefore ?? 1000,
              ),
            );
          }
        }
        const out = await truncation.truncateOversizedToolResultsInSessionManager({
          sessionManager: manager,
          contextWindowTokens: step.contextWindowTokens ?? 100_000,
          maxCharsOverride: step.maxChars,
          aggregateMaxCharsOverride: step.aggregateMaxChars,
          protectTrailingToolResults: step.protectTrailingToolResults,
          projectionState: step.withState === false ? undefined : state,
        });
        const branchMessages = manager
          .getBranch()
          .filter((entry: Record<string, unknown>) => entry.type === "message")
          .map((entry: Record<string, unknown>) => entry.message);
        result = {
          truncated: out.truncated,
          truncatedCount: out.truncatedCount,
          reason: out.reason ?? null,
          branchMessages: clean(branchMessages),
        };
      } else {
        throw new Error(`unknown toolResultProjection step: ${String(step.op)}`);
      }
      stepResults.push({ op: step.op, ...result, state: dumpState() });
    }
    return { ok: true, operation: payload.operation, result: { steps: stepResults } };
  }

  if (payload.operation === "sessionContextWindow") {
    // Reset boundary in the session context window: selectResetKeptEntries (tool-result-pairing.ts)
    // and iterateSessionContextEntries (session.ts) over scripted entry lists. Selected entries
    // are reported as indexes into the input list (both return the input objects themselves).
    const pairing = await importFromRepo(
      repoPath,
      "packages/agent-core/src/harness/session/tool-result-pairing.ts",
    );
    const session = await importFromRepo(
      repoPath,
      "packages/agent-core/src/harness/session/session.ts",
    );
    const cases = (payload.cases ?? []).map((item) => {
      const entries = (item.entries ?? []) as Array<Record<string, unknown>>;
      const indexOf = new Map<unknown, number>(entries.map((entry, index) => [entry, index]));
      return {
        resetKept: pairing
          .selectResetKeptEntries(entries)
          .map((entry: Record<string, unknown>) => indexOf.get(entry)),
        window: [...session.iterateSessionContextEntries(entries)].map(
          (item: { entry: Record<string, unknown>; context: string }) => ({
            index: indexOf.get(item.entry),
            context: item.context,
          }),
        ),
      };
    });
    return { ok: true, operation: payload.operation, result: { cases } };
  }

  if (payload.operation === "cacheTtlEligibility") {
    // Cache-TTL provider eligibility and the session marker: isCacheTtlEligibleProvider and
    // readLastCacheTtlTimestamp (cache-ttl.ts), appendAttemptCacheTtlIfNeeded
    // (run/attempt-thread-helpers.ts) over a real projection state frozen by
    // truncateOversizedToolResultsInMessages. No provider plugin is registered in the runner, so
    // the plugin hook of isCacheTtlEligibleProvider resolves to undefined (core rules only).
    const cacheTtl = await importFromRepo(repoPath, "src/agents/embedded-agent-runner/cache-ttl.ts");
    const helpers = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/run/attempt-thread-helpers.ts",
    );
    const truncation = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/tool-result-truncation.ts",
    );
    const promptState = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/session-prompt-state.ts",
    );
    const clean = <T>(value: T): T => JSON.parse(JSON.stringify(value ?? null)) as T;
    const eligibility = (payload.cases ?? [])
      .filter((item) => item.kind === "eligibility")
      .map((item) =>
        cacheTtl.isCacheTtlEligibleProvider(item.provider, item.modelId, item.modelApi, item.route),
      );
    const reads = (payload.cases ?? [])
      .filter((item) => item.kind === "read")
      .map((item) => {
        const manager =
          item.manager === "noEntries"
            ? {}
            : item.manager === "throws"
              ? {
                  getEntries: () => {
                    throw new Error("boom");
                  },
                }
              : item.manager === "null"
                ? null
                : { getEntries: () => item.entries ?? [] };
        return cacheTtl.readLastCacheTtlTimestamp(manager, item.context);
      });
    const appends = (payload.cases ?? [])
      .filter((item) => item.kind === "append")
      .map((item) => {
        const state = promptState.createToolResultPromptProjectionState();
        if (item.freezeMessages) {
          truncation.truncateOversizedToolResultsInMessages(
            item.freezeMessages,
            item.contextWindowTokens ?? 2_000,
            item.maxChars,
            item.aggregateMaxChars,
            state,
          );
        }
        const entries: unknown[] = [];
        const sessionManager = item.noAppend
          ? {}
          : { appendCustomEntry: (customType: string, data: unknown) => entries.push({ customType, data: clean(data) }) };
        const eligible =
          item.eligible === "always"
            ? () => true
            : item.eligible === "never"
              ? () => false
              : cacheTtl.isCacheTtlEligibleProvider;
        const results = [];
        for (const round of item.rounds ?? [{}]) {
          results.push(
            helpers.appendAttemptCacheTtlIfNeeded({
              sessionManager,
              timedOutDuringCompaction: round.timedOutDuringCompaction === true,
              compactionOccurredThisAttempt: round.compactionOccurredThisAttempt === true,
              config: item.config,
              provider: item.provider,
              modelId: item.modelId,
              modelApi: item.modelApi,
              modelRoute: item.route,
              isCacheTtlEligibleProvider: eligible,
              now: round.now,
              toolResultPromptProjectionState: state,
            }),
          );
        }
        return { results, entries, lastWrittenSnapshotHash: state.lastWrittenSnapshotHash ?? null };
      });
    return { ok: true, operation: payload.operation, result: { eligibility, reads, appends } };
  }

  if (payload.operation === "transcriptRewrite") {
    // rewriteTranscriptEntriesInSessionManager (embedded-agent-runner/transcript-rewrite.ts) on a
    // real in-memory SessionManager. Each case builds a transcript from `entries` (local labels
    // for ids; {"op":"branch","to":label} and {"op":"resetLeaf"} steer the append cursor), then
    // applies `replacements` (entryId is a label or a raw string) and dumps the result, the active
    // branch, every entry, the append cursor and the persisted entry list including leaf controls,
    // with ids normalized (build labels stay; new entries become n1.., leaf controls l1..) and
    // timestamps dropped.
    const rewrite = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/transcript-rewrite.ts",
    );
    const sessions = await importFromRepo(repoPath, "src/agents/sessions/index.ts");
    const clean = <T>(value: T): T => JSON.parse(JSON.stringify(value ?? null)) as T;
    const results: unknown[] = [];
    for (const item of payload.cases ?? []) {
      const manager = sessions.SessionManager.inMemory(process.cwd());
      const ids = new Map<string, string>();
      const real = (label: unknown) =>
        typeof label === "string" && ids.has(label) ? (ids.get(label) as string) : label;
      for (const spec of (item.entries ?? []) as Array<Record<string, any>>) {
        let id: string | undefined;
        if (spec.op === "branch") {
          manager.branch(real(spec.to));
          continue;
        }
        if (spec.op === "resetLeaf") {
          manager.resetLeaf();
          continue;
        }
        if (spec.type === "message") {
          id = manager.appendMessage(structuredClone(spec.message));
        } else if (spec.type === "compaction") {
          id = manager.appendCompaction(
            spec.summary ?? "summary",
            real(spec.firstKeptEntryId),
            spec.tokensBefore ?? 100,
            spec.details,
            spec.fromHook,
            spec.identity,
            spec.tokensAfter,
          );
        } else if (spec.type === "reset") {
          id = manager.appendResetBoundary(spec.reason ?? "new", real(spec.firstKeptEntryId));
        } else if (spec.type === "thinking_level_change") {
          id = await manager.appendThinkingLevelChange(spec.thinkingLevel);
        } else if (spec.type === "model_change") {
          id = await manager.appendModelChange(spec.provider, spec.modelId);
        } else if (spec.type === "custom") {
          id = manager.appendCustomEntry(spec.customType, spec.data);
        } else if (spec.type === "custom_message") {
          id = manager.appendCustomMessageEntry(
            spec.customType,
            spec.content,
            spec.display ?? true,
            spec.details,
          );
        } else if (spec.type === "session_info") {
          id = manager.appendSessionInfo(spec.name ?? "");
        } else if (spec.type === "branch_summary") {
          id = manager.branchWithSummary(
            spec.parentId === null || spec.parentId === undefined ? null : real(spec.parentId),
            spec.summary ?? "branch",
            spec.details,
            spec.fromHook,
          );
        } else if (spec.type === "label") {
          id = manager.appendLabelChange(real(spec.targetId), spec.label);
        } else {
          throw new Error(`unknown transcriptRewrite entry: ${String(spec.type)}`);
        }
        if (spec.id) {
          ids.set(spec.id, id as string);
        }
      }
      const idToLabel = new Map<string, string>([...ids].map(([label, id]) => [id, label]));
      let nextEntry = 0;
      // Rounds apply in sequence; an entryId may also be {branchIndex: n}, the n-th entry of the
      // active branch at that moment (how a later round names entries a rewrite created).
      const rounds = (item.rounds ?? [
        {
          replacements: item.replacements ?? [],
          preserveReplacementCompactionReplay: item.preserveReplacementCompactionReplay,
        },
      ]) as Array<Record<string, any>>;
      const outcomes: Array<Record<string, unknown>> = [];
      for (const round of rounds) {
        try {
          outcomes.push(
            clean(
              await rewrite.rewriteTranscriptEntriesInSessionManager({
                sessionManager: manager,
                replacements: ((round.replacements ?? []) as Array<Record<string, any>>).map((r) => ({
                  entryId:
                    r.entryId !== null && typeof r.entryId === "object"
                      ? manager.getBranch()[r.entryId.branchIndex]?.id
                      : real(r.entryId),
                  message: structuredClone(r.message),
                })),
                preserveReplacementCompactionReplay: round.preserveReplacementCompactionReplay,
              }),
            ),
          );
        } catch (error) {
          outcomes.push({ error: error instanceof Error ? error.message : String(error) });
        }
        for (const entry of manager.getEntries()) {
          if (!idToLabel.has(entry.id)) {
            idToLabel.set(entry.id, `n${(nextEntry += 1)}`);
          }
        }
      }
      let nextLeaf = 0;
      const label = (id: unknown): unknown => {
        if (typeof id !== "string") {
          return id ?? null;
        }
        if (!idToLabel.has(id)) {
          idToLabel.set(id, `n${(nextEntry += 1)}`);
        }
        return idToLabel.get(id);
      };
      const norm = (entry: Record<string, any>) => {
        const out: Record<string, any> = { ...entry };
        delete out.timestamp;
        for (const key of ["id", "parentId", "firstKeptEntryId", "targetId", "appendParentId", "fromId"]) {
          if (key in out) {
            out[key] = key === "fromId" && out[key] === "root" ? "root" : label(out[key]);
          }
        }
        return clean(out);
      };
      // Name every entry in storage order first so labels do not depend on the dump order.
      const entries = manager.getEntries();
      for (const entry of entries) {
        label(entry.id);
      }
      const persisted = manager
        .getPersistedEntries()
        .filter((entry: Record<string, any>) => entry.type !== "session")
        .map((entry: Record<string, any>) => {
          if (entry.type === "leaf") {
            idToLabel.set(entry.id, `l${(nextLeaf += 1)}`);
          }
          return norm(entry);
        });
      results.push({
        outcomes,
        branch: manager.getBranch().map(norm),
        entries: entries.map(norm),
        leafId: label(manager.getLeafId()),
        appendParentId: label(manager.getAppendParentId()),
        appendMode: manager.getAppendMode() ?? null,
        persisted,
      });
    }
    return { ok: true, operation: payload.operation, result: { cases: results } };
  }

  if (payload.operation === "preemptiveCompaction") {
    const preemptive = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/run/preemptive-compaction.ts",
    );
    // The real OpenClaw host (endpoint classes, tool-result redaction) backs the replay pressure.
    await importFromRepo(repoPath, "src/llm/ai-transport-host.ts");
    await importFromRepo(repoPath, "src/agents/ai-transport-runtime-host.ts");
    const replayModel = (model: Record<string, unknown>) => ({
      input: ["text", "image"],
      contextWindow: 200000,
      maxTokens: 4096,
      reasoning: false,
      name: String(model.id),
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      ...model,
    });
    const decide = (item: Record<string, any>) => {
      const replay = item.replay
        ? { ...item.replay, model: replayModel(item.replay.model) }
        : undefined;
      const messages = item.messages ?? [];
      switch (item.fn) {
        case "boundaryEstimate":
          return preemptive.estimateLlmBoundaryTokenPressure({
            messages,
            systemPrompt: item.systemPrompt,
            prompt: item.prompt ?? "",
            replay,
            ...(typeof item.toolSchemaTokens === "number"
              ? { toolSchemaTokens: item.toolSchemaTokens }
              : {}),
          });
        case "renderedBoundary":
          return preemptive.estimateRenderedLlmBoundaryTokenPressure({
            systemPrompt: item.systemPrompt,
            prompt: item.prompt ?? "",
          });
        case "toolSchema":
          return preemptive.estimateToolSchemaTokenPressure(item.tools);
        case "precheckLog":
          return preemptive.formatPrePromptPrecheckLog(item.params);
        case "budgetStatus":
          return preemptive.buildPrePromptContextBudgetStatus(item.params);
        case "overflowText":
          return preemptive.PREEMPTIVE_OVERFLOW_ERROR_TEXT;
        default:
          return preemptive.shouldPreemptivelyCompactBeforePrompt({
            messages,
            unwindowedMessages: item.unwindowedSame ? messages : item.unwindowedMessages,
            systemPrompt: item.systemPrompt,
            prompt: item.prompt ?? "",
            contextTokenBudget: item.contextWindowTokens ?? 100_000,
            reserveTokens: item.reserveTokens ?? 0,
            toolResultMaxChars: item.toolResultMaxChars,
            toolSchemaTokens: item.toolSchemaTokens,
            llmBoundaryTokenPressure: item.llmBoundaryTokenPressure,
            replay,
          });
      }
    };
    if (Array.isArray(payload.cases)) {
      return {
        ok: true,
        operation: payload.operation,
        result: payload.cases.map((item: Record<string, any>) => {
          try {
            return { value: decide(item) ?? null, error: null };
          } catch (err) {
            return {
              value: null,
              error: err instanceof Error ? err.constructor.name : String(err),
            };
          }
        }),
      };
    }
    return {
      ok: true,
      operation: payload.operation,
      result: decide(payload),
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

  if (payload.operation === "historyLimitCases") {
    // getHistoryLimitFromSessionKey with its optional route facts, one entry per case.
    const history = await importFromRepo(repoPath, "src/agents/embedded-agent-runner/history.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map(
        (item) =>
          history.getHistoryLimitFromSessionKey(
            item.sessionKey,
            item.config ?? payload.config,
            item.route,
          ) ?? null,
      ),
    };
  }

  if (payload.operation === "stripInboundMetadata") {
    // stripInboundMetadata and the display wrapper stripInternalMetadataForDisplay over texts.
    const strip = await importFromRepo(repoPath, "src/auto-reply/reply/strip-inbound-meta.ts");
    const display = await importFromRepo(repoPath, "src/auto-reply/reply/display-text-sanitize.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => ({
        stripped: strip.stripInboundMetadata(String(item.text)),
        display: display.stripInternalMetadataForDisplay(String(item.text)),
      })),
    };
  }

  if (payload.operation === "inboundMetadataHelpers") {
    // stripLeadingInboundMetadata and extractInboundSenderLabel over texts.
    const strip = await importFromRepo(repoPath, "src/auto-reply/reply/strip-inbound-meta.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => ({
        leading: strip.stripLeadingInboundMetadata(String(item.text)),
        sender: strip.extractInboundSenderLabel(String(item.text)),
      })),
    };
  }

  if (payload.operation === "compactionReplayOwner") {
    // replaceCompactionReplayOwnerContent and the checkpoint helpers next to it. A case names
    // the new content as {ref: i} (the original block object at index i, matched by identity
    // like upstream's indexOf) or {literal: value} (a fresh value).
    const replay = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/provider-compaction-replay.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => {
        const message = item.message;
        const content = (item.content ?? []).map((spec: Record<string, unknown>) =>
          "ref" in spec ? message.content[spec.ref as number] : spec.literal,
        );
        let replaced: unknown = null;
        let error: string | null = null;
        try {
          replaced = replay.replaceCompactionReplayOwnerContent(message, content);
        } catch (err) {
          error = err instanceof Error ? err.constructor.name : String(err);
        }
        return {
          replaced,
          error,
          isCheckpoint: replay.isCompactionReplayCheckpoint(message.providerReplay),
          stripped: replay.stripCompactionReplayCheckpoint(message),
        };
      }),
    };
  }

  if (payload.operation === "compactionCheckpoint") {
    // The Anthropic/Responses checkpoint resolvers, preserveCompactionReplayWindow,
    // requiresCompactionReplayRefresh and the replay-plan builders. An owner message is reported
    // as {ref: i} (its index in the case's messages, identity like upstream's ===). A case's
    // `windowed` is a list of {ref: i} (the same object) or {copy: i} (a structured clone).
    const replay = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/provider-compaction-replay.ts",
    );
    const anthropic = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/anthropic-compaction-replay.ts",
    );
    const responses = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/openai-responses-compaction-replay.ts",
    );
    const context = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/provider-replay-context.ts",
    );
    const hash = await importFromRepo(repoPath, "packages/ai/src/utils/hash.ts");
    const windowModule = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/openai-responses-compaction-window.ts",
    );
    const pressure = await importFromRepo(repoPath, "src/agents/sessions/context-token-pressure.ts");
    const runtimeIndex = await importFromRepo(repoPath, "src/agents/runtime/index.ts");
    const usageModule = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/openai-responses-context-usage.ts",
    );
    const converter = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/openai-responses-replay-messages-internal.ts",
    );
    const toolText = await importFromRepo(repoPath, "packages/ai/src/providers/tool-result-text.ts");
    const contract = await importFromRepo(
      repoPath,
      "packages/ai/src/providers/anthropic-model-contract.ts",
    );
    const providerTransform = await importFromRepo(
      repoPath,
      "packages/ai/src/provider-transcript-transform.ts",
    );
    const transportTransform = await importFromRepo(
      repoPath,
      "src/agents/transport-message-transform.ts",
    );
    // The real OpenClaw host (endpoint classification, secret sentinels) is what eligibility
    // runs against in production; the library default host classifies every URL as "default".
    await importFromRepo(repoPath, "src/llm/ai-transport-host.ts");
    await importFromRepo(repoPath, "src/agents/ai-transport-runtime-host.ts");
    const toolCallProviders = new Set([
      "openai",
      "opencode",
      "azure-openai-responses",
      "github-copilot",
    ]);
    const estimator = {
      text: (value: string) => pressure.estimateStringTokenPressure(value),
      image: () => runtimeIndex.IMAGE_BLOCK_TOKENS,
      json: (value: unknown) => pressure.estimateJsonPayloadTokenPressure(value),
      toolResult: (value: string) =>
        pressure.estimateStringTokenPressure(
          value,
          pressure.ESTIMATED_CHARS_PER_TOKEN,
          "tool-result",
        ),
    };
    // A sibling copy of provider-compaction-replay.ts that also exports its private estimator;
    // relative imports resolve from that directory. Removed as soon as it is loaded.
    const replaySource = await fs.readFile(
      path.join(repoPath, "packages/ai/src/transports/provider-compaction-replay.ts"),
      "utf8",
    );
    const exposedPath = path.join(
      repoPath,
      "packages/ai/src/transports",
      `provider-compaction-replay.oracle-${process.pid}.ts`,
    );
    await fs.writeFile(exposedPath, `${replaySource}\nexport { estimateResponsesInput };\n`);
    let exposedPressureHelpers: Record<string, any>;
    try {
      exposedPressureHelpers = await import(pathToFileURL(exposedPath).href);
    } finally {
      await fs.rm(exposedPath, { force: true });
    }
    // The same trick for the continuation module's private normalizeAssistantReplayInput.
    const continuationPath = path.join(
      repoPath,
      "packages/ai/src/transports",
      `openai-responses-continuation.oracle-${process.pid}.ts`,
    );
    await fs.writeFile(
      continuationPath,
      `${await fs.readFile(
        path.join(repoPath, "packages/ai/src/transports/openai-responses-continuation.ts"),
        "utf8",
      )}\nexport { normalizeAssistantReplayInput };\n`,
    );
    let exposedContinuation: Record<string, any>;
    try {
      exposedContinuation = await import(pathToFileURL(continuationPath).href);
    } finally {
      await fs.rm(continuationPath, { force: true });
    }
    const replayModel = (model: Record<string, unknown>) => ({
      input: ["text", "image"],
      contextWindow: 200000,
      maxTokens: 4096,
      reasoning: false,
      name: String(model.id),
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      ...model,
    });
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => {
        const messages = item.messages ?? [];
        const ref = (value: unknown) => {
          const index = messages.indexOf(value);
          return index >= 0 ? { ref: index } : value;
        };
        const refOwner = (value: Record<string, unknown> | undefined) =>
          value === undefined ? null : { ...value, owner: ref(value.owner) };
        const identity = item.identity ?? {};
        const options = { authProfileId: identity.authProfileId, sessionId: identity.sessionId };
        try {
          switch (item.fn) {
            case "shortHash":
              return { value: hash.shortHash(item.text), error: null };
            case "replayContext":
              return { value: context.buildProviderReplayContext(item.model, options), error: null };
            case "newestAnthropic":
              return {
                value: refOwner(
                  anthropic.resolveNewestAnthropicCompaction(messages, item.model, options),
                ),
                error: null,
              };
            case "newestResponses":
              return {
                value: refOwner(
                  responses.resolveNewestOpenAIResponsesCompactionReplay(
                    messages,
                    item.model,
                    options,
                  ),
                ),
                error: null,
              };
            case "requiresRefresh":
              return {
                value: replay.requiresCompactionReplayRefresh(messages, item.model, identity),
                error: null,
              };
            case "preserve": {
              const windowed = (item.windowed ?? []).map((spec: Record<string, number>) =>
                "ref" in spec ? messages[spec.ref] : structuredClone(messages[spec.copy]),
              );
              const out = replay.preserveCompactionReplayWindow(
                messages,
                windowed,
                item.model,
                identity,
              );
              return {
                value: out.map((message: unknown) =>
                  windowed.includes(message) ? ref(message) : message,
                ),
                same: out === windowed,
                error: null,
              };
            }
            case "anthropicPlan": {
              const plan = anthropic.buildAnthropicReplayPlan(messages, item.model, {
                ...options,
                enabled: identity.enabled,
              });
              return { value: { ...plan, messages: plan.messages.map(ref) }, error: null };
            }
            case "responsesPlan": {
              const plan = responses.buildOpenAIResponsesCompactionReplayPlan(
                messages,
                item.model,
                { ...options, ...(item.mode ? { mode: item.mode } : {}) },
              );
              return { value: { ...plan, messages: plan.messages.map(ref) }, error: null };
            }
            case "window":
              return {
                value:
                  windowModule.readOpenAIResponsesCompactionWindow(item.replay, item.model) ?? null,
                error: null,
              };
            case "isOutput":
              return {
                value: windowModule.isOpenAIResponsesCompactionOutput(item.value, item.model),
                error: null,
              };
            case "eligibility": {
              const saved = process.env.ANTHROPIC_BASE_URL;
              if (item.env && "ANTHROPIC_BASE_URL" in item.env) {
                process.env.ANTHROPIC_BASE_URL = item.env.ANTHROPIC_BASE_URL;
              } else {
                delete process.env.ANTHROPIC_BASE_URL;
              }
              try {
                return {
                  value: replay.resolveCompactionReplayEligibility(item.model, {
                    extraParams: item.extraParams,
                    apiKey: item.apiKey,
                  }),
                  error: null,
                };
              } finally {
                if (saved === undefined) {
                  delete process.env.ANTHROPIC_BASE_URL;
                } else {
                  process.env.ANTHROPIC_BASE_URL = saved;
                }
              }
            }
            case "pressure": {
              const out = replay.resolveCompactionReplayPressure(
                messages,
                replayModel(item.model),
                identity,
                estimator,
                item.systemPrompt,
              );
              return {
                value: out === undefined ? null : { ...out, messages: out.messages.map(ref) },
                error: null,
              };
            }
            case "estimateInput": {
              // estimateResponsesInput is private upstream; its source is the only way in.
              // exposedPressureHelpers (below) loaded it through a sibling copy of the module.
              const full = { ...estimator };
              const noTool = { text: full.text, image: full.image, json: full.json };
              return {
                value: exposedPressureHelpers.estimateResponsesInput(
                  item.items,
                  item.withToolResult === false ? noTool : full,
                ),
                error: null,
              };
            }
            case "projections": {
              // The converter's wire input per projection and system-prompt flag, over the
              // provider-role messages; the Python port takes it as a hook result.
              const providerMessages = messages.filter((message: Record<string, unknown>) =>
                ["user", "assistant", "toolResult"].includes(message.role as string),
              );
              const table: Record<string, unknown> = {};
              for (const projection of ["transport", "provider"]) {
                for (const includeSystemPrompt of [false, true]) {
                  const convert =
                    projection === "transport"
                      ? converter.convertResponsesMessages
                      : converter.convertProviderResponsesMessages;
                  table[`${projection}:${includeSystemPrompt}`] = convert(
                    replayModel(item.model),
                    { messages: providerMessages, systemPrompt: item.systemPrompt },
                    toolCallProviders,
                    { ...identity, includeSystemPrompt },
                  );
                }
              }
              return { value: table, error: null };
            }
            case "convert": {
              // The Responses converter itself: the wire input of one projection over the case's
              // messages as given (every role), with the identity's session and auth profile.
              const convert =
                item.projection === "provider"
                  ? converter.convertProviderResponsesMessages
                  : converter.convertResponsesMessages;
              return {
                value: convert(
                  replayModel(item.model),
                  { messages: structuredClone(messages), systemPrompt: item.systemPrompt },
                  toolCallProviders,
                  {
                    ...identity,
                    ...(item.options ?? {}),
                    ...(item.includeSystemPrompt === undefined
                      ? {}
                      : { includeSystemPrompt: item.includeSystemPrompt }),
                  },
                ),
                error: null,
              };
            }
            case "toolResultText": {
              return {
                value: {
                  text: toolText.extractToolResultText(item.blocks, item.options),
                  placeholder: toolText.describeToolResultMediaPlaceholder(item.blocks) ?? null,
                  hasImage: item.blocks.map((block: unknown) =>
                    toolText.isImageWithMediaPayload(block),
                  ),
                  blocks: item.blocks.map(
                    (block: unknown) => toolText.extractToolResultBlockText(block) ?? null,
                  ),
                },
                error: null,
              };
            }
            case "boundReplayMode": {
              return {
                value: contract.resolveModelBoundThinkingReplayMode({
                  source: item.source,
                  target: item.target,
                }),
                error: null,
              };
            }
            case "transform": {
              const model = replayModel(item.model);
              const norm = (id: string) => `n:${id}`;
              const out =
                item.style === "provider"
                  ? providerTransform.transformProviderMessages(
                      structuredClone(messages),
                      model,
                      item.normalize ? norm : undefined,
                    )
                  : transportTransform.transformTransportMessages(
                      structuredClone(messages),
                      model,
                      item.normalize ? norm : undefined,
                      item.options,
                    );
              return { value: out, error: null };
            }
            case "recordUsage": {
              // Bind measured usage to the replay prefix exactly as the transport does after a
              // response: request.input is the wire input before the target assistant message
              // and the target's own replay output follows it.
              const target = messages[item.target];
              const providerBefore = messages
                .slice(0, item.target)
                .filter((message: Record<string, unknown>) =>
                  ["user", "assistant", "toolResult"].includes(message.role as string),
                );
              const convert =
                item.projection === "transport"
                  ? converter.convertResponsesMessages
                  : converter.convertProviderResponsesMessages;
              const model = replayModel(item.model);
              const input = convert(
                model,
                { messages: providerBefore, systemPrompt: item.systemPrompt },
                toolCallProviders,
                { ...identity, includeSystemPrompt: item.includeSystemPrompt === true },
              );
              target.usage = {
                ...target.usage,
                contextUsage: {
                  state: "available",
                  promptTokens: item.promptTokens,
                  totalTokens: item.totalTokens,
                },
              };
              usageModule.recordResponsesContextUsage(
                target,
                model,
                identity,
                { input: [...(item.requestPrefix ?? []), ...input] },
                item.output ?? [],
                item.projection,
              );
              return { value: messages, error: null };
            }
            case "normalizeReplayInput":
              return {
                value: exposedContinuation.normalizeAssistantReplayInput(
                  structuredClone(item.items),
                  item.fromResponse === true,
                ),
                error: null,
              };
            case "prefixFingerprint":
              return {
                value: exposedContinuation.responsesContinuationPrefixFingerprint(
                  structuredClone(item.input),
                  item.output === undefined ? undefined : structuredClone(item.output),
                ),
                error: null,
              };
            case "recordContextUsage": {
              // recordResponsesContextUsage over the case's own request and output; the result is
              // the target's saved input-replay state (JSON, so undefined fields are absent).
              const target = messages[item.target];
              usageModule.recordResponsesContextUsage(
                target,
                replayModel(item.model),
                item.identity,
                structuredClone(item.request),
                structuredClone(item.output),
                item.projection,
              );
              return { value: target.openclawResponsesInputReplay ?? null, error: null };
            }
            case "anthropicCapture": {
              const output: Record<string, unknown> = structuredClone(item.output ?? {});
              const capture = anthropic.createCompactionCapture(output, item.model, options);
              const results = (item.events ?? []).map((event: Record<string, unknown>) =>
                event.op === "begin"
                  ? capture.begin(
                      event.index as number,
                      event.block as never,
                      event.replayIndex as number,
                    )
                  : event.op === "delta"
                    ? capture.delta(event.index as number, event.delta as never)
                    : capture.complete(event.index as number),
              );
              return {
                value: { results, providerReplay: output.providerReplay ?? null },
                error: null,
              };
            }
            case "anthropicSuppress": {
              const output: Record<string, unknown> = structuredClone(item.output ?? {});
              anthropic.suppressAnthropicCompaction(output, item.model, options);
              return { value: { providerReplay: output.providerReplay ?? null }, error: null };
            }
            case "responsesCapture": {
              const output: Record<string, unknown> = structuredClone(item.output ?? {});
              responses.captureOpenAIResponsesCompaction(
                output,
                item.item,
                item.boundary,
                item.model,
                item.metadata ?? undefined,
                item.compactedOutput ?? undefined,
              );
              return { value: { providerReplay: output.providerReplay ?? null }, error: null };
            }
            case "responsesSuppress": {
              const output: Record<string, unknown> = structuredClone(item.output ?? {});
              const rejected: unknown[] = [];
              responses.suppressOpenAIResponsesCompaction(
                output,
                item.model,
                {
                  ...options,
                  ...(item.withCallback
                    ? { onCompactionRejected: (value: unknown) => rejected.push(value) }
                    : {}),
                },
                item.rejected ?? undefined,
              );
              return {
                value: { providerReplay: output.providerReplay ?? null, rejected },
                error: null,
              };
            }
            case "reasoningMetadata":
              return {
                value: responses.buildOpenAIResponsesReasoningReplayMetadata(item.model, options),
                error: null,
              };
            case "replayContextShape":
              return { value: responses.isOpenAIResponsesReplayContext(item.value), error: null };
            case "tracker": {
              const output: Record<string, unknown> = structuredClone(item.output ?? {});
              const tracker = responses.createCompactionTracker(
                output,
                item.model,
                item.metadata ? { reasoningReplayMetadata: item.metadata } : undefined,
              );
              const snapshots = (item.steps ?? []).map((step: Record<string, unknown>) => {
                if (step.op === "added") {
                  tracker.added(step.item as never, step.replayIndex as number);
                } else {
                  tracker.completed(step.item as never, step.fallback as number);
                }
                return structuredClone(output.providerReplay ?? null);
              });
              return { value: { snapshots }, error: null };
            }
            default:
              throw new Error(`unknown fn ${item.fn}`);
          }
        } catch (err) {
          return { value: null, error: err instanceof Error ? err.constructor.name : String(err) };
        }
      }),
    };
  }

  if (payload.operation === "inlineImage") {
    // The inline image data-URL sanitiser, canonical base64, the signature sniffer and the
    // Responses image payload sanitiser (undefined is reported as null).
    const inline = await importFromRepo(
      repoPath,
      "packages/media-core/src/inline-image-data-url.ts",
    );
    const base64 = await importFromRepo(repoPath, "packages/media-core/src/base64.ts");
    const stable = await importFromRepo(repoPath, "packages/normalization-core/src/stable-stringify.ts");
    const sanitizer = await importFromRepo(
      repoPath,
      "packages/ai/src/transports/responses-image-payload-sanitizer.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => {
        try {
          switch (item.fn) {
            case "url":
              return { value: inline.sanitizeInlineImageDataUrl(item.text) ?? null, error: null };
            case "storage":
              return {
                value: inline.sanitizeInlineImageDataUrlForStorage(item.text) ?? null,
                error: null,
              };
            case "base64":
              return {
                value:
                  inline.sanitizeInlineImageBase64({
                    mimeType: item.mimeType,
                    base64: item.text,
                  }) ?? null,
                error: null,
              };
            case "canonical":
              return { value: base64.canonicalizeBase64(item.text) ?? null, error: null };
            case "sniff":
              return {
                value: inline.sniffInlineImageMime(Buffer.from(item.hex, "hex")) ?? null,
                error: null,
              };
            case "stable":
              return { value: stable.stableStringify(item.value), error: null };
            case "hostname": {
              // new URL(text).hostname: the endpoint classifiers' host extraction.
              try {
                return { value: new URL(item.text).hostname, error: null };
              } catch {
                return { value: null, error: null };
              }
            }
            case "payload": {
              const out = sanitizer.sanitizeResponsesImagePayload(item.params);
              return { value: out, same: out === item.params, error: null };
            }
            default:
              throw new Error(`unknown fn ${item.fn}`);
          }
        } catch (err) {
          return { value: null, error: err instanceof Error ? err.constructor.name : String(err) };
        }
      }),
    };
  }

  if (payload.operation === "replayContentCases") {
    // normalizeAssistantReplayContent / sanitizeToolCallInputs over many independent
    // message lists; a throw is reported by the error class name.
    const replayHistory = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/replay-history.ts",
    );
    const repair = await importFromRepo(repoPath, "src/agents/session-transcript-repair.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => {
        const messages = item.messages ?? [];
        try {
          const out =
            item.fn === "sanitizeToolCalls"
              ? repair.sanitizeToolCallInputs(messages, {})
              : replayHistory.normalizeAssistantReplayContent(messages);
          return { messages: out, unchanged: out === messages, error: null };
        } catch (err) {
          return {
            messages: null,
            unchanged: false,
            error: err instanceof Error ? err.constructor.name : String(err),
          };
        }
      }),
    };
  }

  if (payload.operation === "normalizeUsage") {
    // normalizeUsage and hasNonzeroUsage over raw provider usage values, undefined as null.
    const usage = await importFromRepo(repoPath, "src/agents/usage.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) => {
        const normalized = usage.normalizeUsage(item.usage);
        return {
          normalized: normalized ?? null,
          nonzero: usage.hasNonzeroUsage(normalized),
        };
      }),
    };
  }

  if (payload.operation === "repairToolUseResultPairing") {
    const repair = await importFromRepo(repoPath, "src/agents/session-transcript-repair.ts");
    const result = repair.repairToolUseResultPairing(payload.messages ?? [], {
      ...(payload.erroredAssistantResultPolicy
        ? { erroredAssistantResultPolicy: payload.erroredAssistantResultPolicy }
        : {}),
      ...(typeof payload.text === "string" ? { missingToolResultText: payload.text } : {}),
      ...(payload.preserveUnframedToolResults === true
        ? { preserveUnframedToolResults: true }
        : {}),
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        messages: result.messages.map(normalizeRepairMessage),
        added: result.added.map(normalizeRepairMessage),
        discarded: result.discarded.map(normalizeRepairMessage),
        droppedDuplicateCount: result.droppedDuplicateCount,
        droppedOrphanCount: result.droppedOrphanCount,
        moved: result.moved,
      },
    };
  }

  if (payload.operation === "sanitizeToolCallInputs") {
    const repair = await importFromRepo(repoPath, "src/agents/session-transcript-repair.ts");
    const messages = payload.messages ?? [];
    const result = repair.sanitizeToolCallInputs(messages, {
      ...(Array.isArray(payload.allowedToolNames)
        ? { allowedToolNames: payload.allowedToolNames }
        : {}),
    });
    return {
      ok: true,
      operation: payload.operation,
      result: { messages: result, unchanged: result === messages },
    };
  }

  if (payload.operation === "runtimeContextPrompt") {
    const runtimeContextPrompt = await importFromRepo(
      repoPath,
      "src/agents/embedded-agent-runner/run/runtime-context-prompt.ts",
    );
    const runtimeContext = "secret runtime context";
    const fragments = payload.fragments;
    const modelMessages = payload.modelMessages ?? [];
    return {
      ok: true,
      operation: payload.operation,
      result: {
        parts: runtimeContextPrompt.resolveRuntimeContextPromptParts({
          effectivePrompt: payload.prompt ?? "",
          transcriptPrompt: payload.text,
          fragments,
          allowRuntimeOnly: payload.allowRuntimeOnly,
        }),
        currentInboundPrompt: runtimeContextPrompt.buildCurrentInboundPrompt({
          context: payload.entry,
          prompt: "What do you mean hidden?",
          preferResumableText: payload.preferResumableText,
        }),
        appendedContext: runtimeContextPrompt.appendCurrentInboundContext(
          payload.entry,
          fragments ?? [],
        ),
        prependedMessages: runtimeContextPrompt.prependRuntimeContextForModel(
          modelMessages,
          runtimeContext,
        ),
        customMessage: normalizeTimestampedMessage(
          runtimeContextPrompt.buildRuntimeContextCustomMessage(runtimeContext, fragments),
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
      // v2026.9.6 rejects the pin fixture's "agent:main" ("Malformed agent session key"); the
      // main-session key keeps the same agent.
      sessionKey: "agent:main:main",
      messages: payload.messages ?? [],
      modelId: "gpt-test",
    });
    await lifecycle.finalizeHarnessContextEngineTurn({
      contextEngine,
      promptError: false,
      aborted: false,
      yieldAborted: false,
      sessionIdUsed: "session-1",
      sessionKey: "agent:main:main",
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

  if (payload.operation === "contextOverflowTables") {
    // The overflow wording tables behind isLikelyContextOverflowError: every scope of
    // matchesContextOverflowMessage plus the failover/context-overflow helpers and the rate-limit
    // and billing tables they consult, over a corpus of provider messages in one call.
    const overflow = await importFromRepo(repoPath, "packages/ai/src/utils/overflow.ts");
    const failover = await importFromRepo(repoPath, "src/agents/failover/context-overflow.ts");
    const tables = await importFromRepo(repoPath, "src/agents/failover/context-overflow-tables.ts");
    const patterns = await importFromRepo(repoPath, "src/agents/failover/message-patterns.ts");
    const scopes = [
      "assistant-error",
      "failover-explicit",
      "provider-fallback",
      "failover-hint",
      "context-window-too-small",
      "tpm-rate-limit-hint",
      "rate-limit-hint",
    ];
    return {
      ok: true,
      operation: payload.operation,
      result: {
        cases: (payload.texts ?? []).map((text) => {
          const value = text ?? "";
          return {
            scopes: Object.fromEntries(
              scopes.map((scope) => [scope, overflow.matchesContextOverflowMessage(value, scope)]),
            ),
            looksLikeCandidate: tables.looksLikeProviderContextOverflowCandidate(value),
            fromTables: tables.isContextOverflowErrorFromTables(value),
            isContextOverflowError: failover.isContextOverflowError(value),
            isLikelyContextOverflowError: failover.isLikelyContextOverflowError(value),
            isRateLimit: patterns.isRateLimitErrorMessage(value),
            isBilling: patterns.isBillingErrorMessage(value),
            requestSizeCeiling: patterns.isProviderRequestSizeCeilingError(value),
          };
        }),
      },
    };
  }

  if (payload.operation === "assistantOverflow") {
    // Assistant-error overflow path: isContextOverflow (packages/ai overflow.ts) over scripted
    // assistant messages, and the provider-plugin hook of isContextOverflowError /
    // classifyProviderPluginError with plugins built from a declarative spec: `matches` (regex
    // sources tested on the error message; `matchReturn` "undefined" returns undefined),
    // `reason` (classifyFailoverReason result) and a call log of the contexts handed over.
    const overflow = await importFromRepo(repoPath, "packages/ai/src/utils/overflow.ts");
    const failover = await importFromRepo(repoPath, "src/agents/failover/context-overflow.ts");
    const patterns = await importFromRepo(repoPath, "src/agents/failover/provider-patterns.ts");
    const messages = (payload.cases ?? [])
      .filter((item) => item.message !== undefined)
      .map((item) => ({
        isContextOverflow:
          item.contextWindow === undefined
            ? overflow.isContextOverflow(item.message)
            : overflow.isContextOverflow(item.message, item.contextWindow),
      }));
    const plugins = (payload.cases ?? [])
      .filter((item) => item.text !== undefined)
      .map((item) => {
        const spec = item.plugin as Record<string, any> | undefined;
        const calls: unknown[] = [];
        const plugin = spec
          ? {
              id: spec.id,
              matchesContextOverflowError: spec.matches
                ? (ctx: Record<string, unknown>) => {
                    calls.push({ hook: "matches", ctx });
                    if (spec.matchReturn === "undefined") {
                      return undefined;
                    }
                    return (spec.matches as string[]).some((source) =>
                      new RegExp(source, "i").test(String(ctx.errorMessage)),
                    );
                  }
                : undefined,
              classifyFailoverReason:
                spec.reason !== undefined
                  ? (ctx: Record<string, unknown>) => {
                      calls.push({ hook: "classify", ctx });
                      return spec.reason;
                    }
                  : undefined,
            }
          : undefined;
        const providerPlugin = item.mode === "null" ? null : item.mode === "unset" ? undefined : plugin;
        return {
          isContextOverflowError: failover.isContextOverflowError(item.text, { providerPlugin }),
          classify: patterns.classifyProviderPluginError({
            errorMessage: item.text,
            ...(item.context ?? {}),
            providerPlugin,
          }),
          calls,
        };
      });
    return { ok: true, operation: payload.operation, result: { messages, plugins } };
  }

  if (payload.operation === "memoryGet") {
    // extensions/memory-core/src/tools.ts createMemoryGetTool (builtin backend)
    // through the real tool-definition adapter, so param errors come back as the
    // ToolInputError payload the model sees (agent-tool-definition-adapter.ts
    // buildToolExecutionErrorResult) and read failures as the tool's own
    // resolveMemoryReadFailureResult payload. `rawParams` passes the model's
    // arguments as given; otherwise path/from/lines build them (omitted when unset).
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-memory-get-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    try {
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
      const tools = await importFromRepo(repoPath, "extensions/memory-core/src/tools.ts");
      const adapter = await importFromRepo(repoPath, "src/agents/agent-tool-definition-adapter.ts");
      const tool = tools.createMemoryGetTool({ config: cfg, agentId: "main" });
      if (!tool) {
        throw new Error("memory_get tool missing");
      }
      const rawParams =
        payload.rawParams !== undefined
          ? payload.rawParams
          : {
              path: payload.path ?? "",
              ...(payload.from !== undefined ? { from: payload.from } : {}),
              ...(payload.lines !== undefined ? { lines: payload.lines } : {}),
            };
      const [definition] = adapter.toToolDefinitions([tool]);
      const wrapped = await definition.execute(
        "memory_get_oracle",
        rawParams,
        undefined,
        undefined,
        undefined,
      );
      return {
        ok: true,
        operation: payload.operation,
        result: wrapped.details,
      };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "markdownChunks") {
    // chunkMarkdown (packages/memory-host-sdk/src/host/markdown-chunks.ts) on each case:
    // line spans, entry spans and text, without the embedding input and hash.
    const chunks = await importFromRepo(
      repoPath,
      "packages/memory-host-sdk/src/host/markdown-chunks.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: (
        payload.cases as Array<{
          content: string;
          tokens: number;
          overlap: number;
          perEntry?: boolean;
        }>
      ).map((entry) =>
        chunks
          .chunkMarkdown(entry.content, {
            tokens: entry.tokens,
            overlap: entry.overlap,
            perEntry: entry.perEntry,
          })
          .map(
            (chunk: {
              startLine: number;
              endLine: number;
              entryStartLine?: number;
              entryEndLine?: number;
              text: string;
            }) => ({
              startLine: chunk.startLine,
              endLine: chunk.endLine,
              entryStartLine: chunk.entryStartLine ?? null,
              entryEndLine: chunk.entryEndLine ?? null,
              text: chunk.text,
            }),
          ),
      ),
    };
  }

  if (payload.operation === "memoryPromptSection") {
    // `## Memory Recall` of the real prompt-section builder (memory-tool-contract.ts
    // buildMemoryPromptSection): one result per scenario of available tools and citations mode.
    const contract = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory-tool-contract.ts",
    );
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.scenarios as Array<{ availableTools: string[]; citationsMode: string }>).map(
        (scenario) =>
          contract.buildMemoryPromptSection({
            availableTools: new Set(scenario.availableTools),
            citationsMode: scenario.citationsMode,
          }),
      ),
    };
  }

  if (payload.operation === "memoryToolDefinitions") {
    // The model-facing name, description and parameter schema of the real
    // memory_search and memory_get tools (tools.ts createMemorySearchTool /
    // createMemoryGetTool, tools.shared.ts MemorySearchSchema / MemoryGetSchema),
    // as JSON (TypeBox symbol keys dropped).
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-memory-tools-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    try {
      const tools = await importFromRepo(repoPath, "extensions/memory-core/src/tools.ts");
      const cfg = { agents: { defaults: { workspace: path.join(sandbox, "workspace") } } };
      const describe = (tool: { name: string; description: string; parameters: unknown } | null) => {
        if (!tool) {
          throw new Error("memory tool missing");
        }
        return {
          name: tool.name,
          description: tool.description,
          parameters: JSON.parse(JSON.stringify(tool.parameters)),
        };
      };
      return {
        ok: true,
        operation: payload.operation,
        result: [
          describe(tools.createMemorySearchTool({ config: cfg, agentId: "main" })),
          describe(tools.createMemoryGetTool({ config: cfg, agentId: "main" })),
        ],
      };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "listMemoryFiles") {
    // packages/memory-host-sdk/src/host/internal.ts listMemoryFiles on a fixture
    // workspace written by the Python side (no extraPaths, multimodal disabled),
    // reported as workspace-relative paths the way buildFileEntry derives them.
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    const internal = await importFromRepo(repoPath, "packages/memory-host-sdk/src/host/internal.ts");
    const files: string[] = await internal.listMemoryFiles(workspaceDir);
    return {
      ok: true,
      operation: payload.operation,
      result: files.map((file) => path.relative(workspaceDir, file).replace(/\\/g, "/")),
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
    await writeSessionTranscriptFixtures(repoPath, { ...payload, stateDir });
    await registerWikiCorpusFixture(repoPath, payload);
    await registerFakeEmbeddingProvider(repoPath, {
      model: payload.embeddingModel ?? "fake-deterministic",
    });
    await configureDreamingStateForOracle(repoPath);

    const tools = await importFromRepo(repoPath, "extensions/memory-core/src/tools.ts");
    const memoryIndex = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory/index.ts",
    );
    const cfg = buildMemorySearchOracleConfig(payload);
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
      if (payload.rawParams !== undefined) {
        // Raw model arguments go through the real tool-definition adapter, so a
        // thrown ToolInputError comes back serialized exactly as the model sees
        // it (agent-tool-definition-adapter.ts buildToolExecutionErrorResult).
        const adapter = await importFromRepo(repoPath, "src/agents/agent-tool-definition-adapter.ts");
        const [definition] = adapter.toToolDefinitions([tool]);
        const wrapped = await definition.execute(
          "memory_search_oracle",
          payload.rawParams,
          undefined,
          undefined,
          undefined,
        );
        return {
          ok: true,
          operation: payload.operation,
          result: wrapped.details,
        };
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

  if (payload.operation === "memoryIndexIdentity") {
    // extensions/memory-core/src/memory/manager-reindex-state.ts pure exports.
    const reindexState = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory/manager-reindex-state.ts",
    );
    const identity = payload.identity ?? {};
    return {
      ok: true,
      operation: payload.operation,
      result: {
        states: (identity.states ?? []).map((params) =>
          reindexState.resolveMemoryIndexIdentityState(params),
        ),
        providerIdentities: (identity.providerIdentities ?? []).map((params) =>
          reindexState.resolveMemoryIndexProviderIdentities(params),
        ),
        sources: (identity.sources ?? []).map((sources) =>
          reindexState.resolveConfiguredSourcesForMeta(sources),
        ),
        scopes: (identity.scopes ?? []).map((multimodal) =>
          reindexState.resolveConfiguredScopeHash({
            workspaceDir: payload.workspaceDir ?? os.tmpdir(),
            extraPaths: [],
            multimodal,
          }),
        ),
      },
    };
  }

  if (payload.operation === "memorySearchUnavailableResult") {
    // extensions/memory-core/src/tools.shared.ts buildMemorySearchUnavailableResult;
    // a null error stands for undefined.
    const shared = await importFromRepo(repoPath, "extensions/memory-core/src/tools.shared.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.unavailableCases ?? []).map((entry) =>
        shared.buildMemorySearchUnavailableResult(
          entry.error ?? undefined,
          entry.warning !== undefined || entry.action !== undefined
            ? { warning: entry.warning, action: entry.action }
            : undefined,
        ),
      ),
    };
  }

  if (payload.operation === "memorySearchToolSequence") {
    // One process and one memory_search tool, so tools.ts's process-wide
    // cooldown Map carries across steps. Each step scripts the fake provider's
    // embedQuery ("ok", "throw:<message>", "hang" until aborted) and the wiki
    // supplement ("ok", "throw:<message>"). Date.now is offset by `advanceMs`
    // to reach cooldown expiry, and a step's `deadlineFireMs` makes the search
    // deadline timer (DEFAULT_MEMORY_SEARCH_TIMEOUT_MS, read from the real
    // memory/search-deadline.ts: 30 s at v2026.9.6, 15 s at 4c428153) fire after
    // that many real ms (the deadline code and its message are untouched).
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    process.env.OPENCLAW_STATE_DIR = payload.stateDir ?? path.join(payload.workspaceDir, ".openclaw-state");
    const searchDeadline = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory/search-deadline.ts",
    );
    const deadlineTimeoutMs: number = searchDeadline.DEFAULT_MEMORY_SEARCH_TIMEOUT_MS;
    let clockOffsetMs = 0;
    const realNow = Date.now.bind(Date);
    Date.now = () => realNow() + clockOffsetMs;
    const realSetTimeout = globalThis.setTimeout;
    let deadlineFireMs: number | undefined;
    globalThis.setTimeout = ((handler: (...args: unknown[]) => void, timeout?: number, ...args: unknown[]) =>
      realSetTimeout(
        handler,
        timeout === deadlineTimeoutMs && deadlineFireMs !== undefined ? deadlineFireMs : timeout,
        ...args,
      )) as typeof setTimeout;

    let embedQueryBehavior = "ok";
    let supplementBehavior = "ok";
    let embedQueryCalls = 0;
    const memoryState = await importFromRepo(repoPath, "src/plugins/memory-state.ts");
    memoryState.registerMemoryCorpusSupplement("memory-wiki", {
      search: async () => {
        if (supplementBehavior.startsWith("throw:")) {
          throw new Error(supplementBehavior.slice("throw:".length));
        }
        return payload.wikiResults ?? [];
      },
      get: async () => null,
    });
    await registerFakeEmbeddingProvider(repoPath, {
      model: "fake-deterministic",
      embedQuery: async (text: string, options?: { signal?: AbortSignal }) => {
        embedQueryCalls += 1;
        if (embedQueryBehavior.startsWith("throw:")) {
          throw new Error(embedQueryBehavior.slice("throw:".length));
        }
        if (embedQueryBehavior === "hang") {
          return await new Promise<number[]>((_, reject) => {
            options?.signal?.addEventListener(
              "abort",
              () => reject(options.signal?.reason ?? new Error("aborted")),
              { once: true },
            );
          });
        }
        return deterministicEmbedding(`query:${text}`);
      },
    });
    await configureDreamingStateForOracle(repoPath);
    const tools = await importFromRepo(repoPath, "extensions/memory-core/src/tools.ts");
    const memoryIndex = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/memory/index.ts",
    );
    try {
      const tool = tools.createMemorySearchTool({
        config: buildMemorySearchOracleConfig(payload),
        agentId: "main",
        agentSessionKey: "agent:main:oracle",
      });
      if (!tool) {
        throw new Error("memory_search tool missing");
      }
      const steps: unknown[] = [];
      for (const step of payload.searchSteps ?? []) {
        clockOffsetMs += step.advanceMs ?? 0;
        embedQueryBehavior = step.embedQuery ?? "ok";
        supplementBehavior = step.supplement ?? "ok";
        deadlineFireMs = step.deadlineFireMs;
        const callsBefore = embedQueryCalls;
        const result = await tool.execute("memory_search_oracle", step.rawParams);
        steps.push({ result: result.details, embedQueryCalls: embedQueryCalls - callsBefore });
      }
      return { ok: true, operation: payload.operation, result: steps };
    } finally {
      await memoryIndex.closeAllMemorySearchManagers();
    }
  }

  if (payload.operation === "bootstrapContextFiles") {
    return withIsolatedRuntimeState("openclaw-oracle-bootstrap-context-", async () => {
      // src/agents/embedded-agent-helpers/bootstrap.ts buildBootstrapContextFiles plus the
      // src/agents/bootstrap-budget.ts report built from the same files. At v2026.9.6
      // buildBootstrapPromptWarning lives in src/agents/bootstrap-budget-warning.ts, the default
      // caps are private (read through resolveBootstrapMaxChars/resolveBootstrapTotalMaxChars
      // with no config, which return them) and appendBootstrapPromptWarning is gone (0b450013ea0,
      // #130325: the notice goes into the system prompt instead of the user prompt).
      const bootstrap = await importFromRepo(repoPath, "src/agents/embedded-agent-helpers/bootstrap.ts");
      const budget = await importFromRepo(repoPath, "src/agents/bootstrap-budget.ts");
      const budgetWarning = await importFromRepo(repoPath, "src/agents/bootstrap-budget-warning.ts");
      const warnings: string[] = [];
      const bootstrapFiles = (payload.bootstrapFiles ?? []).map((file) => ({
        name: file.name ?? "",
        path: file.path ?? "",
        ...(typeof file.content === "string" ? { content: file.content } : {}),
        missing: file.missing === true,
      }));
      const maxChars = payload.maxChars ?? bootstrap.resolveBootstrapMaxChars();
      const contextFiles = bootstrap.buildBootstrapContextFiles(bootstrapFiles, {
        warn: (message: string) => warnings.push(message),
        maxChars,
        ...(typeof payload.totalMaxChars === "number" ? { totalMaxChars: payload.totalMaxChars } : {}),
      });
      const totalMaxChars = payload.totalMaxChars ?? bootstrap.resolveBootstrapTotalMaxChars();
      const stats = budget.buildBootstrapInjectionStats({ bootstrapFiles, injectedFiles: contextFiles });
      const analysis = budget.analyzeBootstrapBudget({
        files: stats,
        bootstrapMaxChars: maxChars,
        bootstrapTotalMaxChars: totalMaxChars,
      });
      const promptWarning = budgetWarning.buildBootstrapPromptWarning({
        analysis,
        mode: payload.warningMode ?? "always",
        seenSignatures: payload.seenSignatures,
      });
      return {
        ok: true,
        operation: payload.operation,
        result: {
          contextFiles,
          warnings,
          stats,
          analysis: {
            files: analysis.files,
            totalNearLimit: analysis.totalNearLimit,
            hasTruncation: analysis.hasTruncation,
            totals: analysis.totals,
          },
          promptWarning: {
            signature: promptWarning.signature ?? null,
            warningShown: promptWarning.warningShown,
            lines: promptWarning.lines,
            warningSignaturesSeen: promptWarning.warningSignaturesSeen,
          },
          notice: budget.buildBootstrapPromptWarningNotice(promptWarning.lines) ?? null,
        },
      };
    });
  }

  if (payload.operation === "workspaceBootstrapFiles") {
    // src/agents/workspace.ts loadWorkspaceBootstrapFiles/filterBootstrapFilesForSession and
    // src/agents/bootstrap-files.ts resolveBootstrapFilesForRun/resolveBootstrapContextForRun on
    // a fixture workspace written by the Python side (no config, no hooks registered). At
    // v2026.9.6 setup completion lives in the SQLite state DB, so `steps` (runWorkspaceSteps,
    // the lifecycle op's edits and ensures) prepare that state in the same state dir first;
    // bySessionKey passes the bare session key (no workspaceDir, so every MEMORY.md-named file
    // is dropped for shared sessions), runs pass the workspace like the attempt does.
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    return withWorkspaceStepSandbox(async () => {
      const prepared = await runWorkspaceSteps(repoPath, workspaceDir, payload.steps ?? []);
      const workspace = await importFromRepo(repoPath, "src/agents/workspace.ts");
      const bootstrapFilesModule = await importFromRepo(repoPath, "src/agents/bootstrap-files.ts");
      const loaded = await workspace.loadWorkspaceBootstrapFiles(workspaceDir);
      const bySessionKey: Record<string, unknown[]> = {};
      for (const key of payload.keys ?? []) {
        bySessionKey[key] = workspace.filterBootstrapFilesForSession(loaded, key);
      }
      const runs = [];
      for (const run of payload.runs ?? []) {
        const warnings: string[] = [];
        const resolved = await captureUpstreamError(() =>
          bootstrapFilesModule.resolveBootstrapContextForRun({
            workspaceDir,
            sessionKey: run.sessionKey,
            contextMode: run.contextMode,
            runKind: run.runKind,
            warn: (message: string) => warnings.push(message),
          }),
        );
        runs.push(
          "error" in resolved
            ? { run, error: resolved.error, warnings }
            : {
                run,
                bootstrapFiles: resolved.bootstrapFiles,
                contextFiles: resolved.contextFiles,
                warnings,
              },
        );
      }
      return {
        ok: true,
        operation: payload.operation,
        result: {
          prepared,
          loaded,
          bySessionKey,
          runs,
          setupCompleted: await captureUpstreamError(() =>
            workspace.isWorkspaceSetupCompleted(workspaceDir),
          ),
          bootstrapStatus: await captureUpstreamError(() =>
            workspace.resolveWorkspaceBootstrapStatus(workspaceDir),
          ),
        },
      };
    });
  }

  if (payload.operation === "projectContextRender") {
    return withIsolatedRuntimeState("openclaw-oracle-project-context-", async () => {
      // src/agents/system-prompt.ts buildAgentSystemPrompt at v2026.9.6. Project Context is the
      // last block of the stable prefix: buildProjectContextSection
      // (src/agents/system-prompt-context-files.ts) is pushed right before
      // SYSTEM_PROMPT_CACHE_BOUNDARY (system-prompt.ts:1140-1143), and the tag has no dynamic
      // Project Context below the boundary (the pin's "# Dynamic Project Context" for
      // HEARTBEAT.md went with the monitor scratch). So `stable` runs from "# Project Context" to
      // the boundary, and `projectContextBelowBoundary` reports whether any Project Context
      // heading appears in the volatile suffix. buildAgentBootstrapSystemPromptSections is
      // private (system-prompt.ts:257), so the bootstrap sections are cut from the same prompt
      // (bootstrapSectionsText).
      const systemPrompt = await importFromRepo(repoPath, "src/agents/system-prompt.ts");
      const boundaryModule = await importFromRepo(
        repoPath,
        "packages/ai/src/utils/system-prompt-cache-boundary.ts",
      );
      const boundary: string = boundaryModule.SYSTEM_PROMPT_CACHE_BOUNDARY;
      const contextFiles = payload.contextFiles ?? [];
      const prompt: string = systemPrompt.buildAgentSystemPrompt({
        workspaceDir: payload.workspaceDir ?? "/w",
        contextFiles,
        bootstrapMode: payload.bootstrapMode,
        bootstrapTruncationNotice: payload.bootstrapTruncationNotice,
        silentReplyPromptMode: "none",
      });
      const boundaryIndex = prompt.indexOf(boundary);
      if (boundaryIndex === -1) {
        throw new Error("cache boundary missing from system prompt");
      }
      const stablePart = prompt.slice(0, boundaryIndex);
      const stableStart = stablePart.indexOf("\n# Project Context\n");
      const stable =
        stableStart === -1 ? "" : stablePart.slice(stableStart + 1).replace(/\n$/, "");
      const volatileSuffix = prompt.slice(boundaryIndex + boundary.length);
      const workspaceHeading = "## Workspace Files (injected)\n";
      const workspaceIndex = prompt.indexOf(workspaceHeading);
      const workspaceLineEnd = prompt.indexOf("\n", workspaceIndex + workspaceHeading.length);
      const pendingIndex = prompt.indexOf("## Bootstrap Pending\n");
      return {
        ok: true,
        operation: payload.operation,
        result: {
          stable,
          projectContextBelowBoundary: /^# (?:Dynamic )?Project Context$/mu.test(volatileSuffix),
          workspaceFiles:
            workspaceIndex === -1 ? null : prompt.slice(workspaceIndex, workspaceLineEnd),
          bootstrapSections: bootstrapSectionsText(prompt, workspaceIndex),
          bootstrapPendingInPrompt: pendingIndex !== -1,
        },
      };
    });
  }

  if (payload.operation === "workspaceLifecycle") {
    // src/agents/workspace.ts ensureAgentWorkspace + resolveWorkspaceBootstrapStatus over a
    // scripted sequence of file edits (runWorkspaceSteps). At v2026.9.6 setup state and
    // attestations live in the shared SQLite state DB (no workspace JSON state file; legacy JSON
    // state is refused until doctor migrates it), so one state dir per scenario plays the
    // agent's state across ensures (at the pin each ensure got a fresh one so no attestation
    // was ever "recent"). An ensure that throws records its message in that step's snapshot.
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    return withWorkspaceStepSandbox(async () => {
      const snapshots = await runWorkspaceSteps(repoPath, workspaceDir, payload.steps ?? []);
      return { ok: true, operation: payload.operation, result: { snapshots } };
    });
  }

  if (payload.operation === "toolsMdMigration") {
    // src/commands/doctor-tools-md-migration.ts maybeMigrateToolsMd({shouldRepair: true}) on a
    // fixture workspace written by the Python side, for one default agent "main" whose
    // workspace is workspaceDir (the upstream test's config shape). The archive lands under the
    // run's own state dir (<state>/backups/tools-md-migration); stateDirIsFile makes that path a
    // file, as upstream's "cannot be archived" test does. seedArchive (a memory-core probe; upstream
    // has no collision test) pre-writes <agent>-<sha256>.md there before the run: "same" holds
    // TOOLS.md's own text (archiveSource's EEXIST + matching digest path), "different" that text
    // plus one newline (the "archive collision" error with its EEXIST cause). Doctor notes are
    // suppressed (OPENCLAW_SUPPRESS_NOTES) so stdout carries only the JSON result.
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    return withIsolatedRuntimeState("openclaw-oracle-tools-md-", async () => {
      process.env.OPENCLAW_SUPPRESS_NOTES = "1";
      const stateDir = process.env.OPENCLAW_STATE_DIR as string;
      if (payload.stateDirIsFile) {
        await fs.rm(stateDir, { recursive: true, force: true });
        await fs.writeFile(stateDir, "not a directory", "utf-8");
      }
      const archiveDir = path.join(stateDir, "backups", "tools-md-migration");
      if (payload.seedArchive) {
        const tools = await fs.readFile(path.join(workspaceDir, "TOOLS.md"), "utf-8");
        const digest = crypto.createHash("sha256").update(tools).digest("hex");
        await fs.mkdir(archiveDir, { recursive: true, mode: 0o700 });
        await fs.writeFile(
          path.join(archiveDir, `main-${digest}.md`),
          payload.seedArchive === "same" ? tools : `${tools}\n`,
          "utf-8",
        );
      }
      const migration = await importFromRepo(repoPath, "src/commands/doctor-tools-md-migration.ts");
      const cfg = { agents: { list: [{ id: "main", default: true, workspace: workspaceDir }] } };
      const runs = [];
      for (let index = 0; index < (payload.repeat ?? 1); index += 1) {
        runs.push(
          await migration.maybeMigrateToolsMd({
            cfg,
            shouldRepair: true,
            env: { ...process.env, OPENCLAW_STATE_DIR: stateDir },
          }),
        );
      }
      const archives: Record<string, string> = {};
      for (const name of await fs.readdir(archiveDir).catch(() => [] as string[])) {
        archives[name] = await fs.readFile(path.join(archiveDir, name), "utf-8");
      }
      return {
        ok: true,
        operation: payload.operation,
        result: { runs, tree: await snapshotWorkspaceTree(workspaceDir), archives },
      };
    });
  }

  if (payload.operation === "toolsMdMigrationFindings") {
    // src/commands/doctor-tools-md-migration.ts collectToolsMdMigrationFindings (read-only
    // doctor health findings) for one default agent "main" whose workspace is workspaceDir, as
    // upstream's test builds the config; bootstrapMaxChars goes on that agent entry like the
    // test's `fixture.cfg.agents.list[0].bootstrapMaxChars`. The profile and container hints
    // that formatCliCommand would add to the fix hint are cleared.
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    return withIsolatedRuntimeState("openclaw-oracle-tools-md-findings-", async () => {
      delete process.env.OPENCLAW_PROFILE;
      delete process.env.OPENCLAW_CONTAINER_HINT;
      const migration = await importFromRepo(repoPath, "src/commands/doctor-tools-md-migration.ts");
      const agent: Record<string, unknown> = { id: "main", default: true, workspace: workspaceDir };
      if (payload.bootstrapMaxChars !== undefined) {
        agent.bootstrapMaxChars = payload.bootstrapMaxChars;
      }
      const findings = await migration.collectToolsMdMigrationFindings({ agents: { list: [agent] } });
      return {
        ok: true,
        operation: payload.operation,
        result: { findings, tree: await snapshotWorkspaceTree(workspaceDir) },
      };
    });
  }

  if (payload.operation === "toolsMdMergeDecision") {
    // src/commands/doctor-tools-md-migration-content.ts shouldMergeToolsMd and
    // src/commands/doctor-tools-md-migration-guidance.ts rewriteLegacyAgentsToolsGuidance.
    const content = await importFromRepo(repoPath, "src/commands/doctor-tools-md-migration-content.ts");
    const guidance = await importFromRepo(repoPath, "src/commands/doctor-tools-md-migration-guidance.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.texts ?? []).map((text) => ({
        shouldMerge: content.shouldMergeToolsMd(text ?? ""),
        rewritten: guidance.rewriteLegacyAgentsToolsGuidance(text ?? ""),
      })),
    };
  }

  if (payload.operation === "workspaceBootstrapPolicy") {
    // src/agents/workspace-bootstrap-policy.ts WORKSPACE_BOOTSTRAP_FILENAMES,
    // GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES and createWorkspaceBootstrapFilePolicy (no config,
    // so no bootstrap-extra-files patterns), plus src/agents/workspace.ts
    // isExpectedAbsentBootstrapFile.
    const policyModule = await importFromRepo(repoPath, "src/agents/workspace-bootstrap-policy.ts");
    const workspace = await importFromRepo(repoPath, "src/agents/workspace.ts");
    const policy = policyModule.createWorkspaceBootstrapFilePolicy({
      workspaceDir: payload.workspaceDir ?? "/w",
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        filenames: [...policyModule.WORKSPACE_BOOTSTRAP_FILENAMES],
        generated: [...policyModule.GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES],
        paths: (payload.keys ?? []).map((relativePath) => ({
          path: relativePath,
          canRead: policy.canRead(relativePath),
          canList: policy.canList(relativePath),
          canWrite: policy.canWrite(relativePath),
          expectedAbsent: workspace.isExpectedAbsentBootstrapFile(relativePath),
        })),
      },
    };
  }

  if (payload.operation === "startupContext") {
    return withIsolatedRuntimeState("openclaw-oracle-startup-context-", async () => {
      // src/auto-reply/reply/startup-context.ts buildSessionStartupContextPrelude.
      if (!payload.workspaceDir) {
        throw new Error("workspaceDir is required");
      }
      const startup = await importFromRepo(repoPath, "src/auto-reply/reply/startup-context.ts");
      const prelude = await startup.buildSessionStartupContextPrelude({
        workspaceDir: payload.workspaceDir,
        nowMs,
        cfg: {
          agents: {
            defaults: {
              userTimezone: timezone,
              ...(payload.startupContext ? { startupContext: payload.startupContext } : {}),
            },
          },
        },
      });
      return { ok: true, operation: payload.operation, result: { prelude: prelude ?? null } };
    });
  }

  if (payload.operation === "consolidateMemory") {
    // extensions/memory-core/src/dreaming-consolidation.ts through test-helpers.ts
    // consolidateMemoryForTests with a stubbed model (no network). Each scenario either runs the
    // model pass over `candidates` (replies: one entry per call, a string, {throw}, or
    // {raw} for a non-string result) or applies a hand-built `plan` directly.
    const helpers = await loadMemoryCoreTestHelpers(repoPath);
    const consolidation = await importFromRepo(
      repoPath,
      "extensions/memory-core/src/dreaming-consolidation.ts",
    );
    const scenarioResults: unknown[] = [];
    for (const scenario of payload.scenarios ?? []) {
      const warnings: string[] = [];
      const calls: Array<Record<string, unknown>> = [];
      const replies: unknown[] = Array.isArray(scenario.replies) ? scenario.replies : [];
      const subagent = {
        complete: async (options: Record<string, unknown>) => {
          calls.push({ ...options });
          const reply = replies[calls.length - 1] as unknown;
          if (isRecord(reply) && typeof reply.throw === "string") {
            throw new Error(reply.throw);
          }
          if (isRecord(reply) && "raw" in reply) {
            return reply.raw;
          }
          return { text: reply };
        },
      };
      const scenarioNowMs = Number.isFinite(scenario.nowMs) ? Number(scenario.nowMs) : nowMs;
      const applyParams = (plan: unknown) => ({
        existingMemory: String(scenario.existingMemory ?? ""),
        plan,
        nowMs: scenarioNowMs,
        timezone: scenario.timezone ?? "UTC",
        ...(typeof scenario.memoryFileMaxChars === "number"
          ? { memoryFileMaxChars: scenario.memoryFileMaxChars }
          : {}),
        maxPriorEntryLossFraction: Number(scenario.maxPriorEntryLossFraction ?? 0.25),
      });
      let plan: unknown = null;
      if (scenario.plan) {
        plan = scenario.plan;
      } else {
        plan = await helpers.consolidateMemoryForTests({
          subagent,
          existingMemory: String(scenario.existingMemory ?? ""),
          candidates: scenario.candidates ?? [],
          ...(typeof scenario.model === "string" ? { model: scenario.model } : {}),
          maxPriorEntryLossFraction: Number(scenario.maxPriorEntryLossFraction ?? 0.25),
          ...(typeof scenario.memoryFileMaxChars === "number"
            ? { memoryFileMaxChars: scenario.memoryFileMaxChars }
            : {}),
          ...(typeof scenario.maxPromotedSnippetTokens === "number"
            ? { maxPromotedSnippetTokens: scenario.maxPromotedSnippetTokens }
            : {}),
          nowMs: scenarioNowMs,
          logger: { info: () => {}, warn: (message: string) => warnings.push(message) },
        });
      }
      const applied = plan ? consolidation.applyMemoryConsolidationPlan(applyParams(plan)) : null;
      scenarioResults.push({ plan, applied, calls, warnings });
    }
    return {
      ok: true,
      operation: payload.operation,
      result: {
        systemPrompt: (
          await (async () => {
            // The system prompt is private; read it off a one-candidate pass.
            let seen: unknown = null;
            await helpers.consolidateMemoryForTests({
              subagent: {
                complete: async (options: Record<string, unknown>) => {
                  seen = options.extraSystemPrompt;
                  return { text: "{}" };
                },
              },
              existingMemory: "",
              candidates: [
                {
                  key: "k",
                  path: "memory/2026-07-01.md",
                  startLine: 1,
                  endLine: 1,
                  snippet: "x",
                  score: 0.5,
                  conceptTags: [],
                  provenance: { originClass: "owner" },
                },
              ],
              maxPriorEntryLossFraction: 0.25,
              nowMs,
              logger: { info: () => {}, warn: () => {} },
            });
            return seen;
          })()
        ),
        scenarios: scenarioResults,
      },
    };
  }

  if (payload.operation === "memoryBudgetCompaction") {
    // extensions/memory-core/src/memory-budget.ts compactMemoryForBudget (its private
    // parseMemoryBlocks decides which blocks are promotion sections) and
    // DEFAULT_MEMORY_FILE_MAX_CHARS.
    const budget = await importFromRepo(repoPath, "extensions/memory-core/src/memory-budget.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: {
        defaultMemoryFileMaxChars: budget.DEFAULT_MEMORY_FILE_MAX_CHARS,
        cases: (payload.cases ?? []).map((item) =>
          budget.compactMemoryForBudget({
            existingMemory: String(item.existingMemory ?? ""),
            newSection: String(item.newSection ?? ""),
            budgetChars: Number(item.budgetChars),
          }),
        ),
      },
    };
  }

  if (payload.operation === "heartbeatConstants") {
    // src/auto-reply/heartbeat.ts and src/auto-reply/tokens.ts exports. The pin's
    // HEARTBEAT_TRANSCRIPT_PROMPT is INTERNAL_WAKE_TRANSCRIPT_PROMPTS.heartbeat at v2026.9.6
    // (cdda5825f8b, #143866; same "[OpenClaw heartbeat poll]" value); every value of that
    // object is a transcript row the heartbeat filter drops.
    const heartbeat = await importFromRepo(repoPath, "src/auto-reply/heartbeat.ts");
    const tokens = await importFromRepo(repoPath, "src/auto-reply/tokens.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: {
        HEARTBEAT_TOKEN: tokens.HEARTBEAT_TOKEN,
        SILENT_REPLY_TOKEN: tokens.SILENT_REPLY_TOKEN,
        HEARTBEAT_PROMPT: heartbeat.HEARTBEAT_PROMPT,
        HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS: heartbeat.HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS,
        HEARTBEAT_RESPONSE_TOOL_PROMPT: heartbeat.HEARTBEAT_RESPONSE_TOOL_PROMPT,
        HEARTBEAT_TRANSCRIPT_PROMPT: heartbeat.INTERNAL_WAKE_TRANSCRIPT_PROMPTS.heartbeat,
        INTERNAL_WAKE_TRANSCRIPT_PROMPTS: Object.values(heartbeat.INTERNAL_WAKE_TRANSCRIPT_PROMPTS),
        DEFAULT_HEARTBEAT_EVERY: heartbeat.DEFAULT_HEARTBEAT_EVERY,
        DEFAULT_HEARTBEAT_ACK_MAX_CHARS: heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
      },
    };
  }

  if (payload.operation === "heartbeatContentEffectivelyEmpty") {
    // src/auto-reply/heartbeat.ts isHeartbeatContentEffectivelyEmpty; null stands for undefined.
    const heartbeat = await importFromRepo(repoPath, "src/auto-reply/heartbeat.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.texts ?? []).map((text) =>
        heartbeat.isHeartbeatContentEffectivelyEmpty(text ?? undefined),
      ),
    };
  }

  // Retired at v2026.9.6: parseHeartbeatTasks and isTaskDue were removed in b23c7bd0f84 (#113165;
  // HEARTBEAT.md `tasks:` entries became independent cron jobs, cron owns due-ness), so the
  // parseHeartbeatTasks and heartbeatTaskDue ops are gone (docs/upstream_port_v2026_9_6.md).

  if (payload.operation === "heartbeatDurations") {
    // src/cli/parse-duration.ts parseDurationMs and src/infra/heartbeat-summary.ts
    // resolveHeartbeatIntervalMs (the duration and interval cases of the pin's
    // heartbeatTaskDue op). Case kinds: "duration" (ms or the thrown message), "interval"
    // (every absent = unset heartbeat config).
    const duration = await importFromRepo(repoPath, "src/cli/parse-duration.ts");
    const summary = await importFromRepo(repoPath, "src/infra/heartbeat-summary.ts");
    const result = (payload.cases ?? []).map((item) => {
      if (item.kind === "duration") {
        try {
          return {
            ms: duration.parseDurationMs(
              item.raw,
              item.defaultUnit ? { defaultUnit: item.defaultUnit } : undefined,
            ),
          };
        } catch (error) {
          return { error: error instanceof Error ? error.message : String(error) };
        }
      }
      if (item.kind === "interval") {
        return summary.resolveHeartbeatIntervalMs(
          {},
          undefined,
          "every" in item ? { every: item.every } : undefined,
        );
      }
      throw new Error(`unknown heartbeatDurations case kind: ${String(item.kind)}`);
    });
    return { ok: true, operation: payload.operation, result };
  }

  if (payload.operation === "heartbeatPromptConfig") {
    // src/auto-reply/heartbeat.ts resolveHeartbeatPromptCore (the pin's resolveHeartbeatPrompt,
    // renamed in e74be5d41db, #122157) / resolveHeartbeatPromptForResponseTool; null stands
    // for an unset prompt.
    const heartbeat = await importFromRepo(repoPath, "src/auto-reply/heartbeat.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.texts ?? []).map((text) => ({
        prompt: heartbeat.resolveHeartbeatPromptCore(text ?? undefined),
        responseToolPrompt: heartbeat.resolveHeartbeatPromptForResponseTool(text ?? undefined),
      })),
    };
  }

  if (payload.operation === "stripHeartbeatToken") {
    // src/auto-reply/heartbeat.ts stripHeartbeatToken; text null stands for undefined.
    const heartbeat = await importFromRepo(repoPath, "src/auto-reply/heartbeat.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.cases ?? []).map((item) =>
        heartbeat.stripHeartbeatToken(item.text ?? undefined, {
          ...("mode" in item ? { mode: item.mode } : {}),
          ...("maxAckChars" in item ? { maxAckChars: item.maxAckChars } : {}),
        }),
      ),
    };
  }

  if (payload.operation === "heartbeatRunPrompt") {
    // src/infra/heartbeat-runner.ts runHeartbeatOnce per case, with the case's monitor scratch
    // seeded the way upstream's tests do (seedHeartbeatScratchForTest: a CronService heartbeat
    // job plus writeCronJobScratch, here in a per-case cron store partition, cfg.cron.store)
    // and the case's scheduled tasks passed as `tasks` (what cron hands the runner for due
    // heartbeat-task jobs). Target "none" (no channel delivery), messages.visibleReplies pins the
    // heartbeat_respond choice, and getReplyFromConfig captures the model input and answers
    // HEARTBEAT_OK. The Body ends with appendCronStyleCurrentTimeLine's lines, returned as
    // timeLine from the real resolveCronStyleNow; like flushPlan, the op reports the host's
    // detected 12/24-hour format (hostTimeFormat, resolveUserTimeFormat(undefined), which
    // resolveCronStyleNow uses since edecdbd05ef #111527) so the Python side can pass it on.
    // plugins.enabled=false keeps runHeartbeatOnce from loading the runtime plugin registry;
    // the main session entry is seeded through the SQLite session accessor. HOME and
    // OPENCLAW_STATE_DIR are sandboxed.
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-heartbeat-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    await fs.mkdir(process.env.HOME, { recursive: true });
    try {
      const runner = await importFromRepo(repoPath, "src/infra/heartbeat-runner.ts");
      const sessions = await importFromRepo(repoPath, "src/config/sessions.ts");
      const sessionAccessor = await importFromRepo(repoPath, "src/config/sessions/session-accessor.ts");
      const currentTime = await importFromRepo(repoPath, "src/agents/current-time.ts");
      const dateTime = await importFromRepo(repoPath, "src/agents/date-time.ts");
      const results = [];
      let index = 0;
      for (const scenario of payload.cases ?? []) {
        index += 1;
        const scenarioNowMs = Number(scenario.nowMs);
        const storePath = path.join(sandbox, `sessions-${index}.json`);
        const cronStorePath = path.join(sandbox, `cron-${index}`, "jobs.json");
        await seedHeartbeatScratchCase(repoPath, cronStorePath, scenario.scratch);
        const cfg = {
          plugins: { enabled: false },
          agents: {
            defaults: {
              workspace: path.join(sandbox, `workspace-${index}`),
              userTimezone: "UTC",
              heartbeat: {
                every: "5m",
                target: "none",
                ...(typeof scenario.prompt === "string" ? { prompt: scenario.prompt } : {}),
              },
            },
          },
          messages: { visibleReplies: scenario.useResponseTool ? "message_tool" : "automatic" },
          session: { store: storePath },
          cron: { store: cronStorePath },
        };
        const sessionKey = sessions.resolveMainSessionKey(cfg);
        await sessionAccessor.replaceSessionEntry(
          { storePath, sessionKey },
          { sessionId: `sid-${index}`, updatedAt: scenarioNowMs - 3_600_000 },
        );
        const calls: Array<{ ctx: Record<string, unknown>; opts: Record<string, unknown> }> = [];
        const res = await runner.runHeartbeatOnce({
          cfg,
          ...(scenario.source ? { source: scenario.source } : {}),
          ...(scenario.intent ? { intent: scenario.intent } : {}),
          ...(scenario.reason ? { reason: scenario.reason } : {}),
          ...(scenario.tasks ? { tasks: scenario.tasks } : {}),
          deps: {
            getQueueSize: () => 0,
            nowMs: () => scenarioNowMs,
            getReplyFromConfig: async (ctx: Record<string, unknown>, opts: Record<string, unknown>) => {
              calls.push({ ctx, opts });
              return { text: "HEARTBEAT_OK" };
            },
          },
        });
        results.push({
          status: res.status,
          reason: res.status === "skipped" ? res.reason : null,
          body: calls[0]?.ctx?.Body ?? null,
          isHeartbeat: calls[0]?.opts?.isHeartbeat ?? null,
          timeLine: currentTime.resolveCronStyleNow(cfg, scenarioNowMs).timeLine,
        });
      }
      return {
        ok: true,
        operation: payload.operation,
        hostTimeFormat: dateTime.resolveUserTimeFormat(undefined),
        result: results,
      };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "heartbeatPreflight") {
    // src/infra/heartbeat-runner-prompt.ts resolveHeartbeatPreflight and resolveHeartbeatRunPrompt
    // called directly per case (fresh process: no queued system events), with the case's monitor
    // scratch seeded in its own cron store partition like heartbeatRunPrompt. The run prompt is
    // resolved from that preflight with canRelayToUser false, as runHeartbeatOnce passes
    // preflight.heartbeatScratchContent and the case's scheduled tasks.
    return withIsolatedRuntimeState("openclaw-oracle-heartbeat-preflight-", async () => {
      const prompt = await importFromRepo(repoPath, "src/infra/heartbeat-runner-prompt.ts");
      const results = [];
      let index = 0;
      for (const scenario of payload.cases ?? []) {
        index += 1;
        const cronStorePath = path.join(
          process.env.OPENCLAW_STATE_DIR as string,
          `cron-${index}`,
          "jobs.json",
        );
        await seedHeartbeatScratchCase(repoPath, cronStorePath, scenario.scratch);
        const heartbeat = {
          every: "5m",
          target: "none",
          ...(typeof scenario.prompt === "string" ? { prompt: scenario.prompt } : {}),
        };
        const cfg = {
          agents: { defaults: { heartbeat } },
          cron: { store: cronStorePath },
          session: { store: path.join(process.env.OPENCLAW_STATE_DIR as string, `sessions-${index}.json`) },
        };
        const scheduledTasks = scenario.tasks ?? [];
        const preflight = await prompt.resolveHeartbeatPreflight({
          cfg,
          agentId: "main",
          heartbeat,
          ...(scenario.source ? { source: scenario.source } : {}),
          ...(scenario.reason ? { reason: scenario.reason } : {}),
          scheduledTasks,
        });
        const run = preflight.skipReason
          ? null
          : prompt.resolveHeartbeatRunPrompt({
              cfg,
              heartbeat,
              preflight,
              canRelayToUser: false,
              startedAt: Number(scenario.nowMs ?? 0),
              scheduledTasks,
              heartbeatScratchContent: preflight.heartbeatScratchContent,
              useHeartbeatResponseTool: Boolean(scenario.useResponseTool),
            });
        results.push({
          skipReason: preflight.skipReason ?? null,
          heartbeatScratchContent: preflight.heartbeatScratchContent ?? null,
          scratchRevision: preflight.scratchRevision ?? null,
          isExecEventWake: preflight.isExecEventWake,
          isCronWake: preflight.isCronWake,
          isWakePayload: preflight.isWakePayload,
          prompt: run?.prompt ?? null,
          usesHeartbeatResponseTool: run?.usesHeartbeatResponseTool ?? null,
        });
      }
      return { ok: true, operation: payload.operation, result: results };
    });
  }

  if (payload.operation === "heartbeatReplyDecision") {
    // src/infra/heartbeat-delivery-normalization.ts classifyHeartbeatAgentOutcome for a plain text
    // reply (no tool response, no run failure, no media, no source-reply suppression, no exec
    // relay), with DEFAULT_HEARTBEAT_ACK_MAX_CHARS as heartbeat-dispatch.ts passes it; plus
    // src/auto-reply/tokens.ts isSilentReplyPayloadText and src/auto-reply/heartbeat.ts
    // isHeartbeatAcknowledgementText on the same text. text null stands for no reply payload.
    const normalization = await importFromRepo(repoPath, "src/infra/heartbeat-delivery-normalization.ts");
    const tokens = await importFromRepo(repoPath, "src/auto-reply/tokens.ts");
    const heartbeat = await importFromRepo(repoPath, "src/auto-reply/heartbeat.ts");
    const result = (payload.cases ?? []).map((item) => {
      const outcome = normalization.classifyHeartbeatAgentOutcome({
        agentRun: {
          agentRunFailed: false,
          ...(item.text === null || item.text === undefined ? {} : { replyPayload: { text: item.text } }),
        },
        hasRelayableExecCompletion: false,
        suppressUnmarkedSourceReplies: false,
        responsePrefix: item.responsePrefix ?? undefined,
        ackMaxChars: heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
      });
      return {
        decision:
          outcome.kind === "delivery"
            ? { kind: "delivery", text: outcome.normalized.text, silent: Boolean(outcome.normalized.silent) }
            : { kind: outcome.kind, eventStatus: outcome.eventStatus, silent: Boolean(outcome.silent) },
        silentReply: tokens.isSilentReplyPayloadText(item.text ?? undefined),
        acknowledgement: heartbeat.isHeartbeatAcknowledgementText(item.text ?? undefined),
      };
    });
    return { ok: true, operation: payload.operation, result };
  }

  // Retired at v2026.9.6: the heartbeatSystemSection op read src/agents/heartbeat-system-prompt.ts
  // and the "## Heartbeats" system-prompt section, both removed in 6a1dedb00c2 (#129642); the
  // heartbeat prompt now lives only in the scheduled heartbeat user turn
  // (src/infra/heartbeat-runner-prompt.ts resolveHeartbeatRunPrompt).

  if (payload.operation === "heartbeatSessionFilter") {
    // src/auto-reply/heartbeat-filter.ts isHeartbeatUserMessage over message cases, and
    // packages/memory-host-sdk/src/host/session-files.ts buildSessionEntry (whose
    // sanitizeSessionText drops heartbeat rows) over transcript fixtures in a sandboxed
    // OPENCLAW_STATE_DIR.
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-heartbeat-corpus-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    await fs.mkdir(process.env.HOME, { recursive: true });
    try {
      const filter = await importFromRepo(repoPath, "src/auto-reply/heartbeat-filter.ts");
      const hints = await importFromRepo(repoPath, "src/plugin-sdk/message-tool-delivery-hints.ts");
      const sessionFiles = await importFromRepo(
        repoPath,
        "packages/memory-host-sdk/src/host/session-files.ts",
      );
      const messages = (payload.cases ?? []).map((item) =>
        filter.isHeartbeatUserMessage(item.message, item.heartbeatPrompt ?? undefined),
      );
      const sessionsDir = path.join(process.env.OPENCLAW_STATE_DIR, "agents", "main", "sessions");
      await fs.mkdir(sessionsDir, { recursive: true });
      const entries = [];
      for (const transcript of payload.sessionTranscripts ?? []) {
        const fileName = transcript.fileName?.trim() || "session-oracle.jsonl";
        if (fileName.includes("/") || fileName.includes("\\") || !fileName.endsWith(".jsonl")) {
          throw new Error(`invalid session transcript fixture name: ${fileName}`);
        }
        const absPath = path.join(sessionsDir, fileName);
        const lines = (transcript.entries ?? []).map((entry) => JSON.stringify(entry));
        await fs.writeFile(absPath, `${lines.join("\n")}\n`, "utf-8");
        const entry = await sessionFiles.buildSessionEntry(absPath);
        entries.push(entry ? { content: entry.content, lineMap: entry.lineMap } : null);
      }
      return {
        ok: true,
        operation: payload.operation,
        result: { messages, entries, deliveryHints: [...hints.MESSAGE_TOOL_DELIVERY_HINTS] },
      };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "heartbeatScratchContract") {
    // src/cron/scratch-contract.ts CRON_JOB_SCRATCH_MAX_BYTES and assertCronJobScratchContent
    // over size cases (content built as `unit` repeated `count` times plus `suffix`), then
    // src/cron/scratch-store.ts writeCronJobScratch / readCronJobScratchState /
    // deleteCronJobScratch / readHeartbeatMonitorScratch over a step sequence on the real state
    // DB, and hashCronScratchSource over texts. The heartbeat monitor job is added like
    // src/infra/heartbeat-runner.test-utils.ts seedHeartbeatScratchForTest (a system-owned
    // CronService job, declarationKey heartbeat:<agentId>, payload heartbeat) without a scratch
    // row; readHeartbeatMonitorScratch results drop the generated jobId.
    return withIsolatedRuntimeState("openclaw-oracle-heartbeat-scratch-", async () => {
      const contract = await importFromRepo(repoPath, "src/cron/scratch-contract.ts");
      const store = await importFromRepo(repoPath, "src/cron/scratch-store.ts");
      const cronStore = await importFromRepo(repoPath, "src/cron/store.ts");
      const storePath = cronStore.resolveCronJobsStorePath();
      const jobId = await seedHeartbeatMonitorJob(repoPath, storePath, "main");
      const build = (item: Record<string, any>) =>
        `${String(item.unit ?? "").repeat(Number(item.count ?? 0))}${String(item.suffix ?? "")}`;
      const sizes = (payload.cases ?? []).map((item) => {
        try {
          contract.assertCronJobScratchContent(build(item));
          return { ok: true };
        } catch (error) {
          return { error: error instanceof Error ? error.message : String(error) };
        }
      });
      const steps = [];
      for (const step of payload.scenarios ?? []) {
        try {
          if (step.op === "write") {
            steps.push(
              store.writeCronJobScratch({
                storePath,
                jobId,
                content: step.content && typeof step.content === "object" ? build(step.content) : step.content,
                ...("expectedRevision" in step ? { expectedRevision: step.expectedRevision } : {}),
                ...("sourceSha256" in step ? { sourceSha256: step.sourceSha256 } : {}),
                ...("nowMs" in step ? { nowMs: step.nowMs } : {}),
              }),
            );
          } else if (step.op === "read") {
            steps.push(store.readCronJobScratchState(storePath, jobId));
          } else if (step.op === "readMonitor") {
            steps.push(store.readHeartbeatMonitorScratch(storePath, "main")?.state ?? null);
          } else if (step.op === "delete") {
            steps.push(
              store.deleteCronJobScratch(
                storePath,
                jobId,
                {},
                "expectedRevision" in step ? { expectedRevision: step.expectedRevision } : undefined,
              ),
            );
          } else {
            throw new Error(`unknown heartbeatScratchContract step: ${String(step.op)}`);
          }
        } catch (error) {
          steps.push({ error: error instanceof Error ? error.message : String(error) });
        }
      }
      return {
        ok: true,
        operation: payload.operation,
        result: {
          maxBytes: contract.CRON_JOB_SCRATCH_MAX_BYTES,
          sizes,
          steps,
          hashes: (payload.texts ?? []).map((text) => store.hashCronScratchSource(text ?? "")),
        },
      };
    });
  }

  if (payload.operation === "legacyHeartbeatTasks") {
    // src/commands/heartbeat-task-legacy.ts analyzeLegacyHeartbeatTasks (doctor's reader of the
    // retired tasks: syntax) over texts.
    const legacy = await importFromRepo(repoPath, "src/commands/heartbeat-task-legacy.ts");
    return {
      ok: true,
      operation: payload.operation,
      result: (payload.texts ?? []).map((text) => legacy.analyzeLegacyHeartbeatTasks(text ?? "")),
    };
  }

  if (payload.operation === "heartbeatScratchMigration") {
    // src/commands/doctor-heartbeat-scratch-migration.ts maybeMigrateHeartbeatFilesToScratch
    // ({shouldRepair: true}) and collectHeartbeatScratchMigrationFindings on a fixture workspace
    // written by the Python side, for agent "main" (every 30m) whose workspace is workspaceDir;
    // retainSource adds agent "ops" with heartbeat every 0m on the same workspace (upstream's
    // disabled shared owner). Steps: "migrate", "findings", "scratch" (ensureHeartbeatMonitorJobs
    // then writeCronJobScratch for main: content, or null to unset) and "write" (a workspace
    // file). After each migrate the op returns main's scratch state, the workspace tree and the
    // archive listing under <state>/backups/heartbeat-migration (a directory maps its entries).
    if (!payload.workspaceDir) {
      throw new Error("workspaceDir is required");
    }
    const workspaceDir = payload.workspaceDir;
    return withIsolatedRuntimeState("openclaw-oracle-heartbeat-migration-", async () => {
      process.env.OPENCLAW_SUPPRESS_NOTES = "1";
      delete process.env.OPENCLAW_PROFILE;
      delete process.env.OPENCLAW_CONTAINER_HINT;
      const stateDir = process.env.OPENCLAW_STATE_DIR as string;
      const migration = await importFromRepo(repoPath, "src/commands/doctor-heartbeat-scratch-migration.ts");
      const cadence = await importFromRepo(repoPath, "src/commands/doctor-heartbeat-cadence-migration.ts");
      const store = await importFromRepo(repoPath, "src/cron/scratch-store.ts");
      const cronStore = await importFromRepo(repoPath, "src/cron/store.ts");
      // retainSource is doctor-heartbeat-scratch-migration.test.ts sharedHeartbeatConfig: an
      // explicit heartbeat on each agent makes only those agents heartbeat owners.
      const cfg = payload.scenarios?.[0]?.retainSource
        ? {
            agents: {
              defaults: { workspace: workspaceDir },
              list: [
                { id: "main", workspace: workspaceDir, heartbeat: { every: "30m" } },
                { id: "ops", workspace: workspaceDir, heartbeat: { every: "0m" } },
              ],
            },
          }
        : {
            agents: {
              defaults: { heartbeat: { every: "30m" } },
              list: [{ id: "main", default: true, workspace: workspaceDir }],
            },
          };
      const storePath = cronStore.resolveCronJobsStorePathFromConfig(cfg);
      const archiveDir = path.join(stateDir, "backups", "heartbeat-migration");
      const monitorId = async () => (await cadence.ensureHeartbeatMonitorJobs(cfg, storePath)).get("main").id;
      const listArchives = async () => {
        const out: Record<string, unknown> = {};
        for (const entry of await fs.readdir(archiveDir, { withFileTypes: true }).catch(() => [])) {
          const full = path.join(archiveDir, entry.name);
          if (entry.isDirectory()) {
            const inner: Record<string, string> = {};
            for (const name of await fs.readdir(full)) {
              inner[name] = await fs.readFile(path.join(full, name), "utf-8");
            }
            out[`${entry.name}/`] = inner;
          } else {
            out[entry.name] = await fs.readFile(full, "utf-8");
          }
        }
        return out;
      };
      const steps = [];
      for (const step of payload.steps ?? []) {
        if (step.op === "write") {
          await fs.writeFile(path.join(workspaceDir, String(step.path)), String(step.content ?? ""), "utf-8");
          steps.push(null);
        } else if (step.op === "scratch") {
          const jobId = await monitorId();
          const current = store.readCronJobScratchState(storePath, jobId);
          steps.push(
            store.writeCronJobScratch({
              storePath,
              jobId,
              content: step.content ?? null,
              expectedRevision: current.currentRevision,
            }),
          );
        } else if (step.op === "findings") {
          steps.push(await migration.collectHeartbeatScratchMigrationFindings(cfg));
        } else if (step.op === "migrate") {
          const result = await migration.maybeMigrateHeartbeatFilesToScratch({ cfg, shouldRepair: true });
          steps.push({
            result,
            scratch: store.readCronJobScratchState(storePath, await monitorId()),
            tree: await snapshotWorkspaceTree(workspaceDir),
            archives: await listArchives(),
          });
        } else {
          throw new Error(`unknown heartbeatScratchMigration step: ${String(step.op)}`);
        }
      }
      return { ok: true, operation: payload.operation, result: steps };
    });
  }

  if (payload.operation === "heartbeatTaskMigration") {
    // src/commands/doctor-heartbeat-task-migration.ts maybeMigrateHeartbeatTasksToCron
    // ({shouldRepair: true, nowMs}) and collectHeartbeatTaskMigrationFindings, set up like
    // doctor-heartbeat-task-migration.test.ts createFixture: agent "main" (every 30m), its
    // heartbeat monitor job with the case's scratch, the heartbeat session entry with the case's
    // legacy heartbeatTaskState, and optional existing cron jobs (CronService.add with the given
    // fields, matchesExisting isHeartbeatTaskCronJob, as createExistingInboxJob). Each run returns
    // changes/warnings, the heartbeat-task jobs (sorted by declaration key, ids dropped), main's
    // scratch state and the session's remaining heartbeatTaskState.
    return withIsolatedRuntimeState("openclaw-oracle-heartbeat-tasks-", async () => {
      process.env.OPENCLAW_SUPPRESS_NOTES = "1";
      delete process.env.OPENCLAW_PROFILE;
      delete process.env.OPENCLAW_CONTAINER_HINT;
      const env = { ...process.env };
      const migration = await importFromRepo(repoPath, "src/commands/doctor-heartbeat-task-migration.ts");
      const store = await importFromRepo(repoPath, "src/cron/scratch-store.ts");
      const cronStore = await importFromRepo(repoPath, "src/cron/store.ts");
      const heartbeatTask = await importFromRepo(repoPath, "src/cron/heartbeat-task.ts");
      const heartbeatSession = await importFromRepo(repoPath, "src/infra/heartbeat-runner-session.ts");
      const sessionAccessor = await importFromRepo(repoPath, "src/config/sessions/session-accessor.ts");
      const { CronService } = await importFromRepo(repoPath, "src/cron/service.ts");
      const cfg = { agents: { defaults: { heartbeat: { every: "30m" } }, list: [{ id: "main" }] } };
      const storePath = cronStore.resolveCronJobsStorePathFromConfig(cfg, env);
      const scenario = payload.scenarios?.[0] ?? {};
      const nowMs = Number(scenario.nowMs);
      const jobId = await seedHeartbeatMonitorJob(repoPath, storePath, "main");
      store.writeCronJobScratch({ storePath, jobId, content: String(scenario.scratch ?? ""), expectedRevision: 0 });
      const session = heartbeatSession.resolveHeartbeatSession(cfg, "main", cfg.agents.defaults.heartbeat, undefined, env);
      await sessionAccessor.replaceSessionEntry(
        { storePath: session.storePath, sessionKey: session.sessionKey, env },
        {
          sessionId: "heartbeat-main",
          updatedAt: nowMs,
          ...(scenario.taskState ? { heartbeatTaskState: scenario.taskState } : {}),
        },
      );
      const noop = () => {};
      for (const job of scenario.existingJobs ?? []) {
        const cron = new CronService({
          storePath,
          nowMs: () => nowMs - 60_000,
          cronEnabled: false,
          defaultAgentId: "main",
          log: { debug: noop, info: noop, warn: noop, error: noop },
          enqueueSystemEvent: () => false,
          requestHeartbeat: noop,
          runIsolatedAgentJob: async () => ({ status: "skipped", error: "oracle" }),
        });
        await cron.add(job, {
          enabledExplicit: true,
          systemOwned: true,
          matchesExisting: heartbeatTask.isHeartbeatTaskCronJob,
        });
      }
      const runs = [];
      for (const offset of scenario.runOffsetsMs ?? [0]) {
        const findings = await migration.collectHeartbeatTaskMigrationFindings(cfg, env);
        const result = await migration.maybeMigrateHeartbeatTasksToCron({
          cfg,
          env,
          shouldRepair: true,
          nowMs: nowMs + Number(offset),
        });
        const jobs = (await cronStore.loadCronJobsStore(storePath)).jobs
          .filter(heartbeatTask.isHeartbeatTaskCronJob)
          .map(({ id: _id, ...rest }: Record<string, unknown>) => rest)
          .toSorted((a: any, b: any) => (a.declarationKey < b.declarationKey ? -1 : 1));
        runs.push({
          findings,
          result,
          jobs,
          scratch: store.readCronJobScratchState(storePath, jobId),
          taskState:
            heartbeatSession.resolveHeartbeatSession(cfg, "main", undefined, undefined, env).entry
              ?.heartbeatTaskState ?? null,
        });
      }
      return { ok: true, operation: payload.operation, result: { storePath, runs } };
    });
  }

  if (payload.operation === "automationJobSchedule") {
    // src/cron/service/jobs-scheduling.ts computeJobNextRunAtMs and isJobDue (not forced) over
    // every-schedule jobs given in upstream's CronJob shape, each at the case's nowMs; and
    // src/cron/heartbeat-task.ts heartbeatTaskDeclarationKey / isHeartbeatTaskCronJob.
    const scheduling = await importFromRepo(repoPath, "src/cron/service/jobs-scheduling.ts");
    const heartbeatTask = await importFromRepo(repoPath, "src/cron/heartbeat-task.ts");
    const result = (payload.cases ?? []).map((item) => {
      const job = structuredClone(item.job);
      return {
        nextRunAtMs: scheduling.computeJobNextRunAtMs(structuredClone(job), Number(item.nowMs)) ?? null,
        due: scheduling.isJobDue(structuredClone(job), Number(item.nowMs), { forced: false }),
        isHeartbeatTask: heartbeatTask.isHeartbeatTaskCronJob(structuredClone(job)),
      };
    });
    const keys = (payload.scenarios ?? []).map((item) =>
      heartbeatTask.heartbeatTaskDeclarationKey(
        String(item.agentId),
        String(item.taskName),
        ...("occurrenceIndex" in item ? [Number(item.occurrenceIndex)] : []),
      ),
    );
    return { ok: true, operation: payload.operation, result: { cases: result, keys } };
  }

  // Replaces the retired sessionMemoryTranscript op (it called sanitizeSessionMemoryTranscriptText,
  // no longer exported since 2cc49503a60 #107412, and the file readers getRecentSessionContent,
  // getRecentSessionContentWithResetFallback and findPreviousSessionFile, removed with the
  // file-era transcript runtime in 4273ca9dbd9 #113233). The module now projects transcript
  // events: each case's `events` go through the real getRecentSessionProjectionFromEvents (with
  // `messageCount` when given) and countSessionMemoryMessages; sanitizeSessionMemoryTranscriptText
  // is exercised through the rendered text of a one-message case.
  if (payload.operation === "sessionMemoryProjection") {
    const transcript = await importFromRepo(repoPath, "src/hooks/bundled/session-memory/transcript.ts");
    const cases = (payload.cases ?? []).map((item: Record<string, any>) => ({
      projection:
        "messageCount" in item
          ? transcript.getRecentSessionProjectionFromEvents(item.events, item.messageCount)
          : transcript.getRecentSessionProjectionFromEvents(item.events),
      count: transcript.countSessionMemoryMessages(item.events),
    }));
    return { ok: true, operation: payload.operation, result: { cases } };
  }

  if (payload.operation === "sessionCorpusEntry") {
    // packages/memory-host-sdk/src/host/session-files.ts buildSessionEntryInProcess over a JSONL
    // transcript file per case (the file branch, whose line map is the raw line ordinal; the SQLite
    // branch is the same projection). Redaction is upstream's default, redactSensitiveText in
    // tools mode (memory_core.redact), the store classification is pinned by explicit
    // generatedBy* flags, and the file's mtime is set to the case's `mtimeMs`. A case's
    // `fileName` decides the archive handling (cron records classify only in usage-counted
    // archives such as x.jsonl.reset.<iso>).
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-session-entry-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    process.env.OPENCLAW_LOG_LEVEL = "silent";
    try {
      const sessionFiles = await importFromRepo(
        repoPath,
        "packages/memory-host-sdk/src/host/session-files.ts",
      );
      const cases = [];
      for (const [index, item] of (payload.cases ?? []).entries()) {
        const dir = path.join(sandbox, `case-${index}`);
        await fs.mkdir(dir, { recursive: true });
        const absPath = path.join(dir, String(item.fileName ?? "session.jsonl"));
        await fs.writeFile(absPath, String(item.jsonl), "utf-8");
        const mtime = new Date(Number(item.mtimeMs ?? 1_000_000_000_000));
        await fs.utimes(absPath, mtime, mtime);
        const observed: unknown[] = [];
        const entry = await sessionFiles.buildSessionEntryInProcess(
          absPath,
          {
            generatedByDreamingNarrative: item.generatedByDreamingNarrative ?? false,
            generatedByCronRun: item.generatedByCronRun ?? false,
            ...(item.sessionKind ? { sessionKind: item.sessionKind } : {}),
            onTranscriptMessage: (message: unknown, observedAt: number) =>
              observed.push([message, observedAt]),
          },
        );
        cases.push(
          entry
            ? {
                content: entry.content,
                lineMap: entry.lineMap,
                messageTimestampsMs: entry.messageTimestampsMs,
                lineProvenance: entry.lineProvenance,
                hash: entry.hash,
                sessionKind: entry.sessionKind,
                generatedByDreamingNarrative: entry.generatedByDreamingNarrative === true,
                generatedByCronRun: entry.generatedByCronRun === true,
                observed: observed.length,
              }
            : null,
        );
      }
      return { ok: true, operation: payload.operation, result: { cases } };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "redactSensitiveText") {
    // src/logging/redact.ts redactSensitiveText(text, { mode: "tools" }), the redaction
    // buildSessionEntry applies to every exported session text. `texts` are redacted one by one;
    // `meta` also returns the pattern tables (redact-patterns.ts) and the \p{C}/\p{Z} ranges
    // of this runtime for the table-equality checks.
    process.env.OPENCLAW_LOG_LEVEL = "silent";
    const redact = await importFromRepo(repoPath, "src/logging/redact.ts");
    const patterns = await importFromRepo(repoPath, "src/logging/redact-patterns.ts");
    const texts = (payload as Record<string, any>).texts ?? [];
    const result: Record<string, unknown> = {
      texts: texts.map((text: string) => redact.redactSensitiveText(text, { mode: "tools" })),
    };
    if ((payload as Record<string, any>).meta) {
      const ranges = (re: RegExp) => {
        const out: number[][] = [];
        let start = -1;
        for (let cp = 0; cp <= 0x10ffff; cp++) {
          const hit = re.test(String.fromCodePoint(cp));
          if (hit && start < 0) start = cp;
          if (!hit && start >= 0) {
            out.push([start, cp - 1]);
            start = -1;
          }
        }
        if (start >= 0) out.push([start, 0x10ffff]);
        return out;
      };
      result.meta = {
        defaultStringPatterns: [...patterns.DEFAULT_REDACT_STRING_PATTERNS],
        bodySecretKeys: [...patterns.BODY_SECRET_KEYS],
        unicodeC: ranges(/^\p{C}$/u),
        unicodeZ: ranges(/^\p{Z}$/u),
      };
    }
    return { ok: true, operation: payload.operation, result };
  }

  if (payload.operation === "redactModelVisibleSecrets") {
    // src/logging/redact.ts redactModelVisibleSecrets (the host redactor of the Responses
    // converter's tool-result text): `values` are JSON values redacted one by one, `keys` go
    // through isSensitiveFieldKey, `fields` ([key, value] pairs) through
    // redactModelVisibleSensitiveFieldValueWithConfig, and `meta` returns the tool-payload
    // pattern table. A sandbox HOME keeps readLoggingConfig on its default (no user patterns).
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-model-redact-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    process.env.OPENCLAW_LOG_LEVEL = "silent";
    try {
      const redact = await importFromRepo(repoPath, "src/logging/redact.ts");
      const patterns = await importFromRepo(repoPath, "src/logging/redact-patterns.ts");
      const body = payload as Record<string, any>;
      const result: Record<string, unknown> = {
        values: (body.values ?? []).map((value: unknown) => {
          try {
            return { value: redact.redactModelVisibleSecrets(structuredClone(value)) };
          } catch (error) {
            return { error: String((error as Error)?.name ?? error) };
          }
        }),
        keys: (body.keys ?? []).map((key: string) => redact.isSensitiveFieldKey(key)),
        fields: (body.fields ?? []).map(([key, value]: [string, string]) =>
          redact.redactModelVisibleSensitiveFieldValueWithConfig(key, value),
        ),
      };
      if (body.meta) {
        result.meta = {
          toolPayloadStringPatterns: patterns.TOOL_PAYLOAD_REDACT_PATTERNS.filter(
            (pattern: unknown) => typeof pattern === "string",
          ),
          toolPayloadPatternCount: patterns.TOOL_PAYLOAD_REDACT_PATTERNS.length,
          defaultPatternCount: patterns.DEFAULT_REDACT_PATTERNS.length,
        };
      }
      return { ok: true, operation: payload.operation, result };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "sessionMemorySlug") {
    // src/hooks/llm-slug-generator.ts generateSlugViaLLM with only its model run replaced:
    // a module hook resolves its ../agents/embedded-agent.js import to a stub whose
    // runEmbeddedAgent returns each case's reply (in memory-core the host supplies that model
    // call), so the real prompt, error-payload rejection and slug normalisation run. A
    // case reply is the first run payload ({text, isError}), null for no payloads, or
    // {throw} to make the run fail. `texts` go through the real parseApiErrorPayload and
    // extractLeadingHttpStatus (src/shared/assistant-error-format.ts).
    installEmbeddedAgentStub();
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-session-slug-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    // Logging only: keeps stdout JSON-only and the shared /tmp/openclaw log untouched.
    process.env.OPENCLAW_LOG_LEVEL = "silent";
    try {
      const slugGenerator = await importFromRepo(repoPath, "src/hooks/llm-slug-generator.ts");
      const errorFormat = await importFromRepo(repoPath, "src/shared/assistant-error-format.ts");
      const cases = [];
      for (const item of payload.cases ?? []) {
        const prompts: string[] = [];
        setEmbeddedAgentStubReply(item.reply, prompts);
        const slug = await slugGenerator.generateSlugViaLLM({
          sessionContent: String(item.sessionContent ?? ""),
          cfg: {},
          // Required at v2026.9.6 (the helper run is admitted for that agent).
          agentId: "main",
        });
        cases.push({ slug, prompt: prompts[0] ?? null });
      }
      const errorHelpers = (payload.texts ?? []).map((text) => ({
        payload: errorFormat.parseApiErrorPayload(text ?? undefined),
        status: errorFormat.extractLeadingHttpStatus(text ?? ""),
      }));
      return { ok: true, operation: payload.operation, result: { cases, errorHelpers } };
    } finally {
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  if (payload.operation === "sessionMemoryHook") {
    // src/hooks/bundled/session-memory/handler.ts default export (the /new and /reset
    // hook) plus flushSessionMemoryWritesForTest, with events from
    // src/hooks/internal-hooks.ts createInternalHookEvent. Each scenario gets its own
    // workspace (context.workspaceDir) seeded with `files`, then runs its events in
    // order: process.env.TZ = event.timezone, event.timestamp = new Date(event.nowMs),
    // hooks.internal.entries["session-memory"] from `messages`/`llmSlug`. At v2026.9.6 the hook
    // reads the ending session from the agent's SQLite store (captureSessionMemoryTranscript),
    // so each scenario gets its own agent id (its own store) and `transcripts`
    // ({sessionId: message events}) are seeded the way writeSessionTranscriptFixtures does
    // (upsertSessionEntry, then appendSessionTranscriptMessageByIdentity per message) under
    // every session key the scenario's events use for that id. With llmSlug the real
    // generateSlugViaLLM runs against the embedded-agent stub, which returns
    // `slugReply`. The result is the memory/ tree and the slug prompts per scenario.
    installEmbeddedAgentStub();
    const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-oracle-session-hook-"));
    process.env.HOME = path.join(sandbox, "home");
    process.env.OPENCLAW_STATE_DIR = path.join(sandbox, "state");
    // Logging only: keeps stdout JSON-only and the shared /tmp/openclaw log untouched.
    process.env.OPENCLAW_LOG_LEVEL = "silent";
    delete process.env.OPENCLAW_TEST_FAST;
    delete process.env.VITEST;
    delete process.env.NODE_ENV;
    const originalTz = process.env.TZ;
    try {
      const handler = await importFromRepo(repoPath, "src/hooks/bundled/session-memory/handler.ts");
      const internalHooks = await importFromRepo(repoPath, "src/hooks/internal-hooks.ts");
      const sessionPaths = await importFromRepo(repoPath, "src/config/sessions/paths.ts");
      const sessionStore = await importFromRepo(repoPath, "src/plugin-sdk/session-store-runtime.ts");
      const transcriptStore = await importFromRepo(
        repoPath,
        "src/plugin-sdk/session-transcript-runtime.ts",
      );
      const scenarios = [];
      for (const [index, scenario] of (payload.scenarios ?? []).entries()) {
        const workspaceDir = path.join(sandbox, `workspace-${index}`);
        await fs.mkdir(workspaceDir, { recursive: true });
        for (const [relative, content] of Object.entries(scenario.files ?? {})) {
          if (path.isAbsolute(relative) || relative.split("/").includes("..")) {
            throw new Error(`invalid session hook fixture path: ${relative}`);
          }
          await fs.mkdir(path.dirname(path.join(workspaceDir, relative)), { recursive: true });
          await fs.writeFile(path.join(workspaceDir, relative), String(content), "utf-8");
        }
        const prompts: string[] = [];
        const agentId = `oracle-${index}`;
        const storePath: string = sessionPaths.resolveSessionStorePathCore(undefined, { agentId });
        await fs.mkdir(path.dirname(storePath), { recursive: true });
        const seeded = new Set<string>();
        for (const event of (scenario.events ?? []) as Array<Record<string, any>>) {
          const entry =
            (event.type ?? "command") === "command"
              ? (event.previousSessionEntry ?? event.sessionEntry)
              : event.sessionEntry;
          const sessionId = isRecord(entry) ? entry.sessionId : undefined;
          // The store refuses keys that are not canonical for the agent, so the rows are keyed
          // by the scenario agent's main key (the hook reads by session id).
          const sessionKey = `agent:${agentId}:main`;
          const transcript =
            typeof sessionId === "string" ? scenario.transcripts?.[sessionId.trim()] : undefined;
          if (!transcript || seeded.has(`${sessionId}\n${sessionKey}`)) {
            continue;
          }
          seeded.add(`${sessionId}\n${sessionKey}`);
          const id = String(sessionId).trim();
          await sessionStore.upsertSessionEntry({
            agentId,
            sessionKey,
            storePath,
            entry: { sessionId: id, updatedAt: 1 },
          });
          for (const row of transcript) {
            if (isRecord(row) && row.type === "message" && isRecord(row.message)) {
              await transcriptStore.appendSessionTranscriptMessageByIdentity({
                agentId,
                sessionId: id,
                sessionKey,
                storePath,
                message: row.message,
              });
            }
          }
        }
        for (const event of (scenario.events ?? []) as Array<Record<string, any>>) {
          process.env.TZ = String(event.timezone);
          const hookConfig: Record<string, unknown> = {};
          if ("messages" in event) {
            hookConfig.messages = event.messages;
          }
          if (event.llmSlug) {
            hookConfig.llmSlug = true;
          }
          const previous = isRecord(event.previousSessionEntry)
            ? { ...event.previousSessionEntry }
            : undefined;
          const hookEvent = internalHooks.createInternalHookEvent(
            event.type ?? "command",
            event.action ?? "new",
            event.sessionKey ?? "agent:main:main",
            {
              // v2026.9.6 requires context.agentId (handler.ts requireSessionMemoryAgentId).
              agentId,
              workspaceDir,
              ...(Object.keys(hookConfig).length > 0
                ? { cfg: { hooks: { internal: { entries: { "session-memory": hookConfig } } } } }
                : {}),
              ...(previous ? { previousSessionEntry: previous } : {}),
              ...(isRecord(event.sessionEntry) ? { sessionEntry: { ...event.sessionEntry } } : {}),
              ...(event.reason !== undefined ? { reason: event.reason } : {}),
              ...(event.commandSource ? { commandSource: event.commandSource } : {}),
            },
          );
          hookEvent.timestamp = new Date(Number(event.nowMs));
          setEmbeddedAgentStubReply(event.slugReply ?? null, prompts);
          await handler.default(hookEvent);
          await handler.flushSessionMemoryWritesForTest();
        }
        const memoryDir = path.join(workspaceDir, "memory");
        let memory: Record<string, string> | null = null;
        try {
          const names = (await fs.readdir(memoryDir)).toSorted();
          memory = {};
          for (const name of names) {
            memory[name] = await fs.readFile(path.join(memoryDir, name), "utf-8");
          }
        } catch {
          memory = null;
        }
        scenarios.push({ memory, prompts });
      }
      return { ok: true, operation: payload.operation, result: { scenarios } };
    } finally {
      if (originalTz === undefined) {
        delete process.env.TZ;
      } else {
        process.env.TZ = originalTz;
      }
      await fs.rm(sandbox, { recursive: true, force: true }).catch(() => {});
    }
  }

  const promotionOperations = new Set([
    "recordShortTermRecalls",
    "recordShortTermRecallSequence",
    "recordDreamingPhaseSignals",
    "rankShortTermPromotionCandidates",
    "applyShortTermPromotions",
    "consolidationHistory",
    "applyPromotionScenarios",
    "originsLedger",
    "fileLockProbe",
    "recordRecallScenarios",
    "sessionBackfillLineage",
    "dailyIngestionScenarios",
    "memoryWriteProvenance",
    "sessionArtifactNames",
    "sessionIngestionScenarios",
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
  const testHelpers = await loadMemoryCoreTestHelpers(repoPath);
  await testHelpers.configureMemoryCoreDreamingStateForTests();
  const promotionState = testHelpers.shortTermTestState as PromotionStateModule;
  const promotion = await importFromRepo(
    repoPath,
    "extensions/memory-core/src/short-term-promotion.ts",
  );

  try {
    await seedPromotionStateFromWorkspace(promotionState, payload.workspaceDir);
    const snapshotPromotionFiles = async () => {
      await exportPromotionStateToWorkspace(promotionState, payload.workspaceDir, nowMs);
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

    if (payload.operation === "consolidationHistory") {
      // dreaming-consolidation-artifacts.ts appendConsolidationSummary and
      // appendConsolidationSkippedSummary over the seeded DREAMS.md, one step after another.
      const artifacts = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/dreaming-consolidation-artifacts.ts",
      );
      for (const step of payload.historySteps ?? []) {
        if (step.kind === "skipped") {
          await artifacts.appendConsolidationSkippedSummary({
            workspaceDir: payload.workspaceDir,
            nowMs: Number(step.nowMs),
            reason: String(step.reason),
          });
        } else {
          await artifacts.appendConsolidationSummary({
            workspaceDir: payload.workspaceDir,
            nowMs: Number(step.nowMs),
            result: step.result,
          });
        }
      }
      return { ok: true, operation: payload.operation, files: await snapshotPromotionFiles() };
    }

    if (payload.operation === "fileLockProbe") {
      // The second lock of the deep phase: the real withFileLock with MEMORY_WRITE_LOCK_OPTIONS
      // (fewer retries) on the real lock target of resolveMemoryPromotionLockTarget (not exported,
      // so recomputed here the same way). An optional seeded sidecar stands for another holder.
      const { withFileLock } = await importFromRepo(repoPath, "src/plugin-sdk/file-lock.ts");
      const probe = payload.lockProbe ?? {};
      const workspaceDir = String(payload.workspaceDir);
      const lockDir = path.join(promotionStateDir, "locks");
      await fs.mkdir(lockDir, { recursive: true, mode: 0o700 });
      const canonical = await fs.realpath(workspaceDir).catch(() => path.resolve(workspaceDir));
      const hash = crypto.createHash("sha256").update(canonical).digest("hex");
      const target = path.join(lockDir, `memory-promotion-${hash}`);
      if (isRecord(probe.seed)) {
        const seed = { ...probe.seed } as Record<string, unknown>;
        if (seed.pid === "self") {
          seed.pid = process.pid;
        }
        await fs.writeFile(`${target}.lock`, `${JSON.stringify(seed, null, 2)}\n`, {
          mode: 0o600,
        });
      }
      const retries = Number.isFinite(probe.retries) ? Number(probe.retries) : 3;
      let outcome: Record<string, unknown>;
      try {
        outcome = await withFileLock(
          target,
          {
            retries: { retries, factor: 1.2, minTimeout: 5, maxTimeout: 10 },
            stale: 120_000,
            staleRecovery: "fail-closed",
          },
          async () => {
            const lockPath = `${target}.lock`;
            const raw = await fs.readFile(lockPath, "utf-8");
            const stat = await fs.stat(lockPath);
            const dirStat = await fs.stat(lockDir);
            return {
              ok: true,
              lockName: path.basename(lockPath),
              expectedName: `memory-promotion-${hash}.lock`,
              raw,
              mode: stat.mode & 0o777,
              dirMode: dirStat.mode & 0o777,
              listing: (await fs.readdir(lockDir)).toSorted(),
            };
          },
        );
      } catch (error) {
        outcome = {
          ok: false,
          code: (error as { code?: string }).code ?? null,
          message: String((error as Error).message).replaceAll(target, "<target>"),
        };
      }
      const afterListing = (await fs.readdir(lockDir)).toSorted();
      return {
        ok: true,
        operation: payload.operation,
        result: { ...outcome, afterListing, seeded: isRecord(probe.seed) },
      };
    }

    if (payload.operation === "originsLedger") {
      // The memory-entry origins ledger (memory-entry-origins.ts) over the real per-agent SQLite
      // database of the oracle's state directory, one step after another; every step reports the
      // rows of every agent afterwards.
      const origins = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/memory-entry-origins.ts",
      );
      const sqliteRuntime = await importFromRepo(repoPath, "src/plugin-sdk/sqlite-runtime.ts");
      const agentIds: string[] = payload.agentIds ?? ["main"];
      for (const agentId of agentIds) {
        await fs.mkdir(path.dirname(sqliteRuntime.resolveOpenClawAgentSqlitePath({ agentId })), {
          recursive: true,
        });
      }
      const steps: unknown[] = [];
      let chunkCounter = 0;
      for (const step of payload.originSteps ?? []) {
        let result: unknown = null;
        try {
          if (step.kind === "record") {
            result = origins.recordMemoryEntryOrigins({
              agentId: step.agentId,
              origins: step.origins,
              ...(typeof step.entryKey === "string" ? { entryKey: step.entryKey } : {}),
            });
          } else if (step.kind === "reserve") {
            const rollback = origins.reserveMemoryEntryOrigins({
              agentIds: step.agentIds,
              previousMemory: step.previousMemory,
              operations: step.operations,
            });
            if (step.rollback === true) {
              rollback();
            }
          } else if (step.kind === "prune") {
            await origins.pruneMemoryEntryOrigins({
              workspaceDir: payload.workspaceDir,
              agentIds: step.agentIds,
              entryKeys: step.entryKeys,
              retainedEntryKeys: new Set<string>(step.retainedEntryKeys ?? []),
            });
          } else if (step.kind === "index") {
            const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: step.agentId }).db;
            for (const text of step.texts as string[]) {
              chunkCounter += 1;
              db.prepare(
                "INSERT INTO memory_index_chunks (id, path, source, start_line, end_line, hash, model, text, embedding, updated_at) VALUES (?, 'MEMORY.md', ?, 1, 1, ?, 'm', ?, X'', 0)",
              ).run(`chunk-${chunkCounter}`, step.source ?? "memory", `h${chunkCounter}`, text);
            }
          } else if (step.kind === "preimage") {
            const artifactsModule = await importFromRepo(
              repoPath,
              "extensions/memory-core/src/dreaming-consolidation-artifacts.ts",
            );
            result = [
              ...(await artifactsModule.storeMemoryPreimage({
                workspaceDir: payload.workspaceDir,
                content: step.content,
                nowMs: step.nowMs,
                agentIds: step.agentIds,
                retainedEntryKeys: new Set<string>(step.retainedEntryKeys ?? []),
              })),
            ].toSorted();
          } else if (step.kind === "tombstone") {
            // recordMemorySessionTombstonesInDatabase on the agent's real database (the revision
            // fence bump included).
            const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: step.agentId }).db;
            result = origins.recordMemorySessionTombstonesInDatabase(db, {
              agentId: step.agentId,
              sessionIds: step.sessionIds,
              ...(typeof step.reason === "string" ? { reason: step.reason } : {}),
              ...(Number.isFinite(step.createdAt) ? { createdAt: Number(step.createdAt) } : {}),
            });
          } else if (step.kind === "tombstones") {
            result = origins.listMemorySessionTombstones({
              agentId: step.agentId,
              ...(Array.isArray(step.sessionIds) ? { sessionIds: step.sessionIds } : {}),
            });
          } else if (step.kind === "list") {
            result = origins.listMemoryEntryOrigins({
              agentId: step.agentId,
              ...(Array.isArray(step.sessionIds) ? { sessionIds: step.sessionIds } : {}),
              ...(Array.isArray(step.entryKeys) ? { entryKeys: step.entryKeys } : {}),
            });
          }
        } catch (error) {
          result = { error: String((error as Error).message) };
        }
        steps.push({
          result,
          state: Object.fromEntries(
            agentIds.map((agentId) => [agentId, origins.listMemoryEntryOrigins({ agentId })]),
          ),
          tombstones: Object.fromEntries(
            agentIds.map((agentId) => [agentId, origins.listMemorySessionTombstones({ agentId })]),
          ),
          // The index revision fence counter (memory_index_state) of every agent database.
          revisions: Object.fromEntries(
            agentIds.map((agentId) => [
              agentId,
              (
                sqliteRuntime
                  .openOpenClawAgentDatabase({ agentId })
                  .db.prepare("SELECT revision FROM memory_index_state WHERE id = 1")
                  .get() as { revision: number } | undefined
              )?.revision ?? null,
            ]),
          ),
        });
      }
      return { ok: true, operation: payload.operation, result: { steps } };
    }

    if (payload.operation === "recordRecallScenarios") {
      // recordShortTermRecalls with session origins over many seeded workspaces in one process:
      // each scenario seeds tombstones, replays its recalls and reports the recall store, the
      // origins ledger and the tombstones of its own agents (agent ids are unique per scenario).
      const origins = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/memory-entry-origins.ts",
      );
      const sqliteRuntime = await importFromRepo(repoPath, "src/plugin-sdk/sqlite-runtime.ts");
      const scenarioResults: unknown[] = [];
      for (const scenario of payload.recallScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        const scenarioNowMs = Number.isFinite(scenario.nowMs) ? Number(scenario.nowMs) : nowMs;
        await seedPromotionStateFromWorkspace(promotionState, workspaceDir);
        const agentIds: string[] = scenario.agentIds ?? [];
        for (const agentId of agentIds) {
          await fs.mkdir(path.dirname(sqliteRuntime.resolveOpenClawAgentSqlitePath({ agentId })), {
            recursive: true,
          });
        }
        for (const seed of scenario.seedTombstones ?? []) {
          const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: seed.agentId }).db;
          origins.recordMemorySessionTombstonesInDatabase(db, {
            agentId: seed.agentId,
            sessionIds: seed.sessionIds,
            createdAt: 1,
          });
        }
        let error: string | null = null;
        try {
          for (const recall of scenario.recalls ?? []) {
            await promotion.recordShortTermRecalls({
              workspaceDir,
              query: recall.query ?? "",
              results: recall.results ?? [],
              nowMs: Number.isFinite(recall.nowMs) ? Number(recall.nowMs) : scenarioNowMs,
              timezone: recall.timezone ?? timezone,
              ...(typeof recall.signalType === "string" ? { signalType: recall.signalType } : {}),
              ...(recall.dedupeByQueryPerDay === true ? { dedupeByQueryPerDay: true } : {}),
              ...(typeof recall.dayBucket === "string" ? { dayBucket: recall.dayBucket } : {}),
            });
          }
        } catch (caught) {
          error = String((caught as Error).message);
        }
        await exportPromotionStateToWorkspace(promotionState, workspaceDir, scenarioNowMs);
        scenarioResults.push({
          name: scenario.name,
          error,
          files: await snapshotFiles(workspaceDir),
          // Every host event of the workspace, diagnostic variants (memory.recall.skipped) included.
          events: await (
            await importFromRepo(repoPath, "src/memory-host-sdk/events.ts")
          ).readMemoryHostEventRecords({ workspaceDir }),
          origins: Object.fromEntries(
            agentIds.map((agentId) => [agentId, origins.listMemoryEntryOrigins({ agentId })]),
          ),
          tombstones: Object.fromEntries(
            agentIds.map((agentId) => [agentId, origins.listMemorySessionTombstones({ agentId })]),
          ),
        });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: scenarioResults } };
    }

    if (payload.operation === "sessionBackfillLineage") {
      // session-backfill.ts: buildSessionBackfillDiaryEntries and coalesceBackfillClaims are not
      // exported, so the real source is loaded with one extra export line (from a copy beside it,
      // removed again) and the grounded-signal half of applySessionBackfillDays runs the exported
      // recordGroundedShortTermCandidates on the coalesced claims. The origins ledger and the
      // recall store are reported per scenario (agent ids are unique per scenario).
      const sourcePath = path.join(repoPath, "extensions/memory-core/src/session-backfill.ts");
      const patchedPath = path.join(
        repoPath,
        `extensions/memory-core/src/session-backfill.oracle-${process.pid}.ts`,
      );
      const original = await fs.readFile(sourcePath, "utf-8");
      await fs.writeFile(
        patchedPath,
        `${original}\nexport { buildSessionBackfillDiaryEntries, coalesceBackfillClaims };\n`,
      );
      let backfill: Record<string, any>;
      try {
        backfill = await import(pathToFileURL(patchedPath).href);
      } finally {
        await fs.unlink(patchedPath).catch(() => {});
      }
      const origins = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/memory-entry-origins.ts",
      );
      const sqliteRuntime = await importFromRepo(repoPath, "src/plugin-sdk/sqlite-runtime.ts");
      const scenarioResults: unknown[] = [];
      for (const scenario of payload.backfillScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        const scenarioNowMs = Number.isFinite(scenario.nowMs) ? Number(scenario.nowMs) : nowMs;
        await seedPromotionStateFromWorkspace(promotionState, workspaceDir);
        const agentIds: string[] = scenario.agentIds ?? [];
        for (const agentId of agentIds) {
          await fs.mkdir(path.dirname(sqliteRuntime.resolveOpenClawAgentSqlitePath({ agentId })), {
            recursive: true,
          });
        }
        for (const seed of scenario.seedTombstones ?? []) {
          const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: seed.agentId }).db;
          origins.recordMemorySessionTombstonesInDatabase(db, {
            agentId: seed.agentId,
            sessionIds: seed.sessionIds,
            createdAt: 1,
          });
        }
        let error: string | null = null;
        let diary: unknown = null;
        const coalesced: unknown[] = [];
        try {
          if (Array.isArray(scenario.days)) {
            diary = backfill.buildSessionBackfillDiaryEntries({
              agentId: scenario.agentId,
              days: scenario.days,
            });
          }
          for (const day of scenario.recordDays ?? []) {
            const grounded = backfill.coalesceBackfillClaims(day.results);
            coalesced.push(grounded);
            if (grounded.length === 0) {
              continue;
            }
            await promotion.recordGroundedShortTermCandidates({
              workspaceDir,
              query: `__dreaming_session_backfill__:${day.day}`,
              items: grounded.map((result: Record<string, any>) => ({
                path: result.path,
                startLine: result.startLine,
                endLine: result.endLine,
                snippet: result.snippet,
                score: 0.58,
                dayBucket: day.day,
                provenance: result.provenance,
                sessionOrigin: result.sessionOrigin,
              })),
              dedupeByQueryPerDay: true,
              nowMs: scenarioNowMs,
              timezone,
            });
          }
        } catch (caught) {
          error = String((caught as Error).message);
        }
        await exportPromotionStateToWorkspace(promotionState, workspaceDir, scenarioNowMs);
        scenarioResults.push({
          name: scenario.name,
          error,
          diary,
          coalesced,
          files: await snapshotFiles(workspaceDir),
          origins: Object.fromEntries(
            agentIds.map((agentId) => [agentId, origins.listMemoryEntryOrigins({ agentId })]),
          ),
        });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: scenarioResults } };
    }

    if (payload.operation === "dailyIngestionScenarios") {
      // dreaming-phases.ts daily ingestion: buildDailyIngestionResults, ingestDailyMemorySignals and
      // seedHistoricalDailyMemorySignals are not exported, so the real source is loaded with one
      // extra export line. A scenario is a list of steps (write/remove files with a fixed mtime,
      // trust records, build, ingest, seed); after every step the recall store and the daily
      // ingestion checkpoint are reported.
      const phases = await importPatched(
        repoPath,
        "extensions/memory-core/src/dreaming-phases.ts",
        "export { buildDailyIngestionResults, ingestDailyMemorySignals };",
      );
      const dreamingStateModule = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/dreaming-state.ts",
      );
      const artifactProvenance = await importFromRepo(
        repoPath,
        "src/memory/memory-artifact-provenance.ts",
      );
      const hostEvents = await importFromRepo(repoPath, "src/memory-host-sdk/events.ts");
      const scenarioResults: unknown[] = [];
      for (const scenario of payload.ingestScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        const scenarioTimezone = scenario.timezone ?? timezone;
        await seedPromotionStateFromWorkspace(promotionState, workspaceDir);
        const stepResults: unknown[] = [];
        for (const step of scenario.steps ?? []) {
          let result: unknown = null;
          let error: string | null = null;
          const stepNowMs = Number.isFinite(step.nowMs) ? Number(step.nowMs) : nowMs;
          try {
            if (step.kind === "write") {
              const target = path.join(workspaceDir, step.path);
              await fs.mkdir(path.dirname(target), { recursive: true });
              await fs.writeFile(target, step.content, "utf-8");
              if (Number.isFinite(step.mtimeMs)) {
                await fs.utimes(target, Number(step.mtimeMs) / 1000, Number(step.mtimeMs) / 1000);
              }
            } else if (step.kind === "remove") {
              await fs.rm(path.join(workspaceDir, step.path), { force: true });
            } else if (step.kind === "provenance") {
              const rollback = await artifactProvenance.recordMemoryArtifactWriteProvenance({
                workspaceDir,
                relativePath: step.relativePath,
                contentBefore: step.contentBefore ?? "",
                contentAfter: step.contentAfter ?? "",
                originClass: step.originClass,
                observedAt: step.observedAt,
              });
              if (step.rollback === true && rollback) {
                await rollback();
              }
            } else if (step.kind === "build") {
              result = phases.buildDailyIngestionResults({
                raw: step.raw,
                path: step.path,
                limit: step.limit,
                defaultObservedAt: step.defaultObservedAt,
                ...(step.recorded ? { recorded: step.recorded } : {}),
              });
            } else if (step.kind === "ingest") {
              await phases.ingestDailyMemorySignals({
                workspaceDir,
                lookbackDays: step.lookbackDays,
                limit: step.limit,
                nowMs: stepNowMs,
                timezone: scenarioTimezone,
              });
            } else if (step.kind === "seed") {
              result = await phases.seedHistoricalDailyMemorySignals({
                workspaceDir,
                filePaths: (step.filePaths as string[]).map((entry) =>
                  path.isAbsolute(entry) ? entry : path.join(workspaceDir, entry),
                ),
                limit: step.limit,
                nowMs: stepNowMs,
                timezone: scenarioTimezone,
              });
            }
          } catch (caught) {
            error = String((caught as Error).message);
          }
          const recallStore = (await promotionState.readRecallStore(
            workspaceDir,
            new Date(stepNowMs).toISOString(),
          )) as { entries?: Record<string, unknown> };
          const dailyEntries = await dreamingStateModule.readMemoryCoreWorkspaceEntries({
            namespace: "dreaming-daily-ingestion",
            workspaceDir,
          });
          stepResults.push({
            result,
            error,
            recall: withSortedEntries(recallStore).entries,
            daily: Object.fromEntries(
              (dailyEntries as Array<{ key: string; value: unknown }>)
                .toSorted((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
                .map((entry) => [entry.key, entry.value]),
            ),
          });
        }
        scenarioResults.push({
          name: scenario.name,
          steps: stepResults,
          events: await hostEvents.readMemoryHostEventRecords({ workspaceDir }),
        });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: scenarioResults } };
    }

    if (payload.operation === "sessionIngestionScenarios") {
      // session-ingestion.ts / dreaming-phases.ts session ingestion. Two scenario kinds:
      // - "scan": scanSessionIngestionSource over JSONL files (the file branch of buildSessionEntry),
      //   step after step with the checkpoint and seen hashes chained like the sweep does;
      // - "sweep": the real ingestSessionTranscriptSignals (dreaming-phases.ts with one extra export
      //   line) over sessions seeded in the agent's SQLite session store, tombstones, an admission
      //   policy and the real corpus enumeration; the recall store, the session checkpoint, the
      //   session corpus files, the origins ledger and the host events are reported after each step.
      const phases = await importPatched(
        repoPath,
        "extensions/memory-core/src/dreaming-phases.ts",
        "export { ingestSessionTranscriptSignals };",
      );
      const sessionIngestion = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/session-ingestion.ts",
      );
      const origins = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/memory-entry-origins.ts",
      );
      const sqliteRuntime = await importFromRepo(repoPath, "src/plugin-sdk/sqlite-runtime.ts");
      const hostEvents = await importFromRepo(repoPath, "src/memory-host-sdk/events.ts");
      const sessionsSdk = await importFromRepo(
        repoPath,
        "src/plugin-sdk/memory-core-host-engine-sessions.ts",
      );
      const paths = await importFromRepo(repoPath, "src/config/sessions/paths.ts");
      const sessionStore = await importFromRepo(repoPath, "src/plugin-sdk/session-store-runtime.ts");
      const transcriptStore = await importFromRepo(
        repoPath,
        "src/plugin-sdk/session-transcript-runtime.ts",
      );
      const scenarioResults: unknown[] = [];
      for (const scenario of payload.sessionScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        const scenarioTimezone = scenario.timezone ?? timezone;
        const stepResults: unknown[] = [];
        if (scenario.kind === "scan") {
          let chainPrevious: Record<string, any> | undefined;
          const chainSeen: Record<string, string[]> = {};
          for (const step of scenario.steps ?? []) {
            let result: unknown = null;
            let error: string | null = null;
            try {
              const target = path.join(
                workspaceDir,
                "agents",
                step.agentId,
                "sessions",
                `${step.sessionId}.jsonl`,
              );
              if (step.kind === "write") {
                await fs.mkdir(path.dirname(target), { recursive: true });
                await fs.writeFile(
                  target,
                  (step.records as unknown[]).map((record) => JSON.stringify(record)).join("\n") +
                    (step.records.length > 0 ? "\n" : ""),
                  "utf-8",
                );
                if (Number.isFinite(step.mtimeMs)) {
                  await fs.utimes(target, Number(step.mtimeMs) / 1000, Number(step.mtimeMs) / 1000);
                }
              } else if (step.kind === "remove") {
                await fs.rm(target, { force: true });
              } else if (step.kind === "scan") {
                const source = step.foreign
                  ? sessionIngestion.foreignSessionIngestionSource(step.agentId, target)
                  : sessionIngestion.sessionIngestionSourceFromCorpus({
                      agentId: step.agentId,
                      sessionId: step.sessionId,
                      sessionFile: target,
                      transcriptSource: "file",
                      artifactKind: "active-session",
                      sessionKind: step.sessionKind ?? "interactive",
                      ...(step.sessionKey ? { sessionKey: step.sessionKey } : {}),
                      ...(step.generatedByCronRun ? { generatedByCronRun: true } : {}),
                      ...(step.generatedByDreamingNarrative
                        ? { generatedByDreamingNarrative: true }
                        : {}),
                    });
                if (!source) {
                  stepResults.push({ result: null, error: null });
                  continue;
                }
                const blocked = new Set<string>(step.blockDays ?? []);
                const included = step.includeDays ? new Set<string>(step.includeDays) : undefined;
                const scan = await sessionIngestion.scanSessionIngestionSource({
                  source,
                  previous: step.chain ? chainPrevious : step.previous,
                  seenMessages: step.chain ? chainSeen : (step.seen ?? {}),
                  timezone: scenarioTimezone,
                  ...(Number.isFinite(step.maxCandidates)
                    ? { maxCandidates: step.maxCandidates }
                    : {}),
                  ...(step.verifyContent === true ? { verifyContent: true } : {}),
                  ...(Array.isArray(step.acceptOrigins)
                    ? {
                        acceptProvenance: (provenance: { originClass: string }) =>
                          (step.acceptOrigins as string[]).includes(provenance.originClass),
                      }
                    : {}),
                  classifyDay: (day: string) =>
                    blocked.has(day) ? "block" : !included || included.has(day) ? "include" : "skip",
                });
                if (step.chain) {
                  if (scan.fileState) {
                    chainPrevious = scan.fileState;
                  }
                  if (scan.candidates.length > 0) {
                    chainSeen[source.scope] = sessionIngestion.mergeTrackedMessageHashes(
                      chainSeen[source.scope] ?? [],
                      scan.candidates.map((candidate: { hash: string }) => candidate.hash),
                    );
                  }
                }
                result = { scan, scope: source.scope, stateKey: source.stateKey };
              }
            } catch (caught) {
              error = String((caught as Error).message);
            }
            stepResults.push({ result, error });
          }
        } else {
          const agentIds: string[] = scenario.agentIds ?? [];
          const cfg = {
            agents: {
              list: agentIds.map((agentId) => ({ id: agentId, workspace: workspaceDir })),
            },
          };
          const policyConfig = scenario.pluginConfig;
          await seedPromotionStateFromWorkspace(promotionState, workspaceDir);
          for (const agentId of agentIds) {
            await fs.mkdir(path.dirname(sqliteRuntime.resolveOpenClawAgentSqlitePath({ agentId })), {
              recursive: true,
            });
          }
          for (const step of scenario.steps ?? []) {
            let result: unknown = null;
            let error: string | null = null;
            const stepNowMs = Number.isFinite(step.nowMs) ? Number(step.nowMs) : nowMs;
            try {
              if (step.kind === "session" || step.kind === "append") {
                const sessionsDir: string = paths.resolveSessionTranscriptsDirForAgent(step.agentId);
                const storePath = path.join(sessionsDir, "sessions.json");
                await fs.mkdir(sessionsDir, { recursive: true });
                const sessionKey = step.sessionKey ?? `agent:${step.agentId}:${step.sessionId}`;
                if (step.kind === "session") {
                  await sessionStore.upsertSessionEntry({
                    agentId: step.agentId,
                    sessionKey,
                    storePath,
                    entry: { sessionId: step.sessionId, updatedAt: stepNowMs, ...(step.entry ?? {}) },
                  });
                }
                for (const message of step.messages ?? []) {
                  await transcriptStore.appendSessionTranscriptMessageByIdentity({
                    agentId: step.agentId,
                    sessionId: step.sessionId,
                    sessionKey,
                    storePath,
                    message,
                  });
                }
              } else if (step.kind === "tombstone") {
                const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: step.agentId }).db;
                origins.recordMemorySessionTombstonesInDatabase(db, {
                  agentId: step.agentId,
                  sessionIds: step.sessionIds,
                  createdAt: 1,
                });
              } else if (step.kind === "ingest") {
                await phases.ingestSessionTranscriptSignals({
                  workspaceDir,
                  cfg,
                  lookbackDays: step.lookbackDays,
                  nowMs: stepNowMs,
                  timezone: scenarioTimezone,
                  ...(policyConfig
                    ? { admissionPolicy: sessionIngestion.resolveAdmissionPolicy(policyConfig) }
                    : {}),
                });
              }
            } catch (caught) {
              error = String((caught as Error).message);
            }
            await exportPromotionStateToWorkspace(promotionState, workspaceDir, stepNowMs);
            const sessionState = await sessionIngestion.readSessionIngestionState(workspaceDir);
            const corpusDir = path.join(workspaceDir, "memory", ".dreams", "session-corpus");
            const corpus: Record<string, string> = {};
            for (const name of (await fs.readdir(corpusDir).catch(() => [] as string[])).toSorted()) {
              corpus[name] = await fs.readFile(path.join(corpusDir, name), "utf-8");
            }
            const corpusEntries: Array<Record<string, unknown>> = [];
            for (const agentId of agentIds) {
              corpusEntries.push(
                ...(await sessionsSdk.listSessionTranscriptCorpusEntriesForAgent(agentId, {
                  includeRetainedSqlite: true,
                })),
              );
            }
            stepResults.push({
              result,
              error,
              state: sessionState,
              corpus,
              corpusEntries: corpusEntries.map((entry) => ({
                agentId: entry.agentId,
                sessionId: entry.sessionId,
                sessionKey: entry.sessionKey ?? null,
                sessionKind: entry.sessionKind ?? null,
                artifactKind: entry.artifactKind ?? null,
                transcriptSource: entry.transcriptSource ?? null,
                generatedByDreamingNarrative: entry.generatedByDreamingNarrative === true,
                generatedByCronRun: entry.generatedByCronRun === true,
              })),
              recall: withSortedEntries(
                (await promotionState.readRecallStore(
                  workspaceDir,
                  new Date(stepNowMs).toISOString(),
                )) as Record<string, unknown>,
              ).entries,
              origins: Object.fromEntries(
                agentIds.map((agentId) => [agentId, origins.listMemoryEntryOrigins({ agentId })]),
              ),
            });
          }
        }
        scenarioResults.push({
          name: scenario.name,
          steps: stepResults,
          events:
            scenario.kind === "scan"
              ? []
              : await hostEvents.readMemoryHostEventRecords({ workspaceDir }),
        });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: scenarioResults } };
    }

    if (payload.operation === "sessionArtifactNames") {
      // src/config/sessions/artifacts.ts filename classifiers over a list of names.
      const artifacts = await importFromRepo(repoPath, "src/config/sessions/artifacts.ts");
      return {
        ok: true,
        operation: payload.operation,
        result: {
          names: (payload.texts ?? []).map((name) => ({
            name,
            primary: artifacts.isPrimarySessionTranscriptFileName(String(name)),
            archive: artifacts.isSessionArchiveArtifactName(String(name)),
            checkpoint: artifacts.isCompactionCheckpointTranscriptFileName(String(name)),
            sessionId: artifacts.parseUsageCountedSessionIdFromFileName(String(name)),
          })),
        },
      };
    }

    if (payload.operation === "memoryWriteProvenance") {
      // src/agents/memory-write-provenance.ts: the observer the flush's write tool and the
      // session-memory hook attach to their file writes, over the real trust store. A step writes
      // (or deletes) one file through the observer; the trust records of the workspace are
      // reported after every step.
      const observerModule = await importFromRepo(
        repoPath,
        "src/agents/memory-write-provenance.ts",
      );
      const artifactProvenance = await importFromRepo(
        repoPath,
        "src/memory/memory-artifact-provenance.ts",
      );
      const scenarioResults: unknown[] = [];
      for (const scenario of payload.provenanceScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        await fs.mkdir(workspaceDir, { recursive: true });
        const stepResults: unknown[] = [];
        for (const step of scenario.steps ?? []) {
          let result: unknown = null;
          let error: string | null = null;
          try {
            const target = path.isAbsolute(step.path) ? step.path : path.join(workspaceDir, step.path);
            if (step.kind === "symlink") {
              await fs.mkdir(path.dirname(target), { recursive: true });
              await fs.symlink(
                path.isAbsolute(step.target) ? step.target : path.join(workspaceDir, step.target),
                target,
              );
            } else if (step.kind === "mkdir") {
              await fs.mkdir(target, { recursive: true });
            } else {
              const observer = observerModule.createMemoryWriteProvenanceObserver({
                mutationRoot: workspaceDir,
                workspaceDir,
                resolveOriginClass: () => step.originClass ?? "agent",
                ...(typeof step.sessionId === "string" ? { sessionId: step.sessionId } : {}),
                ...(typeof step.sessionKey === "string" ? { sessionKey: step.sessionKey } : {}),
                now: () => Number(step.observedAt ?? 0),
              });
              if (step.kind === "classifies") {
                result = await observer.classifies(target);
              } else if (step.kind === "write") {
                await fs.mkdir(path.dirname(target), { recursive: true });
                await observer.write({
                  absolutePath: target,
                  contentBefore: step.contentBefore ?? "",
                  contentAfter: step.contentAfter ?? "",
                  commit: async () => {
                    if (step.failCommit === true) {
                      throw new Error("commit failed");
                    }
                    await fs.writeFile(target, step.contentAfter ?? "", "utf-8");
                  },
                });
              } else if (step.kind === "delete") {
                await fs.rm(target, { force: true });
                await observer.clearAfterDelete(target, step.contentBefore ?? "");
              }
            }
          } catch (caught) {
            error = String((caught as Error).message);
          }
          stepResults.push({
            result,
            error,
            records: await artifactProvenance.listMemoryArtifactProvenance({ workspaceDir }),
          });
        }
        scenarioResults.push({ name: scenario.name, steps: stepResults });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: scenarioResults } };
    }

    if (payload.operation === "applyPromotionScenarios") {
      // The apply half of the deep phase over many seeded workspaces in one process (an oracle
      // start costs seconds): rejectedCandidates, the memory.promotion.applied host events, the
      // origins ledger, the lock/write order and the consolidation artifacts.
      const origins = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/memory-entry-origins.ts",
      );
      const sqliteRuntime = await importFromRepo(repoPath, "src/plugin-sdk/sqlite-runtime.ts");
      const hostEvents = await importFromRepo(repoPath, "src/memory-host-sdk/events.ts");
      const artifacts = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/dreaming-consolidation-artifacts.ts",
      );
      const artifactProvenance = await importFromRepo(
        repoPath,
        "src/memory/memory-artifact-provenance.ts",
      );
      const testAgentId = "memory-core-test";
      const results: unknown[] = [];
      for (const scenario of payload.promotionScenarios ?? []) {
        const workspaceDir = String(scenario.workspaceDir);
        const scenarioNowMs = Number.isFinite(scenario.nowMs) ? Number(scenario.nowMs) : nowMs;
        await seedPromotionStateFromWorkspace(promotionState, workspaceDir);
        const originAgents: string[] = [testAgentId, ...(scenario.workspaceAgentIds ?? [])];
        for (const agentId of originAgents) {
          await fs.mkdir(path.dirname(sqliteRuntime.resolveOpenClawAgentSqlitePath({ agentId })), {
            recursive: true,
          });
          const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId }).db;
          try {
            db.exec("DELETE FROM memory_entry_origins");
          } catch {
            // The table is created lazily by the first record.
          }
          try {
            db.exec("DELETE FROM memory_index_chunks");
          } catch {
            // Missing chunk table.
          }
        }
        for (const seed of scenario.seedOrigins ?? []) {
          origins.recordMemoryEntryOrigins({ agentId: seed.agentId, origins: [seed] });
        }
        // Daily-file trust records (the flush's quarantine), written by the real writer one after
        // another; an optional `rollback` undoes the step the way a failed flush would.
        for (const seed of scenario.seedArtifactProvenance ?? []) {
          const rollback = await artifactProvenance.recordMemoryArtifactWriteProvenance({
            workspaceDir,
            relativePath: seed.relativePath,
            contentBefore: seed.contentBefore ?? "",
            contentAfter: seed.contentAfter ?? "",
            originClass: seed.originClass,
            observedAt: seed.observedAt,
            ...(typeof seed.sessionId === "string" ? { sessionId: seed.sessionId } : {}),
            ...(typeof seed.sessionKey === "string" ? { sessionKey: seed.sessionKey } : {}),
          });
          if (seed.rollback === true && rollback) {
            await rollback();
          }
        }
        for (const seed of scenario.seedIndexChunks ?? []) {
          const db = sqliteRuntime.openOpenClawAgentDatabase({ agentId: seed.agentId }).db;
          db.prepare(
            "INSERT INTO memory_index_chunks (id, path, source, start_line, end_line, hash, model, text, embedding, updated_at) VALUES (?, 'MEMORY.md', 'memory', 1, 1, ?, 'm', ?, X'', 0)",
          ).run(`chunk-${crypto.randomUUID()}`, crypto.randomUUID(), seed.text);
        }

        // Order of the lock sidecar, MEMORY.md and DREAMS.md writes, taken from the fs calls.
        const timeline: string[] = [];
        const fsPromises = (await import("node:fs/promises")).default as unknown as Record<
          string,
          (...args: unknown[]) => Promise<unknown>
        >;
        const originals: Record<string, (...args: unknown[]) => Promise<unknown>> = {};
        // The sidecar is created natively (not through fs.promises), so its appearance is noticed
        // at the next fs call that passes through the hook.
        const canonicalWorkspace = await fs.realpath(workspaceDir);
        const lockSidecar = path.join(
          promotionStateDir,
          "locks",
          `memory-promotion-${crypto.createHash("sha256").update(canonicalWorkspace).digest("hex")}.lock`,
        );
        let lockSeen = false;
        const label = (op: string, args: unknown[]): string | null => {
          const target = String(op === "rename" ? args[1] : args[0]);
          if (!lockSeen && fsSync.existsSync(lockSidecar)) {
            lockSeen = true;
            timeline.push("lock:acquire");
          }
          const base = path.basename(target);
          if (base.startsWith("memory-promotion-") && base.endsWith(".lock")) {
            return op === "unlink" || op === "rm" ? "lock:release" : null;
          }
          if (op !== "rename" && op !== "writeFile") {
            return null;
          }
          if (base === "MEMORY.md") {
            return "memory:write";
          }
          return base === "DREAMS.md" || base === "dreams.md" ? "dreams:write" : null;
        };
        for (const op of ["open", "rename", "writeFile", "unlink", "rm"]) {
          originals[op] = fsPromises[op];
          fsPromises[op] = async function (this: unknown, ...args: unknown[]) {
            const entry = label(op, args);
            if (entry) {
              timeline.push(entry);
            }
            return await originals[op].apply(this, args);
          };
        }

        const consolidationConfig = isRecord(scenario.consolidation)
          ? (scenario.consolidation as Record<string, any>)
          : undefined;
        const replies: unknown[] = Array.isArray(consolidationConfig?.replies)
          ? consolidationConfig.replies
          : [];
        const calls: Array<Record<string, unknown>> = [];
        const warnings: string[] = [];
        const infos: string[] = [];
        const subagent = {
          complete: async (options: Record<string, unknown>) => {
            calls.push({ ...options });
            for (const mutation of consolidationConfig?.mutateDuringCall ?? []) {
              const target = path.join(workspaceDir, String(mutation.path));
              if (mutation.append === true) {
                await originals.writeFile.call(fsPromises, target, mutation.content, { flag: "a" });
              } else {
                await originals.writeFile.call(fsPromises, target, mutation.content);
              }
            }
            const reply = replies[calls.length - 1] as unknown;
            if (isRecord(reply) && typeof reply.throw === "string") {
              throw new Error(reply.throw);
            }
            return { text: reply };
          },
        };
        const applyParams = {
          workspaceDir,
          nowMs: scenarioNowMs,
          timezone: scenario.timezone ?? timezone,
          candidates: scenario.candidates ?? [],
          ...(scenario.limit !== undefined ? { limit: scenario.limit } : {}),
          ...(scenario.minScore !== undefined ? { minScore: scenario.minScore } : {}),
          ...(scenario.minRecallCount !== undefined
            ? { minRecallCount: scenario.minRecallCount }
            : {}),
          ...(scenario.minUniqueQueries !== undefined
            ? { minUniqueQueries: scenario.minUniqueQueries }
            : {}),
          ...(scenario.maxAgeDays !== undefined ? { maxAgeDays: scenario.maxAgeDays } : {}),
          ...(scenario.memoryFileMaxChars !== undefined
            ? { memoryFileMaxChars: scenario.memoryFileMaxChars }
            : {}),
          ...(scenario.maxPriorEntryLossFraction !== undefined
            ? { maxPriorEntryLossFraction: scenario.maxPriorEntryLossFraction }
            : {}),
          ...(scenario.maxPromotedSnippetTokens !== undefined
            ? { maxPromotedSnippetTokens: scenario.maxPromotedSnippetTokens }
            : {}),
          ...(Array.isArray(scenario.workspaceAgentIds)
            ? { workspaceAgentIds: scenario.workspaceAgentIds }
            : {}),
        };
        let applied: unknown;
        let error: string | null = null;
        try {
          if (consolidationConfig || scenario.agent === true) {
            applied = await testHelpers.applyShortTermPromotionsForTests({
              ...applyParams,
              ...(consolidationConfig
                ? {
                    consolidation: {
                      ...(consolidationConfig.noSubagent === true ? {} : { subagent }),
                      ...(typeof consolidationConfig.model === "string"
                        ? { model: consolidationConfig.model }
                        : {}),
                      logger: {
                        info: (message: string) => infos.push(message),
                        warn: (message: string) => warnings.push(message),
                      },
                    },
                  }
                : {}),
            });
          } else {
            applied = await promotion.applyShortTermPromotions(applyParams);
          }
        } catch (caught) {
          error = String((caught as Error).message);
        } finally {
          for (const op of Object.keys(originals)) {
            fsPromises[op] = originals[op];
          }
        }
        await exportPromotionStateToWorkspace(promotionState, workspaceDir, scenarioNowMs);
        const files = await snapshotFiles(workspaceDir);
        const memoryHostEvents = await hostEvents.readMemoryHostEvents({ workspaceDir });
        const originRows = Object.fromEntries(
          originAgents.map((agentId) => [agentId, origins.listMemoryEntryOrigins({ agentId })]),
        );
        const preimages = (await artifacts.readMemoryPreimages(workspaceDir)).map(
          (entry: { value: unknown }) => entry.value,
        );
        results.push({
          name: scenario.name,
          error,
          applied,
          files,
          artifactProvenance: await artifactProvenance.listMemoryArtifactProvenance({
            workspaceDir,
          }),
          events: memoryHostEvents,
          origins: originRows,
          preimages,
          calls,
          warnings,
          infos,
          timeline,
        });
      }
      return { ok: true, operation: payload.operation, result: { scenarios: results } };
    }

    const policy = await resolvePromotionPolicy(repoPath, payload);
    if (isRecord(payload.consolidation)) {
      // The deep phase with consolidation: applyShortTermPromotionsForTests (the test agent id
      // enables the consolidation path) with a stubbed subagent (replies: one entry per call, a
      // string, {throw} or {raw}); preimages come back from the plugin state store.
      const consolidationConfig = payload.consolidation as Record<string, unknown>;
      const replies: unknown[] = Array.isArray(consolidationConfig.replies)
        ? consolidationConfig.replies
        : [];
      const calls: Array<Record<string, unknown>> = [];
      const warnings: string[] = [];
      const infos: string[] = [];
      const subagent = {
        complete: async (options: Record<string, unknown>) => {
          calls.push({ ...options });
          if (typeof consolidationConfig.mutateMemoryDuringCall === "string") {
            await fs.appendFile(
              path.join(String(payload.workspaceDir), "MEMORY.md"),
              consolidationConfig.mutateMemoryDuringCall,
            );
          }
          const reply = replies[calls.length - 1] as unknown;
          if (isRecord(reply) && typeof reply.throw === "string") {
            throw new Error(reply.throw);
          }
          if (isRecord(reply) && "raw" in reply) {
            return reply.raw;
          }
          return { text: reply };
        },
      };
      const artifacts = await importFromRepo(
        repoPath,
        "extensions/memory-core/src/dreaming-consolidation-artifacts.ts",
      );
      const result = await testHelpers.applyShortTermPromotionsForTests({
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
        ...(typeof payload.maxPriorEntryLossFraction === "number"
          ? { maxPriorEntryLossFraction: payload.maxPriorEntryLossFraction }
          : {}),
        consolidation: {
          ...(consolidationConfig.noSubagent === true ? {} : { subagent }),
          ...(typeof consolidationConfig.model === "string"
            ? { model: consolidationConfig.model }
            : {}),
          logger: {
            info: (message: string) => infos.push(message),
            warn: (message: string) => warnings.push(message),
          },
        },
      });
      const preimages = (await artifacts.readMemoryPreimages(payload.workspaceDir)).map(
        (entry: { value: unknown }) => entry.value,
      );
      return {
        ok: true,
        operation: payload.operation,
        result: { ...result, calls, warnings, infos, preimages },
        files: await snapshotPromotionFiles(),
      };
    }
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
      ...(typeof payload.maxPriorEntryLossFraction === "number"
        ? { maxPriorEntryLossFraction: payload.maxPriorEntryLossFraction }
        : {}),
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

// v2026.9.6 keeps SQLite handles, workers and timers alive after an operation, so the runner
// exits explicitly once its JSON line is flushed instead of waiting for an empty event loop.
function writeAndExit(body: string, exitCode: number): void {
  process.stdout.write(body, () => process.exit(exitCode));
}

main()
  .then((result) => {
    writeAndExit(JSON.stringify(result), 0);
  })
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    writeAndExit(JSON.stringify({ ok: false, error: { code: "runner-error", message } }), 1);
  });
