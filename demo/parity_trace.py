from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from demo.openclaw_oracle import OpenClawOracle
from demo.short_term_promotion import (
    DEFAULT_DEEP_DREAMING_ENABLED,
    DEFAULT_DEEP_DREAMING_LIMIT,
    DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    SHORT_TERM_STORE_RELATIVE_PATH,
    rank_short_term_promotion_candidates,
    record_short_term_recalls,
)
from memory_core.config import MemoryConfig

DEEP_POLICY_CONDITION = (
    "score >= minScore && signals >= minRecallCount && "
    "contextDiversity >= minUniqueQueries && ageDays <= maxAgeDays"
)
CONFIGURED_DEEP_POLICY_CONFIG = {
    "plugins": {
        "entries": {
            "memory-core": {
                "config": {
                    "dreaming": {
                        "enabled": True,
                        "phases": {
                            "deep": {
                                "enabled": True,
                                "limit": 7,
                                "minScore": 0.72,
                                "minRecallCount": 4,
                                "minUniqueQueries": 2,
                                "maxAgeDays": 14,
                                "recencyHalfLifeDays": 10,
                            }
                        },
                    }
                }
            }
        }
    }
}
RECALL_QUERY = "address preference"
RECALL_RESULT = {
    "source": "memory",
    "path": "memory/2026-05-26.md",
    "startLine": 3,
    "endLine": 3,
    "snippet": "- User prefers to be addressed as dodo.",
    "score": 1,
}
RECALL_NOW_MS = 1779811200000
RECALL_TIMEZONE = "Europe/Istanbul"
RECALL_STORE_PATH = SHORT_TERM_STORE_RELATIVE_PATH.as_posix()
RECALL_CONDITION = 'result.source === "memory" && isShortTermMemoryPath(result.path)'
REPEATED_RECALL_NOW_MS = 1779897600000
REPEATED_RECALL_QUERY = "preferred name"
NON_MEMORY_RECALL_RESULT = {
    "source": "workspace",
    "path": "notes.md",
    "startLine": 1,
    "endLine": 1,
    "snippet": "Ignore this non-memory result.",
    "score": 1,
}
RANKING_NOW_MS = RECALL_NOW_MS + 4 * 86_400_000
RANKING_QUERIES = [
    "address preference",
    "preferred name",
    "user salutation",
    "name preference",
    "how to address user",
]


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
    python_values = _python_deep_policy_values({})
    try:
        oracle_result = oracle.run({"operation": "deepPolicy", "config": {}})
    except Exception as exc:
        oracle_result = {"ok": False, "error": {"message": str(exc)}}
    if not oracle_result.get("ok"):
        error = oracle_result.get("error", {})
        message = (
            error.get("message", "oracle error")
            if isinstance(error, dict)
            else "oracle error"
        )
        return _deep_policy_error_trace(python_values, message, error)
    oracle_result_values = oracle_result.get("result")
    if not isinstance(oracle_result_values, dict):
        error = {"message": "invalid oracle result"}
        return _deep_policy_error_trace(python_values, error["message"], error)
    openclaw_values = _select_deep_policy_values(oracle_result_values)
    return {
        "id": "deep-policy",
        "label": "Deep dreaming policy values",
        "condition": DEEP_POLICY_CONDITION,
        "python": {"decision": "computed", "values": python_values, "reasons": []},
        "openclaw": {"decision": "computed", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


def build_configured_deep_policy_trace(oracle: OpenClawOracle | Any | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    python_values = _python_deep_policy_values(CONFIGURED_DEEP_POLICY_CONFIG)
    try:
        oracle_result = oracle.run(
            {"operation": "deepPolicy", "config": CONFIGURED_DEEP_POLICY_CONFIG}
        )
    except Exception as exc:
        oracle_result = {"ok": False, "error": {"message": str(exc)}}
    if not oracle_result.get("ok"):
        error = oracle_result.get("error", {})
        message = (
            error.get("message", "oracle error")
            if isinstance(error, dict)
            else "oracle error"
        )
        return _configured_deep_policy_error_trace(python_values, message, error)
    oracle_result_values = oracle_result.get("result")
    if not isinstance(oracle_result_values, dict):
        error = {"message": "invalid oracle result"}
        return _configured_deep_policy_error_trace(python_values, error["message"], error)
    openclaw_values = _select_deep_policy_values(oracle_result_values)
    return {
        "id": "configured-deep-policy",
        "label": "Configured deep dreaming policy values",
        "condition": "config.plugins.entries.memory-core.config.dreaming.phases.deep",
        "python": {"decision": "computed", "values": python_values, "reasons": []},
        "openclaw": {"decision": "computed", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


def _python_deep_policy_values(config: dict[str, Any]) -> dict[str, Any]:
    plugin_config = _memory_core_plugin_config(config)
    dreaming = _as_dict(plugin_config.get("dreaming"))
    phases = _as_dict(dreaming.get("phases"))
    deep = _as_dict(phases.get("deep"))
    dreaming_enabled = _bool(dreaming.get("enabled"), DEFAULT_DEEP_DREAMING_ENABLED)
    deep_enabled = _bool(deep.get("enabled"), True)
    return {
        "minScore": _float(deep.get("minScore"), DEFAULT_PROMOTION_MIN_SCORE),
        "minRecallCount": _non_negative_int(
            deep.get("minRecallCount"), DEFAULT_PROMOTION_MIN_RECALL_COUNT
        ),
        "minUniqueQueries": _non_negative_int(
            deep.get("minUniqueQueries"), DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES
        ),
        "maxAgeDays": _positive_int(
            deep.get("maxAgeDays"), DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS
        ),
        "enabled": dreaming_enabled and deep_enabled,
        "limit": _non_negative_int(deep.get("limit"), DEFAULT_DEEP_DREAMING_LIMIT),
        "recencyHalfLifeDays": _non_negative_int(
            deep.get("recencyHalfLifeDays"), DEFAULT_RECENCY_HALF_LIFE_DAYS
        ),
    }


def _memory_core_plugin_config(config: dict[str, Any]) -> dict[str, Any]:
    plugins = _as_dict(config.get("plugins"))
    entries = _as_dict(plugins.get("entries"))
    memory_core = _as_dict(entries.get("memory-core"))
    return _as_dict(memory_core.get("config")) or config


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _select_deep_policy_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "minScore": values.get("minScore"),
        "minRecallCount": values.get("minRecallCount"),
        "minUniqueQueries": values.get("minUniqueQueries"),
        "maxAgeDays": values.get("maxAgeDays"),
        "enabled": values.get("enabled"),
        "limit": values.get("limit"),
        "recencyHalfLifeDays": values.get("recencyHalfLifeDays"),
    }


def _bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return fallback


def _non_negative_int(value: Any, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def _deep_policy_error_trace(
    python_values: dict[str, Any], message: str, error: dict[str, Any] | Any
) -> dict[str, Any]:
    return {
        "id": "deep-policy",
        "label": "Deep dreaming policy values",
        "condition": DEEP_POLICY_CONDITION,
        "python": {"decision": "available", "values": python_values, "reasons": []},
        "openclaw": {
            "decision": "error",
            "values": {},
            "reasons": [message],
        },
        "diff": {"status": "error", "details": [error]},
    }


def _configured_deep_policy_error_trace(
    python_values: dict[str, Any], message: str, error: dict[str, Any] | Any
) -> dict[str, Any]:
    return {
        "id": "configured-deep-policy",
        "label": "Configured deep dreaming policy values",
        "condition": "config.plugins.entries.memory-core.config.dreaming.phases.deep",
        "python": {"decision": "available", "values": python_values, "reasons": []},
        "openclaw": {
            "decision": "error",
            "values": {},
            "reasons": [message],
        },
        "diff": {"status": "error", "details": [error]},
    }


def build_recall_tracking_trace(oracle: OpenClawOracle | Any) -> dict[str, Any]:
    with (
        tempfile.TemporaryDirectory(prefix="memory-core-python-recall-") as python_dir,
        tempfile.TemporaryDirectory(prefix="memory-core-openclaw-recall-") as oracle_dir,
    ):
        python_workspace = Path(python_dir)
        oracle_workspace = Path(oracle_dir)
        _seed_recall_workspace(python_workspace)
        _seed_recall_workspace(oracle_workspace)
        record_short_term_recalls(
            config=MemoryConfig(workspace_dir=python_workspace),
            query=RECALL_QUERY,
            results=[RECALL_RESULT],
            now_ms=RECALL_NOW_MS,
        )
        try:
            python_values = _recall_values_from_files(
                _snapshot_recall_files(python_workspace),
                query=RECALL_QUERY,
                result=RECALL_RESULT,
            )
        except Exception as exc:
            error = {"message": f"invalid python fixture: {exc}"}
            return _recall_tracking_error_trace({}, error["message"], error)

        try:
            oracle_result = oracle.run(
                {
                    "operation": "recordShortTermRecalls",
                    "query": RECALL_QUERY,
                    "results": [RECALL_RESULT],
                    "nowMs": RECALL_NOW_MS,
                    "timezone": RECALL_TIMEZONE,
                    "workspaceDir": str(oracle_workspace),
                }
            )
        except Exception as exc:
            oracle_result = {"ok": False, "error": {"message": str(exc)}}

    if not isinstance(oracle_result, dict):
        error = {"message": "invalid oracle result"}
        return _recall_tracking_error_trace(python_values, error["message"], error)
    if not oracle_result.get("ok"):
        error = oracle_result.get("error", {})
        message = (
            error.get("message", "oracle error")
            if isinstance(error, dict)
            else "oracle error"
        )
        return _recall_tracking_error_trace(python_values, message, error)
    try:
        openclaw_values = _recall_values_from_files(
            oracle_result.get("files"),
            query=RECALL_QUERY,
            result=RECALL_RESULT,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        error = {"message": "invalid oracle result", "details": str(exc)}
        return _recall_tracking_error_trace(python_values, error["message"], error)
    return {
        "id": "recall-tracking",
        "label": "Recall tracking from memory_search",
        "condition": RECALL_CONDITION,
        "python": {
            "decision": "recordable",
            "values": python_values,
            "reasons": [],
        },
        "openclaw": {
            "decision": "recorded",
            "values": openclaw_values,
            "reasons": [],
        },
        "diff": diff_values(python_values, openclaw_values),
    }


def build_repeated_recall_tracking_trace(oracle: OpenClawOracle | Any) -> dict[str, Any]:
    recalls = [
        {"query": RECALL_QUERY, "results": [RECALL_RESULT], "nowMs": RECALL_NOW_MS},
        {
            "query": REPEATED_RECALL_QUERY,
            "results": [RECALL_RESULT, NON_MEMORY_RECALL_RESULT],
            "nowMs": REPEATED_RECALL_NOW_MS,
        },
    ]
    with (
        tempfile.TemporaryDirectory(prefix="memory-core-python-recall-sequence-") as python_dir,
        tempfile.TemporaryDirectory(prefix="memory-core-openclaw-recall-sequence-") as oracle_dir,
    ):
        python_workspace = Path(python_dir)
        oracle_workspace = Path(oracle_dir)
        _seed_recall_workspace(python_workspace)
        _seed_recall_workspace(oracle_workspace)
        for recall in recalls:
            record_short_term_recalls(
                config=MemoryConfig(workspace_dir=python_workspace),
                query=recall["query"],
                results=recall["results"],
                now_ms=recall["nowMs"],
            )
        try:
            python_values = _recall_values_from_files(
                _snapshot_recall_files(python_workspace),
                query=REPEATED_RECALL_QUERY,
                result=RECALL_RESULT,
            )
        except Exception as exc:
            error = {"message": f"invalid python fixture: {exc}"}
            return _recall_tracking_error_trace({}, error["message"], error)

        try:
            oracle_result = oracle.run(
                {
                    "operation": "recordShortTermRecallSequence",
                    "recalls": recalls,
                    "timezone": RECALL_TIMEZONE,
                    "workspaceDir": str(oracle_workspace),
                }
            )
        except Exception as exc:
            oracle_result = {"ok": False, "error": {"message": str(exc)}}

    if not isinstance(oracle_result, dict):
        error = {"message": "invalid oracle result"}
        return _recall_tracking_error_trace(python_values, error["message"], error)
    if not oracle_result.get("ok"):
        error = oracle_result.get("error", {})
        message = (
            error.get("message", "oracle error")
            if isinstance(error, dict)
            else "oracle error"
        )
        return _recall_tracking_error_trace(python_values, message, error)
    try:
        openclaw_values = _recall_values_from_files(
            oracle_result.get("files"),
            query=REPEATED_RECALL_QUERY,
            result=RECALL_RESULT,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        error = {"message": "invalid oracle result", "details": str(exc)}
        return _recall_tracking_error_trace(python_values, error["message"], error)
    return {
        "id": "repeated-recall-tracking",
        "label": "Repeated recall tracking and non-memory filtering",
        "condition": (
            "two recordShortTermRecalls calls update one memory entry; "
            "non-memory results are ignored"
        ),
        "python": {
            "decision": "recordable",
            "values": python_values,
            "reasons": [],
        },
        "openclaw": {
            "decision": "recorded",
            "values": openclaw_values,
            "reasons": [],
        },
        "diff": diff_values(python_values, openclaw_values),
    }


def build_promotion_ranking_trace(oracle: OpenClawOracle | Any) -> dict[str, Any]:
    recalls = [
        {"query": query, "results": [RECALL_RESULT], "nowMs": RECALL_NOW_MS + index * 86_400_000}
        for index, query in enumerate(RANKING_QUERIES)
    ]
    with (
        tempfile.TemporaryDirectory(prefix="memory-core-python-ranking-") as python_dir,
        tempfile.TemporaryDirectory(prefix="memory-core-openclaw-ranking-") as oracle_dir,
    ):
        python_workspace = Path(python_dir)
        oracle_workspace = Path(oracle_dir)
        _seed_recall_workspace(python_workspace)
        _seed_recall_workspace(oracle_workspace)
        for recall in recalls:
            record_short_term_recalls(
                config=MemoryConfig(workspace_dir=python_workspace),
                query=recall["query"],
                results=recall["results"],
                now_ms=recall["nowMs"],
            )
        python_candidates = rank_short_term_promotion_candidates(
            config=MemoryConfig(workspace_dir=python_workspace),
            now_ms=RANKING_NOW_MS,
            limit=10,
            min_score=DEFAULT_PROMOTION_MIN_SCORE,
            min_recall_count=DEFAULT_PROMOTION_MIN_RECALL_COUNT,
            min_unique_queries=DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        )
        python_values = {
            "candidates": [_promotion_candidate_values(candidate) for candidate in python_candidates]
        }

        try:
            sequence_result = oracle.run(
                {
                    "operation": "recordShortTermRecallSequence",
                    "recalls": recalls,
                    "timezone": RECALL_TIMEZONE,
                    "workspaceDir": str(oracle_workspace),
                }
            )
            if not isinstance(sequence_result, dict) or not sequence_result.get("ok"):
                oracle_result = sequence_result
            else:
                oracle_result = oracle.run(
                    {
                        "operation": "rankShortTermPromotionCandidates",
                        "workspaceDir": str(oracle_workspace),
                        "nowMs": RANKING_NOW_MS,
                        "timezone": RECALL_TIMEZONE,
                    }
                )
        except Exception as exc:
            oracle_result = {"ok": False, "error": {"message": str(exc)}}

    if not isinstance(oracle_result, dict):
        error = {"message": "invalid oracle result"}
        return _promotion_ranking_error_trace(python_values, error["message"], error)
    if not oracle_result.get("ok"):
        error = oracle_result.get("error", {})
        message = (
            error.get("message", "oracle error")
            if isinstance(error, dict)
            else "oracle error"
        )
        return _promotion_ranking_error_trace(python_values, message, error)
    raw_candidates = oracle_result.get("result", {}).get("candidates")
    if not isinstance(raw_candidates, list):
        error = {"message": "invalid oracle result"}
        return _promotion_ranking_error_trace(python_values, error["message"], error)
    openclaw_values = {"candidates": [_promotion_candidate_values(candidate) for candidate in raw_candidates]}
    return {
        "id": "promotion-ranking",
        "label": "Promotion candidate ranking",
        "condition": (
            "rankShortTermPromotionCandidates over a five-query recall store"
        ),
        "python": {"decision": "ranked", "values": python_values, "reasons": []},
        "openclaw": {"decision": "ranked", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


def _promotion_candidate_values(candidate: Any) -> dict[str, Any]:
    get = candidate.get if isinstance(candidate, dict) else lambda key, default=None: getattr(candidate, key, default)
    components = get("components", {}) or {}
    if not isinstance(components, dict):
        components = {}
    return {
        "key": get("key"),
        "path": get("path"),
        "startLine": get("startLine", get("start_line")),
        "endLine": get("endLine", get("end_line")),
        "snippet": get("snippet"),
        "recallCount": get("recallCount", get("recall_count")),
        "dailyCount": get("dailyCount", get("daily_count")),
        "groundedCount": get("groundedCount", get("grounded_count")),
        "signalCount": get("signalCount", get("signal_count")),
        "avgScore": _round_float(get("avgScore", get("avg_score"))),
        "maxScore": _round_float(get("maxScore", get("max_score"))),
        "uniqueQueries": get("uniqueQueries", get("unique_queries")),
        "ageDays": _round_float(get("ageDays", get("age_days"))),
        "score": _round_float(get("score")),
        "conceptTags": list(get("conceptTags", get("concept_tags", [])) or []),
        "components": {
            key: _round_float(components.get(key))
            for key in ("frequency", "relevance", "diversity", "recency", "consolidation", "conceptual")
        },
    }


def _round_float(value: Any) -> Any:
    return round(float(value), 12) if isinstance(value, int | float) else value


def _promotion_ranking_error_trace(
    python_values: dict[str, Any], message: str, error: dict[str, Any] | Any
) -> dict[str, Any]:
    return {
        "id": "promotion-ranking",
        "label": "Promotion candidate ranking",
        "condition": "rankShortTermPromotionCandidates over a five-query recall store",
        "python": {"decision": "ranked", "values": python_values, "reasons": []},
        "openclaw": {"decision": "error", "values": {}, "reasons": [message]},
        "diff": {"status": "error", "details": [error]},
    }


def _seed_recall_workspace(workspace: Path) -> None:
    memory_path = workspace / RECALL_RESULT["path"]
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# 2026-05-26\n\n- User prefers to be addressed as dodo.\n", encoding="utf-8")


def _snapshot_recall_files(workspace: Path) -> dict[str, str]:
    path = workspace / SHORT_TERM_STORE_RELATIVE_PATH
    return {RECALL_STORE_PATH: path.read_text(encoding="utf-8") if path.exists() else ""}


def _recall_values_from_files(
    files: Any, *, query: str, result: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(files, dict):
        raise TypeError("files must be an object")
    raw_store = files.get(RECALL_STORE_PATH)
    if not isinstance(raw_store, str) or not raw_store:
        raise ValueError(f"missing {RECALL_STORE_PATH}")
    store = json.loads(raw_store)
    entries = store.get("entries") if isinstance(store, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("recall store entries must be an object")
    return {
        "query": query,
        "path": result["path"],
        "score": result["score"],
        "file": RECALL_STORE_PATH,
        "entryCount": len(entries),
        "entries": entries,
    }


def _recall_tracking_error_trace(
    python_values: dict[str, Any], message: str, error: dict[str, Any] | Any
) -> dict[str, Any]:
    return {
        "id": "recall-tracking",
        "label": "Recall tracking from memory_search",
        "condition": RECALL_CONDITION,
        "python": {"decision": "recordable", "values": python_values, "reasons": []},
        "openclaw": {
            "decision": "error",
            "values": {},
            "reasons": [message],
        },
        "diff": {"status": "error", "details": [error]},
    }


def build_parity_trace(oracle: OpenClawOracle | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    return {
        "oracle": oracle.metadata(),
        "steps": [
            build_deep_policy_trace(oracle),
            build_configured_deep_policy_trace(oracle),
            build_recall_tracking_trace(oracle),
            build_repeated_recall_tracking_trace(oracle),
            build_promotion_ranking_trace(oracle),
        ],
    }
