// Transparent call receipts for this lane only. No faults, hooks or decisions.
import fs from "node:fs";
import promises from "node:fs/promises";
import { modelError } from "./model-runtime-observation.mjs";

export function encode(value, seen = new Set()) {
  if (value === undefined) return { $type: "undefined" };
  if (typeof value === "bigint") return { $type: "bigint", value: String(value) };
  if (typeof value === "function") return { $type: "function", name: value.name, source: String(value) };
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return { $type: "recursive-reference" };
  seen = new Set([...seen, value]);
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) return { $type: "bytes", hex: Buffer.from(value).toString("hex") };
  if (Array.isArray(value)) return value.map(item => encode(item, seen));
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, encode(item, seen)]));
}

export function callObservers(receipts) {
  let active = false;
  const restores = [];
  function record(operation, when, facts) {
    const row = { sequence: receipts.length + 1, operation, when,
      monotonicNs: process.hrtime.bigint().toString(), ...encode(facts) };
    receipts.push(row); return row;
  }
  function descriptors(args) {
    return args.filter(arg => Number.isInteger(arg) && arg >= 0).flatMap(fd => {
      try { return [{ fd, path: fs.readlinkSync(`/proc/self/fd/${fd}`) }]; }
      catch { return []; }
    });
  }
  function wrap(target, name, prefix) {
    const original = target[name];
    if (typeof original !== "function") return;
    target[name] = function (...args) {
      if (!active) return Reflect.apply(original, this, args);
      const before = record(prefix + name, "before", { arguments: args, descriptors: descriptors(args) });
      const succeed = value => {
        record(prefix + name, "after", { call: before.sequence, result: value }); return value;
      };
      const fail = error => {
        record(prefix + name, "after", { call: before.sequence, error: modelError(error) }); throw error;
      };
      try {
        const returned = Reflect.apply(original, this, args);
        return returned instanceof Promise ? returned.then(succeed, fail) : succeed(returned);
      } catch (error) { return fail(error); }
    };
    restores.push(() => { target[name] = original; });
  }
  return {
    observeBinding(binding) {
      for (const name of Object.keys(binding)) wrap(binding, name, "native.");
    },
    observeStore(store, namespace) {
      for (const name of Object.keys(store)) wrap(store, name, `store[${namespace}].`);
      return store;
    },
    start() {
      for (const name of ["writeFile", "appendFile", "rename", "unlink", "mkdir", "rmdir"]) wrap(promises, name, "fs.");
      for (const name of ["writeSync", "fsyncSync", "renameSync", "unlinkSync"]) wrap(fs, name, "fs.");
      active = true;
    },
    stop() { active = false; },
    restore() { active = false; for (const restore of restores.reverse()) restore(); },
  };
}
