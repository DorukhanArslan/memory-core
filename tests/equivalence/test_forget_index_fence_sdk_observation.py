"""Pure observer/protocol regressions; no original memory engine is executed."""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from equivalence.forget_index_fence_sdk import (
    _OriginalObserver,
    _common_calls,
    _common_snapshot,
    _code_identity,
    _encode,
    _error,
    _files,
    _full_stat,
    _safe_path,
    _select_snapshot_receiver,
    _validate_actor_command,
)


def _labelled_method(self, argument=None):
    raise AssertionError("A labelled stand-in must never be executed")


def _unrelated_method(self):
    raise AssertionError("An unrelated stand-in must never be executed")


def _labelled_public(context, store):
    raise AssertionError("The public stand-in must never be executed")


def _labelled_worker(context, store):
    raise AssertionError("The worker stand-in must never be executed")


def _frame(function, **values):
    return SimpleNamespace(f_code=function.__code__, f_locals=values)


def _specification(name, receiver):
    return {"name": name, "receiver": receiver, "code": {"source": "labelled-test-only"}}


class _LabelledSnapshotProcess:
    """Only protocol lifecycle state; this receiver runs no memory engine."""

    def __init__(self, actor, pid):
        self.actor, self.acquired = actor, False
        self.exit_code = None
        self.child = SimpleNamespace(pid=pid, poll=lambda: self.exit_code)
        self.commands = []

    def command(self, operation, **values):
        if self.exit_code is not None:
            raise ValueError("I/O operation on closed file.")
        self.commands.append({"operation": operation, **values})
        if operation == "acquire":
            self.acquired = True
        if operation == "snapshot":
            return {"actor": self.actor, "pid": self.child.pid, "label": values["label"],
                    "labelledRawBytes": "unchanged physical receiver return"}

    def reap(self, code=0):
        self.exit_code = code


def test_snapshot_after_retry_uses_live_acquired_receiver_without_restarting_reaped_foreground():
    foreground = _LabelledSnapshotProcess("foreground", 101)
    killed_forgetter = _LabelledSnapshotProcess("forgetter", 102)
    builder = _LabelledSnapshotProcess("builder", 103)
    for process in (foreground, killed_forgetter, builder):
        process.command("acquire")
    killed_forgetter.reap(-9)
    for process in (builder, foreground):
        process.command("close")
        process.command("stop")
        process.reap()
    retry_forgetter = _LabelledSnapshotProcess("forgetter", 104)
    retry_forgetter.command("acquire")
    retry_forgetter.command("call", kind="forget", label="retry")
    actors = {"foreground": foreground, "forgetter": retry_forgetter, "builder": builder}
    command_counts = [len(process.commands) for process in actors.values()]

    receiver, receipt = _select_snapshot_receiver(actors)
    assert receiver is retry_forgetter
    assert [len(process.commands) for process in actors.values()] == command_counts
    returned = receiver.command("snapshot", label="afterRestartedForgetRetry")

    assert returned == {"actor": "forgetter", "pid": 104, "label": "afterRestartedForgetRetry",
                        "labelledRawBytes": "unchanged physical receiver return"}
    assert receipt == {"requestedActor": None, "preferredActor": "foreground", "selectedActor": "forgetter",
                       "pid": 104, "reason": "implicit-live-acquired-fallback", "candidates": [
                           {"actor": "foreground", "pid": 101, "poll": 0, "acquired": True},
                           {"actor": "forgetter", "pid": 104, "poll": None, "acquired": True},
                           {"actor": "builder", "pid": 103, "poll": 0, "acquired": True}]}
    assert foreground.commands[-1] == {"operation": "stop"}
    assert sum(command["operation"] == "acquire" for command in retry_forgetter.commands) == 1


def test_snapshot_prefers_original_foreground_and_respects_explicit_other_receiver():
    actors = {name: _LabelledSnapshotProcess(name, pid) for name, pid in (("foreground", 111), ("forgetter", 112))}
    for process in actors.values():
        process.command("acquire")
    selected, receipt = _select_snapshot_receiver(actors)
    assert selected is actors["foreground"] and receipt["reason"] == "implicit-foreground-live-acquired"
    selected, receipt = _select_snapshot_receiver(actors, "forgetter")
    assert selected is actors["forgetter"] and receipt["requestedActor"] == "forgetter"
    assert receipt["reason"] == "explicit-live-acquired-actor"


