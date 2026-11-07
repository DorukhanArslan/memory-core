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


@pytest.fixture
def packages(tmp_path, monkeypatch):
    destination = tmp_path / "npm"
    raw_by_package = {}
    sections = []
    for name, version in (
        ("@openclaw/fs-safe", "0.21.1"),
        ("@openclaw/fs-safe-linux-x64-gnu", "0.21.1"),
        ("p-map", "7.0.8"),
        ("kysely", "0.29.6"),
    ):
        raw = _tar({
            "package/package.json": json.dumps({"name": name, "version": version}).encode(),
            "package/dist/index.js": b"export const realArtifact = true;\n",
        })
        raw_by_package[name] = raw
        quote = "'" if name.startswith("@") else ""
        sections.append(f"  {quote}{name}@{version}{quote}:\n"
                        f"    resolution: {{integrity: {_integrity(raw)}}}\n")
    lock = "\n".join(sections).encode()
    monkeypatch.setattr(deps, "_committed_lock", lambda _: ("a" * 40, lock))
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
                     ("@openclaw/fs-safe-linux-x64-gnu", "0.21.1"), ("p-map", "7.0.8"),
                     ("kysely", "0.29.6")]
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
        manifest["additionalPackages"].pop()
    elif change == "duplicate-kysely":
        manifest["additionalPackages"].append(dict(manifest["additionalPackages"][1]))
    elif change == "wrong-registry":
        manifest["registry"] = "https://registry.example.invalid"
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
