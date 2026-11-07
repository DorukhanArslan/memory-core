"""Persistent cache boundaries independently exercised with real SQLite."""

from copy import deepcopy
import math
import sqlite3
import struct

import pytest

from memory_core.index.embedding_cache import (
    clear_memory_embedding_cache_identities,
    collect_memory_cached_embeddings,
    decode_memory_embedding,
    encode_memory_embedding,
    ensure_embedding_cache_schema,
    is_valid_memory_embedding,
    load_memory_embedding_cache,
    upsert_memory_embedding_cache,
    validate_memory_embedding_batch,
)


PROVIDER = {"id": "provider", "model": "model"}
IDENTITY = {"provider": "provider", "model": "model", "providerKey": "endpoint-a"}
ALIAS = {**IDENTITY, "model": "alias"}


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    ensure_embedding_cache_schema(connection)
    yield connection
    connection.close()


def put(db, entries, **options):
    upsert_memory_embedding_cache(
        db, enabled=True, provider=PROVIDER, provider_key="endpoint-a",
        entries=entries, now=options.pop("now", 100), **options,
    )


def load(db, hashes, identities=None):
    return load_memory_embedding_cache(
        db, enabled=True, provider_identities=identities or [IDENTITY], hashes=hashes,
    )


def raw(db, identity, chunk_hash, payload, dims):
    db.execute(
        "INSERT INTO memory_embedding_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        (identity["provider"], identity["model"], identity["providerKey"],
         chunk_hash, payload, dims, 100),
    )


def test_vectors_have_portable_binary64_encoding_and_preserve_negative_zero():
    vector = [1, -0.0, 1.25, -2.5]
    encoded = encode_memory_embedding(vector)
    assert encoded == struct.pack("<dddd", 1, -0.0, 1.25, -2.5)
    decoded = decode_memory_embedding(encoded)
    assert decoded == vector
    assert math.copysign(1, decoded[1]) == -1
    assert encode_memory_embedding([]) == b""


@pytest.mark.parametrize("coordinate", [True, False, "1", None, math.nan, math.inf, -math.inf,
                                        10**1000])
def test_encoder_rejects_non_numeric_or_non_finite_coordinates(coordinate):
    with pytest.raises(ValueError, match="Memory embeddings require finite numeric coordinates"):
        encode_memory_embedding([1, coordinate])


@pytest.mark.parametrize("payload", [b"", b"short", struct.pack("<d", math.nan),
                                    struct.pack("<dd", 1, math.inf), "legacy json", None])
def test_invalid_binary_vectors_remain_unusable(payload):
    assert decode_memory_embedding(payload) == []


@pytest.mark.parametrize(("embedding", "dimensions", "expected"), [
    ([1], 1, True), ([1], 1.0, True), ([1], None, False), ([1], True, False),
    ([1], "1", False), ([1], 0, False), ([1], math.nan, False),
    ([], 0, False), ([1, math.inf], 2, False), ([1, False], 2, False),
    ((1, 2), 2, False),
])
def test_embedding_validation_uses_array_and_strict_dimension_contract(embedding, dimensions, expected):
    assert is_valid_memory_embedding(embedding, dimensions) is expected


def test_omitted_dimension_is_not_an_explicit_null():
    assert is_valid_memory_embedding([1, 2]) is True
    assert is_valid_memory_embedding([1, 2], None) is False


def test_disabled_or_empty_operations_need_no_cache_table():
    with sqlite3.connect(":memory:") as connection:
        assert load_memory_embedding_cache(connection, enabled=False,
                                           provider_identities=[IDENTITY], hashes=["h"]) == {}
        assert load_memory_embedding_cache(connection, enabled=True,
                                           provider_identities=[], hashes=["h"]) == {}
        assert load_memory_embedding_cache(connection, enabled=True,
                                           provider_identities=[IDENTITY], hashes=[""]) == {}
        upsert_memory_embedding_cache(connection, enabled=False, provider=PROVIDER,
                                      provider_key="endpoint-a", entries=[{"hash": "h"}])


