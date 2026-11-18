// Drive the published heartbeat runner, its actual event queue, cron store and channel dispatch.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
const [request, root, dir, resultFile] = process.argv.slice(2);
const { input } = JSON.parse(await fs.readFile(request, "utf8"));
const imp = (name) => import(pathToFileURL(path.join(root, "dist", name)).href);
const { t: runHeartbeatOnce } = await imp("heartbeat-runner-run-CGCaTa5u.mjs");
const { u: onHeartbeatEvent } = await imp("system-event-ownership-rW7KBn85.mjs");
const { i: enqueue, l: peek } = await imp("system-events-CGtOrtY9.mjs");
const { saveCronStore, loadCronStore } = await imp("plugin-sdk/cron-store-runtime.js");
const { i: readMonitor, o: writeScratch } = await imp("scratch-store-BsjpiVxl.mjs");
const { loadSessionEntry, replaceSessionEntry } = await imp("session-accessor-CiKKTlbe.mjs");
const { t: createPluginRegistry } = await imp("registry-empty-BTjzcMW2.mjs");
const { w: setActivePluginRegistry } = await imp("runtime-9cxii0oQ.mjs");

const workspace = path.join(dir, "workspace");
const storePath = path.join(dir, "state/cron/jobs.json");
const sessionKey = "agent:main:main";
const scope = { storePath: path.join(dir, "state/agents/main/sessions/sessions.json"), sessionKey };
const sink = [];
// Only the last hop is a fixture. The original router, SQLite delivery queue and
// channel dispatcher decide whether to call it. No built-in channel is enabled.
const channel = {
  id: "telegram", meta: { id: "telegram", label: "Local recorder", selectionLabel: "Local recorder",
    docsPath: "/local", blurb: "In-process recording recipient" },
  capabilities: { chatTypes: ["direct"] },
  config: { listAccountIds: () => ["default"], resolveAccount: () => ({}),
    isConfigured: () => true, resolveAllowFrom: () => ["*"] },
  outbound: { deliveryMode: "direct", resolveTarget: ({ to }) => ({ ok: true, to }),
    async sendText(args) {
      const result = { channel: "telegram", messageId: "local-" + (sink.length + 1), chatId: args.to };
      sink.push({ args: snapshot(args), result });
      return result;
    } },
};
const registry = createPluginRegistry();
const registration = { pluginId: channel.id, plugin: channel, source: "local recording recipient" };
registry.channels.push(registration);
registry.channelSetups.push({ ...registration, enabled: true });
setActivePluginRegistry(registry);

function snapshot(value, seen = new Set()) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "function") return { type: "function", name: value.name };
  if (typeof value === "symbol") return { type: "symbol", description: value.description };
  if (typeof value === "bigint") return { type: "bigint", value: String(value) };
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return { type: "cycle" };
  if (value instanceof Date) return { type: "Date", value: value.toISOString() };
  if (value instanceof Error) return { name: value.name, message: value.message, stack: value.stack };
  if (value instanceof AbortSignal) return { type: "AbortSignal", aborted: value.aborted, reason: snapshot(value.reason) };
  seen.add(value);
  const out = Array.isArray(value) ? value.map((item) => snapshot(item, seen)) :
    Object.fromEntries(Reflect.ownKeys(value).map((key) => [typeof key === "symbol" ? String(key) : key, snapshot(value[key], seen)]));
  seen.delete(value);
  return out;
}

const day = 86_400_000;
function makeJob(id, name, declarationKey, payload, firstAt) {
  return { id, name, declarationKey, payload, enabled: true, agentId: "main", sessionTarget: "main",
    wakeMode: "next-heartbeat", createdAtMs: input.nowMs - day, updatedAtMs: input.nowMs - day,
    schedule: { kind: "every", everyMs: day, anchorMs: firstAt }, state: { nextRunAtMs: firstAt } };
}
const monitor = makeJob("monitor-main", "heartbeat-main", "heartbeat:main", { kind: "heartbeat" }, input.nowMs + day);
await saveCronStore(storePath, { version: 1, jobs: [monitor] });
await replaceSessionEntry(scope, { sessionId: "fixture-heartbeat-main", updatedAt: input.nowMs - day });
const readState = async () => ({
  store: await loadCronStore(storePath), monitor: readMonitor(storePath, "main"), session: loadSessionEntry(scope),
  queue: peek(sessionKey),
});
const raw = { initial: await readState(), steps: [] };
const actual = [];

