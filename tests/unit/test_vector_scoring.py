"""CPU vector candidates and their existing public-search ownership boundaries."""
from __future__ import annotations

import json
import math
import struct

import pytest

from memory_core.cancellation import CancellationSignal, OperationAbortedError
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.publication import (
    CHUNK_DETAILS_TABLE, PreparedChunk, PreparedIndexRevision, PreparedSource,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.index.vector import cosine_similarity, decode_memory_embedding


@pytest.mark.parametrize("a,b,expected", [
    ([1, 0], [1], 1), ([1], [1, 100], 1), ([1, 100], [1], 1),
    ([-1], [1, 0], -1), ([], [1], 0), ([0, 0], [1], 0),
    ([None, 1], [1, 1], 1 / math.sqrt(2)),
])
def test_cosine_uses_only_the_shared_prefix_and_native_zero_fallback(a, b, expected):
    assert cosine_similarity(a, b) == expected


@pytest.mark.parametrize("raw,expected", [
    ('[1, 0, -0.5]', [1, 0, -0.5]), ('[]', []),
    ('invalid', []), ('{"vector":[1]}', []), ('[null]', []), ('[true]', []),
    ('[NaN]', []), ('[Infinity]', []), ('[1e400]', []),
    (struct.pack("<dd", 1, -0.5), [1, -0.5]),
    (b"\x01\x02\x03", []), (struct.pack("<d", math.nan), []),
    (struct.pack("<d", math.inf), []),
])
def test_derived_embedding_decoding_keeps_corrupt_rows_inert(raw, expected):
    assert decode_memory_embedding(raw) == expected


def make_store(tmp_path, *, provider=None):
    root = tmp_path / "workspace"
    root.mkdir()
    store = SQLiteMemoryStore(MemoryConfig(
        workspace_dir=root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=provider is not None, text_search=provider is None,
                           temporal_decay=False, mmr=False),
    ), provider)
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    return store


def seed(db, rowid, identifier, embedding, *, model="target", source="memory", text=None):
    db.execute("INSERT INTO chunks(rowid,id,path,start_line,end_line,source,text,embedding) "
               "VALUES (?,?,?,3,5,?,?,?)", (
                   rowid, identifier, f"{source}/{identifier}.md", source,
                   text or identifier, embedding if isinstance(embedding, bytes) else json.dumps(embedding),
               ))
    db.execute(f"INSERT INTO {CHUNK_DETAILS_TABLE} VALUES (?, 'hash', ?, 1)", (identifier, model))


