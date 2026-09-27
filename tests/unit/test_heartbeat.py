"""Offline tests for memory_core.heartbeat (v2026.9.6 shape: monitor scratch, NO_REPLY).

Expected values come from upstream tests at pin 4c42815348 (src/auto-reply/heartbeat.test.ts,
src/cli/cli-utils.test.ts) and at v2026.9.6 (src/auto-reply/tokens.test.ts,
src/infra/heartbeat-runner.returns-default-unset.test.ts,
src/infra/heartbeat-runner.tool-response.test.ts); the oracle suite compares the same inputs
against the real TypeScript functions.
"""

import pytest

from memory_core import heartbeat
from memory_core.heartbeat_scratch import HeartbeatScratch, HeartbeatScratchState
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY


def test_heartbeat_constants_are_upstream_verbatim():
    assert heartbeat.HEARTBEAT_TOKEN == "HEARTBEAT_OK"
    assert heartbeat.SILENT_REPLY_TOKEN == "NO_REPLY"
    assert heartbeat.HEARTBEAT_PROMPT == (
        "Follow the heartbeat monitor scratch context when provided. Recurring tasks are "
        "automations; create or change their schedules with the automations tool, not heartbeat "
        "scratch. Do not infer or repeat old tasks from prior chats. If nothing needs attention, "
        "reply NO_REPLY."
    )
    assert heartbeat.HEARTBEAT_RESPONSE_TOOL_PROMPT.endswith(
        f"{heartbeat.HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS} "
        f"{heartbeat.HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS}"
    )
    assert heartbeat.DEFAULT_HEARTBEAT_EVERY == "30m"
    assert heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS == 300


def test_heartbeat_transcript_prompt_brand_follows_runtime_identity():
    assert heartbeat.HEARTBEAT_TRANSCRIPT_PROMPT == "[memory-core heartbeat poll]"
    assert MEMORY_CORE_RUNTIME_IDENTITY.heartbeat_transcript_prompt == "[memory-core heartbeat poll]"
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.heartbeat_transcript_prompt == (
        "[OpenClaw heartbeat poll]"
    )
    assert MEMORY_CORE_RUNTIME_IDENTITY.internal_wake_transcript_prompts == ("[memory-core heartbeat poll]",)
    assert "[OpenClaw cron wake]" in OPENCLAW_COMPAT_RUNTIME_IDENTITY.internal_wake_transcript_prompts


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, False),
        ("", True),
        ("   ", True),
        ("\n\n\n", True),
        ("\t\t", True),
        ("# HEARTBEAT.md\n\n", True),
        ("# Header\n# Another comment", True),
        ("<!--\nHeartbeat template.\nKeep this comment-only file quiet.\n-->", True),
        ("<!--\ntasks:\n  - name: inbox\n    interval: 30m\n    prompt: Check inbox\n-->", True),
        ("<!-- One --> <!-- Two -->", True),
        ("<!-- One -->\n# Header", True),
        ("Reminder <!-- not scaffolding -->", False),
        (
            "```markdown\n# Keep this file empty when you want to skip.\n\n- Check email\n```\n",
            False,
        ),
        ("```markdown\nKeep this file empty unless you want a tiny checklist.\n```\n", False),
        ("- Check email", False),
        ("# HEARTBEAT.md\n## Tasks\nCheck the server logs\n", False),
        ("#TODO", False),
    ],
)
def test_is_heartbeat_content_effectively_empty(content, expected):
    assert heartbeat.is_heartbeat_content_effectively_empty(content) is expected