@pytest.mark.parametrize("state", ["missing", "unacquired", "reaped"])
def test_snapshot_explicit_unavailable_receiver_never_falls_back(state):
    live = _LabelledSnapshotProcess("forgetter", 122)
    live.command("acquire")
    actors = {"forgetter": live}
    if state != "missing":
        actors["foreground"] = _LabelledSnapshotProcess("foreground", 121)
        if state == "reaped":
            actors["foreground"].command("acquire")
            actors["foreground"].reap()
    with pytest.raises(ValueError, match="selected SDK snapshot actor is not live and acquired"):
        _select_snapshot_receiver(actors, "foreground")
    assert live.commands == [{"operation": "acquire"}]


def test_snapshot_without_any_live_acquired_receiver_refuses_without_acquiring():
    unopened = _LabelledSnapshotProcess("foreground", 131)
    reaped = _LabelledSnapshotProcess("builder", 132)
    reaped.command("acquire")
    reaped.reap()
    with pytest.raises(ValueError, match="already live and acquired"):
        _select_snapshot_receiver({"foreground": unopened, "builder": reaped})
    assert unopened.commands == []


def test_observer_requires_exact_code_receiver_and_labelled_scope_without_executing_them(monkeypatch):
    owner, unrelated_owner = object(), object()
    code = _labelled_method.__code__
    gate_calls = []
    observer = _OriginalObserver({code: _specification("labelled-method", "self")},
        gate_callback=lambda *arguments: gate_calls.append(arguments))
    observer.bind_owner(owner, "actual-owner")
    frame = _frame(_labelled_method, self=owner, argument={"raw": 7})

    def forbid_source_lookup(*arguments, **options):
        raise AssertionError("An in-flight observer must not read a source file")

    monkeypatch.setattr(Path, "read_bytes", forbid_source_lookup)
    observer.profile(frame, "call", None)
    assert observer.events == []
    with observer.call_scope("actual-call", "sync"):
        observer.profile(_frame(_labelled_method, self=unrelated_owner), "call", None)
        observer.profile(_frame(_unrelated_method, self=owner), "call", None)
        observer.profile(frame, "c_call", object())
        observer.profile(frame, "call", None)
        observer.profile(frame, "return", 3)

    assert [row["event"] for row in observer.events] == ["original-call", "original-return"]
    call, returned = observer.events
    assert call["owner"] == "actual-owner" and call["exactReceiver"] is True
    assert call["receiverObjectId"] == str(id(owner))
    assert call["arguments"] == {"argument": {"raw": 7}}
    assert call["callLabel"] == "actual-call" and call["callKind"] == "sync"
    assert returned["callSequence"] == call["sequence"]
    assert type(returned["returned"]) is int and returned["returned"] == 3
    assert len(gate_calls) == 2 and all(arguments[0] is frame for arguments in gate_calls)
    assert observer.owners[id(owner)][0] is owner
    assert getattr(observer.local, "scope", None) is None
    assert observer.local.stack == ()


def test_worker_attribution_uses_the_exact_saved_context_and_store_on_another_thread():
    owner, other_owner, context, other_context = object(), object(), object(), object()
    observer = _OriginalObserver({
        _labelled_public.__code__: _specification("labelled-public", None),
        _labelled_worker.__code__: _specification("labelled-worker", None),
    })
    observer.bind_owner(owner, "actual-owner")
    public = _frame(_labelled_public, context=context, store=owner)
    with observer.call_scope("public-query", "search"):
        observer.profile(public, "call", None)
        observer.profile(public, "return", {"complete": True})
    worker_thread_ids = []

    def observe_worker():
        worker_thread_ids.append(threading.get_ident())
        for invalid in (
            _frame(_labelled_worker, context=other_context, store=owner),
            _frame(_labelled_worker, context=context, store=other_owner),
            _frame(_unrelated_method, context=context, store=owner),
        ):
            observer.profile(invalid, "call", None)
        worker = _frame(_labelled_worker, context=context, store=owner)
        observer.profile(worker, "call", None)
        observer.profile(worker, "return", False)

    thread = threading.Thread(target=observe_worker)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert worker_thread_ids and worker_thread_ids[0] != threading.get_ident()
    worker_events = [row for row in observer.events if row["name"] == "labelled-worker"]
    assert len(worker_events) == 2
    assert all(row["callLabel"] == "public-query" for row in worker_events)
    assert worker_events[1]["returned"] is False
    saved_context, saved_owner, scope = observer.contexts[(id(context), id(owner))]
    assert saved_context is context and saved_owner is owner
    assert scope == {"label": "public-query", "kind": "search"}


