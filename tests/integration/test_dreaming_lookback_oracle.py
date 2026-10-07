"""Compare ISO/day phase freshness with the real filter in dreaming-phases.ts."""

import os
from datetime import UTC, datetime
from pathlib import Path

from demo.openclaw_oracle import OpenClawOracle
from memory_core.consolidation.dreaming import filter_recall_entries_within_lookback


def test_dreaming_lookback_matches_openclaw():
    # dreaming-phases.test.ts's stale, fresh-day, historical daily-only and cutoff cases.
    now_ms = int(datetime(2026, 4, 15, 12, tzinfo=UTC).timestamp() * 1000)
    stale = "2026-03-01T00:00:00.000Z"
    entries = [
        {"key": "fresh-day", "lastRecalledAt": stale, "recallDays": ["2026-04-14"]},
        {"key": "bad-timestamp-fresh-day", "lastRecalledAt": "not-a-date", "recallDays": ["2026-04-14"]},
        {"key": "historical-daily", "lastRecalledAt": "2026-04-15T12:00:00.000Z",
         "recallDays": ["2026-04-01"], "recallCount": 0, "dailyCount": 3},
        {"key": "stale-everything", "lastRecalledAt": stale, "recallDays": ["2026-03-02"]},
        {"key": "fresh-time", "lastRecalledAt": "2026-04-14T00:00:00.000Z", "recallDays": []},
        {"key": "invalid", "lastRecalledAt": "not-a-date", "recallDays": ["not-a-day"]},
        {"key": "cutoff-day", "lastRecalledAt": stale, "recallDays": ["2026-04-12"]},
        {"key": "old-day", "lastRecalledAt": stale, "recallDays": ["2026-04-11"]},
        {"key": "exact-cutoff", "lastRecalledAt": "2026-04-12T12:00:00.000Z", "recallDays": []},
        {"key": "before-cutoff", "lastRecalledAt": "2026-04-12T11:59:59.999Z", "recallDays": []},
    ]
    entries = [{"recallCount": 1, "dailyCount": 0, "groundedCount": 0, **row} for row in entries]
    cases = [{"entries": entries, "nowMs": now_ms, "lookbackDays": days} for days in [-1, 0, 0.5, 1, 3, 7]]
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=120)
    response = oracle.run({"operation": "dreamingLookback", "cases": cases})
    assert response["ok"] is True, response
    expected = [filter_recall_entries_within_lookback(
        entries=case["entries"], now_ms=case["nowMs"], lookback_days=case["lookbackDays"],
    ) for case in cases]
    assert response["result"] == expected
