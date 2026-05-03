# OpenClaw Memory Python Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a faithful Python port of OpenClaw core memory with a reusable library, SQLite hybrid index, `memory_search`, `memory_get`, prompt parity, and a FastAPI demo website.

**Architecture:** The Python library owns all OpenClaw-compatible behavior; the FastAPI demo is a thin validation surface over the same APIs. The implementation follows upstream commit `7f6798094ce9486a8f463772f4535484aca73fe2`, with parity tests locking prompt text, tool contracts, FTS query behavior, hybrid merge, MMR, and temporal decay.

**Tech Stack:** Python 3.11+, pytest, FastAPI, Jinja2, httpx/TestClient, SQLite FTS5, httpx for OpenAI-compatible embeddings, ruff.

---

## File Structure

- Create `pyproject.toml`: package metadata, runtime dependencies, test tooling, ruff config.
- Create `README.md`: quickstart, OpenClaw upstream commit, embedding env vars, demo command.
- Create `LICENSE.openclaw`: upstream MIT license notice copied from OpenClaw.
- Create `memory_core/config.py`: typed config dataclasses and defaults.
- Create `memory_core/workspace.py`: memory file discovery, safe path resolution, line-window reads.
- Create `memory_core/prompt_section.py`: `## Memory Recall` section builder.
- Create `memory_core/tools/citations.py`: citation mode, line source decoration, character clamps.
- Create `memory_core/tools/memory_get.py`: public `memory_get` service.
- Create `memory_core/tools/memory_search.py`: public `memory_search` service.
- Create `memory_core/index/chunking.py`: Markdown chunking with line ranges.
- Create `memory_core/index/fts.py`: upstream-style FTS query and BM25 score mapping.
- Create `memory_core/index/vector.py`: cosine similarity helpers.
- Create `memory_core/index/hybrid.py`: hybrid result merge.
- Create `memory_core/index/mmr.py`: CJK-aware tokenization and MMR reranking.
- Create `memory_core/index/temporal_decay.py`: date extraction and score decay.
- Create `memory_core/index/sqlite_store.py`: SQLite schema, forced reindex, vector/FTS search.
- Create `memory_core/embeddings/base.py`: provider protocol and deterministic fake provider.
- Create `memory_core/embeddings/openai_compatible.py`: HTTP embedding adapter.
- Create `memory_core/parity/upstream.py`: upstream commit and referenced source paths.
- Create `demo/app.py`: FastAPI app and API routes.
- Create `demo/templates/index.html`: demo UI.
- Create `demo/static/styles.css`: restrained styling for the demo.
- Create `tests/unit/`, `tests/integration/`, `tests/parity/`, and `tests/demo/`.

## Task 1: Project Scaffold And Upstream Metadata

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `LICENSE.openclaw`
- Create: `memory_core/__init__.py`
- Create: `memory_core/parity/upstream.py`
- Test: `tests/parity/test_upstream_metadata.py`

- [ ] **Step 1: Write the failing metadata test**

```python
# tests/parity/test_upstream_metadata.py
from memory_core.parity.upstream import UPSTREAM_COMMIT, UPSTREAM_SOURCE_PATHS


def test_upstream_commit_is_pinned():
    assert UPSTREAM_COMMIT == "7f6798094ce9486a8f463772f4535484aca73fe2"


def test_referenced_upstream_sources_are_recorded():
    assert "extensions/memory-core/src/prompt-section.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/hybrid.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/mmr.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/temporal-decay.ts" in UPSTREAM_SOURCE_PATHS
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/parity/test_upstream_metadata.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'memory-core'`.

- [ ] **Step 3: Add package metadata and upstream constants**

```toml
# pyproject.toml
[project]
name = "memory-core"
version = "0.1.0"
description = "Python port of OpenClaw core memory"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "httpx>=0.27",
  "jinja2>=3.1",
  "pydantic>=2.8",
  "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"
```

```python
# memory_core/__init__.py
"""Python port of OpenClaw core memory."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

```python
# memory_core/parity/upstream.py
UPSTREAM_REPOSITORY = "https://github.com/openclaw/openclaw"
UPSTREAM_COMMIT = "7f6798094ce9486a8f463772f4535484aca73fe2"

UPSTREAM_SOURCE_PATHS = {
    "extensions/memory-core/src/prompt-section.ts",
    "extensions/memory-core/src/tools.ts",
    "extensions/memory-core/src/tools.citations.ts",
    "extensions/memory-core/src/tools.shared.ts",
    "extensions/memory-core/src/memory/hybrid.ts",
    "extensions/memory-core/src/memory/mmr.ts",
    "extensions/memory-core/src/memory/temporal-decay.ts",
    "extensions/memory-core/src/memory/manager.ts",
    "extensions/memory-core/src/memory/manager-search.ts",
}
```

```text
# LICENSE.openclaw
MIT License

Copyright (c) 2025 Peter Steinberger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

