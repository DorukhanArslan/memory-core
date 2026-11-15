"""Selected actual V6 suite custody; absent captures earn no acceptance credit."""
from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence import forget_index_fence_v6 as frozen

ROOT = Path(__file__).resolve().parents[2]
SELECTORS = {
    "suite_report": "MEMORY_FORGET_INDEX_FENCE_V6_SUITE_REPORT",
    "native_capture_root": "MEMORY_FORGET_INDEX_FENCE_V6_NATIVE_CAPTURE_ROOT",
    "sdk_capture_root": "MEMORY_FORGET_INDEX_FENCE_V6_SDK_CAPTURE_ROOT",
    "reference": "MEMORY_FORGET_INDEX_FENCE_REFERENCE_ROOT",
    "sdk_source_root": "MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT",
    "adapter_root": "MEMORY_FORGET_INDEX_FENCE_ADAPTER_ROOT",
    "node": "MEMORY_EQ_NODE",
}


@lru_cache(maxsize=1)
def _cli():
    spec = spec_from_file_location("v6_actual_suite_admission", ROOT / "scripts/replay_forget_index_fence.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _selected_suite():
    selected = {key: os.environ.get(variable) for key, variable in SELECTORS.items()}
    if selected["suite_report"] is None:
        pytest.skip("No explicitly selected actual V6 suite; no acceptance credit")
    assert all(selected.values()), "V6 suite replay requires every independently selected source and physical root"
    assert os.environ.get("MEMORY_FORGET_INDEX_FENCE_V6_CAPTURE_ROOT") is None, "V6 suite and collector selection cannot mix"
    cli = _cli()
    args = SimpleNamespace(version="v6", **{key: Path(value) for key, value in selected.items()})
    authority = cli._authorities(args, guard, frozen)
    rows, _, _ = cli._admit_suite_report(args, authority, {"sourceReports": []}, frozen)
    return args, rows


@pytest.mark.parametrize("case", frozen.build_cases(), ids=lambda case: case["id"])
def test_actual_v6_pair_requires_whole_suite_results_and_complete_independent_custody(case):
    args, rows = _selected_suite()
    selected = rows[case["id"]]
    cli = _cli()
    assert all(cli._seal(item["path"]) == item for item in selected["files"].values())
    actual = guard.replay_case(case, selected["directories"]["native"], selected["directories"]["sdk"],
        approved_node=args.node, approved_reference=args.reference, approved_sdk_root=args.sdk_source_root,
        approved_adapter_root=args.adapter_root, include_results=True)
    assert actual["validated"] is True and actual["acceptancePointsAwarded"] == 0
    assert type(actual["publicMatch"]) is bool
    guard._same(actual["nativeResult"], selected["nativeResult"], "Actual V6 Native whole result changed after suite admission")
    guard._same(actual["sdkResult"], selected["sdkResult"], "Actual V6 SDK whole result changed after suite admission")
    assert all(cli._seal(item["path"]) == item for item in selected["files"].values())


def test_v6_actual_suite_selector_never_uses_an_implicit_root(monkeypatch):
    monkeypatch.delenv(SELECTORS["suite_report"], raising=False)
    with pytest.raises(pytest.skip.Exception, match="No explicitly selected actual V6 suite"):
        _selected_suite.__wrapped__()


@pytest.mark.parametrize("missing", [key for key in SELECTORS if key != "suite_report"])
def test_v6_actual_suite_requires_each_declared_authority_before_admission(monkeypatch, missing):
    for variable in SELECTORS.values():
        monkeypatch.setenv(variable, "UNIT_EXPLICIT_SELECTOR")
    monkeypatch.delenv(SELECTORS[missing])
    with pytest.raises(AssertionError, match="requires every independently selected"):
        _selected_suite.__wrapped__()
