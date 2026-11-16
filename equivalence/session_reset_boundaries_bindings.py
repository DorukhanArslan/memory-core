"""Authenticate bundled reset-hook, durable provenance and retrieval owners.

These declarations award no acceptance credit. Committed source and official
published artifacts are authenticated separately; no reproduced build is claimed.
"""
import hashlib
from pathlib import Path

from equivalence import bootstrap_discovery_bindings as hooks
from equivalence import embedding_cache_lifecycle_bindings as managed
from equivalence import memory_budget_bindings as budget
from equivalence import session_admission_runtime_bindings as sessions
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
OPERATION = "session-reset-boundaries-runtime"


def _select(names, values):
    return {name: values[name] for name in names}


_MANAGED_SOURCES = (
    "extensions/memory-core/src/memory/manager-runtime.ts",
    "extensions/memory-core/src/memory/manager.ts",
    "extensions/memory-core/src/memory/manager-search-orchestration.ts",
    "extensions/memory-core/src/memory/manager-source-sync-ops.ts",
    "extensions/memory-core/src/memory/manager-sync-ops.ts",
    "extensions/memory-core/src/memory/manager-index-preparation.ts",
    "extensions/memory-core/src/memory/manager-index.worker.ts",
    "extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts",
    "extensions/memory-core/src/dreaming-state.ts",
    "extensions/memory-core/src/memory-workspace-lock.ts",
    "src/plugin-state/plugin-state-store.ts",
    "src/plugin-state/plugin-state-store.sqlite.ts",
    "src/state/openclaw-agent-db-lifecycle.ts",
)
_SESSION_SOURCES = (
    "extensions/memory-core/src/tools.ts",
    "extensions/memory-core/src/memory-search-tool-query.ts",
    "src/config/sessions/session-accessor.ts",
    "src/config/sessions/session-accessor.entry.ts",
    "src/config/sessions/session-accessor.sqlite-entry.ts",
    "src/config/sessions/session-accessor.sqlite-read.ts",
    "src/config/sessions/session-accessor.sqlite-transcript-write.ts",
    "packages/memory-host-sdk/src/host/session-provenance.ts",
)
SOURCE_HASHES = {
    **_select(_MANAGED_SOURCES, managed.SOURCE_HASHES),
    **_select(_SESSION_SOURCES, sessions.SOURCE_HASHES),
    **_select(("src/hooks/internal-hooks.ts",), hooks.SOURCE_HASHES),
    "src/hooks/bundled/session-memory/handler.ts": "1304d092f59d97dc42abcdfc9ab2b5d497adc96112d52be36f6279fc4ef37807",
    "src/hooks/bundled/session-memory/capture.ts": "a104a8263c34f5b8b2d03975734aa6818b5aab0d63ff605df83ec8aec11b8412",
    "src/hooks/bundled/session-memory/transcript.ts": "6ce4dcd3f69ad0fc8ab07f2957a82ef977f91473e52b99c748d666218bc0da45",
    "src/agents/memory-write-provenance.ts": "628c004d93b38b06108d426750ca1ef1e8459c108202d0568b18e4c02bfebd13",
    "src/memory/memory-artifact-provenance.ts": "68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373",
    "src/hooks/policy.ts": "52cf99036eab4bbd0b7585e35fa10b2eedcf886d1ecfcf73cf24a72a1881d983",
    "src/hooks/internal-hook-types.ts": "3b161315efe5f3c8c4d52b8bbdc4ecdd8f5639dae3b9d0e3546ed9aea5a18808",
    "src/hooks/session-auto-reset.ts": "43e37b2c95795cb260f6751f8931bf084322ad4d68e22f71d792828e4fdac376",
    "src/infra/fs-safe.ts": "4df60b4136ca5f0b117a90e257a41a8b448638c4f46112ca43240f7a23b1fc6a",
    "src/config/sessions/session-accessor.sqlite-active-events.ts": "8313bc8a4f68f008da3f2b93b059eb173b8dcbf709f86c0bdfbeeac6ce39ea5a",
    "src/config/sessions/transcript-visible-events.ts": "15250a85089fc04749f3e82bb37008b178149acdb85dfc3b0a4387e2386ec774",
    "src/security/external-content.ts": "6390947a2aa834484102b54eaad88c112f6f939ded834ff8ce74a0882842eaed",
    "src/sessions/input-provenance.ts": "9316c1c3a96295f44fc4c5dd599fc7e5d306651f06c9a1ce07f3f667f29a2dc6",
    "src/shared/transcript-only-openclaw-assistant.ts": "22f845e6b3514a4a694f09fab0fab7168a3a2be31a8de0c592ce5a5c82eff86e",
    "src/agents/date-time.ts": "051a17e9166dcafd666930f5975045da8400d31a968fc6b2103ef57bc8675e47",
    "extensions/memory-core/src/memory-read-tool.ts": "318bdf62b8503176b55eda4c6431b91e6b330cbeb3178f390f0623e87f621c37",
    "packages/memory-host-sdk/src/host/read-file.ts": "340bb4aff7a88ee80591e5d0bc4f959367e7d2b6d7f06017d599f0342cb29dd2",
    "src/state/openclaw-state-db.paths.ts": "e3169d4e1f8df9b1bec5572bb20158c5800d135d26341b2af0920f73a06d95e1",
    "src/config/sessions/session-accessor.sqlite-reset-window.ts": "bb63c2a6438be73959f954d1e7d30185ac8e0781a42111809f9fd8fd94ff3af1",
    "packages/agent-core/src/harness/session/tool-result-pairing.ts": "432a3ab386709ea2341f6f336c42eb78eae7ef323ff5f293a69ece53ebb1701b",
    "src/state/openclaw-state-db.ts": "8f4f7a1a7cecb4d4e4ab9b762e85785ed1476d66bc195ef8f157efdc7871704c",
    "src/logging/logger.ts": "8c7832f365fbb826bf338a5488b8136483fcf515dfe202a25b71e2f38d972b9e",
    "extensions/memory-core/src/short-term-promotion-record.ts": "b8d168519af14de5ae793d6738d3a86d51e41cdcc12cbd5b22fb174ba108d8c7",
}
SOURCE_ANCHORS = {
    **_select(_MANAGED_SOURCES, managed.SOURCE_ANCHORS),
    **_select(_SESSION_SOURCES, sessions.SOURCE_ANCHORS),
    "src/hooks/internal-hooks.ts": (
        "export function registerInternalHook(", "export function unregisterInternalHook(",
        "export async function triggerInternalHook(", "export function createInternalHookEvent("),
    "src/hooks/bundled/session-memory/handler.ts": (
        "async function saveSessionMemoryNow(", "const saveSessionToMemory: HookHandler = (event) => {",
        "export async function flushSessionMemoryWritesForTest()", "export default saveSessionToMemory;"),
    "src/hooks/bundled/session-memory/capture.ts": ("export function captureSessionMemoryTranscript(",),
    "src/hooks/bundled/session-memory/transcript.ts": (
        "export function countSessionMemoryMessages(", "export function getRecentSessionProjectionFromEvents("),
    "src/agents/memory-write-provenance.ts": ("export function createMemoryWriteProvenanceObserver(",),
    "src/memory/memory-artifact-provenance.ts": (
        "export async function recordMemoryArtifactWriteProvenance(",
        "export async function listMemoryArtifactProvenance("),
    "src/hooks/policy.ts": ("export function resolveHookConfig(",),
    "src/hooks/internal-hook-types.ts": ("export interface InternalHookEvent {",),
    "src/hooks/session-auto-reset.ts": ("export function isSessionAutoResetReason(",),
    "src/infra/fs-safe.ts": ("export async function root(",),
    "src/config/sessions/session-accessor.sqlite-active-events.ts": (
        "export function readSessionTranscriptBoundedMessageTailPage(",),
    "src/config/sessions/transcript-visible-events.ts": ("export function selectVisibleTranscriptEvents<T>(",),
    "src/security/external-content.ts": ("export function sanitizeModelSpecialTokens(",),
    "src/sessions/input-provenance.ts": ("export function hasInterSessionUserProvenance(",),
    "src/shared/transcript-only-openclaw-assistant.ts": (
        "export function isOpenClawDeliveryMirrorAssistantMessage(",),
    "src/agents/date-time.ts": ("export function resolveUserTimezone(",),
    "extensions/memory-core/src/memory-read-tool.ts": ("export async function executeMemoryReadResult(",),
    "packages/memory-host-sdk/src/host/read-file.ts": (
        "export async function readMemoryFile(", "export async function readAgentMemoryFile("),
    "src/state/openclaw-state-db.paths.ts": ("export function resolveOpenClawStateSqlitePath(",),
    "src/config/sessions/session-accessor.sqlite-reset-window.ts": (
        "function findLatestResetMessageWindow(", "export function resolveVisibleMessagePositions("),
    "packages/agent-core/src/harness/session/tool-result-pairing.ts": (
        "export function selectResetKeptEntries(",),
    "src/state/openclaw-state-db.ts": ("export function openOpenClawStateDatabase(",),
    "src/logging/logger.ts": ("export async function flushLogger(",),
    "extensions/memory-core/src/short-term-promotion-record.ts": (
        "export async function recordShortTermRecalls(",),
}
SOURCE_ANCHORS["extensions/memory-core/src/tools.ts"] += (
    "export function createMemoryGetTool(", 'options.oneShotCliRun ? "cli" : undefined',
)
SOURCE_ANCHORS["src/config/sessions/session-accessor.sqlite-entry.ts"] = (
    "export function loadSessionEntry(", "export async function replaceSessionEntry(",
)
SOURCE_ANCHORS["extensions/memory-core/src/memory-workspace-lock.ts"] += (
    "export async function withMemoryWorkspacePreparation<T>(",
    "  return await inProcessMemoryWorkspaceLocks.enqueue(key, prepare);",
)

