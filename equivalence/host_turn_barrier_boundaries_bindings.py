"""Pinned original full channel delivery and optional-maintenance declarations.

This inventory authenticates pristine sources and official compiled artifacts
separately; it is not execution evidence and awards no conditions. The Native
channel dispatcher owns its actual reply operation and delivery completion.
"""
from pathlib import Path

from equivalence.host_restart_bindings import REFERENCE_COMMIT, _owners
from equivalence.host_turn_barrier_bindings import (
    ADDITIONAL_REQUIRED_HOST_ARTIFACTS as OUTCOME_ARTIFACTS,
    prepare_host_turn_barrier_bindings,
)

SOURCE_HASHES = {'src/auto-reply/reply/dispatch-from-config.ts': 'c86c6066ec6b85d55b642dd389e246119acd59a0fad298d9bc73406fc6d141a3',
 'src/auto-reply/reply/dispatch-from-config.prepare-operation.ts': '7e3e052a3b59cd88084a1652ab2865784d43e4e99a2378cd62e8bfb036eeb967',
 'src/auto-reply/reply/dispatch-from-config.prepare-delivery.ts': '8019fc876fd50727105d1f67f9048dd317d9f1f61ef3f2c931e6f53d2734ccf3',
 'src/auto-reply/reply/dispatch-from-config.execute.ts': 'd8f37e4dacb0b08b7402e2701d3585e1c59abf1b103e3d16984b015948a74ee1',
 'src/auto-reply/reply/dispatch-from-config.finalize.ts': 'd7e9e5eee061385a81a8a662d121a0b6372d0e11670a64d8d2b717c6fe6c3874',
 'src/auto-reply/reply/reply-dispatcher.ts': 'd64b0042495fb3eda7708d8e4eb12934bd767878e7d9df4c70fe784e6e77db2f',
 'src/auto-reply/reply/pending-final-delivery.ts': '9dba470e986ff78a59616f5d5511f9d41d3807b2fba1464a6fd8de25ad860abc'}

SOURCE_ANCHORS = {'src/auto-reply/reply/dispatch-from-config.ts': ('export async function dispatchReplyFromConfig(',),
 'src/auto-reply/reply/dispatch-from-config.prepare-operation.ts': ('export async function '
                                                                    'prepareDispatchOperation(',),
 'src/auto-reply/reply/dispatch-from-config.prepare-delivery.ts': ('export async function '
                                                                   'prepareDispatchDelivery(',),
 'src/auto-reply/reply/dispatch-from-config.execute.ts': ('export async function executeDispatch(',),
 'src/auto-reply/reply/dispatch-from-config.finalize.ts': ('export async function '
                                                           'finalizeDispatchAndAudit(',),
 'src/auto-reply/reply/reply-dispatcher.ts': ('export function createReplyDispatcher(',),
 'src/auto-reply/reply/pending-final-delivery.ts': ('export function '
                                                    'resolvePendingFinalDeliveryCompletion(',)}

COMPILED_HASHES = {'dist/dispatch-from-config-BG9rT_X3.mjs': 'a110ec6fe2d59a34d40267aeb84f1df136999c6b47bd9aeeeab410d1c3610fd1',
 'dist/reply-dispatcher-XbSXLzuk.mjs': '289f052ac0b105bd4e868e477019a95f8475f36a84956850e77c9021d5867a40',
 'dist/memory-state-BmtUbXjH.mjs': 'ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f'}

COMPILED_ANCHORS = {'dist/dispatch-from-config-BG9rT_X3.mjs': ('async function dispatchReplyFromConfig(params)',),
 'dist/reply-dispatcher-XbSXLzuk.mjs': ('function createReplyDispatcher(options)',),
 'dist/memory-state-BmtUbXjH.mjs': ('function resolveMemoryFlushPlan(params)',)}

ADDITIONAL_REQUIRED_HOST_ARTIFACTS = tuple(dict.fromkeys((*OUTCOME_ARTIFACTS, *COMPILED_HASHES)))


def prepare_host_turn_barrier_boundaries_bindings(checkout: Path, runtime_root: Path) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    base = prepare_host_turn_barrier_bindings(checkout, runtime_root)
    return {
        "kind": "official-release-host-turn-barrier-boundary-owners",
        "operation": "host-turn-barrier-boundaries-runtime",
        "referenceCommit": REFERENCE_COMMIT,
        "naturalHostOwners": base,
        "additionalSourceBindings": _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True),
        "additionalCompiledBindings": _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False),
        "requiredLoadedArtifacts": list(ADDITIONAL_REQUIRED_HOST_ARTIFACTS),
        "sourceBuildReproduced": False,
        "sourceFallbackAllowed": False,
        "covers": [],
        "acceptancePointsAwarded": 0,
        "hostEntrypoint": {"path": "dist/dispatch-from-config-BG9rT_X3.mjs", "export": "n",
                           "owner": "dispatchReplyFromConfig"},
        "deliveryEntrypoint": {"path": "dist/reply-dispatcher-XbSXLzuk.mjs", "export": "i",
                               "owner": "createReplyDispatcher"},
        "declarationLimits": [
            "Import presence is not execution; protected actor and actual runtime custody are also required.",
            "The dispatcher creates its own reply operation; no fixture-supplied replyOperation is permitted.",
            "Scripted model and channel delivery transports are declared host seams, not original replacements.",
            "Native full dispatch returns are compared with actual SDK channel-adapter delivery accounting; "
            "the complete SDK HostTurnOutcome is separate custody, not a raw return-API identity claim.",
            "Native bootstrap files are disabled through the declared original skipBootstrap option; "
            "the SDK owner uses initialize=False. Corpus, scores and all public payload fields remain complete.",
            "The Linux read lease blocks genuine pre-model target preparation, not an admitted append syscall.",
            "A pending provider transport can be abandoned before its own cleanup; no cleanup-join claim is made.",
            "A private maintenance error, persisted stamp or log is not an externally delivered warning.",
            "A new foreground question waits for actual original maintenance owner settlement, not merely abort.",
            "No forced publication, fixture synchronization, maintenance drain or timer replacement supplies a match.",
        ],
    }
