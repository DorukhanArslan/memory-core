"""Pinned source and published owners for the six forget/lineage diagnostics.

This authenticates bytes and call ownership only. It never invokes an original
business owner and does not claim a reproduced source build or full host scan.
"""
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {
    'extensions/memory-core/src/cli-index-search.runtime.ts': '1cb313da8f2dd7597f03aafb879cdc49d969deed18ae7bfd6fdd1a45e5a9280a',
    'extensions/memory-core/src/memory-forget.ts': '6f50711f972a369e16b7eed957826ee49d575ce50f06642d517612d352aeb475',
    'extensions/memory-core/src/memory-forget-curated-writes.ts': '8e4e8f2ed6f74f4e796824f041334cf6074b234fa827dee5b43ec4ffeabdd556',
    'extensions/memory-core/src/memory-forget-index-sources.ts': 'b7af323286b6a8a17f400998db85a4f6e3c0b6a8ea5c2677651966c928298cd9',
    'extensions/memory-core/src/memory-entry-origins.ts': 'd84877d05b1621d554260c23b3d4678eb184ffce9ad7fd0255abee67ac3ad0d7',
    'extensions/memory-core/src/memory-session-tombstones.ts': '0ebc12b61cc4d27f868331a68f709968c1fa0ea9a4fe4a1f8e7ec870a350fe2d',
    'extensions/memory-core/src/memory-workspace-lock.ts': '557bf3bdb03a8139af1c3fe40d106b3fb74e8ad20c30969bd888a7bccf25beb2',
    'extensions/memory-core/src/short-term-promotion-memory-write.ts': '73efe7aded716c4ad1dce87230ef0cd538737491190168b1769765dd8ad092e5',
    'src/plugin-sdk/memory-core-host-engine-sessions.ts': 'e05da58485856c557ae7e37e97dbffba0da0abe8b72d355261ee784d1db12f7b',
    'src/plugin-sdk/session-store-runtime.ts': '2d98e36a3e04f61a1809b60ac4ffaeb538de0c99ce111b38c8dea2726185bc11',
    'src/config/sessions/session-accessor.sqlite-transcript-write.ts': '4e6ee07463e2cd5e1064400535dc332d7c0d2c761997eefb3b59dea6d33a1b0a',
    'src/config/sessions/session-accessor.sqlite-participants.native.ts': '4dafb7dea69bd122b39c650f4e801d5c79fcc207476217bf8a99dfdbf3efe4ff',
    'packages/memory-host-sdk/src/host/session-transcript-corpus.ts': '8bc7c3f008e3b4d9c04da985cec647b830c54c2c205f15d4ff834e202585dfb7',
    'extensions/memory-core/src/session-ingestion.ts': 'a220ead109095fef8994435b2fe6c51667190574f2ab25d07919bdf1257a8af2',
    'extensions/memory-core/src/short-term-promotion-record.ts': 'b8d168519af14de5ae793d6738d3a86d51e41cdcc12cbd5b22fb174ba108d8c7',
    'extensions/memory-core/src/short-term-promotion-store.ts': '556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84',
    'extensions/memory-core/src/dreaming-consolidation-artifacts.ts': '3ab27880336927e05100efe3e320d7909c5cc42cb3b5abae147fc9755a4ef2d0',
    'extensions/memory-core/src/dreaming-ingestion-state.ts': '1d4fca365fa88ef871766adccb85bface2aaff04e4ed54ce996f187ae5150905',
    'extensions/memory-core/src/dreaming-state.ts': 'b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
}
SOURCE_ANCHORS = {
    'extensions/memory-core/src/cli-index-search.runtime.ts': ('export async function runMemoryForget(opts: MemoryForgetCommandOptions) {',),
    'extensions/memory-core/src/memory-forget.ts': ('export async function forgetMemoryEntries(params: MemoryForgetParams): Promise<MemoryForgetReport> {', 'function scrubMemoryContent(params: {'),
    'extensions/memory-core/src/memory-forget-curated-writes.ts': ('export function collectTranscriptWrites(params: {',),
    'extensions/memory-core/src/memory-forget-index-sources.ts': ('export async function planMemoryIndex(params: {',),
    'extensions/memory-core/src/memory-entry-origins.ts': ('export function recordMemoryEntryOrigins(params: {', 'export function listMemorySessionTombstones(params: {'),
    'extensions/memory-core/src/memory-session-tombstones.ts': ('export function ensureMemorySessionTombstones(db: DatabaseSync): void {',),
    'extensions/memory-core/src/memory-workspace-lock.ts': ('export async function withMemoryWorkspaceLock<T>(',),
    'extensions/memory-core/src/short-term-promotion-memory-write.ts': ('export async function commitMemoryContent(',),
    'src/plugin-sdk/memory-core-host-engine-sessions.ts': ('export function resolveMemorySessionTargets(params: MemorySessionSelectors): MemorySessionTarget[] {',),
    'src/plugin-sdk/session-store-runtime.ts': ('export async function upsertSessionEntry(params: UpsertSessionEntryParams): Promise<void> {',),
    'src/config/sessions/session-accessor.sqlite-transcript-write.ts': ('export function replaceTranscriptEventsSync(',),
    'src/config/sessions/session-accessor.sqlite-participants.native.ts': ('export function recordSessionParticipant(',),
    'packages/memory-host-sdk/src/host/session-transcript-corpus.ts': ('export async function listSessionTranscriptCorpusEntriesForAgent(',),
    'extensions/memory-core/src/session-ingestion.ts': ('export function sessionIngestionSourceFromCorpus(', 'export function sessionExclusionReason('),
    'extensions/memory-core/src/short-term-promotion-record.ts': ('export async function recordGroundedShortTermCandidates(params: {',),
    'extensions/memory-core/src/short-term-promotion-store.ts': ('export async function readStore(', 'export async function writeStore('),
    'extensions/memory-core/src/dreaming-consolidation-artifacts.ts': ('export function readMemoryPreimages(workspaceDir: string) {',),
    'extensions/memory-core/src/dreaming-ingestion-state.ts': ('export async function readSessionIngestionState(', 'export async function writeSessionIngestionState('),
    'extensions/memory-core/src/dreaming-state.ts': ('export async function writeMemoryCoreWorkspaceEntries(',),
}

