// Independent native writer. Original OpenClaw owns acquisition, nesting, retries and cleanup.
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { setTimeout as sleep } from "node:timers/promises";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";

const context = JSON.parse(fs.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT, "utf8"));
const {role, root, definition} = context.workspaceLockActor;
const directory = path.join(root, role);
const input = definition.input;
const workspace = role === "waiter" && input.workspace === "other" ? "B" : "A";
const work = path.join(root, "workspaces", workspace);
const key = createHash("sha256").update(work).digest("hex");
const environment = {OPENCLAW_STATE_DIR: context.stateDirectory, OPENCLAW_CONFIG_PATH: context.configPath};
const database = path.join(context.stateDirectory, "state/openclaw.sqlite");
const identity = {pid: process.pid, ppid: process.ppid, workspace};
const clock = () => JSON.parse(fs.readFileSync(path.join(root, "clock.json"), "utf8"))[role];
const digest = data => createHash("sha256").update(data).digest("hex");
const encode = (_, value) => value === undefined ? {$type:"undefined"} : typeof value === "bigint" ? String(value) : value;
const errorOf = e => ({name:e.name,message:e.message,stack:e.stack,...(e.code ? {code:e.code}:{}),
  ...(e.outcome ? {outcome:e.outcome}:{}),...(e.cause ? {cause:errorOf(e.cause)}:{})});
const realTimeout = setTimeout;
const realPerformance = performance.now;
let origin = "setup";
let seq = 0;
let observations = 0;
let stage = "startup";

function record(event, fields = {}) {
  fs.appendFileSync(path.join(directory,"receipts.jsonl"),
    JSON.stringify({...identity, sequence:++seq, event, origin, nowMs:clock(), ...fields}, encode) + "\n");
}
function mark(name, data) {
  const target = path.join(directory, name + ".json");
  fs.writeFileSync(target + ".tmp",JSON.stringify({...identity,...data},encode));
  fs.renameSync(target + ".tmp",target);
}
function physical() {
  const db = new DatabaseSync(database,{readOnly:true});
  try {
    return {database, rows: db.prepare("SELECT entry_key, value_json FROM plugin_state_entries WHERE plugin_id=? AND namespace=? ORDER BY entry_key")
      .all("memory-core","short-term-locks")};
  } finally { db.close(); }
}
function inspectStore(real) {
  const result = {...real};
  for (const method of ["observe","compareAndApply"]) {
    result[method] = async (...args) => {
      const call = seq + 1;
      record("store-call",{method,args,call});
      try {
        const returned = await real[method](...args);
        record("store-return",{method,call,returned});
        if (role === "waiter" && stage === "acquiring" && origin === "lease" &&
            method === "observe" && returned.value && ++observations === 2) {
          mark("observed_twice",{lease:returned.value,observations,physical:physical()});
        }
        return returned;
      } catch(error) { record("store-error",{method,call,error:errorOf(error)}); throw error; }
    };
  }
  return result;
}
async function observe(marker, inspect) {
  const previous = origin;
  origin = marker;
  try { return await inspect(); } finally { origin = previous; }
}
async function owner(relative, alias) {
  const file = path.join(context.runtime.runtimeRoot, relative);
  const imported = (await import(pathToFileURL(file).href))[alias];
  if (typeof imported !== "function") throw Error("Missing original owner " + relative);
  record("owner",{relative, alias, name:imported.name, sourceSha256:digest(String(imported)), artifactSha256:digest(fs.readFileSync(file))});
  return imported;
}
async function waitFor(name) {
  while (!fs.existsSync(path.join(root,name))) await sleep(12);
}

Object.assign(process.env, environment);
mock.method(Date,"now", clock);
record("startup",{node:process.execPath, timersUnchanged:realTimeout === setTimeout && realPerformance === performance.now,
  state:environment,definition,workspaceKey:key,processStart:fs.readFileSync("/proc/self/stat","utf8")});
const lease = await owner("dist/dreaming-dreams-file-BJzlZFlf.mjs","g");
const configure = await owner("dist/dreaming-state-VYUvbU-n.mjs","p");
const openStore = await owner("dist/plugin-sdk/plugin-state-store-runtime.js","createPluginStateKeyedStore");
const close = await owner("dist/plugin-state-store-BPUaLoVD.mjs","u");
const processStartTime = await owner("dist/pid-alive-BYw_9KTp.mjs","n");
let exposed;
configure(options => {
  const selected = openStore("memory-core",{...options,env:environment});
  record("factory",{options,methods:Object.keys(selected)});
  exposed = inspectStore(selected);
  return exposed;
});
let outcome;
try {
  origin = "lease";
  stage = "acquiring";
  record("lock-call",{workspaceDir:work});
  await lease(work, async () => {
    stage = "acquired";
    const entered = async () => {
      const original = await observe("after-acquire",() => exposed.observe(key));
      const realLease = original.value;
      if (!realLease || !realLease.owner.startsWith(process.pid + ":")) throw Error("No physical lease for process");
      fs.appendFileSync(path.join(work,"journal.txt"), input.lines[role === "holder" ? 0 : 1]);
      record("write",{path:path.join(work,"journal.txt"),line:input.lines[role === "holder" ? 0 : 1],physical:physical()});
      let visibleLease = realLease;
      if (role === "holder" && input.holder === "replace-start-time") {
        const priorPid = process.ppid;
        const olderStartTime = processStartTime(priorPid);
        if (olderStartTime === null || !(olderStartTime < realLease.ownerStartTime)) throw Error("No distinct prior PID start time");
        visibleLease = {...realLease,ownerStartTime:olderStartTime};
        const applied = await observe("replace-start-time",() => exposed.compareAndApply(key, original.comparison,
          {operation:"update",action:"set",value:visibleLease}));
        if (applied.status !== "applied") throw Error("Could not change the observed fixture lease");
        record("replaced",{priorPid,olderStartTime,original:realLease,replacement:visibleLease,physical:physical()});
      }
      const proof = {lease:visibleLease,physical:physical()};
      record("entered",proof);
      mark("entered",proof);
    };
    if (role === "waiter") {
      record("nested-call",{workspaceDir:work});
      await lease(work, entered);
      record("nested-return");
      await waitFor("finish-waiter");
      const latest = await observe("before-release",() => exposed.observe(key));
      const proof = {lease:latest.value,physical:physical()};
      record("before-release",proof);
      mark("before-release",proof);
    } else {
      await entered();
      await waitFor("release");
    }
  });
  outcome = {status:"acquired",error:null};
} catch(error) {
  if (error.code !== "MEMORY_WORKSPACE_LOCK_HELD") { record("unexpected",{error:errorOf(error)}); throw error; }
  outcome = {status:"held",error:errorOf(error)};
}
record("lock-return",{...outcome,physical:physical()});
await close();
record("closed",{timersUnchanged:realTimeout === setTimeout && realPerformance === performance.now});
mock.restoreAll();
mark("done",outcome);
