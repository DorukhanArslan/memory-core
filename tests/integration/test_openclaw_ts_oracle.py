import os
from pathlib import Path
import json
import tempfile

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
    OPENCLAW_COMPAT_BRANDING,
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


def test_real_openclaw_oracle_deep_policy_uses_configured_values():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run(
        {
            "operation": "deepPolicy",
            "config": {
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
            },
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["enabled"] is True
    assert result["result"]["limit"] == 7
    assert result["result"]["minScore"] == 0.72
    assert result["result"]["minRecallCount"] == 4
    assert result["result"]["minUniqueQueries"] == 2
    assert result["result"]["maxAgeDays"] == 14
    assert result["result"]["recencyHalfLifeDays"] == 10


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


def test_real_openclaw_oracle_records_short_term_recall():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-integration-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
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


def test_real_openclaw_oracle_records_short_term_recall_sequence():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-sequence-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-26.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- User prefers to be addressed as dodo.",
            "score": 1,
        }
        result = oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
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
                ],
            }
        )

    assert result["ok"] is True
    assert result["operation"] == "recordShortTermRecallSequence"
    recall_store = json.loads(result["files"]["memory/.dreams/short-term-recall.json"])
    entries = recall_store["entries"]
    entry = entries["memory:memory/2026-05-26.md:3:3"]
    assert len(entries) == 1
    assert entry["recallCount"] == 2
    assert entry["queryHashes"] == ["aa5368a7c7bd", "1da206d81a95"]
    assert entry["recallDays"] == ["2026-05-26", "2026-05-27"]


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
            ["backup", "backups", "glacier", "qmd", "router", "sync"],
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


def test_real_openclaw_oracle_ranks_short_term_promotion_candidate():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-ranking-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
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
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [base_result],
                        "nowMs": 1779811200000 + index * 86_400_000,
                    }
                    for index, query in enumerate(queries)
                ],
            }
        )
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


def test_real_openclaw_oracle_first_promotion_write_bootstraps_memory_header():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-first-promotion-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
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


def test_real_openclaw_oracle_second_apply_reconciles_existing_marker_without_duplicate():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-duplicate-apply-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
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


def test_real_openclaw_oracle_ranking_applies_max_age_gate():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-max-age-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
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


def test_real_openclaw_oracle_ranking_uses_recency_half_life_days():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-recency-half-life-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
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


def test_real_openclaw_oracle_ranking_applies_score_recall_unique_query_and_limit_gates():
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
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
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
                ],
            }
        )
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


def test_real_openclaw_oracle_reconciles_existing_promotion_marker():
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
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
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
                ],
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


def test_real_openclaw_oracle_reconciles_spaced_case_insensitive_promotion_marker():
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


def test_real_openclaw_oracle_compacts_oldest_promotion_section_when_memory_budget_exceeded():
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


def test_real_openclaw_oracle_leaves_memory_unchanged_before_append_when_budget_fits():
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


def test_real_openclaw_oracle_drops_all_old_promotion_sections_when_budget_cannot_fit_otherwise():
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


def test_real_openclaw_oracle_ranking_skips_promoted_at_entry():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-promoted-at-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
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
                ],
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


def test_real_openclaw_oracle_ignores_contaminated_dreaming_snippets():
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


def test_real_openclaw_oracle_keeps_candidate_like_daily_memory_evidence():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    snippet = "Candidate: move backups weekly. confidence: 0.76 evidence: memory/2026-04-08.md:1-1"
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-clean-candidate-") as tmp_dir:
        workspace = Path(tmp_dir)
        result = {
            "source": "memory",
            "path": "memory/2026-04-08.md",
            "startLine": 1,
            "endLine": 1,
            "snippet": snippet,
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [result],
                        "nowMs": 1779811200000 + index,
                    }
                    for index, query in enumerate(
                        ("backup candidate", "weekly backups", "backup evidence")
                    )
                ],
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


def test_real_openclaw_oracle_apply_skips_candidate_when_live_note_no_longer_contains_snippet():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-stale-source-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Different note content now.\n", encoding="utf-8")
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


def test_real_openclaw_oracle_promotion_header_uses_dreaming_timezone():
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
        branding=OPENCLAW_COMPAT_BRANDING,
    )
    python_custom_message = build_runtime_context_custom_message(
        "secret runtime context",
        branding=OPENCLAW_COMPAT_BRANDING,
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
            branding=OPENCLAW_COMPAT_BRANDING,
        ),
        "conversationSnapshot": build_context_engine_conversation_snapshot(
            messages_snapshot=messages,
            pre_prompt_message_count=3,
            branding=OPENCLAW_COMPAT_BRANDING,
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
