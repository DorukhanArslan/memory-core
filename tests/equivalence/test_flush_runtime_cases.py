"""Integrity checks for runtime fixtures; native results require the pinned run."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from equivalence.flush_runtime import (
    build_flush_runtime_cases,
    run_flush_runtime,
    serialized_event_bytes,
)


def _case(name):
    return next(case["input"] for case in build_flush_runtime_cases()
                if case["id"] == f"flush-runtime-{name}")


def test_runtime_fixtures_are_unique_reproducible_json_and_declare_their_boundary():
    cases = build_flush_runtime_cases()
    assert cases == build_flush_runtime_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["operation"] == "flush-trigger-runtime" for case in cases)
    assert all(case["requirement"] == "flush.trigger-usage" for case in cases)
    allowed = {"flush.trigger-usage.outcomes", "flush.trigger-usage.boundaries"}
    assert {point for case in cases for point in case["covers"]} == allowed
    assert all(case["covers"] and set(case["covers"]) <= allowed for case in cases)
    assert all(len(case["covers"]) == len(set(case["covers"])) for case in cases)
    assert all("before model execution" in case["driverScope"] for case in cases)
    assert all("absent fields preserved" in case["normalizationPolicy"] for case in cases)


def test_runtime_acceptance_classification_tracks_the_behavior_each_fixture_exercises():
    cases = {case["id"].removeprefix("flush-runtime-"): case for case in build_flush_runtime_cases()}
    assert cases["stale-usage-recovered"]["covers"] == ["flush.trigger-usage.outcomes"]
    assert cases["oversized-tool-projection"]["covers"] == ["flush.trigger-usage.outcomes"]
    assert cases["heartbeat-exclusion"]["covers"] == ["flush.trigger-usage.boundaries"]
    assert cases["retry-exhaustion-and-next-cycle"]["covers"] == ["flush.trigger-usage.boundaries"]
    assert cases["transcript-bytes-at"]["covers"] == [
        "flush.trigger-usage.outcomes", "flush.trigger-usage.boundaries",
    ]
    assert cases["current-cycle-success-suppresses"]["covers"] == [
        "flush.trigger-usage.outcomes", "flush.trigger-usage.boundaries",
    ]


def test_python_transport_preserves_inputs_and_retains_full_evidence(tmp_path):
    arguments = _case("retry-exhaustion-and-next-cycle")
    before = deepcopy(arguments)
    output = run_flush_runtime(arguments, evidence_directory=tmp_path)
    assert arguments == before
    assert json.loads(json.dumps(output, allow_nan=False)) == output
    raw = json.loads((tmp_path / "python-raw.json").read_text(encoding="utf-8"))
    assert len(raw) == len(output["snapshots"]) == 6
    assert all("session" in snapshot and "decision" in snapshot for snapshot in raw)
    assert raw[0]["session"]["entry"]["sessionId"] == "session"


def test_runtime_accounting_regression_covers_the_maintenance_output_asymmetry():
    empty_prompt = run_flush_runtime(_case("fresh-empty-prompt-does-not-read-output"))
    recovered = run_flush_runtime(_case("stale-usage-recovered"))
    below = run_flush_runtime(_case("fresh-output-buffer-below"))
    at = run_flush_runtime(_case("fresh-output-buffer-at"))
    assert empty_prompt["snapshots"][0]["outcome"] == "skipped"
    assert recovered["snapshots"][0]["triggered"] is True
    assert below["snapshots"][0]["triggered"] is False
    assert at["snapshots"][0]["triggered"] is True
    assert recovered["snapshots"][0]["entry"]["totalTokensFresh"] is True


def test_retry_fixture_reloads_state_exhausts_and_readmits_next_cycle():
    snapshots = run_flush_runtime(_case("retry-exhaustion-and-next-cycle"))["snapshots"]
    assert [snapshot["outcome"] for snapshot in snapshots] == [
        "failed", "failed", "exhausted", "skipped", "failed", "failed",
    ]
    assert snapshots[2]["entry"]["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    assert snapshots[4]["entry"]["memoryFlush"] == {
        "kind": "failed", "compactionCount": 0, "failureCount": 1,
    }
    assert all(snapshot["entry"] == snapshot["persistedEntry"] for snapshot in snapshots)


def test_incognito_adapter_keeps_state_process_local():
    for name in ("incognito-entry-exclusion", "incognito-key-exclusion"):
        snapshot = run_flush_runtime(_case(name))["snapshots"][0]
        assert snapshot["triggered"] is False
        assert snapshot["persistedEntry"] is None
        assert snapshot["transcriptByteSize"] is None


def test_unicode_byte_threshold_comes_from_exact_canonical_event_bytes():
    arguments = _case("transcript-bytes-at")
    byte_size = serialized_event_bytes(arguments["events"])
    assert byte_size == arguments["flushConfig"]["forceFlushTranscriptBytes"]
    assert byte_size > len(json.dumps(arguments["events"][0], ensure_ascii=False,
                                     separators=(",", ":")))
    assert run_flush_runtime(_case("transcript-bytes-below"))["snapshots"][0]["triggered"] is False
    assert run_flush_runtime(arguments)["snapshots"][0]["triggered"] is True


def test_host_byte_snapshot_drops_discarded_history_after_reset():
    arguments = _case("reset-discards-byte-force")
    assert serialized_event_bytes(arguments["events"]) > 1
    snapshot = run_flush_runtime(arguments)["snapshots"][0]
    assert snapshot["transcriptByteSize"] == 0
    assert snapshot["preparationAttempts"] == 0
    assert snapshot["outcome"] == "skipped"


def test_leaf_fixture_uses_selected_branch_instead_of_latest_side_usage():
    discarded = run_flush_runtime(_case("active-leaf-discards-side-usage"))["snapshots"][0]
    selected = run_flush_runtime(_case("active-leaf-selects-reliable-usage"))["snapshots"][0]
    assert discarded["triggered"] is False
    assert discarded["entry"]["totalTokens"] == 50
    assert selected["triggered"] is True
    assert selected["entry"]["totalTokens"] == 175999


def test_runtime_usage_scan_stops_at_latest_output_only_anchor_and_bounded_tail():
    for name in ("latest-output-only-anchor-stops-scan", "usage-tail-limit-excludes-old-snapshot"):
        snapshot = run_flush_runtime(_case(name))["snapshots"][0]
        assert snapshot["triggered"] is False
        assert "totalTokens" not in snapshot["entry"]


def _reviewed_owner_fixture(tmp_path, monkeypatch):
    from equivalence import flush_runtime_bindings as bindings

    checkout = tmp_path / "source"
    runtime = tmp_path / "runtime"
    source_name = "src/auto-reply/reply/agent-runner-memory.ts"
    compiled_name = "dist/agent-runner-memory-Cc4lCZcs.mjs"
    source = "export async function runMemoryFlushIfNeeded(params) { return params; }\n"
    compiled = "async function runMemoryFlushIfNeeded(params) { return params; }\n" \
               "export { runMemoryFlushIfNeeded as t };\n"
    for root, name, text in ((checkout, source_name, source), (runtime, compiled_name, compiled)):
        file = root / name
        file.parent.mkdir(parents=True)
        file.write_text(text, encoding="utf-8")
    monkeypatch.setattr(bindings, "SOURCE_HASHES", {source_name: hashlib.sha256(source.encode()).hexdigest()})
    monkeypatch.setattr(bindings, "COMPILED_HASHES", {compiled_name: hashlib.sha256(compiled.encode()).hexdigest()})
    monkeypatch.setattr(bindings.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(stdout=bindings.REFERENCE_COMMIT + "\n"))
    return bindings, checkout, runtime, source_name, compiled_name


@pytest.mark.parametrize("changed", ["source", "compiled"])
def test_runtime_owner_provenance_rejects_modified_reviewed_bytes(tmp_path, monkeypatch, changed):
    bindings, checkout, runtime, source_name, compiled_name = _reviewed_owner_fixture(tmp_path, monkeypatch)
    evidence = bindings.prepare_flush_runtime_bindings(checkout, runtime)
    assert evidence["entrypoint"]["owner"] == "runMemoryFlushIfNeeded"
    assert evidence["sourceBuildReproduced"] is False
    path = checkout / source_name if changed == "source" else runtime / compiled_name
    path.write_bytes(path.read_bytes() + b"\n// modified\n")
    with pytest.raises(ValueError, match="reviewed bytes"):
        bindings.prepare_flush_runtime_bindings(checkout, runtime)


def test_runtime_owner_provenance_rejects_wrong_source_revision(tmp_path, monkeypatch):
    bindings, checkout, runtime, _, _ = _reviewed_owner_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(bindings.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(stdout="0" * 40 + "\n"))
    with pytest.raises(ValueError, match="commit differs"):
        bindings.prepare_flush_runtime_bindings(checkout, runtime)
