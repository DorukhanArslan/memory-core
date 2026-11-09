"""Exact original store declarations and official compiled heartbeat scratch exports.

The fixture uses the same public row owners as upstream store tests. Source
declarations and publisher-attested compiled release bytes remain separate;
neither source rewriting nor reconstructed upstream algorithms are permitted.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {
    "src/cron/scratch-contract.ts": "78a2fc107ad4e5bb2af33accc8728013d77abcf785d0d498207ab9f751c14e27",
    "src/cron/scratch-store.ts": "04dc0f6937aa65dc0aaec4ed4eefa9115b1578b26ac65b47af926260b7583712",
    "src/cron/store/key.ts": "b0fb6c24eb4104427d3a2767ca041db9cdceac6833972d6fc0d07a26d422c67c",
    "src/cron/store/row-codec.ts": "f50366a8ee1a5a5eb075df3a8d80fbf15ee6e6ffd162c1aa59711e2c89aafd54",
    "src/state/openclaw-state-db.ts": "8f4f7a1a7cecb4d4e4ab9b762e85785ed1476d66bc195ef8f157efdc7871704c",
}
COMPILED_HASHES = {
    "dist/scratch-contract-B-Laspel.mjs": "48b547c772979d454611a91c29348cae00776c175448eb0756fcfdaa90951c3f",
    "dist/scratch-store-BsjpiVxl.mjs": "17a3373733a1af33974c11601436fc3a081f21daef252e94c805eef533204768",
    "dist/row-codec-CFdZvBgt.mjs": "a28523efc77832a776926e5735a90f867c8482da97ac8c48aca5dfe4a4bce279",
    "dist/key-BBZ40bDq.mjs": "2a21777dac5cb9375d52155212eff0ed59b01771b8532a2dcb925bde1e37ab08",
    "dist/openclaw-state-db-Dh2awMJ8.mjs": "e5aad1c1e5a6d9b1ed371c2a176cf39015d3d3d8293d9aa9128b977cc540f75b",
}
EXPORTS = {
    "dist/scratch-contract-B-Laspel.mjs": {"assertCronJobScratchContent": "n", "CRON_JOB_SCRATCH_MAX_BYTES": "t"},
    "dist/scratch-store-BsjpiVxl.mjs": {"readCronJobScratchState": "r", "writeCronJobScratch": "o",
        "deleteCronJobScratch": "t", "hashCronScratchSource": "n", "readHeartbeatMonitorScratch": "i",
        "readHeartbeatMonitorScratchReadOnly": "a"},
    "dist/row-codec-CFdZvBgt.mjs": {"upsertCronJobRow": "h", "replaceCronRows": "u",
        "deleteCronJobRowInDatabase": "n", "loadCronRows": "a"},
    "dist/key-BBZ40bDq.mjs": {"cronStoreKey": "t"},
    "dist/openclaw-state-db-Dh2awMJ8.mjs": {"runOpenClawStateWriteTransaction": "l", "openOpenClawStateDatabase": "r"},
}


def _git(checkout: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True, timeout=10).stdout


def prepare_heartbeat_runtime_bindings(checkout: Path, runtime: Path) -> dict:
    checkout, runtime = checkout.resolve(strict=True), runtime.resolve(strict=True)
    if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
            or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
            or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
        raise ValueError("Heartbeat scratch requires its clean exact original source root")
    sources, artifacts = [], []
    for name, digest in SOURCE_HASHES.items():
        original = _git(checkout, "show", "HEAD:" + name)
        if (hashlib.sha256(original).hexdigest() != digest or (checkout / name).read_bytes() != original
                or (checkout / name).is_symlink()):
            raise ValueError("A pinned heartbeat source declaration changed")
        sources.append({"path": name, "sha256": digest})
    for name, digest in COMPILED_HASHES.items():
        target = runtime / name
        raw = target.read_bytes()
        if target.is_symlink() or target.stat().st_nlink != 1 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("A pinned heartbeat compiled export changed")
        text = raw.decode()
        for symbol, alias in EXPORTS[name].items():
            if text.count(symbol + " as " + alias) != 1:
                raise ValueError("A heartbeat owner no longer has its reviewed direct export")
        artifacts.append({"path": name, "sha256": digest, "exports": EXPORTS[name]})
    return {"kind": "fixed-heartbeat-scratch-original-bindings", "referenceCommit": REFERENCE_COMMIT,
            "sourceBuildReproduced": False, "sourceDeclarations": sources, "compiledArtifacts": artifacts}
