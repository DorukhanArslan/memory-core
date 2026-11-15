"""Source-only registration, custody and dispatch doubles; no original engines."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from equivalence import harness
from equivalence.cases import build_cases as catalog, run_python
from equivalence.forget_index_fence import build_cases as v1_cases
from equivalence.forget_index_fence_v2 import build_cases as v2_cases
from equivalence.forget_index_fence_v3 import build_cases as v3_cases
from equivalence.forget_index_fence_v4 import build_cases as v4_cases
from equivalence.forget_index_fence_v5 import build_cases as v5_cases
from equivalence.forget_index_fence_v6 import (
    CASE_HASHES, POINTS, build_cases, validate_registration,
)
from equivalence.harness import (
    HarnessError, _forget_index_fence_family_complete, _oracle,
    _load_forget_index_fence_reference, _read_forget_index_fence_raw,
    _seal_forget_index_fence_authorities,
    _seal_forget_index_fence_references, _validate_forget_index_fence_pair,
    _validate_python_runtime_diagnostic_file, _validate_scope,
)


ROOT = Path(__file__).resolve().parents[2]
NATIVE_MODULE = "equivalence.forget_index_fence_native"
SDK_MODULE = "equivalence.forget_index_fence_sdk"
GUARD_MODULE = "equivalence.forget_index_fence_evidence"
UNIT_NATIVE_KIND = "labelled-forget-index-fence-transport"


def _rows():
    return [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]


def test_explicit_migration_preserves_all_nonwhitelisted_definitions_annotations_and_scope():
    registered, family = catalog(), build_cases()
    assert len(registered) == 1465 and registered[1452:] == family
    from equivalence.catalog_migration import definition_authority
    from equivalence.host_turn_barrier_v4 import OPERATION as host_operation, business_case
    migration = definition_authority(registered, fif_version="v6")
    assert migration["originalPrefixUnchanged"] is False
    assert len(migration["hostReplacements"]) == 4 and len(migration["fifReplacements"]) == 13
    previous = [business_case(case) if case["operation"] == host_operation else case for case in registered[:1452]]
    wire = json.dumps(previous, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == "0fa31b6393c65303f4fa2e1663671e4ef60eb15edc563f05aba218c8c408349c"
    assert sum("fixtureSource" in case for case in previous) == 79
    assert sum("diagnosticOnly" in case for case in previous) == 1
    assert sum("fixtureSource" in case or "diagnosticOnly" in case for case in registered) == 80
    assert [case["id"] for case in family] == list(CASE_HASHES)
    assert len(family) == len(CASE_HASHES) == 13
    assert all(case["operation"] == "forget-index-fence-v6-runtime"
               and case["id"].startswith("forget-index-fence-v6-")
               and case["input"]["kind"] == "forget-index-fence-v6" for case in family)
    assert POINTS == ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
    validate_registration(registered)
    scope_path = ROOT / "equivalence/scope.json"
    assert hashlib.sha256(scope_path.read_bytes()).hexdigest() == "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
    requirements, points = _validate_scope(json.loads(scope_path.read_text()), registered)
    assert len(requirements) == len(points) == 64
    assert sum(len(acceptance) for acceptance in points.values()) == 128
    assert _forget_index_fence_family_complete(_rows()) is True


@pytest.mark.parametrize("removed", list(CASE_HASHES))
def test_every_member_is_required_for_both_original_points(removed):
    cases = [case for case in build_cases() if case["id"] != removed]
    with pytest.raises(ValueError, match="thirteen"):
        validate_registration(cases)
    assert _forget_index_fence_family_complete(
        [row for row in _rows() if row["id"] != removed]) is False


@pytest.mark.parametrize("status", ["mismatched", "blocked", "uncovered"])
def test_one_nonmatching_member_blocks_the_whole_two_point_gate(status):
    for index in range(13):
        rows = _rows()
        rows[index]["status"] = status
        assert _forget_index_fence_family_complete(rows) is False


@pytest.mark.parametrize("flag", [None, False, 0, 1, 1.0, "true", {"validated": True}])
def test_every_member_requires_actual_boolean_paired_custody(flag):
    for index in range(13):
        rows = _rows()
        rows[index]["runtimeEvidenceValidated"] = flag
        assert _forget_index_fence_family_complete(rows) is False


@pytest.mark.parametrize("attack", [
    "reordered", "duplicate", "extra", "changed-input", "other-operation", "one-point",
    "removed-effects-barrier", "premature-deferred-barrier", "unbounded-effects-policy",
    "unsupported-sync-override", "removed-watch-ready", "removed-watch-effects",
    "late-target-recapture", "missing-watch-owner", "unbounded-watch-policy", "early-crash-close",
])
def test_changed_family_or_partial_coverage_cannot_borrow_acceptance(attack):
    cases = build_cases()
    if attack == "reordered":
        cases[0], cases[1] = cases[1], cases[0]
    elif attack == "duplicate":
        cases[1] = deepcopy(cases[0])
    elif attack == "extra":
        cases.append(deepcopy(cases[0]))
    elif attack == "changed-input":
        cases[2]["input"]["clock"]["nowMs"] += 1
    elif attack == "other-operation":
        cases[2]["operation"] = "index-publication"
    elif attack == "one-point":
        cases[2]["covers"] = list(POINTS[:1])
    elif attack == "removed-effects-barrier":
        steps = cases[2]["input"]["steps"]
        steps.remove(next(step for step in steps if step["operation"] == "await-original-search-effects"))
    elif attack == "premature-deferred-barrier":
        steps = cases[2]["input"]["steps"]
        barrier = next(step for step in steps if step["operation"] == "await-original-search-effects"
                       and step["label"] == "afterForget")
        steps.remove(barrier)
        query = next(index for index, step in enumerate(steps)
                     if step["operation"] == "public-memory-search" and step["label"] == "afterForget")
        steps.insert(query + 1, barrier)
    elif attack == "unbounded-effects-policy":
        cases[2]["input"]["observationPolicy"]["searchEffects"]["maxReferencesPerBarrier"] = 0
    elif attack == "unsupported-sync-override":
        cases[2]["input"]["config"]["memory"]["search"]["sync"] = {"onSearch": True, "watch": False}
    elif attack in {"removed-watch-ready", "removed-watch-effects", "missing-watch-owner"}:
        steps = cases[2]["input"]["steps"]
        operation = "await-original-watch-ready" if attack == "removed-watch-ready" else "await-original-watch-effects"
        step = next(step for step in steps if step["operation"] == operation)
        if attack == "missing-watch-owner":
            step["actors"] = ["foreground"]
        else:
            steps.remove(step)
    elif attack == "late-target-recapture":
        cases[2]["input"]["observationPolicy"]["watchEffects"]["targetBinding"] = "Recapture a later version"
    elif attack == "unbounded-watch-policy":
        cases[2]["input"]["observationPolicy"]["watchEffects"]["maxReferencesPerBarrier"] = 0
    else:
        steps = cases[6]["input"]["steps"]
        first = next(i for i, step in enumerate(steps) if step == {"operation": "original-owner-close", "actor": "foreground"})
        block = steps[first:first + 3]
        del steps[first:first + 3]
        retry = next(i for i, step in enumerate(steps) if step["operation"] == "start-fresh-original-process" and step["actor"] == "forgetter")
        steps[retry:retry] = block
    with pytest.raises(ValueError):
        validate_registration(cases)
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in cases]
    assert _forget_index_fence_family_complete(rows) is False
    with pytest.raises(HarnessError) as failure:
        _validate_scope(json.loads((ROOT / "equivalence/scope.json").read_text()), cases)
    assert failure.value.code == "cases-invalid"


@pytest.mark.parametrize("previous", [v1_cases, v2_cases, v3_cases, v4_cases, v5_cases], ids=["v1", "v2", "v3", "v4", "v5"])
def test_previous_diagnostics_cannot_supply_v4_registration_or_credit(previous):
    original = previous()
    with pytest.raises(ValueError, match="thirteen"):
        validate_registration(original)
    assert _forget_index_fence_family_complete([
        dict(case, status="matched", runtimeEvidenceValidated=True) for case in original]) is False
    with pytest.raises(HarnessError) as failure:
        _validate_scope(json.loads((ROOT / "equivalence/scope.json").read_text()), original)
    assert failure.value.code == "cases-invalid"


def test_sdk_dispatch_validates_literal_and_returns_the_whole_actual_result(monkeypatch, tmp_path):
    module = ModuleType(SDK_MODULE)
    actual = {"provider": "none", "calls": {"labelled": [False, 0, None]}, "snapshots": {}}
    calls = []

    def driver(value, *, evidence_directory):
        calls.append((value, evidence_directory))
        return actual

    module.run_forget_index_fence_sdk_case = driver
    monkeypatch.setitem(sys.modules, SDK_MODULE, module)
    case = dict(build_cases()[0], _diagnosticDirectory=tmp_path)
    assert run_python(case) is actual
    assert calls == [(case["input"], tmp_path)]
    case["input"]["scenario"] += "-changed"
    with pytest.raises(ValueError):
        run_python(case)
    assert len(calls) == 1
    for previous in (v1_cases, v2_cases, v3_cases, v4_cases):
        with pytest.raises(ValueError, match="Unsupported equivalence operation"):
            run_python(previous()[0])
    assert len(calls) == 1


@pytest.fixture
def native_transport(monkeypatch, tmp_path):
    module = ModuleType(NATIVE_MODULE)
    module.NATIVE_KIND = UNIT_NATIVE_KIND

    def not_called(*args, **kwargs):
        pytest.fail("Original execution is forbidden in these transport doubles")

    module.run_native_case = not_called
    monkeypatch.setitem(sys.modules, NATIVE_MODULE, module)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    return module


def _native(tmp_path, cases, *, timeout=180, runtime=None):
    return _oracle(tmp_path / "unexecuted-node", ROOT / "equivalence/release-oracle.mjs",
                   tmp_path / "selected-reference", cases, timeout, release_runtime=runtime)


def test_native_requires_authenticated_runtime_before_dispatch(native_transport, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [build_cases()[0]])
    assert failure.value.code == "release-runtime-unavailable"
    assert not (tmp_path / ".equivalence-results").exists()


def test_native_forbids_batch_fallback(native_transport, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, build_cases()[:2], runtime={"label": "unit only"})
    assert failure.value.code == "forget-index-fence-capability-invalid"
    assert not (tmp_path / ".equivalence-results").exists()


def test_native_rejects_changed_v5_controls_before_transport_entry(native_transport, tmp_path):
    case = build_cases()[0]
    case["input"]["steps"] = [step for step in case["input"]["steps"]
                              if step["operation"] != "await-original-search-effects"]
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [case], runtime={"label": "unit only"})
    assert failure.value.code == "cases-invalid"
    assert not (tmp_path / ".equivalence-results").exists()


@pytest.mark.parametrize("previous", [v1_cases, v2_cases, v3_cases, v4_cases, v5_cases], ids=["v1", "v2", "v3", "v4", "v5"])
def test_previous_native_dispatch_cannot_fall_back_to_an_unregistered_capability(native_transport, tmp_path, previous):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, previous()[:1], runtime={"label": "unit only"})
    assert failure.value.code == "forget-index-fence-version-invalid"
    assert not (tmp_path / ".equivalence-results").exists()


@pytest.mark.parametrize("timeout", [0, -1, 181, True, False, None, "180", float("nan"), float("inf")])
def test_native_timeout_is_bounded_before_dispatch(native_transport, tmp_path, timeout):
    with pytest.raises(HarnessError) as failure:
        _native(tmp_path, [build_cases()[0]], timeout=timeout, runtime={"label": "unit only"})
    assert failure.value.code == "timeout-invalid"


@pytest.mark.parametrize("size", [191658328, 512 * 1024 * 1024])
def test_complete_forget_sdk_custody_is_admitted_up_to_512_mib(size):
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_size=size)
    _validate_python_runtime_diagnostic_file(info, "forget-index-fence-v6-runtime")


@pytest.mark.parametrize("operation,limit_mib", [
    ("forget-index-fence-v6-runtime", 512),
    ("forget-index-fence-v5-runtime", 512),
    ("forget-index-fence-v2-runtime", 512),
    ("forget-index-fence-v3-runtime", 512),
    ("forget-index-fence-v4-runtime", 512),
    ("forget-index-fence-runtime", 512),
    ("host-turn-barrier-boundaries-runtime", 32),
    ("query-sync-boundaries-runtime", 16),
])
def test_sdk_custody_limits_stay_bounded_per_family(operation, limit_mib):
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1,
                           st_size=limit_mib * 1024 * 1024)
    _validate_python_runtime_diagnostic_file(info, operation)
    info.st_size += 1
    with pytest.raises(ValueError, match="Invalid runtime diagnostic"):
        _validate_python_runtime_diagnostic_file(info, operation)


def test_native_forget_custody_remains_bounded_at_128_mib(native_transport, tmp_path):
    def driver(selected, node, runtime, directory, *, timeout, checkout):
        (directory / "evidence").mkdir(parents=True)
        with (directory / "evidence/native-raw.json").open("wb") as stream:
            stream.truncate(128 * 1024 * 1024 + 1)
        return {"kind": UNIT_NATIVE_KIND}

    native_transport.run_native_case = driver
    with pytest.raises(HarnessError, match="no retry") as failure:
        _native(tmp_path, [build_cases()[0]], runtime={"label": "unit only"})
    assert "Invalid original forget/index-fence diagnostic file" in str(failure.value.__cause__)


def test_native_transport_keeps_the_explicit_directory_and_original_bytes(native_transport, tmp_path):
    case = build_cases()[0]
    raw = [{"label": "unexecuted transport fixture", "value": [False, 0, None]}]
    wire = (json.dumps(raw) + "\n").encode()
    result = {"provider": "none", "calls": {}, "snapshots": {"whole": [False, 0, None]}}
    results = [{"id": case["id"], "ok": True, "result": result}]
    calls = []

    def driver(selected, node, runtime, directory, *, timeout, checkout):
        calls.append((selected, checkout))
        assert timeout == 180
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_bytes(wire)
        return {"kind": UNIT_NATIVE_KIND, "results": results, "releaseSources": [],
                "releaseTrace": {}, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    native_transport.run_native_case = driver
    actual = _native(tmp_path, [case], runtime={"label": "unit only"})
    assert calls == [(case, tmp_path / "selected-reference")]
    assert actual["results"] is results
    assert actual["runtimeDiagnostics"] == [{
        "id": case["id"], "sha256": hashlib.sha256(wire).hexdigest(),
        "rawSnapshotReference": {"directory": actual["evidenceDirectory"],
                                 "file": "evidence/native-raw.json", "bytes": len(wire),
                                 "sha256": hashlib.sha256(wire).hexdigest()},
        "validationStatus": "verified", "evidenceDirectory": actual["evidenceDirectory"],
    }]
    assert "rawSnapshots" not in actual["runtimeDiagnostics"][0]
    assert "unexecuted transport fixture" not in json.dumps(actual)
    assert (Path(actual["evidenceDirectory"]) / "evidence/native-raw.json").read_bytes() == wire


@pytest.mark.parametrize("cause", ["timeout", "execution-refusal"])
def test_first_failure_keeps_streams_and_never_retries(native_transport, tmp_path, cause):
    case, calls = build_cases()[0], []
    error = (subprocess.TimeoutExpired("unexecuted transport", 180) if cause == "timeout"
             else ValueError("labelled original refusal"))

    def driver(selected, node, runtime, directory, *, timeout, checkout):
        calls.append(directory)
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_text('[{"label":"first rejected capture"}]')
        (directory / "stderr.log").write_text("whole first stderr\n")
        raise error

    native_transport.run_native_case = driver
    with pytest.raises(HarnessError, match="no retry") as failure:
        _native(tmp_path, [case], runtime={"label": "unit only"})
    assert calls and len(calls) == 1
    assert failure.value.__cause__ is error
    assert failure.value.code == "forget-index-fence-evidence-invalid"
    assert failure.value.rejected_evidence["coverageCredit"] is False
    assert (calls[0] / "stderr.log").read_text() == "whole first stderr\n"


@pytest.mark.parametrize("affirmative", [True, None, False, 1, "true"])
def test_pair_gate_requires_true_and_explicit_independently_selected_paths(monkeypatch, tmp_path, affirmative):
    module = ModuleType(GUARD_MODULE)
    observed = []

    def validate(*args, **kwargs):
        observed.append((args, kwargs))
        return affirmative

    module.validate_pair = validate
    monkeypatch.setitem(sys.modules, GUARD_MODULE, module)
    monkeypatch.setattr(harness, "ROOT", tmp_path / "trusted-sdk")
    native_directory = harness.ROOT / ".equivalence-results/forget-index-fence-v6/actual-native"
    (native_directory / "evidence").mkdir(parents=True)
    (native_directory / "evidence/native-raw.json").write_text('[{"native":"whole"}]\n')
    reference, _ = _read_forget_index_fence_raw(native_directory, "native")
    case, original = build_cases()[0], {
        "validationStatus": "verified", "rawSnapshotReference": reference,
        "evidenceDirectory": str(native_directory),
    }
    snapshots = [{"sdk": "whole"}]
    def invoke():
        _validate_forget_index_fence_pair(
            case, original, snapshots, {"native": "result"}, {"sdk": "result"},
            node=tmp_path / "trusted-node", checkout=tmp_path / "trusted-reference",
            sdk_directory=tmp_path / "actual-sdk")
    if affirmative is True:
        invoke()
    else:
        with pytest.raises(ValueError, match="affirmatively"):
            invoke()
    assert len(observed) == 1
    assert observed[0][1] == {
        "approved_node": tmp_path / "trusted-node", "approved_reference": tmp_path / "trusted-reference",
        "approved_sdk_root": tmp_path / "trusted-sdk", "approved_adapter_root": tmp_path / "trusted-sdk",
        "native_directory": native_directory,
        "sdk_directory": tmp_path / "actual-sdk",
    }


@pytest.mark.parametrize("missing", ["evidenceDirectory", "rawSnapshotReference", "validationStatus"])
def test_pair_without_complete_original_physical_custody_cannot_reach_guard(monkeypatch, tmp_path, missing):
    module = ModuleType(GUARD_MODULE)

    def not_called(*args, **kwargs):
        pytest.fail("Incomplete original custody must fail before pair admission")

    module.validate_pair = not_called
    monkeypatch.setitem(sys.modules, GUARD_MODULE, module)
    original = {"validationStatus": "verified", "rawSnapshotReference": {}, "evidenceDirectory": str(tmp_path)}
    del original[missing]
    with pytest.raises(ValueError, match="authenticated"):
        _validate_forget_index_fence_pair(build_cases()[0], original, [{}], {}, {},
            node=tmp_path / "unexecuted-node", checkout=tmp_path / "trusted-reference", sdk_directory=tmp_path)


@pytest.fixture
def owned_raw(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    directory = tmp_path / ".equivalence-results/forget-index-fence-v6/unit-native"
    (directory / "evidence").mkdir(parents=True)
    wire = (json.dumps([{"label": "UNIT_BEFORE", "whole": [False, 0, None],
                         "nested": {"extra": "retained"}}], indent=3) + "\n").encode()
    filename = directory / "evidence/native-raw.json"
    filename.write_bytes(wire)
    reference, snapshots = _read_forget_index_fence_raw(directory, "native")
    return directory, filename, wire, reference, snapshots


def test_reference_keeps_every_original_byte_without_inline_raw(owned_raw):
    directory, filename, wire, reference, snapshots = owned_raw
    assert reference == {"directory": str(directory), "file": "evidence/native-raw.json",
                         "bytes": len(wire), "sha256": hashlib.sha256(wire).hexdigest()}
    assert _load_forget_index_fence_reference(reference, "native", directory) == snapshots
    assert filename.read_bytes() == wire
    assert "UNIT_BEFORE" not in json.dumps(reference)
    assert snapshots[0]["whole"] == [False, 0, None]


@pytest.mark.parametrize("attack", [
    "extra-field", "wrong-file", "wrong-side", "wrong-size", "boolean-size",
    "wrong-hash", "same-size-edited-bytes", "missing-file", "symlink", "hardlink",
    "aliased-directory", "noncanonical-directory", "outside-root", "different-owned-directory",
])
def test_reference_rejects_changed_missing_or_unowned_original_file(owned_raw, tmp_path, attack):
    directory, filename, wire, reference, _ = owned_raw
    reference = deepcopy(reference)
    expected, side = directory, "native"
    if attack == "extra-field":
        reference["rawSnapshots"] = []
    elif attack == "wrong-file":
        reference["file"] = "../native-raw.json"
    elif attack == "wrong-side":
        side = "python"
    elif attack == "wrong-size":
        reference["bytes"] += 1
    elif attack == "boolean-size":
        reference["bytes"] = True
    elif attack == "wrong-hash":
        reference["sha256"] = "0" * 64
    elif attack == "same-size-edited-bytes":
        changed = wire.replace(b"UNIT_BEFORE", b"UNIT_AFTER!")
        assert len(changed) == len(wire)
        filename.write_bytes(changed)
    elif attack == "missing-file":
        filename.unlink()
    elif attack == "symlink":
        original = filename.with_name("original.json")
        filename.rename(original)
        filename.symlink_to(original)
    elif attack == "hardlink":
        import os
        os.link(filename, filename.with_name("alias.json"))
    elif attack == "aliased-directory":
        original = directory.with_name("real-native")
        directory.rename(original)
        directory.symlink_to(original, target_is_directory=True)
    elif attack == "noncanonical-directory":
        reference["directory"] += "/."
    elif attack == "outside-root":
        expected = tmp_path / "outside"
        (expected / "evidence").mkdir(parents=True)
        (expected / "evidence/native-raw.json").write_bytes(wire)
        reference["directory"] = str(expected)
    else:
        other = directory.with_name("another-owned-native")
        (other / "evidence").mkdir(parents=True)
        (other / "evidence/native-raw.json").write_bytes(wire)
        reference["directory"] = str(other)
    with pytest.raises((ValueError, OSError)):
        _load_forget_index_fence_reference(reference, side, expected)


@pytest.mark.parametrize("wire", [
    b"{}", b"[]", b"[{},{}]", b"[false]", b'[{"key":1,"key":2}]', b'[{"value":NaN}]', b"{",
])
def test_complete_reference_loader_requires_exactly_one_strict_json_record(owned_raw, wire):
    directory, filename, _, reference, _ = owned_raw
    filename.write_bytes(wire)
    reference = {**reference, "bytes": len(wire), "sha256": hashlib.sha256(wire).hexdigest()}
    with pytest.raises(ValueError):
        _load_forget_index_fence_reference(reference, "native", directory)


def _referenced_report(tmp_path):
    rows, diagnostics = _rows(), []
    for index, row in enumerate(rows):
        for side in ("native", "python"):
            directory = tmp_path / ".equivalence-results/forget-index-fence-v6" / f"unit-{index}-{side}"
            filename = directory / ("evidence/native-raw.json" if side == "native" else "python-raw.json")
            filename.parent.mkdir(parents=True)
            filename.write_text(json.dumps([{"label": "unexecuted unit custody", "caseId": row["id"],
                                            "whole": [False, 0, None]}]) + "\n")
            reference, _ = _read_forget_index_fence_raw(directory, side)
            diagnostics.append({"id": row["id"], "side": side, "sha256": reference["sha256"],
                                "evidenceDirectory": str(directory), "rawSnapshotReference": reference,
                                "validationStatus": "verified"})
    return {"cases": rows, "runtimeDiagnostics": diagnostics}


def _reference_seals(report):
    return {(item["id"], item["side"]): dict(item["rawSnapshotReference"])
            for item in report["runtimeDiagnostics"]}


def test_final_reference_seal_keeps_old_inline_records_and_complete_family_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    report = _referenced_report(tmp_path)
    expected = _reference_seals(report)
    old = {"id": "old-family-unit", "side": "python", "sha256": "whole-old-sha",
           "rawSnapshots": [{"whole": [False, 0, None]}], "validationStatus": "verified"}
    report["runtimeDiagnostics"].append(deepcopy(old))

    def no_second_parse(*args, **kwargs):
        pytest.fail("Final sealing must stream the original bytes, not retain another parsed capture")

    monkeypatch.setattr(harness, "_read_forget_index_fence_raw", no_second_parse)
    _seal_forget_index_fence_references(report, expected)
    assert report["runtimeDiagnostics"][-1] == old
    assert all("rawSnapshots" not in item for item in report["runtimeDiagnostics"][:-1])
    assert _forget_index_fence_family_complete(report["cases"]) is True
    assert "unexecuted unit custody" not in json.dumps(report)


@pytest.mark.parametrize("attack", [
    "edited-file", "missing-file", "missing-side", "duplicate-side",
    "unverified-side", "missing-reference", "changed-diagnostic-sha", "unexpected-inline-raw",
    "replaced-coherent-reference",
])
def test_final_reference_change_prevents_atomic_point_credit(monkeypatch, tmp_path, attack):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    report = _referenced_report(tmp_path)
    expected = _reference_seals(report)
    assert _forget_index_fence_family_complete(report["cases"]) is True
    diagnostic = report["runtimeDiagnostics"][1]
    reference = diagnostic["rawSnapshotReference"]
    filename = Path(reference["directory"]) / reference["file"]
    if attack == "edited-file":
        filename.write_bytes(filename.read_bytes() + b" ")
    elif attack == "missing-file":
        filename.unlink()
    elif attack == "missing-side":
        report["runtimeDiagnostics"].remove(diagnostic)
    elif attack == "duplicate-side":
        report["runtimeDiagnostics"].append(deepcopy(diagnostic))
    elif attack == "unverified-side":
        diagnostic["validationStatus"] = "unverified"
    elif attack == "missing-reference":
        del diagnostic["rawSnapshotReference"]
    elif attack == "changed-diagnostic-sha":
        diagnostic["sha256"] = "0" * 64
    elif attack == "replaced-coherent-reference":
        other = report["runtimeDiagnostics"][3]
        diagnostic.update({key: deepcopy(other[key]) for key in
                           ("rawSnapshotReference", "evidenceDirectory", "sha256")})
    else:
        diagnostic["rawSnapshots"] = [{}]
    with pytest.raises(HarnessError) as failure:
        _seal_forget_index_fence_references(report, expected)
    assert failure.value.code == "runtime-evidence-changed"
    assert report["cases"][0]["status"] == "blocked"
    assert report["cases"][0]["runtimeEvidenceValidated"] is False
    assert _forget_index_fence_family_complete(report["cases"]) is False


@pytest.mark.parametrize("change", [None, "source", "node", "source-refusal"])
def test_final_original_authority_seal_binds_external_roots_and_blocks_changed_owners(monkeypatch, tmp_path, change):
    bindings = ModuleType("equivalence.forget_index_fence_bindings")
    authority = ModuleType("equivalence.model_runtime_authority")
    selected_reference, runtime_root, node = (tmp_path / name for name in ("reference", "runtime", "node"))
    declared = {"label": "UNIT_SOURCE_ONLY", "sourceBuildReproduced": False, "sourceFallbackAllowed": False}
    executable = {"label": "UNIT_NODE_ONLY", "sha256": "1" * 64}
    calls = []

    def prepare(reference, runtime):
        calls.append(("source", reference, runtime))
        if change == "source-refusal":
            raise ValueError("Labelled source authority refusal; no original execution")
        return {**declared, **({"label": "CHANGED_SOURCE"} if change == "source" else {})}

    def prepare_node(selected):
        calls.append(("node", selected))
        return {**executable, **({"sha256": "2" * 64} if change == "node" else {})}

    bindings.prepare_forget_index_fence_bindings = prepare
    authority.prepare_model_node_authority = prepare_node
    monkeypatch.setitem(sys.modules, bindings.__name__, bindings)
    monkeypatch.setitem(sys.modules, authority.__name__, authority)
    old = {"id": "OLD_INLINE_UNIT", "operation": "echo", "status": "matched"}
    report = {"forgetIndexFenceBindings": deepcopy(declared), "forgetIndexFenceNode": deepcopy(executable),
              "cases": [*_rows(), old]}
    if change is None:
        _seal_forget_index_fence_authorities(report, checkout=selected_reference, node=node, runtime_root=runtime_root)
        assert _forget_index_fence_family_complete(report["cases"]) is True
    else:
        with pytest.raises(HarnessError) as failure:
            _seal_forget_index_fence_authorities(report, checkout=selected_reference, node=node, runtime_root=runtime_root)
        assert failure.value.code == "runtime-evidence-changed"
        assert all(row["runtimeEvidenceValidated"] is False and row["status"] == "blocked"
                   for row in report["cases"][:-1])
        assert _forget_index_fence_family_complete(report["cases"]) is False
    assert calls[0] == ("source", selected_reference, runtime_root)
    if change in {None, "node"}:
        assert calls[1] == ("node", node)
    assert report["cases"][-1] is old and old == {"id": "OLD_INLINE_UNIT", "operation": "echo", "status": "matched"}
    assert report["forgetIndexFenceBindings"] == declared and declared["sourceBuildReproduced"] is False


@pytest.mark.parametrize("mismatch", [False, True])
def test_actual_suite_assembly_keeps_whole_matched_v5_results_and_atomic_eligibility(monkeypatch, tmp_path, mismatch):
    """Run the real coordinator with labelled transports, never original engines."""
    from equivalence import model_runtime_authority, release_runtime

    bindings = ModuleType("equivalence.forget_index_fence_bindings")
    native_module = ModuleType(NATIVE_MODULE)
    guard = ModuleType(GUARD_MODULE)
    declarations = {"label": "UNIT_BINDINGS_ONLY", "sourceBuildReproduced": False}
    bindings.prepare_forget_index_fence_bindings = lambda *args: deepcopy(declarations)
    native_module.NATIVE_KIND = UNIT_NATIVE_KIND
    guard.validate_pair = lambda *args, **kwargs: True
    monkeypatch.setitem(sys.modules, bindings.__name__, bindings)
    monkeypatch.setitem(sys.modules, native_module.__name__, native_module)
    monkeypatch.setitem(sys.modules, guard.__name__, guard)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    (tmp_path / "equivalence").mkdir()
    (tmp_path / "equivalence/release-oracle.mjs").write_text("// UNIT_ONLY: never executed\n")
    reference = {"tag": "UNIT_REFERENCE_ONLY", "commit": "1" * 40}
    monkeypatch.setattr(harness, "_validate_reference", lambda *args: deepcopy(reference))
    monkeypatch.setattr(harness, "_implementation_identity", lambda: {"sourceSha256": "2" * 64})
    monkeypatch.setattr(harness, "_adapter_identity", lambda: {"UNIT_ADAPTER_ONLY": "3" * 64})
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority",
                        lambda *args: {"label": "UNIT_NODE_ONLY"})
    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *args: {
        "runtimeRoot": str(tmp_path / "unit-runtime"), "packages": [], "reference": reference})
    cases, dispatched = build_cases(), []

    def result(case):
        return {"provider": "none", "calls": {"UNIT_WHOLE": {"extra": [False, 0, None], "id": case["id"]}},
                "snapshots": {"UNIT_WHOLE": {"extra": {"retained": True}}}}

    def native(case, node, runtime, directory, *, timeout, checkout):
        dispatched.append(case["id"])
        raw = [{"label": "UNIT_NATIVE_CAPTURE_ONLY", "caseId": case["id"]}]
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_text(json.dumps(raw) + "\n")
        return {"kind": UNIT_NATIVE_KIND, "results": [{"id": case["id"], "ok": True, "result": result(case)}],
                "releaseSources": [], "releaseTrace": {"label": "UNIT_TRACE_ONLY"},
                "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    def sdk(case):
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "python-raw.json").write_text('[{"label":"UNIT_SDK_CAPTURE_ONLY"}]\n')
        value = result(case)
        if mismatch and case["id"] == cases[0]["id"]:
            value["calls"]["UNIT_WHOLE"]["actualDifference"] = "retained"
        return value

    native_module.run_native_case = native
    report, code = harness.run_suite(
        checkout=tmp_path / "unit-reference", node=tmp_path / "unit-node", smoke=True,
        reference_path=ROOT / "equivalence/reference.json", scope_path=ROOT / "equivalence/scope.json",
        oracle_path=ROOT / "equivalence/release-oracle.mjs", cases=cases, python_runner=sdk)
    assert not report["errors"], report["errors"]
    assert dispatched == list(CASE_HASHES) and len(report["cases"]) == 13
    assert code == (1 if mismatch else 0)
    for case, row in zip(cases, report["cases"], strict=True):
        assert row["operation"] == case["operation"] and row["input"] == case["input"]
        assert row["openclaw"] == result(case)
        assert row["python"]["snapshots"] == result(case)["snapshots"]
        assert row["python"]["calls"]["UNIT_WHOLE"]["extra"] == [False, 0, None]
        assert row["runtimeEvidenceValidated"] is True
    assert _forget_index_fence_family_complete(report["cases"]) is (not mismatch)
    requirement = next(item for item in report["requirements"] if item["id"] == "forget.index-fence")
    assert all(item["matchedCaseIds"] == ([] if mismatch else list(CASE_HASHES))
               for item in requirement["acceptance"])
    assert report["fullScopePassed"] is False  # Labelled smoke is never real acceptance.
