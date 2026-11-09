// Transport and observations only. All redaction/session behavior is upstream.
import fs from "node:fs";
import crypto from "node:crypto";

export const APPROVED_MODEL_RUNTIME = Object.freeze({
  nodeVersion: "v24.16.0", icuVersion: "78.3", unicodeVersion: "17.0",
  sha256: "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
});

export function modelRuntimeIdentity() {
  const identity = { execPath: fs.realpathSync(process.execPath), nodeVersion: process.version,
    icuVersion: process.versions.icu, unicodeVersion: process.versions.unicode,
    sha256: crypto.createHash("sha256").update(fs.readFileSync(process.execPath)).digest("hex") };
  for (const [key, value] of Object.entries(APPROVED_MODEL_RUNTIME)) {
    if (identity[key] !== value) throw Error("The model boundary requires the approved Node/ICU/Unicode binary");
  }
  return identity;
}

export function modelChildEnvironment() {
  if (!process.env.NODE_OPTIONS || !process.env.MEMORY_EQ_RELEASE_CONTEXT) {
    throw Error("Model boundary children require the inherited protected release bootstrap");
  }
  return { PATH: process.env.PATH, LANG: "C.UTF-8", TZ: "UTC",
    NODE_OPTIONS: process.env.NODE_OPTIONS, MEMORY_EQ_RELEASE_CONTEXT: process.env.MEMORY_EQ_RELEASE_CONTEXT };
}

export function observeModelChildStreams(child) {
  let stdout = "", stderr = "";
  // Decode across byte chunks with Node's own incremental UTF-8 decoder.
  // Stringifying each Buffer independently corrupts a split multibyte scalar.
  child.stdout.setEncoding("utf8"); child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  return () => ({ stdout, stderr });
}

export function modelError(error) {
  const seen = new Set();
  const observe = (value) => {
    if (value === null || typeof value !== "object") return value;
    if (seen.has(value)) return { $diagnosticCircularReference: true };
    seen.add(value);
    if (Array.isArray(value)) return value.map(observe);
    const own = Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, observe(value[key])]));
    return value instanceof Error ? { name: value.name, message: value.message, ...own } : own;
  };
  return error !== null && typeof error === "object" ? observe(error)
    : { name: typeof error, message: String(error), value: error };
}

export function modelEncode(value) {
  return JSON.parse(JSON.stringify(value, (_key, item) => typeof item === "function"
    ? { $type: "function", name: item.name, source: String(item) } : item));
}

export function modelSessionSql(database) {
  return Object.fromEntries(database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND " +
    "(name GLOB 'session_*' OR name GLOB 'transcript_*') ORDER BY name").all().map(({ name }) => {
    if (!/^[A-Za-z0-9_]+$/.test(name)) throw Error("Unexpected owned transcript SQL identifier");
    return [name, { columns: database.prepare(`PRAGMA table_info("${name}")`).all(),
      rows: database.prepare(`SELECT * FROM "${name}"`).all().map((row) => Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key, value instanceof Uint8Array
          ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) }];
  }));
}

export function modelMarkerState(message, redaction, logging) {
  return (Array.isArray(message?.content) ? message.content : []).map((block, index) => ({ index,
    type: block?.type ?? null, ...(block?.type === "text" && typeof block.text === "string"
      ? { prepared: redaction.U(block, block.text, logging), text: block.text } : {}) }));
}
