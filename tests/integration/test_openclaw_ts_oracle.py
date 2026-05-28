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
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=180,
    )

    fixtures = [
        (
            "memory/2026-04-04.md",
            "Configuración de gateway, configuration du routeur, Sicherung und Überwachung Glacier.",
            [
                "gateway",
                "glacier",
                "routeur",
                "sicherung",
                "überwachung",
                "configuración",
                "configuration",
            ],
        ),
        (
            "memory/2026-04-05.md",
            "障害対応ルーター設定とバックアップ確認。路由器备份与网关同步。라우터 백업 페일오ーバー 점검.",
            [
                "バックアップ",
                "ルーター",
                "障害対応",
                "路由器",
                "备份",
                "网关",
                "라우터",
                "백업",
            ],
        ),
        (
            "memory/.dreams/session-corpus/2026-04-16.txt",
            "Assistant: the system should remind you about the Ollama provider setup in your workspace.",
            ["remind", "ollama", "provider", "setup"],
        ),
        (
            "memory/2026-04-03.md",
            "Move backups to S3 Glacier and sync QMD router notes.",
            ["backup", "backups", "glacier", "qmd", "router", "sync"],
        ),
        (
            "memory/2026-04-06.md",
            "Configuración du routeur et sauvegarde Glacier.",
            ["glacier", "sauvegarde", "routeur", "configuración"],
        ),
    ]

    for relative_path, snippet, expected_tags in fixtures:
        result = oracle.run(
            {
                "operation": "deriveConceptTags",
                "path": relative_path,
                "snippet": snippet,
            }
        )

        assert result["ok"] is True
        assert result["result"]["conceptTags"] == expected_tags


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


def test_real_openclaw_oracle_first_promotion_write_bootstraps_memory_header():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-first-promotion-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["appended"] == 1
    assert applied["files"]["MEMORY.md"].startswith(
        "# Long-Term Memory\n\n\n## Promoted From Short-Term Memory (2026-05-26)"
    )


def test_real_openclaw_oracle_reconciles_existing_promotion_marker():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-marker-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        key = "memory:memory/2026-05-08.md:3:3"
        (workspace / "MEMORY.md").write_text(
            "# Long-Term Memory\n\n"
            "## Promoted From Short-Term Memory (2026-05-08)\n\n"
            f"<!-- openclaw-memory-promotion:{key} -->\n"
            "- Move backups to S3 Glacier. [score=0.900 recalls=5 avg=1.000 "
            "source=memory/2026-05-08.md:3-3]\n",
            encoding="utf-8",
        )
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [base_result],
                        "nowMs": 1779811200000 + index,
                    }
                    for index, query in enumerate(
                        (
                            "backup policy",
                            "glacier backup",
                            "s3 retention",
                            "cold storage",
                            "backup notes",
                        )
                    )
                ],
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    assert [candidate["key"] for candidate in ranked["result"]["candidates"]] == [key]
    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert applied["result"]["appended"] == 0
    assert applied["result"]["reconciledExisting"] == 1
    recall_store = json.loads(applied["files"]["memory/.dreams/short-term-recall.json"])
    assert recall_store["entries"][key]["promotedAt"] == "2026-05-26T16:00:00.000Z"


def test_real_openclaw_oracle_ranking_skips_promoted_at_entry():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-promoted-at-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
        base_result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [base_result],
                        "nowMs": 1779811200000 + index,
                    }
                    for index, query in enumerate(
                        (
                            "backup policy",
                            "glacier backup",
                            "s3 retention",
                            "cold storage",
                            "backup notes",
                        )
                    )
                ],
            }
        )
        recall_path = workspace / "memory" / ".dreams" / "short-term-recall.json"
        recall_store = json.loads(recall_path.read_text(encoding="utf-8"))
        key = "memory:memory/2026-05-08.md:3:3"
        recall_store["entries"][key]["promotedAt"] = "2026-05-08T12:00:00.000Z"
        recall_path.write_text(json.dumps(recall_store), encoding="utf-8")
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    assert ranked["result"]["candidates"] == []


