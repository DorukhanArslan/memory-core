// Verify each original import, including the runtime-owned copy of the one offline fixture.
import fs from "node:fs";
import { createHash } from "node:crypto";
import { registerHooks } from "node:module";
import path from "node:path";
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
  const filename = fs.realpathSync(target);
  let entry = known.get(filename);
  if (!entry) {
    const relative = path.relative(context.state, filename).split(path.sep).join("/");
    const capture = /^tmp\/plugin-captures\/[a-f0-9-]{36}\/captures\/openclaw-plugin-build-[A-Za-z0-9]{6}\/package-0\/node_modules\/prompt-runtime-provider\/index\.mjs$/;
    if (capture.test(relative) && filename === path.resolve(target)) {
      const fixture = known.get(context.fixture);
      if (fixture && hash(fs.readFileSync(filename)) === fixture[1]) entry = fixture;
    }
  }
  if (!entry) throw Error("Unverified provider overflow module: " + filename);
  const [index, digest] = entry;
  if (!seen.has(index)) {
    if (hash(fs.readFileSync(filename)) !== digest) throw Error("Changed provider overflow module: " + filename);
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
