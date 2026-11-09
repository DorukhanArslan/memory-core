"""Pinned rank-only owners and the original SQLite-backed signal-store route."""
from pathlib import Path
from copy import deepcopy

from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
PROMOTION_RANKING_OPERATION = "promotion-ranking-runtime"


def validate_promotion_ranking_profile(value: dict) -> dict:
    if (type(value) is not dict or set(value) != {"kind", "operation", "inputKind", "nodeRuntime"}
            or value["kind"] != "approved-promotion-ranking-profile"
            or value["operation"] != PROMOTION_RANKING_OPERATION or value["inputKind"] != "promotion-ranking"):
        raise ValueError("Promotion ranking requires its exact independent compiled profile")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_promotion_ranking_profile(node: Path) -> dict:
    return validate_promotion_ranking_profile({"kind": "approved-promotion-ranking-profile",
        "operation": PROMOTION_RANKING_OPERATION, "inputKind": "promotion-ranking",
        "nodeRuntime": prepare_model_node_authority(node)})


def prepare_promotion_ranking_bindings(checkout: Path, runtime_root: Path) -> dict:
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Promotion ranking requires the exact unchanged pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    prefix = "extensions/memory-core/src/"
    links = [
        (prefix + "short-term-promotion.ts", "./short-term-promotion-store.js", ("readPhaseSignalStore", "readStore"), "import"),
        (prefix + "short-term-promotion.ts", "./dreaming-consolidation-candidates.js", ("isPromotionOriginBlocked",), "import"),
        (prefix + "short-term-promotion.ts", "./short-term-promotion-utils.js", ("normalizeWeights", "calculateRecencyComponent", "isContaminatedDreamingSnippet", "totalSignalCountForEntry"), "import"),
        (prefix + "short-term-promotion.ts", "./time.js", ("resolveMemoryCoreNowMs", "resolveMemoryCoreTimestamp"), "import"),
        (prefix + "short-term-promotion-store.ts", "./dreaming-state.js", ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntry"), "import"),
        (prefix + "short-term-promotion-store.ts", "./short-term-promotion-utils.js", ("normalizeShortTermRecallStore", "enforceShortTermRecallSnippetCap", "enforceShortTermRecallStoreRetention"), "import"),
        (prefix + "short-term-promotion-types.ts", "openclaw/plugin-sdk/memory-core-host-status", ("DEFAULT_MEMORY_DEEP_DREAMING_MIN_SCORE", "DEFAULT_MEMORY_DEEP_DREAMING_MIN_RECALL_COUNT", "DEFAULT_MEMORY_DEEP_DREAMING_MIN_UNIQUE_QUERIES"), "import"),
        ("src/plugin-sdk/memory-core-host-status.ts", "../memory-host-sdk/dreaming.js", ("DEFAULT_MEMORY_DEEP_DREAMING_MIN_SCORE", "DEFAULT_MEMORY_DEEP_DREAMING_MIN_RECALL_COUNT", "DEFAULT_MEMORY_DEEP_DREAMING_MIN_UNIQUE_QUERIES"), "export"),
        ("src/plugin-state/plugin-state-store.ts", "./plugin-state-worker-client.js", ("registerPluginStateInWorker", "listPluginStateInKeyRangeInWorker"), "import"),
        ("src/state/openclaw-state-worker-owner.ts", "../infra/sqlite-worker-store.js", ("openSharedStateSqliteWorkerStore",), "import"),
        ("src/state/openclaw-state-worker-owner.ts", "../infra/runtime-process-url.js", ("resolveRuntimeProcessEntrypointUrl",), "import"),
    ]
    return {"kind": "official-release-promotion-ranking-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False, "covers": [],
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind=kind)
            for module, specifier, names, kind in links],
        "sourceAliasLink": {"path": "src/state/openclaw-state-worker-store.ts",
            "declaration": 'import { getOpenClawStateWorkerOwner as owner } from "./openclaw-state-worker-owner.js";'},
        "rankEntrypoint": {"path": "dist/short-term-promotion-MX1vHJuE.mjs", "export": "t"},
        "storeEntrypoints": {"path": "dist/short-term-promotion-store-B6T388Bo.mjs",
            "readRecall": "a", "writeRecall": "l", "readPhase": "r", "writePhase": "c",
            "readRawStore": "i", "normalizeRecall": "k", "retainRecall": "_", "normalizePhase": "n"},
        "factoryEntrypoints": {"configure": {"path": "dist/dreaming-state-VYUvbU-n.mjs", "export": "p"},
            "keyed": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "r", "pluginId": "memory-core"},
            "close": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "u"}},
        "databasePathEntrypoint": {"path": "dist/openclaw-state-db.paths-rJI64Ab5.mjs", "export": "s"},
        "requiredPluginStateWorkerArtifact": "dist/plugin-state.worker-Bt1nfP3u.mjs",
        "requiredWorkerRoute": list(PROMOTION_WORKER_ROUTE),
        "workerClock": "Original protected worker clock; only main-thread Date is controlled",
        "sharedBudgetModule": {"path": "dist/memory-budget-BodJnew-.mjs", "called": False},
        "rankOnly": True, "providerConstructed": False, "managerConstructed": False,
        "promotionApplied": False, "rankingAlgorithmInAdapter": False,
        "clock": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "publicBoundary": "Complete normalized recall/phase stores and complete ordered original candidate returns",
        "rawBoundary": "Literal arguments, original factory calls, actual keyed entries and full physical SQLite before/after",
        "storedOrderPolicy": "Original keyed-store iteration order; no output sorting or tie repair"}