_MANAGED_COMPILED = (
    "dist/extensions/memory-core/manager-runtime.js",
    "dist/plugin-sdk/config-runtime.js",
    "dist/runtime-9cxii0oQ.mjs",
    "dist/registry-empty-BTjzcMW2.mjs",
    "dist/dreaming-state-VYUvbU-n.mjs",
    "dist/plugin-state-store-BPUaLoVD.mjs",
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
    "dist/manager-cpu-worker-runtime-CAWQOyFu.mjs",
    "dist/manager-index-preparation-wXpJtJiU.mjs",
    "dist/manager-cpu-entrypoints-bJosRUx9.mjs",
    "dist/runtime-worker-url-S0NIVxUR.mjs",
    "dist/worker-task-pool-BQlnRNqZ.mjs",
    "dist/extensions/memory-core/memory-index.worker.js",
    "dist/manager-index.worker-CinEDBkE.mjs",
)
_SESSION_COMPILED = (
    "dist/tools-DotaQGXh.mjs",
    "dist/session-accessor-CiKKTlbe.mjs",
    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
)
COMPILED_HASHES = {
    **_select(_MANAGED_COMPILED, managed.COMPILED_HASHES),
    **_select(_SESSION_COMPILED, sessions.COMPILED_HASHES),
    **_select(("dist/internal-hooks-CwVYIajG.mjs",), hooks.COMPILED_HASHES),
    "dist/bundled/session-memory/handler.js": "2279d7ebb3f1ed5789aae0ca8b226ede49c4241569b70b7c126f901551fc59ea",
    "dist/capture-C0uwbnBj.mjs": "9a14915706ed3832327510f760aa7152cdea3deb67f53e08ee65894fe74e9cd2",
    "dist/agent-tools.read-ZzkirzL1.mjs": "bec516044e956d92b1297b154a48ef9ee75e83dfdfe79b8dda5668a9995e778c",
    "dist/memory-artifact-provenance-DhnyWiV1.mjs": "d9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c",
    "dist/fs-safe-CHQXnCPk.mjs": "f3c36c1f9de0572825f72f154c5f2e6e969a7e1fb7ab7914933bb40d18c18414",
    "dist/policy-Cxp-LZzC.mjs": "4e4e44abfa15eb142ce1e0b62f02efa9a4621a46e5da7637adba25563fd3c2c3",
    "dist/session-auto-reset-CQG7JZk0.mjs": "9289021e32b0f6255203af9f274ef0d103535ab484a3e119945c94f1cbfdf30e",
    "dist/session-accessor.sqlite-active-events-U8XgB2zT.mjs": "5c88e50a023eb581630c9d2c310e1ba60692617a891507f73c4673c7baa15103",
    "dist/session-provenance-2cpkCo2r.mjs": "d5015d2e15036f4c1d8e517f6fbf3837a87056f9c5cd629de221c45bbe9c910c",
    "dist/openclaw-state-db.paths-rJI64Ab5.mjs": "8cecbc669117d451fb3681898c056714e463437f1c6ada6a537609864c0c4214",
    "dist/read-file-CH8NQLbp.mjs": "eec2ac48d772f0d2303c65bf3ea3a0866c42f864bf8e9c75f7307643044a4687",
    "dist/session-accessor.sqlite-reset-window-DKSgjJpK.mjs": "e511d10c9e35acbb1ca49cc38641a9d523174dd3815290f5c68b86d34b76282d",
    "dist/tool-result-pairing-Cxh1CJVG.mjs": "15ac445c19df0a718696cd62b243153e5f78652e07492c3ad99b81d01dbdf190",
    "dist/openclaw-state-db-Dh2awMJ8.mjs": "e5aad1c1e5a6d9b1ed371c2a176cf39015d3d3d8293d9aa9128b977cc540f75b",
    "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs": "bb80d5b238fb5eaeb23a0f2a12d9a978b9cafa3962e78984538d801eb6f86e64",
    "dist/logger-Cn5hoa7J.mjs": "abf43650b59da282edeb842edde44eac1d2078827e8cc077d8a70f69f975f76b",
    "dist/short-term-promotion-record-CEpBdgKW.mjs": "228c2ebc76cc3ccf81d8c3542f1e4eaf276674547e61924c67bf352bc387469e",
    "dist/short-term-promotion-record-DrLa1fiO.mjs": "26a083e3c17cd6512af9785266c7bdffe459cd02591be4127004efe7eb8887c7",
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": "fbc57813554fc29a6b7c5bcbada4baa21d5f774c33edd54297a3976741fa4492",
}
COMPILED_ANCHORS = {
    **_select(_MANAGED_COMPILED, managed.COMPILED_ANCHORS),
    **_select(_SESSION_COMPILED, sessions.COMPILED_ANCHORS),
    "dist/internal-hooks-CwVYIajG.mjs": (
        "function registerInternalHook(", "function unregisterInternalHook(",
        "async function triggerInternalHook(", "function createInternalHookEvent("),
    "dist/bundled/session-memory/handler.js": (
        "async function saveSessionMemoryNow(", "const saveSessionToMemory = (event) => {",
        "async function flushSessionMemoryWritesForTest(",
        "export { saveSessionToMemory as default, flushSessionMemoryWritesForTest };"),
    "dist/capture-C0uwbnBj.mjs": (
        "function getRecentSessionProjectionFromEvents(", "function captureSessionMemoryTranscript(",
        "captureSessionMemoryTranscript as t"),
    "dist/agent-tools.read-ZzkirzL1.mjs": (
        "function createMemoryWriteProvenanceObserver(", "createMemoryWriteProvenanceObserver as p"),
    "dist/memory-artifact-provenance-DhnyWiV1.mjs": (
        "async function recordMemoryArtifactWriteProvenance(",
        "async function listMemoryArtifactProvenance(", "listMemoryArtifactProvenance as n"),
    "dist/fs-safe-CHQXnCPk.mjs": ("async function root$1(", "root$1 as w"),
    "dist/policy-Cxp-LZzC.mjs": ("function resolveHookConfig(", "resolveHookConfig as t"),
    "dist/session-auto-reset-CQG7JZk0.mjs": ("function isSessionAutoResetReason(",),
    "dist/session-accessor.sqlite-active-events-U8XgB2zT.mjs": (
        "function readSessionTranscriptBoundedMessageTailPage(",),
    "dist/session-provenance-2cpkCo2r.mjs": ("function classifySessionMessageOrigin(",),
    "dist/openclaw-state-db.paths-rJI64Ab5.mjs": ("function resolveOpenClawStateSqlitePath(",),
    "dist/read-file-CH8NQLbp.mjs": (
        "async function readMemoryFile(", "async function readAgentMemoryFile("),
    "dist/session-accessor.sqlite-reset-window-DKSgjJpK.mjs": (
        "function findLatestResetMessageWindow(", "function resolveVisibleMessagePositions(",
        'import { f as selectResetKeptEntries } from "./tool-result-pairing-Cxh1CJVG.mjs";'),
    "dist/tool-result-pairing-Cxh1CJVG.mjs": (
        "function selectResetKeptEntries(", "selectResetKeptEntries as f"),
    "dist/openclaw-state-db-Dh2awMJ8.mjs": (
        "function openOpenClawStateDatabase(", "openOpenClawStateDatabase as r"),
    "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs": (
        "function loadSessionEntry(scope)", "async function replaceSessionEntry(scope, entry)",
        "replaceSessionEntry as m", "loadSessionEntry as s"),
    "dist/logger-Cn5hoa7J.mjs": ("async function flushLogger(", "flushLogger as n"),
    "dist/short-term-promotion-record-CEpBdgKW.mjs": (
        'import { i as recordShortTermRecalls } from "./short-term-promotion-record-DrLa1fiO.mjs";',
        "export { recordShortTermRecalls };"),
    "dist/short-term-promotion-record-DrLa1fiO.mjs": (
        "async function recordShortTermRecalls(", "recordShortTermRecalls as i"),
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": (
        "async function withMemoryWorkspacePreparation(", "withMemoryWorkspacePreparation as _"),
}
COMPILED_ANCHORS["dist/tools-DotaQGXh.mjs"] += ("function createMemoryGetTool(",)

