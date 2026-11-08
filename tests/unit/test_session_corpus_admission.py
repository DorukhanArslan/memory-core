import json
import os

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus, is_memory_session_indexable
from memory_core.workspace import MemoryWorkspace


def _message(text="Nebula archive fact", *, system=False):
    return {"type": "message", "message": {
        "role": "user", "content": text,
        **({"provenance": {"kind": "internal_system"}} if system else {"__openclaw": {"senderIsOwner": True}}),
    }}


def _catalog(tmp_path, **options):
    state = tmp_path / "state"
    store = state / "agents/main/sessions/sessions.json"
    store.parent.mkdir(parents=True)
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", store_path=store,
                                   clock_ms=lambda: 1000, **options)
    return catalog, MemoryCoreSessionCorpus(state, catalog=catalog)


def test_catalog_enumeration_and_manager_admission_are_distinct_real_owners(tmp_path):
    catalog, corpus = _catalog(tmp_path)
    rows = [
        ("agent:main:direct:alice", "interactive", {}),
        ("agent:main:hook", "plugin", {"pluginOwnerId": "plugin", "hookExternalContentSource": "gmail"}),
        ("agent:main:heartbeat", "heartbeat", {"heartbeatIsolatedBaseSessionKey": "agent:main:main"}),
        ("agent:main:cron:job:run:r1", "cron", {}),
        ("agent:main:dreaming-narrative-run", "dream", {}),
        ("agent:main:child", "cron-child", {"parentSessionKey": "agent:main:cron:job:run:r1"}),
    ]
    for key, identity, metadata in rows:
        catalog.upsert_session(key, {"sessionId": identity, "updatedAt": 100, **metadata})
        catalog.append_events(identity, [_message(identity)])
    entries = {entry["sessionId"]: entry for entry in corpus.discover_entries()}
    assert set(entries) == {row[1] for row in rows}
    assert entries["plugin"]["sessionKind"] == "interactive"
    assert "generatedByCronRun" not in entries["interactive"]
    assert entries["cron-child"]["sessionKind"] == "cron"
    assert entries["dream"]["generatedByDreamingNarrative"] is True
    assert {file.session_id for file in corpus.discover_files()} == {"interactive", "plugin"}


@pytest.mark.parametrize("metadata,known,acp,admitted", [
    ({}, True, False, True), ({}, False, False, False), ({}, True, True, False),
    ({"pluginOwnerId": "plugin"}, True, False, False),
    ({"hookExternalContentSource": "webhook"}, True, False, False),
])
def test_retained_windows_require_recorded_exclusion_sensitive_authority(tmp_path, metadata, known, acp, admitted):
    catalog, corpus = _catalog(tmp_path)
    catalog.retain_transcript("agent:main:old", {"sessionId": "retained", "updatedAt": 10, **metadata},
                              provenance_known=known, acp_owned=acp)
    catalog.append_events("retained", [_message()])
    assert corpus.discover_entries() == []
    retained = corpus.discover_entries(include_retained_sqlite=True)
    assert bool(retained) is admitted
    if admitted:
        assert retained[0]["artifactKind"] == "retained-session"


def test_registered_archive_identity_overrides_name_and_unowned_shared_artifact_is_excluded(tmp_path):
    catalog, corpus = _catalog(tmp_path, shared_store=True)
    directory = catalog.store_path.parent
    registered = directory / "guessed.jsonl.reset.2027-03-12T00-00-00.000Z"
    unknown = directory / "orphan.jsonl.deleted.2027-03-12T00-00-00.000Z"
    for filename in (registered, unknown):
        filename.write_text(json.dumps(_message()) + "\n", encoding="utf-8")
    catalog.record_archive(registered.name, "recorded", session_key="agent:main:old", path=registered)
    entry, = corpus.discover_entries()
    assert entry["sessionId"] == "recorded"
    assert entry["sessionKey"] == "agent:main:old"
    assert entry["artifactKind"] == "archive-artifact"
    assert corpus.read_index_entry(corpus.discover_files()[0]).content == "User: Nebula archive fact"


def test_foreign_owned_active_and_archive_rows_do_not_enter_the_selected_agent(tmp_path):
    catalog, corpus = _catalog(tmp_path)
    catalog.upsert_session("agent:ops:direct:alice", {"sessionId": "foreign"})
    catalog.append_events("foreign", [_message()])
    artifact = catalog.store_path.parent / "foreign.jsonl.reset.2027-03-12T00-00-00.000Z"
    artifact.write_text(json.dumps(_message()) + "\n", encoding="utf-8")
    assert corpus.discover_entries() == []


def test_nondefault_agent_main_aliases_preserve_the_registered_key_and_canonical_owner(tmp_path):
    state = tmp_path / "state"
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", agent_id="ops", main_key="primary",
                                   clock_ms=lambda: 1000)
    catalog.upsert_session("agent:main:main", {"sessionId": "legacy-main", "updatedAt": 10})
    catalog.append_events("legacy-main", [_message()])
    corpus = MemoryCoreSessionCorpus(state, agent_id="ops", catalog=catalog)
    entry, = corpus.discover_entries()
    assert entry["agentId"] == "ops"
    assert entry["sessionKey"] == entry["sessionFile"] == "agent:main:main"
    assert corpus.discover_files()[0].rel_path == "sessions/ops/legacy-main.jsonl"


