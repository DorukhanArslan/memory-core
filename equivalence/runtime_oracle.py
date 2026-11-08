"""Bounded execution evidence for the authenticated official release oracle.

Artifact archive verification remains the caller's responsibility before and
after the complete batch. This context owns process/thread tracing and retains
raw case diagnostics without presenting compiled files as TypeScript sources.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

from equivalence.release_runtime import ReleaseRuntimeError, validate_release_sources


ROOT = Path(__file__).resolve().parents[1]
MAX_TRACE_FILES = 512
MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_SINGLE_TRACE_BYTES = 8 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 16 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TRACE = re.compile(r"([1-9][0-9]*)-([0-9]+)\.jsonl\Z")
_CONTEXT_ENV = "MEMORY_EQ_RELEASE_CONTEXT"
_FIXTURE_CAPTURE = re.compile(
    r"tmp/plugin-captures/[0-9a-f-]{36}/captures/openclaw-plugin-build-[A-Za-z0-9]{6}"
    r"/package-0/node_modules/equivalence/flush-execution\.mjs\Z"
)
_OPERATIONS = {
    "importance-project-runtime": (
        "importance-project-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "exact-path-runtime": (
        "exact-path-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", False,
    ),
    "index-lifecycle-runtime": ("index-lifecycle.mjs", None, True),
    "flush-trigger-runtime": (
        "flush-runtime.mjs", "dist/agent-runner-memory-Cc4lCZcs.mjs", False,
    ),
    "flush-execution-runtime": (
        "flush-execution.mjs", "dist/agent-runner-memory-Cc4lCZcs.mjs", True,
    ),
    "search-contract-runtime": (
        "search-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", True,
    ),
    "search-contract-helper-runtime": (
        "search-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
}


class RuntimeOracleError(ValueError):
    """The release process did not provide bounded authenticated execution evidence."""


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes | str):
    def invalid(_value):
        raise ValueError("non-finite JSON")
    return json.loads(raw, parse_constant=invalid)


def _regular(path: Path, limit: int) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
            or path.is_symlink()):
        raise RuntimeOracleError("Runtime evidence is not an independent bounded regular file.")
    return path.read_bytes()


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeOracleError("Runtime evidence has an invalid artifact path.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise RuntimeOracleError("Runtime evidence has an invalid artifact path.")
    return value


class ReleaseOracleExecution:
    """One fresh provider-none process with a trusted preload inherited by workers."""

    def __init__(self, config: dict, adapter_hashes: dict[str, str], *, fixture_captures: bool = False):
        self.config = deepcopy(config)
        self.adapter_hashes = dict(adapter_hashes)
        self.fixture_captures = fixture_captures
        self.env: dict[str, str] = {}
        self._temporary = None
        self._entered = False

    def __enter__(self):
        try:
            runtime_root = Path(self.config["runtimeRoot"])
            if not runtime_root.is_absolute() or not runtime_root.is_dir():
                raise RuntimeOracleError("An authenticated absolute release runtime is required.")
            package_map = {}
            for package in self.config["packages"]:
                location = _relative(package["location"])
                directory = Path(package["directory"])
                if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
                    raise RuntimeOracleError("A release package root is invalid.")
                for entry in package["files"]:
                    relative = _relative(entry["path"])
                    digest = entry["sha256"]
                    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                        raise RuntimeOracleError("A release package digest is invalid.")
                    key = (location, relative)
                    if key in package_map:
                        raise RuntimeOracleError("Release package evidence must be unique.")
                    package_map[key] = digest
            self._packages = package_map
            self._locals = {}
            for name, digest in self.adapter_hashes.items():
                if Path(name).name != name:
                    raise RuntimeOracleError("Oracle adapter identities must use plain filenames.")
                if not name.endswith(".mjs"):
                    continue
                path = ROOT / "equivalence" / name
                if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                    raise RuntimeOracleError("An oracle adapter digest is invalid.")
                if _digest(_regular(path, MAX_DIAGNOSTIC_BYTES)) != digest:
                    raise RuntimeOracleError("An oracle adapter changed before release execution.")
                self._locals[str(path.resolve())] = digest
            required = {"release-preload.mjs", "release-oracle.mjs", "index-lifecycle.mjs"}
            if not required <= {Path(path).name for path in self._locals}:
                raise RuntimeOracleError("Release execution requires all reviewed oracle adapters.")
            self._temporary = tempfile.TemporaryDirectory(prefix="memory-release-oracle-")
            self.root = Path(self._temporary.name)
            self.trace_directory = self.root / "traces"
            self.evidence_directory = self.root / "evidence"
            self.trace_directory.mkdir()
            self.evidence_directory.mkdir()
            self.context_path = self.root / "context.json"
            self.state_directory = self.root / "state"
            self.config_path = self.root / "openclaw.json"
            self.config_path.write_text(json.dumps({"session": {"maintenance": {"mode": "warn"}}, "logging": {
                "level": "silent", "consoleLevel": "silent", "file": str(self.root / "runtime.log"),
            }}), encoding="utf-8")
            self._context = {
                "schemaVersion": 1, "kind": "release-oracle-execution",
                "runtime": self.config,
                "allowedLocal": [{"path": path, "sha256": digest}
                                 for path, digest in sorted(self._locals.items())],
                "traceDirectory": str(self.trace_directory),
                "evidenceDirectory": str(self.evidence_directory),
                "stateDirectory": str(self.state_directory), "configPath": str(self.config_path),
                "providerMode": "none", "fetchPolicy": "deny",
                "fixtureSourceCaptures": [],
            }
            if self.fixture_captures:
                fixture = str((ROOT / "equivalence/flush-execution.mjs").resolve())
                if fixture not in self._locals:
                    raise RuntimeOracleError("Fixture captures require the reviewed flush execution adapter.")
                self._context["fixtureSourceCaptures"] = [{
                    "sourcePath": fixture, "sha256": self._locals[fixture],
                    "basename": "flush-execution.mjs",
                }]
            raw = (json.dumps(self._context, separators=(",", ":"), allow_nan=False) + "\n").encode()
            self.context_path.write_bytes(raw)
            self.context_path.chmod(0o600)
            self._context_digest = _digest(raw)
            preload = ROOT / "equivalence/release-preload.mjs"
            self._preload_digest = self._locals[str(preload.resolve())]
            self.env = {
                "NODE_OPTIONS": "--import=" + preload.as_uri(),
                _CONTEXT_ENV: str(self.context_path),
                "OPENCLAW_STATE_DIR": str(self.state_directory),
                "OPENCLAW_CONFIG_PATH": str(self.config_path),
            }
            self._entered = True
            return self
        except (OSError, KeyError, TypeError, ValueError) as error:
            if self._temporary is not None:
                self._temporary.cleanup()
            if isinstance(error, RuntimeOracleError):
                raise
            raise RuntimeOracleError("The release oracle execution context could not be prepared.") from None

    def __exit__(self, *_exception):
        self._entered = False
        if self._temporary is not None:
            self._temporary.cleanup()

    def collect(self, result: dict, cases: list[dict]) -> dict:
        """Validate all observed threads and retain case raw state in the report."""
        if not self._entered:
            raise RuntimeOracleError("Release execution evidence requires an active owned context.")
        try:
            return self._collect(result, cases)
        except (OSError, KeyError, TypeError, ValueError, ReleaseRuntimeError) as error:
            if isinstance(error, RuntimeOracleError):
                raise
            raise RuntimeOracleError("The release oracle returned invalid execution evidence.") from None

    def _collect(self, result: dict, cases: list[dict]) -> dict:
        if (not isinstance(result, dict) or result.get("kind") != "official-release-runtime-comparison"
                or result.get("sources") != [] or len(cases) != 1
                or not isinstance(result.get("results"), list) or len(result["results"]) != 1):
            raise RuntimeOracleError("Release oracle comparisons require one fresh isolated case.")
        case = cases[0]
        row = result["results"][0]
        operation = case.get("operation")
        search_profile_kinds = {"search-contract-runtime": {"tool"},
                                "search-contract-helper-runtime": {"definition", "prepare-arguments"}}
        if (operation in search_profile_kinds
                and case.get("input", {}).get("kind") not in search_profile_kinds[operation]):
            raise RuntimeOracleError("Search fixtures must use their narrowly declared helper or whole-tool profile.")
        if (not isinstance(row, dict) or operation not in _OPERATIONS
                or row.get("id") != case.get("id") or type(row.get("ok")) is not bool
                or set(row) != ({"id", "ok", "result"} if row["ok"] else {"id", "ok", "error"})):
            raise RuntimeOracleError("The release oracle returned an unexpected case identity.")
        if row["ok"] and (not isinstance(row["result"], dict) or row["result"].get("provider") != "none"):
            raise RuntimeOracleError("Release memory fixtures require provider none.")
        if _digest(_regular(self.context_path, MAX_TRACE_BYTES)) != self._context_digest:
            raise RuntimeOracleError("The owned release execution configuration changed.")
        for path, digest in self._locals.items():
            if _digest(_regular(Path(path), MAX_DIAGNOSTIC_BYTES)) != digest:
                raise RuntimeOracleError("An oracle adapter changed during release execution.")
        traces = sorted(self.trace_directory.iterdir())
        if not traces or len(traces) > MAX_TRACE_FILES:
            raise RuntimeOracleError("The release oracle returned missing or excessive thread traces.")
        total = 0
        loaded, bootstrap, worker_imports, local_imports, captures = {}, [], [], set(), {}
        for trace in traces:
            filename = _TRACE.fullmatch(trace.name)
            if filename is None:
                raise RuntimeOracleError("A release thread trace has an invalid identity.")
            raw = _regular(trace, MAX_SINGLE_TRACE_BYTES)
            total += len(raw)
            if total > MAX_TRACE_BYTES or not raw.endswith(b"\n"):
                raise RuntimeOracleError("Release thread traces are excessive or incomplete.")
            events = [_json(line) for line in raw.splitlines()]
            if (not events or any(not isinstance(event, dict) for event in events)
                    or events[0].get("event") != "bootstrap"):
                raise RuntimeOracleError("A runtime thread bypassed its trusted preload.")
            pid, thread = int(filename[1]), int(filename[2])
            first = events[0]
            if (first.get("pid") != pid or first.get("threadId") != thread
                    or first.get("isMainThread") is not (thread == 0)
                    or first.get("contextSha256") != self._context_digest
                    or first.get("preloadSha256") != self._preload_digest
                    or first.get("fetchDenied") is not True or first.get("providerMode") != "none"):
                raise RuntimeOracleError("Runtime thread bootstrap protection was not attested.")
            bootstrap.append({"pid": pid, "threadId": thread, "isMainThread": thread == 0})
            for event in events[1:]:
                if event.get("pid") != pid or event.get("threadId") != thread:
                    raise RuntimeOracleError("A runtime trace forged another thread identity.")
                if event.get("event") in {"rejected", "network-denied"}:
                    raise RuntimeOracleError("The runtime attempted an unverified import or network request.")
                if event.get("event") not in {"load", "resolve-native"}:
                    raise RuntimeOracleError("The runtime returned an unsupported trace event.")
                kind, path, digest = event.get("kind"), event.get("path"), event.get("sha256")
                if kind == "oracle":
                    if self._locals.get(path) != digest:
                        raise RuntimeOracleError("An oracle import did not match its reviewed adapter.")
                    if event["event"] == "load" and thread == 0:
                        local_imports.add(path)
                elif kind == "fixture-capture":
                    source = event.get("sourcePath")
                    capture = event.get("capturePath")
                    proof = event.get("proofPath")
                    if (not self.fixture_captures or case.get("operation") != "flush-execution-runtime"
                            or source != str((ROOT / "equivalence/flush-execution.mjs").resolve())
                            or path != source or self._locals.get(source) != digest
                            or not isinstance(capture, str) or not _FIXTURE_CAPTURE.fullmatch(capture)):
                        raise RuntimeOracleError("A fixture source capture has no reviewed owner.")
                    expected_proof = "fixture-source-captures/" + _digest(
                        (capture + "\0" + digest).encode()
                    ) + ".mjs"
                    if proof != expected_proof:
                        raise RuntimeOracleError("A fixture source capture has invalid retained proof.")
                    proof_directory = self.evidence_directory / "fixture-source-captures"
                    if (proof_directory.is_symlink() or not proof_directory.is_dir()
                            or proof_directory.resolve() != proof_directory):
                        raise RuntimeOracleError("A fixture source capture proof escaped its owned directory.")
                    proof_bytes = _regular(self.evidence_directory / proof, MAX_DIAGNOSTIC_BYTES)
                    if _digest(proof_bytes) != digest:
                        raise RuntimeOracleError("A retained fixture source capture changed its bytes.")
                    if event["event"] == "load":
                        captures[capture] = {
                            "sourcePath": source, "capturePath": capture, "sha256": digest,
                            "proofPath": proof, "proofSha256": _digest(proof_bytes),
                            "bytes": len(proof_bytes),
                        }
                elif kind == "release":
                    key = (event.get("package"), path)
                    if self._packages.get(key) != digest:
                        raise RuntimeOracleError("A runtime import is not an authenticated release file.")
                    if event["event"] == "load":
                        loaded[key] = {"package": key[0], "path": key[1], "sha256": digest}
                        if thread > 0:
                            worker_imports.append({"package": key[0], "path": key[1],
                                                   "threadId": thread, "pid": pid})
                else:
                    raise RuntimeOracleError("A runtime import has an unknown authority.")
        if not any(item["isMainThread"] for item in bootstrap):
            raise RuntimeOracleError("The release main process did not execute its trusted preload.")
        adapter, required_owner, requires_worker = _OPERATIONS[operation]
        if not {str((ROOT / "equivalence" / name).resolve())
                for name in ("release-oracle.mjs", adapter)} <= local_imports:
            raise RuntimeOracleError("The reviewed release runner and case adapter did not execute.")
        if required_owner is not None and ("node_modules/openclaw", required_owner) not in loaded:
            message = ("The actual native runtime owner did not execute."
                       if operation in {"exact-path-runtime", "importance-project-runtime"}
                       else "The actual native flush runtime owner did not execute.")
            raise RuntimeOracleError(message)
        if operation == "importance-project-runtime":
            from equivalence.importance_project_runtime_bindings import COMPILED_HASHES

            if any(("node_modules/openclaw", owner) not in loaded for owner in COMPILED_HASHES):
                raise RuntimeOracleError("The actual native preparation, metadata and ranking owners did not execute.")
        if operation in {"search-contract-runtime", "search-contract-helper-runtime"}:
            from equivalence.search_contract_runtime_bindings import REQUIRED_LOADED_ARTIFACTS_BY_PROFILE

            if any(("node_modules/openclaw", owner) not in loaded
                   for owner in REQUIRED_LOADED_ARTIFACTS_BY_PROFILE[operation]):
                raise RuntimeOracleError("The actual declared native search-tool owners did not execute.")
        if case.get("operation") == "flush-execution-runtime" and not captures:
            raise RuntimeOracleError("The native provider loader did not execute a reviewed fixture source capture.")
        if operation == "flush-execution-runtime" and (
            "node_modules/openclaw", "dist/extensions/memory-core/manager-runtime.js"
        ) not in loaded:
            raise RuntimeOracleError("The actual native memory manager did not execute during flush comparison.")
        if requires_worker and not any(
            item["path"].endswith("/memory-index.worker.js") for item in worker_imports
        ):
            raise RuntimeOracleError("The actual native memory worker did not inherit runtime protection.")
        release_sources = [loaded[key] for key in sorted(loaded)]
        if required_owner is None:
            validate_release_sources(self.config, release_sources)
        else:
            validate_release_sources(self.config, release_sources, required_entry=required_owner)
        case_hash = _digest(case["id"].encode("utf-8"))
        evidence = self.evidence_directory / case_hash / "native-raw.json"
        raw = _regular(evidence, MAX_DIAGNOSTIC_BYTES)
        diagnostic = _json(raw)
        if not isinstance(diagnostic, list):
            raise RuntimeOracleError("Native lifecycle diagnostics must retain raw snapshot rows.")
        if operation == "flush-execution-runtime" and not any(
            isinstance(row, dict) and isinstance(row.get("modelCalls"), list) and row["modelCalls"]
            for row in diagnostic
        ):
            raise RuntimeOracleError("The scripted provider did not observe an actual native model callback.")
        answer = deepcopy(result)
        answer["releaseSources"] = release_sources
        if captures:
            answer["fixtureCaptures"] = [captures[key] for key in sorted(captures)]
        answer["releaseTrace"] = {"kind": "authenticated-process-thread-trace",
                                  "threads": bootstrap, "protectedWorkerThreads": sum(
                                      not item["isMainThread"] for item in bootstrap),
                                  "loadedReleaseFiles": len(release_sources),
                                  "networkFetchDenied": True, "provider": "none",
                                  "nativeBinaryPolicy": "all artifact bytes authenticated before and after execution"}
        answer["runtimeDiagnostics"] = [{"id": case["id"], "sha256": _digest(raw),
                                          "rawSnapshots": diagnostic}]
        return answer
