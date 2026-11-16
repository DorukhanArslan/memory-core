"""Authenticate genuine embedding-cache manager, provider and worker owners.

Static declarations grant no behavioral credit. Official compiled bytes and
committed-source authentication are separate; no reproduced build is claimed.
"""
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'extensions/memory-core/src/memory/manager-runtime.ts': '0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'extensions/memory-core/src/memory/manager-embedding-cache.ts': '75fb4853466385740e4150d247797516e4c7698896fb63e6acb3c546faea5f09',
 'extensions/memory-core/src/memory/manager-embedding-ops.ts': 'd48ee54c3081385116757671cfa71fefb1187dcad688f9a985c704f550118a3f',
 'extensions/memory-core/src/memory/manager-embedding-policy.ts': '6f07d3b1b0998003cc9ab450d14da4f666d9653a797f8d12f7363b679f502823',
 'extensions/memory-core/src/memory/manager-provider-lifecycle.ts': '128250bef2657f587c891ed833c32abd9ae66d387a9d40b2b9c89fa0cdd1df79',
 'extensions/memory-core/src/memory/manager-reindex-state.ts': '920dfbd46b3ac3f08ffa892642a4bb8474c779f22872107ccbf536a47f926044',
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': '04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55',
 'extensions/memory-core/src/memory/manager-source-sync-ops.ts': 'bc6a8fba716ffe3bd6cb130b3e415a057982b84a494ded95429acf7d7721e4b1',
 'extensions/memory-core/src/memory/manager-sync-ops.ts': '5e2732c67f5e07cbb545ec9aad4f7e40ac391561b0c645f68f5ce6e865dcbf18',
 'extensions/memory-core/src/memory/manager-sync-base.ts': '882b622e142cd05f06607f8e10162adb40731a8f797dba36f7f300383ddf6062',
 'extensions/memory-core/src/memory/manager-database-context.ts': 'bf2006808241b2ed7c07636b49f447e44d1d2fcf1141a4c9d60744738d194bf8',
 'extensions/memory-core/src/memory/manager-db-kernel.ts': '4973db0580dc6dd7ac032a983efffa79ccb14fc4206f046b94c4250c7b5597ca',
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': 'b0bf466a54ee67705f5b7327a31c0013e9ee44a57117181ca5860c5ef90e30b5',
 'extensions/memory-core/src/memory/manager-index-preparation.ts': '208e5c367e6f5dd79f1837050404fe67a9f05ac8fa5e5ad1860c12f4a259e041',
 'extensions/memory-core/src/memory/manager-index.worker.ts': 'f68ee277284e834688a38993724a2844be65d581a05abd6455720f61d20452a7',
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': '060ebff91bcc60a819551cb44e055597e778a0792bf041da18f4749afebe686c',
 'extensions/memory-core/src/memory/manager-cpu-entrypoints.ts': '20a5b2b2c957b7ba23518093e539f78066bacad520610acc58806e3cb5fcf2a9',
 'extensions/memory-core/src/memory/embeddings.ts': '8f9972dcd7ab11adef532d23e22f497e07d96b8972bc77ce99c8a00e8a2b407b',
 'src/agents/memory-search.ts': 'a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2',
 'src/plugins/embedding-provider-types.ts': '167d7c191da2bb7e5f759372ba83869c1744842cb99268f95e3e35d2f0cc130d',
 'src/plugins/embedding-provider-runtime.ts': '2c079f9978ce21c12961100717a345bf64d4c054f95ed2158a575c5e7c0514fd',
 'src/plugins/embedding-providers.ts': '626d609ea69e9e5a1ec62caf9232c75fc1da4d07e0b92fcaa765f8f1dd9c444c',
 'src/plugins/memory-embedding-provider-runtime.ts': '67e88498c09bd81bcb6f7ca8ea1ed3568468e34f880e14bd7d3b724e1b7de555',
 'src/plugins/registry.ts': '4f49793315d848868dfa7c5b517f08f52ff3e7b04ec0ff2186047ed7a30ee4bc',
 'src/plugins/registry-api.ts': '3b4e9764baeba09913b081379441359af0c8d07514c36dd2e6429ab851f02132',
 'src/plugins/registry-registrars-providers.ts': '733573da4c79ed26ec110aacdc26f7894269304f54ab286500249772f8cced6d',
 'src/plugins/registry-empty.ts': '8512baea357321aa7743f43dfb76c75fe1397ce752f2794d112d23e2baa7ef2e',
 'src/plugins/runtime.ts': '2e0b61b8902f3dc16b8b427c96bfa61d7a0b65d2386952e44f5ac7aec5f77172',
 'src/plugins/plugin-metadata-snapshot.ts': 'e7e329a73d5c84fc4a368b58ded7de1a9cfacdb1d23b83e763b6d3188037f957',
 'src/plugins/loader.ts': '04f30e7b07d329c059290a6a666f0e5b797a956f6b9ba44213cbd3e31b1e831d',
 'src/plugins/loader-runtime-load.ts': 'ea1d0c49308736d8fd75316ed612483c9dfb89ad0966ed32a3e0f0beb46c8409',
 'packages/memory-host-sdk/src/host/embedding-vector.ts': '515e3d73f9e6adff455f6f3db477d253fac0a10e44b53179d47683d101068de9',
 'packages/memory-host-sdk/src/host/memory-schema.ts': '4c7bc3e66b22298f21fc43e0a7f002f9cd64825e70c395f45135cfee1973f57d',
 'src/infra/runtime-worker-url.ts': '9b694a778a84725e989ad2380195557993afbf25dc97e64112f7a65b2a2087e0',
 'src/infra/worker-task-pool.ts': 'fcaafd845ed8a9285ea385a05a4324e01a6c5bfc29a5fca99b69705054be8bca'}

