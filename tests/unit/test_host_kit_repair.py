"""HostKit.repair_tool_calls(): upstream's replay repair over host rows (docs/host_kit.md, F26)."""

from __future__ import annotations

import pytest

from memory_core import ToolCallRepair
from memory_core._transcript_repair_constants import DEFAULT_MISSING_TOOL_RESULT_TEXT
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit
from memory_core.replay_repair import (
    sanitize_tool_call_inputs,
    sanitize_tool_use_result_pairing_for_model,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC

USER = {"role": "user", "content": "Search please."}
LATER = {"role": "user", "content": "Are you there?"}


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False, reindex=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, seed_bootstrap=False, **options)


def _call(call_id, name="memory_search", args=None) -> dict:
    return {"id": call_id, "name": name, "args": {"query": "x"} if args is None else args}


def _ask(*calls, content="") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": list(calls)}


def _answer(call_id, text="{}", name="memory_search", **extra) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": text, **extra}


def _shape(repair: ToolCallRepair) -> list[tuple]:
    shape = []
    for row in repair.messages:
        if row.get("role") == "assistant":
            shape.append(("assistant", tuple(call.get("id") for call in row.get("tool_calls", ()))))
        elif row.get("role") == "tool":
            shape.append(("tool", row["tool_call_id"]))
        else:
            shape.append((row.get("role"), row.get("content")))
    return shape


def _upstream_shape(messages: list[dict]) -> list[tuple]:
    shape = []
    for message in messages:
        if message.get("role") == "assistant":
            calls = [b["id"] for b in message["content"] if b.get("type") == "toolCall"]
            shape.append(("assistant", tuple(calls)))
        elif message.get("role") == "toolResult":
            shape.append(("tool", message["toolCallId"]))
        else:
            shape.append((message["role"], message["content"]))
    return shape


