"""The bare reset prompts equal the pinned upstream source text (source-backed check).

Upstream ``src/auto-reply/reply/session-reset-prompt.ts`` builds its pending and
limited variants from ``src/agents/bootstrap-prompt.ts``; the string literals of
both files are extracted and composed the same way, then compared with
``memory_core.bootstrap.startup``. Needs ``OPENCLAW_ORACLE_REPO`` (no Node run).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from memory_core.bootstrap.startup import (
    BARE_SESSION_RESET_PROMPT_BASE,
    BARE_SESSION_RESET_PROMPT_BOOTSTRAP_LIMITED,
    BARE_SESSION_RESET_PROMPT_BOOTSTRAP_PENDING,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENCLAW_ORACLE_REPO"), reason="needs OPENCLAW_ORACLE_REPO"
)
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _source(relative: str) -> str:
    return (Path(os.environ["OPENCLAW_ORACLE_REPO"]) / relative).read_text(encoding="utf-8")


def _block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin: source.index(end, begin)]


def _strings(block: str) -> list[str]:
    return [json.loads(f'"{match}"') for match in _STRING_RE.findall(block)]


def test_bare_session_reset_prompts_equal_upstream_source():
    reset = _source("src/auto-reply/reply/session-reset-prompt.ts")
    bootstrap = _source("src/agents/bootstrap-prompt.ts")
    full_fixed = _strings(_block(bootstrap, "export function buildFullBootstrapPromptLines", "export function buildLimited"))
    limited_fixed = _strings(_block(bootstrap, "export function buildLimitedBootstrapPromptLines", "\n}\n"))
    base = _strings(_block(reset, "const BARE_SESSION_RESET_PROMPT_BASE =", ";\n"))
    pending = _strings(_block(reset, "const BARE_SESSION_RESET_PROMPT_BOOTSTRAP_PENDING", '].join(" ")'))
    limited = _strings(_block(reset, "const BARE_SESSION_RESET_PROMPT_BOOTSTRAP_LIMITED", '].join(" ")'))

    assert base == [BARE_SESSION_RESET_PROMPT_BASE]
    # pending: first line, readLine, firstReplyLine, then two trailing lines.
    head, read_line, first_reply_line, *tail = pending
    assert " ".join([head, read_line, *full_fixed, first_reply_line, *tail]) == (
        BARE_SESSION_RESET_PROMPT_BOOTSTRAP_PENDING
    )
    # limited: first line, introLine (dropped by .slice(1)), nextStepLine, two trailing lines.
    head, _intro_line, next_step_line, *tail = limited
    assert " ".join([head, *limited_fixed, next_step_line, *tail]) == BARE_SESSION_RESET_PROMPT_BOOTSTRAP_LIMITED
