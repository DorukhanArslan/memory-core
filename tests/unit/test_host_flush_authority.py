"""Host flush authority is carried from preparation through writes and completion."""

from __future__ import annotations

import asyncio
import errno
import os
import threading

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState, TurnUsage
from memory_core.host import flush as flush_module
from memory_core.host import kit as kit_module
from memory_core import memory_flush as memory_flush_module
from memory_core import workspace as workspace_module

NOW_MS = 1_790_375_400_000
TARGET = "memory/2026-09-25.md"
TRANSCRIPT = ({"role": "user", "content": "Keep the velvetkiwi codename."},)


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _session() -> SessionState:
    return SessionState(
        session_key="agent:main:main",
        session_id="s1",
        entry={"sessionId": "s1", "compactionCount": 0},
    )


def _request(kit, session, method, assert_current):
    if method == "after_turn":
        record = kit.after_turn(
            session,
            transcript=TRANSCRIPT,
            usage=TurnUsage(176_000, 10),
            assert_current=assert_current,
        )
        assert record.flush_failure is None
        assert record.flush is not None
        return record.flush
    flush = kit.request_flush(session, transcript=TRANSCRIPT, assert_current=assert_current)
    assert flush is not None
    return flush


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
def test_public_flush_checks_authority_through_completion(tmp_path, method):
    checks = []

    def assert_current():
        checks.append((tmp_path / TARGET).exists())

    kit = _kit(tmp_path)
    session = _session()
    flush = _request(kit, session, method, assert_current)
    assert checks[0] is False
    assert checks[-1] is True
    preparation_checks = len(checks)

    result = flush.dispatch("write", {"path": TARGET, "content": "- velvetkiwi"})
    assert result["action"] == "appended"
    assert len(checks) > preparation_checks
    dispatch_checks = len(checks)
    outcome = flush.complete(session)

    assert len(checks) > dispatch_checks
    assert outcome.entries == ("- velvetkiwi",)
    assert outcome.session.entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    assert (tmp_path / TARGET).read_text() == "- velvetkiwi"


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
@pytest.mark.parametrize("error_type", [RuntimeError, OSError, asyncio.CancelledError])
def test_cancelled_public_flush_propagates_without_preparing_target(tmp_path, method, error_type):
    session = _session()
    error = error_type("flush authority is stale")

    def assert_current():
        raise error

    with pytest.raises(error_type) as caught:
        _request(_kit(tmp_path), session, method, assert_current)

    assert caught.value is error
    assert not (tmp_path / "memory").exists()
    assert session.entry == {"sessionId": "s1", "compactionCount": 0}


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
def test_authority_oserror_after_mkdir_does_not_become_a_failure_strike(tmp_path, method):
    error = OSError("cancelled after parent creation")
    session = _session()

    def assert_current():
        if (tmp_path / "memory").exists():
            raise error

    with pytest.raises(OSError) as caught:
        _request(_kit(tmp_path), session, method, assert_current)

    assert caught.value is error
    assert not (tmp_path / TARGET).exists()
    assert "memoryFlush" not in session.entry


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
@pytest.mark.parametrize("error_type", [RuntimeError, OSError, asyncio.CancelledError])
def test_preparation_authority_exception_survives_close_failure(
    tmp_path, monkeypatch, method, error_type
):
    kit = _kit(tmp_path)
    session = _session()
    (tmp_path / TARGET).parent.mkdir(parents=True)
    (tmp_path / TARGET).write_bytes(b"- existing\n")
    authority_error = error_type("authority revoked after target open")
    close_error = OSError("target close failed")
    checks = 0
    descriptors = []
    original_close = os.close

    def assert_current():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise authority_error

    def close(descriptor):
        original_close(descriptor)
        descriptors.append(descriptor)
        raise close_error

    def unexpected(*args, **kwargs):
        pytest.fail("cancelled preparation recorded a failure or handed off a request")

    monkeypatch.setattr(memory_flush_module.os, "close", close)
    monkeypatch.setattr(kit_module, "record_memory_flush_failure", unexpected)
    monkeypatch.setattr(kit, "_flush_request", unexpected)
    with pytest.raises(error_type) as caught:
        _request(kit, session, method, assert_current)

    assert caught.value is authority_error
    assert caught.value.__cause__ is close_error
    assert checks == 3
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert (tmp_path / TARGET).read_bytes() == b"- existing\n"
    assert "memoryFlush" not in session.entry


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
def test_preparation_close_failure_without_authority_keeps_filesystem_failure(
    tmp_path, monkeypatch, method
):
    kit = _kit(tmp_path)
    session = _session()
    close_error = OSError("target close failed")
    descriptors = []
    original_close = os.close

    def close(descriptor):
        original_close(descriptor)
        descriptors.append(descriptor)
        raise close_error

    monkeypatch.setattr(memory_flush_module.os, "close", close)
    if method == "after_turn":
        record = kit.after_turn(session, transcript=TRANSCRIPT, usage=TurnUsage(176_000, 10))
        assert record.flush is None
        assert record.flush_failure.failure_count == 1
        assert record.flush_failure.error == str(close_error)
        assert record.session.entry["memoryFlush"] == {"kind": "failed", "failureCount": 1}
    else:
        with pytest.raises(OSError) as caught:
            kit.request_flush(session, transcript=TRANSCRIPT)
        assert caught.value is close_error

    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert "memoryFlush" not in session.entry


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
def test_authority_is_rechecked_after_building_flush_messages(tmp_path, monkeypatch, method):
    kit = _kit(tmp_path)
    error = RuntimeError("cancelled while building context")
    cancelled = False
    original = kit._flush_messages

    def messages(*args):
        nonlocal cancelled
        result = original(*args)
        cancelled = True
        return result

    def assert_current():
        if cancelled:
            raise error

    monkeypatch.setattr(kit, "_flush_messages", messages)
    with pytest.raises(RuntimeError) as caught:
        _request(kit, _session(), method, assert_current)

    assert caught.value is error
    assert (tmp_path / TARGET).read_bytes() == b""


