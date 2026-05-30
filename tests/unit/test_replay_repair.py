from memory_core.replay_repair import repair_tool_use_result_pairing


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
    assert result.dropped_duplicate_count == 0


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
