"""Pinned original apply owners and the already reviewed plugin-state backend.

Pinning supplies no execution evidence or acceptance credit. The first diagnostic
uses the original early return after its provenance read and workspace lease;
the promotion file lock and publication branches remain separate roles.
"""
import hashlib
from pathlib import Path
import stat

from equivalence import memory_budget_bindings as budget
from equivalence import promotion_ranking_bindings as ranking
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners


REFERENCE_COMMIT = ranking.REFERENCE_COMMIT
PROMOTION_APPLY_OPERATION = "promotion-apply-reconcile-runtime"
PROMOTION_WORKER_ROUTE = tuple(ranking.PROMOTION_WORKER_ROUTE)
REQUIRED_WORKER_ARTIFACTS = PROMOTION_WORKER_ROUTE


def _merged_anchors(*manifests):
    result = {}
    for manifest in manifests:
        for relative, anchors in manifest.items():
            result[relative] = tuple(dict.fromkeys((*result.get(relative, ()), *anchors)))
    return result


SOURCE_HASHES = {**budget.SOURCE_HASHES, **ranking.SOURCE_HASHES,
    "src/memory/memory-artifact-provenance.ts":
        "68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373",
    "src/plugin-sdk/memory-core-host-runtime-core.ts":
        "9d0fc4e1f1ec1f4c4a140a2a5b8cb63246c18091274cc8ffa51b5274b03a653b"}
SOURCE_ANCHORS = _merged_anchors(budget.SOURCE_ANCHORS, ranking.SOURCE_ANCHORS, {
    "src/memory/memory-artifact-provenance.ts": (
        'const MEMORY_ARTIFACT_PROVENANCE_OWNER_ID = "core:memory-artifact-provenance";',
        'const MEMORY_ARTIFACT_PROVENANCE_NAMESPACE = "workspace-files";',
        "export async function listMemoryArtifactProvenance(params:",
    ),
    "src/plugin-sdk/memory-core-host-runtime-core.ts": (
        '  listMemoryArtifactProvenance,',
    ),
    "extensions/memory-core/src/short-term-promotion-apply.ts": (
        "const dailyProvenanceEntries = await listMemoryArtifactProvenance({ workspaceDir });",
        "  if (rehydratedSelected.length === 0) {",
        "  const promotionLockTarget = await resolveMemoryPromotionLockTarget(workspaceDir);",
    ),
    "extensions/memory-core/src/memory-workspace-lock.ts": (
        "async function acquireMemoryWorkspaceLock(",
        "      if (!lockStore.observe || !lockStore.compareAndApply) {",
    ),
    "src/plugin-state/plugin-state-store.ts": (
        "export function createCorePluginStateKeyedStore<T>(",
    ),
})
COMPILED_HASHES = {**budget.COMPILED_HASHES, **ranking.COMPILED_HASHES,
    "dist/memory-artifact-provenance-DhnyWiV1.mjs":
        "d9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c"}
COMPILED_ANCHORS = _merged_anchors(budget.COMPILED_ANCHORS, ranking.COMPILED_ANCHORS, {
    "dist/short-term-promotion-MX1vHJuE.mjs": (
        'import { n as listMemoryArtifactProvenance } from "./memory-artifact-provenance-DhnyWiV1.mjs";',
        "if (rehydratedSelected.length === 0) return {",
    ),
    "dist/short-term-promotion-store-B6T388Bo.mjs": ("readStore as a", "writeStore as l"),
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": ("withMemoryWorkspaceLock as g",),
    "dist/memory-artifact-provenance-DhnyWiV1.mjs": (
        "async function listMemoryArtifactProvenance(params)",
        "listMemoryArtifactProvenance as n",
        'import { t as createCorePluginStateKeyedStore } from "./plugin-state-store-BPUaLoVD.mjs";',
    ),
    "dist/plugin-state-store-BPUaLoVD.mjs": (
        "function createCorePluginStateKeyedStore(options)",
        "createCorePluginStateKeyedStore as t",
    ),
    "dist/memory-host-events-C8-U38f1.mjs": ("readMemoryHostEventRecords as n",),
    "dist/file-lock-bsl71RWY.mjs": ("withFileLock as s",),
})

