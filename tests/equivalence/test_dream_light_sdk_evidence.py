"""The light dreaming gate needs physical publication and non-vacuous grouping."""
import json

import pytest

from equivalence.dream_light import build_cases
from equivalence.dream_light_sdk import run_sdk
from equivalence.dream_light_sdk_evidence import validate_sdk


def test_sdk_gate_reopens_the_report_even_with_a_matching_receipt(tmp_path):
    case = next(case for case in build_cases() if case["id"].endswith("diary-priority"))
    public = run_sdk(case, tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_bytes())
    validate_sdk(case, public, raw, tmp_path)
    report = tmp_path / "sdk-fixture/workspace/memory/dreaming/light/2026-01-01.md"
    report.write_bytes(report.read_bytes().replace(b"shoreline", b"altered  "))
    with pytest.raises(ValueError, match="live fixture"):
        validate_sdk(case, public, raw, tmp_path)


def test_sdk_gate_checks_all_contributing_source_keys(tmp_path):
    case = next(case for case in build_cases() if case["id"].endswith("group-and-order"))
    public = run_sdk(case, tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_bytes())
    fields = raw[0]["operations"][0]["return"]["fields"]
    fields["light_entries"][0]["sourceEntryKeys"] = ["cedar"]
    with pytest.raises(ValueError, match="source groups"):
        validate_sdk(case, public, raw, tmp_path)
