// Compare the original public merger, concept tagger and safe UTF-16 owners without projected strings.
import { runHybridScoring } from "./hybrid-scoring.mjs";

export async function runEngineUnicodeCollation(input, importReference) {
  const vocabulary = await importReference("extensions/memory-core/src/concept-vocabulary.ts");
  const strings = await importReference("packages/normalization-core/src/string-coerce.ts");
  const cuts = await importReference("packages/normalization-core/src/utf16-slice.ts");
  const word = new Intl.Segmenter("und", { granularity: "word" });
  const merge = await runHybridScoring(input.merge, importReference);
  const texts = input.texts.map(text => ({
    input: text,
    units: Array.from({ length: text.length }, (_, index) => text.charCodeAt(index)),
    length: text.length,
    lower: strings.normalizeLowercaseStringOrEmpty(text),
    wordLike: Array.from(word.segment(text)).filter(item => item.isWordLike).map(item => item.segment),
    tags: vocabulary.deriveConceptTags({ path: "", snippet: text, limit: 64 }),
    slices: input.ranges.map(([start, end]) => cuts.sliceUtf16Safe(text, start, end)),
    truncated: input.limits.map(limit => cuts.truncateUtf16Safe(text, limit)),
  }));
  return { merge, texts };
}
