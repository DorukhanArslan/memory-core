"""Extract upstream constants from the OpenClaw TypeScript source (no hand-copying).

AGENTS.md › Parity rules: upstream prompt, template and safety constants are copied verbatim by
script, and a set-equality check compares them with the source at test time
(tests/integration/test_extracted_upstream_constants.py). From the checkout named by
``--repo`` (default ``OPENCLAW_ORACLE_REPO``) this script generates, writing every non-ASCII
character as a ``\\u`` escape:

- ``memory_core/bootstrap/_tools_md_constants.py``: the TOOLS.md migration templates, guidance
  rewrites and heading, and the doctor finding texts of ``collectToolsMdMigrationFindings``
  (src/commands/doctor-tools-md-migration*.ts; template literals become ``str.format``
  templates whose fields name the upstream expressions);
- ``memory_core/bootstrap/_bootstrap_constants.py``: the bootstrap budget numbers and the AGENTS.md
  policy-digest keyword sets (src/agents/embedded-agent-helpers/bootstrap.ts,
  src/agents/bootstrap-budget.ts, src/agents/bootstrap-budget-warning.ts);
- ``memory_core/_heartbeat_constants.py``: the heartbeat prompts and tokens, the monitor-scratch
  contract, the heartbeat run-prompt and transcript-filter texts, the automation declaration
  prefixes, the texts of the two doctor migrations (HEARTBEAT.md -> monitor scratch,
  ``tasks:`` -> automation jobs) and the cron store's persist refusal
  (src/cron/store/row-codec.ts); see HEARTBEAT_SOURCES;
- ``memory_core/_memory_flush_constants.py``: the memory-flush hints and default prompts of
  ``buildMemoryFlushPlan`` (extensions/memory-core/src/flush-plan.ts; the prompt arrays are
  joined with ``" "`` and ``${SILENT_REPLY_TOKEN}`` is substituted from src/auto-reply/tokens.ts),
  the flush plan and compaction reserve defaults (src/agents/agent-settings.ts,
  src/agents/agent-compaction-constants.ts), the flush failure limits
  (src/auto-reply/reply/agent-runner-memory.ts), ``SESSION_TOTAL_TOKENS_VERSION``
  (src/config/sessions/types.ts), the byte-size unit table of ``forceFlushTranscriptBytes``
  (src/cli/parse-bytes.ts), and the texts of the flush run the host kit builds: the ``write``
  tool (src/agents/sessions/tools/write.ts), its append-only flush wrapper
  (src/agents/agent-tools.read.ts ``wrapToolMemoryFlushAppendOnlyWrite``), the target-file
  errors (src/auto-reply/reply/memory-flush-session.ts ``ensureMemoryFlushTargetFile``) and the
  ``## Conversation Context`` header (src/agents/system-prompt.ts);
- ``memory_core/_transcript_repair_constants.py``: the synthetic missing-tool-result text and
  marker of the tool-call replay repair
  (packages/agent-core/src/harness/session/tool-result-pairing.ts) and the tool-call name rules
  of its input repair (src/agents/tool-call-shared.ts; the regex literal's source as text);
- ``memory_core/tools/_memory_tool_constants.py``: the ``memory_search``/``memory_get`` tool
  descriptions and source contract, the ``## Memory Recall`` lines of
  ``buildMemoryPromptSection`` (extensions/memory-core/src/memory-tool-contract.ts; ternaries
  inside templates become a template plus its clause literals), the corpus enums and error of
  ``readCorpusParam`` (tools.ts), the per-corpus outcome texts and the deadline
  (memory-corpus.ts, memory/search-deadline.ts), the read texts and limits of
  ``readMemoryFile`` (packages/memory-host-sdk/src/host/read-file*.ts, read-retry.ts) and the
  refusal texts of the built @openclaw/fs-safe it resolves and reads through (see
  MEMORY_TOOL_SOURCES and FS_SAFE_SOURCES)::

    .venv/bin/python scripts/extract_upstream_constants.py --repo /tmp/openclaw-head

``--check`` compares instead of writing and exits 1 on a difference.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.project_name import DISPLAY_NAME, PACKAGE_NAME  # noqa: E402

PACKAGE_DIR = ROOT / PACKAGE_NAME
OUTPUT = PACKAGE_DIR / "bootstrap" / "_tools_md_constants.py"
BOOTSTRAP_OUTPUT = PACKAGE_DIR / "bootstrap" / "_bootstrap_constants.py"
HEARTBEAT_OUTPUT = PACKAGE_DIR / "_heartbeat_constants.py"
FLUSH_OUTPUT = PACKAGE_DIR / "_memory_flush_constants.py"
TRANSCRIPT_REPAIR_OUTPUT = PACKAGE_DIR / "_transcript_repair_constants.py"
MEMORY_TOOLS_OUTPUT = PACKAGE_DIR / "tools" / "_memory_tool_constants.py"
CHECK_TEST = "tests/integration/test_extracted_upstream_constants.py"
BOOTSTRAP_SOURCE = "src/agents/embedded-agent-helpers/bootstrap.ts"
BUDGET_SOURCE = "src/agents/bootstrap-budget.ts"
BUDGET_WARNING_SOURCE = "src/agents/bootstrap-budget-warning.ts"
CONTENT_SOURCE = "src/commands/doctor-tools-md-migration-content.ts"
GUIDANCE_SOURCE = "src/commands/doctor-tools-md-migration-guidance.ts"
MIGRATION_SOURCE = "src/commands/doctor-tools-md-migration.ts"
MIGRATION_BUDGET_SOURCE = "src/commands/doctor-tools-md-migration-budget.ts"
FLUSH_PLAN_SOURCE = "extensions/memory-core/src/flush-plan.ts"
TOKENS_SOURCE = "src/auto-reply/tokens.ts"
AGENT_SETTINGS_SOURCE = "src/agents/agent-settings.ts"
COMPACTION_CONSTANTS_SOURCE = "src/agents/agent-compaction-constants.ts"
RUNNER_MEMORY_SOURCE = "src/auto-reply/reply/agent-runner-memory.ts"
SESSION_TYPES_SOURCE = "src/config/sessions/types.ts"
PARSE_BYTES_SOURCE = "src/cli/parse-bytes.ts"
WRITE_TOOL_SOURCE = "src/agents/sessions/tools/write.ts"
AGENT_TOOLS_READ_SOURCE = "src/agents/agent-tools.read.ts"
FLUSH_SESSION_SOURCE = "src/auto-reply/reply/memory-flush-session.ts"
SYSTEM_PROMPT_SOURCE = "src/agents/system-prompt.ts"
TOOL_RESULT_PAIRING_SOURCE = "packages/agent-core/src/harness/session/tool-result-pairing.ts"
TOOL_CALL_SHARED_SOURCE = "src/agents/tool-call-shared.ts"
# Template-literal expressions of the flush write wrapper -> str.format field names.
FLUSH_WRITE_TEMPLATE_FIELDS = {
    "tool.description": "description",
    "options.relativePath": "relative_path",
}
# Template-literal expressions of the finding texts -> str.format field names.
FINDING_TEMPLATE_FIELDS = {
    "target.primaryAgentId": "agent_id",
    "agentId": "agent_id",
    "errorMessage(error)": "error",
    "params.mergedChars": "merged_chars",
    "bootstrapMaxChars": "bootstrap_max_chars",
    'formatCliCommand("openclaw doctor --fix")': "command",
}

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0", "`": "`"}


def _read_ts_string(source: str, index: int) -> tuple[str, int]:
    """Parse one '...' or "..." literal starting at ``index``; return (value, end index)."""
    quote = source[index]
    out: list[str] = []
    position = index + 1
    while True:
        char = source[position]
        if char == quote:
            return "".join(out), position + 1
        if char == "\\":
            code = source[position + 1]
            if code == "u":
                if source[position + 2] == "{":
                    end = source.index("}", position + 3)
                    out.append(chr(int(source[position + 3 : end], 16)))
                    position = end + 1
                else:
                    out.append(chr(int(source[position + 2 : position + 6], 16)))
                    position += 6
                continue
            if code not in _ESCAPES:
                raise ValueError(f"unsupported escape \\{code} at {position}")
            out.append(_ESCAPES[code])
            position += 2
            continue
        if char == "\n":
            raise ValueError(f"unterminated string literal at {index}")
        out.append(char)
        position += 1


def _skip_space(source: str, index: int) -> int:
    while index < len(source) and source[index] in " \t\r\n":
        index += 1
    return index


def ts_string_expression(source: str, index: int) -> tuple[str, int]:
    """A literal or a ``+`` concatenation of literals starting at ``index``."""
    parts: list[str] = []
    index = _skip_space(source, index)
    while True:
        if source[index] not in "\"'":
            raise ValueError(f"expected a string literal at {index}: {source[index:index + 20]!r}")
        value, index = _read_ts_string(source, index)
        parts.append(value)
        index = _skip_space(source, index)
        if index >= len(source) or source[index] != "+":
            return "".join(parts), index
        index = _skip_space(source, index + 1)


def ts_string_constant(source: str, name: str) -> str:
    """Value of ``const NAME = "..." + '...';``."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    value, _ = ts_string_expression(source, match.end())
    return value


def _expression_end(source: str, index: int) -> int:
    """End index (after the closing brace) of a ``${...}`` expression whose body starts at
    ``index``; string and nested template literals inside it are skipped whole."""
    depth = 1
    end = index
    while depth:
        current = source[end]
        if current in "\"'":
            _, end = _read_ts_string(source, end)
            continue
        if current == "`":
            end = _template_end(source, end)
            continue
        depth += {"{": 1, "}": -1}.get(current, 0)
        end += 1
    return end


