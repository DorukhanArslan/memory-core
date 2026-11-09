// Protected original atomic owners over literal files and delegated IO faults.
// This adapter supplies no publication, rollback, append or settlement algorithm.
import fs from "node:fs/promises";
import syncFs from "node:fs";
import path from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
import { threadId } from "node:worker_threads";
import { pathToFileURL } from "node:url";
import { publicAtomicError, rawAtomicError, encodeAtomicPublic } from "./atomic-publication-codec.mjs";

const statFields = ["dev", "ino", "mode", "nlink", "size", "uid", "gid", "mtimeNs", "ctimeNs"];
const fullStat = (stat) => Object.fromEntries(statFields.map((key) => [key, String(stat[key])]));
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
function jsonValue(value, seen = new WeakSet()) {
  if (value === undefined) return { type: "undefined" };
  if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
  if (value instanceof Error) return rawAtomicError(value);
  if (value instanceof Date) return { type: "Date", value: value.toISOString() };
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) return { type: "bytes", bytes: Array.from(value) };
  if (typeof value === "function") return { type: "function", name: value.name };
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return { type: "repeated-reference" };
  seen.add(value);
  try {
    if (Array.isArray(value)) return value.map((entry) => jsonValue(entry, seen));
    if (typeof value.fd === "number") return { fd: value.fd };
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, jsonValue(item, seen)]));
  } finally { seen.delete(value); }
}

