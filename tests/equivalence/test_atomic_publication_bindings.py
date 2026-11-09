"""Synthetic owner guards never execute originals or establish publication parity."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from equivalence import atomic_publication_bindings as bindings
from equivalence.reference_bindings import _NAMED_FROM, _runtime_names


def _labelled_sources(anchors, specifications):
    values = {path: "// Labelled original owner fixture, never executed.\n" + "\n".join(items) + "\n"
              for path, items in anchors.items()}
    for module, specifier, pairs, kind in specifications:
        present = [match for match in _NAMED_FROM.finditer(values[module])
                   if match["kind"] == kind and match["specifier"] == specifier]
        if present:
            assert len(present) == 1 and all(pair in _runtime_names(present[0]) for pair in pairs)
            continue
        names = ", ".join(left if left == right else f"{left} as {right}" for left, right in pairs)
        values[module] += f'{kind} {{ {names} }} from "{specifier}";\n'
    return values


@pytest.fixture
def texts():
    return {
        "source": _labelled_sources(bindings.SOURCE_ANCHORS, bindings.SOURCE_LINKS),
        "compiled": _labelled_sources(bindings.COMPILED_ANCHORS, bindings.COMPILED_LINKS),
        "external": _labelled_sources(bindings.EXTERNAL_ANCHORS, bindings.EXTERNAL_LINKS),
    }


def _trees(root, monkeypatch, texts):
    checkout, runtime = root / "reference", root / "runtime/node_modules/openclaw"
    owners = {"source": checkout, "compiled": runtime, "external": runtime.parent / "@openclaw/fs-safe"}
    for kind, files in texts.items():
        for path, content in files.items():
            file = owners[kind] / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        monkeypatch.setattr(bindings, f'{kind.upper()}_HASHES', {
            path: hashlib.sha256(content.encode()).hexdigest() for path, content in files.items()
        })
    package_metadata = {
        bindings.FS_SAFE_PACKAGE: {"name": "@openclaw/fs-safe", "version": "0.21.1",
                                  "exports": {"./root": {"default": "./dist/root.js"}}},
        bindings.NATIVE_PACKAGE: {"name": "@openclaw/fs-safe-linux-x64-gnu", "version": "0.21.1",
                                  "main": "fs-safe-native.node", "os": ["linux"], "cpu": ["x64"], "libc": ["glibc"]},
    }
    package_hashes = {}
    for package, metadata in package_metadata.items():
        file = root / "runtime" / package / "package.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(metadata))
        package_hashes[package] = hashlib.sha256(file.read_bytes()).hexdigest()
    monkeypatch.setattr(bindings, "PACKAGE_HASHES", package_hashes)
    native = root / "runtime" / bindings.NATIVE_PACKAGE / "fs-safe-native.node"
    native.write_bytes(b"\x7fELFLabelled non-executable native binding fixture")
    monkeypatch.setattr(bindings, "NATIVE_BINARY_SHA256", hashlib.sha256(native.read_bytes()).hexdigest())

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout).decode().strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Labelled atomic owners")
    monkeypatch.setattr(bindings, "REFERENCE_COMMIT", git("rev-parse", "HEAD"))
    return checkout, runtime


@pytest.fixture
def trees(tmp_path, monkeypatch, texts):
    return _trees(tmp_path, monkeypatch, texts)


def test_exact_three_entries_and_native_dependency_are_explicit_without_execution_claims(trees):
    result = bindings.prepare_atomic_publication_bindings(*trees)
    assert result["kind"] == "official-release-atomic-publication-owners"
    assert result["entrypoints"] == bindings.ENTRYPOINTS
    assert result["entrypoints"]["atomic-append-runtime"] == {
        "package": "node_modules/@openclaw/fs-safe", "path": "dist/root.js", "export": "root",
    }
    assert len(result["sourceBindings"]) == 8 and len(result["compiledBindings"]) == 8
    assert len(result["externalRuntimeBindings"]) == 30 and len(result["nativeBinaryBindings"]) == 1
    for key in ("sourceBuildReproduced", "providerTransportVerified", "managerExecutionVerified",
                "indexExecutionVerified", "workerExecutionVerified", "fullAgentToolExecutionVerified",
                "fullPromotionSchedulerExecutionVerified", "receiptPhysicalInterchangeabilityClaimed"):
        assert result[key] is False
    assert result["nativeResolution"]["actualResolutionAndNapiCallsRequired"] is True
    assert result["nativeResolution"]["nativeModeOverridePermitted"] is False
    assert result["nativeResolution"]["testLoaderPermitted"] is False
    for operation, owners in bindings.REQUIRED_ARTIFACTS_BY_OPERATION.items():
        assert result["requiredLoadedOwnersByOperation"][operation] == [
            {"package": package, "path": path} for package, path in owners
        ]
    assert bindings.NATIVE_BINDING_OWNER not in bindings.REQUIRED_ARTIFACTS_BY_OPERATION["atomic-append-runtime"]
    assert bindings.NATIVE_BINDING_OWNER in bindings.REQUIRED_ARTIFACTS_BY_OPERATION["atomic-bootstrap-runtime"]
    assert len(result["sourceImportLinks"]) == 9 and len(result["compiledImportLinks"]) == 10
    assert len(result["externalImportLinks"]) == 22


OWNERS = [(kind, path) for kind, hashes in (("source", bindings.SOURCE_HASHES),
          ("compiled", bindings.COMPILED_HASHES), ("external", bindings.EXTERNAL_HASHES)) for path in hashes]


@pytest.mark.parametrize("kind,path", OWNERS)
def test_each_changed_original_owner_is_rejected(trees, kind, path):
    checkout, runtime = trees
    root = {"source": checkout, "compiled": runtime, "external": runtime.parent / "@openclaw/fs-safe"}[kind]
    with (root / path).open("a") as file:
        file.write("\n// changed original bytes\n")
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


@pytest.mark.parametrize("kind,path", OWNERS)
def test_reviewed_hash_cannot_remove_original_owner_declaration(tmp_path, monkeypatch, texts, kind, path):
    anchors = getattr(bindings, f'{kind.upper()}_ANCHORS')
    texts[kind][path] = texts[kind][path].replace(anchors[path][0], "// removed original declaration")
    trees = _trees(tmp_path, monkeypatch, texts)
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


@pytest.mark.parametrize("kind,specification", [
    ("source", bindings.SOURCE_LINKS[0]),
    ("compiled", bindings.COMPILED_LINKS[0]),
    ("external", bindings.EXTERNAL_LINKS[1]),
])
@pytest.mark.parametrize("mutation", ["owner", "alias", "type", "duplicate"])
def test_reviewed_bytes_still_require_exact_actual_named_owner_edge(tmp_path, monkeypatch, texts, kind, specification, mutation):
    module, specifier, pairs, declaration_kind = specification
    source = texts[kind][module]
    match = next(match for match in _NAMED_FROM.finditer(source)
                 if match["kind"] == declaration_kind and match["specifier"] == specifier)
    original = match[0]
    if mutation == "owner":
        replacement = original.replace(specifier, "./unrelated-owner.js")
    elif mutation == "alias":
        left, right = pairs[0]
        replacement = original.replace(left if left == right else f"{left} as {right}", f"{left} as unrelatedOwner")
    elif mutation == "type":
        replacement = original.replace(declaration_kind, declaration_kind + " type", 1)
    else:
        replacement = original + "\n" + original
    texts[kind][module] = source[:match.start()] + replacement + source[match.end():]
    trees = _trees(tmp_path, monkeypatch, texts)
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


@pytest.mark.parametrize("part", ["root-entry", "native-binary", "external-package", "native-package"])
def test_exact_external_entry_binary_and_package_cannot_borrow_symlink_identity(trees, tmp_path, part):
    _, runtime = trees
    relative = {
        "root-entry": "@openclaw/fs-safe/dist/root.js", "native-binary": "@openclaw/fs-safe-linux-x64-gnu/fs-safe-native.node",
        "external-package": "@openclaw/fs-safe/package.json", "native-package": "@openclaw/fs-safe-linux-x64-gnu/package.json",
    }[part]
    path = runtime.parent / relative
    real = tmp_path / "borrowed-original"
    path.rename(real)
    path.symlink_to(real)
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


@pytest.mark.parametrize("part", ["native-main", "native-os", "external-root-export"])
def test_reviewed_package_hash_cannot_select_another_entry_or_platform(trees, monkeypatch, part):
    _, runtime = trees
    package = bindings.FS_SAFE_PACKAGE if part == "external-root-export" else bindings.NATIVE_PACKAGE
    file = runtime.parent.parent / package / "package.json"
    metadata = json.loads(file.read_text())
    if part == "native-main":
        metadata["main"] = "another.node"
    elif part == "native-os":
        metadata["os"] = ["darwin"]
    else:
        metadata["exports"]["./root"]["default"] = "./dist/unrelated.js"
    file.write_text(json.dumps(metadata))
    hashes = deepcopy(bindings.PACKAGE_HASHES)
    hashes[package] = hashlib.sha256(file.read_bytes()).hexdigest()
    monkeypatch.setattr(bindings, "PACKAGE_HASHES", hashes)
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


def test_binary_changed_bytes_are_rejected_and_do_not_count_as_module_execution(trees):
    _, runtime = trees
    (runtime.parent / "@openclaw/fs-safe-linux-x64-gnu/fs-safe-native.node").write_bytes(b"\x7fELFchanged binary")
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


def test_exact_git_identity_is_required_even_with_unmodified_owner_files(trees, monkeypatch):
    monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    with pytest.raises(bindings.AtomicPublicationBindingError):
        bindings.prepare_atomic_publication_bindings(*trees)


def test_mutating_a_report_cannot_redirect_later_original_entry_metadata(trees):
    result = bindings.prepare_atomic_publication_bindings(*trees)
    result['entrypoints']['atomic-append-runtime']['path'] = 'dist/unrelated.js'
    assert bindings.prepare_atomic_publication_bindings(*trees)['entrypoints']['atomic-append-runtime']['path'] == 'dist/root.js'
