# Faz 6 Closeout: Transcript And Runtime Context

This phase ports isolated OpenClaw transcript/context helpers into the Python package and wires the demo to use the replay-cleanup subset before sending live transcript context.

## What Is Covered

Covered with executable OpenClaw TS oracle fixtures:

- `memory_core.history`
  - Resolves per-channel/per-DM history limits from OpenClaw-style session keys.
  - Keeps the last N user turns plus following messages.
- `memory_core.replay_history`
  - Drops blank user replay messages.
  - Normalizes legacy assistant string/object content.
  - Converts mid-history empty assistant error turns to OpenClaw's replay sentinel.
  - Drops trailing empty error or zero-usage stop assistant turns.
  - Drops transcript-only OpenClaw assistant mirror entries.
  - Strips internal runtime context markers from assistant replay text.
- `memory_core.replay_repair`
  - Moves matching tool results directly after assistant tool calls.
  - Adds timestamped synthetic missing tool results.
  - Drops orphaned or duplicate tool results for the covered fixtures.
  - Honors aborted/error assistant result drop policy.
- `memory_core.runtime_context_prompt`
  - Splits visible prompt, model-only prompt additions, and hidden runtime context blocks.
  - Builds current inbound context prompt prefixes.
  - Builds hidden custom runtime-context messages.
- `memory_core.context_engine_lifecycle`
  - Strips hidden runtime-context custom messages before context-engine assembly/finalization.
  - Recomputes `prePromptMessageCount` after hidden-message stripping.

## Simple Example

Input transcript:

```text
User: Bana Doruk de.
Custom hidden runtime context: WhatsApp DM, sender id 123
Assistant: Tamam Doruk.
User: Nasıl hitap edeceksin?
```

Context engine / memory-facing transcript:

```text
User: Bana Doruk de.
Assistant: Tamam Doruk.
User: Nasıl hitap edeceksin?
```

The hidden runtime context is useful for routing and prompt construction, but it is not user-authored conversation and must not be stored as memory evidence.

## Demo Behavior

The demo still uses a simplified transcript window:

```text
previous chat turns -> replay cleanup -> message/char budget -> model
```

It is useful for manual inspection, but it is not full OpenClaw runtime parity. The demo now avoids replaying internal runtime markers and silent assistant artifacts if they appear in stored transcript text.

## Intentional Gaps

These are left as runtime-adapter work, not memory-core MVP work:

- Provider plugin replay hooks.
- Full provider-specific replay validation.
- Real context-engine windowing plugin behavior.
- OpenClaw platform/session persistence edge cases beyond the isolated helpers above.

## Status

Faz 6 is complete for the plug-and-play Python memory-core MVP boundary.

Full OpenClaw runtime parity remains partial by design, and the parity matrix keeps those runtime-adapter gaps visible.
