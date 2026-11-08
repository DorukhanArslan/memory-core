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
    return {"kind": "official-release-durable-session-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False, "managerFixture": False,
        "providerTransportVerified": False, "fullHostOrchestrationVerified": False,
        "reusedCatalogIndexBindings": reused, "sourceBindings": source_evidence,
        "compiledBindings": compiled, "sourceImportLinks": links,
        "phaseOrder": ["write", "continue", "verify"], "distinctOSProcessesRequired": True,
        "requiredArtifactsInEveryPhase": list(REQUIRED_PHASE_ARTIFACTS),
        "requiredArtifactsWhenAppending": list(APPEND_PHASE_ARTIFACTS),
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