```markdown
<!-- README.md -->
# memory-core

Python port of OpenClaw core memory, pinned to upstream commit
`7f6798094ce9486a8f463772f4535484aca73fe2`.

The first implementation slice covers `MEMORY.md`, `memory/YYYY-MM-DD.md`,
`memory_search`, `memory_get`, hybrid search, citations, and a local FastAPI demo.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/parity/test_upstream_metadata.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md LICENSE.openclaw memory-core tests/parity/test_upstream_metadata.py
git commit -m "chore: scaffold OpenClaw memory port"
```

## Task 2: Config Defaults And Workspace File Access

**Files:**
- Create: `memory_core/config.py`
- Create: `memory_core/workspace.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_workspace.py`

- [ ] **Step 1: Write failing config and workspace tests**

```python
# tests/unit/test_config.py
from pathlib import Path

from memory_core.config import MemoryConfig


def test_default_config_matches_first_slice_requirements(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path)
    assert cfg.agent_id == "main"
    assert cfg.embedding_provider == "openai-compatible"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.vector_weight == 0.5
    assert cfg.text_weight == 0.5
    assert cfg.memory_get_max_chars == 20_000
    assert cfg.memory_get_default_lines == 120
```

```python
# tests/unit/test_workspace.py
from pathlib import Path

import pytest

from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError


def test_discovers_root_and_dated_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Long\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-03.md").write_text("# Day\n", encoding="utf-8")
    (tmp_path / "memory" / "notes.txt").write_text("skip\n", encoding="utf-8")

    workspace = MemoryWorkspace(tmp_path)

    assert [entry.rel_path for entry in workspace.discover_memory_files()] == [
        "MEMORY.md",
        "memory/2026-05-03.md",
    ]


def test_safe_read_rejects_parent_escape(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)
    with pytest.raises(UnsafeMemoryPathError):
        workspace.read_text("../secret.txt")


def test_read_lines_uses_one_based_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("a\nb\nc\nd\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("MEMORY.md", from_line=2, line_count=2)

    assert result.path == "MEMORY.md"
    assert result.text == "b\nc\n"
    assert result.start_line == 2
    assert result.end_line == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config.py tests/unit/test_workspace.py -v`

Expected: FAIL because `config.py` and `workspace.py` do not exist.

- [ ] **Step 3: Implement config and workspace access**

```python
# memory_core/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryConfig:
    workspace_dir: Path
    agent_id: str = "main"
    store_path: Path | None = None
    embedding_provider: str = "openai-compatible"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    citation_mode: str = "on"
    memory_get_max_chars: int = 20_000
    memory_get_default_lines: int = 120
    vector_weight: float = 0.5
    text_weight: float = 0.5
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    temporal_decay_enabled: bool = False
    temporal_decay_half_life_days: float = 30.0

    def resolved_store_path(self) -> Path:
        if self.store_path is not None:
            return self.store_path
        return self.workspace_dir / ".openclaw-memory" / f"{self.agent_id}.sqlite"
```

```python
# memory_core/workspace.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class UnsafeMemoryPathError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryFile:
    rel_path: str
    abs_path: Path
    source: str = "memory"


@dataclass(frozen=True)
class MemoryReadResult:
    path: str
    text: str
    start_line: int
    end_line: int


class MemoryWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def discover_memory_files(self) -> list[MemoryFile]:
        files: list[MemoryFile] = []
        for name in ("MEMORY.md", "memory.md"):
            path = self.root / name
            if path.is_file():
                files.append(MemoryFile(name, path))
                break
        memory_dir = self.root / "memory"
        if memory_dir.is_dir():
            for path in sorted(memory_dir.glob("*.md")):
                if path.name[:10].count("-") == 2 and len(path.name) == len("YYYY-MM-DD.md"):
                    files.append(MemoryFile(path.relative_to(self.root).as_posix(), path))
        return files

    def resolve_memory_path(self, rel_path: str) -> Path:
        normalized = rel_path.replace("\\", "/").lstrip("/")
        candidate = (self.root / normalized).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")
        return candidate

    def read_text(
        self,
        rel_path: str,
        *,
        from_line: int | None = None,
        line_count: int | None = None,
    ) -> MemoryReadResult:
        path = self.resolve_memory_path(rel_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = max(1, from_line or 1)
        if line_count is None:
            selected = lines[start - 1 :]
        else:
            selected = lines[start - 1 : start - 1 + max(0, line_count)]
        end = start + len(selected) - 1 if selected else start - 1
        return MemoryReadResult(rel_path.replace("\\", "/"), "".join(selected), start, end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config.py tests/unit/test_workspace.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/config.py memory_core/workspace.py tests/unit/test_config.py tests/unit/test_workspace.py
git commit -m "feat: add memory workspace access"
```

## Task 3: Prompt Section And Citation Helpers

