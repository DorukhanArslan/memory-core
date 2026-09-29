"""The LangGraph agent of examples/langgraph_agent.py against a real chat model.

Opt-in: MEMORY_CORE_LIVE_OPENAI=1 with OPENAI_API_KEY and OPENAI_MODEL (OPENAI_BASE_URL for an
endpoint other than OpenAI's). memory-core picks no model, so the test skips without
OPENAI_MODEL. The workspace is FTS-only; the flush window is chosen so that every turn with real
usage is past the flush threshold. A real model can vary, so each assertion names its step.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pytest

from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState
from memory_core.memory_flush import build_memory_flush_plan, resolve_memory_flush_threshold
from memory_core.project_name import ENV_PREFIX

LIVE_FLAG = f"{ENV_PREFIX}LIVE_OPENAI"

pytestmark = pytest.mark.skipif(
    os.environ.get(LIVE_FLAG) != "1"
    or not os.environ.get("OPENAI_API_KEY")
    or not os.environ.get("OPENAI_MODEL"),
    reason=f"{LIVE_FLAG}=1, OPENAI_API_KEY and OPENAI_MODEL are required for the live agent test",
)


def _window_with_a_one_token_threshold(root: Path) -> int:
    for window in range(1, 1_000):
        plan = build_memory_flush_plan(workspace_dir=root, context_window_tokens=window)
        threshold = resolve_memory_flush_threshold(
            context_window_tokens=window,
            reserve_tokens_floor=plan.reserve_tokens_floor,
            soft_threshold_tokens=plan.soft_threshold_tokens,
        )
        if threshold == 1:
            return window
    raise AssertionError("no window gives a one-token flush threshold")


def _say(graph, text: str, config: dict) -> dict:
    from langchain_core.messages import HumanMessage

    return graph.invoke({"messages": [HumanMessage(text)]}, config)


def test_live_langgraph_agent_flushes_and_recalls_across_new(tmp_path: Path):
    pytest.importorskip("langgraph")
    chat_openai = pytest.importorskip("langchain_openai").ChatOpenAI
    import examples.langgraph_agent as example

    root = tmp_path / "workspace"
    kit = HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    )
    model = chat_openai(
        model=os.environ["OPENAI_MODEL"],
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        stream_usage=True,
        max_tokens=example.DEFAULT_MAX_TOKENS,
    )
    graph = example.build_graph(
        kit, model, context_window_tokens=_window_with_a_one_token_threshold(root)
    )
    config = {"configurable": {"thread_id": "live-thread"}}
    codename = f"orchid-{secrets.token_hex(3)}"

    first = _say(
        graph,
        f"Please remember this durable fact: our project codename is {codename}.",
        config,
    )

    maintenance = first["memory_maintenance"]
    session = SessionState.from_json(first["memory_session"])
    assert first["messages"][-1].type == "ai", "turn 1: no reply"
    assert isinstance(session.entry.get("totalTokens"), int), (
        f"turn 1: no provider usage reached the kit: {maintenance}"
    )
    assert maintenance["flush"] == "token_threshold", f"turn 1: flush not due: {maintenance}"
    assert maintenance["failure"] is None, f"turn 1: flush turn failed: {maintenance}"
    assert session.entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}, (
        f"turn 1: cycle not stamped: {dict(session.entry)}"
    )
    daily = (root / maintenance["target"]).read_text(encoding="utf-8")
    assert codename in daily, f"turn 1: the flush did not write the codename: {daily!r}"

    reset = _say(graph, "/new", config)

    assert reset["messages"][-1].type == "ai", "/new: no reset reply"
    assert (
        SessionState.from_json(reset["memory_session"]).session_id != session.session_id
    ), "/new: the session id did not rotate"

    later = _say(graph, "What is our project codename? Check your memory.", config)

    reply = later["messages"][-1].text
    asked = max(
        index for index, message in enumerate(later["messages"]) if message.type == "human"
    )
    found_by = [
        f"{message.name}: {_result_paths(message.content)}"
        for message in later["messages"][asked:]
        if message.type == "tool" and codename in message.content
    ]
    in_transcript = [
        message.type
        for message in later["messages"][:asked]
        if codename in str(message.content)
    ]
    path = found_by or (f"the reset turn's transcript ({in_transcript})" if in_transcript else None)
    print(f"live agent: the codename came by {path}")
    assert codename.lower() in reply.lower(), (
        f"after /new: the reply lacks the codename (found by: {path}): {reply!r}"
    )
    assert path is not None, "after /new: the reply names the codename, but no memory path did"


def _result_paths(content: str) -> list[str]:
    payload = json.loads(content)
    hits = payload.get("results") or [payload]
    return sorted({hit["path"] for hit in hits if isinstance(hit.get("path"), str)})