def test_is_heartbeat_content_effectively_empty_uses_javascript_whitespace():
    # U+00A0 and U+FEFF are JavaScript whitespace (String.prototype.trim);
    # U+001C is Python whitespace but not JavaScript whitespace.
    assert heartbeat.is_heartbeat_content_effectively_empty(" ﻿") is True
    assert heartbeat.is_heartbeat_content_effectively_empty("\u001c") is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10000", 10_000),
        ("10s", 10_000),
        ("1m", 60_000),
        ("2h", 7_200_000),
        ("2d", 172_800_000),
        ("0.5s", 500),
        ("1h30m", 5_400_000),
        ("2m500ms", 120_500),
    ],
)
def test_parse_duration_ms(raw, expected):
    assert heartbeat.parse_duration_ms(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("1h30", 'Invalid duration: "1h30".'),
        ("1h-30m", 'Invalid duration (each composite segment needs a unit): "1h-30m".'),
        ("9007199254740993ms", 'Invalid duration: "9007199254740993ms".'),
        ("9007199254740990ms10ms", 'Invalid duration: "9007199254740990ms10ms".'),
        ("  ", "Invalid duration (empty): empty value."),
    ],
)
def test_parse_duration_ms_rejects_invalid_values(raw, message):
    with pytest.raises(ValueError) as error:
        heartbeat.parse_duration_ms(raw)
    assert str(error.value) == f"{message} Use values like 500ms, 30s, 5m, 2h, or 1h30m."


def test_parse_duration_ms_default_unit_applies_to_bare_numbers_only():
    assert heartbeat.parse_duration_ms("5", default_unit="m") == 300_000
    assert heartbeat.parse_duration_ms("5s", default_unit="m") == 5_000


def test_parse_duration_ms_rounds_halves_up():
    assert heartbeat.parse_duration_ms("0.0015s") == 2
    assert heartbeat.parse_duration_ms("2.5") == 3


@pytest.mark.parametrize(
    ("every", "expected"),
    [
        (None, 30 * 60_000),
        ("0m", None),
        ("oops", None),
        ("5m", 5 * 60_000),
        ("5", 5 * 60_000),
        ("2h", 2 * 60 * 60_000),
        ("", None),
    ],
)
def test_resolve_heartbeat_interval_ms(every, expected):
    assert heartbeat.resolve_heartbeat_interval_ms(every) == expected


def test_resolve_heartbeat_prompts():
    assert heartbeat.resolve_heartbeat_prompt(None) == heartbeat.HEARTBEAT_PROMPT
    assert heartbeat.resolve_heartbeat_prompt("  Check the queue.  ") == "Check the queue."
    assert (
        heartbeat.resolve_heartbeat_prompt_for_response_tool()
        == heartbeat.HEARTBEAT_RESPONSE_TOOL_PROMPT
    )
    custom = heartbeat.resolve_heartbeat_prompt_for_response_tool(
        "Check the deployment queue and only interrupt the user for blockers."
    )
    assert custom == (
        "Check the deployment queue and only interrupt the user for blockers.\n\n"
        + heartbeat.HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS
        + "\n\n"
        + heartbeat.HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS
    )
    assert heartbeat.resolve_heartbeat_prompt_for_response_tool(custom) == custom


def _strip(text, **kwargs):
    result = heartbeat.strip_heartbeat_token(text, **kwargs)
    return (result.should_skip, result.text, result.did_strip)


def test_strip_heartbeat_token_skips_empty_and_token_only_replies():
    assert _strip(None, mode="heartbeat") == (True, "", False)
    assert _strip("  ", mode="heartbeat") == (True, "", False)
    assert _strip("HEARTBEAT_OK", mode="heartbeat") == (True, "", True)
    assert _strip("HEARTBEAT_OK 🦞", mode="heartbeat") == (True, "", True)


def test_strip_heartbeat_token_heartbeat_mode_ack_limit():
    assert _strip("ALERT HEARTBEAT_OK", mode="heartbeat") == (True, "", True)
    long = "A" * (heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS + 1)
    assert _strip(f"{long} HEARTBEAT_OK", mode="heartbeat") == (False, long, True)
    assert _strip("ALERT HEARTBEAT_OK", mode="heartbeat", max_ack_chars=0) == (
        False,
        "ALERT",
        True,
    )
    assert _strip("ALERT HEARTBEAT_OK", mode="heartbeat", max_ack_chars=" 5 ") == (True, "", True)
    assert _strip("ALERT HEARTBEAT_OK", mode="heartbeat", max_ack_chars="") == (
        False,
        "ALERT",
        True,
    )


