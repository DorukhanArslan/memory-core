// Fixture transport only. Original tracked TypeScript owns every native decision.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export async function runFlushContract(input, importReference) {
  if (input.kind === "plan") {
    const reference = await importReference("extensions/memory-core/src/flush-plan.ts");
    const { resolveUserTimeFormat } = await importReference("src/agents/date-time.ts");
    const originalNow = Date.now;
    try {
      Date.now = () => input.fallbackNowMs;
      const result = reference.buildMemoryFlushPlan(input.params);
      return {
        hostTimeFormat: resolveUserTimeFormat(undefined),
        plan: result === null ? null : { ...result, model: result.model ?? null },
      };
    } finally {
      Date.now = originalNow;
    }
  }
  if (input.kind === "target") {
    const reference = await importReference("src/auto-reply/reply/memory-flush-session.ts");
    const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "memory-flush-contract-"));
    const root = path.join(temporary, "workspace");
    try {
      await fs.mkdir(root);
      const relativePath = input.relativePath.replaceAll("@workspace", root);
      if (input.existingText !== null && input.existingText !== undefined) {
        const target = path.join(root, relativePath.trim());
        await fs.mkdir(path.dirname(target), { recursive: true });
        await fs.writeFile(target, input.existingText, "utf8");
      }
      let result;
      try {
        await reference.ensureMemoryFlushTargetFile({
          workspaceDir: root, relativePath, assertCurrent() {},
        });
        result = { ok: true };
      } catch (error) {
        result = { ok: false, error: { message: error.message } };
      }
      const files = {};
      async function visit(directory) {
        for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
          const target = path.join(directory, entry.name);
          if (entry.isDirectory()) await visit(target);
          else if (entry.isFile()) files[path.relative(root, target).replaceAll(path.sep, "/")] = await fs.readFile(target, "utf8");
        }
      }
      await visit(root);
      return { ...result, files };
    } finally {
      await fs.rm(temporary, { recursive: true, force: true });
    }
  }
  if (input.kind === "fresh") {
    const reference = await importReference("src/config/sessions/types.ts");
    return reference.resolveFreshSessionTotalTokens(input.entry) ?? null;
  }
  if (input.kind === "error") {
    const reference = await importReference("src/auto-reply/reply/memory-flush-errors.ts");
    const error = input.exception ? new Error(input.message, input.cause === undefined ? undefined : {
      cause: new Error(input.cause),
    }) : input.message;
    return reference.truncateMemoryFlushErrorMessage(error);
  }
  if (input.kind === "gate" || input.kind === "threshold") {
    const reference = await importReference("src/auto-reply/reply/memory-flush.ts");
    if (input.kind === "threshold") return reference.resolveCompactionThreshold(input.params);
    return {
      shouldRun: reference.shouldRunMemoryFlush({
        entry: input.entry ?? undefined, tokenCount: input.tokenCount ?? undefined,
        threshold: input.threshold,
      }),
      alreadyFlushed: input.entry == null ? null : reference.hasAlreadyFlushedForCurrentCompaction(input.entry),
    };
  }
  throw Error(`Unsupported flush contract operation: ${input.kind}`);
}