**Files:**
- Create: `memory_core/prompt_section.py`
- Create: `memory_core/tools/__init__.py`
- Create: `memory_core/tools/citations.py`
- Test: `tests/parity/test_prompt_section.py`
- Test: `tests/unit/test_citations.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/parity/test_prompt_section.py
from memory_core.prompt_section import build_prompt_section


def test_prompt_section_with_both_tools_matches_upstream_shape():
    lines = build_prompt_section({"memory_search", "memory_get"}, citations_mode="on")
    assert lines[0] == "## Memory Recall"
    assert "Before answering anything about prior work" in lines[1]
    assert "run memory_search on MEMORY.md + memory/*.md + indexed session transcripts" in lines[1]
    assert "then use memory_get to pull only the needed lines" in lines[1]
    assert lines[2] == "Citations: include Source: <path#line> when it helps the user verify memory snippets."
    assert lines[3] == ""


def test_prompt_section_omits_when_no_tools():
    assert build_prompt_section(set(), citations_mode="on") == []
```

```python
# tests/unit/test_citations.py
from memory_core.tools.citations import clamp_text, source_label


def test_source_label_uses_path_and_start_line():
    assert source_label("memory/2026-05-03.md", 7) == "Source: memory/2026-05-03.md#7"


def test_clamp_text_reports_truncation():
    result = clamp_text("abcdef", max_chars=4)
    assert result.text == "abcd"
    assert result.truncated is True
    assert result.original_chars == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/parity/test_prompt_section.py tests/unit/test_citations.py -v`

Expected: FAIL because prompt and citation modules do not exist.

- [ ] **Step 3: Implement prompt and citations**

```python
# memory_core/prompt_section.py
from __future__ import annotations


def build_prompt_section(available_tools: set[str], *, citations_mode: str) -> list[str]:
    has_memory_search = "memory_search" in available_tools
    has_memory_get = "memory_get" in available_tools
    if not has_memory_search and not has_memory_get:
        return []
    if has_memory_search and has_memory_get:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts; "
            "then use memory_get to pull only the needed lines. If low confidence after search, "
            "say you checked."
        )
    elif has_memory_search:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md + indexed session transcripts "
            "and answer from the matching results. If low confidence after search, say you checked."
        )
    else:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos that already point to a specific memory file or note: run memory_get to pull "
            "only the needed lines. If low confidence after reading them, say you checked."
        )
    lines = ["## Memory Recall", tool_guidance]
    if citations_mode == "off":
        lines.append(
            "Citations are disabled: do not mention file paths or line numbers in replies unless the user explicitly asks."
        )
    else:
        lines.append("Citations: include Source: <path#line> when it helps the user verify memory snippets.")
    lines.append("")
    return lines
```

```python
# memory_core/tools/citations.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClampedText:
    text: str
    truncated: bool
    original_chars: int


def source_label(path: str, start_line: int) -> str:
    return f"Source: {path}#{start_line}"


def clamp_text(text: str, *, max_chars: int) -> ClampedText:
    if len(text) <= max_chars:
        return ClampedText(text=text, truncated=False, original_chars=len(text))
    return ClampedText(text=text[:max_chars], truncated=True, original_chars=len(text))
```

```python
# memory_core/tools/__init__.py
"""Tool-level memory helpers."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/parity/test_prompt_section.py tests/unit/test_citations.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/prompt_section.py memory_core/tools tests/parity/test_prompt_section.py tests/unit/test_citations.py
git commit -m "feat: add prompt and citation parity"
```

## Task 4: Core Search Algorithms

**Files:**
- Create: `memory_core/index/__init__.py`
- Create: `memory_core/index/fts.py`
- Create: `memory_core/index/vector.py`
- Create: `memory_core/index/hybrid.py`
- Create: `memory_core/index/mmr.py`
- Create: `memory_core/index/temporal_decay.py`
- Test: `tests/parity/test_search_algorithms.py`

- [ ] **Step 1: Write failing parity tests**