def _upstream(rows: list[dict]) -> list[dict]:
    """The host rows in upstream's message shape, written out by hand."""
    out = []
    for row in rows:
        if row["role"] == "assistant":
            blocks = [{"type": "text", "text": row["content"]}] if row["content"] else []
            for call in row.get("tool_calls", ()):
                blocks.append(
                    {
                        "type": "toolCall",
                        "id": call["id"],
                        "name": call["name"],
                        "arguments": call.get("args"),
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif row["role"] == "tool":
            out.append(
                {
                    "role": "toolResult",
                    "toolCallId": row["tool_call_id"],
                    "toolName": row["name"],
                    "content": [{"type": "text", "text": row["content"]}],
                    "isError": row.get("status") == "error",
                }
            )
        else:
            out.append(row)
    return out


TRANSCRIPTS = {
    "unanswered": [USER, _ask(_call("call-1")), LATER],
    "displaced": [USER, _ask(_call("call-1"), _call("call-2")), LATER, _answer("call-2")],
    "orphan-and-duplicate": [
        USER,
        _answer("orphan"),
        _ask(_call("call-1")),
        _answer("call-1", "first"),
        _answer("call-1", "second"),
        LATER,
    ],
    "repeated-ids": [
        USER,
        _ask(_call("call-1")),
        _answer("call-1", "first"),
        {"role": "assistant", "content": "reply 1"},
        LATER,
        _ask(_call("call-1")),
        _answer("call-1", "second"),
    ],
    "id-less-call": [USER, _ask(_call(None), _call("call-2")), _answer("call-2"), LATER],
    "no-call-left": [USER, _ask(_call(None)), LATER],
    "well-formed": [USER, _ask(_call("call-1")), _answer("call-1"), {"role": "assistant", "content": "ok"}],
}


@pytest.mark.parametrize("name", sorted(TRANSCRIPTS))
def test_repair_equals_the_core_repair_of_the_mapped_messages(tmp_path, name):
    rows = TRANSCRIPTS[name]
    expected = sanitize_tool_use_result_pairing_for_model(
        sanitize_tool_call_inputs(_upstream(rows)), False
    )

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert _shape(repair) == _upstream_shape(expected)
    assert len(repair.sources) == len(repair.messages)


def test_repair_answers_an_unanswered_call_after_its_assistant_row(tmp_path):
    rows = TRANSCRIPTS["unanswered"]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages[:2] == tuple(rows[:2])
    assert repair.messages[1] is rows[1]
    assert repair.messages[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
    }
    assert repair.messages[3] is rows[2]
    assert repair.sources == (0, 1, None, 2)


def test_repair_moves_a_displaced_tool_row_before_the_next_user_row(tmp_path):
    rows = TRANSCRIPTS["displaced"]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert _shape(repair) == [
        ("user", USER["content"]),
        ("assistant", ("call-1", "call-2")),
        ("tool", "call-1"),
        ("tool", "call-2"),
        ("user", LATER["content"]),
    ]
    assert repair.messages[3] is rows[3]
    assert repair.sources == (0, 1, None, 3, 2)


def test_repair_drops_orphan_and_duplicate_tool_rows(tmp_path):
    rows = TRANSCRIPTS["orphan-and-duplicate"]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages == (rows[0], rows[2], rows[3], rows[5])
    assert repair.sources == (0, 2, 3, 5)


def test_repair_keeps_repeated_provider_ids_on_later_turns(tmp_path):
    rows = TRANSCRIPTS["repeated-ids"]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages == tuple(rows)
    assert all(row is original for row, original in zip(repair.messages, rows, strict=True))


def test_repair_drops_a_call_without_an_id_and_an_emptied_assistant_row(tmp_path):
    kit = _kit(tmp_path)
    partly = TRANSCRIPTS["id-less-call"]
    emptied = TRANSCRIPTS["no-call-left"]

    kept = kit.repair_tool_calls(partly)
    gone = kit.repair_tool_calls(emptied)

    assert kept.messages[1] == {**partly[1], "tool_calls": [partly[1]["tool_calls"][1]]}
    assert kept.messages[1]["tool_calls"][0] is partly[1]["tool_calls"][1]
    assert kept.messages[1] is not partly[1] and len(partly[1]["tool_calls"]) == 2
    assert kept.sources == (0, 1, 2, 3)
    assert gone.messages == (emptied[0], emptied[2])
    assert gone.sources == (0, 2)


def test_repair_removes_the_tool_calls_key_when_no_call_is_kept(tmp_path):
    # An empty tool_calls array is rejected by OpenAI; a reply with text stays without the key.
    rows = [USER, _ask(_call(None), content="Let me look."), LATER]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages[1] == {"role": "assistant", "content": "Let me look."}
    assert repair.sources == (0, 1, 2)


def test_repair_reads_openai_and_flat_tool_call_shapes(tmp_path):
    openai = {
        "id": "call-1",
        "type": "function",
        "function": {"name": " memory_get ", "arguments": '{"path": "MEMORY.md"}'},
    }
    flat = {"id": "call-2", "name": "memory_search ", "arguments": '{"query": "x"}'}
    rows = [USER, _ask(openai, flat), _answer("call-1", name="memory_get")]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    calls = repair.messages[1]["tool_calls"]
    assert calls == [
        {**openai, "function": {**openai["function"], "name": "memory_get"}},
        {**flat, "name": "memory_search"},
    ]
    assert openai["function"]["name"] == " memory_get "
    assert repair.messages[3] == {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
    }


def test_repair_gives_a_paired_legacy_tool_row_its_call_id(tmp_path):
    # normalizeLegacyToolResultId: an id-less result of a frame's only call belongs to it.
    legacy = {"role": "tool", "name": "memory_search", "content": "{}"}
    blank_name = _answer("call-2", name="  ")
    rows = [USER, _ask(_call("call-1")), legacy, _ask(_call("call-2")), blank_name]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages[2] == {**legacy, "tool_call_id": "call-1"}
    # A row changed only by the tool-name normalization comes back as the host's object.
    assert repair.messages[4] is blank_name
    assert repair.sources == (0, 1, 2, 3, 4)


@pytest.mark.parametrize("blank", ["", "  "])
def test_repair_gives_a_blank_id_tool_row_its_call_id(tmp_path, blank):
    # extractToolResultIds trims a blank id to nothing, so the row is id-less upstream and
    # normalizeLegacyToolResultId pairs it with its frame's only call: the model must get that
    # call's id, never the blank one.
    row = _answer(blank)
    rows = [USER, _ask(_call("call-1")), row]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages[2] == {**row, "tool_call_id": "call-1"}
    assert row["tool_call_id"] == blank
    assert repair.sources == (0, 1, 2)


def test_repair_marks_a_paired_legacy_tool_row_with_a_status_as_an_error(tmp_path):
    # normalizeLegacyToolResultId returns the paired result with isError: true, which a row
    # carrying the kit's status field reads as status "error"; a row without one keeps its
    # plain shape (a strict validator rejects extra keys).
    success = _answer(None, status="success")
    del success["tool_call_id"]
    rows = [USER, _ask(_call("call-1")), success]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages[2] == {**success, "tool_call_id": "call-1", "status": "error"}
    assert success["status"] == "success"
    blank = _answer("", status="success")
    (_, _, paired) = _kit(tmp_path).repair_tool_calls([USER, _ask(_call("call-1")), blank]).messages
    assert paired == {**blank, "tool_call_id": "call-1", "status": "error"}


def test_repair_leaves_content_tool_call_blocks_unread(tmp_path):
    # An Anthropic-style message carries each call as a content block and in tool_calls; only
    # tool_calls is read, so the call counts once and the blocks come back as they were.
    blocks = [
        {"type": "text", "text": "Searching."},
        {"type": "tool_use", "id": "call-1", "name": "memory_search", "input": {"query": "x"}},
        {"type": "tool_use", "id": "call-9", "name": "memory_search", "input": {}},
    ]
    row = {"role": "assistant", "content": blocks, "tool_calls": [_call("call-1")]}
    rows = [USER, row, _answer("call-1")]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert repair.messages == tuple(rows)
    assert repair.messages[1] is row


def test_repair_passes_the_allowed_tool_names(tmp_path):
    rows = [USER, _ask(_call("call-1"), _call("call-2", name="web_search")), LATER]

    repair = _kit(tmp_path).repair_tool_calls(rows, allowed_tool_names=["MEMORY_SEARCH"])
    unrestricted = _kit(tmp_path).repair_tool_calls(rows)

    assert _shape(repair) == [
        ("user", USER["content"]),
        ("assistant", ("call-1",)),
        ("tool", "call-1"),
        ("user", LATER["content"]),
    ]
    assert _shape(unrestricted)[1:4] == [
        ("assistant", ("call-1", "call-2")),
        ("tool", "call-1"),
        ("tool", "call-2"),
    ]
    # A call that already has a real result stays although its tool is no longer offered.
    answered = [USER, _ask(_call("call-3", name="web_search")), _answer("call-3", name="web_search")]
    assert _kit(tmp_path).repair_tool_calls(
        answered, allowed_tool_names=["memory_search"]
    ).messages == tuple(answered)


def test_repair_returns_the_host_rows_themselves_when_nothing_changes(tmp_path):
    rows = TRANSCRIPTS["well-formed"] + [{"role": "system", "content": "x"}, {"role": "custom"}]

    repair = _kit(tmp_path).repair_tool_calls(rows)

    assert isinstance(repair, ToolCallRepair)
    assert all(row is original for row, original in zip(repair.messages, rows, strict=True))
    assert repair.sources == tuple(range(len(rows)))
    assert _kit(tmp_path).repair_tool_calls([]) == ToolCallRepair(messages=(), sources=())


def test_repair_sources_point_at_the_host_rows(tmp_path):
    for rows in TRANSCRIPTS.values():
        repair = _kit(tmp_path).repair_tool_calls(rows)
        for row, source in zip(repair.messages, repair.sources, strict=True):
            if source is None:
                assert row["content"] == DEFAULT_MISSING_TOOL_RESULT_TEXT
            elif row is not rows[source]:
                assert row["role"] in ("assistant", "tool")
                assert row["role"] == rows[source]["role"]


def test_repair_synthetic_row_is_plain_chat_completions(tmp_path):
    rows = TRANSCRIPTS["unanswered"]

    for kit in (_kit(tmp_path / "a"), _kit(tmp_path / "b", identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)):
        synthetic = kit.repair_tool_calls(rows).messages[2]
        assert synthetic == {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
        }
    assert DEFAULT_MISSING_TOOL_RESULT_TEXT.startswith("[openclaw] missing tool result")


def test_repair_rejects_a_row_that_is_not_a_mapping(tmp_path):
    kit = _kit(tmp_path)

    for rows in ([USER, "not a row"], [USER, None], "rows", [_ask("not a call")]):
        with pytest.raises(TypeError):
            kit.repair_tool_calls(rows)


def test_repair_touches_no_file(tmp_path):
    kit = _kit(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    for rows in TRANSCRIPTS.values():
        kit.repair_tool_calls(rows)

    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