class AtomicIoObservation {
  constructor(input, raw, subject, target, binding) {
    this.input = input; this.raw = raw; this.subject = subject; this.target = target; this.binding = binding;
    this.scope = new AsyncLocalStorage(); this.descriptors = new Map(); this.attempts = new Map();
    this.original = { promises: {}, sync: {}, binding: {} }; this.restores = []; this.preimageReadArmed = false;
    this.candidates = input.faults.map(() => 0); this.stageCounter = 0; this.attemptCounter = 0;
    this.gates = { first: { ready: deferred(), release: deferred() }, second: { ready: deferred(), release: deferred() } };
    this.concurrencyHeld = false;
    for (const name of ["open", "readFile", "writeFile", "rename", "unlink", "stat", "lstat", "mkdir", "chmod", "rm", "readdir", "readlink"])
      this.original.promises[name] = fs[name];
    for (const name of ["fstatSync", "lstatSync", "statSync", "readlinkSync", "fsyncSync", "fchmodSync", "closeSync", "write", "writeSync", "renameSync", "unlinkSync", "openSync", "readSync"])
      this.original.sync[name] = syncFs[name];
  }
  owned(candidate) {
    if (typeof candidate !== "string" && !Buffer.isBuffer(candidate) && !(candidate instanceof URL)) return false;
    const name = candidate instanceof URL ? candidate.pathname : String(candidate);
    const absolute = path.resolve(name);
    return absolute === this.subject || absolute.startsWith(this.subject + path.sep);
  }
  fdPath(fd) {
    try { return this.original.sync.readlinkSync(`/proc/self/fd/${fd}`); }
    catch { return this.descriptors.get(fd)?.path ?? null; }
  }
  fdStat(fd) {
    try { return fullStat(this.original.sync.fstatSync(fd, { bigint: true })); }
    catch { return null; }
  }
  fdRecord(fd) {
    const known = this.descriptors.get(fd), filename = this.fdPath(fd);
    if (known) return { ...known, actualPath: filename, stat: this.fdStat(fd) };
    if (!filename || !this.owned(filename)) return null;
    const stat = this.fdStat(fd);
    const role = filename === this.target ? "target" : stat && (Number(stat.mode) & syncFs.constants.S_IFMT) === syncFs.constants.S_IFDIR ? "parent" : "stage";
    return { path: filename, actualPath: filename, role, stat };
  }
  pathRole(filename) {
    const absolute = path.resolve(String(filename));
    if (absolute === this.target) return "target";
    if ([...this.descriptors.values()].some((record) => record.path === absolute && record.role === "stage")) return "stage";
    if (this.raw.stageAllocations.some((record) => record.path === absolute) || this.raw.exclusiveAttempts.some((record) => record.path === absolute)) return "stage";
    return "parent";
  }
  event(operation, role, when, details = {}) {
    const event = { seq: this.raw.ioEvents.length + 1, actor: this.scope.getStore() ?? "write", operation, role, when, ...details };
    this.raw.ioEvents.push(event); return event;
  }
  makeError(fault) {
    const error = new Error(fault.message);
    if (fault.code !== null) error.code = fault.code;
    for (const key of ["errno", "syscall", "path", "dest"]) if (Object.hasOwn(fault, key)) error[key] = fault[key];
    return error;
  }
  chooseFault(operation, role) {
    for (let index = 0; index < this.input.faults.length; index += 1) {
      const fault = this.input.faults[index];
      if (fault.operation !== operation || fault.role !== role || this.raw.faults[index].matched) continue;
      this.candidates[index] += 1;
      if (this.candidates[index] === fault.occurrence) return { index, fault };
    }
    return null;
  }
  consume(selected, event, details = {}) {
    const injected = this.event("fault", selected.fault.role, "after", {
      path: event.path, ...(event.fd === undefined ? {} : { fd: event.fd }),
      arguments: { input: structuredClone(selected.fault), ioEvent: event.seq }, ...details,
    });
    this.raw.faults[selected.index].matched += 1;
    this.raw.faults[selected.index].events.push(injected.seq);
    return injected;
  }
  reject(selected, event) {
    const error = this.makeError(selected.fault);
    this.consume(selected, event, { error: publicAtomicError(error), rawError: rawAtomicError(error) });
    return error;
  }
  fixtureMutation(selected, event) {
    const fault = selected.fault;
    const filename = fault.effect === "replace-stage" ? event.path : this.target;
    if (!this.owned(filename)) throw Error("Atomic external mutation escaped its declared subject");
    const invoke = (method, args) => {
      const before = this.event("fixture." + method, fault.role, "before", { path: filename,
        arguments: { method: "node:fs." + method, args: jsonValue(args) } });
      try {
        const result = this.original.sync[method](...args);
        this.event("fixture." + method, fault.role, "after", { path: filename, call: before.seq,
          arguments: before.arguments, result: jsonValue(result) }); return result;
      } catch (error) {
        this.event("fixture." + method, fault.role, "after", { path: filename, call: before.seq,
          arguments: before.arguments, error: publicAtomicError(error), rawError: rawAtomicError(error) }); throw error;
      }
    };
    if (fault.effect === "external-inplace") {
      const fd = invoke("openSync", [filename, syncFs.constants.O_WRONLY | syncFs.constants.O_TRUNC]);
      try { invoke("writeSync", [fd, Buffer.from(fault.externalContent), 0, Buffer.byteLength(fault.externalContent), 0]); }
      finally { invoke("closeSync", [fd]); }
    } else {
      const staged = fault.effect === "replace-stage" ? filename : path.join(path.dirname(this.target), "external-replacement-0");
      if (fault.effect === "replace-stage") invoke("renameSync", [filename, path.join(path.dirname(filename), "parked-stage-0")]);
      const fd = invoke("openSync", [staged, syncFs.constants.O_WRONLY | syncFs.constants.O_CREAT | syncFs.constants.O_EXCL,
        fault.effect === "replace-stage" ? 0o600 : 0o666]);
      try { invoke("writeSync", [fd, Buffer.from(fault.externalContent), 0, Buffer.byteLength(fault.externalContent), 0]); }
      finally { invoke("closeSync", [fd]); }
      if (fault.effect === "external-replace") invoke("renameSync", [staged, filename]);
    }
    this.consume(selected, event, { result: { effect: fault.effect } });
  }
  afterEffect(selected, event) {
    if (!selected) return;
    if (selected.fault.effect === "reject-after") throw this.reject(selected, event);
    if (["external-inplace", "external-replace"].includes(selected.fault.effect)) this.fixtureMutation(selected, event);
  }
  synchronous(operation, role, method, args, invoke, details = {}) {
    const before = this.event(operation, role, "before", { arguments: { method, args: jsonValue(args) }, ...details });
    const selected = this.chooseFault(operation, role);
    let terminalRecorded = false;
    try {
      if (selected?.fault.effect === "replace-stage") this.fixtureMutation(selected, before);
      if (selected?.fault.effect === "reject-before") throw this.reject(selected, before);
      let result;
      if (selected?.fault.effect === "zero-write") {
        this.consume(selected, before, { result: 0 }); result = 0;
      } else if (selected?.fault.effect === "partial-write") {
        const partial = [...args]; partial[3] = Math.min(selected.fault.bytes, args[3]);
        before.arguments.requestedArgs = jsonValue(args);
        before.arguments.delegatedArgs = jsonValue(partial);
        result = invoke(partial);
        this.event(operation, role, "after", { call: before.seq, arguments: before.arguments,
          ...details, delegatedArguments: jsonValue(partial), result: jsonValue(result), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
        terminalRecorded = true;
        throw this.reject(selected, before);
      } else result = invoke(args);
      const after = this.event(operation, role, "after", { call: before.seq, arguments: before.arguments, ...details,
        result: jsonValue(result), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
      terminalRecorded = true;
      this.afterEffect(selected, after);
      return result;
    } catch (error) {
      if (!terminalRecorded) this.event(operation, role, "after", { call: before.seq, arguments: before.arguments, ...details,
        error: publicAtomicError(error), rawError: rawAtomicError(error), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
      throw error;
    }
  }
  async asynchronous(operation, role, method, args, invoke, details = {}, afterDelegate = null) {
    const before = this.event(operation, role, "before", { arguments: { method, args: jsonValue(args) }, ...details });
    const selected = this.chooseFault(operation, role);
    let terminalRecorded = false;
    try {
      if (selected?.fault.effect === "replace-stage") this.fixtureMutation(selected, before);
      if (selected?.fault.effect === "reject-before") throw this.reject(selected, before);
      let result;
      if (selected?.fault.effect === "zero-write") {
        result = { bytesWritten: 0, buffer: args[0] };
        this.consume(selected, before, { result: jsonValue(result) });
      } else if (selected?.fault.effect === "partial-write") {
        const bytes = typeof args[0] === "string" ? Buffer.from(args[0], "utf8") : Buffer.from(args[0]);
        const offset = typeof args[1] === "number" ? args[1] : 0;
        const partial = [bytes.subarray(offset, offset + selected.fault.bytes), 0,
          Math.min(selected.fault.bytes, bytes.length - offset), args.length > 3 ? args[3] : 0];
        before.arguments.requestedArgs = jsonValue(args);
        before.arguments.delegatedArgs = jsonValue(partial);
        result = await invoke(partial, true);
        this.event(operation, role, "after", { call: before.seq, arguments: before.arguments, ...details,
          delegatedArguments: jsonValue(partial), result: jsonValue(result), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
        terminalRecorded = true;
        throw this.reject(selected, before);
      } else result = await invoke(args, false);
      const observed = afterDelegate ? await afterDelegate(result, before) : result;
      const after = this.event(operation, role, "after", { call: before.seq, arguments: before.arguments, ...details,
        result: jsonValue(observed), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
      terminalRecorded = true;
      this.afterEffect(selected, after);
      return result;
    } catch (error) {
      const after = terminalRecorded ? null : this.event(operation, role, "after", { call: before.seq, arguments: before.arguments, ...details,
        error: publicAtomicError(error), rawError: rawAtomicError(error), ...(details.fd === undefined ? {} : { stat: this.fdStat(details.fd) }) });
      if (this.input.concurrency?.schedule === "exclusive-bootstrap" && this.scope.getStore() === "second" &&
          operation === "lstat" && details.path === this.target && error.code === "ENOENT") {
        this.gates.second.ready.resolve(after?.seq);
      }
      throw error;
    }
  }
  registerHandle(handle, filename, role, flags, mode, before) {
    const fd = handle.fd, stat = this.fdStat(fd);
    this.descriptors.set(fd, { path: filename, role });
    const exclusive = typeof flags === "string" ? flags.includes("x") : (flags & syncFs.constants.O_EXCL) !== 0;
    if (exclusive) {
      const attempt = this.raw.exclusiveAttempts.find((item) => item.beforeEvent === before.seq);
      attempt.fd = fd; attempt.status = "returned";
      if (role === "stage") this.raw.stageAllocations.push({ id: "stage-" + this.stageCounter++,
        actor: this.scope.getStore() ?? "write", path: filename, fd, kind: "exclusive-open",
        beforeEvent: before.seq, afterEvent: null, stat });
    }
    const invoke = Object.fromEntries(["write", "writeFile", "read", "sync", "truncate", "chmod", "stat", "close"]
      .map((name) => [name, handle[name].bind(handle)]));
    let disposing = false;
    for (const [name, operation] of Object.entries({ write: "write", writeFile: "write", read: "read", sync: role === "parent" ? "parent-sync" : "file-sync",
      truncate: "truncate", chmod: "fchmod", stat: "fstat", close: "close" })) {
      const originalDescriptor = Object.getOwnPropertyDescriptor(handle, name);
      const wrapper = async (...args) => name === "close" && disposing ? invoke.close(...args) : this.asynchronous(operation, role, "FileHandle." + name, args,
        (parameters, partial) => partial && name === "writeFile" ? invoke.write(...parameters) : invoke[name](...parameters),
        { path: this.fdPath(fd) ?? filename, allocationPath: filename, fd },
        name === "stat" ? (result) => ({ observed: jsonValue(result), stat: this.fdStat(fd) }) : null);
      handle[name] = wrapper;
      this.restores.push(() => {
        if (originalDescriptor) Object.defineProperty(handle, name, originalDescriptor);
        else delete handle[name];
      });
    }
    const originalDispose = handle[Symbol.asyncDispose]?.bind(handle);
    if (originalDispose) {
      const originalDescriptor = Object.getOwnPropertyDescriptor(handle, Symbol.asyncDispose);
      handle[Symbol.asyncDispose] = async () => this.asynchronous("close", role, "FileHandle.Symbol.asyncDispose", [],
        async () => { disposing = true; try { return await originalDispose(); } finally { disposing = false; } },
        { path: this.fdPath(fd) ?? filename, allocationPath: filename, fd });
      this.restores.push(() => {
        if (originalDescriptor) Object.defineProperty(handle, Symbol.asyncDispose, originalDescriptor);
        else delete handle[Symbol.asyncDispose];
      });
    }
    return { fd, stat };
  }
  install() {
    for (const name of ["open", "readFile", "writeFile", "rename", "unlink", "stat", "lstat", "mkdir", "chmod", "rm"]) {
      const original = this.original.promises[name];
      fs[name] = async (...args) => {
        if (!this.owned(args[0])) return original(...args);
        const filename = path.resolve(String(args[0]));
        let role = this.pathRole(filename), operation = name;
        if (name === "rename") { operation = "publish"; role = "target"; }
        if (name === "unlink") operation = "cleanup";
        if (name === "readFile" && filename === this.target && this.preimageReadArmed) operation = "before-read";
        if (name === "open") {
          const flags = args[1], exclusive = typeof flags === "string" ? flags.includes("x") : (flags & syncFs.constants.O_EXCL) !== 0;
          if (exclusive && filename !== this.target) role = "stage";
          const before = this.event("open", role, "before", { path: filename,
            arguments: { method: "node:fs/promises.open", args: jsonValue(args) } });
          let attempt;
          if (exclusive) {
            attempt = { id: "attempt-" + this.attemptCounter++, actor: this.scope.getStore() ?? "write", path: filename,
              flags, mode: args[2] ?? 0o666, beforeEvent: before.seq, afterEvent: null, status: "pending" };
            this.raw.exclusiveAttempts.push(attempt);
          }
          try {
            const handle = await original(...args);
            const result = this.registerHandle(handle, filename, role, flags, args[2] ?? 0o666, before);
            const after = this.event("open", role, "after", { path: filename, fd: handle.fd,
              call: before.seq, arguments: before.arguments, result, stat: result.stat });
            if (attempt) attempt.afterEvent = after.seq;
            for (const stage of this.raw.stageAllocations) if (stage.beforeEvent === before.seq) stage.afterEvent = after.seq;
            if (role === "stage") this.preimageReadArmed = true;
            if (this.input.concurrency?.schedule === "checked-replacements" && role === "stage" &&
                this.scope.getStore() === "first" && !this.concurrencyHeld) {
              this.concurrencyHeld = true; this.gates.first.ready.resolve(after.seq); await this.gates.first.release.promise;
            }
            return handle;
          } catch (error) {
            const after = this.event("open", role, "after", { path: filename, call: before.seq, arguments: before.arguments,
              error: publicAtomicError(error), rawError: rawAtomicError(error) });
            if (attempt) { attempt.afterEvent = after.seq; attempt.status = attempt.fd === undefined ? "rejected" : "returned"; }
            throw error;
          }
        }
        const returned = await this.asynchronous(operation, role, "node:fs/promises." + name, args,
          (parameters) => original(...parameters), { path: filename, ...(name === "rename" ? { destination: path.resolve(String(args[1])) } : {}) });
        if (this.input.concurrency?.schedule === "checked-replacements" && this.scope.getStore() === "second" && name === "stat" && filename === path.dirname(this.target)) this.gates.second.ready.resolve();
        return returned;
      };
      this.restores.push(() => { fs[name] = original; });
    }
    for (const name of ["fstatSync", "fsyncSync", "fchmodSync", "closeSync", "writeSync", "readSync"]) {
      const original = this.original.sync[name];
      syncFs[name] = (...args) => {
        const record = this.fdRecord(args[0]);
        if (!record) return original(...args);
        const operation = ({ fstatSync: "fstat", fsyncSync: record.role === "parent" ? "parent-sync" : "file-sync",
          fchmodSync: "fchmod", closeSync: "close", writeSync: "write", readSync: "read" })[name];
        const result = this.synchronous(operation, record.role, "node:fs." + name, args,
          (parameters) => original(...parameters), { path: record.actualPath ?? record.path, allocationPath: record.path,
            fd: args[0], ...(record.stat ? { stat: record.stat } : {}) });
        if (name === "fstatSync") this.raw.ioEvents.at(-1).stat = this.fdStat(args[0]);
        return result;
      };
      this.restores.push(() => { syncFs[name] = original; });
    }
    const write = this.original.sync.write;
    syncFs.write = (fd, buffer, offset, length, position, callback) => {
      const record = this.fdRecord(fd);
      if (!record) return write(fd, buffer, offset, length, position, callback);
      const args = [fd, buffer, offset, length, position];
      const before = this.event("write", record.role, "before", { path: record.actualPath ?? record.path,
        allocationPath: record.path, fd, stat: record.stat, arguments: { method: "node:fs.write", args: jsonValue(args) } });
      const selected = this.chooseFault("write", record.role);
      if (selected?.fault.effect === "reject-before") {
        const error = this.reject(selected, before);
        this.event("write", record.role, "after", { call: before.seq, path: before.path, fd,
          arguments: before.arguments, error: publicAtomicError(error), rawError: rawAtomicError(error),
          stat: this.fdStat(fd), dispatched: false });
        return queueMicrotask(() => callback(error));
      }
      if (selected?.fault.effect === "zero-write") {
        this.consume(selected, before, { result: { bytesWritten: 0 } });
        this.event("write", record.role, "after", { call: before.seq, path: before.path, fd, arguments: before.arguments,
          result: { bytesWritten: 0 }, stat: this.fdStat(fd) });
        return queueMicrotask(() => callback(null, 0, buffer));
      }
      const delegatedLength = selected?.fault.effect === "partial-write" ? Math.min(length, selected.fault.bytes) : length;
      if (selected?.fault.effect === "partial-write") {
        before.arguments.requestedArgs = jsonValue(args);
        before.arguments.delegatedArgs = jsonValue([fd, buffer, offset, delegatedLength, position]);
      }
      return write(fd, buffer, offset, delegatedLength, position, (error, written, returned) => {
        const after = this.event("write", record.role, "after", { call: before.seq, path: before.path, fd,
          arguments: before.arguments, delegatedArguments: jsonValue([fd, buffer, offset, delegatedLength, position]),
          ...(error ? { error: publicAtomicError(error), rawError: rawAtomicError(error) } : { result: { bytesWritten: written } }), stat: this.fdStat(fd) });
        const finish = () => callback(error ?? (selected?.fault.effect === "partial-write" ? this.reject(selected, after) : null), written, returned);
        if (this.input.concurrency?.schedule === "exclusive-bootstrap" && this.scope.getStore() === "first" && !this.concurrencyHeld && !error) {
          this.concurrencyHeld = true; this.gates.first.ready.resolve(after.seq); this.gates.first.release.promise.then(finish);
        } else finish();
      });
    };
    this.restores.push(() => { syncFs.write = write; });
    for (const name of ["createStagedFile", "stagedFileMatches", "removeStagedFile", "renameNoReplace", "renameReplace", "closeOwnedFd"]) {
      if (typeof this.binding?.[name] !== "function") continue;
      const originalFunction = this.binding[name], original = (...args) => Reflect.apply(originalFunction, this.binding, args);
      this.original.binding[name] = originalFunction;
      this.binding[name] = (...args) => {
        if (name === "closeOwnedFd") {
          const record = this.fdRecord(args[0]);
          if (!record) return original(...args);
          return this.synchronous("close", record.role, "native." + name, args, (parameters) => original(...parameters),
            { path: record.actualPath ?? record.path, allocationPath: record.path, fd: args[0], stat: record.stat });
        }
        const parent = this.fdRecord(args[0]);
        if (!parent || !this.owned(parent.actualPath ?? parent.path)) return original(...args);
        const filename = path.join(parent.actualPath ?? parent.path, String(args[1]));
        if (name === "createStagedFile") {
          const before = this.event("open", "stage", "before", { path: filename, fd: args[0],
            arguments: { method: "native." + name, args: jsonValue(args) }, stat: parent.stat });
          try {
            const fd = original(...args), stat = this.fdStat(fd);
            this.descriptors.set(fd, { path: filename, role: "stage" });
            const after = this.event("open", "stage", "after", { path: filename, fd, call: before.seq,
              arguments: before.arguments, result: { fd, stat, parentFd: args[0], parentStat: parent.stat }, stat });
            this.raw.stageAllocations.push({ id: "stage-" + this.stageCounter++, actor: this.scope.getStore() ?? "write",
              path: filename, fd, kind: "native-stage", beforeEvent: before.seq, afterEvent: after.seq, stat,
              parentFd: args[0], parentStat: parent.stat });
            this.preimageReadArmed = true; return fd;
          } catch (error) {
            this.event("open", "stage", "after", { path: filename, call: before.seq, arguments: before.arguments,
              error: publicAtomicError(error), rawError: rawAtomicError(error) }); throw error;
          }
        }
        const operation = name === "removeStagedFile" ? "cleanup" : name === "stagedFileMatches" ? "stage-match" : "publish";
        const role = operation === "publish" ? "target" : "stage";
        const details = { path: filename, fd: name === "stagedFileMatches" || name === "removeStagedFile" ? args[2] : undefined,
          ...(operation === "publish" ? { destination: path.join(this.fdPath(args[2]), String(args[3])) } : {}) };
        return this.synchronous(operation, role, "native." + name, args, (parameters) => original(...parameters), details);
      };
      this.restores.push(() => { this.binding[name] = originalFunction; });
    }
  }
  restore() { for (const restore of this.restores.reverse()) restore(); }
}

async function snapshot(subject, originals) {
  const result = [];
  async function visit(filename) {
    const info = await originals.lstat(filename, { bigint: true });
    const entry = { path: filename, kind: info.isFile() ? "file" : info.isDirectory() ? "directory" : info.isSymbolicLink() ? "symlink" : "other",
      mode: Number(info.mode & 0o7777n), stat: fullStat(info) };
    if (info.isFile()) entry.bytes = Array.from(await originals.readFile(filename));
    if (info.isSymbolicLink()) entry.link = await originals.readlink(filename);
    result.push(entry);
    if (info.isDirectory()) for (const name of (await originals.readdir(filename)).sort()) await visit(path.join(filename, name));
  }
  await visit(subject); return result;
}
const logical = (entries) => entries.map(({ stat, ...entry }) => entry);

async function runAtomicRuntime(kind, operation, input, runtimeConfig) {
  if (input?.version !== 1 || input.kind !== kind || !path.isAbsolute(runtimeConfig?.runtimeRoot ?? "") ||
      !path.isAbsolute(runtimeConfig?.evidenceDirectory ?? "") || !Array.isArray(input.faults) ||
      typeof input.path !== "string" || path.isAbsolute(input.path) || input.path.split(/[\\/]/).some((part) => !part || part === "." || part === "..")) {
    throw Error("Atomic proof requires its declared literal kind and owned authenticated runtime");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const fixtureBase = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-atomic-fixture-"));
  const subject = path.join(fixtureBase, "subject"), target = path.join(subject, input.path);
  const previousMask = process.umask(input.umask);
  const raw = { schemaVersion: 1, operation, kind, input: structuredClone(input), fixtureBase,
    pid: process.pid, threadId, requests: [], ioEvents: [], faults: input.faults.map((fault) => ({ input: structuredClone(fault), matched: 0, events: [] })),
    stageAllocations: [], exclusiveAttempts: [], snapshots: { before: [], after: [] }, outcomes: [], codec: { version: 1 } };
  const imp = (relative) => import(pathToFileURL(path.join(runtimeConfig.runtimeRoot, relative)).href);
  let observation;
  try {
    await fs.mkdir(path.dirname(target), { recursive: true });
    if (input.initial !== null) { await fs.writeFile(target, input.initial.content); await fs.chmod(target, input.initial.mode); }
    await fs.chmod(path.dirname(target), input.parentMode);
    const { getNativeBinding } = await imp("../@openclaw/fs-safe/dist/native.js");
    const binding = getNativeBinding();
    raw.defaultNativeBinding = { available: binding !== undefined,
      overrideVariablesAbsent: ["FS_SAFE_NATIVE_MODE", "OPENCLAW_FS_SAFE_NATIVE_MODE", "FS_SAFE_PYTHON_MODE", "OPENCLAW_FS_SAFE_PYTHON_MODE"].every((key) => process.env[key] === undefined),
      functions: binding === undefined ? [] : Object.keys(binding).filter((name) => typeof binding[name] === "function").sort() };
    if (!binding || !raw.defaultNativeBinding.overrideVariablesAbsent) throw Error("Atomic proof requires its genuine default native filesystem backend");
    let original, owner;
    if (kind === "commit") {
      const module = await imp("dist/short-term-promotion-memory-write-DLJgScco.mjs");
      original = module.commitMemoryContent; owner = "commitMemoryContent";
    } else if (kind === "bootstrap") {
      const module = await imp("dist/workspace-C0LMBmap.mjs"); original = module.u; owner = "publishBootstrapFile";
    } else {
      const module = await imp("../@openclaw/fs-safe/dist/root.js");
      const root = await module.root(subject); original = root.append.bind(root); owner = "Root.append";
    }
    observation = new AtomicIoObservation(input, raw, subject, target, binding);
    raw.snapshots.before = await snapshot(subject, observation.original.promises);
    observation.install();
    async function execute(id, content) {
      return observation.scope.run(id, async () => {
        const arguments_ = kind === "commit" ? { filePath: target, content,
          expectedContent: input.request.expectedContent, expectedHash: input.request.expectedHash,
          allowInPlaceFallback: input.request.allowInPlaceFallback, tempPrefix: input.request.tempPrefix }
          : kind === "bootstrap" ? { filePath: target, content }
            : { relativePath: input.path, data: content, options: { mkdir: true, prependNewlineIfNeeded: input.request.prependNewlineIfNeeded } };
        const request = { id, owner, arguments: structuredClone(arguments_) }; raw.requests.push(request);
        observation.event("request", "target", "before", { path: target, arguments: { method: owner, args: jsonValue(arguments_) } });
        try {
          const returned = kind === "commit" ? await original(arguments_) : kind === "bootstrap" ? await original(target, content)
            : await original(input.path, content, arguments_.options);
          const outcome = { id, status: "fulfilled", value: returned ?? null }; request.outcome = outcome; return outcome;
        } catch (error) {
          const outcome = { id, status: "rejected", error: publicAtomicError(error) };
          request.outcome = outcome; request.rawError = rawAtomicError(error); return outcome;
        }
      });
    }
    if (!input.concurrency) raw.outcomes = [await execute("write", input.request.content)];
    else {
      const [firstWriter, secondWriter] = input.concurrency.writers;
      const first = execute(firstWriter.id, firstWriter.content);
      await observation.gates.first.ready.promise;
      const second = execute(secondWriter.id, secondWriter.content);
      await observation.gates.second.ready.promise;
      observation.event("concurrency-release", "target", "before", { path: target,
        arguments: { schedule: input.concurrency.schedule, first: firstWriter.id, second: secondWriter.id } });
      observation.gates.first.release.resolve();
      const firstOutcome = await first;
      observation.gates.second.release.resolve();
      raw.outcomes = [firstOutcome, await second];
    }
  } catch (error) {
    raw.adapterError = rawAtomicError(error); throw error;
  } finally {
    observation?.restore();
    if (observation) raw.snapshots.after = await snapshot(subject, observation.original.promises);
    process.umask(previousMask);
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
  }
  return encodeAtomicPublic({ provider: "none", outcomes: raw.outcomes,
    snapshots: { before: logical(raw.snapshots.before), after: logical(raw.snapshots.after) } }, raw);
}

export async function runAtomicCommitRuntime(input, runtimeConfig) {
  return runAtomicRuntime("commit", "atomic-commit-runtime", input, runtimeConfig);
}
export async function runAtomicAppendRuntime(input, runtimeConfig) {
  return runAtomicRuntime("append", "atomic-append-runtime", input, runtimeConfig);
}
export async function runAtomicBootstrapRuntime(input, runtimeConfig) {
  return runAtomicRuntime("bootstrap", "atomic-bootstrap-runtime", input, runtimeConfig);
}
