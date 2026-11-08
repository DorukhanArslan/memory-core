"""Authenticate the original public file/SQLite transcript source boundaries.

Source declarations and official release bytes remain distinct authorities.
The profile does not construct an index manager, implement transcript filtering
in an adapter, or claim SQLite/JSONL source-cache freshness equivalence.
"""
from __future__ import annotations

from pathlib import Path
import hashlib

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _owners, _named_link

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'packages/memory-host-sdk/src/host/session-files.ts': 'd184bf1a1b098a02b08ed131321fb47d6caf5bee9e1cc6d88751502dbb8761ee',
 'packages/memory-host-sdk/src/host/session-entry-projection.ts': '34458bdb1827bc240626c7f81f6840ce5b23263e3f37b5342881f3ec9eaaad8d',
 'packages/memory-host-sdk/src/host/session-provenance.ts': '312eac1018ccb49bd98acee26f70a074fa51ed8c17075ad98b8fbbd62469e63b',
 'packages/memory-host-sdk/src/host/session-reset-recall.ts': 'dea5a5ad57b0219692f1e723abe3a5f2cda767cd4888abece657fbd9fc67adb8',
 'packages/memory-host-sdk/src/host/openclaw-runtime-session.ts': '51fed14e0695f0caf97d1b3296ed5cdba7b8867bca4de8611509af68fce14eed',
 'src/plugin-sdk/memory-core-host-engine-sessions.ts': 'e05da58485856c557ae7e37e97dbffba0da0abe8b72d355261ee784d1db12f7b',
 'src/config/sessions/session-accessor.sqlite-read.ts': '6434a27cd8268627fd1787d7afebe2c97792cee17376262534248fb388fa068d',
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': '4e6ee07463e2cd5e1064400535dc332d7c0d2c761997eefb3b59dea6d33a1b0a',
 'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11',
 'src/config/sessions/archive-compression.ts': 'be57fa752f1ee4bcda62090b35e93216665a691b79b8766d84ffe5434b183dda',
 'src/infra/zstd-codec.ts': '4ef503fe0fc8f57b7ecb97a04a831fbb15360a28d2b0095e1f28564d545f6f58',
 'packages/memory-host-sdk/src/engine-sessions.ts': 'd4c312c0b7fb9a1caac069081869517118d9f0a863fc78dc846a86ed45ad1997',
 'packages/memory-host-sdk/src/host/fs-utils.ts': '17f4e7697239791c99ba487ee26a62ff9bc9b23d2f08cd7e894d1a51e79f2e73',
 'packages/memory-host-sdk/src/host/read-retry.ts': '9cb198e12356e8cf1c3f35dc6d1d4cfaf0f00dbb0c1d74f71b71d8cd42d7c4da',
 'src/config/sessions/session-transcript-read-worker-runtime.ts': '7ebf8c229238a6825100d50dd89ea3973494d8ad76662d35f59f0ea70d17ae07',
 'src/config/sessions/session-transcript.worker.ts': '7e50bf974d3fd7b694b4d29007df6cfa896ae8f8bb395911e7b6b1e78008ea03',
 'src/infra/runtime-process-entrypoints.ts': '23576e3d35022ff7d7c4b4b163587d826b7e2b96b7e84533f8ac92189c7f3752',
 'src/infra/runtime-worker-url.ts': '9b694a778a84725e989ad2380195557993afbf25dc97e64112f7a65b2a2087e0',
 'src/infra/worker-task-pool.ts': 'fcaafd845ed8a9285ea385a05a4324e01a6c5bfc29a5fca99b69705054be8bca',
 'src/infra/tmp-openclaw-dir.ts': 'a0e74b9fb4e9b53215d7bc1fa830d539345a98a973d5b308db9db5de20d8afed'}

