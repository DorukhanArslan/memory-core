// Fresh process reads only real persisted owners; no prior messages are inputs.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const request = JSON.parse(fs.readFileSync(0, "utf8"));
let output;
try {
  const { directory, runtimeRoot, input } = request;
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "state");
  process.env.OPENCLAW_CONFIG_PATH = path.join(directory, "openclaw.json");
  const imp = (name) => import(pathToFileURL(path.join(runtimeRoot, name)).href);
  const cfg = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const config = await imp("dist/plugin-sdk/config-runtime.js"); config.setRuntimeConfigSnapshot(cfg);
  const sessions = await imp("dist/plugin-sdk/session-store-runtime.js");
  const accessor = await imp("dist/session-accessor-CiKKTlbe.mjs");
  const engine = await imp("dist/plugin-sdk/memory-core-host-engine-sessions.js");
  const sessionFiles = await imp("dist/session-files-DVVT4Ngb.mjs");
  const artifacts = await imp("dist/memory-artifact-provenance-DhnyWiV1.mjs");
  const sql = await imp("dist/plugin-sdk/sqlite-runtime.js");
  const scope = { agentId: input.agentId, sessionId: input.sessionId, sessionKey: input.sessionKey,
    storePath: sessions.resolveStorePath(undefined, { agentId: input.agentId }) };
  const observations = [];
  const options = { ...scope, sessionKind: "interactive", updatedAtMs: input.nowMs,
    onTranscriptMessage: (message, timestampMs) => observations.push({ message, timestampMs }) };
  const sourceEntry = await engine.buildSessionEntry(input.sessionKey, options);
  const databasePath = accessor.resolveSessionTranscriptDatabasePath(scope);
  const database = sql.openOpenClawAgentDatabase({ agentId: input.agentId, path: databasePath });
  const sessionSql = Object.fromEntries(database.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND " +
    "(name GLOB 'session_*' OR name GLOB 'transcript_*') ORDER BY name").all().map(({ name }) => {
    if (!/^[A-Za-z0-9_]+$/.test(name)) throw Error("Unexpected owned transcript schema name");
    return [name, { columns: database.db.prepare(`PRAGMA table_info("${name}")`).all(),
      rows: database.db.prepare(`SELECT * FROM "${name}"`).all().map((row) => Object.fromEntries(Object.entries(row)
        .map(([key, value]) => [key, value instanceof Uint8Array ? { type: "bytes", hex: Buffer.from(value).toString("hex") } : value]))) }];
  }));
  const result = { pid: process.pid, ppid: process.ppid, request, scope,
    events: accessor.loadTranscriptEventsSync(scope), currentEntry: sessions.getSessionEntry(scope),
    sourceEntry, sourceCutoff: sessionFiles.a(sourceEntry), observations,
    readRequest: { absPath: input.sessionKey, options: { ...options, onTranscriptMessage: true } }, databasePath, sessionSql,
    artifacts: await artifacts.n({ workspaceDir: path.join(directory, "workspace") }) };
  output = result; config.clearRuntimeConfigSnapshot();
} catch (error) {
  output = { fatal: { name: error.name, message: error.message }, stack: error.stack,
    pid: process.pid, ppid: process.ppid }; process.exitCode = 1;
}
await new Promise((resolve, reject) => process.stdout.write(JSON.stringify(output) + "\n",
  (error) => error ? reject(error) : resolve()));