```python
# tests/parity/test_search_algorithms.py
from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.index.hybrid import HybridKeywordResult, HybridVectorResult, merge_hybrid_results
from memory_core.index.mmr import mmr_rerank, tokenize
from memory_core.index.temporal_decay import calculate_temporal_decay_multiplier


def test_fts_query_quotes_tokens_with_and():
    assert build_fts_query('router vlan "prod"') == '"router" AND "vlan" AND "prod"'
    assert build_fts_query("!!!") is None


def test_bm25_rank_to_score_matches_upstream_formula():
    assert bm25_rank_to_score(-3.0) == 0.75
    assert bm25_rank_to_score(3.0) == 0.25


def test_hybrid_merge_combines_vector_and_keyword_scores():
    merged = merge_hybrid_results(
        vector=[HybridVectorResult("a", "MEMORY.md", 1, 2, "memory", "alpha", 0.8)],
        keyword=[HybridKeywordResult("a", "MEMORY.md", 1, 2, "memory", "alpha keyword", 0.4)],
        vector_weight=0.5,
        text_weight=0.5,
    )
    assert merged[0].score == 0.6000000000000001
    assert merged[0].snippet == "alpha keyword"


def test_mmr_tokenizer_handles_ascii_and_cjk():
    tokens = tokenize("Router VLAN 我喜欢你好")
    assert "router" in tokens
    assert "vlan" in tokens
    assert "我" in tokens
    assert "你好" in tokens


def test_temporal_decay_half_life():
    assert round(calculate_temporal_decay_multiplier(age_in_days=30, half_life_days=30), 3) == 0.5


def test_mmr_rerank_keeps_relevant_diverse_items():
    items = [
        {"id": "a", "score": 1.0, "content": "router vlan alpha"},
        {"id": "b", "score": 0.9, "content": "router vlan alpha duplicate"},
        {"id": "c", "score": 0.8, "content": "calendar preference"},
    ]
    ranked = mmr_rerank(items, enabled=True, lambda_=0.7)
    assert ranked[0]["id"] == "a"
    assert {item["id"] for item in ranked} == {"a", "b", "c"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/parity/test_search_algorithms.py -v`

Expected: FAIL because index modules do not exist.

- [ ] **Step 3: Implement algorithms**

```python
# memory_core/index/fts.py
from __future__ import annotations

import math
import re


def build_fts_query(raw: str) -> str | None:
    tokens = [t.strip() for t in re.findall(r"[\w]+", raw, flags=re.UNICODE) if t.strip()]
    if not tokens:
        return None
    return " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


def bm25_rank_to_score(rank: float) -> float:
    if not math.isfinite(rank):
        return 1 / (1 + 999)
    if rank < 0:
        relevance = -rank
        return relevance / (1 + relevance)
    return 1 / (1 + rank)
```

```python
# memory_core/index/vector.py
from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```

```python
# memory_core/index/hybrid.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HybridVectorResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    vector_score: float


@dataclass(frozen=True)
class HybridKeywordResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    text_score: float


@dataclass(frozen=True)
class HybridResult:
    path: str
    start_line: int
    end_line: int
    score: float
    vector_score: float
    text_score: float
    snippet: str
    source: str


def merge_hybrid_results(
    *,
    vector: list[HybridVectorResult],
    keyword: list[HybridKeywordResult],
    vector_weight: float,
    text_weight: float,
) -> list[HybridResult]:
    by_id: dict[str, dict[str, object]] = {}
    for result in vector:
        by_id[result.id] = {
            "path": result.path,
            "start_line": result.start_line,
            "end_line": result.end_line,
            "source": result.source,
            "snippet": result.snippet,
            "vector_score": result.vector_score,
            "text_score": 0.0,
        }
    for result in keyword:
        entry = by_id.setdefault(
            result.id,
            {
                "path": result.path,
                "start_line": result.start_line,
                "end_line": result.end_line,
                "source": result.source,
                "snippet": result.snippet,
                "vector_score": 0.0,
                "text_score": 0.0,
            },
        )
        entry["text_score"] = result.text_score
        if result.snippet:
            entry["snippet"] = result.snippet
    merged = [
        HybridResult(
            path=str(entry["path"]),
            start_line=int(entry["start_line"]),
            end_line=int(entry["end_line"]),
            source=str(entry["source"]),
            snippet=str(entry["snippet"]),
            vector_score=float(entry["vector_score"]),
            text_score=float(entry["text_score"]),
            score=vector_weight * float(entry["vector_score"]) + text_weight * float(entry["text_score"]),
        )
        for entry in by_id.values()
    ]
    return sorted(merged, key=lambda item: item.score, reverse=True)
```

```python
# memory_core/index/mmr.py
from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u1100-\u11ff]")


def tokenize(text: str) -> set[str]:
    lower = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9_]+", lower)
    chars = list(lower)
    cjk_data = [(char, index) for index, char in enumerate(chars) if CJK_RE.match(char)]
    bigrams = [
        cjk_data[i][0] + cjk_data[i + 1][0]
        for i in range(len(cjk_data) - 1)
        if cjk_data[i + 1][1] == cjk_data[i][1] + 1
    ]
    unigrams = [char for char, _ in cjk_data]
    return set(ascii_tokens + bigrams + unigrams)


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_rerank(items: list[dict], *, enabled: bool = False, lambda_: float = 0.7) -> list[dict]:
    if not enabled or len(items) <= 1:
        return list(items)
    clamped = max(0.0, min(1.0, lambda_))
    max_score = max(item["score"] for item in items)
    min_score = min(item["score"] for item in items)
    score_range = max_score - min_score
    selected: list[dict] = []
    remaining = list(items)
    token_cache = {item["id"]: tokenize(item["content"]) for item in items}
    while remaining:
        best = None
        best_score = float("-inf")
        for candidate in remaining:
            relevance = 1.0 if score_range == 0 else (candidate["score"] - min_score) / score_range
            max_similarity = max(
                (jaccard_similarity(token_cache[candidate["id"]], token_cache[item["id"]]) for item in selected),
                default=0.0,
            )
            mmr_score = clamped * relevance - (1 - clamped) * max_similarity
            if mmr_score > best_score or (
                mmr_score == best_score and (best is None or candidate["score"] > best["score"])
            ):
                best = candidate
                best_score = mmr_score
        selected.append(best)
        remaining.remove(best)
    return selected
```

