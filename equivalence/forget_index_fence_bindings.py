"""Authenticate original forget/index fence owners before any paired execution.

This module reads pinned source and separately published release bytes only.
Declarations, imports and route requirements grant no behavioral acceptance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence import atomic_publication_bindings as atomic
from equivalence import durable_session_runtime_bindings as durable
from equivalence import promotion_apply_bindings as promotion
from equivalence import promotion_apply_family_bindings as promotion_family
from equivalence import query_sync_outcomes_bindings as query
from equivalence import session_admission_runtime_bindings as sessions
from equivalence.promotion_apply_bindings import _merged_anchors
from equivalence.reference_bindings import _git
from equivalence.search_contract_runtime_bindings import _owners

REFERENCE_COMMIT = query.REFERENCE_COMMIT
OPERATION = "forget-index-fence-v3-runtime"

ADDITIONAL_SOURCE_HASHES = {'extensions/memory-core/src/cli.runtime.ts': 'ec6a2e2676d6a4b5fb2b364866021f88b389bca5946cc40451877cbfbbfdf1ba',
 'extensions/memory-core/src/cli-index-search.runtime.ts': '1cb313da8f2dd7597f03aafb879cdc49d969deed18ae7bfd6fdd1a45e5a9280a',
 'extensions/memory-core/src/cli-runtime-common.ts': 'd8ef99c4d123a6bbde6c4e15f42478e655772d4866539fbb27392afc50cfb8f0',
 'extensions/memory-core/src/memory-forget.ts': '6f50711f972a369e16b7eed957826ee49d575ce50f06642d517612d352aeb475',
 'extensions/memory-core/src/memory-forget-index-sources.ts': 'b7af323286b6a8a17f400998db85a4f6e3c0b6a8ea5c2677651966c928298cd9',
 'extensions/memory-core/src/memory-forget-curated-writes.ts': '8e4e8f2ed6f74f4e796824f041334cf6074b234fa827dee5b43ec4ffeabdd556',
 'extensions/memory-core/src/memory-forget-report.ts': '3add12d4a0205afef1f8de96da2c430398e7b96580b2cade78fc1f55c14a6fbd',
 'extensions/memory-core/src/memory-session-tombstones.ts': '0ebc12b61cc4d27f868331a68f709968c1fa0ea9a4fe4a1f8e7ec870a350fe2d',
 'extensions/memory-core/src/memory/manager-db.ts': 'db30980ca17529261aac5cbbe139e5c7933a0885d18939211d4c4b32ea144924',
 'extensions/memory-core/src/memory/manager-embedding-ops.ts': 'd48ee54c3081385116757671cfa71fefb1187dcad688f9a985c704f550118a3f',
 'extensions/memory-core/src/memory/manager-shadow-task.ts': '222a3ad6445eaa3b58dbf92213af0454ec9e28d7577a001d2d1d1684b23ef0c7',
 'packages/memory-host-sdk/src/host/memory-schema.ts': '4c7bc3e66b22298f21fc43e0a7f002f9cd64825e70c395f45135cfee1973f57d',
 'packages/memory-host-sdk/src/host/memory-schema-base.ts': 'e662a672cad79e2ba0ee36ae71bfc78bd7f84255d9a20498fb868445408014e8',
 'packages/memory-host-sdk/src/host/memory-schema-fts.ts': '775bd0eaa40f455ffd2ae6388841ecb8d6be4f610ffcd798b45e3f9e29766ffb',
 'packages/memory-host-sdk/src/host/memory-schema-provenance.ts': 'd4bc55183dea446802e39cff24e11027e0c0418f02dde337ca586a413e4578c6',
 'src/config/io.runtime.ts': 'c31c88bc70453ce91a2e1df3e5830bc1a99d8ff0cc5afd5e51fd4c18cff0c099',
 'src/config/runtime-snapshot.ts': '16f1308be97b38b2524026c3367d9653248522ae60861b3ddbc770d127ba0d5d',
 'src/plugin-sdk/config-runtime.ts': '34cbd9c1d5dc0e5356795b29251b3e889b2b752532db908036053dbd23e65248',
 'src/plugin-sdk/session-transcript-runtime.ts': 'f6e5a66d91b440b65d5c1c355bf0dca9f5669c53e9a423a5d8abbecc4f9d661a',
 'src/config/sessions/session-accessor.transcript-turn.ts': 'a46005a0a1862c3ce06d5dc6067a817a64491a9ad94aa236b74b662b47ea720f',
 'src/state/openclaw-agent-db-lifecycle.ts': 'a49e35f38d6584969d28183cec435581b6a6797bd4b4eaf3f7b5d7507429b16c',
 'src/state/openclaw-agent-db-write.ts': '1a78602562da78a8a94b7105db5d2188ea73b0227b60dcb7b11b3f3788ff5c97',
 'src/plugin-sdk/sqlite-worker-runtime.ts': '2f9bde0d0996f51dd60017f5131f86c1fcae26dcb287e81e0e7301a30a61cebd',
 'src/plugin-sdk/sqlite-runtime.ts': '6fa47548183e9c9425d541051cecbb6f6fb1b611dbe8e5b8bd78fc6d698ce903',
 'src/infra/sqlite-transaction.ts': '7b4caf5b30e1eb6626ffce2ae90583fa979c8289fdd0128ce29acc00448f253f',
 'src/infra/worker-task-server.ts': '3ee977b63028f42aa62b62a3fd3628e8afc5f5b614ca65e65d0ca26b7669e523'}

ADDITIONAL_SOURCE_ANCHORS = {'extensions/memory-core/src/cli.runtime.ts': ('  runMemoryForget,',),
 'extensions/memory-core/src/cli-index-search.runtime.ts': ('export async function '
                                                            'runMemoryForget(opts: '
                                                            'MemoryForgetCommandOptions) {',),
 'extensions/memory-core/src/cli-runtime-common.ts': ('export function resolveMemoryAgent(',),
 'extensions/memory-core/src/memory-forget.ts': ('export async function forgetMemoryEntries(',
                                                 'async function forgetWorkspaceMemory(',
                                                 '          if (recorded === 0) {',
                                                 '      // The marker has committed. A purge failure '
                                                 'must leave it durable for retry.'),
 'extensions/memory-core/src/memory-forget-index-sources.ts': ('export async function planMemoryIndex(',
                                                               'export function '
                                                               'deleteMemoryIndexSources('),
 'extensions/memory-core/src/memory-forget-curated-writes.ts': ('export function '
                                                                'collectTranscriptWrites(',),
 'extensions/memory-core/src/memory-forget-report.ts': ('export function summarizeParticipantMatches(',),
 'extensions/memory-core/src/memory-session-tombstones.ts': ('export function '
                                                             'ensureMemorySessionTombstones(',
                                                             'export function '
                                                             'hasMemorySessionTombstone('),
 'extensions/memory-core/src/memory/manager-db.ts': ('export async function resetMemoryDatabase(',
                                                     'export async function '
                                                     'cleanupAgedMemoryReindexTempFiles(',
                                                     'export function '
                                                     'openMemoryDatabaseReadOnlyAtPath('),
 'extensions/memory-core/src/memory/manager-embedding-ops.ts': ('  private async writeChunks(',
                                                                '  private async '
                                                                'withGeneratedEmbeddingCacheWrite('),
 'extensions/memory-core/src/memory/manager-shadow-task.ts': ('export function '
                                                              'readMemoryShadowIdentity(',
                                                              'export function '
                                                              'assertMemoryShadowIdentity('),
 'packages/memory-host-sdk/src/host/memory-schema.ts': ('export function ensureMemoryIndexSchema(',),
 'packages/memory-host-sdk/src/host/memory-schema-base.ts': ('export function '
                                                             'buildMemoryIndexStrictSchema(',),
 'packages/memory-host-sdk/src/host/memory-schema-fts.ts': ('export function '
                                                            'ensureMemoryPathFtsTriggers(',),
 'packages/memory-host-sdk/src/host/memory-schema-provenance.ts': ('export function '
                                                                   'ensureMemoryChunkProvenance(',),
 'src/config/io.runtime.ts': ('export function getRuntimeConfig(',),
 'src/config/runtime-snapshot.ts': ('export function setRuntimeConfigSnapshot(',),
 'src/plugin-sdk/config-runtime.ts': ('  setRuntimeConfigSnapshot,',),
 'src/plugin-sdk/session-transcript-runtime.ts': ('export async function '
                                                  'appendSessionTranscriptMessageByIdentityStrict<TMessage>(',),
 'src/config/sessions/session-accessor.transcript-turn.ts': ('export async function '
                                                             'persistSessionTranscriptTurn(',),
 'src/state/openclaw-agent-db-lifecycle.ts': ('export async function '
                                              'closeOpenClawAgentDatabasesAsync(',),
 'src/state/openclaw-agent-db-write.ts': ('export function withOpenClawAgentDatabaseWrite<T>(',),
 'src/plugin-sdk/sqlite-worker-runtime.ts': ('  runSqliteImmediateTransactionSync,',),
 'src/plugin-sdk/sqlite-runtime.ts': ('export { withOpenClawAgentDatabaseWrite } from '
                                      '"../state/openclaw-agent-db-write.js";',),
 'src/infra/sqlite-transaction.ts': ('export function runSqliteImmediateTransactionSync<T>(',),
 'src/infra/worker-task-server.ts': ('export function serveWorkerTasks<Output>(',)}

ADDITIONAL_COMPILED_HASHES = {'dist/cli.runtime-CVRN4xUp.mjs': '8005b01a0e308c8bb984349a985c2a605fad8fa44431a567d7e73bc8635bfdcd',
 'dist/short-term-promotion-Cy0NJmOU.mjs': '559d84f465fa0f8d182a6ade016249116fc487b1fe08ece634d8ebb02c18de51',
 'dist/short-term-promotion-record-DrLa1fiO.mjs': '26a083e3c17cd6512af9785266c7bdffe459cd02591be4127004efe7eb8887c7',
 'dist/memory-session-tombstones-B1AGruLs.mjs': '8246f0c143130e397c952f8bef014e212bceeb73a14b3146afc57335ba0432e2',
 'dist/memory-schema-SE7C0M3V.mjs': '131ec423f55c59ea6461e71ae2a220b3192809d1737680c08e065c9e841f6a7b',
 'dist/manager-shadow-task-DGuJMed1.mjs': '748168bcfdeb0755b0e3c2b7bbfa623f4bb3b41613a6bea0c458a9b618dbe658',
 'dist/extensions/memory-core/memory-search.worker.js': 'b6c37bfcccdb1240e61550de9c730395113e0dcadc22c54f0814106dfacf042c',
 'dist/runtime-snapshot-BFi3jxlO.mjs': '0cb73088d71ff77c47d63931a00d9c771b5fc5c205ad77f3588335c8a908f9cb',
 'dist/plugin-sdk/config-runtime.js': 'ca8ea03ec6a8eeb48c4f300f7a88171aba943e6999a40791205d0027bd1d2a18',
 'dist/io.runtime-w45cmCNp.mjs': '12c678073ff907a2e1315bb0831f8d63422957f13c366e47b003362869dad627',
 'dist/runtime-BC29JSZp.mjs': '0825c97c0d79ef2049599a3a7ff0027e1803dd96d4e0ca05a9b7eb38f748e2da',
 'dist/plugin-sdk/session-transcript-runtime.js': '6b1fc98f8770ffe7d994bbd3f6a616ba5ee08910403534e14cc44c13cd84fe17',
 'dist/session-transcript-runtime-Bo5y_sts.mjs': '02c9381d6aa5495a0814dd11cfaf6b5ed9249a5e3064633d7ac396dd1447c398',
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': 'ece2b2b08f3e03c8ddb3dc70e29265f23c6b3df52e37e981e79a6bbd424a5a84',
 'dist/plugin-sdk/session-store-runtime.js': '495b19c73cb71dce90914b28d0c9492da41622fbdfb7a4966885ba7f83cbbba2',
 'dist/openclaw-agent-db-write-CX8lsDvQ.mjs': 'a88747b8af314cf69a8a627f4cc1b5a01e19e250577322c7c6afbe954d7d6487',
 'dist/sqlite-transaction-BHOCk0oF.mjs': '25193a2a2e8945bf0c433c52e333665adb4333e6cf66de46d22dd8341387ef52',
 'dist/worker-task-server-CF3aSh39.mjs': '0528de35a64cfead2597bcf0d1db768d3c9339971e10f013612756ff1a0ca167',
 'dist/worker-task-server-TOWocWCm.mjs': '89e91a98d4bd7a96f69d43d4216fd90b896bfe8bcce536c792ca32a93b8b4e04',
 'dist/sqlite-worker-runtime-DK9m_wsx.mjs': 'ea23cef4ea5c2b4125344060a90fb8a11888f7a7283c5066a1542d4153a53c6b'}

ADDITIONAL_COMPILED_ANCHORS = {'dist/cli.runtime-CVRN4xUp.mjs': ('async function runMemoryForget(opts) {',
                                   'async function forgetMemoryEntries(params) {',
                                   'async function forgetWorkspaceMemory(params, workspaceDir, context) '
                                   '{',
                                   'async function planMemoryIndex(params) {',
                                   'function deleteMemoryIndexSources(database, sources) {',
                                   'function collectTranscriptWrites(params) {'),
 'dist/short-term-promotion-Cy0NJmOU.mjs': ('export { applyShortTermPromotions,',),
 'dist/short-term-promotion-record-DrLa1fiO.mjs': ('async function recordShortTermRecalls(params) {',
                                                   'async function '
                                                   'recordGroundedShortTermCandidates(params) {'),
 'dist/memory-session-tombstones-B1AGruLs.mjs': ('function ensureMemorySessionTombstones(db) {',
                                                 'function hasMemorySessionTombstone(db, agentId, '
                                                 'sessionId) {'),
 'dist/memory-schema-SE7C0M3V.mjs': ('function ensureMemoryIndexSchema(params) {',),
 'dist/manager-shadow-task-DGuJMed1.mjs': ('function readMemoryShadowIdentity(filename) {',
                                           'function assertMemoryShadowIdentity(filename, expected) {'),
 'dist/extensions/memory-core/memory-search.worker.js': ('import '
                                                         '"../../manager-search.worker-BWRvo8WR.mjs";',),
 'dist/runtime-snapshot-BFi3jxlO.mjs': ('function setRuntimeConfigSnapshot(config, sourceConfig) {',
                                        'setRuntimeConfigSnapshot as D'),
 'dist/plugin-sdk/config-runtime.js': (' D as setRuntimeConfigSnapshot,',),
 'dist/io.runtime-w45cmCNp.mjs': ('function getRuntimeConfig(options) {',),
 'dist/runtime-BC29JSZp.mjs': ('const defaultRuntime = {',),
 'dist/plugin-sdk/session-transcript-runtime.js': (' r as '
                                                   'appendSessionTranscriptMessageByIdentityStrict,',),
 'dist/session-transcript-runtime-Bo5y_sts.mjs': ('async function '
                                                  'appendSessionTranscriptMessageByIdentityStrict(params) '
                                                  '{',),
 'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': ('async function '
                                                   'closeOpenClawAgentDatabasesAsync(rootPath) {',
                                                   'closeOpenClawAgentDatabasesAsync as s,'),
 'dist/plugin-sdk/session-store-runtime.js': (' v as upsertSessionEntry }',),
 'dist/openclaw-agent-db-write-CX8lsDvQ.mjs': ('function withOpenClawAgentDatabaseWrite(inputOptions, '
                                               'operation, expectedDatabase) {',),
 'dist/sqlite-transaction-BHOCk0oF.mjs': ('function runSqliteImmediateTransactionSync(db, operation, '
                                          'options) {',),
 'dist/worker-task-server-CF3aSh39.mjs': ('function serveWorkerTasks(handler, options = {}) {',),
 'dist/worker-task-server-TOWocWCm.mjs': ('import "./worker-task-server-CF3aSh39.mjs";',),
 'dist/sqlite-worker-runtime-DK9m_wsx.mjs': ('import "./sqlite-transaction-BHOCk0oF.mjs";',)}


ADDITIONAL_SOURCE_HASHES.update({'extensions/memory-core/src/dreaming-ingestion-state.ts': '1d4fca365fa88ef871766adccb85bface2aaff04e4ed54ce996f187ae5150905',
 'src/config/sessions/session-accessor.sqlite-transcript-turn.ts': 'c199589846efef183c3ed3419aff7d98f96511c7b3f4b633c24a5dedf3f06161',
 'src/config/sessions/session-transcript-commit-completion.ts': '8a7d27d1df31d7385bdafc5673d3e5224086d28465658c610f5540f6d7de31ba'})

ADDITIONAL_SOURCE_ANCHORS.update({'extensions/memory-core/src/dreaming-ingestion-state.ts': ('export async function '
                                                            'readSessionIngestionState(',
                                                            'export async function '
                                                            'writeSessionIngestionState('),
 'src/config/sessions/session-accessor.sqlite-transcript-turn.ts': ('export async function '
                                                                    'appendExpectedSessionTranscriptTurn(',),
 'src/config/sessions/session-transcript-commit-completion.ts': ('export function '
                                                                 'completeSessionTranscriptCommit(',)})

ADDITIONAL_COMPILED_HASHES.update({'dist/dreaming-ingestion-state-licbtf_y.mjs': '91904fa3331423770d712029fa2863d0e30279a33d8b8b9486ab630281ff31e3',
 'dist/memory-core-host-engine-sessions-D3OZsg6m.mjs': '705191a0ebf383e5b5aaf70dae18a7fa7c6030c4c4be7d841483cfe2567632c8'})

ADDITIONAL_COMPILED_ANCHORS.update({'dist/dreaming-ingestion-state-licbtf_y.mjs': ('async function readSessionIngestionState(workspaceDir) '
                                                '{',
                                                'async function '
                                                'writeSessionIngestionState(workspaceDir, state) {'),
 'dist/memory-core-host-engine-sessions-D3OZsg6m.mjs': ('function resolveMemorySessionTargets(params) '
                                                        '{',)})


ADDITIONAL_SOURCE_HASHES.update({'extensions/memory-core/src/short-term-promotion-record.ts': 'b8d168519af14de5ae793d6738d3a86d51e41cdcc12cbd5b22fb174ba108d8c7',
 'src/config/io.ts': 'a38ac75563287ae90f8b747dcf19406c26c52d8832f18b55b92c4900394b2a6b'})

ADDITIONAL_SOURCE_ANCHORS.update({'extensions/memory-core/src/short-term-promotion-record.ts': ('export async function '
                                                               'recordShortTermRecalls(',
                                                               'export async function '
                                                               'recordGroundedShortTermCandidates('),
 'src/config/io.ts': ('  setRuntimeConfigSnapshot,',)})


def _merged_hashes(*manifests: dict[str, str]) -> dict[str, str]:
    """Reject conflicting inherited pins instead of overriding earlier authority."""
    result: dict[str, str] = {}
    for manifest in manifests:
        for relative, digest in manifest.items():
            if relative in result and result[relative] != digest:
                raise ValueError(f"Conflicting forget/index fence owner pin: {relative}")
            result[relative] = digest
    return result


# Reusing declaration authority does not inherit any earlier execution or credit.
# The atomic subset identifies the real file writer reached by forget/promotion;
# its external package/native authority is still supplied by release custody.
_ATOMIC_SOURCE_PATHS = (
    "extensions/memory-core/src/short-term-promotion-memory-write.ts",
    "src/plugin-sdk/security-runtime.ts", "src/plugin-sdk/file-access-runtime.ts",
    "src/infra/file-descriptor.ts", "src/infra/fs-safe.ts", "src/infra/directory-durability.ts",
)
_ATOMIC_COMPILED_PATHS = (
    "dist/short-term-promotion-memory-write-HTLC95gL.mjs",
    "dist/security-runtime-D3RcbWGb.mjs", "dist/file-descriptor-B4yBUiAP.mjs",
    "dist/fs-safe-CHQXnCPk.mjs", "dist/directory-durability-fWp4i1Sl.mjs",
)
_SOURCE_MANIFESTS = (query, sessions, promotion, promotion_family, durable)
ADDITIONAL_SOURCE_HASHES["src/state/openclaw-state-schema.sql"] = (
    "993e08e70b43a7a52e52eb95eda33c19832df4ee1ec4ef1fe4068a4caf38adc7"
)
ADDITIONAL_SOURCE_ANCHORS["src/state/openclaw-state-schema.sql"] = (
    "CREATE TABLE IF NOT EXISTS plugin_state_entries (",
    "CREATE TABLE IF NOT EXISTS plugin_blob_entries (",
)
SOURCE_HASHES = _merged_hashes(
    *(owner.SOURCE_HASHES for owner in _SOURCE_MANIFESTS),
    {path: atomic.SOURCE_HASHES[path] for path in _ATOMIC_SOURCE_PATHS},
    ADDITIONAL_SOURCE_HASHES,
)
SOURCE_ANCHORS = _merged_anchors(
    *(owner.SOURCE_ANCHORS for owner in _SOURCE_MANIFESTS),
    {path: atomic.SOURCE_ANCHORS[path] for path in _ATOMIC_SOURCE_PATHS},
    ADDITIONAL_SOURCE_ANCHORS,
    {
        "extensions/memory-core/src/tools.ts": (
            '                void import("./short-term-promotion-record.js")',
            '                  .then(({ recordShortTermRecalls }) => recordShortTermRecalls(recall))',
        ),
        "extensions/memory-core/src/memory/manager-registry.ts": (
            '      if (params.purpose !== "default") {',
            '    // Withdrawn retirement owners still need explicit retry; live transient managers remain caller-owned.',
        ),
        "extensions/memory-core/src/memory/manager-db-kernel.ts": (
            "export function readMemoryDatabaseRevision(db: DatabaseSync): number {",
            "export class MemoryIndexRevisionConflictError extends Error {",
            "        if (liveRevision !== params.expectedRevision) {",
        ),
        "extensions/memory-core/src/memory/manager-sync-ops.ts": (
            "  private async runInPlaceReindex(params: {",
            "      const originalRevision = readMemoryDatabaseRevision(originalDb);",
            "              expectedRevision: originalRevision,",
        ),
        "extensions/memory-core/src/memory/manager-keyword-retrieval.ts": (
            "  protected async attachRecallMetadata<T extends MemoryRetrievalResult & { id: string }>(",
            "      .filter((entry) => metadataById.has(entry.id))",
        ),
        "extensions/memory-core/src/memory-entry-origins.ts": (
            "export function recordMemorySessionTombstonesInDatabase(",
            "export function deleteMemoryEntryOriginsInDatabase(",
            '          .set((expression) => ({ revision: expression("revision", "+", 1) }))',
        ),
        "extensions/memory-core/src/short-term-promotion-apply.ts": (
            "async function resolveMemoryPromotionLockTarget(workspaceDir: string): Promise<string> {",
            "  const promotionLockTarget = await resolveMemoryPromotionLockTarget(workspaceDir);",
            "      const latestStore = await readStore(workspaceDir, nowIso);",
        ),
        "src/plugin-sdk/memory-core-host-engine-sessions.ts": (
            "export function resolveMemorySessionTargets(params: MemorySessionSelectors): MemorySessionTarget[] {",
        ),
        "src/infra/sqlite-integrity-worker.ts": (
            "function assertSqliteIntegrityWithProcess(",
            "    const child = fork(entry, [], {",
            '      serialization: "advanced",',
        ),
        "src/infra/sqlite-integrity.worker.ts": (
            '    database = openNodeSqliteDatabase(input.pathname, { readOnly: true });',
            '    await sendPhase("checking");',
            '      assertSqliteIntegrity(database, input.databaseLabel, "integrity_check", input.tables, timing);',
        ),
        "src/config/sessions/session-accessor.sqlite-transcript-write.ts": (
            "export function replaceTranscriptEventsSync(",
        ),
        "src/config/sessions/session-accessor.sqlite-read.ts": (
            "export function readTranscriptExportSnapshotReadOnlySync(",
            "          const sessionKey =\n            resolved.sessionKey ??",
            '        { operationLabel: "session transcript export snapshot" },',
        ),
    },
)
COMPILED_HASHES = _merged_hashes(
    *(owner.COMPILED_HASHES for owner in _SOURCE_MANIFESTS),
    {path: atomic.COMPILED_HASHES[path] for path in _ATOMIC_COMPILED_PATHS},
    ADDITIONAL_COMPILED_HASHES,
)
COMPILED_ANCHORS = _merged_anchors(
    *(owner.COMPILED_ANCHORS for owner in _SOURCE_MANIFESTS),
    {path: atomic.COMPILED_ANCHORS[path] for path in _ATOMIC_COMPILED_PATHS},
    ADDITIONAL_COMPILED_ANCHORS,
    {
        "dist/extensions/memory-core/manager-runtime.js": (
            "\tasync runInPlaceReindex(params) {", "\tasync attachRecallMetadata(results, signal, sourceFilterList) {",
            "\t\t\t\t\t\texpectedRevision: originalRevision,",
            "\t\treturn results.filter((entry) => metadataById.has(entry.id)).map((entry) => {",
            "\t\t\t\t}).finally(() => {\n\t\t\t\t\tthis.activeBackgroundSearchSyncs.delete(trackedSearchSync);",
        ),
        "dist/tools-DotaQGXh.mjs": (
            'import("./short-term-promotion-record-CEpBdgKW.mjs").then(({ recordShortTermRecalls }) => recordShortTermRecalls(recall)).catch(() => {});',
        ),
        "dist/manager-db-kernel-DyJADqYu.mjs": (
            "function readMemoryDatabaseRevision(db) {", "var MemoryIndexRevisionConflictError = class extends Error {",
            "publishMemoryDatabaseTables as n, readMemoryDatabaseRevision as r, MemoryIndexRevisionConflictError as t",
        ),
        "dist/memory-entry-origins-BCQSIB3X.mjs": (
            "function recordMemorySessionTombstonesInDatabase(db, params) {",
            "recordMemorySessionTombstonesInDatabase as o",
            "recordMemoryEntryOrigins as a",
        ),
        "dist/short-term-promotion-MX1vHJuE.mjs": (
            "async function resolveMemoryPromotionLockTarget(workspaceDir) {",
            "\tconst canonicalWorkspace = await fs.realpath(workspaceDir).catch(() => path.resolve(workspaceDir));",
            "\tconst promotionLockTarget = await resolveMemoryPromotionLockTarget(workspaceDir);",
        ),
        "dist/dreaming-state-VYUvbU-n.mjs": ("function configureMemoryCoreDreamingState(openKeyedStore) {",),
        "dist/session-accessor-CiKKTlbe.mjs": (
            " u as loadTranscriptEventsSync,", "x as readTranscriptExportSnapshotReadOnlySync",
        ),
        "dist/session-accessor-WMUIp1Kx.mjs": ("async function persistSessionTranscriptTurn(scope, options) {",),
        "dist/plugin-state-store-BPUaLoVD.mjs": ("async function closePluginStateDatabaseAsync() {",),
        "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs": (
            "function assertSqliteIntegrityWithProcess(",
            "const child = fork(entry, [], {",
            'serialization: "advanced",',
        ),
        "dist/infra/sqlite-integrity.worker.js": (
            'database = openNodeSqliteDatabase(input.pathname, { readOnly: true });',
            'await sendPhase("checking");',
            'assertSqliteIntegrity(database, input.databaseLabel, "integrity_check", input.tables, timing);',
        ),
        "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs": (
            "function replaceTranscriptEventsSync(scope, events) {",
            "replaceTranscriptEventsSync as l",
        ),
        "dist/session-accessor.sqlite-read-BsSfe2AE.mjs": (
            "function readTranscriptExportSnapshotReadOnlySync(scope, options = {}) {",
            "\tconst result = withOpenClawAgentDatabaseReadOnly((database) => runSqliteDeferredTransactionSync(database.db, () => {",
            '\t}, { operationLabel: "session transcript export snapshot" }), toDatabaseOptions(resolved));',
        ),
    },
)

# Requirements are attached to an actually executed route. Authentication of a
# composed owner does not imply every case loads every authenticated artifact.
REQUIRED_MAIN_ARTIFACTS_BY_ROUTE = {
    "manager": (
        "dist/extensions/memory-core/manager-runtime.js",
        "dist/manager-vector-warning-DcyxxT5h.mjs", "dist/manager-db-kernel-DyJADqYu.mjs",
        "dist/manager-shadow-task-DGuJMed1.mjs", "dist/manager-search-DgMs3pkc.mjs",
        "dist/manager-cpu-worker-runtime-CAWQOyFu.mjs", "dist/manager-cpu-entrypoints-bJosRUx9.mjs",
        "dist/manager-source-index-kernel-D-njga00.mjs", "dist/manager-index-preparation-wXpJtJiU.mjs",
        "dist/memory-session-tombstones-B1AGruLs.mjs", "dist/memory-schema-SE7C0M3V.mjs",
        "dist/openclaw-agent-db-DRy3ui_B.mjs", "dist/openclaw-agent-db-write-CX8lsDvQ.mjs",
        "dist/sqlite-worker-store-D6Kl0iv0.mjs", "dist/worker-task-pool-BQlnRNqZ.mjs",
        "dist/sqlite-transaction-BHOCk0oF.mjs",
    ),
    "producer": (
        "dist/plugin-sdk/session-store-runtime.js", "dist/session-store-runtime-C3lQUqXM.mjs",
        "dist/plugin-sdk/session-transcript-runtime.js", "dist/session-transcript-runtime-Bo5y_sts.mjs",
        "dist/session-accessor-CiKKTlbe.mjs", "dist/session-accessor-WMUIp1Kx.mjs",
        "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs", "dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs",
        "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
        "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
        "dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs",
        "dist/session-accessor.sqlite-transcript-state-DpXwav5N.mjs",
        "dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs",
        "dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs",
        "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    ),
    "forget": (
        "dist/cli.runtime-CVRN4xUp.mjs", "dist/memory-entry-origins-BCQSIB3X.mjs",
        "dist/memory-session-tombstones-B1AGruLs.mjs", "dist/memory-core-host-engine-sessions-D3OZsg6m.mjs",
        "dist/session-files-DVVT4Ngb.mjs", "dist/memory-core-host-engine-storage-Dn-n8hud.mjs",
        "dist/memory-workspace-files-CC0bKS3d.mjs", "dist/dreaming-dreams-file-BJzlZFlf.mjs",
        "dist/dreaming-state-VYUvbU-n.mjs", "dist/dreaming-ingestion-state-licbtf_y.mjs",
        "dist/short-term-promotion-store-B6T388Bo.mjs", "dist/short-term-promotion-memory-write-HTLC95gL.mjs",
        "dist/memory-artifact-provenance-DhnyWiV1.mjs", "dist/openclaw-agent-db-write-CX8lsDvQ.mjs",
        "dist/sqlite-transaction-BHOCk0oF.mjs", "dist/io.runtime-w45cmCNp.mjs", "dist/runtime-BC29JSZp.mjs",
    ),
    "promotion": (
        "dist/short-term-promotion-Cy0NJmOU.mjs", "dist/short-term-promotion-MX1vHJuE.mjs",
        "dist/short-term-promotion-record-DrLa1fiO.mjs", "dist/short-term-promotion-store-B6T388Bo.mjs",
        "dist/memory-entry-origins-BCQSIB3X.mjs", "dist/memory-artifact-provenance-DhnyWiV1.mjs",
        "dist/dreaming-dreams-file-BJzlZFlf.mjs", "dist/dreaming-state-VYUvbU-n.mjs",
        "dist/file-lock-bsl71RWY.mjs", "dist/short-term-promotion-memory-write-HTLC95gL.mjs",
    ),
    "tools": ("dist/tools-DotaQGXh.mjs",),
    "state": (
        "dist/extensions/memory-core/runtime-api.js", "dist/plugin-sdk/config-runtime.js",
        "dist/runtime-snapshot-BFi3jxlO.mjs", "dist/plugin-sdk/plugin-state-store-runtime.js",
        "dist/plugin-state-store-BPUaLoVD.mjs", "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
        "dist/openclaw-state-db.paths-rJI64Ab5.mjs",
    ),
    "reopen": (
        "dist/extensions/memory-core/manager-runtime.js", "dist/manager-vector-warning-DcyxxT5h.mjs",
        "dist/openclaw-agent-db-DRy3ui_B.mjs", "dist/openclaw-agent-db-readonly-WugFtIYV.mjs",
        "dist/manager-db-kernel-DyJADqYu.mjs", "dist/memory-entry-origins-BCQSIB3X.mjs",
    ),
}
REQUIRED_WORKER_ARTIFACTS_BY_ROUTE = {
    "preparation": (
        "dist/extensions/memory-core/memory-index.worker.js", "dist/manager-index.worker-CinEDBkE.mjs",
        "dist/manager-index-preparation-wXpJtJiU.mjs", "dist/worker-task-server-CF3aSh39.mjs",
    ),
    "publication": (
        "dist/infra/sqlite-store.worker.js", "dist/extensions/memory-core/memory-publication.worker.js",
        "dist/manager-publication.worker-x9zokjMA.mjs", "dist/manager-db-kernel-DyJADqYu.mjs",
        "dist/manager-source-index-kernel-D-njga00.mjs", "dist/memory-session-tombstones-B1AGruLs.mjs",
        "dist/manager-shadow-task-DGuJMed1.mjs", "dist/memory-schema-SE7C0M3V.mjs",
        "dist/sqlite-transaction-BHOCk0oF.mjs",
    ),
    "retrieval": (
        "dist/extensions/memory-core/memory-search.worker.js", "dist/manager-search.worker-BWRvo8WR.mjs",
        "dist/manager-search-DgMs3pkc.mjs", "dist/openclaw-agent-db-readonly-WugFtIYV.mjs",
        "dist/worker-task-server-CF3aSh39.mjs",
    ),
    "state": tuple(promotion.PROMOTION_WORKER_ROUTE),
}
REQUIRED_MAIN_ARTIFACTS = tuple(dict.fromkeys(
    path for route in REQUIRED_MAIN_ARTIFACTS_BY_ROUTE.values() for path in route))
REQUIRED_WORKER_ARTIFACTS = tuple(dict.fromkeys(
    path for route in REQUIRED_WORKER_ARTIFACTS_BY_ROUTE.values() for path in route))
REQUIRED_LOADED_ARTIFACTS = tuple(dict.fromkeys((*REQUIRED_MAIN_ARTIFACTS, *REQUIRED_WORKER_ARTIFACTS)))


class ForgetIndexFenceBindingError(ValueError):
    """A reviewed source, release artifact, declaration or import edge changed."""


def _literal_links(contents: dict[str, str], declarations: dict[str, tuple[str, ...]],
                   *, kind: str = "import") -> list[dict]:
    result = []
    for module, imports in declarations.items():
        for declaration in imports:
            source = contents[module]
            if source.count(declaration) != 1:
                raise ForgetIndexFenceBindingError("An original compiled forget/index import edge changed")
            result.append({"path": module, "declaration": declaration, "kind": kind,
                           "line": source[:source.index(declaration)].count("\n") + 1,
                           "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()})
    return result

_PREFIX = "extensions/memory-core/src/"
_MEMORY = _PREFIX + "memory/"
SOURCE_LINKS = (
    (_PREFIX + "cli.runtime.ts", "./cli-index-search.runtime.js", ("runMemoryForget",), "export"),
    (_PREFIX + "cli-index-search.runtime.ts", "./memory-forget.js", ("forgetMemoryEntries",), "import"),
    (_PREFIX + "cli-index-search.runtime.ts", "openclaw/plugin-sdk/memory-core-host-runtime-core", ("getRuntimeConfig",), "import"),
    (_PREFIX + "memory-forget.ts", "./memory-entry-origins.js", ("deleteMemoryEntryOriginsInDatabase", "listMemoryEntryOrigins", "recordMemorySessionTombstonesInDatabase"), "import"),
    (_PREFIX + "memory-forget.ts", "./memory-forget-index-sources.js", ("deleteMemoryIndexSources", "planMemoryIndex", "referencesSession"), "import"),
    (_PREFIX + "memory-forget.ts", "./memory-forget-curated-writes.js", ("collectTranscriptWrites",), "import"),
    (_PREFIX + "memory-forget.ts", "./memory-workspace-lock.js", ("withMemoryWorkspaceLock",), "import"),
    (_PREFIX + "memory-forget.ts", "./memory-session-tombstones.js", ("ensureMemorySessionTombstones",), "import"),
    (_PREFIX + "memory-forget.ts", "openclaw/plugin-sdk/sqlite-runtime", ("borrowOpenClawAgentDatabase", "runSqliteImmediateTransactionSync", "withOpenClawAgentDatabaseWrite"), "import"),
    (_PREFIX + "memory-entry-origins.ts", "./memory-session-tombstones.js", ("ensureMemorySessionTombstones", "memorySessionTombstonesExist"), "import"),
    (_MEMORY + "manager-embedding-ops.ts", "../memory-session-tombstones.js", ("hasMemorySessionTombstone",), "import"),
    (_MEMORY + "manager-sync-ops.ts", "./manager-db-kernel.js", ("memoryDatabaseTableExists", "readMemoryDatabaseRevision"), "import"),
    (_MEMORY + "manager-sync-ops.ts", "./manager-index-generation-lease.js", ("withMemoryIndexPublishGeneration",), "import"),
    (_MEMORY + "manager-sync-ops.ts", "../memory-workspace-lock.js", ("withMemoryWorkspaceLock",), "import"),
    (_MEMORY + "manager-database-context.ts", "./manager-shadow-task.js", ("assertMemoryShadowIdentity", "readMemoryShadowIdentity"), "import"),
    (_MEMORY + "manager-publication.worker.ts", "./manager-db-kernel.js", ("publishMemoryDatabaseTables", "readMemoryDatabaseRevision"), "import"),
    (_MEMORY + "manager-publication.worker.ts", "../memory-session-tombstones.js", ("hasMemorySessionTombstone",), "import"),
    (_MEMORY + "manager-db-kernel.ts", "openclaw/plugin-sdk/sqlite-worker-runtime", ("runSqliteImmediateTransactionSync",), "import"),
    (_MEMORY + "manager-db.ts", "./manager-index-generation-lease.js", ("withMemoryIndexPublishGeneration",), "import"),
    ("src/plugin-sdk/sqlite-worker-runtime.ts", "../infra/sqlite-transaction.js", ("runSqliteImmediateTransactionSync",), "export"),
    ("src/plugin-sdk/sqlite-runtime.ts", "../state/openclaw-agent-db-write.js", ("withOpenClawAgentDatabaseWrite",), "export"),
    ("src/plugin-sdk/session-transcript-runtime.ts", "../config/sessions/session-accessor.js", ("persistSessionTranscriptTurn",), "import"),
    ("src/config/sessions/session-accessor.ts", "./session-accessor.transcript-turn.js", ("persistSessionTranscriptTurn",), "export"),
    ("src/config/sessions/session-accessor.transcript-turn.ts", "./session-accessor.sqlite-transcript-turn.js", ("appendExpectedSessionTranscriptTurn",), "import"),
    ("src/config/sessions/session-accessor.sqlite-transcript-turn.ts", "./session-accessor.sqlite-transcript-message-append.js", ("appendTranscriptMessageInTransaction",), "import"),
    ("src/config/io.ts", "./runtime-snapshot.js", ("setRuntimeConfigSnapshot",), "export"),
    (_PREFIX + "short-term-promotion-apply.ts", "./memory-entry-origins.js", ("pruneMemoryEntryOrigins", "reserveMemoryEntryOrigins"), "import"),
    (_PREFIX + "short-term-promotion-record.ts", "./memory-entry-origins.js", ("recordMemoryEntryOrigins", "listMemorySessionTombstones"), "import"),
)


def prepare_forget_index_fence_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate only; do not import or execute any original JavaScript owner."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
            raise ForgetIndexFenceBindingError("Forget/index fence requires the unchanged pinned source checkout")
        inherited = query.prepare_query_sync_outcomes_bindings(checkout, runtime_root)
        catalog = sessions.prepare_session_admission_runtime_bindings(checkout, runtime_root)
        applied = promotion_family.prepare_family_bindings(checkout, runtime_root)
        producer = durable.prepare_durable_session_runtime_bindings(checkout, runtime_root)
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        compiled, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        links = [
            *inherited["sourceImportLinks"], *catalog["sourceImportLinks"],
            *applied["originalOwnerBindings"]["sourceImportLinks"],
            *applied["additionalSourceImportLinks"], *producer["sourceImportLinks"],
            *_literal_links(sources, SOURCE_LITERAL_EXPORTS, kind="export"),
            *[sessions._named_link(sources, module, specifier, names, kind=kind)
              for module, specifier, names, kind in SOURCE_LINKS],
        ]
        compiled_links = _literal_links(compiled, COMPILED_IMPORTS)
        required = set(REQUIRED_LOADED_ARTIFACTS)
        if not required.issubset(COMPILED_HASHES):
            raise ForgetIndexFenceBindingError("A required route artifact has no authenticated release owner")
    except (OSError, UnicodeError, KeyError, ValueError) as error:
        if isinstance(error, ForgetIndexFenceBindingError):
            raise
        raise ForgetIndexFenceBindingError("Forget/index fence source and release authority could not be authenticated") from error
    return {
        "kind": "official-release-forget-index-fence-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "constructorSkipped": False, "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False, "providerTransportVerified": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": links, "compiledImportLinks": compiled_links,
        "composedDeclarationAuthorities": [owner.__name__ for owner in _SOURCE_MANIFESTS],
        "entrypoints": {
            "manager": {"path": "dist/extensions/memory-core/manager-runtime.js", "export": "MemoryIndexManager",
                        "methods": ["get", "sync", "search", "readFile", "status", "close"]},
            "forget": {"path": "dist/cli.runtime-CVRN4xUp.mjs", "export": "runMemoryForget",
                       "originalOwner": "forgetMemoryEntries", "resultOwner": "defaultRuntime.writeJson",
                       "directForgetExportAvailable": False},
            "promotion": {"path": "dist/short-term-promotion-Cy0NJmOU.mjs",
                          "exports": ["recordShortTermRecalls", "rankShortTermPromotionCandidates", "applyShortTermPromotions"]},
            "origins": {"path": "dist/memory-entry-origins-BCQSIB3X.mjs", "export": "a", "originalBinding": "recordMemoryEntryOrigins"},
            "producer": {"path": "dist/plugin-sdk/session-store-runtime.js", "exports": ["upsertSessionEntry", "resolveStorePath"]},
            "append": {"path": "dist/plugin-sdk/session-transcript-runtime.js", "export": "appendSessionTranscriptMessageByIdentityStrict"},
            "replace": {"path": "dist/session-accessor-CiKKTlbe.mjs", "export": "replaceTranscriptEventsSync",
                        "sourceOwner": "src/config/sessions/session-accessor.sqlite-transcript-write.ts"},
            "readback": {"path": "dist/session-accessor-CiKKTlbe.mjs", "export": "loadTranscriptEventsSync"},
            "observationReadback": {"path": "dist/session-accessor-CiKKTlbe.mjs",
                                    "export": "readTranscriptExportSnapshotReadOnlySync",
                                    "readOnly": True, "retainedResult": "whole original export snapshot"},
            "config": {"path": "dist/plugin-sdk/config-runtime.js", "export": "setRuntimeConfigSnapshot"},
            "state": {"path": "dist/extensions/memory-core/runtime-api.js", "export": "configureMemoryCoreDreamingState"},
            "stateFactory": {"path": "dist/plugin-sdk/plugin-state-store-runtime.js", "export": "createPluginStateKeyedStore"},
            "stateDatabasePath": {"path": "dist/openclaw-state-db.paths-rJI64Ab5.mjs", "export": "s",
                                  "originalBinding": "resolveOpenClawStateSqlitePath"},
            "tools": {"path": "dist/tools-DotaQGXh.mjs", "exports": ["createMemorySearchTool", "createMemoryGetTool"]},
            "stateClose": {"path": "dist/plugin-state-store-BPUaLoVD.mjs", "export": "u", "originalBinding": "closePluginStateDatabaseAsync"},
            "databaseClose": {"path": "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "export": "s", "originalBinding": "closeOpenClawAgentDatabasesAsync"},
        },
        "requiredMainArtifactsByRoute": {name: list(paths) for name, paths in REQUIRED_MAIN_ARTIFACTS_BY_ROUTE.items()},
        "requiredWorkerArtifactsByRoute": {name: list(paths) for name, paths in REQUIRED_WORKER_ARTIFACTS_BY_ROUTE.items()},
        "requiredMainArtifacts": list(REQUIRED_MAIN_ARTIFACTS),
        "requiredWorkerArtifacts": list(REQUIRED_WORKER_ARTIFACTS),
        "requiredLoadedArtifacts": list(REQUIRED_LOADED_ARTIFACTS),
        "originalChildProcessAuthority": {
            "entry": "dist/infra/sqlite-integrity.worker.js",
            "launchOwner": "src/infra/sqlite-integrity-worker.ts",
            "compiledLaunchOwner": "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs",
            "launchMethod": "fork", "sourceFunction": "assertSqliteIntegrityWithProcess",
            "actualLaunchRequestReplyAndCloseReceiptsRequired": True,
            "ancestryOnlyAdmissionAllowed": False,
        },
        "requiredLoadedArtifactsByProfile": {OPERATION: list(REQUIRED_LOADED_ARTIFACTS)},
        "workerRequiredByProfile": {OPERATION: True}, "covers": [],
        "runtimeProofRequirements": {
            "sourceProducer": "Actual original upsert and exact raw replaceTranscriptEventsSync settlements plus native transcript readback",
            "stalePublication": "Actual original prepared shadow and captured expected revision, committed forget, and original publication settlement",
            "searchFreshness": "Actual original worker snapshot and later live chunk metadata enrichment are separate observations",
            "promotion": "Original caller lock-time candidate and tombstone/origin rechecks; no candidate result replacement",
            "restart": "Distinct OS process and original reopened manager/search settlements against retained durable state",
            "workerCustody": "Required route artifacts and original dispatch/reply/close evidence in their actual main or worker process",
        },
        "limitations": [
            "Declarations and static imports supply provenance only; no earlier behavioral evidence or acceptance credit is inherited.",
            "Required routes are enforced only for operations the frozen case actually calls; authentication alone is not a load receipt.",
            "The search generation lease excludes shadow publication, while forget relies on workspace/database admission and durable revisions. Final live enrichment drops chunks deleted before that read; no later search-return revision fence is asserted.",
            "External fs-safe/native package custody remains separately required when the original file writer executes.",
            "Source, official release and actual execution are separate authorities; an independent source build is not claimed.",
        ],
    }


COMPILED_IMPORTS = {'dist/cli.runtime-CVRN4xUp.mjs': ('import { r as getRuntimeConfig } from "./io.runtime-w45cmCNp.mjs";',
                                   'import { n as listMemoryEntryOrigins, o as '
                                   'recordMemorySessionTombstonesInDatabase, t as '
                                   'deleteMemoryEntryOriginsInDatabase } from '
                                   '"./memory-entry-origins-BCQSIB3X.mjs";',
                                   'import { d as writeBackfillDiaryEntries, g as withMemoryWorkspaceLock, h '
                                   'as resolveLockPath, s as removeBackfillDiaryEntries, t as '
                                   'DREAMS_FILENAMES } from "./dreaming-dreams-file-BJzlZFlf.mjs";',
                                   'import { t as withOpenClawAgentDatabaseWrite } from '
                                   '"./openclaw-agent-db-write-CX8lsDvQ.mjs";',
                                   'import { a as runSqliteImmediateTransactionSync } from '
                                   '"./sqlite-transaction-BHOCk0oF.mjs";',
                                   'import { n as resolveMemorySessionTargets } from '
                                   '"./memory-core-host-engine-sessions-D3OZsg6m.mjs";',
                                   'import { i as commitMemoryContent, o as hashMemoryContent } from '
                                   '"./short-term-promotion-memory-write-HTLC95gL.mjs";'),
 'dist/extensions/memory-core/manager-runtime.js': ('import { i as tableExists, r as '
                                                    'readMemoryDatabaseRevision, t as '
                                                    'MemoryIndexRevisionConflictError } from '
                                                    '"../../manager-db-kernel-DyJADqYu.mjs";',
                                                    'import { n as hasMemorySessionTombstone } from '
                                                    '"../../memory-session-tombstones-B1AGruLs.mjs";',
                                                    'import { r as listMemorySessionTombstones } from '
                                                    '"../../memory-entry-origins-BCQSIB3X.mjs";'),
 'dist/manager-publication.worker-x9zokjMA.mjs': ('import { n as publishMemoryDatabaseTables, r as '
                                                  'readMemoryDatabaseRevision } from '
                                                  '"./manager-db-kernel-DyJADqYu.mjs";',
                                                  'import { n as hasMemorySessionTombstone } from '
                                                  '"./memory-session-tombstones-B1AGruLs.mjs";',
                                                  'import { a as runSqliteImmediateTransactionSync, t as '
                                                  'assertTransactionUsable } from '
                                                  '"./sqlite-transaction-BHOCk0oF.mjs";',
                                                  'import { t as assertMemoryShadowIdentity } from '
                                                  '"./manager-shadow-task-DGuJMed1.mjs";'),
 'dist/manager-db-kernel-DyJADqYu.mjs': ('import { a as runSqliteImmediateTransactionSync } from '
                                         '"./sqlite-transaction-BHOCk0oF.mjs";',
                                         'import { C as ensureMemoryRecallMetadataSchema, E as '
                                         'ensureMemoryChunkProvenance, S as '
                                         'MEMORY_INDEX_CHUNK_RECALL_METADATA_TABLE, _ as '
                                         'dropMemoryChunkFtsTriggers, b as ensureMemoryPathFtsTriggers, m as '
                                         'MEMORY_INDEX_PATHS_FTS_TABLE, p as MEMORY_INDEX_FTS_TABLE, v as '
                                         'dropMemoryPathFtsTriggers, x as rebuildMemoryChunkFts, y as '
                                         'ensureMemoryChunkFtsTriggers } from '
                                         '"./memory-schema-SE7C0M3V.mjs";'),
 'dist/short-term-promotion-Cy0NJmOU.mjs': ('import { a as applyShortTermPromotions, c as '
                                            'loadShortTermPromotionDreamingStats, d as '
                                            'recordRemConsideredPhaseSignals, i as '
                                            'repairShortTermPromotionArtifacts, l as readLightStagedKeys, n '
                                            'as auditShortTermPromotionArtifacts, r as '
                                            'removeGroundedShortTermCandidates, s as '
                                            'filterFreshLightDreamingEntries, t as '
                                            'rankShortTermPromotionCandidates, u as '
                                            'recordDreamingPhaseSignals } from '
                                            '"./short-term-promotion-MX1vHJuE.mjs";',
                                            'import { i as recordShortTermRecalls, n as '
                                            'readShortTermRecallEntries, r as '
                                            'recordGroundedShortTermCandidates, t as '
                                            'filterLiveShortTermRecallEntries } from '
                                            '"./short-term-promotion-record-DrLa1fiO.mjs";'),
 'dist/short-term-promotion-MX1vHJuE.mjs': ('import { i as pruneMemoryEntryOrigins, s as '
                                            'reserveMemoryEntryOrigins } from '
                                            '"./memory-entry-origins-BCQSIB3X.mjs";',
                                            'import { g as withMemoryWorkspaceLock, h as resolveLockPath, m '
                                            'as isShortTermLockStealable, p as '
                                            'deleteShortTermLockEntryIfCurrent, u as updateDreamsFile } from '
                                            '"./dreaming-dreams-file-BJzlZFlf.mjs";',
                                            'import { a as extractPromotionKeys, c as readMemoryContent, i '
                                            'as commitMemoryContent, l as resolveMemoryWritePath, n as '
                                            'MemoryWriteConflictError, o as hashMemoryContent, r as '
                                            'buildPromotionMarker, s as isAtomicReplacePermissionError, t as '
                                            'MemoryAtomicPublicationError } from '
                                            '"./short-term-promotion-memory-write-HTLC95gL.mjs";'),
 'dist/short-term-promotion-record-DrLa1fiO.mjs': ('import { a as recordMemoryEntryOrigins, r as '
                                                   'listMemorySessionTombstones } from '
                                                   '"./memory-entry-origins-BCQSIB3X.mjs";',
                                                   'import { g as withMemoryWorkspaceLock } from '
                                                   '"./dreaming-dreams-file-BJzlZFlf.mjs";'),
 'dist/plugin-sdk/session-store-runtime.js': ('import { _ as updateSessionStoreEntry, a as '
                                              'listSessionEntries, c as patchSessionEntry, d as '
                                              'readTranscriptStatsSync, f as resolveSessionFilePath, g as '
                                              'updateSessionStore, h as resolveStorePath, i as '
                                              'getSessionEntry, l as readAmbientTranscriptWatermark, m as '
                                              'resolveSessionStoreEntry, n as deleteSessionEntry, o as '
                                              'loadSessionStore, p as resolveSessionStoreBackupPaths, r as '
                                              'getConversationSession, s as loadTranscriptEventsSync, t as '
                                              'cleanupSessionLifecycleArtifacts, u as readSessionUpdatedAt, '
                                              'v as upsertSessionEntry } from '
                                              '"../session-store-runtime-C3lQUqXM.mjs";',),
 'dist/plugin-sdk/session-transcript-runtime.js': ('import { _ as createSessionCatalogGitHubLinker, a as '
                                                   'appendSessionYieldContext, c as '
                                                   'readSessionTranscriptEvents, d as '
                                                   'readVisibleSessionTranscriptMessageEntries, f as '
                                                   'resolveSessionTranscriptIdentity, g as '
                                                   'readSessionTranscriptCatalogTitle, h as '
                                                   'readSessionTranscriptCatalogPage, i as '
                                                   'appendSessionTranscriptMessagesByIdentity, l as '
                                                   'readSessionTranscriptRawDelta, m as '
                                                   'withSessionTranscriptWriteLock, n as '
                                                   'appendSessionTranscriptMessageByIdentity, o as '
                                                   'publishSessionTranscriptUpdateByIdentity, p as '
                                                   'resolveSessionTranscriptTarget, r as '
                                                   'appendSessionTranscriptMessageByIdentityStrict, s as '
                                                   'readLatestAssistantTextByIdentity, t as '
                                                   'appendAssistantMirrorMessageByIdentity, u as '
                                                   'readSessionTranscriptVisibleMessageDelta, v as '
                                                   'createSessionCatalogSourceActorProjector } from '
                                                   '"../session-transcript-runtime-Bo5y_sts.mjs";',),
 'dist/session-transcript-runtime-Bo5y_sts.mjs': ('import { d as appendTranscriptMessages, f as '
                                                  'persistSessionTranscriptTurn, k as '
                                                  'readTranscriptRawDelta, o as '
                                                  'appendSessionTranscriptReport } from '
                                                  '"./session-accessor-WMUIp1Kx.mjs";',),
 'dist/session-accessor-CiKKTlbe.mjs': ('import { $ as withSessionPendingInputPersistence, A as '
                                        'persistCompactionBoundaryWithSessionEntrySync, C as '
                                        'preflightSessionTranscriptForManualCompact, D as '
                                        'loadTranscriptSuffixEventsBoundedSync, E as '
                                        'rewriteTranscriptMessageAtAnchor, F as rewriteDoctorSessionEntries, '
                                        'I as listCanonicalSessionRepairFacts, K as '
                                        'recoverSessionEntryFromRestartTombstone, L as '
                                        'loadCanonicalSessionRepairEntries, M as rewindSessionToMessage, N '
                                        'as switchSessionBranch, O as '
                                        'readPreviousIndexedTranscriptEventSync, P as '
                                        'iterateDoctorSessionKeyBatches, Q as stageSessionPendingInput, R as '
                                        'scanDoctorSessionEntriesStrict, T as '
                                        'rewriteAssistantTranscriptMessageForRun, V as '
                                        'recordSessionParticipantInWorker, W as '
                                        'updateSessionProfileInvolvement, X as readSessionPendingInput, Y as '
                                        'listSessionPendingInputs, Z as readSessionSubmittedInput, c as '
                                        'readLatestSessionTranscriptReport, d as appendTranscriptMessages, f '
                                        'as persistSessionTranscriptTurn, i as '
                                        'listSessionParticipantsReadOnly, j as forkSessionAtMessage, k as '
                                        'readTranscriptRawDelta, l as readSessionTranscriptWatermark, n as '
                                        'readSessionBackingFacts, o as appendSessionTranscriptReport, q as '
                                        'bindSessionPendingInputSources, t as '
                                        'readSessionBackingFactsInWorker, w as '
                                        'trimSessionTranscriptForManualCompact, z as '
                                        'scanDoctorSessionEntriesTolerant } from '
                                        '"./session-accessor-WMUIp1Kx.mjs";',
                                        'import { C as readTranscriptIdentityByEventId, E as '
                                        'readTranscriptStatsSync, O as validatePreparedAssistantAppendSync, '
                                        'T as readTranscriptStatsBatchReadOnlySync, _ as '
                                        'readTranscriptEventAtSeqSync, a as inspectTranscriptEventsSync, c '
                                        'as loadTranscriptEvents, d as loadTranscriptHeaderSync, i as '
                                        'hasSessionTranscriptMessage, o as loadLatestAssistantText, s as '
                                        'loadTranscriptEventRowsAfterSeqSync, u as loadTranscriptEventsSync, '
                                        'x as readTranscriptExportSnapshotReadOnlySync } from '
                                        '"./session-accessor.sqlite-read-BsSfe2AE.mjs";'),
 'dist/extensions/memory-core/runtime-api.js': ('import { p as configureMemoryCoreDreamingState } from '
                                                '"../../dreaming-state-VYUvbU-n.mjs";',),
 'dist/plugin-sdk/config-runtime.js': ('import { D as setRuntimeConfigSnapshot, l as '
                                       'getRuntimeConfigSourceSnapshot, n as clearRuntimeConfigSnapshot, o '
                                       'as getRuntimeConfigSnapshot } from '
                                       '"../runtime-snapshot-BFi3jxlO.mjs";',),
 'dist/memory-core-host-engine-sessions-D3OZsg6m.mjs': ('import { M as '
                                                        'listSessionTranscriptArchivesReadOnly, o as '
                                                        'listSessionTranscriptInstances } from '
                                                        '"./session-accessor.sqlite-entry-BrsmAX-T.mjs";',
                                                        'import { i as listSessionParticipantsReadOnly } '
                                                        'from "./session-accessor-WMUIp1Kx.mjs";')}

SOURCE_LITERAL_EXPORTS = {'src/plugin-sdk/config-runtime.ts': ('export {\n'
                                      '  clearConfigCache,\n'
                                      '  clearRuntimeConfigSnapshot,\n'
                                      '  getRuntimeConfigSourceSnapshot,\n'
                                      '  getRuntimeConfigSnapshot,\n'
                                      '  getRuntimeConfig,\n'
                                      '  /**\n'
                                      '   * @deprecated Use getRuntimeConfig(), '
                                      'runtime.config.current(), or pass the\n'
                                      '   * already loaded config through the call path. Runtime code '
                                      'must not reload\n'
                                      '   * config on demand. Bundled plugins and repo code are blocked '
                                      'from using\n'
                                      '   * this by the deprecated-internal-config-api architecture '
                                      'guard.\n'
                                      '   */\n'
                                      '  loadConfig,\n'
                                      '  readConfigFileSnapshotForWrite,\n'
                                      '  setRuntimeConfigSnapshot,\n'
                                      '  /**\n'
                                      '   * @deprecated Use mutateConfigFile() or replaceConfigFile() '
                                      'with an explicit\n'
                                      '   * afterWrite intent so restart behavior stays under host '
                                      'control. Bundled\n'
                                      '   * plugins and repo code are blocked from using this by the\n'
                                      '   * deprecated-internal-config-api architecture guard.\n'
                                      '   */\n'
                                      '  writeConfigFile,\n'
                                      '} from "../config/io.js";',)}