def _template_end(source: str, index: int) -> int:
    """End index (after the closing backtick) of the template literal at ``index``."""
    position = index + 1
    while True:
        char = source[position]
        if char == "`":
            return position + 1
        if char == "\\":
            position += 2
            continue
        if char == "$" and source[position + 1] == "{":
            position = _expression_end(source, position + 2)
            continue
        position += 1


def ts_template_literal(
    source: str,
    index: int,
    fields: dict[str, str],
    on_expression: Callable[[str], str] | None = None,
) -> tuple[str, int]:
    """A backtick template literal at ``index`` as a ``str.format`` template.

    Every ``${expression}`` must be a key of ``fields`` and becomes ``{field}``, unless
    ``on_expression`` is given: it then receives each unmapped expression's text and returns
    the template text to put in its place (``{field}`` for a captured ternary). Literal braces
    are doubled. Returns (template, end index).
    """
    index = _skip_space(source, index)
    if source[index] != "`":
        raise ValueError(f"expected a template literal at {index}: {source[index:index + 20]!r}")
    out: list[str] = []
    position = index + 1
    while True:
        char = source[position]
        if char == "`":
            return "".join(out), position + 1
        if char == "\\":
            code = source[position + 1]
            if code not in _ESCAPES and code not in "${":
                raise ValueError(f"unsupported escape \\{code} at {position}")
            value = _ESCAPES.get(code, code)
            out.append(value.replace("{", "{{").replace("}", "}}"))
            position += 2
            continue
        if char == "$" and source[position + 1] == "{":
            end = _expression_end(source, position + 2)
            expression = source[position + 2 : end - 1].strip()
            if expression in fields:
                out.append("{" + fields[expression] + "}")
            elif on_expression is not None:
                out.append(on_expression(expression))
            else:
                raise ValueError(f"unmapped template expression {expression!r} at {position}")
            position = end
            continue
        out.append({"{": "{{", "}": "}}"}.get(char, char))
        position += 1


