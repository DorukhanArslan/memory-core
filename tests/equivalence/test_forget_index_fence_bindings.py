"""Pure declaration/capability checks; these tests never load an original engine."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from equivalence import forget_index_fence_bindings as bindings
from equivalence.search_contract_runtime_bindings import SearchContractRuntimeBindingError


def test_conflicting_composed_authorities_fail_closed():
    with pytest.raises(ValueError, match="Conflicting forget/index fence owner pin"):
        bindings._merged_hashes({"owner.ts": "a" * 64}, {"owner.ts": "b" * 64})
    assert bindings._merged_hashes({"owner.ts": "a" * 64}, {"owner.ts": "a" * 64}) == {
        "owner.ts": "a" * 64,
    }


def test_route_graphs_have_separate_authenticated_main_and_worker_owners():
    assert set(bindings.REQUIRED_MAIN_ARTIFACTS_BY_ROUTE) == {
        "manager", "producer", "forget", "promotion", "tools", "state", "reopen",
    }
    assert set(bindings.REQUIRED_WORKER_ARTIFACTS_BY_ROUTE) == {
        "preparation", "publication", "retrieval", "state",
    }
    assert set(bindings.SOURCE_HASHES) == set(bindings.SOURCE_ANCHORS)
    assert set(bindings.COMPILED_HASHES) == set(bindings.COMPILED_ANCHORS)
    assert set(bindings.REQUIRED_LOADED_ARTIFACTS) <= set(bindings.COMPILED_HASHES)
    assert "dist/cli.runtime-CVRN4xUp.mjs" in bindings.REQUIRED_MAIN_ARTIFACTS_BY_ROUTE["forget"]
    assert "dist/memory-entry-origins-BCQSIB3X.mjs" in bindings.REQUIRED_MAIN_ARTIFACTS_BY_ROUTE["forget"]
    assert "dist/plugin-sdk/session-transcript-runtime.js" in bindings.REQUIRED_MAIN_ARTIFACTS_BY_ROUTE["producer"]
    assert "dist/memory-session-tombstones-B1AGruLs.mjs" in bindings.REQUIRED_WORKER_ARTIFACTS_BY_ROUTE["publication"]
    assert "dist/extensions/memory-core/memory-search.worker.js" in bindings.REQUIRED_WORKER_ARTIFACTS_BY_ROUTE["retrieval"]
    for manifest in (bindings.SOURCE_HASHES, bindings.COMPILED_HASHES):
        for name, digest in manifest.items():
            assert not Path(name).is_absolute() and ".." not in Path(name).parts
            assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")


@pytest.mark.parametrize("text", ["", "import { x } from './changed.js';", "edge\nedge\n"])
def test_missing_changed_or_ambiguous_literal_import_is_rejected(text):
    with pytest.raises(bindings.ForgetIndexFenceBindingError, match="import edge changed"):
        bindings._literal_links({"owner.mjs": text}, {"owner.mjs": ("edge",)})


def test_literal_import_evidence_retains_complete_original_declaration():
    declaration = 'import { x as original } from "./owner.mjs";'
    evidence = bindings._literal_links({"entry.mjs": "// prefix\n" + declaration + "\n"},
                                       {"entry.mjs": (declaration,)})
    assert evidence == [{"path": "entry.mjs", "declaration": declaration, "kind": "import", "line": 2,
                         "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()}]


def test_owner_authentication_rejects_changed_bytes_and_escaped_symlinks(tmp_path):
    owner = tmp_path / "owner.mjs"
    owner.write_text("original declaration\n")
    digest = hashlib.sha256(owner.read_bytes()).hexdigest()
    anchors = {"owner.mjs": ("original declaration",)}
    bindings._owners(tmp_path, {"owner.mjs": digest}, anchors, committed=False)
    owner.write_text("changed declaration\n")
    with pytest.raises(SearchContractRuntimeBindingError, match="reviewed bytes"):
        bindings._owners(tmp_path, {"owner.mjs": digest}, anchors, committed=False)
    owner.unlink()
    outside = tmp_path / "outside.mjs"
    outside.write_text("original declaration\n")
    owner.symlink_to(outside)
    with pytest.raises(SearchContractRuntimeBindingError, match="escaped"):
        bindings._owners(tmp_path, {"owner.mjs": digest}, anchors, committed=False)


def test_wrong_source_commit_rejected_before_any_composed_owner_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(bindings, "_git", lambda *_: b"unreviewed-commit\n")
    calls = []
    monkeypatch.setattr(bindings.query, "prepare_query_sync_outcomes_bindings",
                        lambda *_: calls.append("should not read"))
    with pytest.raises(bindings.ForgetIndexFenceBindingError, match="unchanged pinned source"):
        bindings.prepare_forget_index_fence_bindings(tmp_path, tmp_path)
    assert calls == []


def _stub_declarations(monkeypatch):
    """Labelled non-executing owners, not a claim about any original behavior."""
    monkeypatch.setattr(bindings, "_git", lambda *_: (bindings.REFERENCE_COMMIT + "\n").encode())
    empty = {"sourceImportLinks": []}
    monkeypatch.setattr(bindings.query, "prepare_query_sync_outcomes_bindings", lambda *_: deepcopy(empty))
    monkeypatch.setattr(bindings.sessions, "prepare_session_admission_runtime_bindings", lambda *_: deepcopy(empty))
    monkeypatch.setattr(bindings.promotion_family, "prepare_family_bindings", lambda *_: {
        "originalOwnerBindings": deepcopy(empty), "additionalSourceImportLinks": [],
    })
    monkeypatch.setattr(bindings.durable, "prepare_durable_session_runtime_bindings", lambda *_: deepcopy(empty))
    monkeypatch.setattr(bindings, "_owners", lambda root, hashes, anchors, *, committed: (
        {}, [{"path": name, "sha256": digest} for name, digest in hashes.items()]))
    monkeypatch.setattr(bindings.sessions, "_named_link", lambda *args, **kwargs: {"kind": "labelled-nonexecuting-edge"})
    monkeypatch.setattr(bindings, "_literal_links", lambda *args, **kwargs: [])


def test_declaration_result_does_not_claim_execution_or_acceptance(monkeypatch, tmp_path):
    _stub_declarations(monkeypatch)
    result = bindings.prepare_forget_index_fence_bindings(tmp_path, tmp_path)
    for flag in ("sourceBuildReproduced", "sourceFallbackAllowed", "fullManagerExecutionVerified",
                 "fullHostOrchestrationVerified", "providerTransportVerified"):
        assert result[flag] is False
    assert result["covers"] == []
    assert result["entrypoints"]["forget"]["directForgetExportAvailable"] is False
    assert result["entrypoints"]["forget"]["export"] == "runMemoryForget"
    assert result["entrypoints"]["append"]["export"] == "appendSessionTranscriptMessageByIdentityStrict"
    assert result["requiredWorkerArtifactsByRoute"]["publication"] != result["requiredWorkerArtifactsByRoute"]["retrieval"]
    assert result["workerRequiredByProfile"] == {bindings.OPERATION: True}


def test_unpinned_required_artifact_cannot_be_reported_as_authenticated(monkeypatch, tmp_path):
    _stub_declarations(monkeypatch)
    monkeypatch.setattr(bindings, "REQUIRED_LOADED_ARTIFACTS", ("dist/unreviewed-worker.js",))
    with pytest.raises(bindings.ForgetIndexFenceBindingError, match="no authenticated release owner"):
        bindings.prepare_forget_index_fence_bindings(tmp_path, tmp_path)
