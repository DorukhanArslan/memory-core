// Uncredited direct owner observations; no sanitizer, transcript or marker algorithm here.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const request = JSON.parse(await fs.readFile(process.argv[2], "utf8"));
const { input, runtimeRoot, fixtureDirectory } = request;
await fs.mkdir(fixtureDirectory, { recursive: true });
process.env.OPENCLAW_STATE_DIR = path.join(fixtureDirectory, "state");
process.env.OPENCLAW_CONFIG_PATH = path.join(fixtureDirectory, "openclaw.json");
process.env.OPENCLAW_HOME = fixtureDirectory;
const logging = { level: "silent", consoleLevel: "silent", ...(input.patterns ? { redactPatterns: input.patterns } : {}) };
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify({ logging }));
const imp = (name) => import(pathToFileURL(path.join(runtimeRoot, "dist", name)).href);
const { s: register } = await imp("secret-redaction-registry-b2B9lcfy.mjs");
for (const secret of input.registeredSecrets ?? []) register(secret);
const { u: sanitize, l: sanitizeArgs } = await imp("embedded-agent-tool-results-Bhhd5B_V.mjs");
const { o: prepare, U: isPrepared } = await imp("redact-BCoakatc.mjs");
const { c: store } = await imp("session-accessor.sqlite-transcript-store-DEXEZWnC.mjs");
const result = {}, identity = {};
if (Object.hasOwn(input, "value")) {
  const prepared = sanitize(input.value);
  result.sanitized = prepared;
  result.arguments = sanitizeArgs(input.value);
  identity.sanitizedOutputReuse = sanitize(prepared) === prepared;
  identity.originalInputReuse = sanitize(input.value) === prepared;
}
if (input.block) {
  const prepared = prepare(input.block, logging);
  result.prepared = prepared;
  identity.preparedBlockReuse = prepare(prepared, logging) === prepared;
  for (const secret of input.laterRegisteredSecrets ?? []) register(secret);
  if (Object.hasOwn(input, "replacePreparedText")) prepared.text = input.replacePreparedText;
  const message = { ...input.message, content: [prepared] };
  const persisted = store(message, { config: { logging } });
  result.stored = persisted;
  identity.storageMessageReuse = persisted === message;
  identity.storageBlockPrepared = isPrepared(persisted.content[0], persisted.content[0].text, logging);
}
process.stdout.write(JSON.stringify({ covers: [], result, identity }) + "\n");
