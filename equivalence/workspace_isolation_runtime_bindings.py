"""Pin the original workspace, manager, recall and maintenance-state owners."""
from __future__ import annotations

from pathlib import Path
from equivalence.get_contract_runtime_bindings import _owners
from equivalence.reference_bindings import _git
from equivalence.reuse_bindings import _named

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'packages/memory-host-sdk/src/host/config-utils.ts': '670063dd2236bd0340950d19accb55b022efcaee7be1275491777c5a1f65fa53',
 'src/agents/agent-scope.ts': 'ef187176518fe241b49b205693cd70dc877e61fabe65e720013b0cf31f43beb7',
 'src/agents/agent-scope-config.ts': '97afbaa31c3014db8ac76550907e25b60b449052aee03a7591917391c768b245',
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': '5ec673cb42dc14662c6be1b4e405d4242f9a24cfa933e8200b98cb329227fb8c',
 'src/agents/memory-search.ts': 'a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'extensions/memory-core/src/memory/manager-registry.ts': '54f25cee8827b40510d34da84d6316481df1d6cf686264235ed45338a8dafb4f',
 'extensions/memory-core/src/memory/manager-index.worker.ts': 'f68ee277284e834688a38993724a2844be65d581a05abd6455720f61d20452a7',
 'packages/memory-host-sdk/src/host/internal.ts': 'f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591',
 'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/short-term-promotion-record.ts': 'b8d168519af14de5ae793d6738d3a86d51e41cdcc12cbd5b22fb174ba108d8c7',
 'extensions/memory-core/src/short-term-promotion-store.ts': '556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84',
 'extensions/memory-core/src/dreaming-state.ts': 'b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
 'extensions/memory-core/src/dreaming-ingestion-state.ts': '1d4fca365fa88ef871766adccb85bface2aaff04e4ed54ce996f187ae5150905',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530'}

SOURCE_ANCHORS = {'packages/memory-host-sdk/src/host/config-utils.ts': ('export function '
                                                       'resolveMemoryHostAgentWorkspaceDir(',),
 'src/agents/agent-scope.ts': ('  AgentSelectionRequiredError,\n  hasAgentRosterProperty,',),
 'src/agents/agent-scope-config.ts': ('export function '
                                      'resolveAgentWorkspaceDir(',),
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': ('  '
                                                          'resolveAgentWorkspaceDir,',),
 'src/agents/memory-search.ts': ('export function resolveMemorySearchConfig(',),
 'extensions/memory-core/src/memory/manager.ts': ('export class '
                                                  'MemoryIndexManager ',),
 'extensions/memory-core/src/memory/manager-registry.ts': ('export function '
                                                           'resolveMemoryIndexManagerCacheKey(',),
 'extensions/memory-core/src/memory/manager-index.worker.ts': ('serveWorkerTasks<MemoryIndexTaskResult>',),
 'packages/memory-host-sdk/src/host/internal.ts': ('export async function '
                                                   'listMemoryFiles(',),
 'extensions/memory-core/src/tools.ts': ('export function '
                                         'createMemorySearchTool(',
                                         'export function '
                                         'createMemoryGetTool('),
 'extensions/memory-core/src/short-term-promotion-record.ts': ('export async '
                                                               'function '
                                                               'recordShortTermRecalls(',),
 'extensions/memory-core/src/short-term-promotion-store.ts': ('export async '
                                                              'function '
                                                              'readStore(',),
 'extensions/memory-core/src/dreaming-state.ts': ('export function '
                                                  'configureMemoryCoreDreamingState(',
                                                  'export async function '
                                                  'writeMemoryCoreWorkspaceEntries('),
 'extensions/memory-core/src/dreaming-ingestion-state.ts': ('export async '
                                                            'function '
                                                            'readDailyIngestionState(',
                                                            'export async '
                                                            'function '
                                                            'writeDailyIngestionState('),
 'src/plugin-state/plugin-state-store.ts': ('export function '
                                            'createPluginStateKeyedStore<T>(',)}

COMPILED_HASHES = {'dist/plugin-sdk/memory-core-host-engine-foundation.js': '27ff3f35b0dc503742ea5cd7010d2b7953fe6adfff19138a752a68b49848c33c',
 'dist/config-utils-DioOBKyj.mjs': '7b740e863ffb8357ca58d856977d938d14415fb59747a909d87003be04ee1543',
 'dist/agent-scope-config-Dm6T00l4.mjs': '046526ee2ad580faaa1a3a3d7bf21b2f29acac5ed58863ab8e4035d91b39088a',
 'dist/memory-search-CIhUURbE.mjs': 'e015aeaa8d8e062eb792ae58d2e4537e5b0f665ea97b946979e644444304a148',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/short-term-promotion-record-DrLa1fiO.mjs': '26a083e3c17cd6512af9785266c7bdffe459cd02591be4127004efe7eb8887c7',
 'dist/short-term-promotion-store-B6T388Bo.mjs': '704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8',
 'dist/dreaming-state-VYUvbU-n.mjs': '8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
 'dist/dreaming-ingestion-state-licbtf_y.mjs': '91904fa3331423770d712029fa2863d0e30279a33d8b8b9486ab630281ff31e3',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
 'dist/extensions/memory-core/memory-index.worker.js': '740d4ac59fd01308335d9f725f2c83cc6565178d428844a1ca5cd2d792a3b27d',
 'dist/manager-index.worker-CinEDBkE.mjs': 'bf8a8a6d0185434fa48f31f82c27010deb8a3b96edf665c2e5d395a68e1b5b61'}

