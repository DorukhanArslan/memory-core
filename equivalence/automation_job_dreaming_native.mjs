// Use the published plugin's registered service, real service facade and real Doctor stores.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
const [request, root, dir, out] = process.argv.slice(2);
const { scenario, nowMs } = JSON.parse(await fs.readFile(request, "utf8"));
const imp = name => import(pathToFileURL(path.join(root, "dist", name)).href);
const env = process.env, storePath = path.join(dir, "state", "cron", "jobs.json");
const { saveCronStore, loadCronStore } = await imp("plugin-sdk/cron-store-runtime.js");
const { t: CronService } = await imp("service-u8zoxec7.mjs");
const { default: plugin } = await imp("extensions/memory-core/index.js");
const { r: startPluginServices } = await imp("services-Bej96uol.mjs");
const { stateMigrations } = await imp("extensions/memory-core/doctor-contract-api.js");
const doctor = stateMigrations.find(migration => migration.id === "memory-core-dreaming-cron");
const { inspectCronJobsForDoctor: inspect, repairCronJobsForDoctor: repair } = await imp("doctor-Dbs5zYHU.mjs");
const { i: offline } = await imp("doctor-sqlite-maintenance-lock-CjN2a1si.mjs");
const { m: withAgent } = await imp("openclaw-agent-db-DRy3ui_B.mjs");
const { i: withPlugin } = await imp("plugin-lifecycle-lease-Bv0VNQKi.mjs");
await saveCronStore(storePath, { version: 1, jobs: scenario.jobs });
const initial = await loadCronStore(storePath), phases = [];
const stop = () => { throw Error("The explicit storage fixture must never execute a scheduled job"); };
for (const [index, step] of scenario.phases.entries()) {
  const stamp = nowMs + index;
  const config = { cron: { store: storePath }, agents: { defaults: { workspace: path.join(dir, "workspace") } },
    plugins: { entries: { "memory-core": { config: { dreaming: step.dreaming } } } } };
  const logs = [], backups = [], cronLogs = [], registeredServices = [];
  const logger = Object.fromEntries(["warn", "error", "info", "debug"].map(level =>
    [level, message => logs.push({ level, message })]));
  const before = await loadCronStore(storePath);
  let receipt;
  if (step.operation === "reconcile") {
    const cron = new CronService({ cronEnabled: true, storePath, nowMs: () => stamp, log: Object.fromEntries(Object.keys(logger).map(level =>
        [level, (...args) => cronLogs.push({ level, args })])),
      scheduler: { signal: new AbortController().signal, schedule: () => ({ cancel() {} }) },
      defaultAgentId: "main", enqueueSystemEvent: stop, requestHeartbeat: stop, runIsolatedAgentJob: stop });
    const services = [], registrations = [];
    const api = { config, runtime: { config: { current: () => config } }, logger,
      registerService(service) { services.push({ id: service.id, pluginId: "memory-core", service, source: "memory-core" }); } };
    for (const name of ["registerCli", "registerCommand", "registerGatewayMethod", "registerMemoryCapability", "registerTool", "on"]) {
      api[name] = (...args) => registrations.push([name, typeof args[0] === "string" ? args[0] : null]);
    }
    plugin.register(api);
    if (services.length !== 1 || services[0].id !== "memory-core-dreaming") throw Error("Missing original dreaming service");
    const handle = await startPluginServices({ registry: { services, plugins: [] }, config,
      workspaceDir: path.join(dir, "workspace"), getCronService: () => cron, throwOnStartError: true });
    try { registeredServices.push(...services.map(service => service.id)); receipt = null; }
    finally { await handle.stop({ strict: true }); cron.stop(); }
    if (logs.some(row => row.level === "error")) throw Error(JSON.stringify(logs));
  } else {
    const scope = { config, env, stateDir: path.join(dir, "state"), pluginId: "memory-core" };
    const context = { inspectCronJobs: () => inspect(scope) };
    if (step.operation === "doctor-preview") {
      receipt = await doctor.detectLegacyState({ ...scope, context });
    } else {
      receipt = await offline({ env, operation: "managed dreaming fixture Doctor",
        run: guard => withAgent({ env }, agent => withPlugin({ env, waitMs: 5000 }, async lease => {
          const authority = {
            assertCurrent() { guard.assertCurrent(); agent.assertOwned(); lease.assertOwned(); },
            assertOwnedInTransaction(db) { guard.assertCurrent(); agent.assertOwnedInTransaction(db); lease.assertOwnedInTransaction(db); },
          };
          return await doctor.migrateLegacyState({ ...scope, context: { ...context,
            async repairCronJobs(inventory, changes) {
              const reply = await repair(scope, authority, inventory, changes);
              if (reply.backupPath) backups.push(reply.backupPath);
              return reply;
            } } });
        })) });
    }
  }
  phases.push({ operation: step.operation, stamp, before, after: await loadCronStore(storePath), logs, receipt, backups, cronLogs, registeredServices });
}
await fs.writeFile(out, JSON.stringify({ initial, phases }), { flag: "wx" });