def test_shared_store_unscoped_keys_use_the_actual_configured_default_owner(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", agent_id="ops", shared_store=True,
                                   default_agent_id="main", clock_ms=lambda: 1000)
    catalog.upsert_session("global", {"sessionId": "main-owned"})
    catalog.upsert_session("agent:ops:direct:alice", {"sessionId": "ops-owned"})
    catalog.append_events("main-owned", [_message()])
    catalog.append_events("ops-owned", [_message()])
    corpus = MemoryCoreSessionCorpus(tmp_path / "state", agent_id="ops", catalog=catalog)
    assert [entry["sessionId"] for entry in corpus.discover_entries()] == ["ops-owned"]


def test_catalog_ownership_is_loaded_after_real_filesystem_preparation(tmp_path, monkeypatch):
    catalog, corpus = _catalog(tmp_path)
    actual_discovery = corpus._archive_files

    def prepare_then_publish_metadata():
        files = actual_discovery()
        catalog.upsert_session("agent:main:fresh", {"sessionId": "fresh", "updatedAt": 10})
        return files

    monkeypatch.setattr(corpus, "_archive_files", prepare_then_publish_metadata)
    assert [entry["sessionId"] for entry in corpus.discover_entries()] == ["fresh"]


def test_compressed_archive_keeps_original_identity_and_size_through_projection_and_index(tmp_path):
    catalog, corpus = _catalog(tmp_path)
    compressed = bytes.fromhex(
        "28b52ffd207a1d0300f2451419704bdb8462d8628f7107c74f8a4a7cff0b04553992aa"
        "21870580b5d653ae15e73121a8206fc0ab951527770c1e41c7b1e60e76862261f2ec4e2a"
        "7cb0f84564f29a0e4a2b2b011f71aa5fd88a8f34d62a05008b8a5055ec9f4184baa6b71206"
    )
    path = catalog.store_path.parent / "s1.jsonl.reset.2027-03-12T00-00-00.000Z.zst"
    path.write_bytes(compressed)
    os.utime(path, ns=(1_804_800_000_123_000_000, 1_804_800_000_123_000_000))
    catalog.record_archive(path.name, "recorded", session_key="agent:main:old", path=path)
    file, = corpus.discover_files()
    source = corpus.read_source_entry(file)
    assert source["content"] == "User: Nebula archive fact"
    assert source["absPath"] == str(path)
    assert source["path"] == f"sessions/main/{path.name}"
    assert source["size"] == len(compressed)
    assert source["mtimeMs"] == 1_804_800_000_123
    assert "revisionMs" not in source

    root = tmp_path / "workspace"
    root.mkdir()
    config = MemoryConfig(root, flags=FeatureFlags(vector_search=False, mmr=False, temporal_decay=False))
    store = SQLiteMemoryStore(config, None)
    store.reindex(MemoryWorkspace(root, session_catalog=catalog, index_sources=["sessions"]))
    hit, = store.search("nebula", min_score=0, sources={"sessions"})
    assert hit.path == source["path"]
    assert hit.snippet == source["content"]
    assert not path.with_suffix("").exists()


def test_manager_admission_rejects_only_all_system_lineage_and_keeps_mixed_sources():
    assert not is_memory_session_indexable({"lineProvenance": [{"originClass": "system"}]})
    assert is_memory_session_indexable({"lineProvenance": [{"originClass": "system"}, {"originClass": "owner"}]})
    assert not is_memory_session_indexable({}, "agent:main:legacy:heartbeat")
    assert is_memory_session_indexable({"sessionKind": "subagent"})


def test_real_index_tracks_catalog_text_provenance_reset_and_tombstone_removal(tmp_path):
    catalog, corpus = _catalog(tmp_path)
    key = "agent:main:direct:alice"
    catalog.upsert_session(key, {"sessionId": "s1", "updatedAt": 100})
    catalog.replace_events("s1", [_message("Cobalt first fact")])
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = MemoryWorkspace(root, session_catalog=catalog, index_sources=["sessions"])
    config = MemoryConfig(root, flags=FeatureFlags(vector_search=False, mmr=False, temporal_decay=False))
    store = SQLiteMemoryStore(config, None)
    store.reindex(workspace)
    hits = store.search("cobalt", min_score=0, sources={"sessions"})
    assert len(hits) == 1
    assert hits[0].source == "sessions"
    first_hash = corpus.read_index_entry(corpus.discover_files()[0]).hash
    assert hits[0].provenance["originClass"] == "owner"

    catalog.replace_events("s1", [_message("Cobalt replacement"), {"type": "reset"}])
    store.reindex(workspace)
    assert corpus.read_index_entry(corpus.discover_files()[0]).hash != first_hash
    assert store.search("replacement", min_score=0, sources={"sessions"})
    catalog.tombstone_session("s1")
    store.reindex(workspace)
    assert store.search("cobalt", min_score=0, sources={"sessions"}) == []
    assert catalog.read_transcript("s1") is not None


def test_excluded_source_policy_does_not_open_session_catalog_or_memory_files(tmp_path, monkeypatch):
    catalog, _corpus = _catalog(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = MemoryWorkspace(root, session_catalog=catalog, index_sources=[])
    monkeypatch.setattr(workspace, "discover_memory_files", lambda: pytest.fail("memory corpus was excluded"))
    monkeypatch.setattr(catalog, "snapshot", lambda: pytest.fail("session corpus was excluded"))
    assert workspace.discover_indexable_files() == []
