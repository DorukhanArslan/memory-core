"""Exact recall, corpus, lineage, event and original SQLite-worker owners."""
from pathlib import Path
import hashlib

from equivalence import forget_lineage_bindings as lineage
from equivalence import memory_budget_bindings as budget
from equivalence import promotion_ranking_bindings as ranking
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"


def _select(names, *maps):
    merged = {}
    for values in maps:
        merged.update(values)
    return {name: merged[name] for name in names}


_SOURCE_NAMES = (
    "extensions/memory-core/src/short-term-promotion-record.ts",
    "extensions/memory-core/src/memory-entry-origins.ts",
    "extensions/memory-core/src/memory-session-tombstones.ts",
    "extensions/memory-core/src/memory-workspace-lock.ts",
    "extensions/memory-core/src/memory-workspace-files.ts",
    "extensions/memory-core/src/session-ingestion.ts",
    "src/memory-host-sdk/events.ts",
    "src/memory-host-sdk/event-store.ts",
    "src/plugin-sdk/plugin-state-store-runtime.ts",
)
SOURCE_HASHES = {name: digest for name, digest in ranking.SOURCE_HASHES.items()
                 if name not in {"extensions/memory-core/src/short-term-promotion.ts",
                                 "extensions/memory-core/src/dreaming-consolidation-candidates.ts"}}
SOURCE_HASHES.update(_select(_SOURCE_NAMES, lineage.SOURCE_HASHES, budget.SOURCE_HASHES))
SOURCE_HASHES.update({
    "packages/memory-host-sdk/src/memory-entry-origins.ts": "507000d2384e3fb0287a31ce9dd474754b72bb1f9d2718e5a696afab5c6fddfa",
    "src/state/openclaw-agent-db.ts": "f28a4f20493b63d9d3ce88e5811e82733b4989068b400d9219736ddce84b5781",
})
SOURCE_ANCHORS = {name: ranking.SOURCE_ANCHORS[name] for name in SOURCE_HASHES if name in ranking.SOURCE_ANCHORS}
SOURCE_ANCHORS.update(_select(_SOURCE_NAMES, lineage.SOURCE_ANCHORS, budget.SOURCE_ANCHORS))
SOURCE_ANCHORS.update({
    "extensions/memory-core/src/short-term-promotion-record.ts": (
        "export async function recordShortTermRecalls(params: {",
        "export async function recordGroundedShortTermCandidates(params: {"),
    "extensions/memory-core/src/session-ingestion.ts": ("export async function appendSessionCorpusLines(params: {",),
    "packages/memory-host-sdk/src/memory-entry-origins.ts": ("export function ensureMemoryEntryOriginsSchema(",),
    "src/state/openclaw-agent-db.ts": ("export function openOpenClawAgentDatabase(",),
})

_COMPILED_NAMES = (
    "dist/short-term-promotion-record-DrLa1fiO.mjs",
    "dist/memory-entry-origins-BCQSIB3X.mjs",
    "dist/memory-workspace-files-CC0bKS3d.mjs",
    "dist/dreaming-dreams-file-BJzlZFlf.mjs",
    "dist/time-BhFVUM0b.mjs",
    "dist/session-ingestion-Dy5uAq-_.mjs",
    "dist/memory-host-events-C8-U38f1.mjs",
    "dist/event-store-BeWtwFJV.mjs",
    "dist/file-lock-bsl71RWY.mjs",
    "dist/plugin-sdk/config-runtime.js",
    "dist/openclaw-agent-db.paths-Dv3PPTNK.mjs",
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
)
COMPILED_HASHES = {name: digest for name, digest in ranking.COMPILED_HASHES.items()
                   if name not in {"dist/short-term-promotion-MX1vHJuE.mjs", "dist/memory-budget-BodJnew-.mjs"}}
