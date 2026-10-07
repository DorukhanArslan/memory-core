"""The upstream callers of the compaction replay decision against the real v2026.9.6 TS.

``replayCallers`` (``scripts/openclaw_oracle_runner.ts``) runs, on the tag's own modules:

* ``prepareEmbeddedAttemptPromptPreflight`` and ``handleEmbeddedAttemptMidTurnPrecheck``
  (``run/attempt-prompt-preflight.ts``), the latter on a real in-memory ``SessionManager`` with the
  real ``truncateOversizedToolResultsInSessionManager``;
* ``installToolResultContextGuard`` (``tool-result-context-guard.ts``) on a fake agent, called the
  way the tool loop calls ``transformContext`` (a growing message list per iteration);
* the eligibility wiring of ``attempt-stream-settle.ts`` (``resolveCompactionReplayEligibility``
  feeding the preflight) and of ``compaction-session-execution.ts`` (eligibility,
  ``preserveCompactionReplayWindow`` and ``estimateLlmBoundaryTokenPressure`` sharing one identity;
  the surrounding 700-line compaction function is not reachable, so that wiring is replayed on the
  real callees).

``memory_core.attempt_preflight`` and ``memory_core.tool_result_context_guard`` must return the same
combined output on every scenario: the preflight state (budget record, recovery route and budget
snapshot, prompt error and its class, skip flag), the log lines, the guard's messages (the same
object when nothing was capped) or signal request, the handler's route, truncation count and the
messages it hands to the session. The two host inputs the Python port takes as callables are fed by
the real functions: ``normalizeMessagesForLlmBoundary`` (its output for the same input) and the
persisted truncation (``truncate_oversized_tool_results_in_session_file`` on the same transcript).
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
    ELIGIBILITY_ENVS,
    ELIGIBILITY_KEYS,
    ELIGIBILITY_PARAMS,
    IDENTS,
    MODELS,
    _measured_base_cases,
    _mutate,
    _run_op,
    _responses_state,
    _retained_state,
    _wire_assistant,
    _wire_user,
)
from test_openclaw_preemptive_replay_oracle import (
    _anthropic_history,
    _knobs,
    _plain_history,
)

from demo.openclaw_oracle import OpenClawOracle
from memory_core import attempt_preflight as pf
from memory_core import compaction_replay as cr
from memory_core import tool_result_context_guard as guard
from memory_core.preemptive_compaction import (
    CompactionReplayPressureContext,
    _active_branch,
    _read_jsonl_entries,
    truncate_oversized_tool_results_in_session_file,
)
from memory_core.tool_result_projection import create_tool_result_prompt_projection_state

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

FIXED_NOW = 1_700_000_000_000
CASES_OP = "replayCallers"


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


@pytest.fixture(scope="module")
def measured(oracle: OpenClawOracle, contexts: dict[tuple[str, str], dict[str, Any]]) -> list[Any]:
    """Histories with Responses usage recorded by the real ``recordResponsesContextUsage``."""

    specs = _measured_base_cases(contexts)
    rows = _run_op(
        oracle,
        "compactionCheckpoint",
        [{"fn": "recordUsage", **{k: v for k, v in spec.items() if k != "name"}} for spec in specs],
    )
    out = []
    for spec, row in zip(specs, rows, strict=True):
        assert row["error"] is None, (spec["name"], row)
        out.append((spec, row["value"]))
    return out


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _diffs(cases: list[Any], rows: list[Any], python_rows: list[Any]) -> list[Any]:
    assert len(rows) == len(python_rows) == len(cases)
    return [
        (case, row, python)
        for case, row, python in zip(cases, rows, python_rows, strict=True)
        if _clean(row) != _clean(python)
    ][:3]


def _py_model(model: dict[str, Any]) -> cr.ReplayModel:
    return cr.ReplayModel(model["provider"], model["api"], model["id"], model.get("baseUrl"))


def _error_name(exc: BaseException) -> str:
    return "Error" if type(exc) is Exception else type(exc).__name__


# --- tool-result messages -----------------------------------------------------------------------

_TEXTS = [
    "alpha beta gamma delta epsilon\n" * 400,
    "x" * 6000,
    "日本語のテキスト。" * 500,
    "é\U0001f600 mixed " * 300,
    "head " * 200 + "\n" + "middle " * 2000 + "\nError: failed\n" + "Traceback (most recent call last)\n" * 5,
    "short",
    "",
    "line\n" * 5000,
]


def _image(rng: random.Random) -> dict[str, Any]:
    return {"type": "image", "data": "A" * rng.choice([4, 400]), "mimeType": "image/png"}


def _tool_result(rng: random.Random, *, valid: bool = False) -> dict[str, Any]:
    """``valid`` keeps every block an object and every message a role, as a session accepts."""

    kind = rng.random()
    message: dict[str, Any] = {
        "role": "toolResult",
        "toolCallId": f"c{rng.randrange(9)}",
        "toolName": rng.choice(["read", "exec", "web_fetch"]),
        "isError": rng.random() < 0.1,
        "timestamp": 1,
    }
    if kind < 0.4:
        message["content"] = [{"type": "text", "text": rng.choice(_TEXTS)}]
    elif kind < 0.55:
        message["content"] = rng.choice(_TEXTS)
    elif kind < 0.8:
        blocks: list[Any] = []
        for _ in range(rng.randrange(1, 6)):
            roll = rng.random()
            if roll < 0.45:
                blocks.append({"type": "text", "text": rng.choice(_TEXTS)})
            elif roll < 0.85:
                blocks.append(_image(rng))
            else:
                blocks.append(
                    rng.choice(
                        [{"type": "json", "value": {"a": [1, 2]}}, {"k": "v" * 900}]
                        + ([] if valid else [None])
                    )
                )
        message["content"] = blocks
    elif kind < 0.9:
        message["content"] = [_image(rng) for _ in range(rng.randrange(1, 8))]
    else:
        message["content"] = [{"type": "text", "text": rng.choice(_TEXTS)}]
        message["role"] = rng.choice(["tool", "toolResult"])
    if rng.random() < 0.3:
        message["details"] = {"spill": "x" * 50}
    if rng.random() < 0.08 and not valid:
        message.pop("role")
        message["type"] = "toolResult"
    if valid:
        message["role"] = "toolResult"
        message.pop("type", None)
        if isinstance(message["content"], str):
            message["content"] = [{"type": "text", "text": message["content"]}]
    return message


def _assistant_with_call(rng: random.Random) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "é" * rng.choice([1, 40])}},
        ],
        "api": "openai-responses",
        "provider": "p",
        "model": "m",
        "stopReason": "toolUse",
        "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2},
        "timestamp": 1,
    }


# --- the mid-turn guard -------------------------------------------------------------------------

_GUARD_MODELS = ("responses", "azure", "anthropic", "completions")


def _guard_cases(measured: list[Any], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    for index in range(count):
        window = rng.choice([200, 1_000, 1_500, 4_000, 12_000, 60_000, 250_000])
        base: list[dict[str, Any]]
        replay: dict[str, Any] | None = None
        if index % 6 == 0 and measured:
            spec, history = rng.choice(measured)
            base = copy.deepcopy(history)
            replay = {
                "model": spec["model"],
                **{k: v for k, v in spec["identity"].items() if k in ("sessionId", "authProfileId")},
                **({"enabled": rng.choice([True, None, False])} if rng.random() < 0.5 else {}),
            }
            if replay.get("enabled") is None:
                replay.pop("enabled", None)
        else:
            base = [_wire_user("start"), _assistant_with_call(rng)]
            if rng.random() < 0.4:
                base = [*_plain_history(rng)[:3], *base]
            if rng.random() < 0.5:
                key = rng.choice(_GUARD_MODELS)
                replay = {"model": MODELS[key], "sessionId": "s1", "authProfileId": "a1"}
                if rng.random() < 0.5:
                    replay["enabled"] = rng.choice([True, False])
        steps = []
        current = base
        for _ in range(rng.randrange(1, 5)):
            steps.append(copy.deepcopy(current))
            current = [*current, *(_tool_result(rng) for _ in range(rng.randrange(0, 3)))]
            if rng.random() < 0.3:
                current.append(_assistant_with_call(rng))
        case: dict[str, Any] = {"fn": "guard", "contextWindowTokens": window, "steps": steps}
        if index % 9 == 1:
            # Heavy tool results under a tiny precheck budget: reducible chars dwarf the overflow.
            heavy = [
                {**_tool_result(rng), "content": [{"type": "text", "text": "data " * rng.choice([4_000, 20_000])}]}
                for _ in range(rng.randrange(2, 8))
            ]
            case["contextWindowTokens"] = 250_000
            case["steps"] = [steps[0], [*steps[0], *heavy]]
            case["midTurnPrecheck"] = {
                "enabled": True,
                "contextTokenBudget": rng.choice([3_000, 8_000, 20_000]),
                "reserveTokens": 0,
                "systemPrompt": None,
                "toolResultMaxChars": rng.choice([100, 500, 2_000]),
                "prePromptMessageCount": len(steps[0]),
            }
            cases.append(case)
            continue
        roll = rng.random()
        if roll < 0.85:
            budget, reserve = rng.choice([(400, 0), (1_000, 200), (4_000, 100), (12_000, 3_000), (60_000, 8_000)])
            options: dict[str, Any] = {
                "enabled": rng.random() < 0.9,
                "contextTokenBudget": budget,
                "reserveTokens": reserve,
                "systemPrompt": rng.choice([None, "", "sys " * 100]),
            }
            if rng.random() < 0.3:
                options["toolResultMaxChars"] = rng.choice([20, 500, 5_000])
            if rng.random() < 0.5:
                options["prePromptMessageCount"] = rng.choice([0, 1, 2, len(base), len(base) + 3, -2, 1.5, 99])
            if replay is not None:
                options["replay"] = replay
            case["midTurnPrecheck"] = options
        cases.append(case)
    return cases


def _py_guard(case: dict[str, Any]) -> dict[str, Any]:
    options = case.get("midTurnPrecheck")
    requests: list[Any] = []
    pre_options = None
    if options is not None:
        replay = options.get("replay")
        pre_options = guard.MidTurnPrecheckOptions(
            enabled=options["enabled"],
            context_token_budget=options["contextTokenBudget"],
            reserve_tokens=lambda: options["reserveTokens"],
            tool_result_max_chars=options.get("toolResultMaxChars"),
            get_system_prompt=lambda: options["systemPrompt"],
            get_pre_prompt_message_count=(
                (lambda: options["prePromptMessageCount"])
                if "prePromptMessageCount" in options
                else None
            ),
            get_replay=(
                (
                    lambda: CompactionReplayPressureContext(
                        _py_model(replay["model"]),
                        replay.get("sessionId"),
                        replay.get("authProfileId"),
                        replay.get("enabled"),
                    )
                )
                if replay
                else None
            ),
            on_mid_turn_precheck=lambda request: requests.append(request.to_dict()),
        )
    instance = guard.ToolResultContextGuard(
        context_window_tokens=case["contextWindowTokens"], mid_turn_precheck=pre_options
    )
    steps: list[Any] = []
    for messages in case["steps"]:
        given = copy.deepcopy(messages)
        try:
            out = instance.transform_context(given)
            steps.append({"kind": "messages", "messages": _clean(out), "same": out is given})
        except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
            request = getattr(exc, "request", None)
            steps.append(
                {
                    "kind": "error",
                    "name": _error_name(exc),
                    "message": str(exc),
                    "request": request.to_dict() if request is not None else None,
                }
            )
    return {"steps": steps, "requests": requests}


def _without_engine_messages(row: dict[str, Any]) -> dict[str, Any]:
    """A TypeError of a malformed message carries V8's wording; only its class is compared."""

    value = _clean(row["value"])
    for step in value["steps"]:
        if step["kind"] == "error" and step["name"] != "MidTurnPrecheckSignal":
            step.pop("message")
    return {**row, "value": value}


