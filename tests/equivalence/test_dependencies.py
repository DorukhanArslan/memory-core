"""Reference artifacts are authenticated independently from source comparisons."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from equivalence import dependencies as deps


def _integrity(raw):
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")


def _tar(files, *, special=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, content in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if special is not None:
            archive.addfile(special)
    return output.getvalue()


LITERAL_PATCH = (b"diff --git a/dist/index.js b/dist/index.js\nindex " + b"0" * 40 + b".." + b"1" * 40
                 + b" 100644\n--- a/dist/index.js\n+++ b/dist/index.js\n@@ -1 +1 @@\n"
                 b"-export const realArtifact = true;\n+export const realArtifact = 'patched';\n")


@pytest.fixture
def packages(tmp_path, monkeypatch):
    destination = tmp_path / "npm"
    raw_by_package = {}
    sections = []
    snapshots = []
    edges = {
        "string-width": {"get-east-asian-width": "1.7.0", "strip-ansi": "7.2.0"},
        "strip-ansi": {"ansi-regex": "6.3.0"},
        "execa": {
            "@sindresorhus/merge-streams": "4.0.0", "figures": "6.1.0", "get-stream": "9.0.1",
            "human-signals": "8.0.1", "is-plain-obj": "4.1.0", "is-stream": "4.0.1",
            "npm-run-path": "6.0.0", "pretty-ms": "9.3.1", "signal-exit": "4.1.0",
            "strip-final-newline": "4.0.0", "which-command": "0.1.0", "yoctocolors": "2.2.0",
        },
        "figures": {"is-unicode-supported": "2.1.0"},
        "get-stream": {"@sec-ant/readable-stream": "0.4.1", "is-stream": "4.0.1"},
        "npm-run-path": {"path-key": "4.0.0", "unicorn-magic": "0.3.0"},
        "pretty-ms": {"parse-ms": "4.0.0"},
        "mdast-util-from-markdown": {"micromark": "4.0.2"},
        "micromark": {"debug": "4.4.3"},
        "debug": {"ms": "2.1.3"},
        "@openclaw/proxyline": {"undici": "8.10.2"},
    }
    contexts = {name: "(supports-color@10.2.2)" for name in (
        "mdast-util-from-markdown", "micromark", "debug",
    )}
    contexts["@openclaw/proxyline"] = f"(patch_hash={deps.PACKAGE_PATCHES[0][3]})(undici@8.10.2)"
    for name, version in (
        ("@openclaw/fs-safe", "0.21.1"),
        ("@openclaw/fs-safe-linux-x64-gnu", "0.21.1"),
        *deps.ADDITIONAL_PACKAGES,
    ):
        package = {"name": name, "version": version}
        if name in edges:
            package["dependencies"] = {key: "^" + value for key, value in edges[name].items()}
        root = name.removeprefix("@types/") if name.startswith("@types/") else "package"
        raw = _tar({
            f"{root}/package.json": json.dumps(package).encode(),
            f"{root}/dist/index.js": b"export const realArtifact = true;\n",
        })
        raw_by_package[name] = raw
        quote = "'" if name.startswith("@") else ""
        sections.append(f"  {quote}{name}@{version}{quote}:\n"
                        f"    resolution: {{integrity: {_integrity(raw)}}}\n")
        key = f"  {quote}{name}@{version}{contexts.get(name, '')}{quote}:"
        if name in edges:
            snapshots.append(key + "\n    dependencies:\n" + "".join(
                f"      {dependency}: {version}{contexts.get(dependency, '')}\n"
                for dependency, version in edges[name].items()
            ))
        else:
            snapshots.append(key + " {}\n")
    lock = ("packages:\n" + "\n".join(sections) + "\nsnapshots:\n" + "\n".join(snapshots)).encode()
    monkeypatch.setattr(deps, "_committed_lock", lambda _: ("a" * 40, lock))
    monkeypatch.setattr(deps, "_committed_patch", lambda _checkout, _lock, name, _version:
                        (LITERAL_PATCH, {"path": deps.PACKAGE_PATCHES[0][2], "sha256": deps._sha(LITERAL_PATCH)})
                        if name == "@openclaw/proxyline" else None)
    monkeypatch.setattr(deps, "_target", lambda: "linux-x64-gnu")
    calls = []

    def download(name, version):
        calls.append((name, version))
        return raw_by_package[name]

    monkeypatch.setattr(deps, "_download", download)
    return destination, raw_by_package, calls


def test_setup_authenticates_and_extracts_only_pinned_artifacts_without_scripts(packages):
    destination, _, calls = packages
    config = deps.prepare_dependencies(Path("unused"), destination, download=True)
    assert calls == [("@openclaw/fs-safe", "0.21.1"),
                     ("@openclaw/fs-safe-linux-x64-gnu", "0.21.1"), *deps.ADDITIONAL_PACKAGES]
    assert config["kind"] == "verified-npm-artifacts"
    assert config["referenceCommit"] == "a" * 40
    assert all(len(package["files"]) == 2 for package in config["packages"])
    before = len(calls)
    assert deps.prepare_dependencies(Path("unused"), destination) == config
    assert len(calls) == before


def test_verification_never_downloads_missing_artifacts(packages):
    destination, _, calls = packages
    with pytest.raises(deps.DependencyError, match="archive is missing"):
        deps.prepare_dependencies(Path("unused"), destination)
    assert calls == []
    assert not destination.exists()


@pytest.mark.parametrize("change", [
    "unknown", "wrong-fs-safe-version", "wrong-p-map-version", "wrong-kysely-version",
    "missing-kysely", "duplicate-kysely", "wrong-registry", "not-an-object",
    "wrong-string-width-version", "wrong-width-dependency-version", "missing-width-dependency",
    "wrong-zod-version", "missing-zod", "wrong-json5-version", "wrong-commander-version",
    "wrong-typebox-version", "missing-typebox",
    "wrong-patch-hash", "missing-patch", "unknown-patch",
])
def test_setup_rejects_packages_and_versions_outside_the_authorized_list(
    packages, tmp_path, monkeypatch, change,
):
    destination, _, calls = packages
    manifest = json.loads((deps.ROOT / "equivalence/dependencies.json").read_text())
    if change == "unknown":
        manifest["additionalPackages"].append({"name": "another-package", "version": "1.0.0"})
    elif change == "wrong-fs-safe-version":
        # This older version also occurs in upstream's lockfile; its presence
        # there does not authorize it for this source oracle.
        manifest["version"] = "0.12.0"
    elif change == "wrong-p-map-version":
        manifest["additionalPackages"][0]["version"] = "7.0.7"
    elif change == "wrong-kysely-version":
        manifest["additionalPackages"][1]["version"] = "0.29.5"
    elif change == "missing-kysely":
        manifest["additionalPackages"].pop(1)
    elif change == "duplicate-kysely":
        manifest["additionalPackages"].append(dict(manifest["additionalPackages"][1]))
    elif change == "wrong-registry":
        manifest["registry"] = "https://registry.example.invalid"
    elif change == "wrong-string-width-version":
        next(package for package in manifest["additionalPackages"]
             if package["name"] == "string-width")["version"] = "4.2.3"
    elif change == "wrong-width-dependency-version":
        next(package for package in manifest["additionalPackages"]
             if package["name"] == "get-east-asian-width")["version"] = "1.6.0"
    elif change == "missing-width-dependency":
        manifest["additionalPackages"] = [package for package in manifest["additionalPackages"]
                                          if package["name"] != "strip-ansi"]
    elif change == "wrong-zod-version":
        next(package for package in manifest["additionalPackages"]
             if package["name"] == "zod")["version"] = "4.6.4"
    elif change == "missing-zod":
        manifest["additionalPackages"] = [package for package in manifest["additionalPackages"]
                                          if package["name"] != "zod"]
    elif change in {"wrong-json5-version", "wrong-commander-version", "wrong-typebox-version"}:
        name = change.removeprefix("wrong-").removesuffix("-version")
        next(package for package in manifest["additionalPackages"]
             if package["name"] == name)["version"] = "0.0.0"
    elif change == "missing-typebox":
        manifest["additionalPackages"] = [package for package in manifest["additionalPackages"]
                                          if package["name"] != "typebox"]
    elif change == "wrong-patch-hash":
        manifest["patches"][0]["sha256"] = "0" * 64
    elif change == "missing-patch":
        manifest.pop("patches")
    elif change == "unknown-patch":
        manifest["patches"].append({"name": "another-package", "version": "1.0.0"})
    else:
        manifest = []
    root = tmp_path / "suite"
    (root / "equivalence").mkdir(parents=True)
    (root / "equivalence/dependencies.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(deps, "ROOT", root)
    with pytest.raises(deps.DependencyError, match="manifest is invalid"):
        deps.prepare_dependencies(Path("unused"), destination, download=True)
    assert calls == []
    assert not destination.exists()


def test_corrupt_archive_is_rejected_before_publication(packages):
    destination, raw, _ = packages
    raw["@openclaw/fs-safe"] = b"corrupt archive bytes"
    with pytest.raises(deps.DependencyError, match="integrity check"):
        deps.prepare_dependencies(Path("unused"), destination, download=True)
    assert not destination.exists()


@pytest.mark.parametrize("change", ["bytes", "missing", "extra", "symlink-file", "symlink-dir"])
def test_installed_file_tampering_blocks_verification_without_repair(packages, change):
    destination, _, calls = packages
    config = deps.prepare_dependencies(Path("unused"), destination, download=True)
    directory = Path(config["packages"][0]["directory"])
    target = directory / "dist/index.js"
    if change == "bytes":
        target.write_bytes(b"export const replaced = true;\n")
    elif change == "missing":
        target.unlink()
    elif change == "extra":
        (directory / "surprise.js").write_bytes(b"not in authenticated archive")
    elif change == "symlink-file":
        target.unlink()
        target.symlink_to(directory / "package.json")
    else:
        target.unlink()
        (directory / "dist").rmdir()
        (directory / "dist").symlink_to(directory)
    before = len(calls)
    with pytest.raises(deps.DependencyError):
        deps.prepare_dependencies(Path("unused"), destination, download=True)
    assert len(calls) == before
    if change == "bytes":
        assert target.read_bytes() == b"export const replaced = true;\n"


def test_archived_bytes_are_reauthenticated_on_each_verification(packages):
    destination, _, _ = packages
    deps.prepare_dependencies(Path("unused"), destination, download=True)
    archive = next((destination / "archives").iterdir())
    archive.write_bytes(b"changed after initial authentication")
    with pytest.raises(deps.DependencyError, match="integrity check"):
        deps.prepare_dependencies(Path("unused"), destination)


def test_patched_package_retains_original_archive_integrity_and_authenticates_derived_bytes(packages):
    destination, raw, calls = packages
    config = deps.prepare_dependencies(Path("unused"), destination, download=True)
    package = next(item for item in config["packages"] if item["name"] == "@openclaw/proxyline")
    assert package["integrity"] == _integrity(raw[package["name"]])
    assert package["patch"] == {"path": deps.PACKAGE_PATCHES[0][2], "sha256": deps._sha(LITERAL_PATCH)}
    target = Path(package["directory"]) / "dist/index.js"
    assert target.read_bytes() == b"export const realArtifact = 'patched';\n"
    target.write_bytes(b"export const realArtifact = true;\n")
    before = len(calls)
    with pytest.raises(deps.DependencyError, match="Installed dependency bytes differ"):
        deps.prepare_dependencies(Path("unused"), destination, download=True)
    assert target.read_bytes() == b"export const realArtifact = true;\n"
    assert len(calls) == before


@pytest.mark.parametrize("change", ["context", "old-count", "new-offset", "traversal", "new-file", "mode", "duplicate"])
def test_literal_dependency_patch_rejects_inexact_hunks_and_unsafe_file_operations(change):
    files = {"dist/index.js": b"export const realArtifact = true;\n"}
    patch = LITERAL_PATCH
    if change == "context":
        patch = patch.replace(b"-export const realArtifact = true;", b"-export const realArtifact = false;")
    elif change == "old-count":
        patch = patch.replace(b"@@ -1 +1 @@", b"@@ -1,2 +1 @@")
    elif change == "new-offset":
        patch = patch.replace(b"@@ -1 +1 @@", b"@@ -1 +2 @@")
    elif change == "traversal":
        patch = patch.replace(b"dist/index.js", b"../index.js")
    elif change == "new-file":
        files = {}
    elif change == "mode":
        patch = patch.replace(b"100644", b"100755")
    else:
        patch += patch
    before = dict(files)
    with pytest.raises(deps.DependencyError, match="unsupported or mismatched literal hunks"):
        deps._apply_literal_patch(files, patch)
    assert files == before


def test_literal_dependency_patch_preserves_missing_final_newlines_and_unmodified_files(monkeypatch):
    prefix = LITERAL_PATCH.split(b"@@ ", 1)[0]
    patch = prefix + (b"@@ -1 +1 @@\n-old\n\\ No newline at end of file\n"
                      b"+new\n\\ No newline at end of file\n")
    files = {"dist/index.js": b"old", "untouched.js": b"stable\n"}
    assert deps._apply_literal_patch(files, patch) == {"dist/index.js": b"new", "untouched.js": b"stable\n"}
    monkeypatch.setattr(deps, "MAX_PATCH_BYTES", 1)
    with pytest.raises(deps.DependencyError, match="patch exceeds the size limit"):
        deps._apply_literal_patch(files, patch)


@pytest.mark.parametrize("name", ["package/../escape", "/package/absolute", "package/./bad", "other/file", "package\\escape"])
def test_authenticated_tarball_cannot_escape_or_alias_paths(name):
    raw = _tar({"package/package.json": b"{}", name: b"payload"})
    with pytest.raises(deps.DependencyError, match="unsafe path"):
        deps._archive_files(raw, _integrity(raw))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_authenticated_tarball_rejects_nonregular_entries(kind):
    info = tarfile.TarInfo("package/dist/linked.js")
    info.type = kind
    info.linkname = "../../escape"
    raw = _tar({"package/package.json": b"{}"}, special=info)
    with pytest.raises(deps.DependencyError, match="non-regular"):
        deps._archive_files(raw, _integrity(raw))


def test_definitelytyped_prefix_requires_the_exact_requested_package_and_a_single_root():
    raw = _tar({"mdast/package.json": b"{}", "mdast/index.d.ts": b"export {};"})
    assert deps._archive_files(raw, _integrity(raw), "@types/mdast") == {
        "package.json": b"{}", "index.d.ts": b"export {};",
    }
    for name in ("", "mdast", "@types/unist", "@types/../mdast"):
        with pytest.raises(deps.DependencyError, match="unsafe path"):
            deps._archive_files(raw, _integrity(raw), name)
    mixed = _tar({"mdast/package.json": b"{}", "package/extra.js": b"payload"})
    with pytest.raises(deps.DependencyError, match="mixed package roots"):
        deps._archive_files(mixed, _integrity(mixed), "@types/mdast")


def test_authenticated_archive_size_and_extraction_size_are_bounded(monkeypatch):
    raw = _tar({"package/package.json": b"{}", "package/large.js": b"12345"})
    monkeypatch.setattr(deps, "MAX_EXTRACTED_BYTES", 3)
    with pytest.raises(deps.DependencyError, match="extracted size"):
        deps._archive_files(raw, _integrity(raw))
    monkeypatch.setattr(deps, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(deps.DependencyError, match="archive exceeds"):
        deps._archive_files(raw, _integrity(raw))


def test_exact_lock_resolution_is_required():
    lock = b"  p-map@7.0.8:\n    resolution: {integrity: sha512-AAAA==}\n"
    assert deps._integrity(lock, "p-map", "7.0.8") == "sha512-AAAA=="
    with pytest.raises(deps.DependencyError, match="uniquely pinned"):
        deps._integrity(lock, "p-map", "7.0.7")
    with pytest.raises(deps.DependencyError, match="uniquely pinned"):
        deps._integrity(lock + lock, "p-map", "7.0.8")


def test_runtime_edges_come_from_project_snapshots_in_a_multi_document_lock():
    lock = b"""---