SOURCE_ANCHORS = {'extensions/memory-core/src/memory/manager-runtime.ts': ('export { MemoryIndexManager };',
                                                          'export async function '
                                                          'closeAllMemoryIndexManagers()'),
 'extensions/memory-core/src/memory/manager.ts': ('export class MemoryIndexManager extends',
                                                  '  static async get(params: {'),
 'extensions/memory-core/src/memory/manager-embedding-cache.ts': ('export function '
                                                                  'loadMemoryEmbeddingCache(params: {',
                                                                  'export function '
                                                                  'upsertMemoryEmbeddingCache(params: {',
                                                                  'export function '
                                                                  'collectMemoryCachedEmbeddings<'),
 'extensions/memory-core/src/memory/manager-embedding-ops.ts': ('export abstract class '
                                                                'MemoryManagerEmbeddingOps',
                                                                '  protected async embedBatchWithRetry(',
                                                                '  protected async embedQueryWithRetry('),
 'extensions/memory-core/src/memory/manager-embedding-policy.ts': ('export function '
                                                                   'buildMemoryEmbeddingBatches<',
                                                                   'export async function '
                                                                   'runMemoryEmbeddingBatchRetryWithSplit<'),
 'extensions/memory-core/src/memory/manager-provider-lifecycle.ts': ('export abstract class '
                                                                     'MemoryProviderLifecycle',
                                                                     '  protected async '
                                                                     'ensureProviderInitialized()'),
 'extensions/memory-core/src/memory/manager-reindex-state.ts': ('export function '
                                                                'resolveMemoryIndexProviderIdentities(params: '
                                                                '{',),
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': ('export abstract class '
                                                                       'MemorySearchOrchestration',),
 'extensions/memory-core/src/memory/manager-source-sync-ops.ts': ('export abstract class '
                                                                  'MemoryManagerSourceSyncOps',),
 'extensions/memory-core/src/memory/manager-sync-ops.ts': ('export abstract class MemoryManagerSyncOps',),
 'extensions/memory-core/src/memory/manager-sync-base.ts': ('export abstract class MemoryManagerSyncBase',),
 'extensions/memory-core/src/memory/manager-database-context.ts': ('export class MemoryIndexDatabase {',),
 'extensions/memory-core/src/memory/manager-db-kernel.ts': ('export function publishMemoryDatabaseTables(',),
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': ('export class MemorySourceIndexKernel '
                                                                      '{',),
 'extensions/memory-core/src/memory/manager-index-preparation.ts': ('export function '
                                                                    'prepareMemoryIndexChunks({',),
 'extensions/memory-core/src/memory/manager-index.worker.ts': ('serveWorkerTasks<MemoryIndexTaskResult>((input)',),
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': ('export async function '
                                                                     'prepareMemoryIndexInWorker(',),
 'extensions/memory-core/src/memory/manager-cpu-entrypoints.ts': ('export const memoryCpuProcessEntrypoints '
                                                                  '= {',),
 'extensions/memory-core/src/memory/embeddings.ts': ('export function resolveEmbeddingProviderIndexIdentity(',
                                                     'export async function createEmbeddingProvider('),
 'src/agents/memory-search.ts': ('export function resolveMemorySearchConfig(',),
 'src/plugins/embedding-provider-types.ts': ('export type EmbeddingProviderAdapter = {',),
 'src/plugins/embedding-provider-runtime.ts': ('export function getEmbeddingProvider(',),
 'src/plugins/embedding-providers.ts': ('export function listRegisteredEmbeddingProviders()',),
 'src/plugins/memory-embedding-provider-runtime.ts': ('export function getMemoryEmbeddingProvider(',),
 'src/plugins/registry.ts': ('export function createPluginRegistry(',),
 'src/plugins/registry-api.ts': ('export function createPluginApiFactory(',),
 'src/plugins/registry-registrars-providers.ts': ('export function createProviderRegistrars(',
                                                  '  const registerEmbeddingProvider = ('),
 'src/plugins/registry-empty.ts': ('export function createEmptyPluginRegistry()',),
 'src/plugins/runtime.ts': ('export function setActivePluginRegistry(',),
 'src/plugins/plugin-metadata-snapshot.ts': ('export function loadPluginMetadataSnapshot(',),
 'src/plugins/loader.ts': ('export function loadAndActivateRootPluginRegistry(',),
 'src/plugins/loader-runtime-load.ts': ('export function loadOpenClawPlugins(',),
 'packages/memory-host-sdk/src/host/embedding-vector.ts': ('export function encodeMemoryEmbedding(',
                                                           'export function decodeMemoryEmbedding('),
 'packages/memory-host-sdk/src/host/memory-schema.ts': ('export function ensureMemoryIndexSchema(',),
 'src/infra/runtime-worker-url.ts': ('export function resolveRuntimeWorkerUrl(',),
 'src/infra/worker-task-pool.ts': ('export class WorkerTaskPool<',)}

