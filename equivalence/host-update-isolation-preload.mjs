// Independent, provider-free update/isolation host capability. Only the harness
// can award acceptance credit; the inherited context carries opaque case hashes.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { threadId } from "node:worker_threads";

const filename = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!filename || !path.isAbsolute(filename)) throw Error("Update context required");
const context = JSON.parse(fs.readFileSync(filename, "utf8"));
const profile = context.hostUpdateIsolationProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
const approved = {
  "host-update-isolation-ascii": "f2baee25788e38724908c1bab506906b246875926d98d1235e585cb6c8005393",
  "host-update-isolation-unicode": "48a300945ad635e1e129f85c02729527ae300def9c46d75f0c2004258ec8ae01",
  "host-update-isolation-write-refusal": "658b4988acd0fc3efe3710275476f4345ddc06c4ef8b2f4349de63ff30dbb320",
  "host-update-isolation-publication-failure": "ea32fd43d2f13f760b889513f1e228b5272390fdab080bb3ee45fa59fdc04bd2"
};
const contextKeys = ["schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
  "hostUpdateIsolationProfile", "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
  "configPath", "approvedReferenceSources", "fixtureSourceCaptures"].sort().join();
if (!profile || profile.kind !== "host-update-isolation-acceptance" ||
    Object.keys(context).sort().join() !== contextKeys || context.kind !== "release-oracle-execution" ||
    Object.keys(profile).sort().join() !== ["kind", "operation", "caseId", "caseWireSha256", "nodeRuntime", "acceptancePointsAwarded"].sort().join() ||
    profile.operation !== "host-update-isolation-runtime" || profile.acceptancePointsAwarded !== 0 ||
    !Object.hasOwn(approved, profile.caseId) || approved[profile.caseId] !== profile.caseWireSha256 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "hostUpdateIsolationProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length) {
  throw Error("Update capability cannot borrow profiles, source substitutions or another family's input carrier");
}
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "host-update-isolation-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
