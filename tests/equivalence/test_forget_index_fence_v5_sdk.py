"""V5 watch control forwarding through labelled stand-ins; no original engines."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_sdk as sdk
from equivalence.forget_index_fence_v5 import build_cases


class _LabelledWatcher:
    def __init__(self):
        raise AssertionError("The control test must not construct a watcher")

    def start(self):
        raise AssertionError("A readiness control must never start observation")

    def capture_versions(self, paths):
        raise AssertionError("A retained effects control must never recapture")

    def status(self):
        self.calls.append("status")
        return self.current_status

    def snapshot(self):
        self.calls.append("snapshot")
        return self.current_snapshot


class _LabelledOwner:
    def __init__(self):
        raise AssertionError("The control test must not construct an owner")

    @property
    def closed(self):
        return self._closed

    @property
    def memory_watcher(self):
        self.property_reads.append(self._watcher)
        return self._watcher

    def wait_for_memory_watches(self, versions, *, timeout=None):
        self.wait_calls.append({"receiver": self, "versions": deepcopy(versions), "timeout": timeout,
                                "scope": deepcopy(self.observer.local.scope)})
        if self.failure is not None:
            raise self.failure
        return self.actual_return


def _actor():
    watcher = object.__new__(_LabelledWatcher)
    watcher.calls = []
    watcher.current_status = {"started": True, "closed": False, "alive": True, "backend": "inotify"}
    watcher.current_snapshot = {"deliveries": [{"labelled": "complete actual snapshot"}], "settledGeneration": 7}
    watcher._backend = SimpleNamespace(fd=35, paths={Path("/labelled/workspace/memory"): (4, (8, 9))},
                                       descriptors={4: Path("/labelled/workspace/memory")})
    watcher._thread = SimpleNamespace(ident=712, is_alive=lambda: True)
    watcher._pipe = (30, 31)
    owner = object.__new__(_LabelledOwner)
    owner._closed, owner._watcher = False, watcher
    owner.property_reads, owner.wait_calls = [], []
    owner.failure = None
    owner.actual_return = {"status": "completed", "delivery": {"targets": [{"whole": True}]}, "rawCount": 3}
    functions = [_LabelledOwner.memory_watcher.fget, _LabelledOwner.wait_for_memory_watches,
                 _LabelledWatcher.start, _LabelledWatcher.status, _LabelledWatcher.snapshot]
    observer = sdk._OriginalObserver({function.__code__: {"name": function.__qualname__, "receiver": "self",
        "code": {"qualname": function.__qualname__, "source": "labelled-source-cached-before-control"}}
        for function in functions})
    observer.bind_owner(owner, "labelled-owner")
    owner.observer = observer
    actor = sdk._SdkActor.__new__(sdk._SdkActor)
    actor.owner, actor.actor, actor.observer, actor.gates, actor.wall_ms = owner, "labelled-actor", observer, {}, 1234
    return actor, owner, watcher


def _versions():
    return [{"path": "/labelled/workspace/MEMORY.md", "exists": True, "version": {
        "device": "8", "inode": "32", "size": 7, "mtimeNs": "1794614400000000000", "ctimeNs": "1794614400000000001"}}]


def _source_calls():
    return [{"kind": "forget", "label": "selected", "actor": "another-original-actor", "returnSeq": 19,
        "watchTargetCapture": {"callKey": "forget:selected", "mutations": [{"receiptKind": "actual-write",
            "receiptSequence": 17, "receipt": {"whole": "retained original receipt"}, "capture": _versions()}],
            "versions": _versions(), "capturedAtNs": "23", "absence": None}}]


@pytest.mark.parametrize("case", build_cases(), ids=lambda case: case["id"])
def test_exact_v5_literals_are_accepted_without_original_execution(case):
    assert sdk._literal(deepcopy(case["input"])) == case


def test_readiness_reads_existing_resources_and_cached_sources_without_start_or_filesystem_work(monkeypatch):
    actor, owner, watcher = _actor()

    def forbidden(*arguments, **options):
        raise AssertionError("A watch readiness control must not read filesystem metadata or source bytes")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "lstat", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    row = actor.command({"id": 1, "operation": "watch-ready", "label": "ready"})
    assert row["outcome"] == {"status": "ready"}
    assert row["ownerObjectId"] == str(id(owner)) and row["watcherObjectId"] == str(id(watcher))
    assert row["status"] == watcher.current_status and row["snapshot"] == watcher.current_snapshot
    assert row["resources"] == {"backendObjectId": str(id(watcher._backend)), "fd": 35,
        "paths": [{"path": "/labelled/workspace/memory", "watchDescriptor": 4, "identity": [8, 9]}],
        "descriptors": [{"watchDescriptor": 4, "path": "/labelled/workspace/memory"}],
        "shutdownPipe": [30, 31], "threadObjectId": str(id(watcher._thread)), "threadId": 712, "threadAlive": True}
    assert all(role["registered"] and role["code"]["source"].startswith("labelled-source")
               for role in row["sourceRoles"].values())
    assert owner.property_reads == [watcher] and watcher.calls == ["status", "snapshot"]
    assert row["returnSeq"] > row["enterSeq"] and actor.watch_ready_waits[-1] == row
    assert actor.wall_ms == 1234 and owner.wait_calls == []


@pytest.mark.parametrize("absence", ["owner", "closed", "watcher", "not-ready"])
def test_readiness_absence_is_explicit_and_retains_return_sequence(absence):
    actor, owner, watcher = _actor()
    if absence == "owner":
        actor.owner = None
    elif absence == "closed":
        owner._closed = True
    elif absence == "watcher":
        owner._watcher = None
    else:
        watcher.current_status["started"] = False
    row = actor._watch_ready("absent")
    assert row["outcome"]["status"] == "absent"
    assert row["outcome"]["reason"]
    assert row["returnSeq"] > row["enterSeq"] and actor.watch_ready_waits[-1] == row
    assert owner.wait_calls == []


def test_effects_forwards_only_retained_cross_actor_versions_to_exact_existing_owner_once():
    actor, owner, watcher = _actor()
    versions, sources = _versions(), _source_calls()
    before = deepcopy((versions, sources, owner.actual_return))
    row = actor.command({"id": 1, "operation": "watch-effects", "label": "effects",
                         "versions": versions, "sourceCalls": sources})
    assert row["versions"] == versions and row["sourceCalls"] == sources
    assert row["outcome"] == {"status": "fulfilled"} and row["returned"] == owner.actual_return
    assert row["api"]["registered"] is True and row["api"]["receiverObjectId"] == str(id(owner))
    assert len(owner.wait_calls) == 1
    call = owner.wait_calls[0]
    assert call["receiver"] is owner and call["versions"] == versions
    assert call["timeout"] == sdk.PROCESS_TIMEOUT_SECONDS - 5
    assert call["scope"]["label"] == "effects" and call["scope"]["kind"] == "watch-control"
    assert row["returnSeq"] > row["enterSeq"] and actor.watch_effect_waits[-1] == row
    assert watcher.calls == ["status"] and actor.wall_ms == 1234
    assert (versions, sources, owner.actual_return) == before


def test_effects_empty_targets_keep_actual_no_applicable_proof_without_start_or_wait():
    actor, owner, _ = _actor()
    source = [{"kind": "forget", "label": "dryRun", "returnSeq": 4,
               "watchTargetCapture": {"callKey": "forget:dryRun", "mutations": [], "versions": []}}]
    row = actor._watch_effects("dry", [], source)
    assert row["outcome"] == {"status": "no-applicable-targets"}
    assert row["sourceCalls"] == source and row["versions"] == []
    assert row["returnSeq"] > row["enterSeq"] and actor.watch_effect_waits[-1] == row
    assert owner.wait_calls == [] and "returned" not in row
    missing = actor._watch_effects("unproved", [], [])
    assert missing["outcome"] == {"status": "absent", "reason": "no-original-source-call-proof"}


def test_effects_preserves_actual_api_exception_and_full_failed_control_receipt():
    actor, owner, _ = _actor()
    failure = RuntimeError("exact retained-version failure")
    failure.code = "LABELLED_ACTUAL_CODE"
    owner.failure = failure
    with pytest.raises(RuntimeError) as caught:
        actor._watch_effects("failed", _versions(), _source_calls())
    assert caught.value is failure and len(owner.wait_calls) == 1
    row = actor.watch_effect_waits[-1]
    assert row["outcome"] == {"status": "rejected"}
    assert row["error"]["message"] == str(failure) and row["error"]["code"] == failure.code
    assert row["returnSeq"] > row["enterSeq"] and "returned" not in row


def test_host_watch_steps_never_acquire_start_recapture_or_contact_absent_closed_and_dead_owners(tmp_path, monkeypatch):
    processes = {}
    versions, captured_call = _versions(), _source_calls()[0]
    captured_call.update(kind="promotion", label="writer", publicPromotion={"memoryPath": str(tmp_path / "workspace" / "MEMORY.md")})

    class Process:
        def __init__(self, value, directory, actor):
            self.actor, self.counter, self.acquired = actor, 0, False
            self.exit_code = 8 if actor == "dead" else None
            self.child = SimpleNamespace(pid=100 + len(processes), poll=lambda: self.exit_code)
            self.receipt = {"actor": actor, "pid": self.child.pid, "stdinCommands": [], "stdoutResponses": []}
            self.controls = []
            processes[actor] = self

        def command(self, operation, **values):
            self.counter += 1
            command = {"id": self.counter, "operation": operation, **values}
            self.receipt["stdinCommands"].append(deepcopy(command))
            if operation == "acquire":
                self.acquired = True
                result = {"labelledActualAcquisition": True}
            elif operation == "close":
                result = {"closed": True}
            elif operation == "stop":
                self.exit_code = 0
                result = {"stopping": True}
            elif operation == "call":
                result = deepcopy(captured_call)
            elif operation in {"watch-ready", "watch-effects"}:
                self.controls.append(command)
                result = {"actor": self.actor, "label": values["label"], "outcome": {"status": "labelled-control"}}
            else:
                raise AssertionError("A watch control requested undeclared work: " + operation)
            self.receipt["stdoutResponses"].append({"id": self.counter, "ok": True, "result": deepcopy(result)})
            return result

        def reap(self):
            return {"code": self.exit_code}

    actors = ["missing", "unacquired", "closed", "live", "dead"]
    steps = [{"operation": "start-fresh-original-process", "actor": name}
             for name in ("unacquired", "closed", "live", "dead")]
    steps += [{"operation": "acquire-original-owner", "actor": "closed"},
              {"operation": "original-owner-close", "actor": "closed"},
              {"operation": "acquire-original-owner", "actor": "live"},
              {"operation": "await-original-watch-ready", "actors": actors, "label": "ready"},
              {"operation": "original-promotion", "actor": "live", "label": "writer"},
              {"operation": "await-original-watch-effects", "actors": actors, "label": "effects", "afterCalls": ["promotion:writer"]}]
    value = {"kind": "forget-index-fence-v5", "clock": {"nowMs": 1}, "steps": steps,
             "promotions": {"writer": {"labelled": "retained original arguments"}}}
    monkeypatch.setattr(sdk, "_literal", lambda value: value)
    monkeypatch.setattr(sdk, "_sdk_sources", lambda: {"labelled": "source-custody"})
    monkeypatch.setattr(sdk, "_adapter_sources", lambda kind: {"labelled": kind})
    monkeypatch.setattr(sdk, "_ActorProcess", Process)
    raw = sdk.run_forget_index_fence_sdk_host({"input": value, "directory": str(tmp_path)})
    assert raw["complete"] is True, raw.get("error")
    assert "missing" not in processes
    for name in ("unacquired", "closed", "dead"):
        assert processes[name].controls == []
    controls = processes["live"].controls
    assert [command["operation"] for command in controls] == ["watch-ready", "watch-effects"]
    assert controls[-1]["versions"] == versions
    assert controls[-1]["sourceCalls"] == [captured_call]
    for step in raw["steps"]:
        if step["specification"]["operation"].startswith("await-original-watch"):
            absent = {row["actor"]: row["outcome"] for row in step["returned"] if row["actor"] != "live"}
            assert all(outcome["status"] == "absent" for outcome in absent.values())