COMPILED_HASHES = {'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/plugin-sdk/config-runtime.js': 'ca8ea03ec6a8eeb48c4f300f7a88171aba943e6999a40791205d0027bd1d2a18',
 'dist/plugin-metadata-snapshot-DT_pRp6g.mjs': '4236d6b46e5044178b8f938eedd2edbd129f1bfd42e9467d49f1cc49dbcb82b9',
 'dist/loader-DpAS3szV.mjs': '8f7973dc6048dff4a775f32b21fdc78d3a38dd73639a478404ed2bc078356106',
 'dist/loader-runtime-load-DpgEqnzx.mjs': '3c30c5d43fb3cd19525853bb6b756cf45cfd05f5da32a732dc129b85cb309787',
 'dist/runtime-9cxii0oQ.mjs': '9f18ed5dbca908c9a71f126d08f09bcfed73e93d80efe9e668fecb5a6e568356',
 'dist/registry-empty-BTjzcMW2.mjs': '11afb0f560f5b31d2785a5b4381d05639862e748a1220370364657d8b4333698',
 'dist/embeddings-C7iNQrWO.mjs': '579afe2c447af15a5d2ecf061565eebf0611b797ca6161c184f2985579680b91',
 'dist/memory-search-CIhUURbE.mjs': 'e015aeaa8d8e062eb792ae58d2e4537e5b0f665ea97b946979e644444304a148',
 'dist/memory-embedding-provider-runtime-q4kxVgoB.mjs': '776e955c685380b74c5cfbbde2657e665daf8344ff2e96cd58159a8ce97c5efc',
 'dist/embedding-provider-runtime-BURKvPES.mjs': 'f118b8d7a68296a2c1ff9dfe22d248b11e4716428b989038f8345ef94736907e',
 'dist/embedding-vector-CGPWflQ5.mjs': 'cf7b100f10b60ef0d820e89c60852681561015c14a40cde91dafeb56ec0802b5',
 'dist/memory-schema-SE7C0M3V.mjs': '131ec423f55c59ea6461e71ae2a220b3192809d1737680c08e065c9e841f6a7b',
 'dist/manager-db-kernel-DyJADqYu.mjs': 'b2af8c64d1450a503cecb97a96d37b3597340c6a68cc7c0231f98befc964bd99',
 'dist/manager-index-preparation-wXpJtJiU.mjs': '6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867',
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': '9225fc056eb1db62970511129ce9843ffd467eb2d6f2b08500b63fd7854fbc45',
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': '6685d974f0ba1ca6e8aa0349658cfb5c427678230396dca00b4549c340ca7f1a',
 'dist/runtime-worker-url-S0NIVxUR.mjs': '49585b6cc537babf6c8e4f795c709e3b109af37b3df46161afcf593b506a136b',
 'dist/worker-task-pool-BQlnRNqZ.mjs': '79ea82aa29baa5d72f600d5191ee4a3a0bd62fed0062cc8da96877cf334ccf2d',
 'dist/extensions/memory-core/memory-index.worker.js': '740d4ac59fd01308335d9f725f2c83cc6565178d428844a1ca5cd2d792a3b27d',
 'dist/manager-index.worker-CinEDBkE.mjs': 'bf8a8a6d0185434fa48f31f82c27010deb8a3b96edf665c2e5d395a68e1b5b61'}

