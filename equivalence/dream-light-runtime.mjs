// Drive the original published light sweep and read its persisted events and stores.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

const hashes = new Set([
  "85658fb6772686c97774a717720651b6ae831bcb87f7c57ca6b4508f75141260",
  "7628489d955457a203b55c9165e00e7f5296fb2a8d6b9bef6300dfe79923d178",
  "0450e2d87e0b8f0579d8332b270cc7057bfaac60f5271fc5dd209503ce399e3d",
  "6639ece8670a1ef566fe1cf3cc976bcc06ce2dd860739c32d11fe8183b5cb2ca",
  "41d01e5c32488e572028c96af0eb73ff424cfe79f8c69daa1dd8d43076139885",
  "bf277cef1dde71a84295b1773cdbf485e215d50351b7cd9d116684d3bea73cd7",
  "a6f789a579911300719f83fb1fbc66428530eab8b23971123f182ffdb62b13a6",
]);
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const ordered = object => Array.isArray(object) ? object.map(ordered) :
  object && typeof object === "object" ? Object.fromEntries(Object.keys(object).sort().map(k => [k, ordered(object[k])])) : object;
const recallFile = "memory/.dreams/short-term-recall.json";
const signalFile = "memory/.dreams/phase-signals.json";
const errorRecord = e => ({name: e.name, message: e.message, stack: e.stack, ...(e.code ? {code: e.code} : {})});

async function snapshot(root, blobs, folder = root, result = {}) {
  for (const name of (await fs.readdir(folder)).sort()) {
    const file = path.join(folder, name);
    const info = await fs.lstat(file);
    if (info.isDirectory()) {
      await snapshot(root, blobs, file, result);
    } else {
      if (info.isSymbolicLink() || !info.isFile() || info.nlink !== 1 || info.size > 4 * 1024 * 1024)
        throw Error("Unsafe or unexpectedly large dreaming fixture file");
      const bytes = await fs.readFile(file);
      const sha256 = digest(bytes);
      blobs[sha256] ??= bytes.toString("base64");
      result[path.relative(root, file)] = {sha256, size: bytes.length, mtimeMs: info.mtimeMs};
    }
  }
  return result;
}

function publicEvents(records, root) {
  // Event paths originate in the real write callback. Only its owned root varies.
  return records.map(event => Object.fromEntries(Object.entries(event).map(([key, value]) =>
    [key, ["reportPath", "inlinePath"].includes(key) && typeof value === "string" && value.startsWith(root + "/") ? "$WORKSPACE" + value.slice(root.length) : value])));
}

export function runDreamLightRuntime(input, runtimeConfig) {
  return runPhase(input, runtimeConfig, "light", hashes);
}

export async function runDreamRemRuntime(input, runtimeConfig) {
  const rem = await import("./dream-rem-runtime.mjs");
  return runPhase(input, runtimeConfig, "rem", rem.remHashes, rem);
}

