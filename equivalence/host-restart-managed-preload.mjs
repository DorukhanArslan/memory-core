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
const profile = context.hostRestartManagedProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-restart-managed-memory-ascii": "85318392a2c1f24fb901a3b7a78ab8f594585dc043591b9d4fac2ea35ece7c31",
  "host-restart-managed-memory-unicode": "eebb928d61de1715fa9ab99053e535d4907557dd937f3c4e6e857e6886cb5b55",
  "host-restart-managed-indexed-sessions": "f9d30cccbd5f1889cc19b3f2155dadec1cbadb756f52067c07bc95ec0f362b49",
  "host-restart-managed-get-failure": "bfc58f0321ca253fb850826d5790a4fd8667d946a0106647acbdfae0369c7fff"
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostRestartManagedProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-restart-managed-development" ||
    Object.keys(context).sort().join() !== contextKeys ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-restart-managed-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostRestartManagedProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Restart capability cannot borrow profiles, source substitutions or a full producer input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-restart-managed-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
