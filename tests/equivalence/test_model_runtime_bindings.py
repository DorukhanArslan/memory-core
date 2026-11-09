"""Non-executing independent declaration fixtures reject model-owner drift."""
from __future__ import annotations

import hashlib

import pytest

from equivalence import model_runtime_bindings as bindings
from equivalence import session_admission_runtime_bindings as owner_helpers


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def declarations(tmp_path, monkeypatch):
    checkout, runtime = tmp_path / "source", tmp_path / "release"
    checkout.mkdir()
    runtime.mkdir()
    source_text = {path: "// labelled original source declaration " + path + "\n"
                   for path in bindings.SOURCE_HASHES}
    for module, specifier, names, kind in bindings.SOURCE_LINKS:
        source_text[module] += kind + " { " + ", ".join(names) + " } from " + repr(specifier) + ";\n"
    for module, declaration, _kind in bindings.LITERAL_SOURCE_LINKS:
        source_text[module] += declaration + "\n"
    compiled_text = {path: "// labelled published declaration " + path + "\n"
                     for path in bindings.COMPILED_HASHES}
    for module, declaration in bindings.COMPILED_LINKS:
        compiled_text[module] += declaration + "\n"
    for side, documents, label in (("source", source_text, "original source"),
                                   ("compiled", compiled_text, "published")):
        monkeypatch.setattr(bindings, side.upper() + "_HASHES", {p: _sha(t) for p, t in documents.items()})
        monkeypatch.setattr(bindings, side.upper() + "_ANCHORS", {
            p: ("// labelled " + label + " declaration " + p,) for p in documents})
        root = checkout if side == "source" else runtime
        for relative, text in documents.items():
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)

    def git(root, *args):
        assert root == checkout
        if args == ("rev-parse", "HEAD"):
            return bindings.REFERENCE_COMMIT.encode()
        if args == ("rev-parse", "--show-toplevel"):
            return str(checkout).encode()
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return b""
        if args[0] == "show":
            return source_text[args[1].removeprefix("HEAD:")].encode()
        raise AssertionError(args)

    monkeypatch.setattr(bindings, "_git", git)
    monkeypatch.setattr(owner_helpers, "_git", git)
    return {"source": checkout, "compiled": runtime, "source_text": source_text,
            "compiled_text": compiled_text, "git": git}


def _prepare(fixture, *, helper=False):
    method = (bindings.prepare_model_tool_result_runtime_bindings if helper
              else bindings.prepare_model_session_runtime_bindings)
    return method(fixture["source"], fixture["compiled"])


def _reviewed_mutation(fixture, side, relative, text):
    """Bypass digest drift only to test a separately reviewed structural guard."""
    (fixture[side] / relative).write_text(text)
    fixture[side + "_text"][relative] = text
    getattr(bindings, side.upper() + "_HASHES")[relative] = _sha(text)


def test_session_manifest_retains_all_reviewed_owner_and_link_evidence(declarations):
    result = _prepare(declarations)
    assert result["kind"] == "official-release-model-session"
    assert len(result["sourceBindings"]) == 43
    assert len(result["compiledBindings"]) == 27
    assert len(result["sourceImportLinks"]) == 25
    assert len(result["compiledImportLinks"]) == 8
    assert result["requiredArtifactsByPhase"]["verify"] == list(bindings.REQUIRED_SESSION_READ_ARTIFACTS)
    assert result["requiredArtifactsByPhase"]["write"] == result["requiredArtifactsByPhase"]["continue"]
    assert set(bindings.REQUIRED_SESSION_WRITE_ARTIFACTS).issubset(result["requiredArtifactsByPhase"]["write"])
    assert result["agentSessionConstructedInPhases"] == ["write", "continue"]
    assert result["verifyPhaseApplicationWritesPermitted"] is False
    assert result["continuationHistoryTransportPermitted"] is False
    assert "no scripts, tool results, registry registrations or history" in result["verifyPhaseInput"]


def test_helper_scope_does_not_authenticate_or_claim_unexecuted_session_owners(declarations):
    result = _prepare(declarations, helper=True)
    assert result["kind"] == "official-release-model-tool-result"
    assert len(result["sourceBindings"]) == 12
    assert len(result["compiledBindings"]) == 6
    assert len(result["sourceImportLinks"]) == 7
    assert len(result["compiledImportLinks"]) == 2
    assert result["requiredArtifacts"] == list(bindings.REQUIRED_HELPER_ARTIFACTS)
    assert result["agentSessionConstructed"] is False
    assert result["sessionManagerConstructed"] is False
    assert result["completeReturnAndIdentityObservationsRequired"] is True
    assert "no persisted append claimed" in result["persistenceScope"]
    assert not any("resource-loader" in row["path"] or "session-manager" in row["path"]
                   for row in result["compiledBindings"])
    for side, selected in (("source", set(bindings.HELPER_SOURCE_PATHS)),
                           ("compiled", set(bindings.REQUIRED_HELPER_ARTIFACTS))):
        for relative in set(declarations[side + "_text"]) - selected:
            (declarations[side] / relative).unlink()
    assert _prepare(declarations, helper=True) == result