COMPILED_ANCHORS = {'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = class MemoryIndexManager',
                                                    'function loadMemoryEmbeddingCache(params) {',
                                                    'function upsertMemoryEmbeddingCache(params) {',
                                                    'async embedBatchWithRetry(',
                                                    'async embedQueryWithRetry('),
 'dist/plugin-sdk/config-runtime.js': ('import { D as setRuntimeConfigSnapshot',),
 'dist/plugin-metadata-snapshot-DT_pRp6g.mjs': ('function loadPluginMetadataSnapshot(',),
 'dist/loader-DpAS3szV.mjs': ('function loadAndActivateRootPluginRegistry(',),
 'dist/loader-runtime-load-DpgEqnzx.mjs': ('function loadOpenClawPlugins(options = {}) {',
                                           'function createPluginRegistry(registryParams) {'),
 'dist/runtime-9cxii0oQ.mjs': ('function setActivePluginRegistry(',),
 'dist/registry-empty-BTjzcMW2.mjs': ('function createEmptyPluginRegistry()',),
 'dist/embeddings-C7iNQrWO.mjs': ('async function createEmbeddingProvider(',
                                  'function resolveEmbeddingProviderIndexIdentity('),
 'dist/memory-search-CIhUURbE.mjs': ('function resolveMemorySearchConfig(',),
 'dist/memory-embedding-provider-runtime-q4kxVgoB.mjs': ('function getMemoryEmbeddingProvider(',),
 'dist/embedding-provider-runtime-BURKvPES.mjs': ('function getEmbeddingProvider(',),
 'dist/embedding-vector-CGPWflQ5.mjs': ('function encodeMemoryEmbedding(', 'function decodeMemoryEmbedding('),
 'dist/memory-schema-SE7C0M3V.mjs': ('function ensureMemoryIndexSchema(',),
 'dist/manager-db-kernel-DyJADqYu.mjs': ('function publishMemoryDatabaseTables(',),
 'dist/manager-index-preparation-wXpJtJiU.mjs': ('function prepareMemoryIndexChunks(',),
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': ('async function prepareMemoryIndexInWorker(',),
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': ('const memoryCpuProcessEntrypoints = {',),
 'dist/runtime-worker-url-S0NIVxUR.mjs': ('function resolveRuntimeWorkerUrl(',),
 'dist/worker-task-pool-BQlnRNqZ.mjs': ('var WorkerTaskPool = class',),
 'dist/extensions/memory-core/memory-index.worker.js': ('import "../../manager-index.worker-CinEDBkE.mjs";',),
 'dist/manager-index.worker-CinEDBkE.mjs': ('serveWorkerTasks((input) => {',)}

SOURCE_HASHES.update({
    "packages/memory-host-sdk/src/host/hash.ts": "face88c71f4d752c24052ab299771ddf55c1c54d76ed2ebac8618a7812818683",
    "src/plugins/core-embedding-providers.ts": "8a89dff7cbc8fba7dc7965065e202e3566e5f0e119dbc7b14ccef87676caee41",
    "src/plugins/openai-compatible-embedding-provider.ts": "8a065497f6b065f68e4c2afbcdda3e6b2b582b817aa1a86049ae2aed419fb6ef",
    "src/state/openclaw-agent-db-lifecycle.ts": "a49e35f38d6584969d28183cec435581b6a6797bd4b4eaf3f7b5d7507429b16c",
})
SOURCE_ANCHORS.update({
    "packages/memory-host-sdk/src/host/hash.ts": ("export function hashText(value: string): string {",),
    "src/plugins/core-embedding-providers.ts": (
        "export const CORE_EMBEDDING_PROVIDERS: RegisteredEmbeddingProvider[] = [",
        "    adapter: openAICompatibleEmbeddingProviderAdapter,",
    ),
    "src/plugins/openai-compatible-embedding-provider.ts": (
        'const OPENAI_COMPATIBLE_EMBEDDING_PROVIDER_ID = "openai-compatible";',
    ),
    "src/state/openclaw-agent-db-lifecycle.ts": ("export async function closeOpenClawAgentDatabasesAsync(",),
})
SOURCE_ANCHORS["extensions/memory-core/src/memory/manager-embedding-ops.ts"] += (
    "function resolveMemoryIndexConcurrency(params: {",
    "  protected getIndexConcurrency(): number {",
)
COMPILED_HASHES["dist/hash-CAMhNIP1.mjs"] = "579f6261976a154cace3a4aa3b3aa638fccb1c0d73f2a42a96dec3694e781dc8"
COMPILED_ANCHORS["dist/hash-CAMhNIP1.mjs"] = ("function hashText(value) {", "export { hashText as t };")
COMPILED_HASHES["dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs"] = "ece2b2b08f3e03c8ddb3dc70e29265f23c6b3df52e37e981e79a6bbd424a5a84"
COMPILED_ANCHORS["dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs"] = (
    "async function closeOpenClawAgentDatabasesAsync(rootPath) {",
    "closeOpenClawAgentDatabasesAsync as s",
)
COMPILED_ANCHORS["dist/extensions/memory-core/manager-runtime.js"] += (
    "function resolveMemoryIndexConcurrency(params) {", "\tgetIndexConcurrency() {",
)

# The original loader creates a host-package symlink inside its owned capture.
# Authenticate that precise observational exception without following the link.
SOURCE_HASHES.update({
    "src/plugins/plugin-source-capture-path.ts": "2065e6365ff5f9137c978c5eed61f4c7984c520d9250fd810bdb3cc7124a7017",
    "src/plugins/plugin-source-capture-directory.ts": "29affbbf41a67b3e20dd82f4d3bfeb5d61cd0df74926497e15cb06708b49ad7f",
    "src/plugins/plugin-package-metadata-capture.ts": "77536e78285935095eecc815fd4b1df61895614001f03e0f3df0c5b63d8a5690",
})
SOURCE_ANCHORS.update({
    "src/plugins/plugin-source-capture-path.ts": (
        'export const PLUGIN_SOURCE_CAPTURE_PREFIX = "openclaw-plugin-build-";',
        "export function resolvePluginSourceCapturesDirectory(stateDir: string): string {"),
    "src/plugins/plugin-source-capture-directory.ts": (
        "export function retainPluginSourceCaptureInstance(stateDir?: string) {",
        "    createDirectory(prefix = PLUGIN_SOURCE_CAPTURE_PREFIX) {"),
    "src/plugins/plugin-package-metadata-capture.ts": (
        "export function createPluginSourceCapture(execute?: <T>(run: () => T) => T) {",
        '      fs.symlinkSync(hostRoot, path.join(modules, "openclaw"), "junction");'),
})

# The genuine manager's publication path takes the memory workspace lease.
# Authenticate the configuration/open/close bridge directly. Its transitive
# worker artifact bytes remain covered by the complete release manifest.
SOURCE_HASHES.update({
    "extensions/memory-core/src/dreaming-state.ts": "b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458",
    "extensions/memory-core/src/memory-workspace-lock.ts": "557bf3bdb03a8139af1c3fe40d106b3fb74e8ad20c30969bd888a7bccf25beb2",
    "src/plugin-state/plugin-state-store.ts": "361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530",
    "src/plugin-state/plugin-state-store.sqlite.ts": "5c8a00ecd21695bb20acac0be92d0477a9a5533f1795f7b0ee153c1e462a5498",
})
SOURCE_ANCHORS.update({
    "extensions/memory-core/src/dreaming-state.ts": (
        "export function configureMemoryCoreDreamingState(",
        "export function openMemoryCoreStateStore<T>("),
    "extensions/memory-core/src/memory-workspace-lock.ts": (
        "export async function withMemoryWorkspaceLock<T>(",
        "async function acquireMemoryWorkspaceLock(",
        "      const observation = await lockStore.observe(lockKey);"),
    "src/plugin-state/plugin-state-store.ts": (
        "export function createPluginStateKeyedStore<T>(",
        "      const observation = await observePluginStateInWorker({"),
    "src/plugin-state/plugin-state-store.sqlite.ts": (
        "export async function closePluginStateDatabaseAsync()",),
})
COMPILED_HASHES.update({
    "dist/dreaming-state-VYUvbU-n.mjs": "8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c",
    "dist/plugin-state-store-BPUaLoVD.mjs": "4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc",
})
COMPILED_ANCHORS.update({
    "dist/dreaming-state-VYUvbU-n.mjs": (
        "function configureMemoryCoreDreamingState(", "configureMemoryCoreDreamingState as p",
        "function openMemoryCoreStateStore(", "openMemoryCoreStateStore as v"),
    "dist/plugin-state-store-BPUaLoVD.mjs": (
        "function createPluginStateKeyedStore(", "createPluginStateKeyedStore as r",
        "async function closePluginStateDatabaseAsync(", "closePluginStateDatabaseAsync as u"),
})

# The cache kernel is inlined in the genuine manager runtime in this release.
# No unused standalone cache-kernel artifact is required to execute.
REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED_HASHES)
GENUINE_HELPER_EXPORTS = {
    "dist/extensions/memory-core/manager-runtime.js": ("MemoryIndexManager", "closeAllMemoryIndexManagers"),
    "dist/plugin-metadata-snapshot-DT_pRp6g.mjs": ("o",),
    "dist/loader-DpAS3szV.mjs": ("t",),
    "dist/runtime-9cxii0oQ.mjs": ("w",),
    "dist/registry-empty-BTjzcMW2.mjs": ("t",),
    "dist/plugin-sdk/config-runtime.js": ("setRuntimeConfigSnapshot", "clearRuntimeConfigSnapshot"),
    "dist/embedding-vector-CGPWflQ5.mjs": ("n",),
    "dist/hash-CAMhNIP1.mjs": ("t",),
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs": ("s",),
    "dist/dreaming-state-VYUvbU-n.mjs": ("p", "v"),
    "dist/plugin-state-store-BPUaLoVD.mjs": ("r", "u"),
}
REQUIRED_WORKER_ROUTE = (
    "dist/extensions/memory-core/memory-index.worker.js",
    "dist/manager-index.worker-CinEDBkE.mjs",
    "dist/manager-index-preparation-wXpJtJiU.mjs",
)


