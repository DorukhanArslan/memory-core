from __future__ import annotations

from typing import Any

from demo.openclaw_oracle import OpenClawOracle
from demo.short_term_promotion import (
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
)


def diff_values(python_values: dict[str, Any], openclaw_values: dict[str, Any]) -> dict[str, Any]:
    details: list[str] = []
    for key in sorted(set(python_values) | set(openclaw_values)):
        left = python_values.get(key)
        right = openclaw_values.get(key)
        if left != right:
            details.append(f"{key}: python={left} openclaw={right}")
    return {"status": "match" if not details else "mismatch", "details": details}


def build_deep_policy_trace(oracle: OpenClawOracle | Any | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    python_values = {
        "minScore": DEFAULT_PROMOTION_MIN_SCORE,
        "minRecallCount": DEFAULT_PROMOTION_MIN_RECALL_COUNT,
        "minUniqueQueries": DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        "maxAgeDays": None,
    }
    oracle_result = oracle.run({"operation": "deepPolicy", "config": {}})
    if not oracle_result.get("ok"):
        return {
            "id": "deep-policy",
            "label": "Deep dreaming policy values",
            "python": {"decision": "available", "values": python_values, "reasons": []},
            "openclaw": {
                "decision": "error",
                "values": {},
                "reasons": [oracle_result.get("error", {}).get("message", "oracle error")],
            },
            "diff": {"status": "error", "details": [oracle_result.get("error", {})]},
        }
    openclaw_values = {
        "minScore": oracle_result["result"].get("minScore"),
        "minRecallCount": oracle_result["result"].get("minRecallCount"),
        "minUniqueQueries": oracle_result["result"].get("minUniqueQueries"),
        "maxAgeDays": oracle_result["result"].get("maxAgeDays"),
    }
    return {
        "id": "deep-policy",
        "label": "Deep dreaming policy values",
        "condition": "score >= minScore && signals >= minRecallCount && contextDiversity >= minUniqueQueries && ageDays <= maxAgeDays",
        "python": {"decision": "computed", "values": python_values, "reasons": []},
        "openclaw": {"decision": "computed", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


def build_parity_trace(oracle: OpenClawOracle | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    return {
        "oracle": oracle.metadata(),
        "steps": [
            build_deep_policy_trace(oracle),
        ],
    }
