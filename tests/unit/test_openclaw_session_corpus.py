from pathlib import Path

from memory_core.session_corpus import MemoryCoreSessionCorpus


def test_openclaw_session_corpus_discovers_visible_session_transcripts(tmp_path: Path):
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
        '{"agent:main:session-nebula":{"sessionId":"session-nebula","sessionFile":"session-nebula.jsonl"}}\n',
        encoding="utf-8",
    )

    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    files = corpus.discover_files()

    assert [item.rel_path for item in files] == ["sessions/main/session-nebula.jsonl"]
    assert files[0].source == "sessions"
    assert files[0].abs_path == sessions_dir / "session-nebula.jsonl"


def test_openclaw_session_corpus_renders_chat_text_for_indexing(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    transcript = sessions_dir / "session-nebula.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"What is Project Nebula?"}]}}',
                '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"Project Nebula is ORBIT-10."}]}}',
                '{"type":"message","message":{"role":"tool","content":[{"type":"text","text":"ignored tool output"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-nebula":{"sessionId":"session-nebula","sessionFile":"session-nebula.jsonl"}}\n',
        encoding="utf-8",
    )
    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    text = corpus.read_index_text(corpus.discover_files()[0])

    assert text == (
        "User: What is Project Nebula?\n"
        "Assistant: Project Nebula is ORBIT-10.\n"
    )


def test_openclaw_session_corpus_ignores_unregistered_transcripts(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "orphan.jsonl").write_text(
        '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"hidden"}]}}\n',
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text("{}\n", encoding="utf-8")

    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    assert corpus.discover_files() == []
