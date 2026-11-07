"""Full-owner lifecycle fixture guards; authenticated native runs are separate."""
from copy import deepcopy
import json

from equivalence.index_lifecycle import build_index_lifecycle_cases, run_index_lifecycle


def _case(suffix):
    return next(case for case in build_index_lifecycle_cases() if case["id"] == f"lifecycle-{suffix}")


def _snapshot(result, label):
    return next(snapshot for snapshot in result["snapshots"] if snapshot["label"] == label)


def test_lifecycle_fixtures_are_deterministic_and_keep_explicit_normalization_scope():
    cases = build_index_lifecycle_cases()
    assert cases == build_index_lifecycle_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["operation"] == "index-lifecycle-runtime" and case["normalizationPolicy"]
               for case in cases)
    assert all(set(case["covers"]) == {
        "indexing.incremental-sync.outcomes", "indexing.incremental-sync.boundaries",
    } for case in cases)


def test_refresh_retains_unchanged_rows_and_reopens_the_persisted_generation(tmp_path):
    case = _case("memory-create-update-rename-delete-reopen")
    before = deepcopy(case)
    result = run_index_lifecycle(case["input"], evidence_directory=tmp_path)
    assert case == before
    assert all(snapshot["error"] is None for snapshot in result["snapshots"])
    initial = _snapshot(result, "initial")["state"]
    unchanged = _snapshot(result, "unchanged")["state"]
    assert {row["text"] for row in initial["chunks"]} == {"Alpha durable note.", "Use short replies."}
    assert all(row["identityRetained"] and row["updatedAt"] == "retained" for row in unchanged["chunks"])
    reopened = _snapshot(result, "reopened-unchanged")["state"]
    assert all(row["identityRetained"] and row["updatedAt"] == "retained" for row in reopened["chunks"])
    deleted = _snapshot(result, "deleted")["state"]
    assert [row["path"] for row in deleted["sources"]] == ["USER.md"]
    assert len(deleted["chunks"]) == len(deleted["fts"]) == len(deleted["provenance"]) == 1
    assert (tmp_path / "python-raw.json").is_file()


def test_content_fingerprint_detects_change_at_fixed_size_and_mtime():
    result = run_index_lifecycle(_case("same-size-time-content-change")["input"])
    initial = _snapshot(result, "initial")["state"]["sources"][0]
    changed = _snapshot(result, "same-size-new-content")["state"]["sources"][0]
    assert initial["mtime"] == changed["mtime"]
    assert initial["size"] == changed["size"]
    assert initial["hash"] != changed["hash"] and changed["hashRetained"] is False


def test_real_chunk_trigger_failure_retains_published_rows_and_retry_publishes_new_rows():
    result = run_index_lifecycle(_case("chunk-write-failure-retains-published-state")["input"])
    failed = _snapshot(result, "failed-change")
    assert failed["error"] == {"kind": "injected-chunk-write-failure"}
    assert [row["text"] for row in failed["state"]["chunks"]] == ["Alpha published note."]
    assert all(row["identityRetained"] and row["updatedAt"] == "retained" for row in failed["state"]["chunks"])
    retry = _snapshot(result, "retry")
    assert retry["error"] is None
    assert [row["text"] for row in retry["state"]["chunks"]] == ["Beta replacement note."]
    assert retry["state"]["sources"][0]["hashRetained"] is False


def test_empty_sources_have_paths_without_invented_chunks():
    result = run_index_lifecycle(_case("empty-and-whitespace-sources")["input"])
    first = result["snapshots"][0]["state"]
    assert len(first["sources"]) == len(first["paths"]) == 3
    assert len(first["chunks"]) == len(first["fts"]) == 1
    emptied = _snapshot(result, "emptied")["state"]
    assert emptied["chunks"] == emptied["fts"] == emptied["details"] == []
    assert len(emptied["sources"]) == len(emptied["paths"]) == 3


def test_host_session_projection_preserves_source_coordinates_and_trust_across_refreshes():
    result = run_index_lifecycle(_case("session-create-append-delete-reopen")["input"])
    initial = _snapshot(result, "initial")["state"]
    session, = [row for row in initial["chunks"] if row["source"] == "sessions"]
    assert session["path"] == "sessions/main/session-a.jsonl"
    assert (session["startLine"], session["endLine"]) == (2, 2)
    assert session["provenance"] == {
        "originClass": "untrusted", "sessionKind": "interactive",
        "observedAt": 1_700_000_000_000, "supersedesKey": None,
    }
    appended = _snapshot(result, "session-appended")["state"]
    session, = [row for row in appended["chunks"] if row["source"] == "sessions"]
    assert (session["startLine"], session["endLine"]) == (2, 3)
    assert session["provenance"]["observedAt"] == 1_700_000_001_000
    source, = [row for row in appended["sources"] if row["source"] == "sessions"]
    assert source["mtime"] == 1_700_000_000_000
    assert source["size"] == {"empty": False, "retained": False, "direction": 1}
    renamed = _snapshot(result, "session-renamed")["state"]
    transferred, = [row for row in renamed["chunks"] if row["source"] == "sessions"]
    assert transferred["path"] == "sessions/main/session-renamed.jsonl"
    assert transferred["text"] == session["text"]
    assert transferred["provenance"] == session["provenance"]
    assert all("session-a" not in row["path"] for row in renamed["sources"] + renamed["fts"])
    deleted = _snapshot(result, "session-deleted")["state"]
    assert all("session-renamed" not in row["path"] for row in deleted["sources"] + deleted["chunks"] + deleted["fts"])
    assert len(deleted["chunks"]) == len(deleted["provenance"]) == len(deleted["recall"]) == 2
