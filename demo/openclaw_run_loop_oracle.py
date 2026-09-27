"""The run-loop Vitest oracle (test infrastructure, demo-only).

Accepted exception to "never modify the oracle checkout" (docs/lab.md › Oracle checkout): the
upstream Vitest project only collects test files inside the checkout, and the case imports
the run-loop harness by relative path, so one generated file,
``src/agents/embedded-agent-runner/memory-core-overflow-run-loop.oracle.test.ts``
(:data:`ORACLE_TEST_FILENAME`), exists there for the duration of one Vitest run and is removed
in a ``finally`` block. A killed run (SIGKILL, a crash) can leave it behind; the next run
removes that stale copy before writing its own and reports it (a :class:`RuntimeWarning` and
``staleTestFileRemoved`` in the result). One run per checkout at a time.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

from demo.openclaw_oracle import OracleNodeError, oracle_subprocess_env


class OpenClawRunLoopOracleError(RuntimeError):
    pass


# The upstream Vitest harness needs 150-210 s on this machine (162 s idle and 204 s at load
# average 7 on 2026-09-26), so 180 s timed out under load; 600 s leaves headroom.
RUN_LOOP_ORACLE_TIMEOUT_SECONDS = 600.0
ORACLE_TEST_FILENAME = "memory-core-overflow-run-loop.oracle.test.ts"


def _remove_stale_oracle_test_file(test_file: Path) -> bool:
    """Remove a copy an interrupted run left in the checkout; True if there was one."""
    if not os.path.lexists(test_file):
        return False
    test_file.unlink()
    warnings.warn(
        f"removed a stale run-loop oracle test file left in the oracle checkout: {test_file}",
        RuntimeWarning,
        stacklevel=3,
    )
    return True


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

    try:
        # Vitest runs on the same Node as the runner (OPENCLAW_ORACLE_NODE, engines check).
        node_env = oracle_subprocess_env(repo_path)
    except OracleNodeError as exc:
        raise OpenClawRunLoopOracleError(str(exc)) from exc
    test_file = test_dir / ORACLE_TEST_FILENAME
    stale_removed = _remove_stale_oracle_test_file(test_file)
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
                    **(node_env if node_env is not None else os.environ),
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
        if stale_removed:
            result["staleTestFileRemoved"] = str(test_file)
        return result


def _overflow_run_loop_oracle_test_source() -> str:
    # Written against the v2026.9.6 run-loop test surface. The pin's
    # overflowBaseRunParams, resetRunOverflowCompactionHarnessMocks, mockOverflowRetrySuccess,
    # queueOverflowAttemptWithOversizedToolOutput and exported truncation mocks are gone: the
    # shared integration harness (run.shared-integration-harness.test-support.ts) owns the run
    # params and a real session row per case, and the truncation seam is the vi.fn module the
    # harness installs for ./tool-result-truncation.js (sessionLikelyHasOversizedToolResults,
    # truncateOversizedToolResultsInSessionManager). The two pin helpers are inlined from
    # 4c428153 run.overflow-compaction.fixture.ts:110-149 with the same inputs. The cases only
    # record what the real run loop did; the Python test owns every assertion.
    return r'''
import fs from "node:fs";
import { afterAll, afterEach, beforeAll, beforeEach, describe, it, type Mock } from "vitest";
import { makeCompactionSuccess, makeOverflowError } from "./run.overflow-compaction.fixture.js";
import {
  mockedCompactDirect,
  mockedIsCompactionFailureError,
  mockedIsLikelyContextOverflowError,
  mockedRunEmbeddedAttempt,
  resetSharedRunIntegrationHarnessMocks,
} from "./run.overflow-compaction.harness.js";
import {
  cleanupSharedRunIntegrationSessions,
  createSharedRunIntegrationSession,
  loadSharedRunIntegrationHarness,
} from "./run.shared-integration-harness.test-support.js";
import type { EmbeddedRunAttemptResult } from "./run/types.js";

type RunEmbeddedAgent = Awaited<ReturnType<typeof loadSharedRunIntegrationHarness>>;
type Session = Awaited<ReturnType<typeof createSharedRunIntegrationSession>>;

let runEmbeddedAgent: RunEmbeddedAgent;
let mockedSessionLikelyHasOversizedToolResults: Mock;
let mockedTruncateOversizedToolResults: Mock;
let session: Session | undefined;
const scenarios: Array<Record<string, unknown>> = [];

function record(name: string, result: Awaited<ReturnType<RunEmbeddedAgent>>) {
  const secondAttempt = mockedRunEmbeddedAttempt.mock.calls[1]?.[0] as
    | { prompt?: unknown; suppressNextUserMessagePersistence?: unknown }
    | undefined;
  const secondPromptIncludesContinuation = String(secondAttempt?.prompt ?? "").includes(
    "Continue from the current transcript",
  );
  const secondSuppressesUserPersistence =
    secondAttempt?.suppressNextUserMessagePersistence === true;
  const firstTruncateCall = mockedTruncateOversizedToolResults.mock.calls[0]?.[0] as
    | { protectTrailingToolResults?: unknown }
    | undefined;
  scenarios.push({
    name,
    attemptCalls: mockedRunEmbeddedAttempt.mock.calls.length,
    compactCalls: mockedCompactDirect.mock.calls.length,
    truncateCalls: mockedTruncateOversizedToolResults.mock.calls.length,
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

function attempt(overrides: Parameters<Session["makeAttemptResult"]>[0] = {}) {
  if (!session) {
    throw new Error("session missing");
  }
  return session.makeAttemptResult(overrides);
}

function compactionSuccess(summary = "Compacted session", firstKeptEntryId = "entry-5") {
  return makeCompactionSuccess({ summary, firstKeptEntryId, tokensBefore: 150000 });
}

describe("memory-core overflow run-loop oracle", () => {
  beforeAll(async () => {
    runEmbeddedAgent = await loadSharedRunIntegrationHarness();
    const truncation = (await import("./tool-result-truncation.js")) as unknown as {
      sessionLikelyHasOversizedToolResults: Mock;
      truncateOversizedToolResultsInSessionManager: Mock;
    };
    mockedSessionLikelyHasOversizedToolResults = truncation.sessionLikelyHasOversizedToolResults;
    mockedTruncateOversizedToolResults = truncation.truncateOversizedToolResultsInSessionManager;
  });

  beforeEach(async () => {
    resetSharedRunIntegrationHarnessMocks();
    mockedSessionLikelyHasOversizedToolResults.mockReset();
    mockedSessionLikelyHasOversizedToolResults.mockReturnValue(false);
    mockedTruncateOversizedToolResults.mockReset();
    mockedTruncateOversizedToolResults.mockResolvedValue({
      truncated: false,
      truncatedCount: 0,
      reason: "no oversized tool results",
    });
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
    session = await createSharedRunIntegrationSession();
  });

  afterEach(async () => {
    await session?.cleanup();
    session = undefined;
  });

  afterAll(async () => {
    await cleanupSharedRunIntegrationSessions();
    const outputPath = process.env.MEMORY_CORE_OVERFLOW_ORACLE_OUT;
    if (!outputPath) {
      throw new Error("MEMORY_CORE_OVERFLOW_ORACLE_OUT missing");
    }
    fs.writeFileSync(outputPath, JSON.stringify({ ok: true, scenarios }), "utf-8");
  });

  it("successful compaction retries", async () => {
    // 4c428153 mockOverflowRetrySuccess.
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(attempt({ promptError: makeOverflowError() }))
      .mockResolvedValueOnce(attempt({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(compactionSuccess());

    const result = await runEmbeddedAgent(session!.runParams);

    record("successful_compaction_retries", result);
  });

  it("attempt-level compaction retries without extra compaction", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(attempt({ promptError: makeOverflowError(), compactionCount: 1 }))
      .mockResolvedValueOnce(attempt({ promptError: null }));

    const result = await runEmbeddedAgent(session!.runParams);

    record("attempt_level_compaction_retries_without_extra_compaction", result);
  });

  it("failed compaction uses tool truncation fallback", async () => {
    // 4c428153 queueOverflowAttemptWithOversizedToolOutput.
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        attempt({
          promptError: makeOverflowError(),
          messagesSnapshot: [
            {
              role: "toolResult",
              content: [{ type: "text", text: "x".repeat(80_000) }],
            } as unknown as EmbeddedRunAttemptResult["messagesSnapshot"][number],
          ],
        }),
      )
      .mockResolvedValueOnce(attempt({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce({
      ok: false,
      compacted: false,
      reason: "nothing to compact",
    });
    mockedSessionLikelyHasOversizedToolResults.mockReturnValue(true);
    mockedTruncateOversizedToolResults.mockResolvedValueOnce({
      truncated: true,
      truncatedCount: 1,
    });

    const result = await runEmbeddedAgent(session!.runParams);

    record("failed_compaction_uses_tool_truncation_fallback", result);
  });

  it("compact then truncate runs after compaction", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        attempt({
          promptError: makeOverflowError("Context overflow: prompt too large for the model (precheck)."),
          preflightRecovery: { route: "compact_then_truncate" },
        }),
      )
      .mockResolvedValueOnce(attempt({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(compactionSuccess());
    mockedTruncateOversizedToolResults.mockResolvedValueOnce({
      truncated: true,
      truncatedCount: 2,
    });

    const result = await runEmbeddedAgent(session!.runParams);

    record("compact_then_truncate_runs_after_compaction", result);
  });

  it("assistant error overflow compacts and retries", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        attempt({
          promptError: null,
          lastAssistant: {
            stopReason: "error",
            errorMessage: "request_too_large: Request size exceeds model context window",
          } as EmbeddedRunAttemptResult["lastAssistant"],
        }),
      )
      .mockResolvedValueOnce(attempt({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(compactionSuccess());

    const result = await runEmbeddedAgent(session!.runParams);

    record("assistant_error_overflow_compacts_and_retries", result);
  });

  it("mid-turn precheck continues from transcript", async () => {
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(
        attempt({
          promptError: makeOverflowError(
            "Context overflow: prompt too large for the model (mid-turn precheck).",
          ),
          promptErrorSource: "precheck",
          preflightRecovery: { route: "compact_only", source: "mid-turn" },
        }),
      )
      .mockResolvedValueOnce(attempt({ promptError: null }));
    mockedCompactDirect.mockResolvedValueOnce(
      makeCompactionSuccess({
        summary: "Compacted after mid-turn precheck",
        firstKeptEntryId: "entry-8",
        tokensBefore: 155000,
      }),
    );

    const result = await runEmbeddedAgent(session!.runParams);

    record("mid_turn_precheck_continues_from_transcript", result);
  });

  it("gives up after max compaction attempts", async () => {
    const overflowError = makeOverflowError();
    mockedRunEmbeddedAttempt
      .mockResolvedValueOnce(attempt({ promptError: overflowError }))
      .mockResolvedValueOnce(attempt({ promptError: overflowError }))
      .mockResolvedValueOnce(attempt({ promptError: overflowError }))
      .mockResolvedValueOnce(attempt({ promptError: overflowError }));
    mockedCompactDirect
      .mockResolvedValueOnce(compactionSuccess("Compacted 1", "entry-3"))
      .mockResolvedValueOnce(compactionSuccess("Compacted 2", "entry-5"))
      .mockResolvedValueOnce(compactionSuccess("Compacted 3", "entry-7"));

    const result = await runEmbeddedAgent(session!.runParams);

    record("give_up_after_max_compaction_attempts", result);
  });
});
'''