async function runScheduled(now, run, row) {
  const definitions = (await loadCronStore(storePath)).jobs.filter((job) => job.id !== monitor.id);
  if (!definitions.length) return run([]);
  const { t: CronService } = await imp("service-u8zoxec7.mjs");
  const { c: isJobDue } = await imp("jobs-scheduling-u2B7TBDi.mjs");
  const due = definitions.filter((job) => isJobDue(job, now, { forced: false }));
  row.due = due.map((job) => job.id);
  const received = [];
  let resolveReady, rejectReady;
  const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  const unexpected = () => { throw Error("Unexpected operation at the fixture cron host boundary"); };
  const service = new CronService({ cronEnabled: false, defaultAgentId: "main", storePath, nowMs: () => now,
    log: { debug() {}, info() {}, warn() {}, error() {} },
    scheduler: { signal: new AbortController().signal, schedule: unexpected },
    enqueueSystemEvent: unexpected, requestHeartbeat: unexpected, runIsolatedAgentJob: unexpected,
    onEvent(event) { row.cronEvents.push(snapshot(event)); },
    async requestHeartbeatAndWait(wake, options) {
      received.push(...wake.tasks);
      row.wakes.push({ wake: snapshot(wake), options: snapshot(options) });
      if (received.length === due.length) resolveReady(run(received));
      return ready;
    },
  });
  try {
    const receipts = Promise.all(definitions.map(async (job) => ({ id: job.id, result: await service.run(job.id, "due") })));
    receipts.catch(rejectReady);
    if (!due.length) resolveReady(run([]));
    const result = await ready;
    row.cronReceipts = await receipts;
    return result;
  } finally { service.stop(); }
}

for (const [i, step] of input.steps.entries()) {
  const at = input.nowMs + i * 60_000;
  const clock = process.env.MEMORY_EQ_HEARTBEAT_CLOCK;
  await fs.writeFile(clock + ".next", String(at));
  await fs.rename(clock + ".next", clock);
  const local = step.target === "local";
  const heartbeat = { every: step.every ?? "5m", target: local ? "telegram" : "none",
    ...(local ? { to: "42000" } : {}), ...(step.prompt === undefined ? {} : { prompt: step.prompt }) };
  const cfg = { plugins: { enabled: false }, agents: { defaults: { workspace, userTimezone: "UTC",
    timeFormat: "12", heartbeat } }, channels: { telegram: { allowFrom: ["*"] } },
    session: { store: scope.storePath }, cron: { store: storePath }, messages: { visibleReplies: "automatic" } };
  await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
  const row = { label: step.label, at, config: cfg, calls: [], events: [], cronEvents: [], wakes: [], queueDepthReads: [] };
  if (step.tasks) {
    const tasks = step.tasks.map((task) => makeJob(task.jobId, task.name, "heartbeat-task:main:" + task.jobId,
      { kind: "systemEvent", text: task.prompt }, at + (task.due ? 0 : day)));
    const store = await loadCronStore(storePath);
    await saveCronStore(storePath, { ...store, jobs: [...store.jobs, ...tasks] });
  }
  if (step.scratch !== undefined) {
    row.scratchWrite = writeScratch({ storePath, jobId: monitor.id, content: step.scratch, nowMs: at });
    if (!row.scratchWrite.ok) throw Error("The original rejected the monitor scratch write");
  }
  const addEvents = (events) => (events ?? []).map(({ text, contextKey }) => snapshot(enqueue(text, { sessionKey, contextKey })));
  row.enqueued = addEvents(step.events);
  row.before = await readState();
  const off = onHeartbeatEvent((event) => row.events.push(snapshot(event)));
  const startSink = sink.length;
  try {
    row.run = await runScheduled(at, (tasks) => {
      const args = { cfg, agentId: "main", sessionKey, source: step.source, reason: step.reason, tasks,
        deps: { nowMs: () => at, getQueueSize(lane) {
          const depth = Number(step.busy === true && lane === "main");
          row.queueDepthReads.push({ lane, depth });
          return depth;
        }, async getReplyFromConfig(...args) {
          const call = { args: snapshot(args) };
          row.calls.push(call);
          call.lateEnqueued = addEvents(step.late);
          if (step.error) {
            const error = Error(step.error);
            call.error = snapshot(error);
            throw error;
          }
          call.result = { text: step.reply };
          return call.result;
        } },
      };
      row.runArguments = snapshot(args);
      return runHeartbeatOnce(args);
    }, row);
  } finally { off(); }
  row.after = await readState();
  row.sends = sink.slice(startSink);
  const event = row.events.at(-1);
  let disposition;
  if (["skipped", "failed"].includes(row.run.status)) disposition = row.run.status;
  else if (event?.status === "sent") disposition = "delivered";
  else if (event?.status === "ok-token" || event?.status === "ok-empty") disposition = "quiet";
  else if (event?.status === "skipped") disposition = event.reason;
  else throw Error("Unaccounted original heartbeat disposition " + JSON.stringify({ run: row.run, event }));
  const ctx = row.calls[0]?.args[0];
  actual.push({ label: step.label, status: row.run.status, reason: row.run.reason ?? null, disposition,
    body: ctx?.Body ?? null, internalTurnSource: ctx?.InternalTurnSource ?? null,
    queueAfter: row.after.queue.map(({ text, contextKey }) => ({ text, contextKey: contextKey ?? null })),
    sent: row.sends.map(({ args }) => args.text) });
  raw.steps.push(row);
}
await fs.writeFile(resultFile, JSON.stringify({ raw, actual }));
