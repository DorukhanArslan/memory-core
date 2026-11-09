"""Original transcript publication and scheduling owners for the new profile.

The policy capability stays separate. Pins authenticate declarations only; real
post-commit notifications, listener delivery and persisted source generations
must be established by the publication evidence guard. No source build, default
turn barrier or original full embedded host execution is asserted here.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.host_restart_bindings import REFERENCE_COMMIT, _owners
from equivalence.host_restart_policy_bindings import prepare_host_restart_policy_bindings

PUBLICATION_OPERATION = "host-restart-publication-runtime"

SOURCE_HASHES = {'src/plugin-sdk/session-transcript-runtime.ts': 'f6e5a66d91b440b65d5c1c355bf0dca9f5669c53e9a423a5d8abbecc4f9d661a',
 'src/config/sessions/session-accessor.transcript-turn.ts': 'a46005a0a1862c3ce06d5dc6067a817a64491a9ad94aa236b74b662b47ea720f',
 'src/config/sessions/session-accessor.sqlite-transcript-turn.ts': 'c199589846efef183c3ed3419aff7d98f96511c7b3f4b633c24a5dedf3f06161',
 'src/config/sessions/session-accessor.sqlite-transcript-sequences.ts': 'ee961a019eee905e1191c742b2ef8fc5dd085b2b1c50aed244d1005353931ed5',
 'src/config/sessions/session-accessor.transcript-target.ts': 'fa62e1f5a025b008fe4552f0b54dfa9586c0f4aee76719aea9031d8a6725db58',
 'src/config/sessions/session-accessor.sqlite-events.ts': 'd224e64572b3ad144ea40f238c33ba621c2b047bb321483e165866f9256c5a9a',
 'src/sessions/transcript-events.ts': 'd30ec2f89cd11b8df52adf3bb4078ddd38ce322deea3fd2cdfabb0344b497373',
 'extensions/memory-core/src/memory/manager-session-sync-ops.ts': '3af5c8c2ef2aca054c3d34190941855ab76374c65cd5d6908b6744fb34ea0a4f',
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': '04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55',
 'extensions/memory-core/src/memory/manager-session-sync-state.ts': 'ee190fecc3c4d8853ef9cf2aba95f786aa144d2a599818533202200a515c96d6',
 'extensions/memory-core/src/memory/manager-session-reindex.ts': 'acac4cbb8832784bc436b6dc975b5e4d68e0666af06a73ee0db53c878137f7e6'}

SOURCE_ANCHORS = {'src/plugin-sdk/session-transcript-runtime.ts': ('export async function '
                                                  'appendSessionTranscriptMessageByIdentityStrict<TMessage>(',
                                                  'export async function '
                                                  'publishSessionTranscriptUpdateByIdentity('),
 'src/config/sessions/session-accessor.transcript-turn.ts': ('export async function '
                                                             'persistSessionTranscriptTurn(',
                                                             'async function publishTranscriptTurnUpdate('),
 'src/config/sessions/session-accessor.sqlite-transcript-turn.ts': ('export async function '
                                                                    'appendExpectedSessionTranscriptTurn(',),
 'src/config/sessions/session-accessor.sqlite-transcript-sequences.ts': ('export function '
                                                                         'readCommittedTranscriptMessageSequence(',
                                                                         'export function '
                                                                         'rememberCommittedTranscriptMessageSequencesInTransaction('),
 'src/config/sessions/session-accessor.transcript-target.ts': ('export function '
                                                               'bindSessionTranscriptStoreScope<',
                                                               'export async function '
                                                               'resolveSessionTranscriptRuntimeTarget('),
 'src/config/sessions/session-accessor.sqlite-events.ts': ('export async function publishTranscriptUpdate(',),
 'src/sessions/transcript-events.ts': ('export function onInternalSessionTranscriptUpdate(',
                                       'export function emitSessionTranscriptUpdate('),
 'extensions/memory-core/src/memory/manager-session-sync-ops.ts': ('const SESSION_DIRTY_DEBOUNCE_MS = 5000;',
                                                                   '  protected ensureSessionListener() {',
                                                                   '  protected async '
                                                                   'runSessionStartupCatchup(): '
                                                                   'Promise<string[]> {',
                                                                   '  private async '
                                                                   'processSessionUpdateBatch(): '
                                                                   'Promise<void> {'),
 'extensions/memory-core/src/memory/manager-search-orchestration.ts': ('  protected '
                                                                       'claimSessionWarmSync(sessionKey?: '
                                                                       'string): boolean {',
                                                                       'const trackedSearchSync = '
                                                                       'this.syncPublishedIndexInBackground({ '
                                                                       'reason: "search" })'),
 'extensions/memory-core/src/memory/manager-session-sync-state.ts': ('export function '
                                                                     'resolveMemorySessionStartupState(',),
 'extensions/memory-core/src/memory/manager-session-reindex.ts': ('export function '
                                                                  'shouldSyncSessionsForReindex(',
                                                                  'if (reason === "session-start" || reason '
                                                                  '=== "watch") {')}

COMPILED_HASHES = {'dist/plugin-sdk/session-transcript-runtime.js': '6b1fc98f8770ffe7d994bbd3f6a616ba5ee08910403534e14cc44c13cd84fe17',
 'dist/session-transcript-runtime-Bo5y_sts.mjs': '02c9381d6aa5495a0814dd11cfaf6b5ed9249a5e3064633d7ac396dd1447c398',
 'dist/session-accessor-WMUIp1Kx.mjs': 'ee241de4a74bc1d44529b4c8ddba311ba1285147bdf965c1cb64b253d502e131',
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': '3dd200872aa5e053a0ab9342b8a107af7fd6a4b1b9a490d2052d55742040c951',
 'dist/session-accessor.transcript-target-vG-nGtYV.mjs': '01158efffa0ae0a91dea780bccaf63d22a65ff73f65ef8a24cbc0770910dc51f',
 'dist/session-history-eviction-CWtTNxrd.mjs': 'c6d625989a01aebe776d593d3b933782bb821f58c34c977d3fd4e472ad9e3cb6',
 'dist/transcript-events-Ce9wKss8.mjs': '3c002577a318257953fa5b1ba10cd16b83c99fca869e4058469a4f274a897c51',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/manager-vector-warning-DcyxxT5h.mjs': 'c08988b8823ef26532ebb3d82cc098b54577b02d7cf4e8e24ebefaa6cb22539d'}

COMPILED_ANCHORS = {'dist/plugin-sdk/session-transcript-runtime.js': ('export { appendAssistantMirrorMessageByIdentity, '
                                                   'appendSessionTranscriptMessageByIdentity, '
                                                   'appendSessionTranscriptMessageByIdentityStrict,',),
 'dist/session-transcript-runtime-Bo5y_sts.mjs': ('async function '
                                                  'appendSessionTranscriptMessageByIdentityStrict(params) {',
                                                  'async function '
                                                  'publishSessionTranscriptUpdateByIdentity(params) {'),
 'dist/session-accessor-WMUIp1Kx.mjs': ('async function persistSessionTranscriptTurn(scope, options) {',
                                        'async function appendExpectedSessionTranscriptTurn(scope, options) '
                                        '{',
                                        'async function publishTranscriptTurnUpdate(params) {'),
 'dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs': ('function '
                                                                'readCommittedTranscriptMessageSequence(message) '
                                                                '{',
                                                                'function '
                                                                'rememberCommittedTranscriptMessageSequencesInTransaction(database, '
                                                                'sessionId, messages) {'),
 'dist/session-accessor.transcript-target-vG-nGtYV.mjs': ('function bindSessionTranscriptStoreScope(scope, '
                                                          'config) {',
                                                          'async function '
                                                          'resolveSessionTranscriptRuntimeTarget(scope, '
                                                          'config, options = {}) {'),
 'dist/session-history-eviction-CWtTNxrd.mjs': ('async function publishTranscriptUpdate(scope, update = {}) '
                                                '{',),
 'dist/transcript-events-Ce9wKss8.mjs': ('function onInternalSessionTranscriptUpdate(listener) {',
                                         'function emitSessionTranscriptUpdate(update) {'),
 'dist/extensions/memory-core/manager-runtime.js': ('const SESSION_DIRTY_DEBOUNCE_MS = 5e3;',
                                                    '\tensureSessionListener() {',
                                                    '\tasync runSessionStartupCatchup() {',
                                                    '\tasync processSessionUpdateBatch() {',
                                                    '\tclaimSessionWarmSync(sessionKey) {',
                                                    'function shouldSyncSessionsForReindex(params) {'),
 'dist/manager-vector-warning-DcyxxT5h.mjs': ('function resolveMemorySessionStartupState(params) {',)}


STRICT_APPEND_ARTIFACTS = (
    "dist/plugin-sdk/session-transcript-runtime.js",
    "dist/session-transcript-runtime-Bo5y_sts.mjs",
    "dist/session-accessor-WMUIp1Kx.mjs",
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.transcript-target-vG-nGtYV.mjs",
)
NOTIFICATION_ARTIFACTS = (
    "dist/transcript-events-Ce9wKss8.mjs",
)
DIRECT_PUBLICATION_ARTIFACTS = (
    "dist/session-history-eviction-CWtTNxrd.mjs",
    *NOTIFICATION_ARTIFACTS,
)
SCHEDULER_ARTIFACTS = (
    "dist/extensions/memory-core/manager-runtime.js",
    "dist/manager-vector-warning-DcyxxT5h.mjs",
)
ADDITIONAL_REQUIRED_HOST_ARTIFACTS = tuple(dict.fromkeys((
    *STRICT_APPEND_ARTIFACTS, *NOTIFICATION_ARTIFACTS, *SCHEDULER_ARTIFACTS,
)))

# These original full-host declarations explain the missing lower-level
# caller obligation. This profile authenticates them without claiming that
# guardSessionManager or the complete embedded runner executes.
FULL_HOST_DECLARATION_HASHES = {
    "src/agents/session-tool-result-guard.ts":
        "174aa005b10c2b55dcbe36152843e8da31cdcc9d8bfe4e4e38efbc34a3b74e90",
    "src/agents/embedded-agent-runner/run/attempt-session-prepare.ts":
        "e32977bad2203fb5683cb07b859346c7658ebfd19fd12e17c64e1cb185ce4e3b",
}
FULL_HOST_DECLARATION_ANCHORS = {
    "src/agents/session-tool-result-guard.ts": ("void publishTranscriptUpdate(sessionTarget, {",),
    "src/agents/embedded-agent-runner/run/attempt-session-prepare.ts": (
        "const sessionManager = guardSessionManager(unguardedSessionManager, {",),
}


def prepare_host_restart_publication_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate exact post-commit owners without issuing notifications."""
    checkout, runtime_root = Path(checkout).absolute(), Path(runtime_root).absolute()
    original = prepare_host_restart_policy_bindings(checkout, runtime_root)
    sources = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    full_host = _owners(checkout, FULL_HOST_DECLARATION_HASHES,
                        FULL_HOST_DECLARATION_ANCHORS, committed=True)
    return {
        "kind": "official-release-host-restart-publication-owners",
        "operation": PUBLICATION_OPERATION, "referenceCommit": REFERENCE_COMMIT,
        "policyHostOwners": original, "additionalSourceBindings": sources,
        "additionalCompiledBindings": compiled,
        "authenticatedOnlyFullHostDeclarations": full_host,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceExecutionPermitted": False, "covers": [], "acceptancePointsAwarded": 0,
        "requiredLoadedArtifacts": list(ADDITIONAL_REQUIRED_HOST_ARTIFACTS),
        "strictAppendEntrypoint": {"path": STRICT_APPEND_ARTIFACTS[0],
            "export": "appendSessionTranscriptMessageByIdentityStrict", "updateMode": "inline"},
        "explicitPublicationEntrypoint": {"path": STRICT_APPEND_ARTIFACTS[0],
            "export": "publishSessionTranscriptUpdateByIdentity", "executionClaimed": False},
        "observationEntrypoint": {"path": NOTIFICATION_ARTIFACTS[0],
            "export": "r", "originalName": "onInternalSessionTranscriptUpdate"},
        "notificationVersionEntrypoint": {"path": NOTIFICATION_ARTIFACTS[0],
            "export": "s", "originalName": "readSessionTranscriptUpdateVersion"},
        "notificationCustody": "Strict append receives the actual emitted loop message and exact session identity; "
            "the original committed sequence and turn owner emits the normalized notification. "
            "A listener may observe notifications but cannot construct or replace their payloads.",
        "startupOwner": "The default manager constructor starts session catchup without awaiting its publication",
        "sessionStartOwner": "Original claimSessionWarmSync runs inside search with the real caller sessionKey",
        "sessionUpdateScheduler": {"owner": "manager-session-sync-ops.ts", "debounceMs": 5000,
            "deltaByteOrMessageThresholdExecutionClaimed": False},
        "searchPublication": "Dirty valid-index search starts original detached publication while retaining its read generation",
        "fullEmbeddedRunnerVerified": False, "automaticTurnBarrierClaimed": False,
        "defaultSdkPublicationPolicyChanged": False,
    }