@pytest.mark.parametrize("method", ["after_turn", "request_flush"])
def test_cancelled_request_cannot_write_or_stamp_success(tmp_path, monkeypatch, method):
    kit = _kit(tmp_path)
    session = _session()
    error = OSError("session revision was replaced")
    cancelled = False

    def assert_current():
        if cancelled:
            raise error

    flush = _request(kit, session, method, assert_current)
    cancelled = True

    def unexpected(*args, **kwargs):
        pytest.fail("cancelled request reached a mutation or stamp")

    monkeypatch.setattr(flush_module, "append_memory_flush_file", unexpected)
    monkeypatch.setattr(flush_module, "record_memory_flush_success", unexpected)
    monkeypatch.setattr(flush_module, "record_memory_flush_failure", unexpected)
    with pytest.raises(OSError) as dispatch_error:
        flush.dispatch("write", {"path": TARGET, "content": "- stale"})
    with pytest.raises(OSError) as completion_error:
        flush.complete(session)

    assert dispatch_error.value is completion_error.value is error
    assert (tmp_path / TARGET).read_bytes() == b""
    assert "memoryFlush" not in session.entry
    with pytest.raises(RuntimeError, match="already completed"):
        flush.dispatch("write", {"path": TARGET, "content": "- too late"})


def test_authority_is_checked_after_reading_dispatch_arguments(tmp_path, monkeypatch):
    cancelled = False

    def assert_current():
        if cancelled:
            raise RuntimeError("cancelled while reading tool arguments")

    flush = _request(_kit(tmp_path), _session(), "request_flush", assert_current)
    original = flush_module.read_tool_call

    def read_arguments(*args):
        nonlocal cancelled
        arguments = original(*args)
        cancelled = True
        return arguments

    monkeypatch.setattr(flush_module, "read_tool_call", read_arguments)
    with pytest.raises(RuntimeError, match="cancelled while reading"):
        flush.dispatch("write", {"path": TARGET, "content": "- stale"})

    assert (tmp_path / TARGET).read_bytes() == b""


