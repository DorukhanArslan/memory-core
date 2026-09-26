"""Curated MEMORY.md writes (memory-core extension): text edits, safety and flag behaviour."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from memory_core.bootstrap import DEFAULT_WORKSPACE_LAYOUT, OPENCLAW_PIN_LAYOUT, WorkspaceLayout
from memory_core.curation import (
    ADD_MEMORY_ENTRY,
    CURATION_OPERATIONS,
    REMOVE_MEMORY_ENTRY,
    REPLACE_MEMORY_ENTRY,
    CurationConflictError,
    CurationError,
    CurationPolicy,
    CurationUnavailableError,
    MemoryCurator,
    add_memory_entry_text,
    remove_memory_entry_text,
    replace_memory_entry_text,
)
from memory_core.flags import FeatureFlags
from memory_core.memory_budget import parse_memory_blocks

# Promotion blocks in the format the promotion pipeline writes
# (short-term-promotion.ts:2322-2335; demo/short_term_promotion.py _build_promotion_section).
PROMOTION_OLD = (
    "## Promoted From Short-Term Memory (2026-04-10)\n"
    "\n"
    "<!-- openclaw-memory-promotion:memory:memory/2026-04-09.md:3:3 -->\n"
    "- alpha [score=0.960 recalls=3 avg=0.920 source=memory/2026-04-09.md:3-3]\n"
)
PROMOTION_NEW = (
    "## Promoted From Short-Term Memory (2026-04-20)\n"
    "\n"
    "<!-- openclaw-memory-promotion:memory:memory/2026-04-19.md:5:6 -->\n"
    "- beta [score=0.910 recalls=4 avg=0.880 source=memory/2026-04-19.md:5-6]\n"
)
MEMORY_WITH_PROMOTIONS = (
    "# Long-Term Memory\n"
    "\n"
    "Some content.\n"
    "\n"
    "## My Notes\n"
    "\n"
    "- Important user content I do not want dropped.\n"
    "- gamma\n"
    "\n"
    f"{PROMOTION_OLD}"
    "\n"
    "## My Reflections\n"
    "- My own notes.\n"
    "\n"
    f"{PROMOTION_NEW}"
)


def _promotion_blocks(content: str) -> list[str]:
    return [block.text.rstrip("\n") for block in parse_memory_blocks(content) if block.kind == "promotion"]


# --- text edits ----------------------------------------------------------------


def test_add_appends_to_the_end_of_an_existing_section_only():
    updated = add_memory_entry_text(MEMORY_WITH_PROMOTIONS, "My Notes", "delta")

    assert updated == MEMORY_WITH_PROMOTIONS.replace("- gamma\n", "- gamma\n- delta\n", 1)


def test_add_creates_a_missing_section_at_the_end_of_the_file():
    updated = add_memory_entry_text(MEMORY_WITH_PROMOTIONS, "Decisions", "- delta")

    assert updated == MEMORY_WITH_PROMOTIONS + "\n## Decisions\n\n- delta\n"
    assert _promotion_blocks(updated) == _promotion_blocks(MEMORY_WITH_PROMOTIONS)


def test_add_to_empty_content_and_to_a_heading_only_section():
    assert add_memory_entry_text("", "## Decisions", "delta") == "## Decisions\n\n- delta\n"
    assert add_memory_entry_text("## Decisions", "Decisions", "delta") == (
        "## Decisions\n\n- delta\n"
    )
    assert add_memory_entry_text("Some content.", "Decisions", "delta") == (
        "Some content.\n\n## Decisions\n\n- delta\n"
    )


def test_add_keeps_crlf_line_endings():
    content = "# Long-Term Memory\r\n\r\n## My Notes\r\n- gamma\r\n"

    assert add_memory_entry_text(content, "My Notes", "delta") == (
        "# Long-Term Memory\r\n\r\n## My Notes\r\n- gamma\r\n- delta\r\n"
    )
    assert add_memory_entry_text(content, "Other", "delta") == (
        content + "\r\n## Other\r\n\r\n- delta\r\n"
    )


@pytest.mark.parametrize(
    ("section", "text", "message"),
    [
        ("My Notes", "", "text required"),
        ("My Notes", "- ", "text required"),
        ("My Notes", "one\ntwo", "text must be a single line"),
        ("My Notes", "one two", "text must be a single line"),
        ("My Notes", "<!-- openclaw-memory-promotion:x --> y", "memory promotion marker"),
        ("My Notes", "bad\x00byte", "NUL"),
        ("My Notes", "lone \ud800 surrogate", "valid Unicode"),
        ("", "delta", "section required"),
        ("### Deep", "delta", "without '#' marks"),
        ("Promoted From Short-Term Memory (2026-04-10)", "delta", "managed by memory promotion"),
        ("Promoted From Short-Term Memory (2026-05-01)", "delta", "managed by memory promotion"),
        ("A\nB", "delta", "section must be a single line"),
    ],
)
def test_add_rejects_invalid_input(section, text, message):
    with pytest.raises(CurationError, match=message):
        add_memory_entry_text(MEMORY_WITH_PROMOTIONS, section, text)


def test_add_refuses_a_section_title_that_appears_twice():
    content = "## My Notes\n- gamma\n## My Notes\n- delta\n"

    with pytest.raises(CurationError, match="appears 2 times"):
        add_memory_entry_text(content, "My Notes", "epsilon")


def test_replace_keeps_indentation_marker_and_every_other_byte():
    content = "## My Notes\n  * gamma  \n1. delta\nplain line\n"

    assert replace_memory_entry_text(content, "gamma", "GAMMA") == (
        "## My Notes\n  * GAMMA\n1. delta\nplain line\n"
    )
    assert replace_memory_entry_text(content, "- delta", "DELTA") == (
        "## My Notes\n  * gamma  \n1. DELTA\nplain line\n"
    )
    assert replace_memory_entry_text(content, "plain line", "PLAIN") == (
        "## My Notes\n  * gamma  \n1. delta\nPLAIN\n"
    )


def test_remove_deletes_exactly_one_line():
    updated = remove_memory_entry_text(MEMORY_WITH_PROMOTIONS, "gamma")

    assert updated == MEMORY_WITH_PROMOTIONS.replace("- gamma\n", "", 1)
    assert _promotion_blocks(updated) == _promotion_blocks(MEMORY_WITH_PROMOTIONS)


def test_edits_add_a_missing_trailing_newline():
    assert remove_memory_entry_text("- gamma\n- delta", "gamma") == "- delta\n"
    assert replace_memory_entry_text("- gamma", "gamma", "delta") == "- delta\n"


def test_promotion_entries_and_stray_markers_are_read_only():
    with pytest.raises(CurationError, match="promotion"):
        replace_memory_entry_text(
            MEMORY_WITH_PROMOTIONS,
            "alpha [score=0.960 recalls=3 avg=0.920 source=memory/2026-04-09.md:3-3]",
            "changed",
        )
    with pytest.raises(CurationError, match="promotion"):
        remove_memory_entry_text(
            MEMORY_WITH_PROMOTIONS, "<!-- openclaw-memory-promotion:memory:memory/2026-04-19.md:5:6 -->"
        )
    stray = "## My Notes\n<!-- openclaw-memory-promotion:k -->\n- gamma\n"
    with pytest.raises(CurationError, match="promotion"):
        remove_memory_entry_text(stray, "<!-- openclaw-memory-promotion:k -->")
    assert remove_memory_entry_text(stray, "gamma") == (
        "## My Notes\n<!-- openclaw-memory-promotion:k -->\n"
    )


def test_every_edit_leaves_promotion_blocks_byte_identical():
    content = add_memory_entry_text(MEMORY_WITH_PROMOTIONS, "My Reflections", "delta")
    content = add_memory_entry_text(content, "Decisions", "epsilon")
    content = replace_memory_entry_text(content, "gamma", "GAMMA")
    content = remove_memory_entry_text(content, "My own notes.")

    assert _promotion_blocks(content) == _promotion_blocks(MEMORY_WITH_PROMOTIONS)
    assert PROMOTION_OLD in content and PROMOTION_NEW in content


def test_ambiguous_entries_need_a_section():
    content = "## My Notes\n- gamma\n## My Reflections\n- gamma\n- gamma\n"

    with pytest.raises(CurationError, match="appears in 2 sections"):
        remove_memory_entry_text(content, "gamma")
    assert remove_memory_entry_text(content, "gamma", section="My Reflections") == (
        "## My Notes\n- gamma\n## My Reflections\n- gamma\n"
    )
    with pytest.raises(CurationError, match="not found in MEMORY.md section 'Other'"):
        remove_memory_entry_text(content, "gamma", section="Other")
    with pytest.raises(CurationError, match="entry not found"):
        replace_memory_entry_text(content, "delta", "x")


# --- curator: files, safety, policy, flag --------------------------------------------


def _curator(root: Path, **kwargs) -> MemoryCurator:
    return MemoryCurator(root, **kwargs)


def _write_memory(root: Path, content: str = MEMORY_WITH_PROMOTIONS) -> Path:
    path = root / "MEMORY.md"
    path.write_text(content, encoding="utf-8", newline="")
    return path


def test_curator_writes_memory_and_reports_the_result(tmp_path):
    path = _write_memory(tmp_path)
    path.chmod(0o640)
    results = []
    curator = _curator(tmp_path, after_write=results.append)

    added = curator.add_memory_entry("My Notes", "delta")
    unchanged = curator.replace_memory_entry("delta", "delta")
    removed = curator.remove_memory_entry("delta")

    assert (added.action, added.changed, added.path) == ("added", True, "MEMORY.md")
    assert (unchanged.action, unchanged.changed) == ("unchanged", False)
    assert (removed.action, removed.changed) == ("removed", True)
    assert results == [added, removed]
    assert path.read_text(encoding="utf-8") == MEMORY_WITH_PROMOTIONS
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert sorted(os.listdir(tmp_path)) == ["MEMORY.md"]
    assert added.to_tool_result() == {
        "status": "ok",
        "tool": ADD_MEMORY_ENTRY,
        "path": "MEMORY.md",
        "action": "added",
        "chars": added.chars,
    }


def test_curator_creates_memory_md_when_missing(tmp_path):
    result = _curator(tmp_path).add_memory_entry("Decisions", "delta")

    assert result.action == "added"
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "## Decisions\n\n- delta\n"


def test_replace_and_remove_need_an_existing_file(tmp_path):
    curator = _curator(tmp_path)

    with pytest.raises(CurationError, match="MEMORY.md does not exist"):
        curator.replace_memory_entry("a", "b")
    with pytest.raises(CurationError, match="MEMORY.md does not exist"):
        curator.remove_memory_entry("a")
    assert not (tmp_path / "MEMORY.md").exists()


def test_curator_refuses_symlinks_and_never_writes_through_them(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("## My Notes\n- gamma\n", encoding="utf-8")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").symlink_to(outside)

    with pytest.raises(CurationError, match="symlink"):
        _curator(root).add_memory_entry("My Notes", "delta")
    assert outside.read_text(encoding="utf-8") == "## My Notes\n- gamma\n"
    assert (root / "MEMORY.md").is_symlink()


def test_curator_refuses_hard_links_directories_aliases_and_bad_utf8(tmp_path):
    (tmp_path / "MEMORY.md").mkdir()
    with pytest.raises(CurationError, match="not a regular file"):
        _curator(tmp_path).add_memory_entry("My Notes", "delta")
    (tmp_path / "MEMORY.md").rmdir()

    original = tmp_path / "other.md"
    original.write_text("- gamma\n", encoding="utf-8")
    os.link(original, tmp_path / "MEMORY.md")
    with pytest.raises(CurationError, match="hard link"):
        _curator(tmp_path).add_memory_entry("My Notes", "delta")
    (tmp_path / "MEMORY.md").unlink()

    (tmp_path / "memory.md").write_text("- gamma\n", encoding="utf-8")
    with pytest.raises(CurationError, match="has memory.md instead of MEMORY.md"):
        _curator(tmp_path).add_memory_entry("My Notes", "delta")
    (tmp_path / "memory.md").unlink()

    (tmp_path / "MEMORY.md").write_bytes(b"- gamma \xff\n")
    with pytest.raises(CurationError, match="not valid UTF-8"):
        _curator(tmp_path).add_memory_entry("My Notes", "delta")
    assert (tmp_path / "MEMORY.md").read_bytes() == b"- gamma \xff\n"


def test_curator_refuses_files_outside_the_root_in_policy_or_layout(tmp_path):
    escaping = WorkspaceLayout(
        name="escaping",
        load_order=("AGENTS.md", "../MEMORY.md"),
        render_priorities=(),
        dynamic_files=frozenset(),
        required_files=(),
        optional_files=(),
        profile_files=(),
        subagent_files=frozenset(),
        cron_files=frozenset(),
        memory_file="../MEMORY.md",
    )

    with pytest.raises(ValueError, match="plain names"):
        MemoryCurator(tmp_path, layout=escaping)
    with pytest.raises(ValueError, match="does not provide"):
        MemoryCurator(tmp_path, policy=CurationPolicy(allowed_files={ADD_MEMORY_ENTRY: {"USER.md"}}))
    with pytest.raises(ValueError, match="unknown curation operations"):
        CurationPolicy(allowed_files={"write": {"MEMORY.md"}})
    with pytest.raises(ValueError, match="collections of file names"):
        CurationPolicy(allowed_files={ADD_MEMORY_ENTRY: "MEMORY.md"})


def test_growing_writes_respect_the_file_cap_but_shrinking_writes_pass(tmp_path):
    content = "## My Notes\n- gamma\n- delta\n"
    _write_memory(tmp_path, content)
    curator = _curator(tmp_path, policy=CurationPolicy.for_layout(file_caps={"MEMORY.md": 20}))

    with pytest.raises(CurationError, match="MEMORY.md would be 37 chars, over its 20-char cap"):
        curator.add_memory_entry("My Notes", "epsilon")
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == content
    # The file starts over its cap (27 > 20); shrinking writes always pass.
    assert curator.remove_memory_entry("gamma").action == "removed"
    assert curator.remove_memory_entry("delta").action == "removed"


def test_growing_writes_respect_the_bootstrap_per_file_limit(tmp_path):
    _write_memory(tmp_path, "## My Notes\n- " + "x" * 90 + "\n")
    curator = _curator(tmp_path, policy=CurationPolicy.for_layout(max_file_chars=110))

    with pytest.raises(CurationError, match="over the 110-char context limit per file"):
        curator.add_memory_entry("My Notes", "y" * 10)
    assert curator.add_memory_entry("My Notes", "y").action == "added"


def test_growing_writes_respect_the_bootstrap_total_budget(tmp_path):
    for name in DEFAULT_WORKSPACE_LAYOUT.load_order:
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("a" * 150, encoding="utf-8")
    _write_memory(tmp_path, "## My Notes\n- gamma\n")
    # AGENTS 150 + seven 1-char files leave 94 chars (>= the 64-char floor) for MEMORY.md.
    policy = CurationPolicy.for_layout(max_file_chars=1_000, total_max_chars=157 + 94)
    curator = _curator(tmp_path, policy=policy)

    assert curator.add_memory_entry("My Notes", "delta").action == "added"
    with pytest.raises(CurationError, match="push MEMORY.md past the 251-char workspace"):
        curator.add_memory_entry("My Notes", "e" * 80)
    (tmp_path / "SOUL.md").write_text("s" * 60, encoding="utf-8")
    # MEMORY.md no longer fits at all: shrinking still passes, growing does not.
    assert curator.remove_memory_entry("delta").action == "removed"
    with pytest.raises(CurationError, match="workspace context budget"):
        curator.add_memory_entry("My Notes", "delta")


def test_flag_off_offers_nothing_and_calls_raise_without_side_effects(tmp_path):
    path = _write_memory(tmp_path)
    calls = []
    curator = _curator(
        tmp_path, flags=FeatureFlags(curated_memory_writes=False), after_write=calls.append
    )

    assert curator.available_operations() == ()
    for call in (
        lambda: curator.add_memory_entry("My Notes", "delta"),
        lambda: curator.replace_memory_entry("gamma", "delta"),
        lambda: curator.remove_memory_entry("gamma"),
    ):
        with pytest.raises(CurationUnavailableError, match="disabled"):
            call()
    assert path.read_text(encoding="utf-8") == MEMORY_WITH_PROMOTIONS
    assert calls == []
    assert FeatureFlags().curated_memory_writes is True


def test_memory_flush_runs_never_curate(tmp_path):
    path = _write_memory(tmp_path)
    curator = _curator(tmp_path)

    assert curator.available_operations(memory_flush=True) == ()
    with pytest.raises(CurationUnavailableError, match="memory flush"):
        curator.add_memory_entry("My Notes", "delta", memory_flush=True)
    assert path.read_text(encoding="utf-8") == MEMORY_WITH_PROMOTIONS


def test_policy_can_withdraw_operations(tmp_path):
    _write_memory(tmp_path)
    curator = _curator(tmp_path, policy=CurationPolicy.for_layout().without(ADD_MEMORY_ENTRY))

    assert curator.available_operations() == (REPLACE_MEMORY_ENTRY, REMOVE_MEMORY_ENTRY)
    with pytest.raises(CurationUnavailableError, match="may not write MEMORY.md"):
        curator.add_memory_entry("My Notes", "delta")
    assert _curator(tmp_path).available_operations() == CURATION_OPERATIONS


def test_pin_layout_allows_memory_entries(tmp_path):
    curator = _curator(tmp_path, layout=OPENCLAW_PIN_LAYOUT)

    assert curator.available_operations() == CURATION_OPERATIONS


def test_a_concurrent_change_aborts_the_write(tmp_path, monkeypatch):
    path = _write_memory(tmp_path)
    curator = _curator(tmp_path)
    reads = []
    original_read = MemoryCurator._read_target

    def racing_read(self, name):
        reads.append(name)
        if len(reads) == 2:
            path.write_text(MEMORY_WITH_PROMOTIONS + "- promoted meanwhile\n", encoding="utf-8")
        return original_read(self, name)

    monkeypatch.setattr(MemoryCurator, "_read_target", racing_read)
    with pytest.raises(CurationConflictError, match="changed during the write"):
        curator.add_memory_entry("My Notes", "delta")
    assert path.read_text(encoding="utf-8").endswith("- promoted meanwhile\n")
    assert sorted(os.listdir(tmp_path)) == ["MEMORY.md"]
