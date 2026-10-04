"""Offline checks of the memory-budget.ts port; the oracle fixture compares it with the pin."""

from memory_core.memory_budget import (
    DEFAULT_MEMORY_FILE_MAX_CHARS,
    MemoryBlock,
    compact_memory_for_budget,
    parse_memory_blocks,
)


def _promotion_section(date: str, size_chars: int) -> str:
    # A generated section (heading, marker, one bullet): v2026.9.6 only drops blocks of that shape.
    head = f"## Promoted From Short-Term Memory ({date})\n<!-- openclaw-memory-promotion:k-{date} -->\n- "
    return head + "x" * max(0, size_chars - len(head))


_MARKER = "<!-- openclaw-memory-promotion:k -->"


def test_parse_splits_at_atx_headings_and_tags_generated_promotion_sections():
    content = (
        "# Long-Term Memory\n\n"
        "## My Notes\n\nImportant user content I do not want dropped.\n"
        f"## Promoted From Short-Term Memory (2026-04-10)\n{_MARKER}\n- entry\n"
        "### Another heading\n"
    )

    blocks = parse_memory_blocks(content)

    assert [(b.kind, b.date, b.entry_count) for b in blocks] == [
        ("preserved", None, 0),
        ("preserved", None, 0),
        ("promotion", "2026-04-10", 1),
        ("preserved", None, 0),
    ]
    assert blocks[0] == MemoryBlock("preserved", "# Long-Term Memory\n")
    assert parse_memory_blocks("") == []


def test_a_promotion_heading_over_mixed_content_is_preserved():
    # Only a body of marker + bullet pairs is generated; anything else may be the user's.
    mixed = f"## Promoted From Short-Term Memory (2026-04-10)\n{_MARKER}\n- entry\nMy own line.\n"
    plain = "## Promoted From Short-Term Memory (2026-04-10)\n- entry\n"

    assert [b.kind for b in parse_memory_blocks(mixed)] == ["preserved"]
    assert [b.kind for b in parse_memory_blocks(plain)] == ["preserved"]


def test_a_generated_section_keeps_its_project_subsections():
    content = (
        "## Promoted From Short-Term Memory (2026-04-10)\n\n### Global\n\n"
        f"{_MARKER}\n- a\n\n### Project: github.com/o/r\n\n{_MARKER}\n- b\n"
    )

    blocks = parse_memory_blocks(content)

    assert [(b.kind, b.entry_count) for b in blocks] == [("promotion", 2)]


def test_parse_ignores_near_miss_promotion_headings():
    for heading in (
        "## Promoted From Short-Term Memory ()",
        "## promoted from short-term memory (2026-04-10)",
        "##Promoted From Short-Term Memory (2026-04-10)",
    ):
        assert [block.kind for block in parse_memory_blocks(f"{heading}\n{_MARKER}\n- entry\n")] == [
            "preserved"
        ]
    trailing = parse_memory_blocks(
        f"## Promoted From Short-Term Memory (2026-04-10) \t\r\n{_MARKER}\n- a"
    )
    assert trailing == [
        MemoryBlock(
            "promotion",
            f"## Promoted From Short-Term Memory (2026-04-10) \t\n{_MARKER}\n- a",
            "2026-04-10",
            1,
        )
    ]


def test_loss_fraction_bounds_how_many_generated_entries_a_write_may_drop():
    existing = f"{_promotion_section('2026-04-10', 400)}\n{_promotion_section('2026-04-20', 400)}"
    kwargs = {
        "existing_memory": existing,
        "new_section": "\n" + _promotion_section("2026-04-29", 400),
        "budget_chars": 900,
    }

    bounded = compact_memory_for_budget(**kwargs, max_prior_entry_loss_fraction=0.25)
    unbounded = compact_memory_for_budget(**kwargs, max_prior_entry_loss_fraction=1)

    assert bounded.dropped_dates == () and bounded.compacted == existing
    assert unbounded.dropped_dates == ("2026-04-10",)


def test_compaction_keeps_memory_that_fits():
    existing = "# Long-Term Memory\n\nSome content.\n"
    new_section = "\n## Promoted From Short-Term Memory (2026-04-29)\n- entry\n"

    result = compact_memory_for_budget(
        existing_memory=existing, new_section=new_section, budget_chars=1_000
    )

    assert result.compacted == existing
    assert result.dropped_dates == ()


def test_compaction_drops_oldest_dates_first_and_keeps_user_sections():
    existing = (
        f"{_promotion_section('2026-04-10', 400)}\n"
        "## My Reflections\nMy own notes.\n\n"
        f"{_promotion_section('2026-04-20', 400)}"
    )

    result = compact_memory_for_budget(
        existing_memory=existing,
        new_section=f"\n{_promotion_section('2026-04-29', 400)}",
        budget_chars=900,
    )

    assert result.dropped_dates == ("2026-04-10",)
    assert "## My Reflections\nMy own notes." in result.compacted
    assert "(2026-04-20)" in result.compacted


def test_compaction_counts_utf16_units():
    # 48-char heading + 10 emoji: 58 code points but 68 UTF-16 units (String.length).
    existing = f"## Promoted From Short-Term Memory (2026-04-10)\n{_MARKER}\n- " + "\U0001f600" * 10
    code_point_fit = len(existing) + 21

    over = compact_memory_for_budget(
        existing_memory=existing, new_section="", budget_chars=code_point_fit
    )
    fits = compact_memory_for_budget(
        existing_memory=existing, new_section="", budget_chars=code_point_fit + 10
    )

    assert over.dropped_dates == ("2026-04-10",)
    assert over.compacted == ""
    assert fits.dropped_dates == ()
    assert fits.compacted == existing


def test_default_budget_is_upstream_value():
    assert DEFAULT_MEMORY_FILE_MAX_CHARS == 10_000
