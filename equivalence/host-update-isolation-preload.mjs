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
  "host-update-isolation-ascii": "03bea4c1977b6bddd1095fff2e348f65481e8dbf31585f40e7ff0acd02d4b290",
  "host-update-isolation-unicode": "94c6f266e48c7cedee5447e19790a3dbe4ad08435453a0a0bfff7676cb1aae63",
  "host-update-isolation-write-refusal": "e9d7c0bc7447242718a736bbcdc62cf027caa77ce4cced3be9d809962c6fddf8",
  "host-update-isolation-publication-failure": "35885ea502411889777c9c76e4f3b0ea043f0baf67a00e4cf0805ae8c3d774fc"
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
