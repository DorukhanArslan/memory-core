from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import sqlite3
import threading

import pytest

from memory_core.session_catalog import MemorySessionCatalog, SessionTranscriptChange
from memory_core.session_transcript_append import TranscriptTurnAdmissionConflictError
from memory_core import secret_registry


KEY = "agent:main:notifications"
SESSION = "notification-session"


def _catalog(tmp_path, **options):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000, **options)
    catalog.upsert_session(KEY, {"sessionId": SESSION})
    return catalog


def _message(text="remember this", **extra):
    return {"role": "user", "content": text, **extra}


def test_listener_reads_committed_transaction_and_can_take_another_write_lock(tmp_path):
    catalog = _catalog(tmp_path)
    changes = []

    def changed(change):
        # A separate writer would fail while the append transaction is open.
        with sqlite3.connect(catalog.path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision,mutation_at FROM memory_session_windows WHERE agent=? AND session_id=?",
                (change.agent_id, change.session_id),
            ).fetchone()
            assert row == (change.revision, change.mutation_at_ms)
            assert db.execute(
                "SELECT revision FROM memory_session_catalog_state WHERE agent=?", (change.agent_id,),
            ).fetchone()[0] == change.catalog_revision
        transcript = catalog.read_transcript(change.session_id, session_key=change.session_key)
        assert transcript.revision == change.revision
        assert transcript.events[-1]["message"] == _message()
        changes.append(change)

    unsubscribe = catalog.subscribe_transcript_changes(changed)
    result = catalog.append_message(SESSION, _message(), session_key=KEY, event_id="first")
    assert result["appended"] is True
    assert catalog.transcript_listener_diagnostics() == ()
    change, = changes
    assert isinstance(change, SessionTranscriptChange)
    assert (change.agent_id, change.session_id, change.session_key, change.store_path) == (
        "main", SESSION, KEY, catalog.path,
    )
    assert (change.revision, change.catalog_revision, change.operation) == (1, 2, "append-message")
    assert change.generation == result["anchor"]["generation"]
    with pytest.raises(FrozenInstanceError):
        change.revision = 50
    unsubscribe()
    unsubscribe()
    catalog.append_message(SESSION, _message("later"), session_key=KEY, event_id="later")
    assert len(changes) == 1


def test_admission_replay_conflict_and_duplicate_event_do_not_notify(tmp_path):
    catalog = _catalog(tmp_path)
    changes = []
    catalog.subscribe_transcript_changes(changes.append)
    message = _message(idempotencyKey="same-admission")
    original = catalog.append_message(SESSION, message, session_key=KEY, event_id="original")
    replay = catalog.append_message(SESSION, message, session_key=KEY, event_id="ignored-replay-id")
    assert replay["appended"] is False
    assert replay["messageId"] == original["messageId"]
    with pytest.raises(TranscriptTurnAdmissionConflictError):
        catalog.append_message(SESSION, _message("different", idempotencyKey="same-admission"),
                               session_key=KEY, event_id="conflicting")
    catalog.append_events(SESSION, [{"type": "message", "id": "original", "message": message}])
    catalog.append_events(SESSION, [])
    assert len(changes) == 1
    assert catalog.read_transcript(SESSION).revision == changes[0].revision


@pytest.mark.parametrize("operation", ["append-message", "append-events", "replace-events"])
def test_rolled_back_write_never_notifies(tmp_path, monkeypatch, operation):
    catalog = _catalog(tmp_path)
    changes = []
    catalog.subscribe_transcript_changes(changes.append)
    before = catalog.read_transcript(SESSION)
    before_catalog = catalog.snapshot().revision
    changed = catalog._changed

    def abort_after_mutation(db):
        changed(db)
        raise RuntimeError("abort the transaction")

    monkeypatch.setattr(catalog, "_changed", abort_after_mutation)
    with pytest.raises(RuntimeError, match="abort the transaction"):
        if operation == "append-message":
            catalog.append_message(SESSION, _message(), session_key=KEY, event_id="rolled-back")
        else:
            event = {"type": "message", "id": "rolled-back", "message": _message()}
            method = catalog.replace_events if operation == "replace-events" else catalog.append_events
            method(SESSION, [event])
    assert changes == []
    assert catalog.read_transcript(SESSION) == before
    assert catalog.snapshot().revision == before_catalog


