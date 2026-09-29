import json
import sqlite3
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.identity import (
    MEMORY_CORE_INDEX_VERSIONS,
    MEMORY_INDEX_META_KEY,
    MemoryIndexVersions,
    hash_text,
    resolve_configured_scope_hash,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.supplements import StaticMemoryCorpusSupplement
from memory_core.tools.memory_search import (
    memory_search,
    memory_search_tool_config_key,
    memory_search_tool_cooldown_key,
    read_memory_search_tool_cooldown,
)
from memory_core.workspace import MemoryWorkspace

FTS_ONLY = FeatureFlags(vector_search=False)
MISSING = {
    "status": "missing",
    "reason": "index metadata is missing",
    "code": "metadata_missing",
    "owner": "openclaw",
}
PAUSED_WARNING = (
    "Tell the user: memory search is paused because the memory index metadata is missing (index "
    "metadata is missing); no configuration change is needed."
)


def _workspace(tmp_path: Path) -> MemoryWorkspace:
    (tmp_path / "MEMORY.md").write_text("- Glacier storage keeps backups cold.\n", encoding="utf-8")
    return MemoryWorkspace(tmp_path)


def _config(tmp_path: Path, **kwargs) -> MemoryConfig:
    return MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "index.sqlite", **kwargs)


def _stored_meta(store: SQLiteMemoryStore) -> str:
    with sqlite3.connect(store.path) as db:
        return db.execute(
            "SELECT value FROM memory_index_meta WHERE key = ?", (MEMORY_INDEX_META_KEY,)
        ).fetchone()[0]


def test_reindex_writes_upstream_shaped_meta_for_fts_only(tmp_path):
    store = SQLiteMemoryStore(_config(tmp_path, flags=FTS_ONLY), None)
    store.reindex(_workspace(tmp_path))

    raw = _stored_meta(store)
    assert json.loads(raw) == {
        "model": "fts-only",
        "provider": "none",
        "providerKey": hash_text('{"provider":"none","model":"fts-only"}'),
        "sources": ["memory", "sessions"],
        "scopeHash": resolve_configured_scope_hash(),
        "chunkTokens": 400,
        "chunkOverlap": 80,
        "chunkingVersion": 0,
        "ftsTokenizer": "unicode61",
        "provenanceVersion": 0,
    }
    # nextMeta's key order (manager-sync-ops.ts:623-645); memory-core's own format versions.
    assert raw.startswith('{"model":"fts-only","provider":"none","providerKey":')
    assert '"chunkOverlap":80,"chunkingVersion":0,"ftsTokenizer":"unicode61"' in raw
    assert raw.endswith(',"provenanceVersion":0}')
    assert store.index_identity() == {"status": "valid"}


def test_reindex_records_vector_dims_for_embedded_indexes(tmp_path):
    store = SQLiteMemoryStore(_config(tmp_path), FakeEmbeddingProvider(dimensions=12))
    store.reindex(_workspace(tmp_path))

    meta = json.loads(_stored_meta(store))
    assert (meta["provider"], meta["model"], meta["vectorDims"]) == (
        "fake",
        "fake-deterministic",
        12,
    )
    assert meta["providerKey"] == hash_text('{"provider":"fake","model":"fake-deterministic"}')
    assert list(meta)[-3:] == ["ftsTokenizer", "provenanceVersion", "vectorDims"]


def test_never_indexed_store_pauses_until_reindex(tmp_path):
    cfg = _config(tmp_path, flags=FTS_ONLY)
    workspace = _workspace(tmp_path)
    store = SQLiteMemoryStore(cfg, None)

    assert store.index_identity() == MISSING
    assert store.search("glacier") == []
    paused = memory_search(cfg, store, query="glacier", corpus="memory")
    assert paused["error"] == "index metadata is missing"
    assert paused["warning"] == PAUSED_WARNING
    assert paused["unavailable"] is True

    store.reindex(workspace)
    assert [hit["path"] for hit in memory_search(cfg, store, query="glacier")["results"]] == [
        "MEMORY.md"
    ]


def test_legacy_store_without_meta_table_is_missing_until_reindex(tmp_path):
    # A store written before index metadata existed: chunks, no meta table.
    path = tmp_path / "index.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE chunks (id TEXT PRIMARY KEY, path TEXT NOT NULL, start_line INTEGER "
            "NOT NULL, end_line INTEGER NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL, "
            "embedding TEXT NOT NULL)"
        )
        db.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(id UNINDEXED, text)")
        db.execute(
            "INSERT INTO chunks VALUES ('c1', 'MEMORY.md', 1, 1, 'memory', 'Glacier note', '[]')"
        )
        db.execute("INSERT INTO chunks_fts VALUES ('c1', 'Glacier note')")
    cfg = _config(tmp_path, flags=FTS_ONLY)
    store = SQLiteMemoryStore(cfg, None)

    assert store.index_identity() == MISSING
    assert memory_search(cfg, store, query="glacier", corpus="memory")["error"] == (
        "index metadata is missing"
    )
    store.reindex(_workspace(tmp_path))
    assert memory_search(cfg, store, query="glacier")["results"]