def test_real_openclaw_oracle_ignores_contaminated_dreaming_snippets():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    contaminated_snippet = (
        "Candidate: Default to action. confidence: 0.76 evidence: "
        "memory/.dreams/session-corpus/2026-04-08.txt:1-1 recalls: 3 status: staged"
    )
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-contaminated-") as tmp_dir:
        workspace = Path(tmp_dir)
        recorded = oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "query": "action preference",
                "results": [
                    {
                        "source": "memory",
                        "path": "memory/2026-04-03.md",
                        "startLine": 1,
                        "endLine": 1,
                        "snippet": contaminated_snippet,
                        "score": 0.92,
                    }
                ],
                "nowMs": 1779811200000,
            }
        )
        store_path = workspace / "memory" / ".dreams" / "short-term-recall.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "updatedAt": "2026-04-04T00:00:00.000Z",
                    "entries": {
                        "contaminated": {
                            "key": "contaminated",
                            "path": "memory/2026-04-03.md",
                            "startLine": 1,
                            "endLine": 1,
                            "source": "memory",
                            "snippet": (
                                "Reflections: Theme: assistant. confidence: 1.00 evidence: "
                                "memory/.dreams/session-corpus/2026-04-08.txt:2-2 recalls: "
                                "4 status: staged"
                            ),
                            "recallCount": 4,
                            "dailyCount": 0,
                            "groundedCount": 0,
                            "totalScore": 3.6,
                            "maxScore": 0.95,
                            "firstRecalledAt": "2026-04-03T00:00:00.000Z",
                            "lastRecalledAt": "2026-04-04T00:00:00.000Z",
                            "queryHashes": ["a", "b"],
                            "recallDays": ["2026-04-03", "2026-04-04"],
                            "conceptTags": ["assistant"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert recorded["ok"] is True
    recall_store = json.loads(recorded["files"]["memory/.dreams/short-term-recall.json"])
    assert recall_store["entries"] == {}
    assert ranked["ok"] is True
    assert ranked["result"]["candidates"] == []


def test_real_openclaw_oracle_keeps_candidate_like_daily_memory_evidence():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    snippet = "Candidate: move backups weekly. confidence: 0.76 evidence: memory/2026-04-08.md:1-1"
    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-clean-candidate-") as tmp_dir:
        workspace = Path(tmp_dir)
        result = {
            "source": "memory",
            "path": "memory/2026-04-08.md",
            "startLine": 1,
            "endLine": 1,
            "snippet": snippet,
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecallSequence",
                "workspaceDir": str(workspace),
                "timezone": "Europe/Istanbul",
                "recalls": [
                    {
                        "query": query,
                        "results": [result],
                        "nowMs": 1779811200000 + index,
                    }
                    for index, query in enumerate(
                        ("backup candidate", "weekly backups", "backup evidence")
                    )
                ],
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 1,
                "minUniqueQueries": 1,
            }
        )

    assert ranked["ok"] is True
    candidates = ranked["result"]["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["key"] == "memory:memory/2026-04-08.md:1:1"
    assert candidates[0]["snippet"] == snippet


def test_real_openclaw_oracle_apply_skips_candidate_when_live_note_no_longer_contains_snippet():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-stale-source-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-05-08.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("# 2026-05-08\n\n- Different note content now.\n", encoding="utf-8")
        result = {
            "source": "memory",
            "path": "memory/2026-05-08.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Move backups to S3 Glacier.",
            "score": 1,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "glacier",
                "results": [result],
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1779811200000,
                "timezone": "Europe/Istanbul",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert ranked["ok"] is True
    assert len(ranked["result"]["candidates"]) == 1
    assert applied["ok"] is True
    assert applied["result"]["applied"] == 0
    assert applied["files"]["MEMORY.md"] == ""
    recall_store = json.loads(applied["files"]["memory/.dreams/short-term-recall.json"])
    assert "promotedAt" not in recall_store["entries"]["memory:memory/2026-05-08.md:3:3"]


def test_real_openclaw_oracle_promotion_header_uses_dreaming_timezone():
    oracle = OpenClawOracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]),
        timeout_seconds=60,
    )

    with tempfile.TemporaryDirectory(prefix="memory-core-openclaw-promotion-timezone-") as tmp_dir:
        workspace = Path(tmp_dir)
        memory_file = workspace / "memory" / "2026-04-01.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            "# 2026-04-01\n\n- Cross-midnight router maintenance window.\n",
            encoding="utf-8",
        )
        result = {
            "source": "memory",
            "path": "memory/2026-04-01.md",
            "startLine": 3,
            "endLine": 3,
            "snippet": "- Cross-midnight router maintenance window.",
            "score": 0.9,
        }
        oracle.run(
            {
                "operation": "recordShortTermRecalls",
                "workspaceDir": str(workspace),
                "query": "router window",
                "results": [result],
                "nowMs": 1775086200000,
                "timezone": "America/Los_Angeles",
            }
        )
        ranked = oracle.run(
            {
                "operation": "rankShortTermPromotionCandidates",
                "workspaceDir": str(workspace),
                "nowMs": 1775111400000,
                "timezone": "America/Los_Angeles",
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )
        applied = oracle.run(
            {
                "operation": "applyShortTermPromotions",
                "workspaceDir": str(workspace),
                "nowMs": 1775111400000,
                "timezone": "America/Los_Angeles",
                "candidates": ranked["result"]["candidates"],
                "minScore": 0,
                "minRecallCount": 0,
                "minUniqueQueries": 0,
            }
        )

    assert applied["ok"] is True
    assert applied["result"]["applied"] == 1
    assert "Promoted From Short-Term Memory (2026-04-01)" in applied["files"]["MEMORY.md"]
