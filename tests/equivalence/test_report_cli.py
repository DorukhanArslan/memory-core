"""The acceptance CLI must retain complete original Unicode observations."""
import json
from pathlib import Path
import sys

import pytest

from equivalence.redaction_fixtures import source_policy_fixtures
from scripts import check_equivalence


def test_report_retains_literal_surrogates_and_full_mismatch_without_changing_status(
    tmp_path, monkeypatch, capsys,
):
    fixture = next(row for row in source_policy_fixtures()
                   if row["id"].endswith("unicode-literal-lone-surrogate"))
    report = {
        "mode": "full", "status": "mismatched", "summary": {"mismatched": 1},
        "errors": [], "fullScopePassed": False,
        "cases": [{"id": fixture["id"], "status": "mismatched",
                   "input": fixture["input"], "native": "\ud800 left \udfff",
                   "python": "İstanbul 😀", "differences": ["actual retained mismatch"]}],
    }
    monkeypatch.setattr(check_equivalence, "run_suite", lambda **kwargs: (report, 1))
    destination = tmp_path / "new" / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "check_equivalence.py", "--reference", str(tmp_path), "--node", str(tmp_path / "node"),
        "--report", str(destination),
    ])

    assert check_equivalence.main() == 1
    assert json.loads(destination.read_text(encoding="utf-8")) == report
    output = capsys.readouterr()
    assert not output.err
    summary = json.loads(output.out)
    assert summary["fullScopePassed"] is False
    assert summary["mismatchedCaseIds"] == [fixture["id"]]
    assert summary["blockedCaseIds"] == []
    assert "İstanbul" not in output.out and "actual retained mismatch" not in output.out


@pytest.mark.parametrize("code,status", [(0, "passed"), (1, "mismatched"), (2, "blocked")])
def test_compact_report_preserves_nested_values_and_suite_return_code(
    tmp_path, monkeypatch, capsys, code, status,
):
    values = [True, False, None, 0, -17, 1.0, -0.0, 1.25, "\ud800\nİstanbul 😀\udfff"]
    report = {
        "mode": "full", "status": status, "summary": {"matched": 1},
        "errors": [], "fullScopePassed": code == 0,
        "cases": [{"id": "retained", "status": "matched", "openclaw": {
            "public": [{"values": values, "raw": {"empty": [], "nested": {"value": None}}}
                       for _ in range(32)],
        }}],
    }
    monkeypatch.setattr(check_equivalence, "run_suite", lambda **kwargs: (report, code))
    destination = tmp_path / "new" / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "check_equivalence.py", "--reference", str(tmp_path), "--node", str(tmp_path / "node"),
        "--report", str(destination),
    ])

    assert check_equivalence.main() == code
    payload = destination.read_bytes()
    retained = json.loads(payload)
    assert retained == report
    actual_values = retained["cases"][0]["openclaw"]["public"][0]["values"]
    assert [type(value) for value in actual_values] == [type(value) for value in values]
    assert json.dumps(actual_values, allow_nan=False) == json.dumps(values, allow_nan=False)
    assert payload.endswith(b"\n") and payload.count(b"\n") == 1
    assert payload.isascii()
    assert len(payload) < len(json.dumps(report, ensure_ascii=True, indent=2).encode("utf-8"))
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["status"] == status


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_report_rejects_nonfinite_original_observations(tmp_path, monkeypatch, capsys, value):
    report = {"original": {"nested": [value]}}
    monkeypatch.setattr(check_equivalence, "run_suite", lambda **kwargs: (report, 0))
    destination = tmp_path / "new" / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "check_equivalence.py", "--reference", str(tmp_path), "--node", str(tmp_path / "node"),
        "--report", str(destination),
    ])

    assert check_equivalence.main() == 2
    assert not destination.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Equivalence report could not be retained.\n"


def test_report_write_failure_returns_retention_error_without_summary(tmp_path, monkeypatch, capsys):
    report = {"original": {"nested": [True, None, "\ud800"]}}
    monkeypatch.setattr(check_equivalence, "run_suite", lambda **kwargs: (report, 1))
    destination = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "check_equivalence.py", "--reference", str(tmp_path), "--node", str(tmp_path / "node"),
        "--report", str(destination),
    ])

    def reject_write(path, *args, **kwargs):
        assert path == destination
        raise OSError("actual report destination rejected")

    monkeypatch.setattr(Path, "write_text", reject_write)
    assert check_equivalence.main() == 2
    assert not destination.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Equivalence report could not be retained.\n"
