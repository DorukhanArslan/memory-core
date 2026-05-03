# OpenClaw Chat Memory Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an OpenClaw-style chat observability demo that shows memory recall, model response, silent memory flush, file diff, and reindex effects while chatting with an LLM.

**Architecture:** Keep `memory_core/` as the reusable port and add a focused `demo/` chat layer. First restore upstream prompt parity, then add flush planning/execution, deterministic and OpenAI-compatible chat engines, FastAPI chat endpoints, and a dense operational UI. Tests drive each layer before implementation.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2 static HTML/CSS/JS, SQLite-backed `memory-core`, pytest, ruff.

---

## File Structure

- Modify `memory_core/prompt_section.py`: restore upstream OpenClaw `## Memory Recall` text including `indexed session transcripts`.
- Create `memory_core/memory_flush.py`: Python port of OpenClaw `buildMemoryFlushPlan`, constants, safety hints, silent reply token handling, date interpolation, and daily-path validation.
- Modify `memory_core/workspace.py`: add append helper restricted to `memory/YYYY-MM-DD.md`; keep read restrictions intact.
- Create `demo/chat_engine.py`: fake and OpenAI-compatible engines behind one interface.
- Create `demo/memory_flush.py`: demo executor that builds flush messages, parses normalized output, appends daily memory, computes diff, and reindexes.
- Create `demo/chat_session.py`: process-local transcript/timeline state for the demo.
- Modify `demo/app.py`: add chat endpoints while preserving existing inspector endpoints.
- Replace `demo/templates/index.html`: chat lab UI with memory pipeline, memory files, inspector, config.
- Replace `demo/static/styles.css`: operational dashboard styling.
- Add/modify tests:
  - `tests/parity/test_prompt_section.py`
  - `tests/unit/test_memory_flush_plan.py`
  - `tests/unit/test_workspace.py`
  - `tests/demo/test_chat_engine.py`
  - `tests/demo/test_chat_memory_flush.py`
  - `tests/demo/test_chat_session.py`
  - `tests/demo/test_demo_app.py`

## Upstream Parity Notes

Implementation must compare against these OpenClaw files before coding:

- `/tmp/openclaw-src/extensions/memory-core/src/flush-plan.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/prompt-section.ts`
- `/tmp/openclaw-src/extensions/memory-core/src/tools.ts`

Copy these strings exactly into Python where applicable:

```python
MEMORY_FLUSH_TARGET_HINT = (
    "Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed)."
)
MEMORY_FLUSH_APPEND_ONLY_HINT = (
    "If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries."
)
MEMORY_FLUSH_READ_ONLY_HINT = (
    "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them."
)
DEFAULT_MEMORY_FLUSH_PROMPT = " ".join(
    [
        "Pre-compaction memory flush.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        "Do NOT create timestamped variant files (e.g., YYYY-MM-DD-HHMM.md); always use the canonical YYYY-MM-DD.md filename.",
        "If nothing to store, reply with <NO_REPLY>.",
    ]
)
DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT = " ".join(
    [
        "Pre-compaction memory flush turn.",
        "The session is near auto-compaction; capture durable memories to disk.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        "You may reply, but usually <NO_REPLY> is correct.",
    ]
)
```

Use the actual `SILENT_REPLY_TOKEN` value from this repo if it exists; if absent, define it as `<NO_REPLY>` and keep all references centralized in `memory_core/memory_flush.py`.

---

### Task 1: Restore Prompt Section Upstream Parity

**Files:**
- Modify: `memory_core/prompt_section.py`
- Modify: `tests/parity/test_prompt_section.py`

- [ ] **Step 1: Verify upstream prompt text before editing**

Run:

```bash
sed -n '1,120p' /tmp/openclaw-src/extensions/memory-core/src/prompt-section.ts
```

Expected: output contains `MEMORY.md + memory/*.md + indexed session transcripts` in both `memory_search` guidance branches.

- [ ] **Step 2: Update failing parity tests for upstream session transcript wording**

Replace `tests/parity/test_prompt_section.py` with:

```python
import pytest

from memory_core.prompt_section import build_prompt_section


def test_prompt_section_with_both_tools_matches_upstream_text():
    assert build_prompt_section({"memory_search", "memory_get"}, citations_mode="on") == [
        "## Memory Recall",
        (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts; "
            "then use memory_get to pull only the needed lines. If low confidence after search, say you checked."
        ),
        "Citations: include Source: <path#line> when it helps the user verify memory snippets.",
        "",
    ]


def test_prompt_section_omits_when_no_tools():
    assert build_prompt_section(set(), citations_mode="on") == []


def test_prompt_section_with_search_only_matches_upstream_text():
    assert build_prompt_section({"memory_search"}, citations_mode="on") == [
        "## Memory Recall",
        (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts "
            "and answer from the matching results. If low confidence after search, say you checked."
        ),
        "Citations: include Source: <path#line> when it helps the user verify memory snippets.",
        "",
    ]


def test_prompt_section_with_get_only_matches_upstream_text():
    assert build_prompt_section({"memory_get"}, citations_mode="on") == [
        "## Memory Recall",
        (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos that already point to a specific memory file or note: run memory_get to pull "
            "only the needed lines. If low confidence after reading them, say you checked."
        ),
        "Citations: include Source: <path#line> when it helps the user verify memory snippets.",
        "",
    ]


def test_prompt_section_with_citations_off_matches_upstream_text():
    assert build_prompt_section({"memory_search"}, citations_mode="off") == [
        "## Memory Recall",
        (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts "
            "and answer from the matching results. If low confidence after search, say you checked."
        ),
        "Citations are disabled: do not mention file paths or line numbers in replies unless the user explicitly asks.",
        "",
    ]


def test_prompt_section_rejects_invalid_citations_mode():
    with pytest.raises(ValueError):
        build_prompt_section({"memory_search"}, citations_mode="auto")
```

- [ ] **Step 3: Run prompt tests and verify they fail**

Run: `pytest tests/parity/test_prompt_section.py -v`

Expected: failures showing current prompt text lacks `+ indexed session transcripts`.

- [ ] **Step 4: Restore upstream prompt text**

In `memory_core/prompt_section.py`, change both search guidance branches to include indexed session transcripts:

```python
if has_memory_search and has_memory_get:
    tool_guidance = (
        "Before answering anything about prior work, decisions, dates, people, preferences, "
        "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts; "
        "then use memory_get to pull only the needed lines. If low confidence after search, say you checked."
    )
elif has_memory_search:
    tool_guidance = (
        "Before answering anything about prior work, decisions, dates, people, preferences, "
        "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts "
        "and answer from the matching results. If low confidence after search, say you checked."
    )
```

