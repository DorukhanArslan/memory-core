// The original explicit run and Doctor use the same public stores as a normal host.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [requestFile, root, directory, phase, resultPath] = process.argv.slice(2);
const input = JSON.parse(await fs.readFile(requestFile, "utf8"));
const imp = (file) => import(pathToFileURL(path.join(root, "dist", file)).href);
const env = process.env;
const { saveCronStore, loadCronStore } = await imp("plugin-sdk/cron-store-runtime.js");
const { n: nextRun, c: isJobDue } = await imp("jobs-scheduling-u2B7TBDi.mjs");
const storePath = path.join(directory, "state", "cron", "jobs.json");
const cfg = { cron: { store: storePath }, agents: { defaults: {
  workspace: path.join(directory, "workspace"), heartbeat: { every: "30m" } }, list: [{ id: "main" }] } };

async function driveScheduling() {
  const { t: CronService } = await imp("service-u8zoxec7.mjs");
  const probes = input.probes.map(({ job, nowMs, forced }) => ({
    nextRunAtMs: nextRun(job, nowMs) ?? null, due: isJobDue(job, nowMs, { forced }),
  }));
  await saveCronStore(storePath, { version: 1, jobs: input.jobs });
  const initialStore = await loadCronStore(storePath);
  const runs = [];
  const unexpected = () => { throw Error("Unexpected host operation during scheduled memory task"); };
  for (const { jobId, atMs, mode, reply } of input.runs) {
    const beforeStore = await loadCronStore(storePath);
    const events = [], callbacks = [];
    const service = new CronService({
      cronEnabled: false, defaultAgentId: "main", storePath, nowMs: () => atMs,
      log: { debug() {}, info() {}, warn() {}, error() {} },
      scheduler: { signal: new AbortController().signal, schedule: unexpected },
      enqueueSystemEvent: unexpected, requestHeartbeat: unexpected, runIsolatedAgentJob: unexpected,
      onEvent(value) { events.push(structuredClone(value)); },
      async requestHeartbeatAndWait(wake) {
        callbacks.push({ wake, reply });
        return reply;
      },
    });
    let receipt;
    try { receipt = await service.run(jobId, mode); }
    finally { service.stop(); }
    runs.push({ jobId, atMs, mode, beforeStore, afterStore: await loadCronStore(storePath),
      events, receipt, callbacks });
  }
  return { probes, initialStore, runs };
}

async function driveMigration() {
  const { i: planMonitor } = await imp("heartbeat-monitor-DczrY0HS.mjs");
  const { o: writeScratch, i: readScratch } = await imp("scratch-store-BsjpiVxl.mjs");
  const { t: resolveSession } = await imp("heartbeat-runner-session-BlQRaBUC.mjs");
  const { m: replaceSession } = await imp("session-accessor.sqlite-entry-BrsmAX-T.mjs");
  const { collectHeartbeatTaskMigrationFindings: findings, maybeMigrateHeartbeatTasksToCron: migrate } =
    await imp("doctor-heartbeat-task-migration-BSKsU-82.mjs");

  const { nowMs } = input;
  const session = () => resolveSession(cfg, "main", cfg.agents.defaults.heartbeat, undefined, env);
  async function snapshot() {
    return { store: await loadCronStore(storePath), monitor: readScratch(storePath, "main", { env }),
      session: session(), findings: await findings(cfg, env) };
  }
  if (phase === "seed") {
    const monitorPlan = planMonitor(cfg, [], { schedulerSeed: "memory-task-outcomes" });
    const monitor = { ...monitorPlan.specs[0].input, id: "fixture-monitor", createdAtMs: nowMs,
      updatedAtMs: nowMs, state: {} };
    monitor.state.nextRunAtMs = nextRun(monitor, nowMs);
    await saveCronStore(storePath, { version: 1, jobs: [monitor, ...input.jobs] });
    const write = writeScratch({ storePath, jobId: monitor.id, content: input.scratch,
      expectedRevision: 0, nowMs, options: { env } });
    if (!write.ok) throw Error("Could not seed original heartbeat monitor scratch");
    const identity = session();
    const entry = await replaceSession({ storePath: identity.storePath, sessionKey: identity.sessionKey, env },
      { sessionId: "fixture-heartbeat-main", updatedAt: nowMs, heartbeatTaskState: input.legacyTaskState });
    return { monitorPlan, write, entry, after: await snapshot() };
  }
  if (!input.phases.includes(phase)) throw Error("Unexpected Doctor phase");
  const before = await snapshot();
  const receipt = await migrate({ cfg, env, nowMs, shouldRepair: phase !== "preview" });
  return { before, receipt, after: await snapshot() };
}

const result = phase === "scheduling" ? await driveScheduling() : await driveMigration();
await fs.writeFile(resultPath, JSON.stringify(result), { flag: "wx", mode: 0o600 });
