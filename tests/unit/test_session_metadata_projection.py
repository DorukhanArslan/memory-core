"""Current metadata projection follows actual participant and rotation owners."""
from contextlib import closing
import json

from memory_core.session_catalog import MemorySessionCatalog


KEY = "agent:main:dm:metadata"


def _catalog(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(KEY, {"sessionId": "old", "updatedAt": 1000, "chatType": "direct"})
    return catalog


def _record(catalog, actor, stamp):
    catalog.record_participant(KEY, {"identity": {"type": "profile", "id": actor},
                                     "promptedAt": stamp, "sessionAgentId": "main"})


def test_current_getter_projects_real_identities_in_native_order_without_persisting_projection(tmp_path):
    catalog = _catalog(tmp_path)
    _record(catalog, "alice", 20)
    _record(catalog, "bob", 10)
    _record(catalog, "alice", 30)
    entry = catalog.get_session_entry(KEY)
    assert entry["participants"] == [{"identity": {"type": "profile", "id": "bob"}},
                                      {"identity": {"type": "profile", "id": "alice"}}]
    assert entry["participantCount"] == 2
    assert catalog.list_participants(KEY)[KEY][1]["contributionCount"] == 2
    entry["participants"][0]["identity"]["id"] = "caller mutation"
    assert catalog.get_session_entry(KEY)["participants"][0]["identity"]["id"] == "bob"
    with closing(catalog._connect()) as db:
        raw = json.loads(db.execute("SELECT entry_json FROM memory_session_nodes").fetchone()[0])
    assert "participants" not in raw and "participantCount" not in raw


def test_absent_real_participants_do_not_gain_empty_defaults_or_authored_projection(tmp_path):
    catalog = _catalog(tmp_path)
    assert "participants" not in catalog.get_session_entry(KEY)
    assert "participantCount" not in catalog.get_session_entry(KEY)
    catalog.upsert_session(KEY, {"sessionId": "old", "participants": [
        {"identity": {"type": "profile", "id": "forged"}},
    ], "participantCount": 999})
    assert "participants" not in catalog.get_session_entry(KEY)
    assert "participantCount" not in catalog.get_session_entry(KEY)
    assert catalog.list_participants(KEY) == {}
    assert catalog.get_session_entry("agent:main:dm:unknown") is None


def test_reopened_getter_uses_actual_side_rows_after_metadata_replacement(tmp_path):
    catalog = _catalog(tmp_path)
    _record(catalog, "alice", 20)
    reopened = MemorySessionCatalog(catalog.path)
    _record(reopened, "bob", 10)
    catalog.upsert_session(KEY, {"sessionId": "old", "label": "replacement", "participants": [],
                                "participantCount": 0})
    assert [record["identity"]["id"] for record in catalog.get_session_entry(KEY)["participants"]] == ["bob", "alice"]
    assert reopened.get_session_entry(KEY)["participantCount"] == 2
    assert reopened.get_session_entry(KEY)["label"] == "replacement"


def test_continuation_and_active_instance_share_current_projection_without_copying_it_to_retained_instance(tmp_path):
    catalog = _catalog(tmp_path)
    _record(catalog, "alice", 10)
    catalog.append_message("old", {"role": "user", "content": "Old context"}, session_key=KEY, event_id="old-user")
    catalog.upsert_session(KEY, {"sessionId": "new", "previousSessionId": "old", "updatedAt": 2000})
    catalog.append_message("new", {"role": "user", "content": "New context"}, session_key=KEY, event_id="new-user")
    current = catalog.get_session_entry(KEY)
    assert current["participantCount"] == 1 and current["abortedLastRun"] is False
    assert catalog.read_continuation("new", session_key=KEY)["entry"] == current
    assert catalog.read_continuation("old", session_key=KEY)["entry"] == current
    instances = {entry["sessionId"]: entry for entry in catalog.list_transcript_instances()}
    assert instances["new"]["entry"]["participants"] == current["participants"]
    assert instances["new"]["entry"]["abortedLastRun"] is False
    assert "participants" not in instances["old"]["entry"]
    assert "participantCount" not in instances["old"]["entry"]
    assert "abortedLastRun" not in instances["old"]["entry"]


def test_rotation_clear_is_persisted_and_same_generation_replacement_has_no_aborted_default(tmp_path):
    catalog = _catalog(tmp_path)
    assert "abortedLastRun" not in catalog.get_session_entry(KEY)
    catalog.upsert_session(KEY, {"sessionId": "old", "abortedLastRun": True})
    assert catalog.get_session_entry(KEY)["abortedLastRun"] is True
    catalog.upsert_session(KEY, {"sessionId": "new", "abortedLastRun": True,
                                "restartRecoveryRuns": [{"runId": "stale"}],
                                "restartRecoveryDeliveryRunId": "delivery-adoption"})
    current = catalog.get_session_entry(KEY)
    assert current["abortedLastRun"] is False
    assert "restartRecoveryRuns" not in current
    assert current["restartRecoveryDeliveryRunId"] == "delivery-adoption"
    assert MemorySessionCatalog(catalog.path).get_session_entry(KEY)["abortedLastRun"] is False
    catalog.upsert_session(KEY, {"sessionId": "new", "label": "same-generation replacement"})
    assert "abortedLastRun" not in catalog.get_session_entry(KEY)


def test_lifecycle_revision_rotation_uses_the_same_actual_recovery_clear(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(KEY, {"sessionId": "old", "lifecycleRevision": "one", "abortedLastRun": True})
    assert catalog.get_session_entry(KEY)["abortedLastRun"] is False
    catalog.upsert_session(KEY, {"sessionId": "old", "lifecycleRevision": "one", "abortedLastRun": True})
    assert catalog.get_session_entry(KEY)["abortedLastRun"] is True
    catalog.upsert_session(KEY, {"sessionId": "old", "lifecycleRevision": "two", "abortedLastRun": True})
    assert catalog.get_session_entry(KEY)["abortedLastRun"] is False


def test_public_participant_projection_preserves_agent_and_process_only_catalog_boundaries(tmp_path):
    catalog = _catalog(tmp_path)
    _record(catalog, "main-alice", 10)
    ops = MemorySessionCatalog(catalog.path, agent_id="ops")
    ops.upsert_session("agent:ops:dm:metadata", {"sessionId": "old"})
    ops.record_participant("agent:ops:dm:metadata", {"identity": {"type": "profile", "id": "ops-bob"}, "promptedAt": 10})
    private = "agent:main:dashboard:incognito-metadata"
    catalog.upsert_session(private, {"sessionId": "private"})
    catalog.record_participant(private, {"identity": {"type": "profile", "id": "private-carol"}, "promptedAt": 10})
    assert catalog.get_session_entry(KEY)["participants"][0]["identity"]["id"] == "main-alice"
    assert ops.get_session_entry("agent:ops:dm:metadata")["participants"][0]["identity"]["id"] == "ops-bob"
    assert catalog.get_session_entry(private)["participants"][0]["identity"]["id"] == "private-carol"
    assert private not in catalog.snapshot().entries
