"""Coverage metadata may close #2 only for its entire reviewed real-input set."""
from copy import deepcopy
import json
import hashlib

import pytest

from equivalence.cases import build_cases
from equivalence.harness import HarnessError, ROOT, _validate_scope
from equivalence.storage_path_acceptance import (
    REVIEWED_STORAGE_PATH_FAMILIES,
    STORAGE_PATH_ACCEPTANCE_POINTS,
    validate_storage_path_acceptance_registration,
)
from equivalence.storage_path_contract import build_storage_path_contract_cases
from equivalence.get_read_race_profile import GET_READ_RACE_PROFILE, build_storage_path_read_race_cases
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


def _scope():
    return json.loads((ROOT / "equivalence/scope.json").read_text())


def test_both_fixed_conditions_require_the_same_literal_eleven_families_and_99_calls():
    cases = build_storage_path_contract_cases()
    validate_storage_path_acceptance_registration(cases)
    requirements, points = _validate_scope(_scope(), cases)
    assert len(requirements) == 64 and sum(map(len, points.values())) == 128
    assert set(REVIEWED_STORAGE_PATH_FAMILIES) == {
        "storage-path-contract-root-relative-and-absolute", "storage-path-contract-traversal-and-missing",
        "storage-path-contract-encoded-literals-and-raw-boundaries", "storage-path-contract-symlink-admission",
        "storage-path-contract-symlink-loop-os-errors", "storage-path-contract-nonregular-and-hardlinks",
        "storage-path-contract-missing-workspace", "storage-path-contract-workspace-is-file",
        "storage-path-contract-plain-extra-root-authority", "storage-path-contract-patterned-extra-root-admission",
        "storage-path-read-race-owned-leaf-to-symlink",
    }
    assert sum(count for count, _ in REVIEWED_STORAGE_PATH_FAMILIES.values()) == 99
    for point in STORAGE_PATH_ACCEPTANCE_POINTS:
        assert {case["id"] for case in cases if point in case["covers"]} == set(REVIEWED_STORAGE_PATH_FAMILIES)


@pytest.mark.parametrize("identifier", tuple(REVIEWED_STORAGE_PATH_FAMILIES))
def test_removing_any_reviewed_family_cannot_leave_either_condition_claimed(identifier):
    cases = [case for case in build_storage_path_contract_cases() if case["id"] != identifier]
    with pytest.raises(HarnessError, match="complete reviewed whole-tool family"):
        _validate_scope(_scope(), cases)


@pytest.mark.parametrize("identifier", tuple(REVIEWED_STORAGE_PATH_FAMILIES))
@pytest.mark.parametrize("point", STORAGE_PATH_ACCEPTANCE_POINTS)
def test_every_family_is_required_for_each_point_independently(identifier, point):
    cases = build_storage_path_contract_cases()
    next(case for case in cases if case["id"] == identifier)["covers"].remove(point)
    with pytest.raises(ValueError, match="exact reviewed input"):
        validate_storage_path_acceptance_registration(cases)


@pytest.mark.parametrize("change", ["request-count", "same-count-substitution", "fixture-bytes", "snapshots", "operation", "helper-claim"])
def test_labels_or_reduced_inputs_cannot_substitute_for_the_reviewed_calls(change):
    cases = build_storage_path_contract_cases()
    first = cases[0]
    if change == "request-count":
        first["input"]["steps"].pop()
    elif change == "same-count-substitution":
        first["input"]["steps"][0] = {"params": {"path": "MEMORY.md", "lines": 1}}
    elif change == "fixture-bytes":
        first["input"]["files"]["MEMORY.md"] += "unreviewed"
    elif change == "snapshots":
        first["input"]["observeFilesystem"] = False
    elif change == "operation":
        first["operation"] = "storage-read-paths"
    else:
        helper = deepcopy(first)
        helper["id"] = "unreviewed-helper"
        cases.append(helper)
    with pytest.raises(ValueError):
        validate_storage_path_acceptance_registration(cases)


def test_historical_uncredited_metadata_stays_uncredited_and_does_not_need_registration():
    historical = build_storage_path_contract_cases()
    for case in historical:
        case["covers"] = []
    validate_storage_path_acceptance_registration(historical)
    _validate_scope(_scope(), historical)
    assert not any(case["covers"] for case in historical)


def test_default_catalog_contains_the_full_set_once_without_lending_points_to_helpers():
    cases = build_cases()
    _validate_scope(_scope(), cases)
    claiming = [case for case in cases if set(case["covers"]) & set(STORAGE_PATH_ACCEPTANCE_POINTS)]
    assert len(claiming) == 11 and {case["id"] for case in claiming} == set(REVIEWED_STORAGE_PATH_FAMILIES)
    assert all(case["operation"] == "get-contract-runtime" and case["input"]["kind"] == "tool" for case in claiming)


def _transport(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    raw = b"// Transport labels only; never a Native behavior oracle.\n"
    (runtime / "owner.mjs").write_bytes(raw)
    config = {"runtimeRoot": str(runtime), "packages": [{"location": "node_modules/openclaw",
              "directory": str(runtime), "files": [{"path": "owner.mjs", "sha256": hashlib.sha256(raw).hexdigest()}]}]}
    adapters = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in (ROOT / "equivalence").glob("*.mjs")}
    return config, adapters


def _result(case):
    return {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": True, "result": {"provider": "none"}},
    ]}


def test_generic_get_execution_cannot_lend_the_official_test_hook(tmp_path):
    config, adapters = _transport(tmp_path)
    case = build_storage_path_read_race_cases()[0]
    with ReleaseOracleExecution(config, adapters) as execution:
        assert "getReadRaceProfile" not in execution._context
        with pytest.raises(RuntimeOracleError, match="explicit narrow native hook"):
            execution.collect(_result(case), [case])


@pytest.mark.parametrize("operation", ["get-contract-helper-runtime", "search-contract-runtime", "session-contract-runtime", "workspace-isolation-runtime"])
def test_reviewed_hook_permission_cannot_cross_to_other_operations(tmp_path, operation):
    config, adapters = _transport(tmp_path)
    case = build_storage_path_read_race_cases()[0]
    case["operation"] = operation
    with ReleaseOracleExecution(config, adapters, get_read_race_profile=GET_READ_RACE_PROFILE) as execution:
        with pytest.raises(ValueError, match="unrelated operation"):
            execution._collect(_result(case), [case])
        with pytest.raises(RuntimeOracleError, match="invalid execution evidence"):
            execution.collect(_result(case), [case])


@pytest.mark.parametrize("other", ["entry_profile", "model_node_runtime", "turn_taint_source", "fixture_captures"])
def test_read_hook_capability_cannot_borrow_other_profile_authority(tmp_path, other):
    config, adapters = _transport(tmp_path)
    options = {"get_read_race_profile": GET_READ_RACE_PROFILE, other: True if other == "fixture_captures" else {}}
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(config, adapters, **options):
            pass
