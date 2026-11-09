"""Real SQLite session revisions refresh fingerprints without replacing stable chunks."""
from copy import deepcopy

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.identity import INDEX_SOURCES_TABLE
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.workspace import MemoryWorkspace


_KEY = "agent:main:direct:fingerprint"
_EVENTS = [{"type": "message", "id": "fixed", "message": {
    "role": "user", "content": "A fixed conversation preference.", "timestamp": 1794182400000,
    "__openclaw": {"senderIsOwner": True}}}]


def _owners(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    clock = [1800000000000]
    catalog = MemorySessionCatalog(state / "agents/main/sessions/authority.sqlite", agent_id="main",
        store_path=state / "agents/main/sessions/sessions.json", clock_ms=lambda: clock[0])
    catalog.upsert_session(_KEY, {"sessionId": "fingerprint", "chatType": "direct", "updatedAt": clock[0]})
    catalog.replace_events("fingerprint", deepcopy(_EVENTS), session_key=_KEY)
    config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    memory_workspace = MemoryWorkspace(workspace, openclaw_state_dir=state, session_catalog=catalog,
                                       index_sources=["memory", "sessions"])
    corpus = MemoryCoreSessionCorpus(state, catalog=catalog, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    return clock, catalog, corpus, store, memory_workspace


def test_same_content_revision_refreshes_exact_fingerprint_without_reparsing_or_republishing(tmp_path, monkeypatch):
    clock, catalog, corpus, store, workspace = _owners(tmp_path)
    store.reindex(workspace)
    before = store.read_published_index()
    source = before["sources"][0]
    file, = corpus.discover_files()
    entry = corpus.read_source_entry(file)
    assert source["hash"] == f"sqlite:{int(entry['revisionMs'])}:{entry['hash']}"
    clock[0] += 500
    catalog.replace_events("fingerprint", deepcopy(_EVENTS), session_key=_KEY)

    def no_reprepare(*args):
        raise AssertionError("A revision-only metadata refresh must keep the original chunks")

    monkeypatch.setattr(store, "_prepare_source_chunks", no_reprepare)
    store.reindex(workspace)
    after = store.read_published_index()
    for name in ("chunks", "fts", "paths", "provenance", "recall", "details"):
        assert after[name] == before[name]
    assert after["sources"][0]["hash"] != source["hash"]
    assert after["sources"][0]["hash"].rsplit(":", 1)[-1] == source["hash"].rsplit(":", 1)[-1]
    assert after["revision"] == before["revision"] + 1


def test_restored_bare_content_fingerprint_converges_without_republishing(tmp_path, monkeypatch):
    _, _, _, store, workspace = _owners(tmp_path)
    store.reindex(workspace)
    before = store.read_published_index()
    content_hash = before["sources"][0]["hash"].rsplit(":", 1)[-1]
    with store.connect() as db:
        db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET hash=?", (content_hash,))
    monkeypatch.setattr(store, "_prepare_source_chunks", lambda *args: (_ for _ in ()).throw(AssertionError("reparse")))
    store.reindex(workspace)
    after = store.read_published_index()
    assert after["sources"] == before["sources"]
    assert after["chunks"] == before["chunks"]


def test_revision_only_source_and_changed_memory_publish_together_without_losing_session_identity(tmp_path):
    clock, catalog, _, store, workspace = _owners(tmp_path)
    note = workspace.root / "MEMORY.md"
    note.write_text("Old memory")
    store.reindex(workspace)
    before = store.read_published_index()
    session = [row for row in before["chunks"] if row["source"] == "sessions"]
    clock[0] += 500
    catalog.replace_events("fingerprint", deepcopy(_EVENTS), session_key=_KEY)
    note.write_text("New memory")
    store.reindex(workspace)
    after = store.read_published_index()
    assert [row for row in after["chunks"] if row["source"] == "sessions"] == session
    old_source = next(row for row in before["sources"] if row["source"] == "sessions")
    new_source = next(row for row in after["sources"] if row["source"] == "sessions")
    assert new_source["hash"] != old_source["hash"]
    assert next(row for row in after["chunks"] if row["source"] == "memory")["text"] == "New memory"


def test_changed_text_and_valid_reset_replace_real_corpus_fingerprints_and_chunk_rows(tmp_path):
    clock, catalog, _, store, workspace = _owners(tmp_path)
    store.reindex(workspace)
    before = store.read_published_index()
    clock[0] += 500
    changed = deepcopy(_EVENTS)
    changed[0]["message"]["content"] = "An updated conversation preference."
    changed.append({"type": "message", "id": "kept", "message": {
        "role": "user", "content": "Kept owner context.", "timestamp": 1794182401000,
        "__openclaw": {"senderIsOwner": True}}})
    changed.append({"type": "reset", "id": "reset", "firstKeptEntryId": "kept"})
    catalog.replace_events("fingerprint", changed, session_key=_KEY)
    store.reindex(workspace)
    after = store.read_published_index()
    assert before["sources"][0]["hash"] != after["sources"][0]["hash"]
    assert {row["id"] for row in before["chunks"]}.isdisjoint(row["id"] for row in after["chunks"])
    assert [row["text"] for row in after["chunks"]] != [row["text"] for row in before["chunks"]]
