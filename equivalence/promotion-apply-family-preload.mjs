// Independent development capability. Never compose with another lane's profile.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { threadId } from "node:worker_threads";

const filename = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!filename || !path.isAbsolute(filename)) throw Error("Family context required");
const context = JSON.parse(fs.readFileSync(filename, "utf8"));
const profile = context.promotionApplyFamilyProfile;
const own = fileURLToPath(import.meta.url);
const ownHash = crypto.createHash("sha256").update(fs.readFileSync(own)).digest("hex");
if (!profile || profile.kind !== "promotion-apply-family-development" ||
    profile.operation !== "promotion-apply-family-runtime" || profile.acceptancePointsAwarded !== 0 ||
    JSON.stringify(profile.nodeRuntime) !== JSON.stringify(context.approvedNodeRuntime) ||
    Object.keys(context).some(key => key.endsWith("Profile") && key !== "promotionApplyFamilyProfile") ||
    !context.allowedLocal?.some(entry => entry.path === own && entry.sha256 === ownHash) ||
    (context.approvedReferenceSources ?? []).length || (context.fixtureSourceCaptures ?? []).length ||
    crypto.createHash("sha256").update(fs.readFileSync(profile.casePath)).digest("hex") !== profile.caseFileSha256) {
  throw Error("Family capability cannot borrow another profile, source, hook or literal");
}
// The shared preload authenticates every actual import in both the main thread
// and inherited workers, verifies the exact binary and denies runtime fetch.
await import("./release-preload.mjs");
fs.appendFileSync(path.join(context.traceDirectory, `${process.pid}-${threadId}.jsonl`),
  JSON.stringify({ event: "promotion-family-bootstrap", pid: process.pid, threadId,
    preloadSha256: ownHash, profile }) + "\n");
