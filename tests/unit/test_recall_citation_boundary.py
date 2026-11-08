"""Only raw recalled evidence, without display citations, enters dreaming."""

from copy import deepcopy

import pytest

from memory_core.consolidation.recall import undecorate_search_results
from memory_core.tools.citations import build_memory_search_presentation


def _row():
    return {
        "path": "memory/2026-09-25.md", "startLine": 3, "endLine": 5,
        "source": "memory", "score": 0.75, "snippet": "- A saved fact.",
        "provenance": {"originClass": "owner", "observedAt": 123},
        "sessionOrigin": {"agentId": "main", "sessionId": "session-1"},
        "projectKey": "leaf",
    }


def test_real_search_presentation_is_removed_before_recall_without_losing_metadata():
    row = _row()
    presented = build_memory_search_presentation([row], True)
    snapshot = deepcopy(presented)
    assert presented[0]["citation"] == "memory/2026-09-25.md#L3-L5"
    assert undecorate_search_results(presented) == [{**presented[0], "snippet": row["snippet"]}]
    assert presented == snapshot


@pytest.mark.parametrize("legacy_label", [False, True])
def test_undecoration_supports_plain_and_legacy_source_prefixed_citation_labels(legacy_label):
    path = "memory/2026-09-25.md#L3-L5"
    row = {**_row(), "citation": f"Source: {path}" if legacy_label else path,
           "snippet": f"- A saved fact.\n\nSource: {path}"}
    original = deepcopy(row)
    result = undecorate_search_results([row])
    assert result == [{**row, "snippet": "- A saved fact."}]
    assert row == original
    assert result[0] is not row


@pytest.mark.parametrize(
    "overrides",
    [
        {"citation": "memory/other.md#L3-L5", "snippet": "fact\n\nSource: memory/a.md#L3-L5"},
        {"citation": "memory/a.md#L3-L5", "snippet": "fact\n\nSource: memory/a.md#L3-L5\nmore"},
        {"snippet": "fact\n\nSource: memory/a.md#L3-L5"},
        {"citation": None, "snippet": "fact\n\nSource: memory/a.md#L3-L5"},
    ],
)
def test_nonmatching_or_nonterminal_source_text_is_not_removed(overrides):
    row = {**_row(), **overrides}
    assert undecorate_search_results([row]) == [row]


def test_citation_off_keeps_the_full_raw_snippet():
    raw = {**_row(), "snippet": "- A saved fact.\n\n"}
    presented = build_memory_search_presentation([raw], False)
    assert undecorate_search_results(presented) == [{**raw, "corpus": "memory"}]
