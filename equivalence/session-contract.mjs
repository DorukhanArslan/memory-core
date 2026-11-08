// Pure original owners supplement the real persisted-session runtime profile.
export async function runSessionContract(input, source) {
  if (input.kind === "source-policy") {
    const owner = await source("src/agents/memory-search-source-policy.ts");
    return { policy: owner.resolveMemorySearchSourcePolicy(input.params) };
  }
  if (input.kind === "indexable") {
    const owner = await source("extensions/memory-core/src/memory/manager-session-sync-state.ts");
    return { indexable: owner.isMemorySessionIndexable(input.entry, input.archivedSessionKey) };
  }
  throw Error(`Unsupported source session-contract operation: ${input.kind}`);
}
