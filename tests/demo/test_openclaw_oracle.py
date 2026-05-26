import json
import subprocess
from pathlib import Path

import demo.openclaw_oracle as openclaw_oracle
from demo.openclaw_oracle import OpenClawOracle, OracleError


def test_oracle_metadata_reports_missing_checkout(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=tmp_path / "missing")

    metadata = oracle.metadata()

    assert metadata["available"] is False
    assert metadata["repoPath"] == str(tmp_path / "missing")
    assert metadata["commit"] is None
    assert metadata["reason"] == "checkout missing"


def test_run_returns_structured_error_when_checkout_missing(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=tmp_path / "missing")

    result = oracle.run({"operation": "deepPolicy"})

    assert result["ok"] is False
    assert result["error"]["code"] == "oracle-unavailable"
    assert "checkout missing" in result["error"]["message"]


def test_oracle_error_is_safe_string():
    err = OracleError("boom")

    assert str(err) == "boom"


def test_run_does_not_allow_payload_to_override_repo_path(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "oracle"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    runner_path = tmp_path / "openclaw_oracle_runner.ts"
    runner_path.write_text("", encoding="utf-8")
    captured_inputs = []

    def fake_run(command, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
        captured_inputs.append(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(openclaw_oracle, "RUNNER_PATH", runner_path)
    monkeypatch.setattr(openclaw_oracle.subprocess, "run", fake_run)

    oracle = OpenClawOracle(repo_path=repo_path)

    result = oracle.run({"operation": "deepPolicy", "repoPath": "/tmp/spoofed"})

    assert result["ok"] is True
    assert json.loads(captured_inputs[0])["repoPath"] == str(repo_path)


def test_run_returns_runner_json(monkeypatch, tmp_path: Path):
    repo = tmp_path / "openclaw"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        assert cmd[:3] == ["pnpm", "exec", "tsx"]
        assert json.loads(kwargs["input"])["operation"] == "deepPolicy"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"ok": True, "operation": "deepPolicy", "result": {"minScore": 0.8}}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = OpenClawOracle(repo_path=repo)

    result = oracle.run({"operation": "deepPolicy"})

    assert result["ok"] is True
    assert result["result"]["minScore"] == 0.8
    assert result["metadata"]["commit"] == "abc123"


def test_run_preserves_structured_runner_error(monkeypatch, tmp_path: Path):
    repo = tmp_path / "openclaw"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        assert cmd[:3] == ["pnpm", "exec", "tsx"]
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout=json.dumps(
                {"ok": False, "error": {"code": "runner-error", "message": "unsupported operation"}}
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = OpenClawOracle(repo_path=repo)

    result = oracle.run({"operation": "unknown"})

    assert result["ok"] is False
    assert result["error"]["code"] == "runner-error"
    assert result["error"]["message"] == "unsupported operation"
    assert result["metadata"]["commit"] == "abc123"


def test_runner_forwards_policy_fields_to_rank_and_apply():
    source = openclaw_oracle.RUNNER_PATH.read_text(encoding="utf-8")

    for field in [
        "limit",
        "minScore",
        "minRecallCount",
        "minUniqueQueries",
        "maxAgeDays",
        "recencyHalfLifeDays",
    ]:
        assert f"{field}: policy.{field}" in source

    assert "limit: 10" not in source
    assert "minScore: 0.75" not in source
    assert "minUniqueQueries: 2" not in source


def test_runner_resolves_memory_core_plugin_config():
    source = openclaw_oracle.RUNNER_PATH.read_text(encoding="utf-8")

    assert 'entries["memory-core"]' in source
    assert "const pluginConfig =" in source
    assert "pluginConfig," in source
    assert "cfg: payload.config ?? {}" in source
