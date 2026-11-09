"""Actual append, branch, model-context and fresh-process durable owners.

The existing catalog/index provenance is reused unchanged. Added owners execute
original published code; reconstructed source builds and full host orchestration
are not asserted. Write phases require their own protected manager/index worker;
verification retains the actual unforced persisted-index path.
"""
from __future__ import annotations
from pathlib import Path
from equivalence.session_admission_runtime_bindings import (
    REFERENCE_COMMIT, _owners, _named_link,
    prepare_session_admission_runtime_bindings, MEMORY_INDEX_WORKER_ARTIFACTS,
)

SOURCE_HASHES = {'packages/agent-core/src/harness/session/session.ts': 'b9da8aab7693741eec60cd43d3e33b36d91e2c2ad2afbc7695320c8bf838350e',
 'packages/agent-core/src/harness/messages.ts': 'cfa370ab4c489262dc769f30c6b07ce6b90c974a2c6cb49d8a366a5edaf20d64',
 'packages/agent-core/src/harness/session/tool-result-pairing.ts': '432a3ab386709ea2341f6f336c42eb78eae7ef323ff5f293a69ece53ebb1701b',
 'src/config/sessions/transcript-visible-events.ts': '15250a85089fc04749f3e82bb37008b178149acdb85dfc3b0a4387e2386ec774',
 'src/config/sessions/transcript-tree.ts': '5b24acb49cdc8634ccb4afad80226e371705775fce9945a7ef2426ac219ff945',
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': '6cbf0606d549cd2fae2e80e63181a0ff81e2eebfe32f8f93f4593d3832947618',
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': '05c4ad331965633ecf0cd850fa7b3e4e1072b62b2728d14f2175a4a5f8dcf79c',
 'src/config/sessions/transcript-header.ts': 'df2f0da864f5c642bc2b2f76332525d8dab52feb282fd959247acf99f55bc0b7',
 'src/config/sessions/version.ts': '39a17391fd9d6c7e73d6ea619a04c8fc47c674f70ec14e0bb4d1786f1e2fc3d3',
 'src/config/sessions/session-accessor.sqlite-transcript-state.ts': 'c978eebfed78ac252f5f84dd346662ff4c10b51792d1f4d9a9bc6cd91c9489d4',
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': 'e2db126148df6df03a8c09cb628f58130ba34d70b5088817f2446699c316ae74',
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': 'e658ffefb7c1c8cfc6ad4c416d8f2f20657cb59f8412eac951e1d8e564afa50d',
 'src/infra/sqlite-integrity-worker.ts': '6a8b51ac07775ccb5963857dde418d04c81657a69d1bbe72b3557c10a16f2803',
 'src/infra/sqlite-integrity.worker.ts': 'f6420abc3be00c1352be662598357448b1048fc6b1f5203025432295a5a2f550',
 'src/infra/sqlite-file-generation.ts': '98f0ef241747ad0fb22564ea229c0dacd84231ef961194f67b1446ebd7e076ab'}
SOURCE_ANCHORS = {'packages/agent-core/src/harness/session/session.ts': ('export function '
                                                        'buildSessionContext(',
                                                        'export function* '
                                                        'iterateSessionContextMessages'),
 'packages/agent-core/src/harness/messages.ts': ('export function '
                                                 'convertToLlm(',),
 'packages/agent-core/src/harness/session/tool-result-pairing.ts': ('export '
                                                                    'function '
                                                                    'selectResetKeptEntries',),
 'src/config/sessions/transcript-visible-events.ts': ('export function '
                                                      'selectVisibleTranscriptEvents<T>',),
 'src/config/sessions/transcript-tree.ts': ('export function '
                                            'scanSessionTranscriptTree<T>',),
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': ('export '
                                                                              'function '
                                                                              'appendTranscriptMessageInTransaction',
                                                                              'export '
                                                                              'function '
                                                                              'prepareTranscriptMessageAppend'),
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': ('export '
                                                                      'function '
                                                                      'ensureTranscriptHeader(',),
 'src/config/sessions/transcript-header.ts': ('export function '
                                              'createSessionTranscriptHeader(',),
 'src/config/sessions/version.ts': ('export const CURRENT_SESSION_VERSION = '
                                    '4;',),
 'src/config/sessions/session-accessor.sqlite-transcript-state.ts': ('export '
                                                                     'function '
                                                                     'ensureTranscriptGenerationInTransaction(',
                                                                     'export '
                                                                     'function '
                                                                     'advanceTranscriptMutationAtInTransaction('),
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': ('export '
                                                                      'function '
                                                                      'createTranscriptEntryAnchor(',),
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': ('export '
                                                                     'function '
                                                                     'appendTranscriptEventInTransaction(',),
 'src/infra/sqlite-integrity-worker.ts': ('export function '
                                          'assertSqliteIntegrityInWorker(',
                                          'const child = fork(entry, [], {'),
 'src/infra/sqlite-integrity.worker.ts': ('async function check(',
                                          'if (!process.send || '
                                          '!process.disconnect)'),
 'src/infra/sqlite-file-generation.ts': ('export function '
                                         'readSqliteIntegrityFileIdentity(',)}
