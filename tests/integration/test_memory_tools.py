from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.supplements import StaticMemoryCorpusSupplement
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace


def test_memory_get_reads_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = memory_get(
        MemoryConfig(workspace_dir=tmp_path), path="MEMORY.md", from_line=2, lines=1
    )
    assert result["path"] == "MEMORY.md"
    assert result["text"] == "beta\n\n[More content available. Use from=3 to continue.]"
    assert result["from"] == 2
    assert result["lines"] == 1
    assert result["truncated"] is True
    assert result["nextFrom"] == 3


def test_memory_get_rejects_non_memory_workspace_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("not memory\n", encoding="utf-8")

    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="notes.txt")

    assert result["disabled"] is True
    assert result["text"] == ""
    assert result["error"] == "path required"


def test_memory_get_reads_wiki_supplement_result(tmp_path: Path):
    wiki = StaticMemoryCorpusSupplement(
        [
            {
                "corpus": "wiki",
                "path": "w1.md",
                "content": "Project Nebula deployment rule.\nRequires security approval.\n",
            }
        ]
    )

    result = memory_get(
        MemoryConfig(workspace_dir=tmp_path),
        path="w1.md",
        from_line=2,
        lines=1,
        corpus="wiki",
        supplements=[wiki],
    )

    assert result == {
        "path": "w1.md",
        "text": "Requires security approval.\n\n[More content available. Use from=3 to continue.]",
        "from": 2,
        "lines": 1,
        "corpus": "wiki",
        "truncated": True,
        "nextFrom": 3,
    }


def test_memory_get_returns_upstream_error_for_session_search_hits(tmp_path: Path):
    # OpenClaw memory_get cannot read session hits either: state-dir transcripts
    # and session-corpus `.txt` files fail readMemoryFile's `.md` memory-path gate.
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-nebula.jsonl").write_text(
        '{"type":"message","message":{"role":"assistant","content":'
        '[{"type":"text","text":"Project Nebula is ORBIT-10."}]}}\n',
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-nebula":{"sessionFile":"session-nebula.jsonl"}}\n',
        encoding="utf-8",
    )
    corpus_dir = tmp_path / "memory" / ".dreams" / "session-corpus"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "2026-05-07.txt").write_text("User: ORBIT-10 corpus line\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        flags=FeatureFlags(vector_search=False),
    )
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(MemoryWorkspace(tmp_path, openclaw_state_dir=tmp_path / ".openclaw-state"))

    hits = memory_search(cfg, store, query="ORBIT-10", corpus="sessions", max_results=5)
    paths = sorted(hit["path"] for hit in hits["results"])

    assert paths == [
        "memory/.dreams/session-corpus/2026-05-07.txt",
        "sessions/main/session-nebula.jsonl",
    ]
    for path in paths:
        for corpus in ("memory", "sessions", "all"):
            assert memory_get(cfg, path=path, corpus=corpus) == {
                "path": path,
                "text": "",
                "disabled": True,
                "error": "path required",
            }


def test_memory_get_all_corpus_falls_back_to_supplement_after_read_failure(tmp_path: Path):
    # tools.ts resolveMemoryReadFailureResult: corpus=all retries supplements.
    wiki = StaticMemoryCorpusSupplement(
        [{"corpus": "wiki", "path": "wiki/nebula.txt", "content": "Nebula rule.\n"}]
    )
    cfg = MemoryConfig(workspace_dir=tmp_path)

    fallback = memory_get(cfg, path="wiki/nebula.txt", corpus="all", supplements=[wiki])
    no_fallback = memory_get(cfg, path="wiki/nebula.txt", corpus="memory", supplements=[wiki])

    assert fallback["corpus"] == "wiki"
    assert fallback["text"].startswith("Nebula rule.")
    assert no_fallback == {
        "path": "wiki/nebula.txt",
        "text": "",
        "disabled": True,
        "error": "path required",
    }


