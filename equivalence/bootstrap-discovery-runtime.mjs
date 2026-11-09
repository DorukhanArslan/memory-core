// Literal host filesystem/setup requests into the three genuine compiled owners.
// Own API returns and complete filesystem/state observations remain private raw.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { mock } from "node:test";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

const templateNames = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md"];
function observe(value, seen = new Set()) {
  if (value === undefined) return { type: "undefined" };
  if (value === null || typeof value !== "object") return typeof value === "bigint"
    ? { type: "bigint", value: value.toString() } : value;
  if (seen.has(value)) return { type: "circular-reference" };
  seen.add(value);
  const result = Array.isArray(value) ? value.map((item) => observe(item, seen))
    : { ...(value instanceof Error ? { name: value.name } : {}),
      ...Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, observe(value[key], seen)])) };
  seen.delete(value);
  return result;
}
function stableError(error) {
  if (error === null || typeof error !== "object") return observe(error);
  return { name: error.name, message: error.message,
    ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) => !["name", "message", "stack"].includes(key))
      .map((key) => [key, key === "cause" ? stableError(error[key]) : observe(error[key])])) };
}
async function tree(root, relative = "") {
  const result = [];
  for (const entry of (await fs.readdir(path.join(root, relative), { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name, "en"))) {
    const name = path.join(relative, entry.name), filename = path.join(root, name), stat = await fs.lstat(filename);
    const row = { path: name, stat, kind: stat.isSymbolicLink() ? "symlink" : stat.isDirectory() ? "directory" : stat.isFile() ? "file" : "other" };
    if (row.kind === "symlink") row.target = await fs.readlink(filename);
    else if (row.kind === "file") row.bytes = { type: "bytes", hex: (await fs.readFile(filename)).toString("hex") };
    result.push(row);
    if (row.kind === "directory") result.push(...await tree(root, name));
  }
  return result;
}

export async function runBootstrapDiscoveryRuntime(input, runtimeConfig) {
  if (input.kind !== "workspace-bootstrap" || !Number.isFinite(input.nowMs) || !Array.isArray(input.steps) ||
      !["openclaw", "memory-core"].includes(input.layout) || !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") ||
      !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "")) throw Error("A literal compiled bootstrap flow requires its owned roots and clock");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-bootstrap-discovery-"));
  const workspace = path.join(directory, "workspace"), stateDirectory = path.join(directory, "state"), configPath = path.join(directory, "openclaw.json");
  const outside = path.join(directory, "outside");
  await fs.mkdir(workspace); await fs.mkdir(stateDirectory); await fs.mkdir(outside);
  const cfg = { logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { maintenance: { mode: "warn" } } };
  await fs.writeFile(configPath, JSON.stringify(cfg));
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = stateDirectory; process.env.OPENCLAW_CONFIG_PATH = configPath;
  const oldDate = Date, oldTimeout = setTimeout, oldPerformance = performance.now;
  mock.timers.enable({ apis: ["Date"], now: input.nowMs });
  const raw = { kind: input.kind, input, fixtureBase: directory, pid: process.pid, ppid: process.ppid,
    runtime: { execPath: fsSync.realpathSync(process.execPath), nodeVersion: process.version, icuVersion: process.versions.icu,
      unicodeVersion: process.versions.unicode, sha256: crypto.createHash("sha256").update(fsSync.readFileSync(process.execPath)).digest("hex") },
    config: cfg, clock: { owner: "node:test", apis: ["Date"], nowMs: Date.now(), dateConstructorReplaced: Date !== oldDate,
      setTimeoutUnchanged: setTimeout === oldTimeout, performanceNowUnchanged: performance.now === oldPerformance },
    packagedTemplates: {}, writes: [], calls: [], snapshots: [], close: null };
  const publicSteps = [];
  let closeState;
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  function filename(relative, root = workspace) {
    if (typeof relative !== "string" || !relative || path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) throw Error("Bootstrap fixture paths must stay inside the owned workspace");
    return path.join(root, relative);
  }
  async function write(files, label) {
    for (const [relative, text] of Object.entries(files ?? {})) {
      const absolute = filename(relative); await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, text); raw.writes.push({ label, path: absolute, input: text });
    }
  }
  async function call(label, owner, request, invoke) {
    const record = { label, owner, request }; raw.calls.push(record);
    try { const result = await invoke(); record.returnedUndefined = result === undefined; record.result = observe(result); return { value: result }; }
    catch (error) { record.error = observe(error); return { error }; }
  }
  try {
    for (const name of templateNames) {
      const templatePath = path.join(runtimeConfig.runtimeRoot, "docs/reference/templates", name), bytes = await fs.readFile(templatePath);
      raw.packagedTemplates[name] = { path: templatePath, bytes: bytes.length,
        sha256: crypto.createHash("sha256").update(bytes).digest("hex"), content: bytes.toString("utf8") };
      if (input.packagedTemplates?.[name] !== bytes.toString("utf8")) throw Error("The common host template bytes differ from the actual release package");
    }
    const workspaceOwner = await imp("dist/workspace-C0LMBmap.mjs"), bootstrapOwner = await imp("dist/bootstrap-files-CgqY-7GK.mjs");
    const stateOwner = await imp("dist/workspace-state-store-NkqJ2B1E.mjs");
    closeState = (await imp("dist/openclaw-state-db-cache-IdIaBoUp.mjs")).a;
    await write(input.files, "initial");
    for (const relative of input.directories ?? []) {
      const absolute = filename(relative); await fs.mkdir(absolute, { recursive: true });
      raw.writes.push({ label: "initial", operation: "mkdir", path: absolute });
    }
    for (const [relative, bytes] of Object.entries(input.fileBytes ?? {})) {
      if (!Array.isArray(bytes) || bytes.some((byte) => !Number.isInteger(byte) || byte < 0 || byte > 255)) throw Error("Literal byte fixtures require octets");
      const absolute = filename(relative); await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, Uint8Array.from(bytes)); raw.writes.push({ label: "initial", path: absolute, bytes });
    }
    for (const [relative, shape] of Object.entries(input.fileSizes ?? {})) {
      if (!Number.isInteger(shape.size) || shape.size < 0 || shape.size > 3 * 1024 * 1024 || !Number.isInteger(shape.fill) || shape.fill < 0 || shape.fill > 255) throw Error("Bounded fixture sizes and fill bytes must be literal integers");
      const absolute = filename(relative); await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, Buffer.alloc(shape.size, shape.fill)); raw.writes.push({ label: "initial", path: absolute, shape });
    }
    for (const [relative, text] of Object.entries(input.outsideFiles ?? {})) {
      const absolute = filename(relative, outside); await fs.mkdir(path.dirname(absolute), { recursive: true });
      await fs.writeFile(absolute, text); raw.writes.push({ label: "initial", path: absolute, input: text });
    }
    for (const [relative, target] of Object.entries(input.symlinks ?? {})) {
      if (!["workspace", "outside"].includes(target.scope)) throw Error("A symlink fixture needs an explicit owned target scope");
      const absolute = filename(relative), resolved = filename(target.path, target.scope === "outside" ? outside : workspace);
      await fs.mkdir(path.dirname(absolute), { recursive: true }); await fs.symlink(resolved, absolute);
      raw.writes.push({ label: "initial", operation: "symlink", path: absolute, target: resolved });
    }
    for (const [relative, target] of Object.entries(input.hardlinks ?? {})) {
      const absolute = filename(relative), resolved = filename(target);
      await fs.mkdir(path.dirname(absolute), { recursive: true }); await fs.link(resolved, absolute);
      raw.writes.push({ label: "initial", operation: "hardlink", path: absolute, target: resolved });
    }
    for (const step of input.steps) {
      await write(step.writes, step.label);
      for (const relative of step.removes ?? []) { const absolute = filename(relative); await fs.rm(absolute, { recursive: true, force: true }); raw.writes.push({ label: step.label, operation: "remove", path: absolute }); }
      if (step.setup) await call(step.label, "mergeWorkspaceSetupState", { dir: workspace, state: step.setup }, () => stateOwner.r(workspace, step.setup));
      let ensured = null;
      if (step.ensure !== undefined) {
        const request = { ...step.ensure, dir: workspace };
        const result = await call(step.label, "ensureAgentWorkspace", request, () => workspaceOwner.t(request));
        ensured = result.error ? { error: stableError(result.error) } : { bootstrapPending: result.value.bootstrapPending };
      }
      const loaded = await call(step.label, "loadWorkspaceBootstrapFiles", { dir: workspace }, () => workspaceOwner.s(workspace));
      const runs = [];
      for (const run of step.runs ?? []) {
        const { sessionKind: _hostKind, ...literal } = run;
        const warnings = [], request = { ...literal, workspaceDir: workspace, warn: (message) => warnings.push(message) };
        const result = await call(step.label, "resolveBootstrapFilesForRun", { ...literal, workspaceDir: workspace }, () => bootstrapOwner.c(request));
        raw.calls.at(-1).warnings = warnings;
        runs.push({ request: run, ...(result.error ? { error: stableError(result.error) } : { files: result.value }), warnings });
      }
      const snapshot = await call(step.label, "readWorkspaceStateSnapshot", { dir: workspace }, () => stateOwner.a(workspace));
      const status = await call(step.label, "resolveWorkspaceBootstrapStatus", { dir: workspace }, () => workspaceOwner.c(workspace));
      const completed = await call(step.label, "isWorkspaceSetupCompleted", { dir: workspace }, () => workspaceOwner.a(workspace));
      raw.snapshots.push({ label: step.label, state: snapshot.error ? { error: observe(snapshot.error) } : observe(snapshot.value),
        workspace: await tree(workspace), workspaceEntries: await fs.readdir(workspace, { recursive: true }),
        hostState: await tree(stateDirectory), hostStateEntries: await fs.readdir(stateDirectory, { recursive: true }),
        outside: await tree(outside), outsideEntries: await fs.readdir(outside, { recursive: true }) });
      publicSteps.push({ label: step.label, ensure: ensured,
        ...(loaded.error ? { loadError: stableError(loaded.error) } : { loaded: loaded.value }), runs,
        bootstrapStatus: status.error ? { error: stableError(status.error) } : status.value,
        setupCompleted: completed.error ? { error: stableError(completed.error) } : completed.value });
    }
    return mapGetFixturePaths({ provider: "none", steps: publicSteps }, directory);
  } catch (error) {
    raw.fatal = observe(error); throw error;
  } finally {
    if (closeState) {
      try { const value = await closeState(); raw.close = { owner: "closeOpenClawStateDatabaseAsync", returnedUndefined: value === undefined, result: observe(value) }; }
      catch (error) { raw.close = { owner: "closeOpenClawStateDatabaseAsync", error: observe(error) }; }
    }
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]) + "\n");
    mock.timers.reset();
    for (const [key, value] of Object.entries(prior)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  }
}