COMPILED_HASHES = {'dist/session-BA9qunLx.mjs': '76e83df0e3056d87ac01eeb929a1b1f5a4722ef274653e3bafef4c64fc9468cd',
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': '252ed9e8717da3b64bee74c0948425d77519bf520b1e131e381d985ec4fb73a0',
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': '26e983f0f600c413613e54b7c8978db7defc046c8bd4a542e75764209e969a95',
 'dist/transcript-header-CP-ow2Zr.mjs': '4adbb6f0a5d024dd72cff7e77b6ef8ddeec3f7955399980fc421e8c815844608',
 'dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs': '18876ef6dd39f1771b5a4b7b656ce5c44272d063a8e6c465f98c07a39280031d',
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': 'dbe095833b6deabf938291cab994d3361534731fa78fbab80e60226727c01393',
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': 'deb4cca4a9d2fc66702e5adc2f3882f620e8d1533fbe7107a7cd95869d54cf5e',
 'dist/transcript-tree-D_mugOJ0.mjs': 'ab04920cc9ccd15770c7838adb5ba4ab7fc0315fcea43e9c633d4833d9fe6cab',
 'dist/infra/sqlite-integrity.worker.js': 'b884b1033d414cea5187d24ee066bce1eddfde6ed3096fadd15e79637f6279df',
 'dist/openclaw-agent-db-maintenance-DBuIm8El.mjs': '8a582f38f3e2ccbca248409dccf1507009d256843f2b684d7f59b6cbeb7eb09b',
 'dist/sqlite-file-generation-Z_oSlnyK.mjs': '47fd0d5b69868fb71239992947a1d85f562f107415b75ca2588eb8f6541c5be5'}
COMPILED_ANCHORS = {'dist/session-BA9qunLx.mjs': ('function buildSessionContext(',
                               'function convertToLlm('),
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': ('function '
                                                                      'appendTranscriptMessageInTransaction(',
                                                                      'function '
                                                                      'prepareTranscriptMessageAppend('),
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': ('function '
                                                                 'ensureTranscriptHeader(',),
 'dist/transcript-header-CP-ow2Zr.mjs': ('function '
                                         'createSessionTranscriptHeader(',
                                         'version: params.version ?? 4,'),
 'dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs': ('function '
                                                                'ensureTranscriptGenerationInTransaction(',
                                                                'function '
                                                                'advanceTranscriptMutationAtInTransaction('),
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': ('function '
                                                                 'createTranscriptEntryAnchor(',),
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': ('function '
                                                                'appendTranscriptEventInTransaction(',),
 'dist/transcript-tree-D_mugOJ0.mjs': ('function scanSessionTranscriptTree(',),
 'dist/infra/sqlite-integrity.worker.js': ('async function check(',
                                           'if (!process.send || '
                                           '!process.disconnect)'),
 'dist/openclaw-agent-db-maintenance-DBuIm8El.mjs': ('function '
                                                     'assertSqliteIntegrityWithProcess(',
                                                     'const child = '
                                                     'fork(entry, [], {'),
 'dist/sqlite-file-generation-Z_oSlnyK.mjs': ('function '
                                              'readSqliteIntegrityFileIdentity(',)}

