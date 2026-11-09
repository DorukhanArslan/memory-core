// Genuine original Root.append and publishBootstrapFile development observations.
// The parent arranges filesystem inputs and per-process resource limits first.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

Object.defineProperty(globalThis, "fetch", { configurable: false, writable: false,
  value: async () => { throw Error("Network disabled in atomic Root development probes"); } });
const request = JSON.parse(fsSync.readFileSync(0, "utf8"));
const { input, directory, runtimeRoot } = request;
process.umask(input.umask);
const root = path.join(directory, "workspace"), target = path.join(root, input.path);
const ownedRoot = path.resolve(root);
const rawValue = (value) => {
  if (value instanceof Error) return { name: value.name, message: value.message,
    own: Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, rawValue(value[key])])) };
  if (Array.isArray(value)) return value.map(rawValue);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rawValue(item)]));
  return typeof value === "bigint" ? { type: "bigint", decimal: String(value) } : value;
};
const errorEnvelope = (error) => {
  const observe = (value) => value instanceof Error ? errorEnvelope(value)
    : Array.isArray(value) ? value.map(observe) : value !== null && typeof value === "object"
      ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, observe(item)]))
      : typeof value === "bigint" ? { type: "bigint", decimal: String(value) } : value;
  const privateKeys = new Set(["name", "message", "stack", "code", "path", "cause", "errno", "syscall"]);
  return { name: error.name, message: error.message, code: error.code ?? null, path: error.path ?? null,
    cause: error.cause === undefined ? null : errorEnvelope(error.cause),
    ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) => !privateKeys.has(key))
      .map((key) => [key, observe(error[key])])) };
};
const raw = { request, pid: process.pid, runtime: { execPath: process.execPath, version: process.version },
  umask: process.umask(), actualOwner: null, calls: [] };
