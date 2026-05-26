from pathlib import Path

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