@pytest.mark.parametrize("helper", [False, True])
def test_profiles_cannot_grant_source_test_network_index_or_full_host_authority(declarations, helper):
    result = _prepare(declarations, helper=helper)
    for field in ("sourceBuildReproduced", "sourceExecutionPermitted", "indexManagerConstructed",
                  "memorySearchExecuted", "modelProviderNetworkVerified", "fullHostOrchestrationVerified",
                  "allSourcePolicyVerified", "privateMarkerFabricated", "globalRegistryResetPermitted",
                  "testEnvironmentSwitchPermitted"):
        assert result[field] is False
    assert result["wholeRuntimeCompiled"] is True
    assert result["referenceCommit"] == "bcfc88812a35243893585dbeca87ca41b48272ca"
    assert result["runtimeEngine"] == {"nodeVersion": "v24.16.0", "unicodeVersion": "17.0",
                                       "executableRealpathAndSha256Required": True, "icuVersionRequired": True}
    assert result["clock"] == {"owner": "node:test", "apis": ["Date"], "realTimersAndPerformance": True}
    assert result["registryIsolation"] == "fresh OS process for every case and every session phase"


@pytest.mark.parametrize("fault", ["pin", "dirty", "root"])
def test_wrong_pin_dirty_source_and_different_repository_are_rejected(declarations, monkeypatch, fault):
    def git(root, *args):
        if fault == "pin" and args == ("rev-parse", "HEAD"):
            return b"f" * 40
        if fault == "dirty" and args[0] == "status":
            return b" M source.ts"
        if fault == "root" and args == ("rev-parse", "--show-toplevel"):
            return b"/different/reference"
        return declarations["git"](root, *args)
    monkeypatch.setattr(bindings, "_git", git)
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("relative", tuple(bindings.SOURCE_HASHES))
def test_every_original_source_owner_is_pinned(declarations, relative):
    file = declarations["source"] / relative
    file.write_text(file.read_text() + "\nchanged")
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("relative", tuple(bindings.COMPILED_HASHES))
def test_every_published_artifact_is_separately_pinned(declarations, relative):
    file = declarations["compiled"] / relative
    file.write_text(file.read_text() + "\nchanged")
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


def test_committed_git_source_cannot_differ_from_working_bytes(declarations):
    relative = "src/agents/embedded-agent-tool-result-cache.ts"
    declarations["source_text"][relative] += "\nchanged committed content"
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("side", ["source", "compiled"])
@pytest.mark.parametrize("outside", [False, True])
def test_even_unchanged_symlinked_owners_are_rejected(declarations, tmp_path, side, outside):
    relative = next(iter(declarations[side + "_text"]))
    original = declarations[side] / relative
    target = (tmp_path if outside else declarations[side]) / "physical-owner"
    target.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(target)
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("side", ["source", "compiled"])
@pytest.mark.parametrize("fault", ["missing", "duplicate"])
def test_owner_anchor_must_be_present_and_unique_even_with_reviewed_hash(declarations, side, fault):
    relative = next(iter(declarations[side + "_text"]))
    text = declarations[side + "_text"][relative]
    anchor = getattr(bindings, side.upper() + "_ANCHORS")[relative][0]
    changed = text.replace(anchor, "removed original declaration") if fault == "missing" else text + anchor
    _reviewed_mutation(declarations, side, relative, changed)
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("edge", bindings.SOURCE_LINKS)
def test_every_original_named_import_export_is_authenticated(declarations, edge):
    module, specifier, names, kind = edge
    declaration = kind + " { " + ", ".join(names) + " } from " + repr(specifier) + ";\n"
    text = declarations["source_text"][module]
    changed = text.replace(declaration, declaration.replace(specifier, specifier + ".changed"))
    assert changed != text
    _reviewed_mutation(declarations, "source", module, changed)
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


def test_original_commented_config_export_is_preserved_and_required(declarations):
    module, declaration, _ = bindings.LITERAL_SOURCE_LINKS[0]
    text = declarations["source_text"][module]
    assert "@deprecated" in declaration
    _reviewed_mutation(declarations, "source", module, text.replace(declaration, declaration + declaration))
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


@pytest.mark.parametrize("edge", bindings.COMPILED_LINKS)
def test_every_published_import_link_is_required_even_with_reviewed_hash(declarations, edge):
    module, declaration = edge
    text = declarations["compiled_text"][module]
    _reviewed_mutation(declarations, "compiled", module, text.replace(declaration, declaration + declaration))
    with pytest.raises(bindings.ModelRuntimeBindingError):
        _prepare(declarations)


def test_genuine_sqlite_context_and_guard_owner_paths_remain_in_separate_phase_sets():
    read, write = set(bindings.REQUIRED_SESSION_READ_ARTIFACTS), set(bindings.REQUIRED_SESSION_WRITE_ARTIFACTS)
    assert {"dist/plugin-sdk/sqlite-runtime.js", "dist/openclaw-agent-db-DRy3ui_B.mjs",
            "dist/node-sqlite-DRQTiYwd.mjs", "dist/session-manager-a8MFS1Kk.mjs",
            "dist/session-accessor.sqlite-read-BsSfe2AE.mjs", "dist/session-BA9qunLx.mjs"} <= read
    assert {"dist/resource-loader-DhipPm1N.mjs", "dist/resource-loader-N7_h4_No.mjs",
            "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
            "dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs"} <= write
    assert not read & {"dist/resource-loader-DhipPm1N.mjs", "dist/resource-loader-N7_h4_No.mjs"}
    assert read | write <= set(bindings.COMPILED_HASHES)
    assert set(bindings.REQUIRED_HELPER_ARTIFACTS) <= set(bindings.COMPILED_HASHES)
