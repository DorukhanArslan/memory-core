"""Restore the original hosted comparison's two sealed artifacts without executing the SDK."""
import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


REPOSITORY = "DorukhanArslan/memory-core"
REPOSITORY_ID = 1393816346
RUN = 44214324963
COMMIT = "8b00530188a1d6e87a02172bebf7b6e8b5c49433"
WORKSPACE = Path("/home/runner/work/memory-core/memory-core")
TEMPORARY = Path("/home/runner/work/_temp")
RAW = (14392639892, "memory-contract-remainder-raw-evidence", 2582430612,
       "f74f90cb038cfe47425e9f61d7a8601dfaa85dce79f56b3642e64dd67f8b07e5")
SUMMARY = (14393591298, "memory-contract-remainder-summary", 308200,
           "bca913e53324e08fa7b73a2f2bac8e31e07a2e4f784d38de327fd6c001d42a3d")
REPORT = {"bytes": 1907529876, "sha256": "2d661807ea171e02ee8f1676ac5eb94b30e720de396141ae65572e0c9e358e7f"}
CHUNK = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, location):
        return None


def https(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password,
            "Artifact storage requires HTTPS without URL credentials")
    return url


class StorageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, location):
        return super().redirect_request(request, fp, code, message, headers, https(location))


def download(seal, target):
    identifier, name, size, sha = seal
    api = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{identifier}"
    headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    github = urllib.request.build_opener(NoRedirect)
    with github.open(urllib.request.Request(api, headers=headers), timeout=60) as response:
        meta = json.load(response)
    source = meta["workflow_run"]
    require((meta["id"], meta["name"], meta["size_in_bytes"], meta["digest"], meta["expired"])
            == (identifier, name, size, "sha256:" + sha, False)
            and (source["id"], source["head_sha"], source["repository_id"], source["head_repository_id"])
            == (RUN, COMMIT, REPOSITORY_ID, REPOSITORY_ID), "Wrong original artifact, run or source")
    try:
        with github.open(urllib.request.Request(api + "/zip", headers=headers), timeout=60):
            raise ValueError("GitHub did not return a signed download location")
    except urllib.error.HTTPError as redirect:
        with redirect:
            require(redirect.code == 302, f"Unexpected GitHub artifact HTTP status {redirect.code}")
            location = https(redirect.headers["Location"])
    # Create a separate request and opener so GitHub authorization never reaches artifact storage.
    count, digest = 0, hashlib.sha256()
    with urllib.request.build_opener(StorageRedirect).open(location, timeout=180) as response, target.open("xb") as out:
        while block := response.read(CHUNK):
            count += len(block)
            require(count <= size, "Archive exceeded its pinned size")
            digest.update(block)
            out.write(block)
    require(count == size and digest.hexdigest() == sha, "Wrong artifact ZIP bytes")


def archive_path(item):
    name = item.orig_filename
    require(name == item.filename and "\\" not in name and not name.startswith("/"), "Unsafe ZIP member name")
    parts = tuple(name.removesuffix("/").split("/"))
    require(all(part not in {"", ".", ".."} for part in parts), "Invalid ZIP member component")
    kind = stat.S_IFMT(item.external_attr >> 16)
    require(kind in {0, stat.S_IFDIR if item.is_dir() else stat.S_IFREG} and not item.flag_bits & 1,
            "Unsupported ZIP member type")
    return PurePosixPath(*parts)


def destination(path, workspace, temporary, host_base):
    root = workspace / ".equivalence-results"
    scratch = temporary / f"memory-core-once-{RUN}"
    absolute = Path("/") / path
    if absolute.is_relative_to(root):
        return root, absolute
    if absolute.is_relative_to(scratch):
        return scratch, absolute
    if absolute.is_relative_to(host_base):
        parts = absolute.relative_to(host_base).parts
        if parts and re.fullmatch(r"memory-host-v4-[a-z0-9_]{8}", parts[0]):
            return host_base / parts[0], absolute
    return None


