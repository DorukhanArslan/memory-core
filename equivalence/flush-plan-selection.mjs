// Read the original host's resolved routing options and every candidate entry without changing them.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import { Session } from "node:inspector";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = "dist/agent-runner-memory-Cc4lCZcs.mjs";
const expectedHash = "9a87aeee70d84d41eb6bf764a70c0334fb679a2f1e21d817c44c5eb306d5620e";

export async function observeFlushSelection(runtimeRoot) {
  const filename = path.join(runtimeRoot, modulePath);
  const text = await fs.readFile(filename, "utf8");
  const hash = createHash("sha256").update(text).digest("hex");
  if (hash !== expectedHash) throw Error("The reviewed native flush selection owner changed");
  const url = pathToFileURL(filename).href;
  const lines = text.split("\n");
  const locate = (anchor, next = 0) => {
    const matches = lines.flatMap((s,i) => s.includes(anchor) ? [i + next] : []);
    if (matches.length !== 1) throw Error("Ambiguous flush selection source location");
    return matches[0];
  };
  const requested = locate("const selection = resolveMemoryFlushModelFallbackOptions(", 1);
  const failure = locate("async function recordMemoryFlushFailure(error, run, initialSessionEntry) {", 1);
  const candidate = locate("runCandidate: async (provider, model, runOptions) => {", 1);
  const session = new Session();
  session.connect();
  const evidence = {url, sha256: hash, sites: {requested, candidate, failure}, receipts: [], errors: []};
  const scripts = new Map();
  const points = new Map();
  function post(method, params = {}) {
    let finished = false, result, failure;
    session.post(method, params, (error, body) => { finished = true; result = body; failure = error; });
    if (!finished || failure) throw Error("Unable to read local flush debug frame: " + method);
    return result;
  }
  const properties = (id) => Object.fromEntries(post("Runtime.getProperties", {objectId: id, ownProperties: true,
    generatePreview: false}).result.filter(p => p.value).map(p => [p.name, p.value]));
  const read = value => {
    if (!value || value.type === "undefined") return {kind: "undefined"};
    if (["string", "number", "boolean"].includes(value.type) || value.subtype === "null") return value.value;
    if (value.subtype === "array") {
      const entries = properties(value.objectId);
      return Array.from({length: entries.length.value}, (_, i) => read(entries[String(i)]));
    }
    throw Error("Unexpected original flush selection property");
  };
  session.on("Debugger.scriptParsed", ({params}) => { if (params.url === url) scripts.set(params.scriptId, url); });
  session.on("Debugger.paused", ({params}) => {
    try {
      const frame = params.callFrames[0];
      const site = points.get(params.hitBreakpoints?.[0]);
      if (!site || scripts.get(frame.location.scriptId) !== url) throw Error("Unexpected flush observer stop");
      const locals = {};
      for (const scope of frame.scopeChain) {
        if (scope.type === "local" || scope.type === "block") {
          for (const [key, value] of Object.entries(properties(scope.object.objectId))) locals[key] ??= value;
        }
      }
      if (site === "failure") {
        const error = locals.error;
        const details = error.objectId ? properties(error.objectId) : {};
        evidence.receipts.push({site, line: frame.location.lineNumber, functionName: frame.functionName,
          values: {description: error.description ?? error.value, ...Object.fromEntries(
            Object.entries(details).filter(([,v]) => ["string", "number", "boolean"].includes(v.type))
              .map(([k,v]) => [k, v.value]))}});
        return;
      }
      const values = site === "selection" ? properties(locals.selection.objectId) : locals;
      const names = site === "selection" ? ["provider", "model", "requestedRouteResolution", "fallbacksOverride"] :
        ["provider", "model"];
      evidence.receipts.push({site, line: frame.location.lineNumber, functionName: frame.functionName,
        values: Object.fromEntries(names.map(name => [name, read(values[name])]))});
    } catch (error) {
      evidence.errors.push({name: error.name, message: error.message, stack: error.stack});
    } finally {
      post("Debugger.resume");
    }
  });
  try {
    post("Debugger.enable");
    for (const [site, lineNumber] of [["selection", requested], ["candidate", candidate], ["failure", failure]]) {
      const breakpoint = post("Debugger.setBreakpointByUrl", {url, lineNumber});
      points.set(breakpoint.breakpointId, site);
    }
  } catch (error) {
    session.disconnect();
    throw error;
  }
  return {evidence, close() { session.disconnect(); }};
}
