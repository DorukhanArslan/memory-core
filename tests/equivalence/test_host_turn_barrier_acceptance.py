"""Registration/credit attack tests; synthetic rows are not native evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases as build_catalog
from equivalence.harness import HarnessError, _host_turn_barrier_family_complete, _validate_scope
from equivalence.host_turn_barrier import (
    CASE_HASHES, MANIFEST, OPERATION, POINTS, REQUIREMENT, build_cases, validate_case, validate_registration,
)


ROOT = Path(__file__).resolve().parents[2]
BOUNDARY = "host.turn-barrier.boundaries"
# Independently computed from committed main 5da6169's original case builder.
PRIOR_CATALOG_SHA256 = "4d4c073876804b5dadf19a496eb45f72732eb82682acdcd14791a218d9b980f7"


def _scope():
    return json.loads((ROOT / "equivalence/scope.json").read_text())


def _matched_rows():
    """Abstract admission states only; these rows never impersonate a capture."""
    return [{**case, "status": "matched", "runtimeEvidenceValidated": True} for case in build_cases()]


def test_catalog_adds_exactly_the_four_frozen_outcomes_without_changing_prior_1411_literals():
    catalog = build_catalog()
    family = [case for case in catalog if case["operation"] == OPERATION]
    assert family == build_cases()
    assert len(family) == len(CASE_HASHES) == 4
    prior = [case for case in catalog if case["operation"] != OPERATION]
    wire = json.dumps(prior, ensure_ascii=True, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode()
    assert len(prior) == 1411
    assert hashlib.sha256(wire).hexdigest() == PRIOR_CATALOG_SHA256
    validate_registration(catalog)


def test_only_original_outcome_is_claimed_and_original_boundary_remains_in_scope():
    requirement = next(row for row in _scope()["requirements"] if row["id"] == REQUIREMENT)
    assert [point["id"] for point in requirement["acceptance"]] == [*POINTS, BOUNDARY]
    assert POINTS == ("host.turn-barrier.outcomes",)
    assert all(case["covers"] == list(POINTS) for case in build_cases())
    assert not any(BOUNDARY in case["covers"] for case in build_catalog())


def test_warm_cases_include_a_real_nonempty_seed_and_natural_positive_recall_control():
    cases = build_cases()
    assert {case["input"]["initialState"] for case in cases} == {"cold", "warm"}
    assert sum(case["input"]["initialState"] == "warm" for case in cases) == 2
    for case in cases:
        value = case["input"]
        assert value["followupTrigger"]["interveningHostActions"] == []
        assert value["policy"]["optionalMaintenancePreemption"] == "unclaimed"
        if value["initialState"] == "warm":
            warmup = value["warmup"]
            query = warmup["recall"]["search"]["query"]
            assert query in warmup["save"]["content"]
            assert query in value["save"]["content"]
            assert value["followup"]["search"]["query"] not in warmup["save"]["content"]
            assert warmup["publication"] == "only-natural-tool-and-search-behavior"
            assert warmup["interveningHostActions"] == []
        else:
            assert "warmup" not in value


@pytest.mark.parametrize("index", range(4))
def test_one_missing_frozen_literal_is_rejected_before_any_execution(index):
    cases = build_cases()
    del cases[index]
    with pytest.raises(HarnessError, match="complete four-case family atomically"):
        _validate_scope(_scope(), cases)


@pytest.mark.parametrize("claim", [[], [BOUNDARY], [*POINTS, BOUNDARY]])
def test_frozen_literal_cannot_drop_outcome_or_claim_maintenance_boundaries(claim):
    cases = build_cases()
    cases[0]["covers"] = claim
    with pytest.raises(ValueError):
        validate_registration(cases)


def test_foreign_operation_cannot_borrow_the_outcome_claim():
    foreign = {"id": "foreign-outcome-shortcut", "operation": "tokenization", "requirement": REQUIREMENT,
               "covers": list(POINTS), "input": {"text": "tea"}}
    with pytest.raises(ValueError):
        validate_registration([*build_cases(), foreign])
    assert _host_turn_barrier_family_complete([*_matched_rows(),
        {**foreign, "status": "matched", "runtimeEvidenceValidated": True}]) is False


def test_foreign_operation_cannot_turn_the_unverified_boundary_into_generic_credit():
    foreign = {"id": "foreign-boundary-shortcut", "operation": "tokenization", "requirement": REQUIREMENT,
               "covers": [BOUNDARY], "input": {"text": "tea"}}
    with pytest.raises(HarnessError):
        _validate_scope(_scope(), [*build_cases(), foreign])


def test_all_four_exact_validated_matches_admit_the_outcome():
    assert _host_turn_barrier_family_complete(_matched_rows()) is True
    assert _host_turn_barrier_family_complete(list(reversed(_matched_rows()))) is True


def test_empty_and_duplicated_rows_never_admit_the_outcome():
    assert _host_turn_barrier_family_complete([]) is False
    rows = _matched_rows()
    rows.append(deepcopy(rows[0]))
    assert _host_turn_barrier_family_complete(rows) is False


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["missing", "mismatched", "blocked", "unverified", "no-marker", "integer-marker", "text-marker"])
def test_one_missing_mismatch_or_unverified_marker_withholds_whole_outcome(index, failure):
    rows = _matched_rows()
    if failure == "missing":
        del rows[index]
    elif failure == "unverified":
        rows[index]["runtimeEvidenceValidated"] = False
    elif failure == "no-marker":
        del rows[index]["runtimeEvidenceValidated"]
    elif failure == "integer-marker":
        rows[index]["runtimeEvidenceValidated"] = 1
    elif failure == "text-marker":
        rows[index]["runtimeEvidenceValidated"] = "true"
    else:
        rows[index]["status"] = failure
    assert _host_turn_barrier_family_complete(rows) is False


@pytest.mark.parametrize("change", ["id", "operation", "requirement", "query", "clock", "manual-barrier", "covers"])
def test_matching_status_does_not_accept_substituted_literals_or_scripted_publication(change):
    rows = _matched_rows()
    if change in {"id", "operation", "requirement"}:
        rows[0][change] += "-different"
    elif change == "query":
        rows[0]["input"]["followup"]["search"]["query"] = "only-the-old-fact"
    elif change == "clock":
        rows[0]["input"]["nowMs"] += 1
    elif change == "manual-barrier":
        rows[0]["input"]["followupTrigger"]["interveningHostActions"] = ["synchronize"]
    else:
        rows[0]["covers"] = [*POINTS, BOUNDARY]
    assert _host_turn_barrier_family_complete(rows) is False


def test_other_host_families_remain_independent_of_the_new_outcome():
    from equivalence.harness import _host_update_isolation_family_complete
    from equivalence.host_update_isolation import build_cases as update_cases

    update = [{**case, "status": "matched", "runtimeEvidenceValidated": True} for case in update_cases()]
    assert _host_turn_barrier_family_complete(update) is False
    assert _host_update_isolation_family_complete(_matched_rows()) is False
    assert _host_turn_barrier_family_complete(update + _matched_rows()) is True
    assert _host_update_isolation_family_complete(update + _matched_rows()) is True


@pytest.mark.parametrize("change", ["extra-key", "kind", "self-credit", "reordered", "missing", "duplicate", "changed-input", "expected-result"])
def test_only_exact_input_only_manifest_is_admitted(tmp_path, change):
    manifest = json.loads(MANIFEST.read_text())
    if change == "extra-key":
        manifest["expected"] = {}
    elif change == "kind":
        manifest["kind"] = "host-update-isolation-acceptance-literals"
    elif change == "self-credit":
        manifest["acceptancePointsAwarded"] = 1
    elif change == "reordered":
        manifest["cases"].reverse()
    elif change == "missing":
        manifest["cases"].pop()
    elif change == "duplicate":
        manifest["cases"].append(deepcopy(manifest["cases"][0]))
    elif change == "changed-input":
        manifest["cases"][0]["input"]["followup"]["search"]["query"] += "-substituted"
    else:
        manifest["cases"][0]["expected"] = {"ready": True}
    altered = tmp_path / "literals.json"
    altered.write_text(json.dumps(manifest, ensure_ascii=False))
    with pytest.raises(ValueError):
        build_cases(altered)


def test_validated_input_is_detached_and_cannot_rewrite_a_frozen_builder_result():
    original = build_cases()[0]
    validated = validate_case(original)
    validated["input"]["followupTrigger"]["interveningHostActions"].append("reindex")
    assert original == build_cases()[0]
    assert set(original) == {"id", "operation", "requirement", "covers", "input"}
