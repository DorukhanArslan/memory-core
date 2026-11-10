"""Actual reopened-manager diagnostics and strict first-query identity gates."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
import os
import sqlite3

import pytest

from memory_core.cancellation import CancellationSignal, OperationAbortedError
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import MEMORY_INDEX_META_KEY
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError, SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.tools.common import MemoryToolError, MemoryToolInputError
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_268_800_000


def _open(config, workspace):
    return ManagedSQLiteMemoryStore(config, workspace, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)


@pytest.fixture
def owner(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").write_text("## Preferences\n\nMy drink preference is cedar tea.\n", encoding="utf8")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", citation_mode="off",
        session_search=False, flags=FeatureFlags(vector_search=False, temporal_decay=False))
    workspace = MemoryWorkspace(root, index_sources=["memory", "sessions"])
    producer = _open(config, workspace)
    assert producer.reindex(workspace) == 1
    producer.close()
    store = _open(config, workspace)
    try:
        yield config, workspace, store
    finally:
        store.close()


def _change_meta(store, **values):
    metadata = store.read_index_meta()
    metadata.update(values)
    with closing(store.connect()) as db, db:
        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?",
                   (json.dumps(metadata), MEMORY_INDEX_META_KEY))


def _diagnostic(store):
    return deepcopy(store.status()["custom"]["indexIdentity"])


def _snapshot(store):
    with closing(store.connect()) as db:
        db.execute("BEGIN")
        return {"metadata": store.read_index_meta(db=db), "published": store.read_published_index(db=db)}


def _tool(config, store):
    return create_memory_search_tool(config, store, context=MemorySearchToolContext(clock=lambda: NOW),
                                     runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)


def test_reopened_diagnostics_stay_unknown_until_the_actual_public_query(owner):
    config, workspace, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    before = _snapshot(store)
    strict = store.index_identity()
    assert strict["code"] == "provider_settings"
    assert _diagnostic(store) == _diagnostic(store) == {"status": "valid"}
    assert _snapshot(store) == before

    envelope = _tool(config, store).execute("first-query", {"query": "cedar", "corpus": "memory", "minScore": 0})
    result = envelope["details"]
    assert json.loads(envelope["content"][0]["text"]) == result
    assert result["results"] == [] and result["unavailable"] is True
    assert result["error"] == strict["reason"] and "paused" in result["warning"]
    assert _diagnostic(store) == strict
    assert _snapshot(store) == before
    assert store.lifecycle_snapshot()["repairs"] == []

    # A new owner has its own uninitialized diagnostic phase; source metadata
    # has not been silently repaired or globally whitelisted.
    store.close()
    reopened = _open(config, workspace)
    try:
        assert _diagnostic(reopened) == {"status": "valid"}
        assert reopened.index_identity() == strict
        assert _snapshot(reopened) == before
    finally:
        reopened.close()


def test_direct_query_establishes_knowledge_without_relaxing_the_raw_gate(owner):
    _, _, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    assert _diagnostic(store) == {"status": "valid"}
    before = _snapshot(store)

    assert store.search("cedar") == []

    assert _diagnostic(store)["code"] == "provider_settings"
    assert _snapshot(store) == before


@pytest.mark.parametrize("kind", ["whitespace", "aborted", "missing-query", "empty-query", "foreign-corpus"])
def test_unadmitted_requests_leave_reopened_identity_knowledge_unchanged(owner, kind):
    config, _, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    before = _snapshot(store)
    if kind == "whitespace":
        assert store.search(" \n\t") == []
    elif kind == "aborted":
        signal = CancellationSignal()
        signal.abort("actual request already cancelled")
        with pytest.raises(OperationAbortedError, match="already cancelled"):
            store.search("cedar", signal=signal)
    elif kind == "foreign-corpus":
        with pytest.raises(MemoryToolError, match="corpus must be one of"):
            _tool(config, store).execute("refused-corpus", {"query": "cedar", "corpus": "foreign"})
    else:
        args = {} if kind == "missing-query" else {"query": ""}
        with pytest.raises(MemoryToolInputError, match="query required"):
            _tool(config, store).execute("refused-query", args)
    assert _diagnostic(store) == {"status": "valid"}
    assert store.index_identity()["code"] == "provider_settings"
    assert _snapshot(store) == before
    assert store.lifecycle_snapshot()["repairs"] == []


def test_ordinary_sqlite_store_keeps_its_strict_default(owner):
    config, _, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    ordinary = SQLiteMemoryStore(config, None)
    assert ordinary.index_identity()["code"] == "provider_settings"
    assert ordinary.search("cedar") == []
    assert _diagnostic(store) == {"status": "valid"}


@pytest.mark.parametrize("failure", [False, True], ids=["published", "physical-journal-refusal"])
def test_explicit_whole_publication_establishes_provider_knowledge(owner, tmp_path, failure):
    _, workspace, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    assert _diagnostic(store) == {"status": "valid"}
    before = _snapshot(store)
    journal = store.path.with_name(store.path.name + "-journal")
    if failure:
        journal.symlink_to(tmp_path / "missing-parent" / "journal")
        with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
            store.reindex(workspace, force=True)
        assert _diagnostic(store)["code"] == "provider_settings"
        assert _snapshot(store) == before
        journal.unlink()
    else:
        assert store.reindex(workspace) == 1
        _change_meta(store, providerKey="another-declared-provider-key")
        assert _diagnostic(store)["code"] == "provider_settings"


def test_admitted_selected_publication_establishes_provider_knowledge(owner):
    _, workspace, store = owner
    assert store.reindex_sources(workspace, sources=["memory"]) == 1
    _change_meta(store, providerKey="declared-other-provider-key")
    assert _diagnostic(store)["code"] == "provider_settings"


@pytest.mark.parametrize("refusal", ["owner", "sources", "paths", "full-reindex-required"])
def test_refused_publications_do_not_establish_provider_knowledge(owner, tmp_path, refusal):
    _, workspace, store = owner
    _change_meta(store, providerKey="declared-other-provider-key")
    before = _snapshot(store)
    if refusal == "owner":
        other = MemoryWorkspace(tmp_path / "foreign-workspace")
        with pytest.raises(ValueError, match="bound workspace"):
            store.reindex(other)
    elif refusal == "sources":
        with pytest.raises(ValueError, match="memory/sessions"):
            store.reindex_sources(workspace, sources=["foreign"])
    elif refusal == "paths":
        with pytest.raises(ValueError, match="canonical relative"):
            store.reindex_sources(workspace, sources=["memory"], paths=["../MEMORY.md"])
    else:
        with pytest.raises(MemoryIndexRequiresFullReindexError):
            store.reindex_sources(workspace, sources=["memory"])
    assert _diagnostic(store) == {"status": "valid"}
    assert store.index_identity()["code"] == "provider_settings"
    assert _snapshot(store) == before


@pytest.mark.parametrize("change,code", [({"model": "other-model"}, "model"),
                                        ({"scopeHash": "other-scope"}, "scope"),
                                        ({"provenanceVersion": 2}, "provenance_version")])
def test_lazy_provider_key_diagnostic_keeps_other_mismatches_visible(owner, change, code):
    _, _, store = owner
    _change_meta(store, providerKey="declared-other-provider-key", **change)
    assert _diagnostic(store)["code"] == code


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                    reason="Requires actual POSIX source-read denial for this user")
@pytest.mark.parametrize("scope", ["whole", "selected"])
def test_failed_actual_source_preparation_keeps_admitted_provider_knowledge(owner, scope):
    _, workspace, store = owner
    source = workspace.root / "MEMORY.md"
    mode = source.stat().st_mode & 0o777
    before = _snapshot(store)
    source.chmod(0)
    try:
        with pytest.raises(PermissionError):
            if scope == "whole":
                store.reindex(workspace)
            else:
                store.reindex_sources(workspace, sources=["memory"])
    finally:
        source.chmod(mode)
    assert _snapshot(store) == before
    _change_meta(store, providerKey="declared-other-provider-key")
    assert _diagnostic(store)["code"] == "provider_settings"
