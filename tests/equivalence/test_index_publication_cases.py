"""Prepared publication fixture guards; real native evidence runs separately."""
from copy import deepcopy
import json

from equivalence.index_publication import build_index_publication_cases, run_index_publication


def _case(name):
    return next(case for case in build_index_publication_cases() if case["id"] == f"publication-{name}")


def test_publication_fixtures_are_deterministic_and_standard_json():
    cases = build_index_publication_cases()
    assert cases == build_index_publication_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["operation"] == "index-publication"
               and case["requirement"] == "indexing.transaction-publication" for case in cases)
    assert all(set(case["covers"]) == {"indexing.transaction-publication.outcomes",
                                      "indexing.transaction-publication.boundaries"}
               for case in cases)
    assert all(case["normalizationPolicy"] for case in cases)


def test_publication_fixtures_retain_all_prepared_metadata_and_empty_sources():
    revision = _case("success")["input"]["replacement"]
    assert any(not source["size"] for source in revision["sources"])
    assert {chunk["provenance"]["originClass"] for chunk in revision["chunks"]} == {
        "owner", "untrusted", "system",
    }
    assert any(chunk["provenance"]["supersedesKey"] for chunk in revision["chunks"])
    assert any(chunk["recall"]["triggers"] for chunk in revision["chunks"])
    assert any(chunk["recall"]["projectKey"] for chunk in revision["chunks"])
    assert all({"embedding", "hash", "model", "updatedAt"} <= chunk.keys()
               for chunk in revision["chunks"])


def test_independent_and_held_readers_observe_coherent_old_or_new_revisions():
    case = _case("reader-snapshot")
    before = deepcopy(case)
    result = run_index_publication(case["input"])
    assert case == before
    assert result["error"] is None
    assert result["before"] != result["after"] == result["reopened"]
    assert result["heldAfter"] == result["before"]
    assert [event["phase"] for event in result["events"]] == ["begin", "commit"]
    for event in result["events"]:
        assert event["reader"] == event["heldReader"] == result["before"]
    assert result["events"][0]["writer"] == result["before"]
    assert result["events"][1]["writer"] == result["after"]
    assert result["after"]["bodyMatches"]["alpha"] == []
    assert result["after"]["bodyMatches"]["beta"] == ["new-memory", "new-session"]
    assert result["after"]["pathMatches"]["empty"] == [["memory/empty.md", "memory"]]
    assert result["revisionAdvanced"] is True


def test_commit_failure_retains_every_old_table_and_live_cache():
    result = run_index_publication(_case("commit-failure-reader-snapshot")["input"])
    assert result["error"] == {"kind": "injected-failure", "stage": "commit"}
    assert result["before"] == result["after"] == result["reopened"] == result["heldAfter"]
    assert result["events"][-1]["writer"] != result["after"]
    assert result["revisionAdvanced"] is False
    assert result["cache"] == [["fixture-provider", "fixture-model", "fixture-key", "retained",
                                "000000000000D03F", 1, 1]]
    assert result["attachments"] == ["main"]
    assert result["attachmentReleased"] is True


def test_stale_revision_cannot_publish_a_replacement():
    result = run_index_publication(_case("stale-revision")["input"])
    assert result["error"] == {"kind": "revision-conflict"}
    assert result["before"] == result["after"] == result["reopened"]
    assert result["revisionAdvanced"] is False


def test_orphan_rows_are_visible_and_are_not_lost_from_rollback_observations():
    result = run_index_publication(_case("orphan-metadata-rollback")["input"])
    assert any(row["chunkId"] == "orphan" for row in result["before"]["recall"])
    assert any(row["chunkId"] == "orphan" for row in result["before"]["provenance"])
    assert result["before"] == result["after"] == result["reopened"]
    replaced = run_index_publication(_case("orphan-metadata-replacement")["input"])
    assert all(row["chunkId"] != "orphan" for row in replaced["after"]["recall"])
    assert all(row["chunkId"] != "orphan" for row in replaced["after"]["provenance"])


def test_failure_after_commit_does_not_invent_a_rollback():
    result = run_index_publication(_case("post-commit-failure")["input"])
    assert result["error"] == {"kind": "post-commit-failure"}
    assert result["before"] != result["after"] == result["reopened"]
    assert result["heldAfter"] == result["before"]
    assert result["revisionAdvanced"] is True