def test_real_openclaw_mid_turn_guard_matches_python(oracle, measured):
    cases = _guard_cases(measured, 1500, 41)
    rows = _run_op(oracle, CASES_OP, cases)
    python_rows = [{"value": _py_guard(case), "error": None} for case in cases]
    assert _diffs(
        cases,
        [_without_engine_messages(row) for row in rows],
        [_without_engine_messages(row) for row in python_rows],
    ) == []
    assert sum(1 for row in rows for s in row["value"]["steps"] if s["kind"] == "error" and s["name"] == "TypeError") > 10
    steps = [step for row in rows for step in row["value"]["steps"]]
    assert sum(1 for s in steps if s["kind"] == "error" and s["name"] == "MidTurnPrecheckSignal") > 100
    assert {s["request"]["route"] for s in steps if s["kind"] == "error" and s["request"]} == {
        "compact_only",
        "compact_then_truncate",
        "truncate_tool_results_only",
    }
    assert sum(1 for s in steps if s["kind"] == "messages" and s["same"]) > 200
    assert sum(1 for s in steps if s["kind"] == "messages" and not s["same"]) > 200
    assert {s["name"] for s in steps if s["kind"] == "error"} >= {"MidTurnPrecheckSignal"}


# --- estimator and limits -----------------------------------------------------------------------


