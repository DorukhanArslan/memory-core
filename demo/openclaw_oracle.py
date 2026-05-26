from __future__ import annotations

import json
import os
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
            completed = subprocess.run(
                ["pnpm", "exec", "tsx", str(RUNNER_PATH)],
                input=body,
                text=True,
                capture_output=True,
                cwd=self.repo_path,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return self._subprocess_error("pnpm-not-found", "pnpm executable not found", metadata)
        except subprocess.TimeoutExpired:
            return self._subprocess_error("oracle-timeout", "oracle runner timed out", metadata)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "oracle runner failed").strip()
            return self._subprocess_error("oracle-runner-failed", message, metadata)
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return self._subprocess_error(
                "oracle-invalid-json",
                f"oracle returned invalid JSON: {exc.msg}",
                metadata,
            )
        if isinstance(result, dict):
            result.setdefault("metadata", metadata)
            return result
        return self._subprocess_error("oracle-invalid-payload", "oracle result was not an object", metadata)

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
