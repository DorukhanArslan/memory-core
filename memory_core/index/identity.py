"""Memory index identity: what an index was built with, and whether it still fits.

Port of OpenClaw ``extensions/memory-core/src/memory/manager-reindex-state.ts``
(``resolveMemoryIndexIdentityState``, ``resolveMemoryIndexProviderIdentities``,
``resolveConfiguredSourcesForMeta``, ``resolveConfiguredScopeHash``). A full
reindex persists the identity as JSON under ``memory_index_meta_v1`` in the
``memory_index_meta`` table (``manager-sync-ops.ts`` ``writeMeta``); a search
compares it with the current configuration and pauses on any difference
instead of mixing incompatible vectors or chunks.

Meta values are compared with JavaScript semantics because they come from
stored JSON: a missing key is ``undefined`` (distinct from ``null``), numbers
compare by value, and ``!meta.vectorDims`` is JavaScript falsiness.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import js_json_stringify, js_trim

MEMORY_INDEX_META_TABLE = "memory_index_meta"
MEMORY_INDEX_META_KEY = "memory_index_meta_v1"
DEFAULT_FTS_TOKENIZER = "unicode61"
# packages/memory-host-sdk/src/host/multimodal.ts DEFAULT_MEMORY_MULTIMODAL_MAX_FILE_BYTES.
DEFAULT_MEMORY_MULTIMODAL_MAX_FILE_BYTES = 10 * 1024 * 1024
FTS_ONLY_MODEL = "fts-only"
NO_PROVIDER_ID = "none"

MEMORY_SOURCES = ("memory", "sessions")
# manager-reindex-state.ts MEMORY_INDEX_PROVENANCE_VERSION and
# packages/memory-host-sdk/src/host/markdown-chunks.ts MEMORY_CHUNKING_VERSION at v2026.9.6.
# The store writes both. Until the chunker is re-ported (stage 2 area 6) the chunking
# version states the tag's number, not the pin-era chunker's.
MEMORY_INDEX_PROVENANCE_VERSION = 1
MEMORY_CHUNKING_VERSION = 5


class _Undefined:
    def __repr__(self) -> str:
        return "undefined"


UNDEFINED: Any = _Undefined()


def hash_text(value: str) -> str:
    """``hashText`` (packages/memory-host-sdk/src/host/hash.ts): sha256 hex of UTF-8."""
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _get(record: object, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, UNDEFINED)
    return UNDEFINED


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _strict_equal(left: object, right: object) -> bool:
    if left is UNDEFINED or right is UNDEFINED:
        return left is right
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _falsy(value: object) -> bool:
    if value is UNDEFINED or value is None or value is False:
        return True
    if _is_number(value):
        return value == 0 or (isinstance(value, float) and math.isnan(value))
    return isinstance(value, str) and value == ""


def _template(value: object) -> str:
    """How ``${value}`` renders a JSON value in a template literal."""
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return repr(value)  # matches Number#toString except for exotic exponents
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join("" if item is None else _template(item) for item in value)
    return "[object Object]"


def resolve_memory_index_provider_identities(
    provider: Mapping[str, str] | None,
    *,
    cache_key_data: Mapping[str, Any] | None = None,
    aliases: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    """``resolveMemoryIndexProviderIdentities``: the primary identity first, then aliases.

    ``providerKey`` hashes the provider's cache-key JSON, which defaults to
    ``{"provider": id, "model": model}``; FTS-only is provider ``none`` /
    model ``fts-only``.
    """
    resolved = provider if provider is not None else {"id": NO_PROVIDER_ID, "model": FTS_ONLY_MODEL}
    candidates: list[tuple[str, Mapping[str, Any]]] = [
        (
            resolved["model"],
            cache_key_data
            if cache_key_data is not None
            else {"provider": resolved["id"], "model": resolved["model"]},
        )
    ]
    if provider is not None:
        candidates.extend((alias["model"], alias["cacheKeyData"]) for alias in aliases)
    seen: set[str] = set()
    identities: list[dict[str, str]] = []
    for index, (model, key_data) in enumerate(candidates):
        provider_key = hash_text(js_json_stringify(key_data))
        key = f"{model}\u0000{provider_key}"
        if (index > 0 and not model) or key in seen:
            continue
        seen.add(key)
        identities.append({"provider": resolved["id"], "model": model, "providerKey": provider_key})
    return identities


def resolve_configured_sources_for_meta(sources: Iterable[str]) -> list[str]:
    """``resolveConfiguredSourcesForMeta``: sorted memory/sessions, default ``["memory"]``."""
    normalized = sorted(source for source in sources if source in MEMORY_SOURCES)
    return normalized or ["memory"]


def _normalize_meta_sources(meta: object) -> list[str]:
    sources = _get(meta, "sources")
    if not isinstance(sources, list):
        # Backward compatibility for older indexes that did not persist sources.
        return ["memory"]
    normalized = sorted({source for source in sources if source in MEMORY_SOURCES})
    return normalized or ["memory"]


def resolve_configured_scope_hash(
    *,
    multimodal_enabled: bool = False,
    modalities: Sequence[str] = (),
    max_file_bytes: int = DEFAULT_MEMORY_MULTIMODAL_MAX_FILE_BYTES,
) -> str:
    """``resolveConfiguredScopeHash`` with no ``extraPaths`` (memory-core has none).

    With multimodal disabled, upstream normalizes ``modalities`` to ``[]``
    before hashing (``normalizeMemoryMultimodalSettings``); pass the
    normalized settings.
    """
    return hash_text(
        js_json_stringify(
            {
                "extraPaths": [],
                "multimodal": {
                    "enabled": multimodal_enabled,
                    "modalities": sorted(modalities),
                    "maxFileBytes": max_file_bytes,
                },
            }
        )
    )


def _js_number(value: object) -> float:
    """The number a stored JSON value becomes in a JavaScript relational comparison."""
    if value is UNDEFINED or value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if _is_number(value):
        return float(value)  # type: ignore[arg-type]
    if isinstance(value, str):
        text = js_trim(value)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


def _version(meta: object, key: str) -> float:
    # `meta.<key> ?? 0`, then compared with a number.
    value = _get(meta, key)
    return 0.0 if value is UNDEFINED or value is None else _js_number(value)


def _openclaw_mismatch(code: str, reason: str, version_order: str) -> dict[str, Any]:
    return {
        "status": "mismatched",
        "reason": reason,
        "code": code,
        "owner": "openclaw",
        "versionOrder": version_order,
    }


def _configured_mismatch(code: str, reason: str) -> dict[str, Any]:
    return {"status": "mismatched", "reason": reason, "code": code, "owner": "configuration"}


def _content_scope_identity_state(
    meta: object,
    *,
    configured_sources: Sequence[str],
    configured_scope_hash: str,
    chunk_tokens: int,
    chunk_overlap: int,
    fts_tokenizer: str,
) -> dict[str, Any]:
    """``resolveContentScopeIdentityState``: embedding identity is deliberately absent."""
    if _normalize_meta_sources(meta) != list(configured_sources):
        return _configured_mismatch("sources", "index sources changed")
    if not _strict_equal(_get(meta, "scopeHash"), configured_scope_hash):
        return _configured_mismatch("scope", "index scope changed")
    if not _strict_equal(_get(meta, "chunkTokens"), chunk_tokens) or not _strict_equal(
        _get(meta, "chunkOverlap"), chunk_overlap
    ):
        return _configured_mismatch("chunking", "index chunking changed")
    meta_tokenizer = _get(meta, "ftsTokenizer")
    if meta_tokenizer is UNDEFINED or meta_tokenizer is None:
        meta_tokenizer = DEFAULT_FTS_TOKENIZER
    if not _strict_equal(meta_tokenizer, fts_tokenizer):
        return _configured_mismatch("fts_tokenizer", "index FTS tokenizer changed")
    return {"status": "valid"}


def resolve_memory_index_identity_state(
    *,
    meta: object,
    provider: Mapping[str, str] | None,
    provider_key: str | None = None,
    provider_aliases: Sequence[Mapping[str, Any]] = (),
    provider_key_known: bool | None = None,
    configured_sources: Sequence[str],
    configured_scope_hash: str,
    chunk_tokens: int,
    chunk_overlap: int,
    vector_ready: bool,
    has_indexed_chunks: bool | None = None,
    fts_tokenizer: str,
) -> dict[str, Any]:
    """``resolveMemoryIndexIdentityState``: ``{"status": "valid"}`` or a diagnostic.

    A diagnostic has a ``reason``, a ``code`` and an ``owner``: ``openclaw`` for a
    missing index or one written by another version of the indexer
    (``provenance_version``, ``chunking_version``; ``versionOrder`` says older or
    newer, ``chunkingVersionOnly`` that an older chunker's corpus still fits the
    configuration), ``configuration`` for a changed setting. A newer version wins
    over an older one, then provenance over chunking, then the configuration
    checks in upstream order. ``meta`` is the parsed stored JSON (``None`` when
    missing or unreadable); a ``None`` ``provider_key`` stands for ``undefined``.
    """
    if _falsy(meta):
        return {
            "status": "missing",
            "reason": "index metadata is missing",
            "code": "metadata_missing",
            "owner": "openclaw",
        }
    provenance = _version(meta, "provenanceVersion")
    chunking = _version(meta, "chunkingVersion")
    # A newer dimension wins over an older one: a rollback cannot rewrite that index.
    if provenance > MEMORY_INDEX_PROVENANCE_VERSION or chunking > MEMORY_CHUNKING_VERSION:
        return _openclaw_mismatch(
            "provenance_version" if provenance > MEMORY_INDEX_PROVENANCE_VERSION else "chunking_version",
            "the index was written by a newer OpenClaw version; upgrade OpenClaw or reindex "
            "explicitly",
            "newer",
        )
    if provenance < MEMORY_INDEX_PROVENANCE_VERSION:
        return _openclaw_mismatch(
            "provenance_version", "index provenance classifier changed", "older"
        )
    content_scope = {
        "configured_sources": configured_sources,
        "configured_scope_hash": configured_scope_hash,
        "chunk_tokens": chunk_tokens,
        "chunk_overlap": chunk_overlap,
        "fts_tokenizer": fts_tokenizer,
    }
    if chunking < MEMORY_CHUNKING_VERSION:
        # Only an older chunker may use the last published lexical corpus.
        state = _openclaw_mismatch(
            "chunking_version", "index chunking implementation changed", "older"
        )
        if _content_scope_identity_state(meta, **content_scope)["status"] == "valid":
            state["chunkingVersionOnly"] = True
        return state

    if provider is not None and "model" not in provider:
        expected_model: Any = UNDEFINED
    else:
        expected_model = (js_trim(provider["model"]) if provider is not None else "") or FTS_ONLY_MODEL
    meta_model = _get(meta, "model")
    matching = [
        identity
        for identity in (
            {"model": expected_model, "providerKey": UNDEFINED if provider_key is None else provider_key},
            *(
                {"model": _get(alias, "model"), "providerKey": _get(alias, "providerKey")}
                for alias in provider_aliases
            ),
        )
        if _strict_equal(identity["model"], meta_model)
    ]
    if expected_model is not UNDEFINED and not matching:
        return _configured_mismatch(
            "model",
            f"index was built for model {_template(meta_model)}, expected {expected_model}",
        )
    expected_provider = provider["id"] if provider is not None else NO_PROVIDER_ID
    meta_provider = _get(meta, "provider")
    if not _strict_equal(meta_provider, expected_provider):
        return _configured_mismatch(
            "provider",
            f"index was built for provider {_template(meta_provider)}, expected {expected_provider}",
        )
    meta_provider_key = _get(meta, "providerKey")
    if (
        expected_model is not UNDEFINED
        and provider_key_known is not False
        and not any(_strict_equal(identity["providerKey"], meta_provider_key) for identity in matching)
    ):
        return _configured_mismatch("provider_settings", "index provider settings changed")
    content = _content_scope_identity_state(meta, **content_scope)
    if content["status"] != "valid":
        return content
    if vector_ready and has_indexed_chunks is not False and _falsy(_get(meta, "vectorDims")):
        return _configured_mismatch("vector_dims", "index vector dimensions are missing")
    return {"status": "valid"}


def parse_index_meta(value: str | None) -> Any:
    """``readMeta``: the stored JSON, or ``None`` when empty or unparsable."""
    if not value:
        return None

    def reject_constant(name: str) -> Any:
        raise ValueError(name)

    try:
        return json.loads(value, parse_constant=reject_constant)
    except ValueError:
        return None
