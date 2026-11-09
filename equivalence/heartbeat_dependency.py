"""Authenticate the exact additional doctor dependency in a private runtime only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from equivalence.dependencies import _committed_lock, _integrity
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.release_runtime import _archive_files, _publish, _verify_tree

CRONER = {"name": "croner", "version": "10.0.1", "location": "node_modules/croner",
          "pin": "upstream-pnpm-lock",
          "integrity": "sha512-ixNtAJndqh173VQ4KodSdJEI6nuioBWI0V1ITNKhZZsO0pEMoDxz539T4FTTbSZ/xIOSuDnzxLVRqBVSvPNE2g=="}


def prepare_heartbeat_dependency(checkout: Path, runtime_cache: Path, archive: Path, *, install=False) -> dict:
    commit, lock = _committed_lock(checkout)
    if commit != REFERENCE_COMMIT or _integrity(lock, "croner", "10.0.1") != CRONER["integrity"]:
        raise ValueError("The doctor dependency must match the exact original source lock")
    archive = archive.resolve(strict=True)
    if archive.is_symlink() or archive.stat().st_nlink != 1 or archive.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("The doctor dependency archive must be an independent bounded regular file")
    raw = archive.read_bytes()
    files = _archive_files(raw, CRONER)
    package = json.loads(files["package.json"])
    if package.get("name") != "croner" or package.get("version") != "10.0.1" or package.get("dependencies"):
        raise ValueError("The doctor dependency changed its exact package identity or dependency closure")
    runtime_cache = runtime_cache.resolve(strict=True)
    target = runtime_cache / CRONER["location"]
    if install and not target.exists():
        _publish(target, files)
    verified = _verify_tree(target, files, set())
    return {**CRONER, "directory": str(target), "fileCount": len(verified),
            "filesSha256": hashlib.sha256(json.dumps(verified, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "files": verified, "archiveSha256": hashlib.sha256(raw).hexdigest(), "archive": str(archive)}
