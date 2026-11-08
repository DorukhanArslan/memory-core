"""Source declarations authenticate owners; they cannot establish session flows."""
from copy import deepcopy
import hashlib
import subprocess

import pytest

from equivalence import session_admission_bindings as bindings


def _functions(*names):
    return "".join(f"export function {name}() {{}}\n" for name in names)


def _edge(kind, names, module):
    return f'{kind} {{ {", ".join(names)} }} from "{module}";\n'


@pytest.fixture
def sources():
    b = bindings
    classifications = ("isCronRunSessionKey", "isDreamingNarrativeSessionStoreKey")
    archives = ("isCompactionCheckpointTranscriptFileName", "isSessionArchiveArtifactName",
                "isUsageCountedSessionTranscriptFileName", "parseUsageCountedSessionIdFromFileName")
    summaries = ("listSessionEntriesCore", "listSessionEntriesReadOnly")
    return {
        b._POLICY: _functions("resolveMemorySearchSourcePolicy"),
        b._CONFIG: _edge("import", ("resolveMemorySearchSourcePolicy",), "./memory-search-source-policy.js"),
        b._ELIGIBILITY: _functions("isMemorySessionIndexable") + _edge(
            "import", classifications, "openclaw/plugin-sdk/memory-core-host-engine-sessions"),
        b._SYNC: _edge("import", ("isMemorySessionIndexable", "resolveMemorySessionStartupState"),
                      "./manager-session-sync-state.js"),
        b._SDK: (
            _edge("export", classifications, "../../packages/memory-host-sdk/src/engine-sessions.js")
            + _functions("loadMemorySessionMetadata")
            + _edge("import", ("listSessionTranscriptInstances",), "../config/sessions/session-accessor.js")
        ),
        b._ENGINE: _edge("export", classifications, "./host/openclaw-runtime-session.js"),
        b._RUNTIME: (
            _edge("export", ("isCronRunSessionKey",), "../../../../src/sessions/session-key-utils.js")
            + _functions("isDreamingNarrativeSessionStoreKey")
            + _edge("export", summaries, "../../../../src/config/sessions/session-accessor.js")
            + _edge("export", archives, "../../../../src/config/sessions/artifacts.js")
            + _edge("import", ("readTranscriptExportSnapshotReadOnlySync",),
                    "../../../../src/config/sessions/session-accessor.js")
        ),
        b._SESSION_KEYS: _functions("isCronRunSessionKey"),
        b._CATALOG: (
            _functions("listSessionTranscriptCorpusEntriesForAgentSync",
                       "listSessionTranscriptCorpusEntriesForAgent")
            + "".join(f"function {name}() {{}}\n" for name in (
                "classifySessionEntry", "collectCronGeneratedSessionKeys", "toRetainedSessionCorpusEntry",
                "projectSessionTranscriptCorpusEntries"))
            + _edge("import", summaries, "./openclaw-runtime-session.js")
        ),
        b._FILES: (
            _functions("buildSessionEntry", "buildSessionEntryInProcess", "statSessionEntrySync",
                       "sessionPathForSessionIdentity")
            + "".join(f"function {name}() {{}}\n" for name in (
                "isDreamingNarrativeGeneratedRecord", "isCronRunGeneratedRecord", "resolveBuildSessionSqliteIdentity"))
            + _edge("import", ("listSessionTranscriptCorpusEntriesForAgentSync",), "./session-transcript-corpus.js")
            + _edge("import", ("collectRawSessionText", "projectSessionEntryRecord"), "./session-entry-projection.js")
            + _edge("import", ("classifySessionMessageOrigin",), "./session-provenance.js")
            + _edge("import", ("readTranscriptExportSnapshotReadOnlySync",), "./openclaw-runtime-session.js")
        ),
        b._PROJECTION: _functions("collectRawSessionText", "projectSessionEntryRecord"),
        b._PROVENANCE: _functions("classifySessionMessageOrigin"),
        b._ARTIFACTS: _functions(*archives),
        b._ACCESSOR: (
            _edge("export", summaries, "./session-accessor.entry.js")
            + _edge("export", ("readTranscriptExportSnapshotReadOnlySync",), "./session-accessor.transcript.js")
        ),
        b._INGESTION: (
            _functions("resolveAdmissionPolicy", "sessionExclusionReason")
            + _edge("import", ("asNullableRecord", "normalizeTrimmedStringList"),
                    "openclaw/plugin-sdk/string-coerce-runtime")
            + _edge("import", ("buildSessionEntry", "loadMemorySessionMetadata", "matchesSessionEntryPrefixHash",
                              "sessionPathForFile", "statSessionEntrySync"),
                    "openclaw/plugin-sdk/memory-core-host-engine-sessions")
            + _edge("import", ("listMemorySessionTombstones",), "./memory-entry-origins.js")
        ),
        b._STRING_SDK: (
            _edge("export", ("asNullableRecord",), "../../packages/normalization-core/src/record-coerce.js")
            + _edge("export", ("normalizeTrimmedStringList",),
                    "../../packages/normalization-core/src/string-normalization.js")
        ),
        b._RECORDS: _functions("asNullableRecord"),
        b._STRING_LIST: _functions("normalizeTrimmedStringList"),
        b._ORIGINS: _functions("listMemorySessionTombstones"),
    }