def test_switching_between_fts_only_and_embeddings_pauses_search(tmp_path):
    workspace = _workspace(tmp_path)
    SQLiteMemoryStore(_config(tmp_path, flags=FTS_ONLY), None).reindex(workspace)

    vector = SQLiteMemoryStore(_config(tmp_path), FakeEmbeddingProvider())
    assert vector.index_identity()["reason"] == (
        "index was built for model fts-only, expected fake-deterministic"
    )

    vector.reindex(workspace)
    # vector_search=False makes the index FTS-only even with an embedder passed.
    fts = SQLiteMemoryStore(_config(tmp_path, flags=FTS_ONLY), FakeEmbeddingProvider())
    assert fts.index_identity()["reason"] == (
        "index was built for model fake-deterministic, expected fts-only"
    )


def test_embedding_endpoint_change_is_a_provider_settings_change(tmp_path):
    # An empty workspace indexes no chunks, so no embedding request is made.
    cfg = _config(tmp_path)
    first = OpenAICompatibleEmbeddingProvider(
        api_key="test-key", model="text-embedding-3-small", base_url="https://a.example/v1"
    )
    SQLiteMemoryStore(cfg, first).reindex(MemoryWorkspace(tmp_path))
    moved = OpenAICompatibleEmbeddingProvider(
        api_key="other-key", model="text-embedding-3-small", base_url="https://b.example/v1"
    )
    same = OpenAICompatibleEmbeddingProvider(
        api_key="other-key", model="text-embedding-3-small", base_url="https://a.example/v1/"
    )

    assert SQLiteMemoryStore(cfg, moved).index_identity() == {
        "status": "mismatched",
        "reason": "index provider settings changed",
        "code": "provider_settings",
        "owner": "configuration",
    }
    # The API key is not part of the identity.
    assert SQLiteMemoryStore(cfg, same).index_identity() == {"status": "valid"}
    assert "other-key" not in _stored_meta(SQLiteMemoryStore(cfg, first))


def test_corrupt_meta_reads_as_missing(tmp_path):
    cfg = _config(tmp_path, flags=FTS_ONLY)
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(_workspace(tmp_path))
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE memory_index_meta SET value = '{not json' WHERE key = ?",
                   (MEMORY_INDEX_META_KEY,))

    assert store.index_identity()["status"] == "missing"


def test_paused_search_records_no_cooldown_and_keeps_the_other_corpus(tmp_path):
    cfg = _config(tmp_path, flags=FTS_ONLY)
    store = SQLiteMemoryStore(cfg, None)
    wiki = StaticMemoryCorpusSupplement(
        [{"corpus": "wiki", "path": "w.md", "score": 1, "snippet": "glacier wiki"}]
    )

    paused_all = memory_search(cfg, store, query="glacier", corpus="all", supplements=[wiki])
    wiki_only = memory_search(cfg, store, query="glacier", corpus="wiki", supplements=[wiki])

    # tools.ts:387-405 and 509-550 at v2026.9.6: under corpus=all the paused memory corpus is
    # unavailable, the wiki hits stay, and the paused guidance joins the warning and action.
    assert "unavailable" not in paused_all
    assert [item["path"] for item in paused_all["results"]] == ["w.md"]
    assert paused_all["corpora"] == [
        {"corpus": "memory", "outcome": "unavailable", "error": "index metadata is missing"},
        {"corpus": "wiki", "outcome": "ok"},
    ]
    assert paused_all["error"] == "index metadata is missing"
    assert paused_all["warning"] == (
        "Memory corpus unavailable: index metadata is missing " + PAUSED_WARNING
    )
    assert paused_all["action"] == (
        "Tell the user to run: SQLiteMemoryStore.reindex(workspace). Rebuilding uses keyword "
        "indexing only and does not call an embedding provider."
    )
    assert [item["path"] for item in wiki_only["results"]] == ["w.md"]
    assert read_memory_search_tool_cooldown(
        memory_search_tool_cooldown_key(cfg, store), memory_search_tool_config_key(cfg, store)
    ) is None