# Failure-only hooks need no CPU task. Authenticate these artifacts without
# requiring their execution until a case actually performs post-hook indexing.
INDEX_WORKER_ROUTE = (
    "dist/extensions/memory-core/memory-index.worker.js",
    "dist/manager-index.worker-CinEDBkE.mjs",
    "dist/manager-index-preparation-wXpJtJiU.mjs",
)
REQUIRED_RUNTIME_ARTIFACTS = tuple(name for name in COMPILED_HASHES if name not in INDEX_WORKER_ROUTE[:2])
GENUINE_HELPER_EXPORTS = {
    "dist/internal-hooks-CwVYIajG.mjs": ("c", "n", "u", "d"),
    "dist/bundled/session-memory/handler.js": ("default", "flushSessionMemoryWritesForTest"),
    "dist/session-accessor-CiKKTlbe.mjs": (
        "replaceTranscriptEvents", "loadTranscriptEventsSync", "replaceSessionEntry", "loadSessionEntry"),
    "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs": ("m", "s"),
    "dist/tools-DotaQGXh.mjs": ("createMemorySearchTool", "createMemoryGetTool"),
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs": ("c",),
    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs": ("u",),
    "dist/capture-C0uwbnBj.mjs": ("t",),
    "dist/agent-tools.read-ZzkirzL1.mjs": ("p",),
    "dist/memory-artifact-provenance-DhnyWiV1.mjs": ("n",),
    "dist/fs-safe-CHQXnCPk.mjs": ("w",),
    "dist/plugin-sdk/config-runtime.js": ("setRuntimeConfigSnapshot", "clearRuntimeConfigSnapshot"),
    "dist/runtime-9cxii0oQ.mjs": ("w",),
    "dist/registry-empty-BTjzcMW2.mjs": ("t",),
    "dist/dreaming-state-VYUvbU-n.mjs": ("p",),
    "dist/plugin-state-store-BPUaLoVD.mjs": ("r", "t", "u"),
    "dist/extensions/memory-core/manager-runtime.js": ("MemoryIndexManager", "closeAllMemoryIndexManagers"),
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs": ("s",),
    "dist/openclaw-state-db.paths-rJI64Ab5.mjs": ("s",),
    "dist/openclaw-state-db-Dh2awMJ8.mjs": ("r",),
    "dist/session-accessor.sqlite-reset-window-DKSgjJpK.mjs": ("u",),
    "dist/tool-result-pairing-Cxh1CJVG.mjs": ("f",),
    "dist/logger-Cn5hoa7J.mjs": ("n",),
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": ("_",),
}
NATIVE_ARTIFACTS = dict(budget.NATIVE_ARTIFACTS)

