import json
from pathlib import Path

import pytest

from demo.chat_engine import ChatMessage, FlushModelOutput, FlushWriteCall
from demo.memory_flush import SILENT_REPLY_TOKEN, parse_flush_output, run_memory_flush
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


class DurableFlushEngine:
    name = "durable"

    def complete(self, *, messages, memory_context):
        raise NotImplementedError

    def flush(self, *, system_prompt, prompt, transcript, target):
        del system_prompt, prompt
        content = transcript[-1].content
        return FlushModelOutput(
            raw_text=json.dumps(
                {
                    "shouldWrite": True,
                    "target": target,
                    "entry": f"- {content}",
                    "reason": "Durable test memory.",
                },
                ensure_ascii=False,
            )
        )


class DurableToolFlushEngine:
    name = "durable-tool"

    def complete(self, *, messages, memory_context):
        raise NotImplementedError

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


def test_parse_flush_output_rejects_target_mismatch():
    parsed = parse_flush_output(
        '{"shouldWrite": true, "target": "MEMORY.md", "entry": "- bad", "reason": "bad"}',
        target="memory/2026-05-03.md",
    )

    assert parsed.should_write is False
    assert parsed.error


@pytest.mark.parametrize("flag", ["false", 1])
def test_parse_flush_output_rejects_non_boolean_should_write(flag: object):
    parsed = parse_flush_output(
        json.dumps(
            {
                "shouldWrite": flag,
                "target": "memory/2026-05-03.md",
                "entry": "- should not write",
                "reason": "malformed",
            }
        ),
        target="memory/2026-05-03.md",
    )

    assert parsed.should_write is False
    assert parsed.error


def test_run_memory_flush_appends_reindexes_and_returns_diff(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=DurableFlushEngine(),
        transcript=[ChatMessage(role="user", content="Ben teknik cevapları Türkçe tercih ediyorum.")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is True
    assert result.target == "memory/2026-05-03.md"
    assert "+- Ben teknik cevapları Türkçe tercih ediyorum." in result.diff
    assert (tmp_path / "memory" / "2026-05-03.md").exists()
    assert store.count_chunks() > 0


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
        engine=DurableFlushEngine(),
        transcript=[ChatMessage(role="user", content="Ben teknik cevapları Türkçe tercih ediyorum.")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    daily_file = tmp_path / "memory" / "2026-05-03.md"
    assert daily_file.exists()
    assert "- Ben teknik cevapları Türkçe tercih ediyorum." in daily_file.read_text(
        encoding="utf-8"
    )
    assert result.parsed.should_write is True
    assert "+- Ben teknik cevapları Türkçe tercih ediyorum." in result.diff
    assert result.indexed_files == 0
    assert result.reindex_error
    assert "index broke" in result.reindex_error


class BadTargetEngine:
    name = "bad"

    def complete(self, *, messages, memory_context):
        raise NotImplementedError

    def flush(self, *, system_prompt, prompt, transcript, target):
        return FlushModelOutput(
            raw_text='{"shouldWrite": true, "target": "MEMORY.md", "entry": "- bad", "reason": "bad"}'
        )


class MalformedShouldWriteEngine:
    name = "malformed"

    def complete(self, *, messages, memory_context):
        raise NotImplementedError

    def flush(self, *, system_prompt, prompt, transcript, target):
        return FlushModelOutput(
            raw_text=json.dumps(
                {
                    "shouldWrite": "false",
                    "target": target,
                    "entry": "- should not write",
                    "reason": "malformed",
                }
            )
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


def test_run_memory_flush_writes_nothing_on_malformed_should_write(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=16))

    result = run_memory_flush(
        config=cfg,
        store=store,
        engine=MalformedShouldWriteEngine(),
        transcript=[ChatMessage(role="user", content="malformed write flag")],
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.parsed.should_write is False
    assert result.parsed.error
    assert result.indexed_files == 0
    assert result.chunks == 0
    assert not (tmp_path / "memory" / "2026-05-03.md").exists()
