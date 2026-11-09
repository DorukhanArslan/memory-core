// Independent, provider-free whole-host development capability. The inherited
// context contains opaque case hashes, never the old prompt or saved fact.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { threadId } from "node:worker_threads";

const filename = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!filename || !path.isAbsolute(filename)) throw Error("Restart context required");
const context = JSON.parse(fs.readFileSync(filename, "utf8"));
const profile = context.hostRestartProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-restart-ascii-recall": "b64ab1b162aa4c81e5713bc51469972b3cb78460206763389b6fd62e84583e91",
  "host-restart-unicode-recall": "c1e13ac38870951148306f924931fb76f0bfd9324bb34cfa3cb04e8fa3fab0bd",
  "host-restart-source-replaced-before-get": "72a5d40610a87b53687c432385fc1dc21173f1d99f2fc9e3ce480f6517a3d15d",
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostRestartProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-restart-recall-development" ||
    Object.keys(context).sort().join() !== contextKeys ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-restart-recall-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostRestartProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Restart capability cannot borrow profiles, source substitutions or a full producer input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-restart-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
