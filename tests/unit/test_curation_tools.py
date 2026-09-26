"""Curation tool specs and dispatcher (memory-core extension)."""

from __future__ import annotations

import json
import os

import pytest

from memory_core.bootstrap import OPENCLAW_PIN_LAYOUT
from memory_core.curation import (
    ADD_MEMORY_ENTRY,
    CURATION_OPERATIONS,
    SET_PROACTIVE_PREFERENCES,
    CurationPolicy,
    CurationUnavailableError,
    MemoryCurator,
    to_tool_error,
)
from memory_core.flags import FeatureFlags

MEMORY_MD = (
    "# Long-Term Memory\n"
    "\n"
    "## My Notes\n"
    "- gamma\n"
    "\n"
    "## Promoted From Short-Term Memory (2026-04-10)\n"
    "\n"
    "<!-- openclaw-memory-promotion:memory:memory/2026-04-09.md:3:3 -->\n"
    "- alpha [score=0.960 recalls=3 avg=0.920 source=memory/2026-04-09.md:3-3]\n"
)
NOW_MS = 1790375400000  # 2026-09-25 22:30 UTC


@pytest.fixture()
def curator(tmp_path):
    (tmp_path / "MEMORY.md").write_text(MEMORY_MD, encoding="utf-8")
    return MemoryCurator(tmp_path, now_ms=lambda: NOW_MS)


def test_tool_definitions_are_json_schema_specs_for_offered_operations(curator):
    definitions = curator.tool_definitions()

    assert [item["name"] for item in definitions] == list(CURATION_OPERATIONS)
    for item in definitions:
        assert set(item) == {"name", "description", "parameters"}
        assert item["description"]
        schema = item["parameters"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert all(prop["type"] == "string" for prop in schema["properties"].values())
    json.dumps(definitions)
    upsert = definitions[CURATION_OPERATIONS.index("upsert_user_directive")]
    assert "limited to 4000 characters" in upsert["description"]


def test_tool_definitions_follow_flag_flush_layout_and_policy(tmp_path, curator):
    assert curator.tool_definitions(memory_flush=True) == []
    assert MemoryCurator(tmp_path, flags=FeatureFlags(curated_memory_writes=False)).tool_definitions() == []
    pin = MemoryCurator(tmp_path, layout=OPENCLAW_PIN_LAYOUT).tool_definitions()
    assert SET_PROACTIVE_PREFERENCES not in [item["name"] for item in pin]
    narrowed = MemoryCurator(
        tmp_path,
        policy=CurationPolicy.for_layout(file_caps={"USER.md": 1500}).without(ADD_MEMORY_ENTRY),
    ).tool_definitions()
    assert ADD_MEMORY_ENTRY not in [item["name"] for item in narrowed]
    assert "limited to 1500 characters" in narrowed[2]["description"]


def test_dispatch_runs_calls_from_json_or_mappings(tmp_path, curator):
    added = curator.dispatch(ADD_MEMORY_ENTRY, json.dumps({"section": "My Notes", "text": "delta"}))
    replaced = curator.dispatch(
        "replace_memory_entry", {"old": "delta", "new": "DELTA", "section": ""}
    )
    removed = curator.dispatch("remove_memory_entry", {"entry": "DELTA", "section": "My Notes"})

    assert added == {
        "status": "ok",
        "tool": ADD_MEMORY_ENTRY,
        "path": "MEMORY.md",
        "action": "added",
        "chars": len(MEMORY_MD.rstrip()) + len("\n- delta"),
    }
    assert (replaced["action"], removed["action"]) == ("replaced", "removed")
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == MEMORY_MD

    directive = curator.dispatch(
        "upsert_user_directive", {"text": "Prefer delta.", "observed": "", "supersede": None}
    )
    assert directive["action"] == "added"
    assert (tmp_path / "USER.md").read_text(encoding="utf-8") == (
        "<!-- observed: 2026-09-25 | status: active -->\n\n- Prefer delta.\n"
    )
    assert curator.dispatch(SET_PROACTIVE_PREFERENCES, {"text": "alpha"})["action"] == "set"
    assert curator.dispatch(SET_PROACTIVE_PREFERENCES, {"text": ""})["action"] == "cleared"
    note = curator.dispatch("append_daily_note", '{"text": "alpha"}')
    assert (note["path"], note["action"]) == ("memory/2026-09-25.md", "appended")
    assert "chars" not in note


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        (ADD_MEMORY_ENTRY, {"section": "My Notes"}, "text required"),
        (ADD_MEMORY_ENTRY, {"section": "My Notes", "text": "  "}, "text required"),
        (ADD_MEMORY_ENTRY, {"section": "My Notes", "text": 5}, "text required"),
        (ADD_MEMORY_ENTRY, "{not json", "arguments must be a JSON object"),
        (ADD_MEMORY_ENTRY, "[1, 2]", "arguments must be a JSON object"),
        (ADD_MEMORY_ENTRY, {"section": "My Notes", "text": "a\nb"}, "text must be a single line"),
        ("replace_memory_entry", {"old": "delta", "new": "x"}, "entry not found in MEMORY.md"),
        ("replace_memory_entry", {"old": "gamma", "new": "x", "section": 3}, "section must be a string"),
        (
            "remove_memory_entry",
            {"entry": "alpha [score=0.960 recalls=3 avg=0.920 source=memory/2026-04-09.md:3-3]"},
            "memory promotion section",
        ),
        ("upsert_user_directive", {"text": "Prefer delta.", "observed": "26.09.2026"}, "YYYY-MM-DD"),
        (SET_PROACTIVE_PREFERENCES, {}, "text required"),
        ("append_daily_note", None, "text required"),
    ],
)
def test_dispatch_returns_tool_errors_for_bad_input(curator, name, arguments, message):
    payload = curator.dispatch(name, arguments)

    assert payload["status"] == "error"
    assert payload["tool"] == name
    assert message in payload["error"]
    assert payload == to_tool_error(name, payload["error"])