COMPILED_ANCHORS = {'dist/plugin-sdk/memory-core-host-engine-foundation.js': ('from '
                                                           '"../agent-scope-config-Dm6T00l4.mjs";',),
 'dist/config-utils-DioOBKyj.mjs': ('function '
                                    'resolveMemoryHostAgentWorkspaceDir(',
                                    'resolveMemoryHostAgentWorkspaceDir as i,'),
 'dist/agent-scope-config-Dm6T00l4.mjs': ('function resolveAgentWorkspaceDir(',
                                          'resolveAgentWorkspaceDir as d,'),
 'dist/memory-search-CIhUURbE.mjs': ('function resolveMemorySearchConfig(',),
 'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = '
                                                    'class '
                                                    'MemoryIndexManager ',),
 'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(',
                             'function createMemoryGetTool('),
 'dist/short-term-promotion-record-DrLa1fiO.mjs': ('async function '
                                                   'recordShortTermRecalls(',),
 'dist/short-term-promotion-store-B6T388Bo.mjs': ('async function readStore(',),
 'dist/dreaming-state-VYUvbU-n.mjs': ('function '
                                      'configureMemoryCoreDreamingState(',
                                      'async function '
                                      'writeMemoryCoreWorkspaceEntries('),
 'dist/dreaming-ingestion-state-licbtf_y.mjs': ('async function '
                                                'readDailyIngestionState(',
                                                'async function '
                                                'writeDailyIngestionState('),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function '
                                          'createPluginStateKeyedStore(',),
 'dist/extensions/memory-core/memory-index.worker.js': ('import '
                                                        '"../../manager-index.worker-CinEDBkE.mjs";',),
 'dist/manager-index.worker-CinEDBkE.mjs': ('serveWorkerTasks((input) =>',)}


MEMORY_INDEX_WORKER_ARTIFACTS = (
    "dist/extensions/memory-core/memory-index.worker.js", "dist/manager-index.worker-CinEDBkE.mjs",
)
REQUIRED_LOADED_ARTIFACTS = tuple(path for path in COMPILED_HASHES
                                if path not in MEMORY_INDEX_WORKER_ARTIFACTS)


def prepare_workspace_isolation_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Workspace isolation requires the unchanged pinned reference checkout")
    source_text, sources = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    specs = (
        ("extensions/memory-core/src/memory/manager.ts", "openclaw/plugin-sdk/memory-core-host-engine-foundation",
         ("resolveAgentWorkspaceDir", "resolveMemorySearchConfig"), "import"),
        ("src/plugin-sdk/memory-core-host-engine-foundation.ts", "../agents/agent-scope.js",
         ("resolveAgentWorkspaceDir",), "export"),
        ("src/agents/agent-scope.ts", "./agent-scope-config.js", ("resolveAgentWorkspaceDir",), "export"),
        ("extensions/memory-core/src/dreaming-ingestion-state.ts", "./dreaming-state.js",
         ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries"), "import"),
        ("extensions/memory-core/src/short-term-promotion-store.ts", "./dreaming-state.js",
         ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries"), "import"),
    )
    links = [_named(source_text, module, specifier, names, kind=kind)
             for module, specifier, names, kind in specs]
    return {"kind": "official-release-workspace-isolation-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "providerTransportVerified": False,
        "constructorSkipped": False, "managerFixture": False,
        "sourceBindings": sources, "compiledBindings": compiled, "sourceImportLinks": links,
        "requiredLoadedArtifacts": list(REQUIRED_LOADED_ARTIFACTS),
        "requiredMemoryIndexWorkerArtifacts": list(MEMORY_INDEX_WORKER_ARTIFACTS),
        "fixtureBoundary": "One host configuration selects each actual agent workspace and real provider-none "
            "manager. Literal file writes, actual manager/tool searches, awaited recall recording and typed "
            "daily-ingestion checkpoint writes execute against those selected owners. Managers close and "
            "reopen over persisted state. Full files, logical publication, tool envelopes, recall stores "
            "and ingestion states stay public; full private agent/plugin SQLite remains raw evidence. "
            "Public owner labels correspond to configured native agents and rebased SDK subjects; the "
            "SDK's unchanged main-agent config remains raw, not replaced by a fake agent override. "
            "No automatic maintenance run, complete promotion behavior, arbitrary agent/subject routing "
            "equivalence or binary schema interchange is claimed."}