packages:
  manager@1.0.0:
    resolution: {integrity: sha512-AAAA==}
snapshots:
  manager@1.0.0: {}
---
packages:
  string-width@8.2.2:
    resolution: {integrity: sha512-BBBB==}
snapshots:
  string-width@8.2.2:
    dependencies:
      get-east-asian-width: 1.7.0
      strip-ansi: 7.2.0
  strip-ansi@7.2.0:
    dependencies:
      ansi-regex: 6.3.0
"""
    assert deps._runtime_dependencies(lock, "string-width", "8.2.2") == {
        "get-east-asian-width": "1.7.0", "strip-ansi": "7.2.0",
    }
    assert deps._runtime_dependencies(lock, "strip-ansi", "7.2.0") == {"ansi-regex": "6.3.0"}
    with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
        deps._runtime_dependencies(lock, "string-width", "4.2.3")
    duplicate = lock + b"---\nsnapshots:\n  string-width@8.2.2: {}\n"
    with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
        deps._runtime_dependencies(duplicate, "string-width", "8.2.2")


def test_peer_context_snapshots_require_one_exact_version_and_reject_ambiguous_contexts():
    lock = b"""snapshots:
  mdast-util-from-markdown@2.0.3(supports-color@10.2.2):
    dependencies:
      micromark: 4.0.2(supports-color@10.2.2)
    transitivePeerDependencies:
      - supports-color
