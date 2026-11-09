// Observational transport only. It supplies no publication algorithm or result.
import path from "node:path";
import { constants } from "node:fs";

const fields = ["dev", "ino", "mode", "nlink", "size", "uid", "gid", "mtimeNs", "ctimeNs"];
const decimal = /^-?(?:0|[1-9][0-9]*)$/;
const safe = BigInt(Number.MAX_SAFE_INTEGER);
function integer(value) {
  if (typeof value === "bigint") return value;
  if (typeof value === "number" && Number.isSafeInteger(value)) return BigInt(value);
  if (typeof value === "string" && decimal.test(value)) return BigInt(value);
  if (value && typeof value === "object" && Object.keys(value).sort().join() === "decimal,type" &&
      ["bigint", "integer"].includes(value.type) && typeof value.decimal === "string" && decimal.test(value.decimal)) return BigInt(value.decimal);
  throw Error("Physical stat fields require exact lossless integers");
}
function lossless(value) {
  if (typeof value === "bigint") return value >= -safe && value <= safe ? Number(value) : { type: "integer", decimal: String(value) };
  if (Array.isArray(value)) return value.map(lossless);
  if (value !== null && typeof value === "object") {
    if (Object.keys(value).sort().join() === "decimal,type" && ["bigint", "integer"].includes(value.type)) return lossless(integer(value));
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, lossless(item)]));
  }
  return value;
}
export function rawAtomicError(error) {
  const active = new Set();
  const observe = (value) => {
    if (value === undefined) return { type: "undefined" };
    if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
    if (typeof value === "symbol" || typeof value === "function") return { type: typeof value, value: String(value) };
    if (typeof value === "number" && !Number.isFinite(value)) return { type: "number", value: String(value) };
    if (value instanceof Error) {
      if (active.has(value)) return { type: "exception-reference", name: value.name, message: value.message };
      active.add(value);
      const result = { type: value.constructor.name, name: value.name, message: value.message,
        own: Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, observe(value[key])])) };
      active.delete(value);
      return result;
    }
    if (Array.isArray(value)) return value.map(observe);
    if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, observe(item)]));
    return value;
  };
  return observe(error);
}
export function publicAtomicError(error) {
  const observe = (value) => {
    if (value instanceof Error) return publicAtomicError(value);
    if (typeof value === "bigint") return { type: "bigint", decimal: String(value) };
    if (Array.isArray(value)) return value.map(observe);
    if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value)
      .filter(([, item]) => item !== undefined).map(([key, item]) => [key, observe(item)]));
    return value;
  };
  const carrier = new Set(["name", "message", "stack", "code", "path", "cause"]);
  return { name: error?.name ?? typeof error, message: error?.message ?? String(error),
    code: error?.code ?? null, path: error?.path ?? null,
    cause: error?.cause === undefined ? null : publicAtomicError(error.cause),
    ...Object.fromEntries(Object.getOwnPropertyNames(error ?? {}).filter((key) => !carrier.has(key) && error[key] !== undefined)
      .map((key) => [key, observe(error[key])])) };
}
function physicalStat(value) {
  if (!value || typeof value !== "object" || fields.some((key) => !(key in value))) throw Error("Actual descriptor observations require complete physical stats");
  return Object.fromEntries(fields.map((key) => [key, integer(value[key])]));
}
function equalStat(left, right) { return fields.every((key) => left[key] === right[key]); }
function owned(base, filename) {
  if (typeof filename !== "string" || !path.isAbsolute(filename) || filename.split(path.sep).includes("..") ||
      !(filename === base || filename.startsWith(base + path.sep))) throw Error("A physical stage requires its actual absolute owned pathname");
  return filename;
}
function exclusive(flags) {
  return typeof flags === "string" ? ["wx", "wx+"].includes(flags)
    : Number.isSafeInteger(flags) && (flags & constants.O_CREAT) !== 0 && (flags & constants.O_EXCL) !== 0;
}
export function encodeAtomicPublic(publicValue, raw) {
  const base = raw.fixtureBase;
  if (typeof base !== "string" || !path.isAbsolute(base)) throw Error("Atomic codecs require an actual absolute fixture root");
  if (!Array.isArray(raw.ioEvents)) throw Error("Atomic observations require complete ordered IO events");
  const events = new Map();
  for (const event of raw.ioEvents) {
    if (!event || !Number.isSafeInteger(event.seq) || event.seq < 0 || events.has(event.seq) ||
        typeof event.arguments !== "object" || event.arguments === null ||
        (events.size && event.seq !== Math.max(...events.keys()) + 1)) throw Error("Atomic IO sequence is incomplete or reordered");
    events.set(event.seq, event);
  }
  if (!Array.isArray(raw.stageAllocations ?? [])) throw Error("Actual allocated stages must remain an ordered list");
  const stages = (raw.stageAllocations ?? []).map((allocation, index) => {
    if (!allocation || allocation.id !== `stage-${index}` || !Number.isSafeInteger(allocation.fd) || allocation.fd < 0 ||
        !["exclusive-open", "native-stage"].includes(allocation.kind)) throw Error("Allocated stages require actual descriptor identities");
    const filename = owned(base, allocation.path), before = events.get(allocation.beforeEvent), after = events.get(allocation.afterEvent);
    if (!before || !after || before.when !== "before" || after.when !== "after" || before.seq >= after.seq ||
        before.role !== "stage" || before.actor !== allocation.actor || after.actor !== allocation.actor ||
        before.path !== filename || after.path !== filename || !after.result || after.result.fd !== allocation.fd ||
        Object.hasOwn(after, "error")) throw Error("A stage must bind its actual creation request, result and descriptor");
    const observed = physicalStat(allocation.stat);
    if (!equalStat(observed, physicalStat(after.result.stat)) || (observed.mode & 0o170000n) !== 0o100000n || observed.nlink !== 1n)
      throw Error("A stage allocation must match its independent regular-file fstat");
    const args = before.arguments.args ?? [];
    if (allocation.kind === "exclusive-open") {
      if (args.length < 3 || String(args[0]) !== filename || !exclusive(args[1]) || !Number.isSafeInteger(args[2]))
        throw Error("An allocated stage must come from its actual exclusive-open request");
    } else {
      if (before.arguments.method !== "native.createStagedFile" || !Number.isSafeInteger(allocation.parentFd) ||
          args[0] !== allocation.parentFd || args[1] !== path.basename(filename) ||
          after.result.parentFd !== allocation.parentFd || !equalStat(physicalStat(after.result.parentStat), physicalStat(allocation.parentStat)))
        throw Error("Native stages require the original native creation operation");
      physicalStat(allocation.parentStat);
    }
    return { ...allocation, path: filename, stat: observed };
  });
  const bindings = new Map();
  function receipts(value) {
    if (Array.isArray(value)) { for (const child of value) receipts(child); return; }
    if (value === null || typeof value !== "object") return;
    if (value.directory && typeof value.temporaryBasename === "string" && value.identity) {
      for (const allocation of stages) {
        const parent = path.dirname(allocation.path), directory = value.directory;
        if (value.temporaryBasename !== path.basename(allocation.path) || directory.path !== parent || directory.realPath !== parent) continue;
        let actual;
        try { actual = physicalStat(value.identity); } catch { continue; }
        const live = [];
        for (const event of events.values()) {
          if (event.seq < allocation.afterEvent || event.fd !== allocation.fd) continue;
          if (event.operation === "close" && event.when === "after" && !Object.hasOwn(event, "error")) break;
          if (event.actor === allocation.actor) live.push(event);
        }
        const publications = [...events.values()].filter((event) => event.seq > allocation.afterEvent && event.actor === allocation.actor &&
          event.operation === "publish" && event.when === "before" &&
          (event.path === allocation.path || event.arguments?.args?.[1] === path.basename(allocation.path)));
        const publicationSeq = publications.length ? Math.min(...publications.map((event) => event.seq)) : -1;
        const syncs = live.filter((event) => event.operation === "file-sync" && event.when === "after" &&
          !Object.hasOwn(event, "error") && event.seq < publicationSeq).map((event) => event.seq);
        const prepared = live.filter((event) => syncs.length && event.seq > Math.max(...syncs) && event.seq < publicationSeq &&
          event.operation === "fstat" && event.when === "after" && !Object.hasOwn(event, "error") && event.stat);
        const observed = prepared.length ? physicalStat(prepared.at(-1).stat) : null;
        const witnessed = observed !== null && equalStat({ ...observed, mode: observed.mode & 0o7777n }, actual);
        const parentStat = allocation.parentStat ?? raw.snapshots?.before?.find((entry) => entry.path === parent)?.stat;
        if (!parentStat || !directory.identity || Object.keys(directory.identity).sort().join() !== "dev,ino") continue;
        if (witnessed && ["dev", "ino"].every((key) => integer(directory.identity[key]) === physicalStat(parentStat)[key] && actual[key] === allocation.stat[key]))
          bindings.set(value, allocation.id);
      }
    }
    for (const child of Object.values(value)) receipts(child);
  }
  receipts(publicValue);
  const paths = new Map(stages.map((allocation) => [allocation.path, path.join(path.dirname(allocation.path), `.${allocation.id}`)]));
  const basenames = new Map(stages.map((allocation) => [path.basename(allocation.path), `.${allocation.id}`]));
  if (!Array.isArray(raw.exclusiveAttempts ?? [])) throw Error("Exclusive IO attempts must retain their ordered results");
  for (const [index, attempt] of (raw.exclusiveAttempts ?? []).entries()) {
    if (!attempt || attempt.id !== `attempt-${index}`) throw Error("Exclusive attempt sequence is incomplete");
    const filename = owned(base, attempt.path), before = events.get(attempt.beforeEvent), after = events.get(attempt.afterEvent);
    if (!before || !after || before.when !== "before" || after.when !== "after" || before.path !== filename || after.path !== filename ||
        before.seq >= after.seq || !exclusive(attempt.flags) || !Number.isSafeInteger(attempt.mode)) throw Error("An exclusive attempt requires its actual owned IO result");
    const args = before.arguments.args ?? [];
    if (args.length < 3 || String(args[0]) !== filename || args[1] !== attempt.flags || args[2] !== attempt.mode)
      throw Error("An exclusive attempt cannot borrow another operation's arguments");
    if (attempt.status === "rejected") {
      if (!Object.hasOwn(after, "error") || Object.hasOwn(attempt, "fd") || Object.hasOwn(after.result ?? {}, "fd") || stages.some((stage) => stage.path === filename))
        throw Error("A hidden or returned stage fd cannot masquerade as a rejected attempt");
      paths.set(filename, path.join(path.dirname(filename), `.exclusive-attempt-${index}`));
    } else if (attempt.status !== "returned") throw Error("An exclusive attempt has no actual returned/rejected result");
  }
  function text(value) {
    for (const [actual, label] of [...paths].sort((a, b) => b[0].length - a[0].length)) value = value.replaceAll(actual, label);
    return value === base ? "$FIXTURE" : value.replaceAll(base + path.sep, "$FIXTURE/");
  }
  function encode(value, field) {
    if (typeof value === "string") return field === "temporaryBasename" ? basenames.get(value) ?? value : text(value);
    if (Array.isArray(value)) return value.map((item) => encode(item));
    if (value !== null && typeof value === "object") {
      const result = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, encode(item, key)]));
      const bound = bindings.get(value);
      if (bound) {
        for (const key of ["dev", "ino", "mtimeNs", "ctimeNs"])
          result.identity[key] = `$PHYSICAL:${bound}:${["mtimeNs", "ctimeNs"].includes(key) ? "prepared:" : ""}${key}`;
        for (const key of ["dev", "ino"]) result.directory.identity[key] = `$PHYSICAL:${bound}:directory:${key}`;
      }
      return lossless(result);
    }
    return lossless(value);
  }
  return encode(publicValue);
}
