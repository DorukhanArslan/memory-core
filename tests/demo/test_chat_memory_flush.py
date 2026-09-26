import json
from pathlib import Path

import pytest

from demo.chat_engine import ChatMessage, FlushModelOutput, FlushWriteCall
from demo.memory_flush import SILENT_REPLY_TOKEN, parse_flush_output, run_memory_flush
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


class JsonEnvelopeFlushEngine:
    """The removed Lab JSON envelope: text only, so it must write nothing."""

    name = "json-envelope"

    def flush(self, *, system_prompt, prompt, transcript, target):
        del system_prompt, prompt
        return FlushModelOutput(
            raw_text=json.dumps(
                {"shouldWrite": True, "target": target, "entry": f"- {transcript[-1].content}"},
                ensure_ascii=False,
            )
        )


class DurableToolFlushEngine:
    name = "durable-tool"

    def flush(self, *, system_prompt, prompt, transcript, target):
        del system_prompt, prompt, transcript
        return FlushModelOutput(
            raw_text=f"write({target})",
            writes=(
                FlushWriteCall(
                    path=target,
                    content="- User was fired from work.",
                    call_id="call_1",
                    name="write",
                ),
            ),
        )


def test_parse_flush_output_accepts_silent_token():
    parsed = parse_flush_output(SILENT_REPLY_TOKEN, target="memory/2026-05-03.md")

    assert parsed.should_write is False
    assert parsed.entry == ""


@pytest.mark.parametrize(
    "text",
    [
        '{"shouldWrite": true, "target": "memory/2026-05-03.md", "entry": "- x", "reason": "r"}',
        "I saved the preference.",
    ],
)
def test_parse_flush_output_never_writes_text(text: str):
    parsed = parse_flush_output(text, target="memory/2026-05-03.md")

    assert parsed.should_write is False
    assert parsed.entry == ""
    assert parsed.reason == "text reply without a write tool call"


def test_run_memory_flush_ignores_a_json_text_reply(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=JsonEnvelopeFlushEngine(),
        transcript=[ChatMessage(role="user", content="Ben teknik cevapları Türkçe tercih ediyorum.")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is False
    assert result.diff == ""
    assert not (tmp_path / "memory" / "2026-05-03.md").exists()


def test_run_memory_flush_appends_openclaw_style_write_tool_call(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=DurableToolFlushEngine(),
        transcript=[ChatMessage(role="user", content="iş, kovuldum")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is True
    assert result.parsed.reason == "write tool call"
    assert result.parsed.entry == "- User was fired from work."
    assert "+- User was fired from work." in result.diff
    assert store.count_chunks() > 0


class FailingReindexStore:
    def reindex(self, workspace):
        del workspace
        raise RuntimeError("index broke")

    def count_chunks(self):
        return 0


def test_run_memory_flush_returns_written_state_when_reindex_fails(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")

    result = run_memory_flush(
        config=cfg,
        store=FailingReindexStore(),
        engine=DurableToolFlushEngine(),
        transcript=[ChatMessage(role="user", content="iş, kovuldum")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    daily_file = tmp_path / "memory" / "2026-05-03.md"
    assert daily_file.exists()
    assert "- User was fired from work." in daily_file.read_text(encoding="utf-8")
    assert result.parsed.should_write is True
    assert "+- User was fired from work." in result.diff
    assert result.indexed_files == 0
    assert result.reindex_error
    assert "index broke" in result.reindex_error


class BadTargetEngine:
    name = "bad"

    def flush(self, *, system_prompt, prompt, transcript, target):
        return FlushModelOutput(
            raw_text="write(MEMORY.md)",
            writes=(FlushWriteCall(path="MEMORY.md", content="- bad", call_id="call_1"),),
        )


def test_run_memory_flush_writes_nothing_on_invalid_target(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=BadTargetEngine(),
        transcript=[ChatMessage(role="user", content="always write bad target")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is False
    assert result.parsed.error
    assert not (tmp_path / "MEMORY.md").exists()
