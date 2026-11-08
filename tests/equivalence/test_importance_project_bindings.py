"""Labelled import-provenance fixtures establish no ranking behavior credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import importance_project_bindings as bindings


@pytest.fixture
def sources():
    return {
        bindings._READER: 'import { INVALID_PROJECT_ANNOTATION_KEY } from "./internal.js";\n',
        bindings._INTERNAL: (
            'export { INVALID_PROJECT_ANNOTATION_KEY, unrelated } from "./curated-annotations.js";\n'
        ),
        bindings._ANNOTATIONS: 'export const INVALID_PROJECT_ANNOTATION_KEY = "labelled";\n',
    }


def _checkout(root: Path, monkeypatch, sources):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root).decode().strip()

    git("init", "-q")
    for relative, source in sources.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled importance/project binding fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    return _checkout(tmp_path, monkeypatch, sources)


def test_reader_constant_projection_authenticates_original_owners_without_broad_facade(
    checkout, sources,
):
    before = deepcopy(sources)
    result = bindings.prepare_importance_project_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-importance-project-binding-projection"
    assert result["reference"]["commit"] == bindings._COMMIT
    assert result["allowedResolutions"] == [{
        "parent": bindings._READER, "specifier": "./internal.js",
        "target": bindings._ANNOTATIONS, "bindings": [bindings._NAME],
    }]
    evidence, = result["projectionEvidence"]
    assert evidence["scope"] == "importance-project-recall-reader"
    assert evidence["facadeInitializationBypassed"] is True
    assert evidence["facadeExecutionVerified"] is False
    assert evidence["fullManagerExecutionVerified"] is False
    assert evidence["fullHostOrchestrationVerified"] is False
    assert [edge["path"] for edge in evidence["chain"]] == [
        bindings._READER, bindings._INTERNAL, bindings._ANNOTATIONS,
    ]
    assert [edge["kind"] for edge in evidence["chain"]] == ["import", "export", "declaration"]
    assert {row["path"] for row in evidence["sources"]} == set(sources)


@pytest.mark.parametrize("mutation", [
    "import-alias", "import-type-only", "import-extra", "import-owner",
    "reexport-owner", "reexport-type-only", "reexport-alias", "reexport-duplicate",
    "owner-not-exported", "owner-duplicate", "owner-missing",
])
def test_even_reviewed_bytes_must_keep_the_unique_original_constant_chain(
    tmp_path, monkeypatch, sources, mutation,
):
    reader, internal, owner = bindings._READER, bindings._INTERNAL, bindings._ANNOTATIONS
    if mutation == "import-alias":
        sources[reader] = sources[reader].replace(bindings._NAME, "Other as " + bindings._NAME)
    elif mutation == "import-type-only":
        sources[reader] = sources[reader].replace("import {", "import type {")
    elif mutation == "import-extra":
        sources[reader] = sources[reader].replace(bindings._NAME, bindings._NAME + ", unreviewed")
    elif mutation == "import-owner":
        sources[reader] = sources[reader].replace("./internal.js", "./other.js")
    elif mutation == "reexport-owner":
        sources[internal] = sources[internal].replace("curated-annotations.js", "other.js")
    elif mutation == "reexport-type-only":
        sources[internal] = sources[internal].replace("export {", "export type {")
    elif mutation == "reexport-alias":
        sources[internal] = sources[internal].replace(bindings._NAME, "Other as " + bindings._NAME)
    elif mutation == "reexport-duplicate":
        sources[internal] *= 2
    elif mutation == "owner-not-exported":
        sources[owner] = sources[owner].replace("export const", "const")
    elif mutation == "owner-duplicate":
        sources[owner] *= 2
    else:
        sources[owner] = ""
    root = _checkout(tmp_path, monkeypatch, sources)
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_bindings(root)


@pytest.mark.parametrize("mutation", [
    "dirty", "digest", "commit", "nested-root", "symlink", "committed-bytes",
])
def test_unowned_source_bytes_cannot_authenticate_recall_reader_bindings(
    checkout, monkeypatch, mutation,
):
    if mutation == "dirty":
        (checkout / bindings._READER).write_text("// changed\n")
    elif mutation == "digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._ANNOTATIONS: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "packages"
    elif mutation == "symlink":
        file = checkout / bindings._ANNOTATIONS
        saved = file.with_name("saved-owner.ts")
        saved.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(saved)
    else:
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_bindings(checkout)


def test_missing_reference_does_not_create_importance_project_evidence(tmp_path):
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_bindings(tmp_path / "absent")
