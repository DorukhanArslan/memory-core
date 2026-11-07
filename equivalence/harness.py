"""Strict execution and reporting for the fresh differential acceptance suite.

Missing evidence is never a successful comparison. The full gate requires every
declared acceptance point, while smoke mode compares only registered cases.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class HarnessError(RuntimeError):
    """A fixed, credential-free diagnostic for unavailable comparison evidence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _json(raw: str) -> Any:
    def invalid_constant(_: str) -> None:
        raise ValueError("non-finite JSON constant")

    return json.loads(raw, parse_constant=invalid_constant)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _committed_digest(checkout: Path, relative: str) -> str:
    try:
        result = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=checkout,
                                capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise HarnessError("oracle-source-mismatch", "Committed source evidence could not be verified.") from None
    if result.returncode != 0:
        raise HarnessError("oracle-source-mismatch", "The oracle imported source not present in the pinned Git tree.")
    return hashlib.sha256(result.stdout).hexdigest()


def _load(path: Path) -> Any:
    try:
        return _json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise HarnessError("manifest-unavailable", "A required suite manifest is missing or invalid.") from None


def _implementation_identity() -> dict[str, Any]:
    digest = hashlib.sha256()
    paths = sorted((ROOT / "memory_core").rglob("*.py"))
    if not paths:
        raise HarnessError("implementation-missing", "Python implementation source evidence is unavailable.")
    for path in paths:
        if path.is_symlink():
            raise HarnessError("implementation-unsafe", "Python implementation source cannot contain symlinks.")
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return {"gitCommit": _command(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "trackedWorkingTreeDirty": bool(_command(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT)),
            "sourceSha256": digest.hexdigest(), "sourceFiles": len(paths)}


def _command(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise HarnessError("preflight-failed", "A required preflight command could not complete.") from None
    if result.returncode != 0:
        raise HarnessError("preflight-failed", "A required preflight command failed.")
    return result.stdout.strip()


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise HarnessError("node-unsupported", "Node did not report a supported release version.")
    return tuple(int(part) for part in match.groups())


def _supports_node(version: str, ranges: str) -> bool:
    """Evaluate the simple comparator ranges in the pinned release contract."""
    parsed = _version(version)
    for alternative in ranges.split("||"):
        comparisons = re.findall(r"(>=|<=|>|<|=)?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", alternative)
        residue = re.sub(r"(>=|<=|>|<|=)?\s*\d+(?:\.\d+)?(?:\.\d+)?", "", alternative)
        if not comparisons or residue.strip():
            raise HarnessError("node-range-invalid", "The reference Node range is not supported by this gate.")
        accepted = True
        for operator, major, minor, patch in comparisons:
            bound = (int(major), int(minor or 0), int(patch or 0))
            checks = {">=": parsed >= bound, ">": parsed > bound, "<=": parsed <= bound,
                      "<": parsed < bound, "=": parsed == bound, "": parsed == bound}
            accepted = accepted and checks[operator]
        if accepted:
            return True
    return False


def _validate_reference(checkout: Path, node: Path, target: dict[str, Any]) -> dict[str, Any]:
    commit, tag = target.get("commit"), target.get("tag")
    if (not isinstance(commit, str) or not _SHA.fullmatch(commit)
            or not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag)):
        raise HarnessError("reference-contract-invalid", "The suite requires an exact release and Git commit.")
    if not checkout.is_dir() or not (checkout / ".git").exists():
        raise HarnessError("reference-missing", "An actual pinned OpenClaw Git checkout is required.")
    actual = _command(["git", "rev-parse", "HEAD"], cwd=checkout)
    if actual != commit:
        raise HarnessError("reference-commit-mismatch", "The reference checkout is at the wrong Git commit.")
    top = Path(_command(["git", "rev-parse", "--show-toplevel"], cwd=checkout)).resolve()
    if top != checkout.resolve():
        raise HarnessError("reference-root-mismatch", "The reference path must identify the checkout root.")
    if _command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=checkout):
        raise HarnessError("reference-dirty", "The reference checkout has modified tracked files.")
    package = _load(checkout / "package.json")
    if not isinstance(package, dict) or package.get("version") != tag.removeprefix("v"):
        raise HarnessError("reference-version-mismatch", "The reference package version differs from the release contract.")
    if not node.is_file() or not os.access(node, os.X_OK):
        raise HarnessError("node-missing", "An executable Node binary is required.")
    actual_node = _command([str(node), "--version"])
    ranges = target.get("nodeRanges")
    if isinstance(ranges, list):
        ranges = " || ".join(ranges)
    if not isinstance(ranges, str) or not _supports_node(actual_node, ranges):
        raise HarnessError("node-unsupported", "Node is outside the pinned release's supported range.")
    minimum = target.get("nodeMin")
    if not isinstance(minimum, str) or _version(actual_node) < _version(minimum):
        raise HarnessError("node-unsupported", "Node is below the suite's minimum supported version.")
    package_ranges = package.get("engines", {}).get("node")
    if not isinstance(package_ranges, str) or not _supports_node(actual_node, package_ranges):
        raise HarnessError("node-unsupported", "Node is outside the reference package's supported range.")
    return {"tag": tag, "commit": actual, "tree": _command(["git", "rev-parse", "HEAD^{tree}"], cwd=checkout),
            "nodeVersion": actual_node, "packageVersion": package["version"],
            "packageSha256": _digest(checkout / "package.json")}


