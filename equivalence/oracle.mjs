// Test-only transport. Every algorithm below is imported from the actual pinned
// source checkout; this file only resolves TS source modules and adapts JSON.
import fs from "node:fs";
import path from "node:path";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import crypto from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

Object.defineProperty(globalThis, "fetch", {
  configurable: false, writable: false,
  value: async function deniedSourceOracleFetch() {
    throw Error("Network fetches are disabled in model-free source comparisons");
  },
});

const root = fs.realpathSync(process.argv[2]);
// Load the argument/fixture adapters before installing the reference-only hook.
// Their source hashes are retained separately by the Python harness.
const adapters = new Map();
for (const [operation, filename, name] of [
  ["storage-discovery", "storage-discovery.mjs", "runStorageDiscovery"],
  ["storage-read-paths", "storage-paths.mjs", "runStoragePaths"],
  ["index-identity", "index-identity.mjs", "runIndexIdentity"],
  ["vector-scoring", "vector-scoring.mjs", "runVectorScoring"],
  ["hybrid-scoring", "hybrid-scoring.mjs", "runHybridScoring"],
  ["embedding-cache", "embedding-cache.mjs", "runEmbeddingCache"],
  ["incremental-index", "incremental-index.mjs", "runIncrementalIndex"],
  ["index-publication", "index-publication.mjs", "runIndexPublication"],
  ["markdown-chunking", "markdown-chunking.mjs", "runMarkdownChunking"],
  ["flush-contract", "flush-contract.mjs", "runFlushContract"],
  ["flush-target", "flush-target.mjs", "runFlushTarget"],
  ["bootstrap-budget", "bootstrap-budget.mjs", "runBootstrapBudget"],
  ["session-projection", "session-projection.mjs", "runSessionProjection"],
]) {
  const url = new URL(filename, import.meta.url);
  if (fs.existsSync(fileURLToPath(url))) adapters.set(operation, (await import(url.href))[name]);
}
const request = JSON.parse(fs.readFileSync(0, "utf8"));
if (!Array.isArray(request.cases)) throw Error("Supply an array of equivalence cases.");
const dependencySources = new Map();
const packages = (request.dependencies?.packages ?? []).map((entry) => ({
  ...entry, directory: fs.realpathSync(entry.directory),
  hashes: new Map(entry.files.map((file) => [file.path, file.sha256])),
}));
const dependencyFile = (filename) => {
  for (const entry of packages) {
    const relative = path.relative(entry.directory, filename).replaceAll(path.sep, "/");
    if (entry.hashes.has(relative)) return { entry, relative };
  }
  return undefined;
};
let trackedFiles;
try {
  trackedFiles = (await promisify(execFile)("git", ["ls-files", "-z"], {
    cwd: root, encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: 10000,
  })).stdout;
} catch {
  throw Error("Could not verify tracked reference source files.");
}
const trackedSources = new Set(trackedFiles.split("\0").filter(Boolean));
const sources = new Set();
const sourceUrl = (relative) => pathToFileURL(path.join(root, relative)).href;
const isInside = (candidate) => candidate === root || candidate.startsWith(root + path.sep);
const sourcePaths = trackedSources.has("tsconfig.json")
  ? JSON.parse(fs.readFileSync(path.join(root, "tsconfig.json"), "utf8")).compilerOptions?.paths ?? {}
  : {};
