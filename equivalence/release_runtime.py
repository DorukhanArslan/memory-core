"""Authenticate the official compiled reference runtime, separately from TS sources.

Only explicit setup downloads artifacts. Runtime comparisons recheck complete
archives and every installed file before and after execution. The publisher's
build commit is checked, but this is not a reproduced build from source.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request

from equivalence.dependencies import (
    DependencyError,
    ROOT,
    _assert_safe_directory,
    _committed_lock,
    _integrity,
    _target,
)


MANIFEST_SHA256 = "f96a871ed899d1e0f4f15e6844dfca11e82accd0e1927942dd84c3533a2c8859"
REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
VERSION = "2026.9.9"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_FILES = 10000
RELEASE_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
RELEASE_MAX_EXTRACTED_BYTES = 768 * 1024 * 1024
RELEASE_MAX_FILES = 30000
_NAME = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+\Z")
_VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
_INTEGRITY = re.compile(r"sha512-[A-Za-z0-9+/]+={0,2}\Z")


class ReleaseRuntimeError(RuntimeError):
    """A bounded artifact diagnostic with no credentials or server response text."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _location(location: str, name: str) -> None:
    if not isinstance(location, str) or "\\" in location:
        raise ReleaseRuntimeError("The release dependency location is invalid.")
    path = PurePosixPath(location)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != location:
        raise ReleaseRuntimeError("The release dependency location is invalid.")
    parts, index, package = path.parts, 0, ""
    while index < len(parts):
        if parts[index] != "node_modules" or index + 1 >= len(parts):
            raise ReleaseRuntimeError("The release dependency location is invalid.")
        index += 1
        package = parts[index]
        index += 1
        if package.startswith("@"):
            if index >= len(parts):
                raise ReleaseRuntimeError("The release dependency location is invalid.")
            package += "/" + parts[index]
            index += 1
        if not _NAME.fullmatch(package):
            raise ReleaseRuntimeError("The release dependency location is invalid.")
    if package != name:
        raise ReleaseRuntimeError("The release dependency location does not match its package.")


def _manifest() -> tuple[dict, str]:
    try:
        raw = (ROOT / "equivalence/release-runtime.json").read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError):
        raise ReleaseRuntimeError("The compiled reference manifest is unavailable.") from None
    if _sha(raw) != MANIFEST_SHA256:
        raise ReleaseRuntimeError("The compiled reference manifest is not the reviewed artifact set.")
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("registry") != "https://registry.npmjs.org"
            or value.get("reference") != {"tag": "v" + VERSION, "commit": REFERENCE_COMMIT}
            or value.get("rootLocation") != "node_modules/openclaw"
            or not isinstance(value.get("packages"), list) or not value["packages"]
            or not isinstance(value.get("nativeTargets"), dict)):
        raise ReleaseRuntimeError("The compiled reference manifest is invalid.")
    seen = set()
    for package in value["packages"]:
        if (not isinstance(package, dict) or not isinstance(package.get("name"), str)
                or not _NAME.fullmatch(package["name"])
                or not isinstance(package.get("version"), str) or not _VERSION.fullmatch(package["version"])
                or not isinstance(package.get("integrity"), str)
                or not _INTEGRITY.fullmatch(package["integrity"])
                or package.get("pin") not in {"upstream-pnpm-lock", "official-release-artifact"}):
            raise ReleaseRuntimeError("The compiled reference package pin is invalid.")
        _location(package.get("location"), package["name"])
        if package["location"] in seen:
            raise ReleaseRuntimeError("Compiled reference dependency locations must be unique.")
        seen.add(package["location"])
    return value, _sha(raw)


def _regular(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReleaseRuntimeError("A compiled reference artifact is not an independent regular file.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        raise ReleaseRuntimeError("A compiled reference download attempted a redirect.")


def _download(package: dict, limit: int) -> bytes:
    name, version = package["name"], package["version"]
    url = "https://registry.npmjs.org/" + name + "/-/" + name.split("/")[-1] + "-" + version + ".tgz"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url), timeout=30) as response:
            raw = response.read(limit + 1)
    except (OSError, urllib.error.URLError):
        raise ReleaseRuntimeError("The exact compiled reference artifact could not be downloaded.") from None
    if len(raw) > limit:
        raise ReleaseRuntimeError("The compiled reference archive exceeds the size limit.")
    return raw


