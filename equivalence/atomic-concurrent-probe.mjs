// Development-only genuine concurrent writers. Barriers hold completed real IO,
// never a replacement publisher or a supplied expected outcome.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

Object.defineProperty(globalThis, "fetch", { configurable: false, writable: false,
  value: async () => { throw Error("Network disabled in concurrent atomic development probes"); } });
const { input, directory, runtimeRoot } = JSON.parse(fsSync.readFileSync(0, "utf8"));
const root = path.join(directory, "workspace"), target = path.join(root, input.path);
const raw = { input, directory, pid: process.pid, calls: [], temporaryPaths: [] };
const scope = new AsyncLocalStorage();
const originals = { open: fs.open, stat: fs.stat, lstat: fs.lstat, write: fsSync.write, readlinkSync: fsSync.readlinkSync };
let completed = false;
process.once("beforeExit", () => {
  if (!completed) process.stderr.write(JSON.stringify({ incomplete: true, raw }) + "\n");
});
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const stages = Object.fromEntries(input.writers.map(({ id }) => [id, { ready: deferred(), release: deferred() }]));
const observe = (value) => value instanceof Error ? { name: value.name, message: value.message,
  own: Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, observe(value[key])])) }
  : Array.isArray(value) ? value.map(observe) : value !== null && typeof value === "object"
    ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, observe(item)]))
    : typeof value === "bigint" ? { type: "bigint", decimal: String(value) } : value;
const errorEnvelope = (error) => {
  const nested = (value) => value instanceof Error ? errorEnvelope(value) : Array.isArray(value) ? value.map(nested)
    : value !== null && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, nested(item)]))
      : typeof value === "bigint" ? { type: "bigint", decimal: String(value) } : value;
  const privateKeys = new Set(["name", "message", "stack", "code", "path", "cause", "errno", "syscall"]);
  return { name: error.name, message: error.message, code: error.code ?? null, path: error.path ?? null,
    cause: error.cause === undefined ? null : errorEnvelope(error.cause),
    ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) => !privateKeys.has(key)).map((key) => [key, nested(error[key])])) };
};
const settled = async (writer, invoke) => scope.run(writer.id, async () => {
  raw.calls.push({ operation: "writer-start", id: writer.id });
  try {
    const returned = await invoke();
    raw.calls.push({ operation: "writer-fulfilled", id: writer.id, returned: returned ?? null });
    return { id: writer.id, status: "fulfilled", returned: returned ?? null };
  } catch (error) {
    raw.calls.push({ operation: "writer-rejected", id: writer.id, exception: observe(error) });
    return { id: writer.id, status: "rejected", error: errorEnvelope(error) };
  }
});
let outcomes;
try {
  if (input.operation === "replace") {
    const { commitMemoryContent } = await import(pathToFileURL(path.join(runtimeRoot, "dist/short-term-promotion-memory-write-DLJgScco.mjs")).href);
    let held = false;
    const secondStat = deferred();
    fs.stat = async (...args) => {
      const result = await originals.stat(...args);
      raw.calls.push({ operation: "stat", id: scope.getStore(), path: String(args[0]) });
      if (scope.getStore() === "second" && String(args[0]) === root) secondStat.resolve();
      return result;
    };
    fs.open = async (...args) => {
      const handle = await originals.open(...args);
      raw.calls.push({ operation: "open", id: scope.getStore(), arguments: args, fd: handle.fd });
      if (args[1] === "wx") {
        raw.temporaryPaths.push(String(args[0]));
        if (scope.getStore() === "first" && !held) {
          held = true;
          stages.first.ready.resolve();
          await stages.first.release.promise;
        }
      }
      return handle;
    };
    const invoke = (writer) => settled(writer, () => commitMemoryContent({ filePath: target, content: writer.data,
      expectedContent: input.initial, expectedHash: createHash("sha256").update(input.initial).digest("hex"),
      tempPrefix: ".MEMORY.concurrent-probe" }));
    const first = invoke(input.writers[0]);
    await stages.first.ready.promise;
    const second = invoke(input.writers[1]);
    await secondStat.promise;
    stages.first.release.resolve();
    outcomes = await Promise.all([first, second]);
  } else if (input.operation === "bootstrap-create") {
    const { u: publishBootstrapFile } = await import(pathToFileURL(path.join(runtimeRoot, "dist/workspace-C0LMBmap.mjs")).href);
    const held = new Set();
    fs.lstat = async (...args) => {
      try { return await originals.lstat(...args); }
      catch (error) {
        raw.calls.push({ operation: "lstat-rejected", id: scope.getStore(), path: String(args[0]), error: observe(error) });
        if (scope.getStore() === "second" && String(args[0]) === target) stages.second.ready.resolve();
        throw error;
      }
    };
    fsSync.write = (fd, buffer, offset, length, position, callback) => {
      const id = scope.getStore();
      if (!stages[id]) return originals.write(fd, buffer, offset, length, position, callback);
      const filename = originals.readlinkSync(`/proc/self/fd/${fd}`);
      raw.calls.push({ operation: "write", id, fd, path: filename, offset, length, position,
        bytes: Buffer.from(buffer).subarray(offset, offset + length).toString("hex") });
      if (!raw.temporaryPaths.includes(filename)) raw.temporaryPaths.push(filename);
      return originals.write(fd, buffer, offset, length, position, (error, written, returned) => {
        raw.calls.push({ operation: "write-return", id, error: error ? observe(error) : null, written });
        if (id !== "first" || held.has(id)) return callback(error, written, returned);
        held.add(id);
        stages[id].ready.resolve();
        stages[id].release.promise.then(() => callback(error, written, returned));
      });
    };
    const first = settled(input.writers[0], () => publishBootstrapFile(target, input.writers[0].data));
    await stages.first.ready.promise;
    const second = settled(input.writers[1], () => publishBootstrapFile(target, input.writers[1].data));
    await stages.second.ready.promise;
    raw.calls.push({ operation: "second-precheck-missing-first-complete-stage-held", targetExists: fsSync.existsSync(target) });
    stages.first.release.resolve();
    const firstResult = await first;
    outcomes = [firstResult, await second];
  } else throw Error("Unknown literal concurrent operation");
} finally {
  fs.open = originals.open;
  fs.stat = originals.stat;
  fs.lstat = originals.lstat;
  fsSync.write = originals.write;
}
const files = [];
for (const name of (await fs.readdir(root)).sort()) {
  const filename = path.join(root, name), info = await fs.lstat(filename, { bigint: true });
  files.push({ path: filename, kind: info.isFile() ? "file" : "other", mode: Number(info.mode & 0o7777n),
    identity: { dev: String(info.dev), ino: String(info.ino), nlink: String(info.nlink) },
    ...(info.isFile() ? { bytes: (await fs.readFile(filename)).toString("hex") } : {}) });
}
raw.files = files;
completed = true;
process.stdout.write(JSON.stringify({ result: { outcomes, files: files.map(({ identity, ...file }) => file) }, raw }) + "\n");
