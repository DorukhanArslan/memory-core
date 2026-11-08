"""Authenticate the original literal-regexp owner used by path retrieval.

The unchanged path search executes its own normalization, SQLite plans and row
projection. This single named binding bypasses broad text facade initialization;
the shared UTF-16 binding is supplied separately by the existing vector binder.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_SEARCH = "extensions/memory-core/src/memory/manager-search.ts"
_SPECIFIER = "openclaw/plugin-sdk/text-utility-runtime"
_FACADE = "src/plugin-sdk/text-utility-runtime.ts"
_UTILS = "src/utils.ts"
_REGEXP = "src/shared/regexp.ts"
_HASHES = {
    _SEARCH: "0f0e97935d28718e077ed867c13d03568ce71c3c89cf5b306a8a4c42e98b7da4",
    _FACADE: "ebf2d7095db5da5bc210276af59a430a1ced82379506d46b684fc4ce6b51f5b6",
    _UTILS: "c0a559097bda662fd274b2e0233593d1a36a0b197df4835bd299dbdb141b53d4",
    _REGEXP: "bafc7ca866952c3df452c25ca0c6ef30756ff2c9f44463ad76da30857aeab35e",
}


def prepare_exact_path_bindings(checkout: Path) -> dict:
    """Resolve the exact original literal-regexp import, never a replacement."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ValueError("Exact-path binding evidence requires the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if file.is_symlink() or not file.resolve().is_relative_to(checkout):
                raise ValueError("An exact-path binding escaped the pinned source tree.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise ValueError("An exact-path binding differs from the original pinned source.")
            sources[relative] = raw.decode("utf-8")
        names = ("escapeRegExp",)
        chain = [
            _named(sources, _SEARCH, _SPECIFIER, names, kind="import", exact=True),
            _named(sources, _FACADE, "../utils.js", names),
            _named(sources, _UTILS, "./shared/regexp.js", names),
            *_declarations(sources, _REGEXP, names),
        ]
        evidence = [{
            "parent": _SEARCH, "specifier": _SPECIFIER, "target": _REGEXP,
            "bindings": list(names), "chain": chain,
            "sources": [{"path": name, "sha256": _HASHES[name]}
                        for name in sorted({item["path"] for item in chain})],
            "scope": "exact-path-query-and-sql-owners",
            "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
            "note": "Original matcher and real SQLite path retrieval execute unchanged. "
                    "Only the authenticated named regexp owner bypasses broad facade setup; "
                    "this does not establish complete manager or host execution.",
        }]
    except (OSError, UnicodeError, ReferenceBindingError) as error:
        raise ValueError("Exact-path binding source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-exact-path-binding-projection",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [{key: row[key] for key in ("parent", "specifier", "target", "bindings")}
                               for row in evidence],
        "projectionEvidence": evidence,
    }
