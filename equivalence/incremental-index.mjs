// Source fixture transport only. Every native source fingerprint comes from
// the exact pinned buildFileEntry implementation; no sync algorithm is copied.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

export async function runIncrementalIndex(input, importReference) {
  const { buildFileEntry } = await importReference("packages/memory-host-sdk/src/host/internal.ts");
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-source-snapshot-"));
  const remove = async (relative) => fs.rm(path.join(root, relative), { force: true, recursive: true });
  async function arrange(entries) {
    for (const entry of entries) {
      const destination = path.join(root, entry.path);
      await fs.mkdir(path.dirname(destination), { recursive: true });
      switch (entry.kind) {
        case "file":
          await fs.writeFile(destination, Buffer.from(entry.dataBase64, "base64"));
          await fs.utimes(destination, input.mtimeMs / 1000, input.mtimeMs / 1000);
          break;
        case "directory": await fs.mkdir(destination); break;
        case "symlink": await fs.symlink(entry.target, destination); break;
        case "hardlink": await fs.link(path.join(root, entry.target), destination); break;
        case "fifo": await promisify(execFile)("mkfifo", [destination]); break;
        default: throw Error(`Unsupported source fixture entry: ${entry.kind}`);
      }
    }
  }
  async function snapshot() {
    const entries = [];
    for (const relative of input.requests) {
      const source = await buildFileEntry(path.join(root, relative), root);
      const entry = source === null ? null : {
        path: source.path, hash: source.hash, size: source.size,
        mtimeMs: source.mtimeMs, kind: source.kind,
      };
      entries.push({ request: relative, entry });
    }
    return { entries };
  }
  try {
    await arrange(input.entries);
    const snapshots = [await snapshot()];
    for (const step of input.steps ?? []) {
      for (const relative of step.remove ?? []) await remove(relative);
      for (const [previous, current] of Object.entries(step.rename ?? {})) {
        await fs.mkdir(path.dirname(path.join(root, current)), { recursive: true });
        await fs.rename(path.join(root, previous), path.join(root, current));
      }
      for (const relative of step.mkdir ?? []) await fs.mkdir(path.join(root, relative), { recursive: true });
      await arrange(step.write ?? []);
      snapshots.push(await snapshot());
    }
    return { snapshots };
  } finally {
    await fs.rm(root, { force: true, recursive: true });
  }
}
