"""Separate pristine-owner authority for zero-credit cold retry development.

Earlier declaration bytes supply source provenance only. No older profile,
behavioral capture, registration or acceptance credit is inherited.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.index_identity_boundaries_bindings import _merged_anchors
from equivalence.query_sync_cold_retry import OPERATION
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


class QuerySyncColdRetryBindingError(ValueError):
    """The frozen development caller lost an original owner or release artifact."""


def prepare_query_sync_cold_retry_bindings(checkout: Path, runtime_root: Path) -> dict:
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
        raise QuerySyncColdRetryBindingError("Cold retry source/release authority is not authentic") from error
    return {
        **inherited,
        "kind": "official-release-query-sync-cold-retry-owner",
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
            "Two independently frozen zero-credit schedules call the original public memory_search "
            "twice on the exact facade-acquired default owner. Only the refusal case arms a genuine "
            "owned dangling reindex-sidecar symlink after acquisition. The first whole public call "
            "returns before the fixture removes only its fault and immediately calls the second "
            "query. No manual sync, reopen, private wait, source mutation or timer drain is supplied. "
            "Original caught bootstrap errors remain genuine custody; actual complete public "
            "envelopes determine the observed result. Original close owns admitted work."
        ),
        "limits": [
            "This standalone development packet awards zero and is not in the acceptance catalog.",
            "Earlier bindings supply byte authority only; no earlier behavioral evidence is reused.",
            "Source and official compiled authorities remain separate; no source build is reproduced.",
            "The owned filesystem refusal is not an exception/backend/result replacement.",
            "Shared query/bootstrap counts do not claim internal worker, task, SQL or raw API identity.",
            "Provider-none cold retry does not establish the complete query-sync boundary condition.",
        ],
    }
