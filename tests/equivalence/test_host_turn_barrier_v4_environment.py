"""Pure Host v4 admission checks; labelled filesystem doubles are not evidence."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil

import pytest

from equivalence import host_turn_barrier as original
from equivalence import host_turn_barrier_v4 as frozen
from equivalence import host_turn_barrier_v4_environment as environment
from equivalence import host_turn_barrier_v4_evidence as evidence
from equivalence import host_turn_barrier_v4_native as native


def test_four_frozen_probes_keep_whole_original_business_and_zero_credit():
    cases = frozen.build_cases()
    assert len(cases) == 4 and all(case["covers"] == [] for case in cases)
    for case, business in zip(cases, original.build_cases(), strict=True):
        assert frozen.business_case(case) == business
        assert frozen.canonical(case["input"]["businessCase"]) == original.case_wire(business)
        assert hashlib.sha256(frozen.case_wire(case)).hexdigest() == frozen.CASE_HASHES[case["id"]]
        registered = frozen.registered_case(case)
        assert registered == {**case, "covers": business["covers"]}
        assert frozen.business_case(registered) == business
        assert frozen.validate_case(registered, registered=True) == registered
        with pytest.raises(ValueError):
            frozen.validate_case(registered)
    frozen.validate_registration([frozen.registered_case(case) for case in cases])


@pytest.mark.parametrize("attack", ["input", "covers", "id", "operation", "requirement", "extra"])
def test_outer_profile_cannot_change_business_or_earn_credit_implicitly(attack):
    case = frozen.build_cases()[0]
    if attack == "input":
        case["input"]["businessCase"]["input"]["nowMs"] += 1
    elif attack == "covers":
        case["covers"] = list(frozen.POINTS)
    elif attack == "extra":
        case["expectedOutcome"] = "match"
    else:
        case[attack] = "FOREIGN"
    with pytest.raises(ValueError):
        frozen.validate_case(case)


@pytest.mark.parametrize("mode", [0, 1, None, "false"])
def test_registration_mode_requires_an_explicit_boolean(mode):
    with pytest.raises(ValueError, match="Boolean"):
        frozen.validate_case(frozen.build_cases()[0], registered=mode)


@pytest.mark.parametrize(("registered", "timeout"), [(False, 120), (True, 180), (True, 121),
                                                    (False, 181), (True, True)])
def test_real_native_entry_rejects_wrong_mode_bound_before_process_or_state(
        tmp_path, registered, timeout):
    case = frozen.build_cases()[0]
    if registered:
        case = frozen.registered_case(case)
    destination = tmp_path / "not-created"
    with pytest.raises(ValueError, match="second process bound"):
        native.run_native_case(case, None, {}, destination, reference_root=None,
                               timeout=timeout, registered=registered)
    assert not destination.exists()


def test_native_mode_bounds_keep_the_existing_registered_and_probe_limits():
    assert native.process_timeout(True) == 120
    assert native.process_timeout(False) == 180
    with pytest.raises(ValueError, match="Boolean"):
        native.process_timeout(1)


@pytest.mark.parametrize("attack", ["partial", "reordered", "duplicate", "original", "changed"])
def test_promotion_requires_exact_four_covers_only_wrappers(attack):
    cases = [frozen.registered_case(case) for case in frozen.build_cases()]
    if attack == "partial":
        cases.pop()
    elif attack == "reordered":
        cases.reverse()
    elif attack == "duplicate":
        cases.append(deepcopy(cases[0]))
    elif attack == "original":
        cases.append(original.build_cases()[0])
    else:
        cases[0]["input"]["environment"]["contractSha256"] = "0" * 64
    with pytest.raises(ValueError, match="covers-only"):
        frozen.validate_registration(cases)


@pytest.fixture
def labelled_mapping(tmp_path, monkeypatch):
    """Actual layout/identity, explicitly doubled root and absent Git ancestors."""
    capture = tmp_path / "separate-capture"
    capture.mkdir()
    contract = deepcopy(environment.environment_contract())
    contract["environment"]["temporaryRoot"] = str(tmp_path)
    monkeypatch.setattr(environment, "environment_contract", lambda: deepcopy(contract))

    def labelled_ancestors(path):
        value = environment.directory(path, missing=True)
        return [{"path": str(item), "exists": item.exists(),
                 "identity": environment.identity(item) if item.exists() else None,
                 "gitEntryPresent": False} for item in (value, *value.parents)]

    monkeypatch.setattr(environment, "ancestor_facts", labelled_ancestors)
    mapping = environment.allocate_execution(capture, "sdk")
    try:
        yield mapping
    finally:
        shutil.rmtree(mapping["executionRoot"])


def test_actual_layout_and_sdk_original_relative_environment_are_bound(labelled_mapping):
    mapping = labelled_mapping
    before = environment.path_observation(mapping)
    assert before["workspaceAncestors"][0]["exists"] is False
    expected = environment.expected_environment(mapping, source_root=environment.ROOT,
                                                executable="/usr/bin/python3")
    assert expected == {"PATH": "/usr/bin" + os.pathsep + os.defpath,
                        "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONPATH": str(environment.ROOT),
                        "OPENCLAW_HOME": mapping["state"],
                        "OPENCLAW_STATE_DIR": str(Path(mapping["state"]) / "state")}
    Path(mapping["workspace"]).mkdir()
    environment.validate_path_observation(before, mapping, before=True)
    after = environment.path_observation(mapping)
    environment.validate_path_observation(after, mapping, before=False)
    with pytest.raises(ValueError, match="absent execution ancestor"):
        environment.validate_path_observation(before, mapping, before=False)


def test_native_environment_retains_exact_original_initial_five_keys(labelled_mapping):
    mapping = {**labelled_mapping, "engine": "native"}
    context = Path(mapping["captureRoot"]) / "context.json"
    expected = environment.expected_environment(mapping, source_root=environment.ROOT,
                                                executable="/opt/node/bin/node", context_path=context)
    assert expected == {"PATH": "/opt/node/bin" + os.pathsep + os.defpath,
        "LANG": "C.UTF-8", "TZ": "UTC",
        "NODE_OPTIONS": f"--import={environment.ROOT}/equivalence/host-turn-barrier-v4-preload.mjs",
        "MEMORY_EQ_RELEASE_CONTEXT": str(context)}


@pytest.mark.parametrize("attack", ["version", "engine", "extra", "cwd", "workspace", "overlap", "mode", "uid"])
def test_mapping_rejects_escaped_aliasing_or_reassigned_ownership(labelled_mapping, monkeypatch, attack):
    mapping = deepcopy(labelled_mapping)
    if attack == "version":
        mapping["version"] = True
    elif attack == "engine":
        mapping["engine"] = "FOREIGN"
    elif attack == "extra":
        mapping["expectedGitRoot"] = None
    elif attack in {"cwd", "workspace"}:
        mapping[attack] = mapping["captureRoot"]
    elif attack == "overlap":
        mapping["captureRoot"] = mapping["state"]
    elif attack == "mode":
        Path(mapping["executionRoot"]).chmod(0o755)
    else:
        monkeypatch.setattr(environment.os, "getuid", lambda: os.stat(mapping["executionRoot"]).st_uid + 1)
    with pytest.raises(ValueError):
        environment.validate_mapping(mapping)


def test_cwd_symlink_and_parent_traversal_are_rejected(labelled_mapping):
    mapping = labelled_mapping
    cwd = Path(mapping["cwd"])
    alias = cwd.with_name("alias")
    alias.symlink_to(cwd, target_is_directory=True)
    for path in (str(alias), str(cwd / ".." / "cwd")):
        with pytest.raises(ValueError, match="aliased|traversing"):
            environment.directory(path)


@pytest.mark.parametrize("attack", ["identity", "capture", "ancestors", "git", "absent", "existsType"])
def test_path_observation_rejects_forged_owner_or_ancestor_facts(labelled_mapping, attack):
    mapping = labelled_mapping
    receipt = environment.path_observation(mapping)
    if attack == "identity":
        receipt["executionIdentity"]["inode"] = "0"
    elif attack == "capture":
        receipt["captureIdentity"]["device"] = "0"
    elif attack == "ancestors":
        receipt["cwdAncestors"].pop()
    elif attack == "git":
        receipt["workspaceAncestors"][0]["gitEntryPresent"] = True
    elif attack == "absent":
        receipt["cwdAncestors"][0].update(exists=False, identity=None)
    else:
        receipt["cwdAncestors"][0]["exists"] = 1
    with pytest.raises(ValueError):
        environment.validate_path_observation(receipt, mapping, before=True)


def test_git_ancestry_guard_rejects_a_file_marker_without_deleting_it(tmp_path):
    marker = tmp_path / ".git"
    marker.write_bytes(b"LABELLED_GIT_MARKER")
    child = tmp_path / "cwd"
    child.mkdir()
    with pytest.raises(ValueError, match="Git ancestry"):
        environment.ancestor_facts(child)
    assert marker.read_bytes() == b"LABELLED_GIT_MARKER"


@pytest.mark.parametrize("registered", [False, True])
def test_combined_guard_passes_whole_unchanged_objects_to_original_business_guard(
        tmp_path, monkeypatch, registered):
    case = frozen.build_cases()[0]
    if registered:
        case = frozen.registered_case(case)
    native, sdk = tmp_path / "native", tmp_path / "sdk"
    native.mkdir()
    sdk.mkdir()
    native_raw = {"raw": ["WHOLE", {"warning": "RETAINED", "corpora": []}]}
    sdk_raw = {"argv": ["python", "-m", "ACTUAL_EXECUTED_CLI"], "hostV4": {"initialArgv": ["STARTUP"]}}
    native_result = {"warning": "ACTUAL", "corpora": [], "surrogate": "\ud800"}
    sdk_result = deepcopy(native_result)
    calls = []
    monkeypatch.setattr(evidence, "_native_environment", lambda *args, **kwargs: calls.append(("native", args)))
    monkeypatch.setattr(evidence, "_sdk_environment", lambda *args, **kwargs: calls.append(("sdk", args)))

    def original_guard(business, raw_n, raw_s, public_n, public_s):
        assert business == original.build_cases()[0]
        assert raw_n is native_raw and raw_s is sdk_raw
        assert public_n is native_result and public_s is sdk_result
        calls.append(("business", business))
        return True

    monkeypatch.setattr(evidence, "validate_business_pair", original_guard)
    before = deepcopy((native_raw, sdk_raw, native_result, sdk_result))
    assert evidence.validate_pair(case, native_raw, sdk_raw, native_result, sdk_result,
        native_directory=native, sdk_directory=sdk, approved_node={"LABELLED": True},
        approved_runtime={}, approved_reference=environment.ROOT,
        approved_source_root=environment.ROOT, registered=registered) is True
    assert [item[0] for item in calls] == ["native", "sdk", "business"]
    assert before == (native_raw, sdk_raw, native_result, sdk_result)
