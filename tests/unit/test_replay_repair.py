"""memory_core.replay_repair: the tool-call replay repair of OpenClaw v2026.9.6.

Cases follow upstream's src/agents/session-transcript-repair.test.ts where they apply.
"""

from memory_core._transcript_repair_constants import (
    DEFAULT_MISSING_TOOL_RESULT_TEXT,
    SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY,
)
from memory_core.replay_repair import (
    is_synthetic_missing_tool_result,
    repair_tool_use_result_pairing,
    sanitize_tool_use_result_pairing_for_model,
)


def _assistant_tool(*tool_ids: str, stop_reason: str | None = None) -> dict:
    message = {
        "role": "assistant",
        "content": [
            {"type": "toolCall", "id": tool_id, "name": "read", "arguments": {}}
            for tool_id in tool_ids
        ],
    }
    if stop_reason is not None:
        message["stopReason"] = stop_reason
    return message


def _tool_result(tool_id: str, text: str = "ok", tool_name: str = "read") -> dict:
    return {
        "role": "toolResult",
        "toolCallId": tool_id,
        "toolName": tool_name,
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def test_repair_tool_use_result_pairing_moves_displaced_results_before_user_messages():
    messages = [
        _assistant_tool("call_1", "call_2"),
        {"role": "user", "content": "this should come after tool results"},
        _tool_result("call_2"),
    ]

    result = repair_tool_use_result_pairing(messages, missing_tool_result_text="aborted")

    assert [message["role"] for message in result.messages] == [
        "assistant",
        "toolResult",
        "toolResult",
        "user",
    ]
    assert result.messages[1]["toolCallId"] == "call_1"
    assert result.messages[1]["content"] == [{"type": "text", "text": "aborted"}]
    assert result.messages[2]["toolCallId"] == "call_2"
    assert result.added[0]["toolCallId"] == "call_1"
    assert result.moved is True


def test_repair_tool_use_result_pairing_drops_orphan_and_duplicate_results():
    messages = [
        {"role": "user", "content": "hello"},
        _tool_result("orphan"),
        _assistant_tool("call_1"),
        _tool_result("call_1", "first"),
        _tool_result("call_1", "duplicate"),
    ]

    result = repair_tool_use_result_pairing(messages)

    assert [message["role"] for message in result.messages] == ["user", "assistant", "toolResult"]
    assert result.messages[2]["content"] == [{"type": "text", "text": "first"}]
    assert result.dropped_orphan_count == 1
    # v2026.9.6 counts a second result of a call within its frame (the pin-era port gave 0).
    assert result.dropped_duplicate_count == 1
    assert result.discarded == [messages[1], messages[4]]


def test_repair_tool_use_result_pairing_preserves_errored_assistant_without_synthesis():
    messages = [
        _assistant_tool("call_error", stop_reason="error"),
        {"role": "user", "content": "retry"},
    ]

    result = repair_tool_use_result_pairing(messages)

    assert result.messages == messages
    assert result.added == []


def test_repair_tool_use_result_pairing_can_drop_errored_assistant_results():
    messages = [
        _assistant_tool("call_aborted", stop_reason="aborted"),
        _tool_result("call_aborted", "partial"),
        {"role": "user", "content": "retry"},
    ]

    result = repair_tool_use_result_pairing(messages, errored_assistant_result_policy="drop")

    assert result.messages == [{"role": "user", "content": "retry"}]
    assert result.added == []


def _exec_call(tool_id: str, stop_reason: str = "toolUse") -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "toolCall", "id": tool_id, "name": "exec", "arguments": {}}],
        "stopReason": stop_reason,
    }


