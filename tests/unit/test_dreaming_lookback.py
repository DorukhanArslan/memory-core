"""Freshness cases from dreaming-phases.test.ts filterRecallEntriesWithinLookback."""

from datetime import UTC, datetime

import pytest

from memory_core.consolidation import dreaming

NOW_MS = int(datetime(2026, 4, 15, 12, tzinfo=UTC).timestamp() * 1000)
STALE = "2026-03-01T00:00:00.000Z"


@pytest.mark.parametrize("entry,keep", [
    ({"lastRecalledAt": STALE, "recallDays": ["2026-04-14"]}, True),
    ({"lastRecalledAt": "not-a-date", "recallDays": ["2026-04-14"]}, True),
    ({"lastRecalledAt": "2026-04-15T12:00:00.000Z", "recallDays": ["2026-04-01"],
      "recallCount": 0, "dailyCount": 3}, False),
    ({"lastRecalledAt": STALE, "recallDays": ["2026-03-02"]}, False),
    ({"lastRecalledAt": "2026-04-14T00:00:00.000Z", "recallDays": []}, True),
    ({"lastRecalledAt": "not-a-date", "recallDays": ["not-a-day"]}, False),
    ({"lastRecalledAt": STALE, "recallDays": ["2026-04-12"]}, True),
    ({"lastRecalledAt": STALE, "recallDays": ["2026-04-11"]}, False),
    ({"lastRecalledAt": "2026-04-12T12:00:00.000Z", "recallDays": []}, True),
    ({"lastRecalledAt": "2026-04-12T11:59:59.999Z", "recallDays": []}, False),
])
def test_phase_lookback_uses_source_days_for_daily_only_entries(entry, keep):
    row = {"key": "example", "recallCount": 1, "dailyCount": 0, "groundedCount": 0, **entry}
    result = dreaming.filter_recall_entries_within_lookback(
        entries=[row], now_ms=NOW_MS, lookback_days=3,
    )
    assert result == ([row] if keep else [])


@pytest.mark.parametrize("lookback,keep", [(0, False), (-1, False), (0.5, False), (1, True), (1.5, True)])
def test_zero_negative_and_fractional_lookback(lookback, keep):
    row = {"key": "example", "recallCount": 1, "lastRecalledAt": "2026-04-14T12:00:00.000Z"}
    assert dreaming.filter_recall_entries_within_lookback(
        entries=[row], now_ms=NOW_MS, lookback_days=lookback,
    ) == ([row] if keep else [])
