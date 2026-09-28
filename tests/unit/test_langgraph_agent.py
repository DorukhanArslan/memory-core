"""The LangGraph agent of examples/langgraph_agent.py, end to end over the host kit.

Every test drives the real compiled graph with an InMemorySaver. The chat model is a scripted
test double (``ScriptedChatModel``): it answers from each test's script and records what it was
sent; nothing here calls a provider.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

pytest.importorskip("langgraph")

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import (  # noqa: E402
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.utils.function_calling import convert_to_openai_tool  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402
from pydantic import Field  # noqa: E402

import examples.langgraph_agent as example  # noqa: E402
from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState  # noqa: E402
from memory_core.adapters.langgraph import transcript_rows  # noqa: E402
from memory_core.bootstrap import format_session_reset_transcript_prompt  # noqa: E402
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY  # noqa: E402

NOW_MS = int(datetime(2026, 9, 29, 12, tzinfo=timezone.utc).timestamp() * 1000)
TODAY = "2026-09-29"
DAILY = f"memory/{TODAY}.md"
# A 128,000-token window: the flush threshold is 128,000 - 20,000 reserve - 4,000 soft.
WINDOW = 128_000
THRESHOLD = 104_000
FACT = "- The project codename is velvetkiwi."
THREAD = {"configurable": {"thread_id": "thread-1"}}


@dataclass
class Call:
    """One model call: what the graph sent and which tools were bound."""

    messages: list[BaseMessage]
    tools: list[str]
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def is_flush(self) -> bool:
        return self.tools == ["write"]


class ScriptedChatModel(BaseChatModel):
    """A test double of a tool-calling chat model; ``script`` answers each call."""

    script: Any
    calls: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = [tool["function"]["name"] for tool in kwargs.get("tools") or []]
        call = Call(messages=list(messages), tools=names, kwargs=kwargs)
        self.calls.append(call)
        return ChatResult(generations=[ChatGeneration(message=self.script(call, self.calls))])


def memory_script(*, usage: int = 110_000, query: str = "codename") -> Callable:
    """Each user turn searches memory once and replies; a flush turn writes FACT once.

    The reply reports ``usage`` prompt tokens (past the WINDOW threshold by default).
    """

    def script(call: Call, calls: list[Call]) -> AIMessage:
        last = call.messages[-1]
        if call.is_flush:
            if isinstance(last, ToolMessage):
                return AIMessage("NO_REPLY")
            target = re.search(r"memory/\d{4}-\d{2}-\d{2}\.md", last.content)[0]
            write = {"path": target, "content": FACT}
            return AIMessage("", tool_calls=[{"name": "write", "args": write, "id": "flush-1"}])
        if isinstance(last, ToolMessage):
            replies = sum(1 for item in calls if not item.is_flush and _ends_with_tool(item))
            return AIMessage(
                f"reply {replies}",
                usage_metadata={
                    "input_tokens": usage,
                    "output_tokens": 20,
                    "total_tokens": usage + 20,
                },
            )
        search = {"name": "memory_search", "args": {"query": query}, "id": f"call-{len(calls)}"}
        return AIMessage("", tool_calls=[search])

    return script


def _ends_with_tool(call: Call) -> bool:
    return isinstance(call.messages[-1], ToolMessage)


def _kit(root: Path) -> HostKit:
    return HostKit.open(
        root,
        config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
        now_ms=lambda: NOW_MS,
    )


def _ids() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"id-{next(counter)}"


def _graph(root: Path, script: Callable, **options: Any):
    model = ScriptedChatModel(script=script)
    kit = options.pop("kit", None) or _kit(root)
    options.setdefault("context_window_tokens", WINDOW)
    options.setdefault("new_id", _ids())
    return kit, model, example.build_graph(kit, model, **options)


def _say(graph, text: str, config=THREAD, **kwargs) -> dict:
    return graph.invoke({"messages": [HumanMessage(text)]}, config, **kwargs)


def _session(state: dict) -> SessionState:
    return SessionState.from_json(state["memory_session"])


def _chat_calls(model: ScriptedChatModel) -> list[Call]:
    return [call for call in model.calls if not call.is_flush]


def _flush_calls(model: ScriptedChatModel) -> list[Call]:
    return [call for call in model.calls if call.is_flush]


def test_turn_offers_the_kit_tools_and_answers_memory_search(tmp_path: Path):
    kit, model, graph = _graph(tmp_path, memory_script(usage=1_000))

    state = _say(graph, "Our codename is velvetkiwi.")

    first, second = model.calls
    assert first.tools == second.tools == [tool["name"] for tool in kit.tools()]
    assert [message.type for message in state["messages"]] == ["human", "ai", "tool", "ai"]
    tool_message = state["messages"][2]
    assert tool_message.tool_call_id == "call-1"
    assert tool_message.status == "success"
    expected = kit.dispatch("memory_search", {"query": "codename"}, session=_session(state))
    assert json.loads(tool_message.content) == expected
    assert second.messages[-1] == tool_message
    assert state["messages"][-1].content == "reply 1"
    assert state["memory_turn"] is None
    assert state["memory_maintenance"]["flush"] == "under_threshold"


def test_system_prompt_comes_from_before_turn_and_stays_out_of_the_transcript(tmp_path: Path):
    kit, model, graph = _graph(tmp_path, memory_script(usage=1_000))

    state = _say(graph, "Hello.")

    expected = kit.before_turn(_session(state), ensure=False).system_prompt
    (system, user) = model.calls[0].messages
    assert isinstance(system, SystemMessage)
    assert system.content == expected
    assert expected.startswith("## Memory Recall")
    assert user.content == "Hello."
    stored = [
        message
        for snapshot in graph.get_state_history(THREAD)
        for message in snapshot.values.get("messages", [])
    ]
    assert stored and not any(isinstance(message, SystemMessage) for message in stored)


def test_runtime_context_reaches_the_model_and_is_optional(tmp_path: Path):
    _, model, graph = _graph(tmp_path, memory_script(usage=1_000))

    _say(graph, "Hello.", context=example.AgentContext(runtime_context="Channel: terminal"))
    state = _say(graph, "Hello again.")

    # Every model call of the turn gets the block right before the turn's user message.
    for call in model.calls[:2]:
        system, runtime, user = call.messages[:3]
        assert isinstance(system, SystemMessage)
        assert isinstance(runtime, HumanMessage)
        assert MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_begin in runtime.content
        assert "Channel: terminal" in runtime.content
        assert user.content == "Hello."
    # Without context= the next turn has no block, and none reached the transcript.
    later = model.calls[2].messages
    assert [message.content for message in later[1:]][0] == "Hello."
    assert not any("Channel: terminal" in str(message.content) for message in later)
    assert not any("Channel: terminal" in str(item.content) for item in state["messages"])


def test_due_flush_runs_after_the_reply_and_writes_the_daily_file(tmp_path: Path):
    seen: list[str] = []
    script = memory_script()

    def recording(call: Call, calls: list[Call]) -> AIMessage:
        if call.is_flush and len(_flush_calls_of(calls)) == 1:
            recording.at_flush = list(seen)
        return script(call, calls)

    _, model, graph = _graph(tmp_path, recording)

    for update in graph.stream(
        {"messages": [HumanMessage("Our codename is velvetkiwi.")]}, THREAD, stream_mode="updates"
    ):
        seen.extend(update)
    state = graph.get_state(THREAD).values

    # The reply was in the stream before the flush model call started (upstream order).
    assert recording.at_flush == ["prepare", "agent", "tools", "agent"]
    assert seen == ["prepare", "agent", "tools", "agent", "maintain"]
    assert (tmp_path / DAILY).read_text(encoding="utf-8") == FACT + "\n"
    assert _session(state).entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    assert state["memory_maintenance"] == {
        "flush": "token_threshold",
        "tokenCount": 110_020,
        "threshold": THRESHOLD,
        "window": WINDOW,
        "target": DAILY,
        "wrote": [FACT],
        "failure": None,
    }
    assert [message.type for message in state["messages"]] == ["human", "ai", "tool", "ai"]
    assert not any(FACT in str(message.content) for message in state["messages"])


def _flush_calls_of(calls: list[Call]) -> list[Call]:
    return [call for call in calls if call.is_flush]


def test_flush_turn_is_restricted_to_the_write_tool_and_not_streamed(tmp_path: Path, monkeypatch):
    kit, model, graph = _graph(tmp_path, memory_script())
    records = []
    after_turn = kit.after_turn

    def spy(*args, **kwargs):
        records.append(after_turn(*args, **kwargs))
        return records[-1]

    monkeypatch.setattr(kit, "after_turn", spy)

    chunks = list(
        graph.stream(
            {"messages": [HumanMessage("Our codename is velvetkiwi.")]},
            THREAD,
            stream_mode="messages",
        )
    )

    (record,) = records
    first_flush, second_flush = _flush_calls(model)
    assert first_flush.tools == second_flush.tools == ["write"]
    assert transcript_rows(first_flush.messages) == list(record.flush.messages)
    nodes = {metadata["langgraph_node"] for _, metadata in chunks}
    # Positive control: the agent's reply streams; nothing of the flush turn does.
    assert any(
        metadata["langgraph_node"] == "agent" and chunk.content == "reply 1"
        for chunk, metadata in chunks
    )
    assert "maintain" not in nodes
    assert not any(chunk.content == "NO_REPLY" for chunk, _ in chunks)
    assert (tmp_path / DAILY).read_text(encoding="utf-8") == FACT + "\n"


def _two_turns(root: Path):
    kit, model, graph = _graph(root, memory_script())
    _say(graph, "Our codename is velvetkiwi.")
    state = _say(graph, "What is our codename?")
    return kit, model, graph, state


def test_second_turn_finds_the_flushed_fact(tmp_path: Path):
    _, model, _, state = _two_turns(tmp_path)

    search = json.loads(state["messages"][-2].content)
    (hit,) = search["results"]
    assert (hit["path"], hit["startLine"]) == (DAILY, 1)
    assert FACT in hit["snippet"]
    assert hit["citation"] == f"Source: {DAILY}#L1-L2"
    # The second turn's model input replays the first turn's transcript.
    replayed = [message.content for message in _chat_calls(model)[2].messages[1:]]
    assert replayed[:4] == ["Our codename is velvetkiwi.", "", replayed[2], "reply 1"]


def test_second_turn_past_the_threshold_reads_already_flushed(tmp_path: Path):
    # The kit's known gap, pinned: without compaction a session flushes once.
    _, model, _, state = _two_turns(tmp_path)

    assert len(_flush_calls(model)) == 2  # one flush turn: a write call and its reply
    assert state["memory_maintenance"]["flush"] == "already_flushed"
    assert state["memory_maintenance"]["target"] is None
    assert (tmp_path / DAILY).read_text(encoding="utf-8") == FACT + "\n"


def test_session_state_survives_in_the_checkpointer(tmp_path: Path):
    saver = InMemorySaver()
    _, _, first = _graph(tmp_path, memory_script(), checkpointer=saver)
    before = _say(first, "Our codename is velvetkiwi.")

    # A restart: a new kit for the same root and a new graph over the same saver.
    _, model, second = _graph(tmp_path, memory_script(), checkpointer=saver, kit=_kit(tmp_path))
    after = _say(second, "What is our codename?")

    assert _session(after).session_id == _session(before).session_id == "id-1"
    assert _session(after).session_key == "thread-1"
    assert model.calls[0].messages[1].content == "Our codename is velvetkiwi."
    assert after["memory_maintenance"]["flush"] == "already_flushed"
    assert len(after["messages"]) == 8


def test_state_loads_under_a_strict_serializer(tmp_path: Path):
    saver = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    _, _, graph = _graph(tmp_path, memory_script(), checkpointer=saver)

    _say(graph, "Our codename is velvetkiwi.")
    state = graph.get_state(THREAD).values

    assert [type(message) for message in state["messages"]] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert _session(state).entry["memoryFlush"]["kind"] == "succeeded"
    assert state["memory_maintenance"]["wrote"] == [FACT]


def test_graph_runs_under_ainvoke(tmp_path: Path):
    _, model, graph = _graph(tmp_path, memory_script())

    state = asyncio.run(
        graph.ainvoke({"messages": [HumanMessage("Our codename is velvetkiwi.")]}, THREAD)
    )

    assert state["messages"][-1].content == "reply 1"
    assert state["memory_maintenance"]["wrote"] == [FACT]
    assert len(model.calls) == 4


def test_invalid_tool_call_gets_the_kit_error_payload(tmp_path: Path):
    def script(call: Call, calls: list[Call]) -> AIMessage:
        if isinstance(call.messages[-1], ToolMessage):
            return AIMessage("I sent broken arguments.")
        broken = {"name": "memory_search", "args": '{"query": ', "id": "call-1", "error": "bad"}
        return AIMessage("", invalid_tool_calls=[broken])

    kit, model, graph = _graph(tmp_path, script)

    state = _say(graph, "Search please.")

    tool_message = state["messages"][2]
    assert (tool_message.tool_call_id, tool_message.status) == ("call-1", "error")
    assert json.loads(tool_message.content) == kit.dispatch(
        "memory_search", '{"query": ', session=_session(state)
    )
    assert model.calls[1].messages[-1] == tool_message
    assert state["messages"][-1].content == "I sent broken arguments."


def test_tools_are_bound_without_strict_mode(tmp_path: Path):
    # bind_tools(strict=True) would make every parameter of the kit's tools required.
    _, model, graph = _graph(tmp_path, memory_script())

    _say(graph, "Our codename is velvetkiwi.")

    assert model.calls and all("strict" not in call.kwargs for call in model.calls)
    tools = model.calls[0].kwargs["tools"]
    search = next(tool for tool in tools if tool["function"]["name"] == "memory_search")
    assert search["function"]["parameters"]["required"] == ["query"]


def _spy(monkeypatch, kit: HostKit, name: str) -> list:
    results = []
    method = getattr(kit, name)

    def spy(*args, **kwargs):
        results.append(method(*args, **kwargs))
        return results[-1]

    monkeypatch.setattr(kit, name, spy)
    return results


def _saved_session_files(root: Path) -> list[Path]:
    return sorted((root / "memory").glob(f"{TODAY}-*.md"))


def test_bare_new_saves_session_memory_and_runs_the_reset_turn(tmp_path: Path, monkeypatch):
    kit, model, graph = _graph(tmp_path, memory_script(usage=1_000))
    news = _spy(monkeypatch, kit, "on_new_session")
    _say(graph, "Our codename is velvetkiwi.")

    state = _say(graph, "/new")

    (new,) = news
    (saved,) = _saved_session_files(tmp_path)
    assert saved == new.saved.path
    assert "user: Our codename is velvetkiwi." in saved.read_text(encoding="utf-8")
    assert "/new" not in saved.read_text(encoding="utf-8")
    row = format_session_reset_transcript_prompt("new", MEMORY_CORE_RUNTIME_IDENTITY)
    assert new.reset.transcript_prompt == row
    assert [(message.type, message.content) for message in state["messages"]][0] == ("human", row)
    assert state["messages"][-1].content == "reply 2"
    # Both model calls of the reset turn get the model prompt in place of the row.
    reset_calls = _chat_calls(model)[2:]
    assert len(reset_calls) == 2
    for call in reset_calls:
        assert call.messages[1].content == new.reset.model_prompt
        assert not any(message.content == row for message in call.messages)
    assert new.reset.prompt in new.reset.model_prompt
    assert state["memory_reset"] is None


def test_new_keeps_the_session_key_and_rotates_the_session_id(tmp_path: Path):
    _, model, graph = _graph(tmp_path, memory_script())
    before = _say(graph, "Our codename is velvetkiwi.")

    after = _say(graph, "/reset")

    old, new = _session(before), _session(after)
    assert (old.session_key, old.session_id) == ("thread-1", "id-1")
    assert (new.session_key, new.session_id) == ("thread-1", "id-2")
    assert after["messages"][0].id == "id-3"
    assert after["messages"][0].content == format_session_reset_transcript_prompt(
        "reset", MEMORY_CORE_RUNTIME_IDENTITY
    )
    # The new session is a new compaction cycle: its due turn flushes again.
    assert old.entry["memoryFlush"] == new.entry["memoryFlush"]
    assert new.entry["sessionId"] == "id-2"
    assert after["memory_maintenance"]["flush"] == "token_threshold"
    assert len(_flush_calls(model)) == 4
    assert (tmp_path / DAILY).read_text(encoding="utf-8") == f"{FACT}\n{FACT}\n"


def test_session_key_mapping_names_the_session(tmp_path: Path):
    _, _, graph = _graph(
        tmp_path, memory_script(usage=1_000), session_key=lambda thread: f"agent:main:{thread}"
    )

    before = _say(graph, "Hello.")
    after = _say(graph, "/new")

    assert _session(before).session_key == _session(after).session_key == "agent:main:thread-1"
    (saved,) = _saved_session_files(tmp_path)
    assert "- **Session Key**: agent:main:thread-1" in saved.read_text(encoding="utf-8")


def test_new_with_text_starts_the_new_session_with_that_text(tmp_path: Path, monkeypatch):
    kit, model, graph = _graph(tmp_path, memory_script(usage=1_000))
    news = _spy(monkeypatch, kit, "on_new_session")
    _say(graph, "Our codename is velvetkiwi.")

    state = _say(graph, "/NEW   What is our codename?")

    (new,) = news
    assert new.reset is None
    assert [message.type for message in state["messages"]] == ["human", "ai", "tool", "ai"]
    assert state["messages"][0].content == "What is our codename?"
    assert _chat_calls(model)[2].messages[1:] == [state["messages"][0]]
    assert len(_saved_session_files(tmp_path)) == 1


def test_reset_prompt_is_not_replayed_on_the_next_turn(tmp_path: Path, monkeypatch):
    kit, model, graph = _graph(tmp_path, memory_script(usage=1_000))
    news = _spy(monkeypatch, kit, "on_new_session")
    _say(graph, "/new")

    _say(graph, "Hello.")

    (new,) = news
    later = _chat_calls(model)[2]
    contents = [message.content for message in later.messages]
    assert contents[1] == new.reset.transcript_prompt
    assert new.reset.model_prompt not in contents
    assert contents[-1] == "Hello."


def test_a_command_that_is_not_first_word_is_an_ordinary_message(tmp_path: Path, monkeypatch):
    kit, _, graph = _graph(tmp_path, memory_script(usage=1_000))
    news = _spy(monkeypatch, kit, "on_new_session")

    state = _say(graph, "please /new")

    assert news == []
    assert state["messages"][0].content == "please /new"


def test_failed_model_call_commits_no_session_state(tmp_path: Path):
    script = memory_script(usage=1_000)
    failing = {"on": False}

    def flaky(call: Call, calls: list[Call]) -> AIMessage:
        if failing["on"]:
            raise RuntimeError("provider down")
        return script(call, calls)

    _, model, graph = _graph(tmp_path, flaky)
    before = _say(graph, "Hello.")
    failing["on"] = True

    with pytest.raises(RuntimeError, match="provider down"):
        _say(graph, "Are you there?")

    stuck = graph.get_state(THREAD)
    assert stuck.next == ("agent",)
    assert stuck.values["memory_session"] == before["memory_session"]
    assert stuck.values["messages"][-1].content == "Are you there?"
    assert stuck.values["memory_turn"] is not None
    # Resume the failed node; the turn completes and is recorded then.
    failing["on"] = False
    resumed = graph.invoke(None, THREAD)
    assert resumed["messages"][-1].content == "reply 2"
    assert resumed["memory_turn"] is None
    assert _session(resumed).entry["totalTokens"] == 1_000
    assert [call.messages[-1].content for call in _chat_calls(model)][-2] == "Are you there?"


def test_failed_flush_turn_records_a_strike_and_keeps_the_reply(tmp_path: Path):
    script = memory_script()

    def failing_flush(call: Call, calls: list[Call]) -> AIMessage:
        if call.is_flush:
            raise RuntimeError("flush model down")
        return script(call, calls)

    _, _, graph = _graph(tmp_path, failing_flush)

    state = _say(graph, "Our codename is velvetkiwi.")

    assert state["messages"][-1].content == "reply 1"
    assert _session(state).entry["memoryFlush"] == {"kind": "failed", "failureCount": 1}
    assert state["memory_maintenance"]["failure"] == {
        "error": "flush model down",
        "failureCount": 1,
        "exhausted": False,
    }
    assert state["memory_maintenance"]["wrote"] == []
    # The target was created before the flush run, as upstream does.
    assert (tmp_path / DAILY).read_text(encoding="utf-8") == ""


def test_redact_and_redactor_reach_the_kit(tmp_path: Path):
    script = memory_script()

    def leaking_flush(call: Call, calls: list[Call]) -> AIMessage:
        if call.is_flush:
            raise RuntimeError("upstream said: token s3cr3t is invalid")
        return script(call, calls)

    _, _, graph = _graph(
        tmp_path,
        leaking_flush,
        redact=lambda text: text.replace("s3cr3t", "[redacted]"),
        redactor=lambda line: line.replace("velvetkiwi", "[codename]"),
    )

    state = _say(graph, "Our codename is velvetkiwi.")
    _say(graph, "/new")

    assert state["memory_maintenance"]["failure"]["error"] == (
        "upstream said: token [redacted] is invalid"
    )
    (saved,) = _saved_session_files(tmp_path)
    text = saved.read_text(encoding="utf-8")
    assert "user: Our codename is [codename]." in text
    assert "velvetkiwi" not in text


def test_redact_maps_a_flush_target_failure(tmp_path: Path):
    # after_turn records a target it cannot create as a strike, without a redact hook of
    # its own; the graph applies the host's redact to the stored message.
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    os.symlink(tmp_path / "elsewhere.md", tmp_path / DAILY)
    _, model, graph = _graph(
        tmp_path, memory_script(), redact=lambda text: text.replace(TODAY, "<date>")
    )

    state = _say(graph, "Our codename is velvetkiwi.")

    failure = state["memory_maintenance"]["failure"]
    assert failure["failureCount"] == 1
    assert "<date>" in failure["error"] and TODAY not in failure["error"]
    assert state["memory_maintenance"]["target"] == DAILY
    assert _flush_calls(model) == []