def _checkout(root, monkeypatch, sources):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root).decode().strip()

    git("init", "-q")
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled source owners without session-flow behavior")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        path: hashlib.sha256(source.encode()).hexdigest() for path, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    assert len(sources) == 19 and set(sources) == set(bindings._HASHES)
    return _checkout(tmp_path, monkeypatch, sources)


def test_source_policy_and_declaration_evidence_never_claims_real_session_admission(checkout, sources):
    before = deepcopy(sources)
    result = bindings.prepare_session_admission_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-session-admission-source-owners"
    assert result["reference"] == {"tag": "v2026.9.9", "commit": bindings._COMMIT}
    assert result["allowedResolutions"] == result["projectionEvidence"] == []
    owners = result["sourceOwnerEvidence"]
    assert [owner["module"] for owner in owners] == [
        bindings._POLICY, bindings._ELIGIBILITY, bindings._CATALOG, bindings._FILES, bindings._INGESTION,
    ]
    assert {source["path"] for owner in owners for source in owner["sources"]} == set(sources)
    for index, owner in enumerate(owners):
        assert owner["originalOwnerExecutionRequired"] is True
        assert owner["facadeInitializationBypassed"] is False
        assert owner["pureHelperComparison"] is (index in {0, 1, 4})
        assert owner["declarationEvidenceOnly"] is (index in {2, 3})
        for claim in ("wholeSessionFlowVerified", "realSqliteAdmissionVerified", "indexPublicationVerified",
                      "sessionVisibilityVerified", "fullManagerExecutionVerified", "fullHostOrchestrationVerified"):
            assert owner[claim] is False
    assert owners[-1]["comparedBindings"] == ["resolveAdmissionPolicy"]
    assert owners[-1]["declarationOnlyBindings"] == ["sessionExclusionReason"]
    assert owners[-1]["policyConsumer"] == "session-ingestion"


