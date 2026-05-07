# Chat Streaming Memory Observability Design

Date: 2026-05-07

## Goal

Make the demo usable as a real OpenAI-compatible chat lab: assistant answers must render completely in chat format, stream while they are generated, and memory file changes must be visible immediately after auto/manual memory flush.

## Requirements

- Auto flush defaults to enabled in the UI and API.
- Add `POST /api/chat/send-stream` using server-sent events.
- Stream assistant deltas as they arrive from the OpenAI-compatible chat completion endpoint.
- On stream completion, store the complete assistant response in the chat turn.
- If auto flush is enabled, run the OpenClaw-style memory flush pass after the assistant response completes.
- Emit a final full chat state event after the turn and optional flush are recorded.
- Keep `/api/chat/send` as JSON fallback.
- Memory Files tab displays live file contents from `/api/chat/state`.
- Chat bubbles preserve whitespace/newlines and remain responsive.
- API keys remain request-scoped and are not written to memory files or repo files.

## Event Contract

```text
event: assistant_delta
data: {"text":"..."}

event: final_state
data: {...full chat state...}

event: error
data: {"error":"..."}
```

## Acceptance Criteria

- User can enter API key, send a message, and see assistant text stream into the chat.
- After completion, the final answer remains as a normal assistant chat bubble.
- With auto flush enabled, memory pipeline and memory file contents update after the streamed answer.
- If no API key is supplied, chat send is disabled in the UI and backend returns a JSON/SSE error.
- Tests cover streaming parser, streaming endpoint, default auto flush, state memory contents, and UI smoke.