COMPILED_HASHES = {
    'dist/cli.runtime-CVRN4xUp.mjs': '8005b01a0e308c8bb984349a985c2a605fad8fa44431a567d7e73bc8635bfdcd',
    'dist/runtime-BC29JSZp.mjs': '0825c97c0d79ef2049599a3a7ff0027e1803dd96d4e0ca05a9b7eb38f748e2da',
    'dist/plugin-sdk/config-runtime.js': 'ca8ea03ec6a8eeb48c4f300f7a88171aba943e6999a40791205d0027bd1d2a18',
    'dist/extensions/memory-core/runtime-api.js': '520c6cc05e74399c910425488cacd52867bb587434a36d33c8b90d11326d75ec',
    'dist/plugin-sdk/plugin-state-store-runtime.js': '6e34e2530c913403a15ce4f93a3c8fdfbbb7caaa9ea191faa5993c6b469f1e61',
    'dist/plugin-sdk/session-store-runtime.js': '495b19c73cb71dce90914b28d0c9492da41622fbdfb7a4966885ba7f83cbbba2',
    'dist/session-store-runtime-C3lQUqXM.mjs': '42c91a431b20934055e124edf556bffdb57e203615f814fd6c6067654c5caf20',
    'dist/session-accessor-CiKKTlbe.mjs': '287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a',
    'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
    'dist/session-sharing-store.native-BimL-D2p.mjs': 'aebaab26efa1bd90032da848404ccf17715faf39b4b1c525bf6aefe14dcfb915',
    'dist/memory-core-host-engine-sessions-D3OZsg6m.mjs': '705191a0ebf383e5b5aaf70dae18a7fa7c6030c4c4be7d841483cfe2567632c8',
    'dist/memory-entry-origins-BCQSIB3X.mjs': '35506e30b05eb6ebc688b90688b449d06c2a01ffabb0348c1eaa1b1f9d0fd37d',
    'dist/openclaw-agent-db.paths-Dv3PPTNK.mjs': '4e27befc30963b354b9d1098832c6d8202a54cd40d1b188908f89e7321102945',
    'dist/openclaw-state-db.paths-rJI64Ab5.mjs': '8cecbc669117d451fb3681898c056714e463437f1c6ada6a537609864c0c4214',
    'dist/dreaming-state-VYUvbU-n.mjs': '8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
    'dist/short-term-promotion-store-B6T388Bo.mjs': '704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8',
    'dist/dreaming-ingestion-state-licbtf_y.mjs': '91904fa3331423770d712029fa2863d0e30279a33d8b8b9486ab630281ff31e3',
    'dist/short-term-promotion-MX1vHJuE.mjs': 'be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da',
    'dist/session-files-DVVT4Ngb.mjs': '0a933051a4cf16dd7f5ddb15df3df6d5c950cd1a09b7fd2729d8c86e54842dc9',
    'dist/session-ingestion-Dy5uAq-_.mjs': 'c0dff0210ad2ddcc662224271200840bf99a8e4edbebd9291adf6adaa881ccf3',
    'dist/short-term-promotion-record-DrLa1fiO.mjs': '26a083e3c17cd6512af9785266c7bdffe459cd02591be4127004efe7eb8887c7',
    'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': 'ece2b2b08f3e03c8ddb3dc70e29265f23c6b3df52e37e981e79a6bbd424a5a84',
    'dist/openclaw-state-db-cache-IdIaBoUp.mjs': 'e0cddcf3fa25fc081f0edb4cc9d31c4d29dabd1206dc440dd239f1bf665a543e',
}
COMPILED_ANCHORS = {
    'dist/cli.runtime-CVRN4xUp.mjs': ('async function runMemoryForget(opts) {', 'async function forgetMemoryEntries(params) {'),
    'dist/runtime-BC29JSZp.mjs': ('writeJson: (value, space = 2) => {',),
    'dist/plugin-sdk/config-runtime.js': ('export { GROUP_POLICY_BLOCKED_LABEL,',),
    'dist/extensions/memory-core/runtime-api.js': ('export { auditDreamingArtifacts,',),
    'dist/plugin-sdk/plugin-state-store-runtime.js': ('export { createPluginStateKeyedStore,',),
    'dist/plugin-sdk/session-store-runtime.js': ('upsertSessionEntry };',),
    'dist/session-store-runtime-C3lQUqXM.mjs': ('async function upsertSessionEntry(params) {',),
    'dist/session-accessor-CiKKTlbe.mjs': ('export { MAX_SESSION_PARTICIPANTS,',),
    'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function replaceTranscriptEventsSync(scope, events) {',),
    'dist/session-sharing-store.native-BimL-D2p.mjs': ('function recordSessionParticipant(scope, params) {',),
    'dist/memory-core-host-engine-sessions-D3OZsg6m.mjs': ('function resolveMemorySessionTargets(params) {',),
    'dist/memory-entry-origins-BCQSIB3X.mjs': ('function recordMemoryEntryOrigins(params) {', 'function recordMemorySessionTombstonesInDatabase(db, params) {'),
    'dist/openclaw-agent-db.paths-Dv3PPTNK.mjs': ('function resolveOpenClawAgentSqlitePath(options) {',),
    'dist/openclaw-state-db.paths-rJI64Ab5.mjs': ('function resolveOpenClawStateSqlitePath(env = process.env) {',),
    'dist/dreaming-state-VYUvbU-n.mjs': ('async function writeMemoryCoreWorkspaceEntries(params) {',),
    'dist/short-term-promotion-store-B6T388Bo.mjs': ('async function readStore(workspaceDir, nowIso) {',),
    'dist/dreaming-ingestion-state-licbtf_y.mjs': ('async function readSessionIngestionState(workspaceDir) {',),
    'dist/short-term-promotion-MX1vHJuE.mjs': ('function readMemoryPreimages(workspaceDir) {',),
    'dist/session-files-DVVT4Ngb.mjs': ('async function listSessionTranscriptCorpusEntriesForAgent(agentId, options = {}) {',),
    'dist/session-ingestion-Dy5uAq-_.mjs': ('function sessionExclusionReason(source, policy, forgottenSessionIds) {',),
    'dist/short-term-promotion-record-DrLa1fiO.mjs': ('async function recordGroundedShortTermCandidates(params) {',),
    'dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs': ('async function closeOpenClawAgentDatabasesAsync(rootPath) {',),
    'dist/openclaw-state-db-cache-IdIaBoUp.mjs': ('async function closeOpenClawStateDatabaseAsync(options) {',),
}

REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED_HASHES)
GENUINE_HELPER_EXPORTS = {
    "dist/cli.runtime-CVRN4xUp.mjs": ("runMemoryForget",),
    "dist/plugin-sdk/session-store-runtime.js": ("upsertSessionEntry", "resolveStorePath"),
    "dist/session-accessor-CiKKTlbe.mjs": ("replaceTranscriptEventsSync", "loadTranscriptEventsSync"),
    "dist/session-sharing-store.native-BimL-D2p.mjs": ("i",),
    "dist/memory-entry-origins-BCQSIB3X.mjs": ("a", "n", "r"),
    "dist/short-term-promotion-store-B6T388Bo.mjs": ("a", "l", "r", "c"),
    "dist/dreaming-ingestion-state-licbtf_y.mjs": ("l", "d"),
    "dist/short-term-promotion-MX1vHJuE.mjs": ("o",),
    "dist/session-files-DVVT4Ngb.mjs": ("l",),
    "dist/session-ingestion-Dy5uAq-_.mjs": ("u", "l"),
    "dist/short-term-promotion-record-DrLa1fiO.mjs": ("r", "n"),
}


def prepare_forget_lineage_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Verify exact original owner bytes without importing or running them."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Forget lineage diagnostics require the exact pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    compiled, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    source_specs = (
        ("extensions/memory-core/src/cli-index-search.runtime.ts", "./memory-forget.js", ("forgetMemoryEntries",)),
        ("extensions/memory-core/src/memory-forget.ts", "./memory-entry-origins.js", ("listMemoryEntryOrigins", "recordMemorySessionTombstonesInDatabase", "deleteMemoryEntryOriginsInDatabase")),
        ("extensions/memory-core/src/memory-forget.ts", "openclaw/plugin-sdk/memory-core-host-engine-sessions", ("resolveMemorySessionTargets", "listSessionTranscriptCorpusEntriesForAgent")),
        ("extensions/memory-core/src/memory-forget.ts", "./dreaming-ingestion-state.js", ("readSessionIngestionState", "writeSessionIngestionState")),
        ("extensions/memory-core/src/dreaming-consolidation-artifacts.ts", "./dreaming-state.js", ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries")),
    )
    # The official release inlines forgetMemoryEntries in the CLI artifact;
    # its complete bytes retain selectors, tombstones, artifact rewrites and errors.
    return {
        "schemaVersion": 1, "kind": "official-release-forget-lineage-owners",
        "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                              for module, specifier, names in source_specs],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "genuineHelperExports": {key: list(value) for key, value in GENUINE_HELPER_EXPORTS.items()},
        "forgetCliArtifact": "dist/cli.runtime-CVRN4xUp.mjs",
        "forgetOwnerInlinedInCliArtifact": True,
        "provider": "none", "fullHostBackfillScanExercised": False,
        "replayScope": "Actual session admission and grounded candidate persistence owners",
        "reopenScope": "Close original database owners and reopen through original readers in one process",
        "clockFixture": {"owner": "node:test", "apis": ["Date"]},
        "stdoutObservation": "Capture full original CLI stdout and forward unchanged bytes to stderr",
        "acceptancePointsAwarded": 0, "covers": [],
    }