def test_observed_exception_retains_class_message_and_args_without_invoking_original():
    class LabelledFailure(ValueError):
        pass

    owner = object()
    observer = _OriginalObserver({_labelled_method.__code__: _specification("labelled-method", "self")})
    observer.bind_owner(owner, "actual-owner")
    frame = _frame(_labelled_method, self=owner)
    error = LabelledFailure("precise original message", 4)
    with observer.call_scope("failing-sync", "sync"):
        observer.profile(frame, "call", None)
        returned_trace = observer.exception_trace(frame, "exception", (type(error), error, None))
        observer.profile(frame, "return", None)
    assert returned_trace == observer.exception_trace
    assert len(observer.exceptions) == 1
    row = observer.exceptions[0]
    assert row["owner"] == "actual-owner" and row["callLabel"] == "failing-sync"
    assert row["error"] == {"module": type(error).__module__, "name": type(error).__qualname__,
                            "message": str(error), "args": ["precise original message", 4]}
    assert observer.exception_trace(_frame(_unrelated_method, self=owner), "exception",
                                    (type(error), error, None)) is None


def test_original_return_keeps_actual_present_fence_frame_scalars_without_source_io(monkeypatch):
    owner = object()
    observer = _OriginalObserver({_labelled_method.__code__: _specification("labelled-fence", "self")})
    observer.bind_owner(owner, "actual-fence")
    frame = _frame(_labelled_method, self=owner, expected=7, live=9,
        expected_revision=11, expected_fence_revision=None, current_revision=13,
        expected_fence=15, generation=17, mutation_generation=19,
        arbitrary="not-a-declared-fence-scalar")

    def forbid_source_lookup(*arguments, **options):
        raise AssertionError("Returning from an original frame must not read source files")

    monkeypatch.setattr(Path, "read_bytes", forbid_source_lookup)
    with observer.call_scope("original-sync", "sync"):
        observer.profile(frame, "call", None)
        observer.profile(frame, "return", None)

    returned = observer.events[-1]
    assert returned["returned"] is None
    assert returned["frameScalars"] == {"expected": 7, "live": 9, "expected_revision": 11,
        "expected_fence_revision": None, "current_revision": 13, "expected_fence": 15,
        "generation": 17, "mutation_generation": 19}
    assert frame.f_locals["live"] == 9 and frame.f_locals["expected"] == 7


def test_physical_file_capture_retains_every_actual_stat_field_as_an_exact_string(tmp_path):
    source = tmp_path / "ordinary-source.md"
    source.write_bytes(b"actual ordinary source bytes\n")
    before = source.lstat()
    expected_names = {name for name in dir(before) if name.startswith("st_")}

    assert _full_stat(before) == {name: str(getattr(before, name)) for name in expected_names}
    captured = _files(tmp_path)

    assert len(captured) == 1 and captured[0]["path"] == "ordinary-source.md"
    assert set(captured[0]["stat"]) == expected_names
    assert set(captured[0]["statAfter"]) == expected_names
    assert all(type(item) is str for item in captured[0]["stat"].values())
    assert captured[0]["stat"]["st_ctime_ns"] == str(before.st_ctime_ns)
    assert captured[0]["stat"]["st_mtime_ns"] == captured[0]["mtimeNs"]
    assert captured[0]["hex"] == b"actual ordinary source bytes\n".hex()