function declaredWorkspaceSource(specifier) {
  if (!specifier.startsWith("@openclaw/") && !specifier.startsWith("openclaw/plugin-sdk/")) return;
  let mapped = sourcePaths[specifier];
  if (!mapped && /^openclaw\/plugin-sdk\/[a-z][a-z0-9-]*$/.test(specifier)
      && JSON.stringify(sourcePaths["openclaw/plugin-sdk/*"]) === '["./src/plugin-sdk/*.ts"]') {
    mapped = [`./src/plugin-sdk/${specifier.split("/").at(-1)}.ts`];
  }
  if (!mapped) return;
  if (!Array.isArray(mapped) || mapped.length !== 1 || typeof mapped[0] !== "string"
      || !/^\.\/(?:packages|src)\/[A-Za-z0-9_./-]+\.ts$/.test(mapped[0])) {
    throw Error("Unsupported declared workspace source mapping");
  }
  const relative = mapped[0].slice(2);
  if (relative.split("/").includes("..") || !trackedSources.has(relative)
      || !isInside(fs.realpathSync(path.join(root, relative)))) {
    throw Error("Workspace source mapping escapes the tracked reference");
  }
  sources.add("tsconfig.json");
  return relative;
}
const publicSources = new Map([
  ["openclaw/plugin-sdk/string-coerce-runtime", "src/plugin-sdk/string-coerce-runtime.ts"],
  ["openclaw/plugin-sdk/memory-core-host-engine-schema", "src/plugin-sdk/memory-core-host-engine-schema.ts"],
  ["openclaw/plugin-sdk/memory-core-host-engine-indexing", "src/plugin-sdk/memory-core-host-engine-indexing.ts"],
  ["openclaw/plugin-sdk/sqlite-worker-runtime", "src/plugin-sdk/sqlite-worker-runtime.ts"],
  ["openclaw/plugin-sdk/memory-core-host-runtime-core", "src/plugin-sdk/memory-core-host-runtime-core.ts"],
  ["@openclaw/net-policy/redact-sensitive-url", "packages/net-policy/src/redact-sensitive-url.ts"],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    for (const projection of request.bindings?.allowedResolutions ?? []) {
      if (specifier === projection.specifier && context.parentURL === sourceUrl(projection.parent)) {
        return { url: sourceUrl(projection.target), shortCircuit: true };
      }
    }
    const declared = declaredWorkspaceSource(specifier);
    if (declared) return { url: sourceUrl(declared), shortCircuit: true };
    if (publicSources.has(specifier)) {
      return { url: sourceUrl(publicSources.get(specifier)), shortCircuit: true };
    }
    const sourcePackage = /^@openclaw\/(normalization-core|media-core|session-url-contract|retry|model-catalog-core|llm-core|ai)(?:\/([a-z][a-z0-9-]*(?:\/[a-z][a-z0-9-]*)*))?$/.exec(specifier);
    if (sourcePackage) {
      const [, packageName, subpath] = sourcePackage;
      const name = subpath ?? "index";
      let sourceName = name;
      if (!/^[a-z][a-z0-9-]*(?:\/[a-z][a-z0-9-]*)*$/.test(name)) throw Error("Invalid workspace source module.");
      if (packageName === "model-catalog-core" || packageName === "llm-core" || packageName === "ai") {
        const manifest = `packages/${packageName}/package.json`;
        if (!trackedSources.has(manifest)) throw Error("Untracked source package manifest.");
        const declared = JSON.parse(fs.readFileSync(path.join(root, manifest), "utf8"));
        const exported = declared.exports?.[subpath ? `./${subpath}` : "."];
        const target = typeof exported === "string" ? exported : exported?.import ?? exported?.default;
        const declaredPath = typeof target === "string"
          ? /^\.\/dist\/([a-z][a-z0-9-]*(?:\/[a-z][a-z0-9-]*)*)\.mjs$/.exec(target) : undefined;
        if (declared.name !== `@openclaw/${packageName}` || !declaredPath) {
          throw Error("Workspace source alias differs from its declared package export.");
        }
        sourceName = declaredPath[1];
        sources.add(manifest);
      }
      return { url: sourceUrl(`packages/${packageName}/src/${sourceName}.ts`), shortCircuit: true };
    }
    for (const entry of packages) {
      if (specifier === entry.name || specifier.startsWith(entry.name + "/")) {
        // Continue with Node's normal package export resolver from the verified
        // package tree. Calling require.resolve here would reenter this hook.
        const resolution = nextResolve(specifier, {
          ...context, parentURL: pathToFileURL(path.join(entry.directory, "package.json")).href,
        });
        const resolved = fs.realpathSync(fileURLToPath(resolution.url));
        if (!dependencyFile(resolved)) throw Error("Dependency resolution escaped the verified artifact.");
        return { url: pathToFileURL(resolved).href, shortCircuit: true };
      }
    }
    // Upstream TS imports its eventual .js build outputs. Resolve to the exact
    // tracked source file. Node executes its original TypeScript contents.
    if (specifier.startsWith(".") && specifier.endsWith(".js") && context.parentURL?.startsWith("file:")) {
      const candidate = fileURLToPath(new URL(specifier.slice(0, -3) + ".ts", context.parentURL));
      if (isInside(candidate) && fs.existsSync(candidate)) {
        return { url: pathToFileURL(candidate).href, shortCircuit: true };
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith("file:")) {
      const source = fs.realpathSync(fileURLToPath(url));
      const dependency = dependencyFile(source);
      if (dependency) {
        const sha256 = crypto.createHash("sha256").update(fs.readFileSync(source)).digest("hex");
        if (sha256 !== dependency.entry.hashes.get(dependency.relative)) throw Error("Dependency bytes changed.");
        dependencySources.set(`${dependency.entry.name}\0${dependency.relative}`, {
          package: dependency.entry.name, path: dependency.relative, sha256,
        });
        return nextLoad(url, context);
      }
      if (!isInside(source)) throw Error("Reference import escaped the pinned checkout and verified artifacts.");
      const relative = path.relative(root, source).replaceAll(path.sep, "/");
      if (!trackedSources.has(relative)) throw Error("Reference import is not a tracked source file.");
      sources.add(relative);
    } else if (!url.startsWith("node:")) {
      throw Error("Reference import used an unsupported module source.");
    }
    return nextLoad(url, context);
  },
});

