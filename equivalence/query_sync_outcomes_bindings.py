"""Authenticate the original query-sync owners and their official release bytes.

These declarations supply provenance only. Genuine source mutations, public tool
dispatch, worker requests and replies, and original close settlement must still
be observed separately. No earlier family's behavioral evidence is inherited.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.index_identity_boundaries_bindings import (
    COMPILED_ANCHORS as IDENTITY_COMPILED_ANCHORS,
    COMPILED_HASHES as IDENTITY_COMPILED_HASHES,
    REQUIRED_MAIN_ARTIFACTS as IDENTITY_REQUIRED_MAIN_ARTIFACTS,
    REQUIRED_WORKER_ARTIFACTS as IDENTITY_REQUIRED_WORKER_ARTIFACTS,
    SOURCE_ANCHORS as IDENTITY_SOURCE_ANCHORS,
    SOURCE_HASHES as IDENTITY_SOURCE_HASHES,
    IndexIdentityBoundariesBindingError,
    _merged_anchors,
    prepare_index_identity_boundaries_bindings,
)
from equivalence.reference_bindings import ReferenceBindingError
from equivalence.reuse_bindings import ReuseBindingError, _named
from equivalence.search_contract_runtime_bindings import (
    REFERENCE_COMMIT,
    SearchContractRuntimeBindingError,
    _owners,
)

OPERATION = "query-sync-outcomes-runtime"

ADDITIONAL_SOURCE_HASHES = {
    "extensions/memory-core/src/memory/manager-watch-ops.ts":
        "a8997a7763c2ebd281dbfeb22b895bfee407928ef2de8e55b5b0df2a9fad5089",
    "extensions/memory-core/src/memory/manager-watch-resources.ts":
        "86a5317459b222911c2f441256117031cc181c60024b16a9ca4e44a21047a696",
    "extensions/memory-core/src/memory/file-watcher.ts":
        "8e4aa9ad6ddb453d0a79c6312ee357d00a3eb324f283739bfd84db9f947f6bf0",
    "extensions/memory-core/src/memory/watch-settle.ts":
        "216bffee556af6a2cf8fadbfcab0ebed242d0d306f7e4b5876f7092f10ac5e5a",
    "extensions/memory-core/src/memory/manager-source-state.ts":
        "cb5060607d2f9166285768d41d40eb439632ecd691b5fe591f31ca6f54ffe88e",
    "extensions/memory-core/src/memory/manager-source-sync-ops.ts":
        "bc6a8fba716ffe3bd6cb130b3e415a057982b84a494ded95429acf7d7721e4b1",
    "extensions/memory-core/src/memory/manager-search-maintenance.ts":
        "912eec6a343daa43e0d7eee5bfea95f4d174d3cc26b8eec477600def061a957d",
    "extensions/memory-core/src/memory/manager-sync-outcome.ts":
        "ee4cb9359285e322a52e963695f4b84bf07c4903facb392e83549540c9d2a3c1",
    "extensions/memory-core/src/memory/manager-keyword-retrieval.ts":
        "fd754dd63c7c31bc892a36cd300b3107369c46d554abb12e50cf085374123458",
    "extensions/memory-core/src/memory/temporal-decay.ts":
        "9f17677375dfc02664101c984563ce10fbff94c2629e38adcb8ec4b0d860b8d4",
    "src/plugin-sdk/process-runtime.ts":
        "a74d33e18876dc2f5de6d531de08b7cd744e0f727529f918989ef6ea665ac4a8",
    "src/infra/worker-task-pool.ts":
        "fcaafd845ed8a9285ea385a05a4324e01a6c5bfc29a5fca99b69705054be8bca",
    "src/infra/worker-task-pool-core.ts":
        "1cda75ab8e4a9df63b96174a701a82080c7c41fa7fe6e98a0d13941af7660727",
    "src/infra/worker-task-pool.types.ts":
        "49009b1da6c23da0a1b33e3c214c626897cb48289b0591628447aaf11a78f6eb",
    "src/infra/sqlite-worker-broker-reply.ts":
        "3b5040dd5b8521c27f1500b45b244df265c927b0215309399aceb79ebf5cb819",
    "packages/memory-host-sdk/src/host/internal.ts":
        "f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591",
    "extensions/memory-core/src/memory/manager-sqlite-lease.ts":
        "df3a7c9cc8a7a481cc91db5cafa68d2f550ff61393de98cc3490e73dbc492b0b",
}

ADDITIONAL_SOURCE_ANCHORS = {
    "extensions/memory-core/src/memory/manager.ts": (
        "  protected async syncPublishedIndexInBackground(params: { reason: string }): Promise<void> {",
        "  protected async syncAdmitted(",
        "  private async closeOnce(): Promise<void> {",
        "    await this.awaitManagerIdle();",
        "    await this.syncing?.catch(reportPendingWorkError);",
    ),
    "extensions/memory-core/src/memory/manager-sync-base.ts": (
        "  protected markMemoryWatchDirty(): void {",
        "    this.memoryWatchGeneration += 1;",
        "  takeReindexRetryStateForMaintenance(): MemoryReindexRetryState {",
    ),
    "extensions/memory-core/src/memory/manager-provider-lifecycle.ts": (
        "  protected async awaitManagerIdle(): Promise<void> {",
        '    while (this.purpose !== "cli" && this.activeBackgroundSearchSyncs.size > 0) {',
    ),
    "extensions/memory-core/src/memory/manager-search-orchestration.ts": (
        '        const trackedSearchSync = this.syncPublishedIndexInBackground({ reason: "search" })',
        "        this.activeBackgroundSearchSyncs.add(trackedSearchSync);",
    ),
    "extensions/memory-core/src/memory/manager-watch-ops.ts": (
        "export abstract class MemoryManagerWatchOps extends MemoryManagerSyncBase {",
        "  protected ensureWatcher() {",
        "  protected async closeWatchResources(): Promise<void> {",
    ),
    "extensions/memory-core/src/memory/manager-watch-resources.ts": (
        "export abstract class MemoryFileWatchResources {",
        "  protected markMemoryWatchDirty(watchPath?: string, stats?: MemoryWatchEventStats): void {",
        "  private scheduleWatchSync() {",
        "  async close(): Promise<void> {",
    ),
    "extensions/memory-core/src/memory/file-watcher.ts": (
        "export class MemoryFileWatcher extends MemoryFileWatchResources {",
        "  protected async startWatching(): Promise<void> {",
        '    watcher.on("add", markDirty);',
        '    watcher.on("change", markDirty);',
    ),
    "extensions/memory-core/src/memory/watch-settle.ts": (
        "export function recordMemoryWatchEventPath(",
        "export async function settleMemoryWatchEventPaths(",
    ),
    "extensions/memory-core/src/memory/manager-source-state.ts": (
        "export async function resolveMemorySourceFileEntries(params: {",
        "export function loadMemorySourceFileState(params: {",
    ),
    "extensions/memory-core/src/memory/manager-source-sync-ops.ts": (
        "export abstract class MemoryManagerSourceSyncOps extends MemoryManagerSessionSyncOps {",
        "  protected override async syncMemoryFiles(params: {",
        "  private async deleteStaleSourceFiles(",
    ),
    "extensions/memory-core/src/memory/manager-search-maintenance.ts": (
        "export async function runMemorySearchMaintenance<DirtyGeneration>(params: {",
        "      await manager.sync({ reason: params.reason });\n    } catch (err) {",
        "    await manager.close();",
    ),
    "extensions/memory-core/src/memory/manager-sync-outcome.ts": (
        "export class MemorySyncOutcomeLedger {",
        "  async track(operation: () => Promise<string | undefined | void>, active = false): Promise<void> {",
    ),
    "extensions/memory-core/src/memory/manager-keyword-retrieval.ts": (
        "export abstract class MemoryKeywordRetrieval extends MemoryProviderLifecycle {",
        "  protected async prepareKeywordSearch(",
    ),
    "extensions/memory-core/src/memory/temporal-decay.ts": (
        "function isEvergreenMemoryPath(filePath: string): boolean {",
        "export async function applyTemporalDecayToHybridResults<",
    ),
    "src/plugin-sdk/process-runtime.ts": (
        'export { WorkerTaskError, WorkerTaskPool } from "../infra/worker-task-pool.js";',
    ),
    "src/infra/worker-task-pool.ts": (
        "export class WorkerTaskPool<Input, Output> {",
        "  run(input: WorkerTaskInput<Input>, options: WorkerTaskOptions<Input>): Promise<Output> {",
    ),
    "src/infra/worker-task-pool-core.ts": (
        "export class WorkerTaskPoolCore<Input, Output> {",
        "  run(input: WorkerTaskInput<Input>, options: WorkerTaskOptions<Input>): Promise<Output> {",
    ),
    "src/infra/worker-task-pool.types.ts": (
        "export type WorkerTaskInput<Input> = Input | (() => Input | Promise<Input>);",
        "export type WorkerTaskOptions<Input> = {",
        "export type WorkerTaskPoolDispatch = {",
    ),
    "src/infra/sqlite-worker-broker-reply.ts": (
        "export function dispatchSqliteWorkerJob(",
        "export function receiveSqliteWorkerReply(",
        "    slot.worker.postMessage(\n      request,",
    ),
    "packages/memory-host-sdk/src/host/internal.ts": (
        "export async function listMemoryFiles(",
        "export async function buildFileEntry(",
    ),
    "extensions/memory-core/src/memory/manager-index-generation-lease.ts": (
        '  const admissionLocation = `${databasePath}.generation-writer.sqlite`;',
        '      `${databasePath}.generation-lock.sqlite`,',
    ),
    "extensions/memory-core/src/memory/manager-sqlite-lease.ts": (
        "export async function tryAcquireMemorySqliteLease(",
        "export async function acquireMemorySqliteWriterLease(",
        '      database.exec("BEGIN");',
        '      database.prepare("SELECT name FROM sqlite_schema LIMIT 1").get();',
        '          database.exec("ROLLBACK");',
    ),
}

ADDITIONAL_COMPILED_HASHES = {
    "dist/file-watcher-DSOr6bb7.mjs":
        "5b5f17389569a45c21bef26a47d5f53b38afb23fc856dcdb890b02ea8e76ba57",
    "dist/plugin-sdk/process-runtime.js":
        "06754f8351a898daf0d1e71c503d9fdd6c9f2f7a021c8afe767a32c120899ae7",
    "dist/worker-task-pool-BQlnRNqZ.mjs":
        "79ea82aa29baa5d72f600d5191ee4a3a0bd62fed0062cc8da96877cf334ccf2d",
    "dist/read-file-CH8NQLbp.mjs":
        "eec2ac48d772f0d2303c65bf3ea3a0866c42f864bf8e9c75f7307643044a4687",
    "dist/sqlite-worker-store-D6Kl0iv0.mjs":
        "d26499b6fabe956da5b29630aaf9061071b8d5ec0608c84076183588aa89f1df",
    "dist/manager-vector-warning-DcyxxT5h.mjs":
        "c08988b8823ef26532ebb3d82cc098b54577b02d7cf4e8e24ebefaa6cb22539d",
}

ADDITIONAL_COMPILED_ANCHORS = {
    "dist/extensions/memory-core/manager-runtime.js": (
        "\tmarkMemoryWatchDirty() {",
        "\tasync syncPublishedIndexInBackground(params) {",
        "async function runMemorySearchMaintenance(params) {",
        "\tasync prepareKeywordSearch(query, limit, options, sourceFilterList) {",
        "\tasync awaitManagerIdle() {",
        "\tasync closeOnce() {",
    ),
    "dist/file-watcher-DSOr6bb7.mjs": (
        "var MemoryFileWatcher = class extends MemoryFileWatchResources {",
        "\tmarkMemoryWatchDirty(watchPath, stats) {",
        "\tscheduleWatchSync() {",
        "async function settleMemoryWatchEventPaths(queue, signal) {",
    ),
    "dist/plugin-sdk/process-runtime.js": (
        'import { r as WorkerTaskError, t as WorkerTaskPool } from "../worker-task-pool-BQlnRNqZ.mjs";',
    ),
    "dist/worker-task-pool-BQlnRNqZ.mjs": (
        "var WorkerTaskPoolCore = class {",
        "var WorkerTaskPool = class {",
        "\t\treturn this.core.run(input, options);",
    ),
    "dist/read-file-CH8NQLbp.mjs": (
        "async function listMemoryFiles(workspaceDir, extraPaths, multimodal, onSkippedSymlinkRoot) {",
        "async function buildFileEntry(absPath, workspaceDir, multimodal) {",
    ),
    "dist/sqlite-worker-store-D6Kl0iv0.mjs": (
        "function dispatchSqliteWorkerJob(slot, job, onRejected) {",
        "function receiveSqliteWorkerReply(slot, reply, owner) {",
        "\t\tslot.worker.postMessage(request, request.operationAdmission ? [request.operationAdmission] : []);",
    ),
    "dist/manager-vector-warning-DcyxxT5h.mjs": (
        "async function tryAcquireMemorySqliteLease(location, mode) {",
        "async function acquireMemorySqliteWriterLease(location, signal) {",
        "async function acquireMemoryIndexReadGeneration(databasePath, signal) {",
        '\t\t\tdatabase.exec("BEGIN");',
        '\t\t\tdatabase.prepare("SELECT name FROM sqlite_schema LIMIT 1").get();',
        '\t\t\tdatabase.exec("ROLLBACK");',
    ),
    "dist/memory-search-CIhUURbE.mjs": (
        "export { resolveMemorySearchIndexConfig as n, resolveMemorySearchSyncConfig as r, "
        "resolveMemorySearchConfig as t };",
    ),
}

SOURCE_HASHES = {**IDENTITY_SOURCE_HASHES, **ADDITIONAL_SOURCE_HASHES}
SOURCE_ANCHORS = _merged_anchors(IDENTITY_SOURCE_ANCHORS, ADDITIONAL_SOURCE_ANCHORS)
COMPILED_HASHES = {**IDENTITY_COMPILED_HASHES, **ADDITIONAL_COMPILED_HASHES}
COMPILED_ANCHORS = _merged_anchors(IDENTITY_COMPILED_ANCHORS, ADDITIONAL_COMPILED_ANCHORS)

REQUIRED_MAIN_ARTIFACTS = tuple(dict.fromkeys((
    *IDENTITY_REQUIRED_MAIN_ARTIFACTS, *ADDITIONAL_COMPILED_HASHES,
)))
REQUIRED_WORKER_ARTIFACTS = tuple(dict.fromkeys((
    *IDENTITY_REQUIRED_WORKER_ARTIFACTS, "dist/sqlite-worker-store-D6Kl0iv0.mjs",
)))
REQUIRED_LOADED_ARTIFACTS = tuple(dict.fromkeys((
    *REQUIRED_MAIN_ARTIFACTS, *REQUIRED_WORKER_ARTIFACTS,
)))


class QuerySyncOutcomesBindingError(ValueError):
    """An original query-sync owner or published release artifact changed."""


def prepare_query_sync_outcomes_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate the closed profile without executing a Native memory owner."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        inherited = prepare_index_identity_boundaries_bindings(checkout, runtime_root)
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(
            runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False,
        )
        memory = "extensions/memory-core/src/memory/"
        chain = [
            *inherited["sourceImportLinks"],
            _named(sources, memory + "manager.ts", "./manager-search-maintenance.js",
                   ("runMemorySearchMaintenance",), kind="import", exact=True),
            _named(sources, memory + "manager-index-generation-lease.ts", "./manager-sqlite-lease.js",
                   ("acquireMemorySqliteWriterLease", "tryAcquireMemorySqliteLease"),
                   kind="import", exact=True),
            _named(sources, memory + "manager-sync-base.ts", "./manager-sync-outcome.js",
                   ("MemorySyncOutcomeLedger",), kind="import", exact=True),
            _named(sources, memory + "manager-sync-ops.ts", "./manager-source-sync-ops.js",
                   ("MemoryManagerSourceSyncOps",), kind="import", exact=True),
            _named(sources, memory + "manager-source-sync-ops.ts", "./manager-source-state.js",
                   ("loadMemorySourceFileState", "resolveMemorySourceFileEntries",
                    "resolveMemorySourceExistingHash"), kind="import", exact=True),
            _named(sources, memory + "manager-source-state.ts",
                   "openclaw/plugin-sdk/memory-core-host-engine-storage",
                   ("buildFileEntry", "listMemoryFiles", "runWithConcurrency"), kind="import"),
            _named(sources, "src/plugin-sdk/memory-core-host-engine-storage.ts",
                   "../../packages/memory-host-sdk/src/engine-storage.js",
                   ("buildFileEntry", "listMemoryFiles")),
            _named(sources, "packages/memory-host-sdk/src/engine-storage.ts", "./host/internal.js",
                   ("buildFileEntry", "listMemoryFiles")),
            _named(sources, memory + "manager-watch-ops.ts", "./file-watcher.js",
                   ("MemoryFileWatcher",), kind="import", exact=True),
            _named(sources, memory + "file-watcher.ts", "./manager-watch-resources.js",
                   ("MemoryFileWatchResources",), kind="import", exact=True),
            _named(sources, memory + "manager-watch-resources.ts", "./watch-settle.js",
                   ("MEMORY_WATCH_MAX_PATHS", "recordMemoryWatchEventPath",
                    "settleMemoryWatchEventPaths"), kind="import", exact=True),
            _named(sources, memory + "manager-search-orchestration.ts",
                   "./manager-keyword-retrieval.js", ("MemoryKeywordRetrieval",),
                   kind="import", exact=True),
            _named(sources, memory + "manager-keyword-retrieval.ts",
                   "./manager-cpu-worker-runtime.js", ("runMemoryKeywordSearch",), kind="import"),
            _named(sources, memory + "manager-keyword-retrieval.ts", "./temporal-decay.js",
                   ("applyTemporalDecayToHybridResults",), kind="import", exact=True),
            _named(sources, memory + "manager-cpu-worker-runtime.ts",
                   "openclaw/plugin-sdk/process-runtime", ("resolveRuntimeWorkerUrl", "WorkerTaskPool"),
                   kind="import", exact=True),
            _named(sources, "src/plugin-sdk/process-runtime.ts", "../infra/worker-task-pool.js",
                   ("WorkerTaskError", "WorkerTaskPool"), exact=True),
            _named(sources, "src/infra/worker-task-pool.ts", "./worker-task-pool-core.js",
                   ("WorkerTaskPoolCore",), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError,
            SearchContractRuntimeBindingError, IndexIdentityBoundariesBindingError) as error:
        raise QuerySyncOutcomesBindingError(
            "Query-sync declarations or original import links could not be authenticated."
        ) from error
    return {
        "kind": "official-release-query-sync-outcomes-owner",
        "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False,
        "constructorSkipped": False,
        "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence,
        "sourceImportLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoints": {
            "publicManagerFacade": {
                "path": "dist/extensions/memory-core/runtime-api.js",
                "export": "getMemorySearchManager",
            },
            "manager": {
                "path": "dist/extensions/memory-core/manager-runtime.js",
                "export": "MemoryIndexManager",
                "methods": ["get", "status", "search", "markMemoryWatchDirty",
                            "syncPublishedIndexInBackground", "prepareKeywordSearch", "close"],
            },
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemorySearchTool"},
            "workerPool": {
                "path": "dist/plugin-sdk/process-runtime.js",
                "export": "WorkerTaskPool", "methods": ["run"],
            },
            "searchConfig": {
                "path": "dist/memory-search-CIhUURbE.mjs",
                "export": "t", "originalBinding": "resolveMemorySearchConfig",
            },
            "readGeneration": {
                "path": "dist/manager-vector-warning-DcyxxT5h.mjs",
                "export": "p", "originalBinding": "acquireMemoryIndexReadGeneration",
                "observation": "Unchanged original lease SQL on owned generation-lock.sqlite "
                               "and generation-writer.sqlite connections only.",
            },
        },
        "requiredLoadedArtifactsByProfile": {OPERATION: list(REQUIRED_LOADED_ARTIFACTS)},
        "requiredMainArtifacts": list(REQUIRED_MAIN_ARTIFACTS),
        "requiredWorkerArtifacts": list(REQUIRED_WORKER_ARTIFACTS),
        "workerRequiredByProfile": {OPERATION: True},
        "fixtureBoundary": (
            "Real source files and declared filesystem changes precede genuine public tool queries. "
            "The original facade and tool resolve the same default owner. A declared original "
            "manager.markMemoryWatchDirty() notification supplies a dirty fact after mutation; "
            "it calls neither sync nor reindex and does not drive a watcher timer. Original "
            "search admission and immediately invoked original close own natural publication "
            "settlement. A fresh owner performs the reopened public query. Actual sync/watch "
            "settings, complete public envelopes and statuses, physical SQL and sources, "
            "worker dispatch/reply receipts and original closure stay in custody."
        ),
        "limits": [
            "Declaration authentication alone proves neither execution nor acceptance.",
            "Earlier family constants supply byte provenance only; earlier captures supply no credit.",
            "Worker imports alone establish no task dispatch, publication or query read generation.",
            "The explicit original dirty notification does not establish OS watcher delivery parity.",
            "Close joins already-admitted work and may cancel untriggered watcher timers; it does "
            "not flush future timers or guarantee a fresh first-query result.",
            "The source checkout, official compiled release, and actual runtime remain separate "
            "authorities; independent source-to-release build reproduction is not claimed.",
            "Provider-none results establish neither semantic/vector transport nor full status "
            "API identity, binary SQLite identity, or query-sync boundary-condition coverage.",
        ],
    }
