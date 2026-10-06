"""The overflow selection of ``recoverEmbeddedRunOverflow`` and the host hooks of the error path.

The selection is an inline expression of ``run/overflow-context-recovery.ts`` and cannot be reached
from the oracle; its two building blocks (``isContextOverflow`` and the provider-plugin hook of
``isContextOverflowError``) are compared with the real TypeScript in
``tests/integration/test_openclaw_assistant_overflow_oracle.py``.
"""

from __future__ import annotations

from typing import Any

from memory_core.overflow_recovery import (
    ContextOverflowError,
    PreparedProviderFailoverOwner,
    is_context_overflow_error,
    is_likely_context_overflow_error,
    resolve_context_overflow_error,
)

OVERFLOW = "prompt is too long: 213462 tokens > 200000 maximum"


def _assistant(stop: str, error: str | None = None, **usage: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": [],
        "stopReason": stop,
        "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, **usage},
    }
    if error is not None:
        message["errorMessage"] = error
    return message


def test_a_prompt_error_decides_alone():
    assistant = _assistant("error", OVERFLOW)
    assert resolve_context_overflow_error(prompt_error=RuntimeError(OVERFLOW), assistant=assistant) == (
        ContextOverflowError(OVERFLOW, "promptError")
    )
    # A non-overflow prompt failure does not inherit the stale assistant overflow.
    assert resolve_context_overflow_error(prompt_error="network down", assistant=assistant) is None
    assert resolve_context_overflow_error(prompt_error="network down", assistant_error_text=OVERFLOW) is None


def test_aborted_or_signal_owned_runs_select_nothing():
    assistant = _assistant("error", OVERFLOW)
    assert resolve_context_overflow_error(aborted=True, assistant=assistant, context_token_budget=1) is None
    assert resolve_context_overflow_error(signal_owned_interruption=True, prompt_error=OVERFLOW) is None


def test_assistant_error_uses_the_response_not_a_text_guess():
    overflow = _assistant("error", f"  {OVERFLOW}  ")
    assert resolve_context_overflow_error(assistant=overflow, context_token_budget=200_000) == (
        ContextOverflowError(OVERFLOW, "assistantError")
    )
    # Without a budget the shape check is off; the text fallback needs assistant_error_text.
    assert resolve_context_overflow_error(assistant=overflow) is None
    assert resolve_context_overflow_error(assistant=overflow, assistant_error_text=OVERFLOW) == (
        ContextOverflowError(OVERFLOW, "assistantError")
    )
    # A structured failover reason vetoes everything for an errored response.
    assert (
        resolve_context_overflow_error(
            assistant=overflow,
            classification={"kind": "reason", "reason": "rate_limit"},
            context_token_budget=200_000,
            assistant_error_text=OVERFLOW,
        )
        is None
    )
    # A structured overflow classification wins, with the generic text when none was recorded.
    assert resolve_context_overflow_error(
        assistant=_assistant("error"), classification={"kind": "context_overflow"}
    ) == ContextOverflowError("Context window exceeded", "assistantError")
    assert resolve_context_overflow_error(
        assistant=_assistant("error", "   "), classification={"kind": "context_overflow"}
    ) == ContextOverflowError("Context window exceeded", "assistantError")


def test_provider_refusal_and_length_stop_veto_the_text_fallback():
    refusal = {**_assistant("error", OVERFLOW), "diagnostics": [{"type": "provider_refusal"}]}
    assert (
        resolve_context_overflow_error(
            assistant=refusal,
            classification={"kind": "context_overflow"},
            context_token_budget=1,
            assistant_error_text=OVERFLOW,
        )
        is None
    )
    length = _assistant("length", input=10, output=5)
    assert resolve_context_overflow_error(assistant=length, assistant_error_text=OVERFLOW) is None
    # A length stop with no output and a prompt filling the window is itself an overflow.
    filled = _assistant("length", input=995)
    assert resolve_context_overflow_error(assistant=filled, context_token_budget=1_000) == (
        ContextOverflowError("Context window exceeded", "assistantError")
    )


def test_silent_overflow_selects_the_assistant():
    silent = _assistant("stop", input=300, cacheRead=900, cacheWrite=100)
    assert resolve_context_overflow_error(assistant=silent, context_token_budget=1_000) == (
        ContextOverflowError("Context window exceeded", "assistantError")
    )
    assert resolve_context_overflow_error(assistant=silent, context_token_budget=2_000) is None


def test_assistant_error_text_only_without_an_assistant_message():
    assert resolve_context_overflow_error(assistant_error_text=OVERFLOW) == ContextOverflowError(
        OVERFLOW, "assistantError"
    )
    assert resolve_context_overflow_error(assistant_error_text="rate limit hit, retry later") is None
    assert resolve_context_overflow_error() is None


def test_provider_plugin_hook_and_discovery():
    message = "acme token ceiling reached: input too long for this deployment"
    assert not is_context_overflow_error(message)
    plugin = PreparedProviderFailoverOwner(
        id="acme", matches_context_overflow_error=lambda ctx: "acme token ceiling" in ctx["errorMessage"]
    )
    assert is_context_overflow_error(message, provider_plugin=plugin)
    assert not is_context_overflow_error(message, provider_plugin=None), "explicit absence skips discovery"
    # An unset plugin goes through the host's discovery; its verdict is a failover reason.
    seen: list[dict[str, Any]] = []

    def discover(context: dict[str, Any]) -> str | None:
        seen.append(context)
        return "context_overflow"

    assert is_context_overflow_error(message, discover_provider_plugin=discover)
    assert seen == [{"errorMessage": message}]
    # isLikelyContextOverflowError passes no plugin, so only discovery can supply one.
    assert is_likely_context_overflow_error(message, discover_provider_plugin=discover)
    assert not is_likely_context_overflow_error(message)
    # The plugin is consulted only behind the candidate gate (a rate limit never reaches it).
    rate_limited = "429 rate limit: acme token ceiling reached, input too long"
    assert not is_context_overflow_error(rate_limited, provider_plugin=plugin)
    # classifyFailoverReason is the fallback verdict when the matcher defers.
    reason_only = PreparedProviderFailoverOwner(id="acme", classify_failover_reason=lambda _c: "context_overflow")
    assert is_context_overflow_error(message, provider_plugin=reason_only)
    assert not is_context_overflow_error(
        message,
        provider_plugin=PreparedProviderFailoverOwner(id="acme", classify_failover_reason=lambda _c: "rate_limit"),
    )
