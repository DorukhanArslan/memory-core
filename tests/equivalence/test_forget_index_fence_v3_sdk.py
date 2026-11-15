"""V3 control tests use genuine stdlib Futures/conditions, never memory engines."""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
import inspect
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import threading
from types import SimpleNamespace

import pytest

from equivalence.forget_index_fence_sdk import (
    _OriginalObserver,
    _SdkActor,
    _await_existing_search_effects,
    _code_identity,
    _search_factory_capabilities,
    _literal,
    _original_bindings,
    _validated_sdk_root,
)


class _NotifyingCondition(threading.Condition):
    """Signal test coordination, then execute the real Condition.wait."""

    def __init__(self):
        super().__init__()
        self.wait_entered = threading.Event()

    def wait(self, timeout=None):
        self.wait_entered.set()
        return super().wait(timeout)


class _LabelledOwner:
    def __init__(self):
        self._condition = _NotifyingCondition()
        self._memory_active = False
        self._memory_jobs = []
        self._full_sync = None

    def search(self, *arguments, **options):
        raise AssertionError("An effects wait must not query")

    reindex = reindex_sources = close = search


def _task(kind, future, owner, job=None):
    return {"receipt": {"kind": kind, "scope": {"label": "query", "kind": "search"},
                         "futureObjectId": str(id(future)), "storeObjectId": str(id(owner))},
            "future": future, "store": owner, "job": job}


def test_effects_wait_joins_real_recall_future_then_original_condition_notification_and_publisher_future():
    owner = _LabelledOwner()
    recall, publication = Future(), Future()
    recall_started = threading.Event()
    owner._memory_active = True
    job = {"state": "running", "id": "labelled-existing-job"}
    owner._memory_jobs.append(job)

    class Tool:
        def wait_for_recalls(self, timeout=None):
            recall_started.set()
            return recall.result(timeout)

    tool, receipt, result = Tool(), {}, {}
    tasks = [_task("recall", recall, owner), _task("memory-publication", publication, owner, job)]

    def wait():
        result["returned"] = _await_existing_search_effects(tool, owner, tasks, receipt, timeout=5)

    thread = threading.Thread(target=wait)
    thread.start()
    try:
        assert recall_started.wait(5)
        assert thread.is_alive() and not owner._condition.wait_entered.is_set()
        recall.set_result(None)
        assert owner._condition.wait_entered.wait(5)
        with owner._condition:
            assert thread.is_alive()
            owner._memory_active = False
            job["state"] = "completed"
            owner._condition.notify_all()
        # Readiness notification alone is insufficient: the actual producer's
        # Future is still unfinished until its original return settles.
        publication.set_result({"labelledActualReturn": 7})
    finally:
        if not recall.done():
            recall.set_result(None)
        with owner._condition:
            owner._memory_active = False
            owner._condition.notify_all()
        if not publication.done():
            publication.set_result(None)
        thread.join(5)
    assert not thread.is_alive() and result["returned"] is receipt
    assert receipt["conditionObjectId"] == str(id(owner._condition))
    assert len(receipt["conditionWaits"]) == 1 and receipt["conditionWaits"][0]["returned"] is True
    assert receipt["publisherFutures"][0]["returned"] == {"labelledActualReturn": 7}
    assert all(task["future"]["state"] == "FINISHED" for task in receipt["tasksAtReturn"])


def test_baseline_tool_without_recall_capability_performs_no_recall_wait_or_new_work():
    owner, tool, receipt = _LabelledOwner(), object(), {}
    result = _await_existing_search_effects(tool, owner, [], receipt, timeout=1)
    assert result is receipt
    assert receipt["recall"] == {"supported": False, "futureObjectIds": []}
    assert receipt["conditionWaits"] == [] and receipt["publisherFutures"] == []


