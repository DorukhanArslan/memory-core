// Fixture-only adapter. The actual read policy and results are from pinned TS.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

async function snapshot(base) {
  const values = {};
  async function visit(directory) {
    for (const name of await fs.readdir(directory)) {
      const target = path.join(directory, name);
      const info = await fs.lstat(target);
      const key = path.relative(base, target).replaceAll(path.sep, "/");
      if (info.isSymbolicLink()) values[key] = `symlink:${await fs.readlink(target)}`;
      else if (info.isFile()) values[key] = "file:" + crypto.createHash("sha256").update(await fs.readFile(target)).digest("hex");
      else if (info.isDirectory()) { values[key] = "directory"; await visit(target); }
      else if (info.isFIFO()) values[key] = "fifo";
      else values[key] = `special:${info.mode & 0o170000}`;
    }
  }
  await visit(base);
  return Object.fromEntries(Object.entries(values).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
}

export async function runStoragePaths(input, importReference) {
  const { readMemoryFile } = await importReference("packages/memory-host-sdk/src/host/read-file.ts");
  const base = await fs.mkdtemp(path.join(os.tmpdir(), "memory-core-read-paths-"));
  const root = path.join(base, "workspace");
  try {
    for (const entry of input.entries) {
      const target = path.join(base, entry.path);
      await fs.mkdir(path.dirname(target), { recursive: true });
      switch (entry.kind) {
        case "file": await fs.writeFile(target, entry.text, "utf8"); break;
        case "directory": await fs.mkdir(target, { recursive: true }); break;
        case "symlink": await fs.symlink(entry.target, target); break;
        case "hardlink": await fs.link(path.join(base, entry.target), target); break;
        case "fifo": await promisify(execFile)("mkfifo", [target], { timeout: 10000 }); break;
        default: throw Error(`Unsupported read fixture kind: ${entry.kind}`);
      }
    }
    const before = await snapshot(base);
    const reads = [];
    for (const request of input.requests) {
      const rawPath = request.replaceAll("@workspace", root).replaceAll("@outside", path.join(base, "outside"));
      try {
        reads.push({ ok: true, result: await readMemoryFile({ workspaceDir: root, relPath: rawPath }) });
      } catch (error) {
        reads.push({ ok: false, error: {
          message: error.message.replaceAll(base, "@fixture"), code: error.code ?? null,
        }});
      }
    }
    return { reads, filesUnchanged: JSON.stringify(before) === JSON.stringify(await snapshot(base)) };
  } finally {
    await fs.rm(base, { recursive: true, force: true });
  }
}
