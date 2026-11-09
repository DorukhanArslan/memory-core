// Complete official memory_get factory and execute boundary. This reader does
// not construct an index manager; genuine secure file IO and wiki registrations
// exercise the native read and corpus owners without an invented index worker.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { decodeSearchToolEnvelope } from "./search-contract-runtime.mjs";

const publicError = (error) => ({ name: error.name,
  ...(error.status === undefined ? {} : { status: error.status }), message: error.message });

// Host identity transport only. Preserve all values and path suffixes; no OS
// wording, cause, code, provider content or envelope field is selected away.
export function mapGetFixturePaths(value, fixtureBase) {
  if (typeof value === "string") return value === fixtureBase ? "$FIXTURE"
    : value.replaceAll(`${fixtureBase}/`, "$FIXTURE/");
  if (Array.isArray(value)) return value.map((item) => mapGetFixturePaths(item, fixtureBase));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [key, mapGetFixturePaths(item, fixtureBase)]));
  return value;
}

const writeStatFields = ["dev", "ino", "mode", "nlink", "uid", "gid", "rdev", "size",
  "blksize", "blocks", "mtimeNs", "ctimeNs"];
const fileKind = (mode) => ({ 32768: "file", 16384: "directory", 40960: "symlink",
  4096: "fifo", 49152: "socket", 8192: "character-device", 24576: "block-device" })[Number(mode) & 61440] ?? "unknown";
const rawStat = (info) => Object.fromEntries(Object.getOwnPropertyNames(info).map((key) => {
  const value = info[key];
  return [key, typeof value === "bigint" ? value.toString() : value];
}));

export async function snapshotGetFixture(base) {
  const entries = [];
  async function visit(filename, root = false) {
    const relative = path.relative(base, filename).split(path.sep).join("/");
    let info;
    try { info = await fs.lstat(filename, { bigint: true }); }
    catch (error) {
      if (!root || !["ENOENT", "ENOTDIR"].includes(error.code)) throw error;
      entries.push({ path: relative, kind: "missing" });
      return;
    }
    const entry = { path: relative, kind: fileKind(info.mode), rawStat: rawStat(info) };
    if (info.isSymbolicLink()) entry.target = await fs.readlink(filename);
    else if (info.isFile()) {
      const handle = await fs.open(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      try {
        const opened = await handle.stat({ bigint: true });
        if (opened.dev !== info.dev || opened.ino !== info.ino) throw Error("Owned fixture changed during its nofollow snapshot");
        entry.openedStat = rawStat(opened);
        entry.bytesBase64 = (await handle.readFile()).toString("base64");
      } finally { await handle.close(); }
    }
    entries.push(entry);
    if (info.isDirectory()) {
      const names = (await fs.readdir(filename)).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
      for (const name of names) await visit(path.join(filename, name));
    }
  }
  for (const name of ["workspace", "outside"]) await visit(path.join(base, name), true);
  return { statFormat: "node-bigint-stats", entries };
}

export function deriveGetFilesystemObservation(raw) {
  function manifest(snapshot) {
    const result = {}, identities = new Map();
    for (const entry of snapshot.entries) {
      if (entry.kind === "missing") { result[entry.path] = { kind: "missing" }; continue; }
      const info = entry.rawStat;
      const value = { kind: entry.kind, ...Object.fromEntries(["mode", "uid", "gid", "nlink", "rdev"]
        .map((key) => [key, Number(info[key])])) };
      if (entry.kind === "file") {
        value.size = Buffer.from(entry.bytesBase64, "base64").length;
        value.bytesBase64 = entry.bytesBase64;
        const identity = `${info.dev}:${info.ino}`;
        identities.set(identity, [...(identities.get(identity) ?? []), entry.path]);
      } else if (entry.kind === "symlink") value.target = entry.target;
      result[entry.path] = value;
    }
    return { manifest: result, hardlinks: [...identities.values()].filter((paths) => paths.length > 1)
      .map((paths) => paths.sort()).sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0) };
  }
  const before = manifest(raw.before), after = manifest(raw.after);
  const first = new Map(raw.before.entries.map((entry) => [entry.path, entry]));
  const last = new Map(raw.after.entries.map((entry) => [entry.path, entry]));
  const stable = first.size === last.size && [...first].every(([relative, left]) => {
    const right = last.get(relative);
    return right && left.kind === right.kind && (left.kind === "missing" ||
      writeStatFields.every((key) => left.rawStat[key] === right.rawStat[key]));
  });
  return { before: before.manifest, after: after.manifest,
    hardlinksBefore: before.hardlinks, hardlinksAfter: after.hardlinks,
    contentUnchanged: JSON.stringify(before) === JSON.stringify(after), writeStatsUnchanged: stable };
}

