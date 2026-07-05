# Live Task Demo Design

## Goal

Build a generic live task demo that exercises `memory_core.live` with a multi-step voice-style workflow, streaming sentence events, trace output, memory recall, and post-session summary hooks.

## Scope

The demo uses a single tenant and avoids domain-specific naming. It models an appointment reschedule task because it has clear steps: verify identity, collect a new time, confirm the change, and summarize durable follow-up context.

## Architecture

The demo adds a focused runtime module under `demo/live_task_demo.py` and mounts API endpoints from `demo/app.py`. The runtime owns deterministic workflow state, fake business actions, a fake streaming provider, latency measurement, identity bootstrap files, and serialization. The app layer only validates payloads, wires the runtime into `memory_core.live`, and returns state or server-sent events.

## Data Flow

A user sends an utterance to `/api/live-task/turn-stream`. The demo runtime loads or creates a session state, advances workflow slots from the utterance, opens subject memory through `SubjectMemory`, prepares a `LiveTurnContext`, and streams events from `stream_live_turn`. Each event is wrapped with elapsed milliseconds so later real provider latency can be compared against the fake provider. Complete turns are appended to the in-memory session transcript and JSONL trace.

Post-call summary is exposed through `/api/live-task/summary`. It writes only durable facts, preferences, and follow-ups to the subject workspace through the existing live SDK summary path.

## API

- `POST /api/live-task/reset`: reset the live task demo state and seed identity files.
- `GET /api/live-task/state`: return workflow state, transcript, trace path, and workspace paths.
- `POST /api/live-task/turn-stream`: stream live turn events as SSE.
- `POST /api/live-task/summary`: write a post-session summary to subject memory.

## Testing

Unit and demo tests cover workflow advancement, fake stream sentence output, SSE latency metadata, trace file creation, and summary memory writes. Tests use the existing fake embedding provider path and do not require network access.
