// Explicit all-source policy profile. No compiled OpenClaw module may enter
// this graph; original private marks and their redactors share module identity.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const request = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const root = fs.realpathSync(request.checkout), fixture = request.fixtureDirectory;
fs.mkdirSync(fixture, { recursive: true });
process.env.OPENCLAW_STATE_DIR = path.join(fixture, "state");
process.env.OPENCLAW_CONFIG_PATH = path.join(fixture, "openclaw.json");
process.env.OPENCLAW_HOME = fixture;
process.env.VITEST = "1";
fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify({ logging: {
  level: "silent", consoleLevel: "silent", file: path.join(fixture, "native.log") } }));
Object.defineProperty(globalThis, "fetch", { writable: false,
  value: async () => { throw Error("Network is disabled in the all-source redaction profile"); } });
const trackedListing = await promisify(execFile)("git", ["ls-files", "-z"], {
  cwd: root, encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: 10000,
});
const tracked = new Set(trackedListing.stdout.split("\0").filter(Boolean));
const aliases = JSON.parse(fs.readFileSync(path.join(root, "tsconfig.json"), "utf8")).compilerOptions.paths;
const sources = new Set(["tsconfig.json"]), dependencySources = new Map();
const packages = request.dependencies.packages.map((entry) => ({ ...entry, directory: fs.realpathSync(entry.directory),
  hashes: new Map(entry.files.map((file) => [file.path, file.sha256])) }));
const sourceUrl = (relative) => pathToFileURL(path.join(root, relative)).href;
const inside = (filename) => filename === root || filename.startsWith(root + path.sep);
function dependencyFile(filename) {
  for (const owner of packages) {
    const relative = path.relative(owner.directory, filename).replaceAll(path.sep, "/");
    if (owner.hashes.has(relative)) return { owner, relative };
  }
}
function declaredAlias(specifier) {
  let targets = aliases[specifier];
  let wildcard = false;
  if (!targets) for (const [name, values] of Object.entries(aliases)) {
    if (!name.endsWith("/*") || !specifier.startsWith(name.slice(0, -1))) continue;
    const tail = specifier.slice(name.length - 1);
    targets = values.map((value) => value.replace("*", tail));
    wildcard = true;
    break;
  }
  if (!targets) return;
  if (targets.length !== 1 || !targets[0].startsWith("./")) throw Error("Ambiguous original workspace source alias");
  let relative = targets[0].slice(2);
  if (!path.extname(relative)) relative += ".ts";
  if (relative.includes("..")) throw Error("Workspace alias escaped its source root");
  if (!tracked.has(relative)) {
    if (wildcard) return;
    throw Error(`Workspace alias does not name an original tracked source: ${specifier} -> ${relative}`);
  }
  return sourceUrl(relative);
}
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("node:")) return nextResolve(specifier, context);
    const alias = declaredAlias(specifier);
    if (alias) return { url: alias, shortCircuit: true };
    for (const owner of packages) if (specifier === owner.name || specifier.startsWith(owner.name + "/")) {
      const resolved = nextResolve(specifier, { ...context, parentURL: pathToFileURL(path.join(owner.directory, "package.json")).href });
      const filename = fs.realpathSync(fileURLToPath(resolved.url));
      if (!dependencyFile(filename)) throw Error("A source dependency escaped its authenticated package");
      return { url: pathToFileURL(filename).href, shortCircuit: true };
    }
    if (specifier.startsWith(".") && context.parentURL?.startsWith("file:")) {
      const candidate = fileURLToPath(new URL(specifier, context.parentURL));
      if (inside(candidate)) {
        const original = candidate.endsWith(".js") ? candidate.slice(0, -3) + ".ts" : candidate;
        if (fs.existsSync(original)) return { url: pathToFileURL(original).href, shortCircuit: true };
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (!url.startsWith("file:")) {
      if (!url.startsWith("node:")) throw Error("Unsupported all-source module origin");
      return nextLoad(url, context);
    }
    const filename = fs.realpathSync(fileURLToPath(url));
    const dependency = dependencyFile(filename);
    if (dependency) {
      const sha256 = crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
      if (sha256 !== dependency.owner.hashes.get(dependency.relative)) throw Error("Source dependency bytes changed");
      dependencySources.set(`${dependency.owner.name}\0${dependency.relative}`, { package: dependency.owner.name,
        path: dependency.relative, sha256 });
    } else {
      const relative = path.relative(root, filename).replaceAll(path.sep, "/");
      if (!inside(filename) || !tracked.has(relative) || relative.startsWith("dist/") || relative.includes("/dist/")) throw Error("Compiled or untracked code entered the explicit source graph");
      sources.add(relative);
    }
    return nextLoad(url, context);
  },
});

const redact = await import(sourceUrl("src/logging/redact.ts"));
const internal = await import(sourceUrl("src/logging/redact-internal-state.ts"));
const registry = await import(sourceUrl("src/logging/secret-redaction-registry.ts"));
const logger = await import(sourceUrl("src/logging/logger.ts"));
const transcript = await import(sourceUrl("src/agents/transcript-redact.ts"));
const configRegex = await import(sourceUrl("src/security/config-regex.ts"));
const reset = globalThis[Symbol.for("openclaw.secretRedactionRegistryTestApi")].resetSecretRedactionRegistryForTest;
const results = [];
for (const testCase of request.cases) {
  reset();
  const input = testCase.input;
  const base = { level: "silent", consoleLevel: "silent", file: path.join(fixture, "native.log"),
    ...(input.patterns ? { redactPatterns: input.patterns } : {}) };
  const logging = input.fullContext ? internal.fullContextToolPayloadRedactionState.mark(base) : base;
  logger.applyLoggingConfig(logging);
  for (const value of input.registeredSecrets ?? []) registry.registerSecretValueForRedaction(value);
  try {
    results.push({ id: testCase.id, covers: [], ok: true, result: {
      explicitSensitiveText: redact.redactSensitiveText(input.text, { mode: input.mode ?? "tools", ...(input.patterns ? { patterns: input.patterns } : {}) }),
      toolText: redact.redactToolPayloadText(input.text), modelText: redact.redactModelVisibleToolPayloadText(input.text),
      structuredTool: redact.redactSecrets(input.value), structuredModel: redact.redactModelVisibleSecrets(input.value),
      transcript: transcript.redactTranscriptMessage(input.message, { logging }),
      policy: internal.captureModelVisibleRedactionPolicy(logging),
      ...(input.directRegex ? { directCompiler: (() => {
        const compiled = configRegex.compileConfigRegex(input.directRegex.source, input.directRegex.flags);
        return compiled && { pattern: compiled.pattern, flags: compiled.flags, reason: compiled.reason,
          accepted: Boolean(compiled.regex) };
      })() } : {}),
    } });
  } catch (error) { results.push({ id: testCase.id, covers: [], ok: false, error: { name: error.name, message: error.message } }); }
}
logger.resetLogger();
process.stdout.write(JSON.stringify({ profile: "explicit-all-source-redaction-policy", sourceFallback: false,
  compiledOpenClawModulesAllowed: false, results,
  runtime: { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
    icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode,
    sha256: crypto.createHash("sha256").update(fs.readFileSync(process.execPath)).digest("hex") },
  sources: [...sources].sort().map((relative) => ({ path: relative,
    sha256: crypto.createHash("sha256").update(fs.readFileSync(path.join(root, relative))).digest("hex") })),
  dependencySources: [...dependencySources.values()] }) + "\n");
