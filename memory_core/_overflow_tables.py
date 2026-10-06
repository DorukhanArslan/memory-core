"""Context-overflow wording tables of OpenClaw v2026.9.6, ported scope by scope.

Sources: ``packages/ai/src/utils/overflow.ts`` (``CONTEXT_OVERFLOW_PATTERN_SCOPES``,
``matchesContextOverflowMessage``), ``src/agents/failover/context-overflow-tables.ts`` (the
provider-fallback candidate gate) and the ``rateLimit`` and ``billing`` tables of
``src/agents/failover/message-patterns.ts`` that ``isLikelyContextOverflowError`` consults.

JavaScript regex semantics are kept: patterns run ASCII-only (``\\b``, ``\\w``, case folding), the
JS ``\\s`` set replaces Python's, ``[\\s\\S]`` becomes "any character" and ``$`` anchors only at the
very end of the text.
"""

from __future__ import annotations

import re
from typing import Final

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim


_JS_DOT = "[^\\n\\r\\u2028\\u2029]"


def _translate(pattern: str) -> str:
    """Rewrites the JS-only constructs of a pattern for ``re`` (see the module docstring)."""

    out: list[str] = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if not in_class and pattern.startswith("[\\s\\S]", index):
            out.append("(?s:.)")
            index += 6
            continue
        if char == "\\" and index + 1 < len(pattern):
            nxt = pattern[index + 1]
            if nxt == "s":
                out.append(JS_SPACE_CLASS if in_class else f"[{JS_SPACE_CLASS}]")
            elif nxt == "S" and not in_class:
                out.append(f"[^{JS_SPACE_CLASS}]")
            else:
                out.append(char + nxt)
            index += 2
            continue
        if char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        elif not in_class and char == "$":
            out.append("\\Z")
            index += 1
            continue
        elif not in_class and char == ".":
            out.append(_JS_DOT)
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def js_regex(pattern: str, *, ignore_case: bool = True) -> re.Pattern[str]:
    flags = re.ASCII | (re.IGNORECASE if ignore_case else 0)
    return re.compile(_translate(pattern), flags)


_CONFIGURED_CONTEXT_SIZE = r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?"

ASSISTANT_OVERFLOW_PATTERNS: Final = tuple(
    js_regex(pattern)
    for pattern in (
        r"prompt is too long",
        r"request_too_large",
        r"input length and `?max_tokens`? exceed context limit: [\d,]+ \+ [\d,]+ > [\d,]+",
        r"input is too long for requested model",
        r"exceeds the context window",
        r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
        r"input token count.*exceeds the maximum",
        r"maximum prompt length is \d+",
        r"reduce the length of the messages",
        r"maximum context length is \d+ tokens",
        r"exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?",
        r"input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)",
        r"exceeds the limit of \d+",
        r"(?:exceeds the available context size|context size has been exceeded)",
        r"greater than the context length",
        r"context window exceeds limit",
        r"exceeded model token limit",
        r"tokens? in request more than max tokens? allowed",
        r"prompt exceeds max(?:imum)? length",
        r"too large for model with \d+ maximum context length",
        _CONFIGURED_CONTEXT_SIZE,
        r"model_context_window_exceeded",
        r"prompt too long; exceeded (?:max )?context length",
        r"context[_ ]length[_ ]exceeded",
        r"too many tokens",
        r"token limit exceeded",
        r"^413\s*(?:status code)?\s*\(no body\)",
    )
)

FAILOVER_EXPLICIT_OVERFLOW_PATTERNS: Final = (
    *(
        js_regex(pattern)
        for pattern in (
            r"request_too_large",
            r"context_overflow",
            _CONFIGURED_CONTEXT_SIZE,
            r"invalid_argument[\s\S]*maximum number of tokens",
            r"request exceeds the maximum size",
            r"context length exceeded",
            r"maximum context length",
            r"prompt is too long",
            r"prompt too long",
            r"exceeds model context window",
            r"model token limit",
            r"input exceeds[\s\S]*maximum number of tokens",
            r"^(?=[\s\S]*context window)(?=[\s\S]*ran out of (?:room|space))",
            r"request size exceeds[\s\S]*context window",
            r"context overflow:",
            r"exceed context limit",
            r"exceeds the model'?s maximum context",
            r"max_tokens[\s\S]*exceed[\s\S]*context",
            r"input(?: length[\s\S]*exceed[\s\S]*context| \([\d,]+\s*tokens?\) is longer than (?:the )?model'?s context length)",
            r"413[\s\S]*too large",
            r"context_window_exceeded",
            r"input length [\d,]+\s+tokens? exceeds the model limit",
        )
    ),
    re.compile("上下文过长|上下文超出|上下文长度超|超出最大上下文|请压缩上下文"),
)

