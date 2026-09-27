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
- ``memory_core/_memory_flush_constants.py``: the memory-flush hints and default prompts of
  ``buildMemoryFlushPlan`` (extensions/memory-core/src/flush-plan.ts; the prompt arrays are
  joined with ``" "`` and ``${SILENT_REPLY_TOKEN}`` is substituted from src/auto-reply/tokens.ts),
  the flush plan and compaction reserve defaults (src/agents/agent-settings.ts,
  src/agents/agent-compaction-constants.ts), the flush failure limits
  (src/auto-reply/reply/agent-runner-memory.ts) and ``SESSION_TOTAL_TOKENS_VERSION``
  (src/config/sessions/types.ts)::

    .venv/bin/python scripts/extract_upstream_constants.py --repo /tmp/openclaw-head

``--check`` compares instead of writing and exits 1 on a difference.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "memory-core" / "bootstrap" / "_tools_md_constants.py"
BOOTSTRAP_OUTPUT = ROOT / "memory-core" / "bootstrap" / "_bootstrap_constants.py"
FLUSH_OUTPUT = ROOT / "memory-core" / "_memory_flush_constants.py"
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
        if source[index] != "+":
            return "".join(parts), index
        index = _skip_space(source, index + 1)


def ts_string_constant(source: str, name: str) -> str:
    """Value of ``const NAME = "..." + '...';``."""
    match = re.search(rf"\bconst {re.escape(name)}\s*=", source)
    if match is None:
        raise ValueError(f"constant {name} not found")
    value, _ = ts_string_expression(source, match.end())
    return value


def ts_template_literal(source: str, index: int, fields: dict[str, str]) -> tuple[str, int]:
    """A backtick template literal at ``index`` as a ``str.format`` template.

    Every ``${expression}`` must be a key of ``fields`` and becomes ``{field}``; literal braces
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
            depth = 1
            end = position + 2
            while depth:
                current = source[end]
                if current in "\"'":
                    _, end = _read_ts_string(source, end)
                    continue
                depth += {"{": 1, "}": -1}.get(current, 0)
                end += 1
            expression = source[position + 2 : end - 1].strip()
            if expression not in fields:
                raise ValueError(f"unmapped template expression {expression!r} at {position}")
            out.append("{" + fields[expression] + "}")
            position = end
            continue
        out.append({"{": "{{", "}": "}}"}.get(char, char))
        position += 1


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
    }


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() or "unknown"


def _render_value(name: str, value: object) -> list[str]:
    if isinstance(value, (str, int, float)):
        return [f"{name} = {ascii(value)}"]
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
                "recognise an untouched file; memory-core never seeds them. The finding texts are",
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
            ],
            note=[
                "The default prompts are the joined upstream arrays with SILENT_REPLY_TOKEN",
                "substituted; MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE is the str.format template of",
                "ensureNoReplyHint (fields: text, silent_reply_token).",
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
