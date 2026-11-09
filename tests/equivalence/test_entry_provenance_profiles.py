"""Full fixed-cut replay of genuine development outcomes, without point credit."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.entry_provenance_fixtures import ENTRY_PROVENANCE_OPERATIONS, build_entry_provenance_cases
from equivalence.entry_provenance_runtime import run_entry_provenance


def _capture():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-development-actual.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    raw = gzip.decompress(compressed)
    assert len(raw) == manifest["rawBytes"]
    assert hashlib.sha256(raw).hexdigest() == manifest["rawSha256"] == "b9ce6bb34a12f98463095bee1d5ea6d39e4bd7996555668b1ac5a8921eaed07b"
    return json.loads(raw)


def test_fixed_catalog_retains_all_three_real_boundaries_without_registration_or_credit():
    cases = build_entry_provenance_cases()
    capture = _capture()
    # Historical uncredited captures used one umbrella routing label. Preserve
    # every literal fact while registering three mutually scoped operations.
    original_cases = deepcopy([row["case"] for row in capture["observations"]])
    for case in original_cases:
        assert case["operation"] == "entry-provenance-runtime"
        case["operation"] = ENTRY_PROVENANCE_OPERATIONS[case["input"]["kind"]]
    assert cases == original_cases
    assert len(cases) == 3 and all(case["covers"] == [] for case in cases)
    assert {case["operation"] for case in cases} == set(ENTRY_PROVENANCE_OPERATIONS.values())
    assert all("No provider loop/transport" in case["driverScope"] for case in cases)
    changed = deepcopy(cases)
    changed[0]["input"]["files"]["MEMORY.md"] = "changed"
    assert build_entry_provenance_cases() == cases


@pytest.mark.parametrize("case", build_entry_provenance_cases(), ids=lambda case: case["id"])
def test_entire_original_fixed_cut_matches_actual_sdk_without_field_drops_or_hash_repair(case, tmp_path):
    capture, = [row for row in _capture()["observations"] if row["case"]["id"] == case["id"]]
    result = run_entry_provenance(case["input"], evidence_directory=tmp_path)
    assert {"ok": True, "result": result} == capture["nativePublic"]
    raw, = json.loads((tmp_path / "python-raw.json").read_text())
    assert raw["input"] == case["input"]
    assert all(snapshot["physical"]["schema"] and snapshot["physical"]["tables"] for snapshot in raw["snapshots"])
    if case["input"]["kind"] == "prepared-provider":
        assert len(result["fragments"]) > len(result["state"]["chunks"])
        assert len({fragment["id"] for fragment in result["fragments"]}) == len(result["state"]["chunks"])
        assert len({fragment["entryStartLine"] for fragment in result["fragments"] if "entryStartLine" in fragment}) == 2
        assert raw["providerCalls"] and raw["preparations"]
    elif case["input"]["kind"] == "session-projection":
        first, revision_only = result["steps"][:2]
        assert first["state"]["chunks"] == revision_only["state"]["chunks"]
        assert first["state"]["sources"] != revision_only["state"]["sources"]
        assert {line["originClass"] for line in first["sources"][0]["entry"]["lineProvenance"]} == {"owner", "agent", "system", "untrusted"}
        valid, invalid = result["steps"][-2:]
        assert len(first["state"]["chunks"]) == len(invalid["state"]["chunks"]) == 1
        assert len(valid["state"]["chunks"]) == 2
        cutoff = valid["sources"][0]["resetRecallCutoff"]["cutoffLine"]
        assert all(chunk["endLine"] < cutoff or chunk["startLine"] >= cutoff for chunk in valid["state"]["chunks"])
        assert all(snapshot["sessionPhysical"]["schema"] for snapshot in raw["snapshots"])
    else:
        assert result["steps"][0]["state"] == result["steps"][1]["state"] == result["steps"][2]["state"]
        assert result["steps"][2]["state"] != result["steps"][3]["state"]


def test_both_original_unmapped_physical_sql_and_all_actual_calls_remain_in_genuine_capture():
    for captured in _capture()["observations"]:
        native, = json.loads(captured["nativeRawJson"])
        sdk, = json.loads(captured["sdkRawJson"])
        assert Path(native["fixtureBase"]).is_absolute() and Path(sdk["fixtureBase"]).is_absolute()
        assert native["calls"] and sdk["calls"]
        assert native["snapshots"] and sdk["snapshots"]
        assert native["calls"][-1] == {"operation": "close", "completed": True}
        for snapshot in native["snapshots"]:
            assert snapshot["physical"]["schema"] and snapshot["physical"]["tables"]
            assert "memory_index_chunks" in {table["name"] for table in snapshot["physical"]["tables"]}
        for snapshot in sdk["snapshots"]:
            assert "chunks" in {table["name"] for table in snapshot["physical"]["tables"]}
