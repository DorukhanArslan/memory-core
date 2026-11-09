"""Non-executing fixtures guard the single unchanged source-owner capability."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence import turn_trust_source_authority as authority
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError, ROOT


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    checkout = tmp_path / "reference"
    file = checkout / authority.SOURCE_PATH
    file.parent.mkdir(parents=True)
    # Deliberately not executable taint code. Only filesystem/hash authority is
    # tested here; no source fixture is imported into a native process.
    raw = b"// Non-executing labelled source-authority fixture.\n"
    file.write_bytes(raw)
    monkeypatch.setattr(authority, "SOURCE_SHA256", _sha(raw))
    committed = {"raw": raw}

    def git(root, *arguments):
        assert root == checkout
        if arguments == ("rev-parse", "HEAD"):
            return authority.REFERENCE_COMMIT.encode()
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(checkout).encode()
        if arguments == ("status", "--porcelain", "--untracked-files=no"):
            return b""
        if arguments == ("show", "HEAD:" + authority.SOURCE_PATH):
            return committed["raw"]
        raise AssertionError(arguments)

    monkeypatch.setattr(authority, "_git", git)
    return checkout, file, committed


def test_fixed_allowlist_is_one_exact_original_source_owner():
    assert authority.REFERENCE_COMMIT == "bcfc88812a35243893585dbeca87ca41b48272ca"
    assert authority.SOURCE_PATH == "src/agents/embedded-agent-runner/run/turn-taint-state.ts"
    assert authority.SOURCE_SHA256 == "7fd28e4064c555256feeaace2dbabb8b08d31ce1e0d7baaf1a1d7b20380723fe"


def test_capability_contains_only_complete_canonical_pinned_identity(source_tree):
    checkout, file, _ = source_tree
    value = authority.prepare_turn_taint_source_authority(checkout)
    assert value == {"kind": "pinned-reference-source", "checkout": str(checkout), "path": str(file),
                     "relativePath": authority.SOURCE_PATH, "sha256": authority.SOURCE_SHA256,
                     "referenceCommit": authority.REFERENCE_COMMIT, "export": "createAgentTurnTaintState",
                     "zeroRuntimeDependencies": True}
    assert authority.validate_turn_taint_source_authority(deepcopy(value)) == value


@pytest.mark.parametrize("field,value", [
    ("kind", "official-compiled-release"), ("path", "/tmp/another-owner.ts"),
    ("relativePath", "src/agents/another-owner.ts"), ("sha256", "0" * 64),
    ("referenceCommit", "0" * 40), ("export", "withAssistantTurnTaint"),
    ("zeroRuntimeDependencies", False), ("zeroRuntimeDependencies", 1),
    ("zeroRuntimeDependencies", "true"), ("additionalSource", "/tmp/second-owner.ts"),
])
def test_additional_paths_or_changed_source_identity_are_rejected(source_tree, field, value):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    capability[field] = value
    with pytest.raises(ValueError):
        authority.validate_turn_taint_source_authority(capability)


@pytest.mark.parametrize("field", ["path", "sha256", "export", "relativePath", "referenceCommit", "zeroRuntimeDependencies"])
def test_incomplete_authority_is_rejected(source_tree, field):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    capability.pop(field)
    with pytest.raises(ValueError):
        authority.validate_turn_taint_source_authority(capability)


@pytest.mark.parametrize("value", [None, [], {}, {"checkout": 1}])
def test_source_authority_requires_a_structured_explicit_checkout(value):
    with pytest.raises(ValueError):
        authority.validate_turn_taint_source_authority(value)


@pytest.mark.parametrize("fault", ["pin", "dirty", "root"])
def test_reference_pin_cleanliness_and_root_are_enforced(source_tree, monkeypatch, fault):
    original = authority._git

    def git(root, *arguments):
        if fault == "pin" and arguments == ("rev-parse", "HEAD"):
            return b"0" * 40
        if fault == "dirty" and arguments[0] == "status":
            return b" M src/another-owner.ts"
        if fault == "root" and arguments == ("rev-parse", "--show-toplevel"):
            return b"/another/reference"
        return original(root, *arguments)

    monkeypatch.setattr(authority, "_git", git)
    with pytest.raises(ValueError):
        authority.prepare_turn_taint_source_authority(source_tree[0])


@pytest.mark.parametrize("side", ["working", "committed"])
def test_working_and_committed_original_bytes_both_require_reviewed_hash(source_tree, side):
    if side == "working":
        source_tree[1].write_bytes(source_tree[1].read_bytes() + b"changed")
    else:
        source_tree[2]["raw"] += b"changed"
    with pytest.raises(ValueError, match="reviewed bytes"):
        authority.prepare_turn_taint_source_authority(source_tree[0])


@pytest.mark.parametrize("part", ["file", "parent"])
def test_symlink_owners_are_rejected_even_when_bytes_and_target_are_owned(source_tree, part):
    checkout, file, _ = source_tree
    if part == "file":
        target = checkout / "physical-source.ts"
        target.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(target)
    else:
        parent = file.parent
        target = checkout / "physical-source-parent"
        parent.rename(target)
        parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        authority.prepare_turn_taint_source_authority(checkout)


def _transport(tmp_path, *, source=None):
    runtime = tmp_path / "runtime/node_modules/openclaw"
    runtime.mkdir(parents=True)
    relative = "dist/extensions/memory-core/manager-runtime.js"
    file = runtime / relative
    file.parent.mkdir(parents=True)
    file.write_bytes(b"// Non-executing release transport fixture.\n")
    config = {"runtimeRoot": str(runtime), "packages": [{"location": "node_modules/openclaw",
              "directory": str(runtime), "files": [{"path": relative, "sha256": _sha(file.read_bytes())}]}]}
    adapters = {file.name: _sha(file.read_bytes()) for file in (ROOT / "equivalence").glob("*.mjs")}
    return ReleaseOracleExecution(config, adapters, turn_taint_source=source)


def _wire(operation):
    case = {"id": "non-executing-source-transport", "operation": operation, "input": {}}
    result = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": True, "result": {"provider": "none"}}]}
    return case, result


@pytest.mark.parametrize("operation", ["index-lifecycle-runtime", "search-contract-runtime", "get-contract-runtime"])
def test_approved_source_context_cannot_be_used_by_existing_compiled_profiles(source_tree, tmp_path, operation):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    with _transport(tmp_path, source=capability) as execution:
        case, result = _wire(operation)
        with pytest.raises(RuntimeOracleError, match="restricted.*mixed turn-trust"):
            execution.collect(result, [case])


def test_mixed_profile_cannot_execute_without_explicit_source_capability(tmp_path):
    with _transport(tmp_path) as execution:
        case, result = _wire("turn-trust-runtime")
        with pytest.raises(RuntimeOracleError, match="restricted.*mixed turn-trust"):
            execution.collect(result, [case])


@pytest.mark.parametrize("operation", ["index-lifecycle-runtime", "search-contract-runtime", "get-contract-runtime"])
def test_reference_source_trace_is_rejected_by_default_profiles(tmp_path, operation):
    with _transport(tmp_path) as execution:
        case, result = _wire(operation)
        # Profile-specific shape admission occurs before trace validation.
        if operation in {"search-contract-runtime", "get-contract-runtime"}:
            case["input"]["kind"] = "tool"
        events = [{"event": "bootstrap", "pid": 111, "threadId": 0, "isMainThread": True,
                   "contextSha256": execution._context_digest, "preloadSha256": execution._preload_digest,
                   "fetchDenied": True, "providerMode": "none"},
                  {"event": "load", "pid": 111, "threadId": 0, "kind": "reference-source",
                   "path": "/unapproved/reference/source.ts", "relativePath": authority.SOURCE_PATH,
                   "sha256": authority.SOURCE_SHA256, "referenceCommit": authority.REFERENCE_COMMIT}]
        (execution.trace_directory / "111-0.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
        with pytest.raises(RuntimeOracleError, match="source import escaped.*authority"):
            execution.collect(result, [case])


@pytest.mark.parametrize("fault", ["removed-source", "changed-source", "changed-pin", "dirty-tree"])
def test_context_constructor_revalidates_saved_source_capability(source_tree, tmp_path, monkeypatch, fault):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    execution = _transport(tmp_path, source=capability)
    original = authority._git
    if fault == "removed-source":
        source_tree[1].unlink()
    elif fault == "changed-source":
        source_tree[1].write_bytes(b"changed before context entry")
    else:
        def changed(root, *arguments):
            if fault == "changed-pin" and arguments == ("rev-parse", "HEAD"):
                return b"0" * 40
            if fault == "dirty-tree" and arguments[0] == "status":
                return b" M src/staged-owner.ts"
            return original(root, *arguments)
        monkeypatch.setattr(authority, "_git", changed)
    with pytest.raises(RuntimeOracleError):
        with execution:
            pytest.fail("A stale saved source capability entered a process context")


@pytest.mark.parametrize("fault", ["working-source", "committed-source", "pin", "dirty"])
def test_collect_revalidates_source_bytes_and_reference_after_context_entry(source_tree, tmp_path, monkeypatch, fault):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    with _transport(tmp_path, source=capability) as execution:
        original = authority._git
        if fault == "working-source":
            source_tree[1].write_bytes(b"source changed while process ran")
        elif fault == "committed-source":
            source_tree[2]["raw"] += b"committed source changed"
        else:
            def changed(root, *arguments):
                if fault == "pin" and arguments == ("rev-parse", "HEAD"):
                    return b"0" * 40
                if fault == "dirty" and arguments[0] == "status":
                    return b"M  src/staged-owner.ts"
                return original(root, *arguments)
            monkeypatch.setattr(authority, "_git", changed)
        case, result = _wire("turn-trust-runtime")
        with pytest.raises(RuntimeOracleError):
            execution.collect(result, [case])


def test_constructor_copies_capability_before_caller_changes_its_dictionary(source_tree, tmp_path):
    capability = authority.prepare_turn_taint_source_authority(source_tree[0])
    execution = _transport(tmp_path, source=capability)
    capability["path"] = "/unapproved/second-source.ts"
    capability["additionalSource"] = "/unapproved/third-source.ts"
    with execution:
        assert execution.turn_taint_source == authority.prepare_turn_taint_source_authority(source_tree[0])
        assert execution._context["approvedReferenceSources"] == [execution.turn_taint_source]
