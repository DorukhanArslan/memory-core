# Live Task Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic live task demo that streams `memory_core.live` events for a multi-step voice-style task and records latency metadata.

**Architecture:** Create `demo/live_task_demo.py` for task state, identity bootstrap, deterministic provider streaming, latency wrapping, and summary helpers. Modify `demo/app.py` to expose state, reset, streaming turn, and summary endpoints. Add tests before implementation.

**Tech Stack:** Python, FastAPI, server-sent events, `memory_core.live`, pytest.

---

### Task 1: Runtime Module

**Files:**
- Create: `demo/live_task_demo.py`
- Test: `tests/demo/test_live_task_demo.py`

- [ ] Write failing tests for identity bootstrap, workflow step advancement, and stream event latency serialization.
- [ ] Run `pytest tests/demo/test_live_task_demo.py -q` and confirm failures come from missing module/API.
- [ ] Implement the minimal runtime functions and dataclasses.
- [ ] Run `pytest tests/demo/test_live_task_demo.py -q` and confirm pass.
- [ ] Commit runtime and tests.

### Task 2: FastAPI Endpoints

**Files:**
- Modify: `demo/app.py`
- Test: `tests/demo/test_demo_app.py`

- [ ] Write failing endpoint tests for reset, state, stream, and summary.
- [ ] Run the targeted tests and confirm failures come from missing endpoints.
- [ ] Wire runtime functions into `demo/app.py`.
- [ ] Run targeted endpoint tests and confirm pass.
- [ ] Commit endpoint and tests.

### Task 3: Verification

**Files:**
- Existing demo and unit tests.

- [ ] Run `pytest tests/demo/test_live_task_demo.py tests/demo/test_demo_app.py -q`.
- [ ] Run `pytest tests/unit/test_live_sdk.py -q`.
- [ ] Run `pytest tests/demo -q`.
- [ ] Commit any final fixes.