SOURCE_HASHES.update({'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'src/agents/memory-search.ts': 'a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2',
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': '5ec673cb42dc14662c6be1b4e405d4242f9a24cfa933e8200b98cb329227fb8c'})
SOURCE_ANCHORS.update({'extensions/memory-core/src/memory/manager.ts': ('  protected readonly '
                                                  'settings: '
                                                  'ResolvedMemorySearchConfig;',
                                                  '    this.settings = {'),
 'src/agents/memory-search.ts': ('export function resolveMemorySearchConfig(',
                                 'const DEFAULT_TEMPORAL_DECAY_ENABLED = true;',
                                 'const DEFAULT_TEMPORAL_DECAY_HALF_LIFE_DAYS '
                                 '= 30;'),
 'src/plugin-sdk/memory-core-host-engine-foundation.ts': ('  '
                                                          'resolveMemorySearchConfig,',)})
COMPILED_HASHES.update({'dist/memory-search-CIhUURbE.mjs': 'e015aeaa8d8e062eb792ae58d2e4537e5b0f665ea97b946979e644444304a148'})
COMPILED_ANCHORS.update({'dist/memory-search-CIhUURbE.mjs': ('function resolveMemorySearchConfig(cfg, '
                                     'agentId) {',
                                     'const DEFAULT_TEMPORAL_DECAY_ENABLED = '
                                     'true;',
                                     'const '
                                     'DEFAULT_TEMPORAL_DECAY_HALF_LIFE_DAYS = '
                                     '30;')})
RANKING_DEFAULT_ARTIFACTS = ("dist/memory-search-CIhUURbE.mjs",)


SOURCE_HASHES.update({'src/agents/main-session-recovery/main-session-recovery-clear.ts': 'ff3fae295eeed9836100d599b4d102fa2f93a230f317aae4fdfe68dfe0d73452',
 'src/config/sessions/session-accessor.sqlite-entry-read.ts': 'f6a4515bca2982da03d0fbf960b4c83a59b2b796e23193dc1d5ec12c671b904c',
 'src/config/sessions/session-accessor.sqlite-participant-projection.ts': 'e629448152fec6732c0d6ba61c3724ab3bfaebb3b03cb418d206602ada1e95de',
 'src/config/sessions/session-accessor.sqlite-status.ts': 'b3e9f3913b29bf94121242b05e107a7f8c76b1ccf50eae94f81facb26efd9511',
 'src/config/sessions/store-entry-shape.ts': '2ca9bdadf9de3ad8c48a77cd8351e70bc45aa4bafd77e58e62be397b94da1511',
 'src/plugin-sdk/session-store-runtime-internal.ts': 'd2de13b9d4d421a7097f5d4216c9ae97598345ddbefc57d6d345224891f36ed3',
 'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11'})
SOURCE_ANCHORS.update({'src/agents/main-session-recovery/main-session-recovery-clear.ts': ('export '
                                                                     'const '
                                                                     'MAIN_SESSION_RECOVERY_CLEAR_PATCH: '
                                                                     'Partial<MainRecoveryStateFields> '
                                                                     '= {',),
 'src/config/sessions/session-accessor.sqlite-entry-read.ts': ('export '
                                                               'function '
                                                               'parseReadableSqliteSessionEntryRow(',),
 'src/config/sessions/session-accessor.sqlite-participant-projection.ts': ('export '
                                                                           'function '
                                                                           'projectSqliteSessionParticipants(',),
 'src/config/sessions/session-accessor.sqlite-status.ts': ('export function '
                                                           'parseSessionEntryJson(',),
 'src/config/sessions/store-entry-shape.ts': ('export function '
                                              'projectCanonicalSessionEntryShape(value: '
                                              'Record<string, unknown>): '
                                              'SessionEntry {',),
 'src/plugin-sdk/session-store-runtime-internal.ts': ('export function '
                                                      'clearGenerationPrivateFieldsForRotatedSessionPatch(',),
 'src/plugin-sdk/session-store-runtime.ts': ('export async function '
                                             'upsertSessionEntry(params: '
                                             'UpsertSessionEntryParams): '
                                             'Promise<void> {',)})
COMPILED_HASHES.update({'dist/main-session-recovery-clear-BczELu-B.mjs': 'ba2bf263f897a47409122d91a727a7af7a74e619f78f7aaa4da8284f9745da47',
 'dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs': 'cad4258ac1e98dcf2979cbdad92b60555e94ecfbe1985d6d0acdc59e3b19a8c9',
 'dist/session-accessor.sqlite-status-DGBuIDuw.mjs': '8218c5bc1715b532c5f01b9e8c09bcacbbb2d55f8e606c02f840528f03df03ff',
 'dist/session-store-runtime-C3lQUqXM.mjs': '42c91a431b20934055e124edf556bffdb57e203615f814fd6c6067654c5caf20',
 'dist/store-entry-shape-fsGxEPpp.mjs': '03494cf016554ef04bd7e2f636f5b1d1e165ac87a87b681a4ed0742ce1248a23'})
COMPILED_ANCHORS.update({'dist/main-session-recovery-clear-BczELu-B.mjs': ('const '
                                                   'MAIN_SESSION_RECOVERY_CLEAR_PATCH '
                                                   '= {',
                                                   'MAIN_SESSION_RECOVERY_CLEAR_PATCH '
                                                   'as t'),
 'dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs': ('function '
                                                          'projectSqliteSessionParticipants(database, '
                                                          'sessionKey, entry) '
                                                          '{',
                                                          'function '
                                                          'parseReadableSqliteSessionEntryRow(database, '
                                                          'row, projection = '
                                                          '"full") {'),
 'dist/session-accessor.sqlite-status-DGBuIDuw.mjs': ('function '
                                                      'parseSessionEntryJson(row, '
                                                      'projection = "full") '
                                                      '{',),
 'dist/session-store-runtime-C3lQUqXM.mjs': ('function '
                                             'clearGenerationPrivateFieldsForRotatedSessionPatch(existingEntry, '
                                             'publicPatch) {',),
 'dist/store-entry-shape-fsGxEPpp.mjs': ('function '
                                         'projectCanonicalSessionEntryShape(value) '
                                         '{',
                                         'projectCanonicalSessionEntryShape as '
                                         'n')})
SOURCE_HASHES["src/config/sessions/session-entry-projection.ts"] = "48eae1e011e50fc043e63f59dd308f003a7898d510fe0847fbab4b2e4508410f"
SOURCE_ANCHORS["src/config/sessions/session-entry-projection.ts"] = ("export const SESSION_ENTRY_PRIVATE_CLEAR_PATCH =",)
COMPILED_HASHES["dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs"] = "3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951"
COMPILED_ANCHORS["dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs"] = ("const SESSION_ENTRY_PRIVATE_CLEAR_PATCH =",)
METADATA_PROJECTION_ARTIFACTS = ("dist/store-entry-shape-fsGxEPpp.mjs", "dist/session-accessor.sqlite-status-DGBuIDuw.mjs", "dist/session-accessor.sqlite-entry-read-CMIsjDi7.mjs")
ROTATED_PRIVATE_FIELDS_ARTIFACTS = ("dist/session-store-runtime-C3lQUqXM.mjs", "dist/main-session-recovery-clear-BczELu-B.mjs", "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs")

REQUIRED_PHASE_ARTIFACTS = (
    "dist/extensions/memory-core/manager-runtime.js",
    "dist/session-accessor-CiKKTlbe.mjs",
    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    "dist/session-files-DVVT4Ngb.mjs",
    "dist/session-BA9qunLx.mjs",
    "dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs",
    "dist/transcript-tree-D_mugOJ0.mjs",
)
APPEND_PHASE_ARTIFACTS = (
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
    "dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs",
    "dist/transcript-header-CP-ow2Zr.mjs",
    "dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs",
    "dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs",
)

def prepare_durable_session_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    reused = prepare_session_admission_runtime_bindings(checkout, runtime_root)
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    specs = (
        ("src/plugin-sdk/session-store-runtime-internal.ts", "../config/sessions/session-entry-projection.js", ("SESSION_ENTRY_PRIVATE_CLEAR_PATCH",)),
        ("src/plugin-sdk/session-store-runtime.ts", "./session-store-runtime-internal.js", ("clearGenerationPrivateFieldsForRotatedSessionPatch",)),
        ("src/plugin-sdk/session-store-runtime-internal.ts", "../agents/main-session-recovery/main-session-recovery-clear.js", ("MAIN_SESSION_RECOVERY_CLEAR_PATCH",)),
        ("src/config/sessions/session-accessor.sqlite-status.ts", "./store-entry-shape.js", ("projectCanonicalSessionEntryShape",)),
        ("src/config/sessions/session-accessor.sqlite-entry-read.ts", "./session-accessor.sqlite-participant-projection.js", ("projectSqliteSessionParticipants",)),
        ("extensions/memory-core/src/memory/manager.ts", "openclaw/plugin-sdk/memory-core-host-engine-foundation", ("resolveMemorySearchConfig",)),
        ("src/infra/sqlite-integrity-worker.ts", "node:child_process", ("fork",)),
        ("src/infra/sqlite-integrity-worker.ts", "./sqlite-file-generation.js", ("readSqliteIntegrityFileIdentity",)),
        ("packages/agent-core/src/harness/session/session.ts", "../messages.js",
         ("createBranchSummaryMessage", "createCompactionSummaryMessage", "createCustomMessage")),
        ("packages/agent-core/src/harness/session/session.ts", "./tool-result-pairing.js", ("selectResetKeptEntries",)),
        ("src/config/sessions/transcript-visible-events.ts", "./transcript-tree.js",
         ("scanSessionTranscriptTree", "selectSessionTranscriptTreePathNodes")),
        ("src/config/sessions/session-accessor.sqlite-transcript-message-append.ts", "./session-accessor.sqlite-transcript-header.js", ("ensureTranscriptHeader",)),
        ("src/config/sessions/session-accessor.sqlite-transcript-header.ts", "./transcript-header.js", ("createSessionTranscriptHeader",)),
        ("src/config/sessions/transcript-header.ts", "./version.js", ("CURRENT_SESSION_VERSION",)),
    )
    links = [_named_link(sources, module, specifier, names, kind="import")
             for module, specifier, names in specs]
    links.append(_named_link(sources, "src/plugin-sdk/memory-core-host-engine-foundation.ts",
                             "../agents/memory-search.js", ("resolveMemorySearchConfig",), kind="export"))
    return {"kind": "official-release-durable-session-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False, "managerFixture": False,
        "providerTransportVerified": False, "fullHostOrchestrationVerified": False,
        "reusedCatalogIndexBindings": reused, "sourceBindings": source_evidence,
        "compiledBindings": compiled, "sourceImportLinks": links,
        "phaseOrder": ["write", "continue", "verify"], "distinctOSProcessesRequired": True,
        "requiredArtifactsInEveryPhase": list(REQUIRED_PHASE_ARTIFACTS),
        "requiredArtifactsWhenAppending": list(APPEND_PHASE_ARTIFACTS),
        "requiredArtifactsWhenRetainingResolvedManagerSettings": list(RANKING_DEFAULT_ARTIFACTS),
        "resolvedManagerSettingsRetained": True,
        "originalTemporalDecayDefaults": {"enabled": True, "halfLifeDays": 30},
        "scoreNormalizationPermitted": False,
        "requiredMetadataProjectionArtifacts": list(METADATA_PROJECTION_ARTIFACTS),
        "requiredPrivateFieldOwnerArtifactsWhenUpserting": list(ROTATED_PRIVATE_FIELDS_ARTIFACTS),
        "requiredWorkerArtifactsWhenIndexWorkExecutes": list(MEMORY_INDEX_WORKER_ARTIFACTS),
        "forcedIndexPhases": ["write", "continue"], "verificationSyncForced": False,
        "headerVersion": 4,
        "incidentalProcessAuthority": {"entry": "dist/infra/sqlite-integrity.worker.js",
            "launchOwner": "src/infra/sqlite-integrity-worker.ts",
            "compiledLaunchOwner": "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs",
            "actualParentPidRequired": True},
        "publicIdentityCodec": {"generation": "first-seen valid32hex append/read anchor identity only",
                                "storePath": "exact actual producer store path only"},
        "fixtureBoundary": "Three child OS processes inherit the trusted preload. Each process reads "
            "the same persisted SQLite/catalog/index state and constructs its own genuine provider-none "
            "manager. Index work requires a genuine memory-index worker; the verification sync "
            "is unforced and may take the persisted fast path. Only the phase's literal mutations and common identity "
            "are supplied; no prior output history is forwarded. Model-visible messages are built by "
            "original branch selector, session-context builder and convertToLlm owners. Raw events, "
            "full SQL, actual append results, clocks and original process IDs remain retained."}