def _format_escape(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def ts_literal_template(source: str, index: int, fields: dict[str, str]) -> tuple[str, int]:
    """A string literal (or ``+`` concatenation) or a template literal at ``index``, as a
    ``str.format`` template (a plain string's braces are doubled). Returns (template, end)."""
    index = _skip_space(source, index)
    if source[index] == "`":
        return ts_template_literal(source, index, fields)
    value, end = ts_string_expression(source, index)
    return _format_escape(value), end


def _top_level_question_mark(expression: str) -> int:
    depth = 0
    position = 0
    while position < len(expression):
        char = expression[position]
        if char in "\"'":
            _, position = _read_ts_string(expression, position)
            continue
        if char == "`":
            position = _template_end(expression, position)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "?" and depth == 0 and expression[position + 1 : position + 2] not in ("?", "."):
            return position
        position += 1
    raise ValueError(f"not a ternary expression: {expression!r}")


def ts_ternary(expression: str, fields: dict[str, str] | None = None) -> tuple[str, str, str]:
    """(condition, consequent, alternate) of ``cond ? A : B`` whose branches are string or
    template literals; the branches come back as ``str.format`` templates (``fields`` maps the
    expressions of a template branch). Nested ternaries in a branch are refused."""
    question = _top_level_question_mark(expression)
    condition = expression[:question].strip()
    consequent, index = ts_literal_template(expression, question + 1, fields or {})
    index = _skip_space(expression, index)
    if expression[index : index + 1] != ":":
        raise ValueError(f"expected ':' in ternary {expression!r}")
    alternate, index = ts_literal_template(expression, index + 1, fields or {})
    if _skip_space(expression, index) != len(expression):
        raise ValueError(f"unexpected text after the ternary in {expression!r}")
    return condition, consequent, alternate


def ts_template_ternary_at(
    source: str, anchor: str, field: str, fields: dict[str, str] | None = None
) -> tuple[str, str, str, str]:
    """The template literal starting with ``anchor`` whose one unmapped ``${...}`` is a
    ternary: (template with ``{field}``, condition, consequent, alternate).

    Every occurrence of the anchor must give the same parts.
    """
    fields = fields or {}
    found: set[tuple[str, str, str, str]] = set()
    for match in re.finditer(re.escape("`" + anchor), source):
        ternaries: list[tuple[str, str, str]] = []

        def capture(expression: str) -> str:
            ternaries.append(ts_ternary(expression, fields))
            return "{" + field + "}"

        template, _ = ts_template_literal(source, match.start(), fields, capture)
        if len(ternaries) != 1:
            raise ValueError(f"template starting {anchor!r}: {len(ternaries)} ternaries, expected 1")
        found.add((template, *ternaries[0]))
    if len(found) != 1:
        raise ValueError(f"template starting {anchor!r}: {len(found)} distinct values")
    return found.pop()


def ts_ternary_at(source: str, condition: str, fields: dict[str, str] | None = None) -> tuple[str, str]:
    """(consequent, alternate) of the one ternary ``<condition> ? A : B`` in ``source`` whose
    condition text is ``condition`` and whose branches are literals."""
    matches = list(re.finditer(re.escape(condition) + r"\s*\?", source))
    if len(matches) != 1:
        raise ValueError(f"ternary on {condition!r}: {len(matches)} occurrences, expected 1")
    consequent, index = ts_literal_template(source, matches[0].end(), fields or {})
    index = _skip_space(source, index)
    if source[index] != ":":
        raise ValueError(f"expected ':' in the ternary on {condition!r}")
    alternate, _ = ts_literal_template(source, index + 1, fields or {})
    return consequent, alternate


def _property_value_index(source: str, name: str, *, template: bool = False) -> int:
    """Index of the value of the first ``name: `` property (``name: ` `` with ``template``)."""
    match = re.search(rf"\b{re.escape(name)}: " + ("(?=`)" if template else ""), source)
    if match is None:
        raise ValueError(f"property {name} not found")
    return match.end()


def extract_tools_md_findings(migration: str, budget: str) -> dict[str, object]:
    """``collectToolsMdMigrationFindings``: check id, fix hint and (requirement, severity,
    message) per ``migrationFinding`` call, in source order."""
    start = migration.index("export async function collectToolsMdMigrationFindings")
    end = migration.index("export async function maybeMigrateToolsMd", start)
    body = migration[start:end]
    default_severity = re.search(r'severity: params\.severity \?\? "(\w+)"', migration)
    if default_severity is None:
        raise ValueError("migrationFinding default severity not found")
    calls = body.split("migrationFinding({")[1:]
    findings: list[tuple[str, str, str]] = []
    for call in calls:
        requirement = re.search(r'requirement: "([^"]+)"', call)
        severity = re.search(r'severity: "(\w+)"', call)
        if requirement is None:
            raise ValueError("migrationFinding call without a requirement")
        message_at = _skip_space(call, _property_value_index(call, "message"))
        if call.startswith("budget.message", message_at):
            # describeToolsMdMergedBootstrapLimits builds this message.
            message, _ = ts_template_literal(
                budget, _property_value_index(budget, "message", template=True),
                FINDING_TEMPLATE_FIELDS,
            )
        else:
            message, _ = ts_template_literal(call, message_at, FINDING_TEMPLATE_FIELDS)
        findings.append(
            (
                requirement.group(1),
                severity.group(1) if severity else default_severity.group(1),
                message,
            )
        )
    fix_hint, _ = ts_template_literal(
        migration, _property_value_index(migration, "fixHint", template=True),
        FINDING_TEMPLATE_FIELDS,
    )
    return {
        "TOOLS_MD_MIGRATION_CHECK_ID": ts_string_constant(migration, "TOOLS_MD_MIGRATION_CHECK_ID"),
        "TOOLS_MD_MIGRATION_FIX_HINT": fix_hint,
        "TOOLS_MD_MIGRATION_FINDINGS": tuple(findings),
    }


def ts_string_pairs(source: str, name: str) -> tuple[tuple[str, str], ...]:
    """Value of ``const NAME = [[a, b], ...] as const;`` for string pairs."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*\[", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    index = match.end()
    pairs: list[tuple[str, str]] = []
    while True:
        index = _skip_space(source, index)
        if source[index] == "]":
            return tuple(pairs)
        if source[index] != "[":
            raise ValueError(f"expected a pair at {index}")
        first, index = ts_string_expression(source, index + 1)
        index = _skip_space(source, index)
        if source[index] != ",":
            raise ValueError(f"expected ',' at {index}")
        second, index = ts_string_expression(source, index + 1)
        index = _skip_space(source, index)
        if source[index] == ",":
            index = _skip_space(source, index + 1)
        if source[index] != "]":
            raise ValueError(f"expected ']' at {index}")
        pairs.append((first, second))
        index = _skip_space(source, index + 1)
        if source[index] == ",":
            index += 1


def extract(repo: Path) -> dict[str, object]:
    content = (repo / CONTENT_SOURCE).read_text(encoding="utf-8")
    guidance = (repo / GUIDANCE_SOURCE).read_text(encoding="utf-8")
    migration = (repo / MIGRATION_SOURCE).read_text(encoding="utf-8")
    return {
        "LEGACY_TOOLS_MD_TEMPLATE": ts_string_constant(content, "LEGACY_TOOLS_MD_TEMPLATE"),
        "LEGACY_TOOLS_DEV_MD_TEMPLATE": ts_string_constant(content, "LEGACY_TOOLS_DEV_MD_TEMPLATE"),
        "LEGACY_TOOLS_DEV_FALLBACK": ts_string_constant(content, "LEGACY_TOOLS_DEV_FALLBACK"),
        "CURRENT_AGENTS_TOOLS_GUIDANCE": ts_string_constant(
            guidance, "CURRENT_AGENTS_TOOLS_GUIDANCE"
        ),
        "LEGACY_AGENTS_TOOLS_GUIDANCE_REWRITES": ts_string_pairs(
            # The array refers to CURRENT_AGENTS_TOOLS_GUIDANCE by name; inline it first.
            guidance.replace(
                "CURRENT_AGENTS_TOOLS_GUIDANCE,",
                repr_ts(ts_string_constant(guidance, "CURRENT_AGENTS_TOOLS_GUIDANCE")) + ",",
            ),
            "LEGACY_AGENTS_TOOLS_GUIDANCE_REWRITES",
        ),
        "MIGRATED_SUBSECTION_HEADING": ts_string_constant(migration, "MIGRATED_SUBSECTION_HEADING"),
        **extract_tools_md_findings(
            migration, (repo / MIGRATION_BUDGET_SOURCE).read_text(encoding="utf-8")
        ),
    }


def repr_ts(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


_NUMERIC_CONST_RE = re.compile(
    r"^(?:export )?const ([A-Z0-9_]+) = ([0-9_.]+(?: \* [0-9_.]+)*)(?: as const)?;", re.MULTILINE
)
# /\b(?:word|...)\b|(?:unbounded|...)/iu (bootstrap.ts AGENTS_POLICY_DIGEST_*_PATTERN).
_KEYWORD_PATTERN_RE = r"const {name} =\s*/\\b\(\?:([^)]*)\)\\b(?:\|\(\?:([^)]*)\))?/iu;"


def ts_numeric_constants(source: str, names: tuple[str, ...]) -> dict[str, int | float]:
    found: dict[str, int | float] = {}
    for match in _NUMERIC_CONST_RE.finditer(source):
        if match.group(1) not in names:
            continue
        factors = [part.replace("_", "") for part in match.group(2).split(" * ")]
        if all("." not in factor for factor in factors):
            value: int | float = 1
            for factor in factors:
                value *= int(factor)
        else:
            value = 1.0
            for factor in factors:
                value *= float(factor)
        found[match.group(1)] = value
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError(f"numeric constants not found: {missing}")
    return {name: found[name] for name in names}


def ts_keyword_pattern(source: str, name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(word-bounded alternatives, unbounded alternatives) of a policy keyword regex."""
    match = re.search(_KEYWORD_PATTERN_RE.format(name=re.escape(name)), source)
    if match is None:
        raise ValueError(f"keyword pattern {name} not found")

    def split(group: str | None) -> tuple[str, ...]:
        if not group:
            return ()
        return tuple(item.replace("\\.", ".") for item in group.split("|"))

    return split(match.group(1)), split(match.group(2))


BOOTSTRAP_NUMERIC = {
    BOOTSTRAP_SOURCE: (
        "DEFAULT_BOOTSTRAP_MAX_CHARS",
        "DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS",
        "USER_BOOTSTRAP_MAX_CHARS",
        "MIN_BOOTSTRAP_FILE_BUDGET_CHARS",
        "BOOTSTRAP_HEAD_RATIO",
        "BOOTSTRAP_TAIL_RATIO",
        "MIN_BOOTSTRAP_TRIMMED_CONTENT_CHARS",
        "AGENTS_POLICY_DIGEST_RATIO",
        "AGENTS_POLICY_HEAD_RATIO",
        "AGENTS_POLICY_TAIL_RATIO",
        "AGENTS_POLICY_DIGEST_MAX_LINE_CHARS",
    ),
    BUDGET_SOURCE: ("DEFAULT_BOOTSTRAP_NEAR_LIMIT_RATIO",),
    BUDGET_WARNING_SOURCE: (
        "DEFAULT_BOOTSTRAP_PROMPT_WARNING_MAX_FILES",
        "DEFAULT_BOOTSTRAP_PROMPT_WARNING_SIGNATURE_HISTORY_MAX",
    ),
}


def extract_bootstrap(repo: Path) -> dict[str, object]:
    constants: dict[str, object] = {}
    for relative, names in BOOTSTRAP_NUMERIC.items():
        constants.update(ts_numeric_constants((repo / relative).read_text(encoding="utf-8"), names))
    bootstrap = (repo / BOOTSTRAP_SOURCE).read_text(encoding="utf-8")
    policy, policy_unbounded = ts_keyword_pattern(bootstrap, "AGENTS_POLICY_DIGEST_CANDIDATE_PATTERN")
    high, high_unbounded = ts_keyword_pattern(bootstrap, "AGENTS_POLICY_DIGEST_HIGH_PRIORITY_PATTERN")
    constants.update(
        {
            "POLICY_DIGEST_KEYWORDS": policy,
            "POLICY_DIGEST_UNBOUNDED_KEYWORDS": policy_unbounded,
            "POLICY_DIGEST_HIGH_PRIORITY_KEYWORDS": high,
            "POLICY_DIGEST_HIGH_PRIORITY_UNBOUNDED_KEYWORDS": high_unbounded,
        }
    )
    return constants


HEARTBEAT_SOURCES = {
    "tokens": "src/auto-reply/tokens.ts",
    "heartbeat": "src/auto-reply/heartbeat.ts",
    "filter": "src/auto-reply/heartbeat-filter.ts",
    "tool": "src/auto-reply/heartbeat-tool-response.ts",
    "scratch": "src/cron/scratch-contract.ts",
    "prompt": "src/infra/heartbeat-runner-prompt.ts",
    "wake": "src/infra/heartbeat-wake.ts",
    "declaration": "src/cron/system-owned-declaration.ts",
    "monitor": "src/cron/heartbeat-monitor.ts",
    "placeholder": "packages/ai/src/replay-turn-classification.ts",
    "task_migration": "src/commands/doctor-heartbeat-task-migration.ts",
    "scratch_migration": "src/commands/doctor-heartbeat-scratch-migration.ts",
    "cron_rows": "src/cron/store/row-codec.ts",
}
# Template-literal expressions of the heartbeat texts -> str.format field names.
HEARTBEAT_TEMPLATE_FIELDS = {
    "agent.agentId": "agent_id",
    "agentId": "agent_id",
    "commit.agentId": "agent_id",
    "errorMessage(error)": "error",
    "document.tasks.length": "count",
    'document.tasks.length === 1 ? "" : "s"': "plural",
    "JSON.stringify(task.name)": "name_json",
    'formatCliCommand("openclaw doctor --fix")': "command",
    "params.task.name": "name",
    "shortenHomePath(source.path)": "path",
    "monitor.displayName ?? monitor.name": "monitor",
    'retainSource ? "a heartbeat owner is disabled" : "another heartbeat owner\'s scratch was '
    'left unchanged"': "reason",
    "heartbeatPath": "path",
    "orphanClaim": "claim",
    "staleClaim": "claim",
    "ownerPid": "pid",
    "conflictPath": "conflict_path",
    "claimPath": "claim",
    "archivePath": "archive",
    "CRON_JOB_SCRATCH_MAX_BYTES": "max_bytes",
    "sizeBytes": "size_bytes",
    "prompt": "prompt",
    "directives": "directives",
    "task.name": "name",
    "task.prompt": "prompt",
    "taskList": "task_list",
    "completionInstruction": "completion",
    "token": "token",
    "invalidJobs": "invalid_jobs",
}
# (python name, source key, raw TypeScript text the literal starts with). Templates become
# str.format templates; "string" entries are plain '...' / "..." literals.
HEARTBEAT_TEMPLATES = (
    ("CRON_JOB_SCRATCH_TOO_LARGE", "scratch", "cron scratch exceeds ${"),
    ("HEARTBEAT_SCRATCH_PROMPT", "prompt", "${prompt}\\n\\nHeartbeat monitor scratch:"),
    ("HEARTBEAT_TASK_LINE", "prompt", "- ${task.name}: ${task.prompt}"),
    ("HEARTBEAT_TASKS_PROMPT", "prompt", "Run the following periodic tasks"),
    ("HEARTBEAT_FILTER_TASK_REPLY_COMPLETION", "filter", "After completing all due tasks, reply ${token}"),
    ("HEARTBEAT_MONITOR_DISPLAY_NAME", "monitor", "Heartbeat (${agent.agentId})"),
    ("HEARTBEAT_TASK_MIGRATION_FIX_HINT", "task_migration", "Run ${formatCliCommand"),
    ("HEARTBEAT_TASK_INTERVAL_ERROR", "task_migration", "task ${JSON.stringify(task.name)} interval"),
    ("HEARTBEAT_TASK_FINDING_UNREADABLE", "task_migration", 'Agent "${agent.agentId}" heartbeat scratch cannot be inspected'),
    ("HEARTBEAT_TASK_FINDING_IN_SCRATCH", "task_migration", 'Agent "${agent.agentId}" has ${document.tasks.length}'),
    ("HEARTBEAT_TASK_FINDING_BLOCKED", "task_migration", 'Agent "${agent.agentId}" heartbeat tasks cannot be migrated'),
    ("HEARTBEAT_TASK_WARNING_UNREADABLE", "task_migration", 'Agent "${agent.agentId}" heartbeat scratch could not be inspected'),
    ("HEARTBEAT_TASK_WARNING_INVALID", "task_migration", 'Agent "${agent.agentId}" heartbeat tasks were not migrated'),
    ("HEARTBEAT_TASK_WARNING_COLLISION", "task_migration", 'Agent "${agent.agentId}" task ${JSON.stringify(task.name)} collides'),
    ("HEARTBEAT_TASK_WARNING_COMMIT_FAILED", "task_migration", 'Agent "${agent.agentId}" task migration could not be committed'),
    ("HEARTBEAT_TASK_WARNING_SCRATCH_CHANGED", "task_migration", 'Agent "${agent.agentId}" scratch changed during task migration'),
    ("HEARTBEAT_TASK_WARNING_JOBS_CHANGED", "task_migration", 'Agent "${agent.agentId}" cron jobs changed during task migration'),
    ("HEARTBEAT_TASK_WARNING_TIMESTAMPS", "task_migration", 'Agent "${agent.agentId}" legacy task timestamps'),
    ("HEARTBEAT_TASK_WARNING_NOT_PLANNED", "task_migration", 'Agent "${agent.agentId}" task jobs could not be planned'),
    ("CRON_STORE_CANNOT_PERSIST", "cron_rows", "Cannot persist cron store with ${invalidJobs}"),
    ("HEARTBEAT_TASK_CHANGE", "task_migration", "Converted ${document.tasks.length}"),
    ("HEARTBEAT_TASK_DISPLAY_NAME", "task_migration", "Heartbeat task: ${params.task.name}"),
    ("HEARTBEAT_SCRATCH_MIGRATION_FIX_HINT", "scratch_migration", "Run ${formatCliCommand"),
    ("HEARTBEAT_SCRATCH_FINDING_LEGACY", "scratch_migration", 'Agent "${agent.agentId}" still stores heartbeat instructions'),
    ("HEARTBEAT_SCRATCH_FINDING_BLOCKED", "scratch_migration", 'Agent "${agent.agentId}" HEARTBEAT.md cannot be migrated'),
    ("HEARTBEAT_SCRATCH_ERROR_ORPHAN_CLAIM", "scratch_migration", "both ${heartbeatPath} and an interrupted migration claim"),
    ("HEARTBEAT_SCRATCH_ERROR_STALE_CLAIM", "scratch_migration", "an interrupted migration claim exists at ${staleClaim}"),
    ("HEARTBEAT_SCRATCH_ERROR_MULTIPLE_CLAIMS", "scratch_migration", "multiple interrupted migration claims exist for"),
    ("HEARTBEAT_SCRATCH_ERROR_CLAIM_HELD", "scratch_migration", "a migration claim for ${heartbeatPath} is held"),
    ("HEARTBEAT_SCRATCH_ERROR_RECREATED", "scratch_migration", "HEARTBEAT.md was recreated during migration"),
    ("HEARTBEAT_SCRATCH_ERROR_RESTORE_FAILED", "scratch_migration", "HEARTBEAT.md migration claim could not be restored"),
    ("HEARTBEAT_SCRATCH_ERROR_ARCHIVE_COLLISION", "scratch_migration", "heartbeat migration archive collision at"),
    ("HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED", "scratch_migration", "${shortenHomePath(source.path)} was not migrated"),
    ("HEARTBEAT_SCRATCH_WARNING_NOT_REMOVED", "scratch_migration", "${shortenHomePath(source.path)} was migrated but not removed"),
    ("HEARTBEAT_SCRATCH_WARNING_UNREADABLE", "scratch_migration", 'Agent "${agentId}" HEARTBEAT.md was not migrated'),
    ("HEARTBEAT_SCRATCH_WARNING_UNSET", "scratch_migration", 'Agent "${agentId}" scratch was explicitly unset'),
    ("HEARTBEAT_SCRATCH_WARNING_DIFFERENT", "scratch_migration", 'Agent "${agentId}" already has different cron scratch'),
    ("HEARTBEAT_SCRATCH_WARNING_NOT_FINALIZED", "scratch_migration", 'Agent "${agentId}" scratch was not finalized'),
    ("HEARTBEAT_SCRATCH_WARNING_ROLLBACK", "scratch_migration", 'Agent "${commit.agentId}" scratch changed before the migration rollback'),
    ("HEARTBEAT_SCRATCH_CHANGE_MIGRATED", "scratch_migration", "Migrated ${shortenHomePath(source.path)}"),
    ("HEARTBEAT_SCRATCH_CHANGE_COPIED", "scratch_migration", "Copied ${shortenHomePath(source.path)}"),
)
HEARTBEAT_STRINGS = (
    ("HEARTBEAT_SKIP_EMPTY_SCRATCH", "prompt", "empty-heartbeat-file"),
    ("HEARTBEAT_TASK_ERROR_NO_TASKS", "task_migration", "tasks: block has no complete"),
    ("HEARTBEAT_TASK_ERROR_INCOMPLETE", "task_migration", "tasks: block contains an incomplete"),
    ("HEARTBEAT_TASK_DESCRIPTION", "task_migration", "Migrated from heartbeat monitor scratch"),
    ("HEARTBEAT_SCRATCH_ERROR_NOT_FILE", "scratch_migration", "HEARTBEAT.md must be a regular file"),
    ("HEARTBEAT_SCRATCH_ERROR_HARDLINK", "scratch_migration", "HEARTBEAT.md has multiple hard links"),
    ("HEARTBEAT_SCRATCH_ERROR_ESCAPES", "scratch_migration", "HEARTBEAT.md symlink target escapes"),
    ("HEARTBEAT_SCRATCH_ERROR_NOT_UTF8", "scratch_migration", "HEARTBEAT.md is not valid UTF-8"),
    ("HEARTBEAT_SCRATCH_ERROR_WORKSPACE_CHANGED", "scratch_migration", "HEARTBEAT.md workspace changed after"),
    ("HEARTBEAT_SCRATCH_ERROR_CLAIM_ESCAPES", "scratch_migration", "claimed HEARTBEAT.md target escapes"),
    ("HEARTBEAT_SCRATCH_ERROR_CHANGED_BEFORE_CLAIM", "scratch_migration", "HEARTBEAT.md changed before the migration claim"),
    ("HEARTBEAT_SCRATCH_ERROR_REVERIFY", "scratch_migration", "claimed HEARTBEAT.md could not be re-verified"),
    ("HEARTBEAT_SCRATCH_ERROR_CHANGED_WHILE_HELD", "scratch_migration", "HEARTBEAT.md changed while the migration claim"),
    ("HEARTBEAT_SCRATCH_ERROR_ORIGINAL_UNVERIFIED", "scratch_migration", "could not verify the original HEARTBEAT.md"),
    ("HEARTBEAT_SCRATCH_ERROR_RECREATED_WHILE_HELD", "scratch_migration", "HEARTBEAT.md was recreated while"),
    ("HEARTBEAT_SCRATCH_ERROR_RESTORED_UNVERIFIED", "scratch_migration", "restored HEARTBEAT.md could not be re-verified"),
    ("HEARTBEAT_SCRATCH_ERROR_CHANGED_AFTER_RESTORE", "scratch_migration", "HEARTBEAT.md changed after the migration claim"),
    ("HEARTBEAT_SCRATCH_ERROR_TARGET_ESCAPES", "scratch_migration", "HEARTBEAT.md target escapes"),
    ("HEARTBEAT_SCRATCH_ERROR_SCRATCH_CHANGED", "scratch_migration", "scratch changed during migration"),
    ("HEARTBEAT_SCRATCH_ERROR_VERIFY_FAILED", "scratch_migration", "scratch verification failed after write"),
    ("HEARTBEAT_SCRATCH_REASON_OWNER_DISABLED", "scratch_migration", "a heartbeat owner is disabled"),
    ("HEARTBEAT_SCRATCH_REASON_OWNER_SKIPPED", "scratch_migration", "another heartbeat owner's scratch"),
)


def ts_template_at(source: str, anchor: str, fields: dict[str, str]) -> str:
    """The template literal whose raw text starts with ``anchor``, as a ``str.format`` template.

    Every occurrence must give the same template (upstream repeats some warnings verbatim).
    """
    needle = "`" + anchor
    templates = {
        ts_template_literal(source, match.start(), fields)[0]
        for match in re.finditer(re.escape(needle), source)
    }
    if len(templates) != 1:
        raise ValueError(f"template starting {anchor!r}: {len(templates)} distinct values")
    return templates.pop()


def ts_string_at(source: str, anchor: str) -> str:
    """The '...' or "..." literal whose text starts with ``anchor``."""
    values = set()
    for quote in "\"'":
        for match in re.finditer(re.escape(quote + anchor), source):
            values.add(_read_ts_string(source, match.start())[0])
    if len(values) != 1:
        raise ValueError(f"string starting {anchor!r}: {len(values)} distinct values")
    return values.pop()


def ts_template_constant(source: str, name: str, values: dict[str, str]) -> str:
    """Value of ``const NAME = `...${OTHER}...`;`` with the named constants filled in."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    template, _ = ts_template_literal(source, match.end(), {key: key for key in values})
    return template.format(**values)


def ts_string_object(source: str, name: str) -> tuple[tuple[str, str], ...]:
    """(key, value) pairs of ``const NAME = { key: "...", ... } as const;`` (comments skipped)."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*\{{", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    index = match.end()
    pairs: list[tuple[str, str]] = []
    while True:
        index = _skip_space(source, index)
        if source.startswith("//", index):
            index = source.index("\n", index) + 1
            continue
        if source[index] == "}":
            return tuple(pairs)
        key = re.match(r"[A-Za-z_$][\w$]*", source[index:])
        if key is None:
            raise ValueError(f"expected a key at {index}")
        index = _skip_space(source, index + key.end())
        if source[index] != ":":
            raise ValueError(f"expected ':' at {index}")
        value, index = ts_string_expression(source, index + 1)
        pairs.append((key.group(0), value))
        index = _skip_space(source, index)
        if source[index] == ",":
            index += 1


def extract_heartbeat(repo: Path) -> dict[str, object]:
    src = {key: (repo / path).read_text(encoding="utf-8") for key, path in HEARTBEAT_SOURCES.items()}
    tokens = {
        name: ts_string_constant(src["tokens"], name)
        for name in ("HEARTBEAT_TOKEN", "SILENT_REPLY_TOKEN")
    }
    heartbeat = src["heartbeat"]
    guidance = ts_string_constant(heartbeat, "HEARTBEAT_CRON_TASK_GUIDANCE")
    context = ts_template_constant(
        heartbeat, "HEARTBEAT_CONTEXT_PROMPT", {"HEARTBEAT_CRON_TASK_GUIDANCE": guidance}
    )
    instructions = ts_string_constant(heartbeat, "HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS")
    fallback = ts_template_constant(
        heartbeat, "HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS", tokens
    )
    tool_name = ts_string_constant(src["tool"], "HEARTBEAT_RESPONSE_TOOL_NAME")
    constants: dict[str, object] = {
        **tokens,
        "HEARTBEAT_CRON_TASK_GUIDANCE": guidance,
        "HEARTBEAT_CONTEXT_PROMPT": context,
        "HEARTBEAT_PROMPT": ts_template_constant(
            heartbeat, "HEARTBEAT_PROMPT", {"HEARTBEAT_CONTEXT_PROMPT": context, **tokens}
        ),
        "HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS": instructions,
        "HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS": fallback,
        "HEARTBEAT_RESPONSE_TOOL_PROMPT": ts_template_constant(
            heartbeat,
            "HEARTBEAT_RESPONSE_TOOL_PROMPT",
            {
                "HEARTBEAT_CONTEXT_PROMPT": context,
                "HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS": instructions,
                "HEARTBEAT_RESPONSE_TOOL_FALLBACK_INSTRUCTIONS": fallback,
            },
        ),
        "HEARTBEAT_RESPONSE_TOOL_NAME": tool_name,
        "INTERNAL_WAKE_TRANSCRIPT_PROMPTS": ts_string_object(
            heartbeat, "INTERNAL_WAKE_TRANSCRIPT_PROMPTS"
        ),
        "DEFAULT_HEARTBEAT_EVERY": ts_string_constant(heartbeat, "DEFAULT_HEARTBEAT_EVERY"),
        **ts_numeric_constants(heartbeat, ("DEFAULT_HEARTBEAT_ACK_MAX_CHARS",)),
        **ts_numeric_constants(src["scratch"], ("CRON_JOB_SCRATCH_MAX_BYTES",)),
        "HEARTBEAT_SKIP_NO_PENDING_EVENT": ts_string_constant(
            src["wake"], "HEARTBEAT_SKIP_NO_PENDING_EVENT"
        ),
        "HEARTBEAT_TASK_PROMPT_PREFIX": ts_string_constant(
            src["filter"], "HEARTBEAT_TASK_PROMPT_PREFIX"
        ),
        "HEARTBEAT_TASKS_COMPLETION": ts_template_at(
            src["prompt"], "After completing all due tasks, reply ${", {"SILENT_REPLY_TOKEN": "t"}
        ).format(t=tokens["SILENT_REPLY_TOKEN"]),
        "HEARTBEAT_TASKS_RESPONSE_TOOL_COMPLETION": ts_template_at(
            src["prompt"],
            "After completing all due tasks:",
            {"HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS": "i"},
        ).format(i=instructions),
        "HEARTBEAT_FILTER_TASK_TOOL_COMPLETION": ts_template_at(
            src["filter"],
            "After completing all due tasks, use ${",
            {"HEARTBEAT_RESPONSE_TOOL_NAME": "n"},
        ).format(n=tool_name),
        "HEARTBEAT_TASK_DECLARATION_PREFIX": ts_string_constant(
            src["declaration"], "HEARTBEAT_TASK_DECLARATION_PREFIX"
        ),
        "HEARTBEAT_DECLARATION_PREFIX": ts_string_constant(
            src["declaration"], "HEARTBEAT_DECLARATION_PREFIX"
        ),
        "STREAM_ERROR_FALLBACK_TEXT": ts_string_constant(
            src["placeholder"], "STREAM_ERROR_FALLBACK_TEXT"
        ),
        "HEARTBEAT_TASK_MIGRATION_CHECK_ID": ts_string_constant(
            src["task_migration"], "HEARTBEAT_TASK_MIGRATION_CHECK_ID"
        ),
        "HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID": ts_string_constant(
            src["scratch_migration"], "HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID"
        ),
        "LEGACY_HEARTBEAT_FILENAME": ts_string_constant(
            src["scratch_migration"], "LEGACY_HEARTBEAT_FILENAME"
        ),
        "HEARTBEAT_CLAIM_INFIX": ts_string_constant(
            src["scratch_migration"], "HEARTBEAT_CLAIM_INFIX"
        ),
    }
    # heartbeat-filter.ts: [HEARTBEAT_TOKEN, SILENT_REPLY_TOKEN].map(...) builds the first two
    # completions, in this order.
    if "...[HEARTBEAT_TOKEN, SILENT_REPLY_TOKEN].map(" not in src["filter"]:
        raise ValueError("heartbeat-filter.ts completion token list changed")
    for name, key, anchor in HEARTBEAT_TEMPLATES:
        constants[name] = ts_template_at(src[key], anchor, HEARTBEAT_TEMPLATE_FIELDS)
    for name, key, anchor in HEARTBEAT_STRINGS:
        constants[name] = ts_string_at(src[key], anchor)
    return constants


def ts_identifier_array(source: str, name: str, values: dict[str, str]) -> tuple[str, ...]:
    """Value of ``const NAME = [A, B, ...];`` whose items are known string constants."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*\[([^\]]*)\];", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    items = [item.strip() for item in match.group(1).split(",") if item.strip()]
    unknown = [item for item in items if item not in values]
    if unknown:
        raise ValueError(f"{name}: unknown identifiers {unknown}")
    return tuple(values[item] for item in items)


def ts_joined_string_array(
    source: str, name: str, values: dict[str, str], fields: dict[str, str]
) -> str:
    """Value of ``const NAME = [item, ...].join(" ");``.

    An item is a string literal, a known string constant or a template literal whose
    ``${expression}`` parts are keys of ``fields`` (their values are substituted).
    """
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*\[", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    index = match.end()
    parts: list[str] = []
    while True:
        index = _skip_space(source, index)
        char = source[index]
        if char == "]":
            break
        if char in "\"'":
            value, index = ts_string_expression(source, index)
        elif char == "`":
            template, index = ts_template_literal(source, index, {key: key for key in fields})
            value = template.format(**fields)
        else:
            identifier = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[index:])
            if identifier is None or identifier.group(0) not in values:
                raise ValueError(f"{name}: unexpected item at {index}: {source[index:index + 30]!r}")
            value = values[identifier.group(0)]
            index += len(identifier.group(0))
        parts.append(value)
        index = _skip_space(source, index)
        if source[index] == ",":
            index += 1
    tail = source[index + 1 :]
    if not tail.startswith('.join(" ")'):
        raise ValueError(f"{name}: expected .join(\" \") after the array")
    return " ".join(parts)


def ts_numeric_record(source: str, name: str) -> dict[str, int]:
    """Value of ``const NAME: Record<string, number> = { key: 1, key: 1024 ** 2, ... };``."""
    match = re.search(rf"\bconst {re.escape(name)}(?::[^=]+)?=\s*\{{([^}}]*)\}};", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    record: dict[str, int] = {}
    for item in (part.strip() for part in match.group(1).split(",")):
        if not item:
            continue
        entry = re.fullmatch(r"([a-z]+):\s*([0-9]+)(?:\s*\*\*\s*([0-9]+))?", item)
        if entry is None:
            raise ValueError(f"{name}: unexpected entry {item!r}")
        record[entry.group(1)] = int(entry.group(2)) ** int(entry.group(3) or 1)
    return record


FLUSH_HINTS = ("MEMORY_FLUSH_TARGET_HINT", "MEMORY_FLUSH_APPEND_ONLY_HINT", "MEMORY_FLUSH_READ_ONLY_HINT")


def extract_memory_flush(repo: Path) -> dict[str, object]:
    flush_plan = (repo / FLUSH_PLAN_SOURCE).read_text(encoding="utf-8")
    silent = ts_string_constant((repo / TOKENS_SOURCE).read_text(encoding="utf-8"), "SILENT_REPLY_TOKEN")
    hints = {name: ts_string_constant(flush_plan, name) for name in FLUSH_HINTS}
    fields = {"SILENT_REPLY_TOKEN": silent}
    no_reply_at = flush_plan.index("function ensureNoReplyHint(")
    no_reply_hint, _ = ts_template_literal(
        flush_plan,
        flush_plan.index("return `", no_reply_at) + len("return "),
        {"text": "text", "SILENT_REPLY_TOKEN": "silent_reply_token"},
    )
    return {
        "SILENT_REPLY_TOKEN": silent,
        **ts_numeric_constants(
            flush_plan,
            ("DEFAULT_MEMORY_FLUSH_SOFT_TOKENS", "DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES"),
        ),
        **ts_numeric_constants(
            (repo / AGENT_SETTINGS_SOURCE).read_text(encoding="utf-8"),
            ("DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR",),
        ),
        **ts_numeric_constants(
            (repo / COMPACTION_CONSTANTS_SOURCE).read_text(encoding="utf-8"),
            ("MAX_COMPACTION_RESERVE_RATIO",),
        ),
        **ts_numeric_constants(
            (repo / RUNNER_MEMORY_SOURCE).read_text(encoding="utf-8"),
            ("MAX_FLUSH_FAILURES", "MAX_FLUSH_ERROR_LENGTH"),
        ),
        **ts_numeric_constants(
            (repo / SESSION_TYPES_SOURCE).read_text(encoding="utf-8"),
            ("SESSION_TOTAL_TOKENS_VERSION",),
        ),
        **hints,
        "MEMORY_FLUSH_REQUIRED_HINTS": ts_identifier_array(
            flush_plan, "MEMORY_FLUSH_REQUIRED_HINTS", hints
        ),
        "DEFAULT_MEMORY_FLUSH_PROMPT": ts_joined_string_array(
            flush_plan, "DEFAULT_MEMORY_FLUSH_PROMPT", hints, fields
        ),
        "DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT": ts_joined_string_array(
            flush_plan, "DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT", hints, fields
        ),
        "MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE": no_reply_hint,
        "UNIT_MULTIPLIERS": ts_numeric_record(
            (repo / PARSE_BYTES_SOURCE).read_text(encoding="utf-8"), "UNIT_MULTIPLIERS"
        ),
        **extract_flush_run(repo),
    }


def extract_flush_run(repo: Path) -> dict[str, str]:
    """Texts of the flush run: the write tool, its flush wrapper, target errors, context header."""
    write = (repo / WRITE_TOOL_SOURCE).read_text(encoding="utf-8")
    wrapper = (repo / AGENT_TOOLS_READ_SOURCE).read_text(encoding="utf-8")
    session = (repo / FLUSH_SESSION_SOURCE).read_text(encoding="utf-8")
    system_prompt = (repo / SYSTEM_PROMPT_SOURCE).read_text(encoding="utf-8")
    return {
        "WRITE_TOOL_DESCRIPTION": ts_string_at(write, "Write/overwrite file"),
        "WRITE_TOOL_PATH_DESCRIPTION": ts_string_at(write, "File path;"),
        "WRITE_TOOL_CONTENT_DESCRIPTION": ts_string_at(write, "File content."),
        "MEMORY_FLUSH_WRITE_DESCRIPTION_TEMPLATE": ts_template_at(
            wrapper, "${tool.description} During memory flush", FLUSH_WRITE_TEMPLATE_FIELDS
        ),
        "MEMORY_FLUSH_WRITE_RESTRICTED_TEMPLATE": ts_template_at(
            wrapper, "Memory flush writes are restricted to", FLUSH_WRITE_TEMPLATE_FIELDS
        ),
        "MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE": ts_template_at(
            wrapper, "Appended content to", FLUSH_WRITE_TEMPLATE_FIELDS
        ),
        "MEMORY_FLUSH_INVALID_TARGET_ERROR": ts_string_at(
            session, "Invalid memory flush target path"
        ),
        "MEMORY_FLUSH_TARGET_OUTSIDE_ERROR": ts_string_at(
            session, "Memory flush target path must stay inside"
        ),
        "CONVERSATION_CONTEXT_HEADER": ts_string_at(system_prompt, "## Conversation Context"),
    }


def ts_regex_constant(source: str, name: str) -> str:
    """Pattern text of ``const NAME = /.../;``, a regex literal without flags."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*/", source)
    if match is None:
        raise ValueError(f"regex constant {name} not found")
    index, in_class, out = match.end(), False, []
    while True:
        char = source[index]
        if char == "\\":
            out.append(source[index : index + 2])
            index += 2
            continue
        if char == "\n":
            raise ValueError(f"unterminated regex literal {name}")
        if char == "/" and not in_class:
            break
        in_class = (in_class or char == "[") and char != "]"
        out.append(char)
        index += 1
    flags = re.match(r"[a-z]*", source[index + 1 :]).group()
    if flags:
        raise ValueError(f"regex constant {name} has flags {flags!r}")
    return "".join(out)


