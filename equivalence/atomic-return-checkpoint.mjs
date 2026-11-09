// Trusted read-only return/exit observations. No writer or cleanup is supplied.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { isMainThread, threadId } from "node:worker_threads";
import { publicAtomicError, rawAtomicError } from "./atomic-publication-codec.mjs";

const original = Object.fromEntries(["openSync", "closeSync", "readSync", "fstatSync", "lstatSync", "readlinkSync",
  "readdirSync", "realpathSync", "readFileSync", "unlinkSync", "rmSync"].map((key) => [key, fs[key]]));
const constants = { ...fs.constants };
const hash = (value) => crypto.createHash("sha256").update(value).digest("hex");
const INVOKE = Symbol.for("memory.equivalence.atomic.invoke");
const CHECKPOINT = Symbol.for("memory.equivalence.atomic.return-checkpoint");
const statFields = ["dev", "ino", "mode", "nlink", "size", "uid", "gid", "mtimeNs", "ctimeNs"];
const fullStat = (value) => Object.fromEntries(statFields.map((key) => [key, String(value[key])]));
const same = (left, right) => left.dev === right.dev && left.ino === right.ino && left.mode === right.mode;

function subjectTree(base) {
  if (process.platform !== "linux") throw Error("The atomic fd-anchored checkpoint is a declared Linux proof profile");
  const rootFd = original.openSync(base, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  const entries = [];
  function visit(parentFd, name, filename) {
    const admittedPath = `/proc/self/fd/${parentFd}/${name}`;
    const observed = original.lstatSync(admittedPath, { bigint: true });
    const kind = observed.isFile() ? "file" : observed.isDirectory() ? "directory" : observed.isSymbolicLink() ? "symlink" : "other";
    const entry = { path: filename, kind, mode: Number(observed.mode & 0o7777n), stat: fullStat(observed) };
    let fd;
    try {
      if (kind === "file" || kind === "directory") {
        fd = original.openSync(admittedPath, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK |
          (kind === "directory" ? constants.O_DIRECTORY : 0));
        if (!same(observed, original.fstatSync(fd, { bigint: true }))) throw Error("Atomic checkpoint entry changed during descriptor admission");
      }
      if (kind === "file") {
        const chunks = []; let size = 0;
        while (true) {
          const window = Buffer.allocUnsafe(65536), count = original.readSync(fd, window, 0, window.length, null);
          if (!count) break;
          size += count;
          if (size > 16 * 1024 * 1024) throw Error("Atomic checkpoint complete file bound exceeded");
          chunks.push(window.subarray(0, count));
        }
        entry.bytes = Array.from(Buffer.concat(chunks));
      } else if (kind === "symlink") entry.link = original.readlinkSync(admittedPath);
      entries.push(entry);
      if (kind === "directory") {
        for (const child of original.readdirSync(`/proc/self/fd/${fd}`).sort()) visit(fd, child, path.join(filename, child));
      }
    } finally { if (fd !== undefined) original.closeSync(fd); }
  }
  try { visit(rootFd, "subject", path.join(base, "subject")); }
  finally { original.closeSync(rootFd); }
  return entries;
}

function readJournal(filename) {
  const fd = original.openSync(filename, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = original.fstatSync(fd, { bigint: true });
    if (!stat.isFile() || stat.nlink !== 1n || stat.size > 16n * 1024n * 1024n) throw Error("Atomic checkpoint journal is not an independent bounded regular file");
    return original.readFileSync(fd);
  } finally { original.closeSync(fd); }
}

export function installAtomicReturnCheckpoint(context, trace) {
  const actual = JSON.parse(original.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT, "utf8"));
  if (!isMainThread || threadId !== 0 || !actual.atomicPublicationProfile ||
      JSON.stringify(actual) !== JSON.stringify(context) || Object.hasOwn(globalThis, INVOKE) || Object.hasOwn(globalThis, CHECKPOINT))
    throw Error("Atomic return observation requires its actual unique main-process capability");
  const binding = context.atomicCaseBinding, profile = context.atomicPublicationProfile;
  if (!binding || Object.keys(binding).sort().join() !== "id,inputJson,inputSha256,operation" ||
      typeof binding.id !== "string" || !binding.id.startsWith("storage.atomic-writes.") || binding.operation !== profile.operation ||
      typeof binding.inputJson !== "string" || hash(Buffer.from(binding.inputJson)) !== binding.inputSha256)
    throw Error("Atomic return observation lost its exact case and literal input binding");
  const input = JSON.parse(binding.inputJson);
  if (input.kind !== profile.inputKind || input.version !== 1 || !["MEMORY.md", "AGENTS.md", "memory/2026-09-04.md"].includes(input.path))
    throw Error("Atomic return observation has an unsupported literal owner request");
  const writers = input.concurrency?.writers ?? [{ id: "write", content: input.request.content }];
  if (!writers.length || writers.some((writer, index) => typeof writer.id !== "string" || writers.findIndex((item) => item.id === writer.id) !== index))
    throw Error("Atomic return observation requires unique declared writer steps");
  const caseDirectory = path.join(context.evidenceDirectory, hash(Buffer.from(binding.id)));
  let fixtureBase, started = 0, completed = false, exiting = false;
  const states = new Map(), settlements = [];
  function reject(code) { trace({ event: "rejected", code }); throw Error(code); }
  function ownedBase(base) {
    if (typeof base !== "string" || !path.isAbsolute(base) || path.dirname(base) !== caseDirectory ||
        !/^native-atomic-[A-Za-z0-9_-]+$/.test(path.basename(base)) || original.realpathSync(base) !== base)
      return reject("atomic-checkpoint-unowned-fixture");
    const stat = original.lstatSync(base);
    if (!stat.isDirectory() || stat.isSymbolicLink()) return reject("atomic-checkpoint-unowned-fixture");
    if (fixtureBase !== undefined && fixtureBase !== base) return reject("atomic-checkpoint-fixture-changed");
    fixtureBase = base;
    return base;
  }
  function emit(event, facts = {}) {
    trace({ event, caseId: binding.id, inputSha256: binding.inputSha256, fixtureBase, ...facts });
  }
  const imp = (relative) => import(pathToFileURL(path.join(context.runtime.runtimeRoot, relative)).href);
  const invoke = async (stepId, base) => {
    ownedBase(base);
    if (completed || exiting || writers[started]?.id !== stepId || states.has(stepId)) return reject("atomic-checkpoint-duplicate-or-out-of-phase-owner");
    const writer = writers[started++], subject = path.join(base, "subject"), target = path.join(subject, input.path);
    states.set(stepId, "running");
    const beforeTree = started === 1 ? subjectTree(base) : undefined;
    let owner, arguments_, call;
    if (input.kind === "commit") {
      const module = await imp("dist/short-term-promotion-memory-write-DLJgScco.mjs");
      owner = "commitMemoryContent";
      arguments_ = { filePath: target, content: writer.content, expectedContent: input.request.expectedContent,
        expectedHash: input.request.expectedHash, allowInPlaceFallback: input.request.allowInPlaceFallback, tempPrefix: input.request.tempPrefix };
      call = () => module.commitMemoryContent(arguments_);
    } else if (input.kind === "bootstrap") {
      const module = await imp("dist/workspace-C0LMBmap.mjs");
      owner = "publishBootstrapFile"; arguments_ = { filePath: target, content: writer.content };
      call = () => module.u(target, writer.content);
    } else {
      const module = await imp("../@openclaw/fs-safe/dist/root.js"), root = await module.root(subject);
      owner = "Root.append"; arguments_ = { relativePath: input.path, data: writer.content,
        options: { mkdir: true, prependNewlineIfNeeded: input.request.prependNewlineIfNeeded } };
      call = () => root.append(input.path, writer.content, arguments_.options);
    }
    emit("atomic-owner-start", { stepId, owner, arguments: arguments_, ...(beforeTree ? { beforeTree } : {}) });
    try {
      const value = await call();
      const outcome = { id: stepId, status: "fulfilled", value: value ?? null };
      const record = { stepId, owner, arguments: arguments_, outcome,
        rawReturned: value === undefined ? { type: "undefined" } : value };
      settlements.push(record); states.set(stepId, "settled"); emit("atomic-owner-settle", record);
      return value;
    } catch (error) {
      const record = { stepId, owner, arguments: arguments_, outcome: { id: stepId, status: "rejected", error: publicAtomicError(error) }, rawError: rawAtomicError(error) };
      settlements.push(record); states.set(stepId, "settled"); emit("atomic-owner-settle", record);
      throw error;
    }
  };
  const checkpoint = (base) => {
    ownedBase(base);
    if (completed || exiting || started !== writers.length || writers.some((writer) => states.get(writer.id) !== "settled"))
      return reject("atomic-checkpoint-duplicate-or-unsettled-return");
    const bytes = readJournal(path.join(caseDirectory, "native-raw.json"));
    const journal = JSON.parse(bytes.toString("utf8"));
    if (!Array.isArray(journal) || journal.length !== 1 || journal[0].fixtureBase !== base || journal[0].pid !== process.pid || journal[0].threadId !== 0)
      return reject("atomic-checkpoint-wrong-owned-journal");
    const tree = subjectTree(base);
    completed = true;
    emit("atomic-return-checkpoint", { rawSha256: hash(bytes), rawBytes: bytes.length,
      ioEventCount: journal[0].ioEvents.length, settlements, subjectTree: tree });
    // Added after the actual owner registered its genuine exit cleanup. It is
    // observation only; original exit hooks remain installed and execute first.
    process.once("exit", () => {
      try { emit("atomic-exit-end", { subjectTree: subjectTree(base) }); }
      catch (error) { emit("atomic-exit-end", { error: publicAtomicError(error), rawError: rawAtomicError(error) }); }
    });
  };
  process.prependOnceListener("exit", () => { exiting = true; emit("atomic-exit-start", { checkpointCompleted: completed }); });
  for (const method of ["unlinkSync", "rmSync", "lstatSync"]) {
    fs[method] = (...args) => {
      const candidate = typeof args[0] === "string" ? path.resolve(args[0]) : null;
      if (!exiting || !fixtureBase || candidate === null || !candidate.startsWith(path.join(fixtureBase, "subject") + path.sep))
        return original[method](...args);
      const facts = { method: "node:fs." + method, arguments: args.map((item) => item === undefined ? { type: "undefined" } : item) };
      emit("atomic-exit-io", { when: "before", ...facts });
      try {
        const value = original[method](...args);
        emit("atomic-exit-io", { when: "after", ...facts, result: value === undefined ? { type: "undefined" }
          : method === "lstatSync" ? { stat: fullStat(value) } : value });
        return value;
      } catch (error) {
        emit("atomic-exit-io", { when: "after", ...facts, error: publicAtomicError(error), rawError: rawAtomicError(error) });
        throw error;
      }
    };
  }
  Object.defineProperty(globalThis, INVOKE, { value: invoke, writable: false, configurable: false });
  Object.defineProperty(globalThis, CHECKPOINT, { value: checkpoint, writable: false, configurable: false });
}
