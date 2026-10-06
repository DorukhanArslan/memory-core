"""Client for the OpenClaw TypeScript oracle runner (test and Lab infrastructure, demo-only).

The oracle checkout is ``OPENCLAW_ORACLE_REPO`` (default :data:`PIN_CHECKOUT_PATH`, a checkout
of the parity pin ``memory_core.parity.upstream.LATEST_INSPECTED_COMMIT`` with its pnpm deps). The
runner starts through the checkout's ``tsx`` (``pnpm exec tsx`` when pnpm is installed), which
runs the first ``node`` on ``PATH``; ``OPENCLAW_ORACLE_NODE`` names a node binary to use instead
(its directory is put first on ``PATH`` for the runner and every process it starts). tsx, pnpm
and vitest start through ``#!/usr/bin/env node``, so the configured value is resolved to an
absolute path (a bare name is looked up on ``PATH``) and must be a file or symlink named
``node``; an alias such as ``node24`` would be probed while the next ``node`` on ``PATH`` runs,
so it is refused. The resolved Node must satisfy the checkout's ``package.json``
``engines.node`` range: v2026.9.6 asks for ``>=24.16.0 <25 || >=26.1.0`` and refuses Node 25
for its SQLite state, so a run with an unsupported Node fails fast with
``oracle-node-unsupported`` instead of failing inside TS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ORACLE_REPO_ENV = "OPENCLAW_ORACLE_REPO"
ORACLE_NODE_ENV = "OPENCLAW_ORACLE_NODE"
# Where the setup in README / docs/lab.md clones the pin checkout (tag v2026.9.6).
PIN_CHECKOUT_PATH = Path("/tmp/openclaw-head")
RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "openclaw_oracle_runner.ts"


def resolve_oracle_repo() -> Path:
    """``OPENCLAW_ORACLE_REPO`` if set, else :data:`PIN_CHECKOUT_PATH`."""
    return Path(os.getenv(ORACLE_REPO_ENV) or PIN_CHECKOUT_PATH)


# Resolved at import like before; prefer resolve_oracle_repo() where the env may change.
DEFAULT_ORACLE_REPO = resolve_oracle_repo()


class OracleError(RuntimeError):
    pass


class OracleNodeError(OracleError):
    """The Node that would run the oracle is missing or outside the checkout's engines range."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --- Node engines check ---------------------------------------------------------------------

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
_PARTIAL_RE = re.compile(r"^v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?$")
_COMPARATOR_RE = re.compile(r"^(<=|>=|<|>|=|\^|~)?\s*(.+)$")


def _parse_node_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def _partial(text: str) -> list[int | None] | None:
    match = _PARTIAL_RE.match(text.strip())
    if not match:
        return None
    return [None if part in (None, "x", "X", "*") else int(part) for part in match.groups()]


def _comparator_bounds(token: str) -> list[tuple[str, tuple[int, int, int]]] | None:
    """One node-semver comparator as (op, version) lower/upper bounds; None if unparseable."""
    match = _COMPARATOR_RE.match(token)
    if not match:
        return None
    op, rest = match.group(1) or "", match.group(2)
    parts = _partial(rest)
    if parts is None:
        return None
    major, minor, patch = parts
    if major is None:
        return [] if op in ("", "=", ">=", "<=", "^", "~") else None
    low = (major, minor or 0, patch or 0)

    def bump(level: int) -> tuple[int, int, int]:
        if level == 0:
            return (major + 1, 0, 0)
        return (major, (minor or 0) + 1, 0)

    precision = 0 if minor is None else 1 if patch is None else 2
    if op in ("", "="):
        if precision == 2:
            return [(">=", low), ("<=", low)]
        return [(">=", low), ("<", bump(precision))]
    if op == ">=":
        return [(">=", low)]
    if op == "<":
        return [("<", low)]
    if op == ">":
        return [(">", low)] if precision == 2 else [(">=", bump(precision))]
    if op == "<=":
        return [("<=", low)] if precision == 2 else [("<", bump(precision))]
    if op == "^":
        if major > 0 or minor is None:
            return [(">=", low), ("<", (major + 1, 0, 0))]
        if minor > 0 or patch is None:
            return [(">=", low), ("<", (0, minor + 1, 0))]
        return [(">=", low), ("<", (0, 0, patch + 1))]
    if op == "~":
        return [(">=", low), ("<", bump(0 if minor is None else 1))]
    return None


