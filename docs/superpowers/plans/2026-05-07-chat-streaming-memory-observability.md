# Chat Streaming Memory Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add streaming OpenAI-compatible chat, default auto flush, and live memory file observability.

**Architecture:** Extend `OpenAICompatibleChatEngine` with a streaming chat completion generator, add an SSE FastAPI endpoint that records the complete streamed answer and then runs memory flush, and update the static UI to consume SSE chunks via `fetch()` streams. Keep the JSON endpoint as fallback.

**Tech Stack:** FastAPI, httpx, plain HTML/CSS/JS, pytest, ruff.

---

## Tasks

- [ ] Add `OpenAICompatibleChatEngine.stream_complete()` and tests for OpenAI streaming chunks.
- [ ] Add `/api/chat/send-stream` returning SSE events: `assistant_delta`, `final_state`, `error`.
- [ ] Default `autoFlush` to true in send and send-stream.
- [ ] Update UI to use `send-stream`, render a temporary assistant bubble, and refresh final state.
- [ ] Keep memory file contents visible in state and UI.
- [ ] Improve responsive chat sizing and preserve assistant whitespace.
- [ ] Run targeted tests, full tests, ruff, inline JS syntax check, and browser smoke.