def extract_transcript_repair(repo: Path) -> dict[str, object]:
    """The texts and name rules of the tool-call replay repair (memory_core.replay_repair)."""
    pairing = (repo / TOOL_RESULT_PAIRING_SOURCE).read_text(encoding="utf-8")
    shared = (repo / TOOL_CALL_SHARED_SOURCE).read_text(encoding="utf-8")
    return {
        **{
            name: ts_string_constant(pairing, name)
            for name in (
                "SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY",
                "DEFAULT_MISSING_TOOL_RESULT_TEXT",
            )
        },
        **ts_numeric_constants(shared, ("TOOL_CALL_NAME_MAX_CHARS",)),
        "TOOL_CALL_NAME_RE": ts_regex_constant(shared, "TOOL_CALL_NAME_RE"),
    }


MEMORY_TOOL_SOURCES = {
    "contract": "extensions/memory-core/src/memory-tool-contract.ts",
    "tools": "extensions/memory-core/src/tools.ts",
    "read_tool": "extensions/memory-core/src/memory-read-tool.ts",
    "corpus": "extensions/memory-core/src/memory-corpus.ts",
    "deadline": "extensions/memory-core/src/memory/search-deadline.ts",
    "read_file": "packages/memory-host-sdk/src/host/read-file.ts",
    "read_shared": "packages/memory-host-sdk/src/host/read-file-shared.ts",
    "read_retry": "packages/memory-host-sdk/src/host/read-retry.ts",
    "fs_utils": "packages/memory-host-sdk/src/host/fs-utils.ts",
}
# @openclaw/fs-safe (the workspace resolve and regular-file read of readMemoryFile) ships as
# built JavaScript in the checkout's node_modules; its version is checked.
FS_SAFE_DIR = "node_modules/@openclaw/fs-safe"
FS_SAFE_VERSION = "0.18.1"
FS_SAFE_SOURCES = {
    "fs_root_context": f"{FS_SAFE_DIR}/dist/root-context.js",
    "fs_root_path": f"{FS_SAFE_DIR}/dist/root-path.js",
    "fs_root_path_errors": f"{FS_SAFE_DIR}/dist/root-path-errors.js",
    "fs_root_path_existing": f"{FS_SAFE_DIR}/dist/root-path-existing.js",
    "fs_path": f"{FS_SAFE_DIR}/dist/path.js",
    "fs_error_detail": f"{FS_SAFE_DIR}/dist/error-detail.js",
    "fs_regular_file": f"{FS_SAFE_DIR}/dist/regular-file.js",
    "fs_identity": f"{FS_SAFE_DIR}/dist/strict-file-identity.js",
}


