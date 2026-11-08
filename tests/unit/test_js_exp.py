"""Captured V8 binary64 regressions; the SDK does not require Node to run them."""
import math
import struct

import pytest

from memory_core.index._js_exp import exp


# Actual Node.js v24.16.0 Math.exp outputs. The broader diagnostic compares
# 11,503 deterministic inputs directly with that runtime, without tolerance.
@pytest.mark.parametrize("input_bits,output_bits", [
    pytest.param("0000000000000000", "3ff0000000000000", id="zero"),
    pytest.param("8000000000000000", "3ff0000000000000", id="negative-zero"),
    pytest.param("be30000000000000", "3feffffffe000000", id="small-range-boundary"),
    pytest.param("bfd62e42fefa39ef", "3fe6a09e667f3bcc", id="half-ln2-platform-libm-difference"),
    pytest.param("bfd62e42ffffffff", "3fe6a09e6622aec0", id="below-highword-reduction-boundary"),
    pytest.param("bfd62e4300000000", "3fe6a09e6622aec0", id="above-highword-reduction-boundary"),
    pytest.param("bff0a2b200000000", "3fd6a09ebfec0ef1", id="multi-ln2-range-reduction"),
    pytest.param("3ff0000000000000", "4005bf0a8b145769", id="positive-one-source-special-case"),
    pytest.param("c086232bdd7abcd2", "001000000000007c", id="normal-subnormal-scale-boundary"),
    pytest.param("c0874910d52d3051", "0000000000000001", id="last-subnormal"),
    pytest.param("c0874910d52d3052", "0000000000000000", id="underflow"),
    pytest.param("40862e42fefa39f0", "7ff0000000000000", id="overflow"),
    pytest.param("fff0000000000000", "0000000000000000", id="negative-infinity"),
    pytest.param("7ff0000000000000", "7ff0000000000000", id="positive-infinity"),
])
def test_exponential_preserves_native_binary64_branch_results(input_bits, output_bits):
    value = struct.unpack(">d", bytes.fromhex(input_bits))[0]
    assert struct.pack(">d", exp(value)).hex() == output_bits


def test_nan_stays_nan_without_a_platform_libm_call():
    assert math.isnan(exp(math.nan))
