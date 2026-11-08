"""Authenticate original session admission policy and transcript owners.

Pure policy and eligibility helpers execute unchanged. Catalog and projection
declarations identify the genuine owners used by the separate real SQLite and
index runtime profile; declaration evidence alone earns no whole-flow credit.
No facade import is redirected or synthesized by this binder.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import ReuseBindingError, _declarations, _named


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_POLICY = "src/agents/memory-search-source-policy.ts"
_CONFIG = "src/agents/memory-search.ts"
_ELIGIBILITY = "extensions/memory-core/src/memory/manager-session-sync-state.ts"
_SYNC = "extensions/memory-core/src/memory/manager-session-sync-ops.ts"
_SDK = "src/plugin-sdk/memory-core-host-engine-sessions.ts"
_ENGINE = "packages/memory-host-sdk/src/engine-sessions.ts"
_RUNTIME = "packages/memory-host-sdk/src/host/openclaw-runtime-session.ts"
_SESSION_KEYS = "src/sessions/session-key-utils.ts"
_CATALOG = "packages/memory-host-sdk/src/host/session-transcript-corpus.ts"
_FILES = "packages/memory-host-sdk/src/host/session-files.ts"
_PROJECTION = "packages/memory-host-sdk/src/host/session-entry-projection.ts"
_PROVENANCE = "packages/memory-host-sdk/src/host/session-provenance.ts"
_ARTIFACTS = "src/config/sessions/artifacts.ts"
_ACCESSOR = "src/config/sessions/session-accessor.ts"
_INGESTION = "extensions/memory-core/src/session-ingestion.ts"
_STRING_SDK = "src/plugin-sdk/string-coerce-runtime.ts"
_RECORDS = "packages/normalization-core/src/record-coerce.ts"
_STRING_LIST = "packages/normalization-core/src/string-normalization.ts"
_ORIGINS = "extensions/memory-core/src/memory-entry-origins.ts"
_HASHES = {
    _POLICY: "b95b8ebf49144924307e153162b1302ba5fd48658e647618aec1ff0d54b0b80f",
    _CONFIG: "a1edad1e59255c5657af97d636be2517a3704f2ca3950e4a06f06892647092b2",
    _ELIGIBILITY: "ee190fecc3c4d8853ef9cf2aba95f786aa144d2a599818533202200a515c96d6",
    _SYNC: "3af5c8c2ef2aca054c3d34190941855ab76374c65cd5d6908b6744fb34ea0a4f",
    _SDK: "e05da58485856c557ae7e37e97dbffba0da0abe8b72d355261ee784d1db12f7b",
    _ENGINE: "d4c312c0b7fb9a1caac069081869517118d9f0a863fc78dc846a86ed45ad1997",
    _RUNTIME: "51fed14e0695f0caf97d1b3296ed5cdba7b8867bca4de8611509af68fce14eed",
    _SESSION_KEYS: "4cfb6c219248bd157a43f85b49bf8f4601233ef089c90f3716e9a1ceb0adf4d5",
    _CATALOG: "8bc7c3f008e3b4d9c04da985cec647b830c54c2c205f15d4ff834e202585dfb7",
    _FILES: "d184bf1a1b098a02b08ed131321fb47d6caf5bee9e1cc6d88751502dbb8761ee",
    _PROJECTION: "34458bdb1827bc240626c7f81f6840ce5b23263e3f37b5342881f3ec9eaaad8d",
    _PROVENANCE: "312eac1018ccb49bd98acee26f70a074fa51ed8c17075ad98b8fbbd62469e63b",
    _ARTIFACTS: "9dc4eedc513390ee7fc7467f6ff43eca218976a72bd311c32a1ebef839e7c399",
    _ACCESSOR: "c9738d2bb1987ce23d3541a3d5d75f7ef282108d6078cea5e91328e6142506ef",
    _INGESTION: "a220ead109095fef8994435b2fe6c51667190574f2ab25d07919bdf1257a8af2",
    _STRING_SDK: "9b3d30c868101d6005cadd5990dbcb62bf9afe91171aaf35191c996005484c47",
    _RECORDS: "6c0f118fc25744b5bb400faa6d06a36f146f3ff001210a6d07cf008ebd829616",
    _STRING_LIST: "194631a168c6e3d76ad47c4cecdc2781f06a42ac3e1535a4d4a9296c39e1a8a4",
    _ORIGINS: "d84877d05b1621d554260c23b3d4678eb184ffce9ad7fd0255abee67ac3ad0d7",
}


class SessionAdmissionBindingError(ValueError):
    """The pinned source admission owners are unavailable or changed."""


def _private_declarations(sources: dict[str, str], module: str, names: tuple[str, ...]) -> list[dict]:
    result = []
    for name in names:
        matches = list(re.finditer(rf"(?m)^(?:async\s+)?function\s+{re.escape(name)}\b", sources[module]))
        if len(matches) != 1:
            raise SessionAdmissionBindingError("A native admission owner declaration changed.")
        result.append({"path": module, "kind": "private-declaration", "binding": name,
                       "line": sources[module][:matches[0].start()].count("\n") + 1})
    return result


def _owner(module: str, names: tuple[str, ...], chain: list[dict], scope: str,
           *, helper: bool) -> dict:
    return {
        "module": module, "bindings": list(names), "chain": chain, "scope": scope,
        "sources": [{"path": relative, "sha256": _HASHES[relative]}
                    for relative in sorted({edge["path"] for edge in chain})],
        "originalOwnerExecutionRequired": True, "pureHelperComparison": helper,
        "declarationEvidenceOnly": not helper, "facadeInitializationBypassed": False,
        "wholeSessionFlowVerified": False, "realSqliteAdmissionVerified": False,
        "indexPublicationVerified": False, "sessionVisibilityVerified": False,
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "note": "These pinned declarations identify unchanged original owners. Pure helper "
                "comparisons do not establish catalog ownership, SQLite transcript reads, index "
                "publication, worker execution, or session visibility; those need separate real runtime evidence.",
    }


def _trace(sources: dict[str, str]) -> list[dict]:
    policy_names = ("resolveMemorySearchSourcePolicy",)
    policy_chain = [
        *_declarations(sources, _POLICY, policy_names),
        _named(sources, _CONFIG, "./memory-search-source-policy.js", policy_names,
               kind="import", exact=True),
    ]
    eligibility_names = ("isMemorySessionIndexable",)
    classification_names = ("isCronRunSessionKey", "isDreamingNarrativeSessionStoreKey")
    eligibility_chain = [
        *_declarations(sources, _ELIGIBILITY, eligibility_names),
        _named(sources, _SYNC, "./manager-session-sync-state.js",
               ("isMemorySessionIndexable", "resolveMemorySessionStartupState"), kind="import", exact=True),
        _named(sources, _ELIGIBILITY, "openclaw/plugin-sdk/memory-core-host-engine-sessions",
               classification_names, kind="import", exact=True),
        _named(sources, _SDK, "../../packages/memory-host-sdk/src/engine-sessions.js", classification_names),
        _named(sources, _ENGINE, "./host/openclaw-runtime-session.js", classification_names),
        _named(sources, _RUNTIME, "../../../../src/sessions/session-key-utils.js", ("isCronRunSessionKey",)),
        *_declarations(sources, _SESSION_KEYS, ("isCronRunSessionKey",)),
        *_declarations(sources, _RUNTIME, ("isDreamingNarrativeSessionStoreKey",)),
    ]
    catalog_names = ("listSessionTranscriptCorpusEntriesForAgentSync",
                     "listSessionTranscriptCorpusEntriesForAgent")
    archive_names = ("isCompactionCheckpointTranscriptFileName", "isSessionArchiveArtifactName",
                     "isUsageCountedSessionTranscriptFileName", "parseUsageCountedSessionIdFromFileName")
    catalog_chain = [
        *_declarations(sources, _CATALOG, catalog_names),
        *_private_declarations(sources, _CATALOG,
                               ("classifySessionEntry", "collectCronGeneratedSessionKeys",
                                "toRetainedSessionCorpusEntry", "projectSessionTranscriptCorpusEntries")),
        _named(sources, _CATALOG, "./openclaw-runtime-session.js",
               ("listSessionEntriesCore", "listSessionEntriesReadOnly"), kind="import"),
        _named(sources, _RUNTIME, "../../../../src/config/sessions/session-accessor.js",
               ("listSessionEntriesCore", "listSessionEntriesReadOnly"), exact=True),
        _named(sources, _ACCESSOR, "./session-accessor.entry.js",
               ("listSessionEntriesCore", "listSessionEntriesReadOnly")),
        _named(sources, _RUNTIME, "../../../../src/config/sessions/artifacts.js", archive_names, exact=True),
        *_declarations(sources, _ARTIFACTS, archive_names),
    ]
    projection_names = ("buildSessionEntry", "buildSessionEntryInProcess", "statSessionEntrySync",
                        "sessionPathForSessionIdentity")
    projection_chain = [
        *_declarations(sources, _FILES, projection_names),
        *_private_declarations(sources, _FILES,
                               ("isDreamingNarrativeGeneratedRecord", "isCronRunGeneratedRecord",
                                "resolveBuildSessionSqliteIdentity")),
        _named(sources, _FILES, "./session-transcript-corpus.js",
               ("listSessionTranscriptCorpusEntriesForAgentSync",), kind="import", exact=True),
        _named(sources, _FILES, "./session-entry-projection.js",
               ("collectRawSessionText", "projectSessionEntryRecord"), kind="import", exact=True),
        *_declarations(sources, _PROJECTION, ("collectRawSessionText", "projectSessionEntryRecord")),
        _named(sources, _FILES, "./session-provenance.js", ("classifySessionMessageOrigin",),
               kind="import", exact=True),
        *_declarations(sources, _PROVENANCE, ("classifySessionMessageOrigin",)),
        _named(sources, _FILES, "./openclaw-runtime-session.js",
               ("readTranscriptExportSnapshotReadOnlySync",), kind="import"),
        _named(sources, _RUNTIME, "../../../../src/config/sessions/session-accessor.js",
               ("readTranscriptExportSnapshotReadOnlySync",), kind="import"),
        _named(sources, _ACCESSOR, "./session-accessor.transcript.js",
               ("readTranscriptExportSnapshotReadOnlySync",)),
    ]
    ingestion_names = ("resolveAdmissionPolicy", "sessionExclusionReason")
    ingestion_chain = [
        *_declarations(sources, _INGESTION, ingestion_names),
        _named(sources, _INGESTION, "openclaw/plugin-sdk/string-coerce-runtime",
               ("asNullableRecord", "normalizeTrimmedStringList"), kind="import", exact=True),
        _named(sources, _STRING_SDK, "../../packages/normalization-core/src/record-coerce.js",
               ("asNullableRecord",)),
        *_declarations(sources, _RECORDS, ("asNullableRecord",)),
        _named(sources, _STRING_SDK, "../../packages/normalization-core/src/string-normalization.js",
               ("normalizeTrimmedStringList",)),
        *_declarations(sources, _STRING_LIST, ("normalizeTrimmedStringList",)),
        _named(sources, _INGESTION, "openclaw/plugin-sdk/memory-core-host-engine-sessions",
               ("buildSessionEntry", "loadMemorySessionMetadata", "matchesSessionEntryPrefixHash",
                "sessionPathForFile", "statSessionEntrySync"), kind="import", exact=True),
        *_declarations(sources, _SDK, ("loadMemorySessionMetadata",)),
        _named(sources, _SDK, "../config/sessions/session-accessor.js",
               ("listSessionTranscriptInstances",), kind="import"),
        _named(sources, _INGESTION, "./memory-entry-origins.js", ("listMemorySessionTombstones",),
               kind="import", exact=True),
        *_declarations(sources, _ORIGINS, ("listMemorySessionTombstones",)),
    ]
    ingestion = _owner(_INGESTION, ingestion_names, ingestion_chain,
                       "native-session-ingestion-admission-policy", helper=True)
    ingestion.update({
        "comparedBindings": ["resolveAdmissionPolicy"],
        "declarationOnlyBindings": ["sessionExclusionReason"],
        "policyConsumer": "session-ingestion",
        "note": "Source cases execute the genuine plugin memoryPolicy.excludeSessions parser. "
                "The original exclusion resolver and metadata/tombstone imports are declaration evidence "
                "for separate real SQLite runtime comparisons. Ingestion exclusions and session-index "
                "eligibility retain their own original consumers; this helper gives no whole-flow credit.",
    })
    return [
        _owner(_POLICY, policy_names, policy_chain, "native-session-corpus-source-policy", helper=True),
        _owner(_ELIGIBILITY, eligibility_names, eligibility_chain, "native-session-corpus-eligibility", helper=True),
        _owner(_CATALOG, catalog_names, catalog_chain, "native-session-catalog-owner-declarations", helper=False),
        _owner(_FILES, projection_names, projection_chain, "native-session-snapshot-projection-declarations", helper=False),
        ingestion,
    ]


def prepare_session_admission_bindings(checkout: Path) -> dict:
    """Authenticate direct native admission owners, without facade projections."""
    checkout = Path(checkout).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise SessionAdmissionBindingError("Session admission owners require the unmodified pinned checkout.")
        sources = {}
        for relative, digest in _HASHES.items():
            file = checkout / relative
            if (any(part.is_symlink() for part in (file, *file.parents) if part != checkout)
                    or not file.resolve().is_relative_to(checkout)):
                raise SessionAdmissionBindingError("A session admission owner escaped the pinned checkout.")
            raw = file.read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != digest):
                raise SessionAdmissionBindingError("A session admission owner differs from its pinned Git source.")
            sources[relative] = raw.decode("utf-8")
        owners = _trace(sources)
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError, ValueError) as error:
        raise SessionAdmissionBindingError("Session admission owner provenance could not be verified.") from error
    return {
        "schemaVersion": 1, "kind": "native-session-admission-source-owners",
        "reference": {"tag": "v2026.9.9", "commit": _COMMIT},
        "allowedResolutions": [], "projectionEvidence": [], "sourceOwnerEvidence": owners,
    }
