// Fixture transport only: the pinned native file reader owns all projection,
// sanitization, redaction, provenance and hash decisions.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export async function runSessionProjection(input, importReference) {
  const reset = await importReference("packages/memory-host-sdk/src/host/session-reset-recall.ts");
  if (input.resetOnly) return {resolvedResetCutoff: reset.resolveSessionResetRecallCutoff(input.resetEvents)};
  const native = await importReference("packages/memory-host-sdk/src/host/session-files.ts");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "memory-core-session-projection-"));
  try {
    if (input.reopenHeartbeatCorpus || input.reopenDatetimeCorpus) {
      const relative = input.reopenDatetimeCorpus ? "agents/main/sessions/calendar.jsonl" : "agents/main/sessions/heartbeat.jsonl";
      const filename = path.join(directory, relative);
      await fs.mkdir(path.dirname(filename), { recursive: true });
      await fs.writeFile(filename, input.jsonl, "utf8");
      await fs.utimes(filename, input.mtimeMs / 1000, input.mtimeMs / 1000);
      const reads = [];
      for (let attempt = 0; attempt < 2; attempt++) {
        const observed = [];
        const entry = await native.buildSessionEntryInProcess(filename, {
          sessionKind: "unknown", onTranscriptMessage: (message, at) => observed.push({message, at}),
        });
        if (entry?.absPath !== filename) throw Error("Original corpus did not return its owned file");
        reads.push({entry: {...entry, absPath: relative}, observed,
          sourceSha256: createHash("sha256").update(await fs.readFile(filename)).digest("hex")});
      }
      return {reads};
    }
    const filename = path.join(directory, input.filename ?? "fixture.jsonl");
    await fs.writeFile(filename, input.jsonl, "utf8");
    await fs.utimes(filename, input.mtimeMs / 1000, input.mtimeMs / 1000);
    const observed = [];
    const entry = await native.buildSessionEntryInProcess(filename, {
      generatedByDreamingNarrative: input.generatedByDreamingNarrative ?? false,
      generatedByCronRun: input.generatedByCronRun ?? false,
      sessionKind: input.sessionKind ?? "unknown",
      onTranscriptMessage: (message, at) => observed.push({message, at}),
    });
    if (!entry) throw Error("Native session fixture unexpectedly returned no entry");
    const lineCount = entry.lineMap.length;
    return {
      entry: {
        content: entry.content,
        lineMap: entry.lineMap,
        messageTimestampsMs: entry.messageTimestampsMs,
        lineProvenance: entry.lineProvenance,
        hash: entry.hash,
        sessionKind: entry.sessionKind,
        generatedByDreamingNarrative: entry.generatedByDreamingNarrative ?? false,
        generatedByCronRun: entry.generatedByCronRun ?? false,
        resetRecallCutoff: native.readSessionEntryResetRecallCutoff(entry),
      },
      observed,
      prefixHashChecks: [-1, 0, lineCount, lineCount + 1]
        .map((count) => native.matchesSessionEntryPrefixHash(entry, count, entry.hash)),
      resolvedResetCutoff: Object.hasOwn(input, "resetEvents")
        ? reset.resolveSessionResetRecallCutoff(input.resetEvents) : null,
    };
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
  }
}
