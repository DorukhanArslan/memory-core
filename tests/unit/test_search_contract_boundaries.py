"""Boundary regressions for the pinned native memory-search tool helpers."""

from copy import deepcopy

import pytest

from memory_core.supplements import (
    RegisteredMemoryCorpusSupplement,
    StaticMemoryCorpusSupplement,
)
from memory_core.tools.citations import (
    build_memory_search_presentation,
    resolve_memory_citations_mode,
    should_include_citations,
)
from memory_core.tools.common import (
    MemoryToolError,
    MemoryToolInputError,
    read_corpus_param,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.tools.corpus import (
    CorpusAttempt,
    compose_memory_corpus_metadata,
    settle_supplements,
)


@pytest.mark.parametrize("blank", ["", " \t\r\n", "\ufeff", "\u00a0\u2028\u2029"])
def test_blank_finite_number_defaults_without_using_the_snake_alias(blank):
    assert read_finite_number_param({"minScore": blank, "min_score": 0.9}, "minScore") is None
    assert read_finite_number_param({"min_score": blank}, "minScore") is None


@pytest.mark.parametrize("invalid", ["\u0085", "\x1c", "\u200b", "NaN", "0x10", [], True])
def test_non_ecmascript_blank_and_invalid_numbers_preserve_native_input_error(invalid):
    with pytest.raises(MemoryToolInputError) as raised:
        read_finite_number_param({"minScore": invalid}, "minScore")
    assert raised.value.name == "ToolInputError"
    assert raised.value.status == 400
    assert raised.value.message == "minScore must be a finite number"


def test_optional_reader_error_text_uses_nullish_defaults():
    with pytest.raises(MemoryToolInputError) as string_error:
        read_string_param({}, "query", required=True, label="")
    assert string_error.value.message == " required"
    for reader, key in (
        (read_positive_integer_param, "maxResults"),
        (read_finite_number_param, "minScore"),
    ):
        with pytest.raises(MemoryToolInputError) as number_error:
            reader({key: "bad"}, key, message="")
        assert number_error.value.message == ""


@pytest.mark.parametrize("raw", [None, "", " \ufeff ", 7, True, ["wiki"]])
def test_non_string_and_blank_corpus_remains_omitted(raw):
    assert read_corpus_param({"corpus": raw}, ("memory", "wiki", "all", "sessions")) is None


def test_corpus_trims_but_does_not_fold_or_widen_invalid_values():
    allowed = ("memory", "wiki", "all", "sessions")
    assert read_corpus_param({"corpus": "\ufeff wiki \n"}, allowed) == "wiki"
    with pytest.raises(MemoryToolError) as raised:
        read_corpus_param({"corpus": "Wiki"}, allowed)
    assert raised.value.message == "corpus must be one of: memory, wiki, all, sessions"
    assert raised.value.name == "Error"
    assert not isinstance(raised.value, MemoryToolInputError)
    assert not hasattr(raised.value, "status")


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("on", "on"), ("off", "off"), ("auto", "auto"), ("ON", "auto"),
     (" on ", "auto"), (None, "auto"), (True, "auto"), ({}, "auto")],
)
def test_citations_mode_accepts_only_the_configured_literal(configured, expected):
    assert resolve_memory_citations_mode(configured) == expected


@pytest.mark.parametrize(
    ("session_key", "include"),
    [
        (None, True),
        ("", True),
        ("agent:main:main", True),
        ("agent:main:telegram:direct:group-of-friends", True),
        (" Agent:MAIN:Discord:GROUP:ABC \ufeff", False),
        ("agent:main:slack:channel:C123", False),
        ("agent:main:matrix:channel:!AbCd:Server", False),
        ("agent:main:signal:group:OpaqueID", False),
        ("agent:main:agent:child:matrix:group:!AbCd:Server:thread:EVENT", False),
        ("agent:main:x:group:peer:channel", False),
        ("telegram:group:peer", True),
        ("agent:main", True),
        ("agent::group:peer", True),
        ("agent:main::group:peer", True),
        ("agent:main: group :peer", True),
        ("agent:main: \tgroup", False),
    ],
)
def test_auto_citations_follow_the_parsed_agent_session_rest(session_key, include):
    assert should_include_citations("auto", session_key) is include
    assert should_include_citations("on", session_key) is True
    assert should_include_citations("off", session_key) is False


