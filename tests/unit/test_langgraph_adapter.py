"""memory_core.adapters.langgraph: the framework-free glue a LangGraph host uses with the kit.

The adapter reads LangChain messages by their attributes and returns plain dicts; these tests
feed it real ``langchain_core`` messages and check what the kit and LangChain make of its output.
"""

import functools
import json
from pathlib import Path

import pytest

from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState, TurnUsage
from memory_core.adapters.langgraph import (
    PendingTurn,
    has_tool_calls,
    tool_messages,
    transcript_rows,
    turn_usage,
)

messages = pytest.importorskip("langchain_core.messages")
AIMessage = messages.AIMessage
ChatMessage = messages.ChatMessage
HumanMessage = messages.HumanMessage
SystemMessage = messages.SystemMessage
ToolMessage = messages.ToolMessage


def _kit(root: Path) -> HostKit:
    return HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    )


def _session() -> SessionState:
    return SessionState.new(session_key="thread-1", session_id="session-1")


def test_transcript_rows_map_langchain_types_to_kit_roles():
    call = {"name": "memory_search", "args": {"query": "codename"}, "id": "call-1"}

    rows = transcript_rows(
        [
            SystemMessage("host system text"),
            HumanMessage("What is our codename?", id="m1"),
            AIMessage("", tool_calls=[call]),
            ToolMessage('{"results": []}', tool_call_id="call-1", name="memory_search"),
            AIMessage("I could not find one."),
            ChatMessage(role="user", content="from a chat message"),
        ]
    )

    assert rows == [
        {"role": "system", "content": "host system text"},
        {"role": "user", "content": "What is our codename?"},
        {"role": "assistant", "content": ""},
        {
            "role": "tool",
            "content": '{"results": []}',
            "tool_call_id": "call-1",
            "name": "memory_search",
        },
        {"role": "assistant", "content": "I could not find one."},
        {"role": "user", "content": "from a chat message"},
    ]


