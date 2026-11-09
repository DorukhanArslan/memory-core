"""Exact ordinary ranking registrations; no SDK or native execution owner.

Family identities and insertion-ordered input wire hashes were read from the
unchanged genuine corrected-sixteen report, never from the current builder.
This is a pre-execution claim guard, not a substitute for source/runtime proof.
"""
from __future__ import annotations

import hashlib
import json


PROMOTION_RANKING_REQUIREMENT = "promotion.ranking-gates"
PROMOTION_RANKING_OPERATION = "promotion-ranking-runtime"
PROMOTION_RANKING_OUTCOMES = "promotion.ranking-gates.outcomes"
PROMOTION_RANKING_BOUNDARIES = "promotion.ranking-gates.boundaries"
PROMOTION_RANKING_PRIMITIVE_CASE_ID = "promotion-ranking-primitive-provenance-safety-diagnostic"
PROMOTION_RANKING_FROZEN_REPORT_SHA256 = "57431cdc8025593e342b97fc4f29d1d17a6a827495e47d994fb78440746342e3"
PROMOTION_RANKING_FROZEN_SOURCE_COMMIT = "f3d23635dd9866e8678515396c72489fc43ea1f8"

# All fifteen proper-object families jointly qualify the outcomes condition.
PROMOTION_RANKING_OUTCOMES_REQUIRED_CASE_IDS = (
    'promotion-ranking-signals-and-components',
    'promotion-ranking-custom-weights',
    'promotion-ranking-score-boundary',
    'promotion-ranking-frequency-boundary',
    'promotion-ranking-diversity-and-age',
    'promotion-ranking-tie-order-and-limit',
    'promotion-ranking-origin-and-promoted-visibility',
    'promotion-ranking-path-and-transcript-gates',
    'promotion-ranking-phase-boost',
    'promotion-ranking-multiline-store-diagnostic',
    'promotion-ranking-equal-path-stability-diagnostic',
    'promotion-ranking-old-phase-diagnostic',
    'promotion-ranking-limit-boundaries',
    'promotion-ranking-numeric-gate-normalization',
    'promotion-ranking-current-default-query-diversity',
)

# The known primitive-provenance mismatch must remain in the boundary family.
PROMOTION_RANKING_BOUNDARIES_REQUIRED_CASE_IDS = (
    'promotion-ranking-signals-and-components',
    'promotion-ranking-custom-weights',
    'promotion-ranking-score-boundary',
    'promotion-ranking-frequency-boundary',
    'promotion-ranking-diversity-and-age',
    'promotion-ranking-tie-order-and-limit',
    'promotion-ranking-origin-and-promoted-visibility',
    'promotion-ranking-path-and-transcript-gates',
    'promotion-ranking-phase-boost',
    'promotion-ranking-multiline-store-diagnostic',
    'promotion-ranking-equal-path-stability-diagnostic',
    'promotion-ranking-old-phase-diagnostic',
    'promotion-ranking-limit-boundaries',
    'promotion-ranking-primitive-provenance-safety-diagnostic',
    'promotion-ranking-numeric-gate-normalization',
    'promotion-ranking-current-default-query-diversity',
)

# ASCII compact JSON; original object/entry order, no sort_keys, no normalization.
PROMOTION_RANKING_INPUT_WIRE_SHA256 = {
    'promotion-ranking-signals-and-components': '7389279b8620fe067f894d29e9ff2e4ef30c10b22c3b0601e60a116506fbb29d',
    'promotion-ranking-custom-weights': '120724cf9a2e43198452e551881f2eff0dc99e3b823225f9db2e1fb82f2cf211',
    'promotion-ranking-score-boundary': 'dd8d9f126b3f62bcd3c34be6f5fc1316e5ff0ed5e8f12a1ad318d9352c541162',
    'promotion-ranking-frequency-boundary': '82f598050836fa8b1ef640fb73e8015794fcaa4ec8dff6e6a2f15c48d6880b2d',
    'promotion-ranking-diversity-and-age': '33a04208f0d9f112e99c3dd75291e3d8fe2677b26583860dedd623beff05554c',
    'promotion-ranking-tie-order-and-limit': 'f083a559ada54d303428860df3f4fdf5bee0abe97b9c6a0d603edfd9bbdd56fb',
    'promotion-ranking-origin-and-promoted-visibility': 'af81b02bf129a30ca994d48aafe7765c6d337f75ae06e94f22f2054675326c26',
    'promotion-ranking-path-and-transcript-gates': 'fda502dfa4be368259703bf1c4d82bb69bfc6ebedc0765a868c4a7a1773094ac',
    'promotion-ranking-phase-boost': 'bf0f02873256669d4ec60aacda10380e0228f7a46499848c1f976e4bda88f561',
    'promotion-ranking-multiline-store-diagnostic': 'a47d1205c69f9cd0c6c4aecc9087ce1677caeb36a6f3f77630c39a271634777f',
    'promotion-ranking-equal-path-stability-diagnostic': '7fe142182191ceaed1589ce52ee5df0e2b2da5716186c73b0da6e98dc623f8a0',
    'promotion-ranking-old-phase-diagnostic': 'ff5df6ca9e975e419a1158a943f465a2900576cdf11a1ba65bc656dff8199e0f',
    'promotion-ranking-limit-boundaries': '1da91cd0bbe2130935e92e229f14cea1ed10045743ed415db3abe7155f1aecbb',
    'promotion-ranking-primitive-provenance-safety-diagnostic': '4053cf6b3a513b4702dd5e28c7f88966b0e93aef9bf4edaa44e46709b6c4a173',
    'promotion-ranking-numeric-gate-normalization': '6cdc3f9d68a1328cb74d9dc81a4a3078bc3f23b416def51d92c8cc00074092dd',
    'promotion-ranking-current-default-query-diversity': '00f8c1e860e5632edb7a13d3b360aaa235c7a94832dfa608f55f70ddb4e941d8',
}