```python
# memory_core/index/temporal_decay.py
from __future__ import annotations

import math


def calculate_temporal_decay_multiplier(*, age_in_days: float, half_life_days: float) -> float:
    if not math.isfinite(half_life_days) or half_life_days <= 0:
        return 1.0
    clamped_age = max(0.0, age_in_days)
    return math.exp(-(math.log(2) / half_life_days) * clamped_age)
```

```python
# memory_core/index/__init__.py
"""Indexing and search algorithms."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/parity/test_search_algorithms.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/index tests/parity/test_search_algorithms.py
git commit -m "feat: port core search algorithms"
```

## Task 5: Embedding Providers

**Files:**
- Create: `memory_core/embeddings/__init__.py`
- Create: `memory_core/embeddings/base.py`
- Create: `memory_core/embeddings/openai_compatible.py`
- Test: `tests/unit/test_embeddings.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_embeddings.py
import pytest

from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider(dimensions=6)
    assert provider.embed_query("alpha") == provider.embed_query("alpha")
    assert provider.embed_query("alpha") != provider.embed_query("beta")


def test_openai_provider_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        OpenAICompatibleEmbeddingProvider(api_key="", model="text-embedding-3-small")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_embeddings.py -v`

Expected: FAIL because embedding modules do not exist.

- [ ] **Step 3: Implement provider protocol, fake provider, and OpenAI-compatible adapter**

```python
# memory_core/embeddings/base.py
from __future__ import annotations

import hashlib
from typing import Protocol


class EmbeddingProvider(Protocol):
    provider_id: str
    model: str

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbeddingProvider:
    provider_id = "fake"
    model = "fake-deterministic"

    def __init__(self, dimensions: int = 16):
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [digest[i % len(digest)] / 255 for i in range(self.dimensions)]
        return values

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"query:{text}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(f"document:{text}") for text in texts]
```

```python
# memory_core/embeddings/openai_compatible.py
from __future__ import annotations

import httpx


class OpenAICompatibleEmbeddingProvider:
    provider_id = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("api_key is required for OpenAI-compatible embeddings")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": inputs},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return [item["embedding"] for item in sorted(payload["data"], key=lambda item: item["index"])]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)
```

```python
# memory_core/embeddings/__init__.py
"""Embedding provider adapters."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_embeddings.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/embeddings tests/unit/test_embeddings.py
git commit -m "feat: add embedding provider adapters"
```

## Task 6: Chunking And SQLite Forced Reindex

**Files:**
- Create: `memory_core/index/chunking.py`
- Create: `memory_core/index/sqlite_store.py`
- Test: `tests/unit/test_chunking.py`
- Test: `tests/integration/test_sqlite_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_chunking.py
from memory_core.index.chunking import chunk_markdown


def test_chunk_markdown_preserves_line_ranges():
    text = "# Title\none two three\nfour five six\n"
    chunks = chunk_markdown("MEMORY.md", text, target_tokens=3, overlap_tokens=1)
    assert chunks[0].path == "MEMORY.md"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line >= 1
    assert chunks[0].text
```

```python
# tests/integration/test_sqlite_store.py
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def test_forced_reindex_indexes_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("User prefers blue cheese with wings.\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-03.md").write_text("Discussed router VLANs.\n", encoding="utf-8")
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))

    indexed = store.reindex(MemoryWorkspace(tmp_path))

    assert indexed == 2
    assert store.count_chunks() >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_chunking.py tests/integration/test_sqlite_store.py -v`

Expected: FAIL because chunking and SQLite store do not exist.

- [ ] **Step 3: Implement chunking and SQLite schema**

