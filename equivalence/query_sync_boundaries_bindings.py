"""Separate pristine-owner authority for zero-credit query-sync boundaries development.

Earlier declaration bytes supply source provenance only. No older profile,
behavioral capture, registration or acceptance credit is inherited.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.index_identity_boundaries_bindings import _merged_anchors
from equivalence.query_sync_boundaries import OPERATION
from equivalence.query_sync_outcomes_bindings import (
    COMPILED_ANCHORS as OUTCOME_COMPILED_ANCHORS,
    COMPILED_HASHES,
    REQUIRED_LOADED_ARTIFACTS,
    REQUIRED_MAIN_ARTIFACTS,
    REQUIRED_WORKER_ARTIFACTS,
    SOURCE_ANCHORS as OUTCOME_SOURCE_ANCHORS,
    SOURCE_HASHES as OUTCOME_SOURCE_HASHES,
    prepare_query_sync_outcomes_bindings,
)
from equivalence.reference_bindings import ReferenceBindingError
from equivalence.reuse_bindings import ReuseBindingError, _named
from equivalence.search_contract_runtime_bindings import _owners

SOURCE_HASHES = {
    **OUTCOME_SOURCE_HASHES,
    "extensions/memory-core/src/memory/manager-reindex-lock.ts":
        "3ad6e120af56a740d278eda3b5fc4cb2b83509bccd3f12591c413de626870ad1",
}
SOURCE_ANCHORS = _merged_anchors(OUTCOME_SOURCE_ANCHORS, {
    "extensions/memory-core/src/memory/manager-reindex-lock.ts": (
        "export async function waitForMemoryReindexLock(",
        '  const lockPath = `${dbPath}.reindex-lock.sqlite`;',
        "    return await acquireMemorySqliteWriterLease(lockPath, timeout);",
    ),
    "extensions/memory-core/src/memory/manager.ts": (
        "        const lock = await waitForMemoryReindexLock(dbPath, { waitForActive: true });",
    ),
    "extensions/memory-core/src/memory/manager-search-orchestration.ts": (
        '            { reason: "search-bootstrap" },',
        '          log.warn(`memory sync failed (search-bootstrap): ${String(err)}`);',
    ),
})
COMPILED_ANCHORS = _merged_anchors(OUTCOME_COMPILED_ANCHORS, {
    "dist/manager-vector-warning-DcyxxT5h.mjs": (
        "async function waitForMemoryReindexLock(dbPath, options = {}) {",
        '\tconst lockPath = `${dbPath}.reindex-lock.sqlite`;',
        "\t\treturn await acquireMemorySqliteWriterLease(lockPath, timeout);",
    ),
    "dist/extensions/memory-core/manager-runtime.js": (
        '\t\t\t\t\tawait this.syncAdmitted({ reason: "search-bootstrap" }, { allowEmbeddingBootstrapFallback: true });',
        '\t\t\t\t\t} else log$1.warn(`memory sync failed (search-bootstrap): ${String(err)}`);',
        "\t\t\t\tconst lock = await waitForMemoryReindexLock(dbPath, { waitForActive: true });",
    ),
})


class QuerySyncBoundariesBindingError(ValueError):
    """The frozen development caller lost an original owner or release artifact."""


def prepare_query_sync_boundaries_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate declarations only; execute no manager, tool, worker or host."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    inherited = prepare_query_sync_outcomes_bindings(checkout, runtime_root)
    try:
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        memory = "extensions/memory-core/src/memory/"
        links = [
            *inherited["sourceImportLinks"],
            _named(sources, memory + "manager.ts", "./manager-reindex-lock.js",
                   ("waitForMemoryReindexLock",), kind="import", exact=True),
            _named(sources, memory + "manager-reindex-lock.ts", "./manager-sqlite-lease.js",
                   ("acquireMemorySqliteWriterLease",), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError) as error:
        raise QuerySyncBoundariesBindingError("Query-sync boundaries source/release authority is not authentic") from error
    return {
        **inherited,
        "kind": "official-release-query-sync-boundaries-owner",
        "acceptancePointsAwarded": 0,
        "registeredAcceptanceCatalogChanged": False,
        "sourceBindings": source_evidence,
        "sourceImportLinks": links,
        "compiledBindings": compiled_evidence,
        "requiredLoadedArtifactsByProfile": {OPERATION: list(REQUIRED_LOADED_ARTIFACTS)},
        "workerRequiredByProfile": {OPERATION: True},
        "requiredMainArtifacts": list(REQUIRED_MAIN_ARTIFACTS),
        "requiredWorkerArtifacts": list(REQUIRED_WORKER_ARTIFACTS),
        "fixtureBoundary": (
            "Independently frozen ordered steps invoke original default-manager/public-tool APIs. "
            "Only declared real SQLite sidecar leases, owned filesystem refusals, actual source "
            "mutations and original revision-rival operations control lifecycle boundaries. "
            "Original sync requests, admitted whole jobs, later runSync stages, publication "
            "commands and complete tool results remain separate custody. A joined request is "
            "not another whole producer. All genuine errors and original close settlements "
            "remain retained; there are no fake exceptions, timer drains or replacement results."
        ),
        "limits": [
            "Declaration authentication and standalone execution award zero; full-family acceptance is separate.",
            "Earlier bindings supply byte authority only; no earlier behavioral evidence is reused.",
            "Source and official compiled authorities remain separate; no source build is reproduced.",
            "The owned filesystem refusal is not an exception/backend/result replacement.",
            "Shared query/bootstrap counts do not claim internal worker, task, SQL or raw API identity.",
            "A five-case subset cannot establish the full boundary condition; typed retry and newer-publication policy require their own exact members.",
        ],
    }
