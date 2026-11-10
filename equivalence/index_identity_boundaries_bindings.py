"""Authenticate original index-identity manager boundaries and official artifacts.

Declarations and import links supply provenance, not runtime or acceptance credit.
The source checkout and publisher's compiled release remain separate authorities;
no independently reproduced source build is claimed.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError
from equivalence.reuse_bindings import ReuseBindingError, _named
from equivalence.search_contract_runtime_bindings import (
    COMPILED_ANCHORS as SEARCH_COMPILED_ANCHORS,
    COMPILED_HASHES as SEARCH_COMPILED_HASHES,
    REFERENCE_COMMIT,
    SOURCE_ANCHORS as SEARCH_SOURCE_ANCHORS,
    SOURCE_HASHES as SEARCH_SOURCE_HASHES,
    SearchContractRuntimeBindingError,
    _owners,
    prepare_search_contract_runtime_bindings,
)

ADDITIONAL_SOURCE_HASHES = {'extensions/memory-core/runtime-api.ts': '9b7bbd261019d84c40ab9826b14020ac40d18e92010e1b21757d9383145a98f8',
 'extensions/memory-core/src/tools.runtime.ts': 'db0cca56eef6ad7b7cd6d56429d42529442a541ca0597f87be0603583e730fc5',
 'extensions/memory-core/src/memory/index.ts': 'efea33108241b8558b13082bf9742b86dee93c7d143ed8bd1cb097b11607136d',
 'extensions/memory-core/src/memory/search-manager.ts': 'c416ce10a435f0eaa8b3dbeae9158ea989b33de2aedf9a8816e52472bb2b1c23',
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': '5ec673cb42dc14662c6be1b4e405d4242f9a24cfa933e8200b98cb329227fb8c',
 'src/agents/memory-search.ts': 'a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'extensions/memory-core/src/memory/manager-registry.ts': '54f25cee8827b40510d34da84d6316481df1d6cf686264235ed45338a8dafb4f',
 'extensions/memory-core/src/memory/manager-database-context.ts': 'bf2006808241b2ed7c07636b49f447e44d1d2fcf1141a4c9d60744738d194bf8',
 'extensions/memory-core/src/memory/manager-sync-base.ts': '882b622e142cd05f06607f8e10162adb40731a8f797dba36f7f300383ddf6062',
 'extensions/memory-core/src/memory/manager-reindex-state.ts': '920dfbd46b3ac3f08ffa892642a4bb8474c779f22872107ccbf536a47f926044',
 'extensions/memory-core/src/memory/manager-retrieval-read.ts': '48076bc9ad42b4ba20daa0583f8a1160eaafa9b3ab575b8542666b2c80765f16',
 'extensions/memory-core/src/memory/manager-provider-lifecycle.ts': '128250bef2657f587c891ed833c32abd9ae66d387a9d40b2b9c89fa0cdd1df79',
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': '04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55',
 'extensions/memory-core/src/memory/manager-sync-ops.ts': '5e2732c67f5e07cbb545ec9aad4f7e40ac391561b0c645f68f5ce6e865dcbf18',
 'extensions/memory-core/src/memory/manager-db-kernel.ts': '4973db0580dc6dd7ac032a983efffa79ccb14fc4206f046b94c4250c7b5597ca',
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': 'b0bf466a54ee67705f5b7327a31c0013e9ee44a57117181ca5860c5ef90e30b5',
 'extensions/memory-core/src/memory/manager-publication.worker.ts': '4bbc2de8a1e50ea089a5de337fbb2eaa5c0352fef5e85bf532557698d8b59b86',
 'extensions/memory-core/src/memory/manager-index-preparation.ts': '208e5c367e6f5dd79f1837050404fe67a9f05ac8fa5e5ad1860c12f4a259e041',
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': '060ebff91bcc60a819551cb44e055597e778a0792bf041da18f4749afebe686c',
 'extensions/memory-core/src/memory/manager-search.worker.ts': 'b477fa182008d9aef544e0fa95d85cf5c731248ee492b60b15886f8b1b88931d',
 'extensions/memory-core/src/memory/manager-index.worker.ts': 'f68ee277284e834688a38993724a2844be65d581a05abd6455720f61d20452a7',
 'extensions/memory-core/src/memory/manager-index-generation-lease.ts': '0e41d89b8be1e702abbe8481520911ea9560b3b14fd9919cc3d4ea4ed07becc8',
 'src/plugin-sdk/memory-core-host-engine-storage.ts': '77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a',
 'packages/memory-host-sdk/src/engine-storage.ts': '8c9e64c08acf587dd3312f4df3a874b423bdc52ea85ff6fabdd1377e2ac12a2a',
 'packages/memory-host-sdk/src/host/types.ts': '737b555fc517671b927bcbab30334ffbd20c3690e02fa72595eeaacbddf06e4a'}
ADDITIONAL_SOURCE_ANCHORS = {'extensions/memory-core/runtime-api.ts': ('export { getMemorySearchManager } from '
                                           '"./src/memory/index.js";',),
 'extensions/memory-core/src/tools.runtime.ts': ('export { getMemorySearchManager } from '
                                                 '"./memory/index.js";',),
 'extensions/memory-core/src/memory/index.ts': ('  getMemorySearchManager,',),
 'extensions/memory-core/src/memory/search-manager.ts': ('export async function getMemorySearchManager(',),
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': ('  resolveMemorySearchConfig,',),
 'src/agents/memory-search.ts': ('export function resolveMemorySearchIndexConfig(',
                                 'export function resolveMemorySearchConfig(',
                                 'function resolveSyncConfig() {'),
 'extensions/memory-core/src/memory/manager.ts': ('  static async get(params: {',
                                                  '  private constructor(params: {',
                                                  '  status(): MemoryProviderStatus {',
                                                  '  private publishedStatus(): MemoryProviderStatus {'),
 'extensions/memory-core/src/memory/manager-registry.ts': ('export class MemoryManagerRegistry<T extends '
                                                           'ClosableMemoryManager> {',),
 'extensions/memory-core/src/memory/manager-database-context.ts': ('export class MemoryIndexDatabase {',),
 'extensions/memory-core/src/memory/manager-sync-base.ts': ('  protected '
                                                            'resolveCurrentIndexIdentityState(params?: {',
                                                            '  protected readMeta(): MemoryIndexMeta | '
                                                            'null {'),
 'extensions/memory-core/src/memory/manager-reindex-state.ts': ('export const '
                                                                'MEMORY_INDEX_PROVENANCE_VERSION = 1;',
                                                                'export function '
                                                                'resolveMemoryIndexIdentityState('),
 'extensions/memory-core/src/memory/manager-retrieval-read.ts': ('export function '
                                                                 'readMemoryIndexMetadata(db: '
                                                                 'DatabaseSync): {',
                                                                 'export function '
                                                                 'readMemoryRetrievalIndexState(db: '
                                                                 'DatabaseSync): MemoryRetrievalIndexState '
                                                                 '{'),
 'extensions/memory-core/src/memory/manager-provider-lifecycle.ts': ('  protected async '
                                                                     'ensureProviderInitialized(): '
                                                                     'Promise<void> {',
                                                                     '  protected async '
                                                                     'ensureEmbeddingProviderForSearch('),
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': ('  async search(query: string, '
                                                                       'opts?: MemoryIndexSearchOptions): '
                                                                       'Promise<MemorySearchResult[]> {',
                                                                       '      const shouldRepairIdentity '
                                                                       '='),
 'extensions/memory-core/src/memory/manager-sync-ops.ts': ('export abstract class MemoryManagerSyncOps '
                                                           'extends MemoryManagerSourceSyncOps {',),
 'extensions/memory-core/src/memory/manager-db-kernel.ts': ('export function '
                                                            'publishMemoryDatabaseTables(params: '
                                                            'MemoryDatabasePublication): void {',),
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': ('export class '
                                                                      'MemorySourceIndexKernel {',),
 'extensions/memory-core/src/memory/manager-publication.worker.ts': ('export function '
                                                                     'bindSqliteWorkerBackend(',),
 'extensions/memory-core/src/memory/manager-index-preparation.ts': ('export function '
                                                                    'prepareMemoryIndexChunks({',),
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': ('export async function '
                                                                     'runMemoryIndexState(',
                                                                     'export async function '
                                                                     'runMemoryKeywordSearch(',
                                                                     'export async function '
                                                                     'prepareMemoryIndexInWorker('),
 'extensions/memory-core/src/memory/manager-search.worker.ts': ('serveWorkerTasks(async (input): '
                                                                'Promise<MemorySearchWorkerOutput> => {',),
 'extensions/memory-core/src/memory/manager-index.worker.ts': ('serveWorkerTasks<MemoryIndexTaskResult>((input) '
                                                               '=> {',),
 'extensions/memory-core/src/memory/manager-index-generation-lease.ts': ('export async function '
                                                                         'acquireMemoryIndexReadGeneration(',),
 'src/plugin-sdk/memory-core-host-engine-storage.ts': ('  resolveMemoryIndexIdentityDiagnostic,',),
 'packages/memory-host-sdk/src/engine-storage.ts': ('  resolveMemoryIndexIdentityDiagnostic,',),
 'packages/memory-host-sdk/src/host/types.ts': ('export function resolveMemoryIndexIdentityDiagnostic(',
                                                'export function resolveMemoryIndexSearchDiagnostic(')}
ADDITIONAL_COMPILED_HASHES = {'dist/extensions/memory-core/runtime-api.js': '520c6cc05e74399c910425488cacd52867bb587434a36d33c8b90d11326d75ec',
 'dist/memory-CO0OCfyl.mjs': '428531446f314cd1d2a5214f78e849a1ae9f7fbd042d66b71505416e7fda9702',
 'dist/memory-search-CIhUURbE.mjs': 'e015aeaa8d8e062eb792ae58d2e4537e5b0f665ea97b946979e644444304a148',
 'dist/tools.runtime.js': '453b5423b3b47e05cf06608162ae184186d332c2042792bde427580cc73d5661',
 'dist/tools.runtime-m4sffzql.mjs': '0e3cca44ae9922d28e02779723a91f99889e6322a77daa4d9700bdcb4f816983',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/manager-search-DgMs3pkc.mjs': 'f97d896dac1037bc8aa96b3b8631cb3efba3ee361f4a8c02039bebc18f6184a0',
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': '9225fc056eb1db62970511129ce9843ffd467eb2d6f2b08500b63fd7854fbc45',
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': '6685d974f0ba1ca6e8aa0349658cfb5c427678230396dca00b4549c340ca7f1a',
 'dist/extensions/memory-core/memory-publication.worker.js': '1567321ec23f591b1d10c8d3291a60353af608658e769b7a6a427bad4f56378f',
 'dist/manager-publication.worker-x9zokjMA.mjs': 'd2b8540a1b29cd70cb21561b577382c9f73d353303f0795a9ba1c39e6f8c3b25',
 'dist/manager-db-kernel-DyJADqYu.mjs': 'b2af8c64d1450a503cecb97a96d37b3597340c6a68cc7c0231f98befc964bd99',
 'dist/manager-source-index-kernel-D-njga00.mjs': '762c8cecb4b1eae8ea90d96eb6ed2759f07fd970c9ef4b12344f5e14ef0745fc',
 'dist/manager-index-preparation-wXpJtJiU.mjs': '6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867',
 'dist/manager-index.worker-CinEDBkE.mjs': 'bf8a8a6d0185434fa48f31f82c27010deb8a3b96edf665c2e5d395a68e1b5b61',
 'dist/manager-search.worker-BWRvo8WR.mjs': '234abd2dd01f7ed01e2e94aa0f25f6cba402676fe7a6b308cfb6729b6c058e4f',
 'dist/types-DTVBdCzw.mjs': '14598f9947a85bf691d345dc54c32899c8931afc580e45f143918afe8b54db50'}
ADDITIONAL_COMPILED_ANCHORS = {'dist/extensions/memory-core/runtime-api.js': ('getMemorySearchManager,',),
 'dist/memory-CO0OCfyl.mjs': ('async function getMemorySearchManager(params) {',
                              'getMemorySearchManager as r'),
 'dist/memory-search-CIhUURbE.mjs': ('function resolveMemorySearchConfig(cfg, agentId) {',
                                     'function resolveSyncConfig() {'),
 'dist/tools.runtime.js': ('export * from "./tools.runtime-m4sffzql.mjs";',),
 'dist/tools.runtime-m4sffzql.mjs': ('export { getMemorySearchManager, readAgentMemoryFile, '
                                     'resolveMemoryBackendConfig };',),
 'dist/extensions/memory-core/manager-runtime.js': ('function resolveMemoryIndexIdentityState(params) {',
                                                    'resolveCurrentIndexIdentityState(params) {',
                                                    'publishedStatus() {'),
 'dist/manager-search-DgMs3pkc.mjs': ('function readMemoryIndexMetadata(db) {',
                                      'function readMemoryRetrievalIndexState(db) {'),
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': ('async function runMemoryIndexState(',
                                                  'async function runMemoryKeywordSearch('),
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': ('const memoryCpuProcessEntrypoints = {',),
 'dist/extensions/memory-core/memory-publication.worker.js': ('export { bindSqliteWorkerBackend, '
                                                              'openExistingSqliteWorkerBackend };',),
 'dist/manager-publication.worker-x9zokjMA.mjs': ('function bindSqliteWorkerBackend(input, context) {',),
 'dist/manager-db-kernel-DyJADqYu.mjs': ('function publishMemoryDatabaseTables(params) {',),
 'dist/manager-source-index-kernel-D-njga00.mjs': ('var MemorySourceIndexKernel = class {',),
 'dist/manager-index-preparation-wXpJtJiU.mjs': ('function prepareMemoryIndexChunks(',),
 'dist/manager-index.worker-CinEDBkE.mjs': ('serveWorkerTasks((input) => {',),
 'dist/manager-search.worker-BWRvo8WR.mjs': ('serveWorkerTasks(async (input) => {',),
 'dist/types-DTVBdCzw.mjs': ('function resolveMemoryIndexIdentityDiagnostic(status) {',
                             'function resolveMemoryIndexSearchDiagnostic(diagnostic, status, agentId) {')}


def _merged_anchors(original: dict, additional: dict) -> dict:
    return {path: tuple(dict.fromkeys((*original.get(path, ()), *additional.get(path, ()))))
            for path in dict.fromkeys((*original, *additional))}


SOURCE_HASHES = {**SEARCH_SOURCE_HASHES, **ADDITIONAL_SOURCE_HASHES}
SOURCE_ANCHORS = _merged_anchors(SEARCH_SOURCE_ANCHORS, ADDITIONAL_SOURCE_ANCHORS)
COMPILED_HASHES = {**SEARCH_COMPILED_HASHES, **ADDITIONAL_COMPILED_HASHES}
COMPILED_ANCHORS = _merged_anchors(SEARCH_COMPILED_ANCHORS, ADDITIONAL_COMPILED_ANCHORS)

REQUIRED_MAIN_ARTIFACTS = (
    *SEARCH_COMPILED_HASHES,
    "dist/extensions/memory-core/runtime-api.js",
    "dist/memory-CO0OCfyl.mjs", "dist/memory-search-CIhUURbE.mjs",
    "dist/tools.runtime.js", "dist/tools.runtime-m4sffzql.mjs",
    "dist/manager-search-DgMs3pkc.mjs", "dist/manager-cpu-worker-runtime-CAWQOyFu.mjs",
    "dist/manager-cpu-entrypoints-bJosRUx9.mjs", "dist/manager-db-kernel-DyJADqYu.mjs",
    "dist/manager-source-index-kernel-D-njga00.mjs",
    "dist/manager-index-preparation-wXpJtJiU.mjs",
)
REQUIRED_WORKER_ARTIFACTS = (
    "dist/extensions/memory-core/memory-publication.worker.js",
    "dist/manager-publication.worker-x9zokjMA.mjs", "dist/manager-db-kernel-DyJADqYu.mjs",
    "dist/manager-source-index-kernel-D-njga00.mjs", "dist/manager-index-preparation-wXpJtJiU.mjs",
    "dist/manager-index.worker-CinEDBkE.mjs", "dist/manager-search.worker-BWRvo8WR.mjs",
    "dist/manager-search-DgMs3pkc.mjs",
)
REQUIRED_LOADED_ARTIFACTS = tuple(dict.fromkeys((*REQUIRED_MAIN_ARTIFACTS,
                                               *REQUIRED_WORKER_ARTIFACTS)))


class IndexIdentityBoundariesBindingError(ValueError):
    """An original identity manager owner or official artifact changed."""


def prepare_index_identity_boundaries_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Pin original declarations and links; runtime observations supply behavior proof."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        inherited = prepare_search_contract_runtime_bindings(checkout, runtime_root)
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS,
                                       committed=False)
        chain = [
            *inherited["sourceImportLinks"],
            _named(sources, "extensions/memory-core/runtime-api.ts", "./src/memory/index.js",
                   ("getMemorySearchManager",), exact=True),
            _named(sources, "extensions/memory-core/src/tools.runtime.ts", "./memory/index.js",
                   ("getMemorySearchManager",), exact=True),
            _named(sources, "extensions/memory-core/src/memory/index.ts", "./search-manager.js",
                   ("closeAllMemorySearchManagers", "closeMemorySearchManager", "getMemorySearchManager"),
                   exact=True),
            _named(sources, "extensions/memory-core/src/memory/search-manager.ts",
                   "openclaw/plugin-sdk/memory-core-host-engine-foundation",
                   ("resolveAgentWorkspaceDir", "resolveMemorySearchConfig"), kind="import"),
            _named(sources, "src/plugin-sdk/memory-core-host-engine-foundation.ts",
                   "../agents/memory-search.js",
                   ("resolveMemorySearchConfig", "resolveMemorySearchSyncConfig"), exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-sync-base.ts",
                   "./manager-reindex-state.js",
                   ("resolveMemoryIndexIdentityState",), kind="import"),
            _named(sources, "extensions/memory-core/src/memory/manager-sync-base.ts",
                   "./manager-retrieval-read.js",
                   ("MEMORY_INDEX_META_KEY", "readMemoryIndexMetadata"), kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-search-orchestration.ts",
                   "./manager-index-generation-lease.js",
                   ("acquireMemoryIndexReadGeneration",), kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-search.worker.ts",
                   "./manager-retrieval-read.js",
                   ("readMemoryRetrievalIndexState", "readMemoryRecallData"), kind="import"),
            _named(sources, "extensions/memory-core/src/memory/manager-index.worker.ts",
                   "./manager-index-preparation.js", ("prepareMemoryIndexChunks",),
                   kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-publication.worker.ts",
                   "./manager-db-kernel.js", ("publishMemoryDatabaseTables", "readMemoryDatabaseRevision"),
                   kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory-search-tool-query.ts",
                   "openclaw/plugin-sdk/memory-core-host-engine-storage",
                   ("resolveMemoryIndexIdentityDiagnostic", "resolveMemoryIndexSearchDiagnostic"),
                   kind="import"),
            _named(sources, "src/plugin-sdk/memory-core-host-engine-storage.ts",
                   "../../packages/memory-host-sdk/src/engine-storage.js",
                   ("resolveMemoryIndexIdentityDiagnostic", "resolveMemoryIndexSearchDiagnostic")),
            _named(sources, "packages/memory-host-sdk/src/engine-storage.ts", "./host/types.js",
                   ("resolveMemoryIndexIdentityDiagnostic", "resolveMemoryIndexSearchDiagnostic")),
        ]
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError,
            SearchContractRuntimeBindingError) as error:
        raise IndexIdentityBoundariesBindingError(
            "Index identity boundary declarations or original import links could not be authenticated."
        ) from error
    return {
        "kind": "official-release-index-identity-boundary-owner",
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "constructorSkipped": False, "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoints": {
            "publicManagerFacade": {"path": "dist/extensions/memory-core/runtime-api.js",
                                    "export": "getMemorySearchManager"},
            "manager": {"path": "dist/extensions/memory-core/manager-runtime.js",
                        "export": "MemoryIndexManager",
                        "methods": ["get", "status", "sync", "search", "close"]},
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemorySearchTool"},
        },
        "requiredLoadedArtifactsByProfile": {
            "index-identity-boundaries-runtime": list(REQUIRED_LOADED_ARTIFACTS)},
        "requiredMainArtifacts": list(REQUIRED_MAIN_ARTIFACTS),
        "requiredWorkerArtifacts": list(REQUIRED_WORKER_ARTIFACTS),
        "workerRequiredByProfile": {"index-identity-boundaries-runtime": True},
        "fixtureBoundary": "The real CLI producer publishes before a declared metadata fixture. "
                           "Original status and default-manager/facade owners then expose complete "
                           "identity diagnostics before the caller's first public memory_search. "
                           "The genuine public tool retains every result, warning/action and debug field; "
                           "full engine-specific statuses and physical SQL snapshots stay in custody. "
                           "Actual resolved sync/watch policies are retained rather than replaced by "
                           "ignored input knobs. The source, official compiled artifact and runtime "
                           "capture authorities remain distinct.",
        "limits": [
            "Declaration and import authentication alone proves neither execution nor acceptance.",
            "Worker artifacts can load during producer setup; loading them alone proves no query admission.",
            "A paused public result does not imply zero manager dispatch: valid formal queries still "
            "call the original manager and can read before paused-result finalization.",
            "Pre-caller-query diagnostics do not claim that no speculative internal SQL query occurred.",
            "Provider-none metadata cases do not establish semantic provider or endpoint discovery parity.",
            "Physical SQLite encodings and complete host lifecycle parity are not claimed.",
        ],
    }