def node_version_satisfies(version: str, range_text: str) -> bool | None:
    """Whether ``version`` satisfies a node-semver range (``||``, comparators, ^, ~, x, a - b).

    Returns ``None`` when the range uses syntax this matcher does not know, so the caller can
    report it instead of guessing.
    """
    parsed = _parse_node_version(version)
    if parsed is None:
        return None
    for alternative in range_text.split("||"):
        text = alternative.strip()
        hyphen = re.match(r"^(\S+)\s+-\s+(\S+)$", text)
        if hyphen:
            upper = _comparator_bounds(f"<={hyphen.group(2)}")
            lower = _comparator_bounds(f">={hyphen.group(1)}")
            if upper is None or lower is None:
                return None
            bounds = [*lower, *upper]
        else:
            tokens = re.findall(r"(?:<=|>=|<|>|=|\^|~)?\s*[^\s<>=^~]+", text) if text else []
            bounds = []
            for token in tokens:
                parsed_bounds = _comparator_bounds(token.strip())
                if parsed_bounds is None:
                    return None
                bounds.extend(parsed_bounds)
        checks = {
            ">=": lambda bound: parsed >= bound,
            ">": lambda bound: parsed > bound,
            "<=": lambda bound: parsed <= bound,
            "<": lambda bound: parsed < bound,
        }
        if all(checks[op](bound) for op, bound in bounds):
            return True
    return False


