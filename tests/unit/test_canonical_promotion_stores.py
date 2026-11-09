"""Canonical promotion views retain source facts without rewriting extension state."""
from copy import deepcopy
import json

import pytest

from memory_core.consolidation.store import (
    read_canonical_phase_signal_store,
    read_canonical_recall_store,
    read_phase_signal_store,
    read_recall_store,
)
from memory_core.consolidation.store_normalization import (
    normalize_short_term_phase_signal_store,
    normalize_short_term_recall_store,
)


NOW = 1775210460000
STAMP = "2026-04-03T10:01:00.000Z"


def _entry(**values):
    return {"path": "memory/2026-04-01.md", "startLine": 1, "endLine": 2,
            "source": "memory", "snippet": "Cedar tea is preferred.", "recallCount": 3,
            "dailyCount": 0, "groundedCount": 0, "totalScore": 2.25, "maxScore": .75,
            "firstRecalledAt": "2026-04-01T10:00:00.000Z", "lastRecalledAt": STAMP,
            "queryHashes": ["a", "b", "c"], "userQueryHashes": ["a", "b", "c"],
            "recallDays": ["2026-04-01", "2026-04-02", "2026-04-03"],
            "conceptTags": ["cedar", "tea"], **values}


def _store(**entries):
    return {"version": 1, "updatedAt": STAMP, "entries": entries}


def test_object_provenance_keeps_typed_defaults_and_complete_canonical_fields():
    value = _store(owner=_entry(provenance={"originClass": "owner"}))
    original = deepcopy(value)
    actual = normalize_short_term_recall_store(value, NOW)
    assert actual == _store(owner={"key": "owner", **_entry(), "provenance": {
        "originClass": "owner", "sessionKind": "unknown", "observedAt": NOW}})
    assert value == original


@pytest.mark.parametrize("origin", [None, "OWNER", "not-an-origin", 7, ["owner"], {}])
def test_invalid_object_origin_stays_untrusted_with_invalid_kind_and_timestamp_fallback(origin):
    value = _store(tainted=_entry(lastRecalledAt="invalid", provenance={
        "originClass": origin, "sessionKind": "not-a-kind", "observedAt": True, "supersedesKey": " old ",
    }))
    result = normalize_short_term_recall_store(value, NOW)["entries"]["tainted"]
    assert result["provenance"] == {"originClass": "untrusted", "sessionKind": "unknown",
                                    "observedAt": NOW, "supersedesKey": "old"}


@pytest.mark.parametrize("provenance", [False, 1, "owner", []])
def test_explicit_malformed_provenance_fails_closed_instead_of_becoming_origin_free(provenance):
    result = normalize_short_term_recall_store(_store(tainted=_entry(provenance=provenance)), NOW)
    assert result["entries"]["tainted"]["provenance"]["originClass"] == "untrusted"


def test_valid_provenance_preserves_observation_and_omits_blank_supersedes():
    result = normalize_short_term_recall_store(_store(known=_entry(provenance={
        "originClass": "agent", "sessionKind": "cron", "observedAt": -1.5, "supersedesKey": " \ufeff",
    })), NOW)
    assert result["entries"]["known"]["provenance"] == {
        "originClass": "agent", "sessionKind": "cron", "observedAt": -1.5}


def test_canonical_read_drops_raw_daily_transcript_but_retains_exact_session_corpus():
    value = _store(daily=_entry(snippet=" User: Cedar tea. "), corpus=_entry(
        path="memory/.dreams/session-corpus/2026-04-01.md", snippet=" User: Cedar tea. "),
        suffix=_entry(path="memory/.dreams/session-corpus/2026-04-01.md.extra", snippet="User: Cedar tea."))
    result = normalize_short_term_recall_store(value, NOW)
    assert list(result["entries"]) == ["corpus"]
    assert result["entries"]["corpus"]["snippet"] == "User: Cedar tea."


def test_normalized_snippets_paths_lists_and_projects_keep_source_omission_semantics():
    value = _store(known=_entry(path="./memory\\2026-04-01.md", snippet="  Cedar\n\ufeff tea.  ",
        queryHashes=[" a ", "a", None, "b", ""], userQueryHashes=[],
        conceptTags=[" CEDAR ", "cedar", 5, "TEA"], recallDays=[None, " 2026-04-01T10:00Z", "invalid"],
        claimHash=" abc ", projectKey="GITHUB.com/Owner/Repo; github.com/Owner/Repo; path:/Case; bad<key", promotedAt=""))
    result = normalize_short_term_recall_store(value, NOW)["entries"]["known"]
    assert result["path"] == "memory/2026-04-01.md" and result["snippet"] == "Cedar tea."
    assert result["queryHashes"] == ["a", "b"] and result["userQueryHashes"] == []
    assert result["conceptTags"] == ["cedar", "tea"] and result["recallDays"] == ["2026-04-01"]
    assert result["claimHash"] == "abc" and result["projectKey"] == "github.com/Owner/Repo; path:/Case"
    assert "promotedAt" not in result and "provenance" not in result


