"""Independent pins for the controlled fresh-chat and host-restart experiment.

These declarations authenticate pristine source and official published artifacts.
They neither reconstruct a source build nor grant any acceptance credit. New
empty sessions use the actual catalog loader and synchronous transcript reader;
the separate history-worker declarations are authenticated, not claimed called.
The producer uses original coding write and explicit publication maintenance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat

from equivalence.reference_bindings import _git

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
HOST_RESTART_OPERATION = "host-restart-recall-runtime"

SOURCE_HASHES = {'src/agents/agent-tools.ts': 'bdcad2054268bf84d89439a5473224118c504a3eb36e1961d6454c09f9d4a391',
 'src/agents/core-coding-tools.ts': '64fb003174fb93c22e8de032006cbc67aadee8bbd565f718846c577808d4902b',
 'src/agents/agent-tools.read.ts': '34db04c4719a01d2b173c690498707e42c2dc8d1b8f6b1bca211fce9c08e3a6a',
 'src/agents/sessions/tools/write.ts': 'e305091da36b3ed8b9af0d358ed3047592721780b569d65ab587f751eaf20b57',
 'src/agents/agent-tools.before-tool-call.wrapper.ts': 'e5291b503723ba40ab621f2d079edbe974c987e6a2b9f121ac2db27fc2b0358c',
 'src/agents/agent-tools.before-tool-call.diagnostics.ts': '9e0aa53a994605b3f7c87dccb62dd95524fd830f7e3b180d3445ef5772991cc1',
 'src/agents/memory-write-provenance.ts': '628c004d93b38b06108d426750ca1ef1e8459c108202d0568b18e4c02bfebd13',
 'src/memory/memory-artifact-provenance.ts': '68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530',
 'src/plugin-sdk/plugin-state-store-runtime.ts': 'ecf895427ac1c6acf31570294fd6c2418dfc7b09a041b0b8f71d44e4d732c998',
 'src/plugin-sdk/agent-core.ts': '36923c1bfeef3df3271659521acb32f0769666563c589da864e01c35c0335171',
 'packages/agent-core/src/agent-loop.ts': 'c16d96af6a900d9a8540955336d43fb66c98810a92aa0693127f1bef35a1164e',
 'packages/agent-core/src/agent-stream-response.ts': '51a45aa652f8a7cb6325e2a520c5c7e7668962f9d865ea1ca9404edca6332bea',
 'packages/agent-core/src/harness/messages.ts': 'cfa370ab4c489262dc769f30c6b07ce6b90c974a2c6cb49d8a366a5edaf20d64',
 'packages/llm-core/src/utils/event-stream.ts': 'c04b8859e2ffe373cf796d997f964b6dddff637711188d4befc1111282942dbd',
 'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11',
 'src/config/sessions/session-accessor.sqlite-read.ts': '6434a27cd8268627fd1787d7afebe2c97792cee17376262534248fb388fa068d',
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': '6cbf0606d549cd2fae2e80e63181a0ff81e2eebfe32f8f93f4593d3832947618',
 'src/config/sessions/session-transcript-worker-runtime.ts': '74c9c60100612dc05b97831fca096f9005cd27cdf47c5020d0b987229d6893b1',
 'src/config/sessions/session-history-worker-runtime.ts': 'b8e172436e1796ab89747d88b73c3dc0d462bb25ba323642c3a5db482ec08a91',
 'src/state/openclaw-agent-db-lifecycle.ts': 'a49e35f38d6584969d28183cec435581b6a6797bd4b4eaf3f7b5d7507429b16c',
 'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/tools.runtime.ts': 'db0cca56eef6ad7b7cd6d56429d42529442a541ca0597f87be0603583e730fc5',
 'extensions/memory-core/src/memory-read-tool.ts': '318bdf62b8503176b55eda4c6431b91e6b330cbeb3178f390f0623e87f621c37',
 'extensions/memory-core/src/memory-search-tool-query.ts': '48168070d098e7540f82e83a2ab5e12cda338af8bded9d1a0b65e22514c93bdb',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'extensions/memory-core/src/memory/manager-runtime.ts': '0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b',
 'extensions/memory-core/src/memory/manager-cpu-entrypoints.ts': '20a5b2b2c957b7ba23518093e539f78066bacad520610acc58806e3cb5fcf2a9',
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': '060ebff91bcc60a819551cb44e055597e778a0792bf041da18f4749afebe686c',
 'extensions/memory-core/src/memory/manager-index.worker.ts': 'f68ee277284e834688a38993724a2844be65d581a05abd6455720f61d20452a7',
 'extensions/memory-core/src/memory/manager-search.worker.ts': 'b477fa182008d9aef544e0fa95d85cf5c731248ee492b60b15886f8b1b88931d',
 'extensions/memory-core/src/memory/manager-publication.worker.ts': '4bbc2de8a1e50ea089a5de337fbb2eaa5c0352fef5e85bf532557698d8b59b86',
 'extensions/memory-core/src/memory/manager-index-preparation.ts': '208e5c367e6f5dd79f1837050404fe67a9f05ac8fa5e5ad1860c12f4a259e041',
 'extensions/memory-core/src/memory/manager-search.ts': '0f0e97935d28718e077ed867c13d03568ce71c3c89cf5b306a8a4c42e98b7da4',
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': 'b0bf466a54ee67705f5b7327a31c0013e9ee44a57117181ca5860c5ef90e30b5',
 'extensions/memory-core/src/dreaming-state.ts': 'b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
 'packages/memory-host-sdk/src/host/read-file.ts': '340bb4aff7a88ee80591e5d0bc4f959367e7d2b6d7f06017d599f0342cb29dd2',
 'packages/memory-host-sdk/src/runtime-files.ts': '1245f01809e91317f28aa6966cbdd7baf34d1d46b858b0dbfd765be29bfb5274',
 'src/plugin-sdk/memory-core-host-runtime-files.ts': '286e82455cd53f203094ed3ef196c622bd98b73f34a8b25a8035e402e5178905',
 'src/agents/agent-scope-config.ts': '97afbaa31c3014db8ac76550907e25b60b449052aee03a7591917391c768b245',
 'src/agents/memory-search.ts': 'a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2',
 'src/infra/runtime-worker-url.ts': '9b694a778a84725e989ad2380195557993afbf25dc97e64112f7a65b2a2087e0',
 'src/infra/runtime-process-entrypoints.ts': '23576e3d35022ff7d7c4b4b163587d826b7e2b96b7e84533f8ac92189c7f3752',
 'src/infra/worker-task-pool-core.ts': '1cda75ab8e4a9df63b96174a701a82080c7c41fa7fe6e98a0d13941af7660727',
 'src/infra/worker-task-server.ts': '3ee977b63028f42aa62b62a3fd3628e8afc5f5b614ca65e65d0ca26b7669e523',
 'src/state/openclaw-agent-worker-store.ts': 'ec1aa29b8ff9bfa2740ecfbf42f6527028046459886d8255b3f0cfa277d8ef66',
 'src/state/openclaw-agent-execution.ts': '9409a7ac37d8db7ea7935edbadce60a93b58e78f16f67796e4e29461d41b9cec',
 'src/state/openclaw-agent-execution-domain.ts': 'c40268c8bea48fe6df4adda605c2516de6b3fb5be64e18245af72fd1d5e2f2a1',
 'src/state/openclaw-agent-execution.worker.ts': 'fab217983686e494a71ed089a2575e361f358f09e3141f88db0b6ec6a400e3de',
 'src/infra/sqlite-store.worker.ts': 'c958da27fa03aa7a31b487ad98836d9419539c8c3c0d6cdce52724f82d8702a8',
 'src/infra/sqlite-worker-store.ts': 'ebc5554be593fb1e28f8256209224f3d74634b5ed35af0b2ad7c69cb15350a54',
 'src/infra/runtime-process-url.ts': '0914e78c0e99eecfb49d0aafec3e82d8e6fa61f3a22cfbf97669c0ffc8441f1e',
 'src/infra/worker-cpu.ts': '41e8c54a90cb84caf392f0d7a5dfdceeef2fe5aa75cbdb85f5c32e03f803d256',
 'src/config/sessions/session-transcript-worker-resources.ts': '6b5bf1f75a1bcc6175cfab76971db6baed16c7321c1818ed0cc374e35f230c5b',
 'src/config/sessions/session-transcript.worker.ts': '7e50bf974d3fd7b694b4d29007df6cfa896ae8f8bb395911e7b6b1e78008ea03',
 'src/plugin-state/plugin-state-worker-client.ts': '2f6d019d90a079e01a1ee2edcfe13b3be7393baad7b951d1de9bfab69ebdbee3',
 'src/plugin-state/plugin-state.worker.ts': '7890fdcd60cd75b59816603242cf6446f236a8901d679185da9191630c7de5b0',
 'src/state/openclaw-state-worker-owner.ts': 'f6cb1576f8bd7f0ce23326e558c7c3968b202e5b03f18e5c41e86488bdc2b127',
 'src/state/openclaw-state-worker-store.ts': '58194c48d5c2d7047fb6429e37b080b4745d6c2562b583ab54773c8612c3c9da',
 'src/state/openclaw-state.worker.ts': '0017e2465c09c9d1bc3701005a065a1de989bc84c4b14a265366c555a9fc56b2'}

SOURCE_ANCHORS = {'src/agents/agent-tools.ts': ('export function createOpenClawCodingTools(', '    resolveOriginClass: () =>'),
 'src/agents/core-coding-tools.ts': ('export function createCoreCodingTools(',),
 'src/agents/agent-tools.read.ts': ('export function createHostWorkspaceWriteTool(',),
 'src/agents/sessions/tools/write.ts': ('export function createWriteTool(',),
 'src/agents/agent-tools.before-tool-call.wrapper.ts': ('export function wrapToolWithBeforeToolCallHook(',),
 'src/agents/agent-tools.before-tool-call.diagnostics.ts': ('export async function recordLoopOutcome(',),
 'src/agents/memory-write-provenance.ts': ('export function createMemoryWriteProvenanceObserver(',
                                           'export function withMemoryWriteProvenance<'),
 'src/memory/memory-artifact-provenance.ts': ('export async function recordMemoryArtifactWriteProvenance(',
                                              'export async function listMemoryArtifactProvenance('),
 'src/plugin-state/plugin-state-store.ts': ('export function createPluginStateKeyedStore<T>(',
                                            'export function createCorePluginStateKeyedStore<T>('),
 'src/plugin-sdk/plugin-state-store-runtime.ts': ('  createPluginStateKeyedStore,',),
 'src/plugin-sdk/agent-core.ts': ('export { runAgentLoop } from "../../packages/agent-core/src/index.js";',),
 'packages/agent-core/src/agent-loop.ts': ('export async function runAgentLoop(',),
 'packages/agent-core/src/agent-stream-response.ts': ('export async function streamAgentResponse(',),
 'packages/agent-core/src/harness/messages.ts': ('export function convertToLlm(',),
 'packages/llm-core/src/utils/event-stream.ts': ('export function createAssistantMessageEventStream(',),
 'src/plugin-sdk/session-store-runtime.ts': ('export function loadSessionStore(',
                                             'export async function upsertSessionEntry('),
 'src/config/sessions/session-accessor.sqlite-read.ts': ('export function loadTranscriptEventsSync(',),
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': ('export function '
                                                                              'appendTranscriptMessageInTransaction<TMessage>(',),
 'src/config/sessions/session-transcript-worker-runtime.ts': ('export function '
                                                              'withSessionHistoryWorkerDatabase<T>(',),
 'src/config/sessions/session-history-worker-runtime.ts': ('export async function '
                                                           'readSessionHistoryPageInWorker(',),
 'src/state/openclaw-agent-db-lifecycle.ts': ('export async function closeOpenClawAgentDatabasesAsync(',),
 'extensions/memory-core/src/tools.ts': ('export function createMemorySearchTool(',
                                         'export function createMemoryGetTool('),
 'extensions/memory-core/src/tools.runtime.ts': ('  readAgentMemoryFile,',
                                                 'export { getMemorySearchManager } from '
                                                 '"./memory/index.js";'),
 'extensions/memory-core/src/memory-read-tool.ts': ('export async function executeMemoryReadResult(',),
 'extensions/memory-core/src/memory-search-tool-query.ts': ('export async function '
                                                            'executeMemorySearchToolQuery(',),
 'extensions/memory-core/src/memory/manager.ts': ('export class MemoryIndexManager ',),
 'extensions/memory-core/src/memory/manager-runtime.ts': ('export { MemoryIndexManager };',),
 'extensions/memory-core/src/memory/manager-cpu-entrypoints.ts': ('export const memoryCpuProcessEntrypoints '
                                                                  '= {',),
 'extensions/memory-core/src/memory/manager-cpu-worker-runtime.ts': ('export async function '
                                                                     'runMemoryKeywordSearch(',
                                                                     'export async function '
                                                                     'prepareMemoryIndexInWorker('),
 'extensions/memory-core/src/memory/manager-index.worker.ts': ('serveWorkerTasks<MemoryIndexTaskResult>',),
 'extensions/memory-core/src/memory/manager-search.worker.ts': ('serveWorkerTasks(async (input): '
                                                                'Promise<MemorySearchWorkerOutput> => {',),
 'extensions/memory-core/src/memory/manager-publication.worker.ts': ('export function '
                                                                     'bindSqliteWorkerBackend(',
                                                                     'export function '
                                                                     'openExistingSqliteWorkerBackend('),
 'extensions/memory-core/src/memory/manager-index-preparation.ts': ('export function '
                                                                    'prepareMemoryIndexChunks(',),
 'extensions/memory-core/src/memory/manager-search.ts': ('export async function searchKeyword(',),
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': ('export class '
                                                                      'MemorySourceIndexKernel',),
 'extensions/memory-core/src/dreaming-state.ts': ('export function configureMemoryCoreDreamingState(',),
 'packages/memory-host-sdk/src/host/read-file.ts': ('export async function readAgentMemoryFile(',),
 'packages/memory-host-sdk/src/runtime-files.ts': ('export { readAgentMemoryFile } from '
                                                   '"./host/read-file.js";',),
 'src/plugin-sdk/memory-core-host-runtime-files.ts': ('  readAgentMemoryFile,',),
 'src/agents/agent-scope-config.ts': ('export function resolveAgentWorkspaceDir(',),
 'src/agents/memory-search.ts': ('export function resolveMemorySearchConfig(',),
 'src/infra/runtime-worker-url.ts': ('export function resolveRuntimeWorkerUrl(',),
 'src/infra/runtime-process-entrypoints.ts': ('sqliteStore: '
                                              'runtimeProcessEntrypoint("infra/sqlite-store.worker")',),
 'src/infra/worker-task-pool-core.ts': ('export class WorkerTaskPoolCore<Input, Output>',),
 'src/infra/worker-task-server.ts': ('export function serveWorkerTasks<',),
 'src/state/openclaw-agent-worker-store.ts': ('export async function '
                                              'openOpenClawAgentSqliteWorkerStore<Operations extends '
                                              'SqliteWorkerOperations>(',),
 'src/state/openclaw-agent-execution.ts': ('export function captureOpenClawAgentDatabaseExecution(',),
 'src/state/openclaw-agent-execution-domain.ts': ('export function createAgentDatabaseDomainOwner(',),
 'src/state/openclaw-agent-execution.worker.ts': ('import { createAgentDatabaseDomainOwner } from '
                                                  '"./openclaw-agent-execution-domain.js";',),
 'src/infra/sqlite-store.worker.ts': ('SQLite store worker requires its host port',),
 'src/infra/sqlite-worker-store.ts': ('export function runSqliteWorkerStoreWrite<Operations extends '
                                      'SqliteWorkerOperations, T>(',),
 'src/infra/runtime-process-url.ts': ('export function resolveRuntimeProcessEntrypointUrl(',),
 'src/infra/worker-cpu.ts': ('export function createCpuTrackedWorker(',),
 'src/config/sessions/session-transcript-worker-resources.ts': ('const workerUrl = '
                                                                'resolveRuntimeWorkerUrl(runtimeProcessEntrypoints.sessionTranscript);',),
 'src/config/sessions/session-transcript.worker.ts': ('serveOwnedWorkerTasks(',),
 'src/plugin-state/plugin-state-worker-client.ts': ('async function execute<Key extends keyof '
                                                    'PluginStateWorkerOperations>(',),
 'src/plugin-state/plugin-state.worker.ts': ('export function executePluginStateCommand(',),
 'src/state/openclaw-state-worker-owner.ts': ('export function getOpenClawStateWorkerOwner(',),
 'src/state/openclaw-state-worker-store.ts': ('import { getOpenClawStateWorkerOwner as owner } from '
                                              '"./openclaw-state-worker-owner.js";',),
 'src/state/openclaw-state.worker.ts': ('executePluginStateCommand',)}

COMPILED_HASHES = {'dist/agent-tools-HIqp3eTk.mjs': '9887e5788b6d88cf3c9a7a5581548d52b5f208fccd2694a01df8bb75017cd702',
 'dist/core-coding-tools-DMPT-DjL.mjs': 'de2d807cb25075f8347888fcac51a907efcd971cedd6fce60c042d7d5201c80e',
 'dist/agent-tools.read-ZzkirzL1.mjs': 'bec516044e956d92b1297b154a48ef9ee75e83dfdfe79b8dda5668a9995e778c',
 'dist/tools-DLW3vi8k.mjs': '100134d5d22981dcad305e470b30c6e8296e6ef7e034bcc2cabc502552c91b02',
 'dist/agent-tools.before-tool-call-Cg8vCu9u.mjs': '69abb7861a76913024828b0a7fd1948fc72081f9a8c91b629d0bc06e966f49c5',
 'dist/agent-tools.before-tool-call.runtime.js': '64f74bcc77d386854f7bb46c030dc01caf081073e3220251ba49f18ed3225811',
 'dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs': '88be9b0b2e1dcdc921606bc9a829bbd6a28ee4c088a1ea0bfab8d2f4a2f4ec46',
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': 'd9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
 'dist/plugin-sdk/plugin-state-store-runtime.js': '6e34e2530c913403a15ce4f93a3c8fdfbbb7caaa9ea191faa5993c6b469f1e61',
 'dist/plugin-sdk/agent-core.js': '354eb73c79096ca4761431cb7fd85d9756a352219fdc3f1187a4ae9607e36af1',
 'dist/agent-core-DrCkPXML.mjs': '44500635166e55c16d9a66f9ddc277cd6cee17b764184b82118b445ac82732eb',
 'dist/llm-ASoRyt-k.mjs': '00a1ffd0459c90d077d3f245633d4ac94d145901ed56b62112cb84cb94aab01f',
 'dist/session-BA9qunLx.mjs': '76e83df0e3056d87ac01eeb929a1b1f5a4722ef274653e3bafef4c64fc9468cd',
 'dist/plugin-sdk/session-store-runtime.js': '495b19c73cb71dce90914b28d0c9492da41622fbdfb7a4966885ba7f83cbbba2',
 'dist/session-store-runtime-C3lQUqXM.mjs': '42c91a431b20934055e124edf556bffdb57e203615f814fd6c6067654c5caf20',
 'dist/session-accessor-CiKKTlbe.mjs': '287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a',
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': 'f351ef360d46add8ead586270b6609b388380cc820d631f7c4ed945e6e506d7e',
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': '252ed9e8717da3b64bee74c0948425d77519bf520b1e131e381d985ec4fb73a0',
 'dist/session-transcript-worker-runtime-Dd9NL9y_.mjs': 'c717b24074c431303a35fe1675d10135e47e1dc018496d2dd7b76ef9c6dbc5f1',
 'dist/session-history-worker-runtime-D47dVCja.mjs': '238df34a062e9cc06594ff93d1d64218237685a1277285bd57cdda32d4200033',
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': 'ece2b2b08f3e03c8ddb3dc70e29265f23c6b3df52e37e981e79a6bbd424a5a84',
 'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/tools.runtime.js': '453b5423b3b47e05cf06608162ae184186d332c2042792bde427580cc73d5661',
 'dist/tools.runtime-m4sffzql.mjs': '0e3cca44ae9922d28e02779723a91f99889e6322a77daa4d9700bdcb4f816983',
 'dist/read-file-CH8NQLbp.mjs': 'eec2ac48d772f0d2303c65bf3ea3a0866c42f864bf8e9c75f7307643044a4687',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': '6685d974f0ba1ca6e8aa0349658cfb5c427678230396dca00b4549c340ca7f1a',
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': '9225fc056eb1db62970511129ce9843ffd467eb2d6f2b08500b63fd7854fbc45',
 'dist/extensions/memory-core/memory-index.worker.js': '740d4ac59fd01308335d9f725f2c83cc6565178d428844a1ca5cd2d792a3b27d',
 'dist/manager-index.worker-CinEDBkE.mjs': 'bf8a8a6d0185434fa48f31f82c27010deb8a3b96edf665c2e5d395a68e1b5b61',
 'dist/extensions/memory-core/memory-search.worker.js': 'b6c37bfcccdb1240e61550de9c730395113e0dcadc22c54f0814106dfacf042c',
 'dist/manager-search.worker-BWRvo8WR.mjs': '234abd2dd01f7ed01e2e94aa0f25f6cba402676fe7a6b308cfb6729b6c058e4f',
 'dist/extensions/memory-core/memory-publication.worker.js': '1567321ec23f591b1d10c8d3291a60353af608658e769b7a6a427bad4f56378f',
 'dist/manager-publication.worker-x9zokjMA.mjs': 'd2b8540a1b29cd70cb21561b577382c9f73d353303f0795a9ba1c39e6f8c3b25',
 'dist/manager-index-preparation-wXpJtJiU.mjs': '6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867',
 'dist/manager-search-DgMs3pkc.mjs': 'f97d896dac1037bc8aa96b3b8631cb3efba3ee361f4a8c02039bebc18f6184a0',
 'dist/manager-source-index-kernel-D-njga00.mjs': '762c8cecb4b1eae8ea90d96eb6ed2759f07fd970c9ef4b12344f5e14ef0745fc',
 'dist/extensions/memory-core/runtime-api.js': '520c6cc05e74399c910425488cacd52867bb587434a36d33c8b90d11326d75ec',
 'dist/dreaming-state-VYUvbU-n.mjs': '8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
 'dist/agent-scope-config-Dm6T00l4.mjs': '046526ee2ad580faaa1a3a3d7bf21b2f29acac5ed58863ab8e4035d91b39088a',
 'dist/memory-search-CIhUURbE.mjs': 'e015aeaa8d8e062eb792ae58d2e4537e5b0f665ea97b946979e644444304a148',
 'dist/plugin-sdk/config-runtime.js': 'ca8ea03ec6a8eeb48c4f300f7a88171aba943e6999a40791205d0027bd1d2a18',
 'dist/runtime-snapshot-BFi3jxlO.mjs': '0cb73088d71ff77c47d63931a00d9c771b5fc5c205ad77f3588335c8a908f9cb',
 'dist/runtime-worker-url-S0NIVxUR.mjs': '49585b6cc537babf6c8e4f795c709e3b109af37b3df46161afcf593b506a136b',
 'dist/runtime-process-entrypoints-Bh4reDp0.mjs': 'd8031c4fff5902dc7c99a70daf2d4c8f1ce809db149e029d77c0dac2873dfc4a',
 'dist/worker-task-pool-BQlnRNqZ.mjs': '79ea82aa29baa5d72f600d5191ee4a3a0bd62fed0062cc8da96877cf334ccf2d',
 'dist/worker-task-server-CF3aSh39.mjs': '0528de35a64cfead2597bcf0d1db768d3c9339971e10f013612756ff1a0ca167',
 'dist/openclaw-agent-worker-store-DyrZR3UA.mjs': '95a1654e5056516ba2e9c7dcd14cfee3de4ce92496c90c70970c20afbc73b5d7',
 'dist/openclaw-agent-execution-Da3Ihc2Y.mjs': '0fc4c45a5d64aeab1446f6df84fcf90c206d847d0bb2738bb0d80c46984a2637',
 'dist/state/openclaw-agent-execution.worker.js': 'a798d178f2a1c7a203d0b9f57d2da2048f3bd7cdfa7c01ab0f7c312ce216885c',
 'dist/infra/sqlite-store.worker.js': 'b6fb8b9d214bd7d35beb77849e1c44926d4963cacd9fc13af40f8c3b43374d69',
 'dist/sqlite-worker-store-D6Kl0iv0.mjs': 'd26499b6fabe956da5b29630aaf9061071b8d5ec0608c84076183588aa89f1df',
 'dist/runtime-process-url-DpjnU3O9.mjs': '9c16d792c31a0a5af157c7e862c7a872110330adb6ce58a2570b5c264b8b3839',
 'dist/worker-cpu-EKuz4_X-.mjs': 'ba8fc5f65b7ad1853164907b14579600627b67c22c9a6a9be64de7ff0b5fb506',
 'dist/session-transcript-worker-resources-CYts_Yt9.mjs': '7cccb1eee6cf7c1fcb751b17ef7c147591fbd6a8015808c7d0b9979500b50557',
 'dist/config/sessions/session-transcript.worker.js': '30bee98b7f19e310f35e9e2f4fa29c48467daf05fc14b6209d0518b347c7610e',
 'dist/plugin-state-worker-client-7ByaGIDy.mjs': 'bee1c828bf9a23d3aeafd84e91d3dfd2b2d685b2d560fc5a9e01aabcd0346217',
 'dist/plugin-state.worker-Bt1nfP3u.mjs': 'd724a51faf2d46e518a733a47528ac9b629e54b1d4f6afa9007d769021bba9f4',
 'dist/openclaw-state-worker-store-DRKGvWWN.mjs': 'd567e4897230641cd70eeeade81cc6281c67bf76626e1fa7cfb19987ce0b73ca',
 'dist/openclaw-state-worker-store-Dy5-mnWx.mjs': '8f2ce584b66eec3ff3c876ddab18947e8af6b2a60fbbf3aeb3e020336410e407',
 'dist/state/openclaw-state.worker.js': '52fdb859d0add218690d0db4358fa5b2f2d2118379163eefb42a35c87f0715d4'}

COMPILED_ANCHORS = {'dist/agent-tools-HIqp3eTk.mjs': ('function createOpenClawCodingTools(', 'createOpenClawCodingTools as t'),
 'dist/core-coding-tools-DMPT-DjL.mjs': ('function createCoreCodingTools(',),
 'dist/agent-tools.read-ZzkirzL1.mjs': ('function createHostWorkspaceWriteTool(',
                                        'function createMemoryWriteProvenanceObserver('),
 'dist/tools-DLW3vi8k.mjs': ('function createWriteTool(',),
 'dist/agent-tools.before-tool-call-Cg8vCu9u.mjs': ('function wrapToolWithBeforeToolCallHook(',
                                                    'async function recordLoopOutcome('),
 'dist/agent-tools.before-tool-call.runtime.js': ('export * from '
                                                  '"./agent-tools.before-tool-call.runtime-DrbwqsOU.mjs";',),
 'dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs': ('const beforeToolCallRuntime = {',),
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': ('async function recordMemoryArtifactWriteProvenance(',
                                                  'async function listMemoryArtifactProvenance('),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function createPluginStateKeyedStore(',
                                          'function createCorePluginStateKeyedStore('),
 'dist/plugin-sdk/plugin-state-store-runtime.js': ('export { createPluginStateKeyedStore, '
                                                   'createPluginStateSyncKeyedStore };',),
 'dist/plugin-sdk/agent-core.js': (' runAgentLoop,',),
 'dist/agent-core-DrCkPXML.mjs': ('async function runAgentLoop(',),
 'dist/llm-ASoRyt-k.mjs': ('function createAssistantMessageEventStream(',),
 'dist/session-BA9qunLx.mjs': ('function convertToLlm(',),
 'dist/plugin-sdk/session-store-runtime.js': ('export { SessionStoreAgentIdRequiredError,',),
 'dist/session-store-runtime-C3lQUqXM.mjs': ('function loadSessionStore(',
                                             'async function upsertSessionEntry('),
 'dist/session-accessor-CiKKTlbe.mjs': ('export {',),
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': ('function loadTranscriptEventsSync(',),
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function appendTranscriptMessage(',),
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': ('function '
                                                                      'appendTranscriptMessageInTransaction(',),
 'dist/session-transcript-worker-runtime-Dd9NL9y_.mjs': ('function withSessionHistoryWorkerDatabase(',),
 'dist/session-history-worker-runtime-D47dVCja.mjs': ('async function readSessionHistoryPageInWorker(',),
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': ('async function closeOpenClawAgentDatabasesAsync(',),
 'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(',
                             'function createMemoryGetTool(',
                             'async function executeMemoryReadResult('),
 'dist/tools.runtime.js': ('export * from "./tools.runtime-m4sffzql.mjs";',),
 'dist/tools.runtime-m4sffzql.mjs': ('export { getMemorySearchManager, readAgentMemoryFile, '
                                     'resolveMemoryBackendConfig };',),
 'dist/read-file-CH8NQLbp.mjs': ('async function readAgentMemoryFile(',),
 'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = class MemoryIndexManager ',
                                                    'async function closeAllMemoryIndexManagers(',
                                                    'moduleUrl: '
                                                    'resolveRuntimeWorkerUrl(memoryCpuProcessEntrypoints.publication),'),
 'dist/manager-cpu-entrypoints-bJosRUx9.mjs': ('const memoryCpuProcessEntrypoints = {',),
 'dist/manager-cpu-worker-runtime-CAWQOyFu.mjs': ('async function runMemoryKeywordSearch(',
                                                  'async function prepareMemoryIndexInWorker('),
 'dist/extensions/memory-core/memory-index.worker.js': ('import "../../manager-index.worker-CinEDBkE.mjs";',),
 'dist/manager-index.worker-CinEDBkE.mjs': ('serveWorkerTasks((input) =>',),
 'dist/extensions/memory-core/memory-search.worker.js': ('import '
                                                         '"../../manager-search.worker-BWRvo8WR.mjs";',),
 'dist/manager-search.worker-BWRvo8WR.mjs': ('function inspectMemoryIndexPresenceInWorker(',),
 'dist/extensions/memory-core/memory-publication.worker.js': ('export { bindSqliteWorkerBackend, '
                                                              'openExistingSqliteWorkerBackend };',),
 'dist/manager-publication.worker-x9zokjMA.mjs': ('function bindSqliteWorkerBackend(',
                                                  'function openExistingSqliteWorkerBackend('),
 'dist/manager-index-preparation-wXpJtJiU.mjs': ('function prepareMemoryIndexChunks(',),
 'dist/manager-search-DgMs3pkc.mjs': ('async function searchKeyword(',),
 'dist/manager-source-index-kernel-D-njga00.mjs': ('var MemorySourceIndexKernel = class',),
 'dist/extensions/memory-core/runtime-api.js': (' configureMemoryCoreDreamingState,',),
 'dist/dreaming-state-VYUvbU-n.mjs': ('function configureMemoryCoreDreamingState(',),
 'dist/agent-scope-config-Dm6T00l4.mjs': ('function resolveAgentWorkspaceDir(',),
 'dist/memory-search-CIhUURbE.mjs': ('function resolveMemorySearchConfig(',),
 'dist/plugin-sdk/config-runtime.js': ('export { GROUP_POLICY_BLOCKED_LABEL,',),
 'dist/runtime-snapshot-BFi3jxlO.mjs': ('function setRuntimeConfigSnapshot(',),
 'dist/runtime-worker-url-S0NIVxUR.mjs': ('function resolveRuntimeWorkerUrl(',),
 'dist/runtime-process-entrypoints-Bh4reDp0.mjs': ('sqliteStore: '
                                                   'runtimeProcessEntrypoint("infra/sqlite-store.worker")',),
 'dist/worker-task-pool-BQlnRNqZ.mjs': ('var WorkerTaskPoolCore = class',),
 'dist/worker-task-server-CF3aSh39.mjs': ('function serveWorkerTasks(',),
 'dist/openclaw-agent-worker-store-DyrZR3UA.mjs': ('async function openOpenClawAgentSqliteWorkerStore(',),
 'dist/openclaw-agent-execution-Da3Ihc2Y.mjs': ('function captureOpenClawAgentDatabaseExecution(',),
 'dist/state/openclaw-agent-execution.worker.js': ('function createAgentDatabaseDomainOwner(',),
 'dist/infra/sqlite-store.worker.js': ('SQLite store worker requires its host port',),
 'dist/sqlite-worker-store-D6Kl0iv0.mjs': ('const carrier = '
                                           'resolveRuntimeProcessEntrypointUrl("sqliteStore");',),
 'dist/runtime-process-url-DpjnU3O9.mjs': ('function resolveRuntimeProcessEntrypointUrl(',),
 'dist/worker-cpu-EKuz4_X-.mjs': ('function createCpuTrackedWorker(',),
 'dist/session-transcript-worker-resources-CYts_Yt9.mjs': ('const workerUrl = '
                                                           'resolveRuntimeWorkerUrl(runtimeProcessEntrypoints.sessionTranscript);',),
 'dist/config/sessions/session-transcript.worker.js': ('serveOwnedWorkerTasks(',),
 'dist/plugin-state-worker-client-7ByaGIDy.mjs': ('//#region '
                                                  'src/plugin-state/plugin-state-worker-client.ts',),
 'dist/plugin-state.worker-Bt1nfP3u.mjs': ('export { executePluginStateCommand };',),
 'dist/openclaw-state-worker-store-DRKGvWWN.mjs': ('export { createOpenClawStateWorkerLease,',),
 'dist/openclaw-state-worker-store-Dy5-mnWx.mjs': ('function getOpenClawStateWorkerOwner(',),
 'dist/state/openclaw-state.worker.js': ('executePluginStateCommand',)}


# Required parent execution is deliberately separate from authenticated-only
# declarations and from artifacts that must execute together inside a worker.
REQUIRED_HOST_ARTIFACTS = (
    "dist/plugin-sdk/config-runtime.js", "dist/runtime-snapshot-BFi3jxlO.mjs",
    "dist/plugin-sdk/agent-core.js", "dist/agent-core-DrCkPXML.mjs",
    "dist/session-BA9qunLx.mjs", "dist/llm-ASoRyt-k.mjs",
    "dist/plugin-sdk/session-store-runtime.js", "dist/session-store-runtime-C3lQUqXM.mjs",
    "dist/session-accessor-CiKKTlbe.mjs", "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
    "dist/extensions/memory-core/manager-runtime.js",
    "dist/extensions/memory-core/runtime-api.js", "dist/dreaming-state-VYUvbU-n.mjs",
    "dist/plugin-sdk/plugin-state-store-runtime.js", "dist/plugin-state-store-BPUaLoVD.mjs",
    "dist/memory-artifact-provenance-DhnyWiV1.mjs",
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
)
WRITE_ARTIFACTS = (
    "dist/agent-tools-HIqp3eTk.mjs", "dist/core-coding-tools-DMPT-DjL.mjs",
    "dist/agent-tools.read-ZzkirzL1.mjs", "dist/tools-DLW3vi8k.mjs",
    "dist/agent-tools.before-tool-call-Cg8vCu9u.mjs",
    "dist/agent-tools.before-tool-call.runtime.js",
    "dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs",
)
READ_ARTIFACTS = (
    "dist/tools-DotaQGXh.mjs", "dist/tools.runtime.js", "dist/tools.runtime-m4sffzql.mjs",
    "dist/read-file-CH8NQLbp.mjs", "dist/agent-scope-config-Dm6T00l4.mjs",
    "dist/memory-search-CIhUURbE.mjs", "dist/manager-cpu-entrypoints-bJosRUx9.mjs",
    "dist/manager-cpu-worker-runtime-CAWQOyFu.mjs", "dist/runtime-worker-url-S0NIVxUR.mjs",
    "dist/worker-task-pool-BQlnRNqZ.mjs", "dist/worker-cpu-EKuz4_X-.mjs",
)
PUBLICATION_PARENT_ARTIFACTS = (
    "dist/openclaw-agent-worker-store-DyrZR3UA.mjs", "dist/openclaw-agent-execution-Da3Ihc2Y.mjs",
    "dist/sqlite-worker-store-D6Kl0iv0.mjs", "dist/runtime-process-url-DpjnU3O9.mjs",
    "dist/runtime-process-entrypoints-Bh4reDp0.mjs",
)
PLUGIN_STATE_PARENT_ARTIFACTS = (
    "dist/plugin-state-worker-client-7ByaGIDy.mjs",
    "dist/openclaw-state-worker-store-DRKGvWWN.mjs",
    "dist/openclaw-state-worker-store-Dy5-mnWx.mjs",
)
WORKER_ROUTES = {
    "index": (
        "dist/extensions/memory-core/memory-index.worker.js",
        "dist/manager-index.worker-CinEDBkE.mjs", "dist/manager-index-preparation-wXpJtJiU.mjs",
        "dist/worker-task-server-CF3aSh39.mjs",
    ),
    "search": (
        "dist/extensions/memory-core/memory-search.worker.js",
        "dist/manager-search.worker-BWRvo8WR.mjs", "dist/manager-search-DgMs3pkc.mjs",
        "dist/worker-task-server-CF3aSh39.mjs",
    ),
    # Publication is a backend inside the genuine SQLite carrier. The
    # canonical agent route also includes the agent executor backend below.
    "publication": (
        "dist/infra/sqlite-store.worker.js",
        "dist/extensions/memory-core/memory-publication.worker.js",
        "dist/manager-publication.worker-x9zokjMA.mjs",
        "dist/manager-source-index-kernel-D-njga00.mjs",
    ),
    "pluginState": (
        "dist/infra/sqlite-store.worker.js", "dist/state/openclaw-state.worker.js",
        "dist/plugin-state.worker-Bt1nfP3u.mjs",
    ),
}
CANONICAL_PUBLICATION_WORKER_ARTIFACTS = (
    *WORKER_ROUTES["publication"], "dist/state/openclaw-agent-execution.worker.js",
)
AGENT_EXECUTION_WORKER_ROUTE = (
    "dist/infra/sqlite-store.worker.js", "dist/state/openclaw-agent-execution.worker.js",
)
ALL_WORKER_ROUTES = tuple(WORKER_ROUTES.values())
PRODUCER_WORKER_ROUTES = ALL_WORKER_ROUTES
READER_WORKER_ROUTES = (WORKER_ROUTES["search"], WORKER_ROUTES["pluginState"],
                        AGENT_EXECUTION_WORKER_ROUTE)
HISTORY_WORKER_ARTIFACTS = (
    "dist/session-history-worker-runtime-D47dVCja.mjs",
    "dist/session-transcript-worker-runtime-Dd9NL9y_.mjs",
    "dist/session-transcript-worker-resources-CYts_Yt9.mjs",
    "dist/config/sessions/session-transcript.worker.js",
)
AUTHENTICATED_ONLY_ARTIFACTS = HISTORY_WORKER_ARTIFACTS
NATIVE_ARTIFACTS = {
    ("node_modules/@openclaw/fs-safe-linux-x64-gnu", "fs-safe-native.node"):
        "f1aad2619542e43af6f28606e7514054bd0824814f2a2bb4b72f5e16e9ea2d7c",
}


def _regular_owners(root: Path, names) -> None:
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("Host restart requires independent canonical owner roots")
    for relative in names:
        filename = root / relative
        if (any(part.is_symlink() for part in (filename, *filename.parents) if part != root)
                or not filename.resolve().is_relative_to(root)):
            raise ValueError("A host restart owner escaped its authenticated root")
        info = filename.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8 * 1024 * 1024:
            raise ValueError("Host restart owners require bounded independent regular files")


def _owners(root: Path, hashes: dict, anchors: dict, *, committed: bool) -> list[dict]:
    _regular_owners(root, hashes)
    result = []
    for relative, digest in hashes.items():
        raw = (root / relative).read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise ValueError("A host restart owner differs from its exact reviewed bytes")
        source = raw.decode("utf-8")
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise ValueError("A host restart declaration lost its unique original linkage")
            locations.append({"anchor": anchor, "line": source[:source.index(anchor)].count("\n") + 1})
        result.append({"path": relative, "sha256": digest, "anchors": locations})
    return result


def prepare_host_restart_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate original owners only; the separate evidence gate proves IO."""
    checkout, runtime_root = Path(checkout).absolute(), Path(runtime_root).absolute()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Host restart requires the exact pinned unchanged reference commit")
    sources = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    native = []
    installation = runtime_root.parent.parent
    for (package, relative), digest in NATIVE_ARTIFACTS.items():
        file = installation / package / relative
        _regular_owners(installation, (str(file.relative_to(installation)),))
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("The host restart published native file-safety artifact changed")
        native.append({"package": package, "path": relative, "sha256": digest,
                       "nativeBuildReproduced": False})
    return {
        "kind": "official-release-host-restart-owners", "operation": HOST_RESTART_OPERATION,
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "sourceFallbackAllowed": False, "sourceExecutionPermitted": False,
        "covers": [], "acceptancePointsAwarded": 0,
        "sourceBindings": sources, "compiledBindings": compiled, "nativeArtifactBindings": native,
        "requiredLoadedArtifacts": list(REQUIRED_HOST_ARTIFACTS),
        "requiredProducerArtifacts": list(WRITE_ARTIFACTS),
        "requiredReadArtifacts": list(READ_ARTIFACTS),
        "requiredPublicationParentArtifacts": list(PUBLICATION_PARENT_ARTIFACTS),
        "requiredPluginStateParentArtifacts": list(PLUGIN_STATE_PARENT_ARTIFACTS),
        "requiredWorkerRoutes": {role: list(paths) for role, paths in WORKER_ROUTES.items()},
        "requiredProducerWorkerRoutes": [list(paths) for paths in PRODUCER_WORKER_ROUTES],
        "requiredReaderWorkerRoutes": [list(paths) for paths in READER_WORKER_ROUTES],
        "requiredCanonicalPublicationWorkerArtifacts": list(CANONICAL_PUBLICATION_WORKER_ARTIFACTS),
        "authenticatedOnlyArtifacts": list(AUTHENTICATED_ONLY_ARTIFACTS),
        "sessionReconstruction": {"store": "loadSessionStore", "transcript": "loadTranscriptEventsSync",
            "initialHistoryMustBeEmpty": True, "historyWorkerInvoked": False},
        "producerEntrypoint": {"path": "dist/agent-tools-HIqp3eTk.mjs", "export": "t", "tool": "write"},
        "loopEntrypoint": {"path": "dist/plugin-sdk/agent-core.js", "export": "runAgentLoop"},
        "readEntrypoints": {"path": "dist/tools-DotaQGXh.mjs",
            "exports": ["createMemorySearchTool", "createMemoryGetTool"]},
        "providerTransportVerified": False, "fullEmbeddedRunnerVerified": False,
        "producerApiParityClaimed": False, "automaticTurnBarrierClaimed": False,
        "publicationFixture": "Actual producer markMemoryWatchDirty and awaited manager.sync; no restarted caller sync",
        "clock": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
    }


# Compact alias for callers following the other equivalence binding modules.
prepare_host_restart_bindings = prepare_host_restart_runtime_bindings
