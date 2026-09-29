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
    sanitize_tool_call_inputs,
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


def _assistant(*blocks: dict, **fields) -> dict:
    return {"role": "assistant", "content": list(blocks), **fields}


def _call_ids(messages: list[dict]) -> list[str]:
    return [
        block.get("id")
        for message in messages
        if message.get("role") == "assistant"
        for block in message["content"]
        if block.get("type") in ("toolCall", "toolUse", "functionCall", "tool_call", "tool_use", "function_call")
    ]


def test_input_repair_drops_calls_without_an_id_or_input():
    no_input = [_assistant({"type": "toolCall", "id": "call_1", "name": "read"}), {"role": "user", "content": "hi"}]
    assert sanitize_tool_call_inputs(no_input) == [no_input[1]]
    blocks = [
        {"type": "toolCall", "id": "call_ok", "name": "read", "arguments": {}},
        {"type": "toolCall", "id": "call_null", "name": "read", "arguments": None},
        {"type": "toolUse", "id": "call_input", "name": "read", "input": {"path": "a"}},
        {"type": "functionCall", "id": "", "name": "exec", "arguments": {}},
        {"type": "toolCall", "id": "   ", "name": "exec", "arguments": {}},
        {"type": "toolCall", "name": "exec", "arguments": {}},
        {"type": "toolCall", "toolCallId": "call_alt_key", "name": "exec", "arguments": "{}"},
    ]

    out = sanitize_tool_call_inputs([_assistant(*blocks)])

    assert [block.get("id", block.get("toolCallId")) for block in out[0]["content"]] == [
        "call_ok",
        "call_input",
        "call_alt_key",
    ]
    # A non-object message is dropped too.
    assert sanitize_tool_call_inputs(["not a message", no_input[1]]) == [no_input[1]]


def test_input_repair_drops_calls_with_a_bad_name():
    blocks = [
        {"type": "toolCall", "id": "call_ok", "name": "read", "arguments": {}},
        {"type": "toolCall", "id": "call_empty", "name": "", "arguments": {}},
        {"type": "toolUse", "id": "call_blank", "name": "   ", "input": {}},
        {"type": "toolCall", "id": "call_none", "arguments": {}},
        {"type": "toolCall", "id": "call_chars", "name": 'toolu_01 <|begin|> {"command"', "arguments": {}},
        {"type": "toolUse", "id": "call_long", "name": "read_" + "x" * 80, "input": {}},
        {"type": "toolCall", "id": "call_ns", "name": "vigil-harbor__memory_status", "arguments": {}},
        {"type": "toolUse", "id": "call_dotted", "name": "my.server:some_tool", "input": {}},
        {"type": "toolCall", "id": "call_unknown", "name": "write", "arguments": {}},
    ]

    unrestricted = sanitize_tool_call_inputs([_assistant(*blocks)])
    restricted = sanitize_tool_call_inputs(
        [_assistant(*blocks)], allowed_tool_names=["read", "vigil-harbor__memory_status"]
    )

    assert _call_ids(unrestricted) == ["call_ok", "call_ns", "call_dotted", "call_unknown"]
    assert _call_ids(restricted) == ["call_ok", "call_ns"]


def test_input_repair_matches_allowed_names_case_insensitively():
    blocks = [
        {"type": "toolCall", "id": "call_1", "name": "Memory_Search", "arguments": {}},
        {"type": "toolCall", "id": "call_2", "name": "memory_get", "arguments": {}},
        {"type": "toolCall", "id": "call_3", "name": "write", "arguments": {}},
    ]

    out = sanitize_tool_call_inputs(
        [_assistant(*blocks)], allowed_tool_names=[" MEMORY_SEARCH ", "Memory_Get", 7, ""]
    )

    assert _call_ids(out) == ["call_1", "call_2"]
    # An empty allowlist restricts nothing.
    assert sanitize_tool_call_inputs(m := [_assistant(*blocks)], allowed_tool_names=[]) is m


def test_input_repair_keeps_a_completed_call_outside_the_allowed_names():
    assistant = _assistant(
        {"type": "toolCall", "id": "old_call", "name": "removed_plugin", "arguments": {"a": 1}}
    )
    result = _tool_result("old_call", "completed", tool_name="removed_plugin")
    allowed = ["read"]

    completed = [assistant, result]
    assert sanitize_tool_call_inputs(completed, allowed_tool_names=allowed) is completed
    assert sanitize_tool_call_inputs([assistant], allowed_tool_names=allowed) == []
    unrelated = _tool_result("other_call", "unrelated", tool_name="removed_plugin")
    synthetic = {**_synthetic("old_call"), "toolName": "removed_plugin"}
    for other in (unrelated, synthetic):
        assert sanitize_tool_call_inputs([assistant, other], allowed_tool_names=allowed) == [other]
    later = _assistant({"type": "toolCall", "id": "old_call", "name": "read", "arguments": {}})
    later_result = _tool_result("old_call", "later")
    assert sanitize_tool_call_inputs(
        [assistant, later, later_result], allowed_tool_names=allowed
    ) == [later, later_result]


