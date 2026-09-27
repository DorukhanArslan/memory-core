"""One host time format for every Current time line (memory_core.current_time).

Upstream builds the flush prompt's, the heartbeat Body's and the bare reset prompt's
``Current time:`` line with the same ``resolveCronStyleNow`` and one detected host format
(edecdbd05ef #111527). memory-core takes the host's ``time_format`` instead; these tests pin that
the flush plan, the heartbeat turn and the reset prompt format the same instant identically for
the same host setting.
"""

from __future__ import annotations

import pytest

import memory_core.bootstrap.startup as startup
import memory_core.heartbeat as heartbeat
import memory_core.memory_flush as memory_flush
from memory_core import build_memory_flush_plan, prepare_heartbeat_turn
from memory_core.bootstrap import append_cron_style_current_time_line as bootstrap_append
from memory_core.bootstrap import build_bare_session_reset_prompt
from memory_core.current_time import (
    DEFAULT_TIME_FORMAT,
    append_cron_style_current_time_line,
    format_current_time_line,
    resolve_time_format,
)
from memory_core.heartbeat_scratch import HeartbeatScratch, HeartbeatScratchState

PM_MS = 1_790_445_900_000  # 2026-09-26T18:05:00Z (21:05 in Istanbul)
AM_MS = 1_790_388_300_000  # 2026-09-26T02:05:00Z (05:05 in Istanbul)
SCRATCH = HeartbeatScratchState(
    current_revision=1,
    scratch=HeartbeatScratch(content="Check the release queue.", revision=1, updated_at_ms=0),
)


def _flush_line(now_ms: int, timezone: str, time_format: str) -> str:
    plan = build_memory_flush_plan(
        workspace_dir=None, now_ms=now_ms, timezone=timezone, time_format=time_format
    )
    return "\n".join(plan.prompt.split("\n")[-2:])


def _heartbeat_line(now_ms: int, timezone: str, time_format: str) -> str:
    turn = prepare_heartbeat_turn(
        now_ms=now_ms, scratch=SCRATCH, timezone=timezone, time_format=time_format
    )
    assert turn.skip_reason is None and turn.message is not None
    return "\n".join(turn.message.split("\n")[-2:])


def _reset_line(now_ms: int, timezone: str, time_format: str) -> str:
    prompt = build_bare_session_reset_prompt(
        now_ms=now_ms, timezone=timezone, time_format=time_format
    )
    return "\n".join(prompt.split("\n")[-2:])


@pytest.mark.parametrize(
    ("now_ms", "timezone", "time_format", "current_time"),
    [
        (PM_MS, "UTC", "24", "Saturday, September 26th, 2026 - 18:05 (UTC)"),
        (PM_MS, "UTC", "12", "Saturday, September 26th, 2026 - 6:05 PM (UTC)"),
        (PM_MS, "Europe/Istanbul", "24", "Saturday, September 26th, 2026 - 21:05 (Europe/Istanbul)"),
        (PM_MS, "Europe/Istanbul", "12", "Saturday, September 26th, 2026 - 9:05 PM (Europe/Istanbul)"),
        (AM_MS, "+03:00", "12", "Saturday, September 26th, 2026 - 5:05 AM (+03:00)"),
        (AM_MS, "America/New_York", "12", "Friday, September 25th, 2026 - 10:05 PM (America/New_York)"),
    ],
)
def test_flush_heartbeat_and_reset_lines_agree_for_one_host_format(
    now_ms, timezone, time_format, current_time
):
    expected = format_current_time_line(now_ms, timezone, time_format)

    assert expected.split("\n")[0] == f"Current time: {current_time}"
    assert _flush_line(now_ms, timezone, time_format) == expected
    assert _heartbeat_line(now_ms, timezone, time_format) == expected
    assert _reset_line(now_ms, timezone, time_format) == expected


def test_every_path_defaults_to_the_same_24_hour_format():
    expected = format_current_time_line(PM_MS, "UTC", "24")

    assert DEFAULT_TIME_FORMAT == "24"
    assert "\n".join(build_memory_flush_plan(workspace_dir=None, now_ms=PM_MS).prompt.split("\n")[-2:]) == expected
    assert "\n".join(prepare_heartbeat_turn(now_ms=PM_MS, scratch=SCRATCH).message.split("\n")[-2:]) == expected
    assert "\n".join(build_bare_session_reset_prompt(now_ms=PM_MS).split("\n")[-2:]) == expected


@pytest.mark.parametrize("time_format", ["auto", "", "12h", None])
def test_every_path_refuses_a_format_it_would_have_to_detect(time_format):
    with pytest.raises(ValueError, match="time_format must be '12' or '24'"):
        resolve_time_format(time_format)
    with pytest.raises(ValueError, match="time_format must be '12' or '24'"):
        build_memory_flush_plan(workspace_dir=None, now_ms=PM_MS, time_format=time_format)
    with pytest.raises(ValueError, match="time_format must be '12' or '24'"):
        prepare_heartbeat_turn(now_ms=PM_MS, scratch=SCRATCH, time_format=time_format)
    with pytest.raises(ValueError, match="time_format must be '12' or '24'"):
        build_bare_session_reset_prompt(now_ms=PM_MS, time_format=time_format)


def test_one_helper_serves_every_caller():
    # The flush plan, the heartbeat turn and the reset prompt import the same function objects.
    assert memory_flush.format_current_time_line is format_current_time_line
    assert heartbeat.append_cron_style_current_time_line is append_cron_style_current_time_line
    assert startup.append_cron_style_current_time_line is append_cron_style_current_time_line
    assert bootstrap_append is append_cron_style_current_time_line


def test_a_refreshed_block_takes_the_host_format():
    once = append_cron_style_current_time_line("Hello", now_ms=PM_MS, time_format="24")
    refreshed = append_cron_style_current_time_line(once, now_ms=PM_MS, time_format="12")

    assert refreshed == f"Hello\n{format_current_time_line(PM_MS, 'UTC', '12')}"
