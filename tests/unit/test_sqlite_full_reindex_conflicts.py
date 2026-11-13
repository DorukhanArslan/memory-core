"""Real row mutations fence opted-in full rebuilds without changing base policy."""
from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import IndexPlan, plan_memory_index, purge_memory_index
from memory_core.consolidation.origins import MemoryEntryOriginLedger, MemoryIndexRevisionConflictError
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.identity import INDEX_SOURCES_TABLE
from memory_core.index.sqlite_store import MemoryIndexSourceChangedError, SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


class RowMutationStore(SQLiteMemoryStore):
    def _uses_row_mutation_revision(self):
        return True


def owner(tmp_path, store_type=RowMutationStore):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (root / "memory" / f"{name}.md").write_text(f"A real {name} source.\n", encoding="utf8")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", flags=FeatureFlags(vector_search=False))
    return store_type(config, None), MemoryWorkspace(root)


def mutation_revision(store):
    with store.connect() as db:
        return store._row_mutation_revision(db=db)


def purge(store, path="memory/b.md"):
    plan = plan_memory_index(
        store, agent_id="main", changed_paths={path}, removed_paths={path},
        session_ids=set(), excluded_session_ids=set(), matches_memory=lambda _text: False,
    )
    assert plan.chunks and purge_memory_index(store, plan)


