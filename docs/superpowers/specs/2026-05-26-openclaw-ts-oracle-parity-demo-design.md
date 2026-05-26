# OpenClaw TS Oracle Parity Demo Design

## Goal

Show, for the same user input and same memory workspace state, how the current Python port and the original OpenClaw TypeScript memory-core implementation advance through memory flush, recall tracking, ranking, promotion gates, and file writes.

The demo must make parity and divergence visible step by step. It must not claim parity unless the TypeScript oracle and Python port produce matching decisions and normalized outputs for the inspected step.

## Source Of Truth

The oracle is the original OpenClaw TypeScript implementation pinned by commit SHA. The first supported oracle surface is memory-core function behavior, not the full OpenClaw gateway/app runtime.

Oracle functions:

- `buildMemoryFlushPlan`
- `recordShortTermRecalls`
- `recordGroundedShortTermCandidates`
- `recordDreamingPhaseSignals`
- `rankShortTermPromotionCandidates`
- `applyShortTermPromotions`
- memory dreaming config resolvers that supply managed deep defaults

The UI should display the OpenClaw source commit used by the oracle.

## Non-Goals

- Do not run the full OpenClaw app, gateway, scheduler, Codex harness, or chat runtime in the first implementation.
- Do not replace the Python chat demo.
- Do not auto-update `USER.md`; if added later, label it as a product extension, not OpenClaw memory-core parity.
- Do not hide mismatches behind friendly labels. Divergence is the point of the mode.

## Architecture

### Oracle Source

Add a reproducible OpenClaw source location. Prefer one of:

- A configured local path, for development.
- A pinned checkout under a cache directory, prepared by a setup script.

The backend must expose the active oracle metadata:

- repository path
- commit SHA
- package manager status
- runner availability

### Node Oracle Runner

Add a Node/TypeScript runner that accepts JSON on stdin and writes JSON on stdout. It should call the real TypeScript OpenClaw memory-core functions and never reimplement their logic.

The runner receives:

- operation name
- workspace directory
- timestamp
- timezone
- config object
- memory search results or candidate fixtures

The runner returns:

- normalized operation result
- resulting file snapshots for relevant memory files
- structured errors if OpenClaw dependencies or source files are unavailable

### Workspace Fixture Pairing

For each trace run, create two temporary workspaces:

- Python workspace
- OpenClaw TS oracle workspace

Seed both workspaces with identical files before the step:

- `MEMORY.md`
- `memory/YYYY-MM-DD.md`
- `memory/.dreams/short-term-recall.json`
- `memory/.dreams/phase-signals.json`
- `DREAMS.md` when relevant

Run each system against its own copy. Compare outputs after the step.

### Trace Model

Represent every inspected step as:

```json
{
  "id": "deep-promotion-gate",
  "label": "Deep promotion gate",
  "python": {
    "decision": "fail",
    "values": {},
    "reasons": []
  },
  "openclaw": {
    "decision": "fail",
    "values": {},
    "reasons": []
  },
  "diff": {
    "status": "match",
    "details": []
  }
}
```

Diff statuses:

- `match`
- `mismatch`
- `python-only`
- `openclaw-only`
- `error`

### Initial Steps

Support these steps first:

1. Flush plan defaults
2. Recall tracking from a memory search result
3. Grounded daily candidate recording
4. Light/REM phase signal recording
5. Rank short-term promotion candidates
6. Apply short-term promotions
7. Deep dreaming policy values

Chat completion behavior remains outside the first parity trace. The demo may still use the live chat engine, but the oracle comparison starts at deterministic memory-core boundaries.

## UI

Add an OpenClaw Parity tab or panel.

For each user action, show a two-column trace:

- left: Python port
- right: OpenClaw TS oracle

Each row shows:

- step name
- input summary
- if condition
- computed values
- decision
- file diff
- match/mismatch badge

Example gate row:

```text
Condition:
score >= minScore && signalCount >= minRecallCount && contextDiversity >= minUniqueQueries

Python:
score=0.76 minScore=0.75 signals=3 unique=2 -> pass

OpenClaw:
score=0.76 minScore=0.80 signals=3 unique=2 -> fail

Result:
mismatch
```

## Error Handling

- If the oracle checkout is missing, show `oracle unavailable` with setup instructions.
- If Node dependencies are missing, show the failed command and stderr summary.
- If the TypeScript runner throws, return a structured `error` trace row instead of breaking the chat demo.
- If OpenClaw and Python write different files, show both file snapshots and unified diff.

## Testing

Add tests for:

- oracle runner metadata when source is missing
- fixture workspace cloning
- Python/OpenClaw mismatch detection for known default differences
- matching recall-store mutation for a simple memory search result
- deep gate mismatch: Python `0.75/3/2` versus OpenClaw managed deep `0.8/3/3`
- UI contains the parity panel, two-column layout, and mismatch labels

## Acceptance Criteria

- A user can enter or select a memory scenario and see Python vs OpenClaw TS results side by side.
- The TS side calls original OpenClaw TypeScript functions, not a Python reimplementation.
- The demo displays OpenClaw commit SHA.
- Known current mismatches are visible and named.
- The harness can be run from tests without starting the full OpenClaw app.
