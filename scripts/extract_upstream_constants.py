"""Extract upstream constants from the OpenClaw TypeScript source (no hand-copying).

AGENTS.md › Parity rules: upstream prompt, template and safety constants are copied verbatim by
script, and a set-equality check compares them with the source at test time
(tests/integration/test_extracted_upstream_constants.py). From the checkout named by
``--repo`` (default ``OPENCLAW_ORACLE_REPO``) this script generates, writing every non-ASCII
character as a ``\\u`` escape:

- ``memory_core/bootstrap/_tools_md_constants.py``: the TOOLS.md migration templates, guidance
  rewrites and heading (src/commands/doctor-tools-md-migration*.ts);
- ``memory_core/bootstrap/_bootstrap_constants.py``: the bootstrap budget numbers and the AGENTS.md
  policy-digest keyword sets (src/agents/embedded-agent-helpers/bootstrap.ts,
  src/agents/bootstrap-budget.ts, src/agents/bootstrap-budget-warning.ts)::

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
CHECK_TEST = "tests/integration/test_extracted_upstream_constants.py"
BOOTSTRAP_SOURCE = "src/agents/embedded-agent-helpers/bootstrap.ts"
BUDGET_SOURCE = "src/agents/bootstrap-budget.ts"
BUDGET_WARNING_SOURCE = "src/agents/bootstrap-budget-warning.ts"
CONTENT_SOURCE = "src/commands/doctor-tools-md-migration-content.ts"
GUIDANCE_SOURCE = "src/commands/doctor-tools-md-migration-guidance.ts"
MIGRATION_SOURCE = "src/commands/doctor-tools-md-migration.ts"

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
    }


def repr_ts(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


_NUMERIC_CONST_RE = re.compile(
    r"^(?:export )?const ([A-Z0-9_]+) = ([0-9_.]+(?: \* [0-9_.]+)*);", re.MULTILINE
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
        lines = [f"{name}: tuple[tuple[str, str], ...] = ("]
        lines.extend(f"    ({ascii(first)}, {ascii(second)})," for first, second in items)
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
            sources=[CONTENT_SOURCE, GUIDANCE_SOURCE, MIGRATION_SOURCE],
            note=[
                "The legacy templates are upstream's retired TOOLS.md stock texts, used only to",
                "recognise an untouched file; memory-core never seeds them.",
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
