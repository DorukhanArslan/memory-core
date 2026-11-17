// Resolve only the scheduler's one additional locked package. Both the main
// thread and the original store workers authenticate imports before execution.
import fs from "node:fs";
import { createHash } from "node:crypto";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { threadId } from "node:worker_threads";

const contextBytes = fs.readFileSync(process.env.MEMORY_EQ_JOB_STATE_CONTEXT);
const context = JSON.parse(contextBytes);
const byPath = new Map(context.files.map(([target, digest], id) => [target, { id, digest }]));
const ownTrace = context.trace + "-" + process.pid + "-" + threadId + ".jsonl";
const seen = new Set();
function trace(value) {
  fs.appendFileSync(ownTrace, JSON.stringify(value) + "\n", { mode: 0o600 });
}
trace({ event: "bootstrap", pid: process.pid, ppid: process.ppid, threadId, node: fs.realpathSync(process.execPath),
  entry: fs.realpathSync(process.argv[1]), contextSha256: createHash("sha256").update(contextBytes).digest("hex") });
function authenticate(target) {
  const resolved = fs.realpathSync(target);
  const entry = byPath.get(resolved);
  if (!entry) throw Error("Unverified scheduled-task import: " + resolved);
  if (!seen.has(entry.id)) {
    if (createHash("sha256").update(fs.readFileSync(resolved)).digest("hex") !== entry.digest) {
      throw Error("Changed scheduled-task import: " + resolved);
    }
    seen.add(entry.id);
    trace({ load: entry.id });
  }
}
registerHooks({
  resolve(specifier, options, next) {
    if (specifier === "croner" && options.parentURL === pathToFileURL(context.scheduler).href) {
      return { url: pathToFileURL(context.croner).href, shortCircuit: true };
    }
    return next(specifier, options);
  },
  load(url, options, next) {
    if (url.startsWith("file:")) authenticate(fileURLToPath(url));
    else if (!url.startsWith("node:")) throw Error("Scheduled tasks require local authenticated modules");
    return next(url, options);
  },
});
const dlopen = process.dlopen;
process.dlopen = function(module, filename, ...args) {
  authenticate(filename);
  return dlopen.call(process, module, filename, ...args);
};