def test_sql_observation_binds_exact_c_receiver_before_factory_return_and_retains_pending_execution(monkeypatch):
    owner, other_owner = object(), object()
    callbacks = []
    observer = _OriginalObserver({_labelled_method.__code__: _specification("MemoryEntryOriginLedger._open_write", "self")},
        sql_callback=lambda *arguments: callbacks.append(arguments))
    observer.bind_owner(owner, "actual-ledger")
    frame = _frame(_labelled_method, self=owner)
    db = sqlite3.connect(":memory:")

    def forbid_source_lookup(*arguments, **options):
        raise AssertionError("SQL observation must not read source files")

    monkeypatch.setattr(Path, "read_bytes", forbid_source_lookup)
    try:
        with observer.call_scope("actual-forget", "forget"):
            observer.profile(_frame(_labelled_method, self=other_owner), "c_call", db.execute)
            observer.profile(_frame(_unrelated_method, self=owner), "c_call", db.execute)
            assert observer.connections == {} and observer.sql_executions == []
            observer.profile(frame, "call", None)
            observer.profile(frame, "c_call", db.execute)
            assert observer.connections[id(db)] is db
            pending = observer.sql_executions[0]
            assert pending["method"] == "execute" and "finishedSequence" not in pending
            assert pending["source"] == "MemoryEntryOriginLedger._open_write"
            assert pending["connectionId"] == str(id(db)) and pending["callLabel"] == "actual-forget"
            assert db.execute("SELECT 1").fetchall() == [(1,)]
            assert pending["statements"] == ["SELECT 1"]
            assert observer.sql[0]["executionSequence"] == pending["sequence"]
            assert len(callbacks) == 1 and callbacks[0][0] is db
            observer.profile(frame, "c_return", db.execute)
            observer.profile(frame, "return", db)
        assert pending["settlement"] == "returned" and pending["finishedSequence"] > pending["sequence"]
        assert observer.local.sql_stack == () and db.total_changes == 0
    finally:
        db.close()


def test_sql_observation_records_c_exception_without_substituting_actual_sqlite_error():
    owner = object()
    observer = _OriginalObserver({_labelled_method.__code__: _specification("MemoryEntryOriginLedger._open_write", "self")})
    observer.bind_owner(owner, "actual-ledger")
    frame = _frame(_labelled_method, self=owner)
    db = sqlite3.connect(":memory:")
    try:
        with observer.call_scope("actual-forget", "forget"):
            observer.profile(frame, "c_call", db.execute)
            with pytest.raises(sqlite3.OperationalError, match="no such table") as original:
                try:
                    db.execute("SELECT * FROM labelled_absent_table")
                except sqlite3.OperationalError:
                    observer.profile(frame, "c_exception", db.execute)
                    raise
        execution = observer.sql_executions[0]
        assert execution["settlement"] == "raised" and observer.local.sql_stack == ()
        assert type(original.value) is sqlite3.OperationalError
        assert str(original.value) == "no such table: labelled_absent_table"
        assert db.total_changes == 0
    finally:
        db.close()


def test_custody_keeps_raw_types_nonfinite_values_and_callable_handles_without_invocation():
    invoked = []

    def callback():
        invoked.append(True)
        raise AssertionError("Observation may not invoke a callback")

    @dataclass
    class LabelledResult:
        raw_count: int
        public_flag: bool
        value: float

    db = sqlite3.connect(":memory:")
    try:
        before = db.total_changes, db.in_transaction
        result = _encode({"result": LabelledResult(1, True, float("inf")), "callback": callback,
                          "sqlite": db, "nan": float("nan"), "bytes": b"\x00\xff"})
        assert type(result["result"]["raw_count"]) is int
        assert result["result"]["public_flag"] is True
        assert result["result"]["value"] == {"nonFiniteFloat": "inf"}
        assert result["nan"] == {"nonFiniteFloat": "nan"}
        assert result["callback"]["callable"] is True
        assert result["callback"]["objectId"] == str(id(callback))
        assert result["sqlite"]["sqliteConnection"] is True
        assert result["sqlite"]["objectId"] == str(id(db))
        assert result["bytes"] == {"bytesHex": "00ff", "bytes": 2}
        assert not invoked and (db.total_changes, db.in_transaction) == before
        json.dumps(result, allow_nan=False)
    finally:
        db.close()