SOURCE_ANCHORS = {'packages/memory-host-sdk/src/host/session-files.ts': ('export async function buildSessionEntry(',
                                                        'export async function '
                                                        'buildSessionEntryInProcess(',
                                                        'export function '
                                                        'sessionPathForSessionIdentity(agentId: string, '
                                                        'sessionId: string): string {',
                                                        'export function '
                                                        'readSessionEntryResetRecallCutoff(',
                                                        'const SESSION_RESET_RECALL_CUTOFF = '
                                                        'Symbol.for("openclaw.memory.sessionResetRecallCutoff");'),
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
 'packages/memory-host-sdk/src/host/openclaw-runtime-session.ts': ('export function '
                                                                   'isDreamingNarrativeSessionStoreKey(sessionKey: '
                                                                   'string): boolean {',),
 'src/plugin-sdk/memory-core-host-engine-sessions.ts': ('export function '
                                                        'loadMemorySessionMetadata(params: {',),
 'src/config/sessions/session-accessor.sqlite-read.ts': ('export function '
                                                         'readTranscriptExportSnapshotReadOnlySync(',
                                                         'export function '
                                                         'loadTranscriptEventsSync(scope: '
                                                         'SessionTranscriptReadScope): '
                                                         'TranscriptEvent[] {'),
 'src/config/sessions/session-accessor.sqlite-transcript-write.ts': ('export function '
                                                                     'replaceTranscriptEventsSync(',),
 'src/plugin-sdk/session-store-runtime.ts': ('export async function upsertSessionEntry(params: '
                                             'UpsertSessionEntryParams): Promise<void> {',
                                             'export async function deleteSessionEntry(params: '
                                             'DeleteSessionEntryParams): Promise<boolean> {'),
 'src/config/sessions/archive-compression.ts': ('export function '
                                                'readSessionArchiveContentSync(filePath: string): '
                                                'string {',
                                                'export function decodeSessionArchiveBytes(bytes: '
                                                'Uint8Array, compressed: boolean): string {',
                                                'export function '
                                                'materializeSessionArchiveForRead(filePath: string): '
                                                'string {'),
 'src/infra/zstd-codec.ts': ('export function resolveZstdCodec(): ZstdCodec | null {',),
 'packages/memory-host-sdk/src/engine-sessions.ts': ('  buildSessionEntry,',
                                                     '} from "./host/session-files.js";'),
 'packages/memory-host-sdk/src/host/fs-utils.ts': ('export { readRegularFile, statRegularFile } from '
                                                   '"@openclaw/fs-safe/advanced";',),
 'packages/memory-host-sdk/src/host/read-retry.ts': ('export async function '
                                                     'retryTransientMemoryRead<T>(',),
 'src/config/sessions/session-transcript-read-worker-runtime.ts': ('export async function '
                                                                   'prepareSessionEntryInWorker(',
                                                                   'const workerUrl = '
                                                                   'resolveRuntimeWorkerUrl(runtimeProcessEntrypoints.sessionTranscript);'),
 'src/config/sessions/session-transcript.worker.ts': ('serveOwnedWorkerTasks(',
                                                      '          const entry = await '
                                                      'buildSessionEntryInProcess('),
 'src/infra/runtime-process-entrypoints.ts': ('export const runtimeProcessEntrypoints = {',),
 'src/infra/runtime-worker-url.ts': ('export function resolveRuntimeWorkerUrl(params: {',),
 'src/infra/worker-task-pool.ts': ('export class WorkerTaskPool<Input, Output> {',),
 'src/infra/tmp-openclaw-dir.ts': ('export const DEFAULT_POSIX_TMP_ROOT = "/tmp/openclaw";',
                                   'export function resolvePreferredOpenClawTmpDir(')}

