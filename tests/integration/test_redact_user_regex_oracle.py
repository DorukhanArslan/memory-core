"""The JavaScript-regex translator of ``logging.redactPatterns`` against V8, on generated expressions.

Each generated pattern (a literal ``/body/flags`` or a bare source) is compiled by the real
``compileConfigRegex`` and run through ``redactSensitiveText({patterns: [pattern]})`` over short
texts drawn from a small alphabet (so most patterns match), and the Python port must agree on the
classification and on every output. Valid JavaScript the port reports as ``unsupported-syntax`` is
checked for the classification only.

Run: ``OPENCLAW_ORACLE_NODE=... OPENCLAW_ORACLE_REPO=/tmp/openclaw-head pytest
tests/integration/test_redact_user_regex_oracle.py``.
"""

from __future__ import annotations

import random

import pytest
from redact_policy_harness import compare, oracle_run

from memory_core.redact_user_patterns import compile_redact_pattern

_LITERALS = [
    "a", "b", "c", "1", "2", "-", "_", " ", "é", "😀", "\\n", "\\.", "\\-", "\\/", "ab", "A", "x",
    "{", "}", "]", "a{x}", "\\8", "\\101", "[^]", "[]", "\\ud83d", "\\x4", "\\k", "\\c", "\\_",
]  # fmt: skip
_CLASSES = [
    "\\d", "\\w", "\\s", "\\D", "\\W", "\\S", ".", "[ab]", "[^ab]", "[a-c1]", "[\\d_]", "[^\\s]", "[\\w-]",
    "[a\\-z]", "[\\D1]", "[\\b]", "[\\u0061-c]", "[\\x61-\\x63]", "[\\-a]", "[a-]", "[\\0]", "[\\cJ]",
]  # fmt: skip
_QUANT = ["", "", "", "*", "+", "?", "{2}", "{1,2}", "{2,}", "*?", "+?", "??", "{1,3}?"]
_FLAGS = ["", "", "i", "m", "s", "u", "iu", "im", "ms", "y", "gi", "ims"]
_TEXT_PARTS = [
    "a", "b", "c", "1", "2", "-", "_", " ", "\n", "\r", "é", "É", "😀", "A", "x", ".", "ab", "aa", "\t",
    "\u2028", "\u00a0", "/",
]  # fmt: skip


def _random_regex(rnd: random.Random, depth: int = 0) -> str:
    def atom() -> str:
        roll = rnd.random()
        if roll < 0.35:
            return rnd.choice(_LITERALS)
        if roll < 0.6:
            return rnd.choice(_CLASSES)
        if roll < 0.68:
            return rnd.choice(["^", "$", "\\b", "\\B"])
        if depth < 2 and roll < 0.9:
            inner = _random_regex(rnd, depth + 1)
            kind = rnd.choice(["(", "(?:", "(?=", "(?!", "(?<=a", "(?<!b", "(?<n>"])
            if kind.startswith(("(?<=", "(?<!")):
                return f"{kind})" if rnd.random() < 0.5 else f"{kind}{rnd.choice(['b', '1', 'c'])})"
            return f"{kind}{inner})"
        if roll < 0.95:
            return "\\1"
        return rnd.choice(["\\u0061", "\\x62", "\\cJ", "\\0", "\\u{61}"])

    parts = []
    for _ in range(rnd.randint(1, 4)):
        piece = atom()
        if not piece.startswith(("^", "$", "\\b", "\\B", "(?=", "(?!", "(?<=", "(?<!")) and piece != "\\1":
            piece += rnd.choice(_QUANT)
        parts.append(piece)
    body = "".join(parts)
    if rnd.random() < 0.25:
        body += "|" + "".join(rnd.choice(_LITERALS + _CLASSES) for _ in range(rnd.randint(1, 3)))
    return body


def _random_pattern(rnd: random.Random) -> str:
    body = _random_regex(rnd)
    flags = rnd.choice(_FLAGS)
    return f"/{body}/{flags}" if rnd.random() < 0.8 and "/" not in body else body


def texts_for(rnd: random.Random, pattern: str) -> list[str]:
    # An empty match inside an astral character under the u flag is an engine corner (V8 resumes
    # between the surrogate halves); u-flag patterns run over BMP texts here, the fixed scenarios
    # cover astral ones.
    parts = [part for part in _TEXT_PARTS if "u" not in pattern.rpartition("/")[2] or part != "\U0001f600"]
    return ["".join(rnd.choice(parts) for _ in range(rnd.randint(0, 14))) for _ in range(8)]


@pytest.mark.parametrize("seed", [31, 32, 33, 34, 35])
def test_generated_user_regexes_match_upstream(seed: int):
    rnd = random.Random(seed)
    scenarios = []
    patterns = []
    for _ in range(500):
        pattern = _random_pattern(rnd)
        patterns.append(pattern)
        texts = texts_for(rnd, pattern)
        steps = [{"fn": "compile", "pattern": pattern}]
        steps += [{"fn": "sensitiveText", "text": text, "patterns": [pattern]} for text in texts]
        scenarios.append({"steps": steps})
    wants = oracle_run(scenarios)
    mismatches = []
    unsupported = 0
    changed = 0
    for pattern, scn, want in zip(patterns, scenarios, wants, strict=True):
        compiled = compile_redact_pattern(pattern)
        if compiled is not None and compiled.reason == "unsupported-syntax":
            unsupported += 1
            # Duplicate group names are valid only in some shapes (V8, ES2025): any is dropped here.
            if pattern.count("(?<n>") < 2:
                assert want["steps"][0]["value"]["reason"] is None, pattern
            continue
        bad = compare(scn, want)
        if bad:
            mismatches.append((pattern, bad[:2]))
        changed += sum(
            1
            for step, result in zip(scn["steps"], want["steps"], strict=True)
            if "text" in step and result["value"] != step["text"]
        )
    assert not mismatches, (len(mismatches), mismatches[:3])
    assert unsupported < 60, unsupported
    assert changed > 400, changed
