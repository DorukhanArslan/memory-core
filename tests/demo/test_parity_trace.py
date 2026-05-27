from demo.parity_trace import (
    build_configured_deep_policy_trace,
    build_deep_policy_trace,
    build_parity_trace,
    build_recall_tracking_trace,
    build_repeated_recall_tracking_trace,
    diff_values,
)


RECALL_STORE_PATH = "memory/.dreams/short-term-recall.json"
EXPECTED_RECALL_STORE = """{
  "version": 1,
  "updatedAt": "2026-05-26T16:00:00.000Z",
  "entries": {
    "memory:memory/2026-05-26.md:3:3": {
      "key": "memory:memory/2026-05-26.md:3:3",
      "path": "memory/2026-05-26.md",
      "startLine": 3,
      "endLine": 3,
      "source": "memory",
      "snippet": "- User prefers to be addressed as dodo.",
      "recallCount": 1,
      "dailyCount": 0,
      "groundedCount": 0,
      "totalScore": 1.0,
      "maxScore": 1.0,
      "firstRecalledAt": "2026-05-26T16:00:00.000Z",
      "lastRecalledAt": "2026-05-26T16:00:00.000Z",
      "queryHashes": [
        "aa5368a7c7bd"
      ],
      "recallDays": [
        "2026-05-26"
      ],
      "conceptTags": [
        "prefers",
        "addressed",
        "dodo"
      ]
    }
  }
}
"""
EXPECTED_REPEATED_RECALL_STORE = """{
  "version": 1,
  "updatedAt": "2026-05-27T16:00:00.000Z",
  "entries": {
    "memory:memory/2026-05-26.md:3:3": {
      "key": "memory:memory/2026-05-26.md:3:3",
      "path": "memory/2026-05-26.md",
      "startLine": 3,
      "endLine": 3,
      "source": "memory",
      "snippet": "- User prefers to be addressed as dodo.",
      "recallCount": 2,
      "dailyCount": 0,
      "groundedCount": 0,
      "totalScore": 2.0,
      "maxScore": 1.0,
      "firstRecalledAt": "2026-05-26T16:00:00.000Z",
      "lastRecalledAt": "2026-05-27T16:00:00.000Z",
      "queryHashes": [
        "aa5368a7c7bd",
        "1da206d81a95"
      ],
      "recallDays": [
        "2026-05-26",
        "2026-05-27"
      ],
      "conceptTags": [
        "prefers",
        "addressed",
        "dodo"
      ]
    }
  }
}
"""


class FakeOracle:
    def metadata(self):
        return {"available": True, "commit": "abc123", "repoPath": "/repo"}

    def run(self, payload):
        if payload["operation"] == "deepPolicy":
            configured = (
                payload.get("config", {})
                .get("plugins", {})
                .get("entries", {})
                .get("memory-core", {})
                .get("config", {})
                .get("dreaming", {})
                .get("phases", {})
                .get("deep", {})
            )
            if configured:
                return {
                    "ok": True,
                    "operation": "deepPolicy",
                    "result": {
                        "minScore": 0.72,
                        "minRecallCount": 4,
                        "minUniqueQueries": 2,
                        "maxAgeDays": 14,
                        "enabled": True,
                        "limit": 7,
                        "recencyHalfLifeDays": 10,
                    },
                }
            return {
                "ok": True,
                "operation": "deepPolicy",
                "result": {
                    "minScore": 0.8,
                    "minRecallCount": 3,
                    "minUniqueQueries": 3,
                    "maxAgeDays": 30,
                    "enabled": False,
                    "limit": 10,
                    "recencyHalfLifeDays": 14,
                },
            }
        if payload["operation"] == "recordShortTermRecalls":
            return {
                "ok": True,
                "operation": "recordShortTermRecalls",
                "files": {RECALL_STORE_PATH: EXPECTED_RECALL_STORE},
            }
        if payload["operation"] == "recordShortTermRecallSequence":
            return {
                "ok": True,
                "operation": "recordShortTermRecallSequence",
                "files": {RECALL_STORE_PATH: EXPECTED_REPEATED_RECALL_STORE},
            }
        raise AssertionError(f"unexpected operation: {payload['operation']}")


class ExplodingOracle:
    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        raise RuntimeError("oracle exploded")


class MalformedSuccessOracle:
    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        return {"ok": True, "operation": "deepPolicy"}


class NoOpRecallOracle(FakeOracle):
    def run(self, payload):
        if payload["operation"] == "recordShortTermRecalls":
            return {
                "ok": True,
                "operation": "recordShortTermRecalls",
                "files": {RECALL_STORE_PATH: '{"version": 1, "entries": {}}'},
            }
        return super().run(payload)


class MalformedRecallOracle(FakeOracle):
    def run(self, payload):
        if payload["operation"] == "recordShortTermRecalls":
            return {"ok": True, "operation": "recordShortTermRecalls"}
        return super().run(payload)


class ExplodingRecallOracle(FakeOracle):
    def run(self, payload):
        if payload["operation"] == "recordShortTermRecalls":
            raise RuntimeError("recall oracle exploded")
        return super().run(payload)


def test_diff_values_reports_mismatch():
    diff = diff_values({"minScore": 0.75}, {"minScore": 0.8})

    assert diff["status"] == "mismatch"
    assert "minScore: python=0.75 openclaw=0.8" in diff["details"]