COMPILED_HASHES = {'dist/session-files-DVVT4Ngb.mjs': '0a933051a4cf16dd7f5ddb15df3df6d5c950cd1a09b7fd2729d8c86e54842dc9',
 'dist/session-accessor-CiKKTlbe.mjs': '287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a',
 'dist/session-accessor.sqlite-entry-BrsmAX-T.mjs': 'bb80d5b238fb5eaeb23a0f2a12d9a978b9cafa3962e78984538d801eb6f86e64',
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': 'f351ef360d46add8ead586270b6609b388380cc820d631f7c4ed945e6e506d7e',
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
 'dist/artifacts-D5koLTEP.mjs': '438b315be956f590b1e06ea29ce13009c8818517e4a227c1f3d96500f48958dd',
 'dist/zstd-codec-C-vEb3Qf.mjs': 'ffa2adb8e96fe3bce2bb4a1d1af86841973f8f5183170e2fb64e876340e95b5a',
 'dist/plugin-sdk/memory-core-host-engine-sessions.js': '745b7ecbad801d31d5147d51824adc2683663a243c5f551ed18aa8cdbb4330ac',
 'dist/openclaw-runtime-session-cZ0ZaiUL.mjs': 'c180ffa73e9e9c8a4fffdc5f4373e57ceaffc74939c19e20c17ea302a3487ff5',
 'dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs': '3764066f2cb47318cff9e130682c3813f43e11d4990f88e8c43a42b3ca8bfbb9',
 'dist/config/sessions/session-transcript.worker.js': '30bee98b7f19e310f35e9e2f4fa29c48467daf05fc14b6209d0518b347c7610e',
 'dist/runtime-process-entrypoints-Bh4reDp0.mjs': 'd8031c4fff5902dc7c99a70daf2d4c8f1ce809db149e029d77c0dac2873dfc4a',
 'dist/runtime-worker-url-S0NIVxUR.mjs': '49585b6cc537babf6c8e4f795c709e3b109af37b3df46161afcf593b506a136b',
 'dist/worker-task-pool-BQlnRNqZ.mjs': '79ea82aa29baa5d72f600d5191ee4a3a0bd62fed0062cc8da96877cf334ccf2d',
 'dist/session-provenance-2cpkCo2r.mjs': 'd5015d2e15036f4c1d8e517f6fbf3837a87056f9c5cd629de221c45bbe9c910c',
 'dist/session-reset-recall-ZlAM1yc3.mjs': '0cd2955edb7a224114e4184780d848d8f31b073e7ef8534d49c77464658d11bd',
 'dist/fs-utils-WWARJ71o.mjs': 'bada7e55184567bafb6693bac0f34854542e978ef06fd5fe6b082bcf839d39df',
 'dist/read-retry-91Lh2b4l.mjs': 'b767d23b66cead2647683323f33f7380fe20137e7781c01d2e4fca95a4e4b046',
 'dist/tmp-openclaw-dir-BSb3HetY.mjs': 'b5f3f4cfc8211fe003211a12b08d0087c0ec7bcd65969b7ab5c84b0cb49d47c9'}

COMPILED_ANCHORS = {'dist/session-files-DVVT4Ngb.mjs': ('async function buildSessionEntry(absPath, opts = {}) {',
                                     'async function buildSessionEntryInProcess(absPath, opts = {}, '
                                     'redactText = (text) => redactSensitiveText(text, { mode: "tools" '
                                     '})) {',
                                     'async function '
                                     'listSessionTranscriptCorpusEntriesForAgent(agentId, options = {}) '
                                     '{',
                                     'function readSessionEntryResetRecallCutoff(entry) {',
                                     'readSessionEntryResetRecallCutoff as a,',
                                     'buildSessionEntry as t'),
 'dist/session-accessor-CiKKTlbe.mjs': ('export {',
                                        'V as recordSessionParticipantInWorker',
                                        'i as listSessionParticipantsReadOnly',
                                        'recordSessionParticipantInWorker as recordSessionParticipant'),
 'dist/session-accessor.sqlite-entry-BrsmAX-T.mjs': ('async function upsertSessionEntryCore(scope, '
                                                     'patch, options = {}) {',
                                                     'function listSessionTranscriptInstances(scope = '
                                                     '{}, options = {}) {'),
 'dist/session-accessor.sqlite-read-BsSfe2AE.mjs': ('function '
                                                    'readTranscriptExportSnapshotReadOnlySync(scope, '
                                                    'options = {}) {',
                                                    'function loadTranscriptEventsSync(scope) {'),
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function '
                                                                'replaceTranscriptEventsSync(scope, '
                                                                'events) {',),
 'dist/artifacts-D5koLTEP.mjs': ('function readSessionArchiveContentSync(filePath) {',
                                 'function decodeSessionArchiveBytes(bytes, compressed) {',
                                 'function materializeSessionArchiveForRead(filePath) {',
                                 'materializeSessionArchiveForRead as v, readSessionArchiveContentSync '
                                 'as y'),
 'dist/zstd-codec-C-vEb3Qf.mjs': ('function resolveZstdCodec() {', 'export { resolveZstdCodec as t };'),
 'dist/plugin-sdk/memory-core-host-engine-sessions.js': ('t as buildSessionEntry } from '
                                                         '"../session-files-DVVT4Ngb.mjs";',
                                                         'export { buildSessionEntry,'),
 'dist/openclaw-runtime-session-cZ0ZaiUL.mjs': ('async function prepareSessionEntryInWorker(...args) '
                                                '{',),
 'dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs': ('async function '
                                                              'prepareSessionEntryInWorker(absPath, '
                                                              'options, redaction) {',
                                                              'const workerUrl = '
                                                              'resolveRuntimeWorkerUrl(runtimeProcessEntrypoints.sessionTranscript);'),
 'dist/config/sessions/session-transcript.worker.js': ('serveOwnedWorkerTasks(',
                                                       'const entry = await '
                                                       'buildSessionEntryInProcess('),
 'dist/runtime-process-entrypoints-Bh4reDp0.mjs': ('sessionTranscript: '
                                                   'runtimeProcessEntrypoint("config/sessions/session-transcript.worker"),',),
 'dist/runtime-worker-url-S0NIVxUR.mjs': ('function resolveRuntimeWorkerUrl(params) {',),
 'dist/worker-task-pool-BQlnRNqZ.mjs': ('var WorkerTaskPool = class',),
 'dist/session-provenance-2cpkCo2r.mjs': ('function classifySessionMessageOrigin(message, turnOrigin) '
                                          '{',),
 'dist/session-reset-recall-ZlAM1yc3.mjs': ('function resolveSessionResetRecallCutoff(events) {',),
 'dist/fs-utils-WWARJ71o.mjs': ('readRegularFile$1 as r,', 'statRegularFile as a,'),
 'dist/read-retry-91Lh2b4l.mjs': ('async function retryTransientMemoryRead(read, label = "memory read") '
                                  '{',),
 'dist/tmp-openclaw-dir-BSb3HetY.mjs': ('const DEFAULT_POSIX_TMP_ROOT = "/tmp/openclaw";',
                                        'function resolvePreferredOpenClawTmpDir(options = {}) {')}

