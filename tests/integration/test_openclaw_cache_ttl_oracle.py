"""Cache-TTL provider eligibility and the session marker against the real v2026.9.6 TypeScript.

``isCacheTtlEligibleProvider`` and ``readLastCacheTtlTimestamp`` (cache-ttl.ts) and
``appendAttemptCacheTtlIfNeeded`` (run/attempt-thread-helpers.ts) run over a corpus of providers,
models, APIs and routes. The runner registers no provider plugin, so the oracle side exercises the
core rules; the plugin hook is covered in ``tests/unit/test_cache_ttl.py`` because no plugin can be
registered from the oracle. The ``attempt-setup.ts`` transform that calls the pruning is not
reachable (it is built inline inside the attempt installer): see the unit tests.
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import tool_result_projection as projection
from memory_core.cache_ttl import (
    append_attempt_cache_ttl_if_needed,
    is_cache_ttl_eligible_provider,
    read_last_cache_ttl_timestamp,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

PROVIDERS = [
    "anthropic",
    "Anthropic",
    "  anthropic-vertex  ",
    "amazon-bedrock",
    "AMAZON-BEDROCK",
    "kilocode",
    "KiloCode",
    "openrouter",
    "google",
    "google-vertex",
    "openai",
    "custom-proxy",
    "",
    "   ",
]
MODEL_IDS = [
    "claude-sonnet-4-6",
    "anthropic.claude-3-haiku",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-opus-4-6-v1",
    "Anthropic/Claude-Opus",
    "anthropic/claude-sonnet-4",
    "ANTHROPIC/x",
    "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/my-claude-profile",
    "arn:aws-cn:bedrock:cn-north-1:123456789012:application-inference-profile/Claude-Prod",
    "arn:aws-us-gov:bedrock:us-gov-west-1:123456789012:application-inference-profile/claude",
    "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/my-prod-assistant",
    "arn:aws:bedrock:us-east-1:123456789012:foundation-model/other",
    "arn:azure:bedrock:x:application-inference-profile/claude",
    "gemini-2.5-pro",
    "Gemini-3-flash",
    "gemini-2.0-flash",
    "gemini-3",
    "gpt-5",
    "",
]
MODEL_APIS: list[str | None] = [
    None,
    "anthropic-messages",
    "google-generative-ai",
    "openai-responses",
    "bedrock-converse-stream",
    "Anthropic-Messages",
]
ROUTES: list[dict[str, Any] | None] = [
    None,
    {"baseUrl": "https://proxy.example/v1", "supportsPromptCacheKey": True},
]


def _oracle(cases: list[dict[str, Any]]) -> dict[str, Any]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=180)
    result = oracle.run({"operation": "cacheTtlEligibility", "cases": cases})
    assert result["ok"] is True
    return result["result"]


def test_eligibility_matches_oracle_over_the_provider_grid():
    grid = list(itertools.product(PROVIDERS, MODEL_IDS, MODEL_APIS, ROUTES))
    cases: list[dict[str, Any]] = []
    for provider, model_id, model_api, route in grid:
        case: dict[str, Any] = {"kind": "eligibility", "provider": provider, "modelId": model_id}
        if model_api is not None:
            case["modelApi"] = model_api
        if route is not None:
            case["route"] = route
        cases.append(case)
    expected = _oracle(cases)["eligibility"]
    assert len(expected) == len(grid) > 3000
    mismatches = [
        (args, want)
        for args, want in zip(grid, expected, strict=True)
        if is_cache_ttl_eligible_provider(*args) != want
    ]
    assert not mismatches, mismatches[:5]
    assert 0 < sum(expected) < len(expected)


def _marker(timestamp: Any, provider: str | None = None, model_id: str | None = None, **extra: Any) -> dict:
    data: dict[str, Any] = {"timestamp": timestamp, **extra}
    if provider is not None:
        data["provider"] = provider
    if model_id is not None:
        data["modelId"] = model_id
    return {"type": "custom", "customType": "openclaw.cache-ttl", "data": data}


def test_last_timestamp_reads_match_oracle():
    other = {"type": "custom", "customType": "other", "data": {"timestamp": 999}}
    entries_sets: list[list[Any]] = [
        [],
        [_marker(100, "anthropic", "claude")],
        [_marker(100, "anthropic", "claude"), _marker(200, "anthropic", "claude")],
        [_marker(300, "anthropic", "claude"), _marker(200, "openai", "gpt")],
        [_marker(100, "Anthropic", " Claude "), other],
        [_marker(0, "anthropic", "claude"), _marker(50, "anthropic", "claude")],
        [_marker(50, "anthropic", "claude"), _marker(0, "anthropic", "claude")],
        [_marker("12", "anthropic", "claude"), _marker(7, "anthropic", "claude")],
        [_marker(7, "anthropic", "claude"), _marker(None, "anthropic", "claude")],
        [_marker(7), _marker(8, "anthropic")],
        [_marker(-5, "anthropic", "claude")],
        [_marker(1.5, "anthropic", "claude")],
        [{"type": "custom", "customType": "openclaw.cache-ttl"}, _marker(4, "anthropic", "claude")],
        [{"type": "custom", "customType": "openclaw.cache-ttl", "data": "text"}],
        [{"type": "message", "customType": "openclaw.cache-ttl", "data": {"timestamp": 5}}],
        [None, 3, "x", _marker(9, "anthropic", "claude")],
    ]
    contexts: list[dict[str, Any] | None] = [
        None,
        {},
        {"provider": "anthropic"},
        {"provider": "ANTHROPIC", "modelId": "claude"},
        {"modelId": "gpt"},
        {"provider": "openai", "modelId": "gpt"},
        {"provider": "  ", "modelId": ""},
        {"provider": "nobody"},
    ]
    cases: list[dict[str, Any]] = []
    python: list[Any] = []
    for entries, context in itertools.product(entries_sets, contexts):
        case: dict[str, Any] = {"kind": "read", "entries": entries}
        if context is not None:
            case["context"] = context
        cases.append(case)
        python.append(read_last_cache_ttl_timestamp(entries, context))
    for manager in ("noEntries", "throws", "null"):
        cases.append({"kind": "read", "manager": manager, "context": {"provider": "anthropic"}})
        python.append(read_last_cache_ttl_timestamp(None if manager != "throws" else _raise))
    expected = _oracle(cases)["reads"]
    assert len(expected) == len(cases)
    assert [None if value is None else value for value in expected] == python
    assert any(value is not None for value in expected) and any(value is None for value in expected)


def _raise() -> list[Any]:
    raise RuntimeError("boom")


CACHE_TTL_CONFIG = {"agents": {"defaults": {"contextPruning": {"mode": "cache-ttl", "ttl": "5m"}}}}


def _big_messages() -> list[dict[str, Any]]:
    text = "alpha beta gamma delta\n" * 700
    messages: list[dict[str, Any]] = [{"role": "user", "content": "go"}]
    for index in range(3):
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": f"c{index}", "name": "read", "arguments": {}}],
            }
        )
        messages.append(
            {
                "role": "toolResult",
                "toolName": "read",
                "toolCallId": f"c{index}",
                "isError": False,
                "timestamp": 100 + index,
                "content": [{"type": "text", "text": text}],
            }
        )
    return messages


def _python_append(case: dict[str, Any]) -> dict[str, Any]:
    state = projection.create_tool_result_prompt_projection_state()
    if case.get("freezeMessages"):
        projection.truncate_oversized_tool_results_in_messages(
            case["freezeMessages"],
            case.get("contextWindowTokens", 2_000),
            case.get("maxChars"),
            case.get("aggregateMaxChars"),
            state,
        )
    entries: list[Any] = []
    eligible = {"always": lambda *_: True, "never": lambda *_: False}.get(
        case.get("eligible"), is_cache_ttl_eligible_provider
    )
    results = [
        append_attempt_cache_ttl_if_needed(
            append_custom_entry=None
            if case.get("noAppend")
            else lambda custom_type, data: entries.append({"customType": custom_type, "data": data}),
            timed_out_during_compaction=round_.get("timedOutDuringCompaction") is True,
            compaction_occurred_this_attempt=round_.get("compactionOccurredThisAttempt") is True,
            config=case.get("config"),
            provider=case["provider"],
            model_id=case["modelId"],
            model_api=case.get("modelApi"),
            model_route=case.get("route"),
            is_eligible=eligible,
            now=round_.get("now"),
            tool_result_prompt_projection_state=state,
        )
        for round_ in case.get("rounds", [{}])
    ]
    return {
        "results": results,
        "entries": entries,
        "lastWrittenSnapshotHash": state.last_written_snapshot_hash,
    }


def test_marker_append_matches_oracle():
    freeze = {
        "freezeMessages": _big_messages(),
        "contextWindowTokens": 2_000,
        "maxChars": 3_000,
        "aggregateMaxChars": 6_000,
    }
    base = {"provider": "anthropic", "modelId": "claude-sonnet-4-6", "config": CACHE_TTL_CONFIG}
    rounds = [{"now": 1_000}, {"now": 2_000}, {"now": 3_000, "compactionOccurredThisAttempt": True}]
    cases = [
        {**base, "rounds": [{"now": 1_000}]},
        {**base, **freeze, "rounds": rounds},
        {**base, **freeze, "rounds": [{"now": 5}, {"timedOutDuringCompaction": True, "now": 6}, {"now": 7}]},
        {**base, "provider": "openai", "modelId": "gpt-5", **freeze, "rounds": [{"now": 1}]},
        {**base, "provider": "google", "modelId": "gemini-3-pro", "modelApi": "google-generative-ai", "rounds": [{"now": 1}]},
        {**base, "provider": "custom", "modelId": "m", "modelApi": "anthropic-messages", "rounds": [{"now": 1}]},
        {**base, "config": {"agents": {"defaults": {"contextPruning": {"mode": "off"}}}}, "rounds": [{"now": 1}]},
        {**base, "config": {}, "rounds": [{"now": 1}]},
        {**base, "config": None, "rounds": [{"now": 1}]},
        {**base, **freeze, "noAppend": True, "rounds": [{"now": 1}, {"now": 2}]},
        {**base, **freeze, "eligible": "never", "rounds": [{"now": 1}]},
        {**base, "provider": "custom", "modelId": "m", "eligible": "always", **freeze, "rounds": [{"now": 1}]},
    ]
    expected = _oracle([{"kind": "append", **case} for case in cases])["appends"]
    assert len(expected) == len(cases)
    for index, (case, want) in enumerate(zip(cases, expected, strict=True)):
        assert _python_append(case) == want, f"case {index}"
    # Premises: a frozen state writes its snapshot once; an unchanged one writes a bare marker.
    assert expected[1]["entries"][0]["data"].get("prunedToolResults") is not None or any(
        "frozenToolResults" in entry["data"] for entry in expected[1]["entries"]
    )
    assert "frozenToolResults" not in expected[1]["entries"][1]["data"]
    assert expected[1]["results"] == [True, True, False]
    assert expected[3]["results"] == [False] and expected[3]["entries"] == []
