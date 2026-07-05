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


def test_openclaw_session_corpus_resolves_active_leaf_path(tmp_path: Path):
    """Leaf-controlled transcripts index only the active branch.

    Mirrors OpenClaw reader behavior after upstream commit 1a002c2d9d:
    selectSessionTranscriptLeafControlledPath(entries) ?? entries
    (src/agents/cli-runner/session-history.ts, transcript-tree.ts).
    """
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-branchy.jsonl").write_text(
        "\n".join(
            [
                '{"type":"session","id":"session-branchy"}',
                '{"type":"message","id":"m1","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"Keep me"}]}}',
                '{"type":"message","id":"m2","parentId":"m1","message":{"role":"assistant","content":[{"type":"text","text":"Abandoned branch reply"}]}}',
                '{"type":"leaf","id":"l1","parentId":"m2","targetId":"m1"}',
                '{"type":"message","id":"m3","parentId":"m1","message":{"role":"assistant","content":[{"type":"text","text":"Active branch reply"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-branchy":{"sessionId":"session-branchy","sessionFile":"session-branchy.jsonl"}}\n',
        encoding="utf-8",
    )
    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    text = corpus.read_index_text(corpus.discover_files()[0])

    assert text == (
        "User: Keep me\n"
        "Assistant: Active branch reply\n"
    )


def test_openclaw_session_corpus_excludes_side_append_entries_from_active_path(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-side.jsonl").write_text(
        "\n".join(
            [
                '{"type":"message","id":"m1","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"Visible question"}]}}',
                '{"type":"message","id":"s1","parentId":"m1","appendMode":"side","message":{"role":"assistant","content":[{"type":"text","text":"Side branch note"}]}}',
                '{"type":"leaf","id":"l1","parentId":"s1","targetId":"m1"}',
                '{"type":"message","id":"m2","parentId":"m1","message":{"role":"assistant","content":[{"type":"text","text":"Visible answer"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-side":{"sessionId":"session-side","sessionFile":"session-side.jsonl"}}\n',
        encoding="utf-8",
    )
    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    text = corpus.read_index_text(corpus.discover_files()[0])

    assert text == (
        "User: Visible question\n"
        "Assistant: Visible answer\n"
    )


def test_openclaw_session_corpus_keeps_file_order_without_leaf_controls(tmp_path: Path):
    sessions_dir = tmp_path / ".openclaw-state" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-flat.jsonl").write_text(
        "\n".join(
            [
                '{"type":"message","id":"m1","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"First"}]}}',
                '{"type":"message","id":"m2","parentId":"m1","message":{"role":"assistant","content":[{"type":"text","text":"Second"}]}}',
                '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"Legacy row without ids"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-flat":{"sessionId":"session-flat","sessionFile":"session-flat.jsonl"}}\n',
        encoding="utf-8",
    )
    corpus = MemoryCoreSessionCorpus(tmp_path / ".openclaw-state", agent_id="main")

    text = corpus.read_index_text(corpus.discover_files()[0])

    assert text == (
        "User: First\n"
        "Assistant: Second\n"
        "Assistant: Legacy row without ids\n"
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
