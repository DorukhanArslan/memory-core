// Original source owners perform parameter coercion and read-result shaping.
// This adapter only passes fixture input and captures public error properties.
export async function runGetContract(input, source) {
  try {
    if (input.kind === "params") {
      const common = await source("src/agents/tools/common.ts");
      const params = common.asToolParamsRecord(input.params);
      return { params: {
        path: common.readToolStringParam(params, "path", { required: true }),
        from: common.readPositiveIntegerParam(params, "from"),
        lines: common.readPositiveIntegerParam(params, "lines"),
      } };
    }
    const owner = await source("packages/memory-host-sdk/src/host/read-file-shared.ts");
    if (input.kind === "read-result") return { result: owner.buildMemoryReadResult(input.options) };
    if (input.kind === "read-result-slice") return { result: owner.buildMemoryReadResultFromSlice(input.options) };
    throw Error(`Unsupported get-contract source operation: ${input.kind}`);
  } catch (error) {
    return { error: { name: error.name, ...(error.status === undefined ? {} : { status: error.status }),
      message: error.message } };
  }
}
