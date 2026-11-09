// Filesystem fixtures only: eligibility and ordering come from listMemoryFiles
// in the verified upstream tree. Named failures are injected at the OS boundary.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { syncBuiltinESMExports } from "node:module";

export async function runStorageDiscovery(input, importReference) {
  const { listMemoryFiles } = await importReference("packages/memory-host-sdk/src/host/internal.ts");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-discovery-"));
  const root = path.join(directory, "workspace");
  const relative = (value) => path.relative(root, value).replaceAll(path.sep, "/") || ".";
  const remove = async (value) => fs.rm(value, { force: true, recursive: true });
  const originalScan = fs.readdir;
  const originalStat = fs.lstat;
  const originalHome = os.homedir;
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
        throw Object.assign(new Error("injected filesystem failure"), { code: input.failure.code, path: value });
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
        return { files: (await listMemoryFiles(root, extraPaths, input.multimodal, callback)).map(relative),
          ...(callback ? { skippedSymlinkRoots: skipped } : {}) };
      } catch (error) {
        if (error.name !== "MemorySourceScanError") throw error;
        return { error: { type: error.name, code: error.code ?? null, path: relative(error.path) } };
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
    return { snapshots };
  } finally {
    fs.readdir = originalScan;
    fs.lstat = originalStat;
    os.homedir = originalHome;
    syncBuiltinESMExports();
    await remove(directory);
  }
}