def _archive_files(raw: bytes, package: dict) -> dict[str, bytes]:
    release = package["name"] == "openclaw"
    max_archive = RELEASE_MAX_ARCHIVE_BYTES if release else MAX_ARCHIVE_BYTES
    max_extracted = RELEASE_MAX_EXTRACTED_BYTES if release else MAX_EXTRACTED_BYTES
    max_files = RELEASE_MAX_FILES if release else MAX_FILES
    if len(raw) > max_archive:
        raise ReleaseRuntimeError("A compiled reference archive exceeds the size limit.")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")
    if integrity != package["integrity"]:
        raise ReleaseRuntimeError("A compiled reference archive failed its pinned integrity check.")
    files, size = {}, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                        or not path.parts or path.parts[0] != "package"
                        or path.as_posix() != member.name.rstrip("/")):
                    raise ReleaseRuntimeError("A compiled reference archive has an unsafe path.")
                if member.isdir():
                    continue
                if not member.isfile() or len(path.parts) < 2:
                    raise ReleaseRuntimeError("A compiled reference archive has a non-regular entry.")
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                if relative in files or len(files) >= max_files or member.size < 0:
                    raise ReleaseRuntimeError("A compiled reference archive has duplicate or excessive entries.")
                size += member.size
                if size > max_extracted:
                    raise ReleaseRuntimeError("A compiled reference archive exceeds its extracted size limit.")
                stream = archive.extractfile(member)
                value = stream.read(member.size + 1) if stream is not None else b""
                if len(value) != member.size:
                    raise ReleaseRuntimeError("A compiled reference archive has an invalid file size.")
                files[relative] = value
    except (OSError, tarfile.TarError, EOFError):
        raise ReleaseRuntimeError("The compiled reference archive is malformed.") from None
    try:
        metadata = json.loads(files["package.json"])
    except (KeyError, ValueError, UnicodeError):
        raise ReleaseRuntimeError("The compiled reference package manifest is missing or invalid.") from None
    if not isinstance(metadata, dict) or any(metadata.get(key) != package[key] for key in ("name", "version")):
        raise ReleaseRuntimeError("The compiled reference package has the wrong name or version.")
    return files


