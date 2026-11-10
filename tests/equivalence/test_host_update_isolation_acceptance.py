"""Whole-host update/isolation credit requires the exact complete authenticated family."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases as build_catalog
from equivalence.harness import HarnessError, _host_update_isolation_family_complete, _validate_scope
from equivalence.host_update_isolation import (
    CASE_HASHES, FAULTS, MANIFEST, OPERATION, POINTS, REQUIREMENT, build_cases, validate_case, validate_registration,
)
from equivalence.host_turn_barrier_boundaries import (
    OPERATION as BOUNDARY_OPERATION, build_cases as build_boundary_cases,
)
from equivalence.index_identity_boundaries import (
    OPERATION as IDENTITY_OPERATION, validate_registration as validate_identity_registration,
)
from equivalence.query_sync_outcomes import (
    OPERATION as QUERY_SYNC_OPERATION, build_cases as query_sync_cases,
    validate_registration as validate_query_sync_registration,
)


ROOT = Path(__file__).resolve().parents[2]


def test_catalog_registers_all_four_exact_hosts_for_both_existing_conditions():
    registered = build_catalog()
    validate_query_sync_registration(registered)
    assert registered[-len(query_sync_cases()):] == query_sync_cases()
    validate_identity_registration(registered)
    catalog = [case for case in registered if case["operation"] not in {IDENTITY_OPERATION, QUERY_SYNC_OPERATION}]
    assert registered[:len(catalog)] == catalog
    claims = [case for case in catalog if set(POINTS).intersection(case["covers"])]
    assert {case["id"] for case in claims} == set(CASE_HASHES)
    assert len(claims) == 4
    assert all(case["operation"] == OPERATION and case["requirement"] == REQUIREMENT
               and case["covers"] == list(POINTS) for case in claims)
    prior = [case for case in catalog if case["operation"] != BOUNDARY_OPERATION]
    assert len(prior) == 1415
    assert prior[-4:] == build_cases()
    assert catalog[:len(prior)] == prior
    assert catalog[len(prior):] == build_boundary_cases()
    validate_registration(catalog)


def test_fixed_scope_names_exactly_the_two_claimed_conditions():
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    requirement = next(item for item in scope["requirements"] if item["id"] == REQUIREMENT)
    assert [point["id"] for point in requirement["acceptance"]] == list(POINTS)


def test_family_declares_two_updates_one_real_refusal_and_one_real_publication_failure():
    faults = [case["input"]["phases"][1].get("fault", {}).get("operation") for case in build_cases()]
    assert faults == [None, None, *FAULTS]
    for case in build_cases():
        produce, update = case["input"]["phases"]
        assert produce["save"]["content"].count(update["update"]["old"]) == 1
        assert update["update"]["new"] not in produce["save"]["content"]
        assert update["update"]["old"] not in produce["isolatedSave"]["content"]
        identities = [value for key, value in case["input"]["identity"].items() if isinstance(value, dict)]
        assert len({item["sessionKey"] for item in identities}) == len(identities)
        assert ("stale" in case["input"]["identity"]) is (update.get("fault", {}).get("operation") == FAULTS[1])


def test_restart_family_remains_separate_and_is_not_widened():
    from equivalence.host_restart_session import CASE_HASHES as restart_hashes, build_cases as restart_cases

    restart = restart_cases()
    assert not set(restart_hashes).intersection(CASE_HASHES)
    assert all(case["operation"] != OPERATION and not set(POINTS).intersection(case["covers"]) for case in restart)
    validate_registration(restart)


@pytest.mark.parametrize("index", range(4))
def test_one_missing_case_fails_scope_before_any_execution(index):
    cases = build_cases()
    del cases[index]
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    with pytest.raises(HarnessError, match="complete four-case family atomically"):
        _validate_scope(scope, cases)


@pytest.mark.parametrize("field", ["id", "operation", "requirement", "input", "covers"])
def test_claim_cannot_replace_owner_input_or_either_condition(field):
    cases = build_cases()
    if field == "input":
        cases[0][field]["nowMs"] += 1
    elif field == "covers":
        cases[0][field] = list(POINTS[:1])
    else:
        cases[0][field] += "-different"
    with pytest.raises((KeyError, ValueError)):
        validate_registration(cases)


def test_empty_coverage_does_not_impersonate_one_registered_family_member():
    cases = build_cases()
    cases[0]["covers"] = []
    with pytest.raises(ValueError):
        validate_registration(cases)


def test_literal_registration_is_detached_and_has_no_expected_result():
    case = build_cases()[0]
    before = deepcopy(case)
    validated = validate_case(case)
    validated["input"]["nowMs"] += 1
    assert case == before
    assert build_cases()[0] == before
    assert set(case) == {"id", "operation", "requirement", "covers", "input"}
    assert "expected" not in json.dumps(case) and "result" not in case


def _complete_rows():
    return [{**case, "status": "matched", "runtimeEvidenceValidated": True} for case in build_cases()]


def test_both_conditions_can_be_credited_only_after_the_entire_exact_family_validates():
    assert _host_update_isolation_family_complete(_complete_rows()) is True


def test_empty_or_duplicated_family_does_not_receive_credit():
    assert _host_update_isolation_family_complete([]) is False
    rows = _complete_rows()
    rows.append(deepcopy(rows[0]))
    assert _host_update_isolation_family_complete(rows) is False


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["missing", "mismatched", "blocked", "unverified", "marker-missing", "truthy-marker"])
def test_partial_match_or_unverified_evidence_cannot_credit_either_condition(index, failure):
    rows = _complete_rows()
    if failure == "missing":
        del rows[index]
    elif failure == "unverified":
        rows[index]["runtimeEvidenceValidated"] = False
    elif failure == "marker-missing":
        del rows[index]["runtimeEvidenceValidated"]
    elif failure == "truthy-marker":
        rows[index]["runtimeEvidenceValidated"] = 1
    else:
        rows[index]["status"] = failure
    assert _host_update_isolation_family_complete(rows) is False


@pytest.mark.parametrize("field", ["id", "operation", "requirement", "input", "covers"])
def test_matching_rows_with_substituted_family_identity_do_not_receive_atomic_credit(field):
    rows = _complete_rows()
    if field == "input":
        rows[0][field]["nowMs"] += 1
    elif field == "covers":
        rows[0][field] = list(POINTS[:1])
    else:
        rows[0][field] += "-different"
    assert _host_update_isolation_family_complete(rows) is False


def test_restart_rows_cannot_complete_the_update_family_or_the_reverse():
    from equivalence.harness import _host_restart_session_family_complete
    from equivalence.host_restart_session import build_cases as restart_cases

    restart = [{**case, "status": "matched", "runtimeEvidenceValidated": True} for case in restart_cases()]
    assert _host_update_isolation_family_complete(restart) is False
    assert _host_restart_session_family_complete(_complete_rows()) is False
    assert _host_update_isolation_family_complete(restart + _complete_rows()) is True


@pytest.mark.parametrize("change", ["extra-key", "another-kind", "self-awarded-credit", "reordered", "missing-member",
                                    "repeated-member", "changed-literal", "expected-result-added"])
def test_literal_manifest_is_admitted_only_in_its_exact_frozen_form(tmp_path, change):
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    if change == "extra-key":
        manifest["expected"] = {}
    elif change == "another-kind":
        manifest["kind"] = "host-restart-session-acceptance-literals"
    elif change == "self-awarded-credit":
        manifest["acceptancePointsAwarded"] = 2
    elif change == "reordered":
        manifest["cases"].reverse()
    elif change == "missing-member":
        del manifest["cases"][-1]
    elif change == "repeated-member":
        manifest["cases"].append(deepcopy(manifest["cases"][0]))
    elif change == "changed-literal":
        manifest["cases"][0]["input"]["phases"][1]["update"]["new"] += " An undeclared fact."
    else:
        manifest["cases"][0]["expected"] = {"committed": True}
    altered = tmp_path / "literals.json"
    altered.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf8")
    with pytest.raises(ValueError, match="independently frozen"):
        build_cases(altered)
    assert build_cases() == build_cases(MANIFEST)


def test_another_operation_cannot_claim_or_complete_an_update_condition():
    foreign = {"id": "labelled-foreign-claim", "operation": "index-lifecycle-runtime", "requirement": REQUIREMENT,
               "covers": [POINTS[0]], "input": {"provider": "none"}}
    with pytest.raises(ValueError, match="complete four-case family atomically"):
        validate_registration([foreign])
    with pytest.raises(ValueError, match="complete four-case family atomically"):
        validate_registration([*build_cases(), foreign])
    rows = [*_complete_rows(), {**foreign, "status": "matched", "runtimeEvidenceValidated": True}]
    assert _host_update_isolation_family_complete(rows) is False
    # The same row without a claim on either condition is simply not part of the family.
    rows[-1]["covers"] = ["indexing.lifecycle"]
    assert _host_update_isolation_family_complete(rows) is True


def test_every_literal_declares_the_positive_control_for_its_superseded_query():
    for case in build_cases():
        produce, update = case["input"]["phases"]
        assert produce["supersededRecall"] == update["recalls"]["superseded"]
        assert produce["supersededRecall"]["query"] in update["update"]["old"]
        assert produce["supersededRecall"]["query"] not in update["update"]["new"]