const promiseOriginal = { open: fs.open };
const syncOriginal = { write: fsSync.write, fsyncSync: fsSync.fsyncSync, readlinkSync: fsSync.readlinkSync };
let armed = input.fault !== undefined;
const fdPath = (fd) => {
  try { return syncOriginal.readlinkSync(`/proc/self/fd/${fd}`); } catch { return null; }
};
const ownedFd = (fd) => { const filename = fdPath(fd); return filename !== null && (filename === ownedRoot || filename.startsWith(ownedRoot + path.sep)); };
const failure = (stage) => {
  armed = false;
  raw.calls.push({ operation: "injected-error", stage, facts: input.fault });
  return Object.assign(new Error(input.fault.message), { code: input.fault.code });
};
function installIoObservation() {
  fsSync.fsyncSync = (fd) => {
    if (ownedFd(fd)) {
      const stage = fsSync.fstatSync(fd).isDirectory() ? "parent-sync" : "file-sync";
      raw.calls.push({ operation: "fsyncSync", fd, path: fdPath(fd), stage });
      if (armed && input.fault.stage === stage) throw failure(stage);
    }
    return syncOriginal.fsyncSync(fd);
  };
  fsSync.write = (fd, buffer, offset, length, position, callback) => {
    if (!ownedFd(fd)) return syncOriginal.write(fd, buffer, offset, length, position, callback);
    raw.calls.push({ operation: "write", fd, path: fdPath(fd), offset, length, position,
      bytes: Buffer.from(buffer).subarray(offset, offset + length).toString("hex") });
    if (armed && input.fault.stage === "write-zero") {
      armed = false;
      raw.calls.push({ operation: "injected-zero-progress-write", stage: "write-zero" });
      return queueMicrotask(() => callback(null, 0, buffer));
    }
    if (armed && input.fault.stage === "write-partial") {
      return syncOriginal.write(fd, buffer, offset, Math.min(2, length), position, (error, written) => {
        raw.calls.push({ operation: "partial-write-return", written, error: error === null ? null : rawValue(error) });
        callback(error ?? failure("write-partial"), written, buffer);
      });
    }
    return syncOriginal.write(fd, buffer, offset, length, position, callback);
  };
  fs.open = async (...args) => {
    const handle = await promiseOriginal.open(...args);
    if (!ownedFd(handle.fd)) return handle;
    raw.calls.push({ operation: "open", arguments: args, fd: handle.fd, path: fdPath(handle.fd) });
    for (const operation of ["write", "sync", "close"]) {
      const invoke = handle[operation].bind(handle), filename = fdPath(handle.fd);
      handle[operation] = async (...parameters) => {
        raw.calls.push({ operation: "handle." + operation, fd: handle.fd, path: filename,
          arguments: parameters.map(rawValue) });
        const stage = operation === "sync" ? fsSync.fstatSync(handle.fd).isDirectory() ? "parent-sync" : "file-sync" : null;
        if (armed && stage !== null && input.fault.stage === stage) throw failure(stage);
        if (armed && operation === "write" && input.fault.stage === "write-zero") {
          armed = false;
          raw.calls.push({ operation: "injected-zero-progress-write", stage: "write-zero" });
          return { bytesWritten: 0, buffer: parameters[0] };
        }
        if (armed && operation === "write" && input.fault.stage === "write-partial") {
          const written = await invoke(parameters[0], parameters[1] ?? 0, Math.min(2, parameters[2] ?? parameters[0].length), parameters[3] ?? null);
          raw.calls.push({ operation: "partial-write-return", result: written });
          throw failure("write-partial");
        }
        return await invoke(...parameters);
      };
    }
    return handle;
  };
}
let observed;
try {
  const { getNativeBinding } = await import(pathToFileURL(path.join(runtimeRoot, "../@openclaw/fs-safe/dist/native.js")).href);
  const nativeBinding = getNativeBinding();
  raw.defaultNativeBinding = { available: nativeBinding !== undefined,
    ownerFunctions: nativeBinding === undefined ? [] : Object.keys(nativeBinding).filter((key) => typeof nativeBinding[key] === "function").sort() };
  let returned;
  if (input.operation === "bootstrap-create") {
    const { u: publishBootstrapFile } = await import(pathToFileURL(path.join(runtimeRoot, "dist/workspace-C0LMBmap.mjs")).href);
    raw.actualOwner = "workspace-C0LMBmap.mjs:publishBootstrapFile";
    installIoObservation();
    returned = await publishBootstrapFile(target, input.data);
  } else if (input.operation === "append") {
    const { root: openRoot } = await import(pathToFileURL(path.join(runtimeRoot, "../@openclaw/fs-safe/dist/root.js")).href);
    raw.actualOwner = "@openclaw/fs-safe:Root.append";
    const owner = await openRoot(root);
    installIoObservation();
    returned = await owner.append(input.path, input.data, { mkdir: true, prependNewlineIfNeeded: true });
  } else throw Error("Unknown literal Root development operation");
  observed = { status: "fulfilled", returned: returned ?? null };
} catch (error) {
  raw.exception = rawValue(error);
  observed = { status: "rejected", error: errorEnvelope(error) };
} finally {
  fs.open = promiseOriginal.open;
  fsSync.write = syncOriginal.write;
  fsSync.fsyncSync = syncOriginal.fsyncSync;
}
raw.faultConsumed = input.fault === undefined ? null : !armed;
const files = [];
async function snapshot(directory) {
  for (const name of (await fs.readdir(directory)).sort()) {
    const filename = path.join(directory, name), info = await fs.lstat(filename, { bigint: true });
    files.push({ path: filename, kind: info.isFile() ? "file" : info.isDirectory() ? "directory" : "other",
      mode: Number(info.mode & 0o7777n), identity: { dev: String(info.dev), ino: String(info.ino), nlink: String(info.nlink) },
      ...(info.isFile() ? { bytes: (await fs.readFile(filename)).toString("hex") } : {}) });
    if (info.isDirectory()) await snapshot(filename);
  }
}
await snapshot(root);
raw.files = files;
// Physical inode identities are private observations, not interchangeable IDs.
const result = { ...observed, files: files.map(({ identity, ...file }) => file) };
process.stdout.write(JSON.stringify({ result, raw }) + "\n");