def test_persistent_cache_is_available_to_a_fresh_connection(tmp_path):
    path = tmp_path / "index.sqlite"
    with sqlite3.connect(path) as connection:
        ensure_embedding_cache_schema(connection)
        put(connection, [{"hash": "hash-a", "embedding": [0.2, 0.8]}])
    with sqlite3.connect(path) as reopened:
        ensure_embedding_cache_schema(reopened)
        assert load(reopened, ["hash-a", "missing"]) == {"hash-a": [0.2, 0.8]}


def test_first_identity_owns_the_hash_even_when_its_cache_row_is_invalid(db):
    raw(db, IDENTITY, "bad", encode_memory_embedding([1, 2]), 99)
    raw(db, ALIAS, "bad", encode_memory_embedding([3, 4]), 2)
    raw(db, ALIAS, "alias-only", encode_memory_embedding([5, 6]), 2)
    assert load(db, ["bad", "alias-only"], [IDENTITY, ALIAS]) == {
        "bad": [], "alias-only": [5, 6],
    }


def test_null_legacy_dimensions_are_accepted_but_oversized_or_corrupt_rows_are_not(db):
    raw(db, IDENTITY, "legacy", encode_memory_embedding([1, 2]), None)
    raw(db, IDENTITY, "huge", encode_memory_embedding([1, 2]), 2**63 - 1)
    raw(db, IDENTITY, "truncated", b"x", None)
    raw(db, IDENTITY, "infinite", struct.pack("<dd", 1, math.inf), 2)
    raw(db, IDENTITY, "empty", b"", 0)
    assert load(db, ["legacy", "huge", "truncated", "infinite", "empty"]) == {
        "legacy": [1, 2], "huge": [], "truncated": [], "infinite": [], "empty": [],
    }


def test_cache_load_batches_fit_a_bounded_sqlite_parameter_limit(db):
    entries = [{"hash": f"hash-{index:04}", "embedding": [index, 1]} for index in range(805)]
    put(db, entries)
    db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 404)
    result = load(db, ["", *[entry["hash"] for entry in entries], "hash-0000"])
    assert len(result) == 805
    assert result["hash-0804"] == [804, 1]


def test_identity_invalidation_preserves_other_provider_spaces_and_index_rows(db):
    put(db, [{"hash": "h", "embedding": [1]}])
    raw(db, ALIAS, "h", encode_memory_embedding([2]), 1)
    other = {**IDENTITY, "providerKey": "endpoint-b"}
    raw(db, other, "h", encode_memory_embedding([3]), 1)
    db.execute("CREATE TABLE chunks (text TEXT)")
    db.execute("INSERT INTO chunks VALUES ('retained published memory')")
    clear_memory_embedding_cache_identities(db, [IDENTITY])
    assert load(db, ["h"]) == {}
    assert load(db, ["h"], [ALIAS]) == {"h": [2]}
    assert load(db, ["h"], [other]) == {"h": [3]}
    assert db.execute("SELECT text FROM chunks").fetchall() == [("retained published memory",)]


def test_last_duplicate_occurrence_controls_vector_order_and_capacity(db):
    entries = [
        {"hash": "a", "embedding": [1]}, {"hash": "b", "embedding": [2]},
        {"hash": "a", "embedding": [3]}, {"hash": "c", "embedding": [4]},
    ]
    before = deepcopy(entries)
    put(db, entries, max_entries=2)
    assert load(db, ["a", "b", "c"]) == {"a": [3], "c": [4]}
    assert db.execute("SELECT hash FROM memory_embedding_cache ORDER BY rowid").fetchall() == [
        ("a",), ("c",),
    ]
    assert entries == before


def test_capacity_reserves_before_insert_and_evicts_globally_by_age_then_rowid(db):
    other = {**IDENTITY, "provider": "other"}
    raw(db, other, "oldest-tie", encode_memory_embedding([1]), 1)
    raw(db, other, "newer-tie", encode_memory_embedding([2]), 1)
    put(db, [{"hash": "incoming", "embedding": [3]}], max_entries=2)
    assert db.execute("SELECT hash FROM memory_embedding_cache ORDER BY rowid").fetchall() == [
        ("newer-tie",), ("incoming",),
    ]
    assert load(db, ["newer-tie"], [other]) == {"newer-tie": [2]}


