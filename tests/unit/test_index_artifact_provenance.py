"""The host write ledger reaches real indexing without inventing trust transitions."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.embeddings import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver


def config_for(root: Path, *, vector: bool = False) -> MemoryConfig:
    return MemoryConfig(
        workspace_dir=root, store_path=root.parent / "index.sqlite",
        flags=FeatureFlags(vector_search=vector),
    )


def origins(memory: Memory) -> list[str]:
    return [row["provenance"]["originClass"]
            for row in memory.store.read_published_index()["chunks"]]


def test_observed_untrusted_file_stays_quarantined_after_changed_content_and_reopen(tmp_path: Path):
    root = tmp_path / "workspace"
    target = root / "memory/2026-09-25.md"
    target.parent.mkdir(parents=True)
    provenance = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    memory = Memory.from_workspace(
        root, config=config_for(root), initialize=False, reindex=False,
        artifact_provenance=provenance,
    )
    assert memory.store.artifact_provenance is provenance
    assert not provenance.path.exists()  # Binding the owner performs no provenance I/O.
    origin = {"value": "untrusted"}
    observer = MemoryWriteProvenanceObserver(
        store=provenance, mutation_root=root, workspace_dir=root,
        resolve_origin_class=lambda: origin["value"], now=lambda: 100,
    )

    def write(before: str, after: str) -> None:
        observer.write(
            absolute_path=target, content_before=before, content_after=after,
            commit=lambda: target.write_text(after, encoding="utf-8"),
        )

    first = "- router preference from an untrusted turn\n"
    write("", first)
    memory.store.reindex(memory.workspace)
    assert origins(memory) == ["untrusted"]
    initial_id = memory.store.read_published_index()["chunks"][0]["id"]

    origin["value"] = "agent"
    second = first + "- later trusted append must retain the file quarantine\n"
    write(first, second)
    memory.store.reindex(memory.workspace)
    assert origins(memory) == ["untrusted"]
    assert memory.store.read_published_index()["chunks"][0]["id"] != initial_id

    reopened = Memory.from_workspace(
        root, config=config_for(root), initialize=False,
        artifact_provenance=MemoryArtifactProvenanceStore(provenance.path),
    )
    assert origins(reopened) == ["untrusted"]
    revision = reopened.store.index_revision()
    write(second, second)
    reopened.store.reindex(reopened.workspace)
    assert origins(reopened) == ["untrusted"]
    assert reopened.store.index_revision() == revision

    # An unchanged source keeps its published trust if the host omits the ledger
    # on reopen; an incremental no-op must not silently promote quarantine.
    unbound = Memory.from_workspace(root, config=config_for(root), initialize=False)
    assert origins(unbound) == ["untrusted"]


def test_host_kit_shares_the_existing_ledger_without_reading_it(tmp_path: Path):
    root = tmp_path / "workspace"
    provenance = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    memory = Memory.from_workspace(
        root, config=config_for(root), initialize=False, reindex=False,
        artifact_provenance=provenance,
    )
    kit = HostKit(memory)
    assert kit._artifact_provenance is provenance
    assert memory.store.artifact_provenance is provenance
    assert not provenance.path.exists()


def test_host_kit_binds_its_write_ledger_to_an_unbound_index(tmp_path: Path):
    root = tmp_path / "workspace"
    memory = Memory.from_workspace(root, config=config_for(root), initialize=False, reindex=False)
    provenance = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    HostKit(memory, artifact_provenance=provenance)
    assert memory.store.artifact_provenance is provenance
    assert not provenance.path.exists()


def test_host_kit_rejects_two_different_trust_ledgers_before_rebinding(tmp_path: Path):
    root = tmp_path / "workspace"
    existing = MemoryArtifactProvenanceStore(tmp_path / "existing.sqlite")
    other = MemoryArtifactProvenanceStore(tmp_path / "other.sqlite")
    memory = Memory.from_workspace(
        root, config=config_for(root), initialize=False, reindex=False,
        artifact_provenance=existing,
    )
    with pytest.raises(ValueError, match="same artifact provenance store"):
        HostKit(memory, artifact_provenance=other)
    assert memory.store.artifact_provenance is existing
    assert not existing.path.exists() and not other.path.exists()


def test_changed_provider_before_reader_opens_rejects_the_old_query_vector(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspace"
    target = root / "memory/router.md"
    target.parent.mkdir(parents=True)
    target.write_text("router preference", encoding="utf-8")
    provider = FakeEmbeddingProvider(dimensions=2)
    memory = Memory.from_workspace(
        root, config=config_for(root, vector=True), embedding_provider=provider,
        initialize=False,
    )
    original_connection = memory.store._search_connection
    changed = []

    @contextmanager
    def change_provider_before_reader(signal):
        if not changed:
            changed.append(True)
            provider.model = "different-vector-space"
            memory.store.reindex(memory.workspace)
        with original_connection(signal) as db:
            yield db

    monkeypatch.setattr(memory.store, "_search_connection", change_provider_before_reader)
    assert memory.store.search("router") == []
    assert memory.store.index_identity()["status"] == "valid"
    assert [row.path for row in memory.store.search("router")] == ["memory/router.md"]