def test_unqualified_busy_publisher_fails_without_waiting_or_manufacturing_a_future():
    owner, receipt = _LabelledOwner(), {}
    owner._memory_active = True
    with pytest.raises(RuntimeError, match="no captured search-origin submission"):
        _await_existing_search_effects(object(), owner, [], receipt, timeout=1)
    assert receipt["conditionWaits"] == [] and owner._memory_active is True


def test_v5_partition_leaves_an_unrelated_watch_publisher_for_its_declared_frontier():
    owner, receipt = _LabelledOwner(), {}
    owner._memory_active = True  # Labelled foreign job, no query-owned Future.
    returned = _await_existing_search_effects(object(), owner, [], receipt, timeout=1, partition_watch=True)
    assert returned is receipt and receipt["partition"] == "retained-search-jobs"
    assert receipt["conditionWaits"] == [] and receipt["publisherFutures"] == []
    assert owner._memory_active is True


def test_actual_unfinished_future_hits_only_the_bounded_watchdog():
    owner, future, receipt = _LabelledOwner(), Future(), {}

    class Tool:
        def wait_for_recalls(self, timeout=None):
            return future.result(timeout)

    with pytest.raises(TimeoutError):
        _await_existing_search_effects(Tool(), owner, [_task("recall", future, owner)], receipt, timeout=0.01)
    assert not future.done() and "returnedAtNs" not in receipt


def test_real_future_result_return_keeps_verified_entry_receiver_when_stdlib_finally_clears_self():
    payload = {"actualReturn": [7, None, {"whole": True}]}
    future = Future()
    future.set_result(payload)
    code = Future.result.__code__
    observer = _OriginalObserver({code: {"name": "Future.result", "receiver": "self", "code": _code_identity(code)}})
    observer.bind_owner(future, "actual-stdlib-future")
    previous = sys.getprofile()
    try:
        sys.setprofile(observer.profile)
        with observer.call_scope("actual-query", "search", 1234):
            returned = future.result(timeout=1)
    finally:
        sys.setprofile(previous)
    assert returned is payload
    call, result = observer.events
    assert call["event"] == "original-call" and result["event"] == "original-return"
    assert result["callSequence"] == call["sequence"] and result["returned"] == payload
    assert call["receiverObjectId"] == str(id(future)) and result["owner"] == "actual-stdlib-future"
    lookup = result["returnLookup"]
    assert lookup["strategy"] == "retained-entry-frame"
    assert lookup["frameObjectId"] == call["frameObjectId"]
    assert lookup["entryCallSequence"] == call["sequence"] and lookup["entryCode"] == call["code"]
    assert lookup["entryReceiverObjectId"] == str(id(future))
    assert lookup["receiverLocalName"] == "self" and lookup["receiverLocalPresent"] is True
    assert lookup["receiverLocal"] is None  # The actual stdlib finally block ran unchanged.
    assert observer.local.stack == ()


def _old_factory(config, store, *, context=None):
    raise AssertionError("Capability inspection must never execute a factory")


def _new_factory(config, store, *, context=None, recall_origins=None, on_event=None):
    raise AssertionError("Capability inspection must never execute a factory")


def test_capabilities_follow_actual_signatures_and_source_instead_of_a_version_label():
    old, new = _search_factory_capabilities(_old_factory), _search_factory_capabilities(_new_factory)
    assert old["recallOrigins"] is False and old["onEvent"] is False
    assert new["recallOrigins"] is True and new["onEvent"] is True
    assert old["signature"] == str(inspect.signature(_old_factory))
    assert old["source"] == _code_identity(_old_factory.__code__)
    assert new["source"] == _code_identity(_new_factory.__code__)


def test_sdk_source_root_must_be_explicit_existing_and_unaliased(tmp_path):
    root = tmp_path / "baseline"
    (root / "memory_core").mkdir(parents=True)
    (root / "memory_core/__init__.py").write_text("# labelled source-only root\n")
    assert _validated_sdk_root(root) == root
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    for invalid in (alias, tmp_path / "missing", Path("relative")):
        with pytest.raises(ValueError, match="independently selected absolute source root"):
            _validated_sdk_root(invalid)