@pytest.mark.parametrize("completion_error", [None, "model failed"])
def test_completion_authority_failure_closes_request_without_recording_result(
    tmp_path, monkeypatch, completion_error
):
    session = _session()
    cancelled = False

    def assert_current():
        if cancelled:
            raise asyncio.CancelledError("abandoned flush")

    flush = _request(_kit(tmp_path), session, "request_flush", assert_current)
    assert flush.dispatch("write", {"path": TARGET, "content": "- committed"})["action"] == "appended"
    cancelled = True

    def unexpected(*args, **kwargs):
        pytest.fail("authority failure must not record a result")

    monkeypatch.setattr(flush_module, "record_memory_flush_success", unexpected)
    monkeypatch.setattr(flush_module, "record_memory_flush_failure", unexpected)
    with pytest.raises(asyncio.CancelledError):
        flush.complete(session, error=completion_error)

    assert (tmp_path / TARGET).read_text() == "- committed"
    assert "memoryFlush" not in session.entry
    with pytest.raises(RuntimeError, match="already completed"):
        flush.complete(session)


def test_wrong_session_does_not_check_authority_or_close_request(tmp_path):
    checks = 0

    def assert_current():
        nonlocal checks
        checks += 1

    flush = _request(_kit(tmp_path), _session(), "request_flush", assert_current)
    preparation_checks = checks
    wrong = SessionState.new(session_key="agent:main:main", session_id="s2")
    with pytest.raises(ValueError, match="s1"):
        flush.complete(wrong)

    assert checks == preparation_checks
    assert flush.complete(_session()).failure is None


@pytest.mark.parametrize("blocked_operation", ["append", "reindex"])
def test_complete_rejects_in_flight_flush_mutation(tmp_path, monkeypatch, blocked_operation):
    kit = _kit(tmp_path)
    session = _session()
    flush = _request(kit, session, "request_flush", None)
    entered = threading.Barrier(2)
    release = threading.Barrier(2)
    original = (
        flush_module.append_memory_flush_file
        if blocked_operation == "append"
        else kit.memory.store.reindex
    )

    def blocked(*args, **kwargs):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        return original(*args, **kwargs)

    if blocked_operation == "append":
        monkeypatch.setattr(flush_module, "append_memory_flush_file", blocked)
    else:
        monkeypatch.setattr(kit.memory.store, "reindex", blocked)
    results = []
    errors = []

    def write():
        try:
            results.append(flush.dispatch("write", {"path": TARGET, "content": "- kept"}))
        except BaseException as error:
            errors.append(error)

    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    try:
        entered.wait(timeout=5)
        with pytest.raises(RuntimeError, match="in-flight dispatch"):
            flush.complete(session)
    finally:
        release.wait(timeout=5)
        writer.join(timeout=5)

    assert not writer.is_alive()
    assert errors == []
    assert results[0]["action"] == "appended"
    assert flush.complete(session).entries == ("- kept",)
    with pytest.raises(RuntimeError, match="already completed"):
        flush.dispatch("write", {"path": TARGET, "content": "- after complete"})
    assert (tmp_path / TARGET).read_text() == "- kept"


def test_authority_callbacks_can_reenter_request_without_deadlocking(tmp_path):
    session = _session()
    flush = None
    phase = None
    refusals = []

    def assert_current():
        if flush is None:
            return
        try:
            if phase == "dispatch":
                flush.complete(session)
            elif phase == "complete":
                flush.dispatch("write", {"path": TARGET, "content": "- reentrant"})
        except RuntimeError as error:
            refusals.append(str(error))

    flush = _request(_kit(tmp_path), session, "request_flush", assert_current)
    errors = []

    def run():
        nonlocal phase
        try:
            phase = "dispatch"
            flush.dispatch("write", {"path": TARGET, "content": "- kept"})
            phase = "complete"
            assert flush.complete(session).entries == ("- kept",)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive(), "authority callback deadlocked on the request lock"
    assert errors == []
    assert len(refusals) >= 2
    assert all(message == "the flush request has an in-flight dispatch" for message in refusals[:-1])
    assert refusals[-1] == "the flush request is already completed"
    assert (tmp_path / TARGET).read_text() == "- kept"