def _any_message(rng: random.Random) -> dict[str, Any]:
    roll = rng.random()
    if roll < 0.35:
        return _tool_result(rng)
    if roll < 0.5:
        return {"role": "user", "content": rng.choice([rng.choice(_TEXTS), [{"type": "text", "text": "hi"}, _image(rng), {"k": 1}], 5, None])}
    if roll < 0.65:
        message = _assistant_with_call(rng)
        message["content"] = rng.choice(
            [
                message["content"],
                [{"type": "thinking", "thinking": "hmm é"}, {"type": "toolCall", "arguments": None}, 7, None, {"x": 1}, [1, 2]],
                "string content",
                [{"type": "toolCall", "name": "n"}],
            ]
        )
        return message
    if roll < 0.75:
        return {"role": "bashExecution", "command": "ls", "output": rng.choice(["", "out " * 40]), "exitCode": rng.choice([0, 1, None]), "cancelled": rng.random() < 0.2, "truncated": True, "fullOutputPath": "/tmp/x", "timestamp": 1}
    if roll < 0.85:
        return rng.choice(
            [
                {"role": "branchSummary", "summary": "s" * 30, "timestamp": 1},
                {"role": "compactionSummary", "summary": 5, "timestamp": 1},
                {"role": "compactionSummary", "timestamp": 1},
            ]
        )
    if roll < 0.93:
        return {"role": "custom", "content": rng.choice(["c" * 20, [{"type": "text", "text": "t"}], 3]), "customType": "x"}
    return rng.choice([{"role": "weird"}, {"role": "user", "content": "gone", "excludeFromContext": True}, {}])


