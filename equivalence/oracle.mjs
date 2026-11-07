// Test-only transport. Every algorithm below is imported from the actual pinned
// source checkout; this file only resolves TS source modules and adapts JSON.
import fs from "node:fs";
import path from "node:path";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import crypto from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const root = fs.realpathSync(process.argv[2]);
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
const publicSources = new Map([
  ["openclaw/plugin-sdk/string-coerce-runtime", "src/plugin-sdk/string-coerce-runtime.ts"],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (publicSources.has(specifier)) {
      return { url: sourceUrl(publicSources.get(specifier)), shortCircuit: true };
    }
    if (specifier.startsWith("@openclaw/normalization-core/")) {
      const name = specifier.slice("@openclaw/normalization-core/".length);
      if (!/^[a-z][a-z0-9-]*$/.test(name)) throw Error("Invalid normalization source module.");
      return { url: sourceUrl(`packages/normalization-core/src/${name}.ts`), shortCircuit: true };
    }
    // Upstream TS imports its eventual .js build outputs. Resolve to the exact
    // tracked source file without copying, editing or transpiling its contents.
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
      if (!isInside(source)) throw Error("Reference import escaped the pinned checkout.");
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

const request = JSON.parse(fs.readFileSync(0, "utf8"));
if (!Array.isArray(request.cases)) throw Error("Supply an array of equivalence cases.");
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
}) + "\n");