PROVIDER_FALLBACK_OVERFLOW_PATTERNS: Final = tuple(
    js_regex(pattern)
    for pattern in (
        r"\binput token count exceeds the maximum number of input tokens\b",
        r"\binput is too long for this model\b",
        r"\binput exceeds the maximum number of tokens\b",
        r"\bollama error:\s*context length exceeded(?:,\s*too many tokens)?\b",
        r"\btotal tokens?.*exceeds? (?:the )?(?:model(?:'s)? )?(?:max|maximum|limit)",
        r"\b(?:(?:request|prompt) \(\d[\d,]*\s*tokens?\) exceeds (?:the )?available context size|context size has been exceeded)\b",
        r"\binput (?:is )?too long for (?:the )?model\b",
    )
)

CONTEXT_OVERFLOW_PATTERN_SCOPES: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "assistant-error": ASSISTANT_OVERFLOW_PATTERNS,
    "failover-explicit": FAILOVER_EXPLICIT_OVERFLOW_PATTERNS,
    "provider-fallback": PROVIDER_FALLBACK_OVERFLOW_PATTERNS,
    "failover-hint": (
        js_regex(
            r"context.*overflow|context window.*(too (?:large|long)|exceed|over|limit|max(?:imum)?|requested|sent|tokens)|prompt.*(too (?:large|long)|exceed|over|limit|max(?:imum)?)|(?:request|input).*(?:context|window|length|token).*(too (?:large|long)|exceed|over|limit|max(?:imum)?)"
        ),
    ),
    "context-window-too-small": (js_regex(r"context window.*(too small|minimum is)"),),
    "tpm-rate-limit-hint": (js_regex(r"\btpm\b|tokens per minute"),),
    "rate-limit-hint": (
        js_regex(
            r"rate limit|too many requests|requests per (?:minute|hour|day)|quota|throttl|429\b|tokens per day"
        ),
    ),
}


def matches_context_overflow_message(error_message: str, scope: str) -> bool:
    """``matchesContextOverflowMessage``: one canonical wording scope, no caller policy."""

    return any(pattern.search(error_message) for pattern in CONTEXT_OVERFLOW_PATTERN_SCOPES[scope])


_PROVIDER_SIGNAL_RE = js_regex(r"\b(?:context|window|prompt|token|tokens|input|request|model)\b")
_PROVIDER_ACTION_RE = js_regex(
    r"\b(?:too\s+(?:large|long|many)|exceed(?:s|ed|ing)?|overflow|limit|maximum|max)\b"
)


def looks_like_provider_context_overflow_candidate(error_message: str) -> bool:
    return (
        not is_rate_limit_error_message(error_message)
        and _PROVIDER_SIGNAL_RE.search(error_message) is not None
        and _PROVIDER_ACTION_RE.search(error_message) is not None
    )


# --- message-patterns.ts: the rateLimit and billing tables -------------------------------------

_RATE_LIMIT_429_RE = js_regex(
    r"""^\s*429\b|\b(?:https?|status(?:[ _-]?code)?|response(?:[ _-]?code)?|http(?:[ _-]?status)?)\b[\s:=#"'(]{0,6}429\b|["'](?:status|code)["']\s*:\s*429\b|\b429\b[\s:)\].,-]*(?:rate[_ -]?limit(?:ed|ing)?|too many requests|resource has been exhausted|quota(?:\s+(?:exceeded|exhausted|depleted|reached))?)\b"""
)

