"""Original Node24 binary64 observations, including platform-libm differences."""
import math
import struct

import pytest

from memory_core.index._js_log1p import log1p


@pytest.mark.parametrize(("input_bits", "output_bits"), [
    ("0000000000000000", "0000000000000000"),
    ("8000000000000000", "8000000000000000"),
    ("bff0000000000000", "fff0000000000000"),
    ("bfefffffffffffff", "c0425e4f7b2737fa"),
    ("bfe0000000000000", "bfe62e42fefa39ef"),
    ("3fb999999999999a", "3fb8663f793c46c7"),
    ("3fd0000000000000", "3fcc8ff7c79a9a22"),
    ("3fe0000000000000", "3fd9f323ecbf984c"),
    ("3ff0000000000000", "3fe62e42fefa39ef"),
    ("4000000000000000", "3ff193ea7aad030a"),
    ("4008000000000000", "3ff62e42fefa39ef"),
    ("4010000000000000", "3ff9c041f7ed8d33"),
    ("4018000000000000", "3fff2272ae325a57"),
    ("4024000000000000", "40032ee3b77f374c"),
    ("4080000000000000", "4018f60adf041bde"),
    ("7fefffffffffffff", "40862e42fefa39ef"),
    ("4065e00000000000", "4014ae935b3cb89e"),
    ("4067000000000000", "4014e1a4f518c72b"),
])
def test_original_logarithm_preserves_the_complete_binary64_result(input_bits, output_bits):
    value = struct.unpack(">d", bytes.fromhex(input_bits))[0]
    assert struct.pack(">d", log1p(value)).hex() == output_bits


@pytest.mark.parametrize("value", [-math.inf, -2.0, math.nan])
def test_original_logarithm_keeps_invalid_domain_outcomes(value):
    assert math.isnan(log1p(value))


def test_original_logarithm_keeps_positive_infinity():
    assert log1p(math.inf) == math.inf
