import json
import os
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


def test_run_falls_back_to_npm_exec_pnpm_when_pnpm_binary_is_missing(monkeypatch, tmp_path: Path):
    repo = tmp_path / "openclaw"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
    (repo / "package.json").write_text('{"packageManager": "pnpm@11.2.2"}', encoding="utf-8")
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        if cmd[:3] == ["pnpm", "exec", "tsx"]:
            raise FileNotFoundError("pnpm")
        assert cmd[:5] == ["npm", "exec", "--yes", "pnpm@11.2.2", "--"]
        assert cmd[5:7] == ["exec", "tsx"]
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
    assert commands[1][:3] == ["pnpm", "exec", "tsx"]
    assert commands[2][:5] == ["npm", "exec", "--yes", "pnpm@11.2.2", "--"]


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


# --- oracle checkout default and Node engines check -------------------------------------------

TAG_ENGINES = ">=24.16.0 <25 || >=26.1.0"  # package.json engines.node at v2026.9.6


def test_default_oracle_repo_is_the_pin_checkout(monkeypatch):
    monkeypatch.delenv("OPENCLAW_ORACLE_REPO", raising=False)
    assert openclaw_oracle.resolve_oracle_repo() == openclaw_oracle.PIN_CHECKOUT_PATH
    assert OpenClawOracle().repo_path == openclaw_oracle.PIN_CHECKOUT_PATH
    monkeypatch.setenv("OPENCLAW_ORACLE_REPO", "/elsewhere/openclaw")
    assert OpenClawOracle().repo_path == Path("/elsewhere/openclaw")


def test_node_version_satisfies_the_tag_engines_range():
    satisfies = openclaw_oracle.node_version_satisfies
    assert satisfies("v24.21.0", TAG_ENGINES) is True
    assert satisfies("v24.16.0", TAG_ENGINES) is True
    assert satisfies("v26.1.0", TAG_ENGINES) is True
    assert satisfies("v25.2.1", TAG_ENGINES) is False
    assert satisfies("v24.15.9", TAG_ENGINES) is False
    assert satisfies("v26.0.5", TAG_ENGINES) is False
    # The old pin 4c428153 asked for >=22.19.0 <23 || >=23.11.0.
    assert satisfies("v25.2.1", ">=22.19.0 <23 || >=23.11.0") is True
    assert satisfies("v23.10.0", ">=22.19.0 <23 || >=23.11.0") is False
    assert satisfies("v24.1.0", "^24.0.0") is True
    assert satisfies("v25.0.0", "^24") is False
    assert satisfies("v24.3.9", "~24.3") is True
    assert satisfies("v20.0.0", "18 - 22") is True
    assert satisfies("v24.0.0", "node >= 24") is None


def _engines_repo(tmp_path: Path, engines: str | None = TAG_ENGINES) -> Path:
    repo = tmp_path / "openclaw"
    repo.mkdir()
    (repo / ".git").mkdir()
    package = {"packageManager": "pnpm@12.4.0"}
    if engines is not None:
        package["engines"] = {"node": engines}
    (repo / "package.json").write_text(json.dumps(package), encoding="utf-8")
    return repo


def _fake_node(tmp_path: Path, version: str) -> Path:
    node = tmp_path / "node-bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
    node.chmod(0o755)
    return node


def test_run_refuses_a_node_outside_the_checkout_engines(monkeypatch, tmp_path: Path):
    repo = _engines_repo(tmp_path)
    node = _fake_node(tmp_path, "v25.2.1")
    monkeypatch.setenv("OPENCLAW_ORACLE_NODE", str(node))
    openclaw_oracle._probe_node_version.cache_clear()

    result = OpenClawOracle(repo_path=repo).run({"operation": "deepPolicy"})

    assert result["ok"] is False
    assert result["error"]["code"] == "oracle-node-unsupported"
    message = result["error"]["message"]
    assert f"OPENCLAW_ORACLE_NODE={node} is v25.2.1" in message
    assert TAG_ENGINES in message and str(repo / "package.json") in message


def test_run_reports_a_missing_oracle_node(monkeypatch, tmp_path: Path):
    repo = _engines_repo(tmp_path)
    monkeypatch.setenv("OPENCLAW_ORACLE_NODE", str(tmp_path / "no-such-node"))
    openclaw_oracle._probe_node_version.cache_clear()

    result = OpenClawOracle(repo_path=repo).run({"operation": "deepPolicy"})

    assert result["ok"] is False
    assert result["error"]["code"] == "oracle-node-missing"


def test_run_puts_the_oracle_node_first_on_path(monkeypatch, tmp_path: Path):
    repo = _engines_repo(tmp_path)
    node = _fake_node(tmp_path, "v24.21.0")
    monkeypatch.setenv("OPENCLAW_ORACLE_NODE", str(node))
    openclaw_oracle._probe_node_version.cache_clear()
    seen_env = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd == [str(node), "--version"]:
            return real_run(cmd, **kwargs)
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        seen_env.append(kwargs.get("env"))
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(openclaw_oracle.subprocess, "run", fake_run)

    result = OpenClawOracle(repo_path=repo).run({"operation": "deepPolicy"})

    assert result["ok"] is True
    assert seen_env[0]["PATH"].split(os.pathsep)[0] == str(node.parent)


def test_resolve_oracle_node_reports_the_engines_check(monkeypatch, tmp_path: Path):
    repo = _engines_repo(tmp_path)
    node = _fake_node(tmp_path, "v24.21.0")
    monkeypatch.setenv("OPENCLAW_ORACLE_NODE", str(node))
    openclaw_oracle._probe_node_version.cache_clear()

    resolved = openclaw_oracle.resolve_oracle_node(repo).to_json()

    assert resolved == {
        "path": str(node),
        "version": "v24.21.0",
        "engines": TAG_ENGINES,
        "satisfies": True,
        "env": "OPENCLAW_ORACLE_NODE",
    }