_RATE_LIMIT_PATTERNS: Final[tuple[re.Pattern[str] | str, ...]] = (
    js_regex(r"rate[_ ]limit|too many requests"),
    _RATE_LIMIT_429_RE,
    js_regex(r"too many (?:concurrent )?requests"),
    js_regex(r"\bthrottl(?:ing[_]?exception|ing|ed)\b"),
    js_regex(r"\bconcurrency limit\b.*\b(?:breached|reached)\b"),
    "model_cooldown",
    "exceeded your current quota",
    js_regex(r"\bresource[_ -]?exhausted\b"),
    js_regex(r"\bquota[_ -]?exceeded\b"),
    "usage limit",
    js_regex(r"\btpm\b"),
    "tokens per minute",
    "tokens per day",
    "请求过于频繁",
    "调用频率",
    "频率限制",
    "配额不足",
    "配额已用尽",
    "额度不足",
    "额度已用尽",
)

_BILLING_ERROR_HARD_402_RE = js_regex(
    r"""["']?(?:status|code)["']?\s*[:=]\s*402\b|\bhttp\s*402\b|\berror(?:\s+code)?\s*[:=]?\s*402\b|^\s*402\s+payment"""
)

_BILLING_PATTERNS: Final[tuple[re.Pattern[str] | str, ...]] = (
    _BILLING_ERROR_HARD_402_RE,
    js_regex(r"\b(?:got|returned|received)\s+(?:a\s+)?402\b(?!\s+records\b)"),
    "payment required",
    "insufficient credits",
    js_regex(r"used\s+all\s+available\s+credits"),
    js_regex(r"(?:monthly\s+)?spend(?:ing)?\s+limit"),
    js_regex(r"insufficient[_ ]quota"),
    js_regex(r"\b(?:go|free)usagelimiterror\b"),
    "available balance",
    "out of budget",
    "credit balance",
    "plans & billing",
    js_regex(r"insufficient[_ ]balance"),
    js_regex(r"\binsufficient\s+\w+\s+balance\b"),
    "insufficient usd or diem balance",
    js_regex(r"requires?\s+more\s+credits"),
    js_regex(r"out of extra usage"),
    js_regex(r"draw from your extra usage"),
    js_regex(r"extra usage is required(?: for long context requests)?"),
    "余额不足",
    "欠费",
    js_regex(r""""code"\s*:\s*"InvalidSubscription\""""),
    js_regex(r"\bdoes not have a valid coding\s*plan subscription\b"),
    js_regex(r""""code"\s*:\s*1311\b""", ignore_case=False),
    js_regex(
        r"\bcurrent\s+subscription\s+plan\b.*\b(?:does\s+not|doesn't|not)\b.*\binclude\s+access\b"
    ),
    js_regex(r"\bmodel\b.*\bnot\s+available\b.*\bcurrent\s+plan\b"),
)

_BILLING_ERROR_HEAD_RE = js_regex(
    r"^(?:error[:\s-]+)?billing(?:\s+error)?(?:[:\s-]+|$)|^(?:error[:\s-]+)?(?:credit balance|insufficient credits?|payment required|http\s*402\b)"
)
_MARKDOWN_SECTION_RE = re.compile(
    f"(?:^|\\n)##[{JS_SPACE_CLASS}]+[^{JS_SPACE_CLASS}]"
)


def _normalize_lower(value: str) -> str:
    return js_trim(value).lower() if isinstance(value, str) else ""


def _matches_error_patterns(raw: str, patterns: tuple[re.Pattern[str] | str, ...]) -> bool:
    if not raw:
        return False
    value = _normalize_lower(raw)
    return any(
        pattern.search(value) is not None if isinstance(pattern, re.Pattern) else pattern in value
        for pattern in patterns
    )


def is_rate_limit_error_message(raw: str) -> bool:
    return _matches_error_patterns(raw, _RATE_LIMIT_PATTERNS)


def is_billing_error_message(raw: str) -> bool:
    value = _normalize_lower(raw)
    if not value:
        return False
    # Multi-section Markdown is explanatory content, not a provider error body.
    if len(_MARKDOWN_SECTION_RE.findall(raw)) > 1:
        return False
    if _matches_error_patterns(value, _BILLING_PATTERNS):
        return True
    if _BILLING_ERROR_HEAD_RE.search(raw) is None:
        return False
    return any(
        word in value
        for word in ("upgrade", "credits", "payment", "purchase", "subscription", "plan")
    )
