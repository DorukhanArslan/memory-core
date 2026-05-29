from memory_core.preemptive_compaction import (
    estimate_pre_prompt_tokens,
    estimate_tool_result_reduction_potential,
    should_preemptively_compact_before_prompt,
    truncate_tool_result_text,
    truncate_oversized_tool_results_in_session_file,
)


def _assistant_history(text: str) -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _tool_result(*texts: str) -> dict:
    return {
        "role": "toolResult",
        "toolCallId": "call_1",
        "toolName": "read",
        "content": [{"type": "text", "text": text} for text in texts],
        "isError": False,
    }


def _session_message(entry_id: str, parent_id: str | None, message: dict) -> dict:
    return {
        "type": "message",
        "id": entry_id,
        "parentId": parent_id,
        "timestamp": "2026-05-30T00:00:00.000Z",
        "message": message,
    }


def _write_jsonl(path, entries: list[dict]) -> None:
    path.write_text("".join(f"{__import__('json').dumps(entry)}\n" for entry in entries), encoding="utf-8")


def test_preemptive_compaction_routes_to_truncate_tool_results_only():
    medium = "alpha beta gamma delta epsilon " * 400
    messages = [
        _assistant_history("short history"),
        _tool_result(medium, medium, medium, medium),
    ]
    reserve_tokens = 2_000
    estimated = estimate_pre_prompt_tokens(
        messages=messages,
        system_prompt="sys",
        prompt="hello",
    )
    context_budget = estimated - 200 + reserve_tokens

    result = should_preemptively_compact_before_prompt(
        messages=messages,
        system_prompt="sys",
        prompt="hello",
        context_token_budget=context_budget,
        reserve_tokens=reserve_tokens,
    )

    assert result.route == "truncate_tool_results_only"
    assert result.should_compact is False
    assert result.overflow_tokens > 0
    assert result.tool_result_reducible_chars > 0


def test_preemptive_compaction_routes_to_fits_when_prompt_budget_is_enough():
    result = should_preemptively_compact_before_prompt(
        messages=[_assistant_history("short history")],
        system_prompt="sys",
        prompt="hello",
        context_token_budget=10_000,
        reserve_tokens=1_000,
    )

    assert result.route == "fits"
    assert result.should_compact is False
    assert result.overflow_tokens == 0
    assert result.estimated_prompt_tokens < result.prompt_budget_before_reserve


def test_preemptive_compaction_routes_to_compact_only_without_reducible_tool_results():
    long_history = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 40
    verbose_system = (
        "system guidance with multiple distinct words to avoid tokenizer overcompression " * 25
    )
    verbose_prompt = (
        "user request with distinct content asking for a detailed answer and more context " * 25
    )

    result = should_preemptively_compact_before_prompt(
        messages=[_assistant_history(long_history)],
        system_prompt=verbose_system,
        prompt=verbose_prompt,
        context_token_budget=500,
        reserve_tokens=50,
    )

    assert result.route == "compact_only"
    assert result.should_compact is True
    assert result.overflow_tokens > 0
    assert result.tool_result_reducible_chars == 0


def test_preemptive_compaction_uses_larger_unwindowed_transcript_estimate():
    verbose_history = (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 40
    )

    result = should_preemptively_compact_before_prompt(
        messages=[_assistant_history("small assembled window")],
        unwindowed_messages=[_assistant_history(verbose_history * 4)],
        system_prompt="sys",
        prompt="hello",
        context_token_budget=500,
        reserve_tokens=50,
    )

    assert result.route == "compact_only"
    assert result.should_compact is True
    assert result.pressure_source == "unwindowed_transcript_estimate"
    assert result.estimated_prompt_tokens > result.prompt_budget_before_reserve


def test_preemptive_compaction_routes_to_compact_then_truncate_when_tools_cannot_cover_overflow():
    medium = "alpha beta gamma delta epsilon " * 220
    long_history = "old discussion with substantial retained context and decisions " * 5000
    verbose_system = "system guidance " * 800
    verbose_prompt = "current user prompt " * 800
    messages = [
        _assistant_history(long_history),
        _tool_result(medium),
        _tool_result(medium),
        _tool_result(medium),
    ]

    result = should_preemptively_compact_before_prompt(
        messages=messages,
        system_prompt=verbose_system,
        prompt=verbose_prompt,
        context_token_budget=12_000,
        reserve_tokens=500,
    )

    assert result.route == "compact_then_truncate"
    assert result.should_compact is True
    assert result.overflow_tokens > 0
    assert result.tool_result_reducible_chars > 0


def test_tool_result_reduction_counts_oversized_and_aggregate_recovery_together():
    oversized = "x" * 45_000
    medium = "alpha beta gamma delta epsilon " * 500
    messages = [
        _assistant_history("short history"),
        _tool_result(oversized),
        _tool_result(medium),
        _tool_result(medium),
    ]

    potential = estimate_tool_result_reduction_potential(
        messages=messages,
        context_window_tokens=128_000,
    )

    assert potential.oversized_reducible_chars > 0
    assert potential.aggregate_reducible_chars > 0
    assert potential.max_reducible_chars == (
        potential.oversized_reducible_chars + potential.aggregate_reducible_chars
    )


def test_truncate_tool_result_text_uses_simple_head_strategy_without_important_tail():
    text = "normal line\n" * 1000

    result = truncate_tool_result_text(text, 5000)

    assert len(result) <= 5000
    assert "normal line" in result
    assert "middle content omitted" not in result
    assert "truncated" in result


def test_truncate_tool_result_text_preserves_important_error_tail():
    head = "Line 1\n" * 500
    middle = "data data data\n" * 500
    tail = "\nError: something failed\nStack trace: at foo.ts:42\n"
    text = head + middle + tail

    result = truncate_tool_result_text(text, 5000)

    assert len(result) <= 5000
    assert "Line 1" in result
    assert "Error: something failed" in result
    assert "middle content omitted" in result


def test_truncate_oversized_tool_results_in_session_file_appends_rewritten_branch(tmp_path):
    session_file = tmp_path / "session.jsonl"
    medium = "alpha beta gamma delta epsilon " * 800
    entries = [
        _session_message("u1", None, {"role": "user", "content": "hello"}),
        _session_message("a1", "u1", _assistant_history("calling tools")),
        _session_message("t1", "a1", _tool_result(medium)),
        _session_message("t2", "t1", _tool_result(medium)),
        _session_message("t3", "t2", _tool_result(medium)),
    ]
    _write_jsonl(session_file, entries)

    result = truncate_oversized_tool_results_in_session_file(
        session_file,
        context_window_tokens=128_000,
        max_chars_override=120,
    )

    assert result.truncated is True
    assert result.truncated_count > 0
    assert result.reason is None
    assert len(session_file.read_text(encoding="utf-8").splitlines()) > len(entries)
    assert sum(len(text) for text in result.tool_texts) <= 120
    assert any("truncated" in text for text in result.tool_texts)
