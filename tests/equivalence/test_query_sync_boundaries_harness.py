"""Labelled gate/transport doubles; no host execution or acceptance credit."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from equivalence import harness
from equivalence.cases import build_cases as catalog, run_python
from equivalence.harness import (
    HarnessError, _oracle, _query_sync_boundaries_family_complete,
    _query_sync_outcomes_family_complete, _validate_scope,
)
from equivalence.query_sync_boundaries import (
    CASE_HASHES, OPERATION, POINTS, build_cases, validate_case, validate_registration,
)
from equivalence.query_sync_outcomes import (
    OPERATION as OUTCOME_OPERATION, POINTS as OUTCOME_POINTS,
    build_cases as outcome_cases, validate_registration as validate_outcome_registration,
)


ROOT = Path(__file__).resolve().parents[2]
NATIVE_MODULE = "equivalence.query_sync_boundaries_native"
SDK_MODULE = "equivalence.query_sync_boundaries_sdk"
UNIT_NATIVE_KIND = "labelled-query-sync-boundary-native-capability"


def _rows():
    return [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]


def _outcome_rows():
    return [dict(case, status="matched", runtimeEvidenceValidated=True) for case in outcome_cases()]


def test_boundary_family_keeps_the_original_scope_and_seven_outcome_members_independent():
    cases = build_cases()
    assert len(cases) == len(CASE_HASHES) == 8
    assert [case["id"] for case in cases] == list(CASE_HASHES)
    assert POINTS == ("indexing.query-sync.boundaries",)
    assert OUTCOME_POINTS == ("indexing.query-sync.outcomes",)
    registered = catalog()
    assert len(registered) == 1452 and registered[1444:] == cases
    validate_registration(registered)
    prior = [case for case in registered if case["operation"] != OPERATION]
    assert len(prior) == 1444 and registered[:1444] == prior
    wire = json.dumps(prior, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == "feea3f91ed24646488b241e6dd739d737c05d25d5c71e724e2febd14b349ece7"
    assert sum("fixtureSource" in case for case in prior) == 79
    assert sum("diagnosticOnly" in case for case in prior) == 1
    assert prior[1437:] == outcome_cases()
    validate_outcome_registration(registered)
    validate_registration([*outcome_cases(), *cases])
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    requirements, points = _validate_scope(scope, [*outcome_cases(), *cases])
    assert len(requirements) == len(points) == 64
    assert sum(len(acceptance) for acceptance in points.values()) == 128
    assert _query_sync_boundaries_family_complete(_rows()) is True


@pytest.mark.parametrize("removed", list(CASE_HASHES))
def test_every_exact_boundary_member_is_required_atomically(removed):
    cases = [case for case in build_cases() if case["id"] != removed]
    with pytest.raises(ValueError, match="complete eight-case"):
        validate_registration(cases)
    assert _query_sync_boundaries_family_complete(
        [row for row in _rows() if row["id"] != removed]) is False


@pytest.mark.parametrize("status", ["mismatched", "blocked", "uncovered"])
def test_every_boundary_member_must_match(status):
    for index in range(8):
        rows = _rows()
        rows[index]["status"] = status
        assert _query_sync_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("flag", [None, False, 0, 1, 1.0, "true", "verified", {"validated": True}])
def test_every_boundary_member_requires_actual_boolean_custody(flag):
    for index in range(8):
        rows = _rows()
        rows[index]["runtimeEvidenceValidated"] = flag
        assert _query_sync_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("field", ["status", "runtimeEvidenceValidated", "input", "covers"])
def test_missing_required_case_or_admission_fields_cannot_credit_the_family(field):
    rows = _rows()
    rows[3].pop(field)
    assert _query_sync_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("attack", [
    "duplicate", "extra", "unknown", "reordered", "changed-wire",
    "outcome-operation", "different-requirement", "outcome-coverage", "uncovered",
])
def test_a_modified_or_extra_boundary_member_cannot_borrow_the_original_point(attack):
    rows = _rows()
    if attack == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif attack == "extra":
        rows.append(deepcopy(rows[0]))
    elif attack == "unknown":
        rows[0]["id"] = "query-sync-boundaries-unreviewed"
    elif attack == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif attack == "changed-wire":
        rows[0]["input"]["nowMs"] += 1
    elif attack == "outcome-operation":
        rows[0]["operation"] = OUTCOME_OPERATION
    elif attack == "different-requirement":
        rows[0]["requirement"] = "indexing.identity"
    elif attack == "outcome-coverage":
        rows[0]["covers"] = list(OUTCOME_POINTS)
    else:
        rows[0]["covers"] = []
    assert _query_sync_boundaries_family_complete(rows) is False


def test_an_unknown_same_requirement_cannot_hide_beside_either_closed_sibling():
    unknown = dict(build_cases()[0], id="unreviewed-query-sync-owner",
                   operation="unreviewed-query-sync-runtime", covers=[])
    for validator in (validate_registration, validate_outcome_registration):
        with pytest.raises(ValueError):
            validator([*outcome_cases(), *build_cases(), unknown])
    rows = [*_outcome_rows(), *_rows(), dict(unknown, status="matched",
                                           runtimeEvidenceValidated=True)]
    assert _query_sync_boundaries_family_complete(rows) is False
    assert _query_sync_outcomes_family_complete(rows) is False


def test_outcome_and_boundary_credit_depend_only_on_their_own_complete_family():
    rows = [*_outcome_rows(), *_rows()]
    assert _query_sync_outcomes_family_complete(rows) is True
    assert _query_sync_boundaries_family_complete(rows) is True
    for removed in CASE_HASHES:
        partial = [row for row in rows if row["id"] != removed]
        assert _query_sync_outcomes_family_complete(partial) is True
        assert _query_sync_boundaries_family_complete(partial) is False
    for removed in (case["id"] for case in outcome_cases()):
        partial = [row for row in rows if row["id"] != removed]
        assert _query_sync_outcomes_family_complete(partial) is False
        assert _query_sync_boundaries_family_complete(partial) is True


def test_a_failed_boundary_does_not_reopen_the_separate_verified_outcomes():
    rows = [*_outcome_rows(), *_rows()]
    rows[-1].update(status="blocked", runtimeEvidenceValidated=False)
    assert _query_sync_outcomes_family_complete(rows) is True
    assert _query_sync_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("field", ["clock", "schedule", "operation", "requirement", "coverage"])
def test_changed_literal_is_rejected_before_importing_the_sdk_driver(field, monkeypatch):
    case = deepcopy(build_cases()[0])
    if field == "clock":
        case["input"]["nowMs"] += 1
    elif field == "schedule":
        case["input"]["unreviewedSchedule"] = True
    elif field == "operation":
        case["operation"] = OUTCOME_OPERATION
    elif field == "requirement":
        case["requirement"] = "indexing.identity"
    else:
        case["covers"] = list(OUTCOME_POINTS)
    monkeypatch.setitem(sys.modules, SDK_MODULE, None)
    monkeypatch.setitem(sys.modules, "equivalence.query_sync_outcomes_sdk", None)
    with pytest.raises(ValueError, match="independently frozen"):
        run_python(case)
    with pytest.raises(ValueError, match="independently frozen"):
        validate_case(case)


def test_sdk_route_preserves_the_complete_return_and_owned_diagnostic_directory(monkeypatch, tmp_path):
    module = ModuleType(SDK_MODULE)
    actual = {"whole": [False, 0, None, {"extraField": "retained"}], "error": None}
    calls = []

    def driver(arguments, *, evidence_directory):
        calls.append((arguments, evidence_directory))
        return actual

    module.run_query_sync_boundaries_case = driver
    monkeypatch.setitem(sys.modules, module.__name__, module)
    case = dict(build_cases()[0], _diagnosticDirectory=tmp_path)
    assert run_python(case) is actual
    assert calls == [(case["input"], tmp_path)]


@pytest.fixture
def native_transport(monkeypatch, tmp_path):
    """Replace only the transport: these labelled receipts are not Native evidence."""
    module = ModuleType(NATIVE_MODULE)
    module.NATIVE_KIND = UNIT_NATIVE_KIND

    def not_called(*args, **kwargs):
        pytest.fail("The unexecuted transport must be rejected before dispatch")

    module.run_native_case = not_called
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    return module


def _native(tmp_path, cases, *, timeout=180, runtime=None):
    return _oracle(tmp_path / "unexecuted-node", ROOT / "equivalence/release-oracle.mjs",
                   tmp_path / "unexecuted-reference", cases, timeout, release_runtime=runtime)


def test_native_requires_authenticated_runtime_before_any_dispatch(native_transport, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [build_cases()[0]])
    assert failure.value.code == "release-runtime-unavailable"
    assert not (tmp_path / ".equivalence-results").exists()


def test_native_batch_cannot_fall_back_to_an_older_capability(native_transport, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, build_cases()[:2], runtime={"label": "unit runtime fixture"})
    assert failure.value.code == "query-sync-boundary-capability-invalid"
    assert not (tmp_path / ".equivalence-results").exists()


@pytest.mark.parametrize("timeout", [0, -1, 181, True, False, None, "180", float("nan"), float("inf")])
def test_native_boundary_timeout_is_bounded_before_dispatch(native_transport, tmp_path, timeout):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [build_cases()[0]], timeout=timeout,
                runtime={"label": "unit runtime fixture"})
    assert failure.value.code == "timeout-invalid"


def test_new_timeout_does_not_expand_the_old_outcome_capability(native_transport, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [outcome_cases()[0]], runtime={"label": "unit runtime fixture"})
    assert failure.value.code == "timeout-invalid"


def test_native_transport_preserves_whole_results_traces_and_exact_raw_bytes(
        native_transport, tmp_path):
    case = build_cases()[0]
    raw = [{"label": "unit transport fixture, not Native evidence", "values": [False, 0, None]}]
    wire = (json.dumps(raw, ensure_ascii=True, indent=2) + "\n").encode()
    result = {"complete": [False, 0, None], "warning": "retained", "debug": {"hits": 0},
              "observed": {"action": "retained", "error": None}}
    results = [{"id": case["id"], "ok": True, "result": result}]
    trace, sources = {"label": "unit trace fixture"}, [{"label": "unit source fixture"}]

    def driver(selected, node, runtime, directory, *, timeout):
        assert selected == case and timeout == 180
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_bytes(wire)
        return {"kind": UNIT_NATIVE_KIND, "results": results, "releaseSources": sources,
                "releaseTrace": trace, "runtimeDiagnostics": raw,
                "evidenceDirectory": str(directory)}

    native_transport.run_native_case = driver
    returned = _native(tmp_path, [case], runtime={"label": "unit runtime fixture"})
    assert returned["results"] is results
    assert returned["releaseSources"] is sources and returned["releaseTrace"] is trace
    assert returned["runtimeDiagnostics"] == [{"id": case["id"], "rawSnapshots": raw,
        "sha256": hashlib.sha256(wire).hexdigest(), "validationStatus": "verified"}]
    assert (Path(returned["evidenceDirectory"]) / "evidence/native-raw.json").read_bytes() == wire


@pytest.mark.parametrize("cause", ["timeout", "execution-refusal"])
def test_first_native_failure_retains_its_original_custody_and_is_never_retried(
        native_transport, tmp_path, cause):
    case, calls = build_cases()[0], []
    wire = b'[{"label":"first rejected transport capture; no Native credit"}]\n'
    error = (subprocess.TimeoutExpired("labelled unexecuted transport", 180)
             if cause == "timeout" else ValueError("first labelled execution refusal"))

    def driver(selected, node, runtime, directory, *, timeout):
        calls.append(directory)
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_bytes(wire)
        (directory / "stdout.json").write_text("first stdout, retained unchanged\n")
        (directory / "stderr.log").write_text("first stderr, retained unchanged\n")
        raise error

    native_transport.run_native_case = driver
    with pytest.raises(HarnessError, match="no retry") as failure:
        _native(tmp_path, [case], runtime={"label": "unit runtime fixture"})
    assert len(calls) == 1 and failure.value.__cause__ is error
    assert failure.value.code == "query-sync-boundaries-evidence-invalid"
    rejected = failure.value.rejected_evidence
    assert rejected == {"caseIds": [case["id"]], "coverageCredit": False,
                        "retainedDirectory": str(calls[0]), "reason": str(error)}
    assert calls[0].is_relative_to(tmp_path / ".equivalence-results/query-sync-boundaries")
    assert (calls[0] / "evidence/native-raw.json").read_bytes() == wire
    assert (calls[0] / "stdout.json").read_text() == "first stdout, retained unchanged\n"
    assert (calls[0] / "stderr.log").read_text() == "first stderr, retained unchanged\n"


@pytest.mark.parametrize("tamper", ["wrong-kind", "changed-bytes", "boolean-for-integer",
                                    "duplicate", "malformed", "symlink", "hardlink", "oversized"])
def test_native_transport_rejects_changed_or_unowned_raw_capture_without_retry(
        native_transport, tmp_path, tamper):
    case, calls = build_cases()[0], []

    def driver(selected, node, runtime, directory, *, timeout):
        calls.append(directory)
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        target = evidence / "native-raw.json"
        raw = [{"label": "unit raw fixture, not Native evidence", "flag": False}]
        shown = deepcopy(raw)
        if tamper == "changed-bytes":
            shown[0]["label"] = "other bytes"
        elif tamper == "boolean-for-integer":
            shown[0]["flag"] = 0
        elif tamper == "duplicate":
            shown.append(deepcopy(shown[0]))
            raw = deepcopy(shown)
        target.write_text(json.dumps(shown))
        if tamper == "malformed":
            target.write_bytes(b"{")
        elif tamper == "symlink":
            other = target.with_name("original.json")
            target.rename(other)
            target.symlink_to(other)
        elif tamper == "hardlink":
            os.link(target, target.with_name("alias.json"))
        elif tamper == "oversized":
            with target.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024 + 1)
        return {"kind": "official-release-query-sync-outcomes" if tamper == "wrong-kind" else UNIT_NATIVE_KIND,
                "results": [], "releaseSources": [], "releaseTrace": {},
                "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    native_transport.run_native_case = driver
    with pytest.raises(HarnessError, match="no retry") as failure:
        _native(tmp_path, [case], runtime={"label": "unit runtime fixture"})
    assert len(calls) == 1 and failure.value.rejected_evidence["coverageCredit"] is False
    assert failure.value.code == "query-sync-boundaries-evidence-invalid"
    assert (calls[0] / "evidence/native-raw.json").lstat()
