"""Reviewed source and official artifact identities for flush execution.

The fixture owns scripted provider replies through the native plugin contract.
Session preparation, append/provenance tools, indexing and finalization remain
native owners. Official artifact authentication is separate from source identity;
this does not attest a reproduced source build.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {
    "src/auto-reply/reply/agent-runner-memory.ts": "283089b92cfd44840aaf5cdea08cec5148015ba93d86668e5e0a2b41fcfe8878",
    "src/auto-reply/reply/memory-flush-session.ts": "3014bd23b500b37bf0b4bc41896e370a22b53a864208a1fd6361257ccc4c2cbe",
    "src/agents/agent-tools.ts": "bdcad2054268bf84d89439a5473224118c504a3eb36e1961d6454c09f9d4a391",
    "src/agents/agent-tools.read.ts": "34db04c4719a01d2b173c690498707e42c2dc8d1b8f6b1bca211fce9c08e3a6a",
    "src/agents/memory-write-provenance.ts": "628c004d93b38b06108d426750ca1ef1e8459c108202d0568b18e4c02bfebd13",
    "src/memory/memory-artifact-provenance.ts": "68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373",
    "src/plugins/provider-runtime.ts": "b209db16ccf0845faa417e8bca7da4c7afbbf1d4b6a66919d246e2c458d62ffd",
    "src/infra/gateway-scheduler.ts": "53c5a46e4cbe447b6b58daefe30f977dae8d06cd2f44b359fca0962617fc120d",
    "src/agents/session-maintenance/run.ts": "043485f2d937b849c800f01b19d88ef5f0a5e9a997f42fded38641ee45ff0987",
    "src/plugins/plugin-source-capture-directory.ts": "29affbbf41a67b3e20dd82f4d3bfeb5d61cd0df74926497e15cb06708b49ad7f",
    "src/plugins/plugin-generation-artifact.ts": "a60117eafae7214b2fca88f4a27df63359495c624d8b4b4294aeec99928d1424",
    "extensions/memory-core/src/flush-plan.ts": "e94b6f5d02c60dc600833592977096e1db5ce3e15a8958348252a3832ddb4bcc",
}
COMPILED_HASHES = {
    "dist/agent-runner-memory-Cc4lCZcs.mjs": "9a87aeee70d84d41eb6bf764a70c0334fb679a2f1e21d817c44c5eb306d5620e",
    "dist/memory-flush-session-BjKZkw5O.mjs": "da4a6471a723a5603ad263da6101a9e93f150938f4da5a77ef00cef00279974f",
    "dist/agent-tools-HIqp3eTk.mjs": "9887e5788b6d88cf3c9a7a5581548d52b5f208fccd2694a01df8bb75017cd702",
    "dist/agent-tools.read-ZzkirzL1.mjs": "bec516044e956d92b1297b154a48ef9ee75e83dfdfe79b8dda5668a9995e778c",
    "dist/memory-artifact-provenance-DhnyWiV1.mjs": "d9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c",
    "dist/provider-runtime-BHqCdO9o.mjs": "c546dc4f068c84a318fb13fff99a15f0b0871065ded276ca7d81c3efd11d751c",
    "dist/gateway-scheduler-TywODsdc.mjs": "92a674af56f14b9340a1c80b9f3ac0ffe8b454d97a1fa4af9a2186a4eac9fc6e",
    "dist/agent-run-registry-RDoBEeyg.mjs": "e0f758f81410927cb1b9836a4fa32790774104a8cfaad20ce9e5a7bcabdb4d98",
    "dist/extensions/memory-core/manager-runtime.js": "6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e",
    "dist/extensions/memory-core/index.js": "ead9aeb06b76504ba8ab9cb50a03c1425d18cbb936285c47f5ae7cf25e2877f8",
}
FIXTURE_MANIFEST = {
    "id": "fixture-memory-model", "providers": ["fixture-memory-model"],
    "configSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def prepare_flush_execution_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Verify unchanged owners and a reviewed data-only provider declaration."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        if commit != REFERENCE_COMMIT:
            raise ValueError("The flush execution reference is not the reviewed commit.")
        for root, hashes in ((checkout, SOURCE_HASHES), (runtime_root, COMPILED_HASHES)):
            for relative, digest in hashes.items():
                file = root / relative
                if (file.is_symlink() or not file.resolve().is_relative_to(root.resolve())
                        or hashlib.sha256(file.read_bytes()).hexdigest() != digest):
                    raise ValueError("A flush execution owner differs from its reviewed bytes.")
        manifest = Path(__file__).with_name("openclaw.plugin.json")
        raw = manifest.read_bytes()
        if manifest.is_symlink() or json.loads(raw) != FIXTURE_MANIFEST:
            raise ValueError("The scripted fixture provider metadata changed.")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise ValueError("Flush execution provenance could not be verified.") from error
    return {
        "kind": "official-release-flush-execution-owner", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False,
        "sourceBindings": [{"path": path, "sha256": digest} for path, digest in SOURCE_HASHES.items()],
        "compiledBindings": [{"path": path, "sha256": digest} for path, digest in COMPILED_HASHES.items()],
        "entrypoint": {"path": "dist/agent-runner-memory-Cc4lCZcs.mjs", "export": "t",
                       "owner": "runMemoryFlushIfNeeded"},
        "fixturePluginManifest": {"path": manifest.name, "sha256": hashlib.sha256(raw).hexdigest()},
        "fixtureBoundary": "Native provider plugin createStreamFn emits labelled assistant replies; "
                           "native session, tool, provenance, index and finalizer owners execute.",
    }
