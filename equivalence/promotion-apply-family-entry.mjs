import fs from "node:fs/promises";
import { writeModelJson, modelError } from "./model-runtime-observation.mjs";

const context = JSON.parse(await fs.readFile(process.env.MEMORY_EQ_RELEASE_CONTEXT, "utf8"));
const testCase = JSON.parse(await fs.readFile(context.promotionApplyFamilyProfile.casePath, "utf8"));
try {
  const { runPromotionApplyFamily } = await import("./promotion-apply-family-runtime.mjs");
  const result = await runPromotionApplyFamily(testCase, {
    runtimeRoot: context.runtime.runtimeRoot, evidenceDirectory: context.evidenceDirectory,
  });
  await writeModelJson({ id: testCase.id, ok: true, result });
} catch (error) {
  await writeModelJson({ id: testCase.id, ok: false, error: modelError(error) });
  process.exitCode = 2;
}
