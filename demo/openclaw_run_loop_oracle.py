from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class OpenClawRunLoopOracleError(RuntimeError):
    pass


# The upstream Vitest harness needs 150-210 s on this machine (162 s idle and 204 s at load
# average 7 on 2026-09-26), so 180 s timed out under load; 600 s leaves headroom.
RUN_LOOP_ORACLE_TIMEOUT_SECONDS = 600.0


def run_overflow_run_loop_oracle(
    *, repo_path: Path, timeout_seconds: float = RUN_LOOP_ORACLE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    repo_path = repo_path.resolve()
    test_dir = repo_path / "src" / "agents" / "embedded-agent-runner"
    vitest = repo_path / "node_modules" / ".bin" / "vitest"
    if not test_dir.exists():
        raise OpenClawRunLoopOracleError(f"OpenClaw run-loop test directory missing: {test_dir}")
    if not vitest.exists():
        raise OpenClawRunLoopOracleError(
            f"OpenClaw vitest binary missing; run pnpm install in {repo_path}"
        )

    test_file = test_dir / "memory-core-overflow-run-loop.oracle.test.ts"
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-run-loop-oracle-") as tmp_dir:
        output_path = Path(tmp_dir) / "result.json"
        test_file.write_text(_overflow_run_loop_oracle_test_source(), encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(vitest), "run", str(test_file.relative_to(repo_path)), "--reporter=dot"],
                cwd=repo_path,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                env={
                    **__import__("os").environ,
                    "MEMORY_CORE_OVERFLOW_ORACLE_OUT": str(output_path),
                },
            )
        finally:
            test_file.unlink(missing_ok=True)

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "OpenClaw run-loop oracle failed").strip()
            raise OpenClawRunLoopOracleError(message)
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenClawRunLoopOracleError(f"OpenClaw run-loop oracle output missing: {exc}") from exc
        if not isinstance(result, dict):
            raise OpenClawRunLoopOracleError("OpenClaw run-loop oracle output was not an object")
        return result


