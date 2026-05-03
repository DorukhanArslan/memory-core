from __future__ import annotations

import math
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for av, bv in zip(a, b, strict=True):
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