def _validate_scope(scope: Any, cases: Any) -> tuple[list[dict], dict[str, set[str]]]:
    if not isinstance(scope, dict) or scope.get("schemaVersion") != 1:
        raise HarnessError("scope-invalid", "A versioned acceptance scope is required.")
    requirements = scope.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise HarnessError("scope-invalid", "The acceptance scope cannot be empty.")
    points: dict[str, set[str]] = {}
    all_points: set[str] = set()
    for requirement in requirements:
        if (not isinstance(requirement, dict) or not isinstance(requirement.get("id"), str)
                or not requirement["id"] or requirement["id"] in points
                or type(requirement.get("required")) is not bool):
            raise HarnessError("scope-invalid", "Requirement identifiers must be unique and explicit.")
        acceptance = requirement.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance:
            raise HarnessError("scope-invalid", "Each requirement needs explicit acceptance points.")
        ids: set[str] = set()
        for point in acceptance:
            if (not isinstance(point, dict) or not isinstance(point.get("id"), str)
                    or not point["id"] or point["id"] in all_points
                    or not isinstance(point.get("description"), str) or not point["description"]):
                raise HarnessError("scope-invalid", "Acceptance point identifiers must be unique and described.")
            ids.add(point["id"])
            all_points.add(point["id"])
        points[requirement["id"]] = ids
    if not any(row["required"] for row in requirements):
        raise HarnessError("scope-invalid", "The full gate needs at least one mandatory requirement.")
    if not isinstance(cases, list) or not cases:
        raise HarnessError("cases-invalid", "At least one actual differential case is required.")
    case_ids: set[str] = set()
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not case["id"] or case["id"] in case_ids
                or case.get("requirement") not in points
                or not isinstance(case.get("operation"), str) or not case["operation"]
                or "input" not in case or not isinstance(case.get("covers"), list)
                or any(not isinstance(point, str) for point in case["covers"])
                or len(set(case["covers"])) != len(case["covers"])
                or not set(case["covers"]) <= points[case["requirement"]]):
            raise HarnessError("cases-invalid", "Cases must have unique identities and valid acceptance-point coverage.")
        case_ids.add(case["id"])
    return requirements, points


