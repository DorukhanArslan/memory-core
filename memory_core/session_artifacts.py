"""Session transcript file names: live transcripts, archives and compaction checkpoints.

Port of the filename classifiers of ``src/config/sessions/artifacts.ts`` (OpenClaw v2026.9.6) that
memory forget and the dreaming ingestion read: :func:`parse_usage_counted_session_id_from_file_name`
(``parseUsageCountedSessionIdFromFileName``: ``<id>.jsonl`` and the ``.jsonl.reset.<stamp>`` and
``.jsonl.deleted.<stamp>`` archives, optionally ``.zst``), :func:`is_session_archive_artifact_name`,
:func:`is_primary_session_transcript_file_name` and :func:`is_compaction_checkpoint_transcript_file_name`.
"""

from __future__ import annotations

import re

SESSION_ARCHIVE_ZSTD_SUFFIX = ".zst"

_ARCHIVE_SUFFIX_RE = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}(?:\.[0-9]{3})?Z)(?:\.([0-9a-f]{32}))?\Z"
)
_LEGACY_STORE_BACKUP_RE = re.compile(r"^sessions\.json\.bak\.[0-9]+\Z")
_CHECKPOINT_RE = re.compile(
    r"^(.+)\.checkpoint\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.jsonl\Z",
    re.IGNORECASE | re.ASCII,
)


def strip_session_archive_compression_suffix(file_name: str) -> str:
    return file_name[: -len(SESSION_ARCHIVE_ZSTD_SUFFIX)] if file_name.endswith(SESSION_ARCHIVE_ZSTD_SUFFIX) else file_name


def has_archive_suffix(file_name: str, reason: str) -> bool:
    """``hasArchiveSuffix``: ``<id>.jsonl.<reason>.<stamp>[.<generation>]`` (``.zst`` ignored)."""
    marker = f".{reason}."
    normalized = strip_session_archive_compression_suffix(file_name)
    index = normalized.rfind(marker)
    if index < 0:
        return False
    return _ARCHIVE_SUFFIX_RE.match(normalized[index + len(marker) :]) is not None


def is_session_archive_artifact_name(file_name: str) -> bool:
    """``isSessionArchiveArtifactName``: archives (deleted, reset, bak) and legacy store backups."""
    if _LEGACY_STORE_BACKUP_RE.match(file_name):
        return True
    return any(has_archive_suffix(file_name, reason) for reason in ("deleted", "reset", "bak"))


def is_compaction_checkpoint_transcript_file_name(file_name: str) -> bool:
    """``isCompactionCheckpointTranscriptFileName``: ``<id>.checkpoint.<uuid>.jsonl``."""
    match = _CHECKPOINT_RE.match(file_name)
    return bool(match and match.group(1) and match.group(2))


def is_primary_session_transcript_file_name(file_name: str) -> bool:
    """``isPrimarySessionTranscriptFileName``: a live ``<id>.jsonl`` transcript."""
    if file_name == "sessions.json" or not file_name.endswith(".jsonl"):
        return False
    if file_name.endswith(".trajectory.jsonl"):
        return False
    if is_compaction_checkpoint_transcript_file_name(file_name):
        return False
    return not is_session_archive_artifact_name(file_name)


def parse_usage_counted_session_id_from_file_name(file_name: str) -> str | None:
    """``parseUsageCountedSessionIdFromFileName``: the session id of a live transcript or its reset/deleted archive."""
    if is_primary_session_transcript_file_name(file_name):
        return file_name[: -len(".jsonl")]
    normalized = strip_session_archive_compression_suffix(file_name)
    for reason in ("reset", "deleted"):
        marker = f".jsonl.{reason}."
        index = normalized.rfind(marker)
        if index > 0 and has_archive_suffix(normalized, reason):
            session_id = normalized[:index]
            return session_id if is_primary_session_transcript_file_name(f"{session_id}.jsonl") else None
    return None


def is_usage_counted_session_transcript_file_name(file_name: str) -> bool:
    return parse_usage_counted_session_id_from_file_name(file_name) is not None