def _overflow_run_loop_oracle_test_source() -> str:
    return r'''
import fs from "node:fs";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import {
  makeAttemptResult,
  makeCompactionSuccess,
  makeOverflowError,
  mockOverflowRetrySuccess,
  queueOverflowAttemptWithOversizedToolOutput,
} from "./run.overflow-compaction.fixture.js";
import {
  loadRunOverflowCompactionHarness,
  mockedCompactDirect,
  mockedIsCompactionFailureError,
  mockedIsLikelyContextOverflowError,
  mockedRunEmbeddedAttempt,
  mockedSessionLikelyHasOversizedToolResults,
  mockedTruncateOversizedToolResultsInSession,
  overflowBaseRunParams as baseParams,
  resetRunOverflowCompactionHarnessMocks,
} from "./run.overflow-compaction.harness.js";
import type { EmbeddedRunAttemptResult } from "./run/types.js";

let runEmbeddedAgent: typeof import("./run.js").runEmbeddedAgent;
const scenarios: Array<Record<string, unknown>> = [];

function record(name: string, result: Awaited<ReturnType<typeof runEmbeddedAgent>>) {
  const secondAttempt = mockedRunEmbeddedAttempt.mock.calls[1]?.[0] as
    | { prompt?: unknown; suppressNextUserMessagePersistence?: unknown }
    | undefined;
  const secondPromptIncludesContinuation = String(secondAttempt?.prompt ?? "").includes(
    "Continue from the current transcript",
  );
  const secondSuppressesUserPersistence =
    secondAttempt?.suppressNextUserMessagePersistence === true;
  const firstTruncateCall = mockedTruncateOversizedToolResultsInSession.mock.calls[0]?.[0] as
    | { protectTrailingToolResults?: unknown }
    | undefined;
  scenarios.push({
    name,
    attemptCalls: mockedRunEmbeddedAttempt.mock.calls.length,
    compactCalls: mockedCompactDirect.mock.calls.length,
    truncateCalls: mockedTruncateOversizedToolResultsInSession.mock.calls.length,
    errorKind: result.meta.error?.kind ?? null,
    payloadIsError: result.payloads?.[0]?.isError ?? null,
    ...(firstTruncateCall
      ? { truncateProtectTrailing: firstTruncateCall.protectTrailingToolResults === true }
      : {}),
    ...(secondPromptIncludesContinuation || secondSuppressesUserPersistence
      ? {
          secondPromptIncludesContinuation,
          secondSuppressesUserPersistence,
        }
      : {}),
  });
}

describe("memory-core overflow run-loop oracle", () => {
  beforeAll(async () => {
    ({ runEmbeddedAgent } = await loadRunOverflowCompactionHarness());
  });

  beforeEach(() => {
    resetRunOverflowCompactionHarnessMocks();
    mockedIsCompactionFailureError.mockImplementation((msg?: string) => {
      if (!msg) {
        return false;
      }
      const lower = msg.toLowerCase();
      return lower.includes("request_too_large") && lower.includes("summarization failed");
    });
    mockedIsLikelyContextOverflowError.mockImplementation((msg?: string) => {
      if (!msg) {
        return false;
      }
      const lower = msg.toLowerCase();
      return (
        lower.includes("request_too_large") ||
        lower.includes("request size exceeds") ||
        lower.includes("context window exceeded") ||
        lower.includes("prompt too large")
      );
    });
  });

  afterAll(() => {
    const outputPath = process.env.MEMORY_CORE_OVERFLOW_ORACLE_OUT;
    if (!outputPath) {
      throw new Error("MEMORY_CORE_OVERFLOW_ORACLE_OUT missing");
    }
    fs.writeFileSync(outputPath, JSON.stringify({ ok: true, scenarios }), "utf-8");
  });

  it("successful compaction retries", async () => {
    mockOverflowRetrySuccess({
      runEmbeddedAttempt: mockedRunEmbeddedAttempt,
      compactDirect: mockedCompactDirect,
    });

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).toHaveBeenCalledTimes(1);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(result.meta.error).toBeUndefined();
    record("successful_compaction_retries", result);
  });

  it("attempt-level compaction retries without extra compaction", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(makeAttemptResult({ promptError: makeOverflowError(), compactionCount: 1 }))
      .mockResolvedValueOnce(makeAttemptResult({ promptError: null }));

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).not.toHaveBeenCalled();
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(result.meta.error).toBeUndefined();
    record("attempt_level_compaction_retries_without_extra_compaction", result);
  });

  it("failed compaction uses tool truncation fallback", async () => {
    queueOverflowAttemptWithOversizedToolOutput(mockedRunEmbeddedAttempt, makeOverflowError());
    mockedRunEmbeddedAttempt.mockResolvedValueOnce(makeAttemptResult({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce({
      ok: false,
      compacted: false,
      reason: "nothing to compact",
    });
    mockedSessionLikelyHasOversizedToolResults.mockReturnValue(true);
    mockedTruncateOversizedToolResultsInSession.mockResolvedValueOnce({
      truncated: true,
      truncatedCount: 1,
    });

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).toHaveBeenCalledTimes(1);
    expect(mockedTruncateOversizedToolResultsInSession).toHaveBeenCalledTimes(1);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(result.meta.error).toBeUndefined();
    record("failed_compaction_uses_tool_truncation_fallback", result);
  });

  it("compact then truncate runs after compaction", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        makeAttemptResult({
          promptError: makeOverflowError("Context overflow: prompt too large for the model (precheck)."),
          preflightRecovery: { route: "compact_then_truncate" },
        }),
      )
      .mockResolvedValueOnce(makeAttemptResult({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(
      makeCompactionSuccess({
        summary: "Compacted session",
        firstKeptEntryId: "entry-5",
        tokensBefore: 150000,
      }),
    );
    mockedTruncateOversizedToolResultsInSession.mockResolvedValueOnce({
      truncated: true,
      truncatedCount: 2,
    });

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).toHaveBeenCalledTimes(1);
    expect(mockedTruncateOversizedToolResultsInSession).toHaveBeenCalledTimes(1);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(result.meta.error).toBeUndefined();
    record("compact_then_truncate_runs_after_compaction", result);
  });

  it("assistant error overflow compacts and retries", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        makeAttemptResult({
          promptError: null,
          lastAssistant: {
            stopReason: "error",
            errorMessage: "request_too_large: Request size exceeds model context window",
          } as EmbeddedRunAttemptResult["lastAssistant"],
        }),
      )
      .mockResolvedValueOnce(makeAttemptResult({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(
      makeCompactionSuccess({
        summary: "Compacted session",
        firstKeptEntryId: "entry-5",
        tokensBefore: 150000,
      }),
    );

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).toHaveBeenCalledTimes(1);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(result.meta.error).toBeUndefined();
    record("assistant_error_overflow_compacts_and_retries", result);
  });

  it("mid-turn precheck continues from transcript", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        makeAttemptResult({
          promptError: makeOverflowError(
            "Context overflow: prompt too large for the model (mid-turn precheck).",
          ),
          promptErrorSource: "precheck",
          preflightRecovery: { route: "compact_only", source: "mid-turn" },
        }),
      )
      .mockResolvedValueOnce(makeAttemptResult({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(
      makeCompactionSuccess({
        summary: "Compacted after mid-turn precheck",
        firstKeptEntryId: "entry-8",
        tokensBefore: 155000,
      }),
    );

    const result = await runEmbeddedAgent(baseParams);
    const retryParams = mockedRunEmbeddedAttempt.mock.calls[1]?.[0] as {
      prompt?: unknown;
      suppressNextUserMessagePersistence?: unknown;
    };

    expect(mockedCompactDirect).toHaveBeenCalledTimes(1);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(2);
    expect(String(retryParams.prompt)).toContain("Continue from the current transcript");
    expect(retryParams.suppressNextUserMessagePersistence).toBe(true);
    expect(result.meta.error).toBeUndefined();
    record("mid_turn_precheck_continues_from_transcript", result);
  });

  it("gives up after max compaction attempts", async () => {
    const overflowError = makeOverflowError();
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(makeAttemptResult({ promptError: overflowError }))
      .mockResolvedValueOnce(makeAttemptResult({ promptError: overflowError }))
      .mockResolvedValueOnce(makeAttemptResult({ promptError: overflowError }))
      .mockResolvedValueOnce(makeAttemptResult({ promptError: overflowError }));
    mockedCompactDirect
      .mockResolvedValueOnce(makeCompactionSuccess({ summary: "Compacted 1", firstKeptEntryId: "entry-3" }))
      .mockResolvedValueOnce(makeCompactionSuccess({ summary: "Compacted 2", firstKeptEntryId: "entry-5" }))
      .mockResolvedValueOnce(makeCompactionSuccess({ summary: "Compacted 3", firstKeptEntryId: "entry-7" }));

    const result = await runEmbeddedAgent(baseParams);

    expect(mockedCompactDirect).toHaveBeenCalledTimes(3);
    expect(mockedRunEmbeddedAttempt).toHaveBeenCalledTimes(4);
    expect(result.meta.error?.kind).toBe("context_overflow");
    expect(result.payloads?.[0]?.isError).toBe(true);
    record("give_up_after_max_compaction_attempts", result);
  });
});
'''