def test_transcript_rows_keep_content_blocks_and_copy_role_dicts():
    blocks = [
        {"type": "text", "text": "Our codename is velvetkiwi."},
        {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
    ]
    role_dict = {"role": "assistant", "content": "Noted.", "type": "message"}

    rows = transcript_rows([HumanMessage(blocks), role_dict])

    assert rows == [
        {"role": "user", "content": blocks},
        {"role": "assistant", "content": "Noted."},
    ]
    assert role_dict == {"role": "assistant", "content": "Noted.", "type": "message"}


def test_transcript_rows_read_type_dicts_and_never_emit_a_type_key(tmp_path: Path):
    # A LangChain message's dict forms (model_dump and messages_to_dict) read like the object.
    # A row with a "type" key would be read as a raw transcript entry by the session-memory
    # hook and dropped, so the saved file shows whether the rows arrived.
    human = HumanMessage("I prefer green tea.")
    ai = AIMessage("Green tea it is.")
    kit = _kit(tmp_path)

    rows = transcript_rows([human.model_dump(), messages.messages_to_dict([ai])[0]])
    new = kit.on_new_session(_session(), command="new", session_id="session-2", transcript=rows)

    assert rows == [
        {"role": "user", "content": "I prefer green tea."},
        {"role": "assistant", "content": "Green tea it is."},
    ]
    saved = new.saved.path.read_text(encoding="utf-8")
    assert "user: I prefer green tea." in saved
    assert "assistant: Green tea it is." in saved


def test_transcript_rows_reject_an_unknown_message_type():
    with pytest.raises(ValueError, match="remove"):
        transcript_rows([messages.RemoveMessage(id="m1")])
    with pytest.raises(ValueError, match="None"):
        transcript_rows([object()])


def test_turn_usage_reads_usage_metadata():
    usage = {"input_tokens": 1200, "output_tokens": 35, "total_tokens": 1235}

    assert turn_usage(AIMessage("reply", usage_metadata=usage)) == TurnUsage(
        prompt_tokens=1200, completion_tokens=35
    )
    assert turn_usage({"type": "ai", "content": "reply", "usage_metadata": usage}) == TurnUsage(
        prompt_tokens=1200, completion_tokens=35
    )


def test_turn_usage_without_usage_metadata_is_none():
    assert turn_usage(AIMessage("reply")) is None
    assert turn_usage(HumanMessage("hi")) is None


def test_has_tool_calls_counts_invalid_calls():
    valid = AIMessage("", tool_calls=[{"name": "memory_get", "args": {}, "id": "call-1"}])
    invalid = AIMessage(
        "",
        invalid_tool_calls=[
            {"name": "memory_search", "args": '{"query": ', "id": "call-2", "error": None}
        ],
    )

    assert has_tool_calls(valid)
    assert has_tool_calls(invalid)
    assert not has_tool_calls(AIMessage("a plain reply"))
    assert not has_tool_calls(HumanMessage("hi"))


def test_tool_messages_answer_every_call_through_dispatch(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("- The project codename is velvetkiwi.\n", encoding="utf-8")
    kit = _kit(tmp_path)
    dispatch = functools.partial(kit.dispatch, session=_session())
    calls = []

    def recording(name, arguments):
        calls.append((name, arguments))
        return dispatch(name, arguments)

    message = AIMessage(
        "",
        tool_calls=[
            {"name": "memory_search", "args": {"query": "codename"}, "id": "call-1"},
            {"name": "memory_get", "args": {"path": "MEMORY.md"}, "id": "call-2"},
        ],
    )

    rows = tool_messages(message, recording)

    assert calls == [("memory_search", {"query": "codename"}), ("memory_get", {"path": "MEMORY.md"})]
    assert [(row["role"], row["tool_call_id"], row["name"], row["status"]) for row in rows] == [
        ("tool", "call-1", "memory_search", "success"),
        ("tool", "call-2", "memory_get", "success"),
    ]
    search, get = (json.loads(row["content"]) for row in rows)
    assert search == dispatch("memory_search", {"query": "codename"})
    assert search["results"][0]["path"] == "MEMORY.md"
    assert get == dispatch("memory_get", {"path": "MEMORY.md"})


def test_tool_messages_answer_invalid_calls_with_the_kit_error_payload(tmp_path: Path):
    kit = _kit(tmp_path)
    dispatch = functools.partial(kit.dispatch, session=_session())
    message = AIMessage(
        "",
        invalid_tool_calls=[
            {"name": "memory_search", "args": '{"query": ', "id": "call-1", "error": "bad"},
            {"name": None, "args": None, "id": "call-2", "error": "no name"},
        ],
    )

    rows = tool_messages(message, dispatch)

    assert [json.loads(row["content"]) for row in rows] == [
        dispatch("memory_search", '{"query": '),
        dispatch("", None),
    ]
    assert json.loads(rows[0]["content"])["error"].startswith("invalid JSON arguments")
    assert [(row["name"], row["status"]) for row in rows] == [
        ("memory_search", "error"),
        ("", "error"),
    ]


def test_tool_messages_mark_error_payloads_and_convert_to_tool_messages(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("- A fact.\n", encoding="utf-8")
    kit = _kit(tmp_path)
    message = AIMessage(
        "",
        tool_calls=[
            {"name": "memory_search", "args": {}, "id": "call-1"},
            {"name": "memory_get", "args": {"path": "MEMORY.md"}, "id": "call-2"},
        ],
    )

    rows = tool_messages(message, functools.partial(kit.dispatch, session=_session()))
    converted = messages.convert_to_messages(rows)

    assert json.loads(rows[0]["content"]) == {
        "status": "error",
        "tool": "memory_search",
        "error": "query required",
    }
    assert all(isinstance(item, ToolMessage) for item in converted)
    assert [(item.tool_call_id, item.name, item.status) for item in converted] == [
        ("call-1", "memory_search", "error"),
        ("call-2", "memory_get", "success"),
    ]
    assert converted[1].content == rows[1]["content"]


def test_tool_messages_reject_a_call_without_an_id():
    # A ToolMessage needs the call's id, so an id-less call is a provider or host error; no
    # call of the message is dispatched.
    calls = []

    def dispatch(name, arguments):
        calls.append(name)
        return {}

    invalid = AIMessage(
        "",
        tool_calls=[{"name": "memory_get", "args": {}, "id": "call-1"}],
        invalid_tool_calls=[{"name": "memory_search", "args": "{", "id": None, "error": None}],
    )
    valid = AIMessage("", tool_calls=[{"name": "memory_get", "args": {}, "id": None}])

    for message in (invalid, valid):
        with pytest.raises(ValueError, match="no string id"):
            tool_messages(message, dispatch)
    assert calls == []


def test_pending_turn_round_trips_json(tmp_path: Path):
    turn = _kit(tmp_path).before_turn(_session(), runtime_context="Channel: terminal")

    pending = PendingTurn.from_context(
        turn, model_prompt="the reset prompt", model_prompt_message_id="message-9"
    )
    data = json.loads(json.dumps(pending.to_json()))

    assert (pending.session, pending.system_prompt, pending.runtime_context, pending.tools) == (
        turn.session,
        turn.system_prompt,
        turn.runtime_context,
        turn.tools,
    )
    assert turn.system_prompt.startswith("## Memory Recall")
    assert "Channel: terminal" in pending.runtime_context
    assert data["session"] == turn.session.to_json()
    assert PendingTurn.from_json(data) == pending
    assert PendingTurn.from_json(PendingTurn.from_context(turn).to_json()).model_prompt is None


def test_pending_turn_from_json_rejects_a_bad_shape(tmp_path: Path):
    good = PendingTurn.from_context(_kit(tmp_path).before_turn(_session())).to_json()
    bad_shapes = [
        None,
        {**good, "session": None},
        {**good, "session": {**good["session"], "sessionId": 7}},
        {**good, "systemPrompt": None},
        {**good, "runtimeContext": 3},
        {**good, "tools": "memory_search"},
        {**good, "tools": ["memory_search"]},
        {**good, "modelPrompt": "a reset prompt"},
        {key: value for key, value in good.items() if key != "systemPrompt"},
    ]

    for data in bad_shapes:
        with pytest.raises(ValueError):
            PendingTurn.from_json(data)


def test_pending_turn_needs_both_reset_fields(tmp_path: Path):
    turn = _kit(tmp_path).before_turn(_session())

    with pytest.raises(ValueError, match="together"):
        PendingTurn.from_context(turn, model_prompt="the reset prompt")
    with pytest.raises(ValueError, match="together"):
        PendingTurn.from_context(turn, model_prompt_message_id="message-9")
