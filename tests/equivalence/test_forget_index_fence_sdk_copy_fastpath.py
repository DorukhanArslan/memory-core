"""Pure observation-copy regressions; no original SDK actors or engines."""
from copy import deepcopy
import math
import operator

import pytest

from equivalence import forget_index_fence_sdk as sdk


@pytest.mark.parametrize("value", [
    None, "", "Unicode 雪 and literal \\n", b"\x00\xff", 0, 2**100,
    True, False, 0.0, -0.0, 1.25, float("inf"), float("-inf"), float("nan"),
])
def test_exact_immutable_scalars_keep_identity_and_value_without_normalization(value):
    copied = sdk._observation_copy(value)
    assert copied is value
    assert type(copied) is type(value)
    if type(value) is float and math.isnan(value):
        assert math.isnan(copied)
    elif type(value) is float and value == 0:
        assert math.copysign(1, copied) == math.copysign(1, value)
    else:
        assert copied == value


def test_nested_mutable_containers_and_tuple_descendants_are_copied_with_shared_aliases():
    shared = {"values": [1, {"flag": True}]}
    nested_tuple = ("unchanged", shared, [shared])
    original = {"tuple": nested_tuple, "sameTuple": nested_tuple,
                "shared": shared, "list": [shared]}
    original["cycle"] = original

    copied = sdk._observation_copy(original)

    assert copied is not original
    assert copied["cycle"] is copied
    assert copied["tuple"] is not nested_tuple
    assert copied["tuple"] is copied["sameTuple"]
    descendant = copied["shared"]
    assert descendant is not shared
    assert descendant is copied["tuple"][1]
    assert descendant is copied["tuple"][2][0]
    assert descendant is copied["list"][0]
    assert copied["tuple"][2] is not nested_tuple[2]
    assert descendant["values"] is not shared["values"]
    assert descendant["values"][1] is not shared["values"][1]
    descendant["values"][1]["flag"] = False
    descendant["values"].append("copied only")
    assert shared == {"values": [1, {"flag": True}]}


@pytest.mark.parametrize("base,value", [(str, "text"), (bytes, b"bytes"), (int, 17), (float, 1.5)])
def test_scalar_subclasses_with_mutable_attributes_use_full_copy(base, value):
    class MutableScalar(base):
        pass

    original = MutableScalar(value)
    original.details = {"events": ["original"]}
    copied = sdk._observation_copy(original)

    assert type(copied) is MutableScalar
    assert copied is not original
    assert copied == original
    assert copied.details is not original.details
    assert copied.details["events"] is not original.details["events"]
    copied.details["events"].append("copied only")
    assert original.details == {"events": ["original"]}


def test_scalar_metaclass_equality_cannot_masquerade_as_an_exact_builtin():
    class ScalarEquality(type):
        __hash__ = type.__hash__

        def __eq__(cls, other):
            return other is str or type.__eq__(cls, other)

    class MutableText(str, metaclass=ScalarEquality):
        pass

    original = MutableText("same scalar contents")
    original.details = {"events": []}
    assert operator.eq(type(original), str)
    assert type(original) is not str

    copied = sdk._observation_copy(original)

    assert type(copied) is MutableText
    assert copied is not original
    assert copied.details is not original.details
    copied.details["events"].append("copy")
    assert original.details == {"events": []}


def test_exact_scalars_never_reach_deepcopy_but_custom_values_still_do(monkeypatch):
    class CustomValue:
        def __init__(self):
            self.details = ["independent"]

    original = CustomValue()
    fallback_values = []

    def checked_deepcopy(value, memo):
        assert value is not None
        assert all(type(value) is not scalar for scalar in (str, bytes, int, float, bool))
        fallback_values.append(value)
        return deepcopy(value, memo)

    monkeypatch.setattr(sdk, "deepcopy", checked_deepcopy)
    copied = sdk._observation_copy({"values": [None, "雪", b"bytes", 2**80, -0.0,
                                              float("nan"), True, False],
                                    "custom": original})

    assert len(fallback_values) == 1 and fallback_values[0] is original
    assert copied["custom"] is not original
    assert copied["custom"].details is not original.details
    assert copied["values"][0] is None
    assert math.isnan(copied["values"][5])
