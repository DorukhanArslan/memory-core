"""The v2026.9.6 oracle worklist (tests/integration/oracle_worklist.py) stays consistent.

Offline checks: every pending-port entry names an existing oracle test, no test is listed twice,
reasons follow the stage-1 wording, and retired operations are gone from the runner while their
tests carry the retired skip.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "tests" / "integration"
RUNNER = ROOT / "scripts" / "openclaw_oracle_runner.ts"


def _worklist():
    spec = importlib.util.spec_from_file_location(
        "oracle_worklist_under_test", INTEGRATION / "oracle_worklist.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses resolve the defining module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _test_functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_pending_port_entries_name_existing_tests_once():
    worklist = _worklist()
    seen: set[str] = set()
    for port in worklist.PENDING_PORTS:
        assert port.tests, port.area
        for entry in port.tests:
            assert entry not in seen, entry
            seen.add(entry)
            file_name, _, test_id = entry.partition("::")
            function = re.split(r"[\[*]", test_id, maxsplit=1)[0]
            assert function in _test_functions(INTEGRATION / file_name), entry


def test_pending_port_reasons_follow_the_stage_one_wording():
    worklist = _worklist()
    for port in worklist.PENDING_PORTS:
        assert port.reason.startswith("pending port to v2026.9.6: "), port.reason
        assert "; upstream " in port.reason, port.reason


def test_pending_port_reason_matches_exact_and_prefix_entries():
    worklist = _worklist()
    exact = "test_openclaw_ts_oracle.py::test_real_openclaw_oracle_deep_policy"
    assert worklist.pending_port_reason(exact).startswith("pending port to v2026.9.6: deep")
    long_param = (
        "test_openclaw_ts_oracle.py::test_real_openclaw_oracle_truncate_tool_result_text_"
        "matches_python[Line 1\\nLine 1]"
    )
    assert worklist.pending_port_reason(long_param) is not None
    assert worklist.pending_port_reason(exact + "_coerces_malformed_values[deep2]") is None


def test_retired_operations_are_gone_from_the_runner_and_skipped_in_tests():
    worklist = _worklist()
    runner = RUNNER.read_text(encoding="utf-8")
    oracle_tests = (INTEGRATION / "test_openclaw_ts_oracle.py").read_text(encoding="utf-8")
    for retired in worklist.RETIRED_OPS:
        assert f'payload.operation === "{retired.operation}"' not in runner, retired.operation
        assert f'@retired_upstream("{retired.operation}")' in oracle_tests, retired.operation
        assert retired.reason.startswith("retired upstream in "), retired.reason
        assert "(v2026.9.6); re-port in stage 2: " in retired.reason, retired.reason
