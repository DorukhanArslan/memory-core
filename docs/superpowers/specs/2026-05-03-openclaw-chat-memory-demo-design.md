# OpenClaw Chat Memory Demo Design

Date: 2026-05-03

## Goal

Replace the current basic FastAPI memory tool demo with an OpenClaw-style chat observability demo. The demo must show how memory recall and memory writes change while a user chats with an LLM, while keeping prompts, architecture, and behavior aligned with the original OpenClaw memory implementation.

## Source Of Truth

The Python implementation must follow the local OpenClaw source clone at:

- `/tmp/openclaw-src/extensions/memory-core/src/flush-plan.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/prompt-section.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/tools.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/memory/hybrid.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/memory/mmr.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/memory/temporal-decay.ts`

The implementation plan must compare these source files against the Python port before coding. Any user-visible prompt text or safety hint that exists as an OpenClaw constant must be copied exactly unless Python/runtime interpolation requires a narrow adaptation.

## Non-Negotiable Parity Rules

- Do not decide memory writes through a special keyword parser.
- Do not treat words such as `remember` as a required trigger.
- Use OpenClaw's pre-compaction memory flush model-pass behavior as the design reference.
- Use OpenClaw's memory flush prompt and system prompt text from `flush-plan.ts`.
- Preserve these OpenClaw flush constraints:
  - Store durable memories only in `memory/YYYY-MM-DD.md`.
  - Create `memory/` if needed.
  - Append new content only when the daily file already exists.
  - Treat `MEMORY.md`, `DREAMS.md`, `SOUL.md`, `TOOLS.md`, and `AGENTS.md` as read-only during the flush.
  - Do not create timestamped variant files.
  - If nothing durable should be stored, return the silent reply token behavior.
- Use OpenClaw's `## Memory Recall` section guidance from `prompt-section.ts`, including the upstream scope of `MEMORY.md + memory/*.md + indexed session transcripts`.
- If the Python demo cannot support an upstream behavior completely, the implementation must either add the missing behavior or leave the UI feature disabled with an explicit parity note. It must not silently approximate OpenClaw while claiming exact parity.

## Architecture

The reusable `memory_core/` library remains the core memory port. The demo gains a chat-specific layer under `demo/`:

- `chat_engine.py`: shared interface for fake and OpenAI-compatible chat engines.
- `memory_flush.py`: OpenClaw-style silent memory flush planning and execution.
- `chat_session.py`: in-memory demo state for transcript turns, recall results, assistant responses, flush results, file diffs, and reindex results.
- `app.py`: new chat endpoints while keeping the existing inspector endpoints.
- `templates/index.html`: a full chat observability UI rather than a raw form panel.

Data flow:

1. User sends a chat message.
2. Demo builds a recall query from the current conversation.
3. Demo runs `memory_search` against OpenClaw's intended memory scope.
4. Chat engine produces an assistant response using the memory recall context.
5. If auto flush is enabled, or if the user presses `Run memory flush`, a separate silent memory flush pass evaluates whether durable information should be appended.
6. If the flush writes memory, the demo appends to `memory/YYYY-MM-DD.md`.
7. The memory index is refreshed.
8. The UI displays recall input, recall output, assistant context, flush decision, file diff, and reindex status for the selected turn.

## Chat Engines

Fake mode is for deterministic local testing. It must not be implemented as a keyword trigger. It should behave as a stable model double that can classify durable information such as user preferences, project decisions, recurring facts, and explicit long-term constraints.

OpenAI-compatible mode uses a chat completion endpoint configured by environment variables. It uses the same recall context, response envelope, memory flush prompt, and file write restrictions as fake mode. If required config is missing, the UI shows the mode as unavailable and the endpoint returns a clear JSON error.

## Memory Flush Contract

`POST /api/chat/flush` runs a separate model pass. It does not generate a user-facing assistant reply.

The internal flush plan must be derived from OpenClaw's `buildMemoryFlushPlan` behavior:

- default soft threshold tokens: `4000`
- default force transcript bytes: `2 * 1024 * 1024`
- relative path: `memory/<date>.md`
- prompt: OpenClaw `DEFAULT_MEMORY_FLUSH_PROMPT` with the active date interpolated
- system prompt: OpenClaw `DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT` with the active date interpolated
- current-time line appended to the prompt in the same role as OpenClaw's plan

