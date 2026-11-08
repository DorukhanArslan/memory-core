// Original public transcript source owners over literal files or real SQLite.
// This fixture supplies bytes/events and observes complete source reads; it
// implements neither transcript filtering nor branch/reset projection.
import fs from "node:fs/promises";
import syncFs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

function publicError(error) {
  return { name: error?.name ?? typeof error, message: error?.message ?? String(error),
    ...Object.fromEntries(Object.getOwnPropertyNames(error ?? {}).filter((key) =>
      !["name", "message", "stack"].includes(key)).map((key) => [key,
      error[key] instanceof Error ? publicError(error[key]) : error[key]])) };
}

export async function runTranscriptBoundaryRuntime(input, runtimeConfig) {
  if (input.kind !== "boundary" || !["jsonl", "sqlite"].includes(input.source) ||
      !Number.isFinite(input.nowMs) || !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") ||
      !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "")) {
    throw Error("Transcript boundaries require literal source mode, clock and authenticated runtime");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-transcript-boundary-"));
  const state = path.join(directory, "state"), workspace = path.join(directory, "workspace");
  const agentId = input.agentId ?? "main", sessionId = input.sessionId ?? "boundary";
  const sessionKey = input.sessionKey ?? `agent:${agentId}:dm:boundary`;
  const fileName = input.fileName ?? `${sessionId}.jsonl`;
  if (path.basename(fileName) !== fileName || /[\\/]/.test(agentId)) throw Error("Source names must remain owned");
  const sessionDirectory = path.join(state, "agents", agentId, "sessions");
  const filename = path.join(sessionDirectory, fileName), configPath = path.join(directory, "openclaw.json");
  await fs.mkdir(workspace, { recursive: true }); await fs.mkdir(sessionDirectory, { recursive: true });
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH", "TMPDIR"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = state; process.env.OPENCLAW_CONFIG_PATH = configPath;
  process.env.TMPDIR = path.join(directory, "tmp"); await fs.mkdir(process.env.TMPDIR);
  const cfg = { agents: { defaults: { workspace }, list: [{ id: agentId, default: true }] },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { maintenance: { mode: "warn" } } };
  await fs.writeFile(configPath, JSON.stringify(cfg));
  const beforeDate = Date, beforeSetTimeout = setTimeout, beforePerformanceNow = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { fixtureBase: directory, kind: "boundary", source: input.source,
    constructorSkipped: true, managerFixture: false, indexManagerConstructed: false,
    clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(),
      dateConstructorReplaced: Date !== beforeDate, setTimeoutUnchanged: setTimeout === beforeSetTimeout,
      performanceNowUnchanged: performance.now === beforePerformanceNow },
    mutations: [], reads: [], sourceCaptures: [], cacheCaptures: [], observerCalls: [],
    environmentFault: { input: input.environmentFault ?? null, calls: [], restored: [] } };
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let clearConfig;
  try {
    const config = await imp("dist/plugin-sdk/config-runtime.js");
    config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
    const engine = await imp("dist/plugin-sdk/memory-core-host-engine-sessions.js");
    const files = await imp("dist/session-files-DVVT4Ngb.mjs");
    let sessions, accessor, scope, storePath;
    if (input.source === "sqlite") {
      sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
      accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
      storePath = sessions.resolveStorePath(undefined, { agentId });
      scope = { agentId, sessionId, sessionKey, storePath };
      await sessions.upsertSessionEntry({ ...scope, entry: { sessionId, updatedAt: input.nowMs,
        ...(input.sessionEntry ?? {}) } });
    }
    const encode = (value) => value.rawBytes !== undefined ? Buffer.from(value.rawBytes)
      : Buffer.from((value.events ?? []).map((event) => JSON.stringify(event)).join("\n") +
        ((value.events ?? []).length ? "\n" : ""), "utf8");
    async function write(value) {
      if (input.source === "sqlite") {
        if (value.rawBytes !== undefined) throw Error("SQLite source mutations must use actual event values");
        await accessor.replaceTranscriptEvents(scope, value.events ?? []);
      } else {
        const bytes = encode(value);
        if (value.sameSize) {
          const before = await fs.stat(filename);
          if (before.size !== bytes.length) throw Error("The literal same-size mutation changed byte length");
        }
        await fs.writeFile(filename, bytes);
        await fs.utimes(filename, (value.mtimeMs ?? input.nowMs) / 1000, (value.mtimeMs ?? input.nowMs) / 1000);
      }
    }
    async function capture() {
      if (input.source === "sqlite") {
        try { return { scope, entry: sessions.getSessionEntry(scope), events: accessor.loadTranscriptEventsSync(scope) }; }
        catch (error) { return { scope, error: publicError(error) }; }
      }
      try {
        const stat = await fs.lstat(filename, { bigint: true });
        const result = { filename, stat: Object.fromEntries(["dev", "ino", "mode", "size", "mtimeNs", "ctimeNs"]
          .map((key) => [key, String(stat[key])])) };
        if (stat.isFile()) result.bytes = Array.from(await fs.readFile(filename));
        if (stat.isSymbolicLink()) {
          result.target = await fs.readlink(filename);
          result.targetBytes = Array.from(await fs.readFile(result.target));
        }
        return result;
      } catch (error) { return { filename, error: publicError(error) }; }
    }
    async function readWithOwnedTemp(run) {
      if (!fileName.endsWith(".zst") || input.source !== "jsonl") return run();
      if (input.environmentFault?.kind !== "preferred-temp-root-unavailable") {
        throw Error("Compressed fixtures require the declared owned temporary-root fallback condition");
      }
      const originalLstat = syncFs.lstatSync;
      const fault = function transcriptFixturePreferredTempFault(candidate, ...args) {
        if (typeof candidate === "string" && candidate.replace(/\/+$/, "") === "/tmp/openclaw") {
          raw.environmentFault.calls.push({ readIndex: raw.reads.length, operation: "lstatSync", path: candidate, code: "EACCES" });
          throw Object.assign(new Error("Declared fixture admission failure for preferred temp root"),
            { code: "EACCES", syscall: "lstat", path: candidate });
        }
        return originalLstat.call(this, candidate, ...args);
      };
      syncFs.lstatSync = fault;
      try { return await run(); }
      finally {
        syncFs.lstatSync = originalLstat;
        raw.environmentFault.restored.push(syncFs.lstatSync === originalLstat);
      }
    }
    async function captureOwnedCache(label) {
      const root = process.env.TMPDIR;
      const found = [];
      async function visit(current) {
        for (const item of await fs.readdir(current, { withFileTypes: true })) {
          const child = path.join(current, item.name);
          if (!child.startsWith(`${root}${path.sep}`)) throw Error("An owned cache escaped its private root");
          if (item.isSymbolicLink()) throw Error("The private cache contains an unexpected symlink");
          if (item.isDirectory()) await visit(child);
          else {
            const bytes = await fs.readFile(child);
            found.push({ path: child, size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
              bytes: Array.from(bytes) });
          }
        }
      }
      await visit(root);
      raw.cacheCaptures.push({ label, root, files: found });
    }
    if (input.initial) { await write(input.initial); raw.mutations.push({ op: "initial", input: input.initial }); }
    const results = [];
    for (const step of input.steps ?? [{ op: "read", label: "initial" }]) {
      if (step.op === "read") {
        const observations = [];
        const options = { sessionKind: "interactive", ...(input.options ?? {}), ...(step.options ?? {}),
          ...(input.source === "sqlite" ? { ...scope, updatedAtMs: input.updatedAtMs ?? input.nowMs } : {}) };
        if (input.observer === true || step.observer === true) options.onTranscriptMessage = (message, timestampMs) => {
          observations.push({ message, timestampMs });
          raw.observerCalls.push({ readIndex: raw.reads.length, message, timestampMs });
          if (input.observerError || step.observerError) {
            const fact = step.observerError ?? input.observerError;
            const error = new Error(fact.message); error.name = fact.name ?? "Error";
            if (fact.code !== undefined) error.code = fact.code;
            throw error;
          }
        };
        const absPath = input.source === "sqlite" ? sessionKey : filename;
        const request = { absPath, options: { ...options, ...(options.onTranscriptMessage ? { onTranscriptMessage: true } : {}) } };
        let result;
        try {
          const entry = await readWithOwnedTemp(() => engine.buildSessionEntry(absPath, options));
          result = { label: step.label, entry,
            ...(entry ? { resetRecallCutoff: files.a(entry) } : {}),
            observedMessages: observations };
        } catch (error) { result = { label: step.label, error: publicError(error), observedMessages: observations }; }
        raw.reads.push({ request, result }); raw.sourceCaptures.push(await capture());
        if (fileName.endsWith(".zst") && input.source === "jsonl") await captureOwnedCache(step.label);
        results.push(result);
      } else if (["write", "replace-events"].includes(step.op)) {
        if (step.op === "replace-events" && input.source !== "sqlite") throw Error("replace-events is a SQLite mutation");
        await write(step); raw.mutations.push({ op: step.op, label: step.label, input: step });
      } else if (["remove", "directory", "symlink"].includes(step.op)) {
        if (input.source !== "jsonl") throw Error("Filesystem mutation requires a file source");
        await fs.rm(filename, { recursive: true, force: true });
        if (step.op === "directory") await fs.mkdir(filename);
        if (step.op === "symlink") {
          const target = path.join(directory, "symlink-target.jsonl");
          await fs.writeFile(target, encode(step)); await fs.utimes(target,
            (step.mtimeMs ?? input.nowMs) / 1000, (step.mtimeMs ?? input.nowMs) / 1000);
          await fs.symlink(target, filename);
        }
        raw.mutations.push({ op: step.op, label: step.label, input: step });
      } else throw Error(`Unsupported transcript source mutation: ${step.op}`);
    }
    return mapGetFixturePaths({ provider: "none", reads: results }, directory);
  } finally {
    mock.timers.reset(); clearConfig?.();
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}
