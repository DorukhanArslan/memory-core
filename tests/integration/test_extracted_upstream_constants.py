"""The script-extracted upstream constants equal the pinned TypeScript source.

scripts/extract_upstream_constants.py generates memory_core/bootstrap/_tools_md_constants.py,
memory_core/bootstrap/_bootstrap_constants.py, memory_core/_heartbeat_constants.py,
memory_core/_memory_flush_constants.py, memory_core/_transcript_repair_constants.py,
memory_core/tools/_memory_tool_constants.py and memory_core/index/_index_identity_constants.py
from the oracle checkout; this regenerates them from ``OPENCLAW_ORACLE_REPO`` and compares them
with the committed files (set-equality check of AGENTS.md › Parity rules). Needs
``OPENCLAW_ORACLE_REPO`` (no Node run).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from memory_core.project_name import PACKAGE_NAME

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENCLAW_ORACLE_REPO"), reason="needs OPENCLAW_ORACLE_REPO"
)


def _script():
    spec = importlib.util.spec_from_file_location(
        "extract_upstream_constants_under_test", ROOT / "scripts" / "extract_upstream_constants.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_constant_modules_equal_the_upstream_source():
    outputs = _script().outputs(Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    assert set(outputs) == {
        ROOT / PACKAGE_NAME / "bootstrap" / "_tools_md_constants.py",
        ROOT / PACKAGE_NAME / "bootstrap" / "_bootstrap_constants.py",
        ROOT / PACKAGE_NAME / "_heartbeat_constants.py",
        ROOT / PACKAGE_NAME / "_memory_flush_constants.py",
        ROOT / PACKAGE_NAME / "_transcript_repair_constants.py",
        ROOT / PACKAGE_NAME / "tools" / "_memory_tool_constants.py",
        ROOT / PACKAGE_NAME / "index" / "_index_identity_constants.py",
    }
    for path, text in outputs.items():
        assert path.read_text(encoding="utf-8") == text, path.name
