"""Authenticate the original parameter and excerpt owners for memory_get.

These are direct source imports with no facade substitutions. The fixture
adapter calls the unchanged native functions; complete tool execution has its
own official release runtime evidence.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_COMMON = "src/agents/tools/common.ts"
_ERRORS = "src/agents/tool-input-error.ts"
_PARAM_KEY = "src/param-key.ts"
_NUMBERS = "packages/normalization-core/src/number-coercion.ts"
_RECORDS = "packages/normalization-core/src/record-coerce.ts"
_STRINGS = "packages/normalization-core/src/string-coerce.ts"
_UTF16 = "packages/normalization-core/src/utf16-slice.ts"
_READ_SHARED = "packages/memory-host-sdk/src/host/read-file-shared.ts"
_HASHES = {
    _COMMON: "3140b2be2998afbd24d2ab68e1d206e86c7dd8ed8147a2b4ff77304419f7c7dc",
    _ERRORS: "70582ae2f67d5d23ce514ee93f249e2c659ddf32e7bf70b1692dcadcf03af7bc",
    _PARAM_KEY: "3393299148b9059e991f9d655e3e930bc507ed1d8d6985db21e4e42466df91ef",
    _NUMBERS: "88c84a37f5c25e5920b6a92cd3435e72710fcdadd33d9d2e034232b37890f886",
    _RECORDS: "6c0f118fc25744b5bb400faa6d06a36f146f3ff001210a6d07cf008ebd829616",
    _STRINGS: "323a54581e6cc4220b02c31238f74d75c503afb9f91623568f01cb55a708bb58",
    _UTF16: "12fd3212b08522a1523263c92f654151ad01605ee48a0ff58a1256889fb7cb5f",
    _READ_SHARED: "cc574d3135a6849b6a62ed640a5e502eb23ca066071ce152d704ce861f2f8b5d",
}


class GetContractBindingError(ValueError):
    """The pinned memory_get source owner evidence is unavailable or changed."""


def _owner(module: str, names: tuple[str, ...], chain: list[dict], scope: str) -> dict:
    return {
        "module": module, "bindings": list(names), "chain": chain, "scope": scope,
        "sources": [{"path": relative, "sha256": _HASHES[relative]}
                    for relative in sorted({edge["path"] for edge in chain})],
        "originalOwnerExecutionRequired": True, "facadeInitializationBypassed": False,
        "fullToolExecutionVerified": False, "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False,
        "note": "The fixture transport calls unchanged original source owners. "
                "This evidence does not establish complete tool or host execution.",
    }


def _trace(sources: dict[str, str]) -> list[dict]:
    parser_names = ("asToolParamsRecord", "readPositiveIntegerParam", "readToolStringParam")
    parser_chain = _declarations(sources, _COMMON,
                                 ("asToolParamsRecord", "readNumberParam", "readPositiveIntegerParam"))
    overloads = list(re.finditer(r"(?m)^export function readToolStringParam\(", sources[_COMMON]))
    if len(overloads) != 3:
        raise GetContractBindingError("The native string parser overloads changed.")
    parser_chain.append({"path": _COMMON, "kind": "overload-declarations",
                         "binding": "readToolStringParam",
                         "lines": [sources[_COMMON][:match.start()].count("\n") + 1
                                   for match in overloads]})
    for specifier, original, names in (
        ("@openclaw/normalization-core/number-coercion", _NUMBERS,
         ("asPositiveSafeInteger", "asSafeIntegerInRange", "parseStrictFiniteNumber")),
        ("@openclaw/normalization-core/record-coerce", _RECORDS, ("asNonArrayRecord",)),
        ("../../param-key.js", _PARAM_KEY, ("readSnakeCaseParamRaw",)),
        ("../tool-input-error.js", _ERRORS, ("ToolAuthorizationError", "ToolInputError")),
    ):
        parser_chain.append(_named(sources, _COMMON, specifier, names, kind="import", exact=True))
        parser_chain.extend(_declarations(sources, original, names))
    parser_chain.extend([
        _named(sources, _PARAM_KEY, "@openclaw/normalization-core/string-coerce",
               ("lowercasePreservingWhitespace",), kind="import", exact=True),
        *_declarations(sources, _STRINGS, ("lowercasePreservingWhitespace",)),
    ])

    read_names = ("buildMemoryReadResult", "buildMemoryReadResultFromSlice",
                  "DEFAULT_MEMORY_READ_LINES", "DEFAULT_MEMORY_READ_MAX_CHARS")
    read_chain = _declarations(sources, _READ_SHARED, read_names)
    for specifier, original, names in (
        ("@openclaw/normalization-core/number-coercion", _NUMBERS, ("resolveIntegerOption",)),
        ("@openclaw/normalization-core/utf16-slice", _UTF16, ("truncateUtf16Safe",)),
    ):
        read_chain.append(_named(sources, _READ_SHARED, specifier, names, kind="import", exact=True))
        read_chain.extend(_declarations(sources, original, names))
    read_chain.extend([
        _named(sources, _NUMBERS, "./string-coerce.ts", ("normalizeOptionalString",),
               kind="import", exact=True),
        *_declarations(sources, _STRINGS, ("normalizeOptionalString",)),
        *_declarations(sources, _UTF16, ("sliceUtf16Safe",)),
    ])
    return [
        _owner(_COMMON, parser_names, parser_chain, "native-memory-get-parameter-parsers"),
        _owner(_READ_SHARED, read_names, read_chain, "native-memory-get-excerpt-shaping"),
    ]


def prepare_get_contract_bindings(checkout: Path) -> dict:
    """Authenticate direct memory_get parser and excerpt owners; no projections."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise GetContractBindingError("Memory-get source owners require the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if (any(part.is_symlink() for part in (file, *file.parents) if part != checkout)
                    or not file.resolve().is_relative_to(checkout)):
                raise GetContractBindingError("A memory-get source owner escaped the pinned checkout.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise GetContractBindingError("A memory-get owner differs from its pinned Git source.")
            sources[relative] = raw.decode("utf-8")
        owners = _trace(sources)
    except (OSError, UnicodeError, ReferenceBindingError, ValueError) as error:
        raise GetContractBindingError("Memory-get source owner provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-get-contract-source-owners",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [], "projectionEvidence": [], "sourceOwnerEvidence": owners,
    }
