import dataclasses
import os
from pathlib import Path
import json
import shutil
import tempfile
import re

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.memory_flush import (
    build_memory_flush_plan,
    build_memory_flush_plan_from_config,
    has_already_flushed_for_current_compaction,
    should_run_memory_flush,
)
from memory_core.history import get_history_limit_from_session_key, limit_history_turns
from memory_core.replay_repair import repair_tool_use_result_pairing
from memory_core.runtime_context_prompt import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    build_current_inbound_prompt,
    build_runtime_context_custom_message,
    resolve_runtime_context_prompt_parts,
)
from memory_core.context_engine_lifecycle import (
    assemble_context_engine_messages,
    build_context_engine_conversation_snapshot,
)
from memory_core.replay_history import normalize_assistant_replay_content
from memory_core.preemptive_compaction import (
    estimate_pre_prompt_tokens,
    estimate_tool_result_reduction_potential,
    should_preemptively_compact_before_prompt,
    truncate_oversized_tool_results_in_session_file,
    truncate_tool_result_text,
)
from memory_core.overflow_recovery import (
    extract_observed_overflow_token_count,
    is_compaction_failure_error,
    is_likely_context_overflow_error,
)
from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    MemoryPromotionRun,
    PromotionCandidate,
    derive_concept_tags,
    rank_short_term_promotion_candidates,
    record_short_term_recalls,
    resolve_deep_dreaming_policy,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_search import memory_search
from memory_core.tools.memory_get import memory_get
from memory_core.workspace import MemoryWorkspace


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


class OpenClawFakeEmbeddingProvider(FakeEmbeddingProvider):
    provider_id = "memory-core-fake"


def _assistant_history(text: str) -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": text}], "timestamp": 1}


def _tool_result(*texts: str) -> dict:
    return {
        "role": "toolResult",
        "toolCallId": "call_1",
        "toolName": "read",
        "content": [{"type": "text", "text": text} for text in texts],
        "isError": False,
        "timestamp": 2,
    }


def _session_message(entry_id: str, parent_id: str | None, message: dict) -> dict:
    return {
        "type": "message",
        "id": entry_id,
        "parentId": parent_id,
        "timestamp": "2026-05-30T00:00:00.000Z",
        "message": message,
    }


def _user_history(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}], "timestamp": 1}


def _normalize_repair_messages(messages: list[dict]) -> list[dict]:
    normalized = []
    for message in messages:
        item = dict(message)
        if isinstance(item.get("timestamp"), int | float):
            item["timestamp"] = "__number__"
        normalized.append(item)
    return normalized


def _normalize_runtime_custom_message(message: dict | None) -> dict | None:
    if message is None:
        return None
    normalized = dict(message)
    if isinstance(normalized.get("timestamp"), int | float):
        normalized["timestamp"] = "__number__"
    return normalized


def test_real_openclaw_oracle_deep_policy():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "deepPolicy", "config": {}})

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["minScore"] == 0.8
    assert result["result"]["minRecallCount"] == 3
    assert result["result"]["minUniqueQueries"] == 3
    assert result["result"]["maxAgeDays"] == 30
    assert result["result"]["enabled"] is False
    assert result["result"]["limit"] == 10
    assert result["result"]["recencyHalfLifeDays"] == 14
    assert result["result"]["maxPromotedSnippetTokens"] == 160
    assert result["result"] == resolve_deep_dreaming_policy({}).as_dict()


def test_real_openclaw_oracle_deep_policy_uses_configured_values():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    config = {
        "plugins": {
            "entries": {
                "memory-core": {
                    "config": {
                        "dreaming": {
                            "enabled": True,
                            "phases": {
                                "deep": {
                                    "enabled": True,
                                    "limit": 7,
                                    "minScore": 0.72,
                                    "minRecallCount": 4,
                                    "minUniqueQueries": 2,
                                    "maxAgeDays": 14,
                                    "recencyHalfLifeDays": 10,
                                }
                            },
                        }
                    }
                }
            }
        }
    }

    result = oracle.run({"operation": "deepPolicy", "config": config})

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["enabled"] is True
    assert result["result"]["limit"] == 7
    assert result["result"]["minScore"] == 0.72
    assert result["result"]["minRecallCount"] == 4
    assert result["result"]["minUniqueQueries"] == 2
    assert result["result"]["maxAgeDays"] == 14
    assert result["result"]["recencyHalfLifeDays"] == 10
    assert result["result"]["maxPromotedSnippetTokens"] == 160
    assert result["result"] == resolve_deep_dreaming_policy(config).as_dict()


@pytest.mark.parametrize(
    "deep",
    [
        {"minScore": 1.4, "limit": None, "maxAgeDays": None, "maxPromotedSnippetTokens": None},
        {"minScore": -0.2, "limit": "Infinity", "maxAgeDays": "Infinity"},
        {"minScore": None, "limit": " 12 ", "maxAgeDays": 0, "maxPromotedSnippetTokens": 0},
        {"minScore": "0.5", "limit": "0x10", "maxAgeDays": -3, "maxPromotedSnippetTokens": "200"},
        {"minScore": "  ", "limit": "1e2", "maxAgeDays": "7.5", "minRecallCount": "x"},
        {"minScore": "abc", "limit": [7], "maxAgeDays": "abc", "recencyHalfLifeDays": "-1"},
        {"minScore": "inf", "limit": [], "minUniqueQueries": 2.9, "recencyHalfLifeDays": True},
        {"limit": 7.9, "minRecallCount": -0.5, "minUniqueQueries": "1_0", "enabled": "TRUE"},
    ],
)
def test_real_openclaw_oracle_deep_policy_coerces_malformed_values(deep: dict):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    config = {
        "plugins": {
            "entries": {
                "memory-core": {"config": {"dreaming": {"enabled": True, "phases": {"deep": deep}}}}
            }
        }
    }

    result = oracle.run({"operation": "deepPolicy", "config": config})

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"] == resolve_deep_dreaming_policy(config).as_dict()


def test_real_openclaw_oracle_flush_plan_matches_python_defaults(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    now_ms = 1777824000000
    config = {
        "agents": {
            "defaults": {
                "userTimezone": "Europe/Istanbul",
                "timeFormat": "24",
            }
        }
    }

    result = oracle.run(
        {
            "operation": "flushPlan",
            "config": config,
            "nowMs": now_ms,
        }
    )
    python_plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=now_ms,
        timezone="Europe/Istanbul",
    )

    assert result["ok"] is True
    assert result["operation"] == "flushPlan"
    assert result["result"] == {
        "softThresholdTokens": python_plan.soft_threshold_tokens,
        "forceFlushTranscriptBytes": python_plan.force_flush_transcript_bytes,
        "reserveTokensFloor": python_plan.reserve_tokens_floor,
        "relativePath": python_plan.relative_path,
        "prompt": python_plan.prompt,
        "systemPrompt": python_plan.system_prompt,
        "model": None,
    }


def test_real_openclaw_oracle_flush_plan_supports_disabled_and_overrides():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    now_ms = 1777824000000

    disabled = oracle.run(
        {
            "operation": "flushPlan",
            "nowMs": now_ms,
            "config": {
                "agents": {
                    "defaults": {
                        "compaction": {
                            "memoryFlush": {
                                "enabled": False,
                            }
                        }
                    }
                }
            },
        }
    )
    configured_config = {
        "agents": {
            "defaults": {
                "userTimezone": "Europe/Istanbul",
                "timeFormat": "24",
                "compaction": {
                    "reserveTokensFloor": 123,
                    "memoryFlush": {
                        "softThresholdTokens": 456,
                        "forceFlushTranscriptBytes": "3mb",
                        "model": "flush-model",
                        "prompt": "Custom prompt.",
                        "systemPrompt": "Custom system.",
                    },
                },
            }
        }
    }
    configured = oracle.run(
        {
            "operation": "flushPlan",
            "nowMs": now_ms,
            "config": configured_config,
        }
    )
    python_configured = build_memory_flush_plan_from_config(
        workspace_dir=Path("/tmp"),
        cfg=configured_config,
        now_ms=now_ms,
    )

    assert disabled["ok"] is True
    assert disabled["result"] is None
    assert configured["ok"] is True
    assert python_configured is not None
    assert configured["result"]["softThresholdTokens"] == 456
    assert configured["result"]["forceFlushTranscriptBytes"] == 3 * 1024 * 1024
    assert configured["result"]["reserveTokensFloor"] == 123
    assert configured["result"]["model"] == "flush-model"
    assert configured["result"]["relativePath"] == "memory/2026-05-03.md"
    assert "Custom prompt." in configured["result"]["prompt"]
    assert "Custom system." in configured["result"]["systemPrompt"]
    assert "Store durable memories only in memory/2026-05-03.md" in configured["result"]["prompt"]
    assert "If no user-visible reply is needed, start with NO_REPLY." in configured["result"]["prompt"]
    assert configured["result"] == {
        "softThresholdTokens": python_configured.soft_threshold_tokens,
        "forceFlushTranscriptBytes": python_configured.force_flush_transcript_bytes,
        "reserveTokensFloor": python_configured.reserve_tokens_floor,
        "relativePath": python_configured.relative_path,
        "prompt": python_configured.prompt,
        "systemPrompt": python_configured.system_prompt,
        "model": python_configured.model,
    }


def test_real_openclaw_oracle_preemptive_compaction_routes_match_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
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

    result = oracle.run(
        {
            "operation": "preemptiveCompaction",
            "messages": messages,
            "systemPrompt": "sys",
            "prompt": "hello",
            "contextWindowTokens": context_budget,
            "reserveTokens": reserve_tokens,
        }
    )
    python_result = should_preemptively_compact_before_prompt(
        messages=messages,
        system_prompt="sys",
        prompt="hello",
        context_token_budget=context_budget,
        reserve_tokens=reserve_tokens,
    )

    assert result["ok"] is True
    assert result["operation"] == "preemptiveCompaction"
    assert result["result"] == {
        "route": python_result.route,
        "shouldCompact": python_result.should_compact,
        "estimatedPromptTokens": python_result.estimated_prompt_tokens,
        "pressureSource": python_result.pressure_source,
        "promptBudgetBeforeReserve": python_result.prompt_budget_before_reserve,
        "overflowTokens": python_result.overflow_tokens,
        "toolResultReducibleChars": python_result.tool_result_reducible_chars,
        "effectiveReserveTokens": python_result.effective_reserve_tokens,
    }


@pytest.mark.parametrize(
    "message",
    [
        "context length exceeded",
        '400 {"message":"prompt is too long: 277403 tokens > 200000 maximum"}',
        "Invalid request: Your request exceeded model token limit: 262144 (requested: 291351)",
        "input length and max_tokens exceed context limit (i.e 156321 + 48384 > 200000)",
        "429 Too Many Requests: request exceeds rate limit",
        "Model context window too small (minimum is 128k tokens)",
    ],
)
def test_real_openclaw_oracle_overflow_error_helpers_match_python(message: str):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "overflowErrorHelpers", "text": message})

    assert result["ok"] is True
    assert result["operation"] == "overflowErrorHelpers"
    assert result["result"] == {
        "isLikelyContextOverflowError": is_likely_context_overflow_error(message),
        "isCompactionFailureError": is_compaction_failure_error(message),
        "extractObservedOverflowTokenCount": extract_observed_overflow_token_count(message),
    }


@pytest.mark.parametrize(
    "payload,expected_route,expected_should_compact",
    [
        (
            {
                "messages": [_assistant_history("short history")],
                "systemPrompt": "sys",
                "prompt": "hello",
                "contextWindowTokens": 10_000,
                "reserveTokens": 1_000,
            },
            "fits",
            False,
        ),
        (
            {
                "messages": [
                    _assistant_history(
                        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
                        * 40
                    )
                ],
                "systemPrompt": (
                    "system guidance with multiple distinct words to avoid tokenizer "
                    "overcompression "
                    * 25
                ),
                "prompt": (
                    "user request with distinct content asking for a detailed answer and more "
                    "context "
                    * 25
                ),
                "contextWindowTokens": 500,
                "reserveTokens": 50,
            },
            "compact_only",
            True,
        ),
        (
            {
                "messages": [_assistant_history("small assembled window")],
                "unwindowedMessages": [
                    _assistant_history(
                        (
                            "alpha beta gamma delta epsilon zeta eta theta iota kappa "
                            "lambda mu "
                        )
                        * 160
                    )
                ],
                "systemPrompt": "sys",
                "prompt": "hello",
                "contextWindowTokens": 500,
                "reserveTokens": 50,
            },
            "compact_only",
            True,
        ),
    ],
)
def test_real_openclaw_oracle_preemptive_compaction_additional_routes_match_python(
    payload: dict,
    expected_route: str,
    expected_should_compact: bool,
):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "preemptiveCompaction", **payload})
    python_result = should_preemptively_compact_before_prompt(
        messages=payload["messages"],
        unwindowed_messages=payload.get("unwindowedMessages"),
        system_prompt=payload.get("systemPrompt"),
        prompt=payload["prompt"],
        context_token_budget=payload["contextWindowTokens"],
        reserve_tokens=payload["reserveTokens"],
    )

    assert result["ok"] is True
    assert result["operation"] == "preemptiveCompaction"
    assert result["result"] == {
        "route": python_result.route,
        "shouldCompact": python_result.should_compact,
        "estimatedPromptTokens": python_result.estimated_prompt_tokens,
        "pressureSource": python_result.pressure_source,
        "promptBudgetBeforeReserve": python_result.prompt_budget_before_reserve,
        "overflowTokens": python_result.overflow_tokens,
        "toolResultReducibleChars": python_result.tool_result_reducible_chars,
        "effectiveReserveTokens": python_result.effective_reserve_tokens,
    }
    assert result["result"]["route"] == expected_route
    assert result["result"]["shouldCompact"] is expected_should_compact