def restore(package, workspace, temporary, host_base, created):
    plan, roots, sizes, members, directories, structural = [], set(), {}, set(), set(), set()
    seen = set()
    for item in package.infolist():
        path = archive_path(item)
        require(path not in seen, "Duplicate ZIP member")
        seen.add(path)
        target = destination(path, workspace, temporary, host_base)
        if target is None:
            require(item.is_dir(), "Artifact file outside its recorded comparison roots")
            structural.add(Path("/") / path)
            continue
        root, dest = target
        require(dest != root or item.is_dir(), "File in place of a comparison root")
        roots.add(root)
        if item.is_dir():
            directories.add(dest)
        else:
            members.add(dest)
            sizes[root] = sizes.get(root, 0) + item.file_size
        plan.append((item, dest))
    require(workspace / ".equivalence-results/full.json" in members, "Original full report missing")
    require(structural <= {p for root in roots for p in root.parents}, "Unexpected ZIP directory")
    require(not members.intersection(directories) and not any(
        parent in members for _, dest in plan for parent in dest.parents), "File/directory conflict in ZIP")
    devices = {}
    for root in roots:
        require(root.parent.is_dir() and root.parent.resolve(strict=True) == root.parent
                and not os.path.lexists(root), "Comparison root is occupied or redirected")
        device = root.parent.stat().st_dev
        current = devices.get(device, 0) + sizes.get(root, 0)
        devices[device] = current
        require(shutil.disk_usage(root.parent).free > current + 16 * CHUNK, "Insufficient expanded artifact space")
    for root in sorted(roots):
        root.mkdir(mode=0o700)
        created.callback(shutil.rmtree, root)
    for item, dest in plan:
        if item.is_dir():
            dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with package.open(item) as src, dest.open("xb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            require(dest.stat().st_size == item.file_size, "Short extracted ZIP file")
    return {"restoredRoots": sorted(str(root) for root in roots), "restoredFiles": len(members),
            "restoredBytes": sum(sizes.values()), "zipEntries": len(seen)}


def verify_summary(package, directory):
    files = sorted(directory.iterdir())
    require(len(files) == len(package.infolist()) and {f.name for f in files} == set(package.namelist()),
            "Raw archive and independently uploaded summary have different members")
    for item in package.infolist():
        path = archive_path(item)
        require(len(path.parts) == 1 and not item.is_dir(), "Unexpected summary ZIP member")
        with package.open(item) as src, (directory / path.name).open("rb") as actual:
            require(hashlib.file_digest(src, "sha256").digest() == hashlib.file_digest(actual, "sha256").digest(),
                    "Restored summary differs from its independent artifact")


def main():
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY and Path(os.environ["GITHUB_WORKSPACE"]) == WORKSPACE
            and Path(os.environ["RUNNER_TEMP"]) == TEMPORARY and TEMPORARY.resolve(strict=True) == TEMPORARY,
            "Restore requires the original repository and GitHub runner paths")
    receipt = TEMPORARY / "restoration.json"
    require(not os.path.lexists(receipt) and shutil.disk_usage(TEMPORARY).free > RAW[2] + SUMMARY[2] + 16 * CHUNK,
            "Restoration receipt already exists or archive space is insufficient")
    with tempfile.TemporaryDirectory(dir=TEMPORARY, prefix="sealed-comparison-") as temp, ExitStack() as created:
        archive, summary = Path(temp) / "raw.zip", Path(temp) / "summary.zip"
        download(SUMMARY, summary)
        download(RAW, archive)
        with zipfile.ZipFile(archive) as original:
            record = restore(original, WORKSPACE, TEMPORARY, Path("/var/tmp"), created)
        results = WORKSPACE / ".equivalence-results"
        with zipfile.ZipFile(summary) as evidence:
            verify_summary(evidence, results / "summary")
        with (results / "full.json").open("rb") as report:
            observed = {"bytes": os.fstat(report.fileno()).st_size, "sha256": hashlib.file_digest(report, "sha256").hexdigest()}
        require(observed == REPORT, "Wrong original full report bytes")
        record.update(runId=RUN, comparisonCommit=COMMIT, artifactId=RAW[0],
                      archive={"bytes": RAW[2], "sha256": RAW[3]}, fullReport=observed,
                      summaryArtifact={"id": SUMMARY[0], "bytes": SUMMARY[2], "sha256": SUMMARY[3]},
                      restorationView="complete")
        with receipt.open("x") as output:
            created.callback(receipt.unlink)
            json.dump(record, output, sort_keys=True)
            output.write("\n")
        created.pop_all()
        print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
