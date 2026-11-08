"""Hybrid binding guards; labelled source fixtures establish no behavioral parity."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import hybrid_bindings as bindings


@pytest.fixture
def sources():
    name = bindings._NAME
    return {
        bindings._RANKING: f'import {{ {name} }} from "{bindings._SPECIFIER}";\n',
        bindings._FACADE: (
            f'export {{ {name}, unrelated }} '
            'from "../../packages/memory-host-sdk/src/engine-storage.js";\n'
        ),
        bindings._STORAGE: f'export {{ {name} }} from "./host/internal.js";\n',
        bindings._INTERNAL: f'export {{ {name} }} from "./curated-annotations.js";\n',
        bindings._ANNOTATIONS: f'export const {name} = "labelled-invalid-key";\n',
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
        "commit", "-qm", "Labelled hybrid binding fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    return _checkout(tmp_path, monkeypatch, sources)


def test_hybrid_projection_keeps_all_five_original_owners_and_limits_claims(checkout, sources):
    before = deepcopy(sources)
    result = bindings.prepare_hybrid_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-hybrid-binding-projection"
    assert result["reference"]["commit"] == bindings._COMMIT
    assert result["allowedResolutions"] == [{
        "parent": bindings._RANKING, "specifier": bindings._SPECIFIER,
        "target": bindings._ANNOTATIONS, "bindings": [bindings._NAME],
    }]
    evidence, = result["projectionEvidence"]
    assert evidence["scope"] == "hybrid-ranking-owners"
    assert evidence["facadeInitializationBypassed"] is True
    assert evidence["facadeExecutionVerified"] is False
    assert evidence["fullManagerExecutionVerified"] is False
    assert evidence["fullHostOrchestrationVerified"] is False
    assert [edge["path"] for edge in evidence["chain"]] == [
        bindings._RANKING, bindings._FACADE, bindings._STORAGE,
        bindings._INTERNAL, bindings._ANNOTATIONS,
    ]
    assert [edge["kind"] for edge in evidence["chain"]] == [
        "import", "export", "export", "export", "declaration",
    ]
    assert {row["path"] for row in evidence["sources"]} == set(sources)
    assert all(len(row["sha256"]) == 64 for row in evidence["sources"])


@pytest.mark.parametrize("mutation", [
    "import-alias", "import-type-only", "import-extra", "facade-owner",
    "facade-alias", "storage-type-only", "internal-owner", "internal-duplicate",
    "owner-not-exported", "owner-duplicate", "owner-missing",
])
def test_reviewed_bytes_still_require_the_unique_original_constant_chain(
    tmp_path, monkeypatch, sources, mutation,
):
    name = bindings._NAME
    if mutation == "import-alias":
        sources[bindings._RANKING] = sources[bindings._RANKING].replace(name, f"{name} as other")
    elif mutation == "import-type-only":
        sources[bindings._RANKING] = sources[bindings._RANKING].replace("import {", "import type {")
    elif mutation == "import-extra":
        sources[bindings._RANKING] = sources[bindings._RANKING].replace(name, f"{name}, unreviewed")
    elif mutation == "facade-owner":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("engine-storage.js", "other.js")
    elif mutation == "facade-alias":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace(name, f"other as {name}")
    elif mutation == "storage-type-only":
        sources[bindings._STORAGE] = sources[bindings._STORAGE].replace("export {", "export type {")
    elif mutation == "internal-owner":
        sources[bindings._INTERNAL] = sources[bindings._INTERNAL].replace("curated-annotations.js", "other.js")
    elif mutation == "internal-duplicate":
        sources[bindings._INTERNAL] *= 2
    elif mutation == "owner-not-exported":
        sources[bindings._ANNOTATIONS] = sources[bindings._ANNOTATIONS].replace("export const", "const")
    elif mutation == "owner-duplicate":
        sources[bindings._ANNOTATIONS] *= 2
    else:
        sources[bindings._ANNOTATIONS] = ""
    root = _checkout(tmp_path, monkeypatch, sources)
    with pytest.raises(ValueError):
        bindings.prepare_hybrid_bindings(root)


@pytest.mark.parametrize("mutation", [
    "dirty", "wrong-digest", "wrong-commit", "nested-root", "symlink", "committed-bytes",
])
def test_changed_or_unowned_sources_cannot_authenticate_hybrid_projection(
    checkout, monkeypatch, mutation,
):
    if mutation == "dirty":
        (checkout / bindings._RANKING).write_text("export const replacement = true;\n")
    elif mutation == "wrong-digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._ANNOTATIONS: "0" * 64})
    elif mutation == "wrong-commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation == "symlink":
        target = checkout / bindings._ANNOTATIONS
        saved = checkout / "saved-owner.ts"
        saved.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(saved)
    else:
        original = bindings._git

        def forged_git(root, *args):
            if args[0] == "show":
                return b"wrong committed bytes"
            return original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(ValueError):
        bindings.prepare_hybrid_bindings(checkout)


def test_missing_reference_yields_no_hybrid_projection(tmp_path):
    with pytest.raises(ValueError):
        bindings.prepare_hybrid_bindings(tmp_path / "absent")
