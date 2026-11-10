"""Actual cold-index repairs, live notice transitions and physical source custody."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import inspect
import os
import sqlite3
import threading

import pytest

from memory_core.cancellation import CancellationSignal
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, HostModelResult, HostSessionRunner, SessionState
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.managed_session import ManagedHostSession
from memory_core.index.identity import MEMORY_INDEX_META_KEY
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError, SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.deadline import MemorySearchDeadlineControl
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_182_400_000


def _owner(tmp_path, *, text=None, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY):
    root = tmp_path / "workspace"
    root.mkdir()
    if text is not None:
        (root / "memory").mkdir()
        (root / "memory/2026-11-09.md").write_text(text, encoding="utf-8")
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite", citation_mode="off",
        session_search=False, flags=FeatureFlags(vector_search=False, temporal_decay=False))
    workspace = MemoryWorkspace(root, index_sources=["memory"])
    store = ManagedSQLiteMemoryStore(config, workspace, runtime_identity=runtime_identity)
    return config, workspace, store


def _search(config, store, query="cedar"):
    tool = create_memory_search_tool(config, store, context=MemorySearchToolContext(clock=lambda: NOW),
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    envelope = tool.execute("actual-search", {"query": query, "corpus": "memory", "minScore": 0})
    assert json.loads(envelope["content"][0]["text"]) == envelope["details"]
    return envelope["details"]


def test_cold_real_note_is_published_and_notice_is_not_replayed(tmp_path):
    config, workspace, store = _owner(tmp_path, text="My drink preference is cedar tea.\n")
    assert store.read_index_meta() is None
    notice = store.status()["custom"]["automaticRebuildNotice"]
    assert notice["sequence"] == 0

    first = _search(config, store)

    assert first["results"][0]["snippet"] == "My drink preference is cedar tea.\n"
    assert first["warning"] == (
        "Automatic memory index repair was requested. To rebuild manually, run: "
        "openclaw memory status --index --agent main. Rebuilding uses keyword indexing only "
        "and does not call an embedding provider."
    )
    assert store.index_identity() == {"status": "valid"}
    assert store.status()["custom"]["automaticRebuildNotice"] is notice
    assert notice["sequence"] == 1
    published = store.read_published_index()
    assert published["chunks"][0]["text"] == (workspace.root / "memory/2026-11-09.md").read_text()
    second = _search(config, store)
    assert second["results"] == first["results"]
    assert "warning" not in second and "corpora" not in second
    assert store.read_published_index() == published
    snapshot = store.lifecycle_snapshot()
    assert len(snapshot["repairs"]) == 1
    assert snapshot["repairs"][0]["state"] == "completed"
    assert snapshot["repairs"][0]["returned"] == 1
    snapshot["repairs"].clear()
    assert len(store.lifecycle_snapshot()["repairs"]) == 1


def test_cold_empty_index_repairs_metadata_without_fabricating_results(tmp_path):
    config, _, store = _owner(tmp_path)

    first = _search(config, store)

    assert first["results"] == [] and first["corpora"] == []
    assert "Automatic memory index repair was requested." in first["warning"]
    assert store.index_identity() == {"status": "valid"}
    assert store.read_published_index()["chunks"] == []
    second = _search(config, store)
    assert second["results"] == [] and "warning" not in second
    assert store.lifecycle_snapshot()["automaticRebuildNotice"]["sequence"] == 1


def test_failed_actual_repair_preserves_error_and_requires_explicit_recovery(tmp_path, monkeypatch):
    config, workspace, store = _owner(tmp_path, text="Cedar source remains on disk.\n")
    discover = workspace.discover_indexable_files
    failure = OSError("real source scan unavailable")
    attempts = []

    def refuse():
        attempts.append(True)
        raise failure

    monkeypatch.setattr(workspace, "discover_indexable_files", refuse)
    actual = _search(config, store)
    assert actual["results"] == []
    assert store.read_index_meta() is None
    assert store.status()["lastSyncError"] == "real source scan unavailable"
    snapshot = store.lifecycle_snapshot()
    assert snapshot["repairs"][0]["state"] == "failed"
    assert any(operation["name"] == "reindex" and operation["state"] == "failed" for operation in snapshot["operations"])
    _search(config, store)
    assert len(attempts) == 1
    with pytest.raises(OSError) as raised:
        store.reindex(workspace, force=True)
    assert raised.value is failure
    monkeypatch.setattr(workspace, "discover_indexable_files", discover)
    store.reindex(workspace, force=True)
    assert "lastSyncError" not in store.status()
    assert _search(config, store)["results"][0]["snippet"] == "Cedar source remains on disk.\n"


def test_newer_index_identity_is_not_automatically_overwritten(tmp_path):
    config, workspace, store = _owner(tmp_path, text="Cedar durable note.\n")
    store.reindex(workspace)
    meta = store.read_index_meta()
    meta["chunkingVersion"] += 1
    with store.connect() as db:
        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?", (json.dumps(meta), MEMORY_INDEX_META_KEY))
    before = store.read_published_index()

    actual = _search(config, store)

    assert actual["results"] == [] and actual["unavailable"] is True
    assert store.index_identity()["versionOrder"] == "newer"
    assert store.read_published_index() == before
    assert store.lifecycle_snapshot()["repairs"] == []


def test_managed_constructor_and_publication_refuse_other_owners_before_io(tmp_path):
    config, workspace, store = _owner(tmp_path)
    other = tmp_path / "other"
    with pytest.raises(ValueError, match="same owner"):
        ManagedSQLiteMemoryStore(replace(config, workspace_dir=other, store_path=other / "index.sqlite"), workspace)
    assert not other.exists()
    with pytest.raises(ValueError, match="provider-none"):
        ManagedSQLiteMemoryStore(replace(config, flags=FeatureFlags(vector_search=True), store_path=other / "index.sqlite"), workspace)
    assert not other.exists()
    with pytest.raises(ValueError, match="bound workspace"):
        store.reindex(MemoryWorkspace(other), force=True)
    assert not other.exists()


def test_existing_host_constructors_integrate_cold_managed_owner(tmp_path):
    config, workspace, store = _owner(tmp_path, text="My drink preference is cedar tea.\n")
    catalog = MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW)
    workspace.session_catalog = catalog
    # Bind the real catalog at construction, rather than rebinding an admitted
    # manager's ownership after it has begun serving calls.
    store = ManagedSQLiteMemoryStore(config, workspace,
        artifact_provenance=MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite"),
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    memory = Memory(config, workspace, store)
    kit = HostKit(memory, artifact_provenance=store.artifact_provenance, now_ms=lambda: NOW,
                  identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    runner = HostSessionRunner(kit, catalog, session=SessionState.new(
        session_key="agent:main:dm:managed", session_id="managed-reader"))
    assert store.read_index_meta() is None

    async def execute(turn):
        arguments = {"query": "drink preference", "corpus": "memory", "minScore": 0}
        turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "read", "name": "memory_search", "arguments": arguments}]})
        actual = await turn.dispatch_async("read", "memory_search", arguments)
        assert actual["results"][0]["snippet"] == "My drink preference is cedar tea.\n"
        assert "Automatic memory index repair was requested." in actual["warning"]
        return HostModelResult()

    outcome = asyncio.run(runner.run_turn("What drink preference did I ask you to remember?", execute=execute))
    assert outcome.ready
    assert store.lifecycle_snapshot()["automaticRebuildNotice"]["sequence"] == 1


def test_close_joins_real_repair_after_awaiting_caller_is_cancelled(tmp_path, monkeypatch):
    _, workspace, store = _owner(tmp_path, text="Cedar repair must settle.\n")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    discover = workspace.discover_indexable_files
    results = []

    def held_scan():
        entered.set()
        assert release.wait(5)
        return discover()

    monkeypatch.setattr(workspace, "discover_indexable_files", held_scan)

    def actual_search():
        try:
            results.extend(store.search("cedar", sources={"memory"}, min_score=0))
        finally:
            finished.set()

    async def scenario():
        caller = asyncio.create_task(asyncio.to_thread(actual_search))
        assert await asyncio.to_thread(entered.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        closing = asyncio.create_task(asyncio.to_thread(store.close))

        def await_closing():
            with store._condition:
                return store._condition.wait_for(lambda: store._closing, timeout=5)

        assert await asyncio.to_thread(await_closing)
        assert not closing.done() and not store.closed
        with pytest.raises(RuntimeError, match="closed"):
            store.search("new caller")
        release.set()
        await closing
        assert await asyncio.to_thread(finished.wait, 5)

    asyncio.run(scenario())
    assert results and store.closed
    assert store.lifecycle_snapshot()["activeOperations"] == 0
    with pytest.raises(RuntimeError, match="closed"):
        store.status()


def test_pre_cancelled_search_never_requests_or_publishes_a_repair(tmp_path):
    _, _, store = _owner(tmp_path, text="Cedar must remain unindexed.\n")
    signal = CancellationSignal()
    failure = RuntimeError("cancelled actual search")
    signal.abort(failure)
    with pytest.raises(RuntimeError) as raised:
        store.search("cedar", signal=signal)
    assert raised.value is failure
    assert store.read_index_meta() is None
    assert store.lifecycle_snapshot()["repairs"] == []


def test_status_journal_is_bounded_without_reusing_operation_ids(tmp_path):
    _, _, store = _owner(tmp_path)
    for _ in range(520):
        store.status()
    snapshot = store.lifecycle_snapshot()
    assert snapshot["operationCount"] == 520
    assert snapshot["operationJournalTruncated"] is True
    assert len(snapshot["operations"]) == 512
    assert snapshot["operations"][0]["id"] == 9
    assert snapshot["operations"][-1]["id"] == 520
    assert snapshot["repairCount"] == 0 and snapshot["repairJournalTruncated"] is False


def test_managed_search_preserves_the_base_typed_public_signature():
    assert inspect.signature(ManagedSQLiteMemoryStore.search) == inspect.signature(SQLiteMemoryStore.search)


def test_managed_search_forwards_every_option_to_the_actual_base_owner(tmp_path, monkeypatch):
    _, _, store = _owner(tmp_path, text="Cedar real source.\n")
    original = SQLiteMemoryStore.search
    observed = []

    def record(owner, query, **options):
        observed.append((owner, query, options))
        return original(owner, query, **options)

    monkeypatch.setattr(SQLiteMemoryStore, "search", record)
    options = {"max_results": 2, "min_score": 0.0, "sources": {"memory"},
        "signal": CancellationSignal(), "active_project_keys": ["alpha"],
        "on_partial_results": lambda _results: None, "session_key": "agent:main:typed-search",
        "on_debug": lambda _event: None, "deadline_control": MemorySearchDeadlineControl()}

    actual = store.search("cedar", **options)

    assert actual and actual[0].snippet == "Cedar real source.\n"
    assert observed[0][:2] == (store, "cedar")
    assert observed[0][2].keys() == options.keys()
    assert all(observed[0][2][key] is value for key, value in options.items())
    assert actual == original(store, "cedar", **options)


def test_managed_search_rethrows_the_original_base_error(tmp_path, monkeypatch):
    _, workspace, store = _owner(tmp_path, text="Cedar already indexed.\n")
    store.reindex(workspace)
    failure = RuntimeError("original base search failure")

    def refuse(*_args, **_options):
        raise failure

    monkeypatch.setattr(SQLiteMemoryStore, "search", refuse)
    with pytest.raises(RuntimeError) as raised:
        store.search("cedar")
    assert raised.value is failure


def _block_index_publication(tmp_path):
    """A real unusable rollback-journal path: readers work, every publication fails."""
    journal = tmp_path / "index.sqlite-journal"
    os.symlink(tmp_path / "missing-journal-directory" / "journal", journal)
    return journal


STALE_WARNING = "Memory index is stale: unable to open database file. Search results may be incomplete."
STALE_ACTION = ("Run: openclaw memory status --index --agent main. Rebuilding uses keyword indexing only "
                "and does not call an embedding provider.")


def test_failed_memory_scope_publication_is_reported_stale_until_that_scope_publishes(tmp_path):
    config, workspace, store = _owner(tmp_path, text="My drink preference is cedar tea.\n")
    assert _search(config, store, "drink preference")["results"][0]["snippet"] == "My drink preference is cedar tea.\n"
    (workspace.root / "memory/2026-11-09.md").write_text("My drink preference is now birch coffee.\n", encoding="utf-8")
    journal = _block_index_publication(tmp_path)

    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        store.reindex_sources(workspace, sources=["memory"])

    assert store.status()["lastSyncError"] == "unable to open database file"
    stale = _search(config, store, "drink preference")
    assert stale["stale"] is True
    assert stale["warning"] == STALE_WARNING
    assert stale["action"] == STALE_ACTION
    assert stale["results"][0]["snippet"] == "My drink preference is cedar tea.\n"
    # The whole-reindex receipt is unchanged; the scoped failure has its own.
    snapshot = store.lifecycle_snapshot()
    assert snapshot["lastSyncError"] is None
    assert snapshot["memoryScopeSyncFailure"] == {"error": "unable to open database file", "paths": None}

    journal.unlink()
    assert store.reindex_sources(workspace, sources=["memory"]) >= 1
    assert "lastSyncError" not in store.status()
    assert "memoryScopeSyncFailure" not in store.lifecycle_snapshot()
    current = _search(config, store, "drink preference")
    assert "stale" not in current and "warning" not in current and "action" not in current
    assert current["results"][0]["snippet"] == "My drink preference is now birch coffee.\n"


def test_whole_reindex_failure_takes_precedence_and_its_success_clears_both(tmp_path, monkeypatch):
    config, workspace, store = _owner(tmp_path, text="Cedar source remains on disk.\n")
    _search(config, store)
    (workspace.root / "memory/2026-11-09.md").write_text("Cedar source changed on disk.\n", encoding="utf-8")
    journal = _block_index_publication(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        store.reindex_sources(workspace, sources=["memory"])
    assert store.status()["lastSyncError"] == "unable to open database file"

    def labelled_whole_failure(self, selected, *, force=False):
        raise RuntimeError("labelled whole-reindex fixture failure")

    with monkeypatch.context() as patched:
        patched.setattr(SQLiteMemoryStore, "reindex", labelled_whole_failure)
        with pytest.raises(RuntimeError, match="labelled whole-reindex fixture failure"):
            store.reindex(workspace, force=True)
    assert store.status()["lastSyncError"] == "labelled whole-reindex fixture failure"
    snapshot = store.lifecycle_snapshot()
    assert snapshot["lastSyncError"] == "labelled whole-reindex fixture failure"
    assert snapshot["memoryScopeSyncFailure"]["error"] == "unable to open database file"

    journal.unlink()
    store.reindex(workspace, force=True)
    assert "lastSyncError" not in store.status()
    snapshot = store.lifecycle_snapshot()
    assert snapshot["lastSyncError"] is None and "memoryScopeSyncFailure" not in snapshot
    current = _search(config, store)
    assert "stale" not in current and current["results"][0]["snippet"] == "Cedar source changed on disk.\n"


def test_sessions_only_publications_neither_set_nor_settle_memory_staleness(tmp_path, monkeypatch):
    config, workspace, store = _owner(tmp_path, text="Cedar source remains on disk.\n")
    _search(config, store)

    def labelled_session_failure(self, selected, *, sources, paths=None, force_sources=False):
        raise RuntimeError("labelled session-scope fixture failure")

    with monkeypatch.context() as patched:
        patched.setattr(SQLiteMemoryStore, "reindex_sources", labelled_session_failure)
        with pytest.raises(RuntimeError, match="labelled session-scope fixture failure"):
            store.reindex_sources(workspace, sources={"sessions"})
    assert "lastSyncError" not in store.status()

    (workspace.root / "memory/2026-11-09.md").write_text("Cedar source changed on disk.\n", encoding="utf-8")
    journal = _block_index_publication(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        store.reindex_sources(workspace, sources=["memory"])
    journal.unlink()
    # A real, successful sessions-only publication of every path is what the
    # background session publisher issues. It must not erase the memory report.
    assert store.reindex_sources(workspace, sources={"sessions"}) == 0
    assert store.status()["lastSyncError"] == "unable to open database file"
    assert _search(config, store)["stale"] is True
    assert store.reindex_sources(workspace, sources={"memory", "sessions"}) >= 1
    assert "lastSyncError" not in store.status()
    assert "stale" not in _search(config, store)


def test_path_limited_publications_settle_exactly_the_failed_paths(tmp_path):
    config, workspace, store = _owner(tmp_path, text="The first drink is cedar tea.\n")
    first, second = "memory/2026-11-09.md", "memory/2026-11-10.md"
    (workspace.root / second).write_text("The second drink is alder tea.\n", encoding="utf-8")
    _search(config, store, "drink")
    (workspace.root / first).write_text("The first drink is birch coffee.\n", encoding="utf-8")
    (workspace.root / second).write_text("The second drink is maple coffee.\n", encoding="utf-8")
    journal = _block_index_publication(tmp_path)
    for path in (first, second):
        with pytest.raises(sqlite3.OperationalError):
            store.reindex_sources(workspace, sources=["memory"], paths=[path])
    assert store.lifecycle_snapshot()["memoryScopeSyncFailure"] == {
        "error": "unable to open database file", "paths": [first, second]}
    # An empty selection has nothing to publish and changes nothing.
    assert store.reindex_sources(workspace, sources=["memory"], paths=[]) == 0
    journal.unlink()

    assert store.reindex_sources(workspace, sources=["memory"], paths=[first]) == 1
    assert store.lifecycle_snapshot()["memoryScopeSyncFailure"]["paths"] == [second]
    partly = _search(config, store, "drink")
    assert partly["stale"] is True and partly["warning"] == STALE_WARNING
    assert {row["snippet"] for row in partly["results"]} == {
        "The first drink is birch coffee.\n", "The second drink is alder tea.\n"}

    assert store.reindex_sources(workspace, sources=["memory"], paths=[second]) == 1
    assert "lastSyncError" not in store.status()
    current = _search(config, store, "drink")
    assert "stale" not in current
    assert {row["snippet"] for row in current["results"]} == {
        "The first drink is birch coffee.\n", "The second drink is maple coffee.\n"}


def test_whole_scope_failure_is_not_settled_by_a_path_limited_publication(tmp_path):
    config, workspace, store = _owner(tmp_path, text="The first drink is cedar tea.\n")
    first, second = "memory/2026-11-09.md", "memory/2026-11-10.md"
    (workspace.root / second).write_text("The second drink is alder tea.\n", encoding="utf-8")
    _search(config, store, "drink")
    (workspace.root / first).write_text("The first drink is birch coffee.\n", encoding="utf-8")
    (workspace.root / second).write_text("The second drink is maple coffee.\n", encoding="utf-8")
    journal = _block_index_publication(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        store.reindex_sources(workspace, sources=["memory"])
    journal.unlink()

    assert store.reindex_sources(workspace, sources=["memory"], paths=[first]) == 1
    assert store.lifecycle_snapshot()["memoryScopeSyncFailure"] == {
        "error": "unable to open database file", "paths": None}
    assert _search(config, store, "drink")["stale"] is True
    assert store.reindex_sources(workspace, sources=["memory"]) == 2
    assert "lastSyncError" not in store.status()
    current = _search(config, store, "drink")
    assert "stale" not in current
    assert {row["snippet"] for row in current["results"]} == {
        "The first drink is birch coffee.\n", "The second drink is maple coffee.\n"}


@pytest.mark.parametrize(("options", "error"), [
    ({"sources": "memory"}, ValueError),
    ({"sources": b"memory"}, ValueError),
    ({"sources": {"memory", "unknown"}}, ValueError),
    ({"sources": []}, ValueError),
    ({"sources": ["memory"], "paths": "MEMORY.md"}, ValueError),
    ({"sources": ["memory"], "paths": ["../outside.md"]}, ValueError),
    ({"sources": ["memory"], "force_sources": 1}, TypeError),
])
def test_refused_selection_arguments_attempt_no_publication_and_report_nothing(tmp_path, options, error):
    config, workspace, store = _owner(tmp_path, text="Cedar source remains on disk.\n")
    _search(config, store)
    _block_index_publication(tmp_path)
    with pytest.raises(error):
        store.reindex_sources(workspace, **options)
    assert "lastSyncError" not in store.status()
    assert "memoryScopeSyncFailure" not in store.lifecycle_snapshot()
    assert "stale" not in _search(config, store)


def test_cold_index_refusal_of_a_selected_publication_is_not_a_publication_failure(tmp_path):
    config, workspace, store = _owner(tmp_path, text="Cedar source remains on disk.\n")
    with pytest.raises(MemoryIndexRequiresFullReindexError):
        store.reindex_sources(workspace, sources=["memory"])
    assert "lastSyncError" not in store.status()
    assert "memoryScopeSyncFailure" not in store.lifecycle_snapshot()
    # The ordinary cold bootstrap still runs and reports only its own notice.
    first = _search(config, store)
    assert first["results"][0]["snippet"] == "Cedar source remains on disk.\n"
    assert "stale" not in first


def test_committed_write_with_failed_refresh_is_reported_stale_by_the_next_search(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite", citation_mode="off",
        session_search=False, flags=FeatureFlags(vector_search=False, temporal_decay=False))
    owner = ManagedHostSession.open(root, catalog=MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW),
        config=config, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, now_ms=lambda: NOW,
        source_policy=resolve_memory_search_source_policy(["memory"], remember_across_conversations=False))
    state = SessionState.new(session_key="agent:main:dm:stale-report", session_id="stale-report")
    search = {"query": "drink preference", "corpus": "memory", "minScore": 0}
    old, new = "My drink preference is cedar tea.", "My drink preference is birch coffee."

    def call(turn, name, arguments):
        turn.record_message({"role": "assistant", "content": [
            {"type": "toolCall", "id": name, "name": name, "arguments": dict(arguments)}]})
        return turn.dispatch(name, name, arguments)

    def answer(turn):
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Done."}]})
        return HostModelResult()

    async def save(turn):
        assert call(turn, "add_memory_entry", {"section": "Preferences", "text": old})["status"] == "ok"
        return answer(turn)

    async def update(turn):
        changed = call(turn, "replace_memory_entry", {"old": old, "new": new})
        # The write stands; only its index refresh failed.
        assert changed["status"] == "ok" and changed["afterWriteError"] == "unable to open database file"
        found = call(turn, "memory_search", search)
        assert found["stale"] is True and found["warning"] == STALE_WARNING
        assert found["action"] == STALE_ACTION
        assert found["results"][0]["snippet"] == f"- {old}\n"
        return answer(turn)

    async def read(turn):
        found = call(turn, "memory_search", search)
        assert "stale" not in found and "warning" not in found and "action" not in found
        assert found["results"][0]["snippet"] == f"- {new}\n"
        return answer(turn)

    async def scenario():
        try:
            await owner.runner(state).run_turn("Remember my drink.", execute=save)
            owner.reindex(force=True)
            journal = _block_index_publication(tmp_path)
            failed = await owner.runner(state).run_turn("Change my drink.", execute=update)
            assert failed.memory_writes_committed and failed.index_status == "failed"
            assert new in (root / "MEMORY.md").read_text(encoding="utf-8")
            assert owner.store.lifecycle_snapshot()["memoryScopeSyncFailure"] == {
                "error": "unable to open database file", "paths": None}
            journal.unlink()
            # The next admission republishes the memory scope; the report ends with it.
            recovered = await owner.runner(state).run_turn("What do I drink?", execute=read)
            assert recovered.ready and not recovered.failures
            assert "lastSyncError" not in owner.store.status()
        finally:
            await owner.aclose()

    asyncio.run(scenario())