def test_strip_heartbeat_token_counts_utf16_units():
    # Each 🦞 is two UTF-16 units, as in JavaScript String.length.
    assert _strip("🦞🦞 HEARTBEAT_OK", mode="heartbeat", max_ack_chars=3) == (False, "🦞🦞", True)
    assert _strip("🦞🦞 HEARTBEAT_OK", mode="heartbeat", max_ack_chars=4) == (True, "", True)
    assert _strip("x HEARTBEAT_OK🦞🦞", mode="message") == (False, "x🦞🦞", True)
    assert _strip("x HEARTBEAT_OK🦞🦞🦞", mode="message") == (
        False,
        "x HEARTBEAT_OK🦞🦞🦞",
        False,
    )


def test_strip_heartbeat_token_message_mode_edges_and_wrappers():
    assert _strip("HEARTBEAT_OK hello", mode="message") == (False, "hello", True)
    assert _strip("hello HEARTBEAT_OK") == (False, "hello", True)
    assert _strip("hello HEARTBEAT_OK there", mode="message") == (
        False,
        "hello HEARTBEAT_OK there",
        False,
    )
    assert _strip("<b>HEARTBEAT_OK</b>", mode="heartbeat") == (True, "", True)
    assert _strip("**HEARTBEAT_OK**", mode="heartbeat") == (True, "", True)
    assert _strip("<code>HEARTBEAT_OK</code> all good", mode="message") == (
        False,
        "all good",
        True,
    )
    assert _strip("I should not respond HEARTBEAT_OK.", mode="message") == (
        False,
        "I should not respond.",
        True,
    )
    assert _strip("All clear. HEARTBEAT_OK", mode="message") == (False, "All clear.", True)
    assert _strip("Alert: disk full", mode="heartbeat") == (False, "Alert: disk full", False)


NOW_MS = 1_790_416_800_000  # 2026-09-26T10:00:00Z
ACTIONABLE = "# Heartbeat scratch\n\n- Check server logs\n- Review pending PRs\n"


def _state(content):
    return HeartbeatScratchState(1, HeartbeatScratch(content, 1, 0))


def test_turn_follows_actionable_scratch_and_never_mentions_heartbeat_md():
    turn = heartbeat.prepare_heartbeat_turn(now_ms=NOW_MS, scratch=_state(ACTIONABLE))
    assert turn.skip_reason is None
    assert turn.prompt == (
        f"{heartbeat.HEARTBEAT_PROMPT}\n\nHeartbeat monitor scratch:\n"
        "# Heartbeat scratch\n\n- Check server logs\n- Review pending PRs"
    )
    assert turn.message == (
        f"{turn.prompt}\nCurrent time: Saturday, September 26th, 2026 - 10:00 (UTC)\n"
        "Reference UTC: 2026-09-26 10:00 UTC"
    )
    assert "HEARTBEAT.md" not in turn.message
    assert turn.scratch_revision == 1


@pytest.mark.parametrize("content", ["# Heartbeat scratch\n\n## Tasks\n\n", "", "<!-- quiet -->"])
def test_effectively_empty_scratch_skips_without_a_prompt(content):
    turn = heartbeat.prepare_heartbeat_turn(now_ms=NOW_MS, scratch=_state(content))
    assert (turn.skip_reason, turn.prompt, turn.message) == ("empty-heartbeat-file", None, None)


@pytest.mark.parametrize("scratch", [None, HeartbeatScratchState(), HeartbeatScratchState(2)])
def test_missing_or_unset_scratch_runs_the_generic_prompt(scratch):
    turn = heartbeat.prepare_heartbeat_turn(now_ms=NOW_MS, scratch=scratch)
    assert turn.skip_reason is None and turn.prompt == heartbeat.HEARTBEAT_PROMPT


