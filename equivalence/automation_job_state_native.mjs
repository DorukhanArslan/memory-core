// Drive the published service's explicit due-mode API with a persisted public job store.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const [requestPath, root, directory] = process.argv.slice(2);
const { input } = JSON.parse(await fs.readFile(requestPath, "utf8"));
const imp = (name) => import(pathToFileURL(path.join(root, "dist", name)).href);
const { t: CronService } = await imp("service-u8zoxec7.mjs");
const { n: computeJobNextRunAtMs } = await imp("jobs-scheduling-u2B7TBDi.mjs");
const { saveCronStore, loadCronStore } = await imp("plugin-sdk/cron-store-runtime.js");
const { createMemoryGetTool } = await imp("tools-DotaQGXh.mjs");
const workspace = path.join(directory, "workspace");
const storePath = path.join(directory, "state", "cron", "jobs.json");
const config = { agents: { defaults: { workspace } },
  memory: { search: { enabled: true, provider: "none", fallback: "none", sources: ["memory"] } } };
await fs.mkdir(path.join(workspace, "memory"), { recursive: true });
async function writeFiles(files) {
  for (const [name, value] of Object.entries(files)) {
    if (!/^memory\/[a-z]+\.md$/.test(name)) throw Error("An input file must belong to the fixture workspace");
    await fs.writeFile(path.join(workspace, name), value);
  }
}
await writeFiles(input.files);
const jobs = input.jobs.map((definition) => {
  const job = { ...definition, createdAtMs: input.nowMs, updatedAtMs: input.nowMs,
    sessionTarget: "main", wakeMode: "next-heartbeat", state: {} };
  job.state.nextRunAtMs = computeJobNextRunAtMs(job, input.nowMs);
  return job;
});
await saveCronStore(storePath, { version: 1, jobs });
const raw = { initialStore: await loadCronStore(storePath), steps: [] };
const actual = { steps: [] };
const unexpected = () => { throw Error("Unexpected host operation during explicit heartbeat task"); };
for (const { jobId, atMs, writes } of input.steps) {
  await writeFiles(writes);
  const beforeStore = await loadCronStore(storePath);
  const events = [], callbacks = [], reads = [];
  const service = new CronService({
    cronEnabled: false, defaultAgentId: "main", storePath, nowMs: () => atMs,
    log: { debug() {}, info() {}, warn() {}, error() {} },
    scheduler: { signal: new AbortController().signal, schedule: unexpected },
    enqueueSystemEvent: unexpected, requestHeartbeat: unexpected, runIsolatedAgentJob: unexpected,
    onEvent(event) { events.push(structuredClone(event)); },
    async requestHeartbeatAndWait(wake) {
      if (wake.tasks?.length !== 1) throw Error("Expected one original delivered task");
      const task = wake.tasks[0];
      const params = input.toolCalls[task.jobId];
      if (!params) throw Error("Received a task with no declared memory tool input");
      const tool = createMemoryGetTool({ config, agentId: wake.agentId });
      if (tool?.name !== "memory_get") throw Error("Original memory_get tool unavailable");
      const envelope = await tool.execute(task.jobId, params);
      const result = JSON.parse(envelope.content[0].text);
      if (!isDeepStrictEqual(result, JSON.parse(JSON.stringify(envelope.details)))) {
        throw Error("Original memory_get text and details differ");
      }
      reads.push({ wake, tool: { name: tool.name, arguments: params, envelope } });
      callbacks.push({ wake, tool: { name: tool.name, arguments: params, result } });
      return { status: "ran", durationMs: 0 };
    },
  });
  let run;
  try { run = await service.run(jobId, "due"); }
  finally { service.stop(); }
  const afterStore = await loadCronStore(storePath);
  const files = {}, fileBytes = {};
  for (const name of Object.keys(input.files)) {
    const bytes = await fs.readFile(path.join(workspace, name));
    files[name] = bytes.toString("utf8");
    fileBytes[name] = bytes.toString("hex");
  }
  actual.steps.push({ jobId, atMs, callbacks, files });
  raw.steps.push({ jobId, atMs, beforeStore, afterStore, run, events, callbacks: reads, fileBytes });
}
process.stdout.write(JSON.stringify({ actual, raw }));
