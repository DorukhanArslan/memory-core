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
    plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert plan.soft_threshold_tokens == DEFAULT_MEMORY_FLUSH_SOFT_TOKENS == 4000
    assert (
        plan.force_flush_transcript_bytes
        == DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES
        == 2 * 1024 * 1024
    )
    assert plan.relative_path == "memory/2026-05-03.md"
    assert "Pre-compaction memory flush." in plan.prompt
    assert (
        "Store durable memories only in memory/2026-05-03.md "
        "(create memory/ if needed)."
    ) in plan.prompt
    assert (
        "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, "
        "SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never "
        "overwrite, replace, or edit them."
    ) in plan.prompt
    assert (
        "If memory/2026-05-03.md already exists, APPEND new content only and do "
        "not overwrite existing entries."
    ) in plan.prompt
    assert (
        "Do NOT create timestamped variant files (e.g., 2026-05-03-HHMM.md); "
        "always use the canonical 2026-05-03.md filename."
    ) in plan.prompt
    assert f"If nothing to store, reply with {SILENT_REPLY_TOKEN}." in plan.prompt
    assert "Current time:" in plan.prompt
    assert "Pre-compaction memory flush turn." in plan.system_prompt
    assert (
        f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct."
    ) in plan.system_prompt


def test_validate_daily_memory_target_accepts_only_canonical_daily_file():
    assert (
        validate_daily_memory_target("memory/2026-05-03.md")
        == "memory/2026-05-03.md"
    )


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
