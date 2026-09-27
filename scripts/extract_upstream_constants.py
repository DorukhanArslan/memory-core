"""Extract upstream string constants from the OpenClaw TypeScript source (no hand-copying).

AGENTS.md › Parity rules: upstream prompt, template and safety constants are copied verbatim by
script, and a set-equality check compares them with the source at test time
(tests/integration/test_tools_md_migration_source.py). This script generates
``memory_core/bootstrap/_tools_md_constants.py`` from the checkout named by ``--repo`` (default
``OPENCLAW_ORACLE_REPO``), writing every non-ASCII character as a ``\\u`` escape::

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


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() or "unknown"


def render(constants: dict[str, object], commit: str) -> str:
    lines = [
        '"""Upstream TOOLS.md migration constants, extracted by scripts/extract_upstream_constants.py.',
        "",
        f"Generated from OpenClaw {commit}:",
        f"{CONTENT_SOURCE},",
        f"{GUIDANCE_SOURCE},",
        f"{MIGRATION_SOURCE}.",
        "Do not edit by hand: re-run the script; tests/integration/test_tools_md_migration_source.py",
        "checks these values against the source. The legacy templates are upstream's retired",
        "TOOLS.md stock texts, used only to recognise an untouched file; memory-core never seeds them.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for name, value in constants.items():
        if isinstance(value, str):
            lines.append(f"{name} = {ascii(value)}")
        else:
            lines.append(f"{name}: tuple[tuple[str, str], ...] = (")
            for first, second in value:  # type: ignore[union-attr]
                lines.append(f"    ({ascii(first)}, {ascii(second)}),")
            lines.append(")")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.getenv("OPENCLAW_ORACLE_REPO"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo (or OPENCLAW_ORACLE_REPO) is required")
    repo = Path(args.repo)
    text = render(extract(repo), _git_head(repo))
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(f"{OUTPUT} differs from {repo}", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