def test_input_repair_drops_an_emptied_assistant_message():
    kept_text = _assistant(
        {"type": "text", "text": "before"},
        {"type": "toolUse", "id": "call_ok", "name": "read", "input": {"path": "a"}},
        {"type": "toolCall", "id": "call_drop", "name": "read"},
        stopReason="toolUse",
    )
    emptied = _assistant({"type": "toolCall", "name": "read", "arguments": {}})
    user = {"role": "user", "content": "next"}

    out = sanitize_tool_call_inputs([kept_text, emptied, user])

    assert out == [{**kept_text, "content": kept_text["content"][:2]}, user]
    assert out[0]["stopReason"] == "toolUse"
    assert out[0]["content"][0] is kept_text["content"][0]


def test_input_repair_trims_names():
    block = {"type": "toolCall", "id": "call_1", "name": " read ", "arguments": {"path": "/tmp/x"}}
    padded = {"type": "toolUse", "id": "call_2", "name": "\u00a0exec\ufeff", "input": {"command": "ls"}}

    out = sanitize_tool_call_inputs([_assistant(block, padded)], allowed_tool_names=["read", "exec"])

    assert out[0]["content"] == [
        {**block, "name": "read"},
        {**padded, "name": "exec"},
    ]
    assert block["name"] == " read "


def test_input_repair_strips_a_finalized_responses_partial_json():
    blocks = [
        {"type": "toolCall", "id": "call_ok", "name": "read", "arguments": {"path": "/a"}},
        {
            "type": "toolCall",
            "id": "call_partial|fc_123",
            "name": "Bash",
            "arguments": {"command": "ls"},
            "partialJson": '{"command": "ls"}',
        },
        {"type": "toolCall", "id": "call_empty|fc_789", "name": "status", "arguments": {}, "partialJson": ""},
        {"type": "toolCall", "id": "toolu_123", "name": "Bash", "arguments": {}, "partialJson": '{"command":'},
        {
            "type": "toolCall",
            "id": "call_truncated|fc_456",
            "name": "Bash",
            "arguments": {"command": "ls"},
            "partialJson": '{"command":"ls"',
        },
        {"type": "toolUse", "id": "call_partial2", "name": "read", "input": None, "partialJson": '{"path":'},
    ]

    out = sanitize_tool_call_inputs(
        [_assistant(*blocks, stopReason="toolUse"), {"role": "user", "content": "retry"}]
    )

    assert _call_ids(out) == ["call_ok", "call_partial|fc_123", "call_empty|fc_789"]
    assert out[0]["content"][1] == {
        key: value for key, value in blocks[1].items() if key != "partialJson"
    }
    assert "partialJson" not in out[0]["content"][2]
    # Not a finalized toolUse turn: every partialJson block is dropped.
    for stop_reason in ("stop", "aborted", "error", "length"):
        stopped = sanitize_tool_call_inputs(
            [_assistant(blocks[1], stopReason=stop_reason), {"role": "user", "content": "retry"}]
        )
        assert _call_ids(stopped) == []


def test_input_repair_reads_snake_case_block_types():
    blocks = [
        {"type": "text", "text": "before"},
        {"type": "tool_use", "id": "tool_1", "name": "read"},
        {"type": "tool_call", "tool_call_id": "tool_2", "name": "write", "arguments": {}},
        {"type": "function_call", "call_id": "tool_3", "name": "exec", "arguments": "{}"},
    ]

    out = sanitize_tool_call_inputs([_assistant(*blocks)], allowed_tool_names=["write", "exec"])

    assert [(block["type"], block.get("name")) for block in out[0]["content"]] == [
        ("text", None),
        ("tool_call", "write"),
        ("function_call", "exec"),
    ]


def test_input_repair_returns_the_input_list_when_nothing_changes():
    messages = [
        {"role": "user", "content": "hi"},
        _assistant(
            {"type": "text", "text": "checking"},
            {"type": "toolCall", "id": "call_1", "name": "read", "arguments": {}},
        ),
        _tool_result("call_1"),
        {"role": "assistant", "content": "a plain string reply"},
        {"role": "toolResult", "toolCallId": "orphan", "content": []},
    ]

    assert sanitize_tool_call_inputs(messages) is messages
    assert sanitize_tool_call_inputs(messages, allowed_tool_names=["READ"]) is messages
    assert sanitize_tool_call_inputs([]) == []
