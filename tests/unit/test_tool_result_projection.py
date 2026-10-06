import json

from memory_core import tool_result_projection as projection
from memory_core.preemptive_compaction import truncate_oversized_tool_results_in_session_file


def _result(call_id: str, text: str, timestamp: int, name: str = "read") -> dict:
    return {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": name,
        "content": [{"type": "text", "text": text}],
        "timestamp": timestamp,
    }


def _assistant(text: str = "ok") -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _conversation(rounds: int, size: int) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": "go"}]
    for index in range(rounds):
        messages.append(_assistant(f"round {index}"))
        messages.append(_result(f"call_{index}", ("line of output\n" * size)[:size], 100 + index))
    messages.extend([_assistant("one"), {"role": "user", "content": "more"}, _assistant("two"), _assistant("three")])
    return messages


PRUNE = {
    "config": {"mode": "cache-ttl", "ttl": "5m"},
    "last_cache_touch_at": 1_000,
    "now": 1_000 + 10 * 60_000,
    "drop_thinking_blocks_for_estimate": True,
    "prune_new_rounds": True,
}


def _prune(messages, state, **overrides):
    options = {**PRUNE, **overrides}
    settings = projection.resolve_cache_ttl_pruning_settings(options.pop("config"))
    assert settings is not None
    return projection.prune_expired_cache_ttl_tool_results(
        messages=messages, settings=settings, context_window_tokens=8_000, projection_state=state, **options
    )


def test_cache_ttl_soft_prune_trims_and_freezes_then_replays_while_fresh():
    messages = _conversation(4, 9_000)
    state = projection.create_tool_result_prompt_projection_state()

    pruned = _prune(messages, state)
    text = pruned[2]["content"][0]["text"]
    assert "[Tool result trimmed: kept first 1500 chars and last 1500 chars of 9000 chars.]" in text
    assert {"tool:call_0:100", "tool:call_1:101"} <= state.frozen
    assert state.replacements["tool:call_0:100"]["cacheTtl"] == "soft"
    # The canonical transcript is untouched.
    assert len(messages[2]["content"][0]["text"]) == 9_000

    # TTL gates new edits only: a fresh cache touch still replays the frozen bytes.
    replay = _prune(messages, state, now=1_500)
    assert replay[2]["content"][0]["text"] == text
    # With no new rounds allowed nothing is edited, frozen bytes still replay.
    assert _prune(_conversation(4, 9_000), projection.create_tool_result_prompt_projection_state(), prune_new_rounds=False)[2] == messages[2]


def test_cache_ttl_hard_clear_replaces_old_results_with_the_placeholder():
    messages = _conversation(22, 3_800)
    state = projection.create_tool_result_prompt_projection_state()
    settings = projection.resolve_cache_ttl_pruning_settings(
        {"mode": "cache-ttl", "ttl": "5m", "hardClear": {"placeholder": " [gone] "}}
    )
    pruned = projection.prune_expired_cache_ttl_tool_results(
        messages=messages,
        settings=settings,
        context_window_tokens=20_000,
        last_cache_touch_at=1_000,
        drop_thinking_blocks_for_estimate=False,
        now=10 * 60_000,
        projection_state=state,
        prune_new_rounds=True,
    )
    cleared = [m for m in pruned if m.get("content") == [{"type": "text", "text": "[gone]"}]]
    assert cleared
    assert "hard" in {r["cacheTtl"] for r in state.replacements.values()}


def test_cache_ttl_settings_follow_the_config():
    assert projection.resolve_cache_ttl_pruning_settings({"mode": "off"}) is None
    settings = projection.resolve_cache_ttl_pruning_settings(
        {"mode": "cache-ttl", "ttl": "bogus", "tools": {"deny": ["Exec*"], "allow": ["*read*", "exec_x"]}}
    )
    assert settings.ttl_ms == 5 * 60_000
    assert settings.hard_clear is True
    assert settings.is_tool_prunable("read_file")
    assert not settings.is_tool_prunable("EXEC_x")
    assert not settings.is_tool_prunable("web_fetch")


def test_projection_marker_round_trips_through_restore():
    messages = _conversation(4, 9_000)
    first = projection.create_tool_result_prompt_projection_state()
    pruned = _prune(messages, first)
    persisted: list[tuple[str, dict]] = []
    projection.persist_tool_result_projections(first, lambda kind, data: persisted.append((kind, data)))
    projection.persist_tool_result_projections(first, lambda kind, data: persisted.append((kind, data)))
    assert len(persisted) == 1, "an unchanged snapshot is not written twice"

    restored = projection.create_tool_result_prompt_projection_state()
    projection.restore_cache_ttl_tool_result_projections(
        restored, [{"type": "custom", "customType": persisted[0][0], "data": persisted[0][1]}]
    )
    assert restored.last_written_snapshot_hash == first.last_written_snapshot_hash
    # The marks materialize on the next replay, whether or not TTL pruning is still on.
    replayed = projection.truncate_oversized_tool_results_in_messages(
        messages, 200_000, projection_state=restored
    ).messages
    assert replayed[2]["content"] == pruned[2]["content"]
    assert restored.frozen == first.frozen


