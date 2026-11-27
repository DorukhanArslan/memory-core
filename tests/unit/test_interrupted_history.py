import asyncio
from copy import deepcopy

import pytest

from memory_core.compaction_replay import ReplayModel
from memory_core.host import ProviderTurnExecutor
from memory_core.host.recovery_history import recovered_session_messages
from memory_core.replay_repair import DEFAULT_MISSING_TOOL_RESULT_TEXT
from memory_core.session_context import build_session_context, convert_to_llm
from tests.unit.test_host_publication_settlement import ID, KEY, _interrupted_turn, _runner


def event(turn, index, role, **fields):
    return {"type": "message", "id": f"{turn}:message:{index}", "message": {"role": role, **fields}}


def call(tool_id):
    return {"type": "toolCall", "id": tool_id, "name": "write", "arguments": {}}


def continuation(events):
    context = build_session_context(events)
    return {"visibleEvents": events, "context": context, "llmMessages": convert_to_llm(context["messages"])}


@pytest.mark.parametrize("responses", [False, True])
def test_mixed_results_are_synthesized_only_for_the_original_call_occurrence(responses):
    cut = "old:message:owner"
    source = continuation([
        event(cut, 0, "assistant", content=[call("finished"), call("reused")]),
        event(cut, 1, "toolResult", toolCallId="finished", toolName="write", content="saved"),
        event("later", 0, "assistant", content=[call("reused")]),
        event("later", 1, "toolResult", toolCallId="reused", toolName="write", content="new receipt"),
    ])
    before = deepcopy(source)
    llm, projection = recovered_session_messages(source, {cut}, now_ms=27, responses=responses)
    assert len(llm) == len(projection) == 5
    assert llm == projection
    assert [row["content"] for row in llm if row["role"] == "toolResult"] == [
        "saved", [{"type": "text", "text": "aborted" if responses else DEFAULT_MISSING_TOOL_RESULT_TEXT}],
        "new receipt",
    ]
    assert llm[2]["toolCallId"] == "reused" and llm[2]["isError"] is True
    assert source == before


def test_compacted_out_or_failed_calls_cannot_create_a_repair_message():
    source = continuation([
        event("cut", 0, "assistant", content=[call("hidden")]),
        {"type": "compaction", "id": "summary", "summary": "New topic", "tokensBefore": 5,
         "timestamp": "2026-11-27T10:00:00Z"},
        event("cut", 1, "assistant", stopReason="aborted", content=[call("failed")]),
    ])
    llm, projection = recovered_session_messages(source, {"cut"}, now_ms=27)
    assert llm is source["llmMessages"]
    assert projection is source["context"]["messages"]
    assert all(row["role"] != "toolResult" for row in llm)


def test_provider_executor_uses_responses_missing_result_without_explicit_history_replay(tmp_path):
    runner = _runner(tmp_path, interrupted_publication="openclaw")
    _interrupted_turn(runner)
    received = []

    async def stream(request):
        received.extend(r for r in request["messages"] if r.get("toolCallId") == "old-write")
        return {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "Four."}]}

    async def summarize(request):
        pytest.fail("The short follow-up should fit in the provider context")

    executor = ProviderTurnExecutor(ReplayModel("openai", "openai-responses", "gpt-5.4"), 128_000, stream, summarize)
    result = asyncio.run(runner.run_turn("Two plus two?", execute=executor, request_id="new"))
    assert not result.failures
    [missing] = received
    assert missing["isError"] is True and missing["content"] == [{"type": "text", "text": "aborted"}]
    stored = runner.catalog.read_continuation(ID, session_key=KEY)["context"]["messages"]
    assert all(r.get("toolCallId") != "old-write" for r in stored)