SOURCE_HASHES = {'extensions/memory-core/src/short-term-promotion.ts': '2c00653755f1ce10d9c933aeda2e44580dbaa97b9c5e33d9596e86f5932d7557',
 'extensions/memory-core/src/short-term-promotion-store.ts': '556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84',
 'extensions/memory-core/src/short-term-promotion-utils.ts': '2c9368be7fcff1581a3e4c706465dc60506fa605cf8db9dba3577fa7cc9274c7',
 'extensions/memory-core/src/short-term-promotion-types.ts': 'c97c17dcc52eea9fc9d320fa77be6f0da901331428d6bfc70d289da9e6764daf',
 'extensions/memory-core/src/dreaming-consolidation-candidates.ts': 'd85ccfe5295655ab8e6ea343f8d3640a06c10fd879536088ad42d4cd48493394',
 'extensions/memory-core/src/dreaming-state.ts': 'b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
 'extensions/memory-core/src/time.ts': '3bdbf0427b95742be8fceae4107a2949ef184df196c75760eee132d06572fdcc',
 'src/plugin-sdk/memory-core-host-status.ts': '5695ca6c4e31068afb7e9f2541595c1e0ba8b86f95c4f8a1e962078fa27497ab',
 'src/memory-host-sdk/dreaming.ts': 'c4f5299cf96c6701e5217dba3e2f41aeca5b5393e3f0c23e00478a394bbf2daf',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530',
 'src/plugin-state/plugin-state-store.sqlite.ts': '5c8a00ecd21695bb20acac0be92d0477a9a5533f1795f7b0ee153c1e462a5498',
 'src/plugin-state/plugin-state-worker-client.ts': '2f6d019d90a079e01a1ee2edcfe13b3be7393baad7b951d1de9bfab69ebdbee3',
 'src/plugin-state/plugin-state.worker.ts': '7890fdcd60cd75b59816603242cf6446f236a8901d679185da9191630c7de5b0',
 'src/state/openclaw-state-db.paths.ts': 'e3169d4e1f8df9b1bec5572bb20158c5800d135d26341b2af0920f73a06d95e1'}