The demo endpoint may return structured observability metadata, but the underlying model instruction must remain OpenClaw-style. The UI can display a normalized result:

```json
{
  "shouldWrite": true,
  "target": "memory/YYYY-MM-DD.md",
  "entry": "- Durable memory entry",
  "reason": "Why this is durable"
}
```

The implementation must keep raw model output visible in the timeline for debugging. If parsing fails, no file is written.

## API

`POST /api/chat/send`

- Accepts `message`, `engine`, and `autoFlush`.
- Runs memory recall before generating the assistant response.
- Stores a turn record with recall query, recall results, assistant response, and optional flush result.
- Returns the full updated chat state.

`POST /api/chat/flush`

- Runs the OpenClaw-style silent memory flush pass for the current transcript.
- Writes only to the allowed daily memory file when the pass produces durable content.
- Reindexes after a successful write.
- Returns the updated chat state.

`GET /api/chat/state`

- Returns transcript, selected turn metadata, memory files, engine availability, and active config.

`POST /api/chat/reset`

- Clears demo transcript and timeline.
- Resets the demo workspace to the seeded state unless the request asks to keep current memory files.

Existing endpoints stay available and move to the UI inspector:

- `POST /api/seed`
- `POST /api/reindex`
- `POST /api/search`
- `POST /api/get`
- `POST /api/prompt-preview`

## UI

The first screen is a working chat lab, not a landing page.

Primary layout:

- Left: chat transcript, engine selector, auto-flush toggle, manual flush button, message input.
- Right: selected-turn memory pipeline with `Recall`, `Assistant Context`, `Flush Decision`, `File Diff`, and `Reindex`.
- Secondary tabs:
  - `Memory Files`: `MEMORY.md`, today's `memory/YYYY-MM-DD.md`, and `DREAMS.md` read-only views.
  - `Tool Inspector`: existing search/get/prompt preview tools.
  - `Config`: fake engine state, OpenAI-compatible config status, timezone, active memory paths.

Visual style should be a dense operational tool: restrained colors, clear status chips, stable dimensions, no decorative hero page, no nested cards, no raw JSON as the primary experience. Raw JSON can be available in collapsible debug panels.

## Error Handling

- Missing real-model config returns a JSON error and disables the real engine in the UI.
- Invalid flush model output results in no write and a visible parse error.
- Attempts to write outside `memory/YYYY-MM-DD.md` are rejected.
- Reindex failures are shown in the timeline and do not hide the previous successful state.
- File reads remain restricted to OpenClaw memory paths and allowed bootstrap files.

## Tests

Add tests before implementation changes.

Required unit tests:

- Flush plan prompt text matches OpenClaw constants after date interpolation.
- Prompt section matches OpenClaw `## Memory Recall` guidance, including indexed session transcripts.
- Fake memory flush does not depend on `remember` as a required trigger.
- Fake memory flush stores stable preferences and decisions.
- Flush write path rejects non-daily targets.
- Invalid flush output writes nothing.

Required integration tests:

- Chat send runs recall before assistant response.
- Manual flush appends to `memory/YYYY-MM-DD.md`, reindexes, and makes the new memory searchable.
- Auto flush performs the same write/reindex flow after the assistant turn.
- Existing tool inspector endpoints continue to work.

Real OpenAI-compatible tests are opt-in only and skipped unless environment variables are configured.

## Out Of Scope

- Full OpenClaw daemon/session lifecycle.
- Deep dreaming promotion into `MEMORY.md`.
- LanceDB plugin capture regex behavior.
- Production persistence for multiple users.
- A real auth system.

## Acceptance Criteria

- The demo lets the user chat and inspect how memory recall and memory flush affect files turn by turn.
- Memory writes are model-pass driven, not special-word driven.
- Prompt and safety text are ported from OpenClaw source files, not invented.
- The Python prompt section is realigned with OpenClaw's upstream session-transcript wording.
- Demo writes are restricted to OpenClaw's daily memory file behavior.
- Existing memory search/get demo functionality remains available.
- Tests verify prompt parity, write safety, chat flow, manual flush, and auto flush.
