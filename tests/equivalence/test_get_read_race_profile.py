"""Closed race-capability guards; labelled files grant no behavioral credit."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence import get_read_race_profile as race


def _case():
    return race.build_storage_path_read_race_cases()[0]


@pytest.fixture
def owners(tmp_path, monkeypatch):
    installation = tmp_path / "runtime"
    runtime = installation / "node_modules/openclaw"
    runtime.mkdir(parents=True)
    hashes = {}
    for relative, anchors in race.OWNER_ANCHORS.items():
        filename = installation / relative
        filename.parent.mkdir(parents=True, exist_ok=True)
        raw = ("// Labelled owner linkage fixture, never executed.\n" + "\n".join(anchors) + "\n").encode()
        filename.write_bytes(raw)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(race, "OWNER_HASHES", hashes)
    return installation, runtime


def test_profile_is_exact_independent_and_has_no_backend_or_source_authority():
    profile = race.validate_get_read_race_profile(race.GET_READ_RACE_PROFILE)
    assert profile is not race.GET_READ_RACE_PROFILE
    assert set(profile) == {"kind", "operation", "inputKind", "hook", "mutation", "module", "sha256"}
    assert profile["operation"] == "get-contract-runtime"
    assert profile["inputKind"] == "tool"
    assert profile["module"] == "node_modules/@openclaw/fs-safe/dist/test-hooks.js"
    assert profile["sha256"] == "207753c214f21d77c7cc82b947f24705c937009a73057ddb08a8ef058334e273"
    profile["hook"] = "unreviewed"
    assert race.GET_READ_RACE_PROFILE["hook"] == "afterPreOpenLstat"


@pytest.mark.parametrize("field", tuple(race.GET_READ_RACE_PROFILE))
@pytest.mark.parametrize("mutation", ("replace", "delete"))
def test_every_scope_or_artifact_field_is_required_and_literal(field, mutation):
    profile = deepcopy(race.GET_READ_RACE_PROFILE)
    if mutation == "replace":
        profile[field] = "unreviewed"
    else:
        del profile[field]
    with pytest.raises(ValueError, match="exact reviewed"):
        race.validate_get_read_race_profile(profile)


@pytest.mark.parametrize("capability", ("sourceCapability", "nodeRuntime", "nativeBackend", "hooks", "callback", "target"))
def test_unknown_authority_cannot_join_the_read_race_profile(capability):
    profile = {**race.GET_READ_RACE_PROFILE, capability: True}
    with pytest.raises(ValueError):
        race.validate_get_read_race_profile(profile)


def test_case_is_one_fixed_owned_mutation_without_acceptance_credit():
    case = _case()
    assert [case] == race.build_storage_path_read_race_cases()
    assert case["covers"] == []
    assert case["requirement"] == "storage.path-safety"
    assert case["input"]["readRace"] == {"kind": "owned-leaf-to-symlink", "hook": "afterPreOpenLstat"}
    assert case["input"]["steps"] == [{"params": {"path": "memory/race.md"}}]
    assert case["input"]["files"] == {"memory/race.md": "Original admitted bytes.\n"}
    assert case["input"]["outsideFiles"] == {"secret.md": "Owned outside sentinel must not be read.\n"}
    assert "intentional fixture rename/symlink" in case["normalizationPolicy"]
    assert json.loads(json.dumps(case, allow_nan=False)) == case
    race.validate_get_read_race_case(case)


@pytest.mark.parametrize("operation", ("get-contract-helper-runtime", "search-contract-runtime", "session-contract-runtime", "storage-read-paths"))
def test_other_operations_cannot_borrow_the_original_get_read_hook(operation):
    case = _case()
    case["operation"] = operation
    with pytest.raises(ValueError, match="unrelated operation"):
        race.validate_get_read_race_case(case)


@pytest.mark.parametrize("mutation", (
    "input-kind", "unknown-hook", "unknown-mutation", "extra-hook", "arbitrary-target",
    "outside-request", "extra-step", "extra-files", "configured-root", "without-snapshots", "numeric-snapshots",
))
def test_runtime_inputs_cannot_widen_the_fixed_read_or_mutation(mutation):
    case = _case()
    value = case["input"]
    if mutation == "input-kind":
        value["kind"] = "definition"
    elif mutation == "unknown-hook":
        value["readRace"]["hook"] = "beforeOpen"
    elif mutation == "unknown-mutation":
        value["readRace"]["kind"] = "arbitrary-write"
    elif mutation == "extra-hook":
        value["readRace"]["beforeOpen"] = True
    elif mutation == "arbitrary-target":
        value["readRace"]["target"] = "/etc/passwd"
    elif mutation == "outside-request":
        value["steps"][0]["params"]["path"] = "../outside/secret.md"
    elif mutation == "extra-step":
        value["steps"].append(deepcopy(value["steps"][0]))
    elif mutation == "extra-files":
        value["files"]["memory/other.md"] = "other"
    elif mutation == "configured-root":
        value["config"] = {"extraPaths": ["$OUTSIDE"]}
    elif mutation == "without-snapshots":
        value["observeFilesystem"] = False
    else:
        value["observeFilesystem"] = 1
    with pytest.raises(ValueError, match="exact owned"):
        race.validate_get_read_race_case(case)


def test_artifact_bindings_pin_setter_callers_and_preopen_order(owners):
    _, runtime = owners
    bindings = race.prepare_get_read_race_bindings(runtime)
    assert {row["path"]: row["sha256"] for row in bindings["compiledBindings"]} == race.OWNER_HASHES
    assert bindings["setterExport"] == "__setFsSafeTestHooksForTest"
    assert bindings["callerEdges"][1] == {
        "owner": "node_modules/@openclaw/fs-safe/dist/local-file-descriptor.js",
        "before": "fsSync.lstatSync", "hook": "afterPreOpenLstat", "after": "fs.open",
    }
    assert bindings["backendOverrides"] is bindings["readResultSubstitution"] is bindings["workerRequired"] is False
    assert race.prepare_get_read_race_profile(_case(), runtime) == race.GET_READ_RACE_PROFILE


@pytest.mark.parametrize("relative", tuple(race.OWNER_HASHES))
def test_changed_official_owner_bytes_are_rejected(owners, relative):
    installation, runtime = owners
    with (installation / relative).open("a") as stream:
        stream.write("// unreviewed drift\n")
    with pytest.raises(ValueError, match="reviewed bytes"):
        race.prepare_get_read_race_profile(_case(), runtime)


@pytest.mark.parametrize("mutation", ("duplicate", "reorder"))
def test_anchor_labels_alone_cannot_establish_the_original_hook_edge(owners, monkeypatch, mutation):
    installation, runtime = owners
    relative = "node_modules/@openclaw/fs-safe/dist/local-file-descriptor.js"
    anchors = list(race.OWNER_ANCHORS[relative])
    if mutation == "duplicate":
        anchors.append(anchors[3])
    else:
        anchors[2], anchors[3] = anchors[3], anchors[2]
    raw = ("\n".join(anchors) + "\n").encode()
    (installation / relative).write_bytes(raw)
    monkeypatch.setitem(race.OWNER_HASHES, relative, hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="linkage|call order"):
        race.prepare_get_read_race_bindings(runtime)


@pytest.mark.parametrize("mutation", ("leaf-symlink", "parent-symlink", "hardlink", "runtime-alias"))
def test_artifact_path_aliases_cannot_inherit_reviewed_authority(owners, mutation):
    installation, runtime = owners
    relative = "node_modules/@openclaw/fs-safe/dist/test-hooks.js"
    filename = installation / relative
    if mutation == "leaf-symlink":
        copied = installation / "copied.js"
        copied.write_bytes(filename.read_bytes())
        filename.unlink()
        filename.symlink_to(copied)
    elif mutation == "parent-symlink":
        original = filename.parent
        moved = original.with_name("moved-dist")
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    elif mutation == "hardlink":
        (installation / "linked.js").hardlink_to(filename)
    else:
        alias = runtime.with_name("alias")
        alias.symlink_to(runtime, target_is_directory=True)
        runtime = alias
    with pytest.raises(ValueError):
        race.prepare_get_read_race_bindings(runtime)
