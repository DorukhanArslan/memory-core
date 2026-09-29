"""The ``## Memory Recall`` section, offline, with the texts the tag's builder returns.

The literals are the outputs of the real ``buildMemoryPromptSection``
(``extensions/memory-core/src/memory-tool-contract.ts`` at v2026.9.6) through the runner op
``memoryPromptSection``; tests/integration/test_openclaw_ts_oracle.py compares all 32 tool-set
and citation combinations against the TypeScript itself.
"""

import pytest

from memory_core.prompt_section import build_prompt_section

SEARCH = (
    "Before answering anything about prior work, decisions, dates, people, preferences, or todos: "
    "run memory_search. If low confidence after search, say you checked."
)
SEARCH_AND_GET = (
    "Before answering anything about prior work, decisions, dates, people, preferences, or todos: "
    "run memory_search; for memory-file hits, use memory_get to pull only the needed lines. If low "
    "confidence after search, say you checked."
)
GET_ONLY = (
    "Before answering anything about prior work, decisions, dates, people, preferences, or todos "
    "that point to a specific memory file: run memory_get to pull only the needed lines. If low "
    "confidence after reading, say you checked."
)
SNIPPETS_ONLY = (
    "Session hits are search snippets only; exact session history is unavailable with the enabled "
    "tools."
)
LINE_NUMBERS = (
    "Session search line numbers are not history offsets. Never read raw transcript files to "
    "expand session hits."
)
OUTCOME = (
    "Report partial, unavailable, or stale recall to the user, including returned warning and "
    "action guidance."
)
CITATIONS_ON = "Citations: include Source: <path#line> when it helps the user verify memory snippets."
CITATIONS_OFF = (
    "Citations are disabled: do not mention file paths or line numbers in replies unless the user "
    "explicitly asks."
)


def test_prompt_section_with_both_memory_tools_and_no_session_tools():
    # The host kit's case: memory-core offers no sessions_* tool.
    assert build_prompt_section({"memory_search", "memory_get"}, citations_mode="on") == [
        "## Memory Recall",
        SEARCH_AND_GET,
        SNIPPETS_ONLY,
        LINE_NUMBERS,
        OUTCOME,
        CITATIONS_ON,
        "",
    ]


def test_prompt_section_omits_when_no_memory_tools():
    assert build_prompt_section(set(), citations_mode="on") == []
    assert build_prompt_section({"sessions_search", "read"}, citations_mode="on") == []


def test_prompt_section_with_search_only_and_citations_off():
    assert build_prompt_section({"memory_search"}, citations_mode="off") == [
        "## Memory Recall",
        SEARCH,
        SNIPPETS_ONLY,
        LINE_NUMBERS,
        OUTCOME,
        CITATIONS_OFF,
        "",
    ]


def test_prompt_section_with_get_only_has_no_session_lines():
    assert build_prompt_section({"memory_get", "sessions_search"}, citations_mode="on") == [
        "## Memory Recall",
        GET_ONLY,
        OUTCOME,
        CITATIONS_ON,
        "",
    ]


@pytest.mark.parametrize(
    ("session_tools", "session_line"),
    [
        (
            {"sessions_search"},
            "For session hits, use sessions_search with distinctive snippet text (and sessionKey "
            "set to the transcript ID when known); exact session history is unavailable with the "
            "enabled tools.",
        ),
        (
            {"sessions_history"},
            "For session hits, use sessions_history with a known session key or transcript ID and "
            "a small limit; paginate its returned history metadata to locate the excerpt.",
        ),
        (
            {"sessions_search", "sessions_history"},
            "For session hits, use sessions_search with distinctive snippet text (and sessionKey "
            "set to the transcript ID when known), then sessions_history with the returned "
            "sessionKey, messageId, and sessionId for a bounded sanitized excerpt.",
        ),
    ],
)
def test_prompt_section_names_the_offered_session_tools(session_tools, session_line):
    assert build_prompt_section({"memory_search", *session_tools}, citations_mode="on") == [
        "## Memory Recall",
        SEARCH,
        session_line,
        LINE_NUMBERS,
        OUTCOME,
        CITATIONS_ON,
        "",
    ]


def test_prompt_section_rejects_invalid_citations_mode():
    # Upstream prints the "on" line for any mode but "off"; memory-core has no "auto" mode.
    with pytest.raises(ValueError):
        build_prompt_section({"memory_search"}, citations_mode="auto")