```python
# memory_core/index/chunking.py
from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str
    source: str = "memory"


def chunk_markdown(
    path: str,
    text: str,
    *,
    target_tokens: int = 400,
    overlap_tokens: int = 80,
) -> list[MemoryChunk]:
    lines = text.splitlines()
    line_tokens = [(index + 1, line, line.split()) for index, line in enumerate(lines)]
    chunks: list[MemoryChunk] = []
    current: list[tuple[int, str, list[str]]] = []
    current_count = 0
    for item in line_tokens:
        current.append(item)
        current_count += len(item[2])
        if current_count >= target_tokens:
            chunks.append(_make_chunk(path, current))
            overlap: list[tuple[int, str, list[str]]] = []
            overlap_count = 0
            for existing in reversed(current):
                overlap.insert(0, existing)
                overlap_count += len(existing[2])
                if overlap_count >= overlap_tokens:
                    break
            current = overlap
            current_count = overlap_count
    if current:
        chunk = _make_chunk(path, current)
        if not chunks or chunks[-1].id != chunk.id:
            chunks.append(chunk)
    return chunks


def _make_chunk(path: str, rows: list[tuple[int, str, list[str]]]) -> MemoryChunk:
    start_line = rows[0][0]
    end_line = rows[-1][0]
    text = "\n".join(row[1] for row in rows).strip() + "\n"
    digest = hashlib.sha256(f"{path}:{start_line}:{end_line}:{text}".encode("utf-8")).hexdigest()
    return MemoryChunk(id=digest, path=path, start_line=start_line, end_line=end_line, text=text)
```

```python
# memory_core/index/sqlite_store.py
from __future__ import annotations

import json
import sqlite3

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
from memory_core.workspace import MemoryWorkspace


class SQLiteMemoryStore:
    def __init__(self, config: MemoryConfig, embeddings: EmbeddingProvider):
        self.config = config
        self.embeddings = embeddings
        self.path = config.resolved_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
            """)
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text)")

    def reindex(self, workspace: MemoryWorkspace) -> int:
        files = workspace.discover_memory_files()
        chunks: list[MemoryChunk] = []
        for file in files:
            text = file.abs_path.read_text(encoding="utf-8")
            chunks.extend(chunk_markdown(file.rel_path, text))
        embeddings = self.embeddings.embed_documents([chunk.text for chunk in chunks]) if chunks else []
        with self.connect() as db:
            db.execute("DELETE FROM chunks")
            db.execute("DELETE FROM chunks_fts")
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                db.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        chunk.path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.source,
                        chunk.text,
                        json.dumps(embedding),
                    ),
                )
                db.execute("INSERT INTO chunks_fts(id, text) VALUES (?, ?)", (chunk.id, chunk.text))
        return len(files)

    def count_chunks(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_chunking.py tests/integration/test_sqlite_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/index/chunking.py memory_core/index/sqlite_store.py tests/unit/test_chunking.py tests/integration/test_sqlite_store.py
git commit -m "feat: add memory chunking and SQLite reindex"
```

## Task 7: Search And Get Tool Services

**Files:**
- Modify: `memory_core/index/sqlite_store.py`
- Create: `memory_core/tools/memory_get.py`
- Create: `memory_core/tools/memory_search.py`
- Test: `tests/integration/test_memory_tools.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/integration/test_memory_tools.py
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace


def test_memory_get_reads_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="MEMORY.md", from_line=2, lines=1)
    assert result["path"] == "MEMORY.md"
    assert result["text"] == "beta\n"
    assert result["startLine"] == 2
    assert result["endLine"] == 2


def test_memory_search_returns_hybrid_results(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("User likes lemon pepper wings.\n", encoding="utf-8")
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="lemon pepper", max_results=3, min_score=0.0)

    assert result["provider"] == "fake"
    assert result["model"] == "fake-deterministic"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert result["results"][0]["corpus"] == "memory"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_memory_tools.py -v`

Expected: FAIL because tool services do not exist and store search methods are missing.

- [ ] **Step 3: Add store search methods and tool services**

Add this method to `SQLiteMemoryStore`:

```python
    def search(self, query: str, *, max_results: int = 5, min_score: float = 0.0):
        from memory_core.index.fts import bm25_rank_to_score, build_fts_query
        from memory_core.index.hybrid import HybridKeywordResult, HybridVectorResult, merge_hybrid_results
        from memory_core.index.vector import cosine_similarity

        query_embedding = self.embeddings.embed_query(query)
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, path, start_line, end_line, source, text, embedding FROM chunks"
            ).fetchall()
            vector = [
                HybridVectorResult(
                    id=row[0],
                    path=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    source=row[4],
                    snippet=row[5],
                    vector_score=cosine_similarity(query_embedding, json.loads(row[6])),
                )
                for row in rows
            ]
            fts_query = build_fts_query(query)
            keyword = []
            if fts_query:
                for row in db.execute(
                    """
                    SELECT c.id, c.path, c.start_line, c.end_line, c.source, c.text, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.id
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    """,
                    (fts_query,),
                ):
                    keyword.append(
                        HybridKeywordResult(
                            id=row[0],
                            path=row[1],
                            start_line=row[2],
                            end_line=row[3],
                            source=row[4],
                            snippet=row[5],
                            text_score=bm25_rank_to_score(float(row[6])),
                        )
                    )
        merged = merge_hybrid_results(
            vector=vector,
            keyword=keyword,
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
        )
        return [item for item in merged if item.score >= min_score][:max_results]
```

