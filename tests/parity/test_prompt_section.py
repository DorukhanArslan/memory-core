import pytest

from memory_core.prompt_section import build_prompt_section

# v2026.9.6 extensions/memory-core/src/memory-tool-contract.ts buildMemoryPromptSection, with the
# tool lists it branches on; tests/integration compares every combination with the real builder.
_PRIOR = "prior work, decisions, dates, people, preferences, or todos"
_SEARCH = (
    f"Before answering anything about {_PRIOR}: run memory_search; for memory-file hits, use "
    "memory_get to pull only the needed lines. If low confidence after search, say you checked."
)
_OUTCOME = (
    "Report partial, unavailable, or stale recall to the user, including returned warning and "
    "action guidance."
)
_CITE_ON = "Citations: include Source: <path#line> when it helps the user verify memory snippets."
_CITE_OFF = (
    "Citations are disabled: do not mention file paths or line numbers in replies unless the "
    "user explicitly asks."
)
_NO_OFFSETS = (
    "Session search line numbers are not history offsets. Never read raw transcript files to "
    "expand session hits."
)
_SNIPPETS_ONLY = (
    "Session hits are search snippets only; exact session history is unavailable with the "
    "enabled tools."
)


def test_prompt_section_with_both_tools_matches_upstream_text():
    assert build_prompt_section({"memory_search", "memory_get"}, citations_mode="on") == [
        "## Memory Recall",
        _SEARCH,
        _SNIPPETS_ONLY,
        _NO_OFFSETS,
        _OUTCOME,
        _CITE_ON,
        "",
    ]


def test_prompt_section_omits_when_no_memory_tools():
    assert build_prompt_section(set(), citations_mode="on") == []
    assert build_prompt_section({"sessions_search"}, citations_mode="on") == []


def test_prompt_section_with_search_only_drops_the_memory_get_hint():
    lines = build_prompt_section({"memory_search"}, citations_mode="on")

    assert lines[1] == (
        f"Before answering anything about {_PRIOR}: run memory_search. If low confidence "
        "after search, say you checked."
    )


def test_prompt_section_with_get_only_has_no_session_guidance():
    assert build_prompt_section({"memory_get"}, citations_mode="on") == [
        "## Memory Recall",
        (
            f"Before answering anything about {_PRIOR} that point to a specific memory file: run "
            "memory_get to pull only the needed lines. If low confidence after reading, say you "
            "checked."
        ),
        _OUTCOME,
        _CITE_ON,
        "",
    ]


def test_prompt_section_points_session_hits_at_the_session_history_tools():
    both = build_prompt_section(
        {"memory_search", "sessions_search", "sessions_history"}, citations_mode="on"
    )
    search_only = build_prompt_section({"memory_search", "sessions_search"}, citations_mode="on")
    history_only = build_prompt_section({"memory_search", "sessions_history"}, citations_mode="on")

    assert both[2] == (
        "For session hits, use sessions_search with distinctive snippet text (and sessionKey set "
        "to the transcript ID when known), then sessions_history with the returned sessionKey, "
        "messageId, and sessionId for a bounded sanitized excerpt."
    )
    assert search_only[2].endswith(
        "when known); exact session history is unavailable with the enabled tools."
    )
    assert history_only[2].startswith("For session hits, use sessions_history with a known")


def test_prompt_section_with_citations_off_matches_upstream_text():
    assert build_prompt_section({"memory_search"}, citations_mode="off")[-2] == _CITE_OFF


def test_prompt_section_rejects_invalid_citations_mode():
    with pytest.raises(ValueError):
        build_prompt_section({"memory_search"}, citations_mode="invalid")
