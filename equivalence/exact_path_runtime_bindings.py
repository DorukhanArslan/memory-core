"""Separate pinned source and official artifact identities for exact-path methods.

The release fixture invokes inherited keyword merge/limit methods through an
unconstructed ``MemoryIndexManager`` prototype. Authentication of those bytes
does not attest a reproduced source build or manager lifecycle execution.
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
_COMPILED = "dist/extensions/memory-core/manager-runtime.js"
SOURCE_HASHES = {
    _KEYWORD: "fd754dd63c7c31bc892a36cd300b3107369c46d554abb12e50cf085374123458",
    _ORCHESTRATION: "04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55",
    _MANAGER: "c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173",
    _RUNTIME: "0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b",
}
COMPILED_HASHES = {
    _COMPILED: "6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e",
}
SOURCE_ANCHORS = {
    _KEYWORD: (
        "export abstract class MemoryKeywordRetrieval extends MemoryProviderLifecycle {",
        "  private mergeKeywordSearchHits(\n",
        "  private limitKeywordSearchHits(\n",
    ),
    _ORCHESTRATION: (
        "export abstract class MemorySearchOrchestration extends MemoryKeywordRetrieval {",
    ),
    _MANAGER: (
        "export class MemoryIndexManager extends MemorySearchOrchestration implements MemorySearchManager {",
    ),
    _RUNTIME: ("export { MemoryIndexManager };",),
}
COMPILED_ANCHORS = {
    _COMPILED: (
        "var MemoryKeywordRetrieval = class extends MemoryProviderLifecycle {",
        "\tmergeKeywordSearchHits(resultSets, exactPathQuery) {",
        "\tlimitKeywordSearchHits(results, nonExactLimit) {",
        "var MemorySearchOrchestration = class extends MemoryKeywordRetrieval {",
        "var MemoryIndexManager = class MemoryIndexManager extends MemorySearchOrchestration {",
        "export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };",
    ),
}


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources: dict[str, str] = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError("An exact-path owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise ValueError("An exact-path owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise ValueError("An exact-path owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def prepare_exact_path_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate original declarations and the separately reviewed release export."""
    checkout = Path(checkout).resolve()
    runtime_root = Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Exact-path runtime evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(
            runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False,
        )
        chain = [
            _named(sources, _ORCHESTRATION, "./manager-keyword-retrieval.js",
                   ("MemoryKeywordRetrieval",), kind="import", exact=True),
            _named(sources, _MANAGER, "./manager-search-orchestration.js",
                   ("MemorySearchOrchestration",), kind="import", exact=True),
            _named(sources, _RUNTIME, "./manager.js",
                   ("getMemoryIndexManagerRegistry", "MemoryIndexManager"), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Exact-path runtime provenance could not be verified.") from error
    return {
        "kind": "official-release-exact-path-method-owner", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": True,
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceClassLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoint": {"path": _COMPILED, "export": "MemoryIndexManager",
                       "owner": "MemoryKeywordRetrieval",
                       "methods": ["mergeKeywordSearchHits", "limitKeywordSearchHits"]},
        "fixtureBoundary": "Object.create(MemoryIndexManager.prototype) invokes unchanged inherited "
                           "keyword merge/limit methods; constructor, provider and full manager "
                           "lifecycle execution are not verified.",
    }