# Export inventories describe available original APIs. These distinct triples
# describe only functions actually observed by this fixture's owner receipts.
REQUIRED_OBSERVED_OWNERS = (
    ("dist/bundled/session-memory/handler.js", "default", "saveSessionToMemory"),
    ("dist/bundled/session-memory/handler.js", "flushSessionMemoryWritesForTest", "flushSessionMemoryWritesForTest"),
    ("dist/internal-hooks-CwVYIajG.mjs", "c", "registerInternalHook"),
    ("dist/internal-hooks-CwVYIajG.mjs", "n", "createInternalHookEvent"),
    ("dist/internal-hooks-CwVYIajG.mjs", "u", "triggerInternalHook"),
    ("dist/internal-hooks-CwVYIajG.mjs", "d", "unregisterInternalHook"),
    ("dist/session-accessor-CiKKTlbe.mjs", "replaceTranscriptEvents", "replaceTranscriptEvents"),
    ("dist/session-accessor-CiKKTlbe.mjs", "loadTranscriptEventsSync", "loadTranscriptEventsSync"),
    ("dist/session-accessor-CiKKTlbe.mjs", "replaceSessionEntry", "replaceSessionEntry"),
    ("dist/session-accessor-CiKKTlbe.mjs", "loadSessionEntry", "loadSessionEntry"),
    ("dist/capture-C0uwbnBj.mjs", "t", "captureSessionMemoryTranscript"),
    ("dist/memory-artifact-provenance-DhnyWiV1.mjs", "n", "listMemoryArtifactProvenance"),
    ("dist/tools-DotaQGXh.mjs", "createMemorySearchTool", "createMemorySearchTool"),
    ("dist/tools-DotaQGXh.mjs", "createMemoryGetTool", "createMemoryGetTool"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.get"),
    ("dist/openclaw-state-db-Dh2awMJ8.mjs", "r", "openOpenClawStateDatabase"),
    ("dist/dreaming-state-VYUvbU-n.mjs", "p", "configureMemoryCoreDreamingState"),
    ("dist/plugin-state-store-BPUaLoVD.mjs", "r", "createPluginStateKeyedStore"),
    ("dist/plugin-state-store-BPUaLoVD.mjs", "u", "closePluginStateDatabaseAsync"),
    ("dist/extensions/memory-core/manager-runtime.js", "closeAllMemoryIndexManagers", "closeAllMemoryIndexManagers"),
    ("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s", "closeOpenClawAgentDatabasesAsync"),
    ("dist/logger-Cn5hoa7J.mjs", "n", "flushLogger"),
    ("dist/dreaming-dreams-file-BJzlZFlf.mjs", "_", "withMemoryWorkspacePreparation"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.sync"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.search"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.readFile"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.close"),
    ("dist/extensions/memory-core/manager-runtime.js", "MemoryIndexManager", "MemoryIndexManager.status"),
)


def prepare_session_reset_boundaries_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Verify original source/artifact bytes without importing a runtime owner."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Reset-hook boundaries require the exact pinned original source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    native_evidence = []
    for (package, relative), expected in NATIVE_ARTIFACTS.items():
        filename = runtime_root.parent.parent / package / relative
        if (not filename.is_file() or filename.is_symlink()
                or not filename.resolve().is_relative_to(runtime_root.parent.resolve())
                or hashlib.sha256(filename.read_bytes()).hexdigest() != expected):
            raise ValueError("The original reset-hook fs-safe native artifact changed")
        native_evidence.append({"package": package, "path": relative, "sha256": expected,
                                "nativeBuildReproduced": False})
    prefix = "src/hooks/bundled/session-memory/"
    links = (
        (prefix + "handler.ts", "./capture.js", ("captureSessionMemoryTranscript",)),
        (prefix + "handler.ts", "../../../agents/memory-write-provenance.js",
         ("createMemoryWriteProvenanceObserver",)),
        (prefix + "handler.ts", "../../../infra/fs-safe.js", ("root",)),
        (prefix + "capture.ts", "./transcript.js", ("countSessionMemoryMessages", "getRecentSessionProjectionFromEvents")),
        (prefix + "transcript.ts", "../../../../packages/memory-host-sdk/src/host/session-provenance.js",
         ("classifySessionMessageOrigin",)),
        ("src/agents/memory-write-provenance.ts", "../memory/memory-artifact-provenance.js",
         ("recordMemoryArtifactWriteProvenance",)),
        ("src/memory/memory-artifact-provenance.ts", "../plugin-state/plugin-state-store.js",
         ("createCorePluginStateKeyedStore",)),
        ("src/config/sessions/session-accessor.sqlite-active-events.ts", "./session-accessor.sqlite-reset-window.js",
         ("resolveVisibleMessagePositions", "resolveTranscriptBoundaryWindow")),
        ("src/config/sessions/session-accessor.sqlite-reset-window.ts",
         "../../../packages/agent-core/src/harness/session/tool-result-pairing.js", ("selectResetKeptEntries",)),
        ("extensions/memory-core/src/short-term-promotion-record.ts", "./memory-workspace-lock.js",
         ("withMemoryWorkspaceLock",)),
    )
    entry_exports = (
        ("src/config/sessions/session-accessor.ts", "./session-accessor.entry.js"),
        ("src/config/sessions/session-accessor.entry.ts", "./session-accessor.sqlite-entry.js"),
    )
    return {
        "kind": "official-release-session-reset-boundaries-owners", "referenceCommit": REFERENCE_COMMIT,
        "operation": OPERATION, "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                              for module, specifier, names in links] + [
            _named_link(sources, module, specifier, ("loadSessionEntry", "replaceSessionEntry"), kind="export")
            for module, specifier in entry_exports],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "genuineHelperExports": {name: list(exports) for name, exports in GENUINE_HELPER_EXPORTS.items()},
        "requiredObservedOwners": [list(owner) for owner in REQUIRED_OBSERVED_OWNERS],
        "nativeArtifacts": native_evidence, "indexWorkerRoute": list(INDEX_WORKER_ROUTE),
        "requiresIndexWorkerForEveryCase": False,
        "provider": "none", "llmSlug": False, "managerConstructed": True,
        "hookInvocation": "Original registration, event construction, dispatch, pending-write drain and unregister",
        "publicBoundary": "Complete reset-hook files, durable provenance and post-hook index/search/read observations",
        "rawBoundary": "Original hook, storage, manager and writer calls/returns/errors plus complete physical SQL/source evidence",
        "clockFixture": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "acceptancePointsAwarded": 0, "covers": [],
    }