```python
# memory_core/tools/memory_get.py
from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.tools.citations import clamp_text
from memory_core.workspace import MemoryWorkspace


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
) -> dict:
    try:
        read = MemoryWorkspace(config.workspace_dir).read_text(
            path,
            from_line=from_line,
            line_count=lines if lines is not None else config.memory_get_default_lines,
        )
        clamped = clamp_text(read.text, max_chars=config.memory_get_max_chars)
        return {
            "path": read.path,
            "text": clamped.text,
            "startLine": read.start_line,
            "endLine": read.end_line,
            "truncated": clamped.truncated,
            "originalChars": clamped.original_chars,
        }
    except Exception as exc:
        return {"path": path, "text": "", "disabled": True, "error": str(exc)}
```

```python
# memory_core/tools/memory_search.py
from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int = 5,
    min_score: float = 0.0,
    corpus: str = "memory",
) -> dict:
    if corpus != "memory":
        return {"results": [], "disabled": True, "error": f"unsupported corpus: {corpus}"}
    try:
        results = store.search(query, max_results=max_results, min_score=min_score)
        return {
            "results": [
                {
                    "corpus": "memory",
                    "path": item.path,
                    "startLine": item.start_line,
                    "endLine": item.end_line,
                    "score": item.score,
                    "vectorScore": item.vector_score,
                    "textScore": item.text_score,
                    "snippet": item.snippet,
                    "source": item.source,
                }
                for item in results
            ],
            "provider": store.embeddings.provider_id,
            "model": store.embeddings.model,
        }
    except Exception as exc:
        return {"results": [], "disabled": True, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_memory_tools.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory_core/index/sqlite_store.py memory_core/tools/memory_get.py memory_core/tools/memory_search.py tests/integration/test_memory_tools.py
git commit -m "feat: add memory search and get tools"
```

## Task 8: FastAPI Demo Website

**Files:**
- Create: `demo/__init__.py`
- Create: `demo/app.py`
- Create: `demo/templates/index.html`
- Create: `demo/static/styles.css`
- Test: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Write failing demo tests**

```python
# tests/demo/test_demo_app.py
from fastapi.testclient import TestClient

from demo.app import app


def test_demo_home_loads():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "OpenClaw Memory Demo" in response.text


def test_prompt_preview_endpoint():
    client = TestClient(app)
    response = client.post("/api/prompt-preview", json={"tools": ["memory_search", "memory_get"], "citationsMode": "on"})
    assert response.status_code == 200
    assert response.json()["lines"][0] == "## Memory Recall"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/demo/test_demo_app.py -v`

Expected: FAIL because `demo.app` does not exist.

- [ ] **Step 3: Implement FastAPI app and UI**

```python
# demo/app.py
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_WORKSPACE = DEMO_ROOT / "workspace"

app = FastAPI(title="OpenClaw Memory Demo")
app.mount("/static", StaticFiles(directory=DEMO_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=DEMO_ROOT / "templates")


def demo_config() -> MemoryConfig:
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    return MemoryConfig(workspace_dir=DEMO_WORKSPACE, store_path=DEMO_WORKSPACE / "memory.sqlite")


def demo_store() -> SQLiteMemoryStore:
    return SQLiteMemoryStore(demo_config(), FakeEmbeddingProvider(dimensions=16))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/seed")
def seed():
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    (DEMO_WORKSPACE / "memory").mkdir(exist_ok=True)
    (DEMO_WORKSPACE / "MEMORY.md").write_text("User prefers lemon pepper wings with blue cheese.\n", encoding="utf-8")
    (DEMO_WORKSPACE / "memory" / "2026-05-03.md").write_text("Discussed router VLAN troubleshooting.\n", encoding="utf-8")
    return {"ok": True}


@app.post("/api/reindex")
def reindex():
    store = demo_store()
    indexed = store.reindex(MemoryWorkspace(demo_config().workspace_dir))
    return {"indexedFiles": indexed, "chunks": store.count_chunks()}


@app.post("/api/search")
def search(payload: dict):
    return memory_search(
        demo_config(),
        demo_store(),
        query=payload.get("query", ""),
        max_results=int(payload.get("maxResults", 5)),
        min_score=float(payload.get("minScore", 0)),
    )


@app.post("/api/get")
def get_memory(payload: dict):
    return memory_get(
        demo_config(),
        path=payload.get("path", "MEMORY.md"),
        from_line=payload.get("from"),
        lines=payload.get("lines"),
    )


@app.post("/api/prompt-preview")
def prompt_preview(payload: dict):
    return {
        "lines": build_prompt_section(
            set(payload.get("tools", [])),
            citations_mode=payload.get("citationsMode", "on"),
        )
    }
```