SOURCE_ANCHORS = {'extensions/memory-core/src/short-term-promotion.ts': ('export async function '
                                                        'rankShortTermPromotionCandidates(',),
 'extensions/memory-core/src/short-term-promotion-store.ts': ('export async function readStore(',
                                                              'export async function writeStore(',
                                                              'export async function readPhaseSignalStore(',
                                                              'export async function writePhaseSignalStore('),
 'extensions/memory-core/src/short-term-promotion-utils.ts': ('export function normalizeShortTermRecallStore(',
                                                              'export function normalizeWeights(',
                                                              'export function calculateRecencyComponent('),
 'extensions/memory-core/src/short-term-promotion-types.ts': ('export const DEFAULT_PROMOTION_MIN_SCORE =',
                                                              'export const DEFAULT_PROMOTION_MIN_RECALL_COUNT '
                                                              '=',
                                                              'export const '
                                                              'DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES ='),
 'extensions/memory-core/src/dreaming-consolidation-candidates.ts': ('export function '
                                                                     'isPromotionOriginBlocked(',),
 'extensions/memory-core/src/dreaming-state.ts': ('export function configureMemoryCoreDreamingState(',
                                                  'export async function readMemoryCoreWorkspaceEntries(',
                                                  'export async function writeMemoryCoreWorkspaceEntries('),
 'extensions/memory-core/src/time.ts': ('export function resolveMemoryCoreNowMs(',
                                        'export function resolveMemoryCoreTimestamp('),
 'src/plugin-sdk/memory-core-host-status.ts': ('  DEFAULT_MEMORY_DEEP_DREAMING_MIN_SCORE,',),
 'src/memory-host-sdk/dreaming.ts': ('export const DEFAULT_MEMORY_DEEP_DREAMING_MIN_SCORE = 0.75;',
                                     'export const DEFAULT_MEMORY_DEEP_DREAMING_MIN_RECALL_COUNT = 3;',
                                     'export const DEFAULT_MEMORY_DEEP_DREAMING_MIN_UNIQUE_QUERIES = 3;'),
 'src/plugin-state/plugin-state-store.ts': ('export function createPluginStateKeyedStore<T>(',),
 'src/plugin-state/plugin-state-store.sqlite.ts': ('export async function closePluginStateDatabaseAsync()',),
 'src/plugin-state/plugin-state-worker-client.ts': ('export function registerPluginStateInWorker(',
                                                    'export function listPluginStateInKeyRangeInWorker('),
 'src/plugin-state/plugin-state.worker.ts': ('export function executePluginStateCommand(',),
 'src/state/openclaw-state-db.paths.ts': ('export function resolveOpenClawStateSqlitePath(',)}

SOURCE_HASHES.update({
    'src/plugin-state/plugin-state-store.kernel.ts': 'db0136ba0988fab6cdc5410bd6a459192a0bda964da26dcddfb2584cc5ab2697',
    'src/state/openclaw-state-worker-store.ts': '58194c48d5c2d7047fb6429e37b080b4745d6c2562b583ab54773c8612c3c9da',
    'src/state/openclaw-state-worker-owner.ts': 'f6cb1576f8bd7f0ce23326e558c7c3968b202e5b03f18e5c41e86488bdc2b127',
    'src/state/openclaw-state.worker.ts': '0017e2465c09c9d1bc3701005a065a1de989bc84c4b14a265366c555a9fc56b2',
    'src/infra/sqlite-store.worker.ts': 'c958da27fa03aa7a31b487ad98836d9419539c8c3c0d6cdce52724f82d8702a8',
    'src/infra/runtime-process-url.ts': '0914e78c0e99eecfb49d0aafec3e82d8e6fa61f3a22cfbf97669c0ffc8441f1e',
})
SOURCE_ANCHORS.update({
    'src/plugin-state/plugin-state-store.kernel.ts': ('export function rowToEntry(', 'export function bindPluginStateEntry('),
    'src/state/openclaw-state-worker-store.ts': ('export async function runOpenClawStateWorkerOperation<T>(',
        'import { getOpenClawStateWorkerOwner as owner } from "./openclaw-state-worker-owner.js";'),
    'src/state/openclaw-state-worker-owner.ts': ('const moduleUrl = resolveRuntimeProcessEntrypointUrl("sharedStateStore");',),
    'src/state/openclaw-state.worker.ts': ('export function createSqliteWorkerBackend(',),
    'src/infra/sqlite-store.worker.ts': ('if (!parentPort)', 'async function receive('),
    'src/infra/runtime-process-url.ts': ('export function resolveRuntimeProcessEntrypointUrl(',),
})

