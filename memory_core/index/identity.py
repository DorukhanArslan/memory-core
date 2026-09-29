"""Memory index identity: what an index was built with, and whether it still fits.

Port of OpenClaw v2026.9.6 ``extensions/memory-core/src/memory/manager-reindex-state.ts``
(``resolveMemoryIndexIdentityState``, ``resolveMemoryIndexProviderIdentities``,
``resolveConfiguredSourcesForMeta``, ``resolveConfiguredScopeHash``) and of the index search
diagnostic in ``packages/memory-host-sdk/src/host/types.ts:202-380``
(``resolveMemoryIndexIdentityReason``, ``resolveMemoryIndexIdentityDiagnostic``,
``formatMemoryIndexRebuildGuidance``, ``resolveMemoryIndexSearchDiagnostic``,
``resolveMemorySearchStaleness``; 28630a9a650 #114819). A full reindex persists the identity
as JSON under ``memory_index_meta_v1`` in the ``memory_index_meta`` table
(``manager-sync-ops.ts`` ``writeMeta``); a search compares it with the current configuration
and pauses on any difference instead of mixing incompatible vectors or chunks.

A difference carries a ``code`` and an ``owner``: ``"configuration"`` for a changed model,
provider, provider settings, sources, scope, chunking, FTS tokenizer or missing vector
dimensions, ``"openclaw"`` (upstream's protocol value for the runtime's own index format; kept
verbatim, like the other parity-bound markers) for missing metadata and for an index whose
``provenanceVersion`` or ``chunkingVersion`` is older or newer than the runtime's, with a
``versionOrder``. Decision D2 of docs/upstream_port_v2026_9_6.md: the two versions are a
parameter (:class:`MemoryIndexVersions`). The oracle compares the function at the tag's versions
(:data:`UPSTREAM_INDEX_VERSIONS`, 1 and 5); memory-core's store writes and compares its own
(:data:`MEMORY_CORE_INDEX_VERSIONS`, 0 and 0: it has neither upstream's provenance classifier,
area 7, nor its v5 chunker, area 6), so an index written before the port, without the two keys,
reads as ``valid``.

Meta values are compared with JavaScript semantics because they come from
stored JSON: a missing key is ``undefined`` (distinct from ``null``), numbers
compare by value, ``(v ?? 0) > N`` converts with ``ToNumber`` and ``!meta.vectorDims`` is
JavaScript falsiness.

Not ported: the repair-failure branch and the ``lastSyncError`` staleness of the diagnostic
(memory-core has no background sync, so no sync error exists).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from dataclasses import dataclass

from memory_core.bootstrap._js import js_json_stringify, js_to_number, js_trim
from memory_core.index._index_identity_constants import (
    MEMORY_CHUNKING_VERSION,
    MEMORY_INDEX_CHUNKING_CHANGED_REASON,
    MEMORY_INDEX_CHUNKING_VERSION_CHANGED_REASON,
    MEMORY_INDEX_CONFIGURATION_CAUSE_TEMPLATE,
    MEMORY_INDEX_CONFIGURATION_CODES,
    MEMORY_INDEX_FTS_TOKENIZER_CHANGED_REASON,
    MEMORY_INDEX_IDENTITY_DEFAULT_REASON,
    MEMORY_INDEX_METADATA_MISSING_CAUSE_TEMPLATE,
    MEMORY_INDEX_METADATA_MISSING_REASON,
    MEMORY_INDEX_MODEL_CHANGED_TEMPLATE,
    MEMORY_INDEX_NEWER_VERSION_REASON,
    MEMORY_INDEX_OPENCLAW_CODES,
    MEMORY_INDEX_PAUSED_WARNING_TEMPLATE,
    MEMORY_INDEX_PROVENANCE_CHANGED_REASON,
    MEMORY_INDEX_PROVENANCE_VERSION,
    MEMORY_INDEX_PROVIDER_CHANGED_TEMPLATE,
    MEMORY_INDEX_PROVIDER_SETTINGS_CHANGED_REASON,
    MEMORY_INDEX_REBUILD_ACTION_TEMPLATE,
    MEMORY_INDEX_REBUILD_GUIDANCE_TEMPLATE,
    MEMORY_INDEX_REBUILD_KEYWORD_ONLY_DISCLOSURE,
    MEMORY_INDEX_REBUILD_PROVIDER_COST_DISCLOSURE,
    MEMORY_INDEX_SCOPE_CHANGED_REASON,
    MEMORY_INDEX_SOURCES_CHANGED_REASON,
    MEMORY_INDEX_STALE_REBUILD_ACTION_TEMPLATE,
    MEMORY_INDEX_STALE_WARNING_TEMPLATE,
    MEMORY_INDEX_VECTOR_DIMS_MISSING_REASON,
)
from memory_core.project_name import DISPLAY_NAME
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

MEMORY_INDEX_META_TABLE = "memory_index_meta"
MEMORY_INDEX_META_KEY = "memory_index_meta_v1"
DEFAULT_FTS_TOKENIZER = "unicode61"
# packages/memory-host-sdk/src/host/multimodal.ts DEFAULT_MEMORY_MULTIMODAL_MAX_FILE_BYTES.
DEFAULT_MEMORY_MULTIMODAL_MAX_FILE_BYTES = 10 * 1024 * 1024
FTS_ONLY_MODEL = "fts-only"
NO_PROVIDER_ID = "none"

MEMORY_SOURCES = ("memory", "sessions")
# manager-reindex-state.ts owners: the runtime's own index format and the user's configuration.
OPENCLAW_OWNER = "openclaw"
CONFIGURATION_OWNER = "configuration"
METADATA_MISSING_CODE = "metadata_missing"


@dataclass(frozen=True)
class MemoryIndexVersions:
    """The index format versions an identity check compares with (decision D2).

    ``newer_reason`` is the reason for an index written by a newer version; it names the
    runtime that owns the versions.
    """

    provenance: int
    chunking: int
    newer_reason: str


# MEMORY_INDEX_PROVENANCE_VERSION and MEMORY_CHUNKING_VERSION at the tag (oracle comparisons).
UPSTREAM_INDEX_VERSIONS = MemoryIndexVersions(
    provenance=MEMORY_INDEX_PROVENANCE_VERSION,
    chunking=MEMORY_CHUNKING_VERSION,
    newer_reason=MEMORY_INDEX_NEWER_VERSION_REASON,
)
# What memory-core's store writes and compares: no provenance classifier, no v5 chunker yet.
MEMORY_CORE_INDEX_VERSIONS = MemoryIndexVersions(
    provenance=0,
    chunking=0,
    newer_reason=(
        f"the index was written by a newer {DISPLAY_NAME} version; upgrade {DISPLAY_NAME} or "
        "reindex explicitly"
    ),
)


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


def _openclaw_mismatch(code: str, reason: str, version_order: str) -> dict[str, Any]:
    # manager-reindex-state.ts:102-108 openClawIndexMismatch.
    return {
        "status": "mismatched",
        "reason": reason,
        "code": code,
        "owner": OPENCLAW_OWNER,
        "versionOrder": version_order,
    }


def _configuration_mismatch(code: str, reason: str) -> dict[str, Any]:
    # manager-reindex-state.ts:110-123 configuredIndexMismatch.
    return {"status": "mismatched", "reason": reason, "code": code, "owner": CONFIGURATION_OWNER}


def _meta_version(meta: object, key: str) -> float:
    # `(meta.<key> ?? 0)` compared with a number: ToNumber of the stored JSON value.
    value = _get(meta, key)
    return js_to_number(0 if value is UNDEFINED or value is None else value)


def _content_scope_identity_state(
    meta: object,
    *,
    configured_sources: Sequence[str],
    configured_scope_hash: str,
    chunk_tokens: int,
    chunk_overlap: int,
    fts_tokenizer: str,
) -> dict[str, Any]:
    """``resolveContentScopeIdentityState`` (manager-reindex-state.ts:213-230): the constraints
    that decide whether stored keyword rows still describe the configured corpus (no embedding
    identity)."""
    if _normalize_meta_sources(meta) != list(configured_sources):
        return _configuration_mismatch("sources", MEMORY_INDEX_SOURCES_CHANGED_REASON)
    if not _strict_equal(_get(meta, "scopeHash"), configured_scope_hash):
        return _configuration_mismatch("scope", MEMORY_INDEX_SCOPE_CHANGED_REASON)
    if not _strict_equal(_get(meta, "chunkTokens"), chunk_tokens) or not _strict_equal(
        _get(meta, "chunkOverlap"), chunk_overlap
    ):
        return _configuration_mismatch("chunking", MEMORY_INDEX_CHUNKING_CHANGED_REASON)
    meta_tokenizer = _get(meta, "ftsTokenizer")
    if meta_tokenizer is UNDEFINED or meta_tokenizer is None:
        meta_tokenizer = DEFAULT_FTS_TOKENIZER
    if not _strict_equal(meta_tokenizer, fts_tokenizer):
        return _configuration_mismatch("fts_tokenizer", MEMORY_INDEX_FTS_TOKENIZER_CHANGED_REASON)
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
    versions: MemoryIndexVersions = MEMORY_CORE_INDEX_VERSIONS,
) -> dict[str, Any]:
    """``resolveMemoryIndexIdentityState`` (manager-reindex-state.ts:232-279, v2026.9.6).

    ``{"status": "valid"}``, or ``missing``/``mismatched`` with ``reason``, ``code`` and
    ``owner`` (plus ``versionOrder`` and, for an older chunker whose content scope still
    matches, ``chunkingVersionOnly`` on an ``openclaw`` mismatch). Order: missing metadata, a
    newer version (provenance first), an older provenance, an older chunker, then the
    configuration: model, provider, provider settings, sources, scope, chunking, FTS tokenizer,
    vector dimensions; the first difference wins. ``meta`` is the parsed stored JSON (``None``
    when missing or unreadable); a ``None`` ``provider_key`` stands for ``undefined``, and a
    provider without a ``"model"`` key skips the model and provider-settings checks
    (``expectedModel`` is undefined upstream).
    """
    if _falsy(meta):
        return {
            "status": "missing",
            "reason": MEMORY_INDEX_METADATA_MISSING_REASON,
            "code": METADATA_MISSING_CODE,
            "owner": OPENCLAW_OWNER,
        }
    provenance = _meta_version(meta, "provenanceVersion")
    chunking = _meta_version(meta, "chunkingVersion")
    # A newer dimension wins over an older one: a rollback cannot rewrite that index.
    if provenance > versions.provenance or chunking > versions.chunking:
        return _openclaw_mismatch(
            "provenance_version" if provenance > versions.provenance else "chunking_version",
            versions.newer_reason,
            "newer",
        )
    if provenance < versions.provenance:
        return _openclaw_mismatch(
            "provenance_version", MEMORY_INDEX_PROVENANCE_CHANGED_REASON, "older"
        )
    content_scope = {
        "configured_sources": configured_sources,
        "configured_scope_hash": configured_scope_hash,
        "chunk_tokens": chunk_tokens,
        "chunk_overlap": chunk_overlap,
        "fts_tokenizer": fts_tokenizer,
    }
    if chunking < versions.chunking:
        # Only an older chunker may use the last published lexical corpus; source/scope
        # identity authorizes it, embedding identity does not.
        mismatch = _openclaw_mismatch(
            "chunking_version", MEMORY_INDEX_CHUNKING_VERSION_CHANGED_REASON, "older"
        )
        if _content_scope_identity_state(meta, **content_scope)["status"] == "valid":
            mismatch["chunkingVersionOnly"] = True
        return mismatch
    # resolveConfigurationIndexIdentityState (manager-reindex-state.ts:167-207).
    if provider is not None and "model" not in provider:
        expected_model: Any = UNDEFINED
    else:
        raw_model = provider.get("model") if provider is not None else None
        expected_model = (js_trim(raw_model) if isinstance(raw_model, str) else "") or FTS_ONLY_MODEL
    meta_model = _get(meta, "model")
    candidates = [
        {"model": expected_model, "providerKey": UNDEFINED if provider_key is None else provider_key},
        *(
            {"model": _get(alias, "model"), "providerKey": _get(alias, "providerKey")}
            for alias in provider_aliases
        ),
    ]
    matching = [identity for identity in candidates if _strict_equal(identity["model"], meta_model)]
    if expected_model is not UNDEFINED and not matching:
        return _configuration_mismatch(
            "model",
            MEMORY_INDEX_MODEL_CHANGED_TEMPLATE.format(
                meta_model=_template(meta_model), expected_model=expected_model
            ),
        )
    expected_provider = provider["id"] if provider is not None else NO_PROVIDER_ID
    meta_provider = _get(meta, "provider")
    if not _strict_equal(meta_provider, expected_provider):
        return _configuration_mismatch(
            "provider",
            MEMORY_INDEX_PROVIDER_CHANGED_TEMPLATE.format(
                meta_provider=_template(meta_provider), expected_provider=expected_provider
            ),
        )
    meta_provider_key = _get(meta, "providerKey")
    if (
        expected_model is not UNDEFINED
        and provider_key_known is not False
        and not any(
            _strict_equal(identity["providerKey"], meta_provider_key) for identity in matching
        )
    ):
        return _configuration_mismatch(
            "provider_settings", MEMORY_INDEX_PROVIDER_SETTINGS_CHANGED_REASON
        )
    content_identity = _content_scope_identity_state(meta, **content_scope)
    if content_identity["status"] != "valid":
        return content_identity
    if vector_ready and has_indexed_chunks is not False and _falsy(_get(meta, "vectorDims")):
        return _configuration_mismatch("vector_dims", MEMORY_INDEX_VECTOR_DIMS_MISSING_REASON)
    return {"status": "valid"}


def _index_identity_record(status: Mapping[str, Any]) -> Mapping[str, Any] | None:
    # asNullableRecord(status.custom?.indexIdentity).
    custom = status.get("custom")
    identity = custom.get("indexIdentity") if isinstance(custom, Mapping) else None
    return identity if isinstance(identity, Mapping) else None


def _trimmed_reason(identity: Mapping[str, Any] | None) -> str:
    reason = identity.get("reason") if identity is not None else None
    return js_trim(reason) if isinstance(reason, str) else ""


def resolve_memory_index_identity_reason(status: Mapping[str, Any]) -> str | None:
    """``resolveMemoryIndexIdentityReason`` (types.ts:239-248): the trimmed reason of a missing or
    mismatched identity, the default reason when it is blank, else ``None``."""
    identity = _index_identity_record(status)
    if identity is None or identity.get("status") not in ("mismatched", "missing"):
        return None
    return _trimmed_reason(identity) or MEMORY_INDEX_IDENTITY_DEFAULT_REASON


def resolve_memory_index_identity_diagnostic(status: Mapping[str, Any]) -> dict[str, Any] | None:
    """``resolveMemoryIndexIdentityDiagnostic`` (types.ts:250-298): the identity as a diagnostic
    when it is a known missing/mismatched shape with a reason, else ``None``."""
    identity = _index_identity_record(status)
    reason = _trimmed_reason(identity)
    if identity is None or not reason:
        return None
    code, owner = identity.get("code"), identity.get("owner")
    if (
        identity.get("status") == "missing"
        and code == METADATA_MISSING_CODE
        and owner == OPENCLAW_OWNER
    ):
        return {"status": "missing", "reason": reason, "code": code, "owner": owner}
    if identity.get("status") != "mismatched":
        return None
    if owner == OPENCLAW_OWNER and code in MEMORY_INDEX_OPENCLAW_CODES:
        diagnostic: dict[str, Any] = {
            "status": "mismatched",
            "reason": reason,
            "code": code,
            "owner": owner,
        }
        if (
            code == "chunking_version"
            and identity.get("chunkingVersionOnly") is True
            and identity.get("versionOrder") != "newer"
        ):
            diagnostic["chunkingVersionOnly"] = True
        return diagnostic
    if owner == CONFIGURATION_OWNER and code in MEMORY_INDEX_CONFIGURATION_CODES:
        return {"status": "mismatched", "reason": reason, "code": code, "owner": owner}
    return None


def format_memory_index_rebuild_guidance(
    status: Mapping[str, Any],
    agent_id: str | None = None,
    *,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    """``formatMemoryIndexRebuildGuidance`` (types.ts:300-311): the rebuild command and whether
    it calls an embedding provider (``requestedProvider``, else ``provider``, is ``none``).

    The command names the runtime (``runtime_identity``; decision D4): upstream's CLI with
    ``--agent``, or memory-core's ``SQLiteMemoryStore.reindex(workspace)``.
    """
    agent = js_trim(agent_id) if isinstance(agent_id, str) else ""
    command = runtime_identity.memory_index_rebuild_command_template.format(
        agent_suffix=(
            runtime_identity.memory_index_rebuild_agent_clause.format(agent_id=agent)
            if agent
            else ""
        )
    )
    requested = status.get("requestedProvider")
    provider = status.get("provider")
    configured = (js_trim(requested) if isinstance(requested, str) else "") or (
        js_trim(provider) if isinstance(provider, str) else ""
    )
    disclosure = (
        MEMORY_INDEX_REBUILD_KEYWORD_ONLY_DISCLOSURE
        if configured == NO_PROVIDER_ID
        else MEMORY_INDEX_REBUILD_PROVIDER_COST_DISCLOSURE
    )
    return MEMORY_INDEX_REBUILD_GUIDANCE_TEMPLATE.format(command=command, disclosure=disclosure)


def resolve_memory_index_search_diagnostic(
    diagnostic: Mapping[str, Any],
    status: Mapping[str, Any],
    agent_id: str | None = None,
    *,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any]:
    """``resolveMemoryIndexSearchDiagnostic`` (types.ts:313-360) without its repair-failure branch
    (no ``lastSyncError`` in memory-core): the paused ``error``/``warning``/``action`` and the
    ``staleness`` of a keyword-only search."""
    reason = diagnostic["reason"]
    identity = _index_identity_record(status)
    newer_index = (
        diagnostic.get("owner") == OPENCLAW_OWNER
        and diagnostic.get("status") == "mismatched"
        and identity is not None
        and identity.get("versionOrder") == "newer"
    )
    if diagnostic.get("owner") == CONFIGURATION_OWNER:
        cause = MEMORY_INDEX_CONFIGURATION_CAUSE_TEMPLATE.format(reason=reason)
    elif diagnostic.get("code") == METADATA_MISSING_CODE:
        cause = MEMORY_INDEX_METADATA_MISSING_CAUSE_TEMPLATE.format(reason=reason)
    elif newer_index:
        cause = reason
    else:
        cause = runtime_identity.memory_index_version_changed_cause_template.format(reason=reason)
    guidance = format_memory_index_rebuild_guidance(
        status, agent_id, runtime_identity=runtime_identity
    )
    owner_label = (
        runtime_identity.memory_index_owner_label
        if diagnostic.get("owner") == OPENCLAW_OWNER
        else diagnostic.get("owner")
    )
    return {
        "error": reason,
        "warning": MEMORY_INDEX_PAUSED_WARNING_TEMPLATE.format(cause=cause, prior_failure=""),
        "action": (
            runtime_identity.memory_index_newer_action_template.format(guidance=guidance)
            if newer_index
            else MEMORY_INDEX_REBUILD_ACTION_TEMPLATE.format(guidance=guidance)
        ),
        "staleness": {
            "stale": True,
            "warning": MEMORY_INDEX_STALE_WARNING_TEMPLATE.format(
                reason=reason,
                owner=owner_label,
                code=diagnostic.get("code"),
                prior_failure="",
            ),
            "action": (
                runtime_identity.memory_index_stale_newer_action_template.format(
                    guidance=guidance
                )
                if newer_index
                else MEMORY_INDEX_STALE_REBUILD_ACTION_TEMPLATE.format(guidance=guidance)
            ),
        },
    }


def resolve_memory_search_staleness(
    status: Mapping[str, Any],
    agent_id: str | None = None,
    *,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any] | None:
    """``resolveMemorySearchStaleness`` (types.ts:362-380) without the ``lastSyncError`` branch:
    the staleness of an identity diagnostic, else ``None``."""
    diagnostic = resolve_memory_index_identity_diagnostic(status)
    if diagnostic is None:
        return None
    return resolve_memory_index_search_diagnostic(
        diagnostic, status, agent_id, runtime_identity=runtime_identity
    )["staleness"]


def is_chunking_upgrade_keyword_only(diagnostic: Mapping[str, Any] | None) -> bool:
    """A pending chunking upgrade on an otherwise matching index (memory-search-tool-query.ts:
    214-219 without the FTS check): search keyword-only instead of pausing."""
    return (
        diagnostic is not None
        and diagnostic.get("status") == "mismatched"
        and diagnostic.get("owner") == OPENCLAW_OWNER
        and diagnostic.get("code") == "chunking_version"
        and diagnostic.get("chunkingVersionOnly") is True
    )


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