COMPILED_HASHES.update(_select(_COMPILED_NAMES, lineage.COMPILED_HASHES, budget.COMPILED_HASHES))
COMPILED_HASHES.update({
    "dist/openclaw-agent-db-DRy3ui_B.mjs": "f851c6fa5b6a766e6afff83684ad02883c45589532bd8ac1e790f20bbb3b0d93",
    "dist/memory-core-host-engine-storage-Dn-n8hud.mjs": "9d62579b77fd6dd89cfa6047d355ab1d9d8b2ec38bcfe6b2528b7b00c3881186",
    "dist/memory-session-tombstones-B1AGruLs.mjs": "8246f0c143130e397c952f8bef014e212bceeb73a14b3146afc57335ba0432e2",
})
COMPILED_ANCHORS = {name: ranking.COMPILED_ANCHORS[name] for name in COMPILED_HASHES if name in ranking.COMPILED_ANCHORS}
COMPILED_ANCHORS.update(_select(_COMPILED_NAMES, lineage.COMPILED_ANCHORS, budget.COMPILED_ANCHORS))
COMPILED_ANCHORS.update({
    "dist/short-term-promotion-record-DrLa1fiO.mjs": ("async function recordShortTermRecalls(params) {",
                                                   "async function recordGroundedShortTermCandidates(params) {"),
    "dist/session-ingestion-Dy5uAq-_.mjs": ("async function appendSessionCorpusLines(params) {",),
    "dist/openclaw-agent-db-DRy3ui_B.mjs": ("function openOpenClawAgentDatabase(options, preparedLease, registrationObserver) {",),
    "dist/memory-core-host-engine-storage-Dn-n8hud.mjs": ("function ensureMemoryEntryOriginsSchema(db) {",),
    "dist/memory-session-tombstones-B1AGruLs.mjs": ("function ensureMemorySessionTombstones(db) {",),
})
REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED_HASHES)
GENUINE_HELPER_EXPORTS = {
    "dist/short-term-promotion-record-DrLa1fiO.mjs": ("i", "r"),
    "dist/short-term-promotion-store-B6T388Bo.mjs": ("a", "l", "D"),
    "dist/memory-entry-origins-BCQSIB3X.mjs": ("n", "r", "o"),
    "dist/memory-host-events-C8-U38f1.mjs": ("n",),
    "dist/session-ingestion-Dy5uAq-_.mjs": ("r",),
    "dist/openclaw-agent-db-DRy3ui_B.mjs": ("c",),
    "dist/memory-core-host-engine-storage-Dn-n8hud.mjs": ("t",),
    "dist/openclaw-agent-db.paths-Dv3PPTNK.mjs": ("c",),
}


def prepare_recall_signals_bindings(checkout: Path, runtime_root: Path) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Recall signals require the exact unchanged pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    native_evidence = []
    for (package, relative), digest in budget.NATIVE_ARTIFACTS.items():
        filename = runtime_root.parent.parent / package / relative
        if (not filename.is_file() or filename.is_symlink()
                or not filename.resolve().is_relative_to(runtime_root.parent.resolve())
                or hashlib.sha256(filename.read_bytes()).hexdigest() != digest):
            raise ValueError("The original fs-safe published native artifact changed")
        native_evidence.append({"package": package, "path": relative, "sha256": digest, "nativeBuildReproduced": False})
    prefix = "extensions/memory-core/src/"
    links = [
        (prefix + "short-term-promotion-record.ts", "./short-term-promotion-store.js", ("readStore", "writeStore")),
        (prefix + "short-term-promotion-record.ts", "./memory-entry-origins.js", ("listMemorySessionTombstones", "recordMemoryEntryOrigins")),
        (prefix + "short-term-promotion-record.ts", "./memory-workspace-lock.js", ("withMemoryWorkspaceLock",)),
        (prefix + "short-term-promotion-record.ts", "openclaw/plugin-sdk/memory-host-events", ("appendMemoryHostEvent",)),
        (prefix + "short-term-promotion-store.ts", "./dreaming-state.js", ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries")),
        ("src/memory-host-sdk/events.ts", "./event-store.js", ("registerMemoryHostEvent", "listStoredMemoryHostEvents")),
    ]
    return {"kind": "official-release-recall-signals-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                              for module, specifier, names in links],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "genuineHelperExports": {key: list(value) for key, value in GENUINE_HELPER_EXPORTS.items()},
        "requiredWorkerRoute": list(ranking.PROMOTION_WORKER_ROUTE), "nativeArtifacts": native_evidence,
        "provider": "none", "managerConstructed": False,
        "sourceRangeScope": "Actual corpus appender returns and unchanged physical bytes before grounded publication",
        "failureScope": "Real SQLite BEFORE INSERT abort; recall publication and events remain unchanged",
        "clockFixture": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "publicBoundary": "Complete recall stores, ordered host records, origin/tombstone rows and completion outcomes",
        "rawBoundary": "Original arguments, producer returns, language returns and complete exceptions, source bytes/ranges, full physical files and SQL",
        "acceptancePointsAwarded": 0, "covers": []}
