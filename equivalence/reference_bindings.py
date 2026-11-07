"""Verify the exact native bindings used by a narrowly projected test import.

The identity kernel needs three values from a broad storage facade. Importing
their actual source owner avoids loading unrelated daemon/state facades, but is
deliberately *not* evidence for facade initialization or full manager execution.
No source text is rewritten and no implementation is provided by this module.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
from typing import Mapping


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_TAG = "v2026.9.9"
_PARENT = "extensions/memory-core/src/memory/manager-reindex-state.ts"
_SPECIFIER = "openclaw/plugin-sdk/memory-core-host-engine-storage"
_FACADE = "src/plugin-sdk/memory-core-host-engine-storage.ts"
_ENGINE = "packages/memory-host-sdk/src/engine-storage.ts"
_TARGET = "packages/memory-host-sdk/src/host/internal.ts"
_HASH = "packages/memory-host-sdk/src/host/hash.ts"
_CHUNKS = "packages/memory-host-sdk/src/host/markdown-chunks.ts"
_BINDINGS = ("hashText", "MEMORY_CHUNKING_VERSION", "normalizeExtraMemoryPathEntries")

# A release change requires deliberate review of every edge, not automatic
# acceptance of whichever exports happen to appear in a caller's checkout.
_SOURCE_SHA256 = {
    _PARENT: "920dfbd46b3ac3f08ffa892642a4bb8474c779f22872107ccbf536a47f926044",
    _FACADE: "77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a",
    _ENGINE: "8c9e64c08acf587dd3312f4df3a874b423bdc52ea85ff6fabdd1377e2ac12a2a",
    _TARGET: "f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591",
    _HASH: "face88c71f4d752c24052ab299771ddf55c1c54d76ed2ebac8618a7812818683",
    _CHUNKS: "caae77122117210dba507956489f1e20f4015a31113e017e9e0b57f72ad78f1b",
}
_NAMED_FROM = re.compile(
    r"(?m)^(?P<kind>import|export)\s+(?P<types>type\s+)?"
    r"\{(?P<names>[^}]+)\}\s+from\s+[\"'](?P<specifier>[^\"']+)[\"'];",
)


class ReferenceBindingError(ValueError):
    """A fixed diagnostic for missing or changed native binding provenance."""


def _git(checkout: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=checkout, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ReferenceBindingError("Native binding provenance could not be verified.") from None
    if result.returncode:
        raise ReferenceBindingError("Native binding provenance could not be verified.")
    return result.stdout


def _runtime_names(match: re.Match) -> list[tuple[str, str]]:
    if match["types"]:
        return []
    names = []
    for item in match["names"].split(","):
        item = item.strip()
        if not item or item.startswith("type "):
            continue
        parsed = re.fullmatch(r"([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?", item)
        if parsed is None:
            raise ReferenceBindingError("A projected binding declaration is unsupported.")
        names.append((parsed[1], parsed[2] or parsed[1]))
    return names


def _edge(sources: Mapping[str, str], module: str, specifier: str,
          bindings: tuple[str, ...], *, kind: str = "export") -> dict:
    content = sources[module]
    matches = [match for match in _NAMED_FROM.finditer(content)
               if match["kind"] == kind and match["specifier"] == specifier]
    accepted = []
    for match in matches:
        pairs = _runtime_names(match)
        if all((name, name) in pairs for name in bindings):
            accepted.append(match)
    if len(accepted) != 1:
        raise ReferenceBindingError("A projected binding is not an unchanged direct named binding.")
    match = accepted[0]
    if kind == "import" and _runtime_names(match) != [(name, name) for name in bindings]:
        raise ReferenceBindingError("The identity kernel imports unexpected runtime bindings.")
    return {
        "path": module,
        "specifier": specifier,
        "bindings": list(bindings),
        "kind": kind,
        "line": content[:match.start()].count("\n") + 1,
        "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest(),
    }


def _trace_projection(sources: Mapping[str, str]) -> list[dict]:
    """Check the pinned syntax subset; this is not a general TypeScript parser."""
    edges = [
        _edge(sources, _PARENT, _SPECIFIER, _BINDINGS, kind="import"),
        _edge(sources, _FACADE, "../../packages/memory-host-sdk/src/engine-storage.js", _BINDINGS),
        _edge(sources, _ENGINE, "./host/internal.js", _BINDINGS),
        _edge(sources, _TARGET, "./hash.js", ("hashText",)),
        _edge(sources, _TARGET, "./markdown-chunks.js", ("MEMORY_CHUNKING_VERSION",)),
    ]
    for module, declaration in (
        (_TARGET, "export function normalizeExtraMemoryPathEntries("),
        (_HASH, "export function hashText("),
        (_CHUNKS, "export const MEMORY_CHUNKING_VERSION = "),
    ):
        if sources[module].count(declaration) != 1:
            raise ReferenceBindingError("A projected binding has no unique original declaration.")
        edges.append({
            "path": module,
            "kind": "declaration",
            "anchor": declaration,
            "line": sources[module][:sources[module].index(declaration)].count("\n") + 1,
        })
    return edges


def prepare_reference_bindings(checkout: Path) -> dict:
    """Return an exact-parent import allowlist and transparent projection evidence.

    The loader must match ``parent``, ``specifier`` and ``target`` together. It
    must not turn this entry into a global alias for the storage SDK facade.
    All paths in the result are relative to the verified native checkout.
    """
    checkout = Path(checkout).resolve()
    if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
            or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve()
            != checkout):
        raise ReferenceBindingError("Projected bindings require the exact pinned native checkout.")
    if _git(checkout, "status", "--porcelain", "--untracked-files=no").strip():
        raise ReferenceBindingError("Projected bindings require unmodified tracked native files.")
    sources = {}
    evidence = []
    for relative, expected in _SOURCE_SHA256.items():
        source = checkout / relative
        try:
            if source.is_symlink() or not source.resolve().is_relative_to(checkout):
                raise ReferenceBindingError("A native binding source escaped the pinned checkout.")
            content = source.read_bytes()
            if (hashlib.sha256(content).hexdigest() != expected
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest()
                    != expected):
                raise ReferenceBindingError("A native binding source differs from its pinned Git source.")
            sources[relative] = content.decode("utf-8")
        except (OSError, UnicodeError):
            raise ReferenceBindingError("A native binding source is missing or invalid.") from None
        evidence.append({"path": relative, "sha256": expected})
    chain = _trace_projection(sources)
    projection = {"parent": _PARENT, "specifier": _SPECIFIER, "target": _TARGET,
                  "bindings": list(_BINDINGS)}
    return {
        "schemaVersion": 1,
        "kind": "reference-binding-projection",
        "reference": {"tag": _TAG, "commit": _COMMIT},
        "allowedResolutions": [projection],
        "projectionEvidence": [{
            **projection,
            "scope": "identity-kernel-only",
            "sources": evidence,
            "chain": chain,
            "facadeExecutionVerified": False,
            "fullManagerExecutionVerified": False,
            "note": (
                "The identity kernel executes the same three named native bindings through their "
                "original source owner. The broad storage facade and its transitive module "
                "initialization are bypassed; their side effects and full manager behavior are "
                "not executed or verified by this projection."
            ),
        }],
    }
