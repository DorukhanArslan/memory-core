"""Proposed fixed #43 literals. No expected result or coverage is supplied."""
from copy import deepcopy


def build_promotion_apply_reconcile_cases():
    path = "memory/2026-05-08.md"
    key = f"memory:{path}:3:3"
    candidate = {
        "key": key,
        "path": path,
        "startLine": 3,
        "endLine": 3,
        "source": "memory",
        "snippet": "- A durable bright kumquat tea preference.",
        "recallCount": 4,
        "dailyCount": 0,
        "groundedCount": 0,
        "signalCount": 4,
        "avgScore": 0.9,
        "maxScore": 1,
        "uniqueQueries": 3,
        "firstRecalledAt": "2026-05-20T16:00:00.000Z",
        "lastRecalledAt": "2026-05-25T16:00:00.000Z",
        "ageDays": 1,
        "score": 0.875,
        "recallDays": ["2026-05-21", "2026-05-22", "2026-05-23"],
        "conceptTags": [],
        "components": {
            "frequency": 0.5,
            "relevance": 0.9,
            "diversity": 0.6,
            "recency": 0.9,
            "consolidation": 0.5,
            "conceptual": 0,
        },
        "provenance": {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1},
    }
    entry_fields = (
        "key", "path", "startLine", "endLine", "source", "snippet", "recallCount",
        "dailyCount", "groundedCount", "maxScore", "firstRecalledAt", "lastRecalledAt",
        "recallDays", "conceptTags", "provenance",
    )
    value = {
        "kind": "promotion-apply-reconcile",
        "nowMs": 1779811200000,
        "directories": ["MEMORY.md"],
        "files": {},
        "recall": {
            "version": 1,
            "updatedAt": "2026-05-26T16:00:00.000Z",
            "entries": {
                key: {
                    **{field: deepcopy(candidate[field]) for field in entry_fields},
                    "totalScore": 3.6,
                    "queryHashes": ["a1", "a2", "a3"],
                    "userQueryHashes": ["a1", "a2", "a3"],
                },
            },
        },
        "candidates": [candidate],
        "options": {
            "timezone": "UTC",
            "memoryFileMaxChars": 10000,
            "maxPriorEntryLossFraction": 0.25,
            "minScore": 0,
            "minRecallCount": 0,
            "minUniqueQueries": 0,
            "limit": 5,
        },
    }
    return [{
        "id": "promotion-apply-zero-rehydrated-directory-memory",
        "requirement": "promotion.apply-reconcile",
        "covers": [],
        "operation": "promotion-apply-reconcile-runtime",
        "input": deepcopy(value),
        "driverScope": (
            "Proposed before diagnostic: one real canonical recalled candidate whose source is "
            "absent, with MEMORY.md an actual empty directory. Original whole apply and the "
            "real SDK promotion owner receive the same literal candidate/options. No model, "
            "expected return, fabricated rejection, filesystem read result, or lock result is supplied."
        ),
    }]
