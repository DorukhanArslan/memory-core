#!/usr/bin/env python3
"""Restore a fixed original report/capture artifact without running engines."""
import hashlib, json, os, shutil, stat, urllib.error, urllib.parse, urllib.request, zipfile
from pathlib import Path

ARTIFACT, SIZE = 14189821910, 2381341124
SHA = "8d800ec817c61dc8e9d2cca5f04d6a6a8c5dd3d2a51451b6a2de507bf3c68c51"
REPORT_SHA = "63a36bff1fcc78c14c56068dfc0dd3ddf39ada113fb591488ab3e3706348a799"
workspace, temporary = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True), Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
archive, receipt = temporary / "raw.zip", temporary / "restoration.json"
once_name = "memory-core-once-43772670403"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    result, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block); count += len(block)
    return {"bytes": count, "sha256": result.hexdigest()}

def anchors(parts):
    return [(index, workspace / name if name == ".equivalence-results" else temporary / name if name == once_name else Path("/var/tmp") / name)
            for index, name in enumerate(parts) if name in {".equivalence-results", once_name} or name.startswith("memory-host-v4-") and len(name) > len("memory-host-v4-")]

def safe_parent(path):
    for item in [path, *path.parents]:
        require(not item.is_symlink(), "A restoration path has a symlink ancestor")
        if item.exists():
            require(item.is_dir(), "A restoration ancestor is not a directory")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None

require(not archive.exists() and not receipt.exists(), "Restoration output already exists")
require(shutil.disk_usage(temporary).free > SIZE + 16 * 1024 * 1024, "Insufficient archive disk space")
repo = os.environ.get("GITHUB_REPOSITORY", "DorukhanArslan/memory-core")
request = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/artifacts/{ARTIFACT}/zip",
    headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
try:
    urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    raise ValueError("Artifact API did not return its expected redirect")
except urllib.error.HTTPError as response:
    require(response.code == 302, "Artifact API did not return HTTP 302")
    location = response.headers["Location"]
parsed = urllib.parse.urlsplit(location)
require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password, "Invalid signed artifact URL")
with urllib.request.urlopen(urllib.request.Request(location), timeout=60) as response, archive.open("xb") as output:
    hasher, downloaded = hashlib.sha256(), 0
    while block := response.read(1024 * 1024):
        downloaded += len(block); require(downloaded <= SIZE, "Artifact exceeds fixed archive size")
        output.write(block); hasher.update(block)
require(downloaded == SIZE and hasher.hexdigest() == SHA, "Artifact ZIP byte count or SHA differs")
with zipfile.ZipFile(archive) as package:
    entries, prefixes, structural = [], {}, set()
    for item in package.infolist():
        name = item.filename.rstrip("/")
        require(name and "\\" not in name and not name.startswith("/"), "Invalid ZIP entry name")
        parts = tuple(name.split("/")); require(all(part not in {"", ".", ".."} for part in parts), "Unsafe ZIP entry path")
        mode = item.external_attr >> 16
        require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in {0, stat.S_IFREG, stat.S_IFDIR}, "Unsupported ZIP entry type")
        entries.append((item, parts))
        candidates = anchors(parts)
        require(len(candidates) <= 1, "A ZIP entry has multiple allowed-root anchors")
        if not item.is_dir():
            require(len(candidates) == 1, "A ZIP file has no allowed-root anchor")
            index, root = candidates[0]; prefix = parts[:index + 1]
            require(root not in prefixes or prefixes[root] == prefix, "A restored root has multiple archive prefixes")
            prefixes[root] = prefix; structural.update(parts[:depth] for depth in range(1, index + 1))
    require(prefixes, "Artifact contains no original files")
    planned, seen, roots, devices = [], set(), set(), {}
    for item, parts in entries:
        if item.is_dir() and parts in structural: continue
        candidates = anchors(parts); require(len(candidates) == 1, "A ZIP entry has no unique allowed-root anchor")
        index, root = candidates[0]
        require(root in prefixes and prefixes[root] == parts[:index + 1], "A ZIP entry has an unknown archive root prefix")
        target = root.joinpath(*parts[index + 1:]); require(target not in seen, "Duplicate ZIP destination"); seen.add(target)
        safe_parent(target if item.is_dir() else target.parent)
        require(item.is_dir() or not target.exists(), "An original output already exists")
        planned.append((item, target)); roots.add(str(root))
        if not item.is_dir():
            ancestor = target.parent
            while not ancestor.exists(): ancestor = ancestor.parent
            device = ancestor.stat().st_dev; previous = devices.get(device, (ancestor, 0)); devices[device] = (previous[0], previous[1] + item.file_size)
    for ancestor, expanded in devices.values(): require(shutil.disk_usage(ancestor).free > expanded + 16 * 1024 * 1024, "Insufficient expanded artifact disk space")
    for item, target in planned:
        if item.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with package.open(item) as source, target.open("xb") as output: shutil.copyfileobj(source, output, 1024 * 1024)
report = workspace / ".equivalence-results/full.json"; report_seal = digest(report)
require(report_seal["sha256"] == REPORT_SHA, "Original full report SHA differs")
record = {"artifactId": ARTIFACT, "archive": {"bytes": downloaded, "sha256": hasher.hexdigest()}, "archivedRootPrefixes": sorted("/".join(prefix) for prefix in prefixes.values()), "restoredRoots": sorted(roots), "zipEntries": len(entries), "restoredFiles": sum(not item.is_dir() for item, _ in planned), "restoredBytes": sum(item.file_size for item, _ in planned), "fullReport": {"path": str(report), **report_seal}, "trackedSourceFilesModified": False}
with receipt.open("x") as output: json.dump(record, output, sort_keys=True); output.write("\n")
print(json.dumps(record, sort_keys=True))
