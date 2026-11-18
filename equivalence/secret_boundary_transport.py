"""Keep the original process streams of the four fixed synthetic boundary callers."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile

from equivalence.secret_boundary_inputs import build_cases, canonical


def retain_streams(case, root, stdout, stderr, *, directory=None):
    expected = next((c for c in build_cases() if c["id"] == case["id"]), None)
    if expected is None or canonical(case) != canonical(expected):
        raise ValueError("Process retention requires an exact registered synthetic input")
    family = root / ".equivalence-results" / "secret-redaction"
    family.mkdir(parents=True, exist_ok=True)
    if family.resolve(strict=True) != family:
        raise ValueError("Secret boundary evidence must stay under the canonical result root")
    if directory is None:
        directory = Path(tempfile.mkdtemp(prefix="native-attempt-", dir=family))
    if directory.resolve(strict=True) != directory or directory.parent != family:
        raise ValueError("Secret boundary process streams escaped the case root")
    out = {"directory": str(directory)}
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        raw = value.encode("utf-8")
        with (directory / (name + ".log")).open("xb") as stream:
            stream.write(raw)
        out[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return out