def test_row_clock_counts_real_canonical_mutations_and_rolls_back(tmp_path):
    store, workspace = owner(tmp_path)
    assert store.reindex(workspace) == 3
    with store.connect() as db:
        canonical_rows = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        canonical_rows += db.execute(f"SELECT COUNT(*) FROM {INDEX_SOURCES_TABLE}").fetchone()[0]
    assert mutation_revision(store) == canonical_rows == 6
    private_generation = store.index_revision()
    initial = mutation_revision(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        chunks = db.execute("UPDATE chunks SET text=text WHERE path='memory/a.md'").rowcount
        sources = db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET hash=hash WHERE path='memory/a.md'").rowcount
        assert store._row_mutation_revision(db=db) == initial + chunks + sources
        db.rollback()
    assert mutation_revision(store) == initial
    with store.connect() as db:
        changed = db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET hash=hash").rowcount
    assert mutation_revision(store) == initial + changed
    assert store.index_revision() == private_generation
    assert mutation_revision(RowMutationStore(store.config, None)) == initial + changed


@pytest.mark.parametrize("store_type,exception", [
    (RowMutationStore, MemoryIndexRevisionConflictError),
    (SQLiteMemoryStore, MemoryIndexSourceChangedError),
])
def test_full_rebuild_preserves_real_competing_purge_and_exact_revision_diagnostic(
    tmp_path, monkeypatch, store_type, exception,
):
    store, workspace = owner(tmp_path, store_type)
    store.reindex(workspace)
    original = store.publish_prepared_index
    observed = {}

    def publish_after_competing_purge(prepared, expected_revision, **options):
        if store_type is RowMutationStore:
            observed["expected"] = mutation_revision(store)
        purge(store)
        observed["published"] = store.read_published_index()
        if store_type is RowMutationStore:
            observed["current"] = mutation_revision(store)
        return original(prepared, expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_competing_purge)
    with pytest.raises(exception) as caught:
        store.reindex(workspace, force=True)
    assert store.read_published_index() == observed["published"]
    assert (workspace.root / "memory/b.md").is_file()
    if store_type is RowMutationStore:
        assert observed["expected"] == 6 and observed["current"] == 8
        assert str(caught.value) == (
            "Memory index changed while full reindex was building "
            f"(expected revision {observed['expected']}, found {observed['current']}); "
            "retry the full reindex."
        )
    else:
        assert "refresh was being prepared" in str(caught.value)


def test_incremental_purge_conflict_keeps_source_changed_policy(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    (workspace.root / "memory/a.md").write_text("A genuine changed source.\n", encoding="utf8")
    original = store.publish_prepared_index
    competing = []

    def publish_after_purge(prepared, expected_revision, **options):
        assert prepared.replace_all is False
        purge(store)
        competing.append(store.read_published_index())
        return original(prepared, expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_purge)
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory index changed"):
        store.reindex(workspace)
    assert store.read_published_index() == competing[0]


def test_external_source_metadata_write_fences_full_rebuild_without_private_generation_bump(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    private_generation, clock = store.index_revision(), mutation_revision(store)
    original = store.publish_prepared_index

    def publish_after_metadata_write(prepared, expected_revision, **options):
        with store.connect() as db:
            changed = db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET mtime=mtime+1 WHERE path='memory/b.md'").rowcount
        assert changed == 1 and store.index_revision() == private_generation
        return original(prepared, expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_metadata_write)
    with pytest.raises(MemoryIndexRevisionConflictError, match=f"expected revision {clock}, found {clock + 1}"):
        store.reindex(workspace, force=True)
    assert mutation_revision(store) == clock + 1
    assert store.index_revision() == private_generation


def test_cache_only_invalidation_keeps_private_generation_conflict_policy(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    clock = mutation_revision(store)
    original = store.publish_prepared_index

    def publish_after_cache_purge(prepared, expected_revision, **options):
        assert purge_memory_index(store, IndexPlan(purge_cache=True))
        return original(prepared, expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_cache_purge)
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory index changed"):
        store.reindex(workspace, force=True)
    assert mutation_revision(store) == clock


def test_full_rebuild_rejects_real_source_edit_without_mislabeling_conflict(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    before, clock = store.read_published_index(), mutation_revision(store)
    original = store._prepare_source_chunks
    edited = False

    def prepare_then_edit(entry, *args):
        nonlocal edited
        prepared = original(entry, *args)
        if not edited:
            edited = True
            (workspace.root / "memory/a.md").write_text("Newer physical bytes.\n", encoding="utf8")
        return prepared

    monkeypatch.setattr(store, "_prepare_source_chunks", prepare_then_edit)
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory source changed"):
        store.reindex(workspace, force=True)
    assert store.read_published_index() == before
    assert mutation_revision(store) == clock


def test_full_rebuild_rejects_real_owner_change_without_mislabeling_conflict(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    before, clock = store.read_published_index(), mutation_revision(store)
    original = store.publish_prepared_index

    def publish_after_owner_change(prepared, expected_revision, **options):
        store.flags = replace(store.flags, vector_search=True)
        store.embeddings = FakeEmbeddingProvider(dimensions=2)
        return original(prepared, expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_owner_change)
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory index owner changed"):
        store.reindex(workspace, force=True)
    assert store.read_published_index() == before
    assert mutation_revision(store) == clock


def test_legacy_enrollment_does_not_invent_prior_mutation_history(tmp_path):
    legacy, workspace = owner(tmp_path, SQLiteMemoryStore)
    legacy.reindex(workspace)
    before = legacy.read_published_index()
    with legacy.connect() as db:
        assert db.execute("SELECT name FROM sqlite_schema WHERE name='memory_core_index_mutation_state'").fetchall() == []
    enrolled = RowMutationStore(legacy.config, None)
    assert enrolled.read_published_index() == before
    assert mutation_revision(enrolled) == 0
    with legacy.connect() as db:
        actual_changes = db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET size=size").rowcount
    assert mutation_revision(enrolled) == actual_changes
    assert mutation_revision(RowMutationStore(legacy.config, None)) == actual_changes
    assert legacy.index_revision() == before["revision"]


def test_failed_sqlite_publication_rolls_back_mutation_counter(tmp_path, monkeypatch):
    store, workspace = owner(tmp_path)
    store.reindex(workspace)
    before, clock = store.read_published_index(), mutation_revision(store)
    original = store.publish_prepared_index

    def publish_invalid_provenance(prepared, expected_revision, **options):
        first = prepared.sources[0]
        chunk = first.chunks[0]
        invalid = replace(chunk, provenance=replace(chunk.provenance, origin_class="invalid-origin"))
        first = replace(first, chunks=(invalid, *first.chunks[1:]))
        return original(replace(prepared, sources=(first, *prepared.sources[1:])), expected_revision, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_invalid_provenance)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        store.reindex(workspace, force=True)
    assert store.read_published_index() == before
    assert mutation_revision(store) == clock


@pytest.mark.parametrize("same_database", [True, False])
def test_explicit_origins_fence_keeps_its_existing_revision_semantics(tmp_path, monkeypatch, same_database):
    store, workspace = owner(tmp_path)
    ledger = MemoryEntryOriginLedger(lambda _agent: store.path if same_database else tmp_path / "origins.sqlite")
    store.revision_fence = ledger.revision_fence("main")
    store.reindex(workspace)
    before, clock, fence_before = store.read_published_index(), mutation_revision(store), store.revision_fence.read()
    assert fence_before == 1 and clock == 6
    original = store._prepare_source_chunks
    changed = False

    def prepare_then_forget(entry, *args):
        nonlocal changed
        prepared = original(entry, *args)
        if not changed:
            changed = True
            ledger.record_session_tombstones("main", ["forgotten"])
        return prepared

    monkeypatch.setattr(store, "_prepare_source_chunks", prepare_then_forget)
    with pytest.raises(MemoryIndexRevisionConflictError, match=r"expected revision 1, found 2"):
        store.reindex(workspace, force=True)
    assert store.read_published_index() == before
    assert mutation_revision(store) == clock
    assert store.revision_fence.read() == fence_before + 1


def test_denied_full_reindex_enters_base_but_prepares_and_publishes_nothing(tmp_path):
    class DeniedStore(RowMutationStore):
        def _allow_full_reindex(self, workspace, *, force):
            self.admission = (workspace.root, force)
            return False

        def _on_index_preparation_admitted(self):
            pytest.fail("A denied full reindex cannot prepare sources")

    store, workspace = owner(tmp_path, DeniedStore)
    assert SQLiteMemoryStore.reindex(store, workspace, force=True) == 0
    assert store.admission == (workspace.root, True)
    assert store.index_revision() == mutation_revision(store) == 0
    assert store.read_published_index()["chunks"] == []
