import os
from pathlib import Path
import json
import tempfile

import pytest

from demo.openclaw_oracle import OpenClawOracle


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def test_real_openclaw_oracle_deep_policy():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "deepPolicy", "config": {}})

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["minScore"] == 0.8
    assert result["result"]["minRecallCount"] == 3
    assert result["result"]["minUniqueQueries"] == 3
    assert result["result"]["maxAgeDays"] == 30
    assert result["result"]["enabled"] is False
    assert result["result"]["limit"] == 10
    assert result["result"]["recencyHalfLifeDays"] == 14


def test_real_openclaw_oracle_records_short_term_recall():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-integration-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        result = oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "query": "address preference",
                "results": [
                    {
                        "source": "memory",
                        "path": "memory/2026-05-26.md",
                        "startLine": 3,
                        "endLine": 3,
                        "snippet": "- User prefers to be addressed as dodo.",
                        "score": 1,
                    }
                ],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "workspaceDir": str(workspace),
            }
        )

    assert result["ok"] is True
    assert result["operation"] == "recordShortTermRecalls"
    recall_store = result["files"]["memory/.dreams/short-term-recall.json"]
    assert "User prefers to be addressed as dodo." in recall_store
    assert '"recallCount": 1' in recall_store


def test_real_openclaw_oracle_records_short_term_recall_sequence():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-sequence-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-26.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-05-26\n\n- User prefers to be addressed as dodo.\n",
            encoding="utf-8",
        )
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-26.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- User prefers to be addressed as dodo.",
            "score": 1,
        }
        result = oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": "address preference",
                        "results": [base_result],
                        "nowMs": 1779811200000,
                    },
                    {
                        "query": "preferred name",
                        "results": [
                            base_result,
                            {
                                "source": "workspace",
                                "path": "notes.md",
                                "startLine": 1,
                                "endLine": 1,
                                "snippet": "Ignore this non-memory result.",
                                "score": 1,
                            },
                        ],
                        "nowMs": 1779897600000,
                    },
                ],
            }
        )

    assert result["ok"] is True
    assert result["operation"] == "recordShortTermRecallSequence"
    recall_store = json.loads(result["files"]["memory/.dreams/short-term-recall.json"])
    entries = recall_store["entries"]
    entry = entries["memory:memory/2026-05-26.md:3:3"]
    assert len(entries) == 1
    assert entry["recallCount"] == 2
    assert entry["queryHashes"] == ["aa5368a7c7bd", "1da206d81a95"]
    assert entry["recallDays"] == ["2026-05-26", "2026-05-27"]