def test_v3_dispatch_authenticates_the_new_frozen_family_and_preserves_v2_literals():
    from equivalence.forget_index_fence_v2 import build_cases as v2_cases
    from equivalence.forget_index_fence_v3 import build_cases as v3_cases

    old, new = v2_cases(), v3_cases()
    assert len(old) == len(new) == 13
    assert all(_literal(case["input"])["id"] == case["id"] for case in [*old, *new])
    assert sum(step["operation"] == "await-original-search-effects"
               for case in new for step in case["input"]["steps"]) == 101


def test_explicit_effects_step_refuses_inflight_or_foreign_owner_and_checks_settlement_before_capture():
    owner, tool = _LabelledOwner(), object()
    actor = _SdkActor.__new__(_SdkActor)
    actor.value = {"kind": "forget-index-fence-v3", "observationPolicy": {"searchEffects": {"maxReferencesPerBarrier": 256}}}
    actor.actor, actor.owner, actor.wall_ms = "foreground", owner, 1234
    actor.gates, actor.search_effect_waits = {}, []
    actor.observer = _OriginalObserver({})
    actor.public_calls = {"search:query": {"pid": os.getpid()}}
    actor.search_tools = {"query": {"tool": tool, "owner": owner, "capabilities": {"labelled": "old pure factory"},
                                    "tasksAtPublicSettle": ()}}
    command = {"id": 1, "operation": "await-search-effects", "label": "query"}
    with pytest.raises(ValueError, match="settled original search"):
        actor.command(command)
    actor.public_calls["search:query"]["returnSeq"] = 77
    actor.search_tools["query"]["owner"] = _LabelledOwner()
    with pytest.raises(ValueError, match="settled original search"):
        actor.command(command)
    actor.search_tools["query"]["owner"] = owner
    with pytest.raises(RuntimeError, match="declared effects barrier"):
        actor._assert_search_effects_settled()
    receipt = actor.command(command)
    assert receipt["recall"]["supported"] is False and receipt["tasksAtEntry"] == []
    assert receipt["publicReturnSequence"] == 77
    actor.search_tools["held"] = {"owner": owner}
    actor.public_calls["search:held"] = {"pid": os.getpid()}
    actor._assert_search_effects_settled()  # An actually held call remains untouched.
    assert actor.public_calls["search:query"] == {"pid": os.getpid(), "returnSeq": 77}
    actor.value["kind"] = "forget-index-fence-v2"
    with pytest.raises(ValueError, match="separately frozen V3"):
        actor.command(command)


def test_lease_registry_uses_actual_generator_bodies_and_returned_owner_without_acquiring():
    codes = _original_bindings()
    if importlib.util.find_spec("memory_core.host.reindex_lease") is None:
        assert not any(row["name"].startswith("_ReindexLease.") or row["name"] == "_lease_for" for row in codes.values())
        return
    from memory_core.host.reindex_lease import _ReindexLease, _lease_for, memory_index_producer_guard

    assert codes[_lease_for.__code__]["bindReturnedOwner"] == "original-reindex-producer-lease"
    assert codes[memory_index_producer_guard.__wrapped__.__code__]["receiver"] is None
    assert codes[_ReindexLease.waiting.__wrapped__.__code__]["receiver"] == "self"
    for name in ("_open_database", "try_acquire", "release", "_close"):
        assert codes[getattr(_ReindexLease, name).__code__]["receiver"] == "self"


def _labelled_lease_open(self):
    raise AssertionError("A labelled source frame is never executed")


def _labelled_lease_continue(self):
    raise AssertionError("A labelled source frame is never executed")