def test_dispatch_returns_tool_errors_for_refused_writes(tmp_path):
    (tmp_path / "USER.md").write_text("x" * 3_990 + "\n", encoding="utf-8")
    curator = MemoryCurator(tmp_path, now_ms=lambda: NOW_MS)

    payload = curator.dispatch("upsert_user_directive", {"text": "Prefer delta."})

    assert payload["status"] == "error"
    assert "over its 4000-char cap" in payload["error"]


def test_dispatch_reports_os_errors_as_tool_errors(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").write_text(MEMORY_MD, encoding="utf-8")
    curator = MemoryCurator(root)
    os.chmod(root, 0o500)
    try:
        payload = curator.dispatch(ADD_MEMORY_ENTRY, {"section": "My Notes", "text": "delta"})
    finally:
        os.chmod(root, 0o700)

    assert payload["status"] == "error"
    assert payload["error"].startswith("write failed:")
    assert (root / "MEMORY.md").read_text(encoding="utf-8") == MEMORY_MD


def test_dispatch_raises_for_tools_not_on_offer(tmp_path, curator):
    with pytest.raises(CurationUnavailableError, match="unknown curation tool: write"):
        curator.dispatch("write", {"path": "MEMORY.md", "content": "x"})
    with pytest.raises(CurationUnavailableError, match="memory flush"):
        curator.dispatch(ADD_MEMORY_ENTRY, {"section": "A", "text": "b"}, memory_flush=True)
    disabled = MemoryCurator(tmp_path, flags=FeatureFlags(curated_memory_writes=False))
    with pytest.raises(CurationUnavailableError, match="disabled"):
        disabled.dispatch(ADD_MEMORY_ENTRY, {"section": "A", "text": "b"})
    pin = MemoryCurator(tmp_path, layout=OPENCLAW_PIN_LAYOUT)
    with pytest.raises(CurationUnavailableError, match="may not write PROACTIVE_PREFERENCES.md"):
        pin.dispatch(SET_PROACTIVE_PREFERENCES, {"text": "alpha"})
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == MEMORY_MD
    assert sorted(os.listdir(tmp_path)) == ["MEMORY.md"]
