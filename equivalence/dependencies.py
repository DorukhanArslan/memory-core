"""Verified npm artifacts for source-only reference execution.

The application does not depend on these packages. They are the pinned native
reference's runtime libraries and its filesystem platform binary. No install
scripts run, and dependency files remain separate from committed TypeScript evidence.
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
MAX_PATCH_BYTES = 1024 * 1024
PACKAGE_PATCHES = (
    ("@openclaw/proxyline", "0.3.12", "patches/@openclaw__proxyline@0.3.12.patch",
     "9e0969d2dc0abb32610053fba342756afb56f4996c90adfdc34f21ad090fbb0f"),
)
ADDITIONAL_PACKAGES = (
    ("p-map", "7.0.8"),
    ("kysely", "0.29.6"),
    ("semver", "7.8.5"),
    ("chalk", "6.0.0"),
    ("tslog", "5.2.0"),
    ("string-width", "8.2.2"),
    ("get-east-asian-width", "1.7.0"),
    ("strip-ansi", "7.2.0"),
    ("ansi-regex", "6.3.0"),
    ("zod", "4.6.5"),
    ("json5", "2.2.3"),
    ("commander", "15.0.0"),
    ("typebox", "1.3.34"),
    ("execa", "10.0.1"),
    ("import-meta-resolve", "4.2.0"),
    ("@sindresorhus/merge-streams", "4.0.0"),
    ("figures", "6.1.0"),
    ("get-stream", "9.0.1"),
    ("human-signals", "8.0.1"),
    ("is-plain-obj", "4.1.0"),
    ("is-stream", "4.0.1"),
    ("npm-run-path", "6.0.0"),
    ("pretty-ms", "9.3.1"),
    ("signal-exit", "4.1.0"),
    ("strip-final-newline", "4.0.0"),
    ("which-command", "0.1.0"),
    ("yoctocolors", "2.2.0"),
    ("is-unicode-supported", "2.1.0"),
    ("@sec-ant/readable-stream", "0.4.1"),
    ("path-key", "4.0.0"),
    ("unicorn-magic", "0.3.0"),
    ("parse-ms", "4.0.0"),
    ("acorn", "8.18.0"),
    ("mdast-util-from-markdown", "2.0.3"),
    ("partial-json", "0.1.7"),
    ("@types/mdast", "4.0.4"),
    ("@types/unist", "3.0.3"),
    ("decode-named-character-reference", "1.3.0"),
    ("devlop", "1.1.0"),
    ("mdast-util-to-string", "4.0.0"),
    ("micromark", "4.0.2"),
    ("micromark-util-decode-numeric-character-reference", "2.0.2"),
    ("micromark-util-decode-string", "2.0.1"),
    ("micromark-util-normalize-identifier", "2.0.1"),
    ("micromark-util-symbol", "2.0.1"),
    ("micromark-util-types", "2.0.2"),
    ("unist-util-stringify-position", "4.0.0"),
    ("character-entities", "2.0.2"),
    ("dequal", "2.0.3"),
    ("@types/debug", "4.1.13"),
    ("debug", "4.4.3"),
    ("micromark-core-commonmark", "2.0.3"),
    ("micromark-factory-space", "2.0.1"),
    ("micromark-util-character", "2.1.1"),
    ("micromark-util-chunked", "2.0.1"),
    ("micromark-util-combine-extensions", "2.0.1"),
    ("micromark-util-encode", "2.0.1"),
    ("micromark-util-resolve-all", "2.0.1"),
    ("micromark-util-sanitize-uri", "2.0.1"),
    ("micromark-util-subtokenize", "2.1.0"),
    ("@types/ms", "2.1.0"),
    ("ms", "2.1.3"),
    ("micromark-factory-destination", "2.0.1"),
    ("micromark-factory-label", "2.0.1"),
    ("micromark-factory-title", "2.0.1"),
    ("micromark-factory-whitespace", "2.0.1"),
    ("micromark-util-classify-character", "2.0.1"),
    ("micromark-util-html-tag-name", "2.0.1"),
    ("mdast-util-gfm-table", "2.0.0"),
    ("micromark-extension-gfm-table", "2.1.2"),
    ("markdown-table", "3.0.4"),
    ("mdast-util-to-markdown", "2.1.2"),
    ("longest-streak", "3.1.0"),
    ("mdast-util-phrasing", "4.1.0"),
    ("unist-util-visit", "5.1.0"),
    ("zwitch", "2.0.4"),
    ("unist-util-is", "6.0.1"),
    ("unist-util-visit-parents", "6.0.2"),
    ("openai", "7.20.0"),
    ("ws", "8.21.3"),
    ("ipaddr.js", "2.5.0"),
    ("hosted-git-info", "10.1.1"),
    ("dotenv", "18.0.1"),
    ("p-limit", "7.3.3"),
    ("lru-cache", "11.5.2"),
    ("yocto-queue", "1.2.2"),
    ("@openclaw/proxyline", "0.3.12"),
    ("undici", "8.10.2"),
)


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
                {"name": name, "version": version} for name, version in ADDITIONAL_PACKAGES]
            or value.get("patches") != [
                {"name": name, "version": version, "path": path, "sha256": sha256}
                for name, version, path, sha256 in PACKAGE_PATCHES]):
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


def _committed_patch(checkout: Path, lock: bytes, name: str, version: str) -> tuple[bytes, dict] | None:
    specification = next((item for item in PACKAGE_PATCHES if item[:2] == (name, version)), None)
    if specification is None:
        return None
    _, _, relative, sha256 = specification
    stanza = re.findall(r"(?ms)^patchedDependencies:\n(.*?)(?=^\S|\Z)", lock.decode("utf-8"))
    key = re.escape(f"  '{name}@{version}': ")
    hashes = [value for section in stanza for value in re.findall(key + r"([0-9a-f]{64})$", section, re.MULTILINE)]
    if hashes != [sha256]:
        raise DependencyError("The reference dependency patch is not uniquely pinned in the lockfile.")
    try:
        patch = checkout / relative
        _assert_safe_directory(patch.parent)
        _assert_regular(patch)
        current = patch.read_bytes()
        committed = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=checkout,
                                   check=True, capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        raise DependencyError("The pinned reference dependency patch could not be verified.") from None
    if len(current) > MAX_PATCH_BYTES or current != committed or _sha(current) != sha256:
        raise DependencyError("The dependency patch differs from the pinned committed patch.")
    return current, {"path": relative, "sha256": sha256}


def _apply_literal_patch(files: dict[str, bytes], patch: bytes) -> dict[str, bytes]:
    """Apply bounded unified hunks to existing archive files, without subprocesses.

    No file creation, deletion, rename, mode changes, binary deltas, offset
    searching, or fuzzy context matching is supported.
    """
    if len(patch) > MAX_PATCH_BYTES:
        raise DependencyError("The reference dependency patch exceeds the size limit.")
    lines = patch.splitlines(keepends=True)
    changed: dict[str, bytes] = {}
    cursor = 0

    def invalid() -> DependencyError:
        return DependencyError("The reference dependency patch has unsupported or mismatched literal hunks.")

    while cursor < len(lines):
        header = re.fullmatch(rb"diff --git a/([A-Za-z0-9_./-]+) b/\1\n", lines[cursor])
        if header is None or cursor + 3 >= len(lines):
            raise invalid()
        relative = header[1].decode("ascii")
        path = PurePosixPath(relative)
        if (path.is_absolute() or ".." in path.parts or path.as_posix() != relative
                or relative not in files or relative in changed or len(changed) >= 100):
            raise invalid()
        if (re.fullmatch(rb"index [0-9a-f]{40}\.\.[0-9a-f]{40} 100644\n", lines[cursor + 1]) is None
                or lines[cursor + 2] != b"--- a/" + header[1] + b"\n"
                or lines[cursor + 3] != b"+++ b/" + header[1] + b"\n"):
            raise invalid()
        cursor += 4
        source = files[relative].splitlines(keepends=True)
        output: list[bytes] = []
        position = 0
        hunks = 0
        while cursor < len(lines) and lines[cursor].startswith(b"@@ "):
            hunk = re.fullmatch(rb"@@ -(\d{1,9})(?:,(\d{1,9}))? \+(\d{1,9})(?:,(\d{1,9}))? @@[^\n]*\n", lines[cursor])
            if hunk is None or hunks >= 1000:
                raise invalid()
            old_count = int(hunk[2]) if hunk[2] is not None else 1
            new_count = int(hunk[4]) if hunk[4] is not None else 1
            old_start = int(hunk[1]) - (1 if old_count else 0)
            new_start = int(hunk[3]) - (1 if new_count else 0)
            if old_start < position or old_start > len(source):
                raise invalid()
            output.extend(source[position:old_start])
            if new_start != len(output):
                raise invalid()
            cursor += 1
            body: list[tuple[bytes, bytes]] = []
            while cursor < len(lines) and lines[cursor][:1] in (b" ", b"+", b"-", b"\\"):
                line = lines[cursor]
                if line == b"\\ No newline at end of file\n":
                    if not body or not body[-1][1].endswith(b"\n"):
                        raise invalid()
                    prefix, content = body[-1]
                    body[-1] = (prefix, content[:-1])
                else:
                    if line[:1] == b"\\" or not line.endswith(b"\n"):
                        raise invalid()
                    body.append((line[:1], line[1:]))
                cursor += 1
            before = [content for prefix, content in body if prefix != b"+"]
            after = [content for prefix, content in body if prefix != b"-"]
            if (len(before) != old_count or len(after) != new_count
                    or source[old_start:old_start + old_count] != before):
                raise invalid()
            output.extend(after)
            position = old_start + old_count
            hunks += 1
        if not hunks:
            raise invalid()
        output.extend(source[position:])
        changed[relative] = b"".join(output)
    if not changed:
        raise invalid()
    result = files | changed
    if sum(map(len, result.values())) > MAX_EXTRACTED_BYTES:
        raise DependencyError("The patched reference dependency exceeds the extracted size limit.")
    return result


def _archive_files(raw: bytes, integrity: str, name: str = "") -> dict[str, bytes]:
    """Authenticate the archive before inspecting its bounded, regular contents."""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise DependencyError("The reference dependency archive exceeds the size limit.")
    actual = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")
    if actual != integrity:
        raise DependencyError("The reference dependency archive failed its pinned integrity check.")
    files: dict[str, bytes] = {}
    total = 0
    # DefinitelyTyped publishes its authenticated archives below the package
    # basename (for example mdast/), rather than npm's usual package/ prefix.
    # Only the requested, pinned @types package may authorize that alternate.
    roots = {"package"}
    if re.fullmatch(r"@types/[a-z0-9][a-z0-9._-]*", name):
        roots.add(name.removeprefix("@types/"))
    archive_root = None
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                        or not path.parts or path.parts[0] not in roots
                        or path.as_posix() != member.name.rstrip("/")):
                    raise DependencyError("A reference dependency archive contains an unsafe path.")
                if archive_root is not None and path.parts[0] != archive_root:
                    raise DependencyError("A reference dependency archive contains mixed package roots.")
                archive_root = path.parts[0]
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


def _runtime_dependencies(lock: bytes, name: str, version: str) -> dict[str, str]:
    """Read exact mandatory edges from the pinned lockfile's snapshot stanza."""
    # The pinned pnpm lock has two YAML documents: pnpm's own executable
    # closure, then the project closure. Only inspect snapshot sections, never
    # an identically named package-resolution stanza elsewhere in the file.
    sections = re.findall(r"(?ms)^snapshots:\n(.*?)(?=^---(?:\n|$)|\Z)", lock.decode("utf-8"))
    quoted = "'" if name.startswith("@") else ""
    # A peer context changes pnpm's snapshot identity, but not the tarball's
    # exact version. The flat oracle supports only one snapshot per version;
    # reject multiple contexts even when their mandatory edges happen to agree.
    peer_context = r"(?:\([@a-zA-Z0-9_./-]+@\d+\.\d+\.\d+\))*"
    patch = next((item[3] for item in PACKAGE_PATCHES if item[:2] == (name, version)), None)
    contexts = r"(?P<context>(?:\(patch_hash=[0-9a-f]{64}\))?" + peer_context + ")"
    key = re.escape(quoted + name + "@" + version) + contexts + re.escape(quoted)
    matches = [(section, match) for section in sections
               for match in re.finditer(r"^  " + key + r":(?P<inline>.*)$", section, re.MULTILINE)]
    if len(matches) != 1:
        raise DependencyError("The dependency runtime snapshot is not uniquely pinned.")
    snapshots, match = matches[0]
    context = match["context"]
    if ((patch is not None and not context.startswith(f"(patch_hash={patch})"))
            or (patch is None and context.startswith("(patch_hash="))):
        raise DependencyError("The dependency runtime snapshot is not uniquely pinned.")
    if match["inline"].strip() == "{}":
        return {}
    remainder = snapshots[match.end():]
    end = re.search(r"\n  \S", remainder)
    block = remainder[:end.start()] if end else remainder
    edges: dict[str, str] = {}
    reading = False
    for line in block.splitlines():
        if line == "    dependencies:":
            reading = True
        elif line.startswith("    ") and not line.startswith("      "):
            reading = False
        elif reading and line.strip():
            edge = re.fullmatch(r"      '?([@a-zA-Z0-9_./-]+)'?: (\d+\.\d+\.\d+)" + peer_context, line)
            if edge is None or edge[1] in edges:
                raise DependencyError("The dependency runtime snapshot has unsupported or ambiguous edges.")
            edges[edge[1]] = edge[2]
    return edges