def test_real_openclaw_char_estimate_and_limits_match_python(oracle):
    rng = random.Random(5)
    messages = [_any_message(rng) for _ in range(2500)]
    cases: list[dict[str, Any]] = [
        {"fn": "charEstimate", "messages": messages[i : i + 250]} for i in range(0, len(messages), 250)
    ]
    windows = [-5, 0, 1, 7, 500, 1023, 1024, 4000, 99_999, 100_000, 200_000, 1_000_000, 12_345.6]
    cases += [{"fn": "limits", "contextWindowTokens": w, "truncatedChars": c} for w in windows for c in (0, 1, 12.7, 5000)]
    rows = _run_op(oracle, CASES_OP, cases)
    assert all(row["error"] is None for row in rows)
    for case, row in zip(cases, rows, strict=True):
        if case["fn"] == "charEstimate":
            assert row["value"] == [guard.estimate_message_chars(m) for m in case["messages"]]
        else:
            assert row["value"] == {
                "contextMaxChars": guard.resolve_tool_result_context_max_chars(case["contextWindowTokens"]),
                "notice": guard.format_context_limit_truncation_notice(case["truncatedChars"]),
            }
    assert len({v for row in rows[:10] for v in row["value"]}) > 40


# --- the mid-turn handler -----------------------------------------------------------------------