def test_capacity_update_republishes_incoming_hash_without_losing_newest_unrelated_row(db):
    put(db, [{"hash": "old", "embedding": [1]}], now=1)
    put(db, [{"hash": "recent", "embedding": [2]}], now=10)
    put(db, [{"hash": "old", "embedding": [3]}], max_entries=2, now=20)
    assert load(db, ["old", "recent"]) == {"old": [3], "recent": [2]}
    assert db.execute("SELECT hash FROM memory_embedding_cache ORDER BY rowid").fetchall() == [
        ("recent",), ("old",),
    ]


@pytest.mark.parametrize("capacity", [None, 0, -1, True, False, math.nan, math.inf, "1"])
def test_invalid_capacities_do_not_evict_rows(db, capacity):
    put(db, [{"hash": "a", "embedding": [1]}, {"hash": "b", "embedding": [2]}],
        max_entries=capacity)
    assert len(load(db, ["a", "b"])) == 2


def test_positive_fractional_capacity_keeps_the_native_slice_negative_zero_boundary(db):
    put(db, [{"hash": "old", "embedding": [1]}])
    put(db, [{"hash": "a", "embedding": [2]}, {"hash": "b", "embedding": [3]}],
        max_entries=0.5)
    assert load(db, ["old", "a", "b"]) == {"a": [2], "b": [3]}


def test_cache_write_uses_the_callers_transaction_without_committing(db):
    db.execute("SAVEPOINT caller")
    put(db, [{"hash": "a", "embedding": [1]}], now=0)
    assert db.execute("SELECT updated_at FROM memory_embedding_cache").fetchone() == (0,)
    db.execute("ROLLBACK TO caller")
    db.execute("RELEASE caller")
    assert load(db, ["a"]) == {}


def test_encoding_failure_rolls_back_eviction_and_partial_rows_in_a_caller_transaction(db):
    put(db, [{"hash": "old", "embedding": [1]}])
    db.commit()
    with pytest.raises(ValueError, match="finite numeric"):
        with db:
            put(db, [{"hash": "a", "embedding": [2]},
                     {"hash": "b", "embedding": [math.inf]}], max_entries=2)
    assert load(db, ["old", "a", "b"]) == {"old": [1]}


def test_collection_keeps_positions_duplicates_and_original_payloads():
    chunks = [{"hash": "a", "metadata": "keep"}, {"hash": "missing"},
              {"hash": "a"}, {"hash": "empty"}, None, {}]
    cached = {"a": [1, 2], "empty": []}
    before = deepcopy((chunks, cached))
    result = collect_memory_cached_embeddings(chunks, cached)
    assert result["embeddings"] == [[1, 2], [], [1, 2], [], [], []]
    assert result["embeddings"][0] is cached["a"]
    assert result["embeddings"][2] is cached["a"]
    assert result["missing"] == [
        {"index": 1, "chunk": chunks[1]}, {"index": 3, "chunk": chunks[3]},
        {"index": 5, "chunk": chunks[5]},
    ]
    assert (chunks, cached) == before


@pytest.mark.parametrize(("vectors", "count", "dimensions"), [
    ([[1, 2]], 2, None), ([[1, 2], [3]], 2, None), ([[1, 2], [3, math.inf]], 2, None),
    ([[1, False]], 1, None), ([[]], 1, None), ([[1, 2]], 1, 3),
    (None, 1, None), (([1, 2],), 1, None),
])
def test_batch_validation_rejects_the_complete_malformed_provider_response(vectors, count, dimensions):
    with pytest.raises(ValueError, match="malformed vector response"):
        validate_memory_embedding_batch(vectors, count, dimensions)


def test_batch_validation_preserves_input_and_infers_only_a_consistent_space():
    vectors = [[1, 2], [3, 4]]
    before = deepcopy(vectors)
    assert validate_memory_embedding_batch(vectors, 2) == 2
    assert validate_memory_embedding_batch(vectors, 2, 2) == 2
    assert validate_memory_embedding_batch([], 0) is None
    assert vectors == before