def test_real_openclaw_oracle_tool_result_reduction_potential_matches_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    oversized = "x" * 45_000
    medium = "alpha beta gamma delta epsilon " * 500
    messages = [
        _assistant_history("short history"),
        _tool_result(oversized),
        _tool_result(medium),
        _tool_result(medium),
    ]

    result = oracle.run(
        {
            "operation": "toolResultReductionPotential",
            "messages": messages,
            "contextWindowTokens": 128_000,
        }
    )
    python_result = estimate_tool_result_reduction_potential(
        messages=messages,
        context_window_tokens=128_000,
    )

    assert result["ok"] is True
    assert result["operation"] == "toolResultReductionPotential"
    assert result["result"] == {
        "maxChars": python_result.max_chars,
        "aggregateBudgetChars": python_result.aggregate_budget_chars,
        "toolResultCount": python_result.tool_result_count,
        "totalToolResultChars": python_result.total_tool_result_chars,
        "oversizedCount": python_result.oversized_count,
        "oversizedReducibleChars": python_result.oversized_reducible_chars,
        "aggregateReducibleChars": python_result.aggregate_reducible_chars,
        "maxReducibleChars": python_result.max_reducible_chars,
    }


@pytest.mark.parametrize(
    "text,max_chars",
    [
        ("normal line\n" * 1000, 5_000),
        (
            ("Line 1\n" * 500)
            + ("data data data\n" * 500)
            + "\nError: something failed\nStack trace: at foo.ts:42\n",
            5_000,
        ),
    ],
)
def test_real_openclaw_oracle_truncate_tool_result_text_matches_python(
    text: str,
    max_chars: int,
):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run(
        {
            "operation": "truncateToolResultText",
            "text": text,
            "maxChars": max_chars,
        }
    )
    python_text = truncate_tool_result_text(text, max_chars)

    assert result["ok"] is True
    assert result["operation"] == "truncateToolResultText"
    assert result["result"]["text"] == python_text


def test_real_openclaw_oracle_truncate_tool_results_in_session_file_matches_python(
    tmp_path: Path,
):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    medium = "alpha beta gamma delta epsilon " * 800
    entries = [
        _session_message("u1", None, {"role": "user", "content": "hello"}),
        _session_message("a1", "u1", _assistant_history("calling tools")),
        _session_message("t1", "a1", _tool_result(medium)),
        _session_message("t2", "t1", _tool_result(medium)),
        _session_message("t3", "t2", _tool_result(medium)),
    ]
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "".join(f"{json.dumps(entry)}\n" for entry in entries),
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "truncateToolResultsInSession",
            "sessionEntries": entries,
            "contextWindowTokens": 128_000,
            "maxChars": 120,
        }
    )
    python_result = truncate_oversized_tool_results_in_session_file(
        session_file,
        context_window_tokens=128_000,
        max_chars_override=120,
    )

    assert result["ok"] is True
    assert result["operation"] == "truncateToolResultsInSession"
    assert result["result"]["truncated"] is python_result.truncated
    assert result["result"]["truncatedCount"] == python_result.truncated_count
    assert result["result"]["toolTexts"] == list(python_result.tool_texts)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "entry": {"totalTokens": 0},
            "contextWindowTokens": 16_000,
            "reserveTokensFloor": 20_000,
            "softThresholdTokens": 4_000,
        },
        {
            "entry": None,
            "contextWindowTokens": 16_000,
            "reserveTokensFloor": 1_000,
            "softThresholdTokens": 4_000,
        },
        {
            "entry": {"totalTokens": 10_000},
            "contextWindowTokens": 100_000,
            "reserveTokensFloor": 20_000,
            "softThresholdTokens": 10_000,
        },
        {
            "entry": {"totalTokens": 85},
            "contextWindowTokens": 100,
            "reserveTokensFloor": 10,
            "softThresholdTokens": 5,
        },
        {
            "entry": {
                "totalTokens": 90_000,
                "compactionCount": 2,
                "memoryFlushCompactionCount": 2,
            },
            "contextWindowTokens": 100_000,
            "reserveTokensFloor": 5_000,
            "softThresholdTokens": 2_000,
        },
        {
            "entry": {"totalTokens": 96_000, "compactionCount": 1},
            "contextWindowTokens": 100_000,
            "reserveTokensFloor": 5_000,
            "softThresholdTokens": 2_000,
        },
        {
            "entry": {"totalTokens": 96_000, "totalTokensFresh": False, "compactionCount": 1},
            "contextWindowTokens": 100_000,
            "reserveTokensFloor": 5_000,
            "softThresholdTokens": 2_000,
        },
        {
            "entry": {"totalTokens": 10, "totalTokensFresh": False, "compactionCount": 1},
            "tokenCount": 93_000,
            "contextWindowTokens": 100_000,
            "reserveTokensFloor": 5_000,
            "softThresholdTokens": 2_000,
        },
    ],
)
def test_real_openclaw_oracle_memory_flush_gate_matches_python(payload: dict):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "memoryFlushGate", **payload})
    entry = payload.get("entry")

    assert result["ok"] is True
    assert result["operation"] == "memoryFlushGate"
    assert result["result"]["shouldRunMemoryFlush"] is should_run_memory_flush(
        entry=entry,
        token_count=payload.get("tokenCount"),
        context_window_tokens=payload["contextWindowTokens"],
        reserve_tokens_floor=payload["reserveTokensFloor"],
        soft_threshold_tokens=payload["softThresholdTokens"],
    )
    assert result["result"]["hasAlreadyFlushedForCurrentCompaction"] is (
        has_already_flushed_for_current_compaction(entry) if entry else False
    )


def test_real_openclaw_oracle_memory_get_reads_line_window_like_python(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    memory_file = tmp_path / "memory" / "2026-05-26.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "\n".join(
            [
                "# 2026-05-26",
                "",
                "- User prefers to be addressed as Doruk.",
                "- User prefers concise Turkish replies.",
                "- User is porting OpenClaw memory-core to Python.",
            ]
        ),
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memoryGet",
            "workspaceDir": str(tmp_path),
            "path": "memory/2026-05-26.md",
            "from": 3,
            "lines": 2,
        }
    )
    python_result = memory_get(
        MemoryConfig(workspace_dir=tmp_path),
        path="memory/2026-05-26.md",
        from_line=3,
        lines=2,
    )

    assert result["ok"] is True
    assert result["operation"] == "memoryGet"
    assert result["result"] == python_result


def test_real_openclaw_oracle_memory_get_reads_root_memory_like_python(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Doruk prefers Turkish replies.",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memoryGet",
            "workspaceDir": str(tmp_path),
            "path": "MEMORY.md",
            "from": 3,
            "lines": 1,
        }
    )
    python_result = memory_get(
        MemoryConfig(workspace_dir=tmp_path),
        path="MEMORY.md",
        from_line=3,
        lines=1,
    )

    assert result["ok"] is True
    assert result["operation"] == "memoryGet"
    assert result["result"] == python_result


def test_real_openclaw_oracle_memory_get_disabled_error_matches_python(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    (tmp_path / "notes.txt").write_text("not memory\n", encoding="utf-8")

    result = oracle.run(
        {
            "operation": "memoryGet",
            "workspaceDir": str(tmp_path),
            "path": "notes.txt",
        }
    )
    python_result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="notes.txt")

    assert result["ok"] is True
    assert result["operation"] == "memoryGet"
    assert result["result"] == python_result


def test_real_openclaw_oracle_memory_get_missing_file_matches_python(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run(
        {
            "operation": "memoryGet",
            "workspaceDir": str(tmp_path),
            "path": "memory/2026-05-26.md",
        }
    )
    python_result = memory_get(
        MemoryConfig(workspace_dir=tmp_path),
        path="memory/2026-05-26.md",
    )

    assert result["ok"] is True
    assert result["operation"] == "memoryGet"
    assert result["result"] == python_result


def test_real_openclaw_oracle_memory_get_char_budget_matches_python(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    memory_file = tmp_path / "memory" / "long.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "\n".join([f"{index}: {'x' * 40}" for index in range(1, 8)]),
        encoding="utf-8",
    )
    config = {"agents": {"defaults": {"contextLimits": {"memoryGetMaxChars": 90}}}}

    result = oracle.run(
        {
            "operation": "memoryGet",
            "workspaceDir": str(tmp_path),
            "config": config,
            "path": "memory/long.md",
            "lines": 7,
        }
    )
    python_result = memory_get(
        MemoryConfig(workspace_dir=tmp_path, memory_get_max_chars=90),
        path="memory/long.md",
        lines=7,
    )

    assert result["ok"] is True
    assert result["operation"] == "memoryGet"
    assert result["result"] == python_result


def test_real_openclaw_oracle_memory_search_memory_corpus_matches_python_paths(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Doruk prefers concise Turkish replies.",
        encoding="utf-8",
    )
    memory_file = tmp_path / "memory" / "2026-05-26.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "# 2026-05-26\n\n- Move backups to S3 Glacier cold storage.",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "glacier",
            "corpus": "memory",
            "maxResults": 3,
            "minScore": 0,
        }
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "python-memory.sqlite",
        vector_weight=0,
        text_weight=1,
    )
    store = SQLiteMemoryStore(cfg, OpenClawFakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    python_result = memory_search(
        cfg,
        store,
        query="glacier",
        corpus="memory",
        max_results=3,
        min_score=0,
    )

    assert result["ok"] is True
    assert result["operation"] == "memorySearch"
    assert result["result"]["provider"] == python_result["provider"]
    assert result["result"]["model"] == python_result["model"]
    assert result["result"]["citations"] == python_result["citations"]
    assert [
        {
            "corpus": item["corpus"],
            "source": item["source"],
            "path": item["path"],
            "startLine": item["startLine"],
            "endLine": item["endLine"],
            "snippet": item["snippet"],
        }
        for item in result["result"]["results"]
    ] == [
        {
            "corpus": item["corpus"],
            "source": item["source"],
            "path": item["path"],
            "startLine": item["startLine"],
            "endLine": item["endLine"],
            "snippet": item["snippet"],
        }
        for item in python_result["results"]
    ]


def test_real_openclaw_oracle_memory_search_relaxes_min_score_for_keyword_hits(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Move backups to S3 Glacier cold storage.",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "glacier",
            "corpus": "memory",
            "maxResults": 3,
            "minScore": 1.1,
        }
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "python-memory.sqlite",
        vector_weight=0,
        text_weight=1,
    )
    store = SQLiteMemoryStore(cfg, OpenClawFakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    python_result = memory_search(
        cfg,
        store,
        query="glacier",
        corpus="memory",
        max_results=3,
        min_score=1.1,
    )

    assert result["ok"] is True
    assert [
        (item["corpus"], item["path"])
        for item in result["result"]["results"]
    ] == [
        (item["corpus"], item["path"])
        for item in python_result["results"]
    ] == [("memory", "MEMORY.md")]
    assert result["result"]["results"][0]["score"] < 1.1


def test_real_openclaw_oracle_memory_search_text_scores_and_line_ranges_match_python(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Alpha alpha alpha project note.\n- Beta project note.\n",
        encoding="utf-8",
    )
    memory_file = tmp_path / "memory" / "2026-05-26.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "# 2026-05-26\n\n- Alpha project note.\n",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "alpha project",
            "corpus": "memory",
            "maxResults": 5,
            "minScore": 0,
        }
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "python-memory.sqlite",
        vector_weight=0,
        text_weight=1,
    )
    store = SQLiteMemoryStore(cfg, OpenClawFakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    python_result = memory_search(
        cfg,
        store,
        query="alpha project",
        corpus="memory",
        max_results=5,
        min_score=0,
    )

    assert result["ok"] is True
    openclaw_results = result["result"]["results"]
    python_results = python_result["results"]
    assert [
        {
            "path": item["path"],
            "startLine": item["startLine"],
            "endLine": item["endLine"],
        }
        for item in openclaw_results
    ] == [
        {
            "path": item["path"],
            "startLine": item["startLine"],
            "endLine": item["endLine"],
        }
        for item in python_results
    ] == [
        {"path": "MEMORY.md", "startLine": 1, "endLine": 5},
        {"path": "memory/2026-05-26.md", "startLine": 1, "endLine": 4},
    ]
    assert [item["path"] for item in openclaw_results] == [
        item["path"] for item in python_results
    ]
    assert [item["score"] for item in openclaw_results] == pytest.approx(
        [item["score"] for item in python_results],
        rel=0,
        abs=1e-12,
    )
    assert [item["textScore"] for item in openclaw_results] == pytest.approx(
        [item["textScore"] for item in python_results],
        rel=0,
        abs=1e-12,
    )


def test_real_openclaw_oracle_memory_search_vector_scores_match_python(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Alpha preference exact note.\n",
        encoding="utf-8",
    )
    memory_file = tmp_path / "memory" / "2026-05-26.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "# 2026-05-26\n\n- Cooking reminder about paprika.\n",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "alpha preference",
            "corpus": "memory",
            "maxResults": 5,
            "minScore": 0,
            "vectorWeight": 1,
            "textWeight": 0,
        }
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "python-memory.sqlite",
        vector_weight=1,
        text_weight=0,
    )
    store = SQLiteMemoryStore(cfg, OpenClawFakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    python_result = memory_search(
        cfg,
        store,
        query="alpha preference",
        corpus="memory",
        max_results=5,
        min_score=0,
    )

    assert result["ok"] is True
    openclaw_results = result["result"]["results"]
    python_results = python_result["results"]
    assert [item["path"] for item in openclaw_results] == [
        item["path"] for item in python_results
    ]
    assert [item["score"] for item in openclaw_results] == pytest.approx(
        [item["score"] for item in python_results],
        rel=0,
        abs=1e-6,
    )
    assert [item["vectorScore"] for item in openclaw_results] == pytest.approx(
        [item["vectorScore"] for item in python_results],
        rel=0,
        abs=1e-6,
    )
    assert [item["score"] for item in openclaw_results] == pytest.approx(
        [item["vectorScore"] for item in openclaw_results],
        rel=0,
        abs=1e-12,
    )


def test_real_openclaw_oracle_memory_search_hybrid_weighted_scores_match_python(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Alpha preference exact note.\n",
        encoding="utf-8",
    )
    memory_file = tmp_path / "memory" / "2026-05-26.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "# 2026-05-26\n\n- Cooking reminder about paprika.\n",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "alpha preference",
            "corpus": "memory",
            "maxResults": 5,
            "minScore": 0,
            "vectorWeight": 0.7,
            "textWeight": 0.3,
        }
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "python-memory.sqlite",
        vector_weight=0.7,
        text_weight=0.3,
    )
    store = SQLiteMemoryStore(cfg, OpenClawFakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    python_result = memory_search(
        cfg,
        store,
        query="alpha preference",
        corpus="memory",
        max_results=5,
        min_score=0,
    )

    assert result["ok"] is True
    openclaw_results = result["result"]["results"]
    python_results = python_result["results"]
    assert [item["path"] for item in openclaw_results] == [
        item["path"] for item in python_results
    ]
    assert [item["score"] for item in openclaw_results] == pytest.approx(
        [item["score"] for item in python_results],
        rel=0,
        abs=1e-6,
    )
    assert [item["vectorScore"] for item in openclaw_results] == pytest.approx(
        [item["vectorScore"] for item in python_results],
        rel=0,
        abs=1e-6,
    )
    assert [item["textScore"] for item in openclaw_results] == pytest.approx(
        [item["textScore"] for item in python_results],
        rel=0,
        abs=1e-12,
    )
    assert [item["score"] for item in openclaw_results] == pytest.approx(
        [
            0.7 * item["vectorScore"] + 0.3 * item["textScore"]
            for item in openclaw_results
        ],
        rel=0,
        abs=1e-12,
    )


def test_real_openclaw_oracle_memory_search_sessions_corpus_reads_openclaw_transcripts(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "stateDir": str(tmp_path / ".openclaw-state"),
            "query": "project nebula orbit-10",
            "corpus": "sessions",
            "maxResults": 3,
            "minScore": 0,
            "config": {
                "agents": {
                    "defaults": {
                        "memorySearch": {
                            "sources": ["memory", "sessions"],
                            "experimental": {"sessionMemory": True},
                        }
                    }
                }
            },
            "sessionTranscripts": [
                {
                    "fileName": "session-nebula.jsonl",
                    "entries": [
                        {
                            "type": "session",
                            "id": "session-nebula",
                            "timestamp": "2026-04-07T15:24:04.113Z",
                        },
                        {
                            "type": "message",
                            "message": {
                                "role": "user",
                                "timestamp": "2026-04-07T15:24:34.113Z",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "What is the current Project Nebula codename?",
                                    }
                                ],
                            },
                        },
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "timestamp": "2026-04-07T15:25:04.113Z",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "The current Project Nebula codename is ORBIT-10.",
                                    }
                                ],
                            },
                        },
                    ],
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "memorySearch"
    first = result["result"]["results"][0]
    assert first["corpus"] == "sessions"
    assert first["source"] == "sessions"
    assert first["path"] == "sessions/main/session-nebula.jsonl"
    assert "Assistant: The current Project Nebula codename is ORBIT-10." in first["snippet"]


