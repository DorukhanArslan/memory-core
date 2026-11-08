"""Binary64 exponential used by the pinned V8 temporal-ranking reference.

Translated from ``exp`` in Node.js v24.16.0's
``deps/v8/src/base/ieee754.cc`` (lines 1447–1560), preserving each floating-point
operation and range-reduction branch. The source belongs to commit
``c7d10158bc31036de6783d66beaaaf551e3167aa`` and has SHA-256
``1bf999809d4c4c1d31ad5ff3578d32614796f159e08b9e7782560d017721a0c2``.

This private helper keeps temporal score/threshold decisions independent of the
platform C math library. It requires no JavaScript runtime.

The following is adapted from fdlibm (http://www.netlib.org/fdlibm).

Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.

Developed at SunSoft, a Sun Microsystems, Inc. business.
Permission to use, copy, modify, and distribute this
software is freely granted, provided that this notice
is preserved.

The original source code covered by the above license has been modified
significantly by Google Inc.
Copyright 2016 the V8 project authors. All rights reserved.

Copyright 2014, the V8 project authors. All rights reserved.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
      copyright notice, this list of conditions and the following
      disclaimer in the documentation and/or other materials provided
      with the distribution.
    * Neither the name of Google Inc. nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
from __future__ import annotations

import struct


_LN2_HIGH = (6.93147180369123816490e-01, -6.93147180369123816490e-01)
_LN2_LOW = (1.90821492927058770002e-10, -1.90821492927058770002e-10)
_INVERSE_LN2 = 1.44269504088896338700e+00
_P1 = 1.66666666666666019037e-01
_P2 = -2.77777777770155933842e-03
_P3 = 6.61375632143793436117e-05
_P4 = -1.65339022054652515390e-06
_P5 = 4.13813679705723846039e-08
_HUGE = 1.0e300
_TWO_MINUS_1000 = 9.33263618503218878990e-302
_TWO_1023 = 8.988465674311579539e307


def _power_of_two(exponent: int) -> float:
    return struct.unpack(">d", struct.pack(">Q", (1023 + exponent) << 52))[0]


def exp(x: float) -> float:
    """Return the original V8 fdlibm exponential, without result correction."""
    high, low = struct.unpack(">II", struct.pack(">d", x))
    sign = (high >> 31) & 1
    high &= 0x7FFFFFFF
    if high >= 0x40862E42:
        if high >= 0x7FF00000:
            if (high & 0xFFFFF) | low:
                return x + x
            return x if sign == 0 else 0.0
        if x > 7.09782712893383973096e02:
            return _HUGE * _HUGE
        if x < -7.45133219101941108420e02:
            return _TWO_MINUS_1000 * _TWO_MINUS_1000

    k = 0
    hi = 0.0
    lo = 0.0
    if high > 0x3FD62E42:
        if high < 0x3FF0A2B2:
            if x == 1.0:
                return 2.718281828459045
            hi = x - _LN2_HIGH[sign]
            lo = _LN2_LOW[sign]
            k = 1 - sign - sign
        else:
            k = int(_INVERSE_LN2 * x + (0.5, -0.5)[sign])
            t = float(k)
            hi = x - t * _LN2_HIGH[0]
            lo = t * _LN2_LOW[0]
        x = hi - lo
    elif high < 0x3E300000:
        if _HUGE + x > 1.0:
            return 1.0 + x

    t = x * x
    two_k = _power_of_two(k if k >= -1021 else k + 1000)
    c = x - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    if k == 0:
        return 1.0 - ((x * c) / (c - 2.0) - x)
    y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi)
    if k >= -1021:
        if k == 1024:
            return y * 2.0 * _TWO_1023
        return y * two_k
    return y * two_k * _TWO_MINUS_1000
