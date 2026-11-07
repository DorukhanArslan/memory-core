"""Verified npm artifacts for source-only reference execution.

The application does not depend on these packages. They are the pinned native
reference's filesystem and SQL dependencies and its platform binary. No install scripts
run, and dependency files remain separate from committed TypeScript evidence.
Every verification checks downloaded archive integrity against the pinned
upstream lockfile, then checks every extracted byte against that archive.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_FILES = 10000


class DependencyError(RuntimeError):
    """A bounded diagnostic which contains no network responses or credentials."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest() -> dict:
    try:
        value = json.loads((ROOT / "equivalence/dependencies.json").read_text())
    except (OSError, ValueError):
        raise DependencyError("The reference dependency manifest is unavailable.") from None
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("registry") != "https://registry.npmjs.org"
            or value.get("package") != "@openclaw/fs-safe"
            or value.get("version") != "0.21.1"
            or not isinstance(value.get("nativeTargets"), list)
            or value.get("additionalPackages") != [
                {"name": "p-map", "version": "7.0.8"},
                {"name": "kysely", "version": "0.29.6"},
            ]):
        raise DependencyError("The reference dependency manifest is invalid.")
    return value


def _target() -> str:
    arch = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine(), platform.machine(),
    )
    if os.name == "nt":
        return f"win32-{arch}-msvc"
    if platform.system() == "Darwin":
        return f"darwin-{arch}"
    if platform.system() == "Linux":
        libc = "musl" if platform.libc_ver()[0] == "musl" else "gnu"
        return f"linux-{arch}-{libc}"
    raise DependencyError("The source oracle filesystem binary does not support this platform.")


def _committed_lock(checkout: Path) -> tuple[str, bytes]:
    try:
        target = json.loads((ROOT / "equivalence/reference.json").read_text())["commit"]
        actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, check=True,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        committed = subprocess.run(["git", "show", "HEAD:pnpm-lock.yaml"], cwd=checkout,
                                   check=True, capture_output=True, timeout=10).stdout
        current = (checkout / "pnpm-lock.yaml").read_bytes()
    except (KeyError, ValueError, OSError, subprocess.SubprocessError):
        raise DependencyError("The pinned reference lockfile could not be verified.") from None
    if actual != target or current != committed:
        raise DependencyError("The dependency lockfile does not match the pinned reference.")
    return actual, current


def _integrity(lock: bytes, name: str, version: str) -> str:
    # Parse only the exact package resolution stanza, not arbitrary YAML. No
    # dependency may be inferred from an unversioned importer or npm metadata.
    quoted = "'" if name.startswith("@") else ""
    pattern = (r"^  " + quoted + re.escape(name + "@" + version) + quoted
               + r":\n    resolution: \{integrity: (sha512-[A-Za-z0-9+/]+={0,2})\}\n")
    matches = re.findall(pattern, lock.decode("utf-8"), flags=re.MULTILINE)
    if len(matches) != 1:
        raise DependencyError("The dependency is not uniquely pinned in the reference lockfile.")
    return matches[0]


def _archive_files(raw: bytes, integrity: str) -> dict[str, bytes]:
    """Authenticate the archive before inspecting its bounded, regular contents."""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise DependencyError("The reference dependency archive exceeds the size limit.")
    actual = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")
    if actual != integrity:
        raise DependencyError("The reference dependency archive failed its pinned integrity check.")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                        or not path.parts or path.parts[0] != "package"
                        or path.as_posix() != member.name.rstrip("/")):
                    raise DependencyError("A reference dependency archive contains an unsafe path.")
                if member.isdir():
                    continue
                if not member.isfile() or len(path.parts) < 2:
                    raise DependencyError("A reference dependency archive contains a non-regular entry.")
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                if relative in files or len(files) >= MAX_FILES or member.size < 0:
                    raise DependencyError("A reference dependency archive has duplicate or excessive files.")
                total += member.size
                if total > MAX_EXTRACTED_BYTES:
                    raise DependencyError("A reference dependency archive exceeds the extracted size limit.")
                stream = archive.extractfile(member)
                if stream is None:
                    raise DependencyError("A reference dependency archive has an unreadable file.")
                value = stream.read(member.size + 1)
                if len(value) != member.size:
                    raise DependencyError("A reference dependency archive has an invalid file size.")
                files[relative] = value
    except (tarfile.TarError, OSError, EOFError):
        raise DependencyError("The authenticated reference dependency archive is invalid.") from None
    if "package.json" not in files:
        raise DependencyError("The reference dependency archive has no package manifest.")
    return files


