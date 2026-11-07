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
_CACHE_PARENT = "extensions/memory-core/src/memory/manager-embedding-cache.ts"
_VECTOR = "packages/memory-host-sdk/src/host/embedding-vector.ts"
_SQL_FACADE = "src/plugin-sdk/sqlite-runtime.ts"
_SQL_TARGET = "src/infra/kysely-sync.ts"
_CACHE_BINDINGS = ("decodeMemoryEmbedding", "encodeMemoryEmbedding")
_SQL_BINDINGS = ("compileSqliteQueryBindings", "executeSqliteQuerySync",
                 "getNodeSqliteKysely", "iterateSqliteQuerySync")

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
_CACHE_SOURCE_SHA256 = {
    _CACHE_PARENT: "75fb4853466385740e4150d247797516e4c7698896fb63e6acb3c546faea5f09",
    _VECTOR: "515e3d73f9e6adff455f6f3db477d253fac0a10e44b53179d47683d101068de9",
    _SQL_FACADE: "6fa47548183e9c9425d541051cecbb6f6fb1b611dbe8e5b8bd78fc6d698ce903",
    _SQL_TARGET: "b00ef2f4a7e5fd229fab29c43729a6ebdce6d9900ddd3c856178f3ecc5d834d7",
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
        raise ReferenceBindingError("A projected kernel imports unexpected runtime bindings.")
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


def _trace_cache_projections(sources: Mapping[str, str]) -> list[dict]:
    vectors = [
        _edge(sources, _CACHE_PARENT, _SPECIFIER, _CACHE_BINDINGS, kind="import"),
        _edge(sources, _FACADE, "../../packages/memory-host-sdk/src/engine-storage.js", _CACHE_BINDINGS),
        _edge(sources, _ENGINE, "./host/internal.js", _CACHE_BINDINGS),
        _edge(sources, _TARGET, "./embedding-vector.js", _CACHE_BINDINGS),
    ]
    sql = [
        _edge(sources, _CACHE_PARENT, "openclaw/plugin-sdk/sqlite-runtime", _SQL_BINDINGS,
              kind="import"),
        _edge(sources, _SQL_FACADE, "../infra/kysely-sync.js", _SQL_BINDINGS),
    ]
    for chain, module, names in ((vectors, _VECTOR, _CACHE_BINDINGS),
                                  (sql, _SQL_TARGET, _SQL_BINDINGS)):
        for name in names:
            anchor = f"export function {name}"
            matches = list(re.finditer(re.escape(anchor) + r"(?:\(|<)", sources[module]))
            if len(matches) != 1:
                raise ReferenceBindingError("A projected cache binding has no unique native declaration.")
            chain.append({"path": module, "kind": "declaration", "anchor": anchor,
                          "line": sources[module][:matches[0].start()].count("\n") + 1})
    return [
        {"resolution": {"parent": _CACHE_PARENT, "specifier": _SPECIFIER,
                        "target": _VECTOR, "bindings": list(_CACHE_BINDINGS)}, "chain": vectors},
        {"resolution": {"parent": _CACHE_PARENT, "specifier": "openclaw/plugin-sdk/sqlite-runtime",
                        "target": _SQL_TARGET, "bindings": list(_SQL_BINDINGS)}, "chain": sql},
    ]


def prepare_reference_bindings(checkout: Path, *, include_cache: bool = False) -> dict:
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
    expected_sources = {**_SOURCE_SHA256, **(_CACHE_SOURCE_SHA256 if include_cache else {})}
    for relative, expected in expected_sources.items():
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
    result = {
        "schemaVersion": 1,
        "kind": "reference-binding-projection",
        "reference": {"tag": _TAG, "commit": _COMMIT},
        "allowedResolutions": [projection],
        "projectionEvidence": [{
            **projection,
            "scope": "identity-kernel-only",
            "sources": [item for item in evidence if item["path"] in _SOURCE_SHA256],
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
    if include_cache:
        for item in _trace_cache_projections(sources):
            resolution, chain = item["resolution"], item["chain"]
            paths = {edge["path"] for edge in chain}
            result["allowedResolutions"].append(resolution)
            result["projectionEvidence"].append({
                **resolution, "scope": "embedding-cache-kernel-only", "chain": chain,
                "sources": [source for source in evidence if source["path"] in paths],
                "facadeExecutionVerified": False, "fullManagerExecutionVerified": False,
                "note": "Original cache, codec and SQLite query implementations execute unchanged. "
                        "Only their verified direct named bindings bypass broad facade initialization; "
                        "provider dispatch, full sync and manager lifecycle are not verified here.",
            })
    return result