def test_legacy_diversity_is_preserved_only_for_unambiguous_recall_rows():
    ordinary, mixed = _entry(), _entry(dailyCount=1)
    del ordinary["userQueryHashes"], mixed["userQueryHashes"]
    result = normalize_short_term_recall_store(_store(ordinary=ordinary, mixed=mixed), NOW)["entries"]
    assert result["ordinary"]["userQueryHashes"] == ["a", "b", "c"]
    assert "userQueryHashes" not in result["mixed"]


def test_numeric_source_fields_use_json_javascript_coercion_and_invalid_rows_are_dropped():
    value = _store(valid=_entry(startLine=None, endLine="0x10", recallCount="3.9", dailyCount=-4,
        groundedCount=True, maxScore="8", totalScore="2.5"), invalid=_entry(startLine="1.1"),
        other=_entry(source="sessions"), missing={"path": "memory/a.md", "source": "memory"})
    result = normalize_short_term_recall_store(value, NOW)["entries"]
    assert list(result) == ["valid"]
    assert {name: result["valid"][name] for name in (
        "startLine", "endLine", "recallCount", "dailyCount", "groundedCount", "maxScore", "totalScore"
    )} == {"startLine": 0, "endLine": 16, "recallCount": 3, "dailyCount": 0, "groundedCount": 1,
           "maxScore": 1, "totalScore": 2.5}


def test_utf16_snippet_cap_does_not_split_a_pair_and_input_remains_unchanged():
    value = _store(long=_entry(snippet="x" * 799 + "😀extra"))
    original = deepcopy(value)
    result = normalize_short_term_recall_store(value, NOW)
    assert result["entries"]["long"]["snippet"] == "x" * 799
    assert value == original


def test_old_phase_signals_survive_for_the_actual_exponential_boost_and_have_no_null_fields():
    value = _store(old={"key": "old", "lightHits": 3, "remHits": 2,
        "lastLightAt": "2026-02-01T10:01:00.000Z", "lastRemAt": "2026-02-01T10:01:00.000Z"})
    assert normalize_short_term_phase_signal_store(value, NOW) == value


def test_phase_counts_zero_rows_key_alias_and_considered_timestamp_are_canonical():
    value = _store(map_key={"key": " real ", "lightHits": "3.9", "remHits": -1,
        "lastLightAt": " 2026-01-01 ", "lastRemAt": None, "lastRemConsideredAt": " considered ", "updatedAt": None},
        zero={"lightHits": "Infinity", "remHits": False})
    assert normalize_short_term_phase_signal_store(value, NOW) == _store(real={
        "key": "real", "lightHits": 3, "remHits": 0, "lastLightAt": "2026-01-01", "lastRemConsideredAt": "considered"})


def test_canonical_and_legacy_readers_keep_distinct_views_and_never_rewrite_bytes(tmp_path):
    recall = tmp_path / "recall.json"
    value = _store(raw=_entry(snippet="Cedar\npreference.", provenance={"originClass": "owner"}))
    recall.write_text(json.dumps(value))
    before = recall.read_bytes()
    assert read_canonical_recall_store(recall, NOW)["entries"]["raw"]["snippet"] == "Cedar preference."
    assert read_recall_store(recall, NOW) == value
    assert recall.read_bytes() == before
    phase = tmp_path / "phase.json"
    old = _store(old={"key": "old", "lightHits": 3, "remHits": 2, "lastLightAt": "2026-02-01"})
    phase.write_text(json.dumps(old))
    before = phase.read_bytes()
    assert "old" in read_canonical_phase_signal_store(phase, NOW)["entries"]
    assert read_phase_signal_store(phase, NOW)["entries"] == {}
    assert phase.read_bytes() == before


@pytest.mark.parametrize("reader", [read_canonical_recall_store, read_canonical_phase_signal_store])
def test_missing_or_invalid_json_is_empty_and_permission_errors_are_not_hidden(tmp_path, reader):
    path = tmp_path / "state.json"
    assert reader(path, NOW) == _store()
    path.write_text("{invalid")
    assert reader(path, NOW) == _store()
    # A real OS error, rather than a mocked JSON loader, remains visible.
    with pytest.raises(IsADirectoryError):
        reader(tmp_path, NOW)


def test_read_retention_is_in_memory_and_leaves_the_entire_extension_store_intact(tmp_path):
    path = tmp_path / "recall.json"
    value = _store(**{f"row-{index:03}": _entry(recallCount=index) for index in range(513)})
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    canonical = read_canonical_recall_store(path, NOW)
    assert len(canonical["entries"]) == 512 and "row-000" not in canonical["entries"]
    assert read_recall_store(path, NOW) == value and path.read_bytes() == before