def _handler_cases(count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        conversation: list[dict[str, Any]] = [_wire_user("go")]
        for _ in range(rng.randrange(0, 5)):
            conversation.append(_assistant_with_call(rng))
            conversation.append(_tool_result(rng, valid=True))
        if rng.random() < 0.5:
            conversation.append({"role": "assistant", "content": [{"type": "text", "text": "done"}], "api": "openai-responses", "provider": "p", "model": "m", "stopReason": "stop", "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}, "timestamp": 1})
        attempt: dict[str, Any] = {"provider": "openai", "modelId": "gpt-x"}
        if rng.random() < 0.8:
            attempt["sessionId"] = "s1"
        if rng.random() < 0.6:
            attempt["sessionKey"] = rng.choice(["main", "", "agent:x"])
        if rng.random() < 0.7:
            attempt["sessionFile"] = "/tmp/s.jsonl"
        if rng.random() < 0.85:
            attempt["contextTokenBudget"] = rng.choice([600, 2_000, 8_000, 50_000, 120_000, 200_000, 500_000])
        cases.append(
            {
                "fn": "midTurn",
                "attempt": attempt,
                "request": {
                    "route": rng.choice(["truncate_tool_results_only", "truncate_tool_results_only", "compact_only", "compact_then_truncate"]),
                    "estimatedPromptTokens": rng.choice([1_000, 90_000, 123_456]),
                    "promptBudgetBeforeReserve": rng.choice([800, 50_000]),
                    "overflowTokens": rng.choice([1, 400, 70_000]),
                    "toolResultReducibleChars": rng.choice([0, 5_000, 90_000]),
                    "effectiveReserveTokens": rng.choice([0, 20_000]),
                },
                "prePromptMessageCount": rng.choice([0, 2, 5]),
                "sessionMessages": conversation,
            }
        )
    return cases


def _py_handler(case: dict[str, Any], tmp_path: Path, index: int) -> dict[str, Any]:
    attempt = case["attempt"]
    path = tmp_path / f"session-{index}.jsonl"
    entries = []
    parent = None
    for position, message in enumerate(case["sessionMessages"]):
        entries.append(
            {
                "type": "message",
                "id": f"e{position}",
                "parentId": parent,
                "timestamp": "2026-05-30T00:00:00.000Z",
                "message": message,
            }
        )
        parent = f"e{position}"
    path.write_text("".join(f"{json.dumps(entry)}\n" for entry in entries), encoding="utf-8")
    state = create_tool_result_prompt_projection_state()
    logs: list[Any] = []
    replaced: list[Any] = []

    def branch_messages() -> list[Any]:
        branch = _active_branch(_read_jsonl_entries(path))
        return [entry["message"] for entry in branch if entry.get("type") == "message"]

    outcome = pf.handle_attempt_mid_turn_precheck(
        attempt=pf.AttemptPromptPreflightAttempt(
            provider=attempt["provider"],
            model_id=attempt["modelId"],
            model=_py_model(MODELS["responses"]),
            session_id=attempt.get("sessionId"),
            session_key=attempt.get("sessionKey"),
            session_file=attempt.get("sessionFile"),
            context_token_budget=attempt.get("contextTokenBudget"),
        ),
        request=guard.MidTurnPrecheckRequest(
            route=case["request"]["route"],
            estimated_prompt_tokens=case["request"]["estimatedPromptTokens"],
            prompt_budget_before_reserve=case["request"]["promptBudgetBeforeReserve"],
            overflow_tokens=case["request"]["overflowTokens"],
            tool_result_reducible_chars=case["request"]["toolResultReducibleChars"],
            effective_reserve_tokens=case["request"]["effectiveReserveTokens"],
        ),
        pre_prompt_message_count=case["prePromptMessageCount"],
        truncate_tool_results=lambda window, max_chars: truncate_oversized_tool_results_in_session_file(
            path,
            context_window_tokens=window,
            max_chars_override=max_chars,
            projection_state=state,
        ),
        build_session_context_messages=branch_messages,
        replace_session_messages=lambda messages: replaced.append(_clean(messages)),
        log=lambda level, message: logs.append([level, message]),
    )
    return {
        "preflightRecovery": outcome.preflight_recovery.to_dict(),
        "promptError": (
            None
            if outcome.prompt_error is None
            else {"name": _error_name(outcome.prompt_error), "message": str(outcome.prompt_error)}
        ),
        "replaced": replaced,
        "branchMessages": _clean(branch_messages()),
        "logs": logs,
    }


def _own_logs(row: dict[str, Any]) -> dict[str, Any]:
    """The handler's lines only: the truncation underneath logs through the same logger."""

    value = _clean(row["value"])
    value["logs"] = [log for log in value["logs"] if "[context-overflow-midturn-precheck]" in log[1]]
    return {**row, "value": value}


def test_real_openclaw_mid_turn_handler_matches_python(oracle, tmp_path):
    cases = _handler_cases(450, 17)
    rows = _run_op(oracle, CASES_OP, cases)
    python_rows = [
        {"value": _py_handler(case, tmp_path, index), "error": None}
        for index, case in enumerate(cases)
    ]
    assert _diffs(cases, [_own_logs(r) for r in rows], [_own_logs(r) for r in python_rows]) == []
    values = [row["value"] for row in rows if row["error"] is None]
    assert len(values) == len(rows)
    recoveries = [v["preflightRecovery"] for v in values]
    assert {r["route"] for r in recoveries} == {
        "truncate_tool_results_only",
        "compact_only",
        "compact_then_truncate",
    }
    assert sum(1 for r in recoveries if r.get("handled") and r["truncatedCount"] > 0) > 30
    assert sum(1 for r in recoveries if r.get("handled") and r["truncatedCount"] == 0) > 30
    assert sum(1 for v in values if v["replaced"]) > 30
    assert sum(1 for v in values if v["promptError"]) > 100


# --- the preflight ------------------------------------------------------------------------------


def _eligibility(rng: random.Random, model: dict[str, Any]) -> dict[str, Any]:
    if rng.random() < 0.5:
        return {
            "extraParams": {"anthropicServerCompaction": True},
            "apiKey": "sk-ant-api03-abc",
            **({"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}} if rng.random() < 0.3 else {}),
        }
    out: dict[str, Any] = {}
    params = rng.choice(ELIGIBILITY_PARAMS)
    key = rng.choice(ELIGIBILITY_KEYS)
    env = rng.choice(ELIGIBILITY_ENVS)
    if params is not None:
        out["extraParams"] = params
    if key is not None:
        out["apiKey"] = key
    if env is not None:
        out["env"] = env
    del model
    return out


def _preflight_attempt(rng: random.Random, model: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    attempt: dict[str, Any] = {"provider": model["provider"], "modelId": model["id"], "model": model}
    if identity.get("sessionId") is not None:
        attempt["sessionId"] = identity["sessionId"]
    elif rng.random() < 0.2:
        attempt["sessionId"] = rng.choice(["", "sid"])
    if rng.random() < 0.6:
        attempt["sessionKey"] = rng.choice(["", "main", "agent:x"])
    if rng.random() < 0.6:
        attempt["sessionFile"] = rng.choice(["", "/tmp/s.jsonl"])
    if identity.get("authProfileId") is not None:
        attempt["runtimePlan"] = {"auth": {"forwardedAuthProfileId": identity["authProfileId"]}}
    elif rng.random() < 0.3:
        attempt["runtimePlan"] = rng.choice([{"auth": {}}, {"auth": {"forwardedAuthProfileId": "a1"}}])
    return attempt


def _preflight_case(
    rng: random.Random,
    *,
    model: dict[str, Any],
    identity: dict[str, Any],
    messages: list[dict[str, Any]],
    knobs: dict[str, Any],
    system_prompt: str | None = None,
) -> dict[str, Any]:
    authority = rng.choice(["assembled", "preassembly_may_overflow", "preassembly_may_overflow"])
    heavy = rng.random() < 0.35
    if heavy:
        # Tool results the truncation could reduce, under a tight budget: every recovery route.
        messages = [
            *messages,
            *(
                {**_tool_result(rng, valid=True), "content": [{"type": "text", "text": "data " * rng.choice([800, 4_000, 20_000])}]}
                for _ in range(rng.randrange(1, 5))
            ),
        ]
        knobs = {**knobs, "contextWindowTokens": rng.choice([1_000, 3_000, 8_000, 20_000]), "reserveTokens": 0}
    case: dict[str, Any] = {
        "fn": "preflight",
        "attempt": _preflight_attempt(rng, model, identity),
        "contextEngineAssemblySucceeded": rng.random() < 0.7,
        "contextEnginePromptAuthority": authority,
        "contextTokenBudget": knobs["contextWindowTokens"],
        "hookMessages": messages,
        "includeBoundaryTimestamp": rng.random() < 0.5,
        "promptForPrecheck": knobs["prompt"],
        "reserveTokens": knobs["reserveTokens"],
        "sessionMessageCount": rng.choice([0, len(messages), len(messages) + 4, 7.9]),
        "state": {
            "contextBudgetStatus": rng.choice([None, {"old": 1}]),
            "preflightRecovery": None,
            "promptError": None,
            "promptErrorSource": None,
            "skipPromptSubmission": rng.random() < 0.08,
        },
        "systemPrompt": system_prompt if system_prompt is not None else (knobs["systemPrompt"] or ""),
        "toolResultMaxChars": rng.choice([100, 500, 2_000] if heavy else [None, 20, 500, 5_000]),
    }
    if rng.random() < 0.15:
        case["compactionReplayEnabled"] = rng.choice([True, False])
    else:
        case["eligibility"] = _eligibility(rng, model)
    if rng.random() < 0.7:
        case["activeContextEngine"] = {
            "info": {"id": rng.choice(["lcm", "é"]), "ownsCompaction": rng.random() < 0.7}
        }
    if "toolSchemaTokens" in knobs:
        case["toolSchemaTokens"] = knobs["toolSchemaTokens"]
    if rng.random() < 0.15:
        case["toolSchemaTokens"] = rng.choice([0, 5, 400])
    if rng.random() < 0.5:
        case["appendOnlyRuntimeContext"] = rng.choice([True, False])
    if rng.random() < 0.5:
        case["timezone"] = rng.choice(["", "UTC", "Europe/Istanbul"])
    if (authority == "preassembly_may_overflow" and rng.random() < 0.85) or rng.random() < 0.1:
        unwindowed = copy.deepcopy(messages)
        if rng.random() < 0.7:
            unwindowed = [*unwindowed, _wire_user("older " * rng.choice([10, 300, 3000]))]
        case["unwindowedMessages"] = unwindowed
    return case


def _preflight_cases(measured: list[Any], contexts: dict[Any, Any], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    plain_models = ["responses", "azure", "anthropic", "anthropic_no_url", "completions", "responses_no_url", "chatgpt"]
    for _ in range(count // 3):
        key = rng.choice(plain_models)
        identity = rng.choice(list(IDENTS.values()))
        cases.append(
            _preflight_case(
                rng,
                model=MODELS[key],
                identity=identity,
                messages=_plain_history(rng),
                knobs=_knobs(rng),
            )
        )
    for _ in range(count // 3):
        spec, history = rng.choice(measured)
        messages = _mutate(history, rng.choice(_MUTATIONS), 3)
        knobs = _knobs(rng)
        cases.append(
            _preflight_case(
                rng,
                model=spec["model"],
                identity=spec["identity"],
                messages=messages,
                knobs=knobs,
                system_prompt=spec["systemPrompt"] if rng.random() < 0.8 else None,
            )
        )
    # Responses checkpoints that need /compact, retained windows and plain prefixes.
    for _ in range(150):
        model_key = rng.choice(["responses", "azure", "transport"])
        ident_key = rng.choice(["none", "both"])
        ctx = contexts[(model_key, ident_key)]
        state = rng.choice(
            [
                {**_responses_state(ctx), "compactedWindow": {"state": "refresh-required"}},
                _retained_state(ctx),
                _responses_state(ctx),
            ]
        )
        owner = _wire_assistant(
            MODELS[model_key], [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}], state
        )
        refresh_messages = [_wire_user("q"), owner, _wire_user("tail " * rng.choice([5, 300]))]
        cases.append(
            _preflight_case(
                rng,
                model=MODELS[model_key],
                identity=IDENTS[ident_key],
                messages=refresh_messages,
                knobs=_knobs(rng),
            )
        )
    for _ in range(count - 2 * (count // 3)):
        ident_key = rng.choice(["none", "both"])
        ctx = contexts[("anthropic", ident_key)]
        case = _preflight_case(
            rng,
            model=MODELS["anthropic"],
            identity=IDENTS[ident_key],
            messages=_anthropic_history(rng, ctx),
            knobs=_knobs(rng),
        )
        if rng.random() < 0.8:
            case.pop("compactionReplayEnabled", None)
            case["eligibility"] = {
                "extraParams": {"anthropicServerCompaction": True},
                "apiKey": "sk-ant-api03-abc",
            }
        cases.append(case)
    return cases


def _py_preflight(case: dict[str, Any], row_value: dict[str, Any]) -> dict[str, Any]:
    attempt = case["attempt"]
    model = _py_model(attempt["model"])
    py_attempt = pf.AttemptPromptPreflightAttempt(
        provider=attempt["provider"],
        model_id=attempt["modelId"],
        model=model,
        session_id=attempt.get("sessionId"),
        session_key=attempt.get("sessionKey"),
        session_file=attempt.get("sessionFile"),
        runtime_plan=attempt.get("runtimePlan"),
    )
    eligibility = case.get("eligibility") or {}
    enabled = (
        case["compactionReplayEnabled"]
        if case.get("compactionReplayEnabled") is not None
        else pf.resolve_attempt_compaction_replay_enabled(
            model,
            effective_extra_params=eligibility.get("extraParams"),
            transport_api_key=eligibility.get("apiKey"),
            env=eligibility.get("env") or {},
        )
    )
    engine = case.get("activeContextEngine")
    state = case["state"]
    logs: list[Any] = []
    normalized = row_value.get("boundaryNormalized") if row_value else None
    seen_options: list[Any] = []

    def normalize(messages: list[Any], options: dict[str, Any]) -> list[Any]:
        seen_options.append(options)
        if isinstance(normalized, dict):
            raise type(normalized["error"], (Exception,), {})()
        assert normalized is not None
        return copy.deepcopy(normalized)

    try:
        result = pf.prepare_attempt_prompt_preflight(
            attempt=py_attempt,
            state=pf.AttemptPromptPreflightState(
                context_budget_status=state["contextBudgetStatus"],
                skip_prompt_submission=state["skipPromptSubmission"],
            ),
            compaction_replay_enabled=enabled,
            context_engine_assembly_succeeded=case["contextEngineAssemblySucceeded"],
            context_engine_prompt_authority=case["contextEnginePromptAuthority"],
            context_token_budget=case["contextTokenBudget"],
            hook_messages_for_current_prompt=copy.deepcopy(case["hookMessages"]),
            prompt_for_precheck=case["promptForPrecheck"],
            reserve_tokens=case["reserveTokens"],
            session_message_count=case["sessionMessageCount"],
            system_prompt=case["systemPrompt"],
            tool_result_max_chars=case["toolResultMaxChars"],
            active_context_engine=(
                pf.ContextEngineInfo(engine["info"]["id"], engine["info"]["ownsCompaction"])
                if engine
                else None
            ),
            append_only_runtime_context=case.get("appendOnlyRuntimeContext"),
            include_boundary_timestamp=case["includeBoundaryTimestamp"],
            timezone=case.get("timezone"),
            tool_schema_tokens=case.get("toolSchemaTokens"),
            unwindowed_context_engine_messages_for_precheck=(
                copy.deepcopy(case["unwindowedMessages"]) if "unwindowedMessages" in case else None
            ),
            normalize_messages_for_llm_boundary=normalize,
            now=FIXED_NOW,
            log=lambda level, message: logs.append([level, message]),
        )
    except Exception as exc:  # noqa: BLE001 - compared by class name
        return {"thrown": _error_name(exc), "compactionReplayEnabled": enabled, "boundaryNormalized": normalized}
    for options in seen_options:
        assert options.get("includeTimestamp") is (None if case["includeBoundaryTimestamp"] else False)
        assert ("timezone" in options) is bool(case.get("timezone"))
    return {
        "state": {
            "contextBudgetStatus": result.context_budget_status,
            "preflightRecovery": (
                result.preflight_recovery.to_dict() if result.preflight_recovery else None
            ),
            "promptError": (
                None
                if result.prompt_error is None
                else {"name": _error_name(result.prompt_error), "message": str(result.prompt_error)}
            ),
            "promptErrorSource": result.prompt_error_source,
            "skipPromptSubmission": result.skip_prompt_submission,
        },
        "logs": logs,
        "compactionReplayEnabled": enabled,
        "boundaryNormalized": normalized,
    }


def test_real_openclaw_preflight_matches_python(oracle, measured, contexts):
    cases = _preflight_cases(measured, contexts, 1800, 77)
    rows: list[Any] = []
    for start in range(0, len(cases), 900):
        rows += _run_op(oracle, CASES_OP, cases[start : start + 900])
    assert all(row["error"] is None for row in rows)
    python_rows = [
        {"value": _py_preflight(case, row["value"]), "error": None}
        for case, row in zip(cases, rows, strict=True)
    ]
    assert _diffs(cases, rows, python_rows) == []
    values = [row["value"] for row in rows]
    states = [v["state"] for v in values if "state" in v]
    assert len(states) > 0.8 * len(rows)
    # Every outcome of the call site is exercised.
    assert sum(1 for s in states if s["skipPromptSubmission"] and s["promptErrorSource"] == "precheck" and s["preflightRecovery"]) > 40
    assert {s["preflightRecovery"]["route"] for s in states if s["preflightRecovery"]} >= {
        "compact_only",
        "compact_then_truncate",
        "truncate_tool_results_only",
    }
    assert sum(1 for s in states if s["promptError"] and s["promptError"]["name"] == "CompactionReplayRefreshRequiredError") > 5
    assert sum(1 for s in states if s["contextBudgetStatus"] and "sessionId" in s["contextBudgetStatus"]) > 100
    assert sum(1 for s in states if s["contextBudgetStatus"] == {"old": 1}) > 20
    logs = [line for v in values for line in v.get("logs", [])]
    assert sum(1 for level, msg in logs if "context-pressure-diagnostic" in msg) > 50
    assert sum(1 for level, msg in logs if "skipped: context engine" in msg) > 20
    assert sum(1 for v in values if isinstance(v.get("boundaryNormalized"), list)) > 100
    assert {v["compactionReplayEnabled"] for v in values} == {True, False}


# --- the eligibility call site of compaction-session-execution.ts --------------------------------


def _session_cases(measured: list[Any], contexts: dict[Any, Any], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        if rng.random() < 0.55:
            spec, history = rng.choice(measured)
            model = spec["model"]
            identity = spec["identity"]
            messages = _mutate(history, rng.choice(_MUTATIONS), 3)
        else:
            ident_key = rng.choice(["none", "both"])
            model = MODELS["anthropic"]
            identity = IDENTS[ident_key]
            messages = _anthropic_history(rng, contexts[("anthropic", ident_key)])
        case: dict[str, Any] = {
            "fn": "compactionSession",
            "model": model,
            "messages": messages,
            "limitFrom": rng.choice([0, 1, 2, 3, len(messages)]),
            "systemPrompt": rng.choice([None, "You are helpful.", "sys " * 100]),
            **{k: v for k, v in identity.items() if k in ("sessionId", "authProfileId")},
        }
        if model["api"] == "anthropic-messages" or rng.random() < 0.2:
            case.update(_eligibility(rng, model))
            if rng.random() < 0.7:
                case["extraParams"] = {"anthropicServerCompaction": True}
                case["apiKey"] = "sk-ant-api03-abc"
        cases.append(case)
    return cases


def _py_session(case: dict[str, Any]) -> dict[str, Any]:
    model = _py_model(case["model"])
    session = pf.resolve_compaction_session_replay(
        model,
        session_id=case.get("sessionId"),
        forwarded_auth_profile_id=case.get("authProfileId"),
        extra_params=case.get("extraParams"),
        transport_api_key=case.get("apiKey"),
        env=case.get("env") or {},
    )
    original = copy.deepcopy(case["messages"])
    windowed = session.preserve_window(original, original[case["limitFrom"] :])
    return {
        "enabled": session.enabled,
        "window": _clean(windowed),
        "windowRefs": [next((i for i, m in enumerate(original) if m is w), -1) for w in windowed],
        "tokensAfter": session.estimate_server_compaction_tokens_after(
            messages=_clean(windowed), system_prompt=case["systemPrompt"]
        ),
    }


def test_real_openclaw_compaction_session_replay_wiring_matches_python(oracle, measured, contexts):
    cases = _session_cases(measured, contexts, 700, 303)
    rows = _run_op(oracle, CASES_OP, cases)
    python = []
    for case in cases:
        try:
            python.append({"value": _py_session(case), "error": None})
        except Exception as exc:  # noqa: BLE001
            python.append({"value": None, "error": _error_name(exc)})
    # A malformed checkpoint state throws in both; only the class is compared (V8's wording differs).
    no_message = [{**r, "message": None} for r in rows]
    assert _diffs(cases, no_message, [{**r, "message": None} for r in python]) == []
    values = [row["value"] for row in rows if row["error"] is None]
    assert len(values) > 0.6 * len(rows)
    assert {v["enabled"] for v in values} == {True, False}
    assert sum(1 for v in values if -1 in v["windowRefs"]) > 20
    assert sum(1 for v in values if v["enabled"] and v["tokensAfter"] > 0) > 100
