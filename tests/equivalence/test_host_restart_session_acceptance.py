"""Whole-host restart credit requires the exact complete authenticated family."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases as build_catalog
from equivalence.harness import HarnessError, _validate_scope
from equivalence.host_restart_session import (
    CASE_HASHES, OPERATION, POINTS, build_cases, validate_case, validate_registration,
)


ROOT = Path(__file__).resolve().parents[2]


def test_catalog_registers_all_four_exact_hosts_for_both_existing_conditions():
    catalog = build_catalog()
    claims = [case for case in catalog if set(POINTS).intersection(case["covers"])]
    assert {case["id"] for case in claims} == set(CASE_HASHES)
    assert len(claims) == 4
    assert all(case["operation"] == OPERATION and case["covers"] == list(POINTS) for case in claims)
    validate_registration(catalog)


def test_previous_fifteen_development_inputs_remain_separate_and_uncredited():
    from equivalence.host_restart import build_cases as original
    from equivalence.host_restart_managed import build_cases as managed
    from equivalence.host_restart_policy import build_cases as policy
    from equivalence.host_restart_publication import build_cases as publication

    families = [original(), policy(), publication(), managed()]
    assert [len(family) for family in families] == [3, 4, 4, 4]
    old = [case for family in families for case in family]
    assert all(case["covers"] == [] and case["operation"] != OPERATION for case in old)
    assert not {case["id"] for case in old}.intersection(CASE_HASHES)
    validate_registration(old)


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
    assert "expected" not in case and "result" not in case


def _complete_rows():
    return [{**case, "status": "matched", "runtimeEvidenceValidated": True} for case in build_cases()]


def test_both_conditions_can_be_credited_only_after_the_entire_exact_family_validates():
    from equivalence.harness import _host_restart_session_family_complete

    assert _host_restart_session_family_complete(_complete_rows()) is True


def test_empty_or_duplicated_family_does_not_receive_credit():
    from equivalence.harness import _host_restart_session_family_complete

    assert _host_restart_session_family_complete([]) is False
    rows = _complete_rows()
    rows.append(deepcopy(rows[0]))
    assert _host_restart_session_family_complete(rows) is False


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["missing", "mismatched", "blocked", "unverified", "marker-missing", "truthy-marker"])
def test_partial_match_or_unverified_evidence_cannot_credit_either_condition(index, failure):
    from equivalence.harness import _host_restart_session_family_complete

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
    assert _host_restart_session_family_complete(rows) is False


@pytest.mark.parametrize("field", ["id", "operation", "requirement", "input", "covers"])
def test_matching_rows_with_substituted_family_identity_do_not_receive_atomic_credit(field):
    from equivalence.harness import _host_restart_session_family_complete

    rows = _complete_rows()
    if field == "input":
        rows[0][field]["nowMs"] += 1
    elif field == "covers":
        rows[0][field] = list(POINTS[:1])
    else:
        rows[0][field] += "-different"
    assert _host_restart_session_family_complete(rows) is False
