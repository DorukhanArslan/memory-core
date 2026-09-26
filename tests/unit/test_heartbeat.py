"""Offline tests for memory_core.heartbeat.

Expected values come from upstream tests at pin 4c42815348
(src/auto-reply/heartbeat.test.ts, src/cli/cli-utils.test.ts,
src/infra/heartbeat-runner.returns-default-unset.test.ts); the oracle suite
compares the same inputs against the real TypeScript functions.
"""

import pytest

from memory_core import heartbeat
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY


def test_heartbeat_constants_are_upstream_verbatim():
    assert heartbeat.HEARTBEAT_TOKEN == "HEARTBEAT_OK"
    assert heartbeat.HEARTBEAT_PROMPT == (
        "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly. Do not infer or "
        "repeat old tasks from prior chats. If nothing needs attention, reply HEARTBEAT_OK."
    )
    assert heartbeat.HEARTBEAT_RESPONSE_TOOL_PROMPT.endswith(
        heartbeat.HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS
    )
    assert heartbeat.DEFAULT_HEARTBEAT_EVERY == "30m"
    assert heartbeat.DEFAULT_HEARTBEAT_ACK_MAX_CHARS == 300


def test_heartbeat_transcript_prompt_brand_follows_runtime_identity():
    assert heartbeat.HEARTBEAT_TRANSCRIPT_PROMPT == "[memory-core heartbeat poll]"
    assert MEMORY_CORE_RUNTIME_IDENTITY.heartbeat_transcript_prompt == "[memory-core heartbeat poll]"
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.heartbeat_transcript_prompt == (
        "[OpenClaw heartbeat poll]"
    )


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
        ("```markdown\n# Keep this file empty when you want to skip.\n\n- Check email\n```\n", False),
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


def test_parse_heartbeat_tasks_does_not_bleed_top_level_fields():
    content = (
        "tasks:\n  - name: email-check\n    interval: 30m\n    prompt: Check for urgent emails\n"
        "interval: should-not-bleed\n"
    )
    assert heartbeat.parse_heartbeat_tasks(content) == [
        heartbeat.HeartbeatTask("email-check", "30m", "Check for urgent emails")
    ]


def test_parse_heartbeat_tasks_ignores_commented_blocks_and_incomplete_entries():
    assert heartbeat.parse_heartbeat_tasks(
        "<!--\ntasks:\n  - name: inbox\n    interval: 30m\n    prompt: Check inbox\n-->\n"
    ) == []
    assert heartbeat.parse_heartbeat_tasks(
        "tasks:\n  - name: inbox\n    prompt: Check inbox\n"
    ) == []


def test_parse_heartbeat_tasks_strips_one_pair_of_edge_quotes():
    content = 'tasks:\n  - name: "email-check"\n    interval: \'30m\'\n    prompt: "Check"\n'
    assert heartbeat.parse_heartbeat_tasks(content) == [
        heartbeat.HeartbeatTask("email-check", "30m", "Check")
    ]


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


def test_is_task_due():
    assert heartbeat.is_task_due(None, "30m", 0) is True
    assert heartbeat.is_task_due(0, "5m", 300_000) is True
    assert heartbeat.is_task_due(1, "5m", 300_000) is False
    assert heartbeat.is_task_due(0, "5", 300_000) is True
    assert heartbeat.is_task_due(0, "oops", 10**12) is False


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
    )
    assert heartbeat.resolve_heartbeat_prompt_for_response_tool(custom) == custom