- [ ] **Step 5: Run prompt tests and full parity tests**

Run: `pytest tests/parity -v`

Expected: all parity tests pass.

- [ ] **Step 6: Commit**

```bash
git add memory_core/prompt_section.py tests/parity/test_prompt_section.py
git commit -m "fix: restore openclaw prompt recall scope"
```

---

### Task 2: Port OpenClaw Memory Flush Plan

**Files:**
- Create: `memory_core/memory_flush.py`
- Create: `tests/unit/test_memory_flush_plan.py`

- [ ] **Step 1: Verify upstream flush source before editing**

Run:

```bash
sed -n '1,180p' /tmp/openclaw-src/extensions/memory-core/src/flush-plan.ts
```

Expected: output contains `DEFAULT_MEMORY_FLUSH_SOFT_TOKENS = 4000`, `DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES = 2 * 1024 * 1024`, `DEFAULT_MEMORY_FLUSH_PROMPT`, `DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT`, and `buildMemoryFlushPlan`.

- [ ] **Step 2: Write failing flush plan tests**

Create `tests/unit/test_memory_flush_plan.py`:

```python
from pathlib import Path

import pytest

from memory_core.memory_flush import (
    DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    SILENT_REPLY_TOKEN,
    UnsafeMemoryFlushTargetError,
    build_memory_flush_plan,
    validate_daily_memory_target,
)


def test_build_memory_flush_plan_ports_openclaw_defaults(tmp_path: Path):
    plan = build_memory_flush_plan(workspace_dir=tmp_path, now_ms=1777824000000, timezone="Europe/Istanbul")

    assert plan.soft_threshold_tokens == DEFAULT_MEMORY_FLUSH_SOFT_TOKENS == 4000
    assert plan.force_flush_transcript_bytes == DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES == 2 * 1024 * 1024
    assert plan.relative_path == "memory/2026-05-03.md"
    assert "Pre-compaction memory flush." in plan.prompt
    assert "Store durable memories only in memory/2026-05-03.md (create memory/ if needed)." in plan.prompt
    assert "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them." in plan.prompt
    assert "If memory/2026-05-03.md already exists, APPEND new content only and do not overwrite existing entries." in plan.prompt
    assert "Do NOT create timestamped variant files (e.g., 2026-05-03-HHMM.md); always use the canonical 2026-05-03.md filename." in plan.prompt
    assert f"If nothing to store, reply with {SILENT_REPLY_TOKEN}." in plan.prompt
    assert "Current time:" in plan.prompt
    assert "Pre-compaction memory flush turn." in plan.system_prompt
    assert f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct." in plan.system_prompt


def test_validate_daily_memory_target_accepts_only_canonical_daily_file():
    assert validate_daily_memory_target("memory/2026-05-03.md") == "memory/2026-05-03.md"


@pytest.mark.parametrize(
    "target",
    [
        "MEMORY.md",
        "DREAMS.md",
        "memory/2026-05-03-1900.md",
        "memory/note.md",
        "../memory/2026-05-03.md",
        "memory/nested/2026-05-03.md",
    ],
)
def test_validate_daily_memory_target_rejects_non_daily_files(target: str):
    with pytest.raises(UnsafeMemoryFlushTargetError):
        validate_daily_memory_target(target)
```

- [ ] **Step 3: Run tests and verify module is missing**

Run: `pytest tests/unit/test_memory_flush_plan.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'memory_core.memory_flush'`.

- [ ] **Step 4: Implement flush plan port**

Create `memory_core/memory_flush.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SILENT_REPLY_TOKEN = "<NO_REPLY>"
DEFAULT_MEMORY_FLUSH_SOFT_TOKENS = 4000
DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES = 2 * 1024 * 1024

MEMORY_FLUSH_TARGET_HINT = (
    "Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed)."
)
MEMORY_FLUSH_APPEND_ONLY_HINT = (
    "If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries."
)
MEMORY_FLUSH_READ_ONLY_HINT = (
    "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them."
)
MEMORY_FLUSH_REQUIRED_HINTS = [
    MEMORY_FLUSH_TARGET_HINT,
    MEMORY_FLUSH_APPEND_ONLY_HINT,
    MEMORY_FLUSH_READ_ONLY_HINT,
]

DEFAULT_MEMORY_FLUSH_PROMPT = " ".join(
    [
        "Pre-compaction memory flush.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        "Do NOT create timestamped variant files (e.g., YYYY-MM-DD-HHMM.md); always use the canonical YYYY-MM-DD.md filename.",
        f"If nothing to store, reply with {SILENT_REPLY_TOKEN}.",
    ]
)
DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT = " ".join(
    [
        "Pre-compaction memory flush turn.",
        "The session is near auto-compaction; capture durable memories to disk.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct.",
    ]
)

DAILY_MEMORY_TARGET_RE = re.compile(r"^memory/\d{4}-\d{2}-\d{2}\.md$")


class UnsafeMemoryFlushTargetError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryFlushPlan:
    soft_threshold_tokens: int
    force_flush_transcript_bytes: int
    reserve_tokens_floor: int
    prompt: str
    system_prompt: str
    relative_path: str


def _format_date_stamp(now_ms: int, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    return datetime.fromtimestamp(now_ms / 1000, tz=dt_timezone.utc).astimezone(tz).strftime("%Y-%m-%d")


def _current_time_line(now_ms: int, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    current = datetime.fromtimestamp(now_ms / 1000, tz=dt_timezone.utc).astimezone(tz)
    return f"Current time: {current.isoformat()}"


def ensure_no_reply_hint(text: str) -> str:
    if SILENT_REPLY_TOKEN in text:
        return text
    return f"{text}\\n\\nIf no user-visible reply is needed, start with {SILENT_REPLY_TOKEN}."


def ensure_memory_flush_safety_hints(text: str) -> str:
    next_text = text.strip()
    for hint in MEMORY_FLUSH_REQUIRED_HINTS:
        if hint not in next_text:
            next_text = f"{next_text}\\n\\n{hint}" if next_text else hint
    return next_text


def append_current_time_line(text: str, time_line: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return time_line
    if "Current time:" in stripped:
        return stripped
    return f"{stripped}\\n{time_line}"


def validate_daily_memory_target(relative_path: str) -> str:
    normalized = relative_path.replace("\\\\", "/").lstrip("/")
    if not DAILY_MEMORY_TARGET_RE.match(normalized):
        raise UnsafeMemoryFlushTargetError(f"memory flush target must be memory/YYYY-MM-DD.md: {relative_path}")
    return normalized


def build_memory_flush_plan(
    *,
    workspace_dir: Path,
    now_ms: int | None = None,
    timezone: str = "UTC",
    prompt: str | None = None,
    system_prompt: str | None = None,
    soft_threshold_tokens: int = DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    force_flush_transcript_bytes: int = DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    reserve_tokens_floor: int = 0,
) -> MemoryFlushPlan:
    del workspace_dir
    resolved_now_ms = now_ms if now_ms is not None else int(datetime.now(tz=dt_timezone.utc).timestamp() * 1000)
    date_stamp = _format_date_stamp(resolved_now_ms, timezone)
    relative_path = validate_daily_memory_target(f"memory/{date_stamp}.md")
    base_prompt = ensure_no_reply_hint(
        ensure_memory_flush_safety_hints((prompt or DEFAULT_MEMORY_FLUSH_PROMPT).strip())
    )
    base_system_prompt = ensure_no_reply_hint(
        ensure_memory_flush_safety_hints((system_prompt or DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT).strip())
    )
    return MemoryFlushPlan(
        soft_threshold_tokens=max(0, int(soft_threshold_tokens)),
        force_flush_transcript_bytes=max(0, int(force_flush_transcript_bytes)),
        reserve_tokens_floor=max(0, int(reserve_tokens_floor)),
        prompt=append_current_time_line(
            base_prompt.replace("YYYY-MM-DD", date_stamp),
            _current_time_line(resolved_now_ms, timezone),
        ),
        system_prompt=base_system_prompt.replace("YYYY-MM-DD", date_stamp),
        relative_path=relative_path,
    )
```