def ts_string_array_at(source: str, anchor: str) -> tuple[str, ...]:
    """The ``[...]`` array of string literals right after the one occurrence of ``anchor``."""
    matches = list(re.finditer(re.escape(anchor) + r"\s*\[", source))
    if len(matches) != 1:
        raise ValueError(f"array after {anchor!r}: {len(matches)} occurrences, expected 1")
    index = matches[0].end()
    items: list[str] = []
    while True:
        index = _skip_space(source, index)
        if source[index] == "]":
            return tuple(items)
        value, index = ts_string_expression(source, index)
        items.append(value)
        index = _skip_space(source, index)
        if source[index] == ",":
            index += 1


def ts_regex_literal_at(source: str, name: str) -> tuple[str, str]:
    """(pattern source, flags) of ``const NAME = /.../flags;``."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=\s*/", source)
    if match is None:
        raise ValueError(f"regex constant {name} not found")
    index, in_class, out = match.end(), False, []
    while True:
        char = source[index]
        if char == "\\":
            out.append(source[index : index + 2])
            index += 2
            continue
        if char == "\n":
            raise ValueError(f"unterminated regex literal {name}")
        if char == "/" and not in_class:
            break
        in_class = (in_class or char == "[") and char != "]"
        out.append(char)
        index += 1
    flags = re.match(r"[a-z]*", source[index + 1 :]).group()
    return "".join(out), flags


def ts_signed_integer_constant(source: str, name: str) -> int:
    match = re.search(rf"^(?:export )?const {re.escape(name)} = (-?[0-9_]+);", source, re.MULTILINE)
    if match is None:
        raise ValueError(f"integer constant {name} not found")
    return int(match.group(1).replace("_", ""))


def ts_number_after(source: str, anchor: str) -> int:
    """The integer literal right after the one occurrence of ``anchor``."""
    matches = list(re.finditer(re.escape(anchor) + r"\s*([0-9_]+)", source))
    if len(matches) != 1:
        raise ValueError(f"number after {anchor!r}: {len(matches)} occurrences, expected 1")
    return int(matches[0].group(1).replace("_", ""))


def _read_sources(repo: Path, sources: dict[str, str]) -> dict[str, str]:
    return {key: (repo / path).read_text(encoding="utf-8") for key, path in sources.items()}


def extract_memory_tools(repo: Path) -> dict[str, object]:
    """Texts and limits of memory_search/memory_get, their prompt section and the read path."""
    src = _read_sources(repo, MEMORY_TOOL_SOURCES)
    fs = _read_sources(repo, FS_SAFE_SOURCES)
    fs_version = re.search(
        r'"version":\s*"([^"]+)"', (repo / FS_SAFE_DIR / "package.json").read_text(encoding="utf-8")
    )
    if fs_version is None or fs_version.group(1) != FS_SAFE_VERSION:
        raise ValueError(f"@openclaw/fs-safe is not {FS_SAFE_VERSION}: {fs_version}")
    contract = src["contract"]
    search_guidance = ts_string_constant(contract, "SEARCH_CORPUS_OUTCOME_GUIDANCE")
    get_guidance = ts_string_constant(contract, "GET_READ_OUTCOME_GUIDANCE")
    guidance_fields = {
        "SEARCH_CORPUS_OUTCOME_GUIDANCE": "search_guidance",
        "GET_READ_OUTCOME_GUIDANCE": "get_guidance",
    }
    guidance_values = {
        "search_guidance": _format_escape(search_guidance),
        "get_guidance": _format_escape(get_guidance),
    }
    search_description = ts_template_at(
        contract, "Mandatory recall step", {"search": "search", **guidance_fields}
    ).format(search="{search}", **guidance_values)
    get_description = ts_template_at(
        contract, "Safe exact excerpt read from ${", {"files": "files", **guidance_fields}
    ).format(files="{files}", **guidance_values)
    recall_search, recall_search_condition, recall_get_clause, recall_no_get = (
        ts_template_ternary_at(contract, "Before answering anything", "memory_get_clause")
    )
    sessions_search, sessions_condition, sessions_history_clause, sessions_no_history_clause = (
        ts_template_ternary_at(contract, "For session hits, use sessions_search", "history_clause")
    )
    if (recall_search_condition, recall_no_get) != ("hasMemoryGet", ""):
        raise ValueError("buildMemoryPromptSection search guidance changed shape")
    if sessions_condition != 'availableTools.has("sessions_history")':
        raise ValueError("buildMemoryPromptSection sessions_search line changed shape")
    corpus = src["corpus"]
    memory_label, wiki_label = ts_ternary_at(corpus, 'attempt.corpus === "memory"')
    read_shared = src["read_shared"]
    read_retry = src["read_retry"]
    tools = src["tools"]
    message_regex, message_flags = ts_regex_literal_at(read_retry, "TRANSIENT_MEMORY_READ_MESSAGE")
    detail_regex, detail_flags = ts_regex_literal_at(
        fs["fs_error_detail"], "UNSAFE_ERROR_DETAIL_CHARACTERS"
    )
    return {
        "MEMORY_SEARCH_TOOL_NAME": ts_string_at(contract, "memory_search"),
        "MEMORY_GET_TOOL_NAME": ts_string_at(contract, "memory_get"),
        "SEARCH_CORPUS_OUTCOME_GUIDANCE": search_guidance,
        "GET_READ_OUTCOME_GUIDANCE": get_guidance,
        "MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE": search_description,
        "MEMORY_GET_TOOL_DESCRIPTION_TEMPLATE": get_description,
        "MEMORY_SOURCE_FILES": ts_string_at(contract, "MEMORY.md, USER.md"),
        "MEMORY_SOURCE_EXTRA_PATHS": ts_string_at(contract, "configured extra paths"),
        "MEMORY_SOURCE_SEARCH_TEMPLATE": ts_template_at(
            contract, "${files}, indexed session transcripts", {"files": "files"}
        ),
        "MEMORY_SEARCH_CORPORA": ts_string_array_at(
            tools, "const modelRequestedCorpus = readCorpusParam(rawParams,"
        ),
        "MEMORY_GET_CORPORA": ts_string_array_at(
            tools, "const requestedCorpus = readCorpusParam(rawParams,"
        ),
        "MEMORY_CORPUS_PARAM_ERROR_TEMPLATE": ts_template_at(
            tools, "corpus must be one of: ${", {'allowed.join(", ")': "allowed"}
        ),
        "MEMORY_RECALL_HEADING": ts_string_at(contract, "## Memory Recall"),
        "MEMORY_RECALL_SEARCH_TEMPLATE": recall_search,
        "MEMORY_RECALL_SEARCH_GET_CLAUSE": recall_get_clause,
        "MEMORY_RECALL_GET_ONLY": ts_string_at(contract, "Before answering anything"),
        "MEMORY_RECALL_SESSIONS_SEARCH_TEMPLATE": sessions_search,
        "MEMORY_RECALL_SESSIONS_HISTORY_CLAUSE": sessions_history_clause,
        "MEMORY_RECALL_SESSIONS_NO_HISTORY_CLAUSE": sessions_no_history_clause,
        "MEMORY_RECALL_SESSIONS_HISTORY_ONLY": ts_string_at(
            contract, "For session hits, use sessions_history"
        ),
        "MEMORY_RECALL_SESSIONS_SNIPPETS_ONLY": ts_string_at(
            contract, "Session hits are search snippets only"
        ),
        "MEMORY_RECALL_SESSION_LINE_NUMBERS": ts_string_at(
            contract, "Session search line numbers"
        ),
        "MEMORY_RECALL_OUTCOME": ts_string_at(contract, "Report partial, unavailable"),
        "MEMORY_RECALL_CITATIONS_OFF": ts_string_at(contract, "Citations are disabled"),
        "MEMORY_RECALL_CITATIONS_ON": ts_string_at(contract, "Citations: include"),
        "MEMORY_PATH_REQUIRED_ERROR": ts_string_at(src["read_file"], "path required"),
        "MEMORY_PATH_NOT_ALLOWED_ERROR": ts_string_at(src["read_file"], "path is not an allowed"),
        "MEMORY_PATH_NOT_ALLOWED_CODE": ts_string_at(src["read_file"], "MEMORY_PATH_NOT_ALLOWED"),
        "MEMORY_READ_FAILED_CODE": ts_string_at(src["read_tool"], "MEMORY_READ_FAILED"),
        **ts_numeric_constants(
            read_shared, ("DEFAULT_MEMORY_READ_LINES", "DEFAULT_MEMORY_READ_MAX_CHARS")
        ),
        "MEMORY_READ_CONTINUE_TEMPLATE": ts_template_at(
            read_shared, "[More content available. Use from=${", {"params.nextFrom": "next_from"}
        ),
        "MEMORY_READ_MAX_CHARS_NOTICE": ts_string_at(
            read_shared, "[More content available. Requested"
        ),
        "MEMORY_READ_FALLBACK_HINT": ts_string_at(read_shared, " If you need the full raw line"),
        "TRANSIENT_MEMORY_READ_ERRNO": ts_signed_integer_constant(
            read_retry, "TRANSIENT_MEMORY_READ_ERRNO"
        ),
        "TRANSIENT_MEMORY_READ_CODES": ts_string_array_at(
            read_retry, "const TRANSIENT_MEMORY_READ_CODES = new Set("
        ),
        "TRANSIENT_MEMORY_READ_MESSAGE_PATTERN": message_regex,
        "TRANSIENT_MEMORY_READ_MESSAGE_FLAGS": message_flags,
        "TRANSIENT_MEMORY_READ_ATTEMPTS": ts_number_after(read_retry, "attempts:"),
        "TRANSIENT_MEMORY_READ_MIN_DELAY_MS": ts_number_after(read_retry, "minDelayMs:"),
        "TRANSIENT_MEMORY_READ_MAX_DELAY_MS": ts_number_after(read_retry, "maxDelayMs:"),
        **ts_numeric_constants(src["deadline"], ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",)),
        "MEMORY_CORPUS_TIMEOUT_TEMPLATE": ts_template_at(
            corpus,
            "${params.operation} timed out after ${",
            {
                "params.operation": "operation",
                "DEFAULT_MEMORY_SEARCH_TIMEOUT_MS / 1000": "seconds",
            },
        ),
        "MEMORY_CORPUS_MEMORY_LABEL": memory_label,
        "MEMORY_CORPUS_WIKI_LABEL": wiki_label,
        "MEMORY_CORPUS_FAILURE_WARNING_TEMPLATE": ts_template_at(
            corpus,
            "${label} corpus ${attempt.outcome}: ${",
            {"label": "label", "attempt.outcome": "outcome", "attempt.error": "error"},
        ),
        "MEMORY_CORPUS_NOT_REGISTERED_WARNING_TEMPLATE": ts_template_at(
            corpus, "${label} corpus is not registered", {"label": "label"}
        ),
        "MEMORY_CORPUS_PLUGIN_FAILURE_TEMPLATE": ts_template_at(
            corpus, "${entry.pluginId}: ${", {"entry.pluginId": "plugin_id", "entry.error": "error"}
        ),
        "MEMORY_CORPUS_SUPPLEMENT_CONCURRENCY": ts_number_after(corpus, "limit: Math.min("),
        "MEMORY_CORPUS_SUPPLEMENT_DEFAULT_MAX_RESULTS": ts_number_after(
            corpus, "Math.max(1, params.maxResults ??"
        ),
        "FS_SAFE_ROOT_BOUNDARY_LABEL": _fs_root_boundary_label(fs["fs_root_context"]),
        "FS_SAFE_OUTSIDE_WORKSPACE_CODE": ts_string_at(fs["fs_root_context"], "outside-workspace"),
        "FS_SAFE_OUTSIDE_WORKSPACE_ERROR": ts_string_at(
            fs["fs_root_context"], "file is outside workspace root"
        ),
        "FS_SAFE_INVALID_PATH_CODE": ts_string_at(fs["fs_root_context"], "invalid-path"),
        "FS_SAFE_PATH_TOO_LONG_ERROR": ts_string_at(
            fs["fs_root_context"], "relative path is too long"
        ),
        "FS_SAFE_ROOT_NOT_DIRECTORY_ERROR": ts_string_at(
            fs["fs_root_context"], "root dir is not a directory"
        ),
        "FS_SAFE_NOT_DIRECTORY_TEMPLATE": ts_template_at(
            fs["fs_root_path"], "Path component is not a directory: ${", {"pathname": "path"}
        ),
        "FS_SAFE_SYMLINK_ESCAPE_TEMPLATE": ts_template_at(
            fs["fs_root_path_errors"],
            "Symlink escapes ${",
            {
                "params.boundaryLabel": "boundary",
                "shortPath(params.rootCanonicalPath)": "root",
                "shortPath(params.symlinkPath)": "path",
            },
        ),
        "FS_SAFE_UNSAFE_DETAIL_PATTERN": detail_regex,
        "FS_SAFE_UNSAFE_DETAIL_FLAGS": detail_flags,
        "FS_SAFE_NOT_REGULAR_FILE_ERROR": ts_string_at(
            fs["fs_regular_file"], "path must be a regular file"
        ),
        "FS_SAFE_NOT_REGULAR_READ_TEMPLATE": ts_template_at(
            fs["fs_regular_file"], "File is not a regular file: ${", {"filePath": "path"}
        ),
        "FS_SAFE_FILE_NOT_FOUND_TEMPLATE": ts_template_at(
            fs["fs_regular_file"], "File not found: ${", {"filePath": "path"}
        ),
        "FS_SAFE_ROOT_NOT_FOUND_CODE": ts_string_at(fs["fs_root_context"], "not-found"),
        "FS_SAFE_ROOT_NOT_FOUND_ERROR": ts_string_at(fs["fs_root_context"], "root dir not found"),
        "FS_SAFE_SYMLINK_CODE": _fs_symlink_code(fs["fs_root_context"]),
        "FS_SAFE_SYMLINK_UNRESOLVED_ERROR": ts_string_at(
            fs["fs_root_path_existing"], "symlink path could not be resolved"
        ),
        "FS_SAFE_NOT_FOUND_CODES": ts_string_array_at(
            fs["fs_path"], "const NOT_FOUND_CODES = new Set("
        ),
        "FS_SAFE_SYMLINK_OPEN_CODES": ts_string_array_at(
            fs["fs_path"], "const SYMLINK_OPEN_CODES = new Set("
        ),
        "MEMORY_FILE_MISSING_CODES": _file_missing_codes(src["fs_utils"]),
        "FS_SAFE_PATH_MISMATCH_CODE": ts_string_at(fs["fs_regular_file"], "path-mismatch"),
        "FS_SAFE_FILE_CHANGED_TEMPLATE": ts_template_at(
            fs["fs_regular_file"], "File changed during read: ${", {"filePath": "path"}
        ),
        "FS_SAFE_IDENTITY_MISMATCH_ERROR": ts_string_at(
            fs["fs_identity"], "file identity changed"
        ),
    }


def _file_missing_codes(fs_utils: str) -> tuple[str, ...]:
    # fs-utils.ts isFileMissingError: the err.code comparisons of its body, in order.
    start = fs_utils.index("export function isFileMissingError(")
    body = fs_utils[start : fs_utils.index("\n}\n", start)]
    codes = tuple(re.findall(r'err\.code === "([^"]+)"', body))
    if not codes:
        raise ValueError("fs-utils.ts isFileMissingError changed")
    return codes


def _fs_symlink_code(root_context: str) -> str:
    # root-context.js resolvePathInRoot rethrows an FsSafeError whose code is "symlink" as is.
    match = re.search(r'error instanceof FsSafeError && error\.code === "([^"]+)"', root_context)
    if match is None:
        raise ValueError("fs-safe root-context.js symlink rethrow changed")
    return match.group(1)


def _fs_root_boundary_label(root_context: str) -> str:
    match = re.search(r'boundaryLabel: "([^"]+)"', root_context)
    if match is None or root_context.count("boundaryLabel: ") != 1:
        raise ValueError("fs-safe root-context.js boundaryLabel changed")
    return match.group(1)


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() or "unknown"


def _render_value(name: str, value: object) -> list[str]:
    if isinstance(value, (str, int, float)):
        return [f"{name} = {ascii(value)}"]
    if isinstance(value, dict):
        lines = [f"{name}: dict[str, int] = {{"]
        lines.extend(f"    {ascii(key)}: {ascii(item)}," for key, item in value.items())
        return [*lines, "}"]
    items = list(value)  # type: ignore[call-overload]
    if items and isinstance(items[0], tuple):
        arity = ", ".join("str" for _ in items[0])
        lines = [f"{name}: tuple[tuple[{arity}], ...] = ("]
        lines.extend(f"    ({', '.join(ascii(part) for part in item)})," for item in items)
        return [*lines, ")"]
    lines = [f"{name}: tuple[str, ...] = ("]
    lines.extend(f"    {ascii(item)}," for item in items)
    return [*lines, ")"]


def render(constants: dict[str, object], commit: str, *, title: str, sources: list[str], note: list[str]) -> str:
    lines = [
        f'"""{title}.',
        "",
        "Extracted by scripts/extract_upstream_constants.py.",
        f"Generated from OpenClaw {commit}:",
        *[f"{source}{'.' if index == len(sources) - 1 else ','}" for index, source in enumerate(sources)],
        f"Do not edit by hand: re-run the script; {CHECK_TEST}",
        "checks these values against the source.",
        *note,
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for name, value in constants.items():
        lines.extend(_render_value(name, value))
    return "\n".join(lines) + "\n"


