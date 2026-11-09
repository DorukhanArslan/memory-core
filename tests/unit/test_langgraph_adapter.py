"""memory_core.adapters.langgraph: the framework-free glue a LangGraph host uses with the kit.

The adapter reads LangChain messages by their attributes and returns plain dicts; these tests
feed it real ``langchain_core`` messages and check what the kit and LangChain make of its output.
"""

import json
from pathlib import Path

import pytest

from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState, TurnUsage
from memory_core._transcript_repair_constants import DEFAULT_MISSING_TOOL_RESULT_TEXT
from memory_core.adapters.langgraph import (
    has_tool_calls,
    repair_tool_calls,
    tool_messages,
    transcript_rows,
    turn_usage,
)
from memory_core.session_memory import get_recent_session_projection_from_events

messages = pytest.importorskip("langchain_core.messages")
AIMessage = messages.AIMessage
ChatMessage = messages.ChatMessage
HumanMessage = messages.HumanMessage
SystemMessage = messages.SystemMessage
ToolMessage = messages.ToolMessage


def _kit(root: Path, *, now_ms=None) -> HostKit:
    return HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
        now_ms=now_ms,
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
    assert 'user: "I prefer green tea."' in saved
    assert 'assistant: "Green tea it is."' in saved


def _message_shape(message, shape):
    if shape == "model_dump":
        return message.model_dump()
    if shape == "messages_to_dict":
        return messages.messages_to_dict([message])[0]
    return message


@pytest.mark.parametrize("shape", ["object", "model_dump", "messages_to_dict"])
def test_transcript_rows_project_only_host_memory_metadata(shape):
    human = HumanMessage(
        "Hello there",
        additional_kwargs={
            "provenance": {"kind": "external_user", "sourceTool": "sessions_send", "jobId": "j1"},
            "__openclaw": {"senderIsOwner": True, "turnTainted": False, "runId": "r1"},
            "provider_payload": {"senderIsOwner": False},
        },
        response_metadata={"__openclaw": {"senderIsOwner": False}},
    )
    ai = AIMessage(
        "Hi! How can I help?",
        additional_kwargs={"__openclaw": {"turnTainted": True}},
    )

    shaped_human = _message_shape(human, shape)
    rows = transcript_rows([shaped_human, _message_shape(ai, shape)])

    assert rows == [
        {
            "role": "user",
            "content": "Hello there",
            "provenance": {"kind": "external_user", "sourceTool": "sessions_send"},
            "__openclaw": {"senderIsOwner": True, "turnTainted": False},
        },
        {
            "role": "assistant",
            "content": "Hi! How can I help?",
            "__openclaw": {"turnTainted": True},
        },
    ]
    source_kwargs = (
        shaped_human.additional_kwargs if shape == "object"
        else (shaped_human["data"] if shape == "messages_to_dict" else shaped_human)["additional_kwargs"]
    )
    assert rows[0]["provenance"] is not source_kwargs["provenance"]
    assert rows[0]["__openclaw"] is not source_kwargs["__openclaw"]
    rows[0]["provenance"]["kind"] = "internal_system"
    rows[0]["__openclaw"]["senderIsOwner"] = False
    assert human.additional_kwargs["provenance"]["kind"] == "external_user"
    assert human.additional_kwargs["__openclaw"]["senderIsOwner"] is True


@pytest.mark.parametrize("shape", ["object", "model_dump", "messages_to_dict"])
@pytest.mark.parametrize("owner,tainted,origin", [(True, False, "agent"), (False, False, "untrusted"), (True, True, "untrusted")])
def test_projected_host_metadata_reaches_session_memory_trust(shape, owner, tainted, origin):
    transcript = [
        HumanMessage("Hello there", additional_kwargs={"__openclaw": {"senderIsOwner": owner}}),
        AIMessage("Hi! How can I help?", additional_kwargs={"__openclaw": {"turnTainted": tainted}}),
    ]
    rows = transcript_rows([_message_shape(message, shape) for message in transcript])

    projection = get_recent_session_projection_from_events(
        [{"type": "message", "message": row} for row in rows]
    )

    assert projection.origin_class == origin


@pytest.mark.parametrize("kind", ["inter_session", "internal_system", "future_kind"])
def test_transcript_rows_keep_provenance_strings_without_reinterpreting_them(kind):
    row = transcript_rows([HumanMessage(
        "Hello there",
        additional_kwargs={"provenance": {"kind": kind, "sourceTool": "memory_search"}},
    )])[0]

    assert row["provenance"] == {"kind": kind, "sourceTool": "memory_search"}