"""
    assert deps._runtime_dependencies(lock, "mdast-util-from-markdown", "2.0.3") == {
        "micromark": "4.0.2",
    }
    duplicate = lock + b"  mdast-util-from-markdown@2.0.3(supports-color@9.0.0): {}\n"
    with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
        deps._runtime_dependencies(duplicate, "mdast-util-from-markdown", "2.0.3")
    for suffix in (b"(supports-color@latest)", b"(supports-color@^10.0.0)", b"trailing"):
        invalid = lock.replace(b"4.0.2(supports-color@10.2.2)", b"4.0.2" + suffix)
        with pytest.raises(deps.DependencyError, match="unsupported or ambiguous edges"):
            deps._runtime_dependencies(invalid, "mdast-util-from-markdown", "2.0.3")


def test_patched_snapshot_requires_the_exact_authorized_patch_identity():
    name, version, _, sha256 = deps.PACKAGE_PATCHES[0]
    lock = (f"snapshots:\n  '{name}@{version}(patch_hash={sha256})(undici@8.10.2)':\n"
            "    dependencies:\n      undici: 8.10.2\n").encode()
    assert deps._runtime_dependencies(lock, name, version) == {"undici": "8.10.2"}
    for changed in (lock.replace(sha256.encode(), b"0" * 64),
                    lock.replace(f"(patch_hash={sha256})".encode(), b""),
                    lock + lock.replace(sha256.encode(), b"0" * 64)):
        with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
            deps._runtime_dependencies(changed, name, version)


def test_mandatory_peer_dependencies_are_included_and_optional_peers_are_excluded():
    package = {"name": "transport", "version": "1.0.0", "peerDependencies": {
        "undici": ">=8 <9", "ws": "^8.0.0",
    }, "peerDependenciesMeta": {"ws": {"optional": True}}}
    lock = b"snapshots:\n  transport@1.0.0:\n    dependencies:\n      undici: 8.10.2\n"
    deps._validate_runtime_closure(package, lock, {"undici": "8.10.2"})
    with pytest.raises(deps.DependencyError, match="runtime dependencies"):
        deps._validate_runtime_closure(package, lock, {})
    package["peerDependenciesMeta"] = {}
    with pytest.raises(deps.DependencyError, match="runtime dependencies"):
        deps._validate_runtime_closure(package, lock, {"undici": "8.10.2", "ws": "8.21.3"})


@pytest.mark.parametrize("change", ["unlisted", "wrong-version", "missing-declaration", "invalid-declaration"])
def test_authenticated_package_runtime_edges_must_match_the_authorized_lock_closure(change):
    package = {"name": "strip-ansi", "version": "7.2.0", "dependencies": {"ansi-regex": "^6.0.1"}}
    lock = b"snapshots:\n  strip-ansi@7.2.0:\n    dependencies:\n      ansi-regex: 6.3.0\n"
    authorized = {"strip-ansi": "7.2.0", "ansi-regex": "6.3.0"}
    deps._validate_runtime_closure(package, lock, authorized)
    if change == "unlisted":
        authorized.pop("ansi-regex")
    elif change == "wrong-version":
        authorized["ansi-regex"] = "5.0.1"
    elif change == "missing-declaration":
        package["dependencies"] = {}
    else:
        package["dependencies"] = []
    with pytest.raises(deps.DependencyError, match="runtime dependencies"):
        deps._validate_runtime_closure(package, lock, authorized)


def test_loaded_dependency_evidence_cannot_forge_sources_or_hashes(packages):
    destination, _, _ = packages
    config = deps.prepare_dependencies(Path("unused"), destination, download=True)
    package = config["packages"][0]
    item = package["files"][0]
    source = {"package": package["name"], **item}
    deps.validate_dependency_sources(config, [source])
    for evidence in ([source, source], [{**source, "sha256": "0" * 64}],
                     [{**source, "path": "../outside.js"}],
                     [{**source, "package": "another-package"}], None):
        with pytest.raises(deps.DependencyError):
            deps.validate_dependency_sources(config, evidence)


def test_standalone_verification_rejects_wrong_reference_and_modified_lock(tmp_path, monkeypatch):
    checkout = tmp_path / "reference"
    checkout.mkdir()
    for args in (("init", "-q"),):
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)
    lock = checkout / "pnpm-lock.yaml"
    lock.write_text("lockfileVersion: '9.0'\n")
    subprocess.run(["git", "add", "."], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Pinned lock fixture"], cwd=checkout, check=True,
                   capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, check=True,
                            capture_output=True, text=True).stdout.strip()
    root = tmp_path / "suite"
    (root / "equivalence").mkdir(parents=True)
    manifest = root / "equivalence/reference.json"
    manifest.write_text(json.dumps({"commit": commit}))
    monkeypatch.setattr(deps, "ROOT", root)
    assert deps._committed_lock(checkout) == (commit, lock.read_bytes())
    lock.write_text("changed uncommitted lock\n")
    with pytest.raises(deps.DependencyError, match="does not match"):
        deps._committed_lock(checkout)
    lock.write_text("lockfileVersion: '9.0'\n")
    manifest.write_text(json.dumps({"commit": "0" * 40}))
    with pytest.raises(deps.DependencyError, match="does not match"):
        deps._committed_lock(checkout)


def test_dependency_patch_requires_matching_committed_bytes_and_lock_hash(tmp_path, monkeypatch):
    checkout = tmp_path / "reference"
    relative = "patches/transport.patch"
    patch = checkout / relative
    patch.parent.mkdir(parents=True)
    patch.write_bytes(LITERAL_PATCH)
    for args in (("init", "-q"), ("add", "."),
                 ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "commit", "-qm", "Pinned patch fixture")):
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)
    sha256 = deps._sha(LITERAL_PATCH)
    monkeypatch.setattr(deps, "PACKAGE_PATCHES", (("@openclaw/proxyline", "0.3.12", relative, sha256),))
    lock = f"patchedDependencies:\n  '@openclaw/proxyline@0.3.12': {sha256}\n".encode()
    assert deps._committed_patch(checkout, lock, "@openclaw/proxyline", "0.3.12") == (
        LITERAL_PATCH, {"path": relative, "sha256": sha256},
    )
    with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
        deps._committed_patch(checkout, lock.replace(sha256.encode(), b"0" * 64), "@openclaw/proxyline", "0.3.12")
    duplicate = lock + f"  '@openclaw/proxyline@0.3.12': {'0' * 64}\n".encode()
    with pytest.raises(deps.DependencyError, match="not uniquely pinned"):
        deps._committed_patch(checkout, duplicate, "@openclaw/proxyline", "0.3.12")
    patch.write_bytes(LITERAL_PATCH + b"uncommitted change\n")
    with pytest.raises(deps.DependencyError, match="differs from the pinned committed patch"):
        deps._committed_patch(checkout, lock, "@openclaw/proxyline", "0.3.12")
