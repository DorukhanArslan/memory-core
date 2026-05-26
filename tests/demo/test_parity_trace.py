from demo.parity_trace import build_deep_policy_trace, diff_values


class FakeOracle:
    def metadata(self):
        return {"available": True, "commit": "abc123", "repoPath": "/repo"}

    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        return {
            "ok": True,
            "operation": "deepPolicy",
            "result": {
                "minScore": 0.8,
                "minRecallCount": 3,
                "minUniqueQueries": 3,
                "maxAgeDays": 30,
            },
        }


class ExplodingOracle:
    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        raise RuntimeError("oracle exploded")


class MalformedSuccessOracle:
    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        return {"ok": True, "operation": "deepPolicy"}


def test_diff_values_reports_mismatch():
    diff = diff_values({"minScore": 0.75}, {"minScore": 0.8})

    assert diff["status"] == "mismatch"
    assert "minScore: python=0.75 openclaw=0.8" in diff["details"]


def test_build_deep_policy_trace_shows_known_default_mismatch():
    trace = build_deep_policy_trace(FakeOracle())

    assert trace["id"] == "deep-policy"
    assert trace["diff"]["status"] == "mismatch"
    assert trace["python"]["values"]["minScore"] == 0.75
    assert trace["openclaw"]["values"]["minScore"] == 0.8
    assert trace["openclaw"]["values"]["minUniqueQueries"] == 3


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
