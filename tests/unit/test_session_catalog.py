from dataclasses import asdict

import pytest

from memory_core.session_catalog import MemorySessionCatalog


def _message(text="Saved fact", *, entry_id="m1"):
    return {"type": "message", "id": entry_id,
            "message": {"role": "user", "content": text, "__openclaw": {"senderIsOwner": True}}}


def test_persisted_catalog_reopens_and_returns_independent_metadata_and_event_snapshots(tmp_path):
    path = tmp_path / "catalog.sqlite"
    catalog = MemorySessionCatalog(path, clock_ms=lambda: 1000)
    metadata = {"sessionId": "s1", "updatedAt": 10,
                "participants": [{"identity": {"type": "profile", "id": "alice"}}]}
    events = [_message()]
    catalog.upsert_session("agent:main:main", metadata)
    catalog.append_events("s1", events)
    metadata["participants"].clear()
    events[0]["message"]["content"] = "caller mutation"

    reopened = MemorySessionCatalog(path, clock_ms=lambda: 1000)
    snapshot = reopened.snapshot()
    assert snapshot.entries["agent:main:main"]["participants"] == [
        {"identity": {"type": "profile", "id": "alice"}},
    ]
    transcript = reopened.read_transcript("s1")
    assert transcript.events[0]["message"]["content"] == "Saved fact"
    snapshot.entries["agent:main:main"]["participants"].clear()
    transcript.events[0]["message"]["content"] = "borrowed mutation"
    assert reopened.snapshot().entries["agent:main:main"]["participants"]
    assert reopened.read_transcript("s1").events[0]["message"]["content"] == "Saved fact"


def test_catalog_mutation_watermark_moves_even_when_clock_and_rendered_content_do_not(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session("agent:main:main", {"sessionId": "s1", "updatedAt": 10})
    events = [_message()]
    catalog.replace_events("s1", events)
    first = catalog.read_transcript("s1")
    catalog.replace_events("s1", events)
    second = catalog.read_transcript("s1")
    assert first.events == second.events
    assert first.mutation_at_ms == 1001
    assert second.mutation_at_ms == 1002
    assert second.revision > first.revision


def test_rotating_and_removing_current_metadata_retains_original_transcript_authority(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    key = "agent:main:telegram:direct:alice"
    catalog.upsert_session(key, {"sessionId": "old", "updatedAt": 10, "chatType": "direct"})
    catalog.append_events("old", [_message("Old fact")])
    catalog.upsert_session(key, {"sessionId": "new", "previousSessionId": "old", "updatedAt": 20})
    catalog.append_events("new", [_message("New fact")])
    assert catalog.snapshot().entries[key]["sessionId"] == "new"
    assert catalog.read_transcript("old", session_key=key).events[0]["message"]["content"] == "Old fact"
    assert catalog.load_session_metadata({"agentId": "main", "sessionId": "old", "sessionKey": key})["chatType"] == "direct"
    catalog.remove_session(key)
    assert catalog.snapshot().entries == {}
    assert catalog.read_transcript("old", session_key=key) is not None


def test_catalog_agent_namespaces_and_identity_reads_fail_closed(tmp_path):
    path = tmp_path / "catalog.sqlite"
    main = MemorySessionCatalog(path, agent_id="main", clock_ms=lambda: 1000)
    ops = MemorySessionCatalog(path, agent_id="ops", clock_ms=lambda: 1000)
    for catalog, content in ((main, "main fact"), (ops, "ops fact")):
        catalog.upsert_session(f"agent:{catalog.agent_id}:main", {"sessionId": "shared-id"})
        catalog.append_events("shared-id", [_message(content)])
    assert list(main.snapshot().entries) == ["agent:main:main"]
    assert list(ops.snapshot().entries) == ["agent:ops:main"]
    assert main.read_transcript("shared-id").events[0]["message"]["content"] == "main fact"
    with pytest.raises(ValueError, match="different catalog agent"):
        main.read_transcript("shared-id", agent_id="ops")
    assert main.read_transcript("shared-id", session_key="agent:main:unknown") is None


def test_reset_cutoff_is_read_from_current_persisted_events_and_tombstones_do_not_authorize_history(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session("agent:main:main", {"sessionId": "s1"})
    catalog.replace_events("s1", [
        _message("before", entry_id="before"), _message("kept", entry_id="kept"),
        {"type": "reset", "firstKeptEntryId": "kept"},
    ])
    assert catalog.read_reset_cutoff("s1") == {"state": "valid", "cutoffLine": 2}
    old_snapshot = catalog.snapshot()
    catalog.tombstone_session("s1")
    assert old_snapshot.forgotten_session_ids == frozenset()
    assert catalog.snapshot().forgotten_session_ids == frozenset({"s1"})
    assert catalog.read_transcript("s1") is not None
    catalog.replace_events("s1", [_message("new stream"), {"type": "reset", "firstKeptEntryId": "gone"}])
    assert catalog.read_reset_cutoff("s1") == {"state": "invalid"}


def test_internal_effect_windows_are_not_public_corpus_entries_but_raw_reads_are_separate(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session("agent:main:internal-session-effects:hidden", {"sessionId": "hidden"})
    catalog.append_events("hidden", [_message()])
    snapshot = catalog.snapshot()
    assert snapshot.entries == {}
    assert snapshot.instances == ()
    assert catalog.read_transcript("hidden") is not None


def test_archive_binding_is_a_persisted_identity_not_a_filename_guess(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.record_archive("old-name.jsonl.reset.2027-03-12T00-00-00.000Z", "recorded-id",
                           session_key="agent:main:main", path=tmp_path / "artifact")
    archive, = catalog.snapshot().archives
    assert asdict(archive) == {
        "archive_name": "old-name.jsonl.reset.2027-03-12T00-00-00.000Z",
        "session_id": "recorded-id", "session_key": "agent:main:main",
        "path": tmp_path / "artifact", "agent_id": "main",
    }
