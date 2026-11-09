"""Binary64 log1p used by the pinned V8 promotion score gates.

Translated without result correction from Node.js v24.16.0, commit
``c7d10158bc31036de6783d66beaaaf551e3167aa``,
``deps/v8/src/base/ieee754.cc`` lines 1783–1879, source SHA-256
``1bf999809d4c4c1d31ad5ff3578d32614796f159e08b9e7782560d017721a0c2``.

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

import math
import struct


_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_LP1 = 6.666666666666735130e-01
_LP2 = 3.999999999940941908e-01
_LP3 = 2.857142874366239149e-01
_LP4 = 2.222219843214978396e-01
_LP5 = 1.818357216161805012e-01
_LP6 = 1.531383769920937332e-01
_LP7 = 1.479819860511658591e-01


def _high(value: float) -> int:
    return struct.unpack(">i", struct.pack(">d", value)[:4])[0]


def _with_high(value: float, high: int) -> float:
    return struct.unpack(">d", struct.pack(">I", high) + struct.pack(">d", value)[4:])[0]


def log1p(x: float) -> float:
    """Return the original V8 logarithm, including its boundary semantics."""
    hx = _high(x)
    ax = hx & 0x7FFFFFFF
    k = 1
    c = 0.0
    if hx < 0x3FDA827A:
        if ax >= 0x3FF00000:
            return -math.inf if x == -1.0 else math.nan
        if ax < 0x3E200000:
            if 1.80143985094819840000e16 + x > 0.0 and ax < 0x3C900000:
                return x
            return x - x * x * 0.5
        if hx > 0 or hx <= -1076707644:  # signed int32 0xBFD2BEC4
            k, f, hu = 0, x, 1
    if hx >= 0x7FF00000:
        return x + x
    if k != 0:
        if hx < 0x43400000:
            u = 1.0 + x
            hu = _high(u)
            k = (hu >> 20) - 1023
            c = (1.0 - (u - x)) if k > 0 else x - (u - 1.0)
            c /= u
        else:
            u = x
            hu = _high(u)
            k = (hu >> 20) - 1023
            c = 0.0
        hu &= 0x000FFFFF
        if hu < 0x6A09E:
            u = _with_high(u, hu | 0x3FF00000)
        else:
            k += 1
            u = _with_high(u, hu | 0x3FE00000)
            hu = (0x00100000 - hu) >> 2
        f = u - 1.0
    hfsq = 0.5 * f * f
    if hu == 0:
        if f == 0.0:
            if k == 0:
                return 0.0
            c += k * _LN2_LO
            return k * _LN2_HI + c
        r = hfsq * (1.0 - 0.66666666666666666 * f)
        if k == 0:
            return f - r
        return k * _LN2_HI - ((r - (k * _LN2_LO + c)) - f)
    s = f / (2.0 + f)
    z = s * s
    r = z * (_LP1 + z * (_LP2 + z * (_LP3 + z * (_LP4 + z * (_LP5 + z * (_LP6 + z * _LP7))))))
    if k == 0:
        return f - (hfsq - s * (hfsq + r))
    return k * _LN2_HI - ((hfsq - (s * (hfsq + r) + (k * _LN2_LO + c))) - f)
