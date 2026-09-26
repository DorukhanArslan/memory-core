"""Offline checks of the memory-budget.ts port; the oracle fixture compares it with the pin."""

from memory_core.memory_budget import (
    DEFAULT_MEMORY_FILE_MAX_CHARS,
    MemoryBlock,
    compact_memory_for_budget,
    parse_memory_blocks,
)


def _promotion_section(date: str, size_chars: int) -> str:
    # memory-budget.test.ts promotionSection helper.
    heading = f"## Promoted From Short-Term Memory ({date})\n"
    return heading + "x" * max(0, size_chars - len(heading))


def test_parse_splits_at_level_two_headings_and_tags_promotion_sections():
    content = (
        "# Long-Term Memory\n\n"
        "## My Notes\n\nImportant user content I do not want dropped.\n"
        "## Promoted From Short-Term Memory (2026-04-10)\n- entry\n"
        "### Promoted From Short-Term Memory (2026-04-11)\n"
    )

    assert parse_memory_blocks(content) == [
        MemoryBlock("preserved", "# Long-Term Memory\n"),
        MemoryBlock("preserved", "## My Notes\n\nImportant user content I do not want dropped."),
        MemoryBlock(
            "promotion",
            "## Promoted From Short-Term Memory (2026-04-10)\n- entry\n"
            "### Promoted From Short-Term Memory (2026-04-11)\n",
            "2026-04-10",
        ),
    ]
    assert parse_memory_blocks("") == []


def test_parse_ignores_near_miss_promotion_headings():
    for heading in (
        "## Promoted From Short-Term Memory ()",
        "## promoted from short-term memory (2026-04-10)",
        "##Promoted From Short-Term Memory (2026-04-10)",
    ):
        assert [block.kind for block in parse_memory_blocks(f"{heading}\n- entry\n")] == [
            "preserved"
        ]
    trailing = parse_memory_blocks("## Promoted From Short-Term Memory (2026-04-10) \t\r\n- a")
    assert trailing == [
        MemoryBlock("promotion", "## Promoted From Short-Term Memory (2026-04-10) \t\n- a", "2026-04-10")
    ]


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
    existing = "## Promoted From Short-Term Memory (2026-04-10)\n" + "\U0001f600" * 10
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
