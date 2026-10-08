"""Check selected public types against an installed artifact, outside the checkout.

The calling interpreter supplies mypy; --python-executable supplies the clean
artifact environment. This checks consumer contracts, not all implementation bodies.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_ERROR = re.compile(r"^(.*):(\d+): error: .*  \[([a-z-]+)\]$")
_EXPECTED = re.compile(r"# E: ([a-z,-]+)\s*$")


def validate_result(result: subprocess.CompletedProcess[str], fixture: Path) -> None:
    """Require exact negative diagnostics; a checker/setup failure is never a pass."""
    expected: Counter[tuple[int, str]] = Counter()
    for number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), 1):
        if match := _EXPECTED.search(line):
            expected.update((number, code) for code in match[1].split(","))
    actual: Counter[tuple[int, str]] = Counter()
    for line in result.stdout.splitlines():
        if ": note: " in line:
            continue
        match = _ERROR.fullmatch(line)
        if match is None or Path(match[1]).name != fixture.name:
            raise RuntimeError(f"unexpected mypy output for {fixture.name}: {line}")
        actual[(int(match[2]), match[3])] += 1
    wanted_code = 1 if expected else 0
    if result.stderr or result.returncode != wanted_code or actual != expected:
        raise RuntimeError(
            f"consumer contract failed for {fixture.name}: expected {dict(expected)}, "
            f"got {dict(actual)} (exit {result.returncode})\n{result.stdout}{result.stderr}"
        )


def check_consumer(python_executable: Path) -> None:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "MYPYPATH"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="memory-core-types-") as temporary:
        scratch = Path(temporary)
        probe = subprocess.run(
            [str(python_executable), "-I", "-B", "-c",
             "import importlib.util, json, sys; "
             "spec = importlib.util.find_spec('memory_core'); "
             "print(json.dumps({'origin': spec.origin if spec else None, 'prefix': sys.prefix}))"],
            cwd=scratch, env=env, capture_output=True, text=True, check=True, timeout=30,
        )
        installed = json.loads(probe.stdout)
        if not installed["origin"]:
            raise RuntimeError("memory_core is not installed in the consumer environment")
        origin = Path(installed["origin"]).resolve()
        if origin.is_relative_to(ROOT) or not origin.is_relative_to(Path(installed["prefix"]).resolve()):
            raise RuntimeError("consumer environment must import an isolated installed artifact")
        for name in ("public_api.py", "invalid_public_api.py"):
            fixture = scratch / name
            shutil.copyfile(HERE / name, fixture)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "mypy", "--python-executable", str(python_executable),
                 "--config-file", str(HERE / "mypy.ini"), "--no-incremental",
                 "--cache-dir", str(scratch / "mypy-cache"), str(fixture)],
                cwd=scratch, env=env, capture_output=True, text=True, check=False, timeout=90,
            )
            validate_result(result, fixture)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-executable", required=True, type=Path)
    args = parser.parse_args()
    try:
        # Keep the venv executable's symlink path: resolving it would select the base Python.
        check_consumer(args.python_executable.absolute())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("installed public typing: valid consumer accepted; 6 invalid calls rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
