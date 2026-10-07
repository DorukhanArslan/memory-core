"""Oracle test of the session transcript file name classifiers against OpenClaw v2026.9.6.

``isPrimarySessionTranscriptFileName``, ``isSessionArchiveArtifactName``,
``isCompactionCheckpointTranscriptFileName`` and ``parseUsageCountedSessionIdFromFileName``
(``src/config/sessions/artifacts.ts``) over live, archived, compressed, checkpoint and malformed names.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.session_artifacts import (
    is_compaction_checkpoint_transcript_file_name,
    is_primary_session_transcript_file_name,
    is_session_archive_artifact_name,
    parse_usage_counted_session_id_from_file_name,
)

STAMP = "2026-05-26T16-00-00.123Z"
UUID_V4 = "123e4567-e89b-42d3-a456-426614174000"
GENERATION = "0123456789abcdef0123456789abcdef"


def _names() -> list[str]:
    base = ["abc", "0198a3e1-aaaa-bbbb-cccc-0123456789ab", "My Session", "a.b", "x" * 40, "é", "a.jsonl", ""]
    names = ["sessions.json", "sessions.json.bak.1700000000", "sessions.json.bak.", "notes.md", "a.trajectory.jsonl", ".jsonl"]
    for b in base:
        names += [
            f"{b}.jsonl",
            f"{b}.JSONL",
            f"{b}.jsonl.reset.{STAMP}",
            f"{b}.jsonl.deleted.{STAMP}",
            f"{b}.jsonl.bak.{STAMP}",
            f"{b}.jsonl.reset.{STAMP}.{GENERATION}",
            f"{b}.jsonl.reset.{STAMP}.zst",
            f"{b}.jsonl.deleted.{STAMP}.{GENERATION}.zst",
            f"{b}.jsonl.reset.2026-05-26T16-00-00Z",
            f"{b}.jsonl.reset.2026-05-26",
            f"{b}.jsonl.reset.{STAMP}.zzz",
            f"{b}.jsonl.other.{STAMP}",
            f"{b}.checkpoint.{UUID_V4}.jsonl",
            f"{b}.CHECKPOINT.{UUID_V4.upper()}.jsonl",
            f"{b}.checkpoint.{UUID_V4}.jsonl.reset.{STAMP}",
            f"{b}.checkpoint.not-a-uuid.jsonl",
            f"{b}.jsonl.reset.{STAMP}.jsonl.deleted.{STAMP}",
            f"{b}.trajectory.jsonl",
            f"{b}.jsonl.pre-doctor-branch-repair-{STAMP.replace('.', '-')}.bak",
        ]
    rng = random.Random(7)
    pieces = [".jsonl", ".reset.", ".deleted.", ".bak.", STAMP, "a", ".zst", ".checkpoint.", UUID_V4, GENERATION, "-", "."]
    for _ in range(600):
        names.append("".join(rng.choice(pieces) for _ in range(rng.randint(1, 7))))
    return names


@pytest.fixture(scope="module")
def _ts():
    names = _names()
    response = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=240).run(
        {"operation": "sessionArtifactNames", "texts": names}
    )
    assert response["ok"] is True, response.get("error")
    return response["result"]["names"]


def test_session_file_name_classifiers_match_openclaw(_ts) -> None:
    for expected in _ts:
        name = expected["name"]
        got = {
            "primary": is_primary_session_transcript_file_name(name),
            "archive": is_session_archive_artifact_name(name),
            "checkpoint": is_compaction_checkpoint_transcript_file_name(name),
            "sessionId": parse_usage_counted_session_id_from_file_name(name),
        }
        assert got == {k: expected[k] for k in got}, name


def test_corpus_has_each_kind(_ts) -> None:
    assert sum(1 for e in _ts if e["primary"]) > 20
    assert sum(1 for e in _ts if e["archive"]) > 50
    assert sum(1 for e in _ts if e["checkpoint"]) > 5
    assert sum(1 for e in _ts if e["sessionId"] and not e["primary"]) > 20
