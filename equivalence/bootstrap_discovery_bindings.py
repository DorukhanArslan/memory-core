"""Authenticate the whole original bootstrap callers, not their execution results.

All source files are reviewed pinned owners. The independent release remains the
executable authority; no source execution, rebuilt release or workspace-wide
lifecycle equivalence is established by this manifest.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
CANONICAL_BOOTSTRAP_FILES = ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md", "MEMORY.md")

SOURCE_HASHES = {'src/agents/workspace.ts': 'd21f6fde6d603c6f3c892c8c2232177585c983bad90f47ba227626527b061844',
 'src/agents/bootstrap-files.ts': '96fba72f04aa4887220a4857244102a22f83e2853f5333459d2834cf42f25dfe',
 'src/agents/workspace-bootstrap-policy.ts': '0c10667389202cdcb8cb85f2d8d7eb5c1a3424b4a112b165f802bd0b26a1d822',
 'src/agents/workspace-bootstrap-publish.ts': 'abad65e904b473f569e4875664fee1d1ff53b6d3d9f8c3cdf428246f079a9659',
 'src/agents/workspace-bootstrap-read.ts': 'f50c1e3af6684694025e505cf4ebcbac13e4330ff24b2ee3074edff8fe8fd219',
 'src/agents/workspace-file-read.ts': '852d1dff9dafe5d41d7d267be6ab549569f74a6629454e38e37ed1b735d47c9b',
 'src/agents/workspace-file-cache.ts': 'a49e7493fbb1aa3f047122db81faaa8852f469545553459b39d5c1894af278ec',
 'src/agents/workspace-templates.ts': '5d61733f98421e118acc2c804262fecdfb423fb73f822a6e0ad95043148d0b02',
 'src/agents/workspace-state-store.ts': '479b538124256a12a0c782b3bbe57fa699575cc4b7f8318ae5cc5289a7c65cbf',
 'src/agents/workspace-state-store.kernel.ts': 'fef18452a42219dfda23f23a312558049684cc24078f0fa4f1520e409d20e2b0',
 'src/agents/workspace-state-identity.ts': 'a26484e438ce735befc655b3102a9b1e1de0881cd7ccaddbb2f048fbe4e0d759',
 'src/agents/workspace-legacy-state.ts': 'c63ec0f67d7153710b718b5be161587c7025f8a517e287517eb1b098ef53ee22',
 'src/agents/workspace-access.ts': '523513a275e9da000d1a67cba774e6d3bc1df818f700a1404dd87514a7f94339',
 'src/agents/bootstrap-cache.ts': 'ab991430b556dce62f07bb39f47c75a1965365b8e2b220e53a6574a4b89c540e',
 'src/agents/bootstrap-hooks.ts': '22a3ca25695761d4aff5a00c7b8408eee1463385310f935d6c747eb371d9e79a',
 'src/agents/workspace-personal-bootstrap.ts': '875c48e02ef7c017f6a669085c16fae87af8d3b1a6ee646830a5d7a4dfdae1ad',
 'src/hooks/internal-hooks.ts': '02000c74e5dcc894c47cccc33f3ad3aeebe173ff010a173c72e3771bce6712eb',
 'src/plugins/legacy-internal-hook-state.ts': '83ef97b38c7952031f005bfae6010487ff5a6a885bbd99d6a6558b9d6a8683e2',
 'src/routing/session-key.ts': 'f581697b1bde74523a78aa3cdea5fd4b11e73374544b1471c0af6c489bf90899',
 'src/sessions/session-key-utils.ts': '4cfb6c219248bd157a43f85b49bf8f4601233ef089c90f3716e9a1ceb0adf4d5',
 'src/sessions/session-chat-type-shared.ts': '1048d81ee5c69dada7979eca2e2128d1a9ba8a3b09075f98d56f403ba4a23e72',
 'src/memory/root-memory-files.ts': 'f9ab7a594f42a75c3e923b46926e4fd6e0d4bf582304824efde1cb2d615e7121',
 'src/infra/boundary-file-read.ts': '69aad298813204c0374bab6a64ccf3bb735a3974a00305bf43110974277d2585',
 'src/infra/openclaw-root.ts': '9e953e59a1d1415088b5fde16a47797c537a6ec028dfb8a354aae7cba1e609b7',
 'packages/markdown-core/src/frontmatter.ts': 'ab1695ca628be86ec88c725b422a745c758dbeaf65f3209429501765e3617036',
 'src/state/openclaw-state-db.ts': '8f4f7a1a7cecb4d4e4ab9b762e85785ed1476d66bc195ef8f157efdc7871704c',
 'src/state/openclaw-state-db-cache.ts': '88187954bc2ce8fbd0b254289640687aa205521266043b1a61e0a623cc211774',
 'src/state/openclaw-state-db.paths.ts': 'e3169d4e1f8df9b1bec5572bb20158c5800d135d26341b2af0920f73a06d95e1',
 'src/plugins/memory-runtime.ts': 'da358078fa03863c13493eab3cc4f2d1010cbb2f93d0f6faaab30c55930a797e'}

SOURCE_ANCHORS = {'src/agents/workspace.ts': ('export async function ensureAgentWorkspace(params?: {',
                             'export async function loadWorkspaceBootstrapFiles(',
                             'export function filterBootstrapFilesForSession(',
                             'async function ensureGitRepo('),
 'src/agents/bootstrap-files.ts': ('export async function resolveBootstrapFilesForRun(',
                                   'async function resolveIneligibleAutomaticMemoryFiles('),
 'src/agents/workspace-bootstrap-policy.ts': ('export const WORKSPACE_BOOTSTRAP_FILENAMES = [',
                                              'export function resolveWorkspaceBootstrapPath('),
 'src/agents/workspace-bootstrap-publish.ts': ('export async function publishBootstrapFile(',
                                               'export async function publishAgentInstructions('),
 'src/agents/workspace-bootstrap-read.ts': ('export const MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES = 2 * 1024 * '
                                            '1024;',
                                            'export async function readWorkspaceBootstrapFile('),
 'src/agents/workspace-file-read.ts': ('export async function readWorkspaceFileWithGuards(',
                                       'export function workspaceFileSourceIdentitiesMatch(',
                                       'export function workspaceFilesShareSourceIdentity('),
 'src/agents/workspace-file-cache.ts': ('export function readWorkspaceFileCache(',
                                        'export function writeWorkspaceFileCache('),
 'src/agents/workspace-templates.ts': ('export async function resolveWorkspaceTemplateSearchDirs(',),
 'src/agents/workspace-state-store.ts': ('export async function readWorkspaceStateSnapshot(',
                                         'export async function mergeWorkspaceSetupState(',
                                         'export async function replaceWorkspaceAttestation('),
 'src/agents/workspace-state-store.kernel.ts': ('export function readWorkspaceStateSnapshotFromDatabase(',
                                                'export function replaceWorkspaceAttestationInDatabase('),
 'src/agents/workspace-state-identity.ts': ('export function resolveWorkspaceStateIdentity(',
                                            'export class WorkspaceVanishedError extends Error {'),
 'src/agents/workspace-legacy-state.ts': ('export function assertNoUnmigratedWorkspaceState(',),
 'src/agents/workspace-access.ts': ('export function getAgentWorkspaceAccess(',),
 'src/agents/bootstrap-cache.ts': ('export async function getOrLoadBootstrapFiles(',),
 'src/agents/bootstrap-hooks.ts': ('export async function applyBootstrapHookOverrides(',),
 'src/agents/workspace-personal-bootstrap.ts': ('export async function loadPersonalUserBootstrapFile(',),
 'src/hooks/internal-hooks.ts': ('export async function triggerInternalHook(',
                                 'export function createInternalHookEvent(',
                                 'export function getRegisteredEventKeys('),
 'src/plugins/legacy-internal-hook-state.ts': ('export function listLegacyPluginInternalHooks(',),
 'src/routing/session-key.ts': ('export function resolveAgentIdFromSessionKey(',),
 'src/sessions/session-key-utils.ts': ('export function isCronSessionKey(',
                                       'export function isSubagentSessionKey('),
 'src/sessions/session-chat-type-shared.ts': ('export function deriveSessionChatTypeFromKey(',),
 'src/memory/root-memory-files.ts': ('export async function exactWorkspaceEntryExists(',),
 'src/infra/boundary-file-read.ts': ('export function isRootFileMissingFailure(',),
 'src/infra/openclaw-root.ts': ('export async function resolveOpenClawPackageRoot(',),
 'packages/markdown-core/src/frontmatter.ts': ('export function extractFrontmatterBlock(',),
 'src/state/openclaw-state-db.ts': ('export function openOpenClawStateDatabase(',
                                    'export function runOpenClawStateWriteTransaction<T>('),
 'src/state/openclaw-state-db-cache.ts': ('export async function closeOpenClawStateDatabaseAsync(',),
 'src/state/openclaw-state-db.paths.ts': ('export function resolveOpenClawStateSqlitePath(',),
 'src/plugins/memory-runtime.ts': ('export async function classifyActiveMemoryWorkspacePaths(',)}

COMPILED_HASHES = {'dist/workspace-C0LMBmap.mjs': 'c39922b28d2d5f7893d7b2a19afbcba3392283af318ab3ecc72d57cf0ae765ba',
 'dist/bootstrap-files-CgqY-7GK.mjs': '835205537668cf94a81d9c9828971e0a3f192866b54fea1858f611d1729db024',
 'dist/workspace-bootstrap-policy-DaS4N8nC.mjs': '799c07d72d14d9795d6404bf64dc3f8b8307d5b4a3f96b76b2cebab68449cf9b',
 'dist/workspace-bootstrap-read-B5B8MlNt.mjs': '431accb5571fe5849374d9b8cbd23c4b9942774618a8450babccbd06c9ea461c',
 'dist/workspace-templates-BkoWvlXF.mjs': 'b7f64bee7bf2fe5339cbc43a7f1cec1e6ddcb52c67048290e6402551881baa08',
 'dist/workspace-state-store-NkqJ2B1E.mjs': '7b05f03c89de7091e2f259887e31b53dc2186a0c8fa08f6df34ca77c05fcf4ed',
 'dist/workspace-state-store.kernel-CN9FHa9x.mjs': '7174e6f1b1b2cc25704fb17b40530981c5d843ce21bbe09b1a12d743ffffab3f',
 'dist/workspace-state-identity-DKiOuwcn.mjs': '58d161addf144ab31431e172f1f6119a16d9fba7081dd86cd60c91e4e29cd8cb',
 'dist/workspace-legacy-state-BTfSVuzc.mjs': '744ccb3d40fab4ba7b6ea7f98cf03bd5db0af6c9477ea5db69d5b0bacd688811',
 'dist/bootstrap-cache-DaET1Mx1.mjs': 'f3bdd50f81143b5862b42b988bc151af67c40b0f8eb041f4b63bddea8f457995',
 'dist/workspace-access-B-jCSAvI.mjs': '12756f2b01da6631b9c1d7325e9935615425508eb2e12db085759c94101ab493',
 'dist/internal-hooks-CwVYIajG.mjs': '7cc392b5a4638eacc6cd03b6bda7fd00ceb22cdd16c78af3f112ddad26c5178b',
 'dist/session-key-BC4m_Ly5.mjs': '04de0d3d458a72be34daba1206c3937c2fc31fbe6a252c1c9ef8b74630138465',
 'dist/session-chat-type-shared-Buo9x_XW.mjs': '0e3e64aab9f733daae8525154a7bbb4f1f36bfb7f48df599a271ce6dec4c78f6',
 'dist/root-memory-files-BUq0D-EI.mjs': '809e6674000e679dd281b9e4cb1ebf98be79476cbfadf9a29c653c1bb2cb7c0e',
 'dist/boundary-file-read-CCth2Hwg.mjs': '96e4d64aa144af2533fce63368ef3c8c7a1fbe8697adfc224ac3bbab9679866e',
 'dist/openclaw-root-DWMGzHgM.mjs': 'd3d6d7acdba7897d0d0973b5c68c7c2e9b89ac7197e47550b714a1dfde1e18c9',
 'dist/frontmatter-Bibn4xoJ.mjs': '988fcb7ffa2d6350c712fd4d9fc24da3916bf77e65e05f00cf7d1e23ec9284f9',
 'dist/openclaw-state-db-Dh2awMJ8.mjs': 'e5aad1c1e5a6d9b1ed371c2a176cf39015d3d3d8293d9aa9128b977cc540f75b',
 'dist/openclaw-state-db-cache-IdIaBoUp.mjs': 'e0cddcf3fa25fc081f0edb4cc9d31c4d29dabd1206dc440dd239f1bf665a543e',
 'dist/openclaw-state-db.paths-rJI64Ab5.mjs': '8cecbc669117d451fb3681898c056714e463437f1c6ada6a537609864c0c4214',
 'dist/memory-runtime-BzdCLKPx.mjs': 'bcfdf870307c0ea827682a6bef89e5c3170d09a2b818c9cbae7f3ce17920fd18'}

COMPILED_ANCHORS = {'dist/workspace-C0LMBmap.mjs': ('async function ensureAgentWorkspace(',
                                 'async function loadWorkspaceBootstrapFiles(',
                                 'ensureAgentWorkspace as t',
                                 'loadWorkspaceBootstrapFiles as s'),
 'dist/bootstrap-files-CgqY-7GK.mjs': ('async function resolveBootstrapFilesForRun(',
                                       'resolveBootstrapFilesForRun as c',
                                       'async function applyBootstrapHookOverrides(',
                                       'async function loadPersonalUserBootstrapFile('),
 'dist/workspace-bootstrap-policy-DaS4N8nC.mjs': ('const WORKSPACE_BOOTSTRAP_FILENAMES = [',),
 'dist/workspace-bootstrap-read-B5B8MlNt.mjs': ('async function readWorkspaceBootstrapFile(',),
 'dist/workspace-templates-BkoWvlXF.mjs': ('async function resolveWorkspaceTemplateSearchDirs(',),
 'dist/workspace-state-store-NkqJ2B1E.mjs': ('async function readWorkspaceStateSnapshot(',
                                             'async function mergeWorkspaceSetupState(',
                                             'async function replaceWorkspaceAttestation('),
 'dist/workspace-state-store.kernel-CN9FHa9x.mjs': ('function readWorkspaceStateSnapshotFromDatabase(',
                                                    'function replaceWorkspaceAttestationInDatabase('),
 'dist/workspace-state-identity-DKiOuwcn.mjs': ('function resolveWorkspaceStateIdentity(',),
 'dist/workspace-legacy-state-BTfSVuzc.mjs': ('function assertNoUnmigratedWorkspaceState(',),
 'dist/bootstrap-cache-DaET1Mx1.mjs': ('async function getOrLoadBootstrapFiles(',),
 'dist/workspace-access-B-jCSAvI.mjs': ('function getAgentWorkspaceAccess(',),
 'dist/internal-hooks-CwVYIajG.mjs': ('async function triggerInternalHook(',
                                      'function getRegisteredEventKeys('),
 'dist/session-key-BC4m_Ly5.mjs': ('function isCronSessionKey(', 'function isSubagentSessionKey('),
 'dist/session-chat-type-shared-Buo9x_XW.mjs': ('function deriveSessionChatTypeFromKey(',),
 'dist/root-memory-files-BUq0D-EI.mjs': ('async function exactWorkspaceEntryExists(',),
 'dist/boundary-file-read-CCth2Hwg.mjs': ('openRootFile as a',),
 'dist/openclaw-root-DWMGzHgM.mjs': ('async function resolveOpenClawPackageRoot(',),
 'dist/frontmatter-Bibn4xoJ.mjs': ('function extractFrontmatterBlock(',),
 'dist/openclaw-state-db-Dh2awMJ8.mjs': ('function openOpenClawStateDatabase(',
                                         'function runOpenClawStateWriteTransaction('),
 'dist/openclaw-state-db-cache-IdIaBoUp.mjs': ('async function closeOpenClawStateDatabaseAsync(',
                                               'closeOpenClawStateDatabaseAsync as a'),
 'dist/openclaw-state-db.paths-rJI64Ab5.mjs': ('function resolveOpenClawStateSqlitePath(',),
 'dist/memory-runtime-BzdCLKPx.mjs': ('async function classifyActiveMemoryWorkspacePaths(',)}

SOURCE_LINKS = (('src/agents/workspace.ts',
  './workspace-bootstrap-publish.js',
  ('publishAgentInstructions', 'publishBootstrapFile'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-bootstrap-policy.js',
  ('WORKSPACE_BOOTSTRAP_FILENAMES', 'resolveWorkspaceBootstrapPath'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-file-read.js',
  ('readWorkspaceFileWithGuards', 'setWorkspaceFileSourceIdentity'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-state-store.js',
  ('readWorkspaceStateSnapshot', 'mergeWorkspaceSetupState', 'replaceWorkspaceAttestation'),
  'import'),
 ('src/agents/workspace.ts', './workspace-templates.js', ('resolveWorkspaceTemplateSearchDirs',), 'import'),
 ('src/agents/workspace.ts',
  '../routing/session-key.js',
  ('isCronSessionKey', 'isSubagentSessionKey'),
  'import'),
 ('src/agents/workspace.ts',
  '../sessions/session-chat-type-shared.js',
  ('deriveSessionChatTypeFromKey',),
  'import'),
 ('src/agents/workspace.ts',
  '../../packages/markdown-core/src/frontmatter.js',
  ('extractFrontmatterBlock',),
  'import'),
 ('src/agents/workspace-file-read.ts',
  './workspace-bootstrap-read.js',
  ('readWorkspaceBootstrapFile', 'MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES'),
  'import'),
 ('src/agents/workspace-file-read.ts',
  './workspace-file-cache.js',
  ('readWorkspaceFileCache', 'writeWorkspaceFileCache'),
  'import'),
 ('src/agents/workspace-file-read.ts', '../infra/boundary-file-read.js', ('openRootFile',), 'import'),
 ('src/agents/workspace-bootstrap-read.ts',
  '../infra/boundary-file-read.js',
  ('readFileDescriptorBounded',),
  'import'),
 ('src/agents/workspace-templates.ts',
  '../infra/openclaw-root.js',
  ('resolveOpenClawPackageRoot',),
  'import'),
 ('src/agents/workspace-state-store.ts',
  './workspace-state-store.kernel.js',
  ('readWorkspaceStateSnapshotFromDatabase', 'resolveWorkspaceIdentityFromDatabase'),
  'import'),
 ('src/agents/workspace-state-store.ts',
  '../state/openclaw-state-db.js',
  ('openOpenClawStateDatabase', 'runOpenClawStateWriteTransaction'),
  'import'),
 ('src/agents/bootstrap-files.ts',
  './workspace.js',
  ('loadWorkspaceBootstrapFiles',
   'filterBootstrapFilesForSession',
   'isWorkspaceSetupCompleted',
   'workspaceFilesShareSourceIdentity'),
  'import'),
 ('src/agents/bootstrap-files.ts', './bootstrap-cache.js', ('getOrLoadBootstrapFiles',), 'import'),
 ('src/agents/bootstrap-files.ts', './bootstrap-hooks.js', ('applyBootstrapHookOverrides',), 'import'),
 ('src/agents/bootstrap-files.ts',
  './workspace-personal-bootstrap.js',
  ('loadPersonalUserBootstrapFile',),
  'import'),
 ('src/agents/bootstrap-files.ts',
  '../plugins/memory-runtime.js',
  ('classifyActiveMemoryWorkspacePaths',),
  'import'),
 ('src/agents/bootstrap-hooks.ts',
  '../hooks/internal-hooks.js',
  ('createInternalHookEvent', 'triggerInternalHook'),
  'import'),
 ('src/agents/bootstrap-cache.ts',
  './workspace.js',
  ('loadWorkspaceBootstrapFiles', 'workspaceFileSourceIdentitiesMatch'),
  'import'))

COMPILED_LINKS = (('dist/workspace-C0LMBmap.mjs',
  'import { a as DEFAULT_SOUL_FILENAME, c as GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES, f as hasGlobPattern, g '
  'as resolveWorkspaceBootstrapPath, h as resolveGlobWalkRoot, i as DEFAULT_MEMORY_FILENAME, l as '
  'WORKSPACE_BOOTSTRAP_FILENAMES, n as DEFAULT_BOOTSTRAP_FILENAME, p as normalizeWorkspacePatternPath, r as '
  'DEFAULT_IDENTITY_FILENAME, s as DEFAULT_USER_FILENAME, t as DEFAULT_AGENTS_FILENAME, u as '
  'createBootstrapPatternMatcher } from "./workspace-bootstrap-policy-DaS4N8nC.mjs";'),
 ('dist/workspace-C0LMBmap.mjs',
  'import { a as readWorkspaceStateSnapshot, c as readWorkspaceFileCache, o as replaceWorkspaceAttestation, '
  'r as mergeWorkspaceSetupState, t as clearExpiredWorkspaceStateForVanishedWorkspace, u as '
  'writeWorkspaceFileCache } from "./workspace-state-store-NkqJ2B1E.mjs";'),
 ('dist/workspace-C0LMBmap.mjs',
  'import { t as resolveWorkspaceTemplateSearchDirs } from "./workspace-templates-BkoWvlXF.mjs";'),
 ('dist/workspace-C0LMBmap.mjs',
  'import { S as isSubagentSessionKey, x as isCronSessionKey } from "./session-key-BC4m_Ly5.mjs";'),
 ('dist/bootstrap-files-CgqY-7GK.mjs',
  'import { a as isWorkspaceSetupCompleted, d as getWorkspaceFileSourceRelativePath, f as '
  'readWorkspaceFileWithGuards, h as workspaceFilesShareSourceIdentity, n as filterBootstrapFilesForSession, '
  'p as setWorkspaceFileSourceIdentity, s as loadWorkspaceBootstrapFiles } from "./workspace-C0LMBmap.mjs";'),
 ('dist/bootstrap-files-CgqY-7GK.mjs',
  'import { i as getOrLoadBootstrapFiles } from "./bootstrap-cache-DaET1Mx1.mjs";'),
 ('dist/bootstrap-files-CgqY-7GK.mjs',
  'import { n as createInternalHookEvent, u as triggerInternalHook } from "./internal-hooks-CwVYIajG.mjs";'),
 ('dist/bootstrap-files-CgqY-7GK.mjs',
  'import { n as classifyActiveMemoryWorkspacePaths } from "./memory-runtime-BzdCLKPx.mjs";'),
 ('dist/workspace-state-store-NkqJ2B1E.mjs',
  'import { a as assertCanonicalTimestamp, c as registerWorkspaceStateAliasIdentitiesInTransaction, d as '
  'resolveWorkspaceIdentityFromDatabase, f as workspacePathEntryExists, i as '
  'assertCanonicalIntegerTimestamp, n as WORKSPACE_CONTENT_RELOCATION_MIGRATION_KIND, r as '
  'WORKSPACE_LEGACY_STATE_MIGRATION_KIND, s as readWorkspaceStateSnapshotFromDatabase } from '
  '"./workspace-state-store.kernel-CN9FHa9x.mjs";'),
 ('dist/workspace-state-store-NkqJ2B1E.mjs',
  'import { l as runOpenClawStateWriteTransaction, r as openOpenClawStateDatabase } from '
  '"./openclaw-state-db-Dh2awMJ8.mjs";'),
 ('dist/bootstrap-cache-DaET1Mx1.mjs',
  'import { m as workspaceFileSourceIdentitiesMatch, s as loadWorkspaceBootstrapFiles } from '
  '"./workspace-C0LMBmap.mjs";'),
 ('dist/workspace-templates-BkoWvlXF.mjs',
  'import { n as resolveOpenClawPackageRoot } from "./openclaw-root-DWMGzHgM.mjs";'))

TEMPLATE_ARTIFACTS = {'AGENTS.md': {'path': 'docs/reference/templates/AGENTS.md',
               'bytes': 6581,
               'sha256': 'bb3a60215f98503b63249097655da6f058c60eb86b5b969c7acf01ae2176db45',
               'sourcePath': 'docs/reference/templates/AGENTS.md',
               'sourceSha256': 'bb3a60215f98503b63249097655da6f058c60eb86b5b969c7acf01ae2176db45'},
 'SOUL.md': {'path': 'docs/reference/templates/SOUL.md',
             'bytes': 1660,
             'sha256': 'e09be19ba4adb76ac77be00441933e03c7219876fbfaca107d49f8ed38c3e459',
             'sourcePath': 'docs/reference/templates/SOUL.md',
             'sourceSha256': 'e09be19ba4adb76ac77be00441933e03c7219876fbfaca107d49f8ed38c3e459'},
 'IDENTITY.md': {'path': 'docs/reference/templates/IDENTITY.md',
                 'bytes': 1520,
                 'sha256': '62dd950cd38df58de3f585f85356f5bd20e36aca4463c4884a7b773344a11199',
                 'sourcePath': 'docs/reference/templates/IDENTITY.md',
                 'sourceSha256': '62dd950cd38df58de3f585f85356f5bd20e36aca4463c4884a7b773344a11199'},
 'USER.md': {'path': 'docs/reference/templates/USER.md',
             'bytes': 1277,
             'sha256': 'ad942983dc5f87da98b51b01a07d463307ba35dd7328d0e92266b7561b71c69a',
             'sourcePath': 'docs/reference/templates/USER.md',
             'sourceSha256': 'ad942983dc5f87da98b51b01a07d463307ba35dd7328d0e92266b7561b71c69a'},
 'BOOTSTRAP.md': {'path': 'docs/reference/templates/BOOTSTRAP.md',
                  'bytes': 7612,
                  'sha256': 'bfc99ba9511b171dd09e769ce436cffff07f2175a2f8170853c439c5948c7b5a',
                  'sourcePath': 'docs/reference/templates/BOOTSTRAP.md',
                  'sourceSha256': 'bfc99ba9511b171dd09e769ce436cffff07f2175a2f8170853c439c5948c7b5a'}}


# The configured builtin profile executes real path and recorded-origin owners.
CLASSIFICATION_SOURCE_HASHES = {'extensions/memory-core/index.ts': '407649ff3005ec692a1c3d15e7e599692e693bf3e6ccbdc7e4aa18755deddd89',
 'extensions/memory-core/src/workspace-path-classifier.ts': 'd5448712cebf1238e313c1af0df3257fe9c7c7a553b61de524aa26db71b14f71',
 'extensions/memory-core/src/memory/memory-path-provenance.ts': '11e0adfcf2069d535b9fc3b9b625a5b65fd64dda4b97e4fa2ba9bcf5fc24a0af',
 'src/memory/memory-artifact-provenance.ts': '68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373',
 'src/plugin-sdk/memory-core-host-runtime-core.ts': '9d0fc4e1f1ec1f4c4a140a2a5b8cb63246c18091274cc8ffa51b5274b03a653b',
 'src/memory-host-sdk/host/types.ts': '0ad7459b0bc2beaab8dc490662b2643c16585da7761b325fa4b61f42467145a0',
 'packages/memory-host-sdk/src/host/types.ts': '737b555fc517671b927bcbab30334ffbd20c3690e02fa72595eeaacbddf06e4a',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530',
 'src/plugins/config-state.ts': '6b5c7c59fd033869a9f9b66527fa7f7926439375f656cbe933dd787c2a39d6b0',
 'src/plugins/config-normalization-shared.ts': '6a24b8f8b8ddb2771e6402ef68316ec23322f2ac87e8c2ceaf4695028c582eca',
 'src/plugins/slots.ts': '724aa32cf22eaf653c76ba43c34577ea3c02f7e026e89b6828bbaa0adc72bedb'}
CLASSIFICATION_SOURCE_ANCHORS = {'extensions/memory-core/index.ts': ('function createLazyMemoryRuntime(host: MemoryCoreRuntimeHost): '
                                     'MemoryPluginRuntime {',),
 'extensions/memory-core/src/workspace-path-classifier.ts': ('export const classifyWorkspaceMemoryPaths: '
                                                             'ClassifyWorkspaceMemoryPaths = async (params) =>',),
 'extensions/memory-core/src/memory/memory-path-provenance.ts': ('export async function '
                                                                 'resolveMemoryPathClassification(params: {',),
 'src/memory/memory-artifact-provenance.ts': ('export async function readMemoryArtifactProvenance(params: {',
                                              'function normalizeStoredProvenance('),
 'src/plugin-sdk/memory-core-host-runtime-core.ts': ('  readMemoryArtifactProvenance,',),
 'src/memory-host-sdk/host/types.ts': ('export * from "../../../packages/memory-host-sdk/src/host/types.js";',),
 'packages/memory-host-sdk/src/host/types.ts': ('export function isMemoryOriginEligibleForAutomaticInjection(',),
 'src/plugin-state/plugin-state-store.ts': ('export function createCorePluginStateKeyedStore<T>(',),
 'src/plugins/config-state.ts': ('export const normalizePluginsConfig = (',),
 'src/plugins/config-normalization-shared.ts': ('export function normalizePluginsConfigWithResolverCore(',),
 'src/plugins/slots.ts': ('export function resolveSlotSelection(slotKey: PluginSlotKey, value: unknown): '
                          'SlotSelection {',)}
CLASSIFICATION_COMPILED_HASHES = {'dist/extensions/memory-core/index.js': 'ead9aeb06b76504ba8ab9cb50a03c1425d18cbb936285c47f5ae7cf25e2877f8',
 'dist/workspace-path-classifier-nZNRErpg.mjs': '7829eab10d8bc0f98146740dc13374cc7296aae0ff170a78da1de8e79300ddd6',
 'dist/workspace-path-classifier-279hOw9K.mjs': '5d5343078f99e4f98a0e3fa0d364bb7a446fdf09f7ec5e74944dbef0c56d647f',
 'dist/memory-path-provenance-C84vBRrO.mjs': '1b1fb934b147bd044121cc42764adadd8e06482e34dee7abf4aa71e15ca771c1',
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': 'd9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c',
 'dist/plugin-sdk/memory-core-host-runtime-core.js': 'a786f0dc9b4bb96173e04ca2e2b07802d6b46319c9a2b3ab5c138fa7298d74cd',
 'dist/types-DTVBdCzw.mjs': '14598f9947a85bf691d345dc54c32899c8931afc580e45f143918afe8b54db50',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc'}
CLASSIFICATION_COMPILED_ANCHORS = {'dist/extensions/memory-core/index.js': ('function createLazyMemoryRuntime(host) {',),
 'dist/workspace-path-classifier-nZNRErpg.mjs': ('export { classifyWorkspaceMemoryPaths };',),
 'dist/workspace-path-classifier-279hOw9K.mjs': ('const classifyWorkspaceMemoryPaths = async (params) =>',),
 'dist/memory-path-provenance-C84vBRrO.mjs': ('async function resolveMemoryPathClassification(params) {',),
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': ('async function readMemoryArtifactProvenance(params) {',),
 'dist/plugin-sdk/memory-core-host-runtime-core.js': ('readMemoryArtifactProvenance, readPositiveIntegerParam',),
 'dist/types-DTVBdCzw.mjs': ('function isMemoryOriginEligibleForAutomaticInjection(originClass) {',),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function createCorePluginStateKeyedStore(options) {',)}
CLASSIFICATION_SOURCE_LINKS = (('src/agents/bootstrap-files.ts',
  '../memory-host-sdk/host/types.js',
  ('isMemoryOriginEligibleForAutomaticInjection',),
  'import'),
 ('extensions/memory-core/src/workspace-path-classifier.ts',
  './memory/memory-path-provenance.js',
  ('resolveMemoryPathClassification',),
  'import'),
 ('extensions/memory-core/src/memory/memory-path-provenance.ts',
  'openclaw/plugin-sdk/memory-core-host-runtime-core',
  ('readMemoryArtifactProvenance',),
  'import'),
 ('src/plugin-sdk/memory-core-host-runtime-core.ts',
  '../memory/memory-artifact-provenance.js',
  ('readMemoryArtifactProvenance', 'listMemoryArtifactProvenance'),
  'export'),
 ('src/memory/memory-artifact-provenance.ts',
  '../plugin-state/plugin-state-store.js',
  ('createCorePluginStateKeyedStore',),
  'import'),
 ('src/plugins/memory-runtime.ts', './config-state.js', ('normalizePluginsConfig',), 'import'),
 ('src/plugins/config-state.ts',
  './config-normalization-shared.js',
  ('normalizePluginsConfigWithResolverCore',),
  'import'),
 ('src/plugins/config-normalization-shared.ts',
  './slots.js',
  ('normalizeSlotValue', 'resolveSlotSelection'),
  'import'))
CLASSIFICATION_COMPILED_LINKS = (('dist/bootstrap-files-CgqY-7GK.mjs',
  'import { r as isMemoryOriginEligibleForAutomaticInjection } from "./types-DTVBdCzw.mjs";'),
 ('dist/extensions/memory-core/index.js', 'import("../../workspace-path-classifier-nZNRErpg.mjs")'),
 ('dist/workspace-path-classifier-nZNRErpg.mjs',
  'import { t as classifyWorkspaceMemoryPaths } from "./workspace-path-classifier-279hOw9K.mjs";'),
 ('dist/workspace-path-classifier-279hOw9K.mjs',
  'import { t as resolveMemoryPathClassification } from "./memory-path-provenance-C84vBRrO.mjs";'),
 ('dist/memory-path-provenance-C84vBRrO.mjs',
  'import { i as readMemoryArtifactProvenance } from "./memory-artifact-provenance-DhnyWiV1.mjs";'),
 ('dist/memory-artifact-provenance-DhnyWiV1.mjs',
  'import { t as createCorePluginStateKeyedStore } from "./plugin-state-store-BPUaLoVD.mjs";'),
 ('dist/plugin-sdk/memory-core-host-runtime-core.js',
  'import { i as readMemoryArtifactProvenance, n as listMemoryArtifactProvenance } from '
  '"../memory-artifact-provenance-DhnyWiV1.mjs";'))
SOURCE_HASHES.update(CLASSIFICATION_SOURCE_HASHES)
SOURCE_ANCHORS.update(CLASSIFICATION_SOURCE_ANCHORS)
COMPILED_HASHES.update(CLASSIFICATION_COMPILED_HASHES)
COMPILED_ANCHORS.update(CLASSIFICATION_COMPILED_ANCHORS)
SOURCE_LINKS += CLASSIFICATION_SOURCE_LINKS
COMPILED_LINKS += CLASSIFICATION_COMPILED_LINKS

CLASSIFICATION_NONBASELINE_ARTIFACTS = ("dist/memory-runtime-BzdCLKPx.mjs", *(path for path in CLASSIFICATION_COMPILED_HASHES if path != "dist/types-DTVBdCzw.mjs"))
# The public facade is authenticated as an available export. The actual bundled
# caller imports the reader implementation directly, so do not invent a load of
# an unused facade to claim execution.
CLASSIFICATION_REQUIRED_ARTIFACTS = tuple(path for path in CLASSIFICATION_NONBASELINE_ARTIFACTS
    if path != "dist/plugin-sdk/memory-core-host-runtime-core.js")
BASELINE_COMPILED_ARTIFACTS = tuple(path for path in COMPILED_HASHES if path not in CLASSIFICATION_NONBASELINE_ARTIFACTS)
CONDITIONAL_COMPILED_ARTIFACTS = {"configuredAutomaticMemoryClassification": CLASSIFICATION_REQUIRED_ARTIFACTS}


class BootstrapDiscoveryBindingError(ValueError):
    """The unchanged original bootstrap ownership cannot be authenticated."""


def _owner(root: Path, relative: str, digest: str, anchors: tuple[str, ...], *, committed: bool):
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or not path.resolve().is_relative_to(root)
            or any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root))):
        raise BootstrapDiscoveryBindingError("A bootstrap owner escaped its authenticated tree")
    raw = path.read_bytes()
    if (hashlib.sha256(raw).hexdigest() != digest or committed
            and hashlib.sha256(_git(root, "show", "HEAD:" + relative)).hexdigest() != digest):
        raise BootstrapDiscoveryBindingError("A bootstrap owner differs from its pinned bytes")
    text = raw.decode("utf-8")
    locations = []
    for anchor in anchors:
        if text.count(anchor) != 1:
            raise BootstrapDiscoveryBindingError("A bootstrap owner lost a unique reviewed declaration")
        locations.append({"anchor": anchor, "line": text[:text.index(anchor)].count("\n") + 1})
    return text, {"path": relative, "sha256": digest, "anchors": locations}


def prepare_bootstrap_discovery_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Bind exact source owners, real compiled callers and literal template bytes."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise BootstrapDiscoveryBindingError("Bootstrap discovery requires the unchanged pinned checkout")
        sources, source_evidence, compiled, compiled_evidence = {}, [], {}, []
        for root, hashes, anchors, committed, texts, evidence in (
            (checkout, SOURCE_HASHES, SOURCE_ANCHORS, True, sources, source_evidence),
            (runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, False, compiled, compiled_evidence),
        ):
            for relative, digest in hashes.items():
                text, record = _owner(root, relative, digest, anchors[relative], committed=committed)
                texts[relative] = text
                evidence.append(record)
        links = [_named_link(sources, module, specifier, names, kind=kind)
                 for module, specifier, names, kind in SOURCE_LINKS]
        compiled_links = []
        for module, declaration in COMPILED_LINKS:
            text = compiled[module]
            if text.count(declaration) != 1:
                raise BootstrapDiscoveryBindingError("A compiled bootstrap import edge changed")
            compiled_links.append({"path": module, "declaration": declaration,
                "line": text[:text.index(declaration)].count("\n") + 1,
                "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()})
        templates = {}
        for name, expected in TEMPLATE_ARTIFACTS.items():
            _, release = _owner(runtime_root, expected["path"], expected["sha256"], (), committed=False)
            _, source = _owner(checkout, expected["sourcePath"], expected["sourceSha256"], (), committed=True)
            raw = (runtime_root / expected["path"]).read_bytes()
            if len(raw) != expected["bytes"] or raw != (checkout / expected["sourcePath"]).read_bytes():
                raise BootstrapDiscoveryBindingError("The packaged literal bootstrap template changed")
            templates[name] = {**expected, "sourceSha256": source["sha256"], "sha256": release["sha256"]}
        return {"kind": "official-release-bootstrap-discovery-owners", "referenceCommit": REFERENCE_COMMIT,
            "sourceBuildReproduced": False, "sourceFallbackAllowed": False, "covers": [],
            "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
            "sourceImportLinks": links, "compiledImportLinks": compiled_links,
            "canonicalBootstrapFiles": list(CANONICAL_BOOTSTRAP_FILES), "templateArtifacts": templates,
            "entrypoints": {
                "ensure": {"path": "dist/workspace-C0LMBmap.mjs", "export": "t", "sourceExport": "ensureAgentWorkspace"},
                "load": {"path": "dist/workspace-C0LMBmap.mjs", "export": "s", "sourceExport": "loadWorkspaceBootstrapFiles"},
                "resolve": {"path": "dist/bootstrap-files-CgqY-7GK.mjs", "export": "c", "sourceExport": "resolveBootstrapFilesForRun"},
            },
            "stateEntrypoints": {
                "snapshot": {"path": "dist/workspace-state-store-NkqJ2B1E.mjs", "export": "a"},
                "setupCompleted": {"path": "dist/workspace-C0LMBmap.mjs", "export": "a"},
                "bootstrapStatus": {"path": "dist/workspace-C0LMBmap.mjs", "export": "c"},
                "close": {"path": "dist/openclaw-state-db-cache-IdIaBoUp.mjs", "export": "a"},
            },
            "requiredCompiledArtifacts": list(BASELINE_COMPILED_ARTIFACTS),
            "conditionalCompiledArtifacts": {key: list(value) for key, value in CONDITIONAL_COMPILED_ARTIFACTS.items()},
            "releaseDependencyAuthenticationRequired": True,
            "fullWorkspaceLifecycleEquivalenceClaimed": False,
            "branchCoverageNotClaimed": ["thirdPartyRegisteredMemoryRuntime", "personalUserProfileOverlay",
                "remoteWorkspaceAccess", "registeredBootstrapHookMutation"],
        }
    except BootstrapDiscoveryBindingError:
        raise
    except (OSError, KeyError, ValueError, UnicodeError) as error:
        raise BootstrapDiscoveryBindingError("Bootstrap discovery authority is unavailable or invalid") from error