EXTERNAL_HASHES = {'dist/secure-temp-dir.js': 'c1a9987945911782371292c24670ac4ac9382986e8edfa8fe2981a074c4a9f4b'}

EXTERNAL_ANCHORS = {'dist/secure-temp-dir.js': ('export function resolveSecureTempRoot(options) {',
                             '    const existingPreferredState = resolveDirState(entryPath);')}


REQUIRED_BOUNDARY_ARTIFACTS = (
    "dist/plugin-sdk/memory-core-host-engine-sessions.js", "dist/session-files-DVVT4Ngb.mjs",
    "dist/session-provenance-2cpkCo2r.mjs", "dist/session-reset-recall-ZlAM1yc3.mjs",
    "dist/fs-utils-WWARJ71o.mjs", "dist/read-retry-91Lh2b4l.mjs",
)
SQLITE_BOUNDARY_ARTIFACTS = (
    "dist/session-accessor-CiKKTlbe.mjs", "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs",
    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs", "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
)
TRANSCRIPT_WORKER_ARTIFACTS = (
    "dist/config/sessions/session-transcript.worker.js",
)
TRANSCRIPT_WORKER_PARENT_ARTIFACTS = (
    "dist/openclaw-runtime-session-cZ0ZaiUL.mjs",
    "dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs",
    "dist/runtime-process-entrypoints-Bh4reDp0.mjs", "dist/runtime-worker-url-S0NIVxUR.mjs",
    "dist/worker-task-pool-BQlnRNqZ.mjs",
)
ARCHIVE_ARTIFACTS = (
    "dist/artifacts-D5koLTEP.mjs", "dist/zstd-codec-C-vEb3Qf.mjs", "dist/tmp-openclaw-dir-BSb3HetY.mjs",
)

class TranscriptBoundaryBindingError(ValueError):
    """The pinned public transcript read owner or native dependency changed."""


