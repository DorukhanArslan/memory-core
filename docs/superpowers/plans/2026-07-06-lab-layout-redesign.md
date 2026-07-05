# Lab Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cramped lab viewport with a mode-based layout for Chat Memory and Live SDK Task workflows.

**Architecture:** Modify `demo/templates/index.html` to add mode controls and contextual inspector panels. Modify `demo/static/styles.css` to use a two-column workspace and scrollable page layout. Update `tests/demo/test_demo_app.py` to lock the new UI contract.

**Tech Stack:** HTML, CSS, vanilla JavaScript, FastAPI template tests, browser verification.

---

### Task 1: UI Contract Tests

**Files:**
- Modify: `tests/demo/test_demo_app.py`

- [ ] Add failing assertions that the home page contains `mode-switch`, `mode-chat`, `mode-live`, `primary-panel active`, `live-observability`, and `renderModeLayout`.
- [ ] Add failing assertions that the home page no longer contains `interaction-stack`.
- [ ] Add failing CSS assertions that `body` uses `overflow: auto`, `.workspace` uses two columns, and `.app-shell` uses `min-height: 100dvh`.
- [ ] Run targeted tests and confirm they fail for missing new layout.

### Task 2: Mode-Based Layout

**Files:**
- Modify: `demo/templates/index.html`
- Modify: `demo/static/styles.css`

- [ ] Replace the three-column cramped workspace with primary and inspector columns.
- [ ] Add Chat Memory and Live SDK Task mode buttons.
- [ ] Move Memory Pipeline into the chat inspector and add a Live SDK event inspector.
- [ ] Add JavaScript mode switching and live event rendering into the right inspector.
- [ ] Run targeted tests and confirm they pass.

### Task 3: Browser Verification

**Files:**
- Existing local server.

- [ ] Run full demo and Live SDK tests.
- [ ] Parse page JavaScript with Node.
- [ ] Use the browser to verify mode switching and Live SDK streaming.
- [ ] Commit the redesign.
