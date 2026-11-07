"""Offline fixture guards; native equivalence requires the real source runner."""
from copy import deepcopy
import json

from equivalence.incremental_index import build_incremental_index_cases, run_incremental_index


def test_source_snapshot_cases_are_deterministic_and_do_not_claim_full_sync():
    cases = build_incremental_index_cases()
    assert cases == build_incremental_index_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["requirement"] == "indexing.incremental-sync" and case["covers"] == []
               for case in cases)


def test_source_snapshot_inputs_keep_raw_newline_and_encoding_boundaries():
    names = {case["id"] for case in build_incremental_index_cases()}
    assert {
        "source-snapshot-crlf", "source-snapshot-bare-cr",
        "source-snapshot-invalid-single-bytes", "source-snapshot-invalid-truncated-sequence",
        "source-snapshot-invalid-surrogate-encoding", "source-snapshot-all-byte-values",
        "source-snapshot-content-changes-with-fixed-size-and-time",
        "source-snapshot-newline-changes-with-fixed-size-and-time",
        "source-snapshot-invalid-bytes-same-decoded-content", "source-snapshot-rename-and-delete",
        "source-snapshot-regular-to-directory-to-missing", "source-snapshot-symlink-and-hardlink-leaves",
    } <= names


def test_source_snapshot_adapters_preserve_inputs_and_serialize_results():
    for case in build_incremental_index_cases():
        before = deepcopy(case)
        result = run_incremental_index(case["input"])
        json.dumps(result, allow_nan=False)
        assert case == before
