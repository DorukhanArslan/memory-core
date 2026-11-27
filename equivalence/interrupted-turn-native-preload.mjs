// Observe loaded bytes, including inherited SQLite workers, before the host caller runs.
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';
import { threadId } from 'node:worker_threads';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const authority = JSON.parse(fs.readFileSync(process.env.RECOVERY_AUTHORITY));
const { root, phase } = process.env;
const trace = path.join(root, phase + '-trace', process.pid + '-' + threadId + '.jsonl');
const write = value => fs.appendFileSync(trace, JSON.stringify(value) + '\n', { mode: 0o600 });
const self = fileURLToPath(import.meta.url);
const here = path.dirname(self);
const plugin = path.join(here, 'host-turn-barrier-provider/index.mjs');
const seen = new Set();
const actual = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
  icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode, sha256: hash(fs.readFileSync(process.execPath)) };
if (Object.keys(actual).some(k => actual[k] !== authority.node[k])) throw Error('Different native runtime');
write({ event: 'bootstrap', pid: process.pid, ppid: process.ppid, threadId, phase, node: actual,
  preloadSha256: hash(fs.readFileSync(self)) });
const sourceCapture = /^tmp\/plugin-captures\/[a-f0-9-]{36}\/captures\/openclaw-plugin-build-[a-z0-9]{6}\/package-0\/node_modules\/host-turn-barrier-provider\/index\.mjs$/i;
function check(url) {
  if (url.startsWith('node:')) return;
  if (!url.startsWith('file:')) throw Error('Unverified module URL');
  const file = fileURLToPath(url);
  const relative = path.relative(root, file);
  const source = sourceCapture.test(relative) ? plugin : file;
  const fileHash = hash(fs.readFileSync(file));
  if (fs.realpathSync(file) !== file || !Object.hasOwn(authority.files, source) || authority.files[source] !== fileHash) {
    write({ event: 'rejected', file });
    throw Error('Unauthenticated module ' + file);
  }
  if (!seen.has(file)) {
    seen.add(file);
    write({ event: 'source', source, ...(file === source ? {} : { capture: relative }), sha256: fileHash });
  }
}
registerHooks({
  resolve(specifier, context, next) {
    const resolved = next(specifier, context);
    if (resolved.url.endsWith('.node')) check(resolved.url);
    return resolved;
  },
  load(url, context, next) { check(url); return next(url, context); },
});
Object.defineProperty(globalThis, 'fetch', { configurable: false, writable: false, value: async () => {
  write({ event: 'network-request' });
  throw Error('The local transport has no external provider');
} });
