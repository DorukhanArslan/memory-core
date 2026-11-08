// Fixture transport for original pinned parser and presentation owners. There is
// no search implementation or expected response in this adapter.
export async function runSearchContract(input, source) {
  try {
    if (input.kind === "params") {
      const common = await source("src/agents/tools/common.ts");
      const params = common.asToolParamsRecord(input.params);
      return { params: {
        query: common.readToolStringParam(params, "query", { required: true }),
        maxResults: common.readPositiveIntegerParam(params, "maxResults"),
        minScore: common.readFiniteNumberParam(params, "minScore"),
      } };
    }
    if (input.kind === "presentation") {
      const owner = await source("extensions/memory-core/src/tools.citations.ts");
      const citations = owner.resolveMemoryCitationsMode({ memory: { citations: input.citationMode } });
      const includeCitations = owner.shouldIncludeCitations({ mode: citations, sessionKey: input.sessionKey });
      return { citations, includeCitations,
        results: [...owner.buildMemorySearchPresentation(input.results, includeCitations).values()] };
    }
    if (input.kind === "unavailable") {
      const owner = await source("extensions/memory-core/src/tools.shared.ts");
      return { result: owner.buildMemorySearchUnavailableResult(input.error, input.overrides) };
    }
    throw Error(`Unsupported search-contract source operation: ${input.kind}`);
  } catch (error) {
    return { error: { name: error.name, ...(error.status === undefined ? {} : { status: error.status }),
      message: error.message } };
  }
}