def test_due_tasks_run_even_with_empty_scratch_and_are_sorted_by_job_id():
    tasks = [
        heartbeat.HeartbeatScheduledTask("job-b", "calendar", "Check calendar changes"),
        heartbeat.HeartbeatScheduledTask("job-a", "inbox", "Check urgent inbox items"),
    ]
    turn = heartbeat.prepare_heartbeat_turn(
        now_ms=NOW_MS, scratch=_state("# Heartbeat scratch\n"), scheduled_tasks=tasks
    )
    assert turn.prompt == (
        "Run the following periodic tasks (only those due based on their intervals):\n\n"
        "- inbox: Check urgent inbox items\n- calendar: Check calendar changes\n\n"
        "After completing all due tasks, reply NO_REPLY.\n\n"
        "Heartbeat monitor scratch:\n# Heartbeat scratch"
    )
    tool = heartbeat.build_heartbeat_run_prompt(scheduled_tasks=tasks[:1], use_response_tool=True)
    assert tool.endswith(
        f"After completing all due tasks:\n{heartbeat.HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS}"
    )


@pytest.mark.parametrize(
    ("source", "reason"),
    [("hook", "wake"), (None, "wake"), ("cron", "cron:job-1"), ("background-task", None)],
)
def test_wake_payloads_and_cron_wakes_bypass_the_scratch(source, reason):
    turn = heartbeat.prepare_heartbeat_turn(
        now_ms=NOW_MS, scratch=_state("# Heartbeat scratch\n"), source=source, reason=reason
    )
    assert turn.skip_reason is None
    assert turn.prompt == heartbeat.HEARTBEAT_PROMPT and turn.scratch_content is None


def test_exec_wake_without_pending_events_is_skipped():
    turn = heartbeat.prepare_heartbeat_turn(
        now_ms=NOW_MS, scratch=_state(ACTIONABLE), source="exec-event"
    )
    assert turn.skip_reason == "no-pending-event"


def test_scratch_already_in_a_custom_prompt_is_not_repeated():
    assert heartbeat.build_heartbeat_run_prompt(
        scratch_content="Check the server logs", prompt="Check the server logs"
    ) == "Check the server logs"


def test_message_normalizes_carriage_returns_like_the_inbound_context():
    turn = heartbeat.prepare_heartbeat_turn(now_ms=NOW_MS, scratch=_state("a\r\nb\rc"))
    assert "\r" not in turn.message and "a\nb\nc" in turn.message
    assert "a\r\nb" in turn.prompt


@pytest.mark.parametrize(
    "text",
    [
        "NO_REPLY",
        "  no_reply \t No_RePlY  ",
        "*NO_REPLY*",
        "\u00abNO_REPLY\u00bb",
        '{"action": "NO_REPLY"}',
        '"NO_REPLY"',
        "<think>internal reasoning</think>\nI will stay quiet here.NO_REPLY",
        "think\ninternal reasoning\nNO_REPLY",
    ],
)
def test_silent_replies_are_recognised(text):
    assert heartbeat.is_silent_reply_payload_text(text)
    assert heartbeat.decide_heartbeat_reply(text).to_json() == {
        "kind": "ack",
        "eventStatus": "ok-token",
        "silent": False,
    }


@pytest.mark.parametrize(
    "text",
    [
        "Here is a helpful response.\n\nNO_REPLY",
        "NO_REPLY but here is more content",
        "\U0001f4acNO_REPLY",
        "think\nHere is the actual answer.\nNO_REPLY",
        "<think>internal reasoning</think>\nYou should not reply to that email.\nNO_REPLY",
    ],
)
def test_substantive_replies_are_not_silent(text):
    assert not heartbeat.is_silent_reply_payload_text(text)


def test_reply_decision_keeps_the_legacy_ack_and_notify_false_rules():
    decide = heartbeat.decide_heartbeat_reply
    assert decide(None).to_json() == {"kind": "ack", "eventStatus": "ok-empty", "silent": False}
    assert decide("HEARTBEAT_OK").deliver is False
    assert decide("All good. HEARTBEAT_OK").deliver is False
    long = "A" * (heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS + 1)
    assert decide(f"{long} HEARTBEAT_OK").to_json() == {
        "kind": "delivery",
        "text": long,
        "silent": False,
    }
    assert decide("Alert: disk full").to_json() == {
        "kind": "delivery",
        "text": "Alert: disk full",
        "silent": False,
    }
    assert decide("No interruption needed.\n\nnotify=false").to_json() == {
        "kind": "delivery",
        "text": "No interruption needed.",
        "silent": True,
    }
    assert decide("notify=false\r\n").to_json() == {
        "kind": "ack",
        "eventStatus": "ok-token",
        "silent": True,
    }
    assert decide("The literal notify=false flag is documented.").deliver is True
    assert decide("[assistant turn failed before producing content]").deliver is False
    assert decide("Ops: disk full", response_prefix="Ops:").text == "Ops: disk full"
    assert decide("Ops: HEARTBEAT_OK", response_prefix="Ops:").deliver is False


