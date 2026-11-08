"""Separate pinned source and official artifact identities for stored ranking.

The runtime fixture constructs the genuine provider-none manager, publishes its
index and calls public search. These authenticated identities do not reproduce
the publisher's source build or establish every manager/host lifecycle contract.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _named


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_KEYWORD = "extensions/memory-core/src/memory/manager-keyword-retrieval.ts"
_ORCHESTRATION = "extensions/memory-core/src/memory/manager-search-orchestration.ts"
_MANAGER = "extensions/memory-core/src/memory/manager.ts"
_RUNTIME = "extensions/memory-core/src/memory/manager-runtime.ts"
_PREPARATION = "extensions/memory-core/src/memory/manager-index-preparation.ts"
_RETRIEVAL = "extensions/memory-core/src/memory/manager-retrieval-read.ts"
_RECALL = "packages/memory-host-sdk/src/host/memory-recall-metadata.ts"
_ANNOTATIONS = "packages/memory-host-sdk/src/host/curated-annotations.ts"
_IMPORTANCE = "extensions/memory-core/src/memory/importance.ts"
_PROJECT = "extensions/memory-core/src/memory/project-ranking.ts"
_COMPILED = "dist/extensions/memory-core/manager-runtime.js"
_COMPILED_PREPARATION = "dist/manager-index-preparation-wXpJtJiU.mjs"
_COMPILED_RETRIEVAL = "dist/manager-search-DgMs3pkc.mjs"
_COMPILED_RECALL = "dist/engine-storage-CaNoPYwo.mjs"
SOURCE_HASHES = {
    _KEYWORD: "fd754dd63c7c31bc892a36cd300b3107369c46d554abb12e50cf085374123458",
    _ORCHESTRATION: "04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55",
    _MANAGER: "c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173",
    _RUNTIME: "0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b",
    _PREPARATION: "208e5c367e6f5dd79f1837050404fe67a9f05ac8fa5e5ad1860c12f4a259e041",
    _RETRIEVAL: "48076bc9ad42b4ba20daa0583f8a1160eaafa9b3ab575b8542666b2c80765f16",
    _RECALL: "37b70200001e49baa0dc489189223ce0e9bf034296926c0ce562139cea8d791d",
    _ANNOTATIONS: "c4bd75fe3476f54508b42623e1f09190816f49e319703375865b9564fe4e7f5d",
    _IMPORTANCE: "b77099a96a50dc07d53d59094bb35fd2230d65ac33d3b1877debb65e7c7e0246",
    _PROJECT: "cb08173e8e35c51cf61dc1323099c252f798cf471aece3c036823c875eb94647",
}
COMPILED_HASHES = {
    _COMPILED: "6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e",
    _COMPILED_PREPARATION: "6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867",
    _COMPILED_RETRIEVAL: "f97d896dac1037bc8aa96b3b8631cb3efba3ee361f4a8c02039bebc18f6184a0",
    _COMPILED_RECALL: "7b897860ea765aaf9fff7fe5ab34058ac8336dfa04ba67d6da2cc879c3b263f8",
}
SOURCE_ANCHORS = {
    _KEYWORD: (
        "export abstract class MemoryKeywordRetrieval extends MemoryProviderLifecycle {",
        "  protected async finalizeKeywordOnlyResults(params: {",
        "  protected async attachRecallMetadata<T extends MemoryRetrievalResult & { id: string }>(",
    ),
    _ORCHESTRATION: (
        "export abstract class MemorySearchOrchestration extends MemoryKeywordRetrieval {",
        "  async search(query: string, opts?: MemoryIndexSearchOptions): Promise<MemorySearchResult[]> {",
    ),
    _MANAGER: (
        "export class MemoryIndexManager extends MemorySearchOrchestration implements MemorySearchManager {",
        "  static async get(params: {", "  async sync(params?: MemorySyncParams): Promise<void> {",
        "  async close(): Promise<void> {",
    ),
    _RUNTIME: ("export { MemoryIndexManager };",),
    _PREPARATION: ("export function prepareMemoryIndexChunks({",),
    _RETRIEVAL: ("export function readMemoryRecallData(db: DatabaseSync, request: MemoryRecallQuery) {",),
    _RECALL: ("export function readMemoryRecallMetadata(db: DatabaseSync, ids: readonly string[]) {",),
    _ANNOTATIONS: ("export function extractCuratedEntryRecallMetadata(params: {",),
    _IMPORTANCE: ("export function applyImportanceMultiplier<T extends { score: number; importance?: number }>(",),
    _PROJECT: ("export function applyProjectRanking<T extends ProjectRankable>(",),
}
COMPILED_ANCHORS = {
    _COMPILED: (
        "var MemoryKeywordRetrieval = class extends MemoryProviderLifecycle {",
        "\tasync finalizeKeywordOnlyResults(params) {",
        "\tasync attachRecallMetadata(results, signal, sourceFilterList) {",
        "var MemorySearchOrchestration = class extends MemoryKeywordRetrieval {",
        "\tasync search(query, opts) {", "\tstatic async get(params) {", "\tasync sync(params) {",
        "var MemoryIndexManager = class MemoryIndexManager extends MemorySearchOrchestration {",
        "function applyImportanceMultiplier(results) {",
        "function applyProjectRanking(results, activeProjectKeys) {",
        "export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };",
    ),
    _COMPILED_PREPARATION: (
        "function prepareMemoryIndexChunks({ entry, source, content, pathClassification, chunking, cutoffLine, provider, hardMaxInputTokens }) {",
        "export { resolveChunkProvenance as n, prepareMemoryIndexChunks as t };",
    ),
    _COMPILED_RETRIEVAL: ("function readMemoryRecallData(db, request) {",),
    _COMPILED_RECALL: ("function readMemoryRecallMetadata(db, ids) {",),
}


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources: dict[str, str] = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError("An importance/project owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise ValueError("An importance/project owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise ValueError("An importance/project owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def prepare_importance_project_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate declared public APIs and separately reviewed published artifacts."""
    checkout = Path(checkout).resolve()
    runtime_root = Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Importance/project runtime evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        chain = [
            _named(sources, _ORCHESTRATION, "./manager-keyword-retrieval.js",
                   ("MemoryKeywordRetrieval",), kind="import", exact=True),
            _named(sources, _MANAGER, "./manager-search-orchestration.js",
                   ("MemorySearchOrchestration",), kind="import", exact=True),
            _named(sources, _RUNTIME, "./manager.js",
                   ("getMemoryIndexManagerRegistry", "MemoryIndexManager"), kind="import", exact=True),
            _named(sources, _KEYWORD, "./manager-retrieval-read.js",
                   ("readMemoryRecallData",), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Importance/project runtime provenance could not be verified.") from error
    return {
        "kind": "official-release-importance-project-owner", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False,
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceClassLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoint": {"path": _COMPILED, "export": "MemoryIndexManager",
                       "methods": ["get", "sync", "search", "close"]},
        "requiredLoadedArtifacts": list(COMPILED_HASHES),
        "fixtureBoundary": "The provider-none runtime uses actual public manager get/sync/search/close "
                           "and observes published recall metadata. Only declared annotation/ranking "
                           "cases are exercised; other manager and host lifecycle contracts remain open.",
    }
