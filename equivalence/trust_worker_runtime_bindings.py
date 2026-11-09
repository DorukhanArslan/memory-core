"""Authenticate the actual source-worker snapshot and original bounded retry owner.

The release remains separately authenticated as published artifacts. An observed
worker reply is a scheduling fixture, never a replacement result or retry owner.
"""
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {
    "packages/memory-host-sdk/src/host/session-files.ts": "d184bf1a1b098a02b08ed131321fb47d6caf5bee9e1cc6d88751502dbb8761ee",
    "packages/memory-host-sdk/src/host/openclaw-runtime-io.ts": "78271920a7acd0d5e905317de56807b889567a07707fb87074c646a25464129e",
    "packages/memory-host-sdk/src/host/openclaw-runtime-session.ts": "51fed14e0695f0caf97d1b3296ed5cdba7b8867bca4de8611509af68fce14eed",
    "src/logging/redact.ts": "ecdfdb1e0f4b0f2aa3eb54aad574bb5375ae8da78539ad937b34ba02dd170e7b",
    "src/logging/secret-redaction-registry.ts": "217d789ec4e6b3896dc7c647d33a8a2eed2df4b754fa0abf93a577296863f689",
    "src/config/sessions/session-transcript-read-worker-runtime.ts": "7ebf8c229238a6825100d50dd89ea3973494d8ad76662d35f59f0ea70d17ae07",
    "src/config/sessions/session-transcript.worker.ts": "7e50bf974d3fd7b694b4d29007df6cfa896ae8f8bb395911e7b6b1e78008ea03",
    "src/infra/worker-task-pool-core.ts": "1cda75ab8e4a9df63b96174a701a82080c7c41fa7fe6e98a0d13941af7660727",
    "src/infra/worker-task-server.ts": "3ee977b63028f42aa62b62a3fd3628e8afc5f5b614ca65e65d0ca26b7669e523",
    "src/infra/runtime-process-entrypoints.ts": "23576e3d35022ff7d7c4b4b163587d826b7e2b96b7e84533f8ac92189c7f3752",
    "src/infra/runtime-worker-url.ts": "9b694a778a84725e989ad2380195557993afbf25dc97e64112f7a65b2a2087e0",
    "src/infra/worker-cpu.ts": "41e8c54a90cb84caf392f0d7a5dfdceeef2fe5aa75cbdb85f5c32e03f803d256",
}
COMPILED_HASHES = {
    "dist/session-files-DVVT4Ngb.mjs": "0a933051a4cf16dd7f5ddb15df3df6d5c950cd1a09b7fd2729d8c86e54842dc9",
    "dist/openclaw-runtime-session-cZ0ZaiUL.mjs": "c180ffa73e9e9c8a4fffdc5f4373e57ceaffc74939c19e20c17ea302a3487ff5",
    "dist/redact-BCoakatc.mjs": "17028994a6670b397e171921efdcd01f00c1b8d4058db5216d62f976e74a65d6",
    "dist/secret-redaction-registry-b2B9lcfy.mjs": "432fe8ecb1999ef09de6a40878fcedf717eb570ec024a75d77f9e5667cd62f24",
    "dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs": "3764066f2cb47318cff9e130682c3813f43e11d4990f88e8c43a42b3ca8bfbb9",
    "dist/config/sessions/session-transcript.worker.js": "30bee98b7f19e310f35e9e2f4fa29c48467daf05fc14b6209d0518b347c7610e",
    "dist/worker-task-pool-BQlnRNqZ.mjs": "79ea82aa29baa5d72f600d5191ee4a3a0bd62fed0062cc8da96877cf334ccf2d",
    "dist/worker-task-server-CF3aSh39.mjs": "0528de35a64cfead2597bcf0d1db768d3c9339971e10f013612756ff1a0ca167",
    "dist/runtime-process-entrypoints-Bh4reDp0.mjs": "d8031c4fff5902dc7c99a70daf2d4c8f1ce809db149e029d77c0dac2873dfc4a",
    "dist/runtime-worker-url-S0NIVxUR.mjs": "49585b6cc537babf6c8e4f795c709e3b109af37b3df46161afcf593b506a136b",
    "dist/worker-cpu-EKuz4_X-.mjs": "ba8fc5f65b7ad1853164907b14579600627b67c22c9a6a9be64de7ff0b5fb506",
}
SOURCE_ANCHORS = {
    "packages/memory-host-sdk/src/host/session-files.ts": (
        "export async function buildSessionEntry(", "for (let attempt = 0; attempt < 2; attempt++) {",
        '"Session transcript redaction changed during preparation; retry the operation.",'),
    "packages/memory-host-sdk/src/host/openclaw-runtime-io.ts": ("  captureSensitiveTextRedactionSnapshot,",),
    "packages/memory-host-sdk/src/host/openclaw-runtime-session.ts": ("export async function prepareSessionEntryInWorker(",),
    "src/logging/redact.ts": ("export function captureSensitiveTextRedactionSnapshot()", "export function createSensitiveTextRedactor("),
    "src/logging/secret-redaction-registry.ts": ("export function getSecretRedactionRegistryRevision()",),
    "src/config/sessions/session-transcript-read-worker-runtime.ts": ("export async function prepareSessionEntryInWorker(",),
    "src/config/sessions/session-transcript.worker.ts": ("            createSensitiveTextRedactor(request.redaction),",),
    "src/infra/worker-task-pool-core.ts": ("export class WorkerTaskPoolCore<Input, Output>", "  private receive(slot: Slot<Input, Output>, message: unknown): void {"),
    "src/infra/worker-task-server.ts": ("export function serveOwnedWorkerTasks<Output>(",),
    "src/infra/runtime-process-entrypoints.ts": ('sessionTranscript: runtimeProcessEntrypoint("config/sessions/session-transcript.worker")',),
    "src/infra/runtime-worker-url.ts": ("export function resolveRuntimeWorkerUrl(params:",),
    "src/infra/worker-cpu.ts": ("export function createCpuTrackedWorker(...args:",),
}
COMPILED_ANCHORS = {
    "dist/session-files-DVVT4Ngb.mjs": ("async function buildSessionEntry(absPath, opts = {}) {", "for (let attempt = 0; attempt < 2; attempt++) {"),
    "dist/openclaw-runtime-session-cZ0ZaiUL.mjs": ("async function prepareSessionEntryInWorker(...args) {",),
    "dist/redact-BCoakatc.mjs": ("function captureSensitiveTextRedactionSnapshot()", "function createSensitiveTextRedactor(snapshot)"),
    "dist/secret-redaction-registry-b2B9lcfy.mjs": ("function getSecretRedactionRegistryRevision()",),
    "dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs": ("async function prepareSessionEntryInWorker(absPath, options, redaction) {",),
    "dist/config/sessions/session-transcript.worker.js": ("createSensitiveTextRedactor(request.redaction)",),
    "dist/worker-task-pool-BQlnRNqZ.mjs": ("var WorkerTaskPoolCore = class {",),
    "dist/worker-task-server-CF3aSh39.mjs": ("function serveOwnedWorkerTasks(handler, options = {}) {",),
    "dist/runtime-process-entrypoints-Bh4reDp0.mjs": ('sessionTranscript: runtimeProcessEntrypoint("config/sessions/session-transcript.worker")',),
    "dist/runtime-worker-url-S0NIVxUR.mjs": ("function resolveRuntimeWorkerUrl(params) {",),
    "dist/worker-cpu-EKuz4_X-.mjs": ("function createCpuTrackedWorker(...args) {",),
}