async function runPhase(input, runtimeConfig, phase, boundHashes, rem) {
  const inputSha256 = digest(JSON.stringify(ordered(input)));
  if (!boundHashes.has(inputSha256) || !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "") ||
      !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "")) throw Error("Unbound light sweep request");
  const evidence = runtimeConfig.evidenceDirectory;
  await fs.mkdir(evidence, {recursive: true});
  const root = await fs.mkdtemp(path.join(evidence, `native-${phase}-`));
  const workspace = path.join(root, "workspace");
  const env = {OPENCLAW_STATE_DIR: path.join(root, "state"), OPENCLAW_HOME: root,
    OPENCLAW_CONFIG_PATH: path.join(root, "openclaw.json")};
  const savedEnv = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const cfg = {agents: {defaults: {workspace, userTimezone: "UTC"}, list: [{id: "main", workspace}]},
    logging: {level: "silent", consoleLevel: "silent", file: path.join(root, "openclaw.log")}};
  const options = input.options;
  const pluginConfig = {dreaming: {enabled: options.enabled, timezone: options.timezone,
    storage: {mode: options.storageMode}, phases: phase === "rem" ? rem.remPhaseConfig(options) : {light: {enabled: true, limit: options.limit,
      lookbackDays: options.lookbackDays, dedupeSimilarity: options.dedupeSimilarity}, rem: {enabled: false}}}};
  const raw = {factoryCalls: [], kind: `official-${phase}-sweep`, input, inputSha256, root, workspace, cfg, pluginConfig, env,
    pid: process.pid, ppid: process.ppid, owners: [], calls: [], snapshots: [], blobs: {}, logs: [], observations: []};
  let clockEnabled = false;
  let close;
  const clockBefore = Date;
  const timerBefore = setTimeout;
  const performanceBefore = performance.now;
  async function owner(relative, alias) {
    const location = path.join(runtimeConfig.runtimeRoot, relative);
    const fn = (await import(pathToFileURL(location).href))[alias];
    if (typeof fn !== "function") throw Error("Original dreaming owner unavailable: " + relative);
    raw.owners.push({relative, alias, name: fn.name, sourceSha256: digest(Function.prototype.toString.call(fn)),
      artifactSha256: digest(await fs.readFile(location))});
    return fn;
  }
  async function call(name, args, fn, invocation = args) {
    const receipt = {name, args: structuredClone(args)};
    raw.calls.push(receipt);
    try {
      const value = await fn(...invocation);
      receipt.returned = value === undefined ? {kind: "undefined"} : {kind: "value", value: structuredClone(value)};
      return value;
    } catch (error) {
      receipt.error = errorRecord(error);
      throw error;
    }
  }
  try {
    Object.assign(process.env, env);
    await fs.mkdir(workspace);
    await fs.writeFile(env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
    let nowMs = input.operations[0].nowMs;
    mock.timers.enable({apis: ["Date"], now: nowMs}); clockEnabled = true;
    for (const [relative, body] of Object.entries(input.files)) {
      const file = path.resolve(workspace, relative);
      if (!file.startsWith(workspace + path.sep)) throw Error("Seed escaped workspace");
      await fs.mkdir(path.dirname(file), {recursive: true});
      await fs.writeFile(file, body, {flag: "wx"});
      await fs.utimes(file, nowMs / 1000, nowMs / 1000);
    }
    const configure = await owner("dist/dreaming-state-VYUvbU-n.mjs", "p");
    const openStore = await owner("dist/plugin-state-store-BPUaLoVD.mjs", "r");
    close = await owner("dist/plugin-state-store-BPUaLoVD.mjs", "u");
    configure(options => {
      const selectedOptions = {...options, env};
      const store = openStore("memory-core", selectedOptions);
      raw.factoryCalls.push({pluginId: "memory-core", options, selectedOptions,
        returnedMethods: Object.keys(store)});
      return store;
    });
    const sweep = await owner("dist/dreaming-phases-rmgXNBLP.mjs", "r");
    const storeModule = "dist/short-term-promotion-store-B6T388Bo.mjs";
    const readCarrier = await owner(storeModule, "i");
    const readRecall = await owner(storeModule, "a");
    const readSignals = await owner(storeModule, "r");
    const readEvents = await owner("dist/plugin-sdk/memory-host-events.js", "readMemoryHostEventRecords");
    const writeRecall = Object.hasOwn(input.files, recallFile) ? await owner(storeModule, "l") : undefined;
    if (writeRecall) await call("writeStore", [workspace, JSON.parse(input.files[recallFile])], writeRecall);
    if (Object.hasOwn(input.files, signalFile)) await call("writePhaseSignalStore", [workspace, JSON.parse(input.files[signalFile])],
      await owner(storeModule, "c"));
    raw.snapshots.push(await snapshot(root, raw.blobs));
    const logger = Object.fromEntries(["info", "debug", "error", "warn"].map(level =>
      [level, (...args) => raw.logs.push({level, args})]));
    const modelCalls = [], sweepResults = [];
    if (phase === "rem") raw.modelCalls = [];
    for (const operation of input.operations) {
      if (operation.op === phase) {
        nowMs = operation.nowMs;
        mock.timers.setTime(nowMs);
        const args = {workspaceDir: workspace, cfg, pluginConfig, nowMs};
        if (phase === "light" || options.agentId !== null) args.agentId = phase === "light" ? "main" : options.agentId;
        const provider = phase === "rem" ? rem.remNarrator(options, modelCalls, raw.modelCalls, async key => {
          const state = await call("readStore", [workspace, new Date(nowMs).toISOString()], readRecall);
          if (!Object.hasOwn(state.entries, key)) throw Error("Missing fixture recall key");
          delete state.entries[key];
          await call("writeStore", [workspace, state], writeRecall);
        }) : {};
        sweepResults.push(await call("runDreamingSweepPhases", [args], sweep, [{...args, ...provider, logger}]));
      } else if (operation.op === "remove") {
        if (!Object.hasOwn(input.files, operation.path)) throw Error("Removal is not a literal seed");
        await fs.unlink(path.join(workspace, operation.path));
      } else throw Error("Unknown operation");
      const now = new Date(nowMs).toISOString();
      for (const kind of ["recall", "phase"]) await call("readShortTermStore", [workspace, kind, now], readCarrier);
      const recall = await call("readStore", [workspace, now], readRecall);
      const signals = await call("readPhaseSignalStore", [workspace, now], readSignals);
      const records = await call("readMemoryHostEventRecords", [{workspaceDir: workspace, env}], readEvents);
      const tree = await snapshot(root, raw.blobs);
      raw.snapshots.push(tree);
      const documents = Object.fromEntries(Object.entries(tree).filter(([p]) => p.startsWith("workspace/") && p.endsWith(".md"))
        .map(([p, record]) => [p.slice("workspace/".length), Buffer.from(raw.blobs[record.sha256], "base64").toString("utf8")]));
      raw.observations.push({operation, documents, recall, signals, events: publicEvents(records, workspace),
        ...(phase === "rem" ? {modelCalls: structuredClone(modelCalls), sweepResults: structuredClone(sweepResults)} : {})});
    }
    raw.completed = true;
    return {observations: raw.observations};
  } catch (error) {
    raw.error = errorRecord(error);
    try { raw.failureSnapshot = await snapshot(root, raw.blobs); } catch (e) { raw.snapshotError = errorRecord(e); }
    throw error;
  } finally {
    if (close) {
      try { await close(); raw.storeClosed = true; }
      catch (error) { raw.closeError = errorRecord(error); }
    }
    if (clockEnabled) mock.timers.reset();
    raw.clockRestored = Date === clockBefore && setTimeout === timerBefore && performance.now === performanceBefore;
    for (const [key, value] of Object.entries(savedEnv)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    raw.blobEncoding = "gzip-base64";
    let capturedBytes = 0;
    for (const [sha256, content] of Object.entries(raw.blobs)) {
      const bytes = Buffer.from(content, "base64");
      capturedBytes += bytes.length;
      if (capturedBytes > 16 * 1024 * 1024) throw Error("Light capture exceeded the reviewed filesystem bound");
      raw.blobs[sha256] = gzipSync(bytes).toString("base64");
    }
    await fs.writeFile(path.join(evidence, "native-raw.json"), JSON.stringify([raw]), {flag: "wx"});
  }
}
