import asyncio
import json
import re
import textwrap
from pathlib import Path

import examples.basic_usage as basic_usage
import examples.live_streaming as live_streaming
import examples.quickstart as quickstart
from memory_core import TurnUsage
from memory_core.live import LiveIdentityStore


class _FakeProvider:
    # Stands in for OpenAICompatibleEmbeddingProvider (EmbeddingProvider protocol).
    provider_id = "openai-compatible"

    def __init__(self, *, api_key, base_url, model):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def embed_query(self, text):
        return [0.1, 0.2]

    def embed_documents(self, texts):
        return [[0.1, 0.2] for _ in texts]


def test_basic_usage_builds_memory_from_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setattr(basic_usage, "OpenAICompatibleEmbeddingProvider", _FakeProvider)

    memory = basic_usage.build_memory(tmp_path)

    assert memory.workspace.root == tmp_path
    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()
    assert memory.store.embeddings.api_key == "sk-test"
    assert memory.store.embeddings.base_url == "https://example.test/v1"
    assert memory.store.embeddings.model == "text-embedding-3-small"


def test_basic_usage_requires_openai_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        basic_usage.build_memory(tmp_path)
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected OPENAI_API_KEY error")


def test_live_streaming_example_emits_tts_sentences(tmp_path: Path):
    live_streaming.seed_identity(tmp_path)

    sentences = asyncio.run(live_streaming.run_live_turn(tmp_path))

    assert sentences == [
        "Tabii, yardimci olayim.",
        "Once kimliginizi dogrulayalim.",
    ]
    assert (tmp_path / "trace" / "session_456.jsonl").exists()


def test_live_streaming_example_seeds_the_default_layout(tmp_path: Path):
    live_streaming.seed_identity(tmp_path)

    identity = LiveIdentityStore(tmp_path, required_files=["AGENTS.md"]).load()
    prompt = identity.to_prompt_section()

    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "PROACTIVE_PREFERENCES.md").read_text(encoding="utf-8") == ""
    assert [Path(path).name for path, _ in identity.sections] == ["AGENTS.md", "SOUL.md"]
    assert "[MISSING]" not in prompt
    assert "Bootstrap Pending" not in prompt


def test_live_streaming_example_records_session_summary(tmp_path: Path):
    memory_path = asyncio.run(live_streaming.record_session_summary(tmp_path))

    assert memory_path.startswith("memory/")
    memory_file = tmp_path / "subjects" / "subj_123" / memory_path
    assert "evening delivery" in memory_file.read_text(encoding="utf-8")


class _StubLLM:
    # Stands in for quickstart.call_my_llm: each chat turn makes one memory_search call and
    # reports a prompt past the default window's 176,000-token flush threshold; the flush run
    # writes one fact to the target its prompt names, as a model would.
    FACT = "- The project codename is velvetkiwi."

    def __init__(self, stdout_so_far):
        self.stdout_so_far = stdout_so_far
        self.turns = []
        self.searches = []
        self.flush_runs = []
        self.printed_before_flush = []
        self.writes = []

    def __call__(self, messages, tools, run_tool):
        names = [tool["name"] for tool in tools]
        if names == ["write"]:
            self.flush_runs.append(list(messages))
            self.printed_before_flush.append(self.stdout_so_far())
            target = re.search(r"memory/\d{4}-\d{2}-\d{2}\.md", messages[-1]["content"])[0]
            arguments = json.dumps({"path": target, "content": self.FACT})
            self.writes.append(run_tool("write", arguments))
            return "NO_REPLY", TurnUsage(None)
        self.turns.append((list(messages), names))
        self.searches.append(run_tool("memory_search", {"query": "velvetkiwi codename"}))
        return f"reply {len(self.turns)}", TurnUsage(180_000, 20)


