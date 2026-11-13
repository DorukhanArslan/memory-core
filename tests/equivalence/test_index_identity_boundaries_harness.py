"""Credit and dispatch boundaries for the independently frozen manager family."""
from copy import deepcopy
import hashlib
import json
import sys
from types import ModuleType

import pytest

from equivalence.cases import build_cases, run_python
from equivalence.harness import HarnessError, ROOT, _index_identity_boundaries_family_complete, _oracle, _validate_scope
from equivalence.index_identity_boundaries import CASE_HASHES, OPERATION, build_cases as family_cases, validate_case, validate_registration
from equivalence.query_sync_outcomes import (
    OPERATION as QUERY_SYNC_OPERATION, build_cases as query_sync_cases,
    validate_registration as validate_query_sync_registration,
)
from equivalence.query_sync_boundaries import (
    build_cases as query_sync_boundary_cases,
    validate_registration as validate_query_sync_boundary_registration,
)


def _rows():
    return [dict(case, status="matched", runtimeEvidenceValidated=True) for case in family_cases()]


def test_registration_appends_independent_family_without_changing_any_prior_definition():
    complete = build_cases()
    validate_query_sync_boundary_registration(complete)
    assert complete[1444:] == query_sync_boundary_cases()
    registered = complete[:1444]
    validate_query_sync_registration(registered)
    assert registered[1437:] == query_sync_cases()
    cases = [case for case in registered if case["operation"] != QUERY_SYNC_OPERATION]
    assert registered[:len(cases)] == cases
    assert len(cases) == 1437
    assert cases[1421:] == family_cases()
    complete_wire = json.dumps(cases, sort_keys=True, ensure_ascii=True,
                               separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(complete_wire).hexdigest() == "c8b6abb93334bc9ec30fc32d266c9738b1ee723e8c7b0bb52a197bfd525795db"
    wire = json.dumps(cases[:1421], sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == "a57e238c1d6cc127744fe82408678faf4471d20c7e8cfd87dcdb06200e8f7444"
    assert len([case for case in cases if case["operation"] == "index-identity"]) == 79
    assert [case["id"] for case in cases[1421:]] == list(CASE_HASHES)
    validate_registration(cases)


def test_exact_family_passes_scope_and_only_its_original_point_gate():
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    requirements, points = _validate_scope(scope, family_cases())
    assert len(requirements) == len(points) == 64
    assert sum(len(acceptance) for acceptance in points.values()) == 128
    assert _index_identity_boundaries_family_complete(_rows()) is True


@pytest.mark.parametrize("removed", list(CASE_HASHES))
def test_each_member_is_required_atomically(removed):
    cases = [case for case in family_cases() if case["id"] != removed]
    with pytest.raises(ValueError, match="complete sixteen-case"):
        validate_registration(cases)
    assert _index_identity_boundaries_family_complete(
        [row for row in _rows() if row["id"] != removed]) is False


@pytest.mark.parametrize("status", ["mismatched", "blocked", "uncovered"])
@pytest.mark.parametrize("index", [0, 7, 15])
def test_a_matching_subset_cannot_credit_the_boundary(index, status):
    rows = _rows()
    rows[index]["status"] = status
    assert _index_identity_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("flag", [None, False, 0, 1, "verified"])
def test_custody_requires_affirmative_boolean_for_every_member(flag):
    for index in range(16):
        rows = _rows()
        rows[index]["runtimeEvidenceValidated"] = flag
        assert _index_identity_boundaries_family_complete(rows) is False


def test_unknown_same_requirement_cannot_hide_behind_the_existing_kernel():
    forged = dict(family_cases()[0], id="borrowed", operation="unreviewed-identity-manager", covers=[])
    with pytest.raises(ValueError):
        validate_registration([*family_cases(), forged])
    assert _index_identity_boundaries_family_complete([*_rows(), dict(forged, status="matched")]) is False


@pytest.mark.parametrize("field", ["clock", "mutation", "corpus", "purpose", "coverage"])
def test_changed_inputs_are_rejected_before_the_sdk_driver_is_imported(field, monkeypatch):
    case = deepcopy(family_cases()[0])
    if field == "clock":
        case["input"]["nowMs"] += 1
    elif field == "mutation":
        case["input"]["metadataMutation"] = {"kind": "delete-metadata-row", "key": "other"}
    elif field == "corpus":
        case["input"]["search"]["corpus"] = "all"
    elif field == "purpose":
        case["input"]["diagnosticSchedule"]["searchManagerPurpose"] = "cli"
    else:
        case["covers"] = ["indexing.identity.outcomes"]
    monkeypatch.setitem(sys.modules, "equivalence.index_identity_boundaries_sdk", None)
    with pytest.raises(ValueError, match="independently frozen"):
        run_python(case)


def test_sdk_dispatch_preserves_the_complete_actual_return_and_owned_diagnostics(monkeypatch, tmp_path):
    module = ModuleType("equivalence.index_identity_boundaries_sdk")
    actual = {"entire": ["actual", {"extraField": False}], "error": None}
    calls = []

    def driver(arguments, *, evidence_directory):
        calls.append((arguments, evidence_directory))
        return actual

    module.run_index_identity_boundaries_case = driver
    monkeypatch.setitem(sys.modules, module.__name__, module)
    case = dict(family_cases()[0], _diagnosticDirectory=tmp_path)
    assert run_python(case) is actual
    assert calls == [(case["input"], tmp_path)]


def test_a_batch_cannot_fall_back_to_an_older_native_capability():
    with pytest.raises(HarnessError) as failure:
        _oracle(ROOT / "unexecuted-node", ROOT / "equivalence/release-oracle.mjs",
                ROOT / "unexecuted-checkout", family_cases()[:2], 60)
    assert failure.value.code == "identity-boundary-capability-invalid"


def test_relabelled_old_kernel_cannot_replace_a_frozen_boundary_member():
    old = next(case for case in build_cases() if case["operation"] == "index-identity")
    forged = dict(old, operation=OPERATION, covers=["indexing.identity.boundaries"])
    with pytest.raises(ValueError, match="independently frozen"):
        validate_case(forged)
