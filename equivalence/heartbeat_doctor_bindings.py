"""Authenticate literal original Doctor declarations and official compiled owners."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SHA256 = "e08e2474e9582bac3fed1730cefe66c5c10a4d001380559191c85ba9bc1622c2"
COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"


def manifest():
    raw = (ROOT / "equivalence/heartbeat-doctor-bindings.proposal.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Doctor literal owner/role manifest changed without review")
    return json.loads(raw)


def prepare_doctor_bindings(checkout: Path, runtime_root: Path):
    value = manifest()
    checkout, runtime_root = checkout.resolve(strict=True), runtime_root.resolve(strict=True)
    def git(*args):
        return subprocess.run(["git", *args], cwd=checkout, capture_output=True, check=True, timeout=10).stdout
    if (git("rev-parse", "HEAD").decode().strip() != COMMIT or
            Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout or
            git("status", "--porcelain", "--untracked-files=no").strip()):
        raise ValueError("Doctor requires its clean original reference root")
    for name, digest in value["sourcePins"].items():
        original = git("show", "HEAD:" + name)
        if hashlib.sha256(original).hexdigest() != digest or (checkout / name).is_symlink() or (checkout / name).read_bytes() != original:
            raise ValueError("An original Doctor source owner changed")
    for name, digest in value["compiledPins"].items():
        file = runtime_root / name
        data = file.read_bytes()
        if file.is_symlink() or file.stat().st_nlink != 1 or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("A compiled Doctor owner differs from its reviewed literal pin")
        pairs = set()
        for declaration in re.findall(r"export\s*\{([^}]+)\}", data.decode()):
            for item in declaration.split(","):
                names = item.strip().split(" as ")
                if names and names[0]:
                    pairs.add((names[0].strip(), names[-1].strip()))
        for original, alias in value["actualCompiledExports"].get(name, {}).items():
            if (original, alias) not in pairs:
                raise ValueError("A Doctor owner lost its exact original direct export")
    return {"kind": "verified-heartbeat-doctor-original-bindings", "manifestSha256": MANIFEST_SHA256,
            "reference": value["reference"], "sourceBuildReproduced": False,
            "sourcePins": value["sourcePins"], "compiledPins": value["compiledPins"],
            "actualCompiledExports": value["actualCompiledExports"], "executionRoles": value["executionRoles"]}