def _oracle(node: Path, script: Path, checkout: Path, cases: list[dict], timeout: float) -> dict:
    if not script.is_file():
        raise HarnessError("oracle-missing", "The independent TypeScript oracle runner is missing.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 120:
        raise HarnessError("timeout-invalid", "The oracle requires a finite timeout of at most 120 seconds.")
    body = json.dumps({"cases": cases}, ensure_ascii=False, allow_nan=False)
    # No provider credentials, runtime switches, Node options or user auth state
    # cross into the source-only oracle. There is one dispatch and no retry.
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC"}
    process = None
    try:
        process = subprocess.Popen([str(node), str(script), str(checkout)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env, cwd=script.parent,
                                   start_new_session=os.name == "posix")
        stdout, _ = process.communicate(body, timeout=timeout)
        if process.returncode != 0:
            raise HarnessError("oracle-failed", "The TypeScript oracle exited unsuccessfully; no retry was made.")
        if len(stdout.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise HarnessError("oracle-output-limit", "The TypeScript oracle exceeded the bounded result size.")
        result = _json(stdout)
    except subprocess.TimeoutExpired:
        if process is not None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
        raise HarnessError("oracle-timeout", "The TypeScript oracle timed out; no retry was made.") from None
    except OSError:
        raise HarnessError("oracle-unavailable", "The TypeScript oracle could not start.") from None
    except (ValueError, UnicodeError):
        raise HarnessError("oracle-protocol", "The TypeScript oracle did not return valid bounded JSON.") from None
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise HarnessError("oracle-protocol", "The TypeScript oracle returned an invalid result envelope.")
    rows = result["results"]
    expected = {case["id"] for case in cases}
    seen: set[str] = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or row["id"] not in expected or row["id"] in seen
                or type(row.get("ok")) is not bool
                or set(row) != ({"id", "ok", "result"} if row["ok"] else {"id", "ok", "error"})):
            raise HarnessError("oracle-protocol", "The TypeScript oracle returned duplicate or invalid case identities.")
        seen.add(row["id"])
    if seen != expected:
        raise HarnessError("oracle-protocol", "The TypeScript oracle omitted registered cases.")
    sources = result.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise HarnessError("oracle-protocol", "The TypeScript oracle returned invalid source evidence.")
    seen_sources: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise HarnessError("oracle-protocol", "The TypeScript oracle returned invalid source evidence.")
        path = (checkout / source["path"]).resolve()
        expected_hash = source.get("sha256")
        if (Path(source["path"]).is_absolute() or ".." in Path(source["path"]).parts
                or Path(source["path"]).as_posix() != source["path"]
                or not path.is_relative_to(checkout.resolve()) or source["path"] in seen_sources
                or not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash)
                or not path.is_file() or _digest(path) != expected_hash
                or _committed_digest(checkout, source["path"]) != expected_hash):
            raise HarnessError("oracle-source-mismatch", "Oracle source evidence does not match the reference checkout.")
        seen_sources.add(source["path"])
    if not any(Path(path).suffix in {".ts", ".mts", ".cts"} for path in seen_sources):
        raise HarnessError("oracle-source-mismatch", "The oracle did not identify any committed TypeScript source.")
    return result


def _same_json(left: Any, right: Any) -> bool:
    # bool is a subclass of int in Python; JSON booleans must not pass as 1/0.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def run_suite(*, checkout: Path, node: Path, smoke: bool = False,
              reference_path: Path = ROOT / "equivalence/reference.json",
              scope_path: Path = ROOT / "equivalence/scope.json",
              oracle_path: Path = ROOT / "equivalence/oracle.mjs",
              cases: list[dict] | None = None,
              python_runner: Callable[[dict], Any] | None = None,
              timeout_seconds: float = 30) -> tuple[dict, int]:
    """Return the report and exit code 0(pass), 1(incomplete/diff), 2(blocked)."""
    started = time.monotonic()
    report: dict[str, Any] = {
        "schemaVersion": 1, "kind": "pinned-differential-acceptance",
        "mode": "smoke" if smoke else "full", "startedAt": datetime.now(timezone.utc).isoformat(),
        "claim": "Registered cases only; no full-equivalence claim." if smoke else
                 "All declared acceptance points are required; historical match labels are not evidence.",
        "environment": {"pythonVersion": platform.python_version(), "platform": sys.platform},
        "status": "blocked", "cases": [], "requirements": [], "errors": [],
        "providerMode": "model-free local fixtures", "providerCredentialsForwarded": False,
        "paidProviderCalls": 0,
    }
    try:
        target, scope = _load(reference_path), _load(scope_path)
        if not isinstance(target, dict):
            raise HarnessError("reference-contract-invalid", "A versioned reference contract is required.")
        if cases is None or python_runner is None:
            from equivalence.cases import build_cases, run_python
            cases = build_cases() if cases is None else cases
            python_runner = run_python if python_runner is None else python_runner
        requirements, _ = _validate_scope(scope, cases)
        report["manifestSha256"] = {"reference": _digest(reference_path), "scope": _digest(scope_path)}
        source_map = ROOT / "equivalence/source-map.json"
        if (reference_path.resolve() == ROOT / "equivalence/reference.json"
                and scope_path.resolve() == ROOT / "equivalence/scope.json" and source_map.is_file()):
            # Inventory identity is traceability metadata, never case coverage.
            report["manifestSha256"]["sourceMap"] = _digest(source_map)
        report["reference"] = _validate_reference(checkout, node, target)
        report["implementation"] = _implementation_identity()
        report["oracleSha256"] = _digest(oracle_path) if oracle_path.is_file() else None
        case_module = ROOT / "equivalence/cases.py"
        report["casesSha256"] = _digest(case_module) if case_module.is_file() else None
        oracle = _oracle(node, oracle_path, checkout, cases, timeout_seconds)
        # A source mutation during comparison invalidates every observed result.
        after = _validate_reference(checkout, node, target)
        if after != report["reference"]:
            raise HarnessError("reference-changed", "The reference checkout changed during comparison.")
        report["sources"] = oracle.get("sources", [])
        native_rows = {row["id"]: row for row in oracle["results"]}
        for case in cases:
            row = {"id": case["id"], "requirement": case["requirement"], "covers": case["covers"],
                   "operation": case["operation"], "input": case["input"]}
            native = native_rows[case["id"]]
            if not native["ok"]:
                row.update(status="blocked", code="oracle-case-failed")
            else:
                try:
                    python = python_runner(deepcopy(case))
                    # Reject non-JSON outputs and non-finite values explicitly.
                    python = _json(json.dumps(python, ensure_ascii=False, allow_nan=False))
                    row["status"] = "matched" if _same_json(python, native["result"]) else "mismatched"
                    if row["status"] == "mismatched":
                        row.update(operation=case["operation"], input=case["input"],
                                   python=python, openclaw=native["result"])
                except Exception:
                    row.update(status="blocked", code="python-case-failed")
            report["cases"].append(row)
        after_implementation = _implementation_identity()
        if after_implementation["sourceSha256"] != report["implementation"]["sourceSha256"]:
            raise HarnessError("implementation-changed", "Python implementation changed during comparison.")
        by_requirement = {requirement["id"]: [] for requirement in requirements}
        for row in report["cases"]:
            by_requirement[row["requirement"]].append(row)
        for requirement in requirements:
            rows = by_requirement[requirement["id"]]
            acceptance = []
            for point in requirement["acceptance"]:
                covering = [row for row in rows if point["id"] in row["covers"]]
                acceptance.append({"id": point["id"], "caseIds": [row["id"] for row in covering],
                                   "matchedCaseIds": [row["id"] for row in covering if row["status"] == "matched"]})
            report["requirements"].append({"id": requirement["id"], "required": requirement["required"],
                                            "acceptance": acceptance, "registeredCases": len(rows)})
        uncovered = [point["id"] for requirement in report["requirements"] if requirement["required"]
                     for point in requirement["acceptance"] if not point["caseIds"]]
        report["uncoveredAcceptance"] = uncovered
        statuses = [row["status"] for row in report["cases"]]
        report["summary"] = {name: statuses.count(name) for name in ("matched", "mismatched", "blocked")}
        report["summary"]["uncoveredAcceptance"] = len(uncovered)
        if "blocked" in statuses:
            report["status"] = "blocked"
        elif "mismatched" in statuses:
            report["status"] = "mismatched"
        elif not smoke and uncovered:
            report["status"] = "incomplete"
        else:
            report["status"] = "passed"
    except HarnessError as error:
        report["errors"].append({"code": error.code, "message": str(error)})
    except Exception:
        report["errors"].append({"code": "harness-failed", "message": "The acceptance harness could not complete."})
    report["durationSeconds"] = round(time.monotonic() - started, 6)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report["fullScopePassed"] = report["mode"] == "full" and report["status"] == "passed"
    exit_code = 0 if report["status"] == "passed" else 2 if report["status"] == "blocked" else 1
    return report, exit_code