def test_paused_action_names_the_runtime(tmp_path):
    cfg = _config(tmp_path, flags=FTS_ONLY)
    store = SQLiteMemoryStore(cfg, None)

    memory_core = memory_search(cfg, store, query="glacier", corpus="memory")
    compat = memory_search(
        cfg,
        store,
        query="glacier",
        corpus="memory",
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    # types.ts:300-311: FTS-only (provider none) rebuilds without an embedding provider.
    assert memory_core["action"] == (
        "Tell the user to run: SQLiteMemoryStore.reindex(workspace). Rebuilding uses keyword "
        "indexing only and does not call an embedding provider."
    )
    assert compat["action"] == (
        "Tell the user to run: openclaw memory status --index --agent main. Rebuilding uses "
        "keyword indexing only and does not call an embedding provider."
    )
    assert memory_core["debug"]["action"] == memory_core["action"]
    assert memory_core["warning"] == compat["warning"] == PAUSED_WARNING


def _set_meta(store: SQLiteMemoryStore, **fields) -> None:
    meta = {**json.loads(_stored_meta(store)), **fields}
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE memory_index_meta SET value = ? WHERE key = ?",
            (json.dumps(meta), MEMORY_INDEX_META_KEY),
        )


def test_an_index_from_before_the_format_versions_is_valid(tmp_path):
    # Decision D2: memory-core compares its own versions (0 and 0), so a stored meta without
    # provenanceVersion/chunkingVersion (every index written before v2026.9.6's port) is valid.
    store = SQLiteMemoryStore(_config(tmp_path, flags=FTS_ONLY), None)
    store.reindex(_workspace(tmp_path))
    meta = json.loads(_stored_meta(store))
    del meta["provenanceVersion"], meta["chunkingVersion"]
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE memory_index_meta SET value = ? WHERE key = ?",
            (json.dumps(meta), MEMORY_INDEX_META_KEY),
        )

    assert store.index_identity() == {"status": "valid"}


def test_a_newer_index_format_pauses_with_the_upgrade_guidance(tmp_path):
    cfg = _config(tmp_path, flags=FTS_ONLY)
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(_workspace(tmp_path))
    _set_meta(store, provenanceVersion="1")

    assert store.index_identity() == {
        "status": "mismatched",
        "reason": (
            "the index was written by a newer memory-core version; upgrade memory-core or "
            "reindex explicitly"
        ),
        "code": "provenance_version",
        "owner": "openclaw",
        "versionOrder": "newer",
    }
    paused = memory_search(cfg, store, query="glacier", corpus="memory")
    assert paused["warning"] == (
        "Tell the user: memory search is paused because the index was written by a newer "
        "memory-core version; upgrade memory-core or reindex explicitly."
    )
    assert paused["action"] == (
        "Tell the user to upgrade memory-core or reindex explicitly: "
        "SQLiteMemoryStore.reindex(workspace). Rebuilding uses keyword indexing only and does "
        "not call an embedding provider."
    )


class _ChunkerV1Store(SQLiteMemoryStore):
    # A memory-core whose chunker moved on: the stored chunkingVersion 0 is older.
    index_versions = MemoryIndexVersions(
        provenance=0, chunking=1, newer_reason=MEMORY_CORE_INDEX_VERSIONS.newer_reason
    )


def test_an_older_chunker_searches_keyword_only_and_reports_staleness(tmp_path):
    # memory-search-tool-query.ts:207-229: a pending chunking upgrade on an otherwise matching
    # index degrades to keyword-only results with the staleness fields instead of pausing.
    cfg = _config(tmp_path)
    workspace = _workspace(tmp_path)
    SQLiteMemoryStore(cfg, FakeEmbeddingProvider()).reindex(workspace)
    provider = FakeEmbeddingProvider()
    calls = []
    provider.embed_query = lambda text: calls.append(text) or [0.0] * provider.dimensions
    store = _ChunkerV1Store(cfg, provider)

    identity = store.index_identity()
    result = memory_search(cfg, store, query="glacier", corpus="memory")

    assert identity["code"] == "chunking_version" and identity["chunkingVersionOnly"] is True
    assert [hit["path"] for hit in result["results"]] == ["MEMORY.md"]
    assert calls == []  # keyword-only: no query embedding
    assert result["stale"] is True
    assert result["warning"] == (
        "Memory index is stale: index chunking implementation changed (owner: memory-core, code: "
        "chunking_version). Search results may be incomplete."
    )
    assert result["action"] == (
        "Run: SQLiteMemoryStore.reindex(workspace). Rebuilding may call the configured embedding "
        "provider and can incur provider cost."
    )
    # Without FTS there is no keyword path: the search pauses.
    no_fts = _ChunkerV1Store(
        _config(tmp_path, flags=FeatureFlags(text_search=False)), FakeEmbeddingProvider()
    )
    assert memory_search(no_fts.config, no_fts, query="glacier", corpus="memory")["error"] == (
        "index chunking implementation changed"
    )
