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


def test_real_openclaw_oracle_deep_policy_uses_configured_values():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run(
        {
            "operation": "deepPolicy",
            "config": {
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
            },
        }
    )

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["enabled"] is True
    assert result["result"]["limit"] == 7
    assert result["result"]["minScore"] == 0.72
    assert result["result"]["minRecallCount"] == 4
    assert result["result"]["minUniqueQueries"] == 2
    assert result["result"]["maxAgeDays"] == 14
    assert result["result"]["recencyHalfLifeDays"] == 10


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


def test_real_openclaw_oracle_derives_concept_vocabulary_tags():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    fixtures = [
        (
            "memory/2026-05-26.md",
            "- User prefers to be addressed as Doruk.",
            ["prefers", "addressed", "doruk"],
        ),
        (
            "memory/2026-05-27-network.md",
            "- Router VLAN DHCP firewall subnet Mikrotik configuration failed.",
            [
                "network",
                "router",
                "vlan",
                "2026-05-27-network.md",
                "network.md",
                "dhcp",
                "firewall",
                "subnet",
            ],
        ),
        (
            "memory/2026-05-28-topic.md",
            "- The user and assistant discussed memory memory 2026-05-26.md "
            "1234 router s3 gateway backup router.",
            ["backup", "gateway", "router", "2026-05-28-topic.md", "topic.md", "discussed"],
        ),
        (
            "memory/2026-05-30-compound.md",
            "- puerta-de-enlace openai_embeddings qmd routeur gateway router vlan s3 "
            "backups failover glacier network extra tokens",
            [
                "backup",
                "backups",
                "embedding",
                "embeddings",
                "failover",
                "gateway",
                "glacier",
                "network",
            ],
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-concepts-") as tmp_dir:
        workspace = Path(tmp_dir)
        recalls = []
        for index, (relative_path, snippet, _) in enumerate(fixtures):
            memory_file = workspace / relative_path
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(f"# Fixture\n\n{snippet}\n", encoding="utf-8")
            recalls.append(
                {
                    "query": f"fixture {index}",
                    "results": [
                        {
                            "source": "memory",
                            "path": relative_path,
                            "startLine": 3,
                            "endLine": 3,
                            "snippet": snippet,
                            "score": 1,
                        }
                    ],
                    "nowMs": 1779811200000 + index,
                }
            )
        result = oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": recalls,
            }
        )

    assert result["ok"] is True
    recall_store = json.loads(result["files"]["memory/.dreams/short-term-recall.json"])
    entries = recall_store["entries"]
    for relative_path, _, expected_tags in fixtures:
        entry = entries[f"memory:{relative_path}:3:3"]
        assert entry["conceptTags"] == expected_tags


def test_real_openclaw_oracle_ranks_short_term_promotion_candidate():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-ranking-") as tmp_dir:
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
        queries = [
            "address preference",
            "preferred name",
            "user salutation",
            "name preference",
            "how to address user",
        ]
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [base_result],
                        "nowMs": 1779811200000 + index * 86_400_000,
                    }
                    for index, query in enumerate(queries)
                ],
            }
        )
        result = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000 + 4 * 86_400_000,
                "timezone": "Europe/Istanbul",
            }
        )

    assert result["ok"] is True
    candidates = result["result"]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["key"] == "memory:memory/2026-05-26.md:3:3"
    assert candidate["recallCount"] == 5
    assert candidate["uniqueQueries"] == 5
    assert candidate["score"] == pytest.approx(0.8900475024284972)
    assert candidate["components"]["frequency"] == pytest.approx(0.7472217363092141)
    assert candidate["components"]["relevance"] == 1
    assert candidate["components"]["diversity"] == 1
    assert candidate["components"]["recency"] == 1
    assert candidate["components"]["consolidation"] == pytest.approx(0.8071428571428572)
    assert candidate["components"]["conceptual"] == 0.5