def _validate_runtime_closure(package: dict, lock: bytes, authorized: dict[str, str]) -> None:
    declared = package.get("dependencies", {})
    peers = package.get("peerDependencies", {})
    metadata = package.get("peerDependenciesMeta", {})
    if (not isinstance(declared, dict) or not isinstance(peers, dict) or not isinstance(metadata, dict)
            or any(not isinstance(item, dict) for item in metadata.values())):
        raise DependencyError("The authenticated package has invalid runtime dependencies.")
    mandatory = set(declared) | {name for name in peers if metadata.get(name, {}).get("optional") is not True}
    edges = _runtime_dependencies(lock, package["name"], package["version"])
    if mandatory != set(edges) or any(authorized.get(name) != version for name, version in edges.items()):
        raise DependencyError("The authenticated runtime dependencies differ from the authorized lockfile closure.")


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
    authorized = {dependency["name"]: dependency["version"] for dependency in dependencies}
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
        files = _archive_files(raw, integrity, name)
        try:
            package = json.loads(files["package.json"])
        except (ValueError, UnicodeError):
            raise DependencyError("The authenticated dependency manifest is invalid.") from None
        if package.get("name") != name or package.get("version") != version:
            raise DependencyError("The authenticated dependency has the wrong name or version.")
        _validate_runtime_closure(package, lock, authorized)
        patch = _committed_patch(checkout, lock, name, version)
        if patch is not None:
            files = _apply_literal_patch(files, patch[0])
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
                         "directory": str(directory), "files": evidence}
                        | ({"patch": patch[1]} if patch is not None else {}))
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
                                   | {"files": len(package["files"])}
                                   | ({"patch": package["patch"]} if "patch" in package else {})
                                   for package in config["packages"]],
                      "installScriptsRun": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
