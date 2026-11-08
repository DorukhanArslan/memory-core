"""Vector binding provenance guards; labelled source fixtures grant no parity credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import vector_bindings as bindings


@pytest.fixture
def sources():
    return {
        bindings._VECTOR: (
            f'import {{ cosineSimilarity, decodeMemoryEmbedding }} from "{bindings._SPECIFIER}";\n'
        ),
        bindings._SHARED: f'import {{ truncateUtf16Safe }} from "{bindings._SPECIFIER}";\n',
        bindings._FACADE: (
            'export { cosineSimilarity, decodeMemoryEmbedding, parseEmbedding } '
            'from "../../packages/memory-host-sdk/src/host/embedding-vector.js";\n'
            'export { truncateUtf16Safe } from "@openclaw/normalization-core/utf16-slice";\n'
        ),
        bindings._CODEC: (
            'export function cosineSimilarity() {}\n'
            'export function decodeMemoryEmbedding() {}\n'
            'export function parseEmbedding() {}\n'
        ),
        bindings._UTF16: 'export function truncateUtf16Safe() {}\n',
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
        "commit", "-qm", "Labelled vector binding fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    return _checkout(tmp_path, monkeypatch, sources)


def test_vector_bindings_preserve_exact_owners_and_limit_claims(checkout, sources):
    before = deepcopy(sources)
    result = bindings.prepare_vector_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-vector-binding-projection"
    assert result["reference"]["commit"] == bindings._COMMIT
    assert result["allowedResolutions"] == [
        {"parent": bindings._VECTOR, "specifier": bindings._SPECIFIER,
         "target": bindings._CODEC, "bindings": ["cosineSimilarity", "decodeMemoryEmbedding"]},
        {"parent": bindings._SHARED, "specifier": bindings._SPECIFIER,
         "target": bindings._UTF16, "bindings": ["truncateUtf16Safe"]},
    ]
    for evidence in result["projectionEvidence"]:
        assert evidence["scope"] == "portable-cpu-vector-candidates"
        assert evidence["facadeInitializationBypassed"] is True
        assert evidence["facadeExecutionVerified"] is False
        assert evidence["fullManagerExecutionVerified"] is False
        assert evidence["acceleratedKnnExecutionVerified"] is False
        assert [row["kind"] for row in evidence["chain"][:2]] == ["import", "export"]
        assert all(len(row["sha256"]) == 64 for row in evidence["sources"])


@pytest.mark.parametrize("mutation", [
    "import-alias", "import-type-only", "import-extra", "facade-owner",
    "facade-alias", "facade-type-only", "facade-duplicate",
    "owner-not-exported", "owner-duplicate", "projection-owner-missing",
])
def test_even_reviewed_fixture_bytes_cannot_replace_or_ambiguate_a_binding(
    tmp_path, monkeypatch, sources, mutation,
):
    if mutation == "import-alias":
        sources[bindings._VECTOR] = sources[bindings._VECTOR].replace(
            "cosineSimilarity,", "cosineSimilarity as score,")
    elif mutation == "import-type-only":
        sources[bindings._VECTOR] = sources[bindings._VECTOR].replace("import {", "import type {")
    elif mutation == "import-extra":
        sources[bindings._VECTOR] = sources[bindings._VECTOR].replace(
            "decodeMemoryEmbedding }", "decodeMemoryEmbedding, unreviewed }")
    elif mutation == "facade-owner":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("embedding-vector.js", "other.js")
    elif mutation == "facade-alias":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace(
            "cosineSimilarity,", "other as cosineSimilarity,")
    elif mutation == "facade-type-only":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("export {", "export type {")
    elif mutation == "facade-duplicate":
        sources[bindings._FACADE] *= 2
    elif mutation == "owner-not-exported":
        sources[bindings._CODEC] = sources[bindings._CODEC].replace("export function cosine", "function cosine")
    elif mutation == "owner-duplicate":
        sources[bindings._CODEC] += 'export function cosineSimilarity() {}\n'
    else:
        sources[bindings._UTF16] = ""
    root = _checkout(tmp_path, monkeypatch, sources)
    with pytest.raises(ValueError):
        bindings.prepare_vector_bindings(root)


@pytest.mark.parametrize("mutation", ["dirty", "wrong-digest", "wrong-commit", "nested-root", "symlink"])
def test_changed_or_unowned_source_cannot_produce_binding_evidence(checkout, monkeypatch, mutation):
    if mutation == "dirty":
        (checkout / bindings._VECTOR).write_text("export const replacement = true;\n")
    elif mutation == "wrong-digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._CODEC: "0" * 64})
    elif mutation == "wrong-commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    else:
        target = checkout / bindings._CODEC
        saved = checkout / "saved-owner.ts"
        saved.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(saved)
    with pytest.raises(ValueError):
        bindings.prepare_vector_bindings(checkout)


def test_missing_reference_produces_no_vector_projection(tmp_path):
    with pytest.raises(ValueError):
        bindings.prepare_vector_bindings(tmp_path / "absent")