def test_restore_stops_at_reset_and_skips_invalid_snapshots():
    state = projection.create_tool_result_prompt_projection_state()
    marker = {
        "type": "custom",
        "customType": "openclaw.cache-ttl",
        "data": {"prunedToolResults": [{"key": "tool:a:1", "mode": "soft"}]},
    }
    projection.restore_cache_ttl_tool_result_projections(state, [marker, {"type": "reset"}])
    assert state.restored_cache_ttl == {}
    bad = {**marker, "data": {"prunedToolResults": [{"key": "x", "mode": "hard"}]}}
    projection.restore_cache_ttl_tool_result_projections(state, [marker, bad])
    assert state.restored_cache_ttl == {"tool:a:1": {"mode": "soft"}}


def test_ambiguous_tool_call_ids_get_stable_fallback_keys():
    messages = [
        {"role": "user", "content": "go"},
        _assistant(),
        _result("dup", "same", 1),
        _result("dup", "same", 1),
        _result("dup", "other", 1),
    ]
    state = projection.create_tool_result_prompt_projection_state()
    keys = projection.get_tool_result_projection_keys(messages, state)
    assert list(state.ambiguous_base_keys) == ["tool:dup:1"]
    assert len(set(keys[2:])) == 3
    assert keys[2].endswith(":0") and keys[3].endswith(":1")
    # A later call sees the same identities.
    assert projection.get_tool_result_projection_keys(messages, state) == keys


def test_reconcile_drops_projections_of_rewritten_sources():
    messages = _conversation(3, 9_000)
    state = projection.create_tool_result_prompt_projection_state()
    projection.truncate_oversized_tool_results_in_messages(messages, 2_000, 3_000, projection_state=state)
    assert state.frozen
    rewritten = json.loads(json.dumps(messages))
    rewritten[2]["content"][0]["text"] = "different"
    projection.reconcile_tool_result_prompt_projection_state(rewritten, state)
    assert "tool:call_0:100" not in state.frozen
    assert "tool:call_1:101" in state.frozen


def test_truncate_in_messages_protects_the_trailing_batch_only_with_state():
    messages = [
        {"role": "user", "content": "go"},
        _assistant(),
        _result("old", "alpha beta\n" * 600, 1),
        _assistant(),
        _result("new", "gamma delta\n" * 600, 2),
    ]
    with_state = projection.truncate_oversized_tool_results_in_messages(
        messages, 2_000, 2_000, 2_500, projection.create_tool_result_prompt_projection_state()
    )
    without = projection.truncate_oversized_tool_results_in_messages(messages, 2_000, 2_000, 2_500)
    assert with_state.truncated_count == without.truncated_count == 2
    assert with_state.aggregate_pressure_engaged and without.aggregate_pressure_engaged


def test_session_recovery_rewrites_frozen_projections_and_follows_the_compaction_window(tmp_path):
    messages = _conversation(4, 9_000)
    state = projection.create_tool_result_prompt_projection_state()
    _prune(messages, state)

    entries: list[dict] = []
    parent = None
    for index, message in enumerate(messages):
        entry = {"type": "message", "id": f"e{index}", "parentId": parent, "message": message}
        entries.append(entry)
        parent = entry["id"]
    entries.append(
        {"type": "compaction", "id": "c1", "parentId": parent, "summary": "s", "firstKeptEntryId": "e6", "tokensBefore": 1}
    )
    path = tmp_path / "session.jsonl"
    path.write_text("".join(f"{json.dumps(e)}\n" for e in entries), encoding="utf-8")

    result = truncate_oversized_tool_results_in_session_file(
        path, context_window_tokens=8_000, max_chars_override=2_000, projection_state=state
    )

    assert result.truncated is True
    # Entries before the first kept one are outside the window: call_0 stays untouched.
    assert len(result.tool_texts[0]) == 9_000
    assert all(len(text) < 9_000 for text in result.tool_texts[2:])
    rewritten = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    appended_compaction = [e for e in rewritten if e.get("type") == "compaction"][-1]
    appended_ids = {e["id"] for e in rewritten[len(entries) :]}
    assert appended_compaction["firstKeptEntryId"] in appended_ids
    assert "projection_key" not in json.dumps(rewritten)


def test_session_context_entries_window():
    branch = [
        {"id": "a", "type": "message", "message": {"role": "user", "content": "1"}},
        {"id": "b", "type": "message", "message": {"role": "assistant", "content": []}},
        {"id": "c", "type": "message", "message": {"role": "user", "content": "2", "excludeFromContext": True}},
        {"id": "d", "type": "compaction", "firstKeptEntryId": "b"},
        {"id": "e", "type": "thinking_level_change"},
        {"id": "f", "type": "message", "message": {"role": "user", "content": "3"}},
    ]
    assert [e["id"] for e in projection.session_context_entries(branch)] == ["d", "b", "f"]
    assert [e["id"] for e in projection.session_context_entries(branch[:3])] == ["a", "b"]
