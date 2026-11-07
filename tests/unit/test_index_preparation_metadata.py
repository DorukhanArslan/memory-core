"""Preparation metadata boundaries from the pinned native source grammar."""
from dataclasses import replace

import pytest

from memory_core.index.chunking import chunk_markdown
from memory_core.index.preparation import (
    INVALID_PROJECT_ANNOTATION_KEY,
    classify_memory_path,
    extract_curated_entry_recall_metadata,
    prepare_chunk_metadata,
    resolve_chunk_provenance,
    strip_memory_annotation_carriers,
)
from memory_core.index.publication import ChunkProvenance, ChunkRecallMetadata


@pytest.mark.parametrize("raw,expected", [
    ("<!--\n trigger: x -->", ""),
    ("<!--trigger\n: x -->", ""),
    ("<!--trigger:\n x -->", "<!--trigger:\n x -->"),
    ("<!--trigger:\n<!--importance: 7 -->", "<!--trigger:\n"),
    ("<!--trigger:x <!--\nimportance:7 -->", "<!--trigger:x"),
    ("text <!--note: visible -->", "text <!--note: visible -->"),
    ("a \t<!--trigger: x -->\r\nb \tX", "a\r\nb \tX"),
    ("a  <!--PROJECT: x -->\u2028b\t ", "a\u2028b"),
    ("a  <!--IMPORTANCE: 8 --> b  ", "a   b"),
])
def test_stripping_retains_native_line_scoped_body_and_prefix_grammar(raw, expected):
    assert strip_memory_annotation_carriers(raw) == expected


def test_unfinished_carriers_and_long_nontrailing_space_runs_are_retained():
    unfinished = "<!--project:" * 20_000
    assert strip_memory_annotation_carriers(unfinished) == unfinished
    spaces = " " * 20_000
    assert strip_memory_annotation_carriers("<!--trigger: x -->" + spaces + "tail") == spaces + "tail"


def test_recall_annotations_keep_suffix_selection_order_and_maximum_importance():
    assert extract_curated_entry_recall_metadata(
        curated_root=True, project_scope_eligible=True,
        source_lines=[
            "body <!--TRIGGER: alpha, beta; alpha --> prose <!-- note --><!--importance: 03 -->",
            "<!--trigger: ignored --> trailing text",
            "<!--importance: 11 --><!--importance: 8 --><!--importance: 2.5 -->",
            "<!--trigger: gamma --><!--project: GitHub.com/Owner/Repo -->",
        ],
    ) == ChunkRecallMetadata(8, "alpha; beta; gamma", "github.com/Owner/Repo")


@pytest.mark.parametrize("value,importance", [
    ("0000000000000000000000000000000000000008", 8),
    ("9" * 10_000, None), ("١", None), ("８", None), ("+8", None), ("0", None), ("10", 10),
])
def test_importance_uses_ascii_digits_and_the_native_allowed_range(value, importance):
    metadata = extract_curated_entry_recall_metadata(
        curated_root=True, project_scope_eligible=False,
        source_lines=[f"body <!--importance: {value} -->"],
    )
    assert metadata.importance == importance


def test_projects_remain_scoped_outside_curated_roots_and_invalid_projects_fail_closed():
    metadata = extract_curated_entry_recall_metadata(
        curated_root=False, project_scope_eligible=True,
        source_lines=["<!--importance: 9 --><!--trigger: ignored --><!--project: Alpha; Beta -->"],
    )
    assert metadata == ChunkRecallMetadata(None, None, "Alpha; Beta")
    invalid = extract_curated_entry_recall_metadata(
        curated_root=True, project_scope_eligible=True,
        source_lines=["<!--project: alpha --> <!--project:"],
    )
    assert invalid.project_key == INVALID_PROJECT_ANNOTATION_KEY


