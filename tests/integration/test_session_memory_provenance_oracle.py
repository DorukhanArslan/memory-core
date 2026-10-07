"""Real hook trust records, using handler.test.ts's owner/untrusted/tainted cases."""

import os
from pathlib import Path

from demo.openclaw_oracle import OpenClawOracle
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.session_memory import save_session_memory

NOW_MS = 1767241815000
SESSION_ID = "test-123"
SESSION_KEY = "agent:main:main"


def test_session_hook_provenance_matches_openclaw(tmp_path: Path):
    scenarios = []
    for owner, tainted, repeats in [(True, False, 1), (False, False, 1), (True, True, 1), (True, False, 2)]:
        rows = [
            {"type": "message", "message": {
                "role": "user", "content": "Retain this request",
                "__openclaw": {"senderIsOwner": owner},
            }},
            {"type": "message", "message": {
                "role": "assistant", "content": "Retained response",
                **({"__openclaw": {"turnTainted": True}} if tainted else {}),
            }},
        ]
        scenarios.append({
            "transcripts": {SESSION_ID: rows},
            "events": [{
                "type": "command", "action": "new", "sessionKey": SESSION_KEY,
                "previousSessionEntry": {"sessionId": SESSION_ID},
                "nowMs": NOW_MS, "timezone": "UTC",
            }] * repeats,
        })
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=120)
    response = oracle.run({
        "operation": "sessionMemoryHook", "scenarios": scenarios, "includeProvenance": True,
    })
    assert response["ok"] is True, response
    for index, (scenario, actual) in enumerate(zip(scenarios, response["result"]["scenarios"], strict=True)):
        root = tmp_path / f"ws-{index}"
        store = MemoryArtifactProvenanceStore(tmp_path / f"trust-{index}.sqlite")
        for _ in scenario["events"]:
            save_session_memory(
                root, session_key=SESSION_KEY, session_id=SESSION_ID,
                events=scenario["transcripts"][SESSION_ID], now_ms=NOW_MS,
                artifact_provenance=store,
            )
        assert {p.name: p.read_text("utf-8") for p in (root / "memory").iterdir()} == actual["memory"]
        expected = [{"relativePath": path, "provenance": {
            "fileHash": record.file_hash, "originClass": record.origin_class,
            "observedAt": record.observed_at,
            "sessionId": record.session_id, "sessionKey": record.session_key,
        }} for path, record in store.list(root)]
        assert sorted(actual["provenance"], key=lambda r: r["relativePath"]) == sorted(
            expected, key=lambda r: r["relativePath"]
        )