@pytest.mark.parametrize("value", [1, 0, "true", "false", None, [], {}])
def test_transcript_rows_do_not_coerce_trust_booleans(value):
    row = transcript_rows([HumanMessage(
        "Hello there",
        additional_kwargs={
            "__openclaw": {"senderIsOwner": value, "turnTainted": value},
        },
    )])[0]

    assert row == {"role": "user", "content": "Hello there"}


@pytest.mark.parametrize("value", [1, 0, True, False, None, [], {}])
def test_transcript_rows_do_not_coerce_provenance_strings(value):
    row = transcript_rows([HumanMessage(
        "Hello there", additional_kwargs={"provenance": {"kind": value, "sourceTool": value}},
    )])[0]

    assert row == {"role": "user", "content": "Hello there"}


def test_transcript_rows_do_not_read_provider_response_metadata():
    row = transcript_rows([HumanMessage(
        "Hello there", response_metadata={"__openclaw": {"senderIsOwner": True}},
    )])[0]

    assert row == {"role": "user", "content": "Hello there"}


def test_transcript_rows_keep_existing_role_mapping_metadata():
    row = {"role": "user", "content": "Hello there", "provenance": {"kind": "future_kind"}}

    projected = transcript_rows([row])[0]

    assert projected == row and projected is not row
    assert projected["provenance"] is row["provenance"]


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
    kit = _kit(tmp_path, now_ms=lambda: 1_790_375_400_000)
    dispatch = kit.dispatcher(_session())
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

    assert calls == [
        ("memory_search", {"query": "codename"}),
        ("memory_get", {"path": "MEMORY.md"}),
    ]
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
    dispatch = kit.dispatcher(_session())
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

    rows = tool_messages(message, kit.dispatcher(_session()))
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


def _history() -> list:
    return [
        HumanMessage("Search please.", id="h1"),
        AIMessage("", id="a1", tool_calls=[{"name": "memory_search", "args": {"q": 1}, "id": "call-1"}]),
        ToolMessage("{}", tool_call_id="call-1", name="memory_search", id="t1"),
        AIMessage("Found nothing.", id="a2"),
        HumanMessage("Are you there?", id="h2"),
    ]


def test_repair_tool_calls_returns_the_original_messages_when_nothing_changes(tmp_path: Path):
    kit = _kit(tmp_path)
    history = _history()
    seen = []

    def repair(rows):
        seen.append(rows)
        return kit.repair_tool_calls(rows)

    repaired = repair_tool_calls(history, repair)

    assert all(message is original for message, original in zip(repaired, history, strict=True))
    (rows,) = seen
    assert [row["role"] for row in rows] == ["user", "assistant", "tool", "assistant", "user"]
    assert [call["id"] for call in rows[1]["tool_calls"]] == ["call-1"]
    assert rows[2]["status"] == "success"
    assert repair_tool_calls([], kit.repair_tool_calls) == []


def test_repair_tool_calls_inserts_a_synthetic_tool_message(tmp_path: Path):
    kit = _kit(tmp_path)
    ai = AIMessage("", tool_calls=[{"name": "memory_search", "args": {"query": "x"}, "id": "call-1"}])
    history = [HumanMessage("Search please."), ai, HumanMessage("Are you there?")]

    repaired = repair_tool_calls(history, kit.repair_tool_calls)

    assert repaired[:2] == history[:2] and repaired[1] is ai and repaired[3] is history[2]
    synthetic = repaired[2]
    assert synthetic == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
        "name": "memory_search",
        "status": "error",
    }
    (converted,) = messages.convert_to_messages([synthetic])
    assert isinstance(converted, ToolMessage)
    assert (converted.tool_call_id, converted.name, converted.status) == (
        "call-1",
        "memory_search",
        "error",
    )