def _memory_row():
    return {
        "path": "memory/世界.md",
        "startLine": 4,
        "endLine": 6,
        "score": 0.75,
        "source": "sessions",
        "corpus": "stale-input-corpus",
        "citation": "stale-input-citation",
        "snippet": "🌱 text <!-- project: leaf -->\n<!-- ordinary comment -->\nmore\ufeff\n",
        "id": "provider-row-id",
        "metadata": {"recordedOrigin": "host", "tags": ["one", "two"]},
        "optionalFlag": None,
    }


def test_citation_presentation_preserves_the_entire_row_without_mutation_or_clamping():
    row = _memory_row()
    original = deepcopy(row)
    assert build_memory_search_presentation([row], True) == [{
        **row,
        "corpus": "sessions",
        "citation": "memory/世界.md#L4-L6",
        "snippet": "🌱 text\n<!-- ordinary comment -->\nmore\n\nSource: memory/世界.md#L4-L6",
    }]
    assert row == original


def test_citation_off_removes_input_citation_without_trimming_or_dropping_fields():
    row = _memory_row()
    expected = {**row, "corpus": "sessions"}
    expected.pop("citation")
    expected["snippet"] = "🌱 text\n<!-- ordinary comment -->\nmore\ufeff\n"
    assert build_memory_search_presentation([row], False) == [expected]


def test_citation_rows_keep_duplicate_values_and_use_single_line_labels():
    row = {**_memory_row(), "endLine": 4, "snippet": "a" * 5000 + "\u0085"}
    presented = build_memory_search_presentation([row, dict(row)], True)
    assert len(presented) == 2
    assert presented[0] == presented[1]
    assert presented[0]["citation"] == "memory/世界.md#L4"
    assert presented[0]["snippet"] == "a" * 5000 + "\u0085\n\nSource: memory/世界.md#L4"
    assert "truncated" not in presented[0]
    assert "originalChars" not in presented[0]


class _Supplement:
    def __init__(self, label, calls, error=None):
        self.label, self.calls, self.error = label, calls, error

    def search(self, *, query, max_results, corpus):
        self.calls.append((self.label, query, max_results, corpus))
        if self.error is not None:
            raise RuntimeError(self.error)
        return [{"path": self.label, "score": 1.0, "snippet": self.label, "source": "wiki"}]

    def get(self, *, path, corpus):
        self.calls.append((self.label, path, corpus))
        return {"path": path, "content": self.label}


def _search_supplements(supplements):
    return settle_supplements(
        supplements,
        lambda supplement: supplement.search(query="leaf", max_results=4, corpus="wiki"),
        lambda completed: [row for result in completed for row in result],
    )


def test_registered_supplements_use_plugin_identity_order_and_multiple_failure_labels():
    calls = []
    supplements = [
        RegisteredMemoryCorpusSupplement("zeta", _Supplement("z", calls, "z failed")),
        RegisteredMemoryCorpusSupplement("middle", _Supplement("m", calls)),
        RegisteredMemoryCorpusSupplement("alpha", _Supplement("a", calls, "a failed")),
    ]
    attempt = _search_supplements(supplements)
    assert calls == [(label, "leaf", 4, "wiki") for label in ("a", "m", "z")]
    assert attempt == CorpusAttempt(
        corpus="wiki", outcome="unavailable",
        value=[{"path": "m", "score": 1.0, "snippet": "m", "source": "wiki"}],
        error="alpha: a failed; zeta: z failed",
    )
    assert [entry.plugin_id for entry in supplements] == ["zeta", "middle", "alpha"]