COMPILED_HASHES = {'dist/short-term-promotion-MX1vHJuE.mjs': 'be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da',
 'dist/short-term-promotion-store-B6T388Bo.mjs': '704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8',
 'dist/short-term-promotion-types-UVm8XCDd.mjs': '2117032ca4a266270aa222f7d7b636b27670af40b81a464823e738e2b8f6e048',
 'dist/dreaming-state-VYUvbU-n.mjs': '8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
 'dist/time-BhFVUM0b.mjs': '2eed429a02ba038dbaf5c16e83acfcae6baa0293dc46370475cb00b1d267ae02',
 'dist/dreaming-dsmlMxw7.mjs': 'd84a68d61fc08db53d0ec7e408017c940151ff10e11a38430c23415a06ffef83',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
 'dist/plugin-state-worker-client-7ByaGIDy.mjs': 'bee1c828bf9a23d3aeafd84e91d3dfd2b2d685b2d560fc5a9e01aabcd0346217',
 'dist/plugin-state.worker-Bt1nfP3u.mjs': 'd724a51faf2d46e518a733a47528ac9b629e54b1d4f6afa9007d769021bba9f4',
 'dist/openclaw-state-db.paths-rJI64Ab5.mjs': '8cecbc669117d451fb3681898c056714e463437f1c6ada6a537609864c0c4214'}
COMPILED_ANCHORS = {'dist/short-term-promotion-MX1vHJuE.mjs': ('async function rankShortTermPromotionCandidates(',
                                            'rankShortTermPromotionCandidates as t'),
 'dist/short-term-promotion-store-B6T388Bo.mjs': ('async function readStore(',
                                                  'async function writeStore(',
                                                  'async function readPhaseSignalStore(',
                                                  'async function writePhaseSignalStore('),
 'dist/short-term-promotion-types-UVm8XCDd.mjs': ('const DEFAULT_PROMOTION_MIN_SCORE =',
                                                  'const DEFAULT_PROMOTION_MIN_RECALL_COUNT = 3;',
                                                  'const DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES = 3;'),
 'dist/dreaming-state-VYUvbU-n.mjs': ('function configureMemoryCoreDreamingState(',
                                      'configureMemoryCoreDreamingState as p'),
 'dist/time-BhFVUM0b.mjs': ('function resolveMemoryCoreNowMs(', 'function resolveMemoryCoreTimestamp('),
 'dist/dreaming-dsmlMxw7.mjs': ('const DEFAULT_MEMORY_DEEP_DREAMING_MIN_SCORE = .75;',),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function createPluginStateKeyedStore(',
                                          'createPluginStateKeyedStore as r',
                                          'closePluginStateDatabaseAsync as u'),
 'dist/plugin-state-worker-client-7ByaGIDy.mjs': ('function registerPluginStateInWorker(',
                                                  'function listPluginStateInKeyRangeInWorker('),
 'dist/plugin-state.worker-Bt1nfP3u.mjs': ('function executePluginStateCommand(',),
 'dist/openclaw-state-db.paths-rJI64Ab5.mjs': ('function resolveOpenClawStateSqlitePath(',
                                               'resolveOpenClawStateSqlitePath as s')}

PROMOTION_WORKER_ROUTE = ('dist/infra/sqlite-store.worker.js', 'dist/state/openclaw-state.worker.js',
                          'dist/plugin-state.worker-Bt1nfP3u.mjs')
COMPILED_HASHES.update({
    'dist/infra/sqlite-store.worker.js': 'b6fb8b9d214bd7d35beb77849e1c44926d4963cacd9fc13af40f8c3b43374d69',
    'dist/state/openclaw-state.worker.js': '52fdb859d0add218690d0db4358fa5b2f2d2118379163eefb42a35c87f0715d4',
    'dist/openclaw-state-worker-store-DRKGvWWN.mjs': 'd567e4897230641cd70eeeade81cc6281c67bf76626e1fa7cfb19987ce0b73ca',
    'dist/openclaw-state-worker-store-Dy5-mnWx.mjs': '8f2ce584b66eec3ff3c876ddab18947e8af6b2a60fbbf3aeb3e020336410e407',
})
COMPILED_ANCHORS.update({
    'dist/infra/sqlite-store.worker.js': ('SQLite store worker requires its host port', 'async function receive('),
    'dist/state/openclaw-state.worker.js': ('function createSqliteWorkerBackend(',),
    'dist/openclaw-state-worker-store-DRKGvWWN.mjs': ('export { createOpenClawStateWorkerLease, executeOpenClawStateWorker,',),
    'dist/openclaw-state-worker-store-Dy5-mnWx.mjs': ('function createSharedStateWorkerOwner(',),
})
