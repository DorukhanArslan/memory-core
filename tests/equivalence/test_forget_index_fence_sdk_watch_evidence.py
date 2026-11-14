"""Input/source-only watcher guard checks; never fabricate a positive capture."""
from copy import deepcopy

import pytest

from equivalence.forget_index_fence_sdk_effects_evidence import _closed_effects_case
from equivalence.forget_index_fence_sdk_watch_evidence import _closed_watch_case
from equivalence.forget_index_fence_v3 import build_cases as build_v3_cases
from equivalence.forget_index_fence_v4 import build_cases as build_v4_cases
from equivalence.forget_index_fence_v5 import build_cases as build_v5_cases


@pytest.mark.parametrize("case", build_v5_cases(), ids=lambda case: case["id"])
def test_sdk_watch_guard_admits_only_each_exact_frozen_v5_member(case):
    assert _closed_watch_case(case) == case
    assert _closed_effects_case(case) == 5
    assert case["input"]["observationPolicy"]["watchEffects"]["protocol"] == "original-watch-effects-v5"
    assert case["input"]["observationPolicy"]["searchEffects"]["protocol"] == "original-search-effects-v3"


@pytest.mark.parametrize("builder", [build_v3_cases, build_v4_cases])
def test_sdk_watch_guard_rejects_historical_versions(builder):
    case = builder()[0]
    with pytest.raises(ValueError):
        _closed_watch_case(case)
    assert _closed_effects_case(case) in (3, 4)


@pytest.mark.parametrize("attack", ["kind", "operation", "coverage", "step", "watch-policy", "public-clock"])
def test_sdk_watch_guard_rejects_unfrozen_lifecycle_inputs(attack):
    case = deepcopy(build_v5_cases()[0])
    if attack == "kind":
        case["input"]["kind"] = "forget-index-fence-v5-extra"
    elif attack == "operation":
        case["operation"] = "forget-index-fence-v4-runtime"
    elif attack == "coverage":
        case["covers"] = case["covers"][:1]
    elif attack == "step":
        index = next(index for index, row in enumerate(case["input"]["steps"])
                     if row["operation"] == "await-original-watch-ready")
        del case["input"]["steps"][index]
    elif attack == "watch-policy":
        case["input"]["observationPolicy"]["watchEffects"]["protocol"] = "original-search-effects-v3"
    else:
        case["input"]["clock"]["sourceWriteClock"]["ticksByCall"]["watch:invented"] = {
            "mtimeMs": 1794614400000, "atimeMs": 1794614400000}
    with pytest.raises(ValueError):
        _closed_watch_case(case)


def test_sdk_watch_family_adds_no_manufactured_public_clock_ticks():
    v3 = build_v3_cases()
    v5 = build_v5_cases()
    assert len(v3) == len(v5) == 13
    for old, current in zip(v3, v5, strict=True):
        assert old["input"]["clock"] == current["input"]["clock"]
