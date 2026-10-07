"""Exercise the integration oracle opt-in gate through real pytest collection and setup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORACLE_TEST = (
    "tests/integration/test_recall_events_oracle.py::test_event_scenarios_cover_the_branches"
)
OFFLINE_TEST = "tests/integration/test_memory_tools.py::test_memory_get_reads_line_window"


def _run_pytest(tmp_path: Path, oracle_repo: str | None, *tests: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("OPENCLAW_ORACLE_REPO", None)
    if oracle_repo is not None:
        env["OPENCLAW_ORACLE_REPO"] = oracle_repo
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env.update(
        TMPDIR=str(scratch),
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_ADDOPTS="",
        MEMORY_CORE_DEMO_OPENAI_API_KEY="",
        MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY="",
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", *tests],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("oracle_repo", [None, ""], ids=["unset", "empty"])
def test_offline_run_skips_oracle_setup_but_runs_other_tests(tmp_path: Path, oracle_repo: str | None):
    # Integration's collection hook sees the whole session, including files outside its folder.
    unrelated = tmp_path / "test_unrelated_oracle.py"
    unrelated.write_text("def test_runs():\n    pass\n", encoding="utf-8")
    result = _run_pytest(tmp_path, oracle_repo, ORACLE_TEST, OFFLINE_TEST, str(unrelated))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed, 1 skipped" in result.stdout


def test_explicit_missing_checkout_fails_instead_of_skipping(tmp_path: Path):
    result = _run_pytest(tmp_path, str(tmp_path / "missing-checkout"), ORACLE_TEST)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 error" in result.stdout
    assert "skipped" not in result.stdout