@pytest.mark.parametrize("path,source,curated,origin", [
    ("MEMORY.md", "memory", True, "agent"),
    ("memory.md", "memory", True, "agent"),
    ("USER.md", "memory", True, "agent"),
    ("memory/topic.md", "memory", False, "agent"),
    ("users/abc-123/USER.md", "memory", False, "agent"),
    ("users/-bad/USER.md", "memory", False, "untrusted"),
    ("DREAMS.md", "memory", False, "system"),
    ("dreams.md", "memory", False, "system"),
    ("Dreams.md", "memory", False, "untrusted"),
    ("memory/.dreams/saved.md", "memory", False, "system"),
    ("memory/dreaming/note.md", "memory", False, "system"),
    ("memory/dreaming.txt", "memory", False, "untrusted"),
    ("MEMORY.md", "sessions", False, "untrusted"),
    ("memory/not-markdown.txt", "memory", False, "untrusted"),
    ("./MEMORY.md", "memory", False, "untrusted"),
    ("memory//note.md", "memory", False, "untrusted"),
    ("memory/../MEMORY.md", "memory", False, "untrusted"),
    ("C:\\memory\\note.md", "memory", False, "untrusted"),
])
def test_classification_uses_canonical_path_and_source_boundaries(path, source, curated, origin):
    assert classify_memory_path(path, source) == {"curatedRoot": curated, "originClass": origin}


def test_recorded_downgrade_wins_but_comments_and_unrelated_paths_do_not_grant_trust():
    assert classify_memory_path("memory/note.md", recorded_origin="untrusted")["originClass"] == "untrusted"
    assert classify_memory_path("notes.txt", recorded_origin="agent")["originClass"] == "untrusted"
    assert classify_memory_path("memory/.dreams/a.md", recorded_origin="agent")["originClass"] == "system"


@pytest.mark.parametrize("mtime,observed", [(-10.5, 0), (0, 0), (12.9, 12), (1000.01, 1000)])
def test_non_session_observation_uses_nonnegative_floored_mtime(mtime, observed):
    assert resolve_chunk_provenance(
        source="memory", path_origin_class="agent", mtime_ms=mtime,
        start_line=1, end_line=4,
        line_provenance=[ChunkProvenance("owner", "interactive", 999)],
    ) == ChunkProvenance("agent", "unknown", observed)


def test_session_provenance_reduces_only_selected_original_rendered_lines():
    lines = [
        {"originClass": "untrusted", "sessionKind": "cron", "observedAt": 999, "supersedesKey": "outside"},
        {"originClass": "owner", "sessionKind": "interactive", "observedAt": 12, "supersedesKey": "prior"},
        {"originClass": "agent", "sessionKind": "interactive", "observedAt": 19, "supersedesKey": "prior"},
        {"originClass": "system", "sessionKind": "cron", "observedAt": 20, "supersedesKey": "different"},
    ]
    assert resolve_chunk_provenance(
        source="sessions", path_origin_class="untrusted", mtime_ms=1_000,
        start_line=2, end_line=3, line_provenance=lines,
    ) == ChunkProvenance("agent", "interactive", 19, "prior")
    assert resolve_chunk_provenance(
        source="sessions", path_origin_class="untrusted", mtime_ms=1_000,
        start_line=2, end_line=4, line_provenance=lines,
    ) == ChunkProvenance("system", "unknown", 20)


def test_missing_session_line_provenance_uses_untrusted_mtime_fallback():
    assert resolve_chunk_provenance(
        source="sessions", path_origin_class="untrusted", mtime_ms=10.9,
        start_line=2, end_line=3, line_provenance=[ChunkProvenance("owner", "interactive", 20)],
    ) == ChunkProvenance("untrusted", "unknown", 10)


def test_chunk_metadata_uses_full_original_entry_span_before_line_remapping():
    original = "# Notes\r\n- Body. <!--importance: 8 --><!--trigger: alpha --><!--project: Repo -->\r\ncontinuation\r\n"
    stripped = strip_memory_annotation_carriers(original)
    chunks = chunk_markdown("MEMORY.md", stripped, per_entry=True)
    entry = next(chunk for chunk in chunks if chunk.entry_start_line == 2)
    fragment = replace(entry, start_line=3, end_line=3)
    provenance, recall = prepare_chunk_metadata(
        path="MEMORY.md", source="memory", text=original, mtime_ms=42.9, chunk=fragment,
    )
    assert provenance == ChunkProvenance("agent", "unknown", 42)
    assert recall == ChunkRecallMetadata(8, "alpha", "Repo")
    _provenance, user_recall = prepare_chunk_metadata(
        path="USER.md", source="memory", text=original, mtime_ms=42.9, chunk=fragment,
    )
    assert user_recall == ChunkRecallMetadata(8, "alpha", None)
