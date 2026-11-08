"""Fixture guards; actual equivalence still requires the authenticated native run."""
from copy import deepcopy
import errno
import inspect
import json
from pathlib import Path

import pytest

from equivalence.flush_target import (
    EXISTING_HEX, TARGET, build_flush_target_cases, run_flush_target,
)
from memory_core.memory_flush import ensure_memory_flush_target_file


def test_flush_target_fixtures_are_reproducible_unique_and_do_not_claim_full_acceptance():
    cases = build_flush_target_cases()
    assert cases == build_flush_target_cases()
    assert len(cases) == 22
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["covers"] == [] and case["operation"] == "flush-target" for case in cases)
    assert all("hard links" in case["declaredDeviation"] for case in cases)
    assert {case["input"].get("rejectAt") for case in cases} == {None, 1, 2, 3}
    assert {case["input"].get("failOperation") for case in cases} == {None, "mkdir", "open", "close"}


def test_flush_target_transport_preserves_inputs_and_returns_complete_json():
    for case in build_flush_target_cases():
        before = deepcopy(case)
        output = run_flush_target(case["input"])
        assert before == case
        json.dumps(output, allow_nan=False)
        assert all(item["closed"] for item in output["descriptors"])
        assert all(item["closeCalls"] == 1 for item in output["descriptors"])
        if "existingHex" in case["input"]:
            assert output["files"] == {TARGET: {"hex": EXISTING_HEX}}


def test_invalid_path_is_rejected_before_authority_or_filesystem_mutations():
    for case in build_flush_target_cases():
        if "-invalid-" not in case["id"]:
            continue
        output = run_flush_target(case["input"])
        assert output["ok"] is False
        assert output["error"]["kind"] == "validation"
        assert output["checks"] == 0
        assert output["events"] == []
        assert output["files"] == {}
        assert output["directories"] == []
        assert output["descriptors"] == []


def test_legacy_helper_is_actually_executed_and_missing_authority_is_visible():
    output = run_flush_target({"relativePath": TARGET, "rejectAt": 1})
    supported = "assert_current" in inspect.signature(ensure_memory_flush_target_file).parameters
    assert output["authorityCallbackSupported"] is supported
    if supported:
        assert output["checks"] == 1
        assert output["files"] == {}
        assert output["events"] == ["assert:1"]
    else:
        assert output["checks"] == 0
        assert output["ok"] is True
        assert output["files"] == {TARGET: {"hex": ""}}
        assert output["events"] == ["mkdir:memory", f"open:{TARGET}", f"close:{TARGET}"]


def test_injected_close_failure_keeps_actual_handle_closure_and_existing_bytes_visible():
    output = run_flush_target({"relativePath": TARGET, "existingHex": EXISTING_HEX,
                               "failOperation": "close"})
    assert output["error"] == {"kind": "os", "code": "EIO", "operation": "close", "path": TARGET}
    assert output["descriptors"] == [{"opened": True, "closeCalls": 1, "closed": True}]
    assert output["files"] == {TARGET: {"hex": EXISTING_HEX}}


def test_mkdir_failure_is_injected_at_operation_boundary_for_existing_directory():
    original_mkdir = Path.mkdir
    output = run_flush_target({"relativePath": TARGET, "existingHex": EXISTING_HEX,
                               "failOperation": "mkdir"})
    assert Path.mkdir is original_mkdir
    assert output["error"] == {
        "kind": "os", "code": "EACCES", "operation": "mkdir", "path": "memory",
    }
    assert output["events"] == (
        ["assert:1", "mkdir:memory"] if output["authorityCallbackSupported"] else ["mkdir:memory"]
    )
    assert output["descriptors"] == []
    assert output["directories"] == ["memory"]
    assert output["files"] == {TARGET: {"hex": EXISTING_HEX}}


@pytest.mark.parametrize("check", (1, 2, 3))
def test_authority_stage_retains_concrete_filesystem_and_descriptor_effects(check):
    output = run_flush_target({"relativePath": TARGET, "rejectAt": check})
    if not output["authorityCallbackSupported"]:
        # Legacy behavior is exposed by the dedicated test and actual first report.
        assert output["checks"] == 0 and output["ok"] is True
        return
    assert output["error"] == {
        "kind": "authority", "reason": "revoked", "check": check,
        "message": f"Flush target revoked at check {check}",
    }
    assert output["checks"] == check
    assert output["directories"] == ([] if check == 1 else ["memory"])
    assert output["files"] == ({TARGET: {"hex": ""}} if check == 3 else {})
    assert output["descriptors"] == (
        [{"opened": True, "closeCalls": 1, "closed": True}] if check == 3 else []
    )
    assert output["events"] == {
        1: ["assert:1"],
        2: ["assert:1", "mkdir:memory", "assert:2"],
        3: ["assert:1", "mkdir:memory", "assert:2", f"open:{TARGET}", "assert:3", f"close:{TARGET}"],
    }[check]


def test_undeclared_os_failure_retains_diagnostics_instead_of_declared_errno_normalization(monkeypatch):
    from memory_core import memory_flush

    def fail(root, relative_path, *, assert_current):
        raise OSError(errno.ENOSPC, "Unexpected full device", str(root / relative_path))

    monkeypatch.setattr(memory_flush, "ensure_memory_flush_target_file", fail)
    output = run_flush_target({"relativePath": TARGET})
    assert output["error"] == {
        "kind": "unexpected", "name": "OSError", "errno": errno.ENOSPC,
        "filename": f"@workspace/{TARGET}",
        "message": f"[Errno {errno.ENOSPC}] Unexpected full device: '@workspace/{TARGET}'",
    }
    assert output["events"] == []
    assert output["files"] == {}
    assert output["directories"] == []


@pytest.mark.parametrize("arguments", [
    {"failOperation": "invented"}, {"rejectAt": 4}, {"authorityError": "invented"},
])
def test_unknown_fixture_controls_are_errors(arguments):
    with pytest.raises(ValueError, match="Unsupported flush target"):
        run_flush_target({"relativePath": TARGET, **arguments})
