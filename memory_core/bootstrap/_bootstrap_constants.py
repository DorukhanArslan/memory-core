"""Upstream bootstrap budget constants and policy-digest keywords.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
src/agents/embedded-agent-helpers/bootstrap.ts,
src/agents/bootstrap-budget.ts,
src/agents/bootstrap-budget-warning.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
The *_UNBOUNDED_KEYWORDS match without word boundaries (the second alternation
group of the upstream /\b(?:...)\b|(?:...)/iu patterns).
"""

from __future__ import annotations

DEFAULT_BOOTSTRAP_MAX_CHARS = 20000
DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS = 60000
USER_BOOTSTRAP_MAX_CHARS = 4000
MIN_BOOTSTRAP_FILE_BUDGET_CHARS = 64
BOOTSTRAP_HEAD_RATIO = 0.75
BOOTSTRAP_TAIL_RATIO = 0.25
MIN_BOOTSTRAP_TRIMMED_CONTENT_CHARS = 16
AGENTS_POLICY_DIGEST_RATIO = 0.35
AGENTS_POLICY_HEAD_RATIO = 0.45
AGENTS_POLICY_TAIL_RATIO = 0.15
AGENTS_POLICY_DIGEST_MAX_LINE_CHARS = 240
DEFAULT_BOOTSTRAP_NEAR_LIMIT_RATIO = 0.85
DEFAULT_BOOTSTRAP_PROMPT_WARNING_MAX_FILES = 3
DEFAULT_BOOTSTRAP_PROMPT_WARNING_SIGNATURE_HISTORY_MAX = 32
POLICY_DIGEST_KEYWORDS: tuple[str, ...] = (
    'AGENTS.md',
    'scoped',
    'required',
    'must',
    'never',
    'do not',
    'before subtree',
    'read scoped',
    'owner',
    'security',
    'secret',
    'credential',
    'test',
    'validation',
    'command',
    'commit',
    'push',
    'github',
    'pr',
)
POLICY_DIGEST_UNBOUNDED_KEYWORDS: tuple[str, ...] = (
    '\U0001f534',
    '\u7981\u6b62',
    '\u56b4\u7981',
    '\u4e0d\u5f97',
    '\u7d55\u4e0d',
    '\u7d55\u5c0d\u4e0d',
    '\u5207\u52ff',
    '\u5fc5\u9808',
    '\u52d9\u5fc5',
    '\u4e00\u5f8b',
    '\u7d05\u7dda',
)
POLICY_DIGEST_HIGH_PRIORITY_KEYWORDS: tuple[str, ...] = (
    'AGENTS.md',
    'scoped',
    'required',
    'must',
    'never',
    'do not',
    'before subtree',
    'read scoped',
    'security',
    'secret',
    'credential',
)
POLICY_DIGEST_HIGH_PRIORITY_UNBOUNDED_KEYWORDS: tuple[str, ...] = (
    '\U0001f534',
    '\u7981\u6b62',
    '\u56b4\u7981',
    '\u4e0d\u5f97',
    '\u7d55\u4e0d',
    '\u7d55\u5c0d\u4e0d',
    '\u5207\u52ff',
)
