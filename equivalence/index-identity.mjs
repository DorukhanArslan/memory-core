// Argument transport only. All decisions and hashes come from the pinned source.
export async function runIndexIdentity(input, importReference) {
  const reference = await importReference(
    "extensions/memory-core/src/memory/manager-reindex-state.ts",
  );
  switch (input.kind) {
    case "state":
      return reference.resolveMemoryIndexIdentityState(input.params);
    case "sources":
      return reference.resolveConfiguredSourcesForMeta(input.sources);
    case "providers":
      return reference.resolveMemoryIndexProviderIdentities(input.params);
    case "scope":
      return reference.resolveConfiguredScopeHash({
        workspaceDir: "/equivalence/workspace",
        extraPaths: [],
        multimodal: input.multimodal,
      });
    default:
      throw Error(`Unsupported index identity operation: ${input.kind}`);
  }
}
