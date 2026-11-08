"""Input/transport integrity; native owner execution establishes equivalence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

import pytest

from equivalence.cases import run_python
from equivalence.get_contract import map_get_fixture_paths
from equivalence.session_contract import build_session_contract_cases, run_session_contract


def test_catalog_is_unique_deterministic_json_and_uncredited_until_actual_proof():
    cases = build_session_contract_cases()
    assert cases == build_session_contract_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(case["covers"] == [] for case in cases)
    assert {case["input"]["kind"] for case in cases} == {"admission-policy", "source-policy", "indexable", "flow"}


def test_genuine_owner_adapters_and_early_dispatcher_preserve_inputs():
    for case in build_session_contract_cases():
        before = deepcopy(case)
        direct = run_session_contract(case["input"])
        assert run_python(case) == direct
        json.dumps(direct, ensure_ascii=False, allow_nan=False)
        assert case == before


def test_policy_absence_and_empty_fields_remain_distinct_without_null_fillers():
    assert run_session_contract({"kind": "admission-policy", "pluginConfig": None}) == {"provider": "none"}
    assert run_session_contract({"kind": "admission-policy", "pluginConfig": {
        "memoryPolicy": {"excludeSessions": {"chatTypes": ["group"]}},
    }}) == {"provider": "none", "policy": {"channels": [], "chatTypes": ["group"], "hookExternalContentSources": []}}


def test_maintenance_indexability_is_called_on_real_owner_metadata():
    assert run_session_contract({"kind": "indexable", "entry": {"sessionKind": "cron"}}) == {"indexable": False}
    assert run_session_contract({"kind": "indexable", "entry": {"lineProvenance": []}}) == {"indexable": True}


def test_unknown_operation_is_not_a_success_placeholder():
    with pytest.raises(ValueError, match="Unsupported session-contract operation"):
        run_session_contract({"kind": "invented"})


@pytest.mark.parametrize("case", [
    case for case in build_session_contract_cases() if case["operation"] == "session-contract-runtime"
], ids=lambda case: case["id"])
def test_runtime_dispatch_retains_complete_wire_queries_source_reads_and_raw_sql(case, tmp_path):
    request = deepcopy(case)
    request["_diagnosticDirectory"] = str(tmp_path / "evidence")
    before = deepcopy(request)
    output = run_python(request)
    assert request == before
    raw, = json.loads((tmp_path / "evidence" / "python-raw.json").read_text())
    assert raw["constructorSkipped"] is False
    assert raw["managerFixture"] is False
    assert len(raw["snapshots"]) == len(case["input"]["steps"])
    assert len(raw["catalogRequests"]) == len(case["input"]["steps"])
    assert all(row["includeContentRevision"] is False for row in raw["catalogRequests"])
    fields = {"label", "catalog", "admitted", "sourceEntries", "published", "indexSources",
              "queries", "reads", "ingestionDecisions", "participantRecords"}
    observed_steps = []
    for snapshot, public in zip(raw["snapshots"], output["steps"], strict=True):
        assert set(public) == fields
        assert fields <= snapshot.keys()
        assert {"sources", "chunks", "fts", "paths"} <= snapshot["fullSql"].keys()
        assert snapshot["sessionSql"]
        observed_steps.append({field: snapshot[field] for field in fields})
    assert map_get_fixture_paths({"provider": "none", "steps": observed_steps}, raw["fixtureBase"]) == output
    query_count = sum(len(step.get("queries", [])) for step in case["input"]["steps"])
    assert len(raw["pythonEnvelopes"]) + len(raw["queryErrors"]) == query_count
    for row in raw["pythonEnvelopes"]:
        envelope = row["pythonEnvelope"]
        assert isinstance(envelope["content"][0]["text"], str)
        assert json.loads(envelope["content"][0]["text"]) == envelope["details"]
    assert len(raw["reads"]) == sum(len(step.get("reads", [])) for step in case["input"]["steps"])
    for written in raw["sessionWrites"]:
        if written["sessionKey"] == "agent:main:dashboard:incognito-hidden":
            assert written["transcript"]
            assert written["sessionKey"] not in written["storedEntries"]
            for snapshot in raw["snapshots"]:
                assert "incognito-hidden" not in json.dumps(snapshot["sessionSql"], ensure_ascii=False)
                assert not any(row["sessionId"] == "incognito-hidden" for row in snapshot["catalog"])
                assert not any("incognito-hidden" in row["path"] for row in snapshot["indexSources"])
    json.dumps(output, ensure_ascii=False, allow_nan=False)


def test_compressed_inputs_are_literal_shared_bytes_and_not_fixture_accepted_hit_lists():
    archive_cases = [case for case in build_session_contract_cases() if case["input"].get("archives")]
    assert len(archive_cases) == 2
    for case in archive_cases:
        archives = case["input"]["archives"]
        assert len(archives) == 2
        archive, = [row for row in archives if "identity" in row]
        legacy, = [row for row in archives if "identity" not in row]
        assert archive["compressedBytes"] == legacy["compressedBytes"]
        assert all(row["name"].endswith(".zst") for row in archives)
        assert bytes(archive["compressedBytes"]).startswith(bytes.fromhex("28b52ffd"))
        assert archive["identity"]["reason"] in {"reset", "deleted"}
        identity = archive["identity"]
        assert isinstance(identity["generation"], str)
        assert re.fullmatch("[0-9a-f]{32}", identity["generation"])
        stamp = datetime.fromtimestamp(identity["createdAt"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.000Z")
        assert archive["name"] == (
            f"{identity['sessionId']}.jsonl.{identity['reason']}.{stamp}.{identity['generation']}.zst"
        )
        assert not {"hits", "visibleKeys", "admitted", "resetSessions"} & case["input"].keys()