def test_quickstart_runs_the_memory_tools_and_the_flush(tmp_path: Path, monkeypatch, capsys):
    printed = []

    def stdout_so_far():
        printed.extend(capsys.readouterr().out.splitlines())
        return list(printed)

    llm = _StubLLM(stdout_so_far)
    lines = iter(["Our codename is velvetkiwi.", "What is our codename?", ""])
    monkeypatch.setattr(quickstart, "call_my_llm", llm)
    monkeypatch.setattr("builtins.input", lambda prompt: next(lines))
    monkeypatch.chdir(tmp_path)

    quickstart.main()

    (first_messages, names), (second_messages, _) = llm.turns
    assert names[:2] == ["memory_search", "memory_get"]
    assert first_messages[0]["role"] == "system"
    assert first_messages[0]["content"].startswith("## Memory Recall")
    assert first_messages[1:] == [{"role": "user", "content": "Our codename is velvetkiwi."}]
    assert [message["content"] for message in second_messages[1:]] == [
        "Our codename is velvetkiwi.",
        "reply 1",
        "What is our codename?",
    ]
    # Turn 1 finds nothing; its flush appends the fact, which turn 2's search finds.
    empty = {"results": [], "provider": "none", "model": "fts-only", "citations": "on"}
    assert llm.searches[0] == empty
    (write,) = llm.writes
    target = write["path"]
    assert write == {
        "status": "ok",
        "tool": "write",
        "path": target,
        "action": "appended",
        "text": f"Appended content to {target}.",
    }
    assert (tmp_path / "my-agent-app" / target).read_text(encoding="utf-8") == llm.FACT + "\n"
    (hit,) = llm.searches[1]["results"]
    assert (hit["path"], hit["startLine"]) == (target, 1)
    assert hit["citation"] == f"Source: {target}#L1-L2"
    assert llm.FACT in hit["snippet"]
    # One flush run over turn 1's text: complete() stamped the compaction cycle and the loop
    # kept that state, so turn 2, past the threshold too, reads already_flushed.
    (flush_messages,) = llm.flush_runs
    roles = [message["role"] for message in flush_messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert flush_messages[-1]["content"].startswith("Pre-compaction memory flush.")
    # The reply is delivered before the flush runs (upstream order); the flush run's reply never.
    assert llm.printed_before_flush == [["reply 1"]]
    assert stdout_so_far() == ["reply 1", "reply 2"]


def test_readme_quickstart_saves_and_recalls_without_a_provider(tmp_path: Path, monkeypatch, capsys):
    readme = (Path(quickstart.__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    section = readme.split("\n## Quickstart\n", 1)[1]
    code = section.split("```python\n", 1)[1].split("\n```\n", 1)[0]
    monkeypatch.chdir(tmp_path)
    namespace = {"__name__": "__main__"}

    exec(code, namespace)

    memory = namespace["reopened"]
    assert memory.store.flags.vector_search is False
    assert memory.store.embeddings is None
    (hit,) = namespace["result"]["results"]
    assert hit["path"] == namespace["path"]
    assert "I prefer technical answers in English." in hit["snippet"]
    assert hit["citation"] == f"Source: {namespace['path']}#L1-L2"
    assert (memory.workspace.root / hit["path"]).is_file()
    output = capsys.readouterr().out
    assert "I prefer technical answers in English." in output
    assert hit["citation"] in output


def test_readme_hybrid_snippet_imports_what_it_uses(tmp_path: Path, monkeypatch):
    # Use a test-only embedder; execute the complete public configuration example.
    import memory_core

    readme = (Path(quickstart.__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "\n### Hybrid search\n" in readme
    snippet = readme.split("\n### Hybrid search\n", 1)[1]
    code = textwrap.dedent(snippet.split("```python\n", 1)[1].split("```\n", 1)[0])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        memory_core, "OpenAICompatibleEmbeddingProvider", lambda **kwargs: _FakeProvider(base_url="", **kwargs)
    )
    monkeypatch.chdir(tmp_path)
    namespace = {}

    exec(code, namespace)

    store = namespace["kit"].memory.store
    assert store.flags.vector_search is True
    assert (store.embeddings.api_key, store.embeddings.model) == ("test-key", "text-embedding-3-small")


def _python_block(doc: str) -> str:
    """The first ``python`` code block of a doc under the repo root."""
    text = (Path(quickstart.__file__).parents[1] / doc).read_text(encoding="utf-8")
    return text.split("```python\n", 1)[1].split("\n```\n", 1)[0] + "\n"


def test_feature_flags_doc_example_runs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace: dict = {}

    exec(_python_block("docs/feature_flags.md"), namespace)

    assert namespace["memory"].config.flags.vector_search is False
    assert (tmp_path / "MEMORY.md").exists()