def test_coordination_connection_handoff_keeps_creator_and_actual_current_execute_scope_separate(tmp_path):
    owner = SimpleNamespace(path=tmp_path / "owned-index.reindex-lock.sqlite")
    observer = _OriginalObserver({
        _labelled_lease_open.__code__: {"name": "_ReindexLease._open_database", "receiver": "self",
                                        "code": _code_identity(_labelled_lease_open.__code__)},
        _labelled_lease_continue.__code__: {"name": "_ReindexLease.try_acquire", "receiver": "self",
                                            "code": _code_identity(_labelled_lease_continue.__code__)},
    })
    observer.bind_owner(owner, "labelled-coordination-owner")
    db = sqlite3.connect(owner.path, check_same_thread=False)

    def execute(function, label, query):
        frame = SimpleNamespace(f_code=function.__code__, f_locals={"self": owner})
        with observer.call_scope(label, "search"):
            observer.profile(frame, "call", None)
            observer.profile(frame, "c_call", db.execute)
            db.execute(query).fetchall()
            observer.profile(frame, "c_return", db.execute)
            observer.profile(frame, "return", None)

    try:
        execute(_labelled_lease_open, "creator", "SELECT 1")
        thread = threading.Thread(target=execute, args=(_labelled_lease_continue, "continued", "SELECT 2"))
        thread.start()
        thread.join(5)
        assert not thread.is_alive()
        first, second = observer.sql
        assert [row["statement"] for row in observer.sql] == ["SELECT 1", "SELECT 2"]
        assert first["connectionOpenedByScope"]["label"] == second["connectionOpenedByScope"]["label"] == "creator"
        assert second["callLabel"] == second["callScope"]["label"] == "continued"
        assert second["source"] == "_ReindexLease._open_database"
        assert observer.sql_executions[1]["source"] == "_ReindexLease.try_acquire"
        assert observer.sql_executions[1]["ownerDatabasePath"] == str(owner.path)
        assert first["connectionId"] == second["connectionId"] == str(id(db))
    finally:
        db.close()


class _LabelledPublisher:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def run(self, job, token):
        self.entered.set()
        assert self.release.wait(5)
        return job["value"]


def test_original_submit_captures_actual_job_before_new_thread_and_future_identity_without_relabeling():
    publisher = _LabelledPublisher()
    codes = {
        ThreadPoolExecutor.submit.__code__: {"name": "ThreadPoolExecutor.submit", "receiver": None,
                                            "code": _code_identity(ThreadPoolExecutor.submit.__code__)},
        _LabelledPublisher.run.__code__: {"name": "ManagedSQLiteMemoryStore._run_memory_publication", "receiver": "self",
                                         "code": _code_identity(_LabelledPublisher.run.__code__)},
    }
    observer = _OriginalObserver(codes)
    observer.bind_owner(publisher, "labelled-actual-publisher")
    old_profile, old_thread_profile = sys.getprofile(), threading.getprofile()
    job, token = {"value": 13}, object()
    try:
        sys.setprofile(observer.profile)
        threading.setprofile(observer.profile)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with observer.call_scope("actual-query", "search", 1234):
                future = executor.submit(publisher.run, job, token)
            assert publisher.entered.wait(5)
            task, = observer.submitted_tasks
            assert task["future"] is future and task["job"] is job and task["store"] is publisher
            assert task["receipt"]["futureObjectId"] == str(id(future))
            assert task["receipt"]["jobObjectId"] == str(id(job))
            assert task["receipt"]["scope"] == {"label": "actual-query", "kind": "search", "wallClockNowMs": 1234}
            publisher.release.set()
            assert future.result(timeout=5) == 13
    finally:
        publisher.release.set()
        sys.setprofile(old_profile)
        threading.setprofile(old_thread_profile)
    calls = [row for row in observer.events if row.get("name") == "ManagedSQLiteMemoryStore._run_memory_publication"]
    assert len(calls) == 2 and all(row["callLabel"] == "actual-query" for row in calls)
    snapshot = observer.task_receipts()
    assert snapshot[0]["future"]["state"] == "FINISHED" and snapshot[0]["future"]["result"] == 13
    assert job == {"value": 13} and deepcopy(snapshot) == snapshot
