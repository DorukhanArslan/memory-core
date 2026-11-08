"""Authenticate genuine SQLite session admission, index and visibility owners.

The whole-flow profile constructs the original provider-none manager and uses
real transcript/catalog/index IO plus hosted in-process Gateway dispatch. The
separate helper profile calls the original ingestion policy export only. Their
claims and worker requirements remain separate; no provider transport or full
Gateway HTTP server equivalence is established.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from equivalence.reference_bindings import ReferenceBindingError, _NAMED_FROM, _git
from equivalence.reuse_bindings import ReuseBindingError, _named

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/memory-search-tool-query.ts': '48168070d098e7540f82e83a2ab5e12cda338af8bded9d1a0b65e22514c93bdb',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'extensions/memory-core/src/memory/manager-runtime.ts': '0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b',
 'extensions/memory-core/src/memory/manager-session-sync-ops.ts': '3af5c8c2ef2aca054c3d34190941855ab76374c65cd5d6908b6744fb34ea0a4f',
 'extensions/memory-core/src/memory/manager-session-sync-state.ts': 'ee190fecc3c4d8853ef9cf2aba95f786aa144d2a599818533202200a515c96d6',
 'src/agents/memory-search-source-policy.ts': 'b95b8ebf49144924307e153162b1302ba5fd48658e647618aec1ff0d54b0b80f',
 'packages/memory-host-sdk/src/host/session-transcript-corpus.ts': '8bc7c3f008e3b4d9c04da985cec647b830c54c2c205f15d4ff834e202585dfb7',
 'packages/memory-host-sdk/src/host/session-files.ts': 'd184bf1a1b098a02b08ed131321fb47d6caf5bee9e1cc6d88751502dbb8761ee',
 'packages/memory-host-sdk/src/host/session-entry-projection.ts': '34458bdb1827bc240626c7f81f6840ce5b23263e3f37b5342881f3ec9eaaad8d',
 'packages/memory-host-sdk/src/host/session-provenance.ts': '312eac1018ccb49bd98acee26f70a074fa51ed8c17075ad98b8fbbd62469e63b',
 'packages/memory-host-sdk/src/host/session-reset-recall.ts': 'dea5a5ad57b0219692f1e723abe3a5f2cda767cd4888abece657fbd9fc67adb8',
 'packages/memory-host-sdk/src/host/session-reset-recall-read.ts': '8bddd41f9438c901061d7afe61a4dece04d7e5d07e31fc47374aaf0cec291ac6',
 'packages/memory-host-sdk/src/host/openclaw-runtime-session.ts': '51fed14e0695f0caf97d1b3296ed5cdba7b8867bca4de8611509af68fce14eed',
 'extensions/memory-core/src/session-reset-recall-metadata.ts': '280747145a20040a548518ac4f9f2fd87b3de9b42815f75c3dc50d9f93061a26',
 'extensions/memory-core/src/session-ingestion.ts': 'a220ead109095fef8994435b2fe6c51667190574f2ab25d07919bdf1257a8af2',
 'extensions/memory-core/src/memory-entry-origins.ts': 'd84877d05b1621d554260c23b3d4678eb184ffce9ad7fd0255abee67ac3ad0d7',
 'extensions/memory-core/src/memory-session-tombstones.ts': '0ebc12b61cc4d27f868331a68f709968c1fa0ea9a4fe4a1f8e7ec870a350fe2d',
 'extensions/memory-core/src/session-search-visibility.ts': '81027cda9baa0a97809f4ecaa1f39425c1e9029d048830d2c0f1ed5960e98e41',
 'src/plugin-sdk/session-transcript-hit.ts': 'caec67d0d74087beee16741835a720cdd62d34ff252e1400f52acd63870cf9bb',
 'src/plugin-sdk/session-visibility.ts': '75de89f30cb53f1c1d77cc04867f233c2356cec135d8878af711d48d61afeb81',
 'src/plugin-sdk/session-visibility-internal.ts': '89f252bd32762545be633f2b6716c9d1c43c622a7f8b0748a28a22825d00ea02',
 'src/plugin-sdk/memory-core-host-engine-sessions.ts': 'e05da58485856c557ae7e37e97dbffba0da0abe8b72d355261ee784d1db12f7b',
 'src/agents/tools/sessions-access.ts': 'c2c29fe2b8c1a9c91206ea6456ac3c4eb0a518c30c46991e4f5ac2821f737b94',
 'src/agents/tools/in-process-gateway.ts': '28a2a37e490f3a8204c1badadc827d5d1ca3f5ca741670cd5523ca9f98472ee3',
 'src/gateway/server-methods/sessions-read.ts': '5a9402b09b5d94e72d28050f10375d03c50e102fbb86c2a007dfe2d58d8694c6',
 'src/gateway/session-row-projection.ts': '9f6098bf064c4209ce8c906364e5771d9c0b2474d21d216dbeebca9f5ba42b08',
 'src/gateway/session-row-projection-access.ts': '98d3af43cbc79d9ee32f033f9942262248874f4144b4ef2b28d549bbceba6531',
 'src/plugins/runtime/gateway-request-scope.ts': '93b37b160965b90be21a0ea82f7257390a376481f97e2f96c0ea9fb89607478e',
 'src/gateway/server-plugin-in-process-dispatch.ts': 'd5e688b8f50a32bdf6c929030539a7af594845a4d2a525f2be45f77a6d56322c',
 'src/gateway/server-in-process-dispatch.ts': '061d815d0b3a6c98e8d921fb8dd1520857bb27b7bd554bcf142fbfefa178d244',
 'src/config/sessions/session-accessor.ts': 'c9738d2bb1987ce23d3541a3d5d75f7ef282108d6078cea5e91328e6142506ef',
 'src/config/sessions/session-accessor.entry.ts': '47f7e9c5469ec710547e1e15616ca632f3f3bc7c33edfe901039582a701f33bf',
 'src/config/sessions/session-accessor.sqlite-entry.ts': '6601aceca571e65fcd0a1dbf6ed9e1f546fc2c82dca644f699e3a60b27e29156',
 'src/config/sessions/session-accessor.sqlite-read.ts': '6434a27cd8268627fd1787d7afebe2c97792cee17376262534248fb388fa068d',
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': '4e6ee07463e2cd5e1064400535dc332d7c0d2c761997eefb3b59dea6d33a1b0a',
 'src/config/sessions/session-accessor.sqlite-lifecycle.ts': '6f2a110001e2ba92577605d36f9986cc8eea595d5469b836c0e2d0f909f404cd',
 'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11',
 'extensions/memory-core/src/memory/manager-index.worker.ts': 'f68ee277284e834688a38993724a2844be65d581a05abd6455720f61d20452a7',
 'packages/normalization-core/src/record-coerce.ts': '6c0f118fc25744b5bb400faa6d06a36f146f3ff001210a6d07cf008ebd829616',
 'packages/normalization-core/src/string-normalization.ts': '194631a168c6e3d76ad47c4cecdc2781f06a42ac3e1535a4d4a9296c39e1a8a4'}
SOURCE_ANCHORS = {'extensions/memory-core/src/tools.ts': ('export function createMemorySearchTool(options: '
                                         'MemoryToolOptions) {',),
 'extensions/memory-core/src/memory-search-tool-query.ts': ('export async function '
                                                            'executeMemorySearchToolQuery(params: {',),
 'extensions/memory-core/src/memory/manager.ts': ('export class MemoryIndexManager extends '
                                                  'MemorySearchOrchestration implements '
                                                  'MemorySearchManager {',),
 'extensions/memory-core/src/memory/manager-runtime.ts': ('export { MemoryIndexManager };',),
 'extensions/memory-core/src/memory/manager-session-sync-ops.ts': ('export abstract class '
                                                                   'MemoryManagerSessionSyncOps extends '
                                                                   'MemoryManagerWatchOps {',
                                                                   '  protected async '
                                                                   'listSessionCorpusEntries()'),
 'extensions/memory-core/src/memory/manager-session-sync-state.ts': ('export function '
                                                                     'isMemorySessionIndexable(',),
 'src/agents/memory-search-source-policy.ts': ('export function resolveMemorySearchSourcePolicy(params: '
                                               '{',),
 'packages/memory-host-sdk/src/host/session-transcript-corpus.ts': ('export function '
                                                                    'listSessionTranscriptCorpusEntriesForAgentSync(',
                                                                    'export async function '
                                                                    'listSessionTranscriptCorpusEntriesForAgent('),
 'packages/memory-host-sdk/src/host/session-files.ts': ('export async function buildSessionEntry(',
                                                        'export async function buildSessionEntryInProcess(',
                                                        'export function '
                                                        'sessionPathForSessionIdentity(agentId: string, '
                                                        'sessionId: string): string {'),
 'packages/memory-host-sdk/src/host/session-entry-projection.ts': ('export function '
                                                                   'projectSessionEntryRecord(value: '
                                                                   'unknown): unknown {',
                                                                   'export function '
                                                                   'collectRawSessionText(content: '
                                                                   'unknown): string | null {'),
 'packages/memory-host-sdk/src/host/session-provenance.ts': ('export function '
                                                             'classifySessionMessageOrigin(',),
 'packages/memory-host-sdk/src/host/session-reset-recall.ts': ('export function '
                                                               'resolveSessionResetRecallCutoff(',),
 'packages/memory-host-sdk/src/host/session-reset-recall-read.ts': ('export async function '
                                                                    'readSessionResetRecallCutoff(',
                                                                    'export function '
                                                                    'readSessionResetRecallCutoffInProcess('),
 'packages/memory-host-sdk/src/host/openclaw-runtime-session.ts': ('export function '
                                                                   'isDreamingNarrativeSessionStoreKey(sessionKey: '
                                                                   'string): boolean {',),
 'extensions/memory-core/src/session-reset-recall-metadata.ts': ('export function '
                                                                 'readSessionArchiveReasonFromHitPath(',),
 'extensions/memory-core/src/session-ingestion.ts': ('export function resolveAdmissionPolicy(',
                                                     'export function sessionExclusionReason(',
                                                     'export function sessionIngestionSourceFromCorpus('),
 'extensions/memory-core/src/memory-entry-origins.ts': ('export function '
                                                        'listMemorySessionTombstones(params: {',),
 'extensions/memory-core/src/memory-session-tombstones.ts': ('export function hasMemorySessionTombstone(',),
 'extensions/memory-core/src/session-search-visibility.ts': ('export async function '
                                                             'filterMemorySearchHitsBySessionVisibility(params: '
                                                             '{',),
 'src/plugin-sdk/session-transcript-hit.ts': ('export function loadCombinedSessionStoreForGateway(',
                                              'export function resolveTranscriptStemToSessionKeys(params: '
                                              '{',
                                              'export function '
                                              'extractTranscriptIdentityFromSessionsMemoryHit('),
 'src/plugin-sdk/session-visibility.ts': ('export async function createSessionVisibilityGuard(',
                                          'export function createSessionVisibilityRowChecker(params: '
                                          'SessionVisibilityCheckerParams): {'),
 'src/plugin-sdk/session-visibility-internal.ts': ('export function '
                                                   'createSessionVisibilityDecisionChecker(params: '
                                                   'SessionVisibilityDecisionParams): {',
                                                   'export async function '
                                                   'listSpawnedSessionKeysWithResult(params: {'),
 'src/plugin-sdk/memory-core-host-engine-sessions.ts': ('export function loadMemorySessionMetadata(params: '
                                                        '{',),
 'src/agents/tools/sessions-access.ts': ('export async function resolveSessionToolAccess(params: {',),
 'src/agents/tools/in-process-gateway.ts': ('export function bindAgentToolGatewayRequest(options?: {',),
 'src/gateway/server-methods/sessions-read.ts': ('export const sessionReadHandlers: GatewayRequestHandlers '
                                                 '= {',
                                                 'export const sessionsListHandler = '
                                                 'sessionReadHandlers["sessions.list"]!;'),
 'src/gateway/session-row-projection.ts': ('export async function createSessionRowProjection(params: '
                                           'records.ProjectionOptions) {',),
 'src/gateway/session-row-projection-access.ts': ('export function bindSessionRowProjection<T extends '
                                                  'object>(',
                                                  'export function getSessionRowProjection(context?: { '
                                                  'sessionRowProjectionOwner?: object }) {'),
 'src/plugins/runtime/gateway-request-scope.ts': ('export function '
                                                  'withPluginRuntimeGatewayContextResolver<T>(',
                                                  'export function getInProcessGatewayRequestContext('),
 'src/gateway/server-plugin-in-process-dispatch.ts': ('export async function '
                                                      'dispatchGatewayMethodInProcessRaw(',
                                                      'export async function '
                                                      'dispatchGatewayMethodInProcess<T>('),
 'src/gateway/server-in-process-dispatch.ts': ('export async function '
                                               'dispatchGatewayRequestInProcessRaw(',),
 'src/config/sessions/session-accessor.ts': ('export * from "./session-history.js";',),
 'src/config/sessions/session-accessor.entry.ts': ('export function listSessionEntriesCore(scope: '
                                                   'SessionEntryListScope = {}): SessionEntrySummary[] {',
                                                   '  upsertSessionEntryCore,'),
 'src/config/sessions/session-accessor.sqlite-entry.ts': ('export async function upsertSessionEntryCore(',
                                                          'export function '
                                                          'listSessionTranscriptInstances('),
 'src/config/sessions/session-accessor.sqlite-read.ts': ('export function '
                                                         'readTranscriptExportSnapshotReadOnlySync(',
                                                         'export function loadTranscriptEventsSync(scope: '
                                                         'SessionTranscriptReadScope): TranscriptEvent[] '
                                                         '{'),
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': ('export function '
                                                                     'replaceTranscriptEventsSync(',),
 'src/config/sessions/session-accessor.sqlite-lifecycle.ts': ('export async function '
                                                              'resetSessionEntryLifecycle(',
                                                              'export async function '
                                                              'deleteSessionEntryLifecycle('),
 'src/plugin-sdk/session-store-runtime.ts': ('export async function upsertSessionEntry(params: '
                                             'UpsertSessionEntryParams): Promise<void> {',
                                             'export async function deleteSessionEntry(params: '
                                             'DeleteSessionEntryParams): Promise<boolean> {'),
 'extensions/memory-core/src/memory/manager-index.worker.ts': ('serveWorkerTasks<MemoryIndexTaskResult>',),
 'packages/normalization-core/src/record-coerce.ts': ('export function asNullableRecord(value: unknown): '
                                                      'Record<string, unknown> | null {',),
 'packages/normalization-core/src/string-normalization.ts': ('export function '
                                                             'normalizeTrimmedStringList(value: unknown): '
                                                             'string[] {',)}
COMPILED_HASHES = {'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/session-files-DVVT4Ngb.mjs': '0a933051a4cf16dd7f5ddb15df3df6d5c950cd1a09b7fd2729d8c86e54842dc9',
 'dist/session-accessor-CiKKTlbe.mjs': '287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a',
 'dist/session-accessor.sqlite-entry-BrsmAX-T.mjs': 'bb80d5b238fb5eaeb23a0f2a12d9a978b9cafa3962e78984538d801eb6f86e64',
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': 'f351ef360d46add8ead586270b6609b388380cc820d631f7c4ed945e6e506d7e',
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
 'dist/session-accessor.sqlite-lifecycle-BruF_dRG.mjs': '5443c3915a1dcf23045f1b0827d1c16696b98723324a61d41a20cde362c0d8e8',
 'dist/session-search-visibility-BSOBplEm.mjs': 'd7ab86815684e09c631ddc06062dbf62a6063be42c08d595b9f2050d24f63675',
 'dist/sessions-helpers-DM7oZCRf.mjs': 'f6b4dcdfde28d78b00110fc7ffde6f2670798710cd7fad85d3a7f086f4e10db2',
 'dist/session-visibility-BxLDreYk.mjs': '43a5450cce9a08a316fddd0cc7779a62bbcdf0870effc0c95ce1fb88b534938c',
 'dist/session-visibility-internal-DIUpAfkW.mjs': '26d08a04e67ff18e83461f377ffc2b943581959cfad08475cdd372f81423e1bf',
 'dist/sessions-read-DE2RieYZ.mjs': 'e59a71893a509f20219b4d537b0aa231d42dc0b463ddec1fdcc1d24fc4e8569b',
 'dist/session-row-projection-B5-QIpdH.mjs': 'cfc4e2f63c6dd2ab0ab4ac1cbd1a6b42fac88ffd24658faa89909a20f2ccd114',
 'dist/session-row-projection-access-CUCrJD4M.mjs': '958c4738fb38c9f48ac087c3987a53104b7828fd4d2144ac0b483daa494f5f27',
 'dist/gateway-request-scope-Btza1qbw.mjs': 'd6dcdd77a938c1d4fc8ca2fb1435efdd3bbd4d8ef59663df60ebffa9ab353f5f',
 'dist/server-plugin-in-process-dispatch-CBGxjSoo.mjs': '52e483b1c420b61514cc11c8d75fb134ddada9f61f63326a066fd96f78811c37',
 'dist/server-in-process-dispatch-DnQz0IUf.mjs': 'd60c8f3003ce2ac2383380c8ab130f01c2ad9ec30934683697772b85085e9930',
 'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/session-ingestion-Dy5uAq-_.mjs': 'c0dff0210ad2ddcc662224271200840bf99a8e4edbebd9291adf6adaa881ccf3',
 'dist/memory-search-source-policy-B3S1qyBP.mjs': '6067ccdc77a747e519980c5d0ed2202afe42c3402f2f0f657038664bedc03434',
 'dist/manager-vector-warning-DcyxxT5h.mjs': 'c08988b8823ef26532ebb3d82cc098b54577b02d7cf4e8e24ebefaa6cb22539d',
 'dist/memory-entry-origins-BCQSIB3X.mjs': '35506e30b05eb6ebc688b90688b449d06c2a01ffabb0348c1eaa1b1f9d0fd37d',
 'dist/record-coerce-TIsquoVR.mjs': '2e10c9bb93d012791f9fa288da1a6c146f4da17214e87dba2ac11059e8d71a9e',
 'dist/string-normalization-YMwDjufr.mjs': 'c9c5599d8f3f2f4982a78aec74e40e3154f61d14d958a2c60e087625bb8ef97e',
 'dist/extensions/memory-core/memory-index.worker.js': '740d4ac59fd01308335d9f725f2c83cc6565178d428844a1ca5cd2d792a3b27d',
 'dist/manager-index.worker-CinEDBkE.mjs': 'bf8a8a6d0185434fa48f31f82c27010deb8a3b96edf665c2e5d395a68e1b5b61'}
COMPILED_ANCHORS = {'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = class MemoryIndexManager '
                                                    'extends MemorySearchOrchestration {',
                                                    '\tasync listSessionCorpusEntries()'),
 'dist/session-files-DVVT4Ngb.mjs': ('async function buildSessionEntry(absPath, opts = {}) {',
                                     'async function buildSessionEntryInProcess(absPath, opts = {}, '
                                     'redactText = (text) => redactSensitiveText(text, { mode: "tools" })) '
                                     '{',
                                     'async function listSessionTranscriptCorpusEntriesForAgent(agentId, '
                                     'options = {}) {'),
 'dist/session-accessor-CiKKTlbe.mjs': ('export {',),
 'dist/session-accessor.sqlite-entry-BrsmAX-T.mjs': ('async function upsertSessionEntryCore(scope, patch, '
                                                     'options = {}) {',
                                                     'function listSessionTranscriptInstances(scope = {}, '
                                                     'options = {}) {'),
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': ('function '
                                                    'readTranscriptExportSnapshotReadOnlySync(scope, '
                                                    'options = {}) {',
                                                    'function loadTranscriptEventsSync(scope) {'),
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function '
                                                                'replaceTranscriptEventsSync(scope, '
                                                                'events) {',),
 'dist/session-accessor.sqlite-lifecycle-BruF_dRG.mjs': ('async function '
                                                         'resetSessionEntryLifecycle(params) {',
                                                         'async function '
                                                         'deleteSessionEntryLifecycle(params) {'),
 'dist/session-search-visibility-BSOBplEm.mjs': ('async function '
                                                 'filterMemorySearchHitsBySessionVisibility(params) {',),
 'dist/sessions-helpers-DM7oZCRf.mjs': ('async function resolveSessionToolAccess(params) {',),
 'dist/session-visibility-BxLDreYk.mjs': ('async function createSessionVisibilityGuard(params) {',
                                          'function createSessionVisibilityRowChecker(params) {'),
 'dist/session-visibility-internal-DIUpAfkW.mjs': ('function '
                                                   'createSessionVisibilityDecisionChecker(params) {',
                                                   'async function '
                                                   'listSpawnedSessionKeysWithResult(params) {'),
 'dist/sessions-read-DE2RieYZ.mjs': ('const sessionReadHandlers = {',),
 'dist/session-row-projection-B5-QIpdH.mjs': ('async function createSessionRowProjection(params) {',),
 'dist/session-row-projection-access-CUCrJD4M.mjs': ('function bindSessionRowProjection(context, read) {',),
 'dist/gateway-request-scope-Btza1qbw.mjs': ('function '
                                             'withPluginRuntimeGatewayContextResolver(resolveGatewayContext, '
                                             'run, options) {',),
 'dist/server-plugin-in-process-dispatch-CBGxjSoo.mjs': ('async function '
                                                         'dispatchGatewayMethodInProcessRaw(method, '
                                                         'params, options) {',
                                                         'async function '
                                                         'dispatchGatewayMethodInProcess(method, params, '
                                                         'options) {'),
 'dist/server-in-process-dispatch-DnQz0IUf.mjs': ('async function '
                                                  'dispatchGatewayRequestInProcessRaw(method, params, '
                                                  'options) {',),
 'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(options) {',
                             'async function executeMemorySearchToolQuery(params) {'),
 'dist/session-ingestion-Dy5uAq-_.mjs': ('function resolveAdmissionPolicy(pluginConfig) {',
                                         'function sessionExclusionReason(source, policy, '
                                         'forgottenSessionIds) {',
                                         'function sessionIngestionSourceFromCorpus(entry) {'),
 'dist/memory-search-source-policy-B3S1qyBP.mjs': ('function resolveMemorySearchSourcePolicy(params) {',),
 'dist/manager-vector-warning-DcyxxT5h.mjs': ('function isMemorySessionIndexable(entry, '
                                              'archivedSessionKey) {',),
 'dist/memory-entry-origins-BCQSIB3X.mjs': ('function listMemorySessionTombstones(params) {',),
 'dist/record-coerce-TIsquoVR.mjs': ('function asNullableRecord(value) {',),
 'dist/string-normalization-YMwDjufr.mjs': ('function normalizeTrimmedStringList(value) {',),
 'dist/extensions/memory-core/memory-index.worker.js': ('import '
                                                        '"../../manager-index.worker-CinEDBkE.mjs";',),
 'dist/manager-index.worker-CinEDBkE.mjs': ('serveWorkerTasks(',)}

HELPER_ARTIFACTS = (
    "dist/session-ingestion-Dy5uAq-_.mjs", "dist/record-coerce-TIsquoVR.mjs",
    "dist/string-normalization-YMwDjufr.mjs",
)
SOURCE_HASHES["src/config/sessions/session-accessor.lifecycle.ts"] = "e0a806f8943c306c6a84b0a4d1616b31148172d1e0cac3a252ecd8ce25c416af"
SOURCE_ANCHORS["src/config/sessions/session-accessor.lifecycle.ts"] = (
    "  resetSessionEntryLifecycle,", "  deleteSessionEntryLifecycle,",
)
# Canonical recorded archive insertion and actual compressed source readers.
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts'] = '367479304fe74ea16a773c34d1dcaa824e34166933d57fd11f2d0facb7767ac0'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts'] = ('export function persistSessionTranscriptArchive(',)
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-archive-artifact.ts'] = '95a883a073845eea05190543136ab9173d98dece27733ad3dff7a47cef053e9f'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-archive-artifact.ts'] = ('export function resolveRegisteredSqliteTranscriptArchiveName(params: {',)
SOURCE_HASHES['src/config/sessions/archive-compression.ts'] = 'be57fa752f1ee4bcda62090b35e93216665a691b79b8766d84ffe5434b183dda'
SOURCE_ANCHORS['src/config/sessions/archive-compression.ts'] = ('export function readSessionArchiveContentSync(filePath: string): string {', 'export function decodeSessionArchiveBytes(bytes: Uint8Array, compressed: boolean): string {', 'export function materializeSessionArchiveForRead(filePath: string): string {')
SOURCE_HASHES['src/infra/zstd-codec.ts'] = '4ef503fe0fc8f57b7ecb97a04a831fbb15360a28d2b0095e1f28564d545f6f58'
SOURCE_ANCHORS['src/infra/zstd-codec.ts'] = ('export function resolveZstdCodec(): ZstdCodec | null {',)
COMPILED_HASHES['dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs'] = '3c501c076f58466cdc45b2c6b7e95a41546ad0349d91dec1c24f41c8f1ad58b3'
COMPILED_ANCHORS['dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs'] = ('import { a as readSessionTranscriptArchiveResetInventory, c as uniqueTranscriptArchives, i as prepareSessionTranscriptArchivePublishPlans, n as hasPendingSessionTranscriptArchives, o as recordSessionTranscriptArchivePublishResults, r as persistSessionTranscriptArchive, s as transcriptArchiveIdentityKey, t as deleteAllSessionTranscriptArchivesInTransaction } from "./session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs";', 'export { deleteAllSessionTranscriptArchivesInTransaction, hasPendingSessionTranscriptArchives, persistSessionTranscriptArchive, prepareSessionTranscriptArchivePublishPlans, readSessionTranscriptArchiveResetInventory, recordSessionTranscriptArchivePublishResults, transcriptArchiveIdentityKey, uniqueTranscriptArchives };')
COMPILED_HASHES['dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs'] = 'c9ba31679773ad9c290a7399fa6f079e15f0a704256642133d0924a4099e6b1f'
COMPILED_ANCHORS['dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs'] = ('function persistSessionTranscriptArchive(database, plan) {', 'persistSessionTranscriptArchive as r,')
COMPILED_HASHES['dist/session-accessor.sqlite-archive-artifact-Ck-KZoV9.mjs'] = 'a2644ad3620541d6c34eed0f05820c29c200f0e2e41a5ab3befb725cd312ff77'
COMPILED_ANCHORS['dist/session-accessor.sqlite-archive-artifact-Ck-KZoV9.mjs'] = ('function resolveRegisteredSqliteTranscriptArchiveName(params) {', 'resolveRegisteredSqliteTranscriptArchiveName as i,')
COMPILED_HASHES['dist/artifacts-D5koLTEP.mjs'] = '438b315be956f590b1e06ea29ce13009c8818517e4a227c1f3d96500f48958dd'
COMPILED_ANCHORS['dist/artifacts-D5koLTEP.mjs'] = ('function readSessionArchiveContentSync(filePath) {', 'function decodeSessionArchiveBytes(bytes, compressed) {', 'function materializeSessionArchiveForRead(filePath) {', 'materializeSessionArchiveForRead as v, readSessionArchiveContentSync as y')
COMPILED_HASHES['dist/zstd-codec-C-vEb3Qf.mjs'] = 'ffa2adb8e96fe3bce2bb4a1d1af86841973f8f5183170e2fb64e876340e95b5a'
COMPILED_ANCHORS['dist/zstd-codec-C-vEb3Qf.mjs'] = ('function resolveZstdCodec() {', 'export { resolveZstdCodec as t };')
ARCHIVE_PERSIST_ARTIFACTS = (
    "dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs",
    "dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs",
)
ARCHIVE_READ_ARTIFACTS = (
    "dist/session-accessor.sqlite-archive-artifact-Ck-KZoV9.mjs",
    "dist/artifacts-D5koLTEP.mjs", "dist/zstd-codec-C-vEb3Qf.mjs",
)
ARCHIVE_ARTIFACTS = (*ARCHIVE_PERSIST_ARTIFACTS, *ARCHIVE_READ_ARTIFACTS)

# Actual participant recording, canonical projection and identity/limit owners.
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-participants.ts'] = 'f7dc1ecc0b32c75123d717c021a730be8316db745d9e9c6b126e0b4aa947fc1e'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-participants.ts'] = ('export { recordSessionParticipantInWorker as recordSessionParticipant } from "./session-sharing-store.async.js";',)
SOURCE_HASHES['src/config/sessions/session-sharing-store.async.ts'] = '2400e80e4211038cd8174f90be03291e1f0bb46aa5ba2e55eb8f18796ad9d9ec'
SOURCE_ANCHORS['src/config/sessions/session-sharing-store.async.ts'] = ('export function recordSessionParticipantInWorker(',)
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-participants.native.ts'] = '4dafb7dea69bd122b39c650f4e801d5c79fcc207476217bf8a99dfdbf3efe4ff'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-participants.native.ts'] = ('export function recordSessionParticipant(',)
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-participant-read.ts'] = '7c40aae93d2b6b7438428169c7566935171e64db41775876721c2afbafb4a697'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-participant-read.ts'] = ('export function listSessionParticipantsReadOnly(scope: {',)
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-participant-projection.ts'] = 'e629448152fec6732c0d6ba61c3724ab3bfaebb3b03cb418d206602ada1e95de'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-participant-projection.ts'] = ('export function participantRecordsBySessionKey(',)
SOURCE_HASHES['src/config/sessions/session-participant-identity.ts'] = '0f30c429556dddcca6c4e4db52ec19868bba5c17a1782863d3987a45e6019ee1'
SOURCE_ANCHORS['src/config/sessions/session-participant-identity.ts'] = ('export function participantIdentityNamespace(identity: SessionParticipantIdentity): string {', 'export function readParticipantIdentity(namespace: string, id: string): SessionParticipantIdentity {', 'export function mergeParticipantAggregate(')
SOURCE_HASHES['src/config/sessions/session-entry-provenance.ts'] = '7dc8cf3cd1c63c540d5791fa76ce22c504e34bc85e387680214f44c7c940fe44'
SOURCE_ANCHORS['src/config/sessions/session-entry-provenance.ts'] = ('export const MAX_SESSION_PARTICIPANTS = SESSION_EXPANDED_PARTICIPANT_LIMIT;',)
SOURCE_HASHES['packages/gateway-protocol/src/schema/session-participant.ts'] = '0e13b778c98e1c7160749a0b16ddaeebfa64725d089c03796fdd32cf56f1df28'
SOURCE_ANCHORS['packages/gateway-protocol/src/schema/session-participant.ts'] = ('export const SessionParticipantIdentitySchema = Type.Union([', 'export const SESSION_EXPANDED_PARTICIPANT_LIMIT = 32;')
COMPILED_HASHES['dist/session-accessor-WMUIp1Kx.mjs'] = 'ee241de4a74bc1d44529b4c8ddba311ba1285147bdf965c1cb64b253d502e131'
COMPILED_ANCHORS['dist/session-accessor-WMUIp1Kx.mjs'] = ('function recordSessionParticipantInWorker(scope, params) {', 'function listSessionParticipantsReadOnly(scope) {', 'recordSessionParticipantInWorker as V,', 'listSessionParticipantsReadOnly as i,')
COMPILED_HASHES['dist/session-sharing-store.native-BimL-D2p.mjs'] = 'aebaab26efa1bd90032da848404ccf17715faf39b4b1c525bf6aefe14dcfb915'
COMPILED_ANCHORS['dist/session-sharing-store.native-BimL-D2p.mjs'] = ('function recordSessionParticipant(scope, params) {', 'export { recordSessionParticipant as i,')
COMPILED_HASHES['dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs'] = 'cad4258ac1e98dcf2979cbdad92b60555e94ecfbe1985d6d0acdc59e3b19a8c9'
COMPILED_ANCHORS['dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs'] = ('function participantIdentityNamespace(identity) {', 'function readParticipantIdentity(namespace, id) {', 'function mergeParticipantAggregate(current, incoming, mode) {', 'function participantRecordsBySessionKey(database, sessionKeys) {')
COMPILED_HASHES['dist/session-participant-BgfyKr4q.mjs'] = 'edcf766bff7d82b52d8dde1a1b92172413e2924ac0521c2d7ed6a0863cbac459'
COMPILED_ANCHORS['dist/session-participant-BgfyKr4q.mjs'] = ('const SessionParticipantIdentitySchema = Type.Union([', 'const SESSION_EXPANDED_PARTICIPANT_LIMIT = 32;', 'SessionParticipantIdentitySchema as r,')
COMPILED_HASHES['dist/session-entry-provenance-BWZtrWXT.mjs'] = 'a2e2c728afdd85f30333a3d742db6b417abe907db297a866bcf6df1c164d3f5f'
COMPILED_ANCHORS['dist/session-entry-provenance-BWZtrWXT.mjs'] = ('const MAX_SESSION_PARTICIPANTS = 32;', 'MAX_SESSION_PARTICIPANTS as t')
COMPILED_ANCHORS['dist/session-accessor-CiKKTlbe.mjs'] += ('V as recordSessionParticipantInWorker', 'i as listSessionParticipantsReadOnly', 'recordSessionParticipantInWorker as recordSessionParticipant')
PARTICIPANT_ARTIFACTS = ('dist/session-accessor-WMUIp1Kx.mjs', 'dist/session-sharing-store.native-BimL-D2p.mjs', 'dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs', 'dist/session-participant-BgfyKr4q.mjs', 'dist/session-entry-provenance-BWZtrWXT.mjs')

# Upserts retain exclusion provenance through the actual session-window writer.
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-provenance.ts'] = '3ee47509fcd9ea96f1e952aaac88ac6041c2cddc67e1daf50726fc5de5796b60'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-provenance.ts'] = ('export function bindSessionEntryProvenance(entry: SessionEntry): SessionProvenanceRow {', 'export function resolveSessionEntryProvenanceRow<T extends SessionProvenanceRow>(params: {')
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-entry-store.ts'] = 'dab59c106015aa568800f7b6bab23955356f66c577445112113f91ae4faa55d7'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-entry-store.ts'] = ('export function writeSessionEntry(', '  const sessionRow = resolveSessionEntryProvenanceRow({')
COMPILED_HASHES['dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs'] = '6ca1b431135ea1c8e70c8c4785902f519c4af6a2ec334e1561dddd3d680864bb'
COMPILED_ANCHORS['dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs'] = ('function resolveSessionEntryProvenanceRow(params) {', 'function writeSessionEntry(database, sessionKey, entry, options = {}) {', 'const sessionRow = resolveSessionEntryProvenanceRow({', 'writeSessionEntry as f,')

# Private session identities route genuine accessor writes to a volatile SQLite owner.
SOURCE_HASHES['src/plugin-sdk/session-key-runtime.ts'] = 'e4057c351baa47f87f91b9bd77b2a0037654b3395fe3db0aec2cbc005dcebad4'
SOURCE_ANCHORS['src/plugin-sdk/session-key-runtime.ts'] = ('  isIncognitoSessionKey,', '} from "../routing/session-key.js";')
SOURCE_HASHES['src/routing/session-key.ts'] = 'f581697b1bde74523a78aa3cdea5fd4b11e73374544b1471c0af6c489bf90899'
SOURCE_ANCHORS['src/routing/session-key.ts'] = ('export { isIncognitoSessionKey } from "../shared/incognito-session-key.js";',)
SOURCE_HASHES['src/shared/incognito-session-key.ts'] = 'b239e14905359b79ccc4abcc0295143e9fe069dcf8b294b65489f5d249108c87'
SOURCE_ANCHORS['src/shared/incognito-session-key.ts'] = ('export { isIncognitoSessionKey } from "../../packages/session-url-contract/src/session-key.js";',)
SOURCE_HASHES['packages/session-url-contract/src/session-key.ts'] = 'f9115545a74167e58ac551b183566f3c6257f54563eaaea4a68937de8bfaecc4'
SOURCE_ANCHORS['packages/session-url-contract/src/session-key.ts'] = ('export function isIncognitoSessionKey(sessionKey: string | undefined | null): boolean {', '  /^agent:[^:]+:(?:dashboard|subagent|internal-session-effects):incognito-[^:]+$/u;')
SOURCE_HASHES['src/config/sessions/session-accessor.transcript-target.ts'] = 'fa62e1f5a025b008fe4552f0b54dfa9586c0f4aee76719aea9031d8a6725db58'
SOURCE_ANCHORS['src/config/sessions/session-accessor.transcript-target.ts'] = ('export function resolveSessionTranscriptDatabasePath(',)
SOURCE_HASHES['src/config/sessions/session-accessor.sqlite-scope.ts'] = 'e25872af2b96c39bb5617bf67829ba082ada27523553b77a56cd52f8c2d57636'
SOURCE_ANCHORS['src/config/sessions/session-accessor.sqlite-scope.ts'] = ('function resolveSqliteDatabaseScopeIdentity(scope: SqliteScopeInput) {', 'export function resolveSqliteTranscriptScope(')
SOURCE_HASHES['src/state/openclaw-agent-db.paths.ts'] = '830bac274b664ac13b13b9c498e79da318999a2217c0a29062a6a4d7ddfc6cf7'
SOURCE_ANCHORS['src/state/openclaw-agent-db.paths.ts'] = ('export const INCOGNITO_AGENT_SQLITE_BASENAME = "incognito-openclaw-agent.sqlite";', 'export function resolveIncognitoOpenClawAgentSqlitePath(', 'export function isIncognitoOpenClawAgentSqlitePath(')
SOURCE_HASHES['src/state/openclaw-agent-db.ts'] = 'f28a4f20493b63d9d3ce88e5811e82733b4989068b400d9219736ddce84b5781'
SOURCE_ANCHORS['src/state/openclaw-agent-db.ts'] = ('export function openOpenClawAgentDatabase(', 'function* openOpenClawAgentDatabaseSteps(', '    const db = openNodeSqliteDatabase(":memory:", { allowExtension });')
COMPILED_HASHES['dist/plugin-sdk/session-key-runtime.js'] = 'd7ed2472090673b14b7e07cf3f8713b33ba32bf50f1ee49ed7f929039830e10c'
COMPILED_ANCHORS['dist/plugin-sdk/session-key-runtime.js'] = ('import { r as isIncognitoSessionKey } from "../session-key-DDIJxXfQ.mjs";', 'export { isIncognitoSessionKey, resolveAgentIdFromSessionKey };')
COMPILED_HASHES['dist/session-key-DDIJxXfQ.mjs'] = '6f3a97336701c837c42f3d1182a3c1b24af5600de4373f1c3057952b4190d9af'
COMPILED_ANCHORS['dist/session-key-DDIJxXfQ.mjs'] = ('function isIncognitoSessionKey(sessionKey) {', 'isIncognitoSessionKey as r,')
COMPILED_HASHES['dist/session-accessor.transcript-target-vG-nGtYV.mjs'] = '01158efffa0ae0a91dea780bccaf63d22a65ff73f65ef8a24cbc0770910dc51f'
COMPILED_ANCHORS['dist/session-accessor.transcript-target-vG-nGtYV.mjs'] = ('function resolveSessionTranscriptDatabasePath(target) {', 'resolveSessionTranscriptDatabasePath as n,')
COMPILED_HASHES['dist/session-accessor.sqlite-scope-CUtOKov2.mjs'] = 'e0f90ad9529e8141371c45781e975dc60977447a30e8b0970dc5edfcd16f360e'
COMPILED_ANCHORS['dist/session-accessor.sqlite-scope-CUtOKov2.mjs'] = ('function resolveSqliteDatabaseScopeIdentity(scope) {', 'const incognitoAgentId = isIncognitoSessionKey(scope.sessionKey) ? resolveAgentIdFromSessionKey(scope.sessionKey) : void 0;')
COMPILED_HASHES['dist/openclaw-agent-db.paths-Dv3PPTNK.mjs'] = '4e27befc30963b354b9d1098832c6d8202a54cd40d1b188908f89e7321102945'
COMPILED_ANCHORS['dist/openclaw-agent-db.paths-Dv3PPTNK.mjs'] = ('const INCOGNITO_AGENT_SQLITE_BASENAME = "incognito-openclaw-agent.sqlite";', 'function resolveIncognitoOpenClawAgentSqlitePath(options) {', 'function isIncognitoOpenClawAgentSqlitePath(pathname, options) {')
COMPILED_HASHES['dist/openclaw-agent-db-DRy3ui_B.mjs'] = 'f851c6fa5b6a766e6afff83684ad02883c45589532bd8ac1e790f20bbb3b0d93'
COMPILED_ANCHORS['dist/openclaw-agent-db-DRy3ui_B.mjs'] = ('function* openOpenClawAgentDatabaseSteps(options, pending, preparedLease, registrationObserver) {', 'const db = openNodeSqliteDatabase(":memory:", { allowExtension });', 'openOpenClawAgentDatabase as c,')
INCOGNITO_ARTIFACTS = ('dist/plugin-sdk/session-key-runtime.js', 'dist/session-key-DDIJxXfQ.mjs', 'dist/session-accessor.transcript-target-vG-nGtYV.mjs', 'dist/session-accessor.sqlite-scope-CUtOKov2.mjs', 'dist/openclaw-agent-db.paths-Dv3PPTNK.mjs', 'dist/openclaw-agent-db-DRy3ui_B.mjs')

HOSTED_GATEWAY_ARTIFACTS = (
    "dist/sessions-helpers-DM7oZCRf.mjs", "dist/sessions-read-DE2RieYZ.mjs",
    "dist/session-row-projection-B5-QIpdH.mjs", "dist/session-row-projection-access-CUCrJD4M.mjs",
    "dist/gateway-request-scope-Btza1qbw.mjs", "dist/server-plugin-in-process-dispatch-CBGxjSoo.mjs",
    "dist/server-in-process-dispatch-DnQz0IUf.mjs",
)
MEMORY_INDEX_WORKER_ARTIFACTS = (
    "dist/extensions/memory-core/memory-index.worker.js", "dist/manager-index.worker-CinEDBkE.mjs",
)
FLOW_ARTIFACTS = tuple(name for name in COMPILED_HASHES
                       if name not in {*HOSTED_GATEWAY_ARTIFACTS, *MEMORY_INDEX_WORKER_ARTIFACTS,
                                       *ARCHIVE_ARTIFACTS, *PARTICIPANT_ARTIFACTS,
                                       *INCOGNITO_ARTIFACTS})
REQUIRED_LOADED_ARTIFACTS_BY_PROFILE = {
    "session-contract-runtime": list(FLOW_ARTIFACTS),
    "session-contract-helper-runtime": list(HELPER_ARTIFACTS),
}


class SessionAdmissionRuntimeBindingError(ValueError):
    """The reviewed session owners or separately authenticated release changed."""


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if (any(part.is_symlink() for part in (file, *file.parents) if part != root)
                or not file.resolve().is_relative_to(root)):
            raise SessionAdmissionRuntimeBindingError("A session runtime owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise SessionAdmissionRuntimeBindingError("A session runtime owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise SessionAdmissionRuntimeBindingError("A session owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def _named_link(sources: dict[str, str], module: str, specifier: str,
                names: tuple[str, ...], *, kind: str) -> dict:
    try:
        return _named(sources, module, specifier, names, kind=kind)
    except ReferenceBindingError:
        # The unchanged canonical entry barrel contains explanatory comments
        # inside its export list. Parse only those declaration tokens, retaining
        # the SHA and line of the complete original bytes; no module is altered.
        candidates = []
        for match in _NAMED_FROM.finditer(sources[module]):
            if match["kind"] != kind or match["specifier"] != specifier or match["types"]:
                continue
            if "//" not in match["names"]:
                continue
            tokens = re.sub(r"//[^\n]*", "", match["names"])
            bindings = []
            for item in tokens.split(","):
                item = item.strip()
                if not item or item.startswith("type "):
                    continue
                parsed = re.fullmatch(r"([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?", item)
                if parsed is None:
                    raise SessionAdmissionRuntimeBindingError("An original session import token changed.")
                bindings.append((parsed[1], parsed[2] or parsed[1]))
            if all((name, name) in bindings for name in names):
                candidates.append(match)
        if len(candidates) != 1:
            raise SessionAdmissionRuntimeBindingError("An original commented session import changed.") from None
        match = candidates[0]
        return {"path": module, "kind": kind, "specifier": specifier, "bindings": list(names),
                "line": sources[module][:match.start()].count("\n") + 1,
                "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest(),
                "originalDeclarationCommentsPreserved": True}


def _links(sources: dict[str, str]) -> list[dict]:
    specs = (
        ("extensions/memory-core/src/memory/manager-runtime.ts", "./manager.js",
         ("getMemoryIndexManagerRegistry", "MemoryIndexManager"), "import"),
        ("extensions/memory-core/src/memory/manager-session-sync-ops.ts", "./manager-session-sync-state.js",
         ("isMemorySessionIndexable", "resolveMemorySessionStartupState"), "import"),
        ("extensions/memory-core/src/memory/manager-session-sync-ops.ts",
         "openclaw/plugin-sdk/memory-core-host-engine-sessions",
         ("listSessionTranscriptCorpusEntriesForAgent", "loadArchivedSessions", "sessionPathForSessionIdentity"), "import"),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./session-transcript-corpus.js",
         ("listSessionTranscriptCorpusEntriesForAgentSync",), "import"),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./session-entry-projection.js",
         ("collectRawSessionText", "projectSessionEntryRecord"), "import"),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./session-provenance.js",
         ("classifySessionMessageOrigin",), "import"),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./session-reset-recall.js",
         ("resolveSessionResetRecallCutoff",), "import"),
        ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts",
         "../../../../src/config/sessions/session-accessor.js", ("listSessionEntriesCore", "listSessionEntriesReadOnly"), "export"),
        ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts",
         "../../../../src/config/sessions/session-accessor.js", ("readTranscriptExportSnapshotReadOnlySync",), "import"),
        ("extensions/memory-core/src/memory-search-tool-query.ts", "./session-search-visibility.js",
         ("filterMemorySearchHitsBySessionVisibility",), "import"),
        ("extensions/memory-core/src/session-search-visibility.ts", "openclaw/plugin-sdk/session-visibility",
         ("createAgentToAgentPolicy", "createSessionVisibilityGuard", "resolveEffectiveSessionToolsVisibility",
          "resolveSandboxSessionToolsVisibility"), "import"),
        ("extensions/memory-core/src/session-search-visibility.ts", "openclaw/plugin-sdk/session-transcript-hit",
         ("extractTranscriptIdentityFromSessionsMemoryHit", "loadCombinedSessionStoreForGateway",
          "resolveTranscriptStemToSessionKeys"), "import"),
        ("extensions/memory-core/src/session-search-visibility.ts", "./session-reset-recall-metadata.js",
         ("readSessionArchiveReasonFromHitPath",), "import"),
        ("src/plugin-sdk/session-visibility.ts", "./session-visibility-internal.js",
         ("createSessionVisibilityDecisionChecker", "listSpawnedSessionKeysWithResult"), "import"),
        ("src/agents/tools/in-process-gateway.ts", "../../gateway/server-plugin-in-process-dispatch.js",
         ("dispatchGatewayMethodInProcess", "getInProcessGatewayRequestContext"), "import"),
        ("src/gateway/server-plugin-in-process-dispatch.ts", "./server-in-process-dispatch.js",
         ("dispatchGatewayRequestInProcessRaw", "unwrapGatewayMethodDispatchResponse"), "import"),
        ("src/gateway/server-methods/sessions-read.ts", "../session-row-projection-access.js",
         ("getSessionRowProjection",), "import"),
        ("src/gateway/server-methods/sessions-read.ts", "../../config/sessions/session-accessor.js",
         ("listSessionEntriesReadOnly", "withSessionEntryReadOnlyScope"), "import"),
        ("src/config/sessions/session-accessor.ts", "./session-accessor.entry.js",
         ("listSessionEntriesCore", "listSessionEntriesReadOnly", "upsertSessionEntryCore"), "export"),
        ("src/config/sessions/session-accessor.entry.ts", "./session-accessor.sqlite-entry.js",
         ("upsertSessionEntryCore",), "export"),
        ("src/config/sessions/session-accessor.ts", "./session-accessor.transcript.js",
         ("readTranscriptExportSnapshotReadOnlySync", "replaceTranscriptEvents", "replaceTranscriptEventsSync"), "export"),
        ("src/config/sessions/session-accessor.ts", "./session-accessor.lifecycle.js",
         ("resetSessionEntryLifecycle", "deleteSessionEntryLifecycle"), "export"),
        ("src/config/sessions/session-accessor.lifecycle.ts", "./session-accessor.sqlite-lifecycle.js",
         ("resetSessionEntryLifecycle", "deleteSessionEntryLifecycle"), "export"),
        ("src/plugin-sdk/session-store-runtime.ts", "../config/sessions/session-accessor.js",
         ("loadSessionEntryReadOnly", "updateSessionEntry"), "import"),
        ("extensions/memory-core/src/session-ingestion.ts", "openclaw/plugin-sdk/memory-core-host-engine-sessions",
         ("loadMemorySessionMetadata",), "import"),
        ("extensions/memory-core/src/session-ingestion.ts", "./memory-entry-origins.js",
         ("listMemorySessionTombstones",), "import"),
        ("src/plugin-sdk/memory-core-host-engine-sessions.ts", "../config/sessions/session-accessor.js",
         ("listSessionTranscriptInstances",), "import"),
        ("src/config/sessions/session-accessor.ts", "./session-accessor.sqlite-participants.js",
         ("recordSessionParticipant",), "export"),
        ("src/config/sessions/session-accessor.ts", "./session-accessor.sqlite-participant-read.js",
         ("listSessionParticipantsReadOnly",), "export"),
        ("src/config/sessions/session-sharing-store.async.ts", "./session-accessor.sqlite-participants.native.js",
         ("recordSessionParticipant",), "import"),
        ("src/config/sessions/session-accessor.sqlite-participants.native.ts", "./session-participant-identity.js",
         ("participantIdentityNamespace", "mergeParticipantAggregate"), "import"),
        ("src/config/sessions/session-accessor.sqlite-participants.native.ts", "./session-entry-provenance.js",
         ("MAX_SESSION_PARTICIPANTS",), "import"),
        ("src/config/sessions/session-accessor.sqlite-participant-read.ts", "./session-accessor.sqlite-participant-projection.js",
         ("participantRecordsBySessionKey",), "import"),
        ("src/config/sessions/session-accessor.sqlite-participant-projection.ts", "./session-participant-identity.js",
         ("readParticipantIdentity",), "import"),
        ("src/config/sessions/session-participant-identity.ts", "../../../packages/gateway-protocol/src/schema/session-participant.js",
         ("SessionParticipantIdentitySchema",), "import"),
        ("src/config/sessions/session-entry-provenance.ts", "../../../packages/gateway-protocol/src/schema/session-participant.js",
         ("SESSION_EXPANDED_PARTICIPANT_LIMIT",), "import"),
        ("src/plugin-sdk/session-key-runtime.ts", "../routing/session-key.js",
         ("isIncognitoSessionKey",), "export"),
        ("src/routing/session-key.ts", "../shared/incognito-session-key.js",
         ("isIncognitoSessionKey",), "export"),
        ("src/shared/incognito-session-key.ts", "../../packages/session-url-contract/src/session-key.js",
         ("isIncognitoSessionKey",), "export"),
        ("src/config/sessions/session-accessor.transcript-target.ts", "./session-accessor.sqlite-scope.js",
         ("resolveSqliteTranscriptScope", "toDatabaseOptions"), "import"),
        ("src/config/sessions/session-accessor.transcript-target.ts", "../../state/openclaw-agent-db.js",
         ("resolveOpenClawAgentSqlitePath",), "import"),
        ("src/config/sessions/session-accessor.sqlite-scope.ts", "../../routing/session-key.js",
         ("isIncognitoSessionKey", "resolveAgentIdFromSessionKey"), "import"),
        ("src/config/sessions/session-accessor.sqlite-scope.ts", "../../state/openclaw-agent-db.js",
         ("openOpenClawAgentDatabase", "resolveIncognitoOpenClawAgentSqlitePath", "resolveOpenClawAgentSqlitePath"), "import"),
        ("src/state/openclaw-agent-db.ts", "./openclaw-agent-db.paths.js",
         ("isIncognitoOpenClawAgentSqlitePath", "resolveOpenClawAgentSqlitePath"), "import"),
        ("src/state/openclaw-agent-db.ts", "./openclaw-agent-db.paths.js",
         ("resolveIncognitoOpenClawAgentSqlitePath",), "export"),
        ("src/config/sessions/session-accessor.sqlite-entry-store.ts", "./session-accessor.sqlite-provenance.js",
         ("resolveSessionEntryProvenanceRow",), "import"),
        ("src/config/sessions/session-accessor.sqlite-entry.ts", "./session-accessor.sqlite-entry-store.js",
         ("readLifecycleTargetSnapshot", "readSessionEntrySelectionSnapshot"), "import"),
        ("src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts",
         "./session-accessor.sqlite-archive-artifact.js", ("resolveRegisteredSqliteTranscriptArchiveName",), "import"),
        ("src/config/sessions/session-accessor.sqlite-archive-artifact.ts", "./archive-compression.js",
         ("encodeSessionArchiveContent", "readSessionArchiveContentSync", "SESSION_ARCHIVE_ZSTD_SUFFIX"), "import"),
        ("src/config/sessions/archive-compression.ts", "../../infra/zstd-codec.js", ("resolveZstdCodec",), "import"),
        ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts",
         "../../../../src/config/sessions/archive-compression.js", ("materializeSessionArchiveForRead",), "export"),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./openclaw-runtime-session.js",
         ("materializeSessionArchiveForRead",), "import"),
    )
    chain = [_named_link(sources, module, specifier, names, kind=kind)
             for module, specifier, names, kind in specs]
    participant_alias_owner = "src/config/sessions/session-accessor.sqlite-participants.ts"
    participant_alias = 'export { recordSessionParticipantInWorker as recordSessionParticipant } from "./session-sharing-store.async.js";'
    if sources[participant_alias_owner].count(participant_alias) != 1:
        raise SessionAdmissionRuntimeBindingError("The original public participant recording alias changed.")
    chain.append({"path": participant_alias_owner, "kind": "export-alias",
                  "specifier": "./session-sharing-store.async.js", "originalBinding": "recordSessionParticipantInWorker",
                  "exportedBinding": "recordSessionParticipant",
                  "line": sources[participant_alias_owner][:sources[participant_alias_owner].index(participant_alias)].count("\n") + 1,
                  "declarationSha256": hashlib.sha256(participant_alias.encode()).hexdigest()})
    module = "src/plugin-sdk/session-visibility-internal.ts"
    anchor = '(await import("../agents/tools/in-process-gateway.js")).bindAgentToolGatewayRequest'
    if sources[module].count(anchor) != 1:
        raise SessionAdmissionRuntimeBindingError("The native hosted Gateway ownership lookup changed.")
    chain.append({"path": module, "kind": "dynamic-import",
                  "specifier": "../agents/tools/in-process-gateway.js",
                  "binding": "bindAgentToolGatewayRequest",
                  "line": sources[module][:sources[module].index(anchor)].count("\n") + 1,
                  "declarationSha256": hashlib.sha256(anchor.encode()).hexdigest()})
    return chain


def prepare_session_admission_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Pin real session flow owners and a separate compiled policy helper profile."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise SessionAdmissionRuntimeBindingError("Session flow evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        chain = _links(sources)
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError, ValueError) as error:
        raise SessionAdmissionRuntimeBindingError("Session runtime provenance could not be verified.") from error
    return {
        "kind": "official-release-session-admission-visibility-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False, "managerFixture": False,
        "defaultProfile": "session-contract-runtime", "topLevelFlagsApplyToProfile": "session-contract-runtime",
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "fullGatewayHTTPVerified": False, "providerTransportVerified": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain, "compiledBindings": compiled_evidence,
        "entrypoints": {
            "manager": {"path": "dist/extensions/memory-core/manager-runtime.js", "export": "MemoryIndexManager",
                        "methods": ["get", "sync", "search", "listSessionCorpusEntries", "close"]},
            "catalog": {"path": "dist/session-files-DVVT4Ngb.mjs", "export": "l",
                        "originalBinding": "listSessionTranscriptCorpusEntriesForAgent"},
            "snapshot": {"path": "dist/session-files-DVVT4Ngb.mjs", "export": "t", "originalBinding": "buildSessionEntry"},
            "accessor": {"path": "dist/session-accessor-CiKKTlbe.mjs", "exports": ["replaceTranscriptEvents", "resetSessionEntryLifecycle"]},
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemorySearchTool"},
            "visibility": {"path": "dist/session-search-visibility-BSOBplEm.mjs", "export": "t",
                           "originalBinding": "filterMemorySearchHitsBySessionVisibility"},
            "admissionPolicy": {"path": "dist/session-ingestion-Dy5uAq-_.mjs", "export": "s", "originalBinding": "resolveAdmissionPolicy"},
            "exclusion": {"path": "dist/session-ingestion-Dy5uAq-_.mjs", "export": "l", "originalBinding": "sessionExclusionReason"},
            "hostedProjection": {"path": "dist/session-row-projection-B5-QIpdH.mjs", "export": "t", "originalBinding": "createSessionRowProjection"},
        },
        "requiredLoadedArtifactsByProfile": REQUIRED_LOADED_ARTIFACTS_BY_PROFILE,
        "additionalHostedGatewayArtifacts": list(HOSTED_GATEWAY_ARTIFACTS),
        "additionalArchiveArtifacts": list(ARCHIVE_ARTIFACTS),
        "archiveReadArtifacts": list(ARCHIVE_READ_ARTIFACTS),
        "archivePersistArtifacts": list(ARCHIVE_PERSIST_ARTIFACTS),
        "archiveArtifactsRequiredWhen": {
            "read": "input.archives or nested step.archives",
            "persist": "any input or nested step archive has a recorded identity",
        },
        "additionalParticipantArtifacts": list(PARTICIPANT_ARTIFACTS),
        "participantArtifactsRequiredWhen": "any initial or nested step session has nonempty participants",
        "additionalIncognitoArtifacts": list(INCOGNITO_ARTIFACTS),
        "incognitoArtifactsRequiredWhen": "any initial or nested step session key is classified private by the actual public owner",
        "incognitoAuthority": {
            "publicClassifier": {"path": "dist/plugin-sdk/session-key-runtime.js", "export": "isIncognitoSessionKey"},
            "classifierOwner": "packages/session-url-contract/src/session-key.ts",
            "runtimeDatabaseTarget": "src/config/sessions/session-accessor.transcript-target.ts",
            "scopeOwner": "src/config/sessions/session-accessor.sqlite-scope.ts",
            "sentinelOwner": "src/state/openclaw-agent-db.paths.ts",
            "databaseOwner": "src/state/openclaw-agent-db.ts",
            "sqliteTarget": ":memory:",
            "privateStatePersisted": False,
            "fullDurableSessionContractVerified": False,
            "restartRecallVerified": False,
        },
        "sessionWriteProvenanceAuthority": {
            "originalOwner": "src/config/sessions/session-accessor.sqlite-provenance.ts",
            "originalBinding": "resolveSessionEntryProvenanceRow",
            "sourceCaller": "src/config/sessions/session-accessor.sqlite-entry-store.ts",
            "callerBinding": "writeSessionEntry",
            "compiledOwner": "dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs",
            "monotonicSessionWindowFacts": ["session_entry_provenance", "acp_owned", "plugin_owner_id", "hook_external_content_source"],
            "callerLifecycleProofRequired": True,
        },
        "participantAuthority": {
            "publicWrite": {"path": "dist/session-accessor-CiKKTlbe.mjs", "export": "recordSessionParticipant"},
            "asyncWrite": {"path": "dist/session-accessor-WMUIp1Kx.mjs", "export": "V",
                           "originalBinding": "recordSessionParticipantInWorker"},
            "nativeWrite": {"path": "dist/session-sharing-store.native-BimL-D2p.mjs", "export": "i",
                            "originalBinding": "recordSessionParticipant"},
            "publicRead": {"path": "dist/session-accessor-CiKKTlbe.mjs", "export": "listSessionParticipantsReadOnly"},
            "readProjection": {"path": "dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs",
                               "originalBindings": ["participantRecordsBySessionKey", "participantIdentityNamespace",
                                                    "readParticipantIdentity", "mergeParticipantAggregate"]},
            "retainedIdentityLimit": 32,
            "participantMetadataGrantsVisibility": False,
        },
        "archiveFixtureAuthority": {
            "recordedArchiveInsertion": {
                "path": "dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs",
                "export": "persistSessionTranscriptArchive",
                "implementationPath": "dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs",
                "originalOwner": "src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts",
            },
            "sourceRead": {
                "path": "dist/artifacts-D5koLTEP.mjs",
                "originalOwner": "src/config/sessions/archive-compression.ts",
                "bindings": ["materializeSessionArchiveForRead", "readSessionArchiveContentSync", "decodeSessionArchiveBytes"],
            },
            "decompression": {
                "path": "dist/zstd-codec-C-vEb3Qf.mjs", "export": "t", "originalBinding": "resolveZstdCodec",
                "originalOwner": "src/infra/zstd-codec.ts", "codec": "node:zlib.zstdDecompressSync",
            },
            "fullArchivePublisherLifecycleVerified": False,
        },
        "hostedGatewayArtifactsRequiredWhen": "input.gateway or effective visibility tree/all",
        "requiredMemoryIndexWorkerArtifacts": list(MEMORY_INDEX_WORKER_ARTIFACTS),
        "workerRequiredByProfile": {"session-contract-runtime": True, "session-contract-helper-runtime": False},
        "profiles": {
            "session-contract-runtime": {"constructorSkipped": False, "managerFixture": False,
                "workerRequired": True, "realFileIO": True, "realSqliteIO": True, "managerOverrides": [],
                "requiresMemoryIndexWorkerProof": True, "incidentalSqlWorkersSatisfyIndexProof": False,
                "rawFlowObservationsRequired": ["sessionWrites", "catalog", "admitted", "sourceEntries", "chunks", "provenance", "candidateHits", "nativeEnvelopes"],
                "hostedGatewayHTTPServerStarted": False},
            "session-contract-helper-runtime": {"constructorSkipped": False, "managerFixture": False,
                "workerRequired": False, "helperOnly": True, "helperToWholeFlowCredit": False,
                "executedBinding": "resolveAdmissionPolicy", "realSqliteIO": False,
                "indexPublicationVerified": False, "sessionVisibilityVerified": False},
        },
        "fixtureBoundary": "Whole-flow cases persist transcript facts through genuine accessors, construct "
                           "the provider-none manager, execute real sync/index/search/read/filter owners, and retain "
                           "complete raw catalog, source, SQL and tool payload evidence. Hosted tree/all lookups "
                           "use genuine in-process Gateway projection and core dispatch; fixture context methods "
                           "record request lifetimes and supply no accepted hit or visibility decision. Indexing "
                           "requires authenticated memory-index worker thread evidence, not incidental SQLite "
                           "workers. The separate compiled admission-policy helper earns no whole-flow credit. "
                           "No model transport, general ranking equivalence, full Gateway HTTP server, or complete "
                           "host orchestration is established by this profile.",
    }
