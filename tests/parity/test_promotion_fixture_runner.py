from __future__ import annotations

from scripts.parity_promotion_fixture import run_fixture


def test_promotion_fixture_matches_openclaw_core_scoring_gate(tmp_path):
    payload = run_fixture(workspace=tmp_path / "fixture")

    assert payload["scenario"] == "openclaw_core_three_signal_preference"
    assert payload["selected"] is False
    assert payload["top"]["reasons"] == ["score 0.569 < 0.750", "unique queries 2 < 3"]
    assert "durablePreference" not in payload["top"]["components"]
