"""The pre-prompt overflow decision with compaction replay pressure against the real v2026.9.6 TS.

``shouldPreemptivelyCompactBeforePrompt`` (``preemptive-compaction.ts``) combines the local
transcript estimate, the provider-measured context usage, the tool schema tokens, the rendered
LLM boundary pressure and, when a provider checkpoint is selected, ``resolveCompactionReplayPressure``
(the checkpoint-projected window, measured Responses usage bound to the wire prefix, the
Anthropic compaction summary). The oracle runs the real function; ``memory_core.preemptive_compaction``
must return the same decision (``route``, ``shouldCompact``, token estimates, ``pressureSource``,
budgets, reducible chars, and the nested ``compactionReplay`` decision) or fail with the same error
class (``CompactionReplayRefreshRequiredError``, ``TypeError``).

Fixtures with measured Responses usage are built by the real ``recordResponsesContextUsage`` (the
``recordUsage`` function of the checkpoint op), reusing the checkpoint test's measured matrix.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import random
from pathlib import Path
from typing import Any

import pytest
from test_openclaw_compaction_checkpoint_oracle import (
    _MUTATIONS,
    IDENTS,
    MODELS,
    _anthropic_state,
    _measured_base_cases,
    _mutate,
    _run_op,
    _wire_assistant,
    _wire_user,
)

from demo.openclaw_oracle import OpenClawOracle
from memory_core import compaction_replay as cr
from memory_core import preemptive_compaction as pc

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


@pytest.fixture(scope="module")
def oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))


@pytest.fixture(scope="module")
def contexts(oracle: OpenClawOracle) -> dict[tuple[str, str], dict[str, Any]]:
    keys = list(itertools.product(MODELS, IDENTS))
    rows = _run_op(
        oracle,
        "compactionCheckpoint",
        [{"fn": "replayContext", "model": MODELS[m], "identity": IDENTS[i]} for m, i in keys],
    )
    assert all(row["error"] is None for row in rows)
    return {key: row["value"] for key, row in zip(keys, rows, strict=True)}


_DECISION_KEYS = {
    "route": "route",
    "shouldCompact": "should_compact",
    "estimatedPromptTokens": "estimated_prompt_tokens",
    "pressureSource": "pressure_source",
    "promptBudgetBeforeReserve": "prompt_budget_before_reserve",
    "overflowTokens": "overflow_tokens",
    "toolResultReducibleChars": "tool_result_reducible_chars",
    "effectiveReserveTokens": "effective_reserve_tokens",
}


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _decision_dict(decision: pc.PreemptiveCompactionDecision) -> dict[str, Any]:
    out = {key: getattr(decision, attr) for key, attr in _DECISION_KEYS.items()}
    if decision.compaction_replay is not None:
        out["compactionReplay"] = _decision_dict(decision.compaction_replay)
    return out


def _py_model(model: dict[str, Any]) -> cr.ReplayModel:
    return cr.ReplayModel(model["provider"], model["api"], model["id"], model.get("baseUrl"))


def _python_decision(case: dict[str, Any]) -> dict[str, Any]:
    messages = _clean(case["messages"])
    replay = case.get("replay")
    boundary = case.get("llmBoundaryTokenPressure")
    try:
        value = pc.should_preemptively_compact_before_prompt(
            messages=messages,
            unwindowed_messages=(
                messages
                if case.get("unwindowedSame")
                else _clean(case["unwindowedMessages"])
                if case.get("unwindowedMessages") is not None
                else None
            ),
            system_prompt=case.get("systemPrompt"),
            prompt=case.get("prompt", ""),
            context_token_budget=case["contextWindowTokens"],
            reserve_tokens=case["reserveTokens"],
            tool_result_max_chars=case.get("toolResultMaxChars"),
            tool_schema_tokens=case.get("toolSchemaTokens"),
            llm_boundary_token_pressure=(
                pc.LlmBoundaryTokenPressure(
                    boundary["estimatedPromptTokens"],
                    boundary["source"],
                    boundary.get("renderedChars"),
                )
                if boundary
                else None
            ),
            replay=(
                pc.CompactionReplayPressureContext(
                    _py_model(replay["model"]),
                    replay.get("sessionId"),
                    replay.get("authProfileId"),
                    replay.get("enabled"),
                )
                if replay
                else None
            ),
        )
        return {"value": _decision_dict(value), "error": None}
    except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
        return {"value": None, "error": type(exc).__name__}


def _first_diffs(cases: list[Any], rows: list[Any], python_rows: list[Any]) -> list[Any]:
    assert len(rows) == len(python_rows) == len(cases)
    return [
        (case, row, python)
        for case, row, python in zip(cases, rows, python_rows, strict=True)
        if _clean(row) != _clean(python)
    ][:3]


_BUDGETS = [(400, 0), (500, 200), (2_000, 100), (10_000, 600), (40_000, 5_000), (200_000, 60_000)]
_SYSTEM_PROMPTS = [None, "", "You are helpful.", "sys " * 400, "é\U0001f600 日本"]
_PROMPTS = ["", "hello", "question " * 300, "é\U0001f600 日本語"]


def _knobs(rng: random.Random) -> dict[str, Any]:
    budget, reserve = rng.choice(_BUDGETS)
    knobs: dict[str, Any] = {
        "contextWindowTokens": budget,
        "reserveTokens": reserve,
        "systemPrompt": rng.choice(_SYSTEM_PROMPTS),
        "prompt": rng.choice(_PROMPTS),
    }
    if rng.random() < 0.5:
        knobs["toolSchemaTokens"] = rng.choice([0, 7, 700, 5_000, -3])
    if rng.random() < 0.3:
        knobs["toolResultMaxChars"] = rng.choice([20, 500, 5_000])
    if rng.random() < 0.2:
        knobs["llmBoundaryTokenPressure"] = rng.choice(
            [
                {"estimatedPromptTokens": 123, "source": "rendered"},
                {"estimatedPromptTokens": 9_999.5, "source": "  padded  ", "renderedChars": 41.2},
                {"estimatedPromptTokens": 50_000, "source": "   "},
                {"estimatedPromptTokens": -5, "source": "neg"},
                {"estimatedPromptTokens": 0, "source": "zero", "renderedChars": -4},
            ]
        )
    return knobs


def _user(text: str) -> dict[str, Any]:
    return _wire_user(text)


def _usage(total: int | None, state: str = "available", **extra: Any) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "input": 10,
        "output": 5,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 15,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
    }
    if total is not None:
        usage["contextUsage"] = {"state": state, "promptTokens": total - 5, "totalTokens": total}
    usage.update(extra)
    return usage


def _plain_history(rng: random.Random) -> list[dict[str, Any]]:
    """Histories without checkpoints: measured usage, barriers, tool results, excluded messages."""

    messages: list[dict[str, Any]] = []
    big = "alpha beta gamma delta epsilon " * rng.choice([1, 20, 200])
    for _ in range(rng.randrange(1, 9)):
        roll = rng.random()
        if roll < 0.25:
            messages.append(_user(rng.choice(["hi", big, "é\U0001f600 日本語"])))
        elif roll < 0.55:
            message = {
                "role": "assistant",
                "content": rng.choice(
                    [
                        [{"type": "text", "text": big}],
                        [{"type": "thinking", "thinking": "t"}],
                        "str",
                    ]
                ),
                "api": rng.choice(["openai-responses", "cli", "anthropic-messages"]),
                "provider": "p",
                "model": "m",
                "stopReason": "stop",
                "timestamp": 1,
            }
            kind = rng.random()
            if kind < 0.4:
                message["usage"] = _usage(rng.choice([800, 5_000, 70_000, 1.5]))
            elif kind < 0.55:
                message["usage"] = _usage(rng.choice([0, 4]), "unavailable")
            elif kind < 0.65:
                message["usage"] = _usage(None)
            elif kind < 0.72:
                message["usage"] = _usage(0, "unavailable", totalTokens=0, input=0, output=0)
            elif kind < 0.78:
                message["usage"] = {"input": 1, "output": 2}
            elif kind < 0.82:
                message["usage"] = _usage(rng.choice([2**40, -5]))
            messages.append(message)
        elif roll < 0.8:
            messages.append(
                {
                    "role": "toolResult",
                    "toolCallId": "c1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": big * rng.choice([1, 3])}],
                    "isError": False,
                    "timestamp": 1,
                }
            )
        elif roll < 0.88:
            messages.append(
                {
                    "role": "bashExecution",
                    "command": "ls",
                    "output": big,
                    "timestamp": 1,
                    **({"excludeFromContext": True} if rng.random() < 0.5 else {}),
                }
            )
        elif roll < 0.94:
            messages.append(
                rng.choice(
                    [
                        {"role": "compactionSummary", "summary": big, "timestamp": 1},
                        {"role": "branchSummary", "summary": "s", "timestamp": 1},
                        {"role": "compactionSummary", "timestamp": 1},
                        {"role": "user", "content": big, "excludeFromContext": True},
                    ]
                )
            )
        else:
            messages.append({"role": "custom", "content": big})
    return messages


def _plain_cases(count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        case = {"fn": "decide", "messages": _plain_history(rng), **_knobs(rng)}
        roll = rng.random()
        if roll < 0.25:
            case["unwindowedMessages"] = _plain_history(rng)
        elif roll < 0.3:
            case["unwindowedSame"] = True
        cases.append(case)
    return cases


def test_real_openclaw_oracle_preemptive_decision_without_replay_matches_python(oracle):
    cases = _plain_cases(2500, 8)
    rows = _run_op(oracle, "preemptiveCompaction", cases)
    python_rows = [_python_decision(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    values = [row["value"] for row in rows if row["error"] is None]
    assert {v["pressureSource"] for v in values} >= {
        "transcript_estimate",
        "provider_context_usage",
        "unwindowed_transcript_estimate",
        "unwindowed_provider_context_usage",
    }
    assert {v["route"] for v in values} == {
        "fits",
        "compact_only",
        "compact_then_truncate",
        "truncate_tool_results_only",
    }


def test_real_openclaw_oracle_estimate_helpers_match_python(oracle):
    rng = random.Random(14)
    tools = [
        [],
        [{"name": "read", "description": "Read a file", "parameters": {"type": "object"}}],
        [
            {
                "name": "a",
                "description": "é\U0001f600",
                "parameters": {"p": {"q": [1, 2]}},
                "extra": 1,
            },
            {"name": "b", "description": "d"},
        ],
        [{"name": "x" * 500, "description": "d" * 3000, "parameters": {"k": "v" * 2000}}],
    ]
    cases: list[dict[str, Any]] = [{"fn": "toolSchema", "tools": value} for value in tools]
    for _ in range(300):
        messages = _plain_history(rng)
        base = {
            "messages": messages,
            "systemPrompt": rng.choice(_SYSTEM_PROMPTS),
            "prompt": rng.choice(_PROMPTS),
        }
        cases.append({"fn": "renderedBoundary", **base})
        schema = rng.choice([None, 0, 33, 900])
        cases.append(
            {
                "fn": "boundaryEstimate",
                **base,
                **({} if schema is None else {"toolSchemaTokens": schema}),
            }
        )
    rows = _run_op(oracle, "preemptiveCompaction", cases)
    python_rows = []
    for case in cases:
        if case["fn"] == "toolSchema":
            value = pc.estimate_tool_schema_token_pressure(case["tools"])
        elif case["fn"] == "renderedBoundary":
            value = pc.estimate_rendered_llm_boundary_token_pressure(
                system_prompt=case["systemPrompt"], prompt=case["prompt"]
            )
        else:
            value = pc.estimate_llm_boundary_token_pressure(
                messages=_clean(case["messages"]),
                system_prompt=case["systemPrompt"],
                prompt=case["prompt"],
                tool_schema_tokens=case.get("toolSchemaTokens"),
            )
        python_rows.append({"value": value, "error": None})
    assert _first_diffs(cases, rows, python_rows) == []


# --- provider checkpoints -----------------------------------------------------------------------


def _replay_context(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    identity = {k: v for k, v in spec["identity"].items() if k in ("sessionId", "authProfileId")}
    replay: dict[str, Any] = {"model": spec["model"], **identity}
    roll = rng.random()
    if roll < 0.5:
        replay["enabled"] = rng.choice([True, None])
    elif roll < 0.6:
        replay["enabled"] = False
    elif roll < 0.7:
        replay["sessionId"] = "other-session"
    return replay


def test_real_openclaw_oracle_preemptive_decision_with_measured_replay_matches_python(
    oracle, contexts
):
    specs = _measured_base_cases(contexts)
    recorded = _run_op(
        oracle,
        "compactionCheckpoint",
        [{"fn": "recordUsage", **{k: v for k, v in spec.items() if k != "name"}} for spec in specs],
    )
    rng = random.Random(311)
    cases: list[dict[str, Any]] = []
    for spec, row in zip(specs, recorded, strict=True):
        assert row["error"] is None, (spec["name"], row)
        for mutation in dict.fromkeys(["none", *rng.sample(_MUTATIONS, 2)]):
            messages = _mutate(row["value"], mutation, 3)
            for _ in range(2):
                knobs = _knobs(rng)
                if rng.random() < 0.8:
                    knobs["systemPrompt"] = spec["systemPrompt"]
                case = {
                    "fn": "decide",
                    "messages": messages,
                    "replay": _replay_context(spec, rng),
                    "mutation": mutation,
                    **knobs,
                }
                if rng.random() < 0.25:
                    case["unwindowedMessages"] = copy.deepcopy(messages) + [
                        _user("later " * rng.choice([10, 500]))
                    ]
                cases.append(case)
    assert len(cases) >= 3000
    oracle_cases = [{k: v for k, v in c.items() if k != "mutation"} for c in cases]
    rows = _run_op(oracle, "preemptiveCompaction", oracle_cases)
    python_rows = [_python_decision(case) for case in oracle_cases]
    assert _first_diffs(oracle_cases, rows, python_rows) == []
    values = [row["value"] for row in rows if row["error"] is None]
    nested = [v for v in values if "compactionReplay" in v]
    assert len(nested) > 1000
    assert {v["compactionReplay"]["pressureSource"] for v in nested} >= {
        "provider_context_usage",
        "provider_compaction_estimate",
    }
    assert len(values) > 0.6 * len(rows)
    assert {row["error"] for row in rows} >= {None, "TypeError"}
    assert len({v["estimatedPromptTokens"] for v in values}) > 300


def _anthropic_history(rng: random.Random, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    model = MODELS["anthropic"]
    summary = rng.choice(["sum", "é\U0001f600 " * 40, "long summary " * 400])
    replay = _anthropic_state(ctx, data=summary, replayIndex=rng.choice([0, 1, 2]))
    blocks = [
        {"type": "text", "text": "A"},
        {"type": "text", "text": "B"},
        {"type": "text", "text": "C"},
    ]
    owner = _wire_assistant(model, blocks, replay)
    messages = [_user("one"), owner, _user("two")]
    if rng.random() < 0.5:
        later = _wire_assistant(model, [{"type": "text", "text": "later"}])
        later["usage"]["contextUsage"] = {
            "state": "available",
            "promptTokens": 5,
            "totalTokens": 900,
        }
        messages.append(later)
    if rng.random() < 0.5:
        messages.append(_user("tail " * rng.choice([5, 300])))
    return messages


def test_real_openclaw_oracle_preemptive_decision_with_anthropic_checkpoint_matches_python(
    oracle, contexts
):
    rng = random.Random(901)
    cases = []
    for ident_key in ("none", "both"):
        ctx = contexts[("anthropic", ident_key)]
        for _ in range(250):
            identity = {k: v for k, v in IDENTS[ident_key].items()}
            replay = {
                "model": MODELS["anthropic"],
                **identity,
                "enabled": rng.choice([True, True, None, False]),
            }
            cases.append(
                {
                    "fn": "decide",
                    "messages": _anthropic_history(rng, ctx),
                    "replay": replay,
                    **_knobs(rng),
                }
            )
    rows = _run_op(oracle, "preemptiveCompaction", cases)
    python_rows = [_python_decision(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    values = [row["value"] for row in rows if row["error"] is None]
    assert sum(1 for v in values if "compactionReplay" in v) > 150
    assert sum(1 for v in values if "compactionReplay" not in v) > 100


def test_real_openclaw_oracle_precheck_log_and_budget_status_match_python(oracle):
    rng = random.Random(21)
    cases: list[dict[str, Any]] = []
    for _ in range(400):
        decide = {"fn": "decide", "messages": _plain_history(rng), **_knobs(rng)}
        decide.pop("llmBoundaryTokenPressure", None)
        cases.append(decide)
    decisions = _run_op(oracle, "preemptiveCompaction", cases)
    params_cases: list[dict[str, Any]] = []
    for case, row in zip(cases, decisions, strict=True):
        assert row["error"] is None
        params: dict[str, Any] = {
            "result": row["value"],
            "provider": rng.choice(["openai", "é\U0001f600", ""]),
            "modelId": rng.choice(["gpt-x", "claude/y"]),
            "messageCount": rng.choice([0, 3, 7.9, -2]),
            "contextTokenBudget": case["contextWindowTokens"] + rng.choice([0, 0.7]),
            "reserveTokens": case["reserveTokens"] + rng.choice([0, 0.4, -1]),
            "now": 1_700_000_000_000,
        }
        for key, values in (
            ("sessionKey", ["", "main", "agent:x"]),
            ("sessionId", ["", "sid"]),
            ("unwindowedMessageCount", [0, 5, 9.5]),
            ("sessionFile", ["/tmp/s.jsonl"]),
        ):
            if rng.random() < 0.5:
                params[key] = rng.choice(values)
        params_cases.append(params)
    oracle_cases: list[dict[str, Any]] = [{"fn": "overflowText"}]
    for params in params_cases:
        oracle_cases.append({"fn": "precheckLog", "params": params})
        oracle_cases.append({"fn": "budgetStatus", "params": params})
    rows = _run_op(oracle, "preemptiveCompaction", oracle_cases)
    assert rows[0]["value"] == pc.PREEMPTIVE_OVERFLOW_ERROR_TEXT
    for index, params in enumerate(params_cases):
        result = pc.PreemptiveCompactionDecision(
            **{attr: params["result"][key] for key, attr in _DECISION_KEYS.items()}
        )
        common = {
            "result": result,
            "provider": params["provider"],
            "model_id": params["modelId"],
            "message_count": params["messageCount"],
            "context_token_budget": params["contextTokenBudget"],
            "reserve_tokens": params["reserveTokens"],
            "session_id": params.get("sessionId"),
            "unwindowed_message_count": params.get("unwindowedMessageCount"),
        }
        log = pc.format_pre_prompt_precheck_log(
            **common, session_key=params.get("sessionKey"), session_file=params.get("sessionFile")
        )
        status = pc.build_pre_prompt_context_budget_status(**common, now=params["now"])
        assert rows[1 + 2 * index]["value"] == log
        assert _clean(rows[2 + 2 * index]["value"]) == _clean(status)