def _publish(directory: Path, files: dict[str, bytes]) -> None:
    _assert_safe_directory(directory.parent)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".release-artifact-", dir=directory.parent))
    try:
        for relative, value in files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        if directory.exists() or directory.is_symlink():
            raise ReleaseRuntimeError("An existing compiled reference package will not be reset.")
        staging.rename(directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _verify_tree(directory: Path, files: dict[str, bytes], children: set[str]) -> list[dict]:
    _assert_safe_directory(directory)
    if not directory.is_dir():
        raise ReleaseRuntimeError("A compiled reference package is missing; run its explicit install command.")
    observed = set()
    for current, directories, filenames in os.walk(directory, followlinks=False):
        parent = Path(current)
        for name in list(directories):
            child = parent / name
            if child.is_symlink():
                raise ReleaseRuntimeError("A compiled reference package contains a symlink.")
            if child.relative_to(directory).as_posix() in children:
                directories.remove(name)
        for name in filenames:
            path = parent / name
            _regular(path)
            relative = path.relative_to(directory).as_posix()
            if relative not in files or path.read_bytes() != files[relative]:
                raise ReleaseRuntimeError("Installed compiled reference bytes differ from their authenticated archive.")
            observed.add(relative)
    if observed != set(files):
        raise ReleaseRuntimeError("A compiled reference package has missing files.")
    return [{"path": path, "sha256": _sha(value)} for path, value in sorted(files.items())]


def prepare_release_runtime(checkout: Path, destination: Path, download: bool = False) -> dict:
    """Verify exact release artifacts; only explicit setup is allowed to download."""
    try:
        manifest, manifest_hash = _manifest()
        commit, lock = _committed_lock(checkout)
        if commit != REFERENCE_COMMIT:
            raise ReleaseRuntimeError("The compiled reference requires its exact source commit.")
        for command in (["git", "rev-parse", "--show-toplevel"],
                        ["git", "status", "--porcelain", "--untracked-files=no"]):
            result = subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=True, timeout=10)
            if ((command[1] == "rev-parse" and Path(result.stdout.strip()).resolve() != checkout.resolve())
                    or (command[1] == "status" and result.stdout.strip())):
                raise ReleaseRuntimeError("The compiled reference requires a clean pinned checkout root.")
        target = _target()
        native = dict(manifest["nativeTargets"][target])
        native.update(location="node_modules/" + native["name"], pin="upstream-pnpm-lock")
        packages = [*manifest["packages"], native]
        packages.sort(key=lambda item: (len(PurePosixPath(item["location"]).parts), item["location"]))
        _assert_safe_directory(destination)
        destination = destination.absolute()
        evidence, build = [], None
        locations = {package["location"] for package in packages}
        for package in packages:
            if package["pin"] == "upstream-pnpm-lock" and _integrity(
                    lock, package["name"], package["version"]) != package["integrity"]:
                raise ReleaseRuntimeError("A release dependency differs from the pinned source lockfile.")
            filename = package["name"].replace("/", "-").lstrip("@") + "-" + package["version"] + ".tgz"
            archive = destination / "archives" / filename
            _assert_safe_directory(archive.parent)
            if archive.exists() or archive.is_symlink():
                _regular(archive)
                raw = archive.read_bytes()
            elif download:
                cache = ROOT / ".reference/npm/archives" / filename
                if cache.is_file() and not cache.is_symlink():
                    _regular(cache)
                    raw = cache.read_bytes()
                else:
                    raw = _download(package, RELEASE_MAX_ARCHIVE_BYTES if package["name"] == "openclaw"
                                    else MAX_ARCHIVE_BYTES)
            else:
                raise ReleaseRuntimeError("A compiled reference archive is missing; run the explicit install command.")
            files = _archive_files(raw, package)
            if package["name"] == "openclaw":
                try:
                    build = json.loads(files["dist/build-info.json"])
                except (KeyError, ValueError, UnicodeError):
                    raise ReleaseRuntimeError("The official release build attestation is missing.") from None
                if not isinstance(build, dict) or build.get("version") != VERSION or build.get("commit") != commit:
                    raise ReleaseRuntimeError("The official release build attests another version or commit.")
                if "dist/extensions/memory-core/manager-runtime.js" not in files:
                    raise ReleaseRuntimeError("The official release has no native memory manager runtime.")
            directory = destination / package["location"]
            if download:
                if not archive.exists():
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open("xb") as stream:
                        stream.write(raw)
                if not directory.exists() and not directory.is_symlink():
                    _publish(directory, files)
            children = {location[len(package["location"]) + 1:] for location in locations
                        if location.startswith(package["location"] + "/")}
            verified = _verify_tree(directory, files, children)
            tree_hash = _sha(json.dumps(verified, sort_keys=True, separators=(",", ":")).encode())
            evidence.append({**package, "directory": str(directory), "fileCount": len(verified),
                             "filesSha256": tree_hash, "files": verified})
        if build is None:
            raise ReleaseRuntimeError("The official release artifact is missing.")
        return {"schemaVersion": 1, "kind": "verified-release-runtime", "reference": manifest["reference"],
                "runtimeRoot": str(destination / manifest["rootLocation"]),
                "lockfileSha256": _sha(lock), "manifestSha256": manifest_hash,
                "buildAttestation": {**build, "sourceBuildReproduced": False,
                                     "authority": "integrity-pinned official npm release"},
                "packages": evidence}
    except (DependencyError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise ReleaseRuntimeError("The compiled reference artifacts could not be safely authenticated.") from None


def validate_release_sources(config: dict, sources: object) -> None:
    """Check the loaded-file subset without presenting compiled bytes as TS source."""
    if not isinstance(sources, list) or not sources:
        raise ReleaseRuntimeError("The compiled reference returned no loaded-file evidence.")
    allowed = {(package["location"], entry["path"]): entry["sha256"]
               for package in config["packages"] for entry in package["files"]}
    seen = set()
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("package"), str)
                or not isinstance(source.get("path"), str)):
            raise ReleaseRuntimeError("The compiled reference returned invalid loaded-file evidence.")
        key = (source.get("package"), source.get("path"))
        if key in seen or key not in allowed or source.get("sha256") != allowed[key]:
            raise ReleaseRuntimeError("Loaded compiled reference bytes are not authenticated artifacts.")
        seen.add(key)
    if ("node_modules/openclaw", "dist/extensions/memory-core/manager-runtime.js") not in seen:
        raise ReleaseRuntimeError("The compiled reference did not execute its real memory manager entry.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / ".reference/release-runtime")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        config = prepare_release_runtime(args.reference.resolve(), args.destination.resolve(), args.install)
    except ReleaseRuntimeError as error:
        print(json.dumps({"kind": "verified-release-runtime", "status": "unavailable", "error": str(error)}))
        return 2
    print(json.dumps({"kind": config["kind"], "status": "verified", "reference": config["reference"],
                      "packages": len(config["packages"]),
                      "files": sum(package["fileCount"] for package in config["packages"]),
                      "sourceBuildReproduced": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
