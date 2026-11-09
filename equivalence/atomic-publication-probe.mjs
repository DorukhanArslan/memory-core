// Uncredited development probe: original published commitMemoryContent only.
// Faults wrap actual IO methods; no publication algorithm or result is supplied.
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

Object.defineProperty(globalThis, "fetch", { configurable: false, writable: false,
  value: async () => { throw Error("Network is disabled in atomic publication development probes"); } });

const request = JSON.parse(fsSync.readFileSync(0, "utf8"));
const { input, directory, runtimeRoot } = request;
const root = path.join(directory, "workspace"), target = path.join(root, "MEMORY.md");
await fs.mkdir(root, { recursive: true });
if (input.initial !== null) {
  await fs.writeFile(target, input.initial); await fs.chmod(target, input.mode);
}
if (input.parentMode !== undefined) await fs.chmod(root, input.parentMode);
const { commitMemoryContent } = await import(pathToFileURL(path.join(runtimeRoot,
  "dist/short-term-promotion-memory-write-DLJgScco.mjs")).href);
const methods = ["open", "rename", "readFile", "stat", "lstat", "unlink", "mkdir", "chmod", "writeFile", "rm", "copyFile"];
const original = Object.fromEntries(methods.map((name) => [name, fs[name]]));
const raw = { request, pid: process.pid, calls: [], tempPaths: [] };
let result, armed = true;
const value = (item) => item instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(item).toString("hex") }
  : typeof item === "object" && item !== null && typeof item.fd === "number" ? { fd: item.fd }
  : item;
const fault = (stage, file) => {
  if (armed && input.fault?.stage === stage) {
    armed = false;
    raw.calls.push({ operation: "injected-error", stage, path: file, facts: input.fault });
    throw Object.assign(new Error(input.fault.message), { code: input.fault.code, path: file, syscall: stage });
  }
};
const errorEnvelope = (error) => {
  const observe = (value) => value instanceof Error ? errorEnvelope(value)
    : Array.isArray(value) ? value.map(observe) : value !== null && typeof value === "object"
      ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, observe(item)])) : value;
  const privateKeys = new Set(["name", "message", "stack", "code", "path", "cause", "publication", "errno", "syscall"]);
  return { name: error.name, message: error.message, code: error.code ?? null, path: error.path ?? null,
    publication: error.publication ?? null, cause: error.cause === undefined ? null : errorEnvelope(error.cause),
    ...Object.fromEntries(Object.getOwnPropertyNames(error).filter((key) => !privateKeys.has(key))
      .map((key) => [key, observe(error[key])])) };
};
const rawError = (error) => {
  const observe = (value) => value instanceof Error ? rawError(value) : Array.isArray(value) ? value.map(observe)
    : value !== null && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, observe(item)])) : value;
  return { type: error.constructor.name, name: error.name, message: error.message,
    properties: Object.fromEntries(Object.getOwnPropertyNames(error).map((key) => [key, observe(error[key])])) };
};
try {
  for (const name of methods) fs[name] = async (...args) => {
    raw.calls.push({ operation: name, arguments: args.map(value) });
    if (name === "rename") fault("rename-before", args[1]);
    if (name === "open" && args[1] === "wx") raw.tempPaths.push(String(args[0]));
    const returned = await original[name](...args);
    if (name === "open") {
      const filename = String(args[0]);
      for (const operation of ["write", "writeFile", "sync", "truncate", "chmod", "stat", "close"]) {
        const invoke = returned[operation].bind(returned);
        returned[operation] = async (...parameters) => {
          raw.calls.push({ operation: "handle." + operation, path: filename, fd: returned.fd, arguments: parameters.map(value) });
          if (operation === "sync" && raw.tempPaths.includes(filename)) fault("temp-sync", filename);
          if (operation === "sync" && filename === root) fault("parent-sync", filename);
          if (operation === "sync" && args[1] === "r+") fault("fallback-sync", filename);
          if (operation === "writeFile" && args[1] === "r+" && input.fault?.stage === "fallback-write-partial" && armed) {
            const bytes = Buffer.from(parameters[0], "utf8").subarray(0, input.partialBytes);
            await returned.write(bytes, 0, bytes.length, 0);
            fault("fallback-write-partial", filename);
          }
          return await invoke(...parameters);
        };
      }
    }
    if (name === "rename") {
      fault("rename-after", args[1]);
      if (input.fault?.stage === "published-replaced" && armed) {
        armed = false;
        await original.writeFile(args[1], input.external);
        raw.calls.push({ operation: "external-write-after-rename", path: args[1], text: input.external });
      }
      if (input.fault?.stage === "published-renamed" && armed) {
        armed = false;
        const external = path.join(root, "external-next");
        await original.writeFile(external, input.external);
        await original.rename(external, args[1]);
        raw.calls.push({ operation: "external-rename-after-rename", from: external, path: args[1], text: input.external });
      }
    }
    return returned;
  };
  const parameters = { filePath: target, tempPrefix: ".MEMORY.atomic-probe", content: input.replacement,
    expectedContent: input.initial ?? "", expectedHash: (await import("node:crypto")).createHash("sha256").update(input.initial ?? "").digest("hex"),
    allowInPlaceFallback: input.allowInPlaceFallback === true };
  raw.commitRequest = parameters;
  const returned = await commitMemoryContent(parameters);
  result = { status: "fulfilled", returned: returned ?? null };
} catch (error) {
  raw.exception = rawError(error);
  result = { status: "rejected", error: errorEnvelope(error) };
} finally {
  for (const name of methods) fs[name] = original[name];
}
raw.faultConsumed = !armed;
const files = [];
for (const name of (await fs.readdir(root)).sort()) {
  const filename = path.join(root, name), info = await fs.lstat(filename);
  files.push({ path: filename, mode: info.mode & 0o7777, kind: info.isFile() ? "file" : info.isSymbolicLink() ? "symlink" : "other",
    ...(info.isFile() ? { bytes: (await fs.readFile(filename)).toString("hex") } : {}) });
}
raw.result = { ...result, files };
process.stdout.write(JSON.stringify({ result: raw.result, raw }) + "\n");
