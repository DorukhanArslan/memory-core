// Independent, provider-free session host capability. Only the harness can
// award acceptance credit; the inherited context carries opaque case hashes.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { threadId } from "node:worker_threads";

const filename = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!filename || !path.isAbsolute(filename)) throw Error("Restart context required");
const context = JSON.parse(fs.readFileSync(filename, "utf8"));
const profile = context.hostRestartSessionProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-restart-session-memory-ascii": "eafee7b0e98b6543cebaeff1523325796f83a4204a0d4eba03606255ccb383d4",
  "host-restart-session-memory-unicode": "8cd6e9ff0c637d9449206e002b5cd89cdd21bff8a939d8018fcfa536442f5435",
  "host-restart-session-indexed-sessions": "1ecac5a32934aceb2d5d3d9170e8a575f3c9ffb68fd0f59f155b1ce511011fa5",
  "host-restart-session-get-failure": "4a2d28259018fd409f49dcb04e450e6946e95aa2abb7a949f2bdae5a0066bc8f"
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostRestartSessionProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-restart-session-acceptance" ||
    Object.keys(context).sort().join() !== contextKeys || context.kind !== "release-oracle-execution" ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-restart-session-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostRestartSessionProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Restart capability cannot borrow profiles, source substitutions or a full producer input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-restart-session-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
