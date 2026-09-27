"""Upstream memory-flush prompts, hints and flush-plan defaults.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
extensions/memory-core/src/flush-plan.ts,
src/auto-reply/tokens.ts,
src/agents/agent-settings.ts,
src/agents/agent-compaction-constants.ts,
src/auto-reply/reply/agent-runner-memory.ts,
src/config/sessions/types.ts,
src/cli/parse-bytes.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
The default prompts are the joined upstream arrays with SILENT_REPLY_TOKEN
substituted; MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE is the str.format template of
ensureNoReplyHint (fields: text, silent_reply_token); UNIT_MULTIPLIERS is the
byte-size unit table of parseByteSize.
"""

from __future__ import annotations

SILENT_REPLY_TOKEN = 'NO_REPLY'
DEFAULT_MEMORY_FLUSH_SOFT_TOKENS = 4000
DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES = 2097152
DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR = 20000
MAX_COMPACTION_RESERVE_RATIO = 0.25
MAX_FLUSH_FAILURES = 3
MAX_FLUSH_ERROR_LENGTH = 200
SESSION_TOTAL_TOKENS_VERSION = 1
MEMORY_FLUSH_TARGET_HINT = 'Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed).'
MEMORY_FLUSH_APPEND_ONLY_HINT = 'If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries.'
MEMORY_FLUSH_READ_ONLY_HINT = 'Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them.'
MEMORY_FLUSH_REQUIRED_HINTS: tuple[str, ...] = (
    'Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed).',
    'If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries.',
    'Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them.',
)
DEFAULT_MEMORY_FLUSH_PROMPT = 'Pre-compaction memory flush. Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed). Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them. If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries. Do NOT create timestamped variant files (e.g., YYYY-MM-DD-HHMM.md); always use the canonical YYYY-MM-DD.md filename. If nothing to store, reply with NO_REPLY.'
DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT = 'Pre-compaction memory flush turn. The session is near auto-compaction; capture durable memories to disk. Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed). Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them. If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries. You may reply, but usually NO_REPLY is correct.'
MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE = '{text}\n\nIf no user-visible reply is needed, start with {silent_reply_token}.'
UNIT_MULTIPLIERS: dict[str, int] = {
    'b': 1,
    'kb': 1024,
    'k': 1024,
    'mb': 1048576,
    'm': 1048576,
    'gb': 1073741824,
    'g': 1073741824,
    'tb': 1099511627776,
    't': 1099511627776,
}
