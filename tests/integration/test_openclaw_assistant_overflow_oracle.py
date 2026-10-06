"""The assistant-error overflow path and the provider-plugin hook against the real v2026.9.6 TypeScript.

``isContextOverflow`` (packages/ai overflow.ts) classifies scripted assistant messages: error
wording with its throttling exclusions, silent overflow, length-stop overflow, context-usage
buckets and provider refusals. ``isContextOverflowError`` and ``classifyProviderPluginError`` run
with provider plugins built from the same declarative spec on both sides (the Python plugin is the
host-supplied :class:`PreparedProviderFailoverOwner`), including the contexts the hooks receive.
The selection inside ``recoverEmbeddedRunOverflow`` is not reachable from the oracle: see
``tests/unit/test_overflow_assistant_path.py``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.overflow_recovery import (
    UNSET,
    PreparedProviderFailoverOwner,
    classify_provider_plugin_error,
    is_context_overflow,
    is_context_overflow_error,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

TEXTS = [
    "prompt is too long: 213462 tokens > 200000 maximum",
    '413 {"error":{"type":"request_too_large","message":"Request exceeds the maximum size"}}',
    "Your input exceeds the context window of this model",
    "Requested token count exceeds the model's maximum context length of 131072 tokens",
    "The input token count (1196265) exceeds the maximum number of tokens allowed (1048575)",
    "This model's maximum prompt length is 131072 but the request contains 537812 tokens",
    "Please reduce the length of the messages or completion",
    "the request exceeds the available context size, try increasing it",
    "413 status code (no body)",
    "400 status code (no body)",
    "Throttling error: Too many tokens, please wait before trying again.",
    "Service unavailable: prompt is too long",
    "ThrottlingException: Too many tokens, please wait before trying again.",
    "Too many tokens",
    "Rate limit exceeded: prompt is too long",
    "429 Too Many Requests: token limit exceeded",
    "context_length_exceeded",
    "the prompt has 250,000 tokens, but the configured context size is 200,000 tokens",
    "Prompt exceeds max length",
    "Model context window too small (minimum is 128k tokens)",
    "AWS Bedrock: Input is too long for this model",
    "ollama error: context length exceeded, too many tokens",
    "Cohere: total tokens 130000 exceeds the model's max limit of 128000",
    "invalid_argument: input exceeds the maximum number of tokens",
    "上下文过长，请压缩上下文",
    "something unrelated failed",
    "",
]


def _usage(**fields: Any) -> dict[str, Any]:
    return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, **fields}


def _assistant(stop: str | None, error: str | None = None, usage: dict | None = None, **extra: Any) -> dict:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": [],
        "usage": usage if usage is not None else _usage(),
        **extra,
    }
    if stop is not None:
        message["stopReason"] = stop
    if error is not None:
        message["errorMessage"] = error
    return message


def _message_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for text in TEXTS:
        cases.append({"message": _assistant("error", text)})
        cases.append({"message": _assistant("error", text), "contextWindow": 200_000})
        cases.append({"message": _assistant("stop", text)})
        cases.append({"message": _assistant("length", text)})
    refusal = {"diagnostics": [{"type": "provider_refusal"}]}
    cases.append({"message": _assistant("error", TEXTS[0], **refusal)})
    cases.append({"message": _assistant("error", TEXTS[0], diagnostics=[{"type": "other"}])})
    cases.append({"message": _assistant("stop", usage=_usage(input=300_000), **refusal), "contextWindow": 1000})
    cases.append({"message": {"role": "assistant", "content": [], "usage": _usage(), "stopReason": "error"}})
    for window in (None, 0, 1000, 1000.5, 99, 100, 101):
        for tokens in (0, 98, 99, 100, 101, 1000, 1001, 5000):
            for stop in ("stop", "length", "error", "toolUse", "aborted"):
                for output in (0, 1):
                    usage = _usage(input=tokens - 10 if tokens > 10 else tokens, cacheRead=6, cacheWrite=4, output=output)
                    case: dict[str, Any] = {"message": _assistant(stop, usage=usage)}
                    if window is not None:
                        case["contextWindow"] = window
                    cases.append(case)
    # Exact fill boundary of the length-stop rule: >= 0.99 * window.
    for tokens in (989, 990, 991):
        cases.append({"message": _assistant("length", usage=_usage(input=tokens)), "contextWindow": 1000})
    usage_variants: list[dict[str, Any]] = [
        _usage(contextUsage={"state": "available", "promptTokens": 5000}),
        _usage(contextUsage={"state": "available", "promptTokens": 5}),
        _usage(contextUsage={"state": "available"}),
        _usage(contextUsage={"state": "unavailable"}, input=9999),
        _usage(contextUsage={"state": "other"}, input=9999),
        _usage(contextUsage={"state": "available", "promptTokens": 5000}, input=1),
        {"input": 5000},
        {"input": 5000, "cacheRead": None, "cacheWrite": None, "output": 0},
        {"output": 0},
        {"input": 5000, "cacheRead": 1, "output": 0},
    ]
    for usage in usage_variants:
        for stop in ("stop", "length"):
            cases.append({"message": _assistant(stop, usage=usage), "contextWindow": 1000})
    return cases


def _python_message(case: dict[str, Any]) -> dict[str, Any]:
    if "contextWindow" in case:
        return {"isContextOverflow": is_context_overflow(case["message"], case["contextWindow"])}
    return {"isContextOverflow": is_context_overflow(case["message"])}


def _oracle(cases: list[dict[str, Any]]) -> dict[str, Any]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run({"operation": "assistantOverflow", "cases": cases})
    assert result["ok"] is True
    return result["result"]


def test_is_context_overflow_matches_oracle():
    cases = _message_cases()
    expected = _oracle(cases)["messages"]
    assert len(expected) == len(cases)
    mismatches = [
        (case, want, _python_message(case))
        for case, want in zip(cases, expected, strict=True)
        if _python_message(case) != want
    ]
    assert not mismatches, mismatches[:3]
    flags = {item["isContextOverflow"] for item in expected}
    assert flags == {True, False}
    assert sum(item["isContextOverflow"] for item in expected) > 60


def _upstream_corpus() -> list[str]:
    root = Path(os.environ["OPENCLAW_ORACLE_REPO"]) / "src" / "agents" / "failover"
    found: list[str] = []
    seen: set[str] = set(TEXTS)
    literal = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
    for path in sorted(root.glob("failover-classification.*.cases.ts")):
        for match in literal.finditer(path.read_text(encoding="utf-8")):
            try:
                text = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                continue
            if len(text) < 12 or " " not in text or text in seen:
                continue
            seen.add(text)
            found.append(text)
    return found


def test_is_context_overflow_matches_oracle_on_upstream_failover_corpus():
    corpus = _upstream_corpus()
    assert len(corpus) > 100
    cases = [{"message": _assistant("error", text)} for text in corpus]
    expected = _oracle(cases)["messages"]
    for case, want in zip(cases, expected, strict=True):
        assert _python_message(case) == want, case["message"]["errorMessage"][:200]


PLUGIN_SPECS: dict[str, dict[str, Any] | None] = {
    "none": None,
    "matches": {"id": "acme", "matches": [r"acme token ceiling", r"too big for acme"]},
    "matches-undefined": {"id": "acme", "matches": [r".*"], "matchReturn": "undefined"},
    "matches-and-reason": {"id": "acme", "matches": [r"zzz-never"], "reason": "context_overflow"},
    "reason-overflow": {"id": "acme", "reason": "context_overflow"},
    "reason-other": {"id": "acme", "reason": "rate_limit"},
    "reason-null": {"id": "acme", "reason": None},
    "empty": {"id": "acme"},
}
PLUGIN_TEXTS = [
    "acme token ceiling reached: input too long for this deployment",
    "too big for acme: tokens limit",
    "acme says the prompt is a lot of tokens over the limit",
    "context window exceeded for the request",
    "Rate limit: acme token ceiling exceeded, input length over the maximum",
    "billing: prompt token limit exceeded for plan",
    "completely unrelated failure",
    "zzz-never matches, but the request token limit exceeded the maximum",
    "AWS Bedrock: Input is too long for this model",
    "",
]
CONTEXTS: list[dict[str, Any]] = [
    {},
    {"provider": "acme", "modelId": "m1", "status": 413, "code": "too_long", "errorType": "invalid_request"},
]


def _python_plugin(spec: dict[str, Any] | None, mode: str, text: str, context: dict[str, Any]) -> dict[str, Any]:
    calls: list[Any] = []
    plugin: PreparedProviderFailoverOwner | None = None
    if spec is not None:

        def matches(ctx: dict[str, Any]) -> bool | None:
            calls.append({"hook": "matches", "ctx": ctx})
            if spec.get("matchReturn") == "undefined":
                return None
            return any(re.search(source, ctx["errorMessage"], re.I) for source in spec["matches"])

        def classify(ctx: dict[str, Any]) -> str | None:
            calls.append({"hook": "classify", "ctx": ctx})
            return spec["reason"]

        plugin = PreparedProviderFailoverOwner(
            id=spec["id"],
            matches_context_overflow_error=matches if spec.get("matches") else None,
            classify_failover_reason=classify if "reason" in spec else None,
        )
    provider_plugin: Any = None if mode == "null" else UNSET if mode == "unset" else plugin
    return {
        "isContextOverflowError": is_context_overflow_error(text, provider_plugin=provider_plugin),
        "classify": classify_provider_plugin_error(
            {"errorMessage": text, **context}, provider_plugin=provider_plugin
        ),
        "calls": calls,
    }


def test_provider_plugin_hook_matches_oracle():
    cases: list[dict[str, Any]] = []
    python_cases: list[tuple[dict[str, Any] | None, str, str, dict[str, Any]]] = []
    for mode in ("owner", "null", "unset"):
        for name, spec in PLUGIN_SPECS.items():
            if mode != "owner" and name not in ("none", "matches"):
                continue
            for text in PLUGIN_TEXTS:
                for context in CONTEXTS:
                    case: dict[str, Any] = {"text": text, "mode": mode, "context": context}
                    if spec is not None:
                        case["plugin"] = spec
                    cases.append(case)
                    python_cases.append((spec, mode, text, context))
    expected = _oracle(cases)["plugins"]
    assert len(expected) == len(cases)
    for index, (want, args) in enumerate(zip(expected, python_cases, strict=True)):
        assert _python_plugin(*args) == want, (index, cases[index])
    # Premises: the plugin decides a message the tables do not, only behind the candidate gate.
    flags = {
        (case["plugin"]["id"] if case.get("plugin") else None, case["text"], case["mode"]): want[
            "isContextOverflowError"
        ]
        for case, want in zip(cases, expected, strict=True)
    }
    assert flags[("acme", PLUGIN_TEXTS[2], "owner")] is False
    assert any(want["calls"] for want in expected), "the hooks were exercised"
    assert any(want["isContextOverflowError"] for case, want in zip(cases, expected, strict=True) if case["mode"] == "owner")
    assert not any(
        want["isContextOverflowError"] and not _python_plugin(None, "unset", case["text"], {})["isContextOverflowError"]
        for case, want in zip(cases, expected, strict=True)
        if case["mode"] != "owner"
    )