def prepare_transcript_boundary_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise TranscriptBoundaryBindingError("Transcript reads require the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        external_root = runtime_root.parent / "@openclaw" / "fs-safe"
        _, external_evidence = _owners(external_root, EXTERNAL_HASHES, EXTERNAL_ANCHORS, committed=False)
        specs = (
            ("src/plugin-sdk/memory-core-host-engine-sessions.ts", "../../packages/memory-host-sdk/src/engine-sessions.js",
             ("buildSessionEntry",), "export"),
            ("packages/memory-host-sdk/src/engine-sessions.ts", "./host/session-files.js", ("buildSessionEntry",), "export"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./session-entry-projection.js",
             ("projectSessionEntryRecord", "collectRawSessionText"), "import"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./session-provenance.js",
             ("classifySessionMessageOrigin",), "import"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./session-reset-recall.js",
             ("resolveSessionResetRecallCutoff",), "import"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./fs-utils.js",
             ("readRegularFile", "statRegularFile"), "import"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./read-retry.js",
             ("retryTransientMemoryRead",), "import"),
            ("packages/memory-host-sdk/src/host/session-files.ts", "./openclaw-runtime-session.js",
             ("materializeSessionArchiveForRead", "prepareSessionEntryInWorker",
              "readTranscriptExportSnapshotReadOnlySync"), "import"),
            ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts",
             "../../../../src/config/sessions/session-accessor.js",
             ("readTranscriptExportSnapshotReadOnlySync",), "import"),
            ("src/config/sessions/session-transcript-read-worker-runtime.ts", "../../infra/runtime-process-entrypoints.js",
             ("runtimeProcessEntrypoints",), "import"),
            ("src/config/sessions/session-transcript-read-worker-runtime.ts", "../../infra/runtime-worker-url.js",
             ("resolveRuntimeWorkerUrl",), "import"),
            ("src/config/sessions/session-transcript-read-worker-runtime.ts", "../../infra/worker-task-pool.js",
             ("WorkerTaskPool",), "import"),
            ("src/config/sessions/archive-compression.ts", "../../infra/zstd-codec.js", ("resolveZstdCodec",), "import"),
            ("src/config/sessions/archive-compression.ts", "../../infra/tmp-openclaw-dir.js",
             ("resolvePreferredOpenClawTmpDir",), "import"),
            ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts", "../../../../src/config/sessions/archive-compression.js",
             ("materializeSessionArchiveForRead",), "export"),
        )
        chain = [_named_link(sources, module, specifier, names, kind=kind)
                 for module, specifier, names, kind in specs]
        dynamic = (
            ("packages/memory-host-sdk/src/host/openclaw-runtime-session.ts",
             'await import("../../../../src/config/sessions/session-transcript-read-worker-runtime.js");'),
            ("src/config/sessions/session-transcript.worker.ts",
             'await import("../../../packages/memory-host-sdk/src/host/session-files.js");'),
        )
        for module, anchor in dynamic:
            expected_count = 2 if module.endswith("openclaw-runtime-session.ts") else 1
            if sources[module].count(anchor) != expected_count:
                raise TranscriptBoundaryBindingError("The actual transcript worker owner import changed.")
            offsets = [index for index in range(len(sources[module])) if sources[module].startswith(anchor, index)]
            chain.append({"path": module, "kind": "dynamic-import", "declaration": anchor,
                          "lines": [sources[module][:index].count("\n") + 1 for index in offsets],
                          "declarationSha256": hashlib.sha256(anchor.encode()).hexdigest()})
    except (OSError, UnicodeError, ValueError) as error:
        raise TranscriptBoundaryBindingError("Transcript source owner provenance could not be verified.") from error
    return {
        "kind": "official-release-transcript-source-boundaries", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "indexManagerConstructed": False, "managerFixture": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain, "compiledBindings": compiled_evidence,
        "externalRuntimeBindings": [{"package": "node_modules/@openclaw/fs-safe", **row} for row in external_evidence],
        "requiredBoundaryArtifacts": list(REQUIRED_BOUNDARY_ARTIFACTS),
        "additionalSqliteArtifacts": list(SQLITE_BOUNDARY_ARTIFACTS),
        "requiredTranscriptWorkerArtifacts": list(TRANSCRIPT_WORKER_ARTIFACTS),
        "transcriptWorkerParentArtifacts": list(TRANSCRIPT_WORKER_PARENT_ARTIFACTS),
        "transcriptWorkerRequiredWhen": "SQLite identity read without observer or explicit parseYieldEveryLines",
        "additionalArchiveArtifacts": list(ARCHIVE_ARTIFACTS),
        "archiveArtifactsRequiredWhen": "JSONL .zst source path",
        "clock": {"owner": "node:test", "apis": ["Date"], "realTimersAndPerformance": True},
        "filesystemFault": {"input": "environmentFault.kind=preferred-temp-root-unavailable",
                            "target": "/tmp/openclaw", "operation": "lstatSync", "code": "EACCES",
                            "purpose": "Genuine secure temporary-root fallback into owned TMPDIR",
                            "originalMethodRestorationRequired": True, "sharedCachePermitted": False},
        "profiles": {
            "jsonl": {"physicalLineOrdinals": True, "fileAndCodecErrorsReturnNull": True},
            "sqlite": {"genuineReadAccessor": True, "projectedStoredEventOrdinals": True,
                       "operationalErrorsPropagate": True, "activeLeafFilteringInAdapter": False},
        },
        "fullHostOrchestrationVerified": False, "restartRecallVerified": False,
        "sourceCacheFreshnessEquivalent": False,
    }
