"""One explicit unchanged source owner in the mixed turn-trust experiment."""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import _git

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_PATH = "src/agents/embedded-agent-runner/run/turn-taint-state.ts"
SOURCE_SHA256 = "7fd28e4064c555256feeaace2dbabb8b08d31ce1e0d7baaf1a1d7b20380723fe"


def prepare_turn_taint_source_authority(checkout: Path) -> dict:
    checkout = Path(checkout).resolve(strict=True)
    file = checkout / SOURCE_PATH
    if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
            or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
            or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()
            or any(path.is_symlink() for path in (file, *file.parents) if path != checkout)
            or file.resolve(strict=True) != file):
        raise ValueError("The one approved taint source requires the unchanged pinned checkout")
    raw = file.read_bytes()
    if (hashlib.sha256(raw).hexdigest() != SOURCE_SHA256
            or hashlib.sha256(_git(checkout, "show", f"HEAD:{SOURCE_PATH}")).hexdigest() != SOURCE_SHA256):
        raise ValueError("The one approved taint source differs from its reviewed bytes")
    return {"kind": "pinned-reference-source", "checkout": str(checkout), "path": str(file),
            "relativePath": SOURCE_PATH, "sha256": SOURCE_SHA256, "referenceCommit": REFERENCE_COMMIT,
            "export": "createAgentTurnTaintState", "zeroRuntimeDependencies": True}


def validate_turn_taint_source_authority(value: dict) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("checkout"), str):
        raise ValueError("Source imports require the one explicit taint-owner authority")
    expected = prepare_turn_taint_source_authority(Path(value["checkout"]))
    if (type(value.get("zeroRuntimeDependencies")) is not bool
            or value.get("zeroRuntimeDependencies") is not True or value != expected):
        raise ValueError("Additional source paths or source identities are not authorized")
    return expected