- [ ] **Step 5: Run unit tests**

Run: `pytest tests/unit/test_memory_flush_plan.py -v`

Expected: all tests pass.

- [ ] **Step 6: Run ruff on the new module**

Run: `ruff check memory_core/memory_flush.py tests/unit/test_memory_flush_plan.py`

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add memory_core/memory_flush.py tests/unit/test_memory_flush_plan.py
git commit -m "feat: port openclaw memory flush plan"
```

---

### Task 3: Add Safe Daily Memory Append Support

**Files:**
- Modify: `memory_core/workspace.py`
- Modify: `tests/unit/test_workspace.py`

- [ ] **Step 1: Add failing append tests**

Append these tests to `tests/unit/test_workspace.py`:

```python
def test_append_daily_memory_creates_memory_directory(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)

    path = workspace.append_daily_memory("memory/2026-05-03.md", "- User prefers concise answers.")

    assert path.relative_to(tmp_path).as_posix() == "memory/2026-05-03.md"
    assert (tmp_path / "memory" / "2026-05-03.md").read_text(encoding="utf-8") == (
        "- User prefers concise answers.\\n"
    )


def test_append_daily_memory_appends_without_overwriting(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    daily = memory_dir / "2026-05-03.md"
    daily.write_text("# 2026-05-03\\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    workspace.append_daily_memory("memory/2026-05-03.md", "- Keep OpenClaw parity.")

    assert daily.read_text(encoding="utf-8") == "# 2026-05-03\\n- Keep OpenClaw parity.\\n"


def test_append_daily_memory_rejects_bootstrap_and_timestamped_files(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("MEMORY.md", "- bad")
    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("memory/2026-05-03-1200.md", "- bad")
```

- [ ] **Step 2: Run tests and verify missing method**

Run: `pytest tests/unit/test_workspace.py -v`

Expected: FAIL with `AttributeError: 'MemoryWorkspace' object has no attribute 'append_daily_memory'`.

- [ ] **Step 3: Implement append helper**

Add to `MemoryWorkspace` in `memory_core/workspace.py`:

```python
def append_daily_memory(self, rel_path: str, entry: str) -> Path:
    normalized = self.normalize_memory_path(rel_path)
    if not normalized.startswith("memory/"):
        raise UnsafeMemoryPathError(f"memory flush writes must target memory/YYYY-MM-DD.md: {rel_path}")
    name = normalized.removeprefix("memory/")
    if "/" in name or DATED_MEMORY_FILE_RE.match(name) is None:
        raise UnsafeMemoryPathError(f"memory flush writes must target memory/YYYY-MM-DD.md: {rel_path}")
    path = self.resolve_memory_path(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = entry.rstrip()
    if not text:
        return path
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\\n")
    return path
```

- [ ] **Step 4: Run workspace tests**

Run: `pytest tests/unit/test_workspace.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add memory_core/workspace.py tests/unit/test_workspace.py
git commit -m "feat: restrict memory flush writes to daily files"
```

---

### Task 4: Add Chat Engines

**Files:**
- Create: `demo/chat_engine.py`
- Create: `tests/demo/test_chat_engine.py`

- [ ] **Step 1: Write failing chat engine tests**

Create `tests/demo/test_chat_engine.py`:

```python
from demo.chat_engine import ChatMessage, FakeChatEngine, OpenAICompatibleChatEngine, engine_status


def test_fake_engine_uses_memory_context_without_keyword_trigger():
    engine = FakeChatEngine()

    response = engine.complete(
        messages=[ChatMessage(role="user", content="Ben kısa yanıtları severim.")],
        memory_context=["MEMORY.md#1: User prefers Turkish."],
    )

    assert response.role == "assistant"
    assert "memory context" in response.content.lower()
    assert "Ben kısa yanıtları severim." in response.content


def test_fake_engine_flush_decision_does_not_require_remember_word():
    engine = FakeChatEngine()

    output = engine.flush(
        system_prompt="Pre-compaction memory flush turn.",
        prompt="Pre-compaction memory flush.",
        transcript=[ChatMessage(role="user", content="Ben bundan sonra teknik cevapları Türkçe tercih ediyorum.")],
        target="memory/2026-05-03.md",
    )

    assert '"shouldWrite": true' in output.raw_text
    assert "memory/2026-05-03.md" in output.raw_text
    assert "Türkçe" in output.raw_text


def test_fake_engine_flush_returns_silent_token_for_transient_chat():
    engine = FakeChatEngine()

    output = engine.flush(
        system_prompt="Pre-compaction memory flush turn.",
        prompt="Pre-compaction memory flush.",
        transcript=[ChatMessage(role="user", content="Selam, nasılsın?")],
        target="memory/2026-05-03.md",
    )

    assert output.raw_text == "<NO_REPLY>"


def test_openai_engine_is_unavailable_without_config(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)

    assert engine_status()["openai"]["available"] is False
    assert OpenAICompatibleChatEngine.from_env() is None
```

- [ ] **Step 2: Run tests and verify module is missing**

Run: `pytest tests/demo/test_chat_engine.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'demo.chat_engine'`.

- [ ] **Step 3: Implement chat engines**

Create `demo/chat_engine.py`:

```python
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from memory_core.memory_flush import SILENT_REPLY_TOKEN


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResponse:
    role: str
    content: str
    raw: dict | None = None


@dataclass(frozen=True)
class FlushModelOutput:
    raw_text: str
    raw: dict | None = None


class ChatEngine(Protocol):
    name: str

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        raise NotImplementedError

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        raise NotImplementedError


class FakeChatEngine:
    name = "fake"

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        latest = messages[-1].content if messages else ""
        context_note = "; ".join(memory_context[:3]) if memory_context else "no recalled memory"
        return ChatResponse(
            role="assistant",
            content=f"Fake assistant saw memory context: {context_note}. Latest user message: {latest}",
        )

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        del system_prompt, prompt
        durable = _find_durable_statement(transcript)
        if durable is None:
            return FlushModelOutput(raw_text=SILENT_REPLY_TOKEN)
        return FlushModelOutput(
            raw_text=json.dumps(
                {
                    "shouldWrite": True,
                    "target": target,
                    "entry": f"- {durable}",
                    "reason": "Stable preference, fact, or project decision worth preserving.",
                },
                ensure_ascii=False,
            )
        )


class OpenAICompatibleChatEngine:
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleChatEngine | None":
        base_url = os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL")
        api_key = os.getenv("OPENCLAW_DEMO_OPENAI_API_KEY")
        model = os.getenv("OPENCLAW_DEMO_OPENAI_MODEL")
        if not base_url or not api_key or not model:
            return None
        return cls(base_url=base_url, api_key=api_key, model=model)

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        api_messages = [
            {
                "role": "system",
                "content": "Use the supplied memory context when relevant. Do not invent memory.",
            },
            {
                "role": "system",
                "content": "Memory context:\\n" + "\\n".join(memory_context),
            },
        ]
        api_messages.extend({"role": item.role, "content": item.content} for item in messages)
        raw = self._chat(api_messages)
        content = raw["choices"][0]["message"]["content"]
        return ChatResponse(role="assistant", content=content, raw=raw)

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        transcript_text = "\\n".join(f"{item.role}: {item.content}" for item in transcript)
        raw = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{prompt}\\n\\nTarget: {target}\\n\\nTranscript:\\n{transcript_text}",
                },
            ]
        )
        return FlushModelOutput(raw_text=raw["choices"][0]["message"]["content"].strip(), raw=raw)

    def _chat(self, messages: list[dict]) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({"model": self.model, "messages": messages}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


def _find_durable_statement(transcript: list[ChatMessage]) -> str | None:
    durable_markers = [
        "tercih ediyorum",
        "severim",
        "prefers",
        "preference",
        "bundan sonra",
        "karar",
        "decision",
        "always",
        "never",
        "project uses",
    ]
    for message in reversed(transcript):
        if message.role != "user":
            continue
        lowered = message.content.lower()
        if any(marker in lowered for marker in durable_markers):
            return message.content.strip()
    return None


def engine_status() -> dict:
    configured = OpenAICompatibleChatEngine.from_env() is not None
    return {
        "fake": {"available": True, "model": "deterministic"},
        "openai": {
            "available": configured,
            "model": os.getenv("OPENCLAW_DEMO_OPENAI_MODEL") or "",
            "baseUrl": os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL") or "",
        },
    }
```

- [ ] **Step 4: Run chat engine tests**

Run: `pytest tests/demo/test_chat_engine.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add demo/chat_engine.py tests/demo/test_chat_engine.py
git commit -m "feat: add demo chat engines"
```

---

### Task 5: Add Demo Memory Flush Executor

**Files:**
- Create: `demo/memory_flush.py`
- Create: `tests/demo/test_chat_memory_flush.py`

- [ ] **Step 1: Write failing memory flush executor tests**

Create `tests/demo/test_chat_memory_flush.py`:

```python
from pathlib import Path

from demo.chat_engine import ChatMessage, FakeChatEngine, FlushModelOutput
from demo.memory_flush import parse_flush_output, run_memory_flush
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


def test_parse_flush_output_accepts_silent_token():
    parsed = parse_flush_output("<NO_REPLY>", target="memory/2026-05-03.md")

    assert parsed.should_write is False
    assert parsed.entry == ""


def test_parse_flush_output_rejects_target_mismatch():
    parsed = parse_flush_output(
        '{"shouldWrite": true, "target": "MEMORY.md", "entry": "- bad", "reason": "bad"}',
        target="memory/2026-05-03.md",
    )

    assert parsed.should_write is False
    assert parsed.error


def test_run_memory_flush_appends_reindexes_and_returns_diff(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=FakeChatEngine(),
        transcript=[ChatMessage(role="user", content="Ben teknik cevapları Türkçe tercih ediyorum.")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is True
    assert result.target == "memory/2026-05-03.md"
    assert "+- Ben teknik cevapları Türkçe tercih ediyorum." in result.diff
    assert (tmp_path / "memory" / "2026-05-03.md").exists()
    assert store.count_chunks() > 0


class BadTargetEngine:
    name = "bad"

    def complete(self, *, messages, memory_context):
        raise NotImplementedError

    def flush(self, *, system_prompt, prompt, transcript, target):
        return FlushModelOutput(
            raw_text='{"shouldWrite": true, "target": "MEMORY.md", "entry": "- bad", "reason": "bad"}'
        )


def test_run_memory_flush_writes_nothing_on_invalid_target(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=BadTargetEngine(),
        transcript=[ChatMessage(role="user", content="always write bad target")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is False
    assert result.parsed.error
    assert not (tmp_path / "MEMORY.md").exists()
```

- [ ] **Step 2: Run tests and verify module is missing**

Run: `pytest tests/demo/test_chat_memory_flush.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'demo.memory_flush'`.

- [ ] **Step 3: Implement memory flush executor**

Create `demo/memory_flush.py`:

```python
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass

from demo.chat_engine import ChatEngine, ChatMessage
from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_flush import SILENT_REPLY_TOKEN, build_memory_flush_plan, validate_daily_memory_target
from memory_core.workspace import MemoryWorkspace


@dataclass(frozen=True)
class ParsedFlushOutput:
    should_write: bool
    target: str
    entry: str
    reason: str
    error: str | None = None


@dataclass(frozen=True)
class MemoryFlushRun:
    target: str
    raw_text: str
    parsed: ParsedFlushOutput
    diff: str
    indexed_files: int
    chunks: int


def parse_flush_output(raw_text: str, *, target: str) -> ParsedFlushOutput:
    stripped = raw_text.strip()
    if stripped == SILENT_REPLY_TOKEN or stripped.startswith(SILENT_REPLY_TOKEN):
        return ParsedFlushOutput(False, target, "", "No durable memory to store.")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return ParsedFlushOutput(False, target, "", "", f"invalid JSON flush output: {exc.msg}")
    should_write = bool(payload.get("shouldWrite"))
    requested_target = str(payload.get("target") or target)
    if requested_target != target:
        return ParsedFlushOutput(False, requested_target, "", "", "flush target does not match planned daily memory file")
    try:
        validate_daily_memory_target(requested_target)
    except ValueError as exc:
        return ParsedFlushOutput(False, requested_target, "", "", str(exc))
    entry = str(payload.get("entry") or "").strip()
    reason = str(payload.get("reason") or "")
    if should_write and not entry:
        return ParsedFlushOutput(False, requested_target, "", reason, "flush requested write without entry")
    return ParsedFlushOutput(should_write, requested_target, entry, reason)


def run_memory_flush(
    *,
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    engine: ChatEngine,
    transcript: list[ChatMessage],
    now_ms: int | None = None,
    timezone: str = "UTC",
) -> MemoryFlushRun:
    plan = build_memory_flush_plan(
        workspace_dir=config.workspace_dir,
        now_ms=now_ms,
        timezone=timezone,
    )
    workspace = MemoryWorkspace(config.workspace_dir)
    before = _read_optional(workspace, plan.relative_path)
    model_output = engine.flush(
        system_prompt=plan.system_prompt,
        prompt=plan.prompt,
        transcript=transcript,
        target=plan.relative_path,
    )
    parsed = parse_flush_output(model_output.raw_text, target=plan.relative_path)
    if parsed.should_write and parsed.error is None:
        workspace.append_daily_memory(parsed.target, parsed.entry)
        indexed_files = store.reindex(workspace)
    else:
        indexed_files = 0
    after = _read_optional(workspace, plan.relative_path)
    return MemoryFlushRun(
        target=plan.relative_path,
        raw_text=model_output.raw_text,
        parsed=parsed,
        diff=_diff(before, after, plan.relative_path),
        indexed_files=indexed_files,
        chunks=store.count_chunks(),
    )


def _read_optional(workspace: MemoryWorkspace, rel_path: str) -> str:
    try:
        return workspace.read_text(rel_path).text
    except FileNotFoundError:
        return ""


def _diff(before: str, after: str, rel_path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )
```

- [ ] **Step 4: Run executor tests**

Run: `pytest tests/demo/test_chat_memory_flush.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add demo/memory_flush.py tests/demo/test_chat_memory_flush.py
git commit -m "feat: add demo memory flush executor"
```

---

### Task 6: Add Chat Session State And API Endpoints

**Files:**
- Create: `demo/chat_session.py`
- Modify: `demo/app.py`
- Create: `tests/demo/test_chat_session.py`
- Modify: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Write failing chat session tests**

Create `tests/demo/test_chat_session.py`:

```python
from demo.chat_session import ChatSessionState


def test_chat_session_records_turns_and_selects_latest():
    state = ChatSessionState()

    turn = state.add_turn(
        user_message="hello",
        recall_query="hello",
        recall_results=[],
        assistant_response="hi",
        memory_context=[],
    )

    assert turn.id == 1
    assert state.selected_turn_id == 1
    assert state.as_dict()["turns"][0]["assistantResponse"] == "hi"


def test_chat_session_reset_clears_turns():
    state = ChatSessionState()
    state.add_turn(
        user_message="hello",
        recall_query="hello",
        recall_results=[],
        assistant_response="hi",
        memory_context=[],
    )

    state.reset()

    assert state.as_dict()["turns"] == []
    assert state.selected_turn_id is None
```

- [ ] **Step 2: Add failing endpoint tests**

Append to `tests/demo/test_demo_app.py`:

```python
def test_chat_state_endpoint_returns_engines_and_memory_files():
    client = TestClient(app)

    response = client.get("/api/chat/state")

    assert response.status_code == 200
    payload = response.json()
    assert "engines" in payload
    assert "memoryFiles" in payload
    assert payload["turns"] == []


def test_chat_send_runs_recall_and_returns_turn():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post("/api/seed")
    client.post("/api/reindex")

    response = client.post(
        "/api/chat/send",
        json={"message": "Ben kısa teknik cevapları Türkçe tercih ediyorum.", "engine": "fake", "autoFlush": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turns"][0]["userMessage"] == "Ben kısa teknik cevapları Türkçe tercih ediyorum."
    assert payload["turns"][0]["recallQuery"]
    assert payload["turns"][0]["assistantResponse"]
    assert payload["turns"][0]["flush"] is None


def test_chat_manual_flush_updates_latest_turn_and_memory_file():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post(
        "/api/chat/send",
        json={"message": "Ben teknik cevapları Türkçe tercih ediyorum.", "engine": "fake", "autoFlush": False},
    )

    response = client.post("/api/chat/flush", json={"engine": "fake"})

    assert response.status_code == 200
    latest = response.json()["turns"][-1]
    assert latest["flush"]["parsed"]["shouldWrite"] is True
    assert "memory/2026-05-03.md" in response.json()["memoryFiles"]


def test_chat_send_auto_flush_updates_turn():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={"message": "Project decision: use OpenClaw prompt text exactly.", "engine": "fake", "autoFlush": True},
    )

    assert response.status_code == 200
    assert response.json()["turns"][-1]["flush"]["parsed"]["shouldWrite"] is True
```

- [ ] **Step 3: Run tests and verify failures**

Run: `pytest tests/demo/test_chat_session.py tests/demo/test_demo_app.py -v`

Expected: failures for missing `demo.chat_session` and `/api/chat/*` endpoints.

- [ ] **Step 4: Implement chat session state**

Create `demo/chat_session.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatTurn:
    id: int
    user_message: str
    recall_query: str
    recall_results: list[dict]
    memory_context: list[str]
    assistant_response: str
    flush: dict | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "userMessage": self.user_message,
            "recallQuery": self.recall_query,
            "recallResults": self.recall_results,
            "memoryContext": self.memory_context,
            "assistantResponse": self.assistant_response,
            "flush": self.flush,
        }


@dataclass
class ChatSessionState:
    turns: list[ChatTurn] = field(default_factory=list)
    selected_turn_id: int | None = None

    def add_turn(
        self,
        *,
        user_message: str,
        recall_query: str,
        recall_results: list[dict],
        memory_context: list[str],
        assistant_response: str,
    ) -> ChatTurn:
        turn = ChatTurn(
            id=len(self.turns) + 1,
            user_message=user_message,
            recall_query=recall_query,
            recall_results=recall_results,
            memory_context=memory_context,
            assistant_response=assistant_response,
        )
        self.turns.append(turn)
        self.selected_turn_id = turn.id
        return turn

    def latest(self) -> ChatTurn | None:
        return self.turns[-1] if self.turns else None

    def transcript_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in self.turns:
            messages.append({"role": "user", "content": turn.user_message})
            messages.append({"role": "assistant", "content": turn.assistant_response})
        return messages

    def reset(self) -> None:
        self.turns.clear()
        self.selected_turn_id = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "turns": [turn.as_dict() for turn in self.turns],
            "selectedTurnId": self.selected_turn_id,
        }
```

- [ ] **Step 5: Add chat endpoint helpers to `demo/app.py`**

Add imports:

```python
from demo.chat_engine import ChatMessage, FakeChatEngine, OpenAICompatibleChatEngine, engine_status
from demo.chat_session import ChatSessionState
from demo.memory_flush import run_memory_flush
```

Add module state and helpers after the `Jinja2Templates` initialization:

```python
CHAT_STATE = ChatSessionState()


def _chat_engine(name: str):
    if name == "fake":
        return FakeChatEngine()
    if name == "openai":
        engine = OpenAICompatibleChatEngine.from_env()
        if engine is None:
            raise DemoPayloadError("OpenAI-compatible engine is not configured")
        return engine
    raise DemoPayloadError("engine must be 'fake' or 'openai'")


def _memory_context_from_results(results: list[dict]) -> list[str]:
    context = []
    for result in results:
        citation = result.get("citation") or f"{result.get('path')}#{result.get('startLine')}"
        snippet = str(result.get("snippet") or "").strip()
        if snippet:
            context.append(f"{citation}: {snippet}")
    return context


def _chat_messages() -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in CHAT_STATE.turns:
        messages.append(ChatMessage(role="user", content=turn.user_message))
        messages.append(ChatMessage(role="assistant", content=turn.assistant_response))
    return messages


def _memory_files() -> dict[str, str]:
    config = demo_config()
    workspace = MemoryWorkspace(config.workspace_dir)
    files: dict[str, str] = {}
    for rel_path in ["MEMORY.md", "DREAMS.md", "memory/2026-05-03.md"]:
        try:
            files[rel_path] = workspace.read_text(rel_path).text
        except FileNotFoundError:
            files[rel_path] = ""
    return files


def _state_payload() -> dict:
    payload = CHAT_STATE.as_dict()
    payload["engines"] = engine_status()
    payload["memoryFiles"] = _memory_files()
    payload["config"] = {"workspace": demo_config().workspace_dir.as_posix(), "timezone": "Europe/Istanbul"}
    return payload
```

- [ ] **Step 6: Add chat endpoints to `demo/app.py`**

Append these endpoints below existing endpoints:

```python
@app.get("/api/chat/state")
def chat_state():
    return _state_payload()


@app.post("/api/chat/reset")
def chat_reset(payload: dict):
    CHAT_STATE.reset()
    if not payload.get("keepMemory"):
        seed()
        reindex()
    return _state_payload()


@app.post("/api/chat/send")
def chat_send(payload: dict):
    try:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise DemoPayloadError("message is required")
        engine = _chat_engine(str(payload.get("engine") or "fake"))
        recall_query = message
        recall_payload = memory_search(
            demo_config(),
            demo_store(),
            query=recall_query,
            max_results=5,
            min_score=0,
        )
        recall_results = list(recall_payload.get("results") or [])
        memory_context = _memory_context_from_results(recall_results)
        messages = _chat_messages() + [ChatMessage(role="user", content=message)]
        response = engine.complete(messages=messages, memory_context=memory_context)
        turn = CHAT_STATE.add_turn(
            user_message=message,
            recall_query=recall_query,
            recall_results=recall_results,
            memory_context=memory_context,
            assistant_response=response.content,
        )
        if bool(payload.get("autoFlush")):
            flush_result = run_memory_flush(
                config=demo_config(),
                store=demo_store(),
                engine=engine,
                transcript=_chat_messages(),
                now_ms=1777824000000,
                timezone="Europe/Istanbul",
            )
            turn.flush = _serialize_flush(flush_result)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.post("/api/chat/flush")
def chat_flush(payload: dict):
    try:
        latest = CHAT_STATE.latest()
        if latest is None:
            raise DemoPayloadError("no chat turn to flush")
        engine = _chat_engine(str(payload.get("engine") or "fake"))
        flush_result = run_memory_flush(
            config=demo_config(),
            store=demo_store(),
            engine=engine,
            transcript=_chat_messages(),
            now_ms=1777824000000,
            timezone="Europe/Istanbul",
        )
        latest.flush = _serialize_flush(flush_result)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
```

Add serializer:

```python
def _serialize_flush(result) -> dict:
    return {
        "target": result.target,
        "rawText": result.raw_text,
        "parsed": {
            "shouldWrite": result.parsed.should_write,
            "target": result.parsed.target,
            "entry": result.parsed.entry,
            "reason": result.parsed.reason,
            "error": result.parsed.error,
        },
        "diff": result.diff,
        "indexedFiles": result.indexed_files,
        "chunks": result.chunks,
    }
```

- [ ] **Step 7: Run demo tests**

Run: `pytest tests/demo -v`

Expected: all demo tests pass.

- [ ] **Step 8: Commit**

```bash
git add demo/app.py demo/chat_session.py tests/demo/test_chat_session.py tests/demo/test_demo_app.py
git commit -m "feat: add chat memory demo api"
```

---

### Task 7: Replace Demo UI With Chat Observability Lab

**Files:**
- Replace: `demo/templates/index.html`
- Replace: `demo/static/styles.css`
- Modify: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Add UI smoke assertions**

Update `test_demo_home_loads` in `tests/demo/test_demo_app.py`:

```python
def test_demo_home_loads():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "OpenClaw Chat Memory Lab" in response.text
    assert "chat-form" in response.text
    assert "memory-pipeline" in response.text
    assert "Tool Inspector" in response.text
```

- [ ] **Step 2: Run UI smoke test and verify failure**

Run: `pytest tests/demo/test_demo_app.py::test_demo_home_loads -v`

Expected: FAIL because old HTML still contains `OpenClaw Memory Demo`.

- [ ] **Step 3: Replace HTML**

Replace `demo/templates/index.html` with a static app shell and JavaScript client. Keep IDs stable for tests and future browser checks:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>OpenClaw Chat Memory Lab</title>
    <link rel="stylesheet" href="/static/styles.css">
  </head>
  <body>
    <main class="app-shell">
      <header class="topbar">
        <div>
          <h1>OpenClaw Chat Memory Lab</h1>
          <p>Observe recall, response, silent memory flush, file diff, and reindex for each turn.</p>
        </div>
        <div class="toolbar">
          <select id="engine">
            <option value="fake">Fake</option>
            <option value="openai">OpenAI-compatible</option>
          </select>
          <label class="toggle"><input id="auto-flush" type="checkbox"> Auto flush</label>
          <button id="manual-flush" type="button">Run memory flush</button>
          <button id="reset" type="button">Reset</button>
          <button id="seed" type="button">Seed</button>
          <button id="reindex" type="button">Reindex</button>
        </div>
      </header>

      <section class="workspace">
        <section class="chat-panel" aria-label="Chat">
          <div id="chat-log" class="chat-log"></div>
          <form id="chat-form" class="composer">
            <textarea id="chat-input" rows="3" placeholder="Type a message that may or may not create durable memory."></textarea>
            <button type="submit">Send</button>
          </form>
        </section>

        <aside id="memory-pipeline" class="pipeline" aria-label="Memory pipeline">
          <h2>Memory Pipeline</h2>
          <div id="pipeline-content" class="pipeline-content"></div>
        </aside>
      </section>

      <nav class="tabs" aria-label="Demo tabs">
        <button class="tab active" data-tab="memory-files" type="button">Memory Files</button>
        <button class="tab" data-tab="tool-inspector" type="button">Tool Inspector</button>
        <button class="tab" data-tab="config" type="button">Config</button>
      </nav>

      <section id="memory-files" class="tab-panel active"></section>

      <section id="tool-inspector" class="tab-panel">
        <h2>Tool Inspector</h2>
        <div class="inspector-grid">
          <form id="search-form" class="tool-form">
            <h3>memory_search</h3>
            <input name="query" value="lemon pepper" aria-label="query">
            <input name="maxResults" value="5" inputmode="numeric" aria-label="max results">
            <input name="minScore" value="0" inputmode="decimal" aria-label="min score">
            <button type="submit">Search</button>
          </form>
          <form id="get-form" class="tool-form">
            <h3>memory_get</h3>
            <input name="path" value="MEMORY.md" aria-label="path">
            <input name="from" value="1" inputmode="numeric" aria-label="from line">
            <input name="lines" value="20" inputmode="numeric" aria-label="line count">
            <button type="submit">Get</button>
          </form>
        </div>
        <pre id="output">{}</pre>
      </section>

      <section id="config" class="tab-panel"></section>
    </main>

    <script>
      let state = {turns: [], memoryFiles: {}, engines: {}, config: {}};

      async function requestJson(url, body) {
        const options = body === undefined ? {} : {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body)
        };
        const response = await fetch(url, options);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || response.statusText);
        }
        return payload;
      }

      async function refresh() {
        state = await requestJson("/api/chat/state");
        render();
      }

      function render() {
        renderChat();
        renderPipeline();
        renderMemoryFiles();
        renderConfig();
      }

      function renderChat() {
        const log = document.querySelector("#chat-log");
        log.replaceChildren();
        for (const turn of state.turns) {
          log.append(messageNode("user", turn.userMessage));
          log.append(messageNode("assistant", turn.assistantResponse));
        }
      }

      function messageNode(role, text) {
        const node = document.createElement("article");
        node.className = `message ${role}`;
        node.textContent = text;
        return node;
      }

      function renderPipeline() {
        const latest = state.turns[state.turns.length - 1];
        const panel = document.querySelector("#pipeline-content");
        panel.replaceChildren();
        if (!latest) {
          panel.append(stepNode("Waiting", "Send a message to populate the memory pipeline."));
          return;
        }
        panel.append(stepNode("Recall", latest.recallQuery + "\\n\\n" + JSON.stringify(latest.recallResults, null, 2)));
        panel.append(stepNode("Assistant Context", latest.memoryContext.join("\\n") || "No recalled memory."));
        panel.append(stepNode("Flush Decision", latest.flush ? JSON.stringify(latest.flush.parsed, null, 2) : "Not run for this turn."));
        panel.append(stepNode("File Diff", latest.flush ? latest.flush.diff || "No file changes." : "Not run for this turn."));
        panel.append(stepNode("Reindex", latest.flush ? `${latest.flush.indexedFiles} files, ${latest.flush.chunks} chunks` : "Not run for this turn."));
      }

      function stepNode(title, text) {
        const node = document.createElement("section");
        node.className = "pipeline-step";
        const heading = document.createElement("h3");
        heading.textContent = title;
        const body = document.createElement("pre");
        body.textContent = text;
        node.append(heading, body);
        return node;
      }

      function renderMemoryFiles() {
        const panel = document.querySelector("#memory-files");
        panel.replaceChildren();
        for (const [path, text] of Object.entries(state.memoryFiles || {})) {
          panel.append(stepNode(path, text || "(missing or empty)"));
        }
      }

      function renderConfig() {
        document.querySelector("#config").innerHTML = `<pre>${JSON.stringify({
          engines: state.engines,
          config: state.config
        }, null, 2)}</pre>`;
      }

      async function postInspector(url, body) {
        const payload = await requestJson(url, body);
        document.querySelector("#output").textContent = JSON.stringify(payload, null, 2);
      }

      document.querySelector("#chat-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const input = document.querySelector("#chat-input");
        state = await requestJson("/api/chat/send", {
          message: input.value,
          engine: document.querySelector("#engine").value,
          autoFlush: document.querySelector("#auto-flush").checked
        });
        input.value = "";
        render();
      });
      document.querySelector("#manual-flush").onclick = async () => {
        state = await requestJson("/api/chat/flush", {engine: document.querySelector("#engine").value});
        render();
      };
      document.querySelector("#reset").onclick = async () => {
        state = await requestJson("/api/chat/reset", {});
        render();
      };
      document.querySelector("#seed").onclick = async () => postInspector("/api/seed", {});
      document.querySelector("#reindex").onclick = async () => postInspector("/api/reindex", {});
      document.querySelector("#search-form").onsubmit = (event) => {
        event.preventDefault();
        postInspector("/api/search", Object.fromEntries(new FormData(event.currentTarget)));
      };
      document.querySelector("#get-form").onsubmit = (event) => {
        event.preventDefault();
        const raw = Object.fromEntries(new FormData(event.currentTarget));
        postInspector("/api/get", {path: raw.path, from: Number(raw.from), lines: Number(raw.lines)});
      };
      document.querySelectorAll(".tab").forEach((tab) => {
        tab.onclick = () => {
          document.querySelectorAll(".tab, .tab-panel").forEach((node) => node.classList.remove("active"));
          tab.classList.add("active");
          document.querySelector(`#${tab.dataset.tab}`).classList.add("active");
        };
      });
      refresh();
    </script>
  </body>
</html>
```

- [ ] **Step 4: Replace CSS**

Replace `demo/static/styles.css` with:

```css
:root {
  color-scheme: light;
  --bg: #eef2f5;
  --panel: #ffffff;
  --panel-strong: #f8fafc;
  --line: #cfd8e3;
  --text: #18222d;
  --muted: #5d6b7a;
  --accent: #2563eb;
  --accent-dark: #1747a6;
  --good: #0f766e;
  --warn: #a16207;
  --code: #101923;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

button,
select,
textarea,
input {
  border: 1px solid var(--line);
  border-radius: 6px;
  font: inherit;
}

button {
  min-height: 34px;
  padding: 7px 11px;
  background: var(--accent);
  border-color: var(--accent);
  color: white;
  cursor: pointer;
}

button:hover {
  background: var(--accent-dark);
}

select,
textarea,
input {
  width: 100%;
  padding: 8px 10px;
  background: white;
  color: var(--text);
}

.app-shell {
  display: grid;
  gap: 16px;
  max-width: 1440px;
  min-height: 100vh;
  margin: 0 auto;
  padding: 18px;
}

.topbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 14px;
}

.topbar h1 {
  margin: 0;
  font-size: 24px;
}

.topbar p {
  margin: 4px 0 0;
  color: var(--muted);
}

.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  color: var(--muted);
}

.toggle input {
  width: auto;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 16px;
  min-height: 560px;
}

.chat-panel,
.pipeline,
.tab-panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}

.chat-panel {
  display: grid;
  grid-template-rows: 1fr auto;
  min-height: 560px;
}

.chat-log {
  display: grid;
  align-content: start;
  gap: 10px;
  overflow: auto;
  padding: 14px;
}

.message {
  max-width: 78%;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.message.user {
  justify-self: end;
  background: #e9f2ff;
  border-color: #bad4ff;
}

.message.assistant {
  justify-self: start;
  background: var(--panel-strong);
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  border-top: 1px solid var(--line);
  padding: 12px;
}

.pipeline {
  overflow: hidden;
}

.pipeline h2 {
  margin: 0;
  border-bottom: 1px solid var(--line);
  padding: 12px 14px;
  font-size: 17px;
}

.pipeline-content {
  display: grid;
  gap: 10px;
  max-height: 710px;
  overflow: auto;
  padding: 12px;
}

.pipeline-step {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-strong);
}

.pipeline-step h3 {
  margin: 0;
  border-bottom: 1px solid var(--line);
  padding: 8px 10px;
  font-size: 14px;
}

pre {
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: #dbeafe;
  background: var(--code);
  padding: 10px;
  font-size: 13px;
  line-height: 1.45;
}

.tabs {
  display: flex;
  gap: 8px;
}

.tab {
  background: white;
  color: var(--text);
  border-color: var(--line);
}

.tab.active {
  background: var(--text);
  border-color: var(--text);
  color: white;
}

.tab-panel {
  display: none;
  padding: 14px;
}

.tab-panel.active {
  display: grid;
  gap: 12px;
}

.inspector-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tool-form {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: var(--panel-strong);
}

.tool-form h3 {
  margin: 0;
}

@media (max-width: 980px) {
  .topbar,
  .workspace,
  .composer,
  .inspector-grid {
    grid-template-columns: 1fr;
  }

  .topbar {
    display: grid;
    align-items: stretch;
  }

  .toolbar {
    justify-content: start;
  }

  .workspace {
    min-height: 0;
  }
}
```

- [ ] **Step 5: Run UI smoke and demo tests**

Run: `pytest tests/demo -v`

Expected: all demo tests pass.

- [ ] **Step 6: Commit**

```bash
git add demo/templates/index.html demo/static/styles.css tests/demo/test_demo_app.py
git commit -m "feat: replace demo with chat memory lab ui"
```

---

### Task 8: End-To-End Verification And Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README demo section**

Add or replace the demo section in `README.md` with:

````markdown
## Chat Memory Demo

Run the OpenClaw-style chat memory lab:

```bash
python -m uvicorn demo.app:app --port 8000
```

Open `http://127.0.0.1:8000`.

The first screen is a chat lab. Send a message, inspect recall results, run manual memory flush, or enable auto flush. Fake mode is deterministic and requires no network. OpenAI-compatible mode is enabled only when these environment variables are set:

```bash
export OPENCLAW_DEMO_OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENCLAW_DEMO_OPENAI_API_KEY="sk-demo-key"
export OPENCLAW_DEMO_OPENAI_MODEL="gpt-4.1-mini"
```

Memory flush writes are restricted to `memory/YYYY-MM-DD.md`, matching OpenClaw's pre-compaction memory flush behavior.
````

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 3: Run lint**

Run: `ruff check .`

Expected: no issues.

- [ ] **Step 4: Run local demo smoke**

Run:

```bash
python -m uvicorn demo.app:app --port 8000
```

In another shell:

```bash
curl -s http://127.0.0.1:8000/api/chat/state
curl -s -X POST http://127.0.0.1:8000/api/chat/send \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ben teknik cevapları Türkçe tercih ediyorum.","engine":"fake","autoFlush":true}'
```

Expected:

- first response contains `"turns":[]`
- second response contains `"shouldWrite":true`
- `memory/2026-05-03.md` appears in `memoryFiles`

Stop uvicorn before ending the task.

- [ ] **Step 5: Optional in-app browser check**

If Browser Use is available in the session, open `http://127.0.0.1:8000`, send a fake chat message, press manual flush, and visually confirm:

- chat messages render in the left panel
- `Recall`, `Assistant Context`, `Flush Decision`, `File Diff`, and `Reindex` render in the right panel
- `Memory Files`, `Tool Inspector`, and `Config` tabs switch without overlap

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs: describe chat memory demo"
```

- [ ] **Step 7: Final status**

Run:

```bash
git status --short
git log --oneline -5
```

Expected:

- no uncommitted implementation changes
- latest commits include the chat memory demo implementation and README update
