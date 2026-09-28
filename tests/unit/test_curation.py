"""Curated MEMORY.md writes (memory-core extension): text edits, safety and flag behaviour."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from memory_core.bootstrap import (
    DEFAULT_WORKSPACE_LAYOUT,
    OPENCLAW_COMPAT_LAYOUT,
    WorkspaceLayout,
    initialize_agent_workspace,
    is_workspace_setup_completed,
)
from memory_core.curation import (
    ADD_MEMORY_ENTRY,
    APPEND_DAILY_NOTE,
    CURATION_OPERATIONS,
    SET_PROACTIVE_PREFERENCES,
    UPSERT_USER_DIRECTIVE,
    CurationConflictError,
    CurationError,
    CurationPolicy,
    CurationUnavailableError,
    MemoryCurator,
    UserDirective,
    add_memory_entry_text,
    parse_user_directives,
    proactive_preferences_text,
    remove_memory_entry_text,
    replace_memory_entry_text,
    upsert_user_directive_text,
)
from memory_core.flags import FeatureFlags
from memory_core.memory_budget import parse_memory_blocks

# Promotion blocks in the format the promotion pipeline writes under the compat identity
# (short-term-promotion.ts:2322-2335; memory_core/consolidation/promotion.py
# _build_promotion_section with OPENCLAW_COMPAT_RUNTIME_IDENTITY).
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
        ("My Notes", "<!-- Memory-Core-Memory-Promotion:x --> y", "memory promotion marker"),
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
    neutral = "## My Notes\n<!--memory-core-memory-promotion:k -->\n- gamma\n"
    with pytest.raises(CurationError, match="promotion"):
        remove_memory_entry_text(neutral, "<!--memory-core-memory-promotion:k -->")
    with pytest.raises(CurationError, match="promotion"):
        add_memory_entry_text(neutral, "<!-- memory-core-memory-promotion:k -->", "delta")
    assert remove_memory_entry_text(neutral, "gamma") == (
        "## My Notes\n<!--memory-core-memory-promotion:k -->\n"
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
    fields = dict(
        name="escaping",
        load_order=("AGENTS.md", "MEMORY.md"),
        render_priorities=(),
        required_files=(),
        optional_files=(),
        generated_files=(),
        profile_files=(),
        subagent_files=frozenset(),
        cron_files=frozenset(),
        skip_absent_files=frozenset(),
        expected_absent_files=frozenset(),
    )
    # WorkspaceLayout itself rejects non-basename entries ...
    with pytest.raises(ValueError, match="plain basenames"):
        WorkspaceLayout(**{**fields, "load_order": ("AGENTS.md", "../MEMORY.md")})
    # ... and the curator keeps its own check for a layout that bypassed it.
    escaping = WorkspaceLayout(**fields)
    object.__setattr__(escaping, "load_order", ("AGENTS.md", "../MEMORY.md"))
    object.__setattr__(escaping, "memory_file", "../MEMORY.md")

    with pytest.raises(ValueError, match="plain names"):
        MemoryCurator(tmp_path, layout=escaping)
    with pytest.raises(ValueError, match="does not provide") as missing_file:
        MemoryCurator(tmp_path, policy=CurationPolicy(allowed_files={ADD_MEMORY_ENTRY: {"USER.md"}}))
    # host-visible text never carries the layout's internal name
    assert DEFAULT_WORKSPACE_LAYOUT.name not in str(missing_file.value)
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
        lambda: curator.upsert_user_directive("Prefer alpha.", observed="2026-09-26"),
        lambda: curator.set_proactive_preferences("alpha"),
        lambda: curator.append_daily_note("alpha", date="2026-09-26"),
    ):
        with pytest.raises(CurationUnavailableError, match="disabled"):
            call()
    assert path.read_text(encoding="utf-8") == MEMORY_WITH_PROMOTIONS
    assert sorted(os.listdir(tmp_path)) == ["MEMORY.md"]
    assert calls == []
    assert FeatureFlags().curated_memory_writes is True


def test_memory_flush_runs_never_curate(tmp_path):
    path = _write_memory(tmp_path)
    curator = _curator(tmp_path)

    assert curator.available_operations(memory_flush=True) == ()
    for call in (
        lambda: curator.add_memory_entry("My Notes", "delta", memory_flush=True),
        lambda: curator.upsert_user_directive("Prefer alpha.", memory_flush=True),
        lambda: curator.set_proactive_preferences("alpha", memory_flush=True),
        lambda: curator.append_daily_note("alpha", memory_flush=True),
    ):
        with pytest.raises(CurationUnavailableError, match="memory flush"):
            call()
    assert path.read_text(encoding="utf-8") == MEMORY_WITH_PROMOTIONS
    assert sorted(os.listdir(tmp_path)) == ["MEMORY.md"]


def test_policy_can_withdraw_operations(tmp_path):
    _write_memory(tmp_path)
    curator = _curator(tmp_path, policy=CurationPolicy.for_layout().without(ADD_MEMORY_ENTRY))

    assert curator.available_operations() == tuple(
        op for op in CURATION_OPERATIONS if op != ADD_MEMORY_ENTRY
    )
    with pytest.raises(CurationUnavailableError, match="may not write MEMORY.md"):
        curator.add_memory_entry("My Notes", "delta")
    assert _curator(tmp_path).available_operations() == CURATION_OPERATIONS


def test_compat_layout_offers_everything_but_proactive_preferences(tmp_path):
    curator = _curator(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT)

    assert curator.available_operations() == tuple(
        op for op in CURATION_OPERATIONS if op != SET_PROACTIVE_PREFERENCES
    )
    with pytest.raises(CurationUnavailableError, match="may not write PROACTIVE_PREFERENCES.md"):
        curator.set_proactive_preferences("alpha")
    assert not (tmp_path / "PROACTIVE_PREFERENCES.md").exists()


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


# --- USER.md directives ----------------------------------------------------------

USER_MD = (
    "# USER.md\n"
    "\n"
    "## Directives\n"
    "\n"
    "<!-- observed: 2026-05-27 | status: active -->\n"
    "\n"
    "- Always alpha.\n"
    "\n"
    "<!-- observed: 2026-05-03 | status: active -->\n"
    "\n"
    "- Prefer beta. <!-- see MEMORY.md -->\n"
    "\n"
    "<!-- observed: 2026-05-26 | status: superseded -->\n"
    "\n"
    "- Never gamma.\n"
    "\n"
    "## Notes\n"
    "\n"
    "Free text stays.\n"
)


def test_parse_user_directives_reads_markers_and_bullets():
    assert parse_user_directives(USER_MD) == [
        UserDirective("2026-05-27", "active", "Always alpha.", 4, 6),
        UserDirective("2026-05-03", "active", "Prefer beta. <!-- see MEMORY.md -->", 8, 10),
        UserDirective("2026-05-26", "superseded", "Never gamma.", 12, 14),
    ]
    assert parse_user_directives("<!-- observed: 2026-05-27 | status: active -->\nno bullet\n") == []


def test_upsert_adds_after_the_last_directive():
    updated, action = upsert_user_directive_text(USER_MD, "Prefer delta.", observed="2026-09-26")

    assert action == "added"
    assert updated == USER_MD.replace(
        "- Never gamma.\n",
        "- Never gamma.\n\n<!-- observed: 2026-09-26 | status: active -->\n\n- Prefer delta.\n",
        1,
    )


def test_upsert_is_idempotent_for_an_active_directive():
    for text in ("Always alpha.", "- Always alpha.", "Prefer beta."):
        assert upsert_user_directive_text(USER_MD, text, observed="2026-09-26") == (
            USER_MD,
            "unchanged",
        )
    # A superseded directive is not active: stating it again records it anew.
    updated, action = upsert_user_directive_text(USER_MD, "Never gamma.", observed="2026-09-26")
    assert action == "added"
    assert updated.count("- Never gamma.") == 2


def test_supersede_keeps_the_old_entry_next_to_its_replacement():
    updated, action = upsert_user_directive_text(
        USER_MD, "Always alpha, briefly.", observed="2026-09-26", supersede="Always alpha."
    )

    assert action == "superseded"
    assert updated == USER_MD.replace(
        "<!-- observed: 2026-05-27 | status: active -->\n\n- Always alpha.\n",
        "<!-- observed: 2026-05-27 | status: superseded -->\n\n- Always alpha.\n"
        "\n<!-- observed: 2026-09-26 | status: active -->\n\n- Always alpha, briefly.\n",
        1,
    )
    directives = parse_user_directives(updated)
    assert [(item.text, item.status) for item in directives[:2]] == [
        ("Always alpha.", "superseded"),
        ("Always alpha, briefly.", "active"),
    ]
    assert directives[1].marker_line == directives[0].directive_line + 2


@pytest.mark.parametrize(
    ("text", "supersede", "message"),
    [
        ("Prefer delta.", "Prefer epsilon.", "no active directive in USER.md matches supersede"),
        ("Prefer delta.", "Never gamma.", "already superseded"),
        ("Always alpha.", "Always alpha.", "different directive"),
        ("Always alpha.", "Prefer beta.", "active directive with this text already exists"),
    ],
)
def test_supersede_errors(text, supersede, message):
    with pytest.raises(CurationError, match=message):
        upsert_user_directive_text(USER_MD, text, observed="2026-09-26", supersede=supersede)


def test_supersede_refuses_ambiguous_active_duplicates():
    doubled = USER_MD + "\n<!-- observed: 2026-06-01 | status: active -->\n\n- Always alpha.\n"

    with pytest.raises(CurationError, match="matches 2 active directives"):
        upsert_user_directive_text(
            doubled, "Always alpha, briefly.", observed="2026-09-26", supersede="Always alpha."
        )


def test_upsert_into_empty_or_directive_free_text_and_crlf():
    assert upsert_user_directive_text("", "Prefer delta.", observed="2026-09-26") == (
        "<!-- observed: 2026-09-26 | status: active -->\n\n- Prefer delta.\n",
        "added",
    )
    assert upsert_user_directive_text("# USER.md", "Prefer delta.", observed="2026-09-26")[0] == (
        "# USER.md\n\n<!-- observed: 2026-09-26 | status: active -->\n\n- Prefer delta.\n"
    )
    crlf = USER_MD.replace("\n", "\r\n")
    updated, _ = upsert_user_directive_text(
        crlf, "Always alpha, briefly.", observed="2026-09-26", supersede="Always alpha."
    )
    assert "\n" not in updated.replace("\r\n", "")
    assert updated.replace("\r\n", "\n") == upsert_user_directive_text(
        USER_MD, "Always alpha, briefly.", observed="2026-09-26", supersede="Always alpha."
    )[0]


@pytest.mark.parametrize("observed", ["2026-9-26", "2026-02-30", "yesterday", ""])
def test_upsert_rejects_bad_observed_dates(observed):
    with pytest.raises(CurationError, match="observed must be a YYYY-MM-DD date"):
        upsert_user_directive_text(USER_MD, "Prefer delta.", observed=observed)


def test_curator_upsert_uses_the_host_clock_and_timezone(tmp_path):
    # 2026-09-25 22:30 UTC is 2026-09-26 01:30 in Istanbul.
    curator = _curator(tmp_path, timezone="Europe/Istanbul", now_ms=lambda: 1790375400000)

    result = curator.upsert_user_directive("Prefer delta.")

    assert (result.path, result.action, result.changed) == ("USER.md", "added", True)
    assert (tmp_path / "USER.md").read_text(encoding="utf-8") == (
        "<!-- observed: 2026-09-26 | status: active -->\n\n- Prefer delta.\n"
    )
    assert _curator(tmp_path, now_ms=lambda: 1790375400000).today() == "2026-09-25"
    with pytest.raises(ValueError, match="unknown timezone"):
        _curator(tmp_path, timezone="Mars/Olympus")


def test_user_md_cap_refuses_growth_past_4000_chars(tmp_path):
    filler = "x" * (4_000 - len(USER_MD) - 10)
    content = USER_MD + filler + "\n"
    (tmp_path / "USER.md").write_text(content, encoding="utf-8")
    curator = _curator(tmp_path)

    with pytest.raises(CurationError, match=r"USER.md would be \d+ chars, over its 4000-char cap"):
        curator.upsert_user_directive("Prefer delta.", observed="2026-09-26")
    with pytest.raises(CurationError, match="4000-char cap"):
        curator.upsert_user_directive(
            "Always alpha, briefly.", observed="2026-09-26", supersede="Always alpha."
        )
    assert (tmp_path / "USER.md").read_text(encoding="utf-8") == content
    assert curator.upsert_user_directive("Always alpha.").action == "unchanged"


# --- PROACTIVE_PREFERENCES.md ------------------------------------------------------


def test_proactive_preferences_text_normalises_endings():
    assert proactive_preferences_text("alpha\r\nbeta  \n\n\n") == "alpha\nbeta\n"
    assert proactive_preferences_text("  \n") == ""
    with pytest.raises(CurationError, match="text required"):
        proactive_preferences_text(None)


def test_curator_sets_and_clears_proactive_preferences(tmp_path):
    curator = _curator(tmp_path)
    path = tmp_path / "PROACTIVE_PREFERENCES.md"

    assert curator.set_proactive_preferences("").action == "unchanged"
    assert not path.exists()
    assert curator.set_proactive_preferences("alpha\r\nbeta").action == "set"
    assert path.read_bytes() == b"alpha\nbeta\n"
    assert curator.set_proactive_preferences("alpha\nbeta\n").action == "unchanged"
    cleared = curator.set_proactive_preferences("")
    assert (cleared.action, cleared.chars) == ("cleared", 0)
    assert path.read_bytes() == b""


def test_proactive_preferences_are_bounded(tmp_path):
    bounded = _curator(tmp_path, policy=CurationPolicy.for_layout(max_file_chars=100))
    with pytest.raises(CurationError, match="over the 100-char context limit per file"):
        bounded.set_proactive_preferences("a" * 101)

    capped = CurationPolicy.for_layout(file_caps={"PROACTIVE_PREFERENCES.md": 10})
    assert dict(capped.file_caps) == {"USER.md": 4_000, "PROACTIVE_PREFERENCES.md": 10}
    with pytest.raises(CurationError, match="over its 10-char cap"):
        _curator(tmp_path, policy=capped).set_proactive_preferences("a" * 11)
    assert not (tmp_path / "PROACTIVE_PREFERENCES.md").exists()


# --- daily notes ----------------------------------------------------------------------


def test_daily_note_appends_through_the_canonical_append(tmp_path):
    results = []
    curator = _curator(
        tmp_path,
        timezone="Europe/Istanbul",
        now_ms=lambda: 1790375400000,
        after_write=results.append,
    )

    first = curator.append_daily_note("alpha\n")
    second = curator.append_daily_note("beta")

    assert (first.operation, first.path, first.action) == (
        APPEND_DAILY_NOTE,
        "memory/2026-09-26.md",
        "appended",
    )
    assert results == [first, second]
    assert (tmp_path / "memory" / "2026-09-26.md").read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert curator.append_daily_note("gamma", date="2026-09-25").path == "memory/2026-09-25.md"


def test_daily_note_skips_empty_text_and_the_exact_no_reply_token(tmp_path):
    curator = _curator(tmp_path, now_ms=lambda: 1790375400000)

    for text in ("", "  \n", "NO_REPLY", "  NO_REPLY\n"):
        result = curator.append_daily_note(text)
        assert (result.action, result.changed) == ("skipped", False)
    assert not (tmp_path / "memory").exists()
    # Only the exact token is silent (decision Q12): text that merely starts with it is kept.
    for text in ("NO_REPLY nothing to keep", "NO_REPLY_FACTS: tea"):
        assert curator.append_daily_note(text).action == "appended"
    assert (tmp_path / "memory" / "2026-09-25.md").read_text(encoding="utf-8") == (
        "NO_REPLY nothing to keep\nNO_REPLY_FACTS: tea\n"
    )
    with pytest.raises(CurationError, match="date must be a YYYY-MM-DD date"):
        curator.append_daily_note("alpha", date="../2026-09-26")


def test_daily_note_refuses_symlinks_and_hard_links(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "memory").symlink_to(outside, target_is_directory=True)
    curator = _curator(root, now_ms=lambda: 1790375400000)
    with pytest.raises(
        CurationError, match=r"^memory/ is a symlink; memory writes never follow symlinks$"
    ):
        curator.append_daily_note("alpha")
    (root / "memory").unlink()

    (root / "memory").mkdir()
    target = outside / "notes.md"
    target.write_text("", encoding="utf-8")
    (root / "memory" / "2026-09-25.md").symlink_to(target)
    with pytest.raises(
        CurationError,
        match=r"^memory/2026-09-25\.md is a symlink; memory writes never follow symlinks$",
    ):
        curator.append_daily_note("alpha")
    (root / "memory" / "2026-09-25.md").unlink()

    os.link(target, root / "memory" / "2026-09-25.md")
    with pytest.raises(CurationError, match="more than one hard link"):
        curator.append_daily_note("alpha")
    assert target.read_text(encoding="utf-8") == ""


def test_user_and_proactive_files_obey_the_same_file_safety(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("", encoding="utf-8")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "USER.md").symlink_to(outside)
    (root / "PROACTIVE_PREFERENCES.md").symlink_to(outside)
    curator = _curator(root)

    with pytest.raises(CurationError, match="symlink"):
        curator.upsert_user_directive("Prefer delta.", observed="2026-09-26")
    with pytest.raises(CurationError, match="symlink"):
        curator.set_proactive_preferences("alpha")
    assert outside.read_text(encoding="utf-8") == ""
    assert UPSERT_USER_DIRECTIVE in curator.available_operations()


def test_budget_check_skips_bootstrap_md_once_setup_is_complete(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("b" * 900, encoding="utf-8")
    _write_memory(tmp_path, "## My Notes\n- gamma\n")
    policy = CurationPolicy.for_layout(max_file_chars=1_000, total_max_chars=1_000)
    curator = _curator(tmp_path, policy=policy)
    with pytest.raises(CurationError, match="workspace context budget"):
        curator.add_memory_entry("My Notes", "d" * 150)

    initialize_agent_workspace(tmp_path, templates={})
    (tmp_path / "BOOTSTRAP.md").write_text("b" * 900, encoding="utf-8")
    assert is_workspace_setup_completed(tmp_path)
    assert curator.add_memory_entry("My Notes", "d" * 150).action == "added"


def test_parallel_curated_writes_to_one_file_lose_no_edit(tmp_path, monkeypatch):
    # Both calls hold os.replace until the other arrives (or 0.5 s pass). Without
    # a per-file lock both pass the re-read check first and the later replace
    # silently drops the earlier edit; with it the second call waits, rereads
    # the file and keeps both entries.
    import threading

    import memory_core.curation as curation_module

    (tmp_path / "MEMORY.md").write_text("# Long-Term Memory\n\n## Notes\n- base\n", encoding="utf-8")
    curator = MemoryCurator(tmp_path)
    barrier = threading.Barrier(2, timeout=0.5)
    real_replace = os.replace

    def replace_after_both_checked(src, dst):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        real_replace(src, dst)

    monkeypatch.setattr(curation_module.os, "replace", replace_after_both_checked)
    errors: list[BaseException] = []

    def add(text: str) -> None:
        try:
            curator.add_memory_entry("Notes", text)
        except BaseException as error:  # reported below
            errors.append(error)

    threads = [threading.Thread(target=add, args=(text,)) for text in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert errors == []
    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "- alpha\n" in content and "- beta\n" in content
