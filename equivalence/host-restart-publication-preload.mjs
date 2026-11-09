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
const profile = context.hostRestartPublicationProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-restart-publication-memory-ascii": "a9abc2c074286701c82f687ebd906102589164c19b9d9c0dbc503073ccbcb7b7",
  "host-restart-publication-memory-unicode": "b375edb367f6820d99a9398db9e384cf640819ae7fd246766c45d955f93b4c5b",
  "host-restart-publication-indexed-sessions": "3121b9952df01cee2e8b9cb0e8492600f560e3c87af51e632e56c71970050bd1",
  "host-restart-publication-get-failure": "05fbc5db48c37efeac4a15b38d5291f4203fcc318e70ea4131ac5b05351261ba"
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostRestartPublicationProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-restart-publication-development" ||
    Object.keys(context).sort().join() !== contextKeys ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-restart-publication-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostRestartPublicationProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Restart capability cannot borrow profiles, source substitutions or a full producer input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-restart-publication-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
