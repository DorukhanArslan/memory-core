"""Authenticate the original CPU-vector owner bindings without broad facade setup.

These exact named reexports retain the real SQLite scan, binary64 decoder and
score/projection functions. They do not establish optional sqlite-vec execution
or full memory-manager orchestration.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_SPECIFIER = "openclaw/plugin-sdk/memory-core-host-engine-knn"
_VECTOR = "extensions/memory-core/src/memory/manager-search-vector.ts"
_SHARED = "extensions/memory-core/src/memory/manager-search-shared.ts"
_FACADE = "src/plugin-sdk/memory-core-host-engine-knn.ts"
_CODEC = "packages/memory-host-sdk/src/host/embedding-vector.ts"
_UTF16 = "packages/normalization-core/src/utf16-slice.ts"
_HASHES = {
    _VECTOR: "3ba4ecfed4e65f4a3c84c673c24d57466eaae8b82c5defe3a54e0f91298cdf4d",
    _SHARED: "410b3078f6e59379ba8db3fc5d4a07343447bd2e0d409b4d4bc9aa1617f28bc4",
    _FACADE: "3a67b71461e9f2e2b5e022208cc967c5238461be4395876361ca0fa34def8545",
    _CODEC: "515e3d73f9e6adff455f6f3db477d253fac0a10e44b53179d47683d101068de9",
    _UTF16: "12fd3212b08522a1523263c92f654151ad01605ee48a0ff58a1256889fb7cb5f",
}


def prepare_vector_bindings(checkout: Path) -> dict:
    """Resolve only reviewed imports to their unchanged original named owners."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Vector binding evidence requires the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if file.is_symlink() or not file.resolve().is_relative_to(checkout):
                raise ValueError("A vector binding escaped the pinned source tree.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise ValueError("A vector binding differs from the original pinned source.")
            sources[relative] = raw.decode("utf-8")
        evidence = []
        for parent, target, names, exported_from in (
            (_VECTOR, _CODEC, ("cosineSimilarity", "decodeMemoryEmbedding"),
             "../../packages/memory-host-sdk/src/host/embedding-vector.js"),
            (_SHARED, _UTF16, ("truncateUtf16Safe",), "@openclaw/normalization-core/utf16-slice"),
        ):
            chain = [
                _named(sources, parent, _SPECIFIER, names, kind="import", exact=True),
                _named(sources, _FACADE, exported_from, names),
                *_declarations(sources, target, names),
            ]
            evidence.append({
                "parent": parent, "specifier": _SPECIFIER, "target": target,
                "bindings": list(names), "chain": chain,
                "sources": [{"path": name, "sha256": _HASHES[name]}
                            for name in sorted({item["path"] for item in chain})],
                "scope": "portable-cpu-vector-candidates",
                "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
                "fullManagerExecutionVerified": False, "acceleratedKnnExecutionVerified": False,
                "note": "Original CPU admission, bounded SQLite scan, codec and projection execute. "
                        "Optional sqlite-vec acceleration and broad facade initialization are unverified.",
            })
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Vector binding source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-vector-binding-projection",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [{key: row[key] for key in ("parent", "specifier", "target", "bindings")}
                               for row in evidence],
        "projectionEvidence": evidence,
    }
