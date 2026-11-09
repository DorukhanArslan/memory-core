"""Non-executing declaration fixtures verify binding rejection and claim limits."""
from copy import deepcopy
import hashlib

import pytest

from equivalence import session_admission_runtime_bindings as owner_helpers
from equivalence import turn_trust_runtime_bindings as bindings


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def declaration_tree(tmp_path, monkeypatch):
    checkout, runtime = tmp_path / "source", tmp_path / "runtime"
    checkout.mkdir()
    runtime.mkdir()
    source_text = {path: "// declaration fixture " + path + "\n" for path in bindings.SOURCE_HASHES}
    for module, specifier, names, kind in bindings.SOURCE_LINKS:
        source_text[module] += kind + " { " + ", ".join(names) + " } from " + repr(specifier) + ";\n"
    for module, declaration, _kind in bindings.LITERAL_SOURCE_LINKS:
        source_text[module] += declaration + "\n"
    source_anchors = {path: ("// declaration fixture " + path,) for path in source_text}
    compiled_text = {path: "\n".join(anchors) for path, anchors in bindings.COMPILED_ANCHORS.items()}
    source_hashes = {path: _sha(text) for path, text in source_text.items()}
    compiled_hashes = {path: _sha(text) for path, text in compiled_text.items()}
    monkeypatch.setattr(bindings, "SOURCE_HASHES", source_hashes)
    monkeypatch.setattr(bindings, "SOURCE_ANCHORS", source_anchors)
    monkeypatch.setattr(bindings, "COMPILED_HASHES", compiled_hashes)
    for root, documents in ((checkout, source_text), (runtime, compiled_text)):
        for path, text in documents.items():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)

    def git(root, *arguments):
        assert root == checkout
        if arguments == ("rev-parse", "HEAD"):
            return bindings.REFERENCE_COMMIT.encode()
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(checkout).encode()
        if arguments == ("status", "--porcelain", "--untracked-files=no"):
            return b""
        if arguments[0] == "show":
            return source_text[arguments[1].removeprefix("HEAD:")].encode()
        raise AssertionError(arguments)

    monkeypatch.setattr(bindings, "_git", git)
    monkeypatch.setattr(owner_helpers, "_git", git)
    authority = {"kind": "non-executing-source-authority-fixture",
                 "relativePath": "src/agents/embedded-agent-runner/run/turn-taint-state.ts"}
    authority_calls = []

    def source_authority(path):
        authority_calls.append(path)
        return deepcopy(authority)

    monkeypatch.setattr(bindings, "prepare_turn_taint_source_authority", source_authority)
    monkeypatch.setattr(bindings, "prepare_transcript_boundary_runtime_bindings",
                        lambda source, compiled: {"kind": "non-executing-shared-owner-fixture"})
    return checkout, runtime, source_text, compiled_text, authority_calls


def _prepare(fixture):
    return bindings.prepare_turn_trust_runtime_bindings(*fixture[:2])


