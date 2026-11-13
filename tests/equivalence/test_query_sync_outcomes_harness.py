"""Credit and dispatch boundaries for the independently frozen query-sync outcome family."""
from copy import deepcopy
import hashlib
import json
import sys
from types import ModuleType

import pytest

from equivalence.cases import build_cases, run_python
from equivalence.harness import HarnessError, ROOT, _query_sync_outcomes_family_complete, _oracle, _validate_scope
from equivalence.query_sync_outcomes import CASE_HASHES, OPERATION, build_cases as family_cases, validate_case, validate_registration
from equivalence.query_sync_boundaries import (
    build_cases as boundary_cases, validate_registration as validate_boundary_registration,
)


def _rows():
    return [dict(case, status="matched", runtimeEvidenceValidated=True) for case in family_cases()]


def test_registration_appends_exact_family_and_retains_all_1437_prior_case_fields():
    registered = build_cases()
    validate_boundary_registration(registered)
    assert registered[1444:] == boundary_cases()
    cases = registered[:1444]
    assert len(cases) == 1444
    assert cases[1437:] == family_cases()
    wire = json.dumps(cases[:1437], sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == "c8b6abb93334bc9ec30fc32d266c9738b1ee723e8c7b0bb52a197bfd525795db"
    assert len([case for case in cases if case["operation"] == "index-identity"]) == 79
    assert [case["id"] for case in cases[1437:]] == list(CASE_HASHES)
    validate_registration(cases)


def test_exact_family_passes_scope_and_only_its_original_point_gate():
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    requirements, points = _validate_scope(scope, family_cases())
    assert len(requirements) == len(points) == 64
    assert sum(len(acceptance) for acceptance in points.values()) == 128
    assert _query_sync_outcomes_family_complete(_rows()) is True


@pytest.mark.parametrize("removed", list(CASE_HASHES))
def test_each_member_is_required_atomically(removed):
    cases = [case for case in family_cases() if case["id"] != removed]
    with pytest.raises(ValueError, match="complete seven-case"):
        validate_registration(cases)
    assert _query_sync_outcomes_family_complete(
        [row for row in _rows() if row["id"] != removed]) is False


@pytest.mark.parametrize("status", ["mismatched", "blocked", "uncovered"])
@pytest.mark.parametrize("index", [0, 3, 6])
def test_a_matching_subset_cannot_credit_the_boundary(index, status):
    rows = _rows()
    rows[index]["status"] = status
    assert _query_sync_outcomes_family_complete(rows) is False


@pytest.mark.parametrize("flag", [None, False, 0, 1, "verified"])
def test_custody_requires_affirmative_boolean_for_every_member(flag):
    for index in range(7):
        rows = _rows()
        rows[index]["runtimeEvidenceValidated"] = flag
        assert _query_sync_outcomes_family_complete(rows) is False


def test_unknown_same_requirement_cannot_hide_beside_the_closed_family():
    forged = dict(family_cases()[0], id="borrowed", operation="unreviewed-query-sync-owner", covers=[])
    with pytest.raises(ValueError):
        validate_registration([*family_cases(), forged])
    assert _query_sync_outcomes_family_complete([*_rows(), dict(forged, status="matched")]) is False


@pytest.mark.parametrize("field", ["clock", "mutation", "corpus", "purpose", "coverage"])
def test_changed_inputs_are_rejected_before_the_sdk_driver_is_imported(field, monkeypatch):
    case = deepcopy(family_cases()[0])
    if field == "clock":
        case["input"]["nowMs"] += 1
    elif field == "mutation":
        case["input"]["sourceMutation"] = {"kind": "none"}
    elif field == "corpus":
        case["input"]["queries"]["first"]["corpus"] = "all"
    elif field == "purpose":
        case["input"]["toolOptions"]["oneShotCliRun"] = True
    else:
        case["covers"] = ["indexing.query-sync.boundaries"]
    monkeypatch.setitem(sys.modules, "equivalence.query_sync_outcomes_sdk", None)
    with pytest.raises(ValueError, match="independently frozen"):
        run_python(case)


def test_sdk_dispatch_preserves_the_complete_actual_return_and_owned_diagnostics(monkeypatch, tmp_path):
    module = ModuleType("equivalence.query_sync_outcomes_sdk")
    actual = {"entire": ["actual", {"extraField": False}], "error": None}
    calls = []

    def driver(arguments, *, evidence_directory):
        calls.append((arguments, evidence_directory))
        return actual

    module.run_query_sync_outcomes_case = driver
    monkeypatch.setitem(sys.modules, module.__name__, module)
    case = dict(family_cases()[0], _diagnosticDirectory=tmp_path)
    assert run_python(case) is actual
    assert calls == [(case["input"], tmp_path)]


def test_a_batch_cannot_fall_back_to_an_older_native_capability():
    with pytest.raises(HarnessError) as failure:
        _oracle(ROOT / "unexecuted-node", ROOT / "equivalence/release-oracle.mjs",
                ROOT / "unexecuted-checkout", family_cases()[:2], 60)
    assert failure.value.code == "query-sync-capability-invalid"


def test_relabelled_old_kernel_cannot_replace_a_frozen_boundary_member():
    old = next(case for case in build_cases() if case["operation"] == "index-identity")
    forged = dict(old, operation=OPERATION, covers=["indexing.query-sync.outcomes"])
    with pytest.raises(ValueError, match="independently frozen"):
        validate_case(forged)
