import pytest

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


def test_prompt_section_with_search_only_matches_upstream_shape():
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


def test_prompt_section_with_get_only_matches_upstream_shape():
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


def test_prompt_section_with_citations_off_matches_upstream_shape():
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