def test_typed_error_flag_uses_actual_class_including_subclasses_without_changing_raw_error():
    class LabelledConflict(Exception):
        pass

    class ChildConflict(LabelledConflict):
        pass

    error = ChildConflict("exact competing revision", 9)
    observed = _error(error, LabelledConflict)
    assert observed["name"] == ChildConflict.__qualname__
    assert observed["message"] == str(error) and observed["args"] == ["exact competing revision", 9]
    assert observed["isTypedConflict"] is True
    assert _error(ValueError(str(error)), LabelledConflict)["isTypedConflict"] is False
    assert _error(error)["isTypedConflict"] is False
    assert error.args == ("exact competing revision", 9)


def test_code_identity_is_derived_from_the_exact_loaded_code_and_source_file():
    code = _labelled_method.__code__
    identity = _code_identity(code)
    source = Path(__file__).resolve()
    assert identity == {"qualname": code.co_qualname, "firstLine": code.co_firstlineno,
                        "file": str(source), "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "bytecodeSha256": hashlib.sha256(code.co_code).hexdigest()}


@pytest.mark.parametrize("relative", [None, "", "/absolute", "../outside", "a/../b", "a//b", "a/./b", "a\\b"])
def test_fixture_path_rejects_noncanonical_or_escaping_inputs(tmp_path, relative):
    with pytest.raises(ValueError):
        _safe_path(tmp_path, relative)


def test_fixture_path_rejects_an_existing_symlink_escape(tmp_path):
    root = tmp_path / "owner"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escaped its exact owner"):
        _safe_path(root, "escape/content.md")
    assert _safe_path(root, "memory/retained.md") == root / "memory" / "retained.md"


@pytest.mark.parametrize("command", [None, {}, {"id": "1", "operation": "observe"},
    {"id": True, "operation": "observe"}, {"id": 1, "operation": "invented-production-operation"},
    {"id": 1, "operation": "arm-gate", "gate": "undeclared"}])
def test_actor_protocol_rejects_invalid_commands_and_undeclared_gates(command):
    with pytest.raises(ValueError):
        _validate_actor_command(command, {"declared": {"boundary": "labelled-test"}})


@pytest.mark.parametrize("operation", ["arm-gate", "await-gate", "release-gate"])
def test_actor_protocol_accepts_only_the_declared_gate_identity_and_preserves_command(operation):
    command = {"id": 5, "operation": operation, "gate": "declared"}
    assert _validate_actor_command(command, {"declared": {"boundary": "labelled-test"}}) is command


def test_common_calls_keep_kind_namespaces_whole_results_and_raw_sync_integer(tmp_path):
    calls = {
        "sync:seed": {"kind": "sync", "label": "seed", "returned": 4,
                      "outcome": {"status": "fulfilled", "isTypedConflict": False}},
        "recall:seed": {"kind": "recall", "label": "seed", "returned": 1},
        "search:fresh": {"kind": "search", "label": "fresh",
                         "details": {"results": [], "warning": "exact warning 9", "action": "exact action"}},
        "sync:fresh": {"kind": "sync", "label": "fresh", "returned": 3,
                       "outcome": {"status": "rejected", "isTypedConflict": True}},
        "forget:seed": {"kind": "forget", "label": "seed",
                        "report": {"createdAt": 1794614400000, "artifacts": {"indexChunks": 3}}},
    }
    before = deepcopy(calls)
    result = _common_calls(calls, tmp_path)
    assert set(result) == set(calls)
    assert result["sync:seed"] == {"operation": "sync", "label": "seed",
                                    "outcome": {"status": "fulfilled", "isTypedConflict": False}}
    assert result["sync:fresh"]["outcome"] == {"status": "rejected", "isTypedConflict": True}
    assert result["recall:seed"]["outcome"] == {"status": "fulfilled"}
    assert result["search:fresh"]["outcome"]["result"] == calls["search:fresh"]["details"]
    assert result["forget:seed"]["outcome"]["result"] == calls["forget:seed"]["report"]
    assert calls == before and type(calls["sync:seed"]["returned"]) is int
    assert type(calls["recall:seed"]["returned"]) is int and calls["recall:seed"]["returned"] == 1


def test_common_calls_preserve_actual_message_code_and_explicit_killed_call_with_complete_raw_error(tmp_path):
    public = {"message": "exact original error 3", "code": 7, "details": {"path": "/original/error/path"}}
    calls = {
        "search:failed": {"kind": "search", "label": "failed", "error": {"message": public["message"], "code": 7,
                          "publicFields": public,
                          "traceback": "raw original stack", "isTypedConflict": False}},
        "search:noCode": {"kind": "search", "label": "noCode", "error": {"message": "exact absent code"}},
        "forget:killed": {"kind": "forget", "label": "killed", "enterSeq": 4,
                          "termination": {"signal": "SIGKILL", "pid": 82}},
    }
    before = deepcopy(calls)
    result = _common_calls(calls, tmp_path)
    assert result["search:failed"]["outcome"] == {"status": "rejected", "error": {"message": public["message"], "code": 7}}
    assert result["search:noCode"]["outcome"] == {"status": "rejected", "error": {"message": "exact absent code"}}
    assert result["forget:killed"]["outcome"] == {"status": "terminated", "signal": "SIGKILL"}
    assert calls == before and "returned" not in calls["forget:killed"]


def test_common_promotion_alias_changes_only_declared_owned_memory_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = str(workspace / "MEMORY.md")
    calls = {"promotion:seed": {"kind": "promotion", "label": "seed", "publicPromotion": {
        "memoryPath": path, "message": path, "appliedCandidates": [{"path": path, "observedAt": 1794614400000}]}}}
    before = deepcopy(calls)
    result = _common_calls(calls, workspace)["promotion:seed"]["outcome"]["result"]
    assert result == {"memoryPath": "$WORKSPACE/MEMORY.md", "message": path,
                      "appliedCandidates": [{"path": path, "observedAt": 1794614400000}]}
    assert calls == before
    with pytest.raises(RuntimeError, match="outside its verified workspace"):
        _common_calls({"promotion:outside": {"kind": "promotion", "label": "outside",
            "publicPromotion": {"memoryPath": str(tmp_path / "outside.md")}}}, workspace)
    (workspace / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="outside its verified workspace"):
        _common_calls({"promotion:symlink": {"kind": "promotion", "label": "symlink",
            "publicPromotion": {"memoryPath": str(workspace / "escape" / "outside.md")}}}, workspace)


def test_common_snapshot_covers_absence_all_chunk_duplicates_timestamps_and_actual_call_settlement(tmp_path):
    selected = "forgotten-labelled-session"
    duplicate = {"path": "MEMORY.md", "source": "memory", "start_line": 3, "end_line": 3,
                 "text": "actual duplicated source row", "id": "opaque-1"}
    value = {"initialFiles": {"MEMORY.md": "declared text", "memory/removed.md": "declared removed"},
             "gates": [{"boundary": "rebuild.revision-captured-before-publication", "callLabel": "old"}],
             "forgetCalls": {"selected": {"sessionIds": [selected]}}}
    logical_sessions = {"facts": [{"agentId": "main", "sessionId": selected, "sessionKey": "source-key",
                                  "entry": {"createdAt": 1794528000000}, "events": [{"id": "original-event"}]}],
                        "admission": [{"agentId": "main", "sessionId": selected, "admitted": False}]}
    snapshot = {"files": [{"path": "MEMORY.md", "hex": "616263", "sha256": "source-sha", "mtimeNs": "original-stat"},
                          {"path": "DREAMS.md", "hex": "646566", "sha256": "created-sha"},
                          {"path": "memory/.dreams/private.json", "hex": "7b7d", "sha256": "private-sha"}],
                "indexSql": {"tables": {"chunks": {"rows": [duplicate, {**duplicate, "id": "opaque-2"}]}}},
                "logicalStores": {"recall": {"updatedAt": "exact-recall-time", "entries": {}},
                                  "phaseSignals": {"updatedAt": "exact-phase-time", "entries": {}},
                                  "ingestion": {"version": 1}, "preimages": [{"createdAt": 1794528000000}]},
                "logicalOrigins": [{"entry_key": "entry", "agent_id": "main", "session_id": selected,
                                    "session_key": "source-key", "origin_class": "owner", "observed_at": 1794528000000}],
                "tombstones": [{"session_id": selected, "agent_id": "main", "reason": "forgotten", "created_at": 1794614400000}],
                "logicalSessions": logical_sessions}
    observations = [{"publicCalls": {"sync:old": {"actor": "builder", "kind": "sync", "label": "old", "enterSeq": 2,
                                                  "apiEntry": {"atNs": "2"}},
                                    "forget:selected": {"actor": "forgetter", "kind": "forget", "enterSeq": 4,
                                                        "apiEntry": {"atNs": "4"}}}},
                    {"publicCalls": {"forget:retry": {"actor": "forgetter", "kind": "forget", "enterSeq": 1,
                                                     "apiEntry": {"atNs": "5"}, "returnSeq": 8}}}]
    before = deepcopy(snapshot)
    result = _common_snapshot(value, snapshot, observations, tmp_path)
    assert set(result) == {"documents", "recall", "phaseSignals", "ingestion", "preimages", "origins",
                           "tombstones", "sessions", "index", "concurrency", "events"}
    assert result["documents"] == [{"path": "DREAMS.md", "exists": True, "bytes": "646566", "sha256": "created-sha"},
                                    {"path": "MEMORY.md", "exists": True, "bytes": "616263", "sha256": "source-sha"},
                                    {"path": "memory/removed.md", "exists": False, "bytes": None, "sha256": None}]
    assert result["index"] == [{"path": "MEMORY.md", "source": "memory", "startLine": 3,
                                 "endLine": 3, "text": "actual duplicated source row"}] * 2
    assert result["tombstones"][0]["createdAt"] == 1794614400000
    assert result["origins"][0]["observedAt"] == 1794528000000
    assert result["sessions"] == logical_sessions and result["preimages"] == snapshot["logicalStores"]["preimages"]
    assert result["concurrency"] == {"markerVisible": True, "forgetSettled": True, "oldBuildSettled": False}
    assert result["events"] == []
    assert snapshot == before
    assert _common_snapshot(value, snapshot, [], tmp_path)["concurrency"] == {
        "markerVisible": True, "forgetSettled": None, "oldBuildSettled": None}


def test_common_snapshot_events_keep_observed_order_and_alias_only_original_promotion_field(tmp_path):
    value = {"initialFiles": {}, "gates": [], "forgetCalls": {"selected": {"sessionIds": ["selected"]}}}
    snapshot = {"files": [], "indexSql": {"tables": {}}, "logicalStores": {
        "recall": {}, "phaseSignals": {}, "ingestion": {}, "preimages": []},
        "logicalOrigins": [], "tombstones": [], "logicalSessions": {"facts": [], "admission": []}}
    original_path = str(tmp_path / "MEMORY.md")
    observations = [{"hostEventReceipts": [{"atNs": "9", "event": {
        "type": "memory.promotion.applied", "memoryPath": original_path,
        "message": original_path, "timestamp": "exact-promotion-time", "applied": 1}}]},
        {"hostEventReceipts": [{"atNs": "3", "event": {
            "type": "memory.recall.recorded", "memoryPath": original_path,
            "timestamp": "exact-recall-time", "candidates": [{"path": original_path}]}}]}]
    before = deepcopy(observations)
    events = _common_snapshot(value, snapshot, observations, tmp_path)["events"]
    assert events == [{"type": "memory.recall.recorded", "memoryPath": original_path,
                      "timestamp": "exact-recall-time", "candidates": [{"path": original_path}]},
                     {"type": "memory.promotion.applied", "memoryPath": "$WORKSPACE/MEMORY.md",
                      "message": original_path, "timestamp": "exact-promotion-time", "applied": 1}]
    assert observations == before
