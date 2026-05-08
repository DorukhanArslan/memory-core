# OpenClaw Memory Parity Design

## Goal

Implement OpenClaw memory behavior in the Python demo while keeping the FastAPI/web UI shell. The target is behavior parity for memory algorithms and file lifecycle, not a TypeScript extension-host clone.

## Source Of Truth

The implementation follows the pinned OpenClaw source commit already referenced by the project:

- `docs/concepts/memory.md`
- `extensions/memory-core/src/prompt-section.ts`
- `extensions/memory-core/src/tools.ts`
- `extensions/memory-core/src/short-term-promotion.ts`
- `extensions/memory-core/src/dreaming.ts`
- `extensions/memory-core/src/memory/*`

When local behavior conflicts with those files, the upstream source wins unless the difference is explicitly documented as a Python demo shell concern.

## Scope

The Python demo remains the user-facing runtime. The work ports OpenClaw memory behavior into Python modules with test coverage:

- Long-term memory: `MEMORY.md`
- Daily memory: `memory/YYYY-MM-DD.md`
- Dreaming workspace: `memory/.dreams/`
- Session transcript corpus: `memory/.dreams/session-corpus/YYYY-MM-DD.md`
- Short-term recall store: `memory/.dreams/short-term-recall.json`
- Phase signals: `memory/.dreams/phase-signals.json`
- Promotion lock: `memory/.dreams/short-term-promotion.lock`

The UI stays a test bench for observing the behavior, not a product clone of OpenClaw.

## Architecture

### Short-Term Promotion

`demo/short_term_promotion.py` becomes the Python behavior port of OpenClaw short-term promotion. It will expose small functions for:

- Recording recall signals from `memory_search` results.
- Recording grounded daily-memory signals after daily flushes.
- Ranking candidates with frequency, relevance, diversity, recency, consolidation, and conceptual components.
- Applying score, recall-count, unique-query/day, age, and already-promoted gates.
- Applying light/REM phase signal boosts using `phase-signals.json`.
- Writing promotion markers to `MEMORY.md`.
- Reconciling already-existing promoted snippets.
- Acquiring and releasing a lock file with stale-lock recovery.
- Auditing and repairing short-term artifacts.

The OpenClaw default thresholds remain visible and used by default:

- `minScore = 0.75`
- `minRecallCount = 3`
- `minUniqueQueries = 2`

No custom strong-statement bypass is allowed.

### Dreaming

Add `demo/dreaming.py` as a behavior port of OpenClaw dreaming. The demo exposes manual endpoints instead of a real background scheduler by default, but the phase behavior and files match OpenClaw.

The dreaming module will support:

- Light sweep: revisit short-term candidates and record phase signals.
- REM sweep: create narrative/dream observations when enough fragments exist.
- Deep sweep: run promotion application from ranked candidates.
- `DREAMS.md` and `memory/.dreams/` file lifecycle.
- Status output for the UI showing phase, candidates touched, files changed, and skipped reasons.

Dreaming is disabled by default unless triggered from the demo UI/API, matching OpenClaw's optional dreaming behavior while keeping the local test bench deterministic.

### Search And Indexing

Search remains Python SQLite/FTS/vector based, but the corpus behavior follows OpenClaw guidance:

- Default `memory_search` searches `MEMORY.md`, `memory/*.md`, and indexed session transcripts.
- `corpus=memory` restricts to memory files.
- `corpus=sessions` restricts to session transcripts.
- Search result metadata includes `source`/`corpus` so recall recording can ignore non-memory snippets when OpenClaw does.

Session transcript files are written under `memory/.dreams/session-corpus/YYYY-MM-DD.md` after chat turns and are indexed on reindex.

### Flush Lifecycle

The demo can keep `auto flush` as an observation aid, but it must be labeled as demo behavior. The flush itself must continue to write only canonical daily memory files and never directly mutate `MEMORY.md`.

Long-term updates happen through promotion/dreaming sweeps, not chat-turn flush.

### UI

The UI should make parity visible:

- Show OpenClaw defaults next to current config.
- Add `Dreaming sweep` and `Audit/Repair` controls.
- Show phase signals, promotion lock state, candidate scoring components, and skip reasons in expandable details.
- Keep the daily-memory selector with latest day first.
- Keep full-screen layout.

### Reset

Global reset clears:

- Chat state
- `MEMORY.md`
- `memory/YYYY-MM-DD.md`
- `.openclaw-memory` index files
- `memory/.dreams/*`

This prevents stale daily/session/promotion artifacts from leaking into later tests.

## Error Handling

- Active promotion lock prevents concurrent promotion and returns a visible skipped/locked result.
- Stale promotion lock is repaired according to upstream stale-lock timing.
- Corrupt short-term or phase-signal JSON produces audit issues and can be repaired.
- Embedding or OpenAI failures return JSON errors without leaking API keys.
- Reindex failures are included in run output without hiding file writes.

## Testing

Add or extend tests for:

- OpenClaw threshold defaults.
- Single strong preference does not bypass promotion gates.
- Repeated recall plus query/day diversity promotes to `MEMORY.md`.
- Phase signals boost candidate score but do not bypass required gates incorrectly.
- Active and stale promotion lock behavior.
- Audit/repair of corrupt short-term artifacts.
- Dreaming light/REM/deep sweep output and file writes.
- Search corpus behavior for memory vs sessions.
- Reset clearing `.dreams` artifacts.
- UI rendering of defaults, dreaming, audit, and candidate details.

## Out Of Scope

- Replacing FastAPI with OpenClaw's TypeScript extension host.
- Reimplementing the full OpenClaw plugin SDK.
- Building a real background scheduler that runs without user action. The demo may expose manual or deterministic scheduled runs, but parity target is memory behavior.
- Adding a custom memory policy that diverges from OpenClaw.

## Acceptance Criteria

- The Python demo no longer contains custom long-term promotion shortcuts.
- Daily flush never writes `MEMORY.md`.
- Long-term promotion uses OpenClaw gates and promotion lifecycle files.
- Dreaming files and phase signals are observable in the UI.
- `memory_search` corpus behavior matches OpenClaw guidance.
- Tests document each supported parity behavior and pass with lint.