def outputs(repo: Path) -> dict[Path, str]:
    commit = _git_head(repo)
    return {
        OUTPUT: render(
            extract(repo),
            commit,
            title="Upstream TOOLS.md migration constants",
            sources=[CONTENT_SOURCE, GUIDANCE_SOURCE, MIGRATION_SOURCE, MIGRATION_BUDGET_SOURCE],
            note=[
                "The legacy templates are upstream's retired TOOLS.md stock texts, used only to",
                f"recognise an untouched file; {DISPLAY_NAME} never seeds them. The finding texts are",
                "str.format templates; their fields stand for upstream template expressions.",
            ],
        ),
        BOOTSTRAP_OUTPUT: render(
            extract_bootstrap(repo),
            commit,
            title="Upstream bootstrap budget constants and policy-digest keywords",
            sources=[BOOTSTRAP_SOURCE, BUDGET_SOURCE, BUDGET_WARNING_SOURCE],
            note=[
                "The *_UNBOUNDED_KEYWORDS match without word boundaries (the second alternation",
                "group of the upstream /\\b(?:...)\\b|(?:...)/iu patterns).",
            ],
        ),
        HEARTBEAT_OUTPUT: render(
            extract_heartbeat(repo),
            commit,
            title="Upstream heartbeat, monitor-scratch and automation-migration constants",
            sources=list(HEARTBEAT_SOURCES.values()),
            note=[
                "Template texts are str.format templates; their fields stand for upstream",
                "template expressions (HEARTBEAT_TEMPLATE_FIELDS in the script). The doctor",
                f"texts name 'openclaw doctor'; {PACKAGE_NAME}.heartbeat_migration substitutes its own",
                "helper names where they are shown (documented deviation).",
            ],
        ),
        FLUSH_OUTPUT: render(
            extract_memory_flush(repo),
            commit,
            title="Upstream memory-flush prompts, hints and flush-plan defaults",
            sources=[
                FLUSH_PLAN_SOURCE,
                TOKENS_SOURCE,
                AGENT_SETTINGS_SOURCE,
                COMPACTION_CONSTANTS_SOURCE,
                RUNNER_MEMORY_SOURCE,
                SESSION_TYPES_SOURCE,
                PARSE_BYTES_SOURCE,
                WRITE_TOOL_SOURCE,
                AGENT_TOOLS_READ_SOURCE,
                FLUSH_SESSION_SOURCE,
                SYSTEM_PROMPT_SOURCE,
            ],
            note=[
                "The default prompts are the joined upstream arrays with SILENT_REPLY_TOKEN",
                "substituted; MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE is the str.format template of",
                "ensureNoReplyHint (fields: text, silent_reply_token); UNIT_MULTIPLIERS is the",
                "byte-size unit table of parseByteSize. The MEMORY_FLUSH_WRITE_*_TEMPLATE texts",
                "are str.format templates of wrapToolMemoryFlushAppendOnlyWrite (fields:",
                "description, relative_path).",
            ],
        ),
        TRANSCRIPT_REPAIR_OUTPUT: render(
            extract_transcript_repair(repo),
            commit,
            title="Upstream constants of the tool-call replay repair",
            sources=[TOOL_RESULT_PAIRING_SOURCE, TOOL_CALL_SHARED_SOURCE],
            note=[
                "DEFAULT_MISSING_TOOL_RESULT_TEXT is the synthetic tool result's text and a",
                "parity-bound marker: upstream recognises a stored synthetic result by it.",
                "TOOL_CALL_NAME_RE is the source of upstream's regex literal (no flags); it",
                "is applied to a trimmed name, so its $ anchor reads alike in Python.",
            ],
        ),
        MEMORY_TOOLS_OUTPUT: render(
            extract_memory_tools(repo),
            commit,
            title="Upstream constants of the memory_search and memory_get tools",
            sources=[
                *MEMORY_TOOL_SOURCES.values(),
                *(f"{path} (@openclaw/fs-safe {FS_SAFE_VERSION})" for path in FS_SAFE_SOURCES.values()),
            ],
            note=[
                "The *_TEMPLATE texts are str.format templates whose fields stand for upstream",
                "template expressions; a *_CLAUSE is the literal a ternary inside a template adds.",
                "The tool descriptions come from memory-tool-contract.ts describe(), the",
                "## Memory Recall lines from buildMemoryPromptSection, the read texts from",
                "readMemoryFile / buildMemoryReadResult and the fs-safe refusals from the built",
                "@openclaw/fs-safe package that readMemoryFile resolves and reads through.",
            ],
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.getenv("OPENCLAW_ORACLE_REPO"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo (or OPENCLAW_ORACLE_REPO) is required")
    repo = Path(args.repo)
    status = 0
    for path, text in outputs(repo).items():
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                print(f"{path} differs from {repo}", file=sys.stderr)
                status = 1
            continue
        path.write_text(text, encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
