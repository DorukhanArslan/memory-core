"""Prompt projection of tool results against the real v2026.9.6 TypeScript.

Each case scripts a sequence of the exported entry points (``truncateOversizedToolResultsInMessages``,
``pruneExpiredCacheTtlToolResults``, ``restoreCacheTtlToolResultProjections``,
``reconcileToolResultPromptProjectionState``, the session-prompt-state serializer and
``truncateOversizedToolResultsInSessionManager`` on a real ``SessionManager``) over one shared
``ToolResultPromptProjectionState``; ``projectToolResultBranch`` is private upstream and is reached
through them. The Python side runs the same script through ``memory_core.tool_result_projection``
and the whole step list, state dumps included, must be equal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import tool_result_projection as projection
from memory_core.preemptive_compaction import (
    _active_branch,
    _read_jsonl_entries,
    truncate_oversized_tool_results_in_session_file,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _dump_state(state: projection.ToolResultPromptProjectionState) -> dict[str, Any]:
    return {
        "replacements": sorted(
            (
                [key, {"cacheTtl": value.get("cacheTtl") or None, "content": _clean(value["content"])}]
                for key, value in state.replacements.items()
            ),
            key=lambda item: item[0],
        ),
        "frozen": sorted(state.frozen),
        "ambiguousBaseKeys": list(state.ambiguous_base_keys),
        "sourceHashByKey": sorted([k, v] for k, v in state.source_hash_by_key.items()),
        "restoredCacheTtl": sorted(
            ([k, _clean(v)] for k, v in state.restored_cache_ttl.items()), key=lambda item: item[0]
        ),
        "lastWrittenSnapshotHash": state.last_written_snapshot_hash,
    }


def _python_steps(steps: list[dict[str, Any]], tmp_path: Path) -> list[dict[str, Any]]:
    state = projection.create_tool_result_prompt_projection_state()
    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        result: dict[str, Any] = {}
        op = step["op"]
        if op == "truncateMessages":
            out = projection.truncate_oversized_tool_results_in_messages(
                step.get("messages", []),
                step.get("contextWindowTokens", 100_000),
                step.get("maxChars"),
                step.get("aggregateMaxChars"),
                None if step.get("withState") is False else state,
            )
            result = {
                "messages": _clean(out.messages),
                "truncatedCount": out.truncated_count,
                "aggregateTruncatedCount": out.aggregate_truncated_count,
                "aggregatePressureEngaged": out.aggregate_pressure_engaged,
                "aggregateBudgetChars": out.aggregate_budget_chars,
            }
        elif op == "prune":
            settings = projection.resolve_cache_ttl_pruning_settings(step.get("config"))
            pruned = False

            def on_pruned() -> None:
                nonlocal pruned
                pruned = True

            if settings is not None:
                out_messages = projection.prune_expired_cache_ttl_tool_results(
                    messages=step.get("messages", []),
                    settings=settings,
                    context_window_tokens=step.get("contextWindowTokens", 100_000),
                    last_cache_touch_at=step.get("lastCacheTouchAt"),
                    drop_thinking_blocks_for_estimate=step.get("dropThinkingBlocksForEstimate") is True,
                    now=step.get("now", 0),
                    projection_state=state,
                    prune_new_rounds=step.get("pruneNewRounds") is not False,
                    on_pruned=on_pruned,
                )
            else:
                out_messages = step.get("messages")
            result = {
                "settings": None
                if settings is None
                else {
                    "ttlMs": settings.ttl_ms,
                    "hardClear": settings.hard_clear,
                    "placeholder": settings.placeholder,
                    "prunable": {
                        name: settings.is_tool_prunable(name) for name in step.get("probeTools", [])
                    },
                },
                "messages": _clean(out_messages),
                "pruned": pruned,
            }
        elif op == "restore":
            projection.restore_cache_ttl_tool_result_projections(state, step.get("entries", []))
        elif op == "reconcile":
            projection.reconcile_tool_result_prompt_projection_state(step.get("messages", []), state)
        elif op == "serialize":
            snapshot = projection.serialize_cache_ttl_tool_result_projections(state)
            persisted: list[Any] = []
            digest = projection.hash_tool_result_projection_snapshot(snapshot)
            projection.persist_tool_result_projections(
                state, lambda custom_type, data: persisted.append({"customType": custom_type, "data": _clean(data)})
            )
            result = {"snapshot": _clean(snapshot), "hash": digest, "persisted": persisted}
        elif op == "session":
            path = tmp_path / f"session-{index}.jsonl"
            entries = step.get("sessionEntries", [])
            path.write_text("".join(f"{json.dumps(entry)}\n" for entry in entries), encoding="utf-8")
            out_session = truncate_oversized_tool_results_in_session_file(
                path,
                context_window_tokens=step.get("contextWindowTokens", 100_000),
                max_chars_override=step.get("maxChars"),
                aggregate_max_chars_override=step.get("aggregateMaxChars"),
                protect_trailing_tool_results=step.get("protectTrailingToolResults", False),
                projection_state=None if step.get("withState") is False else state,
            )
            branch = _active_branch(_read_jsonl_entries(path))
            result = {
                "truncated": out_session.truncated,
                "truncatedCount": out_session.truncated_count,
                "reason": out_session.reason,
                "branchMessages": [e["message"] for e in branch if e.get("type") == "message"],
            }
        else:
            raise AssertionError(op)
        results.append({"op": op, **result, "state": _dump_state(state)})
    return results


def _oracle_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run({"operation": "toolResultProjection", "steps": steps})
    assert result["ok"] is True
    assert result["operation"] == "toolResultProjection"
    return result["result"]["steps"]


def _assert_matches(steps: list[dict[str, Any]], tmp_path: Path) -> list[dict[str, Any]]:
    expected = _oracle_steps(steps)
    actual = _python_steps(steps, tmp_path)
    assert len(actual) == len(expected)
    for index, (python_step, oracle_step) in enumerate(zip(actual, expected, strict=True)):
        assert python_step == oracle_step, f"step {index} ({python_step['op']}) differs"
    return expected


def _text(size: int, label: str = "alpha beta gamma delta") -> str:
    return (label + "\n") * (size // (len(label) + 1) + 1)


def _tool_result(call_id: str | None, text: str, *, timestamp: int | None = None, name: str = "read", **extra: Any) -> dict:
    message: dict[str, Any] = {
        "role": "toolResult",
        "toolName": name,
        "content": [{"type": "text", "text": text}],
        "isError": False,
        **extra,
    }
    if call_id is not None:
        message["toolCallId"] = call_id
    if timestamp is not None:
        message["timestamp"] = timestamp
    return message


def _assistant(text: str = "ok", *, thinking: str | None = None, tool_args: dict | None = None) -> dict:
    content: list[dict[str, Any]] = []
    if thinking is not None:
        content.append({"type": "thinking", "thinking": thinking, "thinkingSignature": "sig"})
    content.append({"type": "text", "text": text})
    if tool_args is not None:
        content.append({"type": "toolCall", "id": "x", "name": "read", "arguments": tool_args})
    return {"role": "assistant", "content": content}


def _conversation(results: int, size: int, *, name: str = "read") -> list[dict[str, Any]]:
    """user, then ``results`` (assistant, tool result) rounds, then a closing assistant turn."""

    messages: list[dict[str, Any]] = [{"role": "user", "content": "please look"}]
    for index in range(results):
        messages.append(_assistant(f"round {index}", thinking="considering", tool_args={"path": f"f{index}"}))
        messages.append(_tool_result(f"call_{index}", _text(size, f"line {index}"), timestamp=100 + index, name=name))
    messages.append(_assistant("done one"))
    messages.append({"role": "user", "content": "more"})
    messages.append(_assistant("done two"))
    messages.append(_assistant("done three"))
    return messages


CACHE_TTL = {"mode": "cache-ttl", "ttl": "5m"}
PRUNE_DEFAULTS = {
    "op": "prune",
    "config": CACHE_TTL,
    "lastCacheTouchAt": 1_000,
    "now": 1_000 + 10 * 60_000,
    "dropThinkingBlocksForEstimate": True,
}


def test_projection_truncate_messages_freezes_and_replays(tmp_path: Path):
    messages = _conversation(3, 9_000)
    steps = [
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 3_000, "aggregateMaxChars": 6_000},
        {"op": "serialize"},
        # Replay: the frozen replacements apply again to the unchanged canonical messages.
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 3_000, "aggregateMaxChars": 6_000},
        # A larger budget does not undo what was already frozen.
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 200_000},
        {"op": "serialize"},
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 3_000, "withState": False},
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[0]["truncatedCount"] >= 1
    assert expected[0]["state"]["frozen"]
    assert expected[1]["persisted"], "a frozen state persists a marker"


def test_projection_truncate_protects_trailing_tool_results(tmp_path: Path):
    messages = _conversation(2, 8_000)[:-4]  # ends on the pending tool result batch
    messages.append(_tool_result("call_late", _text(12_000, "late"), timestamp=900))
    steps = [
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 2_500, "aggregateMaxChars": 3_000},
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 2_500, "aggregateMaxChars": 3_000},
    ]
    _assert_matches(steps, tmp_path)


def test_projection_cache_ttl_soft_prunes_and_replays(tmp_path: Path):
    messages = _conversation(4, 9_000)
    steps = [
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000},
        {"op": "serialize"},
        # TTL gates new edits only: a fresh cache touch still replays the frozen bytes.
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000, "now": 1_500},
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000, "pruneNewRounds": False},
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 8_000},
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[0]["pruned"] is True
    assert any(
        value["cacheTtl"] == "soft" for _key, value in expected[0]["state"]["replacements"]
    )


def test_projection_cache_ttl_hard_clears_when_budget_is_exhausted(tmp_path: Path):
    messages = _conversation(22, 3_800)
    steps = [
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 20_000},
        {"op": "serialize"},
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 20_000},
    ]
    expected = _assert_matches(steps, tmp_path)
    assert any(value["cacheTtl"] == "hard" for _key, value in expected[0]["state"]["replacements"])


def test_projection_cache_ttl_hard_clear_disabled_and_custom_placeholder(tmp_path: Path):
    messages = _conversation(22, 3_800)
    config = {"mode": "cache-ttl", "ttl": "1m", "hardClear": {"enabled": False, "placeholder": "  x  "}}
    cleared = {"mode": "cache-ttl", "ttl": "90s", "hardClear": {"placeholder": "  [gone]  "}}
    steps = [
        {**PRUNE_DEFAULTS, "config": config, "messages": messages, "contextWindowTokens": 20_000},
        {**PRUNE_DEFAULTS, "config": cleared, "messages": messages, "contextWindowTokens": 20_000},
        {"op": "serialize"},
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[1]["settings"]["placeholder"] == "[gone]"


@pytest.mark.parametrize(
    "config",
    [
        None,
        {"mode": "off"},
        {"mode": "cache-ttl"},
        {"mode": "cache-ttl", "ttl": "not a duration"},
        {"mode": "cache-ttl", "ttl": "2h30m"},
        {"mode": "cache-ttl", "ttl": "7"},
        {"mode": "cache-ttl", "tools": {"deny": ["Exec*", "web_FETCH"], "allow": ["*read*", "exec_x"]}},
        {"mode": "cache-ttl", "tools": {"allow": ["*"]}},
        {"mode": "cache-ttl", "tools": {"allow": ["", "  "]}, "hardClear": {"enabled": None}},
    ],
)
def test_projection_cache_ttl_settings(tmp_path: Path, config):
    steps = [
        {
            **PRUNE_DEFAULTS,
            "config": config,
            "messages": [{"role": "user", "content": "hi"}],
            "probeTools": ["read", "READ_FILE", "exec", "Exec_x", "web_fetch", "", "memory_get"],
        }
    ]
    _assert_matches(steps, tmp_path)


def test_projection_cache_ttl_tool_filters_leave_results_alone(tmp_path: Path):
    messages = _conversation(4, 9_000, name="exec")
    config = {"mode": "cache-ttl", "ttl": "5m", "tools": {"deny": ["exec"]}}
    steps = [{**PRUNE_DEFAULTS, "config": config, "messages": messages, "contextWindowTokens": 8_000}]
    expected = _assert_matches(steps, tmp_path)
    assert expected[0]["pruned"] is False


def test_projection_cache_ttl_below_threshold_and_not_expired(tmp_path: Path):
    messages = _conversation(4, 9_000)
    steps = [
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 1_000_000},
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000, "now": 1_100},
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000, "lastCacheTouchAt": None},
        {**PRUNE_DEFAULTS, "messages": messages[:5], "contextWindowTokens": 8_000},
    ]
    _assert_matches(steps, tmp_path)


def test_projection_cache_ttl_images_and_malformed_blocks(tmp_path: Path):
    messages = _conversation(4, 9_000)
    messages[2]["content"] = [
        {"type": "text", "text": "short"},
        {"type": "image", "data": "abc", "mimeType": "image/png"},
        {"type": "text", "text": 5},
    ]
    messages[4]["content"].append({"type": "image", "data": "x" * 50})
    messages[1]["content"].append({"type": "redacted_thinking", "data": "y" * 4000})
    steps = [
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 6_000},
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 6_000, "dropThinkingBlocksForEstimate": False},
    ]
    _assert_matches(steps, tmp_path)


def _marker(*, soft: list[str] = (), hard: dict[str, str] | None = None, frozen: list[dict] | None = None, ambiguous: list[str] | None = None) -> dict:
    data: dict[str, Any] = {
        "prunedToolResults": [
            *({"key": key, "mode": "soft", "extra": 1} for key in soft),
            *({"key": key, "mode": "hard", "placeholder": text} for key, text in (hard or {}).items()),
        ]
    }
    if ambiguous is not None:
        data["ambiguousToolResultBaseKeys"] = ambiguous
    if frozen is not None:
        data["frozenToolResults"] = frozen
    return {"type": "custom", "customType": "openclaw.cache-ttl", "data": data}


def test_projection_restore_materializes_persisted_marks(tmp_path: Path):
    messages = _conversation(3, 9_000)
    from memory_core.tool_result_projection import hash_tool_result_text

    source_hash = hash_tool_result_text([messages[2]["content"][0]["text"]])
    entries = [
        {"type": "message", "message": {"role": "user", "content": "old"}},
        _marker(
            soft=["tool:call_0:100"],
            hard={"tool:call_1:101": "[wiped]"},
            frozen=[
                {"key": "tool:call_0:100", "sourceHash": source_hash, "texts": ["kept text"]},
                {"key": "tool:call_2:102", "sourceHash": "stale"},
            ],
            ambiguous=["tool:dup"],
        ),
        {"type": "custom", "customType": "other", "data": {}},
    ]
    steps = [
        {"op": "restore", "entries": entries},
        {"op": "serialize"},
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 200_000},
        {"op": "serialize"},
        {"op": "restore", "entries": [{"type": "reset"}, _marker(soft=["tool:call_1:101"])]},
        {"op": "restore", "entries": [_marker(soft=["tool:call_1:101"]), {"type": "reset"}]},
        {"op": "restore", "entries": [_marker(soft=["tool:call_1:101"]), {"type": "custom", "customType": "openclaw.cache-ttl", "data": {"prunedToolResults": "bad"}}]},
        {"op": "reconcile", "messages": messages[:3]},
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[2]["state"]["frozen"]


@pytest.mark.parametrize(
    "data",
    [
        {"prunedToolResults": [{"key": "a", "mode": "firm"}]},
        {"prunedToolResults": [{"key": "a", "mode": "hard"}]},
        {"prunedToolResults": [], "ambiguousToolResultBaseKeys": None},
        {"prunedToolResults": [], "frozenToolResults": [{"key": "a"}]},
        {"prunedToolResults": [], "frozenToolResults": [{"key": "a", "sourceHash": "h", "texts": [1]}]},
        {"prunedToolResults": [], "ambiguousToolResultBaseKeys": ["z", "y"]},
        {"prunedToolResults": [{"key": "a", "mode": "soft", "placeholder": 3}]},
    ],
)
def test_projection_restore_schema(tmp_path: Path, data):
    steps = [
        {"op": "restore", "entries": [{"type": "custom", "customType": "openclaw.cache-ttl", "data": data}]},
        {"op": "serialize"},
    ]
    _assert_matches(steps, tmp_path)


def test_projection_ambiguous_tool_call_ids(tmp_path: Path):
    big = _text(8_000, "dup")
    messages = [
        {"role": "user", "content": "go"},
        _assistant("a"),
        _tool_result("dup", big, timestamp=1),
        _tool_result("dup", big, timestamp=1),
        _tool_result("dup", _text(8_000, "other"), timestamp=1),
        _tool_result(None, _text(8_000, "nokey")),
        _tool_result(None, _text(8_000, "stamp"), timestamp=7),
        _tool_result("with-id", _text(8_000, "withid"), id="m-1"),
        _tool_result("with-id", _text(8_000, "withid2"), id="m-2"),
    ]
    steps = [
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 2_500, "aggregateMaxChars": 100_000},
        {"op": "serialize"},
        {"op": "truncateMessages", "messages": list(reversed(messages[2:5])), "contextWindowTokens": 2_000, "maxChars": 2_500, "aggregateMaxChars": 100_000},
        {"op": "reconcile", "messages": messages[:4]},
        {"op": "serialize"},
        {"op": "reconcile", "messages": []},
    ]
    _assert_matches(steps, tmp_path)


def test_projection_reconcile_drops_rewritten_sources(tmp_path: Path):
    messages = _conversation(3, 9_000)
    rewritten = json.loads(json.dumps(messages))
    rewritten[2]["content"][0]["text"] = "rewritten canonical text"
    steps = [
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 2_000, "maxChars": 3_000},
        {"op": "reconcile", "messages": rewritten},
        {"op": "truncateMessages", "messages": rewritten, "contextWindowTokens": 2_000, "maxChars": 3_000},
    ]
    _assert_matches(steps, tmp_path)


def _session(messages: list[dict[str, Any]], *, compaction_at: int | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    parent: str | None = None
    for index, message in enumerate(messages):
        entry_id = f"e{index}"
        entries.append(
            {
                "type": "message",
                "id": entry_id,
                "parentId": parent,
                "timestamp": "2026-05-30T00:00:00.000Z",
                "message": message,
            }
        )
        parent = entry_id
        if compaction_at is not None and index == compaction_at:
            entries.append(
                {
                    "type": "compaction",
                    "id": "c1",
                    "parentId": parent,
                    "timestamp": "2026-05-30T00:00:00.000Z",
                    "summary": "earlier work",
                    "firstKeptEntryId": f"e{max(0, index - 3)}",
                    "tokensBefore": 5_000,
                }
            )
            parent = "c1"
    return entries


def test_projection_session_recovery_rewrites_frozen_projections(tmp_path: Path):
    messages = _conversation(4, 9_000)
    steps = [
        # A TTL prune freezes soft projections; recovery then writes those bytes into the transcript.
        {**PRUNE_DEFAULTS, "messages": messages, "contextWindowTokens": 8_000},
        {
            "op": "session",
            "sessionEntries": _session(messages),
            "contextWindowTokens": 8_000,
            "maxChars": 2_000,
            "aggregateMaxChars": 5_000,
        },
        {"op": "serialize"},
        {
            "op": "session",
            "sessionEntries": _session(messages),
            "contextWindowTokens": 8_000,
            "maxChars": 2_000,
            "aggregateMaxChars": 5_000,
            "withState": False,
        },
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[1]["truncated"] is True


def test_projection_session_frozen_history_stays_reducible_under_recovery(tmp_path: Path):
    messages = _conversation(3, 9_000)
    steps = [
        {"op": "truncateMessages", "messages": messages, "contextWindowTokens": 200_000, "aggregateMaxChars": 10_000_000},
        {
            "op": "session",
            "sessionEntries": _session(messages),
            "contextWindowTokens": 200_000,
            "maxChars": 100_000,
            "aggregateMaxChars": 8_000,
            "protectTrailingToolResults": True,
        },
    ]
    _assert_matches(steps, tmp_path)


def test_projection_session_context_window_follows_compaction(tmp_path: Path):
    messages = _conversation(4, 9_000)
    steps = [
        {
            "op": "session",
            "sessionEntries": _session(messages, compaction_at=6),
            "contextWindowTokens": 8_000,
            "maxChars": 2_000,
            "aggregateMaxChars": 4_000,
        },
    ]
    expected = _assert_matches(steps, tmp_path)
    assert expected[0]["truncated"] is True


def test_projection_session_without_oversized_results(tmp_path: Path):
    messages = [{"role": "user", "content": "hi"}, _assistant("hello")]
    steps = [
        {"op": "session", "sessionEntries": _session(messages), "contextWindowTokens": 8_000},
        {"op": "session", "sessionEntries": [], "contextWindowTokens": 8_000},
    ]
    _assert_matches(steps, tmp_path)
