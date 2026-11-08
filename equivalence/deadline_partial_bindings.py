"""Authenticate original deadline, corpus recovery, and warning result owners.

All owners execute through their genuine source import graphs. This binder
provides no facade projections and does not turn warning formatting into proof
that deadline timers, cooldown state, or complete tools executed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _NAMED_FROM, _git, _runtime_names
from equivalence.reuse_bindings import _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_DEADLINE = "extensions/memory-core/src/memory/search-deadline.ts"
_CONTROL = "packages/memory-host-sdk/src/host/search-deadline-control.ts"
_CORPUS = "extensions/memory-core/src/memory-corpus.ts"
_SHARED = "extensions/memory-core/src/tools.shared.ts"
_STORAGE_SDK = "src/plugin-sdk/memory-core-host-engine-storage.ts"
_STORAGE = "packages/memory-host-sdk/src/engine-storage.ts"
_RUNTIME_SDK = "src/plugin-sdk/memory-core-host-runtime-core.ts"
_STATE = "src/plugins/memory-state.ts"
_CONCURRENCY_SDK = "src/plugin-sdk/concurrency-runtime.ts"
_CONCURRENCY = "src/utils/run-with-concurrency.ts"
_ERROR_SDK = "src/plugin-sdk/error-runtime.ts"
_ERRORS = "src/infra/errors.ts"
_ERROR_COERCION = "packages/normalization-core/src/error-coercion.ts"
_REDACT = "src/logging/redact.ts"
_STRING_SDK = "src/plugin-sdk/string-coerce-runtime.ts"
_STRINGS = "packages/normalization-core/src/string-coerce.ts"
_HASHES = {
    _DEADLINE: "8bbbe60f02eb73552adbcf8e7440c2dad84c6d6d857a0bccf948f6a30ad5f693",
    _CONTROL: "ac3eee0e159c9d949c5367a1e8e40ead6b1c2a5433f9d925dc29184b9dc3208b",
    _CORPUS: "f37d07ba508c47256dfa5b60f71caad06569ca8e3e195bbfc2363c7cc098bca3",
    _SHARED: "f111a96bd8f19e2e7b295133531a1ac240ae9938ef2c0c4cd477a8b914b0d9be",
    _STORAGE_SDK: "77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a",
    _STORAGE: "8c9e64c08acf587dd3312f4df3a874b423bdc52ea85ff6fabdd1377e2ac12a2a",
    _RUNTIME_SDK: "9d0fc4e1f1ec1f4c4a140a2a5b8cb63246c18091274cc8ffa51b5274b03a653b",
    _STATE: "b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229",
    _CONCURRENCY_SDK: "7e16a1938f33c78a42f03f39b575a4e443ef55f8860a31054703674e6fda4173",
    _CONCURRENCY: "fd8e0369534ed9087e56b66eb9dad0bdd09aa8dc34c2296f6e2bc849d28077c3",
    _ERROR_SDK: "91e7eae29418c9659235b1a0cbc96c955c20fac9655db067d83f29c8900bd7c8",
    _ERRORS: "a195735ec6b4f2426dce5eada6f033f40faca93c3dd2777f41ba88bb4b83e1f0",
    _ERROR_COERCION: "699730a7140507cc86c884116d01b3820cc0a3fe9a4c1ed38db58f77c673ab88",
    _REDACT: "ecdfdb1e0f4b0f2aa3eb54aad574bb5375ae8da78539ad937b34ba02dd170e7b",
    _STRING_SDK: "9b3d30c868101d6005cadd5990dbcb62bf9afe91171aaf35191c996005484c47",
    _STRINGS: "323a54581e6cc4220b02c31238f74d75c503afb9f91623568f01cb55a708bb58",
}


class DeadlinePartialBindingError(ValueError):
    """The native deadline and recovery owner provenance is unavailable or changed."""


def _owner(module: str, names: tuple[str, ...], chain: list[dict], scope: str,
           note: str) -> dict:
    return {
        "module": module, "bindings": list(names), "chain": chain, "scope": scope,
        "sources": [{"path": relative, "sha256": _HASHES[relative]}
                    for relative in sorted({edge["path"] for edge in chain})],
        "originalOwnerExecutionRequired": True, "facadeInitializationBypassed": False,
        "deadlineExecutionVerified": False, "cooldownStateExecutionVerified": False,
        "fullToolExecutionVerified": False, "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False, "note": note,
    }


def _error_owners(sources: dict[str, str]) -> list[dict]:
    names = ("extractErrorCode", "formatErrorMessage")
    chain = [
        _named(sources, _CORPUS, "openclaw/plugin-sdk/error-runtime", names,
               kind="import", exact=True),
        _named(sources, _ERROR_SDK, "../infra/errors.js", names),
        _named(sources, _ERRORS, "@openclaw/normalization-core/error-coercion",
               ("extractErrorCode",)),
        *_declarations(sources, _ERROR_COERCION, names),
        *_declarations(sources, _ERRORS, ("formatErrorMessage",)),
        _named(sources, _ERRORS, "../logging/redact.js", ("redactSensitiveText",),
               kind="import", exact=True),
        *_declarations(sources, _REDACT, ("redactSensitiveText",)),
    ]
    # The host formatter deliberately adds redaction to the normalization owner.
    # Authenticate its real local alias without replacing that policy wrapper.
    matches = [match for match in _NAMED_FROM.finditer(sources[_ERRORS])
               if match["kind"] == "import"
               and match["specifier"] == "@openclaw/normalization-core/error-coercion"
               and _runtime_names(match) == [
                   ("extractErrorCode", "extractErrorCode"),
                   ("formatErrorMessage", "formatSharedErrorMessage"),
               ]]
    if len(matches) != 1:
        raise DeadlinePartialBindingError("The native error formatter owner alias changed.")
    match = matches[0]
    chain.append({
        "path": _ERRORS, "kind": "import", "specifier": match["specifier"],
        "bindings": ["extractErrorCode", "formatErrorMessage"],
        "localBindings": ["extractErrorCode", "formatSharedErrorMessage"],
        "line": sources[_ERRORS][:match.start()].count("\n") + 1,
        "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest(),
    })
    return chain


def _trace(sources: dict[str, str]) -> list[dict]:
    deadline_names = ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS", "resolveMemorySearchAbortError",
                      "createMemorySearchDeadlineError", "isMemorySearchDeadlineError",
                      "runMemorySearchWithDeadline")
    control_names = ("MEMORY_SEARCH_DEADLINE_CONTROL", "createMemorySearchDeadlineControl")
    corpus_names = ("unavailableMemoryCorpus", "attemptMemoryCorpus", "runMemoryCorpusDeadline",
                    "composeMemoryCorpusMetadata", "searchMemoryCorpusSupplements",
                    "readMemoryCorpusSupplements")
    corpus_chain = _declarations(sources, _CORPUS, corpus_names)
    imported_deadline = ("createMemorySearchDeadlineError", "DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",
                         "isMemorySearchDeadlineError", "resolveMemorySearchAbortError")
    corpus_chain.extend([
        _named(sources, _CORPUS, "./memory/search-deadline.js", imported_deadline,
               kind="import", exact=True),
        *_declarations(sources, _DEADLINE, imported_deadline),
        _named(sources, _CORPUS, "openclaw/plugin-sdk/memory-core-host-engine-storage",
               ("createMemorySearchDeadlineControl",), kind="import", exact=True),
        _named(sources, _STORAGE_SDK, "../../packages/memory-host-sdk/src/engine-storage.js",
               ("createMemorySearchDeadlineControl",)),
        _named(sources, _STORAGE, "./host/search-deadline-control.js",
               ("createMemorySearchDeadlineControl",)),
        *_declarations(sources, _CONTROL, ("createMemorySearchDeadlineControl",)),
        _named(sources, _CORPUS, "openclaw/plugin-sdk/memory-core-host-runtime-core",
               ("listMemoryCorpusSupplements",), kind="import", exact=True),
        _named(sources, _RUNTIME_SDK, "../plugins/memory-state.js", ("listMemoryCorpusSupplements",)),
        *_declarations(sources, _STATE, ("listMemoryCorpusSupplements",)),
        _named(sources, _CORPUS, "openclaw/plugin-sdk/concurrency-runtime",
               ("runTasksWithConcurrency",), kind="import", exact=True),
        _named(sources, _CONCURRENCY_SDK, "../utils/run-with-concurrency.js",
               ("runTasksWithConcurrency",)),
        *_declarations(sources, _CONCURRENCY, ("runTasksWithConcurrency",)),
        *_error_owners(sources),
    ])
    unavailable_names = ("buildMemorySearchUnavailableResult",)
    unavailable_chain = [
        *_declarations(sources, _SHARED, unavailable_names),
        _named(sources, _SHARED, "./memory/search-deadline.js",
               ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",), kind="import", exact=True),
        *_declarations(sources, _DEADLINE, ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",)),
        _named(sources, _SHARED, "openclaw/plugin-sdk/string-coerce-runtime",
               ("normalizeLowercaseStringOrEmpty",), kind="import", exact=True),
        _named(sources, _STRING_SDK, "../../packages/normalization-core/src/string-coerce.js",
               ("normalizeLowercaseStringOrEmpty",)),
        *_declarations(sources, _STRINGS, ("normalizeLowercaseStringOrEmpty",)),
    ]
    return [
        _owner(_DEADLINE, deadline_names, _declarations(sources, _DEADLINE, deadline_names),
               "native-memory-search-deadline-runner",
               "Authenticates the original timer, cancellation and error-identity owner. "
               "Actual deadline execution requires controlled runtime comparisons."),
        _owner(_CONTROL, control_names, _declarations(sources, _CONTROL, control_names),
               "native-memory-search-balanced-deadline-control",
               "Authenticates the original nested pause/resume fan-out owner and symbol. "
               "Control behavior requires actual source execution."),
        _owner(_CORPUS, corpus_names, corpus_chain,
               "native-memory-corpus-deadline-recovery-and-partial-results",
               "The complete original corpus owner imports its genuine timer, control, "
               "registry, concurrency and redacting error owners. No facade is bypassed."),
        _owner(_SHARED, unavailable_names, unavailable_chain,
               "native-memory-search-unavailable-result-formatting",
               "Warning shaping preserves the native timeout constant. Formatting evidence "
               "does not establish timer, cancellation, cooldown, or complete tool behavior."),
    ]


def prepare_deadline_partial_bindings(checkout: Path) -> dict:
    """Authenticate direct owners for the combined deadline and recovery package."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise DeadlinePartialBindingError("Deadline/recovery owners require the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if (any(part.is_symlink() for part in (file, *file.parents) if part != checkout)
                    or not file.resolve().is_relative_to(checkout)):
                raise DeadlinePartialBindingError("A deadline/recovery owner escaped the pinned checkout.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise DeadlinePartialBindingError("A deadline/recovery owner differs from its pinned Git source.")
            sources[relative] = raw.decode("utf-8")
        owners = _trace(sources)
    except (OSError, UnicodeError, ReferenceBindingError, ValueError) as error:
        raise DeadlinePartialBindingError("Deadline/recovery source provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-deadline-partial-source-owners",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [], "projectionEvidence": [], "sourceOwnerEvidence": owners,
    }
