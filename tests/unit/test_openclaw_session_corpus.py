import json
from pathlib import Path

from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.transcript_tree import select_session_transcript_leaf_controlled_path


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


def test_openclaw_session_corpus_indexes_all_branches_in_file_order(tmp_path: Path):
    """Leaf-controlled transcripts still index every message row in file order.

    Mirrors OpenClaw memory ingestion
    (packages/memory-host-sdk/src/host/session-files.ts buildSessionEntry), which
    never calls the transcript-tree helpers. The active-branch view stays
    available to readers through memory_core.transcript_tree
    (src/agents/cli-runner/session-history.ts reader pattern).
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

    file = corpus.discover_files()[0]

    text = corpus.read_index_text(file)

    assert text == (
        "User: Keep me\n"
        "Assistant: Abandoned branch reply\n"
        "Assistant: Active branch reply\n"
    )
    entries = [json.loads(line) for line in file.abs_path.read_text(encoding="utf-8").splitlines()]
    active = select_session_transcript_leaf_controlled_path(entries)
    assert active is not None
    assert [entry["id"] for entry in active] == ["m1", "m3"]


def test_openclaw_session_corpus_indexes_side_append_entries_in_file_order(tmp_path: Path):
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
        "Assistant: Side branch note\n"
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


def _write_single_session(state_dir: Path, rows: list[tuple[str, object]]) -> None:
    sessions_dir = state_dir / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "session-heartbeat.jsonl").write_text(
        "".join(
            json.dumps({"type": "message", "message": {"role": role, "content": content}}) + "\n"
            for role, content in rows
        ),
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        '{"agent:main:session-heartbeat":{"sessionId":"session-heartbeat",'
        '"sessionFile":"session-heartbeat.jsonl"}}\n',
        encoding="utf-8",
    )


def test_openclaw_session_corpus_drops_heartbeat_rows(tmp_path: Path):
    from memory_core.heartbeat import HEARTBEAT_PROMPT
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    state_dir = tmp_path / ".openclaw-state"
    _write_single_session(
        state_dir,
        [
            ("user", HEARTBEAT_PROMPT),
            ("assistant", "HEARTBEAT_OK"),
            ("user", "[memory-core heartbeat poll]"),
            ("assistant", [{"type": "text", "text": " HEARTBEAT_OK "}]),
            ("user", "[OpenClaw heartbeat poll]"),
            ("assistant", "**HEARTBEAT_OK**"),
            ("user", f"{HEARTBEAT_PROMPT}\nAlso check the queue."),
            ("user", "What is Project Nebula?"),
        ],
    )

    default_corpus = MemoryCoreSessionCorpus(state_dir)
    compat_corpus = MemoryCoreSessionCorpus(
        state_dir, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )

    assert default_corpus.read_index_text(default_corpus.discover_files()[0]) == (
        "User: [OpenClaw heartbeat poll]\n"
        "Assistant: **HEARTBEAT_OK**\n"
        f"User: {HEARTBEAT_PROMPT}\nAlso check the queue.\n"
        "User: What is Project Nebula?\n"
    )
    assert compat_corpus.read_index_text(compat_corpus.discover_files()[0]) == (
        "User: [memory-core heartbeat poll]\n"
        "Assistant: **HEARTBEAT_OK**\n"
        f"User: {HEARTBEAT_PROMPT}\nAlso check the queue.\n"
        "User: What is Project Nebula?\n"
    )


def test_openclaw_session_corpus_drops_silent_replies(tmp_path: Path):
    # v2026.9.6 sanitizeSessionText drops isSilentReplyPayloadText rows of either role; the
    # heartbeat's quiet answer is NO_REPLY now.
    state_dir = tmp_path / ".openclaw-state"
    _write_single_session(
        state_dir,
        [
            ("user", "Check the queue."),
            ("assistant", "NO_REPLY"),
            ("assistant", '{"action": "NO_REPLY"}'),
            ("user", "no_reply"),
            ("assistant", "Here is a helpful response.\n\nNO_REPLY"),
        ],
    )
    corpus = MemoryCoreSessionCorpus(state_dir)

    assert corpus.read_index_text(corpus.discover_files()[0]) == (
        "User: Check the queue.\n"
        "Assistant: Here is a helpful response.\n\nNO_REPLY\n"
    )
