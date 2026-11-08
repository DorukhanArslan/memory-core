// Argument/result transport only. Native pinned exports own all budget decisions.
export async function runBootstrapBudget(input, importReference) {
  const clip = await importReference("src/agents/embedded-agent-helpers/bootstrap.ts");
  const budget = await importReference("src/agents/bootstrap-budget.ts");
  const warnings = await importReference("src/agents/bootstrap-budget-warning.ts");
  if (input.kind === "stats") {
    return { stats: budget.buildBootstrapInjectionStats({
      bootstrapFiles: input.files, injectedFiles: input.injectedFiles,
    }) };
  }
  const maxChars = input.maxChars ?? clip.resolveBootstrapMaxChars();
  const totalMaxChars = input.totalMaxChars ?? Math.max(maxChars, clip.resolveBootstrapTotalMaxChars());
  const messages = [];
  const files = clip.buildBootstrapContextFiles(input.files, {
    maxChars, totalMaxChars, warn: (message) => messages.push(message),
  });
  const stats = budget.buildBootstrapInjectionStats({ bootstrapFiles: input.files, injectedFiles: files });
  const analysis = budget.analyzeBootstrapBudget({ files: stats,
    bootstrapMaxChars: maxChars, bootstrapTotalMaxChars: totalMaxChars,
    nearLimitRatio: input.nearLimitRatio,
  });
  const warningTransitions = [];
  let previous;
  for (const step of input.warningSteps ?? [{ mode: "always" }]) {
    const warning = warnings.buildBootstrapPromptWarning({
      analysis, mode: step.mode, maxFiles: step.maxFiles,
      previousSignature: step.usePrevious && previous ? previous.signature : step.previousSignature,
      seenSignatures: step.useSeen && previous ? previous.warningSignaturesSeen : step.seenSignatures,
    });
    warningTransitions.push({ ...warning, signature: warning.signature ?? null,
      notice: budget.buildBootstrapPromptWarningNotice(warning.lines) ?? null });
    previous = warning;
  }
  return { files, warnings: messages, stats, analysis, warningTransitions };
}
