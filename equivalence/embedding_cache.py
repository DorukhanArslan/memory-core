"""Paired cache-kernel fixtures, separate from provider and manager admission.

SQLite setup and argument transport are fixture code. All reuse, eviction,
validation and serialization decisions come from the production cache helpers.
No case here claims the complete embedding-cache lifecycle acceptance point.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


IDENTITY = {"provider": "provider-a", "model": "model-a", "providerKey": "key-a"}
ALIAS = {"provider": "provider-a", "model": "alias-a", "providerKey": "alias-key"}
OTHER = {"provider": "provider-b", "model": "model-b", "providerKey": "key-b"}


def build_embedding_cache_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(name: str, value: dict) -> None:
        cases.append({"id": f"embedding-cache-{name}", "requirement": "indexing.embedding-cache",
                      "operation": "embedding-cache", "input": value, "covers": []})

    for name, vector, dimensions in (
        ("empty", [], ...), ("zero-vector", [0, 0], ...),
        ("finite", [0.25, -1, 3], ...), ("matching-dimensions", [1, 2], 2),
        ("wrong-dimensions", [1, 2], 3), ("null-dimensions", [1, 2], None),
        ("string-dimensions", [1, 2], "2"), ("zero-dimensions", [1], 0),
        ("bool-dimensions", [1], True),
        ("bool-coordinate", [True, 2], ...), ("string-coordinate", ["1", 2], ...),
        ("null-coordinate", [None, 2], ...), ("object-coordinate", [{}, 2], ...),
        ("nan-coordinate", [{"special": "nan"}, 2], ...),
        ("infinite-coordinate", [{"special": "infinity"}], ...),
        ("negative-infinite-coordinate", [{"special": "-infinity"}], ...),
        ("not-array", "1,2", ...),
    ):
        value = {"kind": "validate", "vector": vector}
        if dimensions is not ...:
            value["dimensions"] = dimensions
        add(f"validate-{name}", value)

    for name, vector in (
        ("empty", []), ("finite", [0, -0.0, 0.25, -1.5, 1e300]),
        ("subnormal", [5e-324, -5e-324]), ("bool", [True]),
        ("string", ["1"]), ("nan", [{"special": "nan"}]),
        ("infinity", [{"special": "infinity"}]),
    ):
        add(f"codec-{name}", {"kind": "codec", "vector": vector})
    for name, value in (("malformed", "00"), ("infinity", "000000000000f07f"),
                        ("nan", "000000000000f87f"), ("empty", "")):
        add(f"decode-{name}", {"kind": "decode", "hex": value})

    def put(entries: list[dict], **options: Any) -> dict:
        return {"action": "put", "entries": entries, **options}

    def entry(hash_: str, vector: list | None = None) -> dict:
        return {"hash": hash_, "embedding": [1, 2] if vector is None else vector}

    def load(hashes: list[str], **options: Any) -> dict:
        return {"action": "load", "hashes": hashes, **options}

    def seed(identity: dict, hash_: str, *, raw: str = "000000000000f03f", dims: Any = 1) -> dict:
        return {"action": "seed", "rows": [{**identity, "hash": hash_, "hex": raw,
                                               "dims": dims, "updatedAt": 100}]}

    scripts = [
        ("reuse-and-reopen", [put([entry("a"), entry("b", [3, 4])]),
                             load(["a", "b", "missing"]), {"action": "reopen"}, load(["a"])]),
        ("disabled-write", [put([entry("a")], enabled=False), load(["a"])]),
        ("missing-provider", [put([entry("a")], provider=None), load(["a"])]),
        ("missing-provider-key", [put([entry("a")], providerKey=""), load(["a"])]),
        ("null-provider-key", [put([entry("a")], providerKey=None), load(["a"])]),
        ("empty-write", [put([]), load([])]),
        ("disabled-load", [put([entry("a")]), load(["a"], enabled=False)]),
        ("no-identities", [put([entry("a")]), load(["a"], identities=[])]),
        ("empty-and-duplicate-hashes", [put([entry("a")]), load(["", "a", "a", "missing"])]),
        ("last-occurrence", [put([entry("a", [1]), entry("b", [2]), entry("a", [3])]),
                             load(["a", "b"])]),
        ("nullable-entries-and-vectors", [put([None, {"hash": "empty", "embedding": None},
                                               entry("a"), None]), load(["a", "empty"])]),
        ("provider-separation", [put([entry("a", [1])]),
                                 put([entry("a", [2])], provider={"id": "provider-b", "model": "model-b"}, providerKey="key-b"),
                                 load(["a"], identities=[IDENTITY, OTHER])]),
        ("alias-priority", [seed(ALIAS, "a", raw="0000000000000040"), seed(IDENTITY, "a"),
                            load(["a"], identities=[IDENTITY, ALIAS]),
                            load(["a"], identities=[ALIAS, IDENTITY])]),
        ("invalid-primary-shadows-alias", [seed(ALIAS, "a"), seed(IDENTITY, "a", raw="00"),
                                          load(["a"], identities=[IDENTITY, ALIAS])]),
        ("null-dimensions-legacy", [seed(IDENTITY, "a", dims=None), load(["a"])]),
        ("wrong-dimensions", [seed(IDENTITY, "a", dims=2), load(["a"])]),
        ("unsafe-legacy-dimensions", [seed(IDENTITY, "a", dims="9007199254740993"), load(["a"])]),
        ("invalid-vectors", [seed(IDENTITY, "short", raw="00"),
                             seed(IDENTITY, "infinite", raw="000000000000f07f"),
                             seed(IDENTITY, "nan", raw="000000000000f87f"),
                             seed(IDENTITY, "empty", raw="", dims=0),
                             load(["short", "infinite", "nan", "empty"])]),
        ("scoped-clear", [seed(IDENTITY, "a"), seed(ALIAS, "a"), seed(OTHER, "a"),
                          {"action": "clear", "identities": [IDENTITY, ALIAS]},
                          load(["a"], identities=[OTHER])]),
        ("clear-empty-identities", [seed(IDENTITY, "a"), {"action": "clear", "identities": []}, load(["a"])]),
        ("capacity-clock-order", [put([entry("old")], now=1), put([entry("newer")], now=2),
                                  put([entry("incoming")], now=3, maxEntries=2)]),
        ("capacity-tie-order", [put([entry("first"), entry("second")], now=1),
                                put([entry("incoming")], now=1, maxEntries=2)]),
        ("capacity-deduplicates-before-trimming", [put([entry("a", [1]), entry("b", [2]),
                                                       entry("a", [3]), entry("c", [4])], maxEntries=2)]),
        ("capacity-reserves-globally", [seed(OTHER, "other-old"),
                                        put([entry("a"), entry("b")], now=101, maxEntries=2)]),
        ("capacity-replaces-before-reservation", [put([entry("a"), entry("b")], now=1),
                                                 put([entry("a", [3]), entry("c")], now=2, maxEntries=2)]),
        ("capacity-zero-disabled", [put([entry("a"), entry("b")], maxEntries=0)]),
        ("capacity-fraction-floors-zero", [put([entry("old")]), put([entry("a"), entry("b")], maxEntries=0.5)]),
        ("capacity-negative-disabled", [put([entry("a"), entry("b")], maxEntries=-1)]),
        ("capacity-infinite-disabled", [put([entry("a"), entry("b")], maxEntries={"special": "infinity"})]),
        ("capacity-nan-disabled", [put([entry("a"), entry("b")], maxEntries={"special": "nan"})]),
        ("capacity-bool-disabled", [put([entry("a"), entry("b")], maxEntries=True)]),
        ("capacity-string-disabled", [put([entry("a"), entry("b")], maxEntries="1")]),
        ("capacity-positive-fraction", [put([entry("a"), entry("b"), entry("c")], maxEntries=2.8)]),
        ("transaction-rollback", [put([entry("old")]), {"action": "begin"},
                                  put([entry("new")]), {"action": "rollback"}, load(["old", "new"])]),
        ("invalid-write-rollback", [put([entry("old")]), {"action": "begin"},
                                    put([entry("valid"), entry("invalid", [True])]),
                                    {"action": "rollback"}, load(["old", "valid", "invalid"])]),
        ("transaction-commit-reopen", [{"action": "begin"}, put([entry("a")]),
                                       {"action": "commit"}, {"action": "reopen"}, load(["a"])]),
        ("collection-preserves-order-and-duplicates", [{"action": "collect", "chunks": [
            {"hash": "a", "label": "first"}, {"hash": "missing"}, {"hash": "a", "label": "again"},
            {"hash": "invalid"}, {"hash": ""}, {}, None,
        ], "cached": [["a", [1, 2]], ["invalid", []]]}]),
        ("batched-lookups", [put([entry(f"hash-{index:03}") for index in range(405)]),
                              load([f"hash-{index:03}" for index in range(405)])]),
    ]
    for name, steps in scripts:
        add(name, {"kind": "script", "steps": steps})
    return deepcopy(cases)


def _special(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"special"}:
        return {"nan": math.nan, "infinity": math.inf, "-infinity": -math.inf}[value["special"]]
    if isinstance(value, list):
        return [_special(item) for item in value]
    return value


def run_embedding_cache(arguments: dict[str, Any]) -> Any:
    from memory_core.index import embedding_cache as cache

    kind = arguments["kind"]
    if kind == "validate":
        options = {"dimensions": arguments["dimensions"]} if "dimensions" in arguments else {}
        return cache.is_valid_memory_embedding(_special(arguments["vector"]), **options)
    if kind == "decode":
        return cache.decode_memory_embedding(bytes.fromhex(arguments["hex"]))
    if kind == "codec":
        try:
            encoded = cache.encode_memory_embedding(_special(arguments["vector"]))
            return {"hex": encoded.hex(), "decoded": cache.decode_memory_embedding(encoded)}
        except ValueError as error:
            return {"error": str(error)}
    if kind != "script":
        raise ValueError(f"Unsupported embedding cache operation: {kind}")

    with tempfile.TemporaryDirectory(prefix="memory-core-cache-") as directory:
        filename = Path(directory) / "cache.sqlite"
        db = sqlite3.connect(filename, isolation_level=None)
        cache.ensure_embedding_cache_schema(db)

        def snapshot() -> list[dict]:
            rows = db.execute("SELECT provider,model,provider_key,hash,embedding,CAST(dims AS TEXT),updated_at "
                              "FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash")
            return [{"provider": provider, "model": model, "providerKey": key, "hash": hash_,
                     "embedding": cache.decode_memory_embedding(raw), "dims": dims, "updatedAt": updated}
                    for provider, model, key, hash_, raw, dims, updated in rows]

        outcomes = []
        try:
            for step in arguments["steps"]:
                action = step["action"]
                outcome: dict[str, Any] = {"action": action}
                try:
                    if action == "put":
                        cache.upsert_memory_embedding_cache(
                            db, enabled=step.get("enabled", True),
                            provider=step.get("provider", {"id": "provider-a", "model": "model-a"}),
                            provider_key=step.get("providerKey", "key-a"),
                            entries=[None if entry is None else
                                     {**entry, "embedding": _special(entry.get("embedding"))}
                                     for entry in step["entries"]],
                            max_entries=_special(step.get("maxEntries")), now=step.get("now", 100),
                        )
                    elif action == "load":
                        loaded = cache.load_memory_embedding_cache(
                            db, enabled=step.get("enabled", True),
                            provider_identities=step.get("identities", [IDENTITY]), hashes=step["hashes"],
                        )
                        outcome["loaded"] = [[key, value] for key, value in sorted(loaded.items())]
                    elif action == "clear":
                        cache.clear_memory_embedding_cache_identities(db, step["identities"])
                    elif action == "seed":
                        for row in step["rows"]:
                            db.execute("INSERT OR REPLACE INTO memory_embedding_cache VALUES (?,?,?,?,?,?,?)",
                                       (row["provider"], row["model"], row["providerKey"], row["hash"],
                                        bytes.fromhex(row["hex"]), row["dims"], row["updatedAt"]))
                    elif action == "collect":
                        outcome["collected"] = cache.collect_memory_cached_embeddings(
                            step["chunks"], dict(step["cached"]))
                    elif action in {"begin", "commit", "rollback"}:
                        db.execute(action.upper())
                    elif action == "reopen":
                        db.close()
                        db = sqlite3.connect(filename, isolation_level=None)
                    else:
                        raise ValueError(f"Unsupported cache script action: {action}")
                except ValueError as error:
                    outcome["error"] = str(error)
                outcome["state"] = snapshot()
                outcomes.append(outcome)
            return outcomes
        finally:
            db.close()
