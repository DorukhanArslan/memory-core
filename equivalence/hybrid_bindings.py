"""Authenticate the original project-ranking constant used by hybrid comparisons.

Only one exact-parent named import is projected to its unchanged original owner.
This bypasses broad storage-facade initialization and does not verify a complete
memory manager or host lifecycle.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_SPECIFIER = "openclaw/plugin-sdk/memory-core-host-engine-storage"
_RANKING = "extensions/memory-core/src/memory/project-ranking.ts"
_FACADE = "src/plugin-sdk/memory-core-host-engine-storage.ts"
_STORAGE = "packages/memory-host-sdk/src/engine-storage.ts"
_INTERNAL = "packages/memory-host-sdk/src/host/internal.ts"
_ANNOTATIONS = "packages/memory-host-sdk/src/host/curated-annotations.ts"
_NAME = "INVALID_PROJECT_ANNOTATION_KEY"
_HASHES = {
    _RANKING: "cb08173e8e35c51cf61dc1323099c252f798cf471aece3c036823c875eb94647",
    _FACADE: "77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a",
    _STORAGE: "8c9e64c08acf587dd3312f4df3a874b423bdc52ea85ff6fabdd1377e2ac12a2a",
    _INTERNAL: "f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591",
    _ANNOTATIONS: "c4bd75fe3476f54508b42623e1f09190816f49e319703375865b9564fe4e7f5d",
}


def prepare_hybrid_bindings(checkout: Path) -> dict:
    """Resolve the reviewed named constant through its authenticated reexports."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Hybrid binding evidence requires the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if file.is_symlink() or not file.resolve().is_relative_to(checkout):
                raise ValueError("A hybrid binding escaped the pinned source tree.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise ValueError("A hybrid binding differs from the original pinned source.")
            sources[relative] = raw.decode("utf-8")
        names = (_NAME,)
        chain = [
            _named(sources, _RANKING, _SPECIFIER, names, kind="import", exact=True),
            _named(sources, _FACADE, "../../packages/memory-host-sdk/src/engine-storage.js", names),
            _named(sources, _STORAGE, "./host/internal.js", names),
            _named(sources, _INTERNAL, "./curated-annotations.js", names),
            *_declarations(sources, _ANNOTATIONS, names),
        ]
        evidence = [{
            "parent": _RANKING, "specifier": _SPECIFIER, "target": _ANNOTATIONS,
            "bindings": list(names), "chain": chain,
            "sources": [{"path": name, "sha256": _HASHES[name]}
                        for name in sorted({item["path"] for item in chain})],
            "scope": "hybrid-ranking-owners",
            "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
            "note": "The original project-ranking import resolves to its unchanged annotation "
                    "constant owner. Broad storage-facade initialization and complete manager "
                    "or host orchestration are unverified.",
        }]
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Hybrid binding source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-hybrid-binding-projection",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [{key: row[key] for key in ("parent", "specifier", "target", "bindings")}
                               for row in evidence],
        "projectionEvidence": evidence,
    }
