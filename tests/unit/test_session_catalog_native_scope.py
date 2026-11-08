"""SQL regressions for native storage identities and transcript activity fences."""
from contextlib import closing
import sqlite3

import pytest

from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus


def _event(text="Saved fact"):
    return {"type": "message", "id": "one", "message": {"role": "user", "content": text}}


@pytest.mark.parametrize("requested,stored", [
    (" Legacy-Unscoped ", "agent:ops:legacy-unscoped"),
    (" Main ", "agent:ops:main"),
    (" GLOBAL ", "global"),
    ("unknown", "unknown"),
    ("", ""),
    ("Agent:OPS:Direct:ALICE", "agent:ops:direct:alice"),
    ("Signal:Group:AbC:THREAD:XYZ", "agent:ops:signal:group:AbC:thread:xyz"),
    ("Matrix:Group:!Room:EXAMPLE:Thread:$Event", "agent:ops:matrix:group:!Room:EXAMPLE:thread:$Event"),
])
def test_sql_storage_scope_canonicalizes_ordinary_keys_and_preserves_opaque_ids(tmp_path, requested, stored):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", agent_id="ops", main_key="primary",
                                   clock_ms=lambda: 1000)
    catalog.upsert_session(requested, {"sessionId": "one", "updatedAt": 1000})
    catalog.replace_events("one", [_event()], session_key=requested)
    reopened = MemorySessionCatalog(catalog.path, agent_id="ops")
    assert list(reopened.snapshot().entries) == [stored]
    assert reopened.get_session_entry(requested) == reopened.get_session_entry(stored)
    transcript = reopened.read_transcript("one", session_key=requested)
    assert transcript.session_key == stored
    assert list(transcript.events) == [_event()]
    with sqlite3.connect(catalog.path) as db:
        assert db.execute("SELECT session_key FROM memory_session_nodes").fetchall() == [(stored,)]
        assert db.execute("SELECT session_key FROM memory_session_windows").fetchall() == [(stored,)]


def test_unscoped_identity_is_shared_by_all_actual_catalog_accessors(tmp_path):
    raw, key = "Legacy-Unscoped", "agent:main:legacy-unscoped"
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", shared_store=True, clock_ms=lambda: 1000)
    catalog.upsert_session(raw, {"sessionId": "one", "updatedAt": 1000, "chatType": "direct"})
    catalog.append_events("one", [_event()], session_key=key)
    catalog.replace_events("one", [_event("Replacement")], session_key=raw)
    assert catalog.get_session_entry(key) == catalog.get_session_entry(raw)
    assert catalog.read_transcript("one", session_key=key) == catalog.read_transcript("one", session_key=raw)
    assert catalog.read_transcript("one", session_key="another-key") is None
    with pytest.raises(ValueError, match="does not belong"):
        catalog.append_events("one", [_event()], session_key="another-key")

    record = {"identity": {"type": "profile", "id": "alice"}, "promptedAt": 42}
    assert catalog.record_participant(raw, record) == "inserted"
    assert catalog.record_participant(key, record) == "updated"
    assert catalog.list_participants(raw) == catalog.list_participants(key)
    assert catalog.list_participants(raw)[key][0]["contributionCount"] == 2
    catalog.record_archive("one.jsonl.reset.saved", "one", session_key=raw)
    assert catalog.snapshot().archives[0].session_key == key
    catalog.retain_transcript(raw, {"sessionId": "old", "updatedAt": 10}, provenance_known=True)
    catalog.append_events("old", [_event("Retained")], session_key=key)
    assert catalog.read_transcript("old", session_key=raw).session_key == key
    origin = {"agentId": "main", "sessionId": "one", "sessionKey": raw}
    metadata = catalog.load_session_metadata(origin, str(catalog.store_path))
    assert metadata == catalog.load_session_metadata({**origin, "sessionKey": key}, str(catalog.store_path))
    assert metadata["sessionKey"] == key
    catalog.tombstone_session("old", session_key=raw)
    assert catalog.snapshot().forgotten_session_ids == frozenset({"old"})

    with sqlite3.connect(catalog.path) as db:
        for table in ("memory_session_nodes", "memory_session_windows", "memory_session_participants",
                      "memory_session_archives"):
            assert set(db.execute(f"SELECT DISTINCT session_key FROM {table}").fetchall()) == {(key,)}
    catalog.remove_session(raw)
    assert catalog.get_session_entry(key) is None
    assert catalog.list_participants(key) == {}
    assert catalog.read_transcript("one", session_key=raw) is not None