def _download(name: str, version: str) -> bytes:
    basename = name.rsplit("/", 1)[-1]
    url = f"https://registry.npmjs.org/{name}/-/{basename}-{version}.tgz"
    class RegistryRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parsed = urllib.parse.urlsplit(newurl)
            if (parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org"
                    or parsed.port not in (None, 443) or parsed.username or parsed.password):
                raise DependencyError("The reference dependency registry redirected to an unsupported host.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    try:
        opener = urllib.request.build_opener(RegistryRedirect())
        with opener.open(url, timeout=30) as response:
            raw = response.read(MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DependencyError("The pinned reference dependency could not be downloaded.") from None
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise DependencyError("The reference dependency archive exceeds the size limit.")
    return raw


def _assert_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise DependencyError("The dependency cache contains a missing or non-regular file.")


def _assert_safe_directory(path: Path) -> None:
    for current in (path, *path.parents):
        if current.is_symlink():
            raise DependencyError("The dependency cache must not contain symlinked directories.")


def _verify_tree(directory: Path, files: dict[str, bytes]) -> list[dict[str, str]]:
    _assert_safe_directory(directory)
    if not directory.is_dir():
        raise DependencyError("The verified reference dependency is not installed; run the dependency install command.")
    actual_paths = set()
    for current, directories, names in os.walk(directory, followlinks=False):
        for name in directories:
            if (Path(current) / name).is_symlink():
                raise DependencyError("The dependency cache must not contain symlinked directories.")
        for name in names:
            path = Path(current) / name
            _assert_regular(path)
            actual_paths.add(path.relative_to(directory).as_posix())
    if actual_paths != files.keys():
        raise DependencyError("Installed dependency files differ from the authenticated archive.")
    evidence = []
    for relative, content in sorted(files.items()):
        path = directory / relative
        if path.read_bytes() != content:
            raise DependencyError("Installed dependency bytes differ from the authenticated archive.")
        evidence.append({"path": relative, "sha256": _sha(content)})
    return evidence


def _publish_files(directory: Path, files: dict[str, bytes]) -> None:
    _assert_safe_directory(directory.parent)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dependency-", dir=directory.parent))
    try:
        for relative, content in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # A pre-existing cache is never replaced or silently repaired.
        if directory.exists() or directory.is_symlink():
            raise DependencyError("The reference dependency destination already exists.")
        staging.rename(directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _prepare_dependencies(checkout: Path, destination: Path, download: bool) -> dict[str, Any]:
    """Verify local artifacts; download only when explicitly requested by setup.

    The returned configuration contains absolute package roots for the source
    oracle's loader. Its file hashes and archive integrities are evidence for
    npm dependencies, never committed upstream source hashes.
    """
    manifest = _manifest()
    commit, lock = _committed_lock(checkout)
    target = _target()
    if target not in manifest["nativeTargets"]:
        raise DependencyError("The source oracle filesystem binary does not support this platform.")
    _assert_safe_directory(destination)
    destination = destination.absolute()
    packages = []
    dependencies = [{"name": name, "version": manifest["version"]}
                    for name in (manifest["package"], manifest["package"] + "-" + target)]
    dependencies.extend(manifest["additionalPackages"])
    for dependency in dependencies:
        name, version = dependency["name"], dependency["version"]
        integrity = _integrity(lock, name, version)
        archive = destination / "archives" / (name.replace("/", "-").lstrip("@") + "-" + version + ".tgz")
        _assert_safe_directory(archive.parent)
        if archive.exists() or archive.is_symlink():
            _assert_regular(archive)
            raw = archive.read_bytes()
        elif download:
            raw = _download(name, version)
        else:
            raise DependencyError("The reference dependency archive is missing; run the dependency install command.")
        files = _archive_files(raw, integrity)
        try:
            package = json.loads(files["package.json"])
        except (ValueError, UnicodeError):
            raise DependencyError("The authenticated dependency manifest is invalid.") from None
        if package.get("name") != name or package.get("version") != version:
            raise DependencyError("The authenticated dependency has the wrong name or version.")
        directory = destination / "node_modules" / name
        if download:
            if not archive.exists():
                archive.parent.mkdir(parents=True, exist_ok=True)
                with archive.open("xb") as output:
                    output.write(raw)
            if not directory.exists() and not directory.is_symlink():
                _publish_files(directory, files)
        evidence = _verify_tree(directory, files)
        packages.append({"name": name, "version": version, "integrity": integrity,
                         "directory": str(directory), "files": evidence})
    return {"schemaVersion": 1, "kind": "verified-npm-artifacts", "referenceCommit": commit,
            "lockfileSha256": _sha(lock), "packages": packages}


def prepare_dependencies(checkout: Path, destination: Path, download: bool = False) -> dict[str, Any]:
    """Verify authenticated packages before/after execution; setup alone downloads."""
    try:
        return _prepare_dependencies(checkout, destination, download)
    except OSError:
        raise DependencyError("The reference dependency cache could not be safely read or published.") from None


def validate_dependency_sources(config: dict, sources: Any) -> None:
    """Validate the oracle's loaded-dependency subset against verified artifacts."""
    if not isinstance(sources, list):
        raise DependencyError("The oracle returned invalid dependency evidence.")
    allowed = {(package["name"], item["path"]): item["sha256"]
               for package in config["packages"] for item in package["files"]}
    seen = set()
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("package"), str)
                or not isinstance(source.get("path"), str)):
            raise DependencyError("The oracle returned invalid dependency evidence.")
        key = (source["package"], source["path"])
        if key in seen or key not in allowed or source.get("sha256") != allowed[key]:
            raise DependencyError("The oracle dependency evidence differs from authenticated artifacts.")
        seen.add(key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / ".reference/npm")
    parser.add_argument("--install", action="store_true", help="download pinned archives and extract without scripts")
    args = parser.parse_args()
    try:
        config = prepare_dependencies(args.reference, args.destination, download=args.install)
    except DependencyError as error:
        print(json.dumps({"kind": "reference-dependency-verification", "verified": False, "error": str(error)}))
        return 1
    print(json.dumps({"kind": "reference-dependency-verification", "verified": True,
                      "referenceCommit": config["referenceCommit"],
                      "lockfileSha256": config["lockfileSha256"],
                      "packages": [{key: package[key] for key in ("name", "version", "integrity")}
                                   | {"files": len(package["files"])} for package in config["packages"]],
                      "installScriptsRun": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
