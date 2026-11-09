// Filesystem fixtures only: eligibility and ordering come from listMemoryFiles
// in the verified upstream tree. Named failures are injected at the OS boundary.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { syncBuiltinESMExports } from "node:module";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";

const errorEnvelope = (error) => ({ type: error.name, message: error.message,
  code: error.code ?? null, path: error.path ?? null,
  cause: error.cause === undefined ? null : errorEnvelope(error.cause) });

function rawError(error) {
  const rawValue = (value) => {
    if (value instanceof Error) return rawError(value);
    if (value === undefined) return { kind: "undefined" };
    if (value === null || typeof value !== "object") return value;
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rawValue(item)]));
  };
  return { type: error.constructor.name, name: error.name, message: error.message,
    properties: Reflect.ownKeys(error).map((key) => {
      const descriptor = Object.getOwnPropertyDescriptor(error, key);
      return { key: String(key), enumerable: descriptor.enumerable, configurable: descriptor.configurable,
        kind: "value" in descriptor ? "data" : "accessor",
        ...("value" in descriptor ? { writable: descriptor.writable } : {
          get: descriptor.get ? { name: descriptor.get.name, source: String(descriptor.get) } : null,
          set: descriptor.set ? { name: descriptor.set.name, source: String(descriptor.set) } : null,
        }), value: rawValue(Reflect.get(error, key)) };
    }) };
}

export async function runStorageDiscovery(input, importReference, { recordDiagnostic } = {}) {
  const { listMemoryFiles } = await importReference("packages/memory-host-sdk/src/host/internal.ts");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-discovery-"));
  const root = path.join(directory, "workspace");
  const relative = (value) => path.relative(root, value).replaceAll(path.sep, "/") || ".";
  const remove = async (value) => fs.rm(value, { force: true, recursive: true });
  const originalScan = fs.readdir;
  const originalStat = fs.lstat;
  const originalHome = os.homedir;
  const raw = { kind: "storage-discovery", fixtureBase: directory, workspaceRoot: root,
    input: structuredClone(input), snapshots: [] };
  try {
    switch (input.workspaceKind) {
      case "missing": break;
      case "file": await fs.writeFile(root, "not a directory"); break;
      case "symlink-loop": await fs.symlink(root, root); break;
      default: {
        await fs.mkdir(root);
        for (const name of input.dirs ?? []) await fs.mkdir(path.join(root, name), { recursive: true });
        for (const [name, text] of Object.entries(input.files ?? {})) {
          const destination = path.join(root, name);
          await fs.mkdir(path.dirname(destination), { recursive: true });
          await fs.writeFile(destination, text, "utf8");
        }
        for (const name of input.fifos ?? []) {
          const destination = path.join(root, name);
          await fs.mkdir(path.dirname(destination), { recursive: true });
          await promisify(execFile)("mkfifo", [destination]);
        }
        for (const [field, operation] of [["symlinks", fs.symlink], ["hardlinks", fs.link]]) {
          for (const [name, target] of Object.entries(input[field] ?? {})) {
            const destination = path.join(root, name);
            await fs.mkdir(path.dirname(destination), { recursive: true });
            await operation(path.join(root, target), destination);
          }
        }
      }
    }
    async function inject(operation, value) {
      if (operation === "scan" && input.removeOnScan && value === path.join(root, input.removeOnScan)) {
        await remove(value);
      }
      if (input.failure && operation === input.failure.operation && value === path.join(root, input.failure.path)) {
        throw Object.assign(new Error(input.failure.message), { code: input.failure.code, path: value });
      }
    }
    fs.readdir = async function(value, ...arguments_) {
      await inject("scan", value);
      return originalScan.call(this, value, ...arguments_);
    };
    fs.lstat = async function(value, ...arguments_) {
      await inject("stat", value);
      return originalStat.call(this, value, ...arguments_);
    };
    async function snapshot() {
      try {
        const extraPaths = (input.extraPaths ?? []).map((entry) => typeof entry === "string"
          ? entry.replaceAll("$FIXTURE", directory)
          : { ...entry, path: entry.path.replaceAll("$FIXTURE", directory) });
        const skipped = [];
        const callback = input.captureSkippedSymlinkRoots ? (value) => skipped.push(relative(value)) : undefined;
        const result = { files: (await listMemoryFiles(root, extraPaths, input.multimodal, callback)).map(relative),
          ...(callback ? { skippedSymlinkRoots: skipped } : {}) };
        raw.snapshots.push({ result: structuredClone(result) });
        return result;
      } catch (error) {
        if (error.name !== "MemorySourceScanError") throw error;
        const result = { error: errorEnvelope(error) };
        raw.snapshots.push({ result: structuredClone(result), exception: rawError(error) });
        return result;
      }
    }
    if (input.homeRoot) {
      os.homedir = () => path.join(directory, "home");
      syncBuiltinESMExports();
    }
    const snapshots = [await snapshot()];
    for (const step of input.steps ?? []) {
      for (const name of step.remove ?? []) await remove(path.join(root, name));
      for (const [previous, current] of Object.entries(step.rename ?? {})) {
        await fs.mkdir(path.dirname(path.join(root, current)), { recursive: true });
        await fs.rename(path.join(root, previous), path.join(root, current));
      }
      snapshots.push(await snapshot());
    }
    const result = { snapshots };
    raw.result = structuredClone(result);
    recordDiagnostic?.(raw);
    return mapGetFixturePaths(result, directory);
  } finally {
    fs.readdir = originalScan;
    fs.lstat = originalStat;
    os.homedir = originalHome;
    syncBuiltinESMExports();
    await remove(directory);
  }
}
