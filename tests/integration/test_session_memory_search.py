"""Session-memory files (/new, /reset) reach memory_search and memory_get.

``save_session_memory`` writes ``memory/<date>-<slug>.md`` (upstream
``src/hooks/bundled/session-memory/handler.ts``). Upstream indexes every
``memory/**/*.md`` (``listMemoryFiles``,
``packages/memory-host-sdk/src/host/internal.ts:150-222``) and treats undated
``memory/`` paths as evergreen for temporal decay (``isEvergreenMemoryPath``,
``extensions/memory-core/src/memory/temporal-decay.ts``), so these files are
searchable, readable and never decay. The host reindexes after the save.
"""

from __future__ import annotations

from pathlib import Path

from memory_core import FeatureFlags, Memory, MemoryConfig
from memory_core.session_memory import save_session_memory

NOW_MS = 1790433000000  # 2026-09-26T14:30:00Z


def _memory(root: Path, *, store_name: str = "main.sqlite", temporal_decay: bool = False) -> Memory:
    return Memory.from_workspace(
        root,
        config=MemoryConfig(
            workspace_dir=root,
            store_path=root / ".memory-core" / store_name,
            flags=FeatureFlags(vector_search=False, temporal_decay=temporal_decay),
        ),
    )


def _save_two_sessions(root: Path):
    timestamped = save_session_memory(
        root,
        session_key="agent:main:main",
        session_id="session-one",
        messages=[
            {"role": "user", "content": "Book the zephyrquartz review for Friday."},
            {"role": "assistant", "content": "Booked the zephyrquartz review for Friday."},
        ],
        now_ms=NOW_MS,
    )
    slugged = save_session_memory(
        root,
        session_key="agent:main:main",
        session_id="session-two",
        messages=[{"role": "user", "content": "The quokkabyte vendor pitch moved to May."}],
        now_ms=NOW_MS,
        slug_generator=lambda prompt: "vendor-pitch",
    )
    return timestamped, slugged


def test_session_memory_files_are_discovered_searched_and_read(tmp_path: Path):
    memory = _memory(tmp_path)
    memory.workspace.append_daily_memory("memory/2026-09-26.md", "- unrelated daily note")
    timestamped, slugged = _save_two_sessions(tmp_path)

    assert (timestamped.rel_path, slugged.rel_path) == (
        "memory/2026-09-26-1430.md",
        "memory/2026-09-26-vendor-pitch.md",
    )
    indexable = {
        item.rel_path: item.source for item in memory.workspace.discover_indexable_files()
    }
    assert indexable[timestamped.rel_path] == indexable[slugged.rel_path] == "memory"

    assert memory.search("zephyrquartz")["results"] == []
    memory.store.reindex(memory.workspace)

    for query, saved in (("zephyrquartz", timestamped), ("quokkabyte", slugged)):
        hits = memory.search(query)["results"]
        assert [(hit["path"], hit["source"]) for hit in hits] == [(saved.rel_path, "memory")]
        assert f"Source: {saved.rel_path}#L" in hits[0]["snippet"]
        read = memory.get(saved.rel_path)
        assert read["path"] == saved.rel_path
        assert read["text"] == saved.path.read_text(encoding="utf-8")
        assert query in read["text"]


def test_session_memory_files_decay_by_their_date_at_v2026_9_6(tmp_path: Path):
    _memory(tmp_path)
    saved, _ = _save_two_sessions(tmp_path)
    old_daily = tmp_path / "memory" / "2020-01-01.md"
    old_daily.write_text("- zephyrquartz review from the old plan\n", encoding="utf-8")

    plain = _memory(tmp_path, store_name="plain.sqlite", temporal_decay=False)
    decayed = _memory(tmp_path, store_name="decayed.sqlite", temporal_decay=True)
    plain_scores = {hit["path"]: hit["score"] for hit in plain.search("zephyrquartz")["results"]}
    decayed_scores = {
        hit["path"]: hit["score"] for hit in decayed.search("zephyrquartz")["results"]
    }

    assert set(plain_scores) == set(decayed_scores) == {saved.rel_path, "memory/2020-01-01.md"}
    # v2026.9.6 reads a dated file with a suffix (`memory/2026-09-26-1430.md`) as dated, so a
    # session-memory file decays by its date like a daily note (it was evergreen at the pin).
    assert decayed_scores[saved.rel_path] < plain_scores[saved.rel_path]
    assert decayed_scores["memory/2020-01-01.md"] < plain_scores["memory/2020-01-01.md"]