def test_real_openclaw_oracle_memory_search_all_balances_memory_and_wiki(
    tmp_path: Path,
):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Memory result A mentions project alpha.",
        encoding="utf-8",
    )

    result = oracle.run(
        {
            "operation": "memorySearch",
            "workspaceDir": str(tmp_path),
            "query": "alpha",
            "corpus": "all",
            "maxResults": 5,
            "minScore": 0,
            "wikiResults": [
                {
                    "corpus": "wiki",
                    "path": "w1.md",
                    "title": "W1",
                    "kind": "entity",
                    "score": 50,
                    "snippet": "wiki 1",
                },
                {
                    "corpus": "wiki",
                    "path": "w2.md",
                    "title": "W2",
                    "kind": "entity",
                    "score": 40,
                    "snippet": "wiki 2",
                },
                {
                    "corpus": "wiki",
                    "path": "w3.md",
                    "title": "W3",
                    "kind": "entity",
                    "score": 30,
                    "snippet": "wiki 3",
                },
                {
                    "corpus": "wiki",
                    "path": "w4.md",
                    "title": "W4",
                    "kind": "entity",
                    "score": 20,
                    "snippet": "wiki 4",
                },
                {
                    "corpus": "wiki",
                    "path": "w5.md",
                    "title": "W5",
                    "kind": "entity",
                    "score": 10,
                    "snippet": "wiki 5",
                },
            ],
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "memorySearch"
    paths_by_corpus = [(item["corpus"], item["path"]) for item in result["result"]["results"]]
    assert ("memory", "MEMORY.md") in paths_by_corpus
    assert [path for corpus, path in paths_by_corpus if corpus == "wiki"] == [
        "w1.md",
        "w2.md",
        "w3.md",
        "w4.md",
    ]
    assert len(paths_by_corpus) == 5


# --- Python side of the promotion fixtures (memory_core.consolidation) ---------------------------
#
# Each promotion test below replays its oracle inputs on a copy of the seeded workspace through
# memory_core.consolidation and asserts Python == TS. The policy mirrors the runner's
# resolvePromotionPolicy: deep-dreaming defaults, overridden by the payload's explicit values.
# Python ranks and applies in one call (run_short_term_promotion) where the runner passes ranked
# candidates to applyShortTermPromotions; the fixtures rank and apply with identical gates.
# Apply runs under OPENCLAW_COMPAT_RUNTIME_IDENTITY so markers carry upstream's prefix.

_POLICY_FIELDS = {
    "limit": "limit",
    "minScore": "min_score",
    "minRecallCount": "min_recall_count",
    "minUniqueQueries": "min_unique_queries",
    "maxAgeDays": "max_age_days",
    "recencyHalfLifeDays": "recency_half_life_days",
    "maxPromotedSnippetTokens": "max_promoted_snippet_tokens",
}
# Candidate fields both sides expose. Python candidates carry no recallDays, source or
# first/lastRecalledAt; those are compared through the recall store instead.
_CANDIDATE_FIELDS = (
    "key",
    "path",
    "startLine",
    "endLine",
    "snippet",
    "recallCount",
    "dailyCount",
    "groundedCount",
    "signalCount",
    "avgScore",
    "maxScore",
    "uniqueQueries",
    "ageDays",
    "score",
    "conceptTags",
    "components",
)
_RECALL_STORE = "memory/.dreams/short-term-recall.json"


class _PythonPromotion:
    """Replays promotion oracle operations on a Python workspace."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.config = MemoryConfig(
            workspace_dir=workspace, store_path=workspace.parent / f"{workspace.name}.sqlite"
        )

    @classmethod
    def copy_of(cls, seeded: Path, target: Path) -> "_PythonPromotion":
        """Copy the seeded oracle workspace to ``target`` before any operation runs."""
        shutil.copytree(seeded, target)
        return cls(target)

    def record(self, query: str, results: list[dict], now_ms: int) -> None:
        record_short_term_recalls(config=self.config, query=query, results=results, now_ms=now_ms)

    def record_sequence(self, recalls: list[dict]) -> None:
        for recall in recalls:
            self.record(recall["query"], recall["results"], recall["nowMs"])

    def rank(self, now_ms: int, **payload) -> list[dict]:
        policy = _runner_policy(payload)
        candidates = rank_short_term_promotion_candidates(
            config=self.config,
            now_ms=now_ms,
            limit=policy.limit,
            min_score=policy.min_score,
            min_recall_count=policy.min_recall_count,
            min_unique_queries=policy.min_unique_queries,
            max_age_days=policy.max_age_days,
            recency_half_life_days=policy.recency_half_life_days,
        )
        return [_python_candidate_view(candidate) for candidate in candidates]

    def apply(
        self, now_ms: int, timezone: str, memory_file_max_chars: int | None = None, **payload
    ) -> MemoryPromotionRun:
        policy = _runner_policy(payload)
        extra = {} if memory_file_max_chars is None else {"memory_file_max_chars": memory_file_max_chars}
        return run_short_term_promotion(
            config=self.config,
            store=SQLiteMemoryStore(self.config, FakeEmbeddingProvider(dimensions=8)),
            now_ms=now_ms,
            timezone=timezone,
            limit=policy.limit,
            min_score=policy.min_score,
            min_recall_count=policy.min_recall_count,
            min_unique_queries=policy.min_unique_queries,
            max_age_days=policy.max_age_days,
            recency_half_life_days=policy.recency_half_life_days,
            max_promoted_snippet_tokens=policy.max_promoted_snippet_tokens,
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
            **extra,
        )

    def memory_text(self) -> str:
        path = self.workspace / "MEMORY.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def recall_entries(self) -> dict:
        path = self.workspace / _RECALL_STORE
        return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else {}

    def edit_recall_store(self, edit) -> None:
        path = self.workspace / _RECALL_STORE
        store = json.loads(path.read_text(encoding="utf-8"))
        edit(store)
        path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _runner_policy(payload: dict):
    overrides = {_POLICY_FIELDS[key]: value for key, value in payload.items()}
    return dataclasses.replace(resolve_deep_dreaming_policy({}), **overrides)


def _ulp_tolerant(value):
    """Wrap every float in ``value`` for a 1e-12 relative comparison.

    V8's fdlibm ``Math.exp``/``Math.log1p`` and the platform libm behind ``math.exp``/``math.log1p``
    can differ in the last ulp (recency at 7 days, half-life 14: TS 0.7071067811865475, Python
    0.7071067811865476), so candidate floats match to rounding, not bit for bit.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return pytest.approx(value, rel=1e-12, abs=1e-15)
    if isinstance(value, dict):
        return {key: _ulp_tolerant(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_ulp_tolerant(item) for item in value]
    return value


def _python_candidate_view(candidate: PromotionCandidate) -> dict:
    view = {
        "key": candidate.key,
        "path": candidate.path,
        "startLine": candidate.start_line,
        "endLine": candidate.end_line,
        "snippet": candidate.snippet,
        "recallCount": candidate.recall_count,
        "dailyCount": candidate.daily_count,
        "groundedCount": candidate.grounded_count,
        "signalCount": candidate.signal_count,
        "avgScore": candidate.avg_score,
        "maxScore": candidate.max_score,
        "uniqueQueries": candidate.unique_queries,
        "ageDays": candidate.age_days,
        "score": candidate.score,
        "conceptTags": list(candidate.concept_tags),
        # Upstream folds the phase boost into the score without listing it as a component.
        "components": {
            key: value for key, value in candidate.components.items() if key != "phaseBoost"
        },
    }
    assert tuple(view) == _CANDIDATE_FIELDS
    return _ulp_tolerant(view)


def _ts_candidate_views(result: dict) -> list[dict]:
    return [
        {field: candidate[field] for field in _CANDIDATE_FIELDS}
        for candidate in result["result"]["candidates"]
    ]


def _ts_recall_entries(result: dict) -> dict:
    return json.loads(result["files"][_RECALL_STORE])["entries"]


def _assert_apply_matches(ts: dict, python: MemoryPromotionRun, python_side: _PythonPromotion):
    assert python_side.memory_text() == ts["files"]["MEMORY.md"]
    assert python_side.recall_entries() == _ts_recall_entries(ts)
    assert {
        "applied": len(python.applied_candidates),
        "appended": python.appended,
        "reconciledExisting": python.reconciled_existing,
        "compactedSections": len(python.compacted_dates),
        "compactedDates": list(python.compacted_dates),
        "appliedKeys": [candidate.key for candidate in python.applied_candidates],
    } == {
        "applied": ts["result"]["applied"],
        "appended": ts["result"]["appended"],
        "reconciledExisting": ts["result"]["reconciledExisting"],
        "compactedSections": ts["result"]["compactedSections"],
        "compactedDates": ts["result"]["compactedDates"],
        "appliedKeys": [candidate["key"] for candidate in ts["result"]["appliedCandidates"]],
    }


def test_real_openclaw_oracle_records_short_term_recall(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-integration-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "query": "address preference",
                "results": [
                    {
                        "source": "memory",
                        "path": "memory/2026-05-26.md",
                        "startLine": 3,
                        "endLine": 3,
                        "snippet": "- User prefers to be addressed as dodo.",
                        "score": 1,
                    }
                ],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "workspaceDir": str(workspace),
            }
        )

    assert result["ok"] is True
    assert result["operation"] == "recordShortTermRecalls"
    recall_store = result["files"]["memory/.dreams/short-term-recall.json"]
    assert "User prefers to be addressed as dodo." in recall_store
    assert '"recallCount": 1' in recall_store
    python_side.record(
        "address preference",
        [
            {
                "source": "memory",
                "path": "memory/2026-05-26.md",
                "startLine": 3,
                "endLine": 3,
                "snippet": "- User prefers to be addressed as dodo.",
                "score": 1,
            }
        ],
        1779811200000,
    )
    assert python_side.recall_entries() == _ts_recall_entries(result)


def test_real_openclaw_oracle_records_short_term_recall_sequence(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-sequence-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-26.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- User prefers to be addressed as dodo.",
            "score": 1,
        }
        recalls = [
            {
                "query": "address preference",
                "results": [base_result],
                "nowMs": 1779811200000,
            },
            {
                "query": "preferred name",
                "results": [
                    base_result,
                    {
                        "source": "workspace",
                        "path": "notes.md",
                        "startLine": 1,
                        "endLine": 1,
                        "snippet": "Ignore this non-memory result.",
                        "score": 1,
                    },
                ],
                "nowMs": 1779897600000,
            },
        ]
        result = oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        python_side.record_sequence(recalls)

    assert result["ok"] is True
    assert result["operation"] == "recordShortTermRecallSequence"
    recall_store = json.loads(result["files"]["memory/.dreams/short-term-recall.json"])
    entries = recall_store["entries"]
    entry = entries["memory:memory/2026-05-26.md:3:3"]
    assert len(entries) == 1
    assert entry["recallCount"] == 2
    assert entry["queryHashes"] == ["aa5368a7c7bd", "1da206d81a95"]
    assert entry["recallDays"] == ["2026-05-26", "2026-05-27"]
    assert python_side.recall_entries() == entries


def test_real_openclaw_oracle_derives_concept_vocabulary_tags():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=180,
    )

    fixtures = [
        (
            "memory/2026-04-04.md",
            "Configuración de gateway, configuration du routeur, Sicherung und Überwachung Glacier.",
            [
                "gateway",
                "glacier",
                "routeur",
                "sicherung",
                "überwachung",
                "configuración",
                "configuration",
            ],
        ),
        (
            "memory/2026-04-05.md",
            "障害対応ルーター設定とバックアップ確認。路由器备份与网关同步。라우터 백업 페일오ーバー 점검.",
            [
                "バックアップ",
                "ルーター",
                "障害対応",
                "路由器",
                "备份",
                "网关",
                "라우터",
                "백업",
            ],
        ),
        (
            "memory/.dreams/session-corpus/2026-04-16.txt",
            "Assistant: the system should remind you about the Ollama provider setup in your workspace.",
            ["remind", "ollama", "provider", "setup"],
        ),
        (
            "memory/2026-04-03.md",
            "Move backups to S3 Glacier and sync QMD router notes.",
            ["backup", "backups", "glacier", "qmd", "router", "s3", "sync"],
        ),
        (
            "memory/2026-04-06.md",
            "Configuración du routeur et sauvegarde Glacier.",
            ["glacier", "sauvegarde", "routeur", "configuración"],
        ),
    ]

    for relative_path, snippet, expected_tags in fixtures:
        result = oracle.run(
            {
                "operation": "deriveConceptTags",
                "path": relative_path,
                "snippet": snippet,
            }
        )

        assert result["ok"] is True
        assert result["result"]["conceptTags"] == expected_tags
        assert derive_concept_tags(relative_path, snippet) == result["result"]["conceptTags"]


def test_real_openclaw_oracle_ranks_short_term_promotion_candidate(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-ranking-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-26.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- User prefers to be addressed as dodo.",
            "score": 1,
        }
        queries = [
            "address preference",
            "preferred name",
            "user salutation",
            "name preference",
            "how to address user",
        ]
        recalls = [
            {
                "query": query,
                "results": [base_result],
                "nowMs": 1779811200000 + index * 86_400_000,
            }
            for index, query in enumerate(queries)
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        python_side.record_sequence(recalls)
        result = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000 + 4 * 86_400_000,
                "timezone": "Europe/Istanbul",
            }
        )

    assert result["ok"] is True
    candidates = result["result"]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["key"] == "memory:memory/2026-05-26.md:3:3"
    assert candidate["recallCount"] == 5
    assert candidate["uniqueQueries"] == 5
    assert candidate["score"] == pytest.approx(0.8900475024284972)
    assert candidate["components"]["frequency"] == pytest.approx(0.7472217363092141)
    assert candidate["components"]["relevance"] == 1
    assert candidate["components"]["diversity"] == 1
    assert candidate["components"]["recency"] == 1
    assert candidate["components"]["consolidation"] == pytest.approx(0.8071428571428572)
    assert candidate["components"]["conceptual"] == 0.5
    assert python_side.rank(1779811200000 + 4 * 86_400_000) == _ts_candidate_views(result)


