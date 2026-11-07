"""Model-free inputs and translations for the native index identity kernel.

These calls compare identity decisions, not query synchronization or admission
through the complete upstream manager. The separate query-sync contract remains
responsible for proving how the host consumes those decisions.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_index_identity_cases() -> list[dict[str, Any]]:
    """Build named configuration and stored-JSON boundaries without snapshots."""
    cases: list[dict[str, Any]] = []

    def add(name: str, arguments: dict[str, Any]) -> None:
        cases.append({
            "id": f"identity-{name}",
            "requirement": "indexing.identity",
            "operation": "index-identity",
            "input": arguments,
            # This kernel does not exercise the manager's actual query dispatch.
            "covers": ["indexing.identity.outcomes"],
        })

    meta = {
        "model": "embedding-a", "provider": "provider-a", "providerKey": "key-a",
        "sources": ["memory", "sessions"], "scopeHash": "scope-a",
        "chunkTokens": 400, "chunkOverlap": 80, "chunkingVersion": 5,
        "provenanceVersion": 1, "ftsTokenizer": "unicode61", "vectorDims": 16,
    }
    params = {
        "meta": meta, "provider": {"id": "provider-a", "model": "embedding-a"},
        "providerKey": "key-a", "configuredSources": ["memory", "sessions"],
        "configuredScopeHash": "scope-a", "chunkTokens": 400, "chunkOverlap": 80,
        "vectorReady": True, "hasIndexedChunks": True, "ftsTokenizer": "unicode61",
    }

    def state(name: str, *, stored: object = ..., **changes: Any) -> None:
        value = deepcopy(params)
        if stored is not ...:
            value["meta"] = deepcopy(stored)
        value.update(changes)
        add(name, {"kind": "state", "params": value})

    state("matching-vector")
    for name, value in (("missing", None), ("false", False), ("empty-string", ""),
                        ("zero", 0), ("empty-object", {}), ("empty-array", [])):
        state(f"metadata-{name}", stored=value)
    for name, value in (
        ("model", {"model": "embedding-old"}),
        ("provider", {"provider": "provider-old"}),
        ("provider-settings", {"providerKey": "endpoint-old"}),
        ("source-memory-only", {"sources": ["memory"]}),
        ("source-order-duplicates", {"sources": ["sessions", "memory", "memory", "unknown"]}),
        ("scope", {"scopeHash": "scope-old"}),
        ("chunk-tokens", {"chunkTokens": 401}),
        ("chunk-overlap", {"chunkOverlap": 81}),
        ("chunk-type", {"chunkTokens": "400"}),
        ("tokenizer", {"ftsTokenizer": "porter"}),
        ("tokenizer-null", {"ftsTokenizer": None}),
        ("vector-zero", {"vectorDims": 0}),
        ("vector-null", {"vectorDims": None}),
        ("vector-false", {"vectorDims": False}),
        ("vector-empty-string", {"vectorDims": ""}),
        ("vector-empty-array", {"vectorDims": []}),
        ("vector-empty-object", {"vectorDims": {}}),
        ("old-provenance", {"provenanceVersion": 0}),
        ("old-chunker", {"chunkingVersion": 4}),
        ("new-provenance", {"provenanceVersion": 2}),
        ("new-chunker", {"chunkingVersion": 6}),
        ("new-provenance-old-chunker", {"provenanceVersion": 2, "chunkingVersion": 4}),
        ("old-provenance-new-chunker", {"provenanceVersion": 0, "chunkingVersion": 6}),
        ("old-chunker-with-scope-change", {"chunkingVersion": 4, "scopeHash": "other"}),
        ("version-numeric-strings", {"provenanceVersion": "1", "chunkingVersion": "5"}),
        ("version-null", {"provenanceVersion": None}),
        ("version-hex-zero", {"provenanceVersion": "0x0"}),
        ("version-binary-newer", {"provenanceVersion": "0b10"}),
        ("version-octal-zero", {"chunkingVersion": "0o0"}),
        ("version-empty-array", {"chunkingVersion": []}),
        ("version-nested-array", {"chunkingVersion": [["0"]]}),
        ("version-multiple-array", {"chunkingVersion": [0, 0]}),
        ("version-invalid-inf", {"provenanceVersion": "inf"}),
        ("version-invalid-underscore", {"provenanceVersion": "0_0"}),
        ("version-invalid-unicode-digit", {"provenanceVersion": "٠"}),
        ("version-invalid-signed-hex", {"provenanceVersion": "+0x0"}),
        ("version-infinity", {"provenanceVersion": "Infinity"}),
        ("version-object", {"chunkingVersion": {}}),
    ):
        state(name, stored={**meta, **value})

    for field in ("model", "provider", "providerKey", "sources", "scopeHash", "chunkTokens",
                  "chunkOverlap", "chunkingVersion", "provenanceVersion", "ftsTokenizer", "vectorDims"):
        state(f"missing-field-{field}", stored={key: value for key, value in meta.items() if key != field})
    state("fts-only", stored={**meta, "provider": "none", "model": "fts-only", "providerKey": "fts-key"},
          provider=None, providerKey="fts-key", vectorReady=False)
    state("provider-model-trim", provider={"id": "provider-a", "model": "\ufeff embedding-a\u00a0"})
    state("provider-model-unresolved", provider={"id": "provider-a"}, providerKey="unresolved")
    state("unknown-provider-key", providerKey="unresolved", providerKeyKnown=False)
    state("known-provider-key", providerKey="unresolved", providerKeyKnown=True)
    state("valid-model-alias", stored={**meta, "model": "alias", "providerKey": "alias-key"},
          providerAliases=[{"model": "alias", "providerKey": "alias-key"}])
    state("wrong-model-alias-key", stored={**meta, "model": "alias", "providerKey": "alias-key"},
          providerAliases=[{"model": "alias", "providerKey": "wrong-key"}])
    state("empty-index-no-dimensions", stored={key: value for key, value in meta.items() if key != "vectorDims"},
          hasIndexedChunks=False)
    state("vectors-not-ready", stored={**meta, "vectorDims": None}, vectorReady=False)
    for sources in ([], ["sessions"], ["memory", "memory"], ["unknown"]):
        add(f"configured-sources-{len(cases)}", {"kind": "sources", "sources": sources})

    for name, values in (
        ("fts", {"provider": None}),
        ("default-provider", {"provider": {"id": "provider-a", "model": "embedding-a"}}),
        ("endpoint-a", {"provider": {"id": "provider-a", "model": "embedding-a"},
                        "cacheKeyData": {"provider": "provider-a", "model": "embedding-a", "baseUrl": "https://a.invalid/v1"}}),
        ("endpoint-b", {"provider": {"id": "provider-a", "model": "embedding-a"},
                        "cacheKeyData": {"provider": "provider-a", "model": "embedding-a", "baseUrl": "https://b.invalid/v1"}}),
        ("aliases", {"provider": {"id": "provider-a", "model": "embedding-a"}, "aliases": [
            {"model": "embedding-a", "cacheKeyData": {"provider": "provider-a", "model": "embedding-a"}},
            {"model": "", "cacheKeyData": {}},
            {"model": "alias", "cacheKeyData": {"provider": "provider-a", "endpoint": "compat"}},
        ]}),
        ("fts-ignores-aliases", {"provider": None, "aliases": [{"model": "alias", "cacheKeyData": {}}]}),
    ):
        add(f"provider-identities-{name}", {"kind": "providers", "params": values})
    for name, multimodal in (
        ("default", {"enabled": False, "modalities": [], "maxFileBytes": 10 * 1024 * 1024}),
        ("enabled", {"enabled": True, "modalities": ["video", "image", "audio"], "maxFileBytes": 1024}),
        ("sorted", {"enabled": True, "modalities": ["audio", "image", "video"], "maxFileBytes": 1024}),
        ("different-cap", {"enabled": True, "modalities": ["video", "image", "audio"], "maxFileBytes": 1025}),
    ):
        add(f"scope-{name}", {"kind": "scope", "multimodal": multimodal})
    return cases


def run_index_identity(arguments: dict[str, Any]) -> Any:
    """Call the public Python identity functions with translated argument names."""
    from memory_core.index.identity import (
        resolve_configured_scope_hash,
        resolve_configured_sources_for_meta,
        resolve_memory_index_identity_state,
        resolve_memory_index_provider_identities,
    )

    kind = arguments["kind"]
    if kind == "sources":
        return resolve_configured_sources_for_meta(arguments["sources"])
    if kind == "providers":
        params = arguments["params"]
        return resolve_memory_index_provider_identities(
            params["provider"], cache_key_data=params.get("cacheKeyData"),
            aliases=params.get("aliases", ()),
        )
    if kind == "scope":
        settings = arguments["multimodal"]
        return resolve_configured_scope_hash(
            multimodal_enabled=settings["enabled"], modalities=settings["modalities"],
            max_file_bytes=settings["maxFileBytes"],
        )
    if kind == "state":
        names = {
            "providerKey": "provider_key", "providerAliases": "provider_aliases",
            "providerKeyKnown": "provider_key_known", "configuredSources": "configured_sources",
            "configuredScopeHash": "configured_scope_hash", "chunkTokens": "chunk_tokens",
            "chunkOverlap": "chunk_overlap", "vectorReady": "vector_ready",
            "hasIndexedChunks": "has_indexed_chunks", "ftsTokenizer": "fts_tokenizer",
        }
        return resolve_memory_index_identity_state(**{
            names.get(key, key): value for key, value in arguments["params"].items()
        })
    raise ValueError(f"Unsupported index identity operation: {kind}")
