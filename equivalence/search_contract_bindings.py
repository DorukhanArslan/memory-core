"""Authenticate original parser and citation owners for search-tool comparisons.

The two exact-parent resolutions execute unchanged original named owners. They
bypass broad facade initialization; the common parsers execute their real source
module and import graph. Tool construction and execution use separate release
runtime evidence, rather than claiming these pure helpers prove host behavior.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_CITATIONS = "extensions/memory-core/src/tools.citations.ts"
_STORAGE_SDK = "src/plugin-sdk/memory-core-host-engine-storage.ts"
_STORAGE = "packages/memory-host-sdk/src/engine-storage.ts"
_INTERNAL = "packages/memory-host-sdk/src/host/internal.ts"
_ANNOTATIONS = "packages/memory-host-sdk/src/host/curated-annotations.ts"
_RUNTIME_SDK = "src/plugin-sdk/memory-core-host-runtime-core.ts"
_ROUTING = "src/routing/session-key.ts"
_SESSION_UTILS = "src/sessions/session-key-utils.ts"
_SESSION_NORMALIZATION = "packages/session-url-contract/src/session-key-normalization.ts"
_COMMON = "src/agents/tools/common.ts"
_NUMBERS = "packages/normalization-core/src/number-coercion.ts"
_RECORDS = "packages/normalization-core/src/record-coerce.ts"
_STRING_LIST = "packages/normalization-core/src/string-normalization.ts"
_STRINGS = "packages/normalization-core/src/string-coerce.ts"
_PARAM_KEY = "src/param-key.ts"
_ERRORS = "src/agents/tool-input-error.ts"
_SHARED = "extensions/memory-core/src/tools.shared.ts"
_DEADLINE = "extensions/memory-core/src/memory/search-deadline.ts"
_HASHES = {
    _CITATIONS: "10ac036c279a1d18ea20e0731b3aee126aebd89f3d3a4fff09b965db5ef80669",
    _STORAGE_SDK: "77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a",
    _STORAGE: "8c9e64c08acf587dd3312f4df3a874b423bdc52ea85ff6fabdd1377e2ac12a2a",
    _INTERNAL: "f45f4006c1f92c6364059532c9ba309533b68c4cd7a6d7516fd017caa9330591",
    _ANNOTATIONS: "c4bd75fe3476f54508b42623e1f09190816f49e319703375865b9564fe4e7f5d",
    _RUNTIME_SDK: "9d0fc4e1f1ec1f4c4a140a2a5b8cb63246c18091274cc8ffa51b5274b03a653b",
    _ROUTING: "f581697b1bde74523a78aa3cdea5fd4b11e73374544b1471c0af6c489bf90899",
    _SESSION_UTILS: "4cfb6c219248bd157a43f85b49bf8f4601233ef089c90f3716e9a1ceb0adf4d5",
    _SESSION_NORMALIZATION: "2ffb6e39064f6938e093abf86aad99cc5b2b7bd0872a836f98a7247ea9904857",
    _COMMON: "3140b2be2998afbd24d2ab68e1d206e86c7dd8ed8147a2b4ff77304419f7c7dc",
    _NUMBERS: "88c84a37f5c25e5920b6a92cd3435e72710fcdadd33d9d2e034232b37890f886",
    _RECORDS: "6c0f118fc25744b5bb400faa6d06a36f146f3ff001210a6d07cf008ebd829616",
    _STRING_LIST: "194631a168c6e3d76ad47c4cecdc2781f06a42ac3e1535a4d4a9296c39e1a8a4",
    _STRINGS: "323a54581e6cc4220b02c31238f74d75c503afb9f91623568f01cb55a708bb58",
    _PARAM_KEY: "3393299148b9059e991f9d655e3e930bc507ed1d8d6985db21e4e42466df91ef",
    _ERRORS: "70582ae2f67d5d23ce514ee93f249e2c659ddf32e7bf70b1692dcadcf03af7bc",
    _SHARED: "f111a96bd8f19e2e7b295133531a1ac240ae9938ef2c0c4cd477a8b914b0d9be",
    _DEADLINE: "8bbbe60f02eb73552adbcf8e7440c2dad84c6d6d857a0bccf948f6a30ad5f693",
}


class SearchContractBindingError(ValueError):
    """The pinned search-tool helper provenance is unavailable or changed."""


def _source_evidence(chain: list[dict]) -> list[dict]:
    return [{"path": name, "sha256": _HASHES[name]}
            for name in sorted({edge["path"] for edge in chain})]


def _parser_evidence(sources: dict[str, str]) -> dict:
    names = ("asToolParamsRecord", "readNumberParam", "readPositiveIntegerParam",
             "readFiniteNumberParam")
    chain = _declarations(sources, _COMMON, names)
    # TypeScript has two declared overloads followed by the original body. Do
    # not extract that body or turn its signatures into replacement functions.
    overloads = list(re.finditer(r"(?m)^export function readToolStringParam\(", sources[_COMMON]))
    if len(overloads) != 3:
        raise SearchContractBindingError("The native string parser overloads changed.")
    chain.append({"path": _COMMON, "kind": "overload-declarations",
                  "binding": "readToolStringParam",
                  "lines": [sources[_COMMON][:match.start()].count("\n") + 1
                            for match in overloads]})
    for specifier, owner, imported in (
        ("@openclaw/normalization-core/number-coercion", _NUMBERS,
         ("asPositiveSafeInteger", "asSafeIntegerInRange", "parseStrictFiniteNumber")),
        ("@openclaw/normalization-core/record-coerce", _RECORDS, ("asNonArrayRecord",)),
        ("@openclaw/normalization-core/string-normalization", _STRING_LIST,
         ("normalizeSingleOrTrimmedStringList",)),
        ("../../param-key.js", _PARAM_KEY, ("readSnakeCaseParamRaw",)),
        ("../tool-input-error.js", _ERRORS, ("ToolAuthorizationError", "ToolInputError")),
    ):
        chain.append(_named(sources, _COMMON, specifier, imported, kind="import", exact=True))
        chain.extend(_declarations(sources, owner, imported))
    chain.append(_named(sources, _PARAM_KEY, "@openclaw/normalization-core/string-coerce",
                        ("lowercasePreservingWhitespace",), kind="import", exact=True))
    chain.extend(_declarations(sources, _STRINGS, ("lowercasePreservingWhitespace",)))
    return {"module": _COMMON, "bindings": [*names, "readToolStringParam"],
            "scope": "native-common-tool-parameter-parsers", "chain": chain,
            "sources": _source_evidence(chain), "originalOwnerExecutionRequired": True,
            "facadeInitializationBypassed": False,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False}


def prepare_search_contract_bindings(checkout: Path) -> dict:
    """Authenticate two citation projections and direct parser source owners."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise SearchContractBindingError("Search-tool bindings require the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if (any(part.is_symlink() for part in (file, *file.parents) if part != checkout)
                    or not file.resolve().is_relative_to(checkout)):
                raise SearchContractBindingError("A search-tool binding escaped the pinned source tree.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise SearchContractBindingError("A search-tool binding differs from its pinned Git source.")
            sources[relative] = raw.decode("utf-8")
        evidence = []
        for specifier, owner, name, intermediates in (
            ("openclaw/plugin-sdk/memory-core-host-engine-storage", _ANNOTATIONS,
             "stripMemoryAnnotationCarriers", (
                 (_STORAGE_SDK, "../../packages/memory-host-sdk/src/engine-storage.js"),
                 (_STORAGE, "./host/internal.js"), (_INTERNAL, "./curated-annotations.js"))),
            ("openclaw/plugin-sdk/memory-core-host-runtime-core", _SESSION_NORMALIZATION,
             "parseAgentSessionKey", (
                 (_RUNTIME_SDK, "../routing/session-key.js"),
                 (_ROUTING, "../sessions/session-key-utils.js"),
                 (_SESSION_UTILS, "@openclaw/session-url-contract/session-key-normalization"))),
        ):
            names = (name,)
            chain = [_named(sources, _CITATIONS, specifier, names, kind="import", exact=True)]
            chain.extend(_named(sources, facade, exported, names)
                         for facade, exported in intermediates)
            chain.extend(_declarations(sources, owner, names))
            evidence.append({
                "parent": _CITATIONS, "specifier": specifier, "target": owner,
                "bindings": list(names), "chain": chain, "sources": _source_evidence(chain),
                "scope": "native-memory-search-citation-presentation",
                "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
                "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
                "note": "The unchanged citation helper imports verified original named owners. "
                        "Broad facade initialization is bypassed; tool construction and host "
                        "orchestration require separate official runtime evidence.",
            })
        citation_names = ("buildMemorySearchPresentation", "resolveMemoryCitationsMode",
                          "shouldIncludeCitations")
        citation_chain = _declarations(sources, _CITATIONS, citation_names)
        owners = [_parser_evidence(sources), {
            "module": _CITATIONS, "bindings": list(citation_names),
            "scope": "native-memory-search-citation-presentation", "chain": citation_chain,
            "sources": _source_evidence(citation_chain), "originalOwnerExecutionRequired": True,
            "facadeInitializationBypassed": True,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        }]
        unavailable_chain = [
            *_declarations(sources, _SHARED, ("buildMemorySearchUnavailableResult",)),
            _named(sources, _SHARED, "./memory/search-deadline.js",
                   ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",), kind="import", exact=True),
            *_declarations(sources, _DEADLINE, ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",)),
        ]
        owners.append({
            "module": _SHARED, "bindings": ["buildMemorySearchUnavailableResult"],
            "nativeConstants": ["DEFAULT_MEMORY_SEARCH_TIMEOUT_MS"],
            "scope": "native-memory-search-unavailable-result", "chain": unavailable_chain,
            "sources": _source_evidence(unavailable_chain), "originalOwnerExecutionRequired": True,
            "facadeInitializationBypassed": False,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
            "note": "The genuine unavailable-result owner imports its native timeout constant. "
                    "This validates result shaping; deadline execution requires its separate contract.",
        })
    except (OSError, UnicodeError, ReferenceBindingError, ValueError) as error:
        raise SearchContractBindingError("Search-tool helper source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-search-contract-binding-projection",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [{key: row[key] for key in ("parent", "specifier", "target", "bindings")}
                               for row in evidence],
        "projectionEvidence": evidence, "sourceOwnerEvidence": owners,
    }