def test_index_failure_keeps_committed_receipt_with_authority_checks(tmp_path, monkeypatch):
    kit = _kit(tmp_path)
    session = _session()
    checks = []
    flush = _request(kit, session, "request_flush", lambda: checks.append("current"))

    def broken_index(workspace):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(kit.memory.store, "reindex", broken_index)
    result = flush.dispatch("write", {"path": TARGET, "content": "- committed once"})
    outcome = flush.complete(session)

    assert result["action"] == "appended"
    assert result["afterWriteError"] == "index unavailable"
    assert outcome.entries == ("- committed once",)
    assert (tmp_path / TARGET).read_text() == "- committed once"


@pytest.mark.parametrize("error_type", [RuntimeError, OSError, asyncio.CancelledError])
def test_cancellation_while_waiting_for_file_lock_prevents_append(
    tmp_path, monkeypatch, error_type
):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    kit = _kit(tmp_path, artifact_provenance=store)
    error = error_type("cancelled while waiting for the file lock")
    cancelled = False

    def assert_current():
        if cancelled:
            raise error

    flush = _request(kit, _session(), "request_flush", assert_current)
    file_lock = workspace_module.workspace_file_lock(tmp_path.resolve(), TARGET)
    waiting = threading.Barrier(2)

    class ObservedLock:
        def __enter__(self):
            waiting.wait(timeout=5)
            return file_lock.__enter__()

        def __exit__(self, *args):
            return file_lock.__exit__(*args)

    monkeypatch.setattr(workspace_module, "workspace_file_lock", lambda *args: ObservedLock())

    def unexpected(*args, **kwargs):
        pytest.fail("cancelled append reached provenance reservation or index refresh")

    monkeypatch.setattr(store, "record_write", unexpected)
    monkeypatch.setattr(kit.memory.store, "reindex", unexpected)
    errors = []

    def write():
        try:
            flush.dispatch("write", {"path": TARGET, "content": "- stale"})
        except BaseException as caught:
            errors.append(caught)

    with file_lock:
        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        waiting.wait(timeout=5)
        cancelled = True
    writer.join(timeout=5)

    assert not writer.is_alive()
    assert errors == [error]
    assert (tmp_path / TARGET).read_bytes() == b""
    assert store.list(tmp_path) == []
    with pytest.raises(error_type) as caught:
        flush.complete(_session())
    assert caught.value is error


@pytest.mark.parametrize("cancel_from", ["origin", "record"])
def test_provenance_callback_cancellation_rolls_back_without_appending(
    tmp_path, monkeypatch, cancel_from
):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    kit = _kit(tmp_path, artifact_provenance=store)
    cancelled = False
    error = OSError("authority revoked by provenance callback")

    def assert_current():
        if cancelled:
            raise error

    def untrusted_turn():
        nonlocal cancelled
        if cancel_from == "origin":
            cancelled = True
        return False

    flush = kit.request_flush(
        _session(),
        transcript=TRANSCRIPT,
        assert_current=assert_current,
        untrusted_turn=untrusted_turn,
    )
    (tmp_path / TARGET).write_text("- original\n")
    store.record_write(
        workspace_dir=tmp_path,
        relative_path=TARGET,
        content_before="",
        content_after="- original\n",
        origin_class="agent",
        observed_at=1,
    )
    previous = store.list(tmp_path)
    original_record = store.record_write
    reservations = []

    def record(*args, **kwargs):
        nonlocal cancelled
        rollback = original_record(*args, **kwargs)
        reservations.append(kwargs["content_after"])
        if cancel_from == "record":
            cancelled = True
        return rollback

    def unexpected_index(*args):
        pytest.fail("cancelled append reached index refresh")

    monkeypatch.setattr(store, "record_write", record)
    monkeypatch.setattr(kit.memory.store, "reindex", unexpected_index)
    with pytest.raises(OSError) as caught:
        flush.dispatch("write", {"path": TARGET, "content": "- stale"})

    assert caught.value is error
    assert reservations == ["- original\n- stale"]
    assert store.list(tmp_path) == previous
    assert (tmp_path / TARGET).read_text() == "- original\n"