export function expandOwnedGetInput(value, base, configuration = false, requireOwned = false) {
  const original = value;
  for (const [token, name] of [["$WORKSPACE", "workspace"], ["$OUTSIDE", "outside"]]) {
    if (value === token || value.startsWith(`${token}/`)) {
      value = path.join(base, name) + value.slice(token.length);
      break;
    }
  }
  if (configuration || requireOwned || value !== original) {
    const checked = value.trim();
    if (configuration && (checked === "~" || checked.startsWith("~/") || checked.startsWith("~\\"))) {
      throw Error("Extra roots must remain within the complete owned fixture");
    }
    const relative = path.relative(base, path.resolve(base, "workspace", checked));
    if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw Error("Expanded get inputs must remain within their complete owned fixture");
    }
  }
  return value;
}

function ownedExtraPaths(values, base) {
  return values.map((value) => {
    if (typeof value === "string") return expandOwnedGetInput(value, base, true);
    if (value && typeof value === "object" && typeof value.path === "string") {
      return { ...structuredClone(value), path: expandOwnedGetInput(value.path, base, true) };
    }
    throw Error("Owned extra roots require a string path or path/pattern record");
  });
}

async function executeGetContractRuntime(input, runtimeConfig) {
  if (!runtimeConfig?.runtimeRoot || !path.isAbsolute(runtimeConfig.runtimeRoot) ||
      !runtimeConfig.evidenceDirectory || !path.isAbsolute(runtimeConfig.evidenceDirectory)) {
    throw Error("Authenticated absolute runtime and evidence directories are required");
  }
  if (input.kind !== "definition" && input.kind !== "tool") {
    throw Error("The protected get runtime accepts only definition or whole-tool fixtures");
  }
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-get-fixture-"));
  const raw = { kind: input.kind, fixtureBase: directory,
    nativeEnvelopes: [], nativeArguments: [], requests: [], indexManagerConstructed: false };
  const workspace = path.join(directory, "workspace");
  const outside = path.join(directory, "outside");
  if ((input.workspaceKind ?? "directory") === "directory") await fs.mkdir(workspace);
  else if (input.workspaceKind === "file") await fs.writeFile(workspace, "workspace is a regular file\n");
  else if (input.workspaceKind !== "missing") throw Error("Unknown owned workspace fixture kind");
  await fs.mkdir(outside);
  const prior = Object.fromEntries(["OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"].map((key) => [key, process.env[key]]));
  process.env.OPENCLAW_STATE_DIR = runtimeConfig.stateDirectory;
  process.env.OPENCLAW_CONFIG_PATH = runtimeConfig.configPath;
  function filename(relative, root = workspace) {
    if (typeof relative !== "string" || path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
      throw Error("Fixture paths must stay inside their owned workspace");
    }
    return path.join(root, relative);
  }
  async function prepareParent(absolute) {
    let current = directory;
    for (const name of path.relative(directory, path.dirname(absolute)).split(path.sep)) {
      if (!name) continue;
      current = path.join(current, name);
      try {
        if ((await fs.lstat(current)).isSymbolicLink()) throw Error("Fixture creation must not follow parent symlinks");
      } catch (error) { if (error.code === "ENOENT") await fs.mkdir(current); else throw error; }
    }
  }
  try {
    for (const relative of input.directories ?? []) await fs.mkdir(filename(relative), { recursive: true });
    for (const [relative, text] of Object.entries(input.files ?? {})) {
      const absolute = filename(relative);
      await prepareParent(absolute);
      await fs.writeFile(absolute, text, "utf8");
    }
    for (const [relative, octets] of Object.entries(input.fileBytes ?? {})) {
      if (!Array.isArray(octets) || octets.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) {
        throw Error("Byte fixtures require arrays of octets");
      }
      const absolute = filename(relative);
      await prepareParent(absolute);
      await fs.writeFile(absolute, Uint8Array.from(octets));
    }
    for (const [relative, text] of Object.entries(input.outsideFiles ?? {})) {
      const absolute = filename(relative, outside);
      await prepareParent(absolute);
      await fs.writeFile(absolute, text, "utf8");
    }
    for (const [relative, target] of Object.entries(input.symlinks ?? {})) {
      if (target.scope !== "workspace" && target.scope !== "outside") throw Error("Unknown fixture symlink scope");
      const absolute = filename(relative);
      await prepareParent(absolute);
      await fs.symlink(filename(target.path, target.scope === "outside" ? outside : workspace), absolute);
    }
    for (const [relative, target] of Object.entries(input.hardlinks ?? {})) {
      if (target.scope !== "workspace" && target.scope !== "outside") throw Error("Unknown fixture hardlink scope");
      const absolute = filename(relative);
      await prepareParent(absolute);
      await fs.link(filename(target.path, target.scope === "outside" ? outside : workspace), absolute);
    }
    if (input.observeFilesystem) raw.filesystem = { before: await snapshotGetFixture(directory) };
    const cfg = { agents: { defaults: { workspace,
      ...(Object.hasOwn(input.config ?? {}, "maxChars") ? { contextLimits: { memoryGetMaxChars: input.config.maxChars } } : {}),
    } }, memory: { search: {
      enabled: input.enabled !== false, provider: "none", fallback: "none",
      sources: input.indexSessions ? ["memory", "sessions"] : ["memory"],
      extraPaths: ownedExtraPaths(input.extraPaths ?? input.config?.extraPaths ?? [], directory),
      ...(input.indexSessions ? { experimental: { sessionMemory: true } } : {}),
    } } };
    if (input.supplements?.length) {
      const { m: register } = await imp("dist/memory-state-BmtUbXjH.mjs");
      for (const fixture of input.supplements) register(fixture.pluginId, {
        search: async () => [],
        get: async (query) => {
          raw.requests.push({ pluginId: fixture.pluginId, query });
          if (fixture.error !== undefined) throw Error(fixture.error);
          return structuredClone(Object.hasOwn(fixture.resultsByLookup ?? {}, query.lookup)
            ? fixture.resultsByLookup[query.lookup] : fixture.result ?? null);
        },
      });
    }
    const { createMemoryGetTool } = await imp("dist/tools-DotaQGXh.mjs");
    let liveConfig = input.missingConfig ? undefined : cfg;
    const tool = createMemoryGetTool({ config: liveConfig, getConfig: () => liveConfig,
      agentId: "main", ...structuredClone(input.options ?? {}) });
    if (input.kind === "definition") {
      const definition = tool ? { label: tool.label, name: tool.name,
        description: tool.description, parameters: tool.parameters } : null;
      raw.definition = definition;
      return { provider: "none", definition };
    }
    if (!tool) throw Error("The native memory get tool was unavailable");
    const steps = [];
    for (const [index, step] of input.steps.entries()) {
      liveConfig = step.missingConfig ? undefined : step.disableConfig
        ? { ...cfg, memory: { ...cfg.memory, search: { ...cfg.memory.search, enabled: false } } } : cfg;
      let result;
      let completed = false;
      try {
        const params = structuredClone(step.params);
        if (typeof params?.path === "string") params.path = expandOwnedGetInput(params.path, directory, false, input.observeFilesystem === true);
        raw.nativeArguments.push({ index, params: structuredClone(params) });
        result = await tool.execute(`fixture-${index}`, params);
        completed = true;
      } catch (error) {
        const value = { error: publicError(error) };
        raw.nativeEnvelopes.push({ index, ...value });
        steps.push(value);
      }
      if (completed) {
        raw.nativeEnvelopes.push({ index, result });
        steps.push({ result: decodeSearchToolEnvelope(result) });
      }
    }
    const result = { provider: "none", steps, requests: raw.requests };
    if (input.observeFilesystem) {
      raw.filesystem.after = await snapshotGetFixture(directory);
      result.filesystem = deriveGetFilesystemObservation(raw.filesystem);
    }
    return input.normalizeFixturePaths ? mapGetFixturePaths(result, directory) : result;
  } finally {
    await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    for (const [key, value] of Object.entries(prior)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}

export async function runGetContractRuntime(input, runtimeConfig) {
  if (input.kind !== "tool") throw Error("The get tool runtime accepts only genuine whole-tool fixtures");
  return await executeGetContractRuntime(input, runtimeConfig);
}

export async function runGetContractHelperRuntime(input, runtimeConfig) {
  if (input.kind !== "definition") throw Error("The get helper runtime accepts only genuine definition fixtures");
  return await executeGetContractRuntime(input, runtimeConfig);
}