@pytest.mark.parametrize("module,old,new", [
    (bindings._POLICY, "export function resolveMemorySearchSourcePolicy", "function resolveMemorySearchSourcePolicy"),
    (bindings._CONFIG, "./memory-search-source-policy.js", "./other.js"),
    (bindings._ELIGIBILITY, "export function isMemorySessionIndexable", "function isMemorySessionIndexable"),
    (bindings._ELIGIBILITY, "import {", "import type {"),
    (bindings._SYNC, "{ isMemorySessionIndexable,", "{ Other as isMemorySessionIndexable,"),
    (bindings._SYNC, "./manager-session-sync-state.js", "./other.js"),
    (bindings._SDK, "../../packages/memory-host-sdk/src/engine-sessions.js", "./other.js"),
    (bindings._ENGINE, "./host/openclaw-runtime-session.js", "./other.js"),
    (bindings._RUNTIME, "../../../../src/sessions/session-key-utils.js", "./other.js"),
    (bindings._SESSION_KEYS, "export function isCronRunSessionKey", "function isCronRunSessionKey"),
    (bindings._CATALOG, "function classifySessionEntry", "function other"),
    (bindings._CATALOG, "function collectCronGeneratedSessionKeys", "function other"),
    (bindings._CATALOG, "function toRetainedSessionCorpusEntry", "function other"),
    (bindings._CATALOG, "function projectSessionTranscriptCorpusEntries", "function other"),
    (bindings._CATALOG, "./openclaw-runtime-session.js", "./other.js"),
    (bindings._RUNTIME, "../../../../src/config/sessions/session-accessor.js", "./other.js"),
    (bindings._ARTIFACTS, "export function isSessionArchiveArtifactName", "function isSessionArchiveArtifactName"),
    (bindings._FILES, "export function buildSessionEntryInProcess", "function buildSessionEntryInProcess"),
    (bindings._FILES, "function resolveBuildSessionSqliteIdentity", "function other"),
    (bindings._FILES, "./session-transcript-corpus.js", "./other.js"),
    (bindings._FILES, "./session-entry-projection.js", "./other.js"),
    (bindings._FILES, "./session-provenance.js", "./other.js"),
    (bindings._PROJECTION, "export function projectSessionEntryRecord", "function projectSessionEntryRecord"),
    (bindings._PROVENANCE, "export function classifySessionMessageOrigin", "function classifySessionMessageOrigin"),
    (bindings._ACCESSOR, "./session-accessor.transcript.js", "./other.js"),
    (bindings._INGESTION, "export function resolveAdmissionPolicy", "function resolveAdmissionPolicy"),
    (bindings._INGESTION, "export function sessionExclusionReason", "function sessionExclusionReason"),
    (bindings._INGESTION, "{ asNullableRecord,", "{ Other as asNullableRecord,"),
    (bindings._INGESTION, "./memory-entry-origins.js", "./other.js"),
    (bindings._STRING_SDK, "record-coerce.js", "other.js"),
    (bindings._STRING_LIST, "export function normalizeTrimmedStringList", "function normalizeTrimmedStringList"),
    (bindings._ORIGINS, "export function listMemorySessionTombstones", "function listMemorySessionTombstones"),
])
def test_reviewed_hashes_do_not_authorize_changed_catalog_provenance_or_import_owners(
    tmp_path, monkeypatch, sources, module, old, new,
):
    assert old in sources[module]
    sources[module] = sources[module].replace(old, new)
    with pytest.raises(bindings.SessionAdmissionBindingError):
        bindings.prepare_session_admission_bindings(_checkout(tmp_path, monkeypatch, sources))


@pytest.mark.parametrize("module,binding", [
    (bindings._POLICY, "resolveMemorySearchSourcePolicy"),
    (bindings._ELIGIBILITY, "isMemorySessionIndexable"),
    (bindings._INGESTION, "sessionExclusionReason"),
])
def test_ambiguous_owner_declarations_fail_closed(tmp_path, monkeypatch, sources, module, binding):
    sources[module] += _functions(binding)
    with pytest.raises(bindings.SessionAdmissionBindingError):
        bindings.prepare_session_admission_bindings(_checkout(tmp_path, monkeypatch, sources))


@pytest.mark.parametrize("mutation", [
    "dirty", "digest", "commit", "nested-root", "symlink", "ancestor-symlink", "committed-bytes",
])
def test_unowned_or_changed_session_owner_files_supply_no_provenance(checkout, monkeypatch, mutation):
    if mutation == "dirty":
        (checkout / bindings._CATALOG).write_text("// modified\n")
    elif mutation == "digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._CATALOG: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "packages"
    elif mutation in {"symlink", "ancestor-symlink"}:
        file = checkout / bindings._CATALOG
        target = file.parent if mutation == "ancestor-symlink" else file
        saved = target.with_name("saved-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=mutation == "ancestor-symlink")
    else:
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(bindings.SessionAdmissionBindingError):
        bindings.prepare_session_admission_bindings(checkout)


def test_missing_session_checkout_is_not_provenance(tmp_path):
    with pytest.raises(bindings.SessionAdmissionBindingError):
        bindings.prepare_session_admission_bindings(tmp_path / "absent")