def test_mixed_profile_retains_complete_declarations_and_explicit_authority(declaration_tree):
    result = _prepare(declaration_tree)
    assert len(result["sourceBindings"]) == 27
    assert len(result["compiledBindings"]) == 19
    assert len(result["sourceImportLinks"]) == 21
    assert declaration_tree[-1] == [declaration_tree[0]]
    assert result["sourceTaintExecutionRequired"] is True
    assert result["wholeRuntimeCompiled"] is False
    assert result["sourceBuildReproduced"] is False
    assert result["privateStampExported"] is False
    assert result["privateStampCaller"] == "public original runAgentLoop"
    assert result["modelProviderTransportVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert result["indexManagerConstructed"] is False
    assert result["requiresCompleteOriginalToolResultBeforeAgentLoopProjection"] is True
    assert result["originalToolPrivatePreparerMutated"] is False
    assert result["originalToolBatchAdmissionVerified"] is False
    assert result["toolInvocationBoundary"] == "Sequential public execute delegation with unchanged arguments and original wrapped-tool receiver"
    assert result["declarationContext"]["embeddedRunLoopActuallyExecuted"] is False
    assert result["declarationContext"]["sourceDeclarationsAreRuntimeExecutionProof"] is False


@pytest.mark.parametrize("fault", ["pin", "dirty", "root"])
def test_pin_cleanliness_and_original_root_are_enforced(declaration_tree, monkeypatch, fault):
    original = bindings._git

    def git(root, *arguments):
        if fault == "pin" and arguments == ("rev-parse", "HEAD"):
            return b"0" * 40
        if fault == "dirty" and arguments[0] == "status":
            return b" M original-source.ts"
        if fault == "root" and arguments == ("rev-parse", "--show-toplevel"):
            return b"/another/reference"
        return original(root, *arguments)

    monkeypatch.setattr(bindings, "_git", git)
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


def test_source_taint_authority_rejection_cannot_be_ignored(declaration_tree, monkeypatch):
    def rejected(_):
        raise ValueError("An additional or changed source owner is forbidden")
    monkeypatch.setattr(bindings, "prepare_turn_taint_source_authority", rejected)
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


@pytest.mark.parametrize("side", ["source", "compiled"])
def test_reviewed_source_and_compiled_bytes_are_independent_authorities(declaration_tree, side):
    root = declaration_tree[0 if side == "source" else 1]
    path = next(iter(bindings.SOURCE_HASHES if side == "source" else bindings.COMPILED_HASHES))
    file = root / path
    file.write_text(file.read_text() + "\nchanged bytes")
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


def test_committed_source_bytes_must_match_working_tree(declaration_tree):
    relative = "src/agents/embedded-agent-runner/run/turn-taint-state.ts"
    declaration_tree[2][relative] += "\nchanged committed bytes"
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


@pytest.mark.parametrize("side", ["source", "compiled"])
def test_even_in_tree_symlink_owners_are_rejected(declaration_tree, side):
    root = declaration_tree[0 if side == "source" else 1]
    relative = next(iter(bindings.SOURCE_HASHES if side == "source" else bindings.COMPILED_HASHES))
    file = root / relative
    target = root / "physical-owner"
    target.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(target)
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


@pytest.mark.parametrize("side", ["source", "compiled"])
def test_hash_review_alone_does_not_admit_nonunique_linkage(declaration_tree, side):
    root = declaration_tree[0 if side == "source" else 1]
    documents = declaration_tree[2 if side == "source" else 3]
    hashes = bindings.SOURCE_HASHES if side == "source" else bindings.COMPILED_HASHES
    anchors = bindings.SOURCE_ANCHORS if side == "source" else bindings.COMPILED_ANCHORS
    relative = next(iter(hashes))
    documents[relative] += "\n" + anchors[relative][0]
    hashes[relative] = _sha(documents[relative])
    (root / relative).write_text(documents[relative])
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


@pytest.mark.parametrize("target", ["named-import", "export-all", "lazy-import"])
def test_original_caller_route_cannot_be_changed_by_only_rehashing(declaration_tree, target):
    if target == "named-import":
        module = "src/agents/embedded-agent-runner/run-loop.ts"
        declaration_tree[2][module] = declaration_tree[2][module].replace("./run/turn-taint-state.js", "./different.js")
    else:
        module, declaration, _ = bindings.LITERAL_SOURCE_LINKS[0 if target == "export-all" else 1]
        declaration_tree[2][module] = declaration_tree[2][module].replace(declaration, "// no original route")
    text = declaration_tree[2][module]
    bindings.SOURCE_HASHES[module] = _sha(text)
    (declaration_tree[0] / module).write_text(text)
    with pytest.raises(bindings.TurnTrustBindingError):
        _prepare(declaration_tree)


def test_critical_real_execution_profiles_keep_loop_wrapper_coding_and_storage_owners():
    assert set(bindings.AGENT_LOOP_ARTIFACTS) == {
        "dist/plugin-sdk/agent-core.js", "dist/agent-core-DrCkPXML.mjs", "dist/llm-ASoRyt-k.mjs"}
    assert {"dist/agent-tools-HIqp3eTk.mjs", "dist/core-coding-tools-DMPT-DjL.mjs",
            "dist/agent-tools.before-tool-call-Cg8vCu9u.mjs", "dist/agent-tools.read-ZzkirzL1.mjs",
            "dist/memory-artifact-provenance-DhnyWiV1.mjs", "dist/plugin-state-store-BPUaLoVD.mjs"} <= set(bindings.TURN_TOOL_ARTIFACTS)
    assert "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs" in bindings.PERSISTENCE_ARTIFACTS
    assert "dist/session-files-DVVT4Ngb.mjs" in bindings.READ_PROJECTION_ARTIFACTS
    assert len(bindings.REQUIRED_TURN_TRUST_ARTIFACTS) == len(set(bindings.REQUIRED_TURN_TRUST_ARTIFACTS))
    assert "dist/extensions/memory-core/manager-runtime.js" not in bindings.REQUIRED_TURN_TRUST_ARTIFACTS