def test_memory_get_wiki_supplement_missing_result(tmp_path: Path):
    result = memory_get(
        MemoryConfig(workspace_dir=tmp_path),
        path="missing.md",
        corpus="wiki",
        supplements=[],
    )

    assert result == {
        "path": "missing.md",
        "text": "",
        "disabled": True,
        "error": "wiki corpus result not found",
    }


def test_memory_search_returns_hybrid_results(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "User likes lemon pepper wings.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="lemon pepper", max_results=3, min_score=0.0)

    assert result["provider"] == "fake"
    assert result["model"] == "fake-deterministic"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert result["results"][0]["corpus"] == "memory"
    assert result["citations"] == "on"
    assert result["results"][0]["citation"] == "Source: MEMORY.md#L1-L2"
    assert result["results"][0]["snippet"].endswith("\n\nSource: MEMORY.md#L1-L2")


def test_memory_search_preserves_keyword_hits_when_min_score_is_too_strict(
    tmp_path: Path,
):
    (tmp_path / "MEMORY.md").write_text(
        "Move backups to S3 Glacier cold storage.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        vector_weight=0,
        text_weight=1,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(
        cfg,
        store,
        query="glacier",
        corpus="memory",
        max_results=3,
        min_score=1.1,
    )

    assert [item["path"] for item in result["results"]] == ["MEMORY.md"]


def test_memory_search_indexes_session_transcripts_by_default(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("User likes lemon pepper wings.\n", encoding="utf-8")
    session_dir = tmp_path / "memory" / ".dreams" / "session-corpus"
    session_dir.mkdir(parents=True)
    (session_dir / "2026-05-07.md").write_text(
        "[chat] User: discussed cobalt router migration.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="cobalt router", max_results=3, min_score=0.0)

    assert {
        (item["path"], item["corpus"]) for item in result["results"]
    } >= {("memory/.dreams/session-corpus/2026-05-07.md", "sessions")}


def test_memory_search_indexes_openclaw_state_session_transcripts(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-nebula.jsonl").write_text(
        "\n".join(
            [
                '{"type":"session","id":"session-nebula"}',
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"What is Project Nebula?"}]}}',
                '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"Project Nebula is ORBIT-10."}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-nebula":{"sessionFile":"session-nebula.jsonl"}}\n',
        encoding="utf-8",
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(
        MemoryWorkspace(tmp_path, openclaw_state_dir=tmp_path / ".openclaw-state")
    )

    result = memory_search(
        cfg,
        store,
        query="project nebula orbit-10",
        corpus="sessions",
        max_results=3,
        min_score=0.0,
    )

    first = result["results"][0]
    assert first["path"] == "sessions/main/session-nebula.jsonl"
    assert first["corpus"] == "sessions"
    assert "Assistant: Project Nebula is ORBIT-10." in first["snippet"]


def test_memory_search_corpus_memory_excludes_session_transcripts(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("User likes lemon pepper wings.\n", encoding="utf-8")
    session_dir = tmp_path / "memory" / ".dreams" / "session-corpus"
    session_dir.mkdir(parents=True)
    (session_dir / "2026-05-07.md").write_text(
        "[chat] User: discussed cobalt router migration.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(
        cfg,
        store,
        query="cobalt router",
        max_results=3,
        min_score=0.0,
        corpus="memory",
    )

    assert {item["corpus"] for item in result["results"]} == {"memory"}


def test_memory_search_corpus_wiki_returns_supplement_results(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    wiki = StaticMemoryCorpusSupplement(
        [
            {"corpus": "wiki", "path": "w1.md", "score": 50, "snippet": "wiki 1"},
            {"corpus": "wiki", "path": "w2.md", "score": 40, "snippet": "wiki 2"},
        ]
    )

    result = memory_search(
        cfg,
        store,
        query="alpha",
        corpus="wiki",
        max_results=5,
        min_score=0,
        supplements=[wiki],
    )

    assert [(item["corpus"], item["path"]) for item in result["results"]] == [
        ("wiki", "w1.md"),
        ("wiki", "w2.md"),
    ]


def test_memory_search_corpus_all_balances_memory_and_supplements(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Memory result A mentions project alpha.",
        encoding="utf-8",
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        vector_weight=0,
        text_weight=1,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    wiki = StaticMemoryCorpusSupplement(
        [
            {"corpus": "wiki", "path": "w1.md", "score": 50, "snippet": "wiki 1"},
            {"corpus": "wiki", "path": "w2.md", "score": 40, "snippet": "wiki 2"},
            {"corpus": "wiki", "path": "w3.md", "score": 30, "snippet": "wiki 3"},
            {"corpus": "wiki", "path": "w4.md", "score": 20, "snippet": "wiki 4"},
            {"corpus": "wiki", "path": "w5.md", "score": 10, "snippet": "wiki 5"},
        ]
    )

    result = memory_search(
        cfg,
        store,
        query="alpha",
        corpus="all",
        max_results=5,
        min_score=0,
        supplements=[wiki],
    )

    paths_by_corpus = [(item["corpus"], item["path"]) for item in result["results"]]
    assert ("memory", "MEMORY.md") in paths_by_corpus
    assert [path for corpus, path in paths_by_corpus if corpus == "wiki"] == [
        "w1.md",
        "w2.md",
        "w3.md",
        "w4.md",
    ]
    assert len(paths_by_corpus) == 5


def test_memory_search_clamps_snippets_and_reports_truncation(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "User likes lemon pepper wings with blue cheese.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        memory_get_max_chars=10,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="lemon pepper", max_results=1, min_score=0.0)

    first = result["results"][0]
    assert first["snippet"] == "User likes\n\nSource: MEMORY.md#L1-L2"
    assert first["truncated"] is True
    assert first["originalChars"] > 10
    assert first["citation"] == "Source: MEMORY.md#L1-L2"


def test_temporal_decay_affects_store_search_order(tmp_path: Path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2000-01-01.md").write_text("alpha beta\n", encoding="utf-8")
    (tmp_path / "memory" / "2999-01-01.md").write_text("alpha beta\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        temporal_decay_enabled=True,
        temporal_decay_half_life_days=1,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    results = store.search("alpha beta", max_results=2, min_score=0.0)

    assert results[0].path == "memory/2999-01-01.md"
    assert results[0].score > results[1].score


def test_undated_and_session_style_notes_are_searchable_and_evergreen(tmp_path: Path):
    # Recursive memory/**/*.md discovery (OpenClaw listMemoryFiles) makes these
    # files searchable; temporal-decay.ts treats non-daily memory/ paths as
    # evergreen, so only the dated daily file decays.
    (tmp_path / "memory" / "topics").mkdir(parents=True)
    for relative in (
        "memory/2000-01-01.md",
        "memory/2000-01-01-1430.md",
        "memory/topics/alpha.md",
    ):
        (tmp_path / relative).write_text("orbit nebula\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        flags=FeatureFlags(vector_search=False, temporal_decay=True),
        temporal_decay_half_life_days=1,
    )
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(MemoryWorkspace(tmp_path))

    results = store.search("orbit nebula", max_results=3, min_score=0.0)
    scores = {result.path: result.score for result in results}

    assert set(scores) == {
        "memory/2000-01-01.md",
        "memory/2000-01-01-1430.md",
        "memory/topics/alpha.md",
    }
    assert scores["memory/2000-01-01-1430.md"] == scores["memory/topics/alpha.md"]
    assert scores["memory/2000-01-01.md"] < scores["memory/topics/alpha.md"] * 1e-6


def test_mmr_config_is_applied_to_store_search(tmp_path: Path, monkeypatch):
    (tmp_path / "MEMORY.md").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2999-01-01.md").write_text("alpha\ngamma\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        mmr_enabled=True,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    calls = []

    def fake_mmr(items, *, enabled, lambda_):
        calls.append((enabled, lambda_, len(items)))
        return list(reversed(items))

    monkeypatch.setattr("memory_core.index.sqlite_store.mmr_rerank", fake_mmr)

    store.search("alpha", max_results=2, min_score=0.0)

    assert calls == [(True, 0.7, 2)]
