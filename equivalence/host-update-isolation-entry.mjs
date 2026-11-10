import fs from "node:fs/promises";
import { createHash } from "node:crypto";
import { writeModelJson, modelError } from "./model-runtime-observation.mjs";

const context = JSON.parse(await fs.readFile(process.env.MEMORY_EQ_RELEASE_CONTEXT, "utf8"));
let stdin = "";
for await (const chunk of process.stdin) stdin += chunk;
const profile = context.hostUpdateIsolationProfile;
let testCase;
try {
  if (createHash("sha256").update(stdin).digest("hex") !== profile.caseWireSha256) {
    throw Error("The whole host literal differs from the protected input binding");
  }
  testCase = JSON.parse(stdin);
  if (testCase.id !== profile.caseId || testCase.operation !== profile.operation ||
      Object.keys(testCase).sort().join() !== "id,input,operation") throw Error("Unexpected update input");
  const { runHostUpdateIsolationRuntime } = await import("./host-update-isolation-runtime.mjs");
  const result = await runHostUpdateIsolationRuntime(testCase.input, {
    runtimeRoot: context.runtime.runtimeRoot, evidenceDirectory: context.evidenceDirectory,
  });
  await writeModelJson({ id: testCase.id, ok: true, result });
} catch (error) {
  await writeModelJson({ id: profile.caseId, ok: false, error: modelError(error) });
  process.exitCode = 2;
}
