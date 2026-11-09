"""Genuine original SQL/call captures reject altered identity and data transport."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.entry_provenance_evidence import _embedding, validate_entry_observations, validate_entry_physical_state
from equivalence.get_contract import map_get_fixture_paths
from equivalence.runtime_oracle import RuntimeOracleError


@pytest.fixture(scope="module")
def original_development_captures():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-protected-captures.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    original = gzip.decompress(compressed)
    assert len(original) == manifest["rawBytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["rawSha256"] == "9e02ba6f86fa9589799981f2f466835c75caf182f10f42c3334b8bfb1371293e"
    capture = json.loads(original)
    results = {}
    for observation in capture["observations"]:
        original_native = observation["nativeJson"].encode()
        assert len(original_native) == observation["bytes"]
        assert hashlib.sha256(original_native).hexdigest() == observation["sha256"]
        native = json.loads(original_native)
        row, = native["results"]
        diagnostic, = native["runtimeDiagnostics"]
        raw, = diagnostic["rawSnapshots"]
        assert row["ok"] is True and row["id"] == diagnostic["id"]
        results[raw["kind"]] = {"raw": raw, "input": raw["input"], "public": row["result"]}
    assert len(results) == 3
    return results


def _raw(captures, kind):
    captured = captures[kind]
    return deepcopy(captured["raw"]), deepcopy(captured["input"]), deepcopy(captured["public"])


def test_actual_original_binary64_blob_decodes_without_float32_reinterpretation(original_development_captures):
    raw, _, _ = _raw(original_development_captures, "prepared-provider")
    table = next(table for table in raw["snapshots"][0]["physical"]["tables"] if table["name"] == "memory_index_chunks")
    original = table["rows"][0]["embedding"]
    assert original == {"type": "bytes", "hex": "000000000000f03f0000000000000000"}
    assert _embedding(original) == [1, 0]


def test_historical_first_failure_keeps_the_same_original_binary64_bytes():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-development-actual.json.gz"
    original = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(original).hexdigest() == "b9ce6bb34a12f98463095bee1d5ea6d39e4bd7996555668b1ac5a8921eaed07b"
    capture = json.loads(original)
    row, = [row for row in capture["observations"] if row["case"]["input"]["kind"] == "prepared-provider"]
    raw, = json.loads(row["nativeRawJson"])
    table = next(table for table in raw["snapshots"][0]["physical"]["tables"] if table["name"] == "memory_index_chunks")
    assert table["rows"][0]["embedding"] == {"type": "bytes", "hex": "000000000000f03f0000000000000000"}
    assert _embedding(table["rows"][0]["embedding"]) == [1, 0]


@pytest.mark.parametrize("kind", ["published-memory", "prepared-provider", "session-projection"])
def test_complete_original_physical_sql_binds_every_canonical_column_and_order(original_development_captures, kind):
    raw, _, _ = _raw(original_development_captures, kind)
    for snapshot in raw["snapshots"]:
        validate_entry_physical_state(snapshot)


@pytest.mark.parametrize("kind", ["published-memory", "session-projection"])
def test_unchanged_actual_manager_calls_and_full_sources_bind_public_output(original_development_captures, kind):
    raw, value, public = _raw(original_development_captures, kind)
    validate_entry_observations(raw, value, public)


@pytest.mark.parametrize("tamper", ["hash", "canonical-id", "vector", "updated-at", "origin", "recall", "fts-text",
                                   "chunk-order", "fts-order", "physical-private-id", "missing-table", "missing-schema",
                                   "physical-hash", "physical-vector-carrier", "row-count", "schema-count",
                                   "shadow-row", "shadow-column", "no-read-transaction"])
def test_changed_canonical_or_full_physical_sql_is_rejected_without_repair(original_development_captures, tamper):
    raw, _, _ = _raw(original_development_captures, "prepared-provider")
    snapshot = raw["snapshots"][0]
    state = snapshot["state"]
    tables = {table["name"]: table for table in snapshot["physical"]["tables"]}
    if tamper == "hash":
        state["chunks"][0]["hash"] = "forged"
    elif tamper == "canonical-id":
        state["chunks"][0]["id"] = "salted-for-uniqueness"
    elif tamper == "vector":
        state["chunks"][0]["embedding"] = []
    elif tamper == "updated-at":
        state["chunks"][0]["updatedAt"] += 1
    elif tamper == "origin":
        state["chunks"][0]["provenance"]["originClass"] = "untrusted"
    elif tamper == "recall":
        state["chunks"][0]["recall"]["importance"] = 10
    elif tamper == "fts-text":
        state["fts"][0]["text"] = "repaired text"
    elif tamper == "chunk-order":
        state["chunks"].reverse()
    elif tamper == "fts-order":
        state["fts"].reverse()
    elif tamper == "physical-private-id":
        del tables["memory_index_sources"]["rows"][0]["id"]
    elif tamper == "missing-table":
        snapshot["physical"]["tables"] = [table for table in snapshot["physical"]["tables"] if table["name"] != "memory_index_chunks_fts_data"]
    elif tamper == "missing-schema":
        snapshot["physical"]["schema"] = snapshot["physical"]["schema"][1:]
    elif tamper == "physical-hash":
        tables["memory_index_chunks"]["rows"][0]["hash"] = "forged"
    elif tamper == "physical-vector-carrier":
        tables["memory_index_chunks"]["rows"][0]["embedding"] = "b'raw bytes were stringified'"
    elif tamper == "row-count":
        tables["memory_index_chunks"]["rowCount"] -= 1
    elif tamper == "schema-count":
        snapshot["physical"]["schemaCount"] -= 1
    elif tamper == "shadow-row":
        tables["memory_index_chunks_fts_data"]["rows"].pop()
    elif tamper == "shadow-column":
        del tables["memory_index_chunks_fts_data"]["rows"][0]["block"]
    else:
        snapshot["physical"]["snapshotTransaction"]["active"] = False
    with pytest.raises(RuntimeOracleError):
        validate_entry_physical_state(snapshot)


@pytest.mark.parametrize("tamper", ["literal-write", "force", "dropped-call", "extra-call", "no-close", "public-drop"])
def test_original_memory_api_requests_and_complete_return_cannot_be_rewritten(original_development_captures, tamper):
    raw, value, public = _raw(original_development_captures, "published-memory")
    if tamper == "literal-write":
        raw["calls"][0]["content"] = "different source"
    elif tamper == "force":
        next(call for call in raw["calls"] if call["operation"] == "sync")["request"]["force"] = True
    elif tamper == "dropped-call":
        raw["calls"].pop(2)
    elif tamper == "extra-call":
        raw["calls"].append(deepcopy(raw["calls"][-1]))
    elif tamper == "no-close":
        raw["calls"][-1]["completed"] = False
    else:
        del public["steps"][0]["state"]["provenance"]
    with pytest.raises(RuntimeOracleError):
        validate_entry_observations(raw, value, public)


@pytest.mark.parametrize("tamper", ["replace-records", "sync-target", "full-source", "cutoff", "source-options",
                                   "bare-fingerprint", "line-provenance-loss", "persisted-record"])
def test_session_replacements_original_reads_and_reset_evidence_remain_complete(original_development_captures, tamper):
    raw, value, public = _raw(original_development_captures, "session-projection")
    first_source = next(call for call in raw["calls"] if call["operation"] == "buildSessionEntry")
    if tamper == "replace-records":
        next(call for call in raw["calls"] if call["operation"] == "replaceTranscriptEvents")["events"] = []
    elif tamper == "sync-target":
        next(call for call in raw["calls"] if call["operation"] == "sync" and "sessions" in call["request"])["request"]["sessions"] = []
    elif tamper == "full-source":
        del first_source["entry"]["content"]
    elif tamper == "cutoff":
        first_source["resetRecallCutoff"] = {"state": "valid", "cutoffLine": 999}
    elif tamper == "source-options":
        first_source["options"]["sessionKey"] = "agent:main:direct:other"
    elif tamper == "bare-fingerprint":
        snapshot = raw["snapshots"][0]
        source = snapshot["state"]["sources"][0]
        source["hash"] = source["hash"].rsplit(":", 1)[-1]
        next(table for table in snapshot["physical"]["tables"] if table["name"] == "memory_index_sources")["rows"][0]["hash"] = source["hash"]
        public = map_get_fixture_paths({"provider": "none", "steps": [
            {key: snapshot[key] for key in ("label", "state", "sources")} for snapshot in raw["snapshots"]]}, raw["fixtureBase"])
    elif tamper == "line-provenance-loss":
        first_source["entry"]["lineProvenance"].pop()
    else:
        snapshot = raw["snapshots"][0]
        table = next(table for table in snapshot["physical"]["tables"] if table["name"] == "transcript_events")
        table["rows"][1]["event_json"] = '{}'
    with pytest.raises(RuntimeOracleError):
        validate_entry_observations(raw, value, public)