const number = (value) => typeof value === "string"
  ? ({ nan: Number.NaN, infinity: Number.POSITIVE_INFINITY, "-infinity": Number.NEGATIVE_INFINITY })[value]
  : value;

async function execute(operation, input) {
  if (adapters.has(operation)) return adapters.get(operation)(input, (relative) => import(sourceUrl(relative)));
  const source = (name) => import(sourceUrl(`extensions/memory-core/src/memory/${name}.ts`));
  switch (operation) {
    case "fts-query":
      return (await source("keyword-query")).buildFtsQuery(input.text);
    case "bm25":
      return (await source("keyword-query")).bm25RankToScore(number(input.rank));
    case "tokenization":
      // Tokenization is a set contract. Sort by Unicode scalar values as Python
      // does, rather than turning JS insertion order into an invented contract.
      return [...(await source("tokenize")).tokenize(input.text)].sort((a, b) => {
        const left = [...a].map((char) => char.codePointAt(0));
        const right = [...b].map((char) => char.codePointAt(0));
        for (let i = 0; i < Math.min(left.length, right.length); i++) {
          if (left[i] !== right[i]) return left[i] - right[i];
        }
        return left.length - right.length;
      });
    case "temporal-decay":
      return (await source("temporal-decay")).applyTemporalDecayToHybridResults({
        results: input.results,
        temporalDecay: { enabled: input.enabled, halfLifeDays: input.halfLifeDays },
        nowMs: input.nowMs,
        sessionSourceMtimes: input.sessionSourceMtimes && new Map(Object.entries(input.sessionSourceMtimes)),
      });
    case "mmr":
      return (await source("mmr")).applyMMRToHybridResults(input.items, {
        enabled: input.enabled, lambda: input.lambda,
      });
    default:
      throw Error(`Unsupported equivalence operation: ${operation}`);
  }
}

const results = [];
for (const testCase of request.cases) {
  try {
    results.push({ id: testCase.id, ok: true, result: await execute(testCase.operation, testCase.input) });
  } catch (error) {
    results.push({ id: testCase.id, ok: false, error: { type: error.name, message: error.message } });
  }
}
process.stdout.write(JSON.stringify({
  results,
  sources: [...sources].sort().map((relative) => ({
    path: relative,
    sha256: crypto.createHash("sha256").update(fs.readFileSync(path.join(root, relative))).digest("hex"),
  })),
  dependencySources: [...dependencySources.values()].sort((a, b) =>
    a.package.localeCompare(b.package) || a.path.localeCompare(b.path)),
}) + "\n");