def test_build_deep_policy_trace_matches_openclaw_defaults():
    trace = build_deep_policy_trace(FakeOracle())

    assert trace["id"] == "deep-policy"
    assert trace["diff"]["status"] == "match"
    assert trace["python"]["values"]["minScore"] == 0.8
    assert trace["openclaw"]["values"]["minScore"] == 0.8
    assert trace["python"]["values"]["minUniqueQueries"] == 3
    assert trace["openclaw"]["values"]["minUniqueQueries"] == 3
    assert trace["python"]["values"]["limit"] == 10
    assert trace["openclaw"]["values"]["limit"] == 10
    assert trace["python"]["values"]["maxAgeDays"] == 30
    assert trace["openclaw"]["values"]["maxAgeDays"] == 30
    assert trace["python"]["values"]["enabled"] is False
    assert trace["openclaw"]["values"]["enabled"] is False
    assert trace["python"]["values"]["recencyHalfLifeDays"] == 14


def test_build_configured_deep_policy_trace_matches_openclaw_config():
    trace = build_configured_deep_policy_trace(FakeOracle())

    assert trace["id"] == "configured-deep-policy"
    assert trace["diff"]["status"] == "match"
    assert trace["python"]["values"] == {
        "minScore": 0.72,
        "minRecallCount": 4,
        "minUniqueQueries": 2,
        "maxAgeDays": 14,
        "enabled": True,
        "limit": 7,
        "recencyHalfLifeDays": 10,
    }
    assert trace["openclaw"]["values"] == trace["python"]["values"]


def test_build_deep_policy_trace_returns_error_when_oracle_raises():
    trace = build_deep_policy_trace(ExplodingOracle())

    assert trace["id"] == "deep-policy"
    assert trace["openclaw"]["decision"] == "error"
    assert trace["diff"]["status"] == "error"
    assert "oracle exploded" in trace["openclaw"]["reasons"]
    assert any("oracle exploded" in str(detail) for detail in trace["diff"]["details"])


def test_build_deep_policy_trace_returns_error_for_invalid_oracle_result():
    trace = build_deep_policy_trace(MalformedSuccessOracle())

    assert trace["openclaw"]["decision"] == "error"
    assert trace["diff"]["status"] == "error"
    assert "invalid oracle result" in trace["openclaw"]["reasons"]
    assert any("invalid oracle result" in str(detail) for detail in trace["diff"]["details"])


def test_build_parity_trace_includes_recall_tracking_step():
    trace = build_parity_trace(FakeOracle())

    ids = [step["id"] for step in trace["steps"]]

    assert "recall-tracking" in ids
    assert "configured-deep-policy" in ids
    assert "repeated-recall-tracking" in ids


def test_build_recall_tracking_trace_exposes_matching_recorded_file_values():
    trace = build_recall_tracking_trace(FakeOracle())

    assert trace["id"] == "recall-tracking"
    assert trace["diff"]["status"] == "match"
    assert trace["python"]["decision"] == "recordable"
    assert trace["openclaw"]["decision"] == "recorded"
    assert trace["python"]["values"]["file"] == RECALL_STORE_PATH
    assert trace["openclaw"]["values"]["file"] == RECALL_STORE_PATH
    assert trace["python"]["values"]["entryCount"] == 1
    assert trace["openclaw"]["values"]["entryCount"] == 1
    assert trace["python"]["values"]["entries"] == trace["openclaw"]["values"]["entries"]


def test_build_repeated_recall_tracking_trace_matches_oracle_sequence():
    trace = build_repeated_recall_tracking_trace(FakeOracle())

    assert trace["id"] == "repeated-recall-tracking"
    assert trace["diff"]["status"] == "match"
    assert trace["python"]["values"]["entryCount"] == 1
    entry = trace["python"]["values"]["entries"]["memory:memory/2026-05-26.md:3:3"]
    assert entry["recallCount"] == 2
    assert entry["queryHashes"] == ["aa5368a7c7bd", "1da206d81a95"]
    assert entry["recallDays"] == ["2026-05-26", "2026-05-27"]
    assert trace["python"]["values"]["entries"] == trace["openclaw"]["values"]["entries"]


def test_build_recall_tracking_trace_reports_mismatch_when_oracle_records_nothing():
    trace = build_recall_tracking_trace(NoOpRecallOracle())

    assert trace["diff"]["status"] == "mismatch"
    assert trace["python"]["values"]["entryCount"] == 1
    assert trace["openclaw"]["values"]["entryCount"] == 0


def test_build_recall_tracking_trace_returns_error_for_invalid_oracle_result():
    trace = build_recall_tracking_trace(MalformedRecallOracle())

    assert trace["openclaw"]["decision"] == "error"
    assert trace["diff"]["status"] == "error"
    assert "invalid oracle result" in trace["openclaw"]["reasons"]
    assert any("invalid oracle result" in str(detail) for detail in trace["diff"]["details"])


def test_build_recall_tracking_trace_returns_error_when_oracle_raises():
    trace = build_recall_tracking_trace(ExplodingRecallOracle())

    assert trace["openclaw"]["decision"] == "error"
    assert trace["diff"]["status"] == "error"
    assert "recall oracle exploded" in trace["openclaw"]["reasons"]
    assert any("recall oracle exploded" in str(detail) for detail in trace["diff"]["details"])