def test_real_openclaw_oracle_first_promotion_write_bootstraps_memory_header(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-first-promotion-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["appended"] == 1
    assert applied["files"]["MEMORY.md"].startswith(
        "# Long-Term Memory\n\n\n## Promoted From Short-Term Memory (2026-05-26)"
    )
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1779811200000)
    assert python_side.rank(1779811200000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_second_apply_reconciles_existing_marker_without_duplicate(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-duplicate-apply-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        first = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        recall_path = workspace / "memory" / ".dreams" / "short-term-recall.json"
        recall_store = json.loads(recall_path.read_text(encoding="utf-8"))
        key = "memory:memory/2026-05-08.md:3:3"
        del recall_store["entries"][key]["promotedAt"]
        recall_path.write_text(json.dumps(recall_store, indent=2) + "\n", encoding="utf-8")
        second = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert first["ok"] is True
    assert first["result"]["applied"] == 1
    assert first["result"]["appended"] == 1
    assert second["ok"] is True
    assert second["result"]["applied"] == 1
    assert second["result"]["appended"] == 0
    assert second["result"]["reconciledExisting"] == 1
    memory_text = second["files"]["MEMORY.md"]
    assert memory_text.count("openclaw-memory-promotion:") == 1
    assert memory_text.count("Move backups to S3 Glacier.") == 1
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1779811200000)
    python_first = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(first, python_first, python_side)
    python_side.edit_recall_store(lambda store: store["entries"][key].pop("promotedAt"))
    python_second = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(second, python_second, python_side)


def test_real_openclaw_oracle_ranking_applies_max_age_gate(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-max-age-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1778241600000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked_without_gate = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778500800000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "maxAgeDays": -1,
            }
        )
        ranked_with_gate = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778500800000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "maxAgeDays": 2,
            }
        )

    assert ranked_without_gate["ok"] is True
    assert len(ranked_without_gate["result"]["candidates"]) == 1
    assert ranked_without_gate["result"]["candidates"][0]["ageDays"] == 3
    assert ranked_with_gate["ok"] is True
    assert ranked_with_gate["result"]["candidates"] == []
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1778241600000)
    assert python_side.rank(1778500800000, **gates, maxAgeDays=-1) == _ts_candidate_views(
        ranked_without_gate
    )
    assert python_side.rank(1778500800000, **gates, maxAgeDays=2) == []


def test_real_openclaw_oracle_ranking_uses_recency_half_life_days(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-recency-half-life-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1778241600000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked_default = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778846400000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        ranked_half_life_7 = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778846400000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "recencyHalfLifeDays": 7,
            }
        )

    assert ranked_default["ok"] is True
    assert ranked_half_life_7["ok"] is True
    default_candidate = ranked_default["result"]["candidates"][0]
    half_life_candidate = ranked_half_life_7["result"]["candidates"][0]
    assert default_candidate["ageDays"] == 7
    assert default_candidate["components"]["recency"] == pytest.approx(0.7071067811865476)
    assert half_life_candidate["ageDays"] == 7
    assert half_life_candidate["components"]["recency"] == pytest.approx(0.5)
    assert half_life_candidate["score"] < default_candidate["score"]
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1778241600000)
    assert python_side.rank(1778846400000, **gates) == _ts_candidate_views(ranked_default)
    assert python_side.rank(1778846400000, **gates, recencyHalfLifeDays=7) == _ts_candidate_views(
        ranked_half_life_7
    )


