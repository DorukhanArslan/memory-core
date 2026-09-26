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


TASKS_CONTEXT_FILE = """# Keep this header

Remember escalation policy.

tasks:
  - name: inbox
    interval: 5m
    prompt: Check urgent inbox items

  - name: calendar
    interval: 5m
    prompt: Check calendar changes

Some global directive after tasks.

- Keep this top-level directive too.
"""
NOW_MS = 1_790_416_800_000


def _workspace(tmp_path, content):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (tmp_path / "HEARTBEAT.md").write_text(content, encoding="utf-8")
    return tmp_path


def test_prepare_heartbeat_turn_lists_due_tasks_and_keeps_other_directives(tmp_path):
    workspace = _workspace(tmp_path, TASKS_CONTEXT_FILE)

    turn = heartbeat.prepare_heartbeat_turn(
        workspace, now_ms=NOW_MS, task_state={"inbox": NOW_MS - 60_000}
    )

    assert turn.skip_reason is None
    assert [task.name for task in turn.due_tasks] == ["calendar"]
    assert turn.prompt == (
        "Run the following periodic tasks (only those due based on their intervals):\n\n"
        "- calendar: Check calendar changes\n\n"
        "After completing all due tasks, reply HEARTBEAT_OK.\n\n"
        "Additional context from HEARTBEAT.md:\n"
        "# Keep this header\n\nRemember escalation policy.\n\n"
        "Some global directive after tasks.\n\n- Keep this top-level directive too."
    )
    assert turn.next_task_state({"inbox": NOW_MS - 60_000, "stale": 1}) == {
        "inbox": NOW_MS - 60_000,
        "stale": 1,
        "calendar": NOW_MS,
    }


def test_prepare_heartbeat_turn_skips_when_no_task_is_due(tmp_path):
    workspace = _workspace(tmp_path, TASKS_CONTEXT_FILE)
    state = {"inbox": NOW_MS - 1, "calendar": NOW_MS - 1}

    turn = heartbeat.prepare_heartbeat_turn(workspace, now_ms=NOW_MS, task_state=state)

    assert turn.skip_reason == heartbeat.HEARTBEAT_SKIP_NO_TASKS_DUE == "no-tasks-due"
    assert turn.prompt is None
    assert turn.next_task_state(state) == state


@pytest.mark.parametrize(
    "content",
    [
        "# HEARTBEAT.md\n\n## Tasks\n\n",
        "# Keep this file empty (or with only comments) to skip heartbeat API calls.\n",
    ],
)
def test_prepare_heartbeat_turn_skips_effectively_empty_file(tmp_path, content):
    turn = heartbeat.prepare_heartbeat_turn(_workspace(tmp_path, content), now_ms=NOW_MS)

    assert turn.skip_reason == heartbeat.HEARTBEAT_SKIP_EMPTY_FILE == "empty-heartbeat-file"
    assert turn.prompt is None


def test_prepare_heartbeat_turn_base_prompt_gets_path_hint_and_directives(tmp_path):
    workspace = _workspace(tmp_path, "# HEARTBEAT.md\n\n- Check server logs\n")

    turn = heartbeat.prepare_heartbeat_turn(workspace, now_ms=NOW_MS)

    assert turn.prompt == (
        f"{heartbeat.HEARTBEAT_PROMPT}\n"
        f"When reading HEARTBEAT.md, use workspace file {workspace}/HEARTBEAT.md (exact case). "
        "Do not read docs/heartbeat.md.\n\n"
        "Additional context from HEARTBEAT.md:\n# HEARTBEAT.md\n\n- Check server logs"
    )
    assert turn.next_task_state(None) is None


def test_prepare_heartbeat_turn_runs_without_a_readable_file(tmp_path):
    missing = heartbeat.prepare_heartbeat_turn(_workspace(tmp_path / "a", None), now_ms=NOW_MS)
    directory = _workspace(tmp_path / "b", None)
    (directory / "HEARTBEAT.md").mkdir()
    unreadable = heartbeat.prepare_heartbeat_turn(directory, now_ms=NOW_MS)

    for turn in (missing, unreadable):
        assert turn.skip_reason is None
        assert turn.prompt.startswith(f"{heartbeat.HEARTBEAT_PROMPT}\nWhen reading HEARTBEAT.md")
        assert "Additional context" not in turn.prompt


def test_prepare_heartbeat_turn_bypass_ignores_the_file(tmp_path):
    workspace = _workspace(tmp_path, "# HEARTBEAT.md\n\n## Tasks\n\n")

    turn = heartbeat.prepare_heartbeat_turn(workspace, now_ms=NOW_MS, bypass_file_gates=True)

    assert turn.skip_reason is None
    assert "Additional context" not in turn.prompt


