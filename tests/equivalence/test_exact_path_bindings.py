"""Exact-path binding guards; labelled source fixtures establish no behavioral parity."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import exact_path_bindings as bindings


@pytest.fixture
def sources():
    return {
        bindings._SEARCH: f'import {{ escapeRegExp }} from "{bindings._SPECIFIER}";\n',
        bindings._FACADE: 'export { escapeRegExp, unrelated } from "../utils.js";\n',
        bindings._UTILS: 'export { escapeRegExp } from "./shared/regexp.js";\n',
        bindings._REGEXP: 'export function escapeRegExp(value: string) { return value; }\n',
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
        "commit", "-qm", "Labelled exact-path binding fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    return _checkout(tmp_path, monkeypatch, sources)


def test_exact_path_projection_keeps_the_four_original_owners_and_limited_claims(checkout, sources):
    before = deepcopy(sources)
    result = bindings.prepare_exact_path_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-exact-path-binding-projection"
    assert result["reference"]["commit"] == bindings._COMMIT
    assert result["allowedResolutions"] == [{
        "parent": bindings._SEARCH, "specifier": bindings._SPECIFIER,
        "target": bindings._REGEXP, "bindings": ["escapeRegExp"],
    }]
    evidence, = result["projectionEvidence"]
    assert evidence["scope"] == "exact-path-query-and-sql-owners"
    assert evidence["facadeInitializationBypassed"] is True
    assert evidence["facadeExecutionVerified"] is False
    assert evidence["fullManagerExecutionVerified"] is False
    assert evidence["fullHostOrchestrationVerified"] is False
    assert [edge["path"] for edge in evidence["chain"]] == [
        bindings._SEARCH, bindings._FACADE, bindings._UTILS, bindings._REGEXP,
    ]
    assert [edge["kind"] for edge in evidence["chain"]] == [
        "import", "export", "export", "declaration",
    ]
    assert {row["path"] for row in evidence["sources"]} == set(sources)
    assert all(len(row["sha256"]) == 64 for row in evidence["sources"])


@pytest.mark.parametrize("mutation", [
    "import-alias", "import-type-only", "import-extra", "facade-owner",
    "facade-type-only", "facade-alias", "utils-owner", "utils-duplicate",
    "owner-not-exported", "owner-duplicate", "owner-missing",
])
def test_reviewed_bytes_still_require_the_unique_original_regexp_chain(
    tmp_path, monkeypatch, sources, mutation,
):
    if mutation == "import-alias":
        sources[bindings._SEARCH] = sources[bindings._SEARCH].replace(
            "escapeRegExp", "escapeRegExp as other",
        )
    elif mutation == "import-type-only":
        sources[bindings._SEARCH] = sources[bindings._SEARCH].replace("import {", "import type {")
    elif mutation == "import-extra":
        sources[bindings._SEARCH] = sources[bindings._SEARCH].replace(
            "escapeRegExp", "escapeRegExp, unreviewed",
        )
    elif mutation == "facade-owner":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("utils.js", "other.js")
    elif mutation == "facade-type-only":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("export {", "export type {")
    elif mutation == "facade-alias":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace(
            "escapeRegExp", "other as escapeRegExp",
        )
    elif mutation == "utils-owner":
        sources[bindings._UTILS] = sources[bindings._UTILS].replace("regexp.js", "other.js")
    elif mutation == "utils-duplicate":
        sources[bindings._UTILS] *= 2
    elif mutation == "owner-not-exported":
        sources[bindings._REGEXP] = sources[bindings._REGEXP].replace("export function", "function")
    elif mutation == "owner-duplicate":
        sources[bindings._REGEXP] *= 2
    else:
        sources[bindings._REGEXP] = ""
    root = _checkout(tmp_path, monkeypatch, sources)
    with pytest.raises(ValueError):
        bindings.prepare_exact_path_bindings(root)


@pytest.mark.parametrize("mutation", [
    "dirty", "wrong-digest", "wrong-commit", "nested-root", "symlink", "committed-bytes",
])
def test_changed_or_unowned_sources_cannot_authenticate_exact_path_projection(
    checkout, monkeypatch, mutation,
):
    if mutation == "dirty":
        (checkout / bindings._SEARCH).write_text("export const replacement = true;\n")
    elif mutation == "wrong-digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._REGEXP: "0" * 64})
    elif mutation == "wrong-commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation == "symlink":
        target = checkout / bindings._REGEXP
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
        bindings.prepare_exact_path_bindings(checkout)


def test_missing_reference_yields_no_exact_path_projection(tmp_path):
    with pytest.raises(ValueError):
        bindings.prepare_exact_path_bindings(tmp_path / "absent")
