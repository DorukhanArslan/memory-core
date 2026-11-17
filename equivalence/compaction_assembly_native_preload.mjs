// Authenticate original package imports in both isolated phases and their workers.
import fs from "node:fs";
import { createHash } from "node:crypto";
import { registerHooks } from "node:module";
import { fileURLToPath } from "node:url";
import { threadId } from "node:worker_threads";
const bytes = fs.readFileSync(process.env.MEMORY_EQ_ASSEMBLY_AUTHORITY);
const context = JSON.parse(bytes);
const known = new Map(context.files.map(([target, digest], index) => [target, [index, digest]]));
const seen = new Set();
const hash = data => createHash("sha256").update(data).digest("hex");
const filename = context.trace + "-" + process.pid + "-" + threadId + ".jsonl";
const trace = row => fs.appendFileSync(filename, JSON.stringify(row) + "\n", { mode: 0o600 });
trace({ event: "bootstrap", pid: process.pid, ppid: process.ppid, threadId, entry: fs.realpathSync(process.argv[1]),
  node: fs.realpathSync(process.execPath), contextSha256: hash(bytes) });
function verify(target) {
  const filename = fs.realpathSync(target), entry = known.get(filename);
  if (!entry) throw Error("Unverified context-assembly module: " + filename);
  const [index, digest] = entry;
  if (!seen.has(index)) {
    if (hash(fs.readFileSync(filename)) !== digest) throw Error("Changed context-assembly module: " + filename);
    seen.add(index); trace({ load: index });
  }
}
registerHooks({ load(url, opts, next) {
  if (url.startsWith("file:")) verify(fileURLToPath(url));
  else if (!url.startsWith("node:")) throw Error("Context assembly requires verified local imports");
  return next(url, opts);
} });
const dlopen = process.dlopen;
process.dlopen = function(module, filename, ...args) { verify(filename); return dlopen.call(process, module, filename, ...args); };
