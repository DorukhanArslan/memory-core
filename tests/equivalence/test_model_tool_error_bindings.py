"""Independent non-executing owner declarations for complete tool failures."""
import hashlib

import pytest

from equivalence import model_tool_error_bindings as bindings
from equivalence import session_admission_runtime_bindings as helpers


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def trees(tmp_path, monkeypatch):
    roots = (tmp_path / "source", tmp_path / "release")
    documents = [{p: "// fixture " + p + "\n" for p in hashes}
                 for hashes in (bindings.SOURCE_HASHES, bindings.COMPILED_HASHES)]
    for module, specifier, names, kind in bindings.SOURCE_LINKS:
        documents[0][module] += kind + " { " + ", ".join(names) + " } from " + repr(specifier) + ";\n"
    for module, declaration in bindings.COMPILED_LINKS:
        documents[1][module] += declaration + "\n"
    for root, texts, prefix in zip(roots, documents, ("SOURCE", "COMPILED"), strict=True):
        root.mkdir()
        monkeypatch.setattr(bindings, prefix + "_HASHES", {p: _sha(t) for p, t in texts.items()})
        monkeypatch.setattr(bindings, prefix + "_ANCHORS", {p: ("// fixture " + p,) for p in texts})
        for relative, text in texts.items():
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)

    def git(root, *args):
        assert root == roots[0]
        if args == ("rev-parse", "HEAD"):
            return bindings.REFERENCE_COMMIT.encode()
        if args == ("rev-parse", "--show-toplevel"):
            return str(root).encode()
        if args[0] == "status":
            return b""
        if args[0] == "show":
            return documents[0][args[1].removeprefix("HEAD:")].encode()
        raise AssertionError(args)

    monkeypatch.setattr(bindings, "_git", git)
    monkeypatch.setattr(helpers, "_git", git)
    return roots, documents, git


def test_complete_error_owner_manifest_is_narrow_and_retains_all_authority(trees):
    value = bindings.prepare_model_tool_error_runtime_bindings(*trees[0])
    assert [len(value[key]) for key in ("sourceBindings", "compiledBindings", "sourceImportLinks", "compiledImportLinks")] == [13, 11, 5, 5]
    assert value["requiredArtifacts"] == list(bindings.REQUIRED_ERROR_ARTIFACTS)
    assert value["errorOwnPropertiesAndCausesRetained"] is True
    assert value["sameThrownErrorReceiptsRequired"] is True
    for field in ("sourceBuildReproduced", "sourceExecutionPermitted", "indexManagerConstructed", "memoryIndexSearchClaimed",
                  "fullHostOrchestrationVerified", "modelProviderNetworkVerified", "registryRevisionOffsetsPermitted", "testEnvironmentSwitchPermitted"):
        assert value[field] is False


@pytest.mark.parametrize("fault", ["pin", "dirty", "root"])
def test_changed_source_identity_is_rejected(trees, monkeypatch, fault):
    def git(root, *args):
        if fault == "pin" and args == ("rev-parse", "HEAD"):
            return b"0" * 40
        if fault == "dirty" and args[0] == "status":
            return b" M original.ts"
        if fault == "root" and args == ("rev-parse", "--show-toplevel"):
            return b"/different/reference"
        return trees[2](root, *args)
    monkeypatch.setattr(bindings, "_git", git)
    with pytest.raises(bindings.ModelToolErrorBindingError):
        bindings.prepare_model_tool_error_runtime_bindings(*trees[0])


@pytest.mark.parametrize("side,relative", [(0, p) for p in bindings.SOURCE_HASHES] + [(1, p) for p in bindings.COMPILED_HASHES])
def test_every_source_and_release_owner_is_pinned(trees, side, relative):
    file = trees[0][side] / relative
    file.write_text(file.read_text() + "\nchanged")
    with pytest.raises(bindings.ModelToolErrorBindingError):
        bindings.prepare_model_tool_error_runtime_bindings(*trees[0])


@pytest.mark.parametrize("side", [0, 1])
def test_same_bytes_cannot_hide_symlinked_owner(trees, side):
    root, documents = trees[0][side], trees[1][side]
    file = root / next(iter(documents))
    target = root / "physical-owner"
    target.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(target)
    with pytest.raises(bindings.ModelToolErrorBindingError):
        bindings.prepare_model_tool_error_runtime_bindings(*trees[0])


@pytest.mark.parametrize("side,edge", [(0, edge) for edge in bindings.SOURCE_LINKS] + [(1, edge) for edge in bindings.COMPILED_LINKS])
def test_import_edges_are_structurally_required_even_with_reviewed_digest(trees, side, edge):
    module = edge[0]
    if side == 0:
        _, specifier, names, kind = edge
        declaration = kind + " { " + ", ".join(names) + " } from " + repr(specifier) + ";\n"
    else:
        declaration = edge[1]
    changed = trees[1][side][module].replace(declaration, "// removed linkage\n")
    trees[1][side][module] = changed
    (trees[0][side] / module).write_text(changed)
    getattr(bindings, "SOURCE_HASHES" if side == 0 else "COMPILED_HASHES")[module] = _sha(changed)
    with pytest.raises(bindings.ModelToolErrorBindingError):
        bindings.prepare_model_tool_error_runtime_bindings(*trees[0])