@pytest.mark.parametrize("error_type", [RuntimeError, OSError, asyncio.CancelledError])
def test_authority_exception_survives_provenance_rollback_failure(
    tmp_path, monkeypatch, error_type
):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    kit = _kit(tmp_path, artifact_provenance=store)
    session = _session()
    error = error_type("authority revoked after provenance reservation")
    rollback_error = OSError("provenance rollback storage unavailable")
    cancelled = False

    def assert_current():
        if cancelled:
            raise error

    flush = _request(kit, session, "request_flush", assert_current)
    (tmp_path / TARGET).write_text("- original\n")
    original_record = store.record_write

    def record(*args, **kwargs):
        nonlocal cancelled
        original_record(*args, **kwargs)
        cancelled = True

        def rollback():
            raise rollback_error

        return rollback

    def unexpected_index(*args):
        pytest.fail("cancelled append reached index refresh")

    monkeypatch.setattr(store, "record_write", record)
    monkeypatch.setattr(kit.memory.store, "reindex", unexpected_index)
    with pytest.raises(error_type) as caught:
        flush.dispatch("write", {"path": TARGET, "content": "- stale"})

    assert caught.value is error
    combined = error.__cause__
    assert isinstance(combined, RuntimeError)
    assert "memory provenance rollback also failed" in str(combined)
    assert combined.__cause__ is rollback_error
    assert (tmp_path / TARGET).read_text() == "- original\n"
    assert "memoryFlush" not in session.entry
    with pytest.raises(error_type) as completed:
        flush.complete(session)
    assert completed.value is error
    assert "memoryFlush" not in session.entry


def test_cancellation_after_open_closes_handle_without_appending(tmp_path, monkeypatch):
    cancelled = False
    error = RuntimeError("cancelled during file open")

    def assert_current():
        if cancelled:
            raise error

    kit = _kit(tmp_path)
    flush = _request(kit, _session(), "request_flush", assert_current)
    original_open = os.open
    descriptors = []

    def open_file(path, flags, *args, **kwargs):
        nonlocal cancelled
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == tmp_path / TARGET and flags & os.O_APPEND:
            descriptors.append(descriptor)
            cancelled = True
        return descriptor

    def unexpected_index(*args):
        pytest.fail("cancelled append reached index refresh")

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(kit.memory.store, "reindex", unexpected_index)
    with pytest.raises(RuntimeError) as caught:
        flush.dispatch("write", {"path": TARGET, "content": "- stale"})

    assert caught.value is error
    assert len(descriptors) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    assert (tmp_path / TARGET).read_bytes() == b""


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_postappend_cancellation_retains_committed_entry_and_skips_index(
    tmp_path, monkeypatch, error_type
):
    cancelled = False
    error = error_type("authority revoked after committed append")

    def assert_current():
        if cancelled:
            raise error

    kit = _kit(tmp_path)
    session = _session()
    flush = _request(kit, session, "request_flush", assert_current)
    original_append = flush_module.append_memory_flush_file

    def append(*args, **kwargs):
        nonlocal cancelled
        path = original_append(*args, **kwargs)
        cancelled = True
        return path

    def unexpected_index(*args):
        pytest.fail("postappend cancellation reached index refresh")

    monkeypatch.setattr(flush_module, "append_memory_flush_file", append)
    monkeypatch.setattr(kit.memory.store, "reindex", unexpected_index)
    if error_type is asyncio.CancelledError:
        with pytest.raises(error_type) as caught:
            flush.dispatch("write", {"path": TARGET, "content": "- committed once"})
        assert caught.value is error
    else:
        result = flush.dispatch("write", {"path": TARGET, "content": "- committed once"})
        assert result["action"] == "appended"
        assert result["afterWriteError"] == str(error)

    assert (tmp_path / TARGET).read_text() == "- committed once"
    assert "memoryFlush" not in session.entry
    # A subsequent authority check succeeds only when the host restores its authority.
    cancelled = False
    assert flush.complete(session).entries == ("- committed once",)
