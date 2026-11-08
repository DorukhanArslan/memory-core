"""Read-contract regressions over the real memory_get executor and files."""

from pathlib import Path

import pytest

from memory_core.config import MemoryConfig
from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
from memory_core.tools.memory_get import (
    build_memory_read_result,
    build_memory_read_result_from_slice,
    execute_memory_get_tool,
)


def test_utf16_read_budget_retains_full_lines_and_continuation(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("😀a\nsecond\n", encoding="utf-8")
    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path, memory_get_max_chars=3), {"path": "MEMORY.md"},
    )
    assert result == {
        "status": "ok", "path": "MEMORY.md", "from": 1, "lines": 1,
        "text": "😀a\n\n[More content available. Use from=2 to continue.]",
        "truncated": True, "nextFrom": 2,
    }


@pytest.mark.parametrize("budget,prefix", [(1, ""), (2, "😀"), (3, "😀a")])
def test_oversized_first_line_is_surrogate_safe_even_when_no_character_fits(
    tmp_path: Path, budget: int, prefix: str,
):
    (tmp_path / "MEMORY.md").write_text("😀abc\n", encoding="utf-8")
    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path, memory_get_max_chars=budget), {"path": "MEMORY.md"},
    )
    assert result == {
        "status": "ok", "path": "MEMORY.md", "from": 1, "lines": 1,
        "text": prefix + "\n\n[More content available. Requested excerpt exceeded the default "
        "maxChars budget. If you need the full raw line, use read on the source file.]",
        "truncated": True,
    }
    result["text"].encode("utf-8")


def test_default_page_size_and_terminal_newline_do_not_invent_a_line(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("\n".join(str(n) for n in range(1, 122)) + "\n", encoding="utf-8")
    config = MemoryConfig(workspace_dir=tmp_path)
    first = execute_memory_get_tool(config, {"path": "MEMORY.md"})
    final = execute_memory_get_tool(config, {"path": "MEMORY.md", "from": first["nextFrom"]})
    assert first == {
        "status": "ok", "path": "MEMORY.md", "from": 1, "lines": 120,
        "text": "\n".join(str(n) for n in range(1, 121))
        + "\n\n[More content available. Use from=121 to continue.]",
        "truncated": True, "nextFrom": 121,
    }
    assert final == {"status": "ok", "path": "MEMORY.md", "from": 121, "lines": 1, "text": "121"}


def test_shared_slice_builder_keeps_empty_excerpt_paging_without_inventing_notice():
    assert build_memory_read_result_from_slice(
        selected_lines=["", ""], rel_path="memory/blank.md", start_line=2.9,
        more_source_lines_remain=True, max_chars=1,
    ) == {
        "status": "ok", "path": "memory/blank.md", "from": 2, "lines": 2,
        "text": "\n\n\n[More content available. Use from=4 to continue.]",
        "truncated": True, "nextFrom": 4,
    }
    assert build_memory_read_result(
        content="", rel_path="MEMORY.md", from_line=0, lines=0,
    ) == {"status": "ok", "path": "MEMORY.md", "from": 1, "lines": 0, "text": ""}


def test_registered_reader_receives_trusted_context_and_owns_complete_excerpt(tmp_path: Path):
    calls = []
    row = {
        "content": "An already selected provider excerpt, longer than the read budget.",
        "path": "wiki/canonical-topic", "corpus": "wiki", "title": "Topic",
        "from": 17, "lines": 4, "nextFrom": 21, "truncated": True,
        "status": "provider-specific", "nested": {"value": None}, "citation": None,
    }

    def read(**options):
        calls.append(options)
        return row

    supplement = RegisteredMemoryCorpusSupplement("wiki", StaticMemoryCorpusSupplement([]), reader=read)
    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path, agent_id="reader", memory_get_max_chars=1),
        {"path": "  /wiki\\topic  ", "from": "2", "lines": "1", "corpus": "wiki"},
        supplements=[supplement], agent_session_key="agent:reader:main", sandboxed=False,
    )
    expected = {key: value for key, value in row.items() if key != "content"}
    expected.update(status="ok", text=row["content"], corpora=[{"corpus": "wiki", "outcome": "ok"}])
    assert result == expected
    assert calls == [{
        "lookup": "/wiki\\topic", "from_line": 2, "line_count": 1, "agent_id": "reader",
        "agent_session_key": "agent:reader:main", "sandboxed": False,
    }]
    assert row["status"] == "provider-specific" and "text" not in row


@pytest.mark.parametrize("content", ["", None])
def test_wiki_empty_and_null_content_never_fall_back_to_snippet(tmp_path: Path, content):
    row = {"path": "provider-topic", "content": content, "snippet": "Do not substitute this.", "extra": None}
    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path), {"path": "topic", "corpus": "wiki"},
        supplements=[RegisteredMemoryCorpusSupplement(
            "wiki", StaticMemoryCorpusSupplement([]), reader=lambda **kwargs: row,
        )],
    )
    assert result == {
        "path": "provider-topic", "text": content, "status": "ok",
        "snippet": "Do not substitute this.", "extra": None,
        "corpora": [{"corpus": "wiki", "outcome": "ok"}],
    }


def test_anonymous_provider_keeps_legacy_call_signature_and_complete_result(tmp_path: Path):
    calls = []

    class LegacySupplement:
        def get(self, *, path, corpus):
            calls.append((path, corpus))
            return {"path": "provider-path", "content": "provider excerpt", "custom": [1, None]}

    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path), {"path": "topic", "corpus": "wiki", "lines": 1},
        supplements=[LegacySupplement()],
    )
    assert calls == [("topic", "wiki")]
    assert result == {
        "status": "ok", "path": "provider-path", "text": "provider excerpt", "custom": [1, None],
        "corpora": [{"corpus": "wiki", "outcome": "ok"}],
    }


def test_all_corpus_preserves_primary_success_and_registered_failure_warning(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("Primary evidence.\n", encoding="utf-8")

    def failed(**options):
        raise RuntimeError("wiki read failed")

    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path), {"path": "MEMORY.md", "corpus": "all"},
        supplements=[RegisteredMemoryCorpusSupplement("wiki", StaticMemoryCorpusSupplement([]), reader=failed)],
    )
    assert result == {
        "status": "ok", "path": "MEMORY.md", "text": "Primary evidence.", "from": 1, "lines": 1,
        "corpora": [{"corpus": "memory", "outcome": "ok"},
                    {"corpus": "wiki", "outcome": "unavailable", "error": "wiki read failed"}],
        "warning": "Wiki corpus unavailable: wiki read failed", "error": "wiki read failed",
    }


def test_all_corpus_uses_provider_result_after_primary_refusal_without_reslicing(tmp_path: Path):
    result = execute_memory_get_tool(
        MemoryConfig(workspace_dir=tmp_path, memory_get_max_chars=1),
        {"path": "wiki/topic.txt", "corpus": "all", "from": 9, "lines": 1},
        supplements=[StaticMemoryCorpusSupplement([{
            "path": "wiki/topic.txt", "content": "Provider excerpt stays intact.", "title": "Wiki",
        }])],
    )
    reason = "path is not an allowed Markdown memory file"
    assert result == {
        "status": "ok", "path": "wiki/topic.txt", "text": "Provider excerpt stays intact.", "title": "Wiki",
        "corpora": [{"corpus": "memory", "outcome": "unavailable", "error": reason},
                    {"corpus": "wiki", "outcome": "ok"}],
        "warning": f"Memory corpus unavailable: {reason}", "error": reason,
    }