def test_one_registered_failure_has_no_plugin_prefix_and_successes_remain():
    calls = []
    attempt = _search_supplements([
        RegisteredMemoryCorpusSupplement("zeta", _Supplement("z", calls)),
        RegisteredMemoryCorpusSupplement("alpha", _Supplement("a", calls, "failed")),
    ])
    assert attempt.error == "failed"
    assert attempt.deadline is False
    assert attempt.value == [{"path": "z", "score": 1.0, "snippet": "z", "source": "wiki"}]


def test_anonymous_supplements_keep_legacy_positions_and_do_not_gain_plugin_labels():
    calls = []
    attempt = _search_supplements([
        _Supplement("z", calls, "z failed"),
        _Supplement("a", calls, "a failed"),
    ])
    assert [call[0] for call in calls] == ["z", "a"]
    assert attempt.error == "z failed; a failed"


def test_mixed_registration_sorts_only_the_existing_registered_slots():
    calls = []
    _search_supplements([
        RegisteredMemoryCorpusSupplement("zeta", _Supplement("z", calls)),
        _Supplement("anonymous", calls),
        RegisteredMemoryCorpusSupplement("alpha", _Supplement("a", calls)),
    ])
    assert [call[0] for call in calls] == ["a", "anonymous", "z"]


def test_registered_wrapper_forwards_get_without_changing_anonymous_protocol():
    calls = []
    wrapper = RegisteredMemoryCorpusSupplement("actual-plugin", _Supplement("label", calls))
    assert wrapper.get(path="entry.md", corpus="wiki") == {"path": "entry.md", "content": "label"}
    assert calls == [("label", "entry.md", "wiki")]


def test_corpus_metadata_preserves_order_failures_and_extra_warning_placement():
    metadata = compose_memory_corpus_metadata([
        CorpusAttempt(corpus="wiki", outcome="unavailable", error="alpha: down; zeta: broken"),
        CorpusAttempt(corpus="memory", outcome="partial", error="partial memory", deadline=True),
    ], ["Index is warming.", "Some provenance is unavailable."])
    assert metadata == {
        "corpora": [
            {"corpus": "memory", "outcome": "partial", "error": "partial memory"},
            {"corpus": "wiki", "outcome": "unavailable", "error": "alpha: down; zeta: broken"},
        ],
        "warning": "Memory corpus partial: partial memory "
                   "Wiki corpus unavailable: alpha: down; zeta: broken "
                   "Index is warming. Some provenance is unavailable.",
        "error": "partial memory; alpha: down; zeta: broken",
        "timedOut": True,
        "timeoutMs": 30_000,
    }


def test_missing_supplement_warning_only_when_wiki_is_the_only_requested_corpus():
    wiki = _search_supplements([])
    assert wiki == CorpusAttempt(corpus="wiki", outcome="not-registered")
    assert compose_memory_corpus_metadata([wiki]) == {
        "corpora": [{"corpus": "wiki", "outcome": "not-registered"}],
        "warning": "Wiki corpus is not registered; results do not cover that requested corpus.",
    }
    assert compose_memory_corpus_metadata([wiki, CorpusAttempt(corpus="memory", outcome="ok")]) == {
        "corpora": [{"corpus": "memory", "outcome": "ok"},
                    {"corpus": "wiki", "outcome": "not-registered"}],
    }


def test_registered_static_supplement_remains_a_usable_search_and_get_provider():
    row = {"corpus": "wiki", "path": "wiki.md", "score": 0.5, "snippet": "leaf"}
    supplement = RegisteredMemoryCorpusSupplement("wiki-provider", StaticMemoryCorpusSupplement([row]))
    assert _search_supplements([supplement]).value == [row]
    assert supplement.get(path="wiki.md", corpus="wiki") == row