def test_prepare_heartbeat_turn_response_tool_wording(tmp_path):
    workspace = _workspace(tmp_path, TASKS_CONTEXT_FILE)

    turn = heartbeat.prepare_heartbeat_turn(workspace, now_ms=NOW_MS, use_response_tool=True)

    assert turn.uses_response_tool is True
    assert heartbeat.HEARTBEAT_TASKS_RESPONSE_TOOL_COMPLETION_INSTRUCTION in turn.prompt
    assert heartbeat.HEARTBEAT_TASKS_COMPLETION_INSTRUCTION not in turn.prompt


def test_custom_prompt_gets_hint_only_when_it_mentions_heartbeat_md(tmp_path):
    workspace = str(tmp_path)
    assert (
        heartbeat.build_heartbeat_prompt(workspace_dir=workspace, prompt="Check the handoff queue.")
        == "Check the handoff queue."
    )
    hinted = heartbeat.build_heartbeat_prompt(
        workspace_dir=workspace, prompt="Read heartbeat.md and check the handoff queue."
    )
    assert hinted.endswith(
        f"use workspace file {workspace}/HEARTBEAT.md (exact case). Do not read docs/heartbeat.md."
    )


def test_path_hint_uses_node_path_join_normalization():
    hinted = heartbeat.append_heartbeat_workspace_path_hint("heartbeat.md", "//srv/./agent/../w/")
    assert "use workspace file /srv/w/HEARTBEAT.md (exact case)" in hinted
    assert heartbeat.append_heartbeat_workspace_path_hint(hinted, "//srv/w") == hinted


def test_file_directives_are_not_repeated():
    assert (
        heartbeat.append_heartbeat_file_directives("Check the server logs", "Check the server logs")
        == "Check the server logs"
    )
    assert heartbeat.append_heartbeat_file_directives("p", "tasks:\n  - name: a\n") == "p"


def test_strip_heartbeat_tasks_block_handles_crlf_and_unindented_entries():
    content = "# Header\r\ntasks:\r\n- name: inbox\r\n  interval: 5m\r\n\r\n- Keep this.\r\n"
    assert heartbeat.strip_heartbeat_tasks_block(content) == "# Header\n- Keep this.\n"


def test_task_named_like_an_object_prototype_key_is_never_due_once_state_exists():
    task = heartbeat.HeartbeatTask("constructor", "5m", "Check")
    assert heartbeat.resolve_due_heartbeat_tasks([task], None, NOW_MS) == [task]
    assert heartbeat.resolve_due_heartbeat_tasks([task], {}, NOW_MS) == []
    assert heartbeat.resolve_due_heartbeat_tasks([task], {"constructor": 0}, NOW_MS) == [task]


def test_update_heartbeat_task_state_ignores_a_new_proto_key():
    task = heartbeat.HeartbeatTask("__proto__", "5m", "Check")
    assert heartbeat.update_heartbeat_task_state(None, [task], [task], NOW_MS) == {}


def test_heartbeat_system_section_only_for_heartbeat_triggers():
    assert heartbeat.resolve_heartbeat_prompt_for_system_prompt(trigger="heartbeat") == (
        heartbeat.HEARTBEAT_PROMPT
    )
    assert heartbeat.resolve_heartbeat_prompt_for_system_prompt(trigger="user") is None
    assert (
        heartbeat.resolve_heartbeat_prompt_for_system_prompt(
            trigger="heartbeat", run_kind="commitment-only"
        )
        is None
    )
    assert (
        heartbeat.resolve_heartbeat_prompt_for_system_prompt(trigger="heartbeat", every="0m")
        is None
    )
    assert (
        heartbeat.resolve_heartbeat_prompt_for_system_prompt(
            trigger="heartbeat", include_system_prompt_section=False
        )
        is None
    )


def test_build_heartbeat_section_lines():
    assert heartbeat.build_heartbeat_section_lines(heartbeat.HEARTBEAT_PROMPT) == [
        "## Heartbeats",
        "If the current user message is a heartbeat poll and nothing needs attention, reply "
        "exactly:",
        "HEARTBEAT_OK",
        'If something needs attention, do NOT include "HEARTBEAT_OK"; reply with the alert text '
        "instead.",
        "",
    ]
    assert heartbeat.build_heartbeat_section_lines(None) == []
    assert heartbeat.build_heartbeat_section_lines("   ") == []
    assert heartbeat.build_heartbeat_section_lines("x", is_minimal=True) == []