def prepare_trust_worker_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Worker redaction diagnostics require the exact pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    specs = [
        ("packages/memory-host-sdk/src/host/session-files.ts", "./openclaw-runtime-io.js", ("captureSensitiveTextRedactionSnapshot", "getSecretRedactionRegistryRevision")),
        ("packages/memory-host-sdk/src/host/session-files.ts", "./openclaw-runtime-session.js", ("prepareSessionEntryInWorker",)),
        ("src/config/sessions/session-transcript-read-worker-runtime.ts", "../../infra/worker-task-pool.js", ("WorkerTaskPool",)),
        ("src/config/sessions/session-transcript.worker.ts", "../../infra/worker-task-server.js", ("serveOwnedWorkerTasks",)),
        ("src/infra/worker-task-pool-core.ts", "./worker-cpu.js", ("createCpuTrackedWorker",)),
        ("src/infra/worker-cpu.ts", "node:worker_threads", ("Worker",)),
    ]
    return {"kind": "official-release-session-redaction-worker-owners", "referenceCommit": REFERENCE_COMMIT,
            "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
            "sourceBindings": source_evidence, "compiledBindings": compiled,
            "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                                  for module, specifier, names in specs],
            "expectedWorkerArtifact": "dist/config/sessions/session-transcript.worker.js",
            "requiredTaskKind": "session-entry", "originalParentRetryLimit": 2,
            "fixtureCut": "Actual successful worker reply, before the unchanged original pool listener accepts it",
            "allowedFixtureMutation": "Register a literal synthetic secret through the genuine parent registry",
            "workerInputOrResultReplacementAllowed": False, "parentRetryReplacementAllowed": False,
            "covers": []}