def prepare_embedding_cache_lifecycle_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Check exact source/artifact bytes without importing or running an owner."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Embedding cache lifecycle requires the exact pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    prefix = "extensions/memory-core/src/memory/"
    links = (
        (prefix + "manager-embedding-ops.ts", "./manager-embedding-cache.js",
         ("loadMemoryEmbeddingCache", "upsertMemoryEmbeddingCache", "collectMemoryCachedEmbeddings")),
        (prefix + "manager-embedding-ops.ts", "./manager-embedding-policy.js",
         ("buildMemoryEmbeddingBatches", "runMemoryEmbeddingBatchRetryWithSplit", "runMemoryEmbeddingRetryLoop")),
        (prefix + "manager-provider-lifecycle.ts", "./embeddings.js", ("createEmbeddingProvider",)),
        (prefix + "manager-embedding-ops.ts", "./manager-cpu-worker-runtime.js", ("prepareMemoryIndexInWorker",)),
        ("src/plugins/embedding-provider-runtime.ts", "./embedding-providers.js",
         ("getRegisteredEmbeddingProvider", "listRegisteredEmbeddingProviders")),
        ("src/plugins/registry.ts", "./registry-api.js", ("createPluginApiFactory",)),
    )
    return {
        "kind": "official-release-embedding-cache-lifecycle-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                              for module, specifier, names in links],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "requiredWorkerRoute": list(REQUIRED_WORKER_ROUTE),
        "genuineHelperExports": {name: list(exports) for name, exports in GENUINE_HELPER_EXPORTS.items()},
        "genuineManagerMethods": ["getIndexConcurrency"],
        "provider": "deterministic-embedding-fixture", "managerConstructed": True, "worker": True,
        "providerTransport": "Original plugin registration and manager provider orchestration; instrumented callback embedder",
        "cacheOwner": "Original manager-inlined cache identity, reuse, validation, batching and retry owners",
        "publicBoundary": "Complete durable cache, effective identity and all query/document embedding callback receipts",
        "rawBoundary": "Original calls/returns/errors, source facts, complete SQL and protected process/worker traces",
        "clockFixture": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "acceptancePointsAwarded": 0, "covers": [],
    }
