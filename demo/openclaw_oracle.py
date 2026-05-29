from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ORACLE_REPO = Path(os.getenv("OPENCLAW_ORACLE_REPO", "/tmp/openclaw-upstream"))
RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "openclaw_oracle_runner.ts"


class OracleError(RuntimeError):
    pass


class OpenClawOracle:
    def __init__(self, repo_path: Path | None = None, timeout_seconds: float = 20.0):
        self.repo_path = repo_path or DEFAULT_ORACLE_REPO
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
            completed = self._run_runner(self._preferred_runner_command(), body)
        except FileNotFoundError:
            try:
                completed = self._run_runner(self._npm_pnpm_runner_command(), body)
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
        return self._subprocess_error("oracle-invalid-payload", "oracle result was not an object", metadata)

    def _run_runner(self, command: list[str], body: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=body,
            text=True,
            capture_output=True,
            cwd=self.repo_path,
            timeout=self.timeout_seconds,
            check=False,
        )

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
