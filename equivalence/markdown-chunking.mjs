// Thin API/fixture adapter; every chunk comes from the exact pinned TS owner.
export async function runMarkdownChunking(input, importReference) {
  const { chunkMarkdown } = await importReference("packages/memory-host-sdk/src/host/markdown-chunks.ts");
  const content = input.contentUnits === undefined ? input.content : String.fromCharCode(...input.contentUnits);
  const sourceLines = content.split("\n");
  const units = (value) => Array.from({ length: value.length }, (_, index) => value.charCodeAt(index));
  if (input.kind === "helpers") {
    const { estimateStringChars } = await importReference("packages/normalization-core/src/cjk-chars.ts");
    const { truncateUtf16Safe, sliceUtf16Safe } = await importReference("packages/normalization-core/src/utf16-slice.ts");
    return {
      estimatedChars: estimateStringChars(content),
      utf16Length: content.length,
      truncatedCodeUnits: input.limits.map((limit) => units(truncateUtf16Safe(content, limit))),
      slicedCodeUnits: input.slices.map(([start, end]) => units(sliceUtf16Safe(content, start, end ?? undefined))),
    };
  }
  return {
    chunks: chunkMarkdown(content, {
      tokens: input.tokens ?? 400,
      overlap: input.overlap ?? 80,
      perEntry: input.perEntry ?? false,
    }).map((chunk) => ({
      startLine: chunk.startLine,
      endLine: chunk.endLine,
      entryStartLine: chunk.entryStartLine ?? null,
      entryEndLine: chunk.entryEndLine ?? null,
      text: chunk.text,
      hash: chunk.hash,
      sourceLineCodeUnits: sourceLines.slice(chunk.startLine - 1, chunk.endLine).map(units),
      entrySourceLineCodeUnits: chunk.entryStartLine === undefined ? null : sourceLines.slice(chunk.entryStartLine - 1, chunk.entryEndLine).map(units),
    })),
  };
}