def test_is_heartbeat_user_message_matches_heartbeat_prompts():
    hinted = (
        f"{heartbeat.HEARTBEAT_PROMPT}\nWhen reading HEARTBEAT.md, use workspace file "
        "/tmp/HEARTBEAT.md (exact case). Do not read docs/heartbeat.md."
    )
    assert heartbeat.is_heartbeat_user_message(
        {"role": "user", "content": hinted}, heartbeat.HEARTBEAT_PROMPT
    )
    assert heartbeat.is_heartbeat_user_message(
        {
            "role": "user",
            "content": "Run the following periodic tasks (only those due based on their "
            "intervals):\n\n- email-check: Check for urgent unread emails\n\nAfter completing "
            "all due tasks, reply HEARTBEAT_OK.",
        }
    )
    assert heartbeat.is_heartbeat_user_message(
        {"role": "user", "content": heartbeat.HEARTBEAT_RESPONSE_TOOL_PROMPT}
    )
    custom = heartbeat.resolve_heartbeat_prompt_for_response_tool("Check the handoff queue.")
    assert heartbeat.is_heartbeat_user_message(
        {"role": "user", "content": f"{custom}\n\nUse workspace notes only."},
        "Check the handoff queue.",
    )


def test_is_heartbeat_user_message_ignores_quoted_or_non_user_mentions():
    assert not heartbeat.is_heartbeat_user_message(
        {"role": "user", "content": "Please reply HEARTBEAT_OK so I can test something."}
    )
    assert not heartbeat.is_heartbeat_user_message({"role": "assistant", "content": "HEARTBEAT_OK"})


def test_is_heartbeat_user_message_transcript_row_follows_runtime_identity():
    memory_core_row = {"role": "user", "content": "[memory-core heartbeat poll]"}
    compat_row = {"role": "user", "content": "[OpenClaw heartbeat poll]"}
    assert heartbeat.is_heartbeat_user_message(memory_core_row)
    assert not heartbeat.is_heartbeat_user_message(compat_row)
    assert heartbeat.is_heartbeat_user_message(
        compat_row, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )
    hinted_row = {
        "role": "user",
        "content": [
            {"type": "text", "text": heartbeat.MESSAGE_TOOL_DELIVERY_HINTS[0]},
            {"type": "input_text", "text": "\n\n[memory-core heartbeat poll]"},
        ],
    }
    assert heartbeat.is_heartbeat_user_message(hinted_row)


def test_is_heartbeat_user_message_matches_v2026_9_6_task_prompts_and_wake_rows():
    task = heartbeat.HeartbeatScheduledTask("job-1", "inbox", "Check inbox")
    for prompt in (
        heartbeat.build_heartbeat_run_prompt(scheduled_tasks=[task]),
        heartbeat.build_heartbeat_run_prompt(scheduled_tasks=[task], use_response_tool=True),
    ):
        assert heartbeat.is_heartbeat_user_message({"role": "user", "content": prompt})
    scratch_prompt = heartbeat.build_heartbeat_run_prompt(scratch_content="- Check logs")
    assert heartbeat.is_heartbeat_user_message(
        {"role": "user", "content": scratch_prompt}, heartbeat.HEARTBEAT_PROMPT
    )
    cron_row = {"role": "user", "content": "[OpenClaw cron wake]"}
    assert not heartbeat.is_heartbeat_user_message(cron_row)
    assert heartbeat.is_heartbeat_user_message(
        cron_row, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )
