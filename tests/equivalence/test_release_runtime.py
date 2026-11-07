"""Artifact verifier guards using labelled archives, never a fake native oracle."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
import subprocess
import tarfile

import pytest

from equivalence import release_runtime as runtime


def archive(files, *, extras=()):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        for path, value in files.items():
            value = value.encode() if isinstance(value, str) else value
            member = tarfile.TarInfo("package/" + path)
            member.size = len(value)
            output.addfile(member, io.BytesIO(value))
        for member, value in extras:
            output.addfile(member, io.BytesIO(value) if value is not None else None)
    return stream.getvalue()


def integrity(raw):
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()


def package(name, version, location, files):
    files = {"package.json": json.dumps({"name": name, "version": version}), **files}
    raw = archive(files)
    return {"name": name, "version": version, "location": location,
            "integrity": integrity(raw), "pin": "upstream-pnpm-lock"}, raw


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    # These tiny test-only packages exercise the verifier. None is offered to
    # the real compiled manager or described as native execution evidence.
    root, checkout, destination = tmp_path / "project", tmp_path / "reference", tmp_path / "artifacts"
    (root / "equivalence").mkdir(parents=True)
    checkout.mkdir()
    for command in (["init", "-q"], ["-c", "user.name=Fixture", "-c", "user.email=f@example.test",
                                     "commit", "--allow-empty", "-qm", "labelled verifier fixture"]):
        subprocess.run(["git", *command], cwd=checkout, check=True)
    values = [
        package("openclaw", runtime.VERSION, "node_modules/openclaw", {
            "dist/build-info.json": json.dumps({"version": runtime.VERSION, "commit": runtime.REFERENCE_COMMIT}),
            "dist/extensions/memory-core/manager-runtime.js": "export const labelledFixture = true;",
        }),
        package("fixture-parent", "1.0.0", "node_modules/fixture-parent", {"index.js": "export {};"}),
        package("fixture-child", "2.0.0", "node_modules/fixture-parent/node_modules/fixture-child",
                {"index.js": "export {};"}),
    ]
    native, native_raw = package("@openclaw/fs-safe-linux-x64-gnu", "0.21.1",
                                  "node_modules/@openclaw/fs-safe-linux-x64-gnu", {"fixture.node": b"fixture"})
    manifest = {"schemaVersion": 1, "registry": "https://registry.npmjs.org",
                "reference": {"tag": "v" + runtime.VERSION, "commit": runtime.REFERENCE_COMMIT},
                "rootLocation": "node_modules/openclaw", "packages": [value[0] for value in values],
                "nativeTargets": {"linux-x64-gnu": {key: native[key] for key in ("name", "version", "integrity")}}}
    manifest["packages"][0]["pin"] = "official-release-artifact"
    raws = {(item["name"], item["version"]): raw for item, raw in [*values, (native, native_raw)]}
    monkeypatch.setattr(runtime, "ROOT", root)
    monkeypatch.setattr(runtime, "_target", lambda: "linux-x64-gnu")
    monkeypatch.setattr(runtime, "_committed_lock", lambda checkout: (runtime.REFERENCE_COMMIT, b"labelled lock"))
    monkeypatch.setattr(runtime, "_integrity", lambda lock, name, version: integrity(raws[name, version]))
    calls = []

    def download(pin, limit):
        calls.append((pin["name"], pin["version"]))
        return raws[pin["name"], pin["version"]]

    monkeypatch.setattr(runtime, "_download", download)

    def write_manifest():
        raw = (json.dumps(manifest, indent=2) + "\n").encode()
        (root / "equivalence/release-runtime.json").write_bytes(raw)
        monkeypatch.setattr(runtime, "MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())

    write_manifest()
    return {"root": root, "checkout": checkout, "destination": destination,
            "manifest": manifest, "raws": raws, "calls": calls, "write_manifest": write_manifest}


def prepare(fixture, download=True):
    return runtime.prepare_release_runtime(fixture["checkout"], fixture["destination"], download)


def test_explicit_setup_authenticates_every_byte_and_verification_does_not_download(fixture):
    config = prepare(fixture)
    assert config["kind"] == "verified-release-runtime"
    assert config["buildAttestation"]["sourceBuildReproduced"] is False
    assert config["runtimeRoot"] == str(fixture["destination"] / "node_modules/openclaw")
    assert len(config["packages"]) == len(fixture["calls"]) == 4
    assert all(pin["files"] and pin["filesSha256"] for pin in config["packages"])
    before = deepcopy(fixture["calls"])
    assert prepare(fixture, download=False) == config
    assert fixture["calls"] == before


def test_missing_cache_does_not_implicitly_download(fixture):
    with pytest.raises(runtime.ReleaseRuntimeError, match="explicit install"):
        prepare(fixture, download=False)
    assert fixture["calls"] == []


@pytest.mark.parametrize("change", ["bytes", "missing", "extra", "symlink", "nested-child"])
def test_installed_tree_tampering_is_rejected_and_not_silently_repaired(fixture, change):
    prepare(fixture)
    parent = fixture["destination"] / "node_modules/fixture-parent"
    target = parent / "index.js"
    if change == "bytes":
        target.write_text("tampered")
    elif change == "missing":
        target.unlink()
    elif change == "extra":
        (parent / "extra.js").write_text("extra")
    elif change == "symlink":
        target.unlink()
        target.symlink_to("package.json")
    else:
        (parent / "node_modules/fixture-child/index.js").write_text("tampered child")
    for download in (False, True):
        with pytest.raises(runtime.ReleaseRuntimeError):
            prepare(fixture, download)


def test_archive_tampering_is_rejected_before_installed_tree_is_trusted(fixture):
    prepare(fixture)
    target = fixture["destination"] / "archives/fixture-parent-1.0.0.tgz"
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(runtime.ReleaseRuntimeError, match="integrity"):
        prepare(fixture, False)


def test_changed_manifest_is_not_a_new_trust_authority(fixture):
    path = fixture["root"] / "equivalence/release-runtime.json"
    path.write_text(path.read_text().replace("fixture-parent", "replacement"))
    with pytest.raises(runtime.ReleaseRuntimeError, match="reviewed artifact set"):
        prepare(fixture)
    assert fixture["calls"] == []


@pytest.mark.parametrize("location", ["/tmp/escaped", "node_modules/../escape", "./node_modules/fixture-parent",
                                     "node_modules/fixture-parent/other", "node_modules\\fixture-parent"])
def test_unsafe_or_ambiguous_install_locations_are_rejected(fixture, location):
    fixture["manifest"]["packages"][1]["location"] = location
    fixture["write_manifest"]()
    with pytest.raises(runtime.ReleaseRuntimeError):
        prepare(fixture)
    assert fixture["calls"] == []


def test_wrong_source_commit_stops_before_any_download(fixture, monkeypatch):
    monkeypatch.setattr(runtime, "_committed_lock", lambda checkout: ("0" * 40, b"labelled lock"))
    with pytest.raises(runtime.ReleaseRuntimeError, match="exact source commit"):
        prepare(fixture)
    assert fixture["calls"] == []


def test_wrong_release_build_commit_is_rejected_even_with_authenticated_archive(fixture):
    pin = fixture["manifest"]["packages"][0]
    files = {"package.json": json.dumps({"name": "openclaw", "version": runtime.VERSION}),
             "dist/build-info.json": json.dumps({"version": runtime.VERSION, "commit": "0" * 40}),
             "dist/extensions/memory-core/manager-runtime.js": "export const labelledFixture = true;"}
    raw = archive(files)
    pin["integrity"] = integrity(raw)
    fixture["raws"]["openclaw", runtime.VERSION] = raw
    fixture["write_manifest"]()
    with pytest.raises(runtime.ReleaseRuntimeError, match="attests another"):
        prepare(fixture)


@pytest.mark.parametrize("path,kind", [("package/../escape", "file"), ("/absolute", "file"),
                                      ("package/link", "symlink"), ("package/pipe", "fifo")])
def test_authenticated_archives_still_reject_unsafe_entries(path, kind):
    member = tarfile.TarInfo(path)
    member.size = 1 if kind == "file" else 0
    if kind == "symlink":
        member.type, member.linkname = tarfile.SYMTYPE, "../../escape"
    elif kind == "fifo":
        member.type = tarfile.FIFOTYPE
    raw = archive({"package.json": '{"name":"fixture","version":"1.0.0"}'},
                  extras=[(member, b"x" if kind == "file" else None)])
    with pytest.raises(runtime.ReleaseRuntimeError):
        runtime._archive_files(raw, {"name": "fixture", "version": "1.0.0", "integrity": integrity(raw)})


def test_archive_extraction_is_bounded(monkeypatch):
    raw = archive({"package.json": '{"name":"fixture","version":"1.0.0"}', "large": "12345"})
    pin = {"name": "fixture", "version": "1.0.0", "integrity": integrity(raw)}
    monkeypatch.setattr(runtime, "MAX_EXTRACTED_BYTES", 2)
    with pytest.raises(runtime.ReleaseRuntimeError, match="size limit"):
        runtime._archive_files(raw, pin)


def test_loaded_runtime_evidence_keeps_artifact_identity_separate(fixture):
    config = prepare(fixture)
    package = next(pin for pin in config["packages"] if pin["name"] == "openclaw")
    entry = next(item for item in package["files"] if item["path"].endswith("manager-runtime.js"))
    row = {"package": package["location"], **entry}
    runtime.validate_release_sources(config, [row])
    for rows in ([], [row, row], [{**row, "sha256": "0" * 64}],
                 [{**row, "package": "unverified"}], [{**row, "path": "../escape"}],
                 [{**row, "package": []}]):
        with pytest.raises(runtime.ReleaseRuntimeError):
            runtime.validate_release_sources(config, rows)
