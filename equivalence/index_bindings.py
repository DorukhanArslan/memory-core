"""Verify original source bindings used by native index lifecycle comparisons.

Package specifiers resolve to the complete original SDK facades. Publication,
schema and transaction implementations remain in their tracked source files;
this module supplies no replacement runtime behavior or partial facade bridges.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
import re
from typing import Mapping

from equivalence.reference_bindings import ReferenceBindingError, _edge, _git


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_TAG = "v2026.9.9"
_PUBLICATION = "extensions/memory-core/src/memory/manager-db-kernel.ts"
_VECTOR_STATE = "extensions/memory-core/src/memory/manager-vector-rebuild-state.ts"
_SCHEMA_SPECIFIER = "openclaw/plugin-sdk/memory-core-host-engine-schema"
_SQL_SPECIFIER = "openclaw/plugin-sdk/sqlite-worker-runtime"
_SCHEMA_FACADE = "src/plugin-sdk/memory-core-host-engine-schema.ts"
_SQL_FACADE = "src/plugin-sdk/sqlite-worker-runtime.ts"
_SCHEMA = "packages/memory-host-sdk/src/host/memory-schema.ts"
_TRANSACTION = "src/infra/sqlite-transaction.ts"
_FTS = "packages/memory-host-sdk/src/host/memory-schema-fts.ts"
_PROVENANCE = "packages/memory-host-sdk/src/host/memory-schema-provenance.ts"
_RECALL = "packages/memory-host-sdk/src/host/memory-schema-recall.ts"
_BASE = "packages/memory-host-sdk/src/host/memory-schema-base.ts"
_SOURCE_KERNEL = "extensions/memory-core/src/memory/manager-source-index-kernel.ts"
_CHUNK_WRITER = "extensions/memory-core/src/memory/manager-chunk-writer.ts"
_INDEX_FACADE = "src/plugin-sdk/memory-core-host-engine-indexing.ts"
_HASH = "packages/memory-host-sdk/src/host/hash.ts"
_CODEC = "packages/memory-host-sdk/src/host/embedding-vector.ts"
_QUERIES = "src/infra/kysely-sync.ts"
_INDEX_SPECIFIER = "openclaw/plugin-sdk/memory-core-host-engine-indexing"
_PUBLICATION_SCHEMA_NAMES = (
    "dropMemoryChunkFtsTriggers", "dropMemoryPathFtsTriggers", "ensureMemoryChunkFtsTriggers",
    "ensureMemoryChunkProvenance", "ensureMemoryRecallMetadataSchema", "ensureMemoryPathFtsTriggers",
    "MEMORY_INDEX_CHUNK_RECALL_METADATA_TABLE", "MEMORY_INDEX_PATHS_FTS_TABLE",
    "MEMORY_INDEX_FTS_TABLE", "rebuildMemoryChunkFts",
)
_SCHEMA_OWNERS = {
    **dict.fromkeys(("dropMemoryChunkFtsTriggers", "dropMemoryPathFtsTriggers",
                     "ensureMemoryChunkFtsTriggers", "ensureMemoryPathFtsTriggers",
                     "MEMORY_INDEX_PATHS_FTS_TABLE", "MEMORY_INDEX_FTS_TABLE",
                     "rebuildMemoryChunkFts"), _FTS),
    "ensureMemoryChunkProvenance": _PROVENANCE,
    "ensureMemoryRecallMetadataSchema": _RECALL,
    "MEMORY_INDEX_CHUNK_RECALL_METADATA_TABLE": _RECALL,
    "MEMORY_INDEX_META_TABLE": _BASE,
    "MEMORY_INDEX_VECTOR_TABLE": _BASE,
}
_KERNEL_SOURCE_SHA256 = {
    _SOURCE_KERNEL: "b0bf466a54ee67705f5b7327a31c0013e9ee44a57117181ca5860c5ef90e30b5",
    _CHUNK_WRITER: "623dc154a82424dbafac73dd1110c5031bb62bde0b54ad275e264fa38a53db9a",
    _INDEX_FACADE: "d539b55f81454443f3b3589e1711c04787941a18782c84c0b3422425be9de472",
    _HASH: "face88c71f4d752c24052ab299771ddf55c1c54d76ed2ebac8618a7812818683",
    _CODEC: "515e3d73f9e6adff455f6f3db477d253fac0a10e44b53179d47683d101068de9",
    _QUERIES: "b00ef2f4a7e5fd229fab29c43729a6ebdce6d9900ddd3c856178f3ecc5d834d7",
}
_SOURCE_SHA256 = {
    _PUBLICATION: "4973db0580dc6dd7ac032a983efffa79ccb14fc4206f046b94c4250c7b5597ca",
    _VECTOR_STATE: "8d9747d21497c0e088bec425a76d85dfe33774cd2e2ae24b45cdca5e3a11154e",
    _SCHEMA_FACADE: "d77d309d557d14d2b9206ac5aa4635dc4275984ac165a6640297ab7ffcab6ac9",
    _SQL_FACADE: "2f9bde0d0996f51dd60017f5131f86c1fcae26dcb287e81e0e7301a30a61cebd",
    _SCHEMA: "4c7bc3e66b22298f21fc43e0a7f002f9cd64825e70c395f45135cfee1973f57d",
    _FTS: "775bd0eaa40f455ffd2ae6388841ecb8d6be4f610ffcd798b45e3f9e29766ffb",
    _PROVENANCE: "d4bc55183dea446802e39cff24e11027e0c0418f02dde337ca586a413e4578c6",
    _RECALL: "960ea0630fca3829a3710e4e0ce7ad6cb916134101c90bbe9cbf0f0e251ae0a9",
    _BASE: "e662a672cad79e2ba0ee36ae71bfc78bd7f84255d9a20498fb868445408014e8",
    _TRANSACTION: "7b4caf5b30e1eb6626ffce2ae90583fa979c8289fdd0128ce29acc00448f253f",
}


class IndexBindingError(ValueError):
    """Native source provenance is missing, modified or ambiguous."""


def _declaration(sources: Mapping[str, str], module: str, name: str) -> dict:
    pattern = rf"(?m)^export\s+(?:async\s+)?(?:function|class|const|let|var)\s+{re.escape(name)}\b"
    matches = list(re.finditer(pattern, sources[module]))
    if len(matches) != 1:
        raise IndexBindingError("A native index binding has no unique original declaration.")
    anchor = matches[0][0]
    return {"path": module, "kind": "declaration", "binding": name, "anchor": anchor,
            "line": sources[module][:matches[0].start()].count("\n") + 1}


def _schema_projection(sources: Mapping[str, str], parent: str,
                       names: tuple[str, ...]) -> dict:
    chain = [
        _edge(sources, parent, _SCHEMA_SPECIFIER, names, kind="import"),
        _edge(sources, _SCHEMA_FACADE,
              "../../packages/memory-host-sdk/src/host/memory-schema.js", names),
    ]
    owners = dict.fromkeys(_SCHEMA_OWNERS[name] for name in names)
    for owner in owners:
        bindings = tuple(name for name in names if _SCHEMA_OWNERS[name] == owner)
        chain.append(_edge(sources, _SCHEMA, f"./{Path(owner).stem}.js", bindings))
        chain.extend(_declaration(sources, owner, name) for name in bindings)
    return {"resolution": {"parent": parent, "specifier": _SCHEMA_SPECIFIER,
                           "target": _SCHEMA_FACADE, "bindings": list(names)}, "chain": chain}


def _trace_index_projections(sources: Mapping[str, str], *, include_source_kernel: bool = False) -> list[dict]:
    """Verify the exact reviewed named-import/reexport syntax at this release."""
    try:
        result = [_schema_projection(sources, _PUBLICATION, _PUBLICATION_SCHEMA_NAMES)]
        transaction_names = ("runSqliteImmediateTransactionSync",)
        result.append({
            "resolution": {"parent": _PUBLICATION, "specifier": _SQL_SPECIFIER,
                           "target": _SQL_FACADE, "bindings": list(transaction_names)},
            "chain": [
                _edge(sources, _PUBLICATION, _SQL_SPECIFIER, transaction_names, kind="import"),
                _edge(sources, _SQL_FACADE, "../infra/sqlite-transaction.js", transaction_names),
                _declaration(sources, _TRANSACTION, transaction_names[0]),
            ],
        })
        result.append(_schema_projection(sources, _VECTOR_STATE, ("MEMORY_INDEX_META_TABLE",)))
        if include_source_kernel:
            for parent, names in ((_SOURCE_KERNEL, ("hashText",)),
                                  (_CHUNK_WRITER, ("encodeMemoryEmbedding",))):
                owner = _HASH if names == ("hashText",) else _CODEC
                chain = [
                    _edge(sources, parent, _INDEX_SPECIFIER, names, kind="import"),
                    _edge(sources, _INDEX_FACADE, f"../../{owner[:-3]}.js", names),
                    _declaration(sources, owner, names[0]),
                ]
                result.append({"resolution": {"parent": parent, "specifier": _INDEX_SPECIFIER,
                                               "target": _INDEX_FACADE, "bindings": list(names)},
                               "chain": chain})
            result.append(_schema_projection(sources, _SOURCE_KERNEL, ("MEMORY_INDEX_VECTOR_TABLE",)))
            for parent, names in (
                (_SOURCE_KERNEL, ("executeSqliteQuerySync", "executeSqliteQueryTakeFirstSync",
                                  "getNodeSqliteKysely", "runSqliteImmediateTransactionSync")),
                (_CHUNK_WRITER, ("compileSqliteQueryBindings", "getNodeSqliteKysely")),
            ):
                chain = [_edge(sources, parent, _SQL_SPECIFIER, names, kind="import")]
                for owner in (_QUERIES, _TRANSACTION):
                    selected = tuple(name for name in names
                                     if (name == "runSqliteImmediateTransactionSync") == (owner == _TRANSACTION))
                    if selected:
                        chain.append(_edge(sources, _SQL_FACADE, f"../infra/{Path(owner).stem}.js", selected))
                        chain.extend(_declaration(sources, owner, name) for name in selected)
                result.append({"resolution": {"parent": parent, "specifier": _SQL_SPECIFIER,
                                               "target": _SQL_FACADE, "bindings": list(names)},
                               "chain": chain})
    except (ReferenceBindingError, KeyError) as error:
        raise IndexBindingError("A native index import is not an unchanged direct named binding.") from error
    return result


def prepare_index_bindings(checkout: Path, *, include_source_kernel: bool = False) -> dict:
    """Return exact-parent aliases plus their complete pinned export provenance.

    Append the returned allowlist/evidence to the regular source oracle config.
    Complete original facade initialization is preserved. Actual runtime source
    traces, rather than this allowlist alone, attest which facades were loaded.
    """
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve()
                != checkout):
            raise IndexBindingError("Native index bindings require the exact pinned checkout.")
        if _git(checkout, "status", "--porcelain", "--untracked-files=no").strip():
            raise IndexBindingError("Native index bindings require unmodified tracked source.")
        sources = {}
        expected_sources = {**_SOURCE_SHA256,
                            **(_KERNEL_SOURCE_SHA256 if include_source_kernel else {})}
        for relative, expected in expected_sources.items():
            path = checkout / relative
            if path.is_symlink() or not path.resolve().is_relative_to(checkout):
                raise IndexBindingError("A native index binding source escaped its checkout.")
            raw = path.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != expected
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != expected):
                raise IndexBindingError("A native index binding source differs from the reviewed release.")
            sources[relative] = raw.decode("utf-8")
    except (OSError, UnicodeError, ReferenceBindingError):
        raise IndexBindingError("Native index binding source evidence is unavailable.") from None
    resolutions, evidence = [], []
    for item in _trace_index_projections(sources, include_source_kernel=include_source_kernel):
        resolution, chain = item["resolution"], item["chain"]
        paths = {entry["path"] for entry in chain}
        resolutions.append(resolution)
        evidence.append({
            **resolution, "scope": ("native-source-index" if resolution["parent"]
                                     in {_SOURCE_KERNEL, _CHUNK_WRITER} else "native-index-publication"),
            "chain": chain,
            "sources": [{"path": path, "sha256": expected_sources[path]} for path in sorted(paths)],
            "facadeExecutionVerified": False, "fullManagerExecutionVerified": False,
            "facadeInitializationBypassed": False,
            "requiredFacadeSource": {"path": resolution["target"],
                                     "sha256": expected_sources[resolution["target"]]},
            "note": "The complete original SDK facade and original owner implementations remain "
                    "unchanged. Runtime source traces must attest facade execution; this import "
                    "allowlist alone does not verify full manager dispatch or behavior.",
        })
    return {"schemaVersion": 1, "kind": "native-index-bindings",
            "reference": {"tag": _TAG, "commit": _COMMIT},
            "allowedResolutions": resolutions, "projectionEvidence": evidence}


def attest_index_facades(config: dict, executed_sources: list[dict]) -> dict:
    """Attach execution evidence only after hashes identify loaded real facades."""
    actual = {source.get("path"): source.get("sha256") for source in executed_sources}
    result = deepcopy(config)
    for entry in result["projectionEvidence"]:
        required = entry["requiredFacadeSource"]
        if actual.get(required["path"]) != required["sha256"]:
            raise IndexBindingError("The source oracle did not execute a required original index facade.")
        entry["facadeExecutionVerified"] = True
    return result