def test_listener_failure_is_recorded_after_commit_without_changing_append_result(tmp_path):
    catalog = _catalog(tmp_path)
    observed = []

    def broken(change):
        assert catalog.read_transcript(change.session_id).revision == change.revision
        raise RuntimeError("listener unavailable")

    unsubscribe = catalog.subscribe_transcript_changes(broken)
    catalog.subscribe_transcript_changes(observed.append)
    result = catalog.append_message(SESSION, _message(), session_key=KEY, event_id="persisted")
    assert result["appended"] is True
    assert catalog.read_transcript(SESSION).events[-1]["id"] == "persisted"
    assert len(observed) == 1
    failure, = catalog.transcript_listener_diagnostics()
    assert failure.change == observed[0]
    assert (failure.error_type, failure.error_message) == ("RuntimeError", "listener unavailable")
    assert catalog.transcript_listener_failure_count == 1
    with pytest.raises(FrozenInstanceError):
        failure.error_message = "modified"
    unsubscribe()
    catalog.append_message(SESSION, _message("second"), session_key=KEY, event_id="second")
    assert len(observed) == 2
    assert catalog.transcript_listener_failure_count == 1


def test_listener_diagnostics_redact_registered_credentials(tmp_path):
    catalog = _catalog(tmp_path)
    credential = "catalog-listener-fixture-credential"
    secret_registry.register_secret_value_for_redaction(credential)

    def broken(_change):
        raise RuntimeError(f"listener failed with {credential}")

    try:
        catalog.subscribe_transcript_changes(broken)
        result = catalog.append_message(SESSION, _message(), session_key=KEY, event_id="redacted")
        assert result["appended"] is True
        failure, = catalog.transcript_listener_diagnostics()
        assert failure.error_message.startswith("listener failed with ")
        assert credential not in failure.error_message
    finally:
        secret_registry.reset_secret_redaction_registry()


def test_unformattable_listener_error_cannot_relabel_a_committed_append(tmp_path):
    catalog = _catalog(tmp_path)

    class BrokenError(Exception):
        def __str__(self):
            raise RuntimeError("broken formatter")

    def broken(_change):
        raise BrokenError()

    catalog.subscribe_transcript_changes(broken)
    assert catalog.append_message(SESSION, _message(), session_key=KEY, event_id="still-persisted")["appended"]
    failure, = catalog.transcript_listener_diagnostics()
    assert failure.error_type == "BrokenError"
    assert failure.error_message == "Transcript listener diagnostic could not be formatted"
    assert catalog.read_transcript(SESSION).events[-1]["id"] == "still-persisted"


def test_raw_import_and_replacement_notify_only_real_transcript_changes(tmp_path):
    catalog = _catalog(tmp_path)
    changes = []
    catalog.subscribe_transcript_changes(changes.append)
    catalog.replace_events(SESSION, [])
    assert changes == []
    event = {"type": "message", "id": "imported", "message": _message()}
    catalog.append_events(SESSION, [event])
    catalog.replace_events(SESSION, [event])
    catalog.replace_events(SESSION, [])
    assert [change.operation for change in changes] == ["append-events", "replace-events", "replace-events"]
    assert [change.revision for change in changes] == [1, 2, 3]
    assert len({change.generation for change in changes}) == 3
    assert catalog.read_transcript(SESSION).events == ()


