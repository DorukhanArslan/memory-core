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
    record_short_term_recalls,
)
from memory_core.config import MemoryConfig

DEEP_POLICY_CONDITION = (
    "score >= minScore && signals >= minRecallCount && "
    "contextDiversity >= minUniqueQueries && ageDays <= maxAgeDays"
)
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
        "maxAgeDays": DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
        "enabled": DEFAULT_DEEP_DREAMING_ENABLED,
        "limit": DEFAULT_DEEP_DREAMING_LIMIT,
        "recencyHalfLifeDays": DEFAULT_RECENCY_HALF_LIFE_DAYS,
    }
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
    openclaw_values = {
        "minScore": oracle_result_values.get("minScore"),
        "minRecallCount": oracle_result_values.get("minRecallCount"),
        "minUniqueQueries": oracle_result_values.get("minUniqueQueries"),
        "maxAgeDays": oracle_result_values.get("maxAgeDays"),
        "enabled": oracle_result_values.get("enabled"),
        "limit": oracle_result_values.get("limit"),
        "recencyHalfLifeDays": oracle_result_values.get("recencyHalfLifeDays"),
    }
    return {
        "id": "deep-policy",
        "label": "Deep dreaming policy values",
        "condition": DEEP_POLICY_CONDITION,
        "python": {"decision": "computed", "values": python_values, "reasons": []},
        "openclaw": {"decision": "computed", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


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
            build_recall_tracking_trace(oracle),
            build_repeated_recall_tracking_trace(oracle),
        ],
    }