def test_real_openclaw_oracle_ranking_applies_score_recall_unique_query_and_limit_gates(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-ranking-gates-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-08\n\n"
            "- Strong promotion candidate for backups.\n"
            "- Medium promotion candidate for routing.\n"
            "- Weak promotion candidate for notes.\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        strong = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Strong promotion candidate for backups.",
            "score": 1,
        }
        medium = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 4,
            "endLine": 4,
            "snippet": "- Medium promotion candidate for routing.",
            "score": 0.9,
        }
        weak = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 5,
            "endLine": 5,
            "snippet": "- Weak promotion candidate for notes.",
            "score": 0.8,
        }
        recalls = [
            {
                "query": "backup policy",
                "results": [strong, medium, weak],
                "nowMs": 1778241600000,
            },
            {
                "query": "backup retention",
                "results": [strong, medium],
                "nowMs": 1778241600001,
            },
            {
                "query": "backup restore",
                "results": [strong],
                "nowMs": 1778241600002,
            },
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        python_side.record_sequence(recalls)
        baseline = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778241600002,
                "timezone": "Europe/Istanbul",
                "limit": 10,
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        min_recall = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778241600002,
                "timezone": "Europe/Istanbul",
                "limit": 10,
                "minScore": 0,
                "minRecallCount": 2,
                "minUniqueQueries": 0,
            }
        )
        unique_queries = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778241600002,
                "timezone": "Europe/Istanbul",
                "limit": 10,
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 3,
            }
        )
        limited = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778241600002,
                "timezone": "Europe/Istanbul",
                "limit": 1,
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        top_score = baseline["result"]["candidates"][0]["score"]
        above_top_score = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1778241600002,
                "timezone": "Europe/Istanbul",
                "limit": 10,
                "minScore": top_score + 0.001,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert baseline["ok"] is True
    assert [candidate["key"] for candidate in baseline["result"]["candidates"]] == [
        "memory:memory/2026-05-08.md:3:3",
        "memory:memory/2026-05-08.md:4:4",
        "memory:memory/2026-05-08.md:5:5",
    ]
    assert [candidate["recallCount"] for candidate in baseline["result"]["candidates"]] == [
        3,
        2,
        1,
    ]
    assert [candidate["key"] for candidate in min_recall["result"]["candidates"]] == [
        "memory:memory/2026-05-08.md:3:3",
        "memory:memory/2026-05-08.md:4:4",
    ]
    assert [candidate["key"] for candidate in unique_queries["result"]["candidates"]] == [
        "memory:memory/2026-05-08.md:3:3"
    ]
    assert [candidate["key"] for candidate in limited["result"]["candidates"]] == [
        "memory:memory/2026-05-08.md:3:3"
    ]
    assert above_top_score["result"]["candidates"] == []
    now_ms = 1778241600002
    for ts_result, payload in (
        (baseline, {"limit": 10, "minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}),
        (min_recall, {"limit": 10, "minScore": 0, "minRecallCount": 2, "minUniqueQueries": 0}),
        (unique_queries, {"limit": 10, "minScore": 0, "minRecallCount": 0, "minUniqueQueries": 3}),
        (limited, {"limit": 1, "minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}),
        (
            above_top_score,
            {
                "limit": 10,
                "minScore": top_score + 0.001,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            },
        ),
    ):
        assert python_side.rank(now_ms, **payload) == _ts_candidate_views(ts_result)


def test_real_openclaw_oracle_reconciles_existing_promotion_marker(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-marker-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        key = "memory:memory/2026-05-08.md:3:3"
        (workspace / "MEMORY.md").write_text(
            "# Long-Term Memory\n\n"
            "## Promoted From Short-Term Memory (2026-05-08)\n\n"
            f"<!-- openclaw-memory-promotion:{key} -->\n"
            "- Move backups to S3 Glacier. [score=0.900 recalls=5 avg=1.000 "
            "source=memory/2026-05-08.md:3-3]\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        recalls = [
            {
                "query": query,
                "results": [base_result],
                "nowMs": 1779811200000 + index,
            }
            for index, query in enumerate(
                (
                    "backup policy",
                    "glacier backup",
                    "s3 retention",
                    "cold storage",
                    "backup notes",
                )
            )
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    assert [candidate["key"] for candidate in ranked["result"]["candidates"]] == [key]
    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["appended"] == 0
    assert applied["result"]["reconciledExisting"] == 1
    recall_store = json.loads(applied["files"]["memory/.dreams/short-term-recall.json"])
    assert recall_store["entries"][key]["promotedAt"] == "2026-05-26T16:00:00.000Z"
    gates = {"minScore": 0, "minRecallCount": 1, "minUniqueQueries": 1}
    python_side.record_sequence(recalls)
    assert python_side.rank(1779811200000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_reconciles_spaced_case_insensitive_promotion_marker(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-marker-variant-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        key = "memory:memory/2026-05-08.md:3:3"
        (workspace / "MEMORY.md").write_text(
            "# Long-Term Memory\n\n"
            "## Promoted From Short-Term Memory (2026-05-08)\n\n"
            f"<!--   OPENCLAW-MEMORY-PROMOTION:{key}-->\n"
            "- Move backups to S3 Glacier. [score=0.900 recalls=1 avg=1.000 "
            "source=memory/2026-05-08.md:3-3]\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["appended"] == 0
    assert applied["result"]["reconciledExisting"] == 1
    assert applied["files"]["MEMORY.md"].count("openclaw-memory-promotion:") == 0
    assert applied["files"]["MEMORY.md"].count("OPENCLAW-MEMORY-PROMOTION:") == 1
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1779811200000)
    assert python_side.rank(1779811200000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_compacts_oldest_promotion_section_when_memory_budget_exceeded(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-memory-budget-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-04-29.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-04-29\n\nRotate the staging Postgres credentials before next deploy.\n",
            encoding="utf-8",
        )
        filler = "x" * 600
        seeded_memory = "\n".join(
            [
                "# Long-Term Memory",
                "",
                "User-authored note that must stay.",
                "",
                "## Promoted From Short-Term Memory (2026-04-10)",
                "<!-- openclaw-memory-promotion:legacy-old -->",
                f"- {filler}",
                "",
                "## Promoted From Short-Term Memory (2026-04-20)",
                "<!-- openclaw-memory-promotion:legacy-newer -->",
                f"- {filler}",
                "",
            ]
        )
        (workspace / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-04-29.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "Rotate the staging Postgres credentials before next deploy.",
            "score": 0.96,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "rotate creds",
                "results": [result],
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "memoryFileMaxChars": 1_400,
            }
        )

    memory_text = applied["files"]["MEMORY.md"]
    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["compactedSections"] == 1
    assert applied["result"]["compactedDates"] == ["2026-04-10"]
    assert "User-authored note that must stay." in memory_text
    assert "(2026-04-10)" not in memory_text
    assert "legacy-old" not in memory_text
    assert "(2026-04-20)" in memory_text
    assert "legacy-newer" in memory_text
    assert "Rotate the staging Postgres credentials" in memory_text
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record('rotate creds', [result], 1777456800000)
    assert python_side.rank(1777456800000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(
        1777456800000, "Europe/Istanbul", memory_file_max_chars=1_400, **gates
    )
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_leaves_memory_unchanged_before_append_when_budget_fits(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-memory-budget-fits-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-04-29.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-04-29\n\nA short snippet that fits comfortably.\n",
            encoding="utf-8",
        )
        seeded_memory = "# Long-Term Memory\n\nSome small existing content.\n"
        (workspace / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-04-29.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "A short snippet that fits comfortably.",
            "score": 0.92,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "tiny note",
                "results": [result],
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "memoryFileMaxChars": 10_000,
            }
        )

    memory_text = applied["files"]["MEMORY.md"]
    assert applied["ok"] is True
    assert applied["result"]["compactedSections"] == 0
    assert applied["result"]["compactedDates"] == []
    assert memory_text.startswith(seeded_memory)
    assert "Some small existing content." in memory_text
    assert "A short snippet that fits comfortably." in memory_text
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record('tiny note', [result], 1777456800000)
    assert python_side.rank(1777456800000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(
        1777456800000, "Europe/Istanbul", memory_file_max_chars=10_000, **gates
    )
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_drops_all_old_promotion_sections_when_budget_cannot_fit_otherwise(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-memory-budget-impossible-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-04-29.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-04-29\n\nFresh material still gets written.\n", encoding="utf-8")
        filler = "x" * 600
        seeded_memory = "\n".join(
            [
                "## Promoted From Short-Term Memory (2026-04-10)",
                "<!-- openclaw-memory-promotion:legacy-old -->",
                f"- {filler}",
                "## Promoted From Short-Term Memory (2026-04-15)",
                "<!-- openclaw-memory-promotion:legacy-middle -->",
                f"- {filler}",
                "## Promoted From Short-Term Memory (2026-04-20)",
                "<!-- openclaw-memory-promotion:legacy-newer -->",
                f"- {filler}",
            ]
        )
        (workspace / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-04-29.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "Fresh material still gets written.",
            "score": 0.92,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "fresh material",
                "results": [result],
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1777456800000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
                "memoryFileMaxChars": 700,
            }
        )

    memory_text = applied["files"]["MEMORY.md"]
    assert applied["ok"] is True
    assert applied["result"]["compactedDates"] == ["2026-04-10", "2026-04-15", "2026-04-20"]
    assert "(2026-04-10)" not in memory_text
    assert "(2026-04-15)" not in memory_text
    assert "(2026-04-20)" not in memory_text
    assert "legacy-old" not in memory_text
    assert "legacy-middle" not in memory_text
    assert "legacy-newer" not in memory_text
    assert "Fresh material still gets written." in memory_text
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record('fresh material', [result], 1777456800000)
    assert python_side.rank(1777456800000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(
        1777456800000, "Europe/Istanbul", memory_file_max_chars=700, **gates
    )
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_ranking_skips_promoted_at_entry(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-promoted-at-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        recalls = [
            {
                "query": query,
                "results": [base_result],
                "nowMs": 1779811200000 + index,
            }
            for index, query in enumerate(
                (
                    "backup policy",
                    "glacier backup",
                    "s3 retention",
                    "cold storage",
                    "backup notes",
                )
            )
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        recall_path = workspace / "memory" / ".dreams" / "short-term-recall.json"
        recall_store = json.loads(recall_path.read_text(encoding="utf-8"))
        key = "memory:memory/2026-05-08.md:3:3"
        recall_store["entries"][key]["promotedAt"] = "2026-05-08T12:00:00.000Z"
        recall_path.write_text(json.dumps(recall_store), encoding="utf-8")
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    assert ranked["result"]["candidates"] == []
    python_side.record_sequence(recalls)

    def mark_promoted(store: dict) -> None:
        store["entries"][key]["promotedAt"] = "2026-05-08T12:00:00.000Z"

    python_side.edit_recall_store(mark_promoted)
    gates = {"minScore": 0, "minRecallCount": 1, "minUniqueQueries": 1}
    assert python_side.rank(1779811200000, **gates) == []


def test_real_openclaw_oracle_ignores_contaminated_dreaming_snippets(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    contaminated_snippet = (
        "Candidate: Default to action. confidence: 0.76 evidence: "
        "memory/.dreams/session-corpus/2026-04-08.txt:1-1 recalls: 3 status: staged"
    )
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-contaminated-") as tmp_dir:
        workspace = Path(tmp_dir)
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        recorded = oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "query": "action preference",
                "results": [
                    {
                        "source": "memory",
                        "path": "memory/2026-04-03.md",
                        "startLine": 1,
                        "endLine": 1,
                        "snippet": contaminated_snippet,
                        "score": 0.92,
                    }
                ],
                "nowMs": 1779811200000,
            }
        )
        store_path = workspace / "memory" / ".dreams" / "short-term-recall.json"
        python_side.record(
            "action preference",
            [
                {
                    "source": "memory",
                    "path": "memory/2026-04-03.md",
                    "startLine": 1,
                    "endLine": 1,
                    "snippet": contaminated_snippet,
                    "score": 0.92,
                }
            ],
            1779811200000,
        )
        assert python_side.recall_entries() == _ts_recall_entries(recorded)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "updatedAt": "2026-04-04T00:00:00.000Z",
                    "entries": {
                        "contaminated": {
                            "key": "contaminated",
                            "path": "memory/2026-04-03.md",
                            "startLine": 1,
                            "endLine": 1,
                            "source": "memory",
                            "snippet": (
                                "Reflections: Theme: assistant. confidence: 1.00 evidence: "
                                "memory/.dreams/session-corpus/2026-04-08.txt:2-2 recalls: "
                                "4 status: staged"
                            ),
                            "recallCount": 4,
                            "dailyCount": 0,
                            "groundedCount": 0,
                            "totalScore": 3.6,
                            "maxScore": 0.95,
                            "firstRecalledAt": "2026-04-03T00:00:00.000Z",
                            "lastRecalledAt": "2026-04-04T00:00:00.000Z",
                            "queryHashes": ["a", "b"],
                            "recallDays": ["2026-04-03", "2026-04-04"],
                            "conceptTags": ["assistant"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        shutil.copyfile(store_path, python_side.workspace / _RECALL_STORE)
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert recorded["ok"] is True
    recall_store = json.loads(recorded["files"]["memory/.dreams/short-term-recall.json"])
    assert recall_store["entries"] == {}
    assert ranked["ok"] is True
    assert ranked["result"]["candidates"] == []
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    assert python_side.rank(1779811200000, **gates) == []


def test_real_openclaw_oracle_keeps_candidate_like_daily_memory_evidence(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    snippet = "Candidate: move backups weekly. confidence: 0.76 evidence: memory/2026-04-08.md:1-1"
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-clean-candidate-") as tmp_dir:
        workspace = Path(tmp_dir)
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-04-08.md",
            "startLine": 1,
            "endLine": 1,
            "snippet": snippet,
            "score": 1,
        }
        recalls = [
            {
                "query": query,
                "results": [result],
                "nowMs": 1779811200000 + index,
            }
            for index, query in enumerate(("backup candidate", "weekly backups", "backup evidence"))
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    candidates = ranked["result"]["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["key"] == "memory:memory/2026-04-08.md:1:1"
    assert candidates[0]["snippet"] == snippet
    python_side.record_sequence(recalls)
    gates = {"minScore": 0, "minRecallCount": 1, "minUniqueQueries": 1}
    assert python_side.rank(1779811200000, **gates) == _ts_candidate_views(ranked)


def test_real_openclaw_oracle_apply_skips_candidate_when_live_note_no_longer_contains_snippet(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-stale-source-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Different note content now.\n", encoding="utf-8")
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert ranked["ok"] is True
    assert len(ranked["result"]["candidates"]) == 1
    assert applied["ok"] is True
    assert applied["result"]["applied"] == 0
    assert applied["files"]["MEMORY.md"] == ""
    recall_store = json.loads(applied["files"]["memory/.dreams/short-term-recall.json"])
    assert "promotedAt" not in recall_store["entries"]["memory:memory/2026-05-08.md:3:3"]
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("glacier", [result], 1779811200000)
    assert python_side.rank(1779811200000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(1779811200000, "Europe/Istanbul", **gates)
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_promotion_header_uses_dreaming_timezone(tmp_path: Path):
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-promotion-timezone-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-04-01.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-04-01\n\n- Cross-midnight router maintenance window.\n",
            encoding="utf-8",
        )
        python_side = _PythonPromotion.copy_of(workspace, tmp_path / "python")
        result = {
            "source": "memory",
            "path": "memory/2026-04-01.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Cross-midnight router maintenance window.",
            "score": 0.9,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "router window",
                "results": [result],
                "nowMs": 1775086200000,
                "timezone": "America/Los_Angeles",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1775111400000,
                "timezone": "America/Los_Angeles",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1775111400000,
                "timezone": "America/Los_Angeles",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert "Promoted From Short-Term Memory (2026-04-01)" in applied["files"]["MEMORY.md"]
    gates = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
    python_side.record("router window", [result], 1775086200000)
    assert python_side.rank(1775111400000, **gates) == _ts_candidate_views(ranked)
    python_run = python_side.apply(1775111400000, "America/Los_Angeles", **gates)
    _assert_apply_matches(applied, python_run, python_side)


def test_real_openclaw_oracle_history_limit_helpers_match_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    config = {
        "channels": {
            "telegram": {
                "dmHistoryLimit": 15,
                "dms": {
                    "123": {"historyLimit": 5},
                    "789": {"historyLimit": 0},
                },
            },
            "slack": {"historyLimit": 10, "dmHistoryLimit": 20},
        }
    }
    messages = [
        _user_history("u1"),
        _assistant_history("a1"),
        _user_history("u2"),
        _assistant_history("a2"),
        _tool_result("tool after a2"),
        _user_history("u3"),
    ]

    result = oracle.run(
        {
            "operation": "historyLimit",
            "config": config,
            "messages": messages,
            "limit": 2,
            "keys": [
                "telegram:dm:123",
                "telegram:dm:456",
                "telegram:dm:789",
                "agent:beta:slack:channel:c1",
                "telegram:slash:123",
                "unknown:dm:123",
            ],
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "historyLimit"
    assert result["result"]["limitedMessages"] == limit_history_turns(messages, 2)
    assert result["result"]["limits"] == {
        "telegram:dm:123": get_history_limit_from_session_key("telegram:dm:123", config),
        "telegram:dm:456": get_history_limit_from_session_key("telegram:dm:456", config),
        "telegram:dm:789": get_history_limit_from_session_key("telegram:dm:789", config),
        "agent:beta:slack:channel:c1": get_history_limit_from_session_key(
            "agent:beta:slack:channel:c1", config
        ),
        "telegram:slash:123": get_history_limit_from_session_key("telegram:slash:123", config),
        "unknown:dm:123": get_history_limit_from_session_key("unknown:dm:123", config),
    }


def test_real_openclaw_oracle_repair_tool_use_result_pairing_matches_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "toolCall", "id": "call_1", "name": "read", "arguments": {}},
                {"type": "toolCall", "id": "call_2", "name": "exec", "arguments": {}},
            ],
        },
        {"role": "user", "content": "this should come after tool results"},
        {
            "role": "toolResult",
            "toolCallId": "call_2",
            "toolName": "exec",
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
        },
    ]

    result = oracle.run(
        {
            "operation": "repairToolUseResultPairing",
            "messages": messages,
            "text": "aborted",
        }
    )
    python_result = repair_tool_use_result_pairing(messages, missing_tool_result_text="aborted")

    assert result["ok"] is True
    assert result["operation"] == "repairToolUseResultPairing"
    assert result["result"] == {
        "messages": _normalize_repair_messages(python_result.messages),
        "added": _normalize_repair_messages(python_result.added),
        "droppedDuplicateCount": python_result.dropped_duplicate_count,
        "droppedOrphanCount": python_result.dropped_orphan_count,
        "moved": python_result.moved,
    }


def test_real_openclaw_oracle_repair_tool_use_result_pairing_drops_aborted_results():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": "call_aborted", "name": "exec", "arguments": {}}],
            "stopReason": "aborted",
        },
        {
            "role": "toolResult",
            "toolCallId": "call_aborted",
            "toolName": "exec",
            "content": [{"type": "text", "text": "partial"}],
            "isError": False,
        },
        {"role": "user", "content": "retry"},
    ]

    result = oracle.run(
        {
            "operation": "repairToolUseResultPairing",
            "messages": messages,
            "erroredAssistantResultPolicy": "drop",
        }
    )
    python_result = repair_tool_use_result_pairing(
        messages,
        errored_assistant_result_policy="drop",
    )

    assert result["ok"] is True
    assert result["result"] == {
        "messages": _normalize_repair_messages(python_result.messages),
        "added": _normalize_repair_messages(python_result.added),
        "droppedDuplicateCount": python_result.dropped_duplicate_count,
        "droppedOrphanCount": python_result.dropped_orphan_count,
        "moved": python_result.moved,
    }


def test_real_openclaw_oracle_runtime_context_prompt_helpers_match_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    prompt = "\n\n".join(["runtime prefix", "visible ask", "retry instruction"])
    effective_prompt = "\n\n".join(
        [
            prompt,
            "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>\nsecret runtime context\n<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
        ]
    )
    current_context = {"text": "Current message:\n#34975 obviyus:", "promptJoiner": " "}

    result = oracle.run(
        {
            "operation": "runtimeContextPrompt",
            "prompt": effective_prompt,
            "text": "visible ask",
            "systemPrompt": effective_prompt,
            "entry": current_context,
        }
    )
    python_parts = resolve_runtime_context_prompt_parts(
        effective_prompt=effective_prompt,
        transcript_prompt="visible ask",
        model_prompt=effective_prompt,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    python_custom_message = build_runtime_context_custom_message(
        "secret runtime context",
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert result["ok"] is True
    assert result["operation"] == "runtimeContextPrompt"
    assert result["result"] == {
        "parts": python_parts,
        "currentInboundPrompt": build_current_inbound_prompt(
            context=current_context,
            prompt="What do you mean hidden?",
        ),
        "customMessage": _normalize_runtime_custom_message(python_custom_message),
    }


def test_real_openclaw_oracle_context_engine_lifecycle_strips_runtime_context():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "old ask"}], "timestamp": 1},
        {
            "role": "custom",
            "customType": "openclaw.runtime-context",
            "content": "old hidden",
            "display": False,
            "details": {"source": "openclaw-runtime-context"},
            "timestamp": 2,
        },
        {"role": "assistant", "content": [{"type": "text", "text": "old answer"}], "timestamp": 3},
        {"role": "user", "content": [{"type": "text", "text": "new ask"}], "timestamp": 4},
        {
            "role": "custom",
            "customType": "openclaw.runtime-context",
            "content": "new hidden",
            "display": False,
            "details": {"source": "openclaw-runtime-context"},
            "timestamp": 5,
        },
        {"role": "assistant", "content": [{"type": "text", "text": "new answer"}], "timestamp": 6},
    ]

    result = oracle.run(
        {
            "operation": "contextEngineLifecycle",
            "messages": messages,
            "limit": 3,
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "contextEngineLifecycle"
    assert result["result"] == {
        "assembleMessages": assemble_context_engine_messages(
            messages,
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        ),
        "conversationSnapshot": build_context_engine_conversation_snapshot(
            messages_snapshot=messages,
            pre_prompt_message_count=3,
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        ),
    }


def test_real_openclaw_oracle_normalize_assistant_replay_content_matches_python():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    zero_usage = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
    }
    messages = [
        {"role": "user", "content": "hello", "timestamp": 0},
        {
            "role": "assistant",
            "content": [],
            "provider": "amazon-bedrock",
            "model": "anthropic.claude-3-haiku-20240307-v1:0",
            "usage": zero_usage,
            "stopReason": "error",
            "timestamp": 0,
        },
        {"role": "user", "content": [{"type": "text", "text": "   "}], "timestamp": 0},
        {
            "role": "assistant",
            "content": "plain string",
            "provider": "amazon-bedrock",
            "model": "anthropic.claude-3-haiku-20240307-v1:0",
            "usage": {"input": 1, "output": 1, "totalTokens": 2},
            "stopReason": "stop",
            "timestamp": 0,
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "channel mirror"}],
            "provider": "openclaw",
            "model": "delivery-mirror",
            "timestamp": 0,
        },
    ]

    result = oracle.run({"operation": "normalizeAssistantReplayContent", "messages": messages})

    assert result["ok"] is True
    assert result["operation"] == "normalizeAssistantReplayContent"
    assert result["result"]["messages"] == normalize_assistant_replay_content(messages)


# --- workspace bootstrap (memory_core.bootstrap) -------------------------------------------------

from memory_core.bootstrap import (  # noqa: E402
    OPENCLAW_PIN_LAYOUT,
    WorkspaceBootstrapFile,
    analyze_bootstrap_budget,
    append_bootstrap_prompt_warning,
    build_bootstrap_context_files,
    build_bootstrap_injection_stats,
    build_bootstrap_prompt_section_lines,
    build_bootstrap_prompt_warning,
    build_bootstrap_prompt_warning_notice,
    build_startup_context,
    bootstrap_status,
    filter_bootstrap_files,
    filter_bootstrap_files_for_session,
    initialize_agent_workspace,
    is_workspace_setup_completed,
    load_workspace_bootstrap_files,
    render_project_context,
    render_workspace_files_injected,
)
from memory_core.bootstrap._js import js_to_well_formed  # noqa: E402
from memory_core.bootstrap.budget import ContextFile  # noqa: E402

UPSTREAM_TEMPLATE_PATHS = {
    "AGENTS.md": "docs/reference/templates/AGENTS.md",
    "SOUL.md": "docs/reference/templates/SOUL.md",
    "TOOLS.md": "docs/reference/templates/TOOLS.md",
    "IDENTITY.md": "docs/reference/templates/IDENTITY.md",
    "USER.md": "docs/reference/templates/USER.md",
    "HEARTBEAT.md": "src/agents/templates/HEARTBEAT.md",
    "BOOTSTRAP.md": "docs/reference/templates/BOOTSTRAP.md",
}


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))


def _upstream_templates() -> dict[str, str]:
    # Test-only: the oracle's own template files stand in for host-supplied templates so the
    # seeding comparison uses identical inputs. Nothing here reaches memory-core defaults.
    repo = Path(os.environ["OPENCLAW_ORACLE_REPO"])
    return {
        name: (repo / relative).read_bytes().decode("utf-8")
        for name, relative in UPSTREAM_TEMPLATE_PATHS.items()
    }


def _bootstrap_file_payload(file: WorkspaceBootstrapFile) -> dict:
    payload = {"name": file.name, "path": file.path, "missing": file.missing}
    if not file.missing and file.content is not None:
        payload["content"] = file.content
    return payload


def _context_file_payload(file: ContextFile) -> dict:
    return {"path": file.path, "content": file.content}


def _stat_payload(stat) -> dict:
    return {
        "name": stat.name,
        "path": stat.path,
        "missing": stat.missing,
        "rawChars": stat.raw_chars,
        "injectedChars": stat.injected_chars,
        "truncated": stat.truncated,
    }


def _python_bootstrap_context_report(
    files: list[WorkspaceBootstrapFile],
    *,
    max_chars: int,
    total_max_chars: int | None,
    warning_mode: str = "always",
    seen_signatures: list[str] | None = None,
) -> dict:
    built = build_bootstrap_context_files(files, max_chars=max_chars, total_max_chars=total_max_chars)
    stats = build_bootstrap_injection_stats(files, built.files)
    analysis = analyze_bootstrap_budget(
        stats,
        bootstrap_max_chars=max_chars,
        bootstrap_total_max_chars=total_max_chars if total_max_chars is not None else 60_000,
    )
    warning = build_bootstrap_prompt_warning(
        analysis,
        mode=warning_mode,
        seen_signatures=seen_signatures,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    return {
        "contextFiles": [_context_file_payload(file) for file in built.files],
        "warnings": list(built.warnings),
        "stats": [_stat_payload(stat) for stat in stats],
        "analysis": {
            "files": [
                {**_stat_payload(file), "nearLimit": file.near_limit, "causes": list(file.causes)}
                for file in analysis.files
            ],
            "totalNearLimit": analysis.total_near_limit,
            "hasTruncation": analysis.has_truncation,
            "totals": {
                "rawChars": analysis.raw_chars,
                "injectedChars": analysis.injected_chars,
                "truncatedChars": analysis.truncated_chars,
                "bootstrapMaxChars": analysis.bootstrap_max_chars,
                "bootstrapTotalMaxChars": analysis.bootstrap_total_max_chars,
                "nearLimitRatio": analysis.near_limit_ratio,
            },
        },
        "promptWarning": {
            "signature": warning.signature,
            "warningShown": warning.warning_shown,
            "lines": list(warning.lines),
            "warningSignaturesSeen": list(warning.warning_signatures_seen),
        },
        "notice": build_bootstrap_prompt_warning_notice(warning.lines),
        "appended": append_bootstrap_prompt_warning("Prompt body", warning.lines),
    }


def _agents_policy_fixture() -> str:
    lines = ["# AGENTS.md - Workspace rules", ""]
    for index in range(60):
        lines.append(f"Prose paragraph {index} about the day, ünïcödé 記憶 and 😀 emoji filler text.")
        if index % 7 == 0:
            lines.append(f"- You must read scoped AGENTS.md files before subtree edits ({index}).")
        if index % 11 == 0:
            lines.append(f"## Section {index}")
        if index % 13 == 0:
            lines.append(f"  2) Never commit secrets; run the test command before push #{index}.")
        if index % 17 == 0:
            lines.append("Security:   credential   handling\tIS required " + "long " * 70)
    lines.append("COMMİT with dotted İ is not an ASCII keyword; ſecurity folds to security.")
    lines.append("final line")
    return "\n".join(lines) + "\n\n"


BOOTSTRAP_CONTEXT_CASES = [
    pytest.param(
        [
            {"name": "SOUL.md", "path": "/w/SOUL.md", "content": "\n".join(
                f"line {i} " + "x" * 40 for i in range(400)
            )},
            {"name": "USER.md", "path": "/w/USER.md", "missing": True},
            {"name": "TOOLS.md", "path": "/w/TOOLS.md", "content": "short\n"},
        ],
        300,
        700,
        id="probe-head-tail",
    ),
    pytest.param(
        [{"name": "SOUL.md", "path": "/w/SOUL.md", "content": "\n".join(
            f"line {i} " + "x" * 40 for i in range(400)
        )}],
        80,
        700,
        id="compact-marker",
    ),
    pytest.param(
        [{"name": "AGENTS.md", "path": "/w/AGENTS.md", "content": _agents_policy_fixture()}],
        900,
        None,
        id="agents-policy-digest",
    ),
    pytest.param(
        [{"name": "agents.md", "path": "/w/agents.md", "content": _agents_policy_fixture()}],
        150,
        2000,
        id="agents-digest-tight",
    ),
    pytest.param(
        [
            {"name": "SOUL.md", "path": "/w/SOUL.md", "content": "😀" * 500},
            {"name": "IDENTITY.md", "path": "/w/IDENTITY.md", "content": "記憶と🧠" * 200},
            {"name": "USER.md", "path": "/w/USER.md", "content": "Doruk ğüşiöçİ " * 120},
        ],
        301,
        5000,
        id="surrogate-split-cjk-turkish",
    ),
    pytest.param(
        [
            {"name": "AGENTS.md", "path": "/w/AGENTS.md", "content": "a" * 150},
            {"name": "SOUL.md", "path": "/w/SOUL.md", "content": "b" * 150},
            {"name": "TOOLS.md", "path": "/w/TOOLS.md", "missing": True},
            {"name": "USER.md", "path": "/w/USER.md", "content": "c" * 30},
            {"name": "MEMORY.md", "path": "/w/MEMORY.md", "content": "d" * 30},
        ],
        150,
        330,
        id="total-budget-exhaustion",
    ),
    pytest.param(
        [
            {"name": "AGENTS.md", "path": "/w/AGENTS.md", "content": "a" * 20},
            {"name": "SOUL.md", "path": "/w/SOUL.md", "missing": True},
            {"name": "USER.md", "path": "/w/USER.md", "missing": True},
        ],
        20,
        40,
        id="missing-marker-clamp-then-break",
    ),
    pytest.param(
        [
            {"name": "SOUL.md", "path": "   ", "content": "no path"},
            {"name": "USER.md", "path": "  /w/USER.md  ", "content": "tail spaces\u00a0\u3000\ufeff \u2028\n"},
            {"name": "TOOLS.md", "path": "/w/TOOLS.md", "content": "keeps NEL\u0085"},
            {"name": "IDENTITY.md", "path": "/w/IDENTITY.md", "content": " \n\t "},
        ],
        200,
        None,
        id="paths-and-js-whitespace",
    ),
    pytest.param(
        [
            {"name": "SOUL.md", "path": f"/w/agent-{index}/SOUL.md", "content": "s" * (400 + index)}
            for index in range(5)
        ],
        256,
        60_000,
        id="duplicate-names-report",
    ),
]


@pytest.mark.parametrize(("files", "max_chars", "total_max_chars"), BOOTSTRAP_CONTEXT_CASES)
def test_real_openclaw_oracle_bootstrap_context_files_match_python(files, max_chars, total_max_chars):
    payload = {
        "operation": "bootstrapContextFiles",
        "bootstrapFiles": files,
        "maxChars": max_chars,
    }
    if total_max_chars is not None:
        payload["totalMaxChars"] = total_max_chars

    result = _oracle().run(payload)

    assert result["ok"] is True, result
    python_files = [
        WorkspaceBootstrapFile(
            name=file["name"],
            path=file["path"],
            content=file.get("content"),
            missing=file.get("missing", False),
        )
        for file in files
    ]
    assert result["result"] == _python_bootstrap_context_report(
        python_files, max_chars=max_chars, total_max_chars=total_max_chars
    )


def test_real_openclaw_oracle_bootstrap_warning_once_mode_matches_python():
    files = [
        {"name": "AGENTS.md", "path": "/w/AGENTS.md", "content": _agents_policy_fixture()},
        {"name": "SOUL.md", "path": "/w/SOUL.md", "content": "é" * 3000},
    ]
    python_files = [WorkspaceBootstrapFile(f["name"], f["path"], f["content"]) for f in files]
    first = _oracle().run(
        {"operation": "bootstrapContextFiles", "bootstrapFiles": files, "maxChars": 1000}
    )
    assert first["ok"] is True, first
    signature = first["result"]["promptWarning"]["signature"]
    assert signature == _python_bootstrap_context_report(
        python_files, max_chars=1000, total_max_chars=None
    )["promptWarning"]["signature"]

    second = _oracle().run(
        {
            "operation": "bootstrapContextFiles",
            "bootstrapFiles": files,
            "maxChars": 1000,
            "warningMode": "once",
            "seenSignatures": [signature, "  ", signature],
        }
    )

    assert second["ok"] is True, second
    assert second["result"]["promptWarning"]["warningShown"] is False
    assert second["result"] == _python_bootstrap_context_report(
        python_files,
        max_chars=1000,
        total_max_chars=None,
        warning_mode="once",
        seen_signatures=[signature, "  ", signature],
    )


def _session_kind_for_key(session_key: str) -> str:
    rest = session_key.split(":", 2)[2].lower()
    if rest.startswith("subagent:"):
        return "subagent"
    if rest.startswith("cron:"):
        return "cron"
    return "main"


def _write_bootstrap_workspace(root: Path, files: dict[str, str | bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


BOOTSTRAP_SESSION_KEYS = [
    "agent:main:main",
    "agent:main:subagent:helper-1",
    "agent:main:cron:nightly",
    "agent:main:telegram:group:42",
    "agent:main:discord:channel:general",
]
BOOTSTRAP_RUNS = [
    {"sessionKey": "agent:main:main"},
    {"sessionKey": "agent:main:telegram:group:42"},
    {"sessionKey": "agent:main:subagent:helper-1"},
    {"sessionKey": "agent:main:cron:nightly", "runKind": "cron"},
    {"sessionKey": "agent:main:main", "runKind": "heartbeat"},
    {"sessionKey": "agent:main:main", "contextMode": "lightweight", "runKind": "heartbeat"},
    {"sessionKey": "agent:main:main", "contextMode": "lightweight", "runKind": "default"},
    {"sessionKey": "agent:main:main", "runKind": "commitment-only"},
]


def _full_workspace_files() -> dict[str, str | bytes]:
    return {
        "AGENTS.md": "# Rules\r\n- Never push.\r\n\r\n\r\n",
        "SOUL.md": "Calm, direct. 🧠\n",
        "TOOLS.md": "## Tools\n- rg\n",
        "IDENTITY.md": "Name: memory-core\nEmoji: 🧠\n",
        "USER.md": "Doruk; prefers Türkçe. ğüşİ\n",
        "HEARTBEAT.md": "# Keep empty\n\n- check inbox\n",
        "BOOTSTRAP.md": "Run the ritual.\n",
        "MEMORY.md": "- Decision: 記憶 stays local.\n",
        "memory/2026-09-26.md": "daily note\n",
        "extra/NOTES.md": "not a bootstrap file\n",
    }


def _python_workspace_bootstrap_result(root: Path, keys: list[str], runs: list[dict]) -> dict:
    loaded = load_workspace_bootstrap_files(root, OPENCLAW_PIN_LAYOUT)
    setup_completed = is_workspace_setup_completed(root)
    python_runs = []
    for run in runs:
        files = filter_bootstrap_files(
            loaded,
            root=root,
            layout=OPENCLAW_PIN_LAYOUT,
            session_kind=_session_kind_for_key(run["sessionKey"]),
            setup_completed=setup_completed,
            context_mode=run.get("contextMode", "full"),
            run_kind=run.get("runKind", "default"),
            include_heartbeat=True,
        )
        built = build_bootstrap_context_files(files, max_chars=20_000, total_max_chars=60_000)
        python_runs.append(
            {
                "run": run,
                "bootstrapFiles": [_bootstrap_file_payload(file) for file in files],
                "contextFiles": [_context_file_payload(file) for file in built.files],
                "warnings": list(built.warnings),
            }
        )
    return {
        "loaded": [_bootstrap_file_payload(file) for file in loaded],
        "bySessionKey": {
            key: [
                _bootstrap_file_payload(file)
                for file in filter_bootstrap_files_for_session(
                    loaded, _session_kind_for_key(key), OPENCLAW_PIN_LAYOUT
                )
            ]
            for key in keys
        },
        "runs": python_runs,
        "setupCompleted": setup_completed,
        "bootstrapStatus": bootstrap_status(root, OPENCLAW_PIN_LAYOUT),
    }


def _workspace_scenario_full(root: Path) -> None:
    _write_bootstrap_workspace(root, _full_workspace_files())


def _workspace_scenario_missing_and_lowercase_memory(root: Path) -> None:
    files = _full_workspace_files()
    for name in ("SOUL.md", "MEMORY.md", "BOOTSTRAP.md"):
        files.pop(name)
    files["memory.md"] = "legacy lowercase memory\n"
    _write_bootstrap_workspace(root, files)


def _workspace_scenario_completed_setup(root: Path) -> None:
    _write_bootstrap_workspace(root, _full_workspace_files())
    (root / "openclaw-workspace-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "bootstrapSeededAt": "2026-09-01T00:00:00.000Z",
                "setupCompletedAt": "2026-09-02T00:00:00.000Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _workspace_scenario_guarded_reads(root: Path) -> None:
    files = _full_workspace_files()
    files["TOOLS.md"] = b"t" * (2 * 1024 * 1024 + 1)
    files.pop("IDENTITY.md")
    files.pop("USER.md")
    files["SOUL.md"] = b"bad utf8 \xff\xfe tail \xe2\x82\n"
    _write_bootstrap_workspace(root, files)
    outside = root.parent / f"{root.name}-outside.md"
    outside.write_text("outside secret\n", encoding="utf-8")
    (root / "IDENTITY.md").symlink_to(outside)
    os.link(root / "HEARTBEAT.md", root / "USER.md")


WORKSPACE_BOOTSTRAP_SCENARIOS = [
    pytest.param(_workspace_scenario_full, id="all-files"),
    pytest.param(_workspace_scenario_missing_and_lowercase_memory, id="missing-lowercase-memory"),
    pytest.param(_workspace_scenario_completed_setup, id="setup-completed-drops-bootstrap"),
    pytest.param(_workspace_scenario_guarded_reads, id="guarded-reads"),
]


@pytest.mark.parametrize("scenario", WORKSPACE_BOOTSTRAP_SCENARIOS)
def test_real_openclaw_oracle_workspace_bootstrap_files_match_python(tmp_path: Path, scenario):
    root = tmp_path / "workspace"
    scenario(root)

    result = _oracle().run(
        {
            "operation": "workspaceBootstrapFiles",
            "workspaceDir": str(root),
            "keys": BOOTSTRAP_SESSION_KEYS,
            "runs": BOOTSTRAP_RUNS,
        }
    )

    assert result["ok"] is True, result
    assert result["result"] == _python_workspace_bootstrap_result(
        root, BOOTSTRAP_SESSION_KEYS, BOOTSTRAP_RUNS
    )


HEARTBEAT_PROMPT_BLOCK = (
    "Default heartbeat prompt:\n`Read HEARTBEAT.md if it exists (workspace context). Follow it "
    "strictly. Do not infer or repeat old tasks from prior chats. If nothing needs attention, "
    "reply HEARTBEAT_OK.`"
)
RENDER_CONTEXT_FILES = [
    {"path": "/w/extra/NOTES.md", "content": "extra notes"},
    {"path": "/w/MEMORY.md", "content": "- 記憶\n\n\n\n- two"},
    {"path": "/w/HEARTBEAT.md", "content": f"tasks\n\n\n{HEARTBEAT_PROMPT_BLOCK}\n\n\nafter"},
    {"path": "/w/Zeta.md", "content": "zeta"},
    {"path": "/w/TOOLS.md", "content": "tools"},
    {"path": "/w/BOOTSTRAP.md", "content": "ritual 🧠"},
    {"path": "/w/alpha.md", "content": "alpha"},
    {"path": "/w/USER.md", "content": "Doruk ğüş"},
    {"path": "/w/IDENTITY.md", "content": ""},
    {"path": "/w/SOUL.md", "content": "calm\n\nwarm"},
    {"path": "/w/AGENTS.md", "content": "rules"},
    {"path": "/w/nested/AGENTS.md", "content": "nested rules"},
]
PROJECT_CONTEXT_RENDER_CASES = [
    pytest.param(RENDER_CONTEXT_FILES, "full", "[Bootstrap truncation warning]\nnotice", id="all-full"),
    pytest.param(
        [file for file in RENDER_CONTEXT_FILES if "BOOTSTRAP" not in file["path"]],
        "full",
        None,
        id="full-without-bootstrap-file",
    ),
    pytest.param(
        [{"path": "/w/HEARTBEAT.md", "content": "only heartbeat"}], "limited", None, id="dynamic-only"
    ),
    pytest.param([], "none", "  ", id="empty"),
    pytest.param(
        [{"path": "/w/SOUL.md", "content": "soul"}, {"path": "  ", "content": "blank path"}],
        None,
        None,
        id="soul-only",
    ),
]


@pytest.mark.parametrize(("files", "mode", "notice"), PROJECT_CONTEXT_RENDER_CASES)
def test_real_openclaw_oracle_project_context_render_matches_python(files, mode, notice):
    payload = {"operation": "projectContextRender", "contextFiles": files}
    if mode is not None:
        payload["bootstrapMode"] = mode
    if notice is not None:
        payload["bootstrapTruncationNotice"] = notice

    result = _oracle().run(payload)

    assert result["ok"] is True, result
    context_files = [ContextFile(file["path"], file["content"]) for file in files]
    stable, dynamic = render_project_context(context_files, OPENCLAW_PIN_LAYOUT)
    sections = build_bootstrap_prompt_section_lines(
        mode, truncation_notice=notice, context_files=context_files, layout=OPENCLAW_PIN_LAYOUT
    )
    assert result["result"] == {
        "stable": stable,
        "dynamic": dynamic,
        "workspaceFiles": render_workspace_files_injected(OPENCLAW_COMPAT_RUNTIME_IDENTITY),
        "bootstrapSections": sections,
        "bootstrapPendingInPrompt": "## Bootstrap Pending" in sections,
    }


def _python_tree_snapshot(root: Path) -> dict[str, str | None]:
    skip = {"openclaw-workspace-state.json", ".openclaw", ".memory-core", ".git"}
    out: dict[str, str | None] = {}

    def walk(relative: str) -> None:
        for entry in os.scandir(root / relative if relative else root):
            if not relative and entry.name in skip:
                continue
            rel = f"{relative}/{entry.name}" if relative else entry.name
            if entry.is_dir(follow_symlinks=False):
                out[f"{rel}/"] = None
                walk(rel)
            else:
                out[rel] = (root / rel).read_bytes().decode("utf-8", errors="replace")

    walk("")
    return dict(sorted(out.items()))


def _normalize_state(raw: str | None) -> dict | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    return {
        key: "__iso__"
        if isinstance(value, str)
        and len(value) == 24
        and value[4] == "-"
        and value[10] == "T"
        and value.endswith("Z")
        else value
        for key, value in parsed.items()
    }


def _python_lifecycle_snapshots(root: Path, steps: list[dict]) -> list[dict]:
    templates = _upstream_templates()
    snapshots = []
    for step in steps:
        target = root / step["path"] if step.get("path") else root
        if step["op"] == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(step.get("content", "").encode("utf-8"))
            continue
        if step["op"] == "remove":
            if target.is_dir():
                import shutil

                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            continue
        if step["op"] == "mkdir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        initialize_agent_workspace(
            root,
            layout=OPENCLAW_PIN_LAYOUT,
            templates=templates,
            skip_optional=step.get("skipOptional") or False,
        )
        state_path = root / ".memory-core" / "workspace-state.json"
        snapshots.append(
            {
                "tree": _python_tree_snapshot(root),
                "state": _normalize_state(
                    state_path.read_text(encoding="utf-8") if state_path.exists() else None
                ),
                "status": bootstrap_status(root, OPENCLAW_PIN_LAYOUT),
                "setupCompleted": is_workspace_setup_completed(root),
            }
        )
    return snapshots


LIFECYCLE_SCENARIOS = [
    pytest.param(
        [
            {"op": "ensure"},
            {"op": "ensure"},
            {"op": "write", "path": "USER.md", "content": "Name: Doruk\n"},
            {"op": "ensure"},
            {"op": "remove", "path": "SOUL.md"},
            {"op": "remove", "path": "AGENTS.md"},
            {"op": "ensure"},
        ],
        id="fresh-seed-then-reconcile-deletes-bootstrap",
    ),
    pytest.param(
        [
            {"op": "ensure", "skipOptional": ["SOUL.md", "HEARTBEAT.md"]},
            {"op": "remove", "path": "BOOTSTRAP.md"},
            {"op": "ensure"},
        ],
        id="skip-optional-then-agent-deletes-bootstrap",
    ),
    pytest.param(
        [{"op": "mkdir", "path": "memory"}, {"op": "ensure"}],
        id="memory-dir-counts-as-configured",
    ),
    pytest.param(
        [{"op": "write", "path": "MEMORY.md", "content": "- fact\n"}, {"op": "ensure"}],
        id="memory-file-counts-as-configured",
    ),
    pytest.param(
        [{"op": "write", "path": "skills/demo/SKILL.md", "content": "# skill\n"}, {"op": "ensure"}],
        id="workspace-skill-counts-as-configured",
    ),
    pytest.param(
        [{"op": "mkdir", "path": ".git"}, {"op": "ensure"}],
        id="git-dir-counts-as-configured",
    ),
    pytest.param(
        [{"op": "write", "path": "IDENTITY.md", "content": "Name: memory-core 🧠\n"}, {"op": "ensure"}],
        id="customized-identity-counts-as-configured",
    ),
    pytest.param(
        [
            {
                "op": "write",
                "path": ".openclaw/workspace-state.json",
                "content": '{"onboardingCompletedAt": "2026-01-02T03:04:05.006Z"}',
            },
            {"op": "ensure"},
            {"op": "ensure"},
        ],
        id="legacy-onboarding-state-migrates",
    ),
    pytest.param(
        [
            {"op": "write", "path": "BOOTSTRAP.md", "content": "host ritual\n"},
            {"op": "ensure"},
            {"op": "write", "path": "SOUL.md", "content": "custom soul\n"},
            {"op": "ensure"},
        ],
        id="existing-bootstrap-marked-then-reconciled",
    ),
    pytest.param(
        [
            {"op": "write", "path": "openclaw-workspace-state.json", "content": "not json"},
            {"op": "ensure"},
        ],
        id="corrupt-state-file",
    ),
]


@pytest.mark.parametrize("steps", LIFECYCLE_SCENARIOS)
def test_real_openclaw_oracle_workspace_lifecycle_matches_python(tmp_path: Path, steps):
    ts_root = tmp_path / "ts" / "workspace"
    py_root = tmp_path / "py" / "workspace"
    ts_root.parent.mkdir(parents=True)
    py_root.parent.mkdir(parents=True)

    result = _oracle().run(
        {"operation": "workspaceLifecycle", "workspaceDir": str(ts_root), "steps": steps}
    )

    assert result["ok"] is True, result
    python_snapshots = _python_lifecycle_snapshots(py_root, steps)
    # Each runtime keeps the setup state in its own file (openclaw-workspace-state.json vs
    # .memory-core/workspace-state.json); snapshots compare the parsed states.
    assert result["result"]["snapshots"] == python_snapshots


def _write_daily(root: Path, name: str, content: str | bytes, mtime: int | None = None) -> None:
    path = root / "memory" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _startup_scenario_istanbul(root: Path) -> None:
    _write_daily(root, "2026-09-27.md", "Bugün: Doruk ```code``` notu 🧠\n" * 3)
    _write_daily(root, "2026-09-26.md", "  \n\t\n")
    _write_daily(root, "2026-09-26-1430.md", "slug 1430\n", mtime=1_790_000_000)
    _write_daily(root, "2026-09-26-api-design.md", "api design\n", mtime=1_790_000_500)
    _write_daily(root, "2026-09-26-zeta.md", "zeta same mtime\n", mtime=1_790_000_500)
    _write_daily(root, "2026-09-26-alpha.md", "alpha same mtime\n", mtime=1_790_000_500)
    _write_daily(root, "2026-09-26-ü[x].md", "odd label\n", mtime=1_790_000_100)
    _write_daily(root, "2026-09-26-oldest.md", "oldest\n", mtime=1_700_000_000)
    _write_daily(root, "2026-09-25.md", "too old for the window\n")


def _startup_scenario_caps(root: Path) -> None:
    _write_daily(root, "2026-09-26.md", ("記憶 line with emoji 😀 " * 40 + "\n") * 5)
    _write_daily(root, "2026-09-25.md", "x" * 5000)
    _write_daily(root, "2026-09-27.md", "utc day entry\n")
    _write_daily(root, "2026-09-25-big.md", b"b" * 20_000)


def _startup_scenario_emoji_at_file_cap(root: Path) -> None:
    # The 1,200-unit per-file cut (startup-context.ts:97) splits the emoji's surrogate pair.
    _write_daily(root, "2026-09-26.md", "a" * 1199 + "😀" + "tail\n")


STARTUP_CONTEXT_CASES = [
    pytest.param(_startup_scenario_istanbul, 1_790_458_200_000, "Europe/Istanbul", None, id="istanbul"),
    pytest.param(
        _startup_scenario_caps,
        1_790_474_400_000,
        "America/Los_Angeles",
        None,
        id="los-angeles-utc-day-and-caps",
    ),
    pytest.param(
        _startup_scenario_caps,
        1_790_474_400_000,
        "America/Los_Angeles",
        {"dailyMemoryDays": 3, "maxFileChars": 700, "maxTotalChars": 900, "maxFileBytes": 6000},
        id="custom-limits",
    ),
    pytest.param(lambda root: root.mkdir(parents=True), 1_790_458_200_000, "UTC", None, id="empty"),
    pytest.param(
        _startup_scenario_emoji_at_file_cap, 1_790_458_200_000, "UTC", None, id="emoji-at-file-cap"
    ),
]


@pytest.mark.parametrize(("scenario", "now_ms", "timezone_name", "limits"), STARTUP_CONTEXT_CASES)
def test_real_openclaw_oracle_startup_context_matches_python(
    tmp_path: Path, scenario, now_ms, timezone_name, limits
):
    root = tmp_path / "workspace"
    scenario(root)
    payload = {
        "operation": "startupContext",
        "workspaceDir": str(root),
        "nowMs": now_ms,
        "timezone": timezone_name,
    }
    if limits:
        payload["startupContext"] = limits

    result = _oracle().run(payload)

    assert result["ok"] is True, result
    kwargs = {}
    if limits:
        kwargs = {
            "daily_memory_days": limits["dailyMemoryDays"],
            "max_file_chars": limits["maxFileChars"],
            "max_total_chars": limits["maxTotalChars"],
            "max_file_bytes": limits["maxFileBytes"],
        }
    ts_prelude = result["result"]["prelude"]
    if scenario is _startup_scenario_emoji_at_file_cap:
        assert re.search("[\ud800-\udfff]", ts_prelude)
    # Transport-boundary deviation: memory-core returns the prelude well-formed
    # (String.prototype.toWellFormed), upstream returns the lone surrogate.
    expected = js_to_well_formed(ts_prelude) if ts_prelude is not None else None
    assert expected == build_startup_context(root, now_ms=now_ms, timezone=timezone_name, **kwargs)


def _upstream_source(relative: str) -> str:
    return (Path(os.environ["OPENCLAW_ORACLE_REPO"]) / relative).read_text(encoding="utf-8")


def _upstream_numeric_constants(source: str) -> dict[str, float]:
    import re

    constants: dict[str, float] = {}
    for match in re.finditer(
        r"^(?:export )?const ([A-Z0-9_]+) = ([0-9_.]+(?: \* [0-9_.]+)*);", source, re.MULTILINE
    ):
        value = 1.0
        for factor in match.group(2).split(" * "):
            value *= float(factor.replace("_", ""))
        constants[match.group(1)] = value
    return constants


def test_bootstrap_constants_and_keyword_sets_equal_upstream_source():
    # Set-equality check (AGENTS.md › Parity rules): constants and the AGENTS.md digest keyword
    # lists are extracted from the pinned TS source, not retyped.
    import re

    from memory_core.bootstrap import budget, files, startup

    bootstrap_source = _upstream_source("src/agents/embedded-agent-helpers/bootstrap.ts")
    keyword_sets = [
        match.split("|")
        for match in re.findall(r"/\\b\(\?:([^)]*)\)\\b/iu", bootstrap_source)
    ]
    assert [
        [keyword.replace("\\.", ".") for keyword in keywords] for keywords in keyword_sets
    ] == [list(budget._POLICY_KEYWORDS), list(budget._HIGH_PRIORITY_KEYWORDS)]

    expected_numbers = {
        **_upstream_numeric_constants(bootstrap_source),
        **_upstream_numeric_constants(_upstream_source("src/agents/bootstrap-budget.ts")),
        **_upstream_numeric_constants(_upstream_source("src/auto-reply/reply/startup-context.ts")),
    }
    workspace_numbers = _upstream_numeric_constants(_upstream_source("src/agents/workspace.ts"))
    expected_numbers["MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES"] = workspace_numbers[
        "MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES"
    ]
    python_numbers = {
        name: float(getattr(module, name))
        for module in (budget, files, startup)
        for name in dir(module)
        if name in expected_numbers
    }
    assert python_numbers == expected_numbers


# --- memory budget compaction (extensions/memory-core/src/memory-budget.ts) --------------


def _promotion_section(date: str, size_chars: int, pad: str = "x") -> str:
    # memory-budget.test.ts promotionSection helper; `pad` widens it to non-ASCII padding.
    heading = f"## Promoted From Short-Term Memory ({date})\n"
    return heading + pad * max(0, size_chars - len(heading))


_UPSTREAM_USER_SECTION = "## My Notes\n\nImportant user content I do not want dropped.\n"
_UPSTREAM_REFLECTIONS = "## My Reflections\nMy own notes.\n\n"
_EMOJI_PAD = "\U0001f600"
_ACCENT_PAD = "\u00e9"

MEMORY_BUDGET_CASES = [
    # memory-budget.test.ts inputs, in test order.
    {
        "existingMemory": "# Long-Term Memory\n\nSome content.\n",
        "newSection": "\n## Promoted From Short-Term Memory (2026-04-29)\n- entry\n",
        "budgetChars": 1_000,
    },
    {
        "existingMemory": (
            f"{_promotion_section('2026-04-10', 500)}\n{_promotion_section('2026-04-20', 500)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 500)}",
        "budgetChars": 1_200,
    },
    {
        "existingMemory": "\n".join(
            _promotion_section(date, 400) for date in ("2026-04-25", "2026-04-10", "2026-04-18")
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 400)}",
        "budgetChars": 1_300,
    },
    {
        "existingMemory": (
            f"# Long-Term Memory\n\n{_UPSTREAM_USER_SECTION}\n{_promotion_section('2026-04-10', 800)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 600)}",
        "budgetChars": 800,
    },
    {
        "existingMemory": "\n".join(
            _promotion_section(date, 600) for date in ("2026-04-10", "2026-04-15", "2026-04-20")
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 600)}",
        "budgetChars": 700,
    },
    {
        "existingMemory": "# Long-Term Memory\n\nLots of user content here.\n" * 50,
        "newSection": f"\n{_promotion_section('2026-04-29', 200)}",
        "budgetChars": 500,
    },
    {
        "existingMemory": _promotion_section("2026-04-10", 500),
        "newSection": f"\n{_promotion_section('2026-04-29', 500)}",
        "budgetChars": 0,
    },
    {"existingMemory": "", "newSection": _promotion_section("2026-04-29", 500), "budgetChars": 100},
    {
        "existingMemory": (
            f"{_promotion_section('2026-04-10', 400)}\n{_UPSTREAM_REFLECTIONS}"
            f"{_promotion_section('2026-04-20', 400)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 400)}",
        "budgetChars": 900,
    },
    {
        "existingMemory": (
            f"{_promotion_section('2026-04-10', 200)}\n{_promotion_section('2026-04-20', 200)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 200)}",
        "budgetChars": 500,
    },
    {
        "existingMemory": (
            f"{_promotion_section('2026-04-10', 1_000)}\n{_promotion_section('2026-04-20', 1_000)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 1_000)}",
        "budgetChars": 2_000,
    },
    # Block-parser edges built from the upstream strings above.
    {
        "existingMemory": (
            f"# Long-Term Memory\n\n{_UPSTREAM_USER_SECTION}\n{_promotion_section('2026-04-10', 800)}"
        ).replace("\n", "\r\n"),
        "newSection": f"\n{_promotion_section('2026-04-29', 600)}",
        "budgetChars": 800,
    },
    {
        "existingMemory": (
            f"{_UPSTREAM_USER_SECTION}"
            "## Promoted From Short-Term Memory (2026-04-10) \t\n- entry\n"
            "### Promoted From Short-Term Memory (2026-04-11)\n- entry\n"
            "## Promoted From Short-Term Memory ()\n- entry\n"
            "##Promoted From Short-Term Memory (2026-04-12)\n- entry\n"
            "## promoted from short-term memory (2026-04-13)\n- entry\n"
            f"{_UPSTREAM_REFLECTIONS}"
        ),
        "newSection": "",
        "budgetChars": 1,
    },
    {
        "existingMemory": "\n".join(
            _promotion_section(date, 300) for date in ("2026-04-20", "2026-04-10", "2026-04-10")
        ),
        "newSection": "",
        "budgetChars": 650,
    },
    {
        "existingMemory": (
            f"# Long-Term Memory\n\n{_UPSTREAM_USER_SECTION}\n"
            f"{_promotion_section('2026-04-10', 300, pad=_EMOJI_PAD)}\n"
            f"{_promotion_section('2026-04-20', 300, pad=_ACCENT_PAD)}"
        ),
        "newSection": f"\n{_promotion_section('2026-04-29', 100, pad=_EMOJI_PAD)}",
        "budgetChars": 800,
    },
    {
        "existingMemory": (
            f"# Long-Term Memory\n\nSome content.\n\n{_promotion_section('2026-04-10', 200)}\n"
            f"{_UPSTREAM_USER_SECTION}\n{_promotion_section('2026-04-20', 200)}\n"
            f"{_UPSTREAM_REFLECTIONS}"
        ),
        "newSection": "",
        "budgetChars": 1,
    },
]


def test_real_openclaw_oracle_memory_budget_compaction_matches_python():
    from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS, compact_memory_for_budget

    result = _oracle().run({"operation": "memoryBudgetCompaction", "cases": MEMORY_BUDGET_CASES})

    assert result["ok"] is True, result
    assert result["result"]["defaultMemoryFileMaxChars"] == DEFAULT_MEMORY_FILE_MAX_CHARS
    python_cases = []
    for case in MEMORY_BUDGET_CASES:
        compacted = compact_memory_for_budget(
            existing_memory=case["existingMemory"],
            new_section=case["newSection"],
            budget_chars=case["budgetChars"],
        )
        python_cases.append(
            {"compacted": compacted.compacted, "droppedDates": list(compacted.dropped_dates)}
        )
    assert result["result"]["cases"] == python_cases
