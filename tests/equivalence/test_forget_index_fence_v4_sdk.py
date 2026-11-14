"""V4 literals and metadata only; no original SDK owner or engine is constructed."""
from collections import deque
from copy import deepcopy
import hashlib
import inspect

import pytest

from equivalence import forget_index_fence_sdk as sdk
from equivalence.forget_index_fence_v3 import build_cases as build_v3_cases
from equivalence.forget_index_fence_v4 import build_cases as build_v4_cases


V4_CASES = build_v4_cases()


@pytest.mark.parametrize("case", V4_CASES, ids=lambda case: case["id"])
def test_every_frozen_v4_literal_is_accepted_without_running_originals(case):
    assert len(V4_CASES) == 13
    assert sdk._literal(deepcopy(case["input"])) == case


def test_mixed_v3_v4_and_unknown_or_modified_profile_inputs_are_rejected():
    v3, v4 = build_v3_cases()[0]["input"], deepcopy(V4_CASES[0]["input"])
    mixed = [dict(deepcopy(v3), kind=v4["kind"]), dict(deepcopy(v4), kind=v3["kind"]),
             dict(deepcopy(v4), kind="forget-index-fence-v99"), None]
    modified = deepcopy(v4)
    modified["config"]["memory"]["search"]["sync"]["watch"] = True
    mixed.append(modified)
    for value in mixed:
        with pytest.raises(ValueError):
            sdk._literal(value)


def test_v4_custody_selects_exact_version_four_sources_and_never_version_three():
    custody = sdk._adapter_sources("forget-index-fence-v4")
    common = {"equivalence/forget_index_fence_sdk.py", "equivalence/forget_index_fence_sdk_cli.py",
              "equivalence/forget_index_fence_sdk_clock.py"}
    version_four = {"equivalence/forget_index_fence_v4.py", "docs/forget_index_fence_v4_literals.json",
                    "docs/forget_index_fence_v4_plan.md"}
    assert {row["path"] for row in custody["files"]} == common | version_four
    assert len(custody["files"]) == 6
    assert all("_v3" not in row["path"] for row in custody["files"])
    for row in custody["files"]:
        payload = (sdk.ROOT / row["path"]).read_bytes()
        assert row["bytes"] == len(payload) and row["sha256"] == hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError):
        sdk._adapter_sources("forget-index-fence-v99")


def test_all_v4_effects_steps_full_clocks_and_recovery_ticks_are_unchanged_from_v3():
    previous = build_v3_cases()
    assert len(previous) == len(V4_CASES) == 13
    effects, recovery_ticks = 0, []
    for old_case, new_case in zip(previous, V4_CASES, strict=True):
        old, new = old_case["input"], new_case["input"]
        assert old_case["id"].replace("-v3-", "-v4-", 1) == new_case["id"]
        assert new["steps"] == old["steps"]
        assert new["clock"] == old["clock"]
        effects += sum(step["operation"] == "await-original-search-effects" for step in new["steps"])
        recovery_ticks.extend(step["wallClockNowMs"] for step in new["steps"] if "wallClockNowMs" in step)
        assert new["config"]["memory"]["search"]["sync"] == {
            "onSearch": True, "onSessionStart": False, "watch": False}
        assert "sync" not in old["config"]["memory"]["search"]
        normalized = deepcopy(new)
        normalized["kind"], normalized["profile"] = old["kind"], old["profile"]
        del normalized["config"]["memory"]["search"]["sync"]
        assert normalized == old
    assert effects == 101
    assert recovery_ticks == [1794614460001] * 9


class _LabelledMaintenanceOwner:
    def __init__(self, config=None, workspace=None, *, memory_publication="on-write"):
        raise AssertionError("Metadata inspection must not construct any owner")

    def _on_search_snapshot(self, db):
        raise AssertionError("Metadata inspection must not execute a source role")

    def _submit_memory_publication(self, revision):
        raise AssertionError("Metadata inspection must not submit work")

    def bind_session_publication(self, controller):
        raise AssertionError("Metadata inspection must not bind a controller")


def test_search_maintenance_metadata_observes_actual_labelled_owner_without_constructor_or_sdk_watch():
    owner = object.__new__(_LabelledMaintenanceOwner)
    controller, executor = object(), object()
    job = {"id": 7, "state": "running", "readRevision": 4}
    owner._memory_publication = "on-search"
    owner._session_publication = controller
    owner._memory_executor = executor
    owner._memory_active = True
    owner._memory_jobs = deque([job], maxlen=256)
    declared = {"onSearch": True, "onSessionStart": False, "watch": False}
    result = sdk._search_maintenance_binding(owner, declared)
    assert result["declaredNativeSync"] == declared and result["declaredNativeSync"] is not declared
    assert result["constructorParameters"] == list(inspect.signature(_LabelledMaintenanceOwner.__init__).parameters)
    actual = result["actualSdk"]
    assert set(actual) == {"memoryPublication", "sessionPublicationController", "memoryExecutor", "memoryActive", "memoryJobs"}
    assert actual["memoryPublication"] == "on-search" and actual["memoryActive"] is True
    assert actual["sessionPublicationController"]["objectId"] == str(id(controller))
    assert actual["memoryExecutor"]["objectId"] == str(id(executor))
    assert actual["memoryJobs"] == [job]
    assert set(result["sourceRoles"]) == {"constructor", "onSearchSnapshot", "submitMemoryPublication", "bindSessionPublication"}
    for key, name in (("constructor", "__init__"), ("onSearchSnapshot", "_on_search_snapshot"),
                      ("submitMemoryPublication", "_submit_memory_publication"),
                      ("bindSessionPublication", "bind_session_publication")):
        assert result["sourceRoles"][key] == sdk._code_identity(getattr(_LabelledMaintenanceOwner, name).__code__)
    assert "watch" not in actual and "onSessionStart" not in actual
    assert owner._memory_jobs[0] is job and owner._memory_active is True
