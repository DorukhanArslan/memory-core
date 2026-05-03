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