def checkout_node_engines(repo_path: Path) -> str | None:
    """``engines.node`` of the checkout's package.json, or None."""
    try:
        raw = json.loads((repo_path / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    engines = raw.get("engines") if isinstance(raw, dict) else None
    value = engines.get("node") if isinstance(engines, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


@lru_cache(maxsize=16)
def _probe_node_version(node: str) -> str | None:
    try:
        completed = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = completed.stdout.strip()
    return version if completed.returncode == 0 and version else None


# The name tsx, pnpm and vitest look up through their `#!/usr/bin/env node` shebangs.
_NODE_BASENAMES = frozenset({"node", "node.exe"})


@dataclass(frozen=True)
class OracleNode:
    """The node binary the oracle runs with and how it compares with the checkout's engines.

    ``named_node`` is False when ``OPENCLAW_ORACLE_NODE`` resolves to a file not named
    ``node``: the scripts would then run the next ``node`` on ``PATH``, not this binary.
    """

    path: str | None
    version: str | None
    engines: str | None
    satisfies: bool | None
    from_env: bool
    named_node: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "version": self.version,
            "engines": self.engines,
            "satisfies": self.satisfies,
            "env": ORACLE_NODE_ENV if self.from_env else None,
            "namedNode": self.named_node,
        }


def _resolve_configured_node(configured: str) -> str | None:
    """Absolute path of ``OPENCLAW_ORACLE_NODE``; a bare name is looked up on ``PATH``."""
    found = shutil.which(configured)
    return os.path.abspath(found) if found else None


def resolve_oracle_node(repo_path: Path, *, probe: bool = True) -> OracleNode:
    """Resolve ``OPENCLAW_ORACLE_NODE`` (else ``node`` on PATH) and check the engines range."""
    configured = os.getenv(ORACLE_NODE_ENV, "").strip()
    if configured:
        resolved = _resolve_configured_node(configured)
        node = resolved or configured
        named_node = resolved is None or os.path.basename(resolved) in _NODE_BASENAMES
    else:
        node = shutil.which("node")
        named_node = True
    engines = checkout_node_engines(repo_path)
    if not node or not probe:
        return OracleNode(node, None, engines, None, bool(configured), named_node)
    version = _probe_node_version(node)
    satisfies = (
        node_version_satisfies(version, engines) if version is not None and engines else None
    )
    return OracleNode(node, version, engines, satisfies, bool(configured), named_node)


def oracle_subprocess_env(repo_path: Path) -> dict[str, str] | None:
    """Environment for oracle subprocesses, or None to inherit.

    Raises :class:`OracleNodeError` when ``OPENCLAW_ORACLE_NODE`` does not run, when it is not
    a binary named ``node`` (the one the scripts' ``#!/usr/bin/env node`` would find), or when
    the resolved Node is outside the checkout's ``engines.node`` range. Without an engines
    range and without ``OPENCLAW_ORACLE_NODE`` nothing is probed.
    """
    configured = os.getenv(ORACLE_NODE_ENV, "").strip()
    engines = checkout_node_engines(repo_path)
    if not configured and not engines:
        return None
    node = resolve_oracle_node(repo_path)
    if configured and node.version is None:
        raise OracleNodeError(
            "oracle-node-missing",
            f"{ORACLE_NODE_ENV}={configured} is not a runnable node binary",
        )
    if not node.named_node:
        raise OracleNodeError(
            "oracle-node-unsupported",
            f"{ORACLE_NODE_ENV}={configured} resolves to {node.path}, which is not named "
            "'node': tsx, pnpm and vitest start through '#!/usr/bin/env node', so the first "
            f"'node' on PATH would run instead of it; point {ORACLE_NODE_ENV} at a binary or "
            "symlink named 'node' (docs/lab.md › Oracle checkout)",
        )
    if node.satisfies is False:
        source = (
            f"{ORACLE_NODE_ENV}={node.path}" if node.from_env else f"node on PATH ({node.path})"
        )
        raise OracleNodeError(
            "oracle-node-unsupported",
            f"{source} is {node.version}, outside the oracle checkout's engines range "
            f"{engines!r} ({repo_path / 'package.json'}); set {ORACLE_NODE_ENV} to a node "
            "binary in that range (docs/lab.md › Oracle checkout)",
        )
    if not configured:
        return None
    node_path = node.path or configured  # a probed version implies a resolved path
    path = f"{os.path.dirname(node_path)}{os.pathsep}{os.environ.get('PATH', '')}"
    runs = shutil.which("node", path=path)
    if runs is None or os.path.abspath(runs) != node_path:
        raise OracleNodeError(
            "oracle-node-unsupported",
            f"{ORACLE_NODE_ENV}={configured} resolves to {node_path}, but 'node' on the oracle "
            f"PATH is {runs}; point {ORACLE_NODE_ENV} at an executable named 'node'",
        )
    return {**os.environ, "PATH": path}


def _kill_orphaned_runners() -> None:
    """End runner processes a timeout orphaned.

    ``subprocess.run`` kills only the direct child (pnpm) on a timeout; the tsx and node below it
    survive, reparented to init, and keep upstream's cross-process state lock, which stalls every
    later call. A runner whose parent is init belongs to no live call, so a concurrent call is
    never touched.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return
    needle = str(RUNNER_PATH)
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[1] != "1":
                continue
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if needle in cmdline:
                os.kill(int(entry.name), signal.SIGKILL)
        except (OSError, IndexError, ValueError):
            continue


class OpenClawOracle:
    def __init__(self, repo_path: Path | None = None, timeout_seconds: float = 60.0):
        self.repo_path = repo_path or resolve_oracle_repo()
        self.timeout_seconds = timeout_seconds

    def metadata(self) -> dict[str, Any]:
        if not self.repo_path.exists():
            return self._unavailable("checkout missing")
        if not (self.repo_path / ".git").exists():
            return self._unavailable("not a git checkout")
        commit = self._git_commit()
        package_manager = "pnpm" if (self.repo_path / "pnpm-lock.yaml").exists() else "unknown"
        return {
            "available": True,
            "repoPath": str(self.repo_path),
            "commit": commit,
            "packageManager": package_manager,
            "runnerPath": str(RUNNER_PATH),
            "reason": None,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = self.metadata()
        if not metadata["available"]:
            return {
                "ok": False,
                "error": {
                    "code": "oracle-unavailable",
                    "message": str(metadata["reason"]),
                },
                "metadata": metadata,
            }
        if not RUNNER_PATH.exists():
            return {
                "ok": False,
                "error": {
                    "code": "oracle-runner-missing",
                    "message": f"runner missing: {RUNNER_PATH}",
                },
                "metadata": metadata,
            }
        return self._run_subprocess(payload, metadata)

    def _run_subprocess(self, payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({**payload, "repoPath": str(self.repo_path)})
        try:
            env = oracle_subprocess_env(self.repo_path)
        except OracleNodeError as exc:
            return self._subprocess_error(exc.code, str(exc), metadata)
        try:
            try:
                completed = self._run_runner(self._preferred_runner_command(), body, env)
            except subprocess.TimeoutExpired:
                # Back-to-back runner processes occasionally stall on upstream's cross-process
                # state lock (about one call in ten in a long suite, never when run alone), so a
                # timed-out call gets one fresh attempt after its process tree is cleared.
                completed = self._run_runner(self._preferred_runner_command(), body, env)
        except FileNotFoundError:
            try:
                completed = self._run_runner(self._npm_pnpm_runner_command(), body, env)
            except FileNotFoundError:
                return self._subprocess_error(
                    "pnpm-not-found",
                    "pnpm executable not found",
                    metadata,
                )
            except subprocess.TimeoutExpired:
                return self._subprocess_error("oracle-timeout", "oracle runner timed out", metadata)
        except subprocess.TimeoutExpired:
            return self._subprocess_error("oracle-timeout", "oracle runner timed out", metadata)
        if completed.returncode != 0:
            structured_error = self._structured_result(completed.stdout, metadata)
            if structured_error is not None and structured_error.get("ok") is False:
                return structured_error
            message = (completed.stderr or completed.stdout or "oracle runner failed").strip()
            return self._subprocess_error("oracle-runner-failed", message, metadata)
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            result = self._structured_result(completed.stdout, metadata)
            if result is None:
                return self._subprocess_error(
                    "oracle-invalid-json",
                    f"oracle returned invalid JSON: {exc.msg}",
                    metadata,
                )
        if isinstance(result, dict):
            result.setdefault("metadata", metadata)
            return result
        return self._subprocess_error(
            "oracle-invalid-payload", "oracle result was not an object", metadata
        )

    def _run_runner(
        self, command: list[str], body: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                input=body,
                text=True,
                capture_output=True,
                cwd=self.repo_path,
                timeout=self.timeout_seconds,
                check=False,
                **({"env": env} if env is not None else {}),
            )
        except subprocess.TimeoutExpired:
            _kill_orphaned_runners()
            raise

    def _preferred_runner_command(self) -> list[str]:
        if shutil.which("pnpm"):
            return ["pnpm", "exec", "tsx", str(RUNNER_PATH)]
        local_tsx = self.repo_path / "node_modules" / ".bin" / "tsx"
        if local_tsx.exists():
            return [str(local_tsx), str(RUNNER_PATH)]
        return ["pnpm", "exec", "tsx", str(RUNNER_PATH)]

    def _npm_pnpm_runner_command(self) -> list[str]:
        return [
            "npm",
            "exec",
            "--yes",
            self._pnpm_package_spec(),
            "--",
            "exec",
            "tsx",
            str(RUNNER_PATH),
        ]

    def _pnpm_package_spec(self) -> str:
        package_json = self.repo_path / "package.json"
        try:
            raw = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "pnpm@latest"
        package_manager = raw.get("packageManager") if isinstance(raw, dict) else None
        if not isinstance(package_manager, str):
            return "pnpm@latest"
        package_manager = package_manager.strip()
        return package_manager if package_manager.startswith("pnpm@") else "pnpm@latest"

    def _git_commit(self) -> str | None:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            cwd=self.repo_path,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "repoPath": str(self.repo_path),
            "commit": None,
            "packageManager": None,
            "runnerPath": str(RUNNER_PATH),
            "reason": reason,
        }

    @staticmethod
    def _subprocess_error(code: str, message: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message}, "metadata": metadata}

    @staticmethod
    def _structured_result(stdout: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            result = None
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            if result is None:
                return None
        if not isinstance(result, dict):
            return None
        result.setdefault("metadata", metadata)
        return result
