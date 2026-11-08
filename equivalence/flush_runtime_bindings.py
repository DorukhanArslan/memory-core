"""Pin the original trigger owner and its separately authenticated release export.

These checks establish reviewed source/artifact identities, not a reproducible
build or a source-module projection. The official archive authentication remains
the release harness's responsibility before and after execution.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {
    "src/auto-reply/reply/agent-runner-memory.ts": "283089b92cfd44840aaf5cdea08cec5148015ba93d86668e5e0a2b41fcfe8878",
    "src/auto-reply/reply/memory-flush.ts": "dedf96e5f7dabc0f7f37e61b58576553c68d60462a466ce1788c6e68d1e00145",
    "src/agents/usage.ts": "337814417cff205e868ec3477111a99e8745536a909fe4a3580d74f05c7f9d85",
    "extensions/memory-core/src/flush-plan.ts": "e94b6f5d02c60dc600833592977096e1db5ce3e15a8958348252a3832ddb4bcc",
    "src/config/sessions/session-accessor.sqlite-active-events.ts": "8313bc8a4f68f008da3f2b93b059eb173b8dcbf709f86c0bdfbeeac6ce39ea5a",
}
COMPILED_HASHES = {
    "dist/agent-runner-memory-Cc4lCZcs.mjs": "9a87aeee70d84d41eb6bf764a70c0334fb679a2f1e21d817c44c5eb306d5620e",
    "dist/memory-state-BmtUbXjH.mjs": "ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f",
    "dist/runtime-9cxii0oQ.mjs": "9f18ed5dbca908c9a71f126d08f09bcfed73e93d80efe9e668fecb5a6e568356",
    "dist/registry-empty-BTjzcMW2.mjs": "11afb0f560f5b31d2785a5b4381d05639862e748a1220370364657d8b4333698",
    "dist/session-accessor-CiKKTlbe.mjs": "287c41790f551f5e31941cde89854babae25a57976a1a24f992e6e955aaf5f8a",
    "dist/extensions/memory-core/index.js": "ead9aeb06b76504ba8ab9cb50a03c1425d18cbb936285c47f5ae7cf25e2877f8",
}


def prepare_flush_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Return provenance only after all fixed owner/export bytes are verified."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        if commit != REFERENCE_COMMIT:
            raise ValueError("Flush runtime reference commit differs from the reviewed owner.")
        for root, hashes in ((checkout, SOURCE_HASHES), (runtime_root, COMPILED_HASHES)):
            for relative, digest in hashes.items():
                file = root / relative
                if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                    raise ValueError("A flush runtime owner differs from its reviewed bytes.")
        source = (checkout / "src/auto-reply/reply/agent-runner-memory.ts").read_text()
        compiled = (runtime_root / "dist/agent-runner-memory-Cc4lCZcs.mjs").read_text()
        if (source.count("export async function runMemoryFlushIfNeeded(") != 1
                or compiled.count("async function runMemoryFlushIfNeeded(") != 1
                or "runMemoryFlushIfNeeded as t" not in compiled):
            raise ValueError("The reviewed native trigger owner/export is unavailable.")
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Flush runtime owner provenance could not be verified.") from error
    return {
        "kind": "official-release-flush-trigger-owner",
        "sourceBuildReproduced": False,
        "referenceCommit": REFERENCE_COMMIT,
        "sourceBindings": [{"path": path, "sha256": digest}
                           for path, digest in SOURCE_HASHES.items()],
        "compiledBindings": [{"path": path, "sha256": digest}
                             for path, digest in COMPILED_HASHES.items()],
        "entrypoint": {"path": "dist/agent-runner-memory-Cc4lCZcs.mjs", "export": "t",
                       "owner": "runMemoryFlushIfNeeded"},
        "fixtureBoundary": "original plan resolver; second resolve throws after the native trigger",
    }
