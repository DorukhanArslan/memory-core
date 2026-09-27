"""Oracle JUnit XML -> ``parity-results.json`` for the Lab's parity view (demo-only).

Producer (isolated env, ``OPENCLAW_ORACLE_REPO`` at a checkout of the pin, ``OPENCLAW_ORACLE_NODE``
at a node binary in that checkout's ``engines.node`` range; docs/lab.md › Oracle checkout)::

    .venv/bin/python -m pytest -q -p no:cacheprovider \\
        tests/integration/test_openclaw_ts_oracle.py tests/integration/test_memory_tools.py \\
        --junitxml=$TMPDIR/memory-core-lab/oracle.xml
    .venv/bin/python -m demo.parity_results $TMPDIR/memory-core-lab/oracle.xml \\
        --out $TMPDIR/memory-core-lab/parity-results.json

Each test gets an area (nodeid keyword map below) and an evidence kind, found by
static analysis of the test source, never by a hand-kept list:

- ``python_eq_ts``: the test calls the real TypeScript through the oracle runner
  *and* memory-core code, so it compares Python with TS directly;
- ``ts_literal``: the oracle runs, but the test body reaches no memory-core code, so
  TS is compared with literals only and Python parity is two-hop;
- ``python_eq_source``: no oracle run; Python constants are checked against the
  upstream source text;
- ``python_literal``: no oracle; Python is compared with literals;
- ``other``: neither.

Results live outside the repo (``MEMORY_CORE_LAB_PARITY_RESULTS`` overrides the path).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from demo.openclaw_oracle import PIN_CHECKOUT_PATH
from memory_core.parity.upstream import LATEST_INSPECTED_COMMIT

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATRIX_PATH = PROJECT_ROOT / "docs" / "parity_matrix.md"
ORACLE_MODULES = ("demo.openclaw_oracle", "demo.openclaw_run_loop_oracle")
PYTHON_MODULE_PREFIXES = ("memory-core", "demo")
DEFAULT_ORACLE_REPO = str(PIN_CHECKOUT_PATH)

PRODUCER_COMMANDS = (
    "TMPDIR=<scratch> PYTHONDONTWRITEBYTECODE=1 MEMORY_CORE_DEMO_OPENAI_API_KEY= "
    f"MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY= OPENCLAW_ORACLE_REPO={DEFAULT_ORACLE_REPO} "
    "OPENCLAW_ORACLE_NODE=<node in the checkout's engines range> "
    ".venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_openclaw_ts_oracle.py "
    "tests/integration/test_memory_tools.py --junitxml=<scratch>/memory-core-lab/oracle.xml",
    ".venv/bin/python -m demo.parity_results <scratch>/memory-core-lab/oracle.xml "
    "--out <scratch>/memory-core-lab/parity-results.json",
)

# (area id, label, nodeid keyword pattern); first match wins.
AREA_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (area, label, re.compile(pattern))
    for area, label, pattern in (
        ("session_memory", "Session-memory hook", r"session_memory"),
        ("heartbeat", "Heartbeat", r"heartbeat"),
        ("curation", "Curated writes", r"curated|curation"),
        (
            "bootstrap",
            "Workspace bootstrap",
            r"bootstrap|workspace_lifecycle|workspace_bootstrap|project_context|startup_context",
        ),
        ("flush", "Memory flush", r"flush"),
        ("memory_get", "memory_get", r"memory_get"),
        (
            "memory_search",
            "memory_search and index",
            r"memory_search|index_identity|list_memory_files|memory_tool|search_",
        ),
        (
            "consolidation",
            "Promotion and dreaming",
            r"promotion|promoted|ranking|ranks_|recall|dreaming|deep_policy|concept|snippet_caps"
            r"|contaminated|reconcile|compacts|memory_budget|apply_|candidate|memory_header",
        ),
        (
            "compaction",
            "Compaction and overflow",
            r"compaction|overflow|tool_result|truncate",
        ),
        (
            "transcript",
            "Transcript and runtime context",
            r"history|replay|runtime_context|context_engine|repair_tool_use",
        ),
        ("run_loop", "Run loop", r"run_loop"),
    )
)


def default_results_path() -> Path:
    override = os.getenv("MEMORY_CORE_LAB_PARITY_RESULTS")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "memory-core-lab" / "parity-results.json"


def area_for(test_name: str) -> tuple[str, str]:
    for area, label, pattern in AREA_RULES:
        if pattern.search(test_name):
            return area, label
    return "other", "Other"


# --- static evidence classification --------------------------------------------------


class _Refs(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.local_python_imports = False
        self.local_oracle_imports = False
        self.reads_upstream_source = False

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id)

    def visit_Constant(self, node: ast.Constant) -> None:
        if node.value == "OPENCLAW_ORACLE_REPO":
            self.reads_upstream_source = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module in ORACLE_MODULES:
            self.local_oracle_imports = True
        elif module.split(".")[0] in PYTHON_MODULE_PREFIXES:
            self.local_python_imports = True

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in ORACLE_MODULES:
                self.local_oracle_imports = True
            elif alias.name.split(".")[0] in PYTHON_MODULE_PREFIXES:
                self.local_python_imports = True

    def visit_Attribute(self, node: ast.Attribute) -> None:
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name):
            self.names.add(root.id)
        self.generic_visit(node)


def _references(node: ast.AST) -> _Refs:
    refs = _Refs()
    refs.visit(node)
    return refs


def classify_test_source(source: str) -> dict[str, str]:
    """Evidence kind per top-level ``test_*`` function of one test module."""
    tree = ast.parse(source)
    python_names: set[str] = set()
    oracle_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            names = {alias.asname or alias.name for alias in node.names}
            if node.module in ORACLE_MODULES:
                oracle_names |= names
            elif node.module.split(".")[0] in PYTHON_MODULE_PREFIXES:
                python_names |= names
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.asname or alias.name.split(".")[0]
                if alias.name in ORACLE_MODULES:
                    oracle_names.add(target)
                elif alias.name.split(".")[0] in PYTHON_MODULE_PREFIXES:
                    python_names.add(target)
    definitions: dict[str, _Refs] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = _references(node)
        elif isinstance(node, ast.Assign):
            refs = _references(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = refs

    def closure(name: str) -> list[_Refs]:
        seen: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            refs = definitions.get(current)
            if refs is not None:
                stack.extend(ref for ref in refs.names if ref in definitions)
        return [definitions[item] for item in seen if item in definitions]

    kinds: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            reached = closure(node.name)
            names = set().union(*(refs.names for refs in reached)) if reached else set()
            uses_ts = bool(names & oracle_names) or any(r.local_oracle_imports for r in reached)
            uses_py = bool(names & python_names) or any(r.local_python_imports for r in reached)
            reads_source = any(r.reads_upstream_source for r in reached)
            if uses_ts and uses_py:
                kinds[node.name] = "python_eq_ts"
            elif uses_ts:
                kinds[node.name] = "ts_literal"
            elif uses_py and reads_source:
                kinds[node.name] = "python_eq_source"
            elif uses_py:
                kinds[node.name] = "python_literal"
            else:
                kinds[node.name] = "other"
    return kinds


# --- junit -> results ---------------------------------------------------------------------


def _test_file_for(classname: str, repo_root: Path) -> Path:
    return repo_root / Path(*classname.split(".")).with_suffix(".py")


def _outcome(case: ET.Element) -> str:
    for child in case:
        if child.tag in {"failure", "error"}:
            return "failed"
        if child.tag == "skipped":
            return "skipped"
    return "passed"


def _git_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    head = completed.stdout.strip()
    return head or None


def _empty_counts() -> dict[str, int]:
    return {"passed": 0, "failed": 0, "skipped": 0}


def build_parity_results(
    junit_path: str | os.PathLike[str],
    *,
    repo_root: Path = PROJECT_ROOT,
    commit: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = ET.parse(junit_path).getroot()
    cases = list(root.iter("testcase"))
    classifications: dict[Path, dict[str, str]] = {}
    areas: dict[str, dict[str, Any]] = {}
    totals = _empty_counts()
    by_evidence: dict[str, dict[str, int]] = {}
    duration = 0.0
    for case in cases:
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        base = name.split("[", 1)[0]
        test_file = _test_file_for(classname, repo_root)
        if test_file not in classifications:
            try:
                classifications[test_file] = classify_test_source(test_file.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                classifications[test_file] = {}
        evidence = classifications[test_file].get(base, "other")
        outcome = _outcome(case)
        time_s = float(case.get("time") or 0.0)
        duration += time_s
        area_id, label = area_for(base)
        area = areas.setdefault(
            area_id,
            {"area": area_id, "label": label, **_empty_counts(), "evidence": {}, "tests": []},
        )
        area[outcome] += 1
        counts = area["evidence"].setdefault(evidence, _empty_counts())
        counts[outcome] += 1
        totals[outcome] += 1
        by_evidence.setdefault(evidence, _empty_counts())[outcome] += 1
        rel_file = test_file.relative_to(repo_root).as_posix() if test_file.is_relative_to(repo_root) else str(test_file)
        area["tests"].append(
            {
                "nodeid": f"{rel_file}::{name}",
                "outcome": outcome,
                "timeS": round(time_s, 3),
                "evidence": evidence,
            }
        )
    return {
        "path": str(Path(junit_path)),
        "generatedAt": generated_at or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "commit": commit if commit is not None else _git_head(repo_root),
        "pin": LATEST_INSPECTED_COMMIT,
        "oracleRepo": os.getenv("OPENCLAW_ORACLE_REPO") or None,
        "durationS": round(duration, 3),
        "totals": totals,
        "byEvidence": by_evidence,
        "evidenceKinds": {
            "python_eq_ts": "oracle + memory-core in the same test: Python == TS",
            "ts_literal": "oracle only: TS vs literals (Python parity is two-hop)",
            "python_eq_source": "no oracle run: Python constants vs the upstream source text",
            "python_literal": "no oracle: Python vs literals",
            "other": "neither",
        },
        "byArea": sorted(areas.values(), key=lambda item: item["area"]),
    }


def load_parity_results(path: Path | None = None) -> dict[str, Any] | None:
    target = path or default_results_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_parity_matrix(path: Path = MATRIX_PATH) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    keys = (
        "area", "openclawSource", "pythonSource", "oracleOperation", "status", "knownGaps",
        "nextTest", "priority",
    )
    for line in lines:
        if not line.startswith("| ") or line.startswith("| Area ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            continue
        row = dict(zip(keys, cells, strict=True))
        row["status"] = row["status"].strip("`")
        rows.append(row)
    return rows


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("junit", help="pytest --junitxml output")
    parser.add_argument("--out", default=None, help="parity-results.json path")
    args = parser.parse_args(list(argv) if argv is not None else None)
    results = build_parity_results(args.junit)
    out = Path(args.out) if args.out else default_results_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    totals = results["totals"]
    print(
        f"{out}: {totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped; "
        + ", ".join(f"{kind} {sum(v.values())}" for kind, v in sorted(results["byEvidence"].items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
