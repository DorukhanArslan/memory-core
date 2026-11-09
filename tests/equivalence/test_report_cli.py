"""The acceptance CLI must retain complete original Unicode observations."""
import json
import sys

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
        "cases": [{"input": fixture["input"], "native": "\ud800 left \udfff",
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
    assert json.loads(output.out)["fullScopePassed"] is False