def promotion_ranking_input_wire_sha256(value: object) -> str:
    """Hash standard JSON while preserving field order and exact UTF-16 units.

    ASCII escaping gives an astral character and its explicit surrogate pair
    the same JSON wire units. Integer/float spellings, array/object order and
    field presence remain visible. No sorting or Unicode normalization occurs.
    """
    def standard_json(item: object) -> bool:
        if item is None or type(item) in (str, bool, int, float):
            return True
        if type(item) is list:
            return all(standard_json(child) for child in item)
        if type(item) is dict:
            return all(type(key) is str and standard_json(child) for key, child in item.items())
        return False

    try:
        valid = standard_json(value)
    except RecursionError as error:
        raise ValueError("Ranking claims require ordinary acyclic JSON input wire values") from error
    if not valid:
        raise ValueError("Ranking claims require ordinary JSON input wire values")
    try:
        wire = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    except (ValueError, OverflowError, RecursionError) as error:
        raise ValueError("Ranking claims require finite standard JSON input wire values") from error
    return hashlib.sha256(wire).hexdigest()


def promotion_ranking_coverage(case_id: str) -> list[str]:
    """Return the approved exact tag map; primitive provenance stays boundary-only."""
    if case_id in PROMOTION_RANKING_OUTCOMES_REQUIRED_CASE_IDS:
        return [PROMOTION_RANKING_OUTCOMES, PROMOTION_RANKING_BOUNDARIES]
    if case_id == PROMOTION_RANKING_PRIMITIVE_CASE_ID:
        return [PROMOTION_RANKING_BOUNDARIES]
    raise ValueError("An undeclared ranking family cannot claim a qualified point")


def validate_promotion_ranking_acceptance(cases: list[dict]) -> None:
    """Require both complete families whenever either ranking point is claimed.

    Historical or custom smoke cases with no ranking coverage remain usable.
    A claim cannot hide the deliberate primitive boundary mismatch, remove an
    entire tag family, replace a case, or alter its original ordered input wire.
    This function neither changes cases nor interprets their comparison results.
    """
    points = {PROMOTION_RANKING_OUTCOMES, PROMOTION_RANKING_BOUNDARIES}
    claiming = [case for case in cases if points.intersection(case.get("covers", []))]
    if not claiming:
        return
    expected = set(PROMOTION_RANKING_BOUNDARIES_REQUIRED_CASE_IDS)
    registered = [case for case in cases if case.get("id") in expected]
    if ({case.get("id") for case in claiming} != expected or len(claiming) != len(expected)
            or len(registered) != len(expected)):
        raise ValueError("A ranking point claim requires all sixteen fixed families, including the primitive boundary mismatch")
    for case in claiming:
        case_id = case["id"]
        if case.get("requirement") != PROMOTION_RANKING_REQUIREMENT or case.get("operation") != PROMOTION_RANKING_OPERATION:
            raise ValueError("A ranking point claim substituted another requirement or execution owner")
        if case.get("covers") != promotion_ranking_coverage(case_id):
            raise ValueError("Ranking claims must retain all fifteen outcomes and all sixteen boundary tags")
        if promotion_ranking_input_wire_sha256(case.get("input")) != PROMOTION_RANKING_INPUT_WIRE_SHA256[case_id]:
            raise ValueError("A ranking point claim changed the frozen insertion-ordered input wire")