```html
<!-- demo/templates/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>OpenClaw Memory Demo</title>
    <link rel="stylesheet" href="/static/styles.css">
  </head>
  <body>
    <main>
      <h1>OpenClaw Memory Demo</h1>
      <section>
        <button id="seed">Seed Memory</button>
        <button id="reindex">Reindex</button>
      </section>
      <section class="grid">
        <form id="search-form">
          <h2>memory_search</h2>
          <input name="query" value="lemon pepper" aria-label="query">
          <input name="maxResults" value="5" aria-label="max results">
          <input name="minScore" value="0" aria-label="min score">
          <button>Search</button>
        </form>
        <form id="get-form">
          <h2>memory_get</h2>
          <input name="path" value="MEMORY.md" aria-label="path">
          <input name="from" value="1" aria-label="from line">
          <input name="lines" value="20" aria-label="line count">
          <button>Get</button>
        </form>
      </section>
      <pre id="output">{}</pre>
    </main>
    <script>
      async function postJson(url, body = {}) {
        const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
        document.querySelector("#output").textContent = JSON.stringify(await response.json(), null, 2);
      }
      document.querySelector("#seed").onclick = () => postJson("/api/seed");
      document.querySelector("#reindex").onclick = () => postJson("/api/reindex");
      document.querySelector("#search-form").onsubmit = (event) => {
        event.preventDefault();
        const data = Object.fromEntries(new FormData(event.currentTarget));
        postJson("/api/search", data);
      };
      document.querySelector("#get-form").onsubmit = (event) => {
        event.preventDefault();
        const raw = Object.fromEntries(new FormData(event.currentTarget));
        postJson("/api/get", {path: raw.path, from: Number(raw.from), lines: Number(raw.lines)});
      };
    </script>
  </body>
</html>
```

```css
/* demo/static/styles.css */
body { font-family: Inter, system-ui, sans-serif; margin: 0; color: #172026; background: #f7f8fa; }
main { max-width: 1100px; margin: 0 auto; padding: 32px; }
button, input { font: inherit; padding: 8px 10px; border: 1px solid #c8d0d9; border-radius: 6px; }
button { background: #1f6feb; color: white; border-color: #1f6feb; cursor: pointer; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin: 24px 0; }
form { display: grid; gap: 10px; background: white; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; }
pre { background: #111827; color: #e5e7eb; padding: 16px; border-radius: 8px; overflow: auto; min-height: 260px; }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/demo/test_demo_app.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo tests/demo/test_demo_app.py
git commit -m "feat: add FastAPI memory demo"
```

## Task 9: Full Verification, Docs, And Demo Run

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` if dependency or ruff config needs adjustment

- [ ] **Step 1: Add README usage details**

````markdown
## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run Tests

```bash
pytest -v
ruff check .
```

## Run Demo

```bash
uvicorn demo.app:app --reload --port 8000
```

Open <http://localhost:8000>, click Seed Memory, click Reindex, then test
`memory_search` and `memory_get`.

## Live OpenAI-Compatible Embeddings

The demo and tests default to deterministic fake embeddings. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.
````

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`

Expected: all tests PASS.

- [ ] **Step 3: Run linter**

Run: `ruff check .`

Expected: PASS. If ruff reports import sorting or line length issues, apply the exact formatting change ruff names and rerun `ruff check .`.

- [ ] **Step 4: Start the demo server**

Run: `uvicorn demo.app:app --port 8000`

Expected: terminal shows `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 5: Smoke test demo endpoints**

Run in another terminal:

```bash
python - <<'PY'
import httpx

base = "http://127.0.0.1:8000"
print(httpx.get(base + "/").status_code)
print(httpx.post(base + "/api/seed").json())
print(httpx.post(base + "/api/reindex").json())
print(httpx.post(base + "/api/search", json={"query": "lemon pepper"}).json()["results"][0]["path"])
print(httpx.post(base + "/api/get", json={"path": "MEMORY.md", "from": 1, "lines": 1}).json()["text"])
PY
```

Expected output contains:

```text
200
{'ok': True}
MEMORY.md
User prefers lemon pepper wings with blue cheese.
```

- [ ] **Step 6: Commit verification docs**

```bash
git add README.md pyproject.toml
git commit -m "docs: add memory demo usage"
```

## Plan Self-Review

Spec coverage:

- Core files: Task 2 and Task 6.
- Prompt section: Task 3.
- Citations/truncation: Task 3 and Task 7.
- Hybrid search: Task 4, Task 6, Task 7.
- Required embeddings: Task 5 and Task 7.
- SQLite forced reindex: Task 6.
- FastAPI demo: Task 8 and Task 9.
- Tests and parity fixtures: Tasks 1 through 9.
- Out-of-scope items stay excluded: no dreaming, active memory, session transcript search, alternate backends, or file watcher tasks are included.

Type consistency:

- Config object is `MemoryConfig`.
- Workspace object is `MemoryWorkspace`.
- Store object is `SQLiteMemoryStore`.
- Public tool functions are `memory_get()` and `memory_search()`.
- Prompt builder is `build_prompt_section()`.

Execution order:

- Tasks are sequential and each has tests plus a commit checkpoint.
- Task 9 is the final verification gate before declaring implementation complete.