def test_model_alias_and_source_filters_precede_top_k_and_preserve_rowid_ties(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        seed(db, 1, "foreign", [1, 0], model="other")
        seed(db, 2, "session", [1, 0], source="sessions")
        seed(db, 30, "z-last-inserted", [1, 0])
        seed(db, -9, "first", [1, 0], model="legacy")
        seed(db, 0, "second", [1, 0])
    rows = store.search_vector_candidates(
        [1, 0], limit=2, provider_model="target", provider_model_aliases=["legacy", "", "target"],
        sources={"memory"},
    )
    assert [row.id for row in rows] == ["first", "second"]
    assert [(row.start_line, row.end_line, row.source, row.vector_score) for row in rows] == [
        (3, 5, "memory", 1), (3, 5, "memory", 1),
    ]


def test_raw_zero_vectors_and_corrupt_blobs_score_zero_but_nonfinite_scores_are_excluded(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        seed(db, 1, "corrupt-length", b"bad")
        seed(db, 2, "corrupt-infinity", struct.pack("<d", math.inf))
        seed(db, 3, "prefix", [1, 999])
        seed(db, 4, "zero", [0, 0])
        seed(db, 5, "overflow", [1e308])
    rows = store.search_vector_candidates([1], limit=10, provider_model="target")
    assert [(row.id, row.vector_score) for row in rows] == [
        ("prefix", 1), ("corrupt-length", 0), ("corrupt-infinity", 0), ("zero", 0), ("overflow", 0),
    ]
    assert all(row.vector_score == 0 for row in store.search_vector_candidates(
        [0], limit=10, provider_model="target",
    ))
    assert all(row.id != "overflow" for row in store.search_vector_candidates(
        [1e308], limit=10, provider_model="target",
    ))


def test_snippet_byte_prefix_preserves_nul_utf16_and_partial_trailing_utf8(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        seed(db, 1, "snippet", [1], text="A\x00😀漢字😀tail")
    row, = store.search_vector_candidates([1], limit=1, provider_model="target", snippet_max_chars=5)
    assert row.snippet == "A\x00😀漢"
    row, = store.search_vector_candidates([1], limit=1, provider_model="target", snippet_max_chars=3)
    assert row.snippet == "A\x00"


def observed_connection(store, observed):
    db = store.connect()
    db.execute("ALTER TABLE chunks RENAME TO observed_chunks")
    db.create_function("observe_embedding", 2, lambda rowid, embedding: observed.append(rowid) or embedding)
    db.execute("CREATE VIEW chunks AS SELECT rowid AS rowid,id,path,start_line,end_line,source,text,"
               "observe_embedding(rowid,embedding) AS embedding FROM observed_chunks")
    db.commit()
    return db


def test_signed_rowid_batches_find_the_late_winner_without_repeating_or_skipping(tmp_path):
    store = make_store(tmp_path)
    rowids = [-2**63, -1, 0, *[2**53 + 1 + i * 2 for i in range(254)], 2**63 - 1]
    with store.connect() as db:
        for i, rowid in enumerate(rowids):
            seed(db, rowid, f"row-{i}", [1, 0] if i == 256 else [0, 1])
    observed = []
    with observed_connection(store, observed) as db:
        rows = store.search_vector_candidates([1, 0], limit=1, provider_model="target", db=db)
    assert observed == rowids
    assert rows[0].id == "row-256"


def test_abort_at_a_full_batch_stops_before_the_next_batch(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i in range(300):
            seed(db, i, f"row-{i}", [1, 0])
    observed = []

    class StopAtBatch(CancellationSignal):
        def throw_if_aborted(self):
            if len(observed) >= 256:
                self.abort("stopped after one batch")
            super().throw_if_aborted()

    with observed_connection(store, observed) as db:
        with pytest.raises(OperationAbortedError, match="stopped after one batch"):
            store.search_vector_candidates([1, 0], limit=1, provider_model="target", signal=StopAtBatch(), db=db)
    assert observed == list(range(256))


def test_a_contender_keeps_its_scored_payload_when_replaced_between_batches(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i in range(257):
            seed(db, i, f"row-{i}", [1, 0] if i == 0 else [0, 1])
    observed = []
    db = observed_connection(store, observed)

    class ReplaceAfterBatch(CancellationSignal):
        changed = False

        def throw_if_aborted(self):
            if len(observed) >= 256 and not self.changed:
                self.changed = True
                db.execute("UPDATE observed_chunks SET path='replacement.md',text='replacement',embedding='[0,1]' WHERE rowid=0")
                db.commit()
            super().throw_if_aborted()

    try:
        result, = store.search_vector_candidates([1, 0], limit=1, provider_model="target", db=db,
                                                signal=ReplaceAfterBatch())
        assert (result.path, result.snippet, result.vector_score) == ("memory/row-0.md", "row-0", 1)
        assert db.execute("SELECT text FROM observed_chunks WHERE rowid=0").fetchone()[0] == "replacement"
    finally:
        db.close()


def test_external_writes_cannot_join_a_batch_score_to_a_replaced_payload(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        seed(db, 0, "row-0", [1, 0])
    observed = []
    db = observed_connection(store, observed)
    writer = store.connect()
    changed = False

    def replace_from_other_connection(rowid, embedding):
        nonlocal changed
        observed.append(rowid)
        if rowid == 0 and not changed:
            changed = True
            writer.execute("UPDATE observed_chunks SET path='replacement.md',text='replacement',"
                           "embedding='[0,1]' WHERE rowid=0")
            writer.commit()
        return embedding

    db.create_function("observe_embedding", 2, replace_from_other_connection)
    try:
        result, = store.search_vector_candidates([1, 0], limit=1, provider_model="target", db=db)
        assert changed
        assert (result.path, result.snippet, result.vector_score) == ("memory/row-0.md", "row-0", 1)
        assert db.execute("SELECT text FROM observed_chunks WHERE rowid=0").fetchone()[0] == "replacement"
    finally:
        writer.close()
        db.close()


def test_empty_query_and_nonpositive_limit_return_before_an_aborted_signal(tmp_path):
    store = make_store(tmp_path)
    signal = CancellationSignal()
    signal.abort("already stopped")
    assert store.search_vector_candidates([], limit=1, signal=signal) == []
    assert store.search_vector_candidates([1], limit=0, signal=signal) == []


class FixtureProvider:
    provider_id = "fixture"
    model = "target"
    dimensions = 2
    query = [1.0]

    def embed_query(self, _text):
        return self.query

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_public_search_uses_filtered_candidates_but_retains_its_own_zero_and_tie_policies(tmp_path):
    provider = FixtureProvider()
    store = make_store(tmp_path, provider=provider)
    chunks = [
        PreparedChunk(identifier, path, "memory", 1, 2, identifier, vector, "hash", model, 1)
        for identifier, path, vector, model in [
            ("foreign", "memory/0.md", [1], "other"),
            ("z", "memory/z.md", [1, 999], "target"),
            ("a", "memory/a.md", [1, 100], "target"),
        ]
    ]
    meta = store._build_index_meta(2, provider=store._index_provider(), provider_key=store._provider_key())
    prepared = PreparedIndexRevision(tuple(
        PreparedSource(chunk.path, chunk.source, "hash", 1, 1, (chunk,)) for chunk in chunks
    ), json.dumps(meta), workspace=str(store.config.workspace_dir))
    store.publish_prepared_index(prepared, store.index_revision())
    assert [row.id for row in store.search_vector_candidates([1], limit=2)] == ["z", "a"]
    assert [row.path for row in store.search("query", max_results=2, min_score=.1)] == ["memory/a.md", "memory/z.md"]
    provider.query = [0, 0]
    assert store.search("query", max_results=2, min_score=0) == []
