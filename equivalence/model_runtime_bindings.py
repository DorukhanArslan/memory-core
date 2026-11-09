"""Authenticate separately pinned compiled model-result and AgentSession owners.

These declarations never grant source execution or claim an index manager,
network provider, full host, or reproduced source build. Runtime collectors must
still authenticate actual owner execution in the applicable fresh OS process.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _owners, _named_link

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'src/agents/embedded-agent-tool-results.ts': 'c09cf7dbaff78bbaa0918edf6dcbcff2ccc2414bcb3fc7a41062a8de3f1e579d',
 'src/agents/embedded-agent-tool-result-cache.ts': 'daf7826ca4aefcded6d80174cca40d2604a6f458563946d08ec88000075953dc',
 'src/logging/redact.ts': 'ecdfdb1e0f4b0f2aa3eb54aad574bb5375ae8da78539ad937b34ba02dd170e7b',
 'src/logging/redact-internal.ts': '94cd7ce5f4ed88d2fcdbc3530e4dd7b291095feff65d76a33cc5de3f73a97e1e',
 'src/logging/redact-internal-state.ts': '31d768d62ac50efd1d443fd27cec301b95363070be564ed5caa3616608d67def',
 'src/logging/secret-redaction-registry.ts': '217d789ec4e6b3896dc7c647d33a8a2eed2df4b754fa0abf93a577296863f689',
 'src/security/config-regex.ts': '438a598fcaebefc20d5e612c52f189bc2a32b83a492399917407e63128d8a1b5',
 'src/agents/transcript-redact.ts': 'd7ff59f554d3ef940b20b4276cc58c7d0ab68ba818a289a1d80970fed42ba95c',
 'src/agents/transcript-redact-text.ts': '0346abdc593ce0dce13dc4919143e6a92ab6ef7855c4ae72ed8f78ef356e8d78',
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': 'e658ffefb7c1c8cfc6ad4c416d8f2f20657cb59f8412eac951e1d8e564afa50d',
 'src/agents/session-tool-result-guard-wrapper.ts': 'ba2e0d2406c559a6e310a20955a28f7c143b4deb916c2aa640dce37a7fc32c9c',
 'src/agents/session-tool-result-guard.ts': '174aa005b10c2b55dcbe36152843e8da31cdcc9d8bfe4e4e38efbc34a3b74e90',
 'src/agents/session-tool-result-guard.payload.ts': '729b9cbcafd37267f431765337e18fe806cbbb455adcfbec2da4bd646f11df60',
 'src/agents/sessions/sdk.ts': 'f642105da707de4dd50445e7aecbafd5c6e4fac776fbedca99b0fc11f9491981',
 'src/agents/sessions/agent-session-base.ts': 'b8bd37b75f34217201e7327c9423ca60ae1928488c83ab36d677e4eae8e83456',
 'src/agents/sessions/session-tool-result-redaction.ts': 'cb854ac407ab2cc07b67a39feaea986316cdb914b217816baae49dbc0f495fa6',
 'src/agents/sessions/session-manager.ts': '869ea03b12fa586bedc4938c68e13f3c879e4a8de67a57173a275fb1b05fe0ff',
 'src/agents/sessions/session-manager-core.ts': '71d82092b70d2177279e71100702954e672904c6190ee0c67c8317b8d3300847',
 'src/agents/sessions/session-manager-persistence.ts': '1c52a15df875e15554e3d08bc6b4d513d3d2f041ac7580d94f3709f273af032a',
 'packages/agent-core/src/harness/session/session.ts': 'b9da8aab7693741eec60cd43d3e33b36d91e2c2ad2afbc7695320c8bf838350e',
 'packages/agent-core/src/harness/messages.ts': 'cfa370ab4c489262dc769f30c6b07ce6b90c974a2c6cb49d8a366a5edaf20d64',
 'src/config/sessions/transcript-visible-events.ts': '15250a85089fc04749f3e82bb37008b178149acdb85dfc3b0a4387e2386ec774',
 'src/config/sessions/transcript-tree.ts': '5b24acb49cdc8634ccb4afad80226e371705775fce9945a7ef2426ac219ff945',
 'src/config/sessions/session-accessor.sqlite-read.ts': '6434a27cd8268627fd1787d7afebe2c97792cee17376262534248fb388fa068d',
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': '4e6ee07463e2cd5e1064400535dc332d7c0d2c761997eefb3b59dea6d33a1b0a',
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': '6cbf0606d549cd2fae2e80e63181a0ff81e2eebfe32f8f93f4593d3832947618',
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': '05c4ad331965633ecf0cd850fa7b3e4e1072b62b2728d14f2175a4a5f8dcf79c',
 'src/config/sessions/transcript-header.ts': 'df2f0da864f5c642bc2b2f76332525d8dab52feb282fd959247acf99f55bc0b7',
 'src/config/sessions/version.ts': '39a17391fd9d6c7e73d6ea619a04c8fc47c674f70ec14e0bb4d1786f1e2fc3d3',
 'src/config/sessions/session-accessor.sqlite-transcript-state.ts': 'c978eebfed78ac252f5f84dd346662ff4c10b51792d1f4d9a9bc6cd91c9489d4',
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': 'e2db126148df6df03a8c09cb628f58130ba34d70b5088817f2446699c316ae74',
 'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11',
 'src/plugin-sdk/config-runtime.ts': '34cbd9c1d5dc0e5356795b29251b3e889b2b752532db908036053dbd23e65248',
 'src/config/runtime-snapshot.ts': '16f1308be97b38b2524026c3367d9653248522ae60861b3ddbc770d127ba0d5d',
 'src/agents/sessions/model-registry.ts': '8f60d28dd28d60580ef13dfb2a730c0ebcb5d29e8949f6e31dfb996257b1d0e8',
 'src/agents/sessions/auth-storage.ts': 'b02173e2abc5f971b154a1c57dd279cc66eff1e9e534bf0bde9ba6a9d3b8982c',
 'src/agents/sessions/resource-loader.ts': 'c7786a19be722b6fe65d9b85eb3e8fbb20404d355c4f814cb9667d3b53949b29',
 'src/agents/sessions/settings-manager.ts': '703716957bcd5ad867828c78182474bc655402e253671ee6109a1ed37b5449fe',
 'packages/llm-core/src/utils/event-stream.ts': 'c04b8859e2ffe373cf796d997f964b6dddff637711188d4befc1111282942dbd',
 'src/state/openclaw-agent-db-lifecycle.ts': 'a49e35f38d6584969d28183cec435581b6a6797bd4b4eaf3f7b5d7507429b16c',
 'src/state/openclaw-agent-db.ts': 'f28a4f20493b63d9d3ce88e5811e82733b4989068b400d9219736ddce84b5781',
 'src/plugin-sdk/sqlite-runtime.ts': '6fa47548183e9c9425d541051cecbb6f6fb1b611dbe8e5b8bd78fc6d698ce903',
 'src/infra/node-sqlite.ts': '0ba2bd399fcfc0c3c3dd0e9e44d1a3ead8936c786eb7fed7e4e12ad0012171cd'}

SOURCE_ANCHORS = {'src/agents/embedded-agent-tool-results.ts': ('export function sanitizeToolArgs(args: unknown): unknown {',
                                               'export function sanitizeToolResult(result: unknown): unknown '
                                               '{'),
 'src/agents/embedded-agent-tool-result-cache.ts': ('export function memoizeSanitizedToolResult',),
 'src/logging/redact.ts': ('export function prepareModelVisibleToolTextBlock',),
 'src/logging/redact-internal.ts': ('export function isPreparedModelVisibleToolText(',),
 'src/logging/redact-internal-state.ts': ('export const modelVisibleToolTextRedactionState = {',
                                          'export function captureModelVisibleRedactionPolicy('),
 'src/logging/secret-redaction-registry.ts': ('export function registerSecretValueForRedaction(value: '
                                              'string): void {',
                                              'export function getSecretRedactionRegistryRevision(): number '
                                              '{'),
 'src/security/config-regex.ts': ('export function compileConfigRegex(',),
 'src/agents/transcript-redact.ts': ('export function redactTranscriptMessage(',),
 'src/agents/transcript-redact-text.ts': ('export function resolveTranscriptLoggingConfig(cfg?: '
                                          'OpenClawConfig) {',),
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': ('export function '
                                                                     'redactTranscriptMessageForStorage',),
 'src/agents/session-tool-result-guard-wrapper.ts': ('export function guardSessionManager(',),
 'src/agents/session-tool-result-guard.ts': ('export function installSessionToolResultGuard(',),
 'src/agents/session-tool-result-guard.payload.ts': ('function sanitizeToolResultDetailsForPersistence(',),
 'src/agents/sessions/sdk.ts': ('export async function createAgentSession(',),
 'src/agents/sessions/agent-session-base.ts': ('export abstract class AgentSessionBase {',),
 'src/agents/sessions/session-tool-result-redaction.ts': ('export function prepareSessionToolResult(',
                                                          'export function setSessionToolTextPreparer('),
 'src/agents/sessions/session-manager.ts': ('export class SessionManager extends SessionManagerBranching {',),
 'src/agents/sessions/session-manager-core.ts': ('export class SessionManagerCore extends '
                                                 'SessionEntryNavigation<SessionEntry> {',),
 'src/agents/sessions/session-manager-persistence.ts': ('export class SessionManagerPersistence extends '
                                                        'SessionManagerCore {',),
 'packages/agent-core/src/harness/session/session.ts': ('export function buildSessionContext(',),
 'packages/agent-core/src/harness/messages.ts': ('export function convertToLlm(',),
 'src/config/sessions/transcript-visible-events.ts': ('export function selectVisibleTranscriptEvents<T>',),
 'src/config/sessions/transcript-tree.ts': ('export function scanSessionTranscriptTree<T>',),
 'src/config/sessions/session-accessor.sqlite-read.ts': ('export function loadTranscriptEventsSync(scope: '
                                                         'SessionTranscriptReadScope): TranscriptEvent[] {',),
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': ('export function '
                                                                     'appendTranscriptMessageSync',),
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': ('export function '
                                                                              'prepareTranscriptMessageAppend',
                                                                              'export function '
                                                                              'appendTranscriptMessageInTransaction'),
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': ('export function '
                                                                      'ensureTranscriptHeader(',),
 'src/config/sessions/transcript-header.ts': ('export function createSessionTranscriptHeader(',),
 'src/config/sessions/version.ts': ('export const CURRENT_SESSION_VERSION = 4;',),
 'src/config/sessions/session-accessor.sqlite-transcript-state.ts': ('export function '
                                                                     'ensureTranscriptGenerationInTransaction(',),
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': ('export function '
                                                                      'createTranscriptEntryAnchor(params: '
                                                                      '{',),
 'src/plugin-sdk/session-store-runtime.ts': ('export async function upsertSessionEntry(params: '
                                             'UpsertSessionEntryParams): Promise<void> {',),
 'src/plugin-sdk/config-runtime.ts': ('  setRuntimeConfigSnapshot,',),
 'src/config/runtime-snapshot.ts': ('export function setRuntimeConfigSnapshot(',
                                    'export function clearRuntimeConfigSnapshot(): void {'),
 'src/agents/sessions/model-registry.ts': ('export class ModelRegistry {',),
 'src/agents/sessions/auth-storage.ts': ('export class AuthStorage {',),
 'src/agents/sessions/resource-loader.ts': ('export class DefaultResourceLoader implements ResourceLoader '
                                            '{',),
 'src/agents/sessions/settings-manager.ts': ('export class SettingsManager {',),
 'packages/llm-core/src/utils/event-stream.ts': ('export function createAssistantMessageEventStream(): '
                                                 'AssistantMessageEventStream {',),
 'src/state/openclaw-agent-db-lifecycle.ts': ('export async function '
                                              'closeOpenClawAgentDatabasesAsync(rootPath?: string): '
                                              'Promise<void> {',),
 'src/state/openclaw-agent-db.ts': ('export function openOpenClawAgentDatabase(',),
 'src/plugin-sdk/sqlite-runtime.ts': ('  openOpenClawAgentDatabase,',),
 'src/infra/node-sqlite.ts': ('export function openNodeSqliteDatabase(',)}

COMPILED_HASHES = {'dist/embedded-agent-tool-results-Bhhd5B_V.mjs': 'e3dc1f14a399d9c8e825818bf044e9876f78b8b509cdee3d7b08fde9b03e9263',
 'dist/redact-BCoakatc.mjs': '17028994a6670b397e171921efdcd01f00c1b8d4058db5216d62f976e74a65d6',
 'dist/secret-redaction-registry-b2B9lcfy.mjs': '432fe8ecb1999ef09de6a40878fcedf717eb570ec024a75d77f9e5667cd62f24',
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': 'deb4cca4a9d2fc66702e5adc2f3882f620e8d1533fbe7107a7cd95869d54cf5e',
 'dist/resource-loader-DhipPm1N.mjs': '064381fbe5c874077b1c20155219dc2158f823a6382f1498bef1db74745bd15f',
 'dist/resource-loader-N7_h4_No.mjs': '32795276297fcdec904b7db6f93a475ac19b06d8c092dac3e5a2cb2d081bf4eb',
 'dist/session-manager-a8MFS1Kk.mjs': '68ddd46bc2f5661ee217e4ff87cd357b654941f85c2f79232bee061d13f3229e',
 'dist/session-BA9qunLx.mjs': '76e83df0e3056d87ac01eeb929a1b1f5a4722ef274653e3bafef4c64fc9468cd',
 'dist/plugin-sdk/config-runtime.js': 'ca8ea03ec6a8eeb48c4f300f7a88171aba943e6999a40791205d0027bd1d2a18',
 'dist/runtime-snapshot-BFi3jxlO.mjs': '0cb73088d71ff77c47d63931a00d9c771b5fc5c205ad77f3588335c8a908f9cb',
 'dist/plugin-sdk/session-store-runtime.js': '495b19c73cb71dce90914b28d0c9492da41622fbdfb7a4966885ba7f83cbbba2',
 'dist/session-store-runtime-C3lQUqXM.mjs': '42c91a431b20934055e124edf556bffdb57e203615f814fd6c6067654c5caf20',
 'dist/session-accessor-CiKKTlbe.mjs': '287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a',
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': 'f351ef360d46add8ead586270b6609b388380cc820d631f7c4ed945e6e506d7e',
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': '252ed9e8717da3b64bee74c0948425d77519bf520b1e131e381d985ec4fb73a0',
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': '26e983f0f600c413613e54b7c8978db7defc046c8bd4a542e75764209e969a95',
 'dist/transcript-header-CP-ow2Zr.mjs': '4adbb6f0a5d024dd72cff7e77b6ef8ddeec3f7955399980fc421e8c815844608',
 'dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs': '18876ef6dd39f1771b5a4b7b656ce5c44272d063a8e6c465f98c07a39280031d',
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': 'dbe095833b6deabf938291cab994d3361534731fa78fbab80e60226727c01393',
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': 'ece2b2b08f3e03c8ddb3dc70e29265f23c6b3df52e37e981e79a6bbd424a5a84',
 'dist/model-registry-CyECwbEb.mjs': 'f7f489dd33417b01e17d0a43fa40ead7c44fe9c77b9cc022d7e03874db559f84',
 'dist/plugin-sdk/llm.js': 'a1c874911df1fc79453cb978277cc52d708f233b41fbba58bdcce6a92106c1b1',
 'dist/llm-ASoRyt-k.mjs': '00a1ffd0459c90d077d3f245633d4ac94d145901ed56b62112cb84cb94aab01f',
 'dist/openclaw-agent-db-DRy3ui_B.mjs': 'f851c6fa5b6a766e6afff83684ad02883c45589532bd8ac1e790f20bbb3b0d93',
 'dist/plugin-sdk/sqlite-runtime.js': '7187fd3a726470e9fb5154a95aa17de55fabc3bf8026b5910a6dbb28137dd431',
 'dist/node-sqlite-DRQTiYwd.mjs': '5008332cd5a0ba99eae3194a790bff4979b5b05f99c2c8c69312d7471f200504'}

COMPILED_ANCHORS = {'dist/embedded-agent-tool-results-Bhhd5B_V.mjs': ('function sanitizeToolArgs(args) {',
                                                   'function sanitizeToolResult(result) {',
                                                   'const sanitizedResults = /* @__PURE__ */ new WeakMap();',
                                                   'sanitizeToolResult as u'),
 'dist/redact-BCoakatc.mjs': ('function prepareModelVisibleToolTextBlock(',
                              'function isPreparedModelVisibleToolText(',
                              'function captureModelVisibleRedactionPolicy(',
                              'prepareModelVisibleToolTextBlock as o',
                              'isPreparedModelVisibleToolText as U'),
 'dist/secret-redaction-registry-b2B9lcfy.mjs': ('function registerSecretValueForRedaction(value) {',
                                                 'function getSecretRedactionRegistryRevision() {',
                                                 'getSecretRedactionRegistryRevision as r',
                                                 'registerSecretValueForRedaction as s'),
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': ('function '
                                                                'redactTranscriptMessageForStorage(message, '
                                                                'options) {',
                                                                'redactTranscriptMessageForStorage as c'),
 'dist/resource-loader-DhipPm1N.mjs': ('function guardSessionManager(sessionManager, opts) {',
                                       'async function createAgentSession(options = {}) {',
                                       'function sanitizeToolResultDetailsForPersistence(details, '
                                       'redactionConfig) {',
                                       'guardSessionManager as i',
                                       'createAgentSession as n'),
 'dist/resource-loader-N7_h4_No.mjs': ('function prepareSessionToolResult(sessionManager, event) {',
                                       'function setSessionToolTextPreparer(sessionManager, prepare) {',
                                       'var SettingsManager = class SettingsManager {',
                                       'var DefaultResourceLoader = class {',
                                       'AgentSession as n'),
 'dist/session-manager-a8MFS1Kk.mjs': ('var SessionManager = class SessionManager extends '
                                       'SessionManagerBranching {',
                                       'SessionManager as t'),
 'dist/session-BA9qunLx.mjs': ('function buildSessionContext(', 'function convertToLlm('),
 'dist/plugin-sdk/config-runtime.js': (' D as setRuntimeConfigSnapshot,',
                                       'saveCronStore, setRuntimeConfigSnapshot, updateConfig'),
 'dist/runtime-snapshot-BFi3jxlO.mjs': ('function setRuntimeConfigSnapshot(config, sourceConfig) {',
                                        'function clearRuntimeConfigSnapshot() {'),
 'dist/plugin-sdk/session-store-runtime.js': ('v as upsertSessionEntry } from '
                                              '"../session-store-runtime-C3lQUqXM.mjs";',),
 'dist/session-store-runtime-C3lQUqXM.mjs': ('async function upsertSessionEntry(params) {',),
 'dist/session-accessor-CiKKTlbe.mjs': ('export {', 'u as loadTranscriptEventsSync,'),
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': ('function loadTranscriptEventsSync(scope) {',),
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function appendTranscriptMessageSync(scope, '
                                                                'options) {',),
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': ('function '
                                                                      'prepareTranscriptMessageAppend(',
                                                                      'function '
                                                                      'appendTranscriptMessageInTransaction('),
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': ('function ensureTranscriptHeader(',),
 'dist/transcript-header-CP-ow2Zr.mjs': ('function createSessionTranscriptHeader(',),
 'dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs': ('function '
                                                                'ensureTranscriptGenerationInTransaction(',),
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': ('function createTranscriptEntryAnchor(',),
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': ('async function '
                                                   'closeOpenClawAgentDatabasesAsync(rootPath) {',
                                                   'closeOpenClawAgentDatabasesAsync as s'),
 'dist/model-registry-CyECwbEb.mjs': ('var AuthStorage = class AuthStorage {',
                                      'var ModelRegistry = class ModelRegistry {',
                                      'AuthStorage as i',
                                      'ModelRegistry as t'),
 'dist/plugin-sdk/llm.js': ('x as createAssistantMessageEventStream, y as resolveProviderContext } from '
                            '"../llm-ASoRyt-k.mjs";',),
 'dist/llm-ASoRyt-k.mjs': ('function createAssistantMessageEventStream() {',
                           'createAssistantMessageEventStream as x'),
 'dist/openclaw-agent-db-DRy3ui_B.mjs': ('function openOpenClawAgentDatabase(options, preparedLease, '
                                         'registrationObserver) {',
                                         'openOpenClawAgentDatabase as c'),
 'dist/plugin-sdk/sqlite-runtime.js': (' c as openOpenClawAgentDatabase,', 'export { SqliteWorkerError,'),
 'dist/node-sqlite-DRQTiYwd.mjs': ('function openNodeSqliteDatabase(location, options) {',
                                   'openNodeSqliteDatabase as t')}

SOURCE_LINKS = (('src/agents/embedded-agent-tool-results.ts',
  '../logging/redact.js',
  ('redactModelVisibleSecrets', 'redactModelVisibleToolPayloadText'),
  'import'),
 ('src/agents/embedded-agent-tool-results.ts',
  './embedded-agent-tool-result-cache.js',
  ('memoizeSanitizedToolResult',),
  'import'),
 ('src/logging/redact-internal.ts',
  './redact-internal-state.js',
  ('fullContextToolPayloadRedactionState', 'modelVisibleToolTextRedactionState'),
  'import'),
 ('src/logging/redact-internal-state.ts',
  './secret-redaction-registry.js',
  ('getSecretRedactionRegistryRevision',),
  'import'),
 ('src/agents/transcript-redact.ts',
  '../logging/redact-internal.js',
  ('copyPreparedModelVisibleToolText', 'isPreparedModelVisibleToolText'),
  'import'),
 ('src/agents/transcript-redact.ts',
  './transcript-redact-text.js',
  ('resolveTranscriptLoggingConfig',),
  'import'),
 ('src/agents/session-tool-result-guard-wrapper.ts',
  '../logging/redact.js',
  ('prepareModelVisibleToolTextBlock',),
  'import'),
 ('src/agents/session-tool-result-guard-wrapper.ts',
  './sessions/session-tool-result-redaction.js',
  ('setSessionToolTextPreparer',),
  'import'),
 ('src/agents/session-tool-result-guard-wrapper.ts',
  './session-tool-result-guard.js',
  ('installSessionToolResultGuard',),
  'import'),
 ('src/agents/session-tool-result-guard-wrapper.ts',
  './transcript-redact.js',
  ('redactTranscriptMessage',),
  'import'),
 ('src/agents/session-tool-result-guard.payload.ts',
  '../logging/redact.js',
  ('redactSensitiveFieldValueWithConfig', 'redactToolPayloadTextWithConfig'),
  'import'),
 ('src/agents/sessions/session-tool-result-redaction.ts',
  '../../logging/redact.js',
  ('prepareModelVisibleToolTextBlock',),
  'import'),
 ('src/agents/sessions/agent-session-base.ts',
  './session-tool-result-redaction.js',
  ('prepareSessionToolResult',),
  'import'),
 ('src/agents/sessions/sdk.ts', './auth-storage.js', ('AuthStorage',), 'import'),
 ('src/agents/sessions/sdk.ts', './model-registry.js', ('ModelRegistry',), 'import'),
 ('src/agents/sessions/sdk.ts', './resource-loader.js', ('DefaultResourceLoader',), 'import'),
 ('src/agents/sessions/sdk.ts', './session-manager.js', ('SessionManager',), 'import'),
 ('src/agents/sessions/sdk.ts', './settings-manager.js', ('SettingsManager',), 'import'),
 ('src/agents/sessions/session-manager.ts',
  '../../config/sessions/session-accessor.sqlite-read.js',
  ('loadTranscriptReadSnapshotSync',),
  'import'),
 ('src/agents/sessions/session-manager.ts',
  '../../config/sessions/session-accessor.sqlite-transcript-write.js',
  ('appendTranscriptMessageSync',),
  'import'),
 ('src/agents/sessions/session-manager-persistence.ts',
  '../../logging/redact-internal.js',
  ('copyPreparedModelVisibleToolText',),
  'import'),
 ('src/agents/sessions/session-manager-persistence.ts',
  '../../config/sessions/session-accessor.sqlite-transcript-write.js',
  ('appendTranscriptEventSnapshotSync', 'appendTranscriptMessageSnapshotSync'),
  'import'),
 ('src/plugin-sdk/sqlite-runtime.ts',
  '../state/openclaw-agent-db.js',
  ('openOpenClawAgentDatabase',),
  'export'),
 ('src/plugin-sdk/sqlite-runtime.ts', '../infra/node-sqlite.js', ('openNodeSqliteDatabase',), 'export'))

LITERAL_SOURCE_LINKS = (('src/plugin-sdk/config-runtime.ts',
  'export {\n'
  '  clearConfigCache,\n'
  '  clearRuntimeConfigSnapshot,\n'
  '  getRuntimeConfigSourceSnapshot,\n'
  '  getRuntimeConfigSnapshot,\n'
  '  getRuntimeConfig,\n'
  '  /**\n'
  '   * @deprecated Use getRuntimeConfig(), runtime.config.current(), or pass the\n'
  '   * already loaded config through the call path. Runtime code must not reload\n'
  '   * config on demand. Bundled plugins and repo code are blocked from using\n'
  '   * this by the deprecated-internal-config-api architecture guard.\n'
  '   */\n'
  '  loadConfig,\n'
  '  readConfigFileSnapshotForWrite,\n'
  '  setRuntimeConfigSnapshot,\n'
  '  /**\n'
  '   * @deprecated Use mutateConfigFile() or replaceConfigFile() with an explicit\n'
  '   * afterWrite intent so restart behavior stays under host control. Bundled\n'
  '   * plugins and repo code are blocked from using this by the\n'
  '   * deprecated-internal-config-api architecture guard.\n'
  '   */\n'
  '  writeConfigFile,\n'
  '} from "../config/io.js";',
  'export'),)

COMPILED_LINKS = (('dist/embedded-agent-tool-results-Bhhd5B_V.mjs',
  'import { G as matchesModelVisibleRedactionPolicy, W as captureModelVisibleRedactionPolicy, b as '
  'redactToolPayloadText, d as redactModelVisibleToolPayloadText, l as redactModelVisibleSecrets, m as '
  'redactSensitiveFieldValue, q as readLoggingConfig, u as redactModelVisibleSensitiveFieldValueWithConfig } '
  'from "./redact-BCoakatc.mjs";'),
 ('dist/resource-loader-DhipPm1N.mjs',
  'import { a as isSensitiveFieldKey, h as redactSensitiveFieldValueWithConfig, o as '
  'prepareModelVisibleToolTextBlock, x as redactToolPayloadTextWithConfig } from "./redact-BCoakatc.mjs";'),
 ('dist/resource-loader-DhipPm1N.mjs',
  'import { a as sessionManagerReadInitialContext, n as SessionMetadataCommittedError, r as '
  'withSessionCompactionPersistence, t as SessionManager } from "./session-manager-a8MFS1Kk.mjs";'),
 ('dist/session-manager-a8MFS1Kk.mjs',
  'import { b as copyCodeModeSourceAppendOptions, c as redactTranscriptMessageForStorage, t as '
  'appendTranscriptEventInTransaction, x as getCodeModeSourceAppend, y as copyCodeModeSourceAppend } from '
  '"./session-accessor.sqlite-transcript-store-DEXEZWnC.mjs";'),
 ('dist/session-manager-a8MFS1Kk.mjs', 'import { t as buildSessionContext } from "./session-BA9qunLx.mjs";'),
 ('dist/plugin-sdk/config-runtime.js',
  'import { D as setRuntimeConfigSnapshot, l as getRuntimeConfigSourceSnapshot, n as '
  'clearRuntimeConfigSnapshot, o as getRuntimeConfigSnapshot } from "../runtime-snapshot-BFi3jxlO.mjs";'),
 ('dist/plugin-sdk/sqlite-runtime.js',
  'import { c as openOpenClawAgentDatabase, p as withOpenClawAgentDatabaseAsync, t as '
  'borrowOpenClawAgentDatabase } from "../openclaw-agent-db-DRy3ui_B.mjs";'),
 ('dist/plugin-sdk/sqlite-runtime.js',
  'import { i as resolveExistingSqliteFileUri, t as openNodeSqliteDatabase } from '
  '"../node-sqlite-DRQTiYwd.mjs";'))

HELPER_SOURCE_PATHS = ('src/agents/embedded-agent-tool-results.ts',
 'src/agents/embedded-agent-tool-result-cache.ts',
 'src/logging/redact.ts',
 'src/logging/redact-internal.ts',
 'src/logging/redact-internal-state.ts',
 'src/logging/secret-redaction-registry.ts',
 'src/security/config-regex.ts',
 'src/agents/transcript-redact.ts',
 'src/agents/transcript-redact-text.ts',
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts',
 'src/plugin-sdk/config-runtime.ts',
 'src/config/runtime-snapshot.ts')

REQUIRED_HELPER_ARTIFACTS = ('dist/embedded-agent-tool-results-Bhhd5B_V.mjs',
 'dist/redact-BCoakatc.mjs',
 'dist/secret-redaction-registry-b2B9lcfy.mjs',
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs',
 'dist/plugin-sdk/config-runtime.js',
 'dist/runtime-snapshot-BFi3jxlO.mjs')

REQUIRED_SESSION_READ_ARTIFACTS = (
    "dist/session-manager-a8MFS1Kk.mjs", "dist/session-BA9qunLx.mjs",
    "dist/session-accessor-CiKKTlbe.mjs", "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    "dist/plugin-sdk/sqlite-runtime.js", "dist/openclaw-agent-db-DRy3ui_B.mjs",
    "dist/node-sqlite-DRQTiYwd.mjs", "dist/secret-redaction-registry-b2B9lcfy.mjs",
    "dist/plugin-sdk/config-runtime.js", "dist/runtime-snapshot-BFi3jxlO.mjs",
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
)
REQUIRED_SESSION_WRITE_ARTIFACTS = (
    "dist/resource-loader-DhipPm1N.mjs", "dist/resource-loader-N7_h4_No.mjs",
    "dist/model-registry-CyECwbEb.mjs", "dist/plugin-sdk/llm.js", "dist/llm-ASoRyt-k.mjs",
    "dist/embedded-agent-tool-results-Bhhd5B_V.mjs", "dist/redact-BCoakatc.mjs",
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
    "dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs",
    "dist/transcript-header-CP-ow2Zr.mjs", "dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs",
    "dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs",
    "dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs",
)


class ModelRuntimeBindingError(ValueError):
    """A reviewed model-result or AgentSession owner changed."""


def _prepare(checkout: Path, runtime_root: Path, *, helper: bool) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ModelRuntimeBindingError("Model owners require the unchanged pinned reference checkout.")
        source_paths = HELPER_SOURCE_PATHS if helper else tuple(SOURCE_HASHES)
        artifact_paths = REQUIRED_HELPER_ARTIFACTS if helper else tuple(COMPILED_HASHES)
        sources, source_evidence = _owners(checkout, {p: SOURCE_HASHES[p] for p in source_paths},
                                           {p: SOURCE_ANCHORS[p] for p in source_paths}, committed=True)
        compiled_sources, compiled_evidence = _owners(
            runtime_root, {p: COMPILED_HASHES[p] for p in artifact_paths},
            {p: COMPILED_ANCHORS[p] for p in artifact_paths}, committed=False)
        source_links = [_named_link(sources, module, specifier, names, kind=kind)
                        for module, specifier, names, kind in SOURCE_LINKS if module in sources]
        for module, declaration, kind in LITERAL_SOURCE_LINKS:
            if module not in sources:
                continue
            text = sources[module]
            if text.count(declaration) != 1:
                raise ModelRuntimeBindingError("An original commented model owner export changed.")
            source_links.append({"path": module, "kind": kind, "declaration": declaration,
                                 "line": text[:text.index(declaration)].count("\n") + 1,
                                 "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest(),
                                 "originalDeclarationCommentsPreserved": True})
        compiled_links = []
        for module, declaration in COMPILED_LINKS:
            if module not in compiled_sources:
                continue
            text = compiled_sources[module]
            if text.count(declaration) != 1:
                raise ModelRuntimeBindingError("A compiled model owner import linkage changed.")
            compiled_links.append({"path": module, "kind": "import", "declaration": declaration,
                                   "line": text[:text.index(declaration)].count("\n") + 1,
                                   "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()})
    except (OSError, UnicodeError, ValueError) as error:
        raise ModelRuntimeBindingError("Model runtime owner provenance could not be verified.") from error
    result = {
        "kind": "official-release-model-tool-result" if helper else "official-release-model-session",
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "sourceExecutionPermitted": False, "wholeRuntimeCompiled": True,
        "sourceBindings": source_evidence, "sourceImportLinks": source_links,
        "compiledBindings": compiled_evidence, "compiledImportLinks": compiled_links,
        "indexManagerConstructed": False, "memorySearchExecuted": False,
        "modelProviderNetworkVerified": False, "fullHostOrchestrationVerified": False,
        "allSourcePolicyVerified": False, "privateMarkerFabricated": False,
        "globalRegistryResetPermitted": False, "testEnvironmentSwitchPermitted": False,
        "registryIsolation": "fresh OS process for every case and every session phase",
        "clock": {"owner": "node:test", "apis": ["Date"], "realTimersAndPerformance": True},
        "runtimeEngine": {"nodeVersion": "v24.16.0", "unicodeVersion": "17.0",
                          "executableRealpathAndSha256Required": True, "icuVersionRequired": True},
    }
    if helper:
        result.update(requiredArtifacts=list(REQUIRED_HELPER_ARTIFACTS),
                      completeReturnAndIdentityObservationsRequired=True,
                      agentSessionConstructed=False, sessionManagerConstructed=False,
                      persistenceScope="original storage helper return; no persisted append claimed")
    else:
        result.update(requiredArtifactsByPhase={
            "write": list(dict.fromkeys((*REQUIRED_SESSION_READ_ARTIFACTS, *REQUIRED_SESSION_WRITE_ARTIFACTS))),
            "continue": list(dict.fromkeys((*REQUIRED_SESSION_READ_ARTIFACTS, *REQUIRED_SESSION_WRITE_ARTIFACTS))),
            "verify": list(REQUIRED_SESSION_READ_ARTIFACTS)},
            agentSessionConstructedInPhases=["write", "continue"],
            verifyPhaseApplicationWritesPermitted=False,
            continuationHistoryTransportPermitted=False,
            verifyPhaseInput="literal persisted identity only; no scripts, tool results, registry registrations or history",
            persistenceScope="actual guarded AgentSession append, SQLite reopen and model context")
    return result


def prepare_model_session_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    return _prepare(checkout, runtime_root, helper=False)


def prepare_model_tool_result_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    return _prepare(checkout, runtime_root, helper=True)