def test_replacements_advance_recorded_activity_and_retained_corpus_mtime(tmp_path):
    key = "agent:main:direct:alice"
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(key, {"sessionId": "old", "updatedAt": 1000})
    catalog.replace_events("old", [_event()], session_key=key)
    first = catalog.read_transcript("old", session_key=key)
    catalog.replace_events("old", [_event()], session_key=key)
    second = catalog.read_transcript("old", session_key=key)
    assert first.updated_at_ms == 1001
    assert second.updated_at_ms == 1002
    assert first.events == second.events

    # Registry observation snapshots transcript activity, rather than treating
    # unrelated metadata bookkeeping as a new transcript event.
    catalog.upsert_session(key, {"sessionId": "old", "updatedAt": 10000})
    catalog.replace_events("old", [_event()], session_key=key)
    assert catalog.read_transcript("old", session_key=key).updated_at_ms == 1003
    catalog.replace_events("old", [_event()], updated_at_ms=900, session_key=key)
    assert catalog.read_transcript("old", session_key=key).updated_at_ms == 1004
    catalog.replace_events("old", [_event()], updated_at_ms=12000.9, session_key=key)
    assert catalog.read_transcript("old", session_key=key).updated_at_ms == 12000
    assert catalog.get_session_entry(key)["updatedAt"] == 10000

    catalog.upsert_session(key, {"sessionId": "new", "updatedAt": 1000})
    catalog.replace_events("new", [_event("Current")], session_key=key)
    corpus = MemoryCoreSessionCorpus(tmp_path / "state", catalog=catalog)
    retained = next(entry for entry in corpus.discover_entries(include_retained_sqlite=True)
                    if entry["sessionId"] == "old")
    assert retained["artifactKind"] == "retained-session"
    assert retained["updatedAtMs"] == 12000
    assert catalog.load_session_metadata({"agentId": "main", "sessionId": "old", "sessionKey": key})["createdAt"] == 1000
    with sqlite3.connect(catalog.path) as db:
        activity, observed = db.execute("SELECT transcript_updated_at,transcript_observed_at "
                                        "FROM memory_session_windows WHERE session_id='old'").fetchone()
    assert (activity, observed) == (12000, 1002)


def test_initial_observed_timestamp_and_reopened_schema_prevent_activity_regression(tmp_path):
    key = "agent:main:direct:alice"
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(key, {"sessionId": "one", "updatedAt": 3000})
    catalog.replace_events("one", [_event()], session_key=key)
    assert catalog.read_transcript("one", session_key=key).updated_at_ms == 3001
    # Exercise the migration from the prior real SDK schema, not a mock reader.
    with sqlite3.connect(catalog.path) as db:
        db.execute("ALTER TABLE memory_session_windows DROP COLUMN transcript_observed_at")
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 900)
    reopened.replace_events("one", [_event()], session_key=key)
    assert reopened.read_transcript("one", session_key=key).updated_at_ms == 3002


def test_key_normalization_keeps_actual_private_database_routing_process_only(tmp_path):
    raw, key = " AGENT:MAIN:Dashboard:Incognito-Hidden ", "agent:main:dashboard:incognito-hidden"
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(raw, {"sessionId": "private", "updatedAt": 1000})
    catalog.replace_events("private", [_event("Private")], session_key=key)
    catalog.record_participant(raw, {"identity": {"type": "profile", "id": "alice"}})
    assert catalog.get_session_entry(raw) == catalog.get_session_entry(key)
    assert catalog.read_transcript("private", session_key=raw).session_key == key
    assert key in catalog.list_participants(raw)
    assert catalog.snapshot().entries == {}
    with closing(catalog._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM memory_session_windows").fetchone()[0] == 0
    assert not catalog.path.with_name("incognito-openclaw-agent.sqlite").exists()