# The facade is pinned as the public factory address. A direct implementation
# import must not be reported as execution of this uncalled public barrel.
AUTHENTICATED_ONLY_ARTIFACTS = ("dist/plugin-sdk/plugin-state-store-runtime.js",)
REQUIRED_ARTIFACTS = {PROMOTION_APPLY_OPERATION: tuple(
    name for name in COMPILED_HASHES if name not in AUTHENTICATED_ONLY_ARTIFACTS)}
NATIVE_ARTIFACTS = dict(budget.NATIVE_ARTIFACTS)
SOURCE_ALIAS_PATH = "src/state/openclaw-state-worker-store.ts"
SOURCE_ALIAS_DECLARATION = (
    'import { getOpenClawStateWorkerOwner as owner } from "./openclaw-state-worker-owner.js";')

_PREFIX = "extensions/memory-core/src/"
SOURCE_LINKS = (
    (_PREFIX + "short-term-promotion-apply.ts", "./short-term-promotion-store.js", ("readStore", "writeStore"), "import"),
    (_PREFIX + "short-term-promotion-apply.ts", "./memory-workspace-lock.js", ("withMemoryWorkspaceLock",), "import"),
    (_PREFIX + "short-term-promotion-apply.ts", "openclaw/plugin-sdk/file-lock", ("withFileLock",), "import"),
    (_PREFIX + "short-term-promotion-apply.ts", "openclaw/plugin-sdk/memory-core-host-runtime-core", ("listMemoryArtifactProvenance",), "import"),
    (_PREFIX + "short-term-promotion-apply.ts", "./time.js", ("resolveMemoryCoreNowMs", "resolveMemoryCoreTimestamp"), "import"),
    (_PREFIX + "short-term-promotion-store.ts", "./dreaming-state.js", ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntry"), "import"),
    (_PREFIX + "memory-workspace-lock.ts", "./dreaming-state.js", ("SHORT_TERM_LOCK_NAMESPACE", "openMemoryCoreStateStore", "memoryCoreWorkspaceStateKey"), "import"),
    ("src/plugin-sdk/memory-core-host-runtime-core.ts", "../memory/memory-artifact-provenance.js", ("listMemoryArtifactProvenance",), "export"),
    ("src/memory/memory-artifact-provenance.ts", "../plugin-state/plugin-state-store.js", ("createCorePluginStateKeyedStore",), "import"),
    ("src/plugin-sdk/plugin-state-store-runtime.ts", "../plugin-state/plugin-state-store.js", ("createPluginStateKeyedStore",), "export"),
    ("src/plugin-state/plugin-state-store.ts", "./plugin-state-worker-client.js", ("registerPluginStateInWorker", "listPluginStateInKeyRangeInWorker"), "import"),
    ("src/state/openclaw-state-worker-owner.ts", "../infra/sqlite-worker-store.js", ("openSharedStateSqliteWorkerStore",), "import"),
    ("src/state/openclaw-state-worker-owner.ts", "../infra/runtime-process-url.js", ("resolveRuntimeProcessEntrypointUrl",), "import"),
    ("src/memory-host-sdk/events.ts", "./event-store.js", ("listStoredMemoryHostEvents",), "import"),
)


def _regular_owners(root, names):
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("Promotion apply requires canonical independent owner roots")
    for relative in names:
        filename = root / relative
        if (any(part.is_symlink() for part in (filename, *filename.parents) if part != root)
                or not filename.resolve().is_relative_to(root)):
            raise ValueError("A promotion apply owner escaped its reviewed tree")
        info = filename.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8 * 1024 * 1024:
            raise ValueError("Promotion apply owners require bounded independent regular files")


def prepare_promotion_apply_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate original bytes/aliases without running any native module."""
    checkout, runtime_root = Path(checkout).absolute(), Path(runtime_root).absolute()
    _regular_owners(checkout, SOURCE_HASHES)
    _regular_owners(runtime_root, COMPILED_HASHES)
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Promotion apply requires the exact unchanged pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    source_links = [_named_link(sources, module, specifier, names, kind=kind)
                    for module, specifier, names, kind in SOURCE_LINKS]
    native_evidence = []
    installation = runtime_root.parent.parent
    for (package, relative), digest in NATIVE_ARTIFACTS.items():
        filename = installation / package / relative
        _regular_owners(installation, (str(filename.relative_to(installation)),))
        if hashlib.sha256(filename.read_bytes()).hexdigest() != digest:
            raise ValueError("The published fs-safe native artifact changed")
        native_evidence.append({"package": package, "path": relative, "sha256": digest,
                                "nativeBuildReproduced": False})
    alias = sources[SOURCE_ALIAS_PATH]
    # _owners also requires this exact alias as a unique original anchor.
    source_alias = {"path": SOURCE_ALIAS_PATH, "declaration": SOURCE_ALIAS_DECLARATION,
                   "line": alias[:alias.index(SOURCE_ALIAS_DECLARATION)].count("\n") + 1,
                   "declarationSha256": hashlib.sha256(SOURCE_ALIAS_DECLARATION.encode()).hexdigest()}
    return {
        "kind": "official-release-promotion-apply-owners", "operation": PROMOTION_APPLY_OPERATION,
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "sourceFallbackAllowed": False, "covers": [], "acceptancePointsAwarded": 0,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": source_links, "sourceAliasLink": source_alias,
        "nativeArtifactBindings": native_evidence,
        "applyEntrypoint": {"path": "dist/short-term-promotion-MX1vHJuE.mjs", "export": "a"},
        "storeEntrypoints": {"path": "dist/short-term-promotion-store-B6T388Bo.mjs",
                             "readRecall": "a", "writeRecall": "l"},
        "factoryEntrypoints": {
            "configure": {"path": "dist/dreaming-state-VYUvbU-n.mjs", "export": "p"},
            "publicKeyed": {"path": AUTHENTICATED_ONLY_ARTIFACTS[0],
                            "export": "createPluginStateKeyedStore", "executionRequired": False},
            "keyed": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "r",
                      "pluginId": "memory-core"},
            "provenanceKeyed": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "t",
                                "ownerId": "core:memory-artifact-provenance", "namespace": "workspace-files"},
            "close": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "u"}},
        "provenanceEntrypoint": {"path": "dist/memory-artifact-provenance-DhnyWiV1.mjs", "export": "n"},
        "eventReadEntrypoint": {"path": "dist/memory-host-events-C8-U38f1.mjs", "export": "n"},
        "databasePathEntrypoint": {"path": "dist/openclaw-state-db.paths-rJI64Ab5.mjs", "export": "s"},
        "workspaceLeaseEntrypoint": {"path": "dist/dreaming-dreams-file-BJzlZFlf.mjs", "export": "g",
                                     "namespace": "short-term-locks", "initialReadRequired": True},
        "promotionFileLockEntrypoint": {"path": "dist/file-lock-bsl71RWY.mjs", "export": "s",
                                       "reachedAfterZeroRehydratedReturn": False},
        "requiredLoadedArtifacts": list(REQUIRED_ARTIFACTS[PROMOTION_APPLY_OPERATION]),
        "authenticatedOnlyArtifacts": list(AUTHENTICATED_ONLY_ARTIFACTS),
        "requiredPluginStateWorkerArtifact": "dist/plugin-state.worker-Bt1nfP3u.mjs",
        "requiredWorkerRoute": list(PROMOTION_WORKER_ROUTE), "workerImportsRequired": True,
        "workerClock": "Original protected worker clock; only main-thread Date is controlled",
        "clock": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "providerConstructed": False, "managerConstructed": False,
        "lockEquivalenceClaimed": False, "publicationOrderingClaimed": False,
    }