def _exec_result(tool_id: str, text: str, is_error: bool = False) -> dict:
    return {
        "role": "toolResult",
        "toolCallId": tool_id,
        "toolName": "exec",
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _synthetic(tool_id: str) -> dict:
    return {
        "role": "toolResult",
        "toolCallId": tool_id,
        "toolName": "read",
        "content": [{"type": "text", "text": DEFAULT_MISSING_TOOL_RESULT_TEXT}],
        "isError": True,
    }


def _texts(messages: list[dict]) -> list[str]:
    return [
        next(block["text"] for block in message["content"] if block.get("type") == "text")
        for message in messages
        if message["role"] == "toolResult"
    ]


def test_repeated_provider_ids_pair_by_occurrence():
    across_turns = [
        _exec_call("exec_0"),
        _exec_result("exec_0", "first"),
        {"role": "user", "content": "next"},
        _exec_call("exec_0"),
        _exec_result("exec_0", "second"),
    ]
    within_a_turn = [
        {
            "role": "assistant",
            "content": [
                {"type": "toolCall", "id": "exec_0", "name": "exec", "arguments": {"cmd": "a"}},
                {"type": "toolCall", "id": "exec_0", "name": "exec", "arguments": {"cmd": "b"}},
            ],
            "stopReason": "toolUse",
        },
        _exec_result("exec_0", "first"),
        _exec_result("exec_0", "second"),
    ]

    for messages in (across_turns, within_a_turn):
        result = repair_tool_use_result_pairing(messages)
        assert result.messages is messages
        assert (result.added, result.dropped_duplicate_count, result.moved) == ([], 0, False)
        assert _texts(result.messages) == ["first", "second"]

    # A later turn's adjacent result stays local; the earlier occurrence gets a synthetic one.
    adjacent = repair_tool_use_result_pairing(
        [_exec_call("exec_0"), _exec_call("exec_0"), _exec_result("exec_0", "second")]
    )
    assert _texts(adjacent.messages) == [DEFAULT_MISSING_TOOL_RESULT_TEXT, "second"]

    # A synthesized later occurrence is stable: a second repair changes nothing.
    first = repair_tool_use_result_pairing(
        [
            _exec_call("exec_0"),
            _exec_result("exec_0", "first"),
            {"role": "user", "content": "next"},
            _exec_call("exec_0"),
        ]
    )
    assert [message["role"] for message in first.messages] == [
        "assistant",
        "toolResult",
        "user",
        "assistant",
        "toolResult",
    ]
    assert _texts(first.messages) == ["first", DEFAULT_MISSING_TOOL_RESULT_TEXT]
    assert repair_tool_use_result_pairing(first.messages).messages is first.messages


def test_a_later_real_result_replaces_a_synthetic_one():
    messages = [_assistant_tool("call_1"), _synthetic("call_1"), _tool_result("call_1", "real")]

    result = repair_tool_use_result_pairing(messages)

    assert _texts(result.messages) == ["real"]
    assert result.discarded == [messages[1]]
    # Across a frame: the late real result replaces the earlier synthetic one.
    across = [
        _assistant_tool("call_1"),
        _synthetic("call_1"),
        {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": "call_2", "name": "write", "arguments": {}}],
        },
        _tool_result("call_1", "real"),
        _tool_result("call_2", "second output", tool_name="write"),
    ]
    repaired = repair_tool_use_result_pairing(across)
    assert _texts(repaired.messages) == ["real", "second output"]
    assert [m.get("toolCallId") for m in repaired.messages] == [None, "call_1", None, "call_2"]
    assert repaired.discarded == [across[1]]
    # Real first, then a synthetic one: the real result stays; two synthetic: the first stays.
    real_first = [_assistant_tool("call_1"), _tool_result("call_1", "real"), _synthetic("call_1")]
    assert _texts(repair_tool_use_result_pairing(real_first).messages) == ["real"]
    two_synthetic = [_assistant_tool("call_1"), _synthetic("call_1"), _synthetic("call_1")]
    kept = repair_tool_use_result_pairing(two_synthetic).messages
    assert kept == two_synthetic[:2]
    # A real error that only contains the marker text is not synthetic.
    marked = {**_synthetic("call_1"), "content": [
        {"type": "text", "text": DEFAULT_MISSING_TOOL_RESULT_TEXT + " (extra context)"}
    ]}
    assert _texts(
        repair_tool_use_result_pairing(
            [_assistant_tool("call_1"), marked, _tool_result("call_1", "real")]
        ).messages
    ) == [DEFAULT_MISSING_TOOL_RESULT_TEXT + " (extra context)"]


def test_is_synthetic_missing_tool_result_reads_the_marker_or_the_default_text():
    assert is_synthetic_missing_tool_result(_synthetic("c"))
    assert is_synthetic_missing_tool_result(
        {"isError": True, "details": {SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY: True}}
    )
    assert not is_synthetic_missing_tool_result({**_synthetic("c"), "isError": False})
    assert not is_synthetic_missing_tool_result(
        {"isError": True, "content": [{"type": "text", "text": "aborted"}]}
    )


def test_a_displaced_result_is_claimed_by_its_unresolved_call():
    late = [
        _assistant_tool("call_read"),
        {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": "call_exec", "name": "exec", "arguments": {}}],
        },
        _tool_result("call_read", "real read output"),
        _tool_result("call_exec", "real exec output", tool_name="exec"),
    ]

    result = repair_tool_use_result_pairing(late)

    assert result.added == []
    assert [message["role"] for message in result.messages] == [
        "assistant",
        "toolResult",
        "assistant",
        "toolResult",
    ]
    assert result.messages[1] is late[2] and result.messages[3] is late[3]
    assert result.moved is True
    # The claimed result gets the call's name when its own is blank; it moves only once.
    blank_name = {**_exec_result("call_read", "late read"), "toolName": "   "}
    normalized = repair_tool_use_result_pairing(
        [
            _exec_call("call_read"),
            {
                "role": "assistant",
                "content": [
                    {"type": "toolCall", "id": "call_write", "name": "write", "arguments": {}}
                ],
            },
            blank_name,
            {**_exec_result("call_write", "write output"), "toolName": "write"},
        ]
    )
    assert normalized.added == [] and normalized.discarded == []
    assert _texts(normalized.messages) == ["late read", "write output"]
    assert normalized.messages[1] == {**blank_name, "toolName": "exec"}


def test_ambiguous_displaced_results_are_dropped():
    ambiguous = repair_tool_use_result_pairing(
        [
            _exec_call("exec_0"),
            _exec_call("exec_0"),
            _exec_result("exec_0", "locally first"),
            _exec_result("exec_0", "ambiguous extra"),
        ]
    )
    assert len(ambiguous.added) == 1
    assert ambiguous.dropped_duplicate_count == 1
    assert _texts(ambiguous.messages) == [DEFAULT_MISSING_TOOL_RESULT_TEXT, "locally first"]
    # An unresolved failed occurrence blocks the guess too.
    blocked = repair_tool_use_result_pairing(
        [
            _exec_call("exec_0"),
            _exec_call("exec_0", "error"),
            _exec_call("write_0"),
            _exec_result("exec_0", "ambiguous displaced output"),
            _exec_result("write_0", "write output"),
        ],
        errored_assistant_result_policy="drop",
    )
    assert blocked.dropped_orphan_count == 1
    assert [message["role"] for message in blocked.messages] == [
        "assistant",
        "toolResult",
        "assistant",
        "toolResult",
    ]
    assert _texts(blocked.messages) == [DEFAULT_MISSING_TOOL_RESULT_TEXT, "write output"]
    # A dropped failed turn keeps its local result from leaking backward.
    failed = repair_tool_use_result_pairing(
        [
            _exec_call("exec_0"),
            _exec_call("exec_0", "error"),
            _exec_result("exec_0", "failed turn output", True),
            {"role": "user", "content": "retry"},
        ],
        errored_assistant_result_policy="drop",
    )
    assert [message["role"] for message in failed.messages] == ["assistant", "toolResult", "user"]
    assert _texts(failed.messages) == [DEFAULT_MISSING_TOOL_RESULT_TEXT]


def test_unframed_results_are_kept_with_preserve_unframed():
    orphan = _tool_result("call_orphan", "orphan")

    alone = repair_tool_use_result_pairing([orphan], preserve_unframed_tool_results=True)

    assert alone.messages == [orphan] and alone.discarded == []
    messages = [
        _assistant_tool("call_1"),
        _tool_result("call_1", "first real"),
        _tool_result("call_1", "second real"),
        _tool_result("call_orphan", "preserved unframed"),
    ]
    kept = repair_tool_use_result_pairing(messages, preserve_unframed_tool_results=True)
    assert kept.messages == [messages[0], messages[1], messages[3]]
    assert kept.discarded == [messages[2]]
    assert kept.dropped_duplicate_count == 1
    dropped = repair_tool_use_result_pairing(messages)
    assert dropped.messages == messages[:2]
    assert dropped.dropped_orphan_count == 1


def test_synthetic_results_carry_the_missing_result_reason():
    result = repair_tool_use_result_pairing(
        [_assistant_tool("call_1"), {"role": "user", "content": "next"}]
    )

    (added,) = result.added
    assert result.messages[1] is added
    assert {key: value for key, value in added.items() if key != "timestamp"} == {
        "role": "toolResult",
        "toolCallId": "call_1",
        "toolName": "read",
        "content": [{"type": "text", "text": DEFAULT_MISSING_TOOL_RESULT_TEXT}],
        "details": {SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY: True, "reason": "missing_tool_result"},
        "isError": True,
    }
    assert isinstance(added["timestamp"], int)
    assert DEFAULT_MISSING_TOOL_RESULT_TEXT.startswith("[openclaw] missing tool result")
    # The model-facing form: policy drop, and "aborted" for the OpenAI Responses API.
    responses = sanitize_tool_use_result_pairing_for_model(
        [_assistant_tool("call_1"), {"role": "user", "content": "next"}], True
    )
    assert _texts(responses) == ["aborted"]
    dropped = sanitize_tool_use_result_pairing_for_model(
        [_assistant_tool("call_1", stop_reason="error"), _tool_result("call_1")], False
    )
    assert dropped == []


def test_discarded_lists_dropped_results_in_source_order():
    orphan_first = [
        {"role": "user", "content": "hello"},
        _tool_result("call_orphan", "orphan"),
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]
    assert repair_tool_use_result_pairing(orphan_first).discarded == [orphan_first[1]]
    messages = [
        _assistant_tool("call_1"),
        _synthetic("call_1"),
        _tool_result("call_orphan", "orphan"),
        _tool_result("call_1"),
    ]

    result = repair_tool_use_result_pairing(messages)

    assert result.discarded == [messages[1], messages[2]]


def test_a_second_result_within_a_frame_counts_as_a_duplicate():
    messages = [
        _assistant_tool("call_1"),
        _tool_result("call_1"),
        _tool_result("call_1", "duplicate"),
    ]

    result = repair_tool_use_result_pairing(messages)

    assert result.messages == messages[:2] and result.messages is not messages
    assert result.dropped_duplicate_count == 1
    assert result.moved is True
    assert result.discarded == [messages[2]]