def test_shared_catalog_instances_notify_their_own_agent_namespace(tmp_path):
    catalog = _catalog(tmp_path)
    peer = MemorySessionCatalog(catalog.path, clock_ms=lambda: 1000)
    other = MemorySessionCatalog(catalog.path, agent_id="other", clock_ms=lambda: 1000)
    other_key = "agent:other:notifications"
    other.upsert_session(other_key, {"sessionId": SESSION})
    main_changes, other_changes = [], []
    catalog.subscribe_transcript_changes(main_changes.append)
    other.subscribe_transcript_changes(other_changes.append)
    peer.append_message(SESSION, _message("main"), session_key=KEY, event_id="main")
    other.append_message(SESSION, _message("other"), session_key=other_key, event_id="other")
    assert [(change.agent_id, change.session_key) for change in main_changes] == [("main", KEY)]
    assert [(change.agent_id, change.session_key) for change in other_changes] == [("other", other_key)]


def test_durable_path_aliases_share_the_actual_catalog_listener_namespace(tmp_path):
    catalog = _catalog(tmp_path)
    alias = tmp_path / "catalog-alias.sqlite"
    alias.symlink_to(catalog.path)
    peer = MemorySessionCatalog(alias, clock_ms=lambda: 1000)
    changes = []
    catalog.subscribe_transcript_changes(changes.append)
    peer.append_message(SESSION, _message(), session_key=KEY, event_id="alias-write")
    change, = changes
    assert change.store_path == catalog.path == peer.path


def test_independent_volatile_backings_do_not_share_a_sentinel_listener_namespace(tmp_path):
    first = MemorySessionCatalog(tmp_path / "first.sqlite", clock_ms=lambda: 1000)
    second = MemorySessionCatalog(tmp_path / "second.sqlite", clock_ms=lambda: 1000)
    key = "agent:main:dashboard:incognito-notifications"
    first.upsert_session(key, {"sessionId": "first-private"})
    second.upsert_session(key, {"sessionId": "second-private"})
    first_private, second_private = first._key_catalog(key), second._key_catalog(key)
    assert first_private.path == second_private.path
    assert first_private._memory_uri != second_private._memory_uri
    first_changes, second_changes, public_changes = [], [], []
    first_private.subscribe_transcript_changes(first_changes.append)
    second_private.subscribe_transcript_changes(second_changes.append)
    first.subscribe_transcript_changes(public_changes.append)

    second.append_message("second-private", _message("second"), session_key=key, event_id="second-write")
    assert first_changes == []
    assert first_private.read_transcript("second-private", session_key=key) is None
    first.append_message("first-private", _message("first"), session_key=key, event_id="first-write")
    assert [change.session_id for change in first_changes] == ["first-private"]
    assert [change.session_id for change in second_changes] == ["second-private"]
    assert public_changes == []


def test_concurrent_commits_retain_actual_distinct_revisions(tmp_path):
    catalog = _catalog(tmp_path)
    changes, guard = [], threading.Lock()

    def changed(change):
        assert catalog.read_transcript(SESSION).revision >= change.revision
        with guard:
            changes.append(change)

    catalog.subscribe_transcript_changes(changed)
    peers = [MemorySessionCatalog(catalog.path, clock_ms=lambda: 1000) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda pair: pair[1].append_message(
            SESSION, _message(str(pair[0])), session_key=KEY, event_id=f"message-{pair[0]}"), enumerate(peers)))
    assert all(result["appended"] for result in results)
    assert len(changes) == 8
    assert {change.revision for change in changes} == set(range(1, 9))
    assert {change.catalog_revision for change in changes} == set(range(2, 10))
    assert len({change.generation for change in changes}) == 1
    assert catalog.transcript_listener_diagnostics() == ()


def test_callback_can_unsubscribe_and_start_a_new_committed_append(tmp_path):
    catalog = _catalog(tmp_path)
    changes = []

    def once(change):
        changes.append(change)
        unsubscribe()
        catalog.append_message(SESSION, _message("nested"), session_key=KEY, event_id="nested")

    unsubscribe = catalog.subscribe_transcript_changes(once)
    catalog.append_message(SESSION, _message(), session_key=KEY, event_id="outer")
    assert len(changes) == 1
    assert catalog.read_transcript(SESSION).events[-1]["id"] == "nested"
    assert catalog.transcript_listener_diagnostics() == ()
