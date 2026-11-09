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
const profile = context.hostRestartPolicyProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-restart-policy-memory-ascii": "1a0344bdf3122292b8826e61fa872126336ec0fd702df6aaf7ebe7cf134be7c3",
  "host-restart-policy-memory-unicode": "11f2e9f9c2c630b86524ea9562fbe97f6ff18ed5b31c01fb2501fbf0c9df3aa8",
  "host-restart-policy-indexed-sessions": "467500cf9c27e7a3e34e5eb37f73bcd462e3bf4e71c204b22272b9d3e53e7824",
  "host-restart-policy-get-failure": "619ccf906f456cbd40f18ab10098adfd715d2f55699736b014162a6a7dbfd710"
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostRestartPolicyProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-restart-policy-development" ||
    Object.keys(context).sort().join() !== contextKeys ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-restart-policy-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostRestartPolicyProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Restart capability cannot borrow profiles, source substitutions or a full producer input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-restart-policy-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