@pytest.mark.parametrize("blank", ["", "  "])
def test_repair_tool_calls_pairs_a_blank_id_tool_message_as_an_error(tmp_path: Path, blank):
    # normalizeLegacyToolResultId: an id-less result of the frame's only call is that call's
    # error result (isError: true), so the copy gets the call's id and status "error".
    kit = _kit(tmp_path)
    ai = AIMessage("", tool_calls=[{"name": "memory_search", "args": {"query": "x"}, "id": "call-1"}])
    blank_id = ToolMessage("{}", tool_call_id=blank, name="memory_search", id="t1")
    history = [HumanMessage("Search please."), ai, blank_id]

    repaired = repair_tool_calls(history, kit.repair_tool_calls)

    assert len(repaired) == 3 and repaired[1] is ai
    copy = repaired[2]
    assert isinstance(copy, ToolMessage) and copy is not blank_id
    assert (copy.tool_call_id, copy.status, copy.id, copy.content) == ("call-1", "error", "t1", "{}")
    assert (blank_id.tool_call_id, blank_id.status) == (blank, "success")
    # A role dict without a status keeps its plain shape.
    role_dict = {"role": "tool", "tool_call_id": blank, "content": "{}"}
    (_, _, paired) = repair_tool_calls([history[0], ai, role_dict], kit.repair_tool_calls)
    assert paired == {**role_dict, "tool_call_id": "call-1"}


def test_repair_tool_calls_copies_an_ai_message_without_its_dropped_calls(tmp_path: Path):
    base = pytest.importorskip("langchain_openai.chat_models.base")
    kit = _kit(tmp_path)
    raw = [
        {"id": "call-9", "type": "function", "function": {"name": "memory_search", "arguments": "{}"}},
        {"id": "call-2", "type": "function", "function": {"name": "memory_get", "arguments": "{}"}},
    ]
    ai = AIMessage(
        "Looking.",
        id="a1",
        tool_calls=[
            {"name": "memory_search", "args": {"query": "x"}, "id": None},
            {"name": " memory_get ", "args": {"path": "MEMORY.md"}, "id": "call-2"},
        ],
        invalid_tool_calls=[{"name": "memory_search", "args": None, "id": "call-3", "error": None}],
        additional_kwargs={"tool_calls": raw},
    )
    history = [HumanMessage("Look it up."), ai, HumanMessage("And?")]

    repaired = repair_tool_calls(history, kit.repair_tool_calls)

    copy = repaired[1]
    assert isinstance(copy, AIMessage) and copy is not ai
    assert (copy.id, copy.content) == ("a1", "Looking.")
    assert [(call["id"], call["name"]) for call in copy.tool_calls] == [("call-2", "memory_get")]
    assert copy.tool_calls[0]["args"] == {"path": "MEMORY.md"}
    assert copy.invalid_tool_calls == []
    assert copy.additional_kwargs == {"tool_calls": [raw[1]]}
    assert len(ai.tool_calls) == 2 and len(ai.invalid_tool_calls) == 1
    assert repaired[2]["tool_call_id"] == "call-2" and repaired[2]["name"] == "memory_get"
    sent = base._convert_message_to_dict(copy)
    assert [call["id"] for call in sent["tool_calls"]] == ["call-2"]
    # With no call left, the copy keeps its text and sends no tool calls at all.
    lone = AIMessage(
        "Only text left.",
        tool_calls=[{"name": "memory_search", "args": {}, "id": None}],
        additional_kwargs={"tool_calls": raw[:1], "function_call": {"name": "memory_search"}},
    )
    (_, bare, _) = repair_tool_calls([history[0], lone, history[2]], kit.repair_tool_calls)
    assert (bare.tool_calls, bare.invalid_tool_calls, bare.additional_kwargs) == ([], [], {})
    assert "tool_calls" not in base._convert_message_to_dict(bare)
    assert "function_call" not in base._convert_message_to_dict(bare)


def test_repair_tool_calls_reads_role_and_type_dicts(tmp_path: Path):
    kit = _kit(tmp_path)
    role_dict = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "memory_get", "arguments": "{}"}}
        ],
    }
    typed = AIMessage("", tool_calls=[{"name": "memory_get", "args": {}, "id": None}]).model_dump()
    wrapped = messages.messages_to_dict(
        [AIMessage("text", tool_calls=[{"name": "memory_get", "args": {}, "id": None}])]
    )[0]
    history = [{"role": "user", "content": "hi"}, role_dict, typed, wrapped, HumanMessage("And?")]

    repaired = repair_tool_calls(history, kit.repair_tool_calls)

    assert repaired[0] is history[0] and repaired[1] is role_dict
    assert repaired[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
        "name": "memory_get",
        "status": "error",
    }
    # The typed dict had no content left and is dropped; the wrapped one keeps its text.
    assert repaired[3] == {**wrapped, "data": {**wrapped["data"], "tool_calls": [], "invalid_tool_calls": []}}
    assert repaired[4] is history[4]
    assert len(repaired) == 5
