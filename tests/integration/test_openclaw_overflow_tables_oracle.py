"""The context-overflow wording tables (provider-fallback candidates included) against the real TS.

One oracle call classifies a hand-written corpus plus every string literal of the upstream failover
corpus files (``src/agents/failover/failover-classification.*.cases.ts``) that looks like a
provider error. Python must agree on every scope of ``matchesContextOverflowMessage`` and on the
helpers built over them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import _overflow_tables as tables
from memory_core.overflow_recovery import (
    extract_observed_overflow_token_count,
    is_compaction_failure_error,
    is_context_overflow_error,
    is_context_overflow_error_from_tables,
    is_likely_context_overflow_error,
    is_provider_request_size_ceiling_error,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

SCOPES = (
    "assistant-error",
    "failover-explicit",
    "provider-fallback",
    "failover-hint",
    "context-window-too-small",
    "tpm-rate-limit-hint",
    "rate-limit-hint",
)

HAND_WRITTEN = [
    # provider-fallback candidates (the gap): reachable only through the candidate gate
    "AWS Bedrock: Input is too long for this model",
    "ValidationException: input token count exceeds the maximum number of input tokens",
    "Google Vertex: input exceeds the maximum number of tokens allowed",
    "ollama error: context length exceeded, too many tokens",
    "ollama error: context length exceeded",
    "Cohere: total tokens 130000 exceeds the model's max limit of 128000",
    "Cohere: total tokens exceed the limit",
    "request (4096 tokens) exceeds the available context size",
    "prompt (12,000 tokens) exceeds available context size",
    "the context size has been exceeded",
    "Input too long for the model",
    "input is too long for model",
    "rate limit: input is too long for this model",
    "Throttling: input is too long for this model",
    "input is too long for this model; quota exhausted",
    # assistant-error / explicit patterns
    "prompt is too long: 213462 tokens > 200000 maximum",
    '413 {"error":{"type":"request_too_large","message":"Request exceeds the maximum size"}}',
    "Your input exceeds the context window of this model",
    "Requested token count exceeds the model's maximum context length of 131072 tokens",
    "The input token count (1196265) exceeds the maximum number of tokens allowed (1048575)",
    "This model's maximum prompt length is 131072 but the request contains 537812 tokens",
    "Please reduce the length of the messages or completion",
    "This endpoint's maximum context length is 8192 tokens. However, you requested about 9000 tokens",
    "The input (9000 tokens) is longer than the model's context length (8192 tokens).",
    "prompt token count of 9000 exceeds the limit of 8192",
    "the request exceeds the available context size, try increasing it",
    "tokens to keep from the initial prompt is greater than the context length",
    "invalid params, context window exceeds limit",
    "Your request exceeded model token limit: 262144 (requested: 291351)",
    "413 status code (no body)",
    "400 status code (no body)",
    "Prompt contains 9000 tokens ... too large for model with 8192 maximum context length",
    "tokens in request more than max tokens allowed",
    "Prompt exceeds max length",
    "model_context_window_exceeded",
    "prompt too long; exceeded max context length by 1234 tokens",
    "context_length_exceeded",
    "Too many tokens",
    "Token limit exceeded",
    "ThrottlingException: Too many tokens, please wait before trying again.",
    "input length and `max_tokens` exceed context limit: 156321 + 48384 > 200000",
    "input length and max_tokens exceed context limit (i.e 156321 + 48384 > 200000)",
    "input length 250000 tokens exceeds the model limit",
    "Codex ran out of room in the model's context window",
    "the context window ran out of space",
    "Request size exceeds model context window",
    "request size exceeds the maximum allowed",
    "Context overflow: prompt too large for the model.",
    "exceed context limit",
    "exceeds the model's maximum context",
    "invalid_argument: input exceeds the maximum number of tokens",
    "INVALID_ARGUMENT: the maximum number of tokens is 1000",
    "the prompt has 250,000 tokens, but the configured context size is 200,000 tokens",
    "the configured context size is 200,000 tokens for this deployment",
    "413 payload too large",
    "上下文过长，请压缩上下文",
    "context_window_exceeded",
    # exclusions and near misses
    "429 Too Many Requests: request exceeds rate limit",
    "Model context window too small (minimum is 128k tokens)",
    "Rate limit: TPM limit 30,000, requested 45,000 tokens: context overflow: prompt too large",
    "Rate limit reached for tokens per minute. Limit 30000, Requested 100",
    "TPM limit 30000 exceeded, requested 45000 tokens",
    "reasoning is mandatory for this model; context window exceeded",
    "reasoning cannot be disabled; prompt too long",
    "insufficient credits: request size exceeds your balance",
    "billing: maximum token limit exceeded for your plan",
    "402 Payment Required: prompt is too long",
    "prompt template exceeds limit",
    "The prompt template is too long",
    "request reached organization TPD rate limit, limit exceeded",
    "Quota exceeded: input tokens exceed the limit",
    "context window too small and exceeds limit",
    "model: gpt context length limit hit",
    "context.overflow",
    "context\noverflow",
    "# Heading\n\nbilling error\n\n## Section A\n\ntext\n\n## Section B\n\ncontext window exceeded",
    "",
    "   ",
    "x" * 5000 + " context window exceeded",
    "CONTEXT WINDOW EXCEEDED",
    "ſ prompt is too long",
    "prompt iſ too long",
    "the request  context window exceeded",
    "error: 402 payment required",
    "billing error: upgrade your plan",
    "Error - credit balance is too low",
    "HTTP 402: spend limit reached",
    "status: 429 rate_limit_error",
    '{"status": 429, "message": "quota exceeded"}',
    "429 resource has been exhausted",
    "ids: 4290 and 1429 tokens exceed the limit",
    "Insufficient MBT balance; context window exceeded",
    "insufficient to reconcile the final balance",
    "余额不足 request too large",
    "请求过于频繁 context window exceeded",
    '"code": 1311 context window exceeded',
    '"code":"InvalidSubscription" prompt too large',
]


def _upstream_corpus() -> list[str]:
    root = Path(os.environ["OPENCLAW_ORACLE_REPO"]) / "src" / "agents" / "failover"
    found: list[str] = []
    seen: set[str] = set()
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


def _python_case(text: str) -> dict:
    return {
        "scopes": {scope: tables.matches_context_overflow_message(text, scope) for scope in SCOPES},
        "looksLikeCandidate": tables.looks_like_provider_context_overflow_candidate(text),
        "fromTables": is_context_overflow_error_from_tables(text),
        "isContextOverflowError": is_context_overflow_error(text),
        "isLikelyContextOverflowError": is_likely_context_overflow_error(text),
        "isRateLimit": tables.is_rate_limit_error_message(text),
        "isBilling": tables.is_billing_error_message(text),
        "requestSizeCeiling": is_provider_request_size_ceiling_error(text),
    }


def _compare(texts: list[str]) -> list[dict]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run({"operation": "contextOverflowTables", "texts": texts})
    assert result["ok"] is True
    cases = result["result"]["cases"]
    assert len(cases) == len(texts)
    mismatches = [
        (text[:200], expected, _python_case(text))
        for text, expected in zip(texts, cases, strict=True)
        if _python_case(text) != expected
    ]
    assert not mismatches, mismatches[:5]
    return cases


def test_overflow_tables_match_oracle_on_hand_written_corpus():
    cases = _compare(HAND_WRITTEN)
    by_text = dict(zip(HAND_WRITTEN, cases, strict=True))
    # The provider-fallback candidate gate decides these; keep the premise of the test visible.
    assert by_text["AWS Bedrock: Input is too long for this model"]["scopes"]["provider-fallback"]
    assert by_text["AWS Bedrock: Input is too long for this model"]["isContextOverflowError"]
    assert not by_text["rate limit: input is too long for this model"]["isContextOverflowError"]


def test_overflow_tables_match_oracle_on_upstream_failover_corpus():
    corpus = _upstream_corpus()
    assert len(corpus) > 100
    _compare(corpus)


def test_observed_token_count_handles_backticked_max_tokens_form():
    # overflowErrorHelpers covers extraction against the oracle; this form was the missing pattern.
    message = "input length and `max_tokens` exceed context limit: 156321 + 48384 > 200000"
    assert extract_observed_overflow_token_count(message) == 204705
    assert is_likely_context_overflow_error(message)
    assert not is_compaction_failure_error(message)
