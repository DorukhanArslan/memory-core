"""No promotion acceptance credit without the entire frozen family and evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases
from equivalence.harness import HarnessError, _validate_scope
from equivalence.promotion_apply_family import (
    ACCEPTANCE, CASE_HASHES, build_registered_cases, validate_execution_case, validate_registration,
)

ROOT = Path(__file__).resolve().parents[2]


def test_full_catalog_registers_every_exact_family_for_both_existing_conditions():
    cases = build_cases()
    claiming = [c for c in cases if set(ACCEPTANCE).intersection(c["covers"])]
    assert {c["id"] for c in claiming} == set(CASE_HASHES)
    assert all(c["covers"] == list(ACCEPTANCE) for c in claiming)
    validate_registration(cases)


@pytest.mark.parametrize("index", range(8))
def test_one_missing_family_fails_scope_before_any_execution(index):
    cases = build_registered_cases()
    del cases[index]
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    with pytest.raises(HarnessError, match="all eight"):
        _validate_scope(scope, cases)


@pytest.mark.parametrize("field", ["id", "operation", "requirement", "input", "covers"])
def test_claim_cannot_substitute_a_different_owner_input_or_coverage(field):
    cases = build_registered_cases()
    if field == "input":
        cases[0][field]["options"]["limit"] += 1
    elif field == "covers":
        cases[0][field] = list(ACCEPTANCE[:1])
    else:
        cases[0][field] += "-different"
    with pytest.raises(ValueError):
        validate_registration(cases)


def test_registration_is_detached_from_literal_source_and_supplies_no_expected_result():
    cases = build_registered_cases()
    original = deepcopy(cases[0])
    validated = validate_execution_case(cases[0])
    validated["input"]["nowMs"] += 1
    assert cases[0] == original
    assert "expected" not in cases[0] and "result" not in cases[0]
    assert build_registered_cases()[0] == original


def test_no_coverage_does_not_impersonate_a_registered_partial_family():
    cases = build_registered_cases()
    cases[0]["covers"] = []
    with pytest.raises(ValueError, match="all eight"):
        validate_registration(cases)
