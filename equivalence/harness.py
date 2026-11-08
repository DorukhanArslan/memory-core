"""Strict execution and reporting for the fresh differential acceptance suite.

Missing evidence is never a successful comparison. The full gate requires every
declared acceptance point, while smoke mode compares only registered cases.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import tempfile
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


def _adapter_identity() -> dict[str, str]:
    paths = sorted((ROOT / "equivalence").glob("*.py")) + sorted((ROOT / "equivalence").glob("*.mjs"))
    fixture_manifest = ROOT / "equivalence/openclaw.plugin.json"
    if fixture_manifest.is_file():
        paths.append(fixture_manifest)
    return {path.name: _digest(path) for path in paths}


def _reference_bindings(checkout: Path, *, cache: bool, publication: bool,
                        reuse_operations: frozenset[str] = frozenset()) -> dict:
    from equivalence.reference_bindings import prepare_reference_bindings

    bindings = (prepare_reference_bindings(checkout, include_cache=True) if cache
                else prepare_reference_bindings(checkout))
    if publication:
        from equivalence.index_bindings import prepare_index_bindings

        extension = prepare_index_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    if reuse_operations & {"vector-scoring", "exact-path-priority"}:
        from equivalence.vector_bindings import prepare_vector_bindings

        extension = prepare_vector_bindings(checkout)
        if "vector-scoring" not in reuse_operations:
            extension = {key: [row for row in extension[key] if row["parent"].endswith(
                "/manager-search-shared.ts"
            )] for key in ("allowedResolutions", "projectionEvidence")}
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    if reuse_operations & {"hybrid-scoring", "exact-path-priority", "importance-project"}:
        from equivalence.hybrid_bindings import prepare_hybrid_bindings

        extension = prepare_hybrid_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    if "exact-path-priority" in reuse_operations:
        from equivalence.exact_path_bindings import prepare_exact_path_bindings

        extension = prepare_exact_path_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    if "importance-project" in reuse_operations:
        from equivalence.importance_project_bindings import prepare_importance_project_bindings

        extension = prepare_importance_project_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    if "search-contract" in reuse_operations:
        from equivalence.search_contract_bindings import prepare_search_contract_bindings

        extension = prepare_search_contract_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
        bindings["searchContractSourceOwners"] = {key: value for key, value in extension.items()
                                                 if key not in {"allowedResolutions", "projectionEvidence"}}
    if "get-contract" in reuse_operations:
        from equivalence.get_contract_bindings import prepare_get_contract_bindings

        extension = prepare_get_contract_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
        bindings["getContractSourceOwners"] = {key: value for key, value in extension.items()
                                              if key not in {"allowedResolutions", "projectionEvidence"}}
    if "deadline-partial" in reuse_operations:
        from equivalence.deadline_partial_bindings import prepare_deadline_partial_bindings

        extension = prepare_deadline_partial_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
        bindings["deadlinePartialSourceOwners"] = {key: value for key, value in extension.items()
                                                  if key not in {"allowedResolutions", "projectionEvidence"}}
    if "session-contract" in reuse_operations:
        from equivalence.session_admission_bindings import prepare_session_admission_bindings

        extension = prepare_session_admission_bindings(checkout)
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
        bindings["sessionAdmissionSourceOwners"] = {key: value for key, value in extension.items()
                                                   if key not in {"allowedResolutions", "projectionEvidence"}}
    if reuse_operations:
        from equivalence.reuse_bindings import prepare_reuse_bindings

        extension = prepare_reuse_bindings(
            checkout, bootstrap="bootstrap-budget" in reuse_operations,
            flush=bool(reuse_operations & {"flush-contract", "flush-target"}),
            session="session-projection" in reuse_operations,
        )
        for key in ("allowedResolutions", "projectionEvidence"):
            bindings.setdefault(key, []).extend(extension[key])
    resolutions = [(entry["parent"], entry["specifier"])
                   for entry in bindings.get("allowedResolutions", [])]
    if len(resolutions) != len(set(resolutions)):
        raise ValueError("Native binding projections conflict.")
    return bindings


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


def _oracle(node: Path, script: Path, checkout: Path, cases: list[dict], timeout: float,
            *, dependencies: dict | None = None, bindings: dict | None = None,
            release_runtime: dict | None = None) -> dict:
    if not script.is_file():
        raise HarnessError("oracle-missing", "The independent TypeScript oracle runner is missing.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 120:
        raise HarnessError("timeout-invalid", "The oracle requires a finite timeout of at most 120 seconds.")
    body = json.dumps({"cases": cases, "dependencies": dependencies,
                       "bindings": bindings}, ensure_ascii=False, allow_nan=False)
    # No provider credentials, runtime switches, Node options or user auth state
    # cross into the source-only oracle. There is one dispatch and no retry.
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC"}
    process = None
    resources = ExitStack()
    execution = None
    try:
        if release_runtime is not None:
            from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError

            try:
                context_options = ({"fixture_captures": True}
                                   if len(cases) == 1 and cases[0]["operation"] == "flush-execution-runtime"
                                   else {})
                execution = resources.enter_context(ReleaseOracleExecution(
                    release_runtime, _adapter_identity(), **context_options))
                # Only this reviewed preload is supplied. User Node options,
                # credentials, proxy/auth state and provider keys stay absent.
                env.update(execution.env)
            except (OSError, ValueError):
                raise HarnessError("runtime-context-invalid", "The verified release execution context is unavailable.") from None
        else:
            # Broad native facades may consult configuration while importing.
            # Keep that state and logging inside this invocation's owned tree;
            # no user home, configured secret or ambient OpenClaw state crosses
            # the credential-free reference boundary.
            source_root = Path(resources.enter_context(tempfile.TemporaryDirectory(
                prefix="memory-source-oracle-")))
            source_config = source_root / "openclaw.json"
            source_config.write_text(json.dumps({
                "logging": {"level": "silent", "consoleLevel": "silent",
                            "file": str(source_root / "native.log")},
                "session": {"maintenance": {"mode": "warn"}},
            }), encoding="utf-8")
            env.update({"OPENCLAW_STATE_DIR": str(source_root / "state"),
                        "OPENCLAW_CONFIG_PATH": str(source_config)})
        # Native retry helpers use TS parameter properties. Node's own source
        # loader executes these with its built-in transform support; no modified
        # reference files or precompiled stand-ins are used.
        flags = ["--experimental-transform-types"] if script.resolve() == ROOT / "equivalence/oracle.mjs" else []
        process = subprocess.Popen([str(node), *flags, str(script), str(checkout)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env, cwd=script.parent,
                                   start_new_session=os.name == "posix")
        stdout, _ = process.communicate(body, timeout=timeout)
        if process.returncode != 0:
            raise HarnessError("oracle-failed", "The TypeScript oracle exited unsuccessfully; no retry was made.")
        if len(stdout.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise HarnessError("oracle-output-limit", "The TypeScript oracle exceeded the bounded result size.")
        result = _json(stdout)
        if execution is not None:
            try:
                result = execution.collect(result, cases)
            except (OSError, ValueError) as error:
                detail = str(error) if isinstance(error, RuntimeOracleError) else "Invalid execution evidence."
                raise HarnessError("runtime-evidence-invalid",
                                   "The release runtime did not provide authenticated process and worker evidence: "
                                   + detail) from None
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
    finally:
        resources.close()
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
    if release_runtime is not None:
        if (result.get("kind") != "official-release-runtime-comparison" or result.get("sources") != []
                or not result.get("releaseSources")):
            raise HarnessError("runtime-evidence-invalid", "Compiled release evidence must remain separate from Git sources.")
        return result
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
              dependency_root: Path = ROOT / ".reference/npm",
              release_runtime_root: Path = ROOT / ".reference/release-runtime",
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
    resources = ExitStack()
    try:
        target, scope = _load(reference_path), _load(scope_path)
        if not isinstance(target, dict):
            raise HarnessError("reference-contract-invalid", "A versioned reference contract is required.")
        if cases is None or python_runner is None:
            from equivalence.cases import build_cases, run_python
            cases = build_cases() if cases is None else cases
            python_runner = run_python if python_runner is None else python_runner
        requirements, _ = _validate_scope(scope, cases)
        runtime_operations = {
            "index-lifecycle-runtime", "flush-trigger-runtime", "flush-execution-runtime",
            "exact-path-runtime",
            "importance-project-runtime",
            "search-contract-runtime", "search-contract-helper-runtime",
            "get-contract-runtime", "get-contract-helper-runtime",
            "deadline-partial-runtime",
            "deadline-partial-get-runtime",
            "session-contract-runtime", "session-contract-helper-runtime",
        }
        runtime_cases = [case for case in cases if case["operation"] in runtime_operations]
        source_cases = [case for case in cases if case["operation"] not in runtime_operations]
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
        dependencies = bindings = None
        required_artifact_execution = any(case["operation"] in {
            "storage-discovery", "storage-read-paths", "index-identity",
            "embedding-cache", "incremental-index",
            "index-publication",
        } for case in cases)
        reuse_operations = frozenset(case["operation"] for case in cases
                                     if case["operation"] in {
                                         "bootstrap-budget", "flush-contract", "flush-target", "session-projection",
                                         "vector-scoring", "hybrid-scoring", "exact-path-priority",
                                         "importance-project",
                                         "search-contract",
                                         "get-contract",
                                         "deadline-partial",
                                         "session-contract",
                                     })
        native_storage = required_artifact_execution or bool(reuse_operations)
        cache_bindings = any(case["operation"] == "embedding-cache" for case in cases)
        publication_bindings = any(case["operation"] == "index-publication" for case in cases)
        if native_storage:
            from equivalence.dependencies import prepare_dependencies

            try:
                dependencies = prepare_dependencies(checkout, dependency_root)
                bindings = _reference_bindings(checkout, cache=cache_bindings,
                                               publication=publication_bindings,
                                               reuse_operations=reuse_operations)
            except (OSError, ValueError, RuntimeError):
                raise HarnessError("reference-dependencies-unavailable",
                                   "Verified native dependencies and binding provenance are required; "
                                   "prepare them with python -m equivalence.dependencies --install.") from None
        adapter_hashes = _adapter_identity()
        report["adapterSha256"] = adapter_hashes
        oracle = (_oracle(node, oracle_path, checkout, source_cases, timeout_seconds,
                          dependencies=dependencies, bindings=bindings)
                  if source_cases else {"results": [], "sources": []})
        runtime_config = None
        if runtime_cases:
            from equivalence.release_runtime import prepare_release_runtime

            try:
                runtime_config = prepare_release_runtime(checkout, release_runtime_root)
            except (OSError, ValueError, RuntimeError):
                raise HarnessError("release-runtime-unavailable",
                                   "Authenticated official release artifacts are required; prepare them with "
                                   "python -m equivalence.release_runtime --install.") from None
            report["releaseRuntime"] = {key: value for key, value in runtime_config.items()
                                        if key not in {"runtimeRoot", "packages"}}
            report["releaseRuntime"]["packages"] = [
                {key: value for key, value in package.items() if key not in {"directory", "files"}}
                for package in runtime_config["packages"]
            ]
            flush_runtime = any(case["operation"] == "flush-trigger-runtime" for case in runtime_cases)
            if flush_runtime:
                from equivalence.flush_runtime_bindings import prepare_flush_runtime_bindings

                try:
                    report["flushRuntimeBindings"] = prepare_flush_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("flush-runtime-owner-unavailable",
                                       "The reviewed native flush owner/export could not be verified.") from None
            flush_execution = any(case["operation"] == "flush-execution-runtime" for case in runtime_cases)
            if flush_execution:
                from equivalence.flush_execution_bindings import prepare_flush_execution_bindings

                try:
                    report["flushExecutionBindings"] = prepare_flush_execution_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("flush-execution-owner-unavailable",
                                       "The reviewed native flush execution owners could not be verified.") from None
            exact_path_runtime = any(case["operation"] == "exact-path-runtime" for case in runtime_cases)
            if exact_path_runtime:
                from equivalence.exact_path_runtime_bindings import prepare_exact_path_runtime_bindings

                try:
                    report["exactPathRuntimeBindings"] = prepare_exact_path_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("exact-path-runtime-owner-unavailable",
                                       "The reviewed native keyword priority owners could not be verified.") from None
            importance_project_runtime = any(
                case["operation"] == "importance-project-runtime" for case in runtime_cases
            )
            if importance_project_runtime:
                from equivalence.importance_project_runtime_bindings import (
                    prepare_importance_project_runtime_bindings,
                )

                try:
                    report["importanceProjectRuntimeBindings"] = prepare_importance_project_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("importance-project-runtime-owner-unavailable",
                                       "The reviewed native stored-ranking owners could not be verified.") from None
            search_contract_runtime = any(case["operation"] in {
                "search-contract-runtime", "search-contract-helper-runtime",
            } for case in runtime_cases)
            if search_contract_runtime:
                from equivalence.search_contract_runtime_bindings import prepare_search_contract_runtime_bindings

                try:
                    report["searchContractRuntimeBindings"] = prepare_search_contract_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("search-contract-runtime-owner-unavailable",
                                       "The reviewed native search-tool owners could not be verified.") from None
            get_contract_runtime = any(case["operation"] in {
                "get-contract-runtime", "get-contract-helper-runtime",
            } for case in runtime_cases)
            if get_contract_runtime:
                from equivalence.get_contract_runtime_bindings import prepare_get_contract_runtime_bindings

                try:
                    report["getContractRuntimeBindings"] = prepare_get_contract_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("get-contract-runtime-owner-unavailable",
                                       "The reviewed native get-tool owners could not be verified.") from None
            deadline_partial_runtime = any(case["operation"] in {
                "deadline-partial-runtime", "deadline-partial-get-runtime",
            } for case in runtime_cases)
            if deadline_partial_runtime:
                from equivalence.deadline_partial_runtime_bindings import prepare_deadline_partial_runtime_bindings

                try:
                    report["deadlinePartialRuntimeBindings"] = prepare_deadline_partial_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("deadline-partial-runtime-owner-unavailable",
                                       "The reviewed native deadline/corpus owners could not be verified.") from None
            session_contract_runtime = any(case["operation"] in {
                "session-contract-runtime", "session-contract-helper-runtime",
            } for case in runtime_cases)
            if session_contract_runtime:
                from equivalence.session_admission_runtime_bindings import prepare_session_admission_runtime_bindings

                try:
                    report["sessionAdmissionRuntimeBindings"] = prepare_session_admission_runtime_bindings(
                        checkout, Path(runtime_config["runtimeRoot"]),
                    )
                except (OSError, ValueError):
                    raise HarnessError("session-contract-runtime-owner-unavailable",
                                       "The reviewed native session admission/visibility owners could not be verified.") from None
            report["releaseSources"], report["releaseTraces"], report["runtimeDiagnostics"] = [], [], []
            if flush_execution:
                report["fixtureCaptures"] = []
            observed_release = {}
            for case in runtime_cases:
                # The real manager retains global state owners. Each distinct
                # case gets one fresh process; failed cases are never retried.
                try:
                    native = _oracle(node, ROOT / "equivalence/release-oracle.mjs", checkout, [case],
                                     max(timeout_seconds, 60), release_runtime=runtime_config)
                except HarnessError:
                    report["failedReferenceCaseId"] = case["id"]
                    raise
                oracle["results"].extend(native["results"])
                for loaded in native["releaseSources"]:
                    observed_release[(loaded["package"], loaded["path"])] = loaded
                report["releaseTraces"].append({"id": case["id"], **native["releaseTrace"]})
                if flush_execution:
                    report["fixtureCaptures"].extend(
                        {"id": case["id"], **capture} for capture in native.get("fixtureCaptures", [])
                    )
                report["runtimeDiagnostics"].extend(
                    {"side": "native", **diagnostic} for diagnostic in native["runtimeDiagnostics"])
            try:
                if prepare_release_runtime(checkout, release_runtime_root) != runtime_config:
                    raise ValueError("Runtime artifacts changed.")
                if flush_runtime and prepare_flush_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["flushRuntimeBindings"]:
                    raise ValueError("Flush runtime owner/export changed.")
                if flush_execution and prepare_flush_execution_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["flushExecutionBindings"]:
                    raise ValueError("Flush execution owners or fixture metadata changed.")
                if exact_path_runtime and prepare_exact_path_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["exactPathRuntimeBindings"]:
                    raise ValueError("Exact-path keyword owners or compiled export changed.")
                if importance_project_runtime and prepare_importance_project_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["importanceProjectRuntimeBindings"]:
                    raise ValueError("Importance/project source or compiled owners changed.")
                if search_contract_runtime and prepare_search_contract_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["searchContractRuntimeBindings"]:
                    raise ValueError("Search-tool source or compiled owners changed.")
                if get_contract_runtime and prepare_get_contract_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["getContractRuntimeBindings"]:
                    raise ValueError("Get-tool source or compiled owners changed.")
                if deadline_partial_runtime and prepare_deadline_partial_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["deadlinePartialRuntimeBindings"]:
                    raise ValueError("Deadline/corpus source or compiled owners changed.")
                if session_contract_runtime and prepare_session_admission_runtime_bindings(
                    checkout, Path(runtime_config["runtimeRoot"]),
                ) != report["sessionAdmissionRuntimeBindings"]:
                    raise ValueError("Session admission/visibility source or compiled owners changed.")
            except (OSError, ValueError, RuntimeError):
                raise HarnessError("release-runtime-changed",
                                   "Official runtime artifact bytes changed during comparison.") from None
            report["releaseSources"] = [observed_release[key] for key in sorted(observed_release)]
        report["referenceExecution"] = {
            "trackedTypeScriptCaseIds": [case["id"] for case in source_cases],
            "compiledReleaseCaseIds": [case["id"] for case in runtime_cases],
        }
        if dependencies is not None:
            from equivalence.dependencies import validate_dependency_sources

            try:
                if prepare_dependencies(checkout, dependency_root) != dependencies:
                    raise ValueError("Native dependencies changed.")
                validate_dependency_sources(dependencies, oracle.get("dependencySources", []))
                if required_artifact_execution and not oracle.get("dependencySources"):
                    raise ValueError("Native dependency execution evidence is missing.")
                current_bindings = _reference_bindings(checkout, cache=cache_bindings,
                                                       publication=publication_bindings,
                                                       reuse_operations=reuse_operations)
                if current_bindings != bindings:
                    raise ValueError("Binding provenance changed.")
            except (OSError, ValueError, RuntimeError):
                raise HarnessError("oracle-dependency-mismatch",
                                   "Native dependency bytes or export provenance changed during execution.") from None
            # Artifact evidence is separate from the committed TypeScript source
            # list. These packages are not presented as files in the Git tree.
            report["dependencies"] = {key: value for key, value in dependencies.items() if key != "packages"}
            report["dependencies"]["packages"] = [
                {key: value for key, value in package.items() if key != "directory"}
                for package in dependencies["packages"]
            ]
            report["dependencySources"] = oracle["dependencySources"]
            report["bindingProjections"] = bindings
            if publication_bindings:
                from equivalence.index_bindings import attest_index_facades, prepare_index_bindings

                try:
                    report["indexFacadeExecution"] = attest_index_facades(
                        prepare_index_bindings(checkout), oracle["sources"])
                except (OSError, ValueError, RuntimeError):
                    raise HarnessError("index-facade-unverified", "The original native index facades were not executed.") from None
        if _adapter_identity() != adapter_hashes:
            raise HarnessError("adapter-changed", "Differential adapters changed during comparison.")
        # A source mutation during comparison invalidates every observed result.
        after = _validate_reference(checkout, node, target)
        if after != report["reference"]:
            raise HarnessError("reference-changed", "The reference checkout changed during comparison.")
        report["sources"] = oracle.get("sources", [])
        native_rows = {row["id"]: row for row in oracle["results"]}
        python_diagnostics = (Path(resources.enter_context(tempfile.TemporaryDirectory(
            prefix="memory-python-runtime-evidence-"))) if runtime_cases else None)
        for case in cases:
            row = {"id": case["id"], "requirement": case["requirement"], "covers": case["covers"],
                   "operation": case["operation"], "input": case["input"]}
            for field in ("normalizationPolicy", "driverScope", "declaredDeviation"):
                if field in case:
                    row[field] = case[field]
            native = native_rows[case["id"]]
            if not native["ok"]:
                row.update(status="blocked", code="oracle-case-failed")
                # Retain a bounded package identifier for source-graph setup
                # failures, without copying arbitrary exception text (which
                # can contain fixture secrets or host data) into reports.
                error = native.get("error")
                message = error.get("message") if isinstance(error, dict) else None
                if isinstance(message, str):
                    missing_package = re.match(
                        r"Cannot find package '(@?[A-Za-z0-9_.\-/]+)' imported from ", message)
                    if missing_package:
                        row["unavailablePackage"] = missing_package[1]
            else:
                try:
                    python_case = deepcopy(case)
                    if case in runtime_cases:
                        directory = python_diagnostics / hashlib.sha256(case["id"].encode()).hexdigest()
                        python_case["_diagnosticDirectory"] = directory
                        row["referenceMode"] = "authenticated-official-release"
                    python = python_runner(python_case)
                    if case in runtime_cases:
                        evidence = directory / "python-raw.json"
                        info = evidence.lstat()
                        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                                or info.st_size > 16 * 1024 * 1024):
                            raise ValueError("Invalid runtime diagnostic file.")
                        raw = evidence.read_bytes()
                        snapshots = _json(raw.decode("utf-8"))
                        if not isinstance(snapshots, list):
                            raise ValueError("Runtime diagnostics must retain raw snapshot rows.")
                        report["runtimeDiagnostics"].append({
                            "id": case["id"], "side": "python", "sha256": hashlib.sha256(raw).hexdigest(),
                            "rawSnapshots": snapshots,
                        })
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
        if _adapter_identity() != adapter_hashes:
            raise HarnessError("adapter-changed", "Differential adapters changed during comparison.")
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
    finally:
        resources.close()
    report["durationSeconds"] = round(time.monotonic() - started, 6)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report["fullScopePassed"] = report["mode"] == "full" and report["status"] == "passed"
    exit_code = 0 if report["status"] == "passed" else 2 if report["status"] == "blocked" else 1
    return report, exit_code
