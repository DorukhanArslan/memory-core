"""Replay only explicitly selected, genuine forget/index-fence packets.

The first retained packet contains a completed SDK attempt and a timed-out
Native attempt. It supplies SDK custody tests only; a failed Native transport
cannot become a positive paired baseline. No test launches an original engine.
"""
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence import build_cases


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_CAPTURE_ROOT")
SDK_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_CAPTURE_ROOT")
SDK_SOURCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT", ROOT)).resolve()
REFERENCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_REFERENCE_ROOT", ROOT / "work/openclaw-v2026.9.9")).resolve()
CASES = build_cases()


def _read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), path
    return json.loads(path.read_text(encoding="utf8"))


@lru_cache(maxsize=2)
def _sdk(case_id):
    if SDK_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected new SDK forget/index-fence packet; no acceptance credit")
    case = next(case for case in CASES if case["id"] == case_id)
    directory = Path(SDK_CAPTURE_ROOT).resolve(strict=True) / case_id / "sdk/evidence"
    path = directory / "python-raw.json"
    assert path.is_file(), f"The explicitly selected packet is incomplete: {path}"
    values = _read(path)
    assert isinstance(values, list) and len(values) == 1, path
    capture = values[0]
    result = capture["observation"]["result"]
    assert guard.validate_capture(case, capture, result, native=False,
        approved_sdk_root=SDK_SOURCE_ROOT, directory=directory) is True
    return case, capture, result, directory


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def sdk_actual(request):
    return _sdk(request.param["id"])


def test_actual_sdk_whole_capture_validates_without_a_native_positive(sdk_actual):
    case, capture, result, directory = sdk_actual
    assert guard.validate_capture(case, capture, result, native=False,
        approved_sdk_root=SDK_SOURCE_ROOT, directory=directory) is True


@pytest.mark.parametrize("field", ["provider", "calls", "snapshots"])
def test_sdk_whole_common_result_cannot_drop_a_field(sdk_actual, field):
    case, _, original, _ = sdk_actual
    result = deepcopy(original)
    del result[field]
    with pytest.raises(ValueError):
        guard.validate_result(case, result)


@pytest.mark.parametrize("field", sorted(guard.FORGET_FIELDS))
def test_sdk_whole_original_forget_report_cannot_drop_a_field(sdk_actual, field):
    case, _, original, _ = sdk_actual
    result = deepcopy(original)
    report = next(call["outcome"]["result"] for call in result["calls"].values()
                  if call["operation"] == "forget" and call["outcome"]["status"] == "fulfilled")
    del report[field]
    with pytest.raises(ValueError):
        guard.validate_result(case, result)


def test_sdk_actual_callable_identity_includes_original_code_location(sdk_actual):
    _, capture, _, _ = sdk_actual
    for process in capture["observation"]["processes"]:
        owners = process["observation"]["codeOwners"]
        identities = [(row["name"], row["code"]["file"], row["code"]["qualname"],
                       row["code"]["firstLine"], row["code"]["bytecodeSha256"]) for row in owners]
        assert len(identities) == len(set(identities))
