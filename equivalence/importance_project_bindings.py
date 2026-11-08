"""Authenticate the original recall reader's constant import without facade setup.

Only the exact named constant import is projected. The complete original SQL
reader, annotation owner and Kysely implementation execute unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_READER = "packages/memory-host-sdk/src/host/memory-recall-metadata.ts"
_INTERNAL = "packages/memory-host-sdk/src/host/internal.ts"
_ANNOTATIONS = "packages/memory-host-sdk/src/host/curated-annotations.ts"
_NAME = "INVALID_PROJECT_ANNOTATION_KEY"
_HASHES = {
    _READER: "37b70200001e49baa0dc489189223ce0e9bf034296926c0ce562139cea8d791d",
    _INTERNAL: "f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591",
    _ANNOTATIONS: "c4bd75fe3476f54508b42623e1f09190816f49e319703375865b9564fe4e7f5d",
}


def prepare_importance_project_bindings(checkout: Path) -> dict:
    """Resolve the reviewed recall-reader import to its unchanged constant owner."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Importance/project bindings require the unchanged pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if file.is_symlink() or not file.resolve().is_relative_to(checkout):
                raise ValueError("An importance/project binding escaped the pinned source tree.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise ValueError("An importance/project binding differs from its pinned source.")
            sources[relative] = raw.decode("utf-8")
        names = (_NAME,)
        chain = [
            _named(sources, _READER, "./internal.js", names, kind="import", exact=True),
            _named(sources, _INTERNAL, "./curated-annotations.js", names),
            *_declarations(sources, _ANNOTATIONS, names),
        ]
        evidence = [{
            "parent": _READER, "specifier": "./internal.js", "target": _ANNOTATIONS,
            "bindings": list(names), "chain": chain,
            "sources": [{"path": name, "sha256": _HASHES[name]}
                        for name in sorted({item["path"] for item in chain})],
            "scope": "importance-project-recall-reader",
            "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
            "note": "Only the reviewed constant binding bypasses broad internal facade setup. "
                    "The original recall SQL reader and annotation owner remain unchanged; "
                    "this projection does not verify manager or host orchestration.",
        }]
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Importance/project source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-importance-project-binding-projection",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [{key: row[key] for key in ("parent", "specifier", "target", "bindings")}
                               for row in evidence],
        "projectionEvidence": evidence,
    }
